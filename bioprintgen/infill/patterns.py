"""Infill pattern registry: built-ins plus user patterns from ``<app>/patterns``.

Every pattern has a string id (the built-ins keep their `InfillType` values, so
settings files and exports from earlier versions still resolve) and one of
three kinds:

* ``lines``    - rectilinear (built-in); spacing = strand centre distance.
* ``levelset`` - the gyroid and *equation patterns*: the strand follows the
                 zero-level curve of f(x, y, z) at each layer height, the way
                 the gyroid does.  ``patterns/<id>.json``::

                     {"name": "Schwarz P",
                      "description": "...",
                      "equation": "cos(x) + cos(y) + cos(z)",
                      "level": 0}

                 x, y, z are scaled so that 2*pi = one *period* (the cell
                 size you set), so f must repeat every 2*pi along each axis.
                 The equation is parsed, not executed: only numbers, x y z pi
                 e tau, + - * / ** % and the functions in `FUNCTIONS` are
                 accepted.  Infill % works automatically - the line density of
                 the curve is measured once when the pattern loads.
* ``path``     - a Python plugin ``patterns/<id>.py`` that draws strokes
                 itself (see patterns/templates/path_template.py)::

                     PATTERN = {"name": "Concentric", "description": "..."}

                     def generate(region, layer, settings, spacing):
                         return [[(x0, y0), (x1, y1), ...], ...]

                 The app clips every stroke to the region and drops degenerate
                 ones, so a plugin may overshoot.  `spacing` is the strand
                 centre distance (already derived from Infill % in % mode);
                 aim for about 1/spacing mm of line per mm^2 so % stays right.
                 Plugins are ordinary Python - only install ones you trust.

Files in ``patterns/templates`` are documentation and are not loaded.
"""
from __future__ import annotations

import ast
import importlib.util
import json
import math
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional

import numpy as np

from ..model import InfillType, GYROID_LINE_DENSITY, pattern_id

APP_DIR = Path(__file__).resolve().parent.parent.parent


class PatternError(RuntimeError):
    pass


@dataclass
class Pattern:
    id: str
    name: str
    kind: str                      # "lines" | "levelset" | "path"
    description: str = ""
    equation: str = ""             # levelset (user)
    level: float = 0.0
    builtin: bool = False
    path: Optional[Path] = None
    field_fn: Optional[Callable] = field(default=None, repr=False)   # levelset
    generate_fn: Optional[Callable] = field(default=None, repr=False)  # path
    _density: Optional[float] = field(default=None, repr=False)

    def definition(self) -> dict:
        """What an export embeds so the print can be rebuilt without the file."""
        return {"name": self.name, "kind": self.kind, "equation": self.equation,
                "level": self.level, "description": self.description}


# --------------------------------------------------------------------------- #
#  Safe equations
# --------------------------------------------------------------------------- #
FUNCTIONS = {
    "sin": np.sin, "cos": np.cos, "tan": np.tan,
    "asin": np.arcsin, "acos": np.arccos, "atan": np.arctan, "atan2": np.arctan2,
    "sinh": np.sinh, "cosh": np.cosh, "tanh": np.tanh,
    "exp": np.exp, "log": np.log, "sqrt": np.sqrt, "abs": np.abs,
    "sign": np.sign, "floor": np.floor, "min": np.minimum, "max": np.maximum,
}
_NAMES = {"x", "y", "z", "pi", "e", "tau"}
_CONSTANTS = {"pi": math.pi, "e": math.e, "tau": 2 * math.pi}
_OPS = (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow, ast.Mod, ast.USub, ast.UAdd)


def compile_equation(text: str) -> Callable:
    """Return fn(X, Y, z) -> array for an equation in x, y, z.

    Raises PatternError with a readable message for anything outside the
    whitelist (attribute access, names other than x/y/z/constants, ...)."""
    text = (text or "").strip().replace("^", "**")
    if not text:
        raise PatternError("the equation is empty")
    try:
        tree = ast.parse(text, mode="eval")
    except SyntaxError as e:
        raise PatternError(f"syntax error in equation: {e.msg}") from None
    for node in ast.walk(tree):
        if isinstance(node, (ast.Expression, ast.Load)) or isinstance(node, _OPS):
            continue
        if isinstance(node, (ast.BinOp, ast.UnaryOp)):
            continue
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) \
                and not isinstance(node.value, bool):
            continue
        if isinstance(node, ast.Name):
            if node.id in _NAMES or node.id in FUNCTIONS:
                continue
            raise PatternError(f"unknown name '{node.id}' (use x, y, z, pi, e, tau "
                               f"and {', '.join(sorted(FUNCTIONS))})")
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in FUNCTIONS \
                    and not node.keywords:
                continue
            raise PatternError("only the listed functions can be called")
        raise PatternError(f"'{type(node).__name__}' is not allowed in an equation")
    # float constants: 9**9**9 then overflows at once instead of building a huge int
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant):
            node.value = float(node.value)
    code = compile(tree, "<equation>", "eval")
    env = {"__builtins__": {}, **FUNCTIONS, **_CONSTANTS}

    def fn(X, Y, z):
        with np.errstate(all="ignore"):
            out = eval(code, env, {"x": X, "y": Y, "z": z})   # whitelisted AST only
        out = np.asarray(out, dtype=float)
        return np.nan_to_num(np.broadcast_to(out, np.shape(X)), nan=0.0)

    fn(np.zeros((2, 2)), np.zeros((2, 2)), np.float64(0.3))      # fail early
    return fn


def _levelset_field(eq: Callable):
    """Adapt fn(X, Y, z) to the (xs, ys, z, f) signature of levelset_strokes."""
    def field_fn(xs, ys, z, f):
        X, Y = np.meshgrid(xs * f, ys * f)
        return eq(X, Y, np.float64(z * f))
    return field_fn


def measure_line_density(eq: Callable, level: float = 0.0,
                         n: int = 256, nz: int = 16) -> float:
    """Dimensionless line density k of a 2*pi-periodic level set: a strand of
    width w at period P covers k*w/P of the area (gyroid: ~2.45 measured this
    way; the built-in uses the 2.494 found on real prints)."""
    from contourpy import contour_generator
    xs = np.linspace(0.0, 2 * math.pi, n)
    X, Y = np.meshgrid(xs, xs)
    total = 0.0
    for i in range(nz):
        z = np.float64(2 * math.pi * (i + 0.5) / nz)
        F = eq(X, Y, z)
        length = 0.0
        for arr in contour_generator(xs, xs, F).lines(level):
            if len(arr) > 1:
                length += float(np.hypot(*np.diff(arr, axis=0).T).sum())
        total += length / (2 * math.pi) ** 2
    return 2 * math.pi * total / nz


# --------------------------------------------------------------------------- #
#  Registry
# --------------------------------------------------------------------------- #
_BUILTINS = [
    Pattern(InfillType.RECTILINEAR_CONNECTED.value, "Rectilinear – connected", "lines",
            "Parallel strands joined into a serpentine.", builtin=True),
    Pattern(InfillType.RECTILINEAR_SEPARATE.value, "Rectilinear – separate bars", "lines",
            "Parallel strands, each printed on its own.", builtin=True),
    Pattern(InfillType.GYROID.value, "Gyroid", "levelset",
            "sin x cos y + sin y cos z + sin z cos x = 0",
            equation="sin(x)*cos(y) + sin(y)*cos(z) + sin(z)*cos(x)", builtin=True,
            _density=GYROID_LINE_DENSITY),
]

_registry: Dict[str, Pattern] = {}
_errors: Dict[str, str] = {}
_loaded = False
_generation = 0          # bumped on every reload (a reloaded file keeps its id)


def generation() -> int:
    """Changes whenever patterns are (re)loaded, so callers caching toolpaths
    know a pattern with an unchanged id may now draw something else."""
    return _generation


def patterns_dir() -> Path:
    env = os.environ.get("BIOPRINTGEN_PATTERNS")
    return Path(env) if env else APP_DIR / "patterns"


def _load_equation(path: Path) -> Pattern:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise PatternError("the file must hold a JSON object")
    return make_equation_pattern(path.stem.lower(), data, path)


def make_equation_pattern(pid: str, data: dict, path: Optional[Path] = None) -> Pattern:
    eq = compile_equation(str(data.get("equation", "")))
    try:
        level = float(data.get("level", 0.0) or 0.0)
    except (TypeError, ValueError):
        raise PatternError("level must be a number") from None
    p = Pattern(pid, str(data.get("name") or pid), "levelset",
                str(data.get("description", "")), equation=str(data["equation"]),
                level=level, path=path, field_fn=_levelset_field(eq))
    k = measure_line_density(eq, level)
    if k <= 1e-6:
        raise PatternError(f"f(x, y, z) = {level:g} has no curves - "
                           "check the equation or the level")
    p._density = k
    return p


def _load_plugin(path: Path) -> Pattern:
    spec = importlib.util.spec_from_file_location(f"bioprintgen_pattern_{path.stem}", path)
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except Exception as e:  # noqa: BLE001 - user code
        raise PatternError(f"could not import: {type(e).__name__}: {e}") from None
    gen = getattr(mod, "generate", None)
    if not callable(gen):
        raise PatternError("the plugin has no generate(region, layer, settings, spacing)")
    meta = getattr(mod, "PATTERN", {}) or {}
    return Pattern(path.stem.lower(), str(meta.get("name") or path.stem), "path",
                   str(meta.get("description", "")), path=path, generate_fn=gen)


def reload() -> Dict[str, str]:
    """(Re)load user patterns.  Returns {file name: error} for files that failed."""
    global _loaded, _generation
    _generation += 1
    _registry.clear()
    _errors.clear()
    for p in _BUILTINS:
        _registry[p.id] = p
    folder = patterns_dir()
    if folder.is_dir():
        for path in sorted(folder.iterdir()):
            if path.suffix.lower() not in (".json", ".py") or path.name.startswith("_"):
                continue
            pid = path.stem.lower()
            if pid in _registry:
                _errors[path.name] = f"id '{pid}' is already taken"
                continue
            try:
                pat = _load_equation(path) if path.suffix.lower() == ".json" \
                    else _load_plugin(path)
            except PatternError as e:
                _errors[path.name] = str(e)
                continue
            except Exception as e:  # noqa: BLE001 - malformed user file
                _errors[path.name] = f"{type(e).__name__}: {e}"
                continue
            _registry[pid] = pat
    _loaded = True
    return dict(_errors)


def _ensure():
    if not _loaded:
        reload()


def available() -> List[Pattern]:
    """Built-ins first, then user patterns by name."""
    _ensure()
    builtins = [p for p in _registry.values() if p.builtin]
    user = sorted((p for p in _registry.values() if not p.builtin),
                  key=lambda p: p.name.lower())
    return builtins + user


def errors() -> Dict[str, str]:
    _ensure()
    return dict(_errors)


def get(pid) -> Optional[Pattern]:
    _ensure()
    return _registry.get(pattern_id(pid))


def kind_of(pid) -> Optional[str]:
    p = get(pid)
    return p.kind if p else None


def line_density(pid) -> float:
    p = get(pid)
    if p is None or p.kind != "levelset":
        return GYROID_LINE_DENSITY
    return p._density or GYROID_LINE_DENSITY


def register_embedded(definitions: dict) -> List[str]:
    """Register equation patterns embedded in an imported file whose ids are
    not known here (session only - nothing is written to the patterns folder).
    Returns the ids that were added."""
    _ensure()
    added = []
    for pid, d in (definitions or {}).items():
        if pid in _registry or not isinstance(d, dict) or d.get("kind") != "levelset":
            continue
        try:
            _registry[pid] = make_equation_pattern(pid, d)
            _registry[pid].description = (_registry[pid].description +
                                          " (embedded in an imported file)").strip()
            added.append(pid)
        except Exception:  # noqa: BLE001
            continue
    return added


# --------------------------------------------------------------------------- #
#  Generation
# --------------------------------------------------------------------------- #
def generate_user(pattern: Pattern, region, layer, settings) -> list:
    """Strokes for an equation or plugin pattern, clipped to `region`."""
    from .gyroid import levelset_strokes
    if pattern.kind == "levelset":
        period = max(settings.effective_gyroid_period(), 1e-3)
        return levelset_strokes(region, layer.z, period, pattern.field_fn, pattern.level)
    spacing = settings.effective_spacing()
    try:
        raw = pattern.generate_fn(region, layer, settings, spacing)
    except Exception as e:  # noqa: BLE001 - user code
        raise PatternError(f"pattern '{pattern.name}' failed on layer {layer.index}: "
                           f"{type(e).__name__}: {e}") from None
    return clip_strokes(raw, region)


def clip_strokes(raw, region) -> list:
    from shapely.geometry import LineString, MultiLineString, GeometryCollection
    out = []
    for stroke in raw or []:
        try:
            pts = [(float(p[0]), float(p[1])) for p in stroke]
        except (TypeError, ValueError, IndexError):
            continue
        if len(pts) < 2:
            continue
        clipped = LineString(pts).intersection(region)
        if clipped.is_empty:
            continue
        if isinstance(clipped, LineString):
            parts = [clipped]
        elif isinstance(clipped, (MultiLineString, GeometryCollection)):
            parts = [g for g in clipped.geoms if isinstance(g, LineString)]
        else:
            parts = []
        for g in parts:
            if g.length > 1e-6 and len(g.coords) >= 2:
                out.append(list(g.coords))
    return out
