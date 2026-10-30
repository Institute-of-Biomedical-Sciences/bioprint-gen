"""User-defined g-code flavours (templates).

A *flavour* is a set of small text templates, one per action the writer
performs (header, layer change, travel, extrude, tool change, ...).  Each
template is a Python ``str.format`` string with named placeholders, plus
optional conditional blocks; the writer fills them in per move.

Flavours are stored as JSON files in the app folder (``<app>/flavours``, or
``$BIOPRINTGEN_FLAVOURS``), so they persist across sessions and can be
imported/exported as plain files.  Starting points ship in
``<app>/flavours/templates``: ``planet_cnc.json`` and ``marlin.json``
reproduce the built-in Planet CNC and Marlin writers byte-for-byte (enforced
by tests/test_flavour_templates.py).

Template syntax
---------------
* ``{name}``            placeholder (unknown placeholders are left as text)
* ``{?cond:text}``      *text* only when *cond* holds; ``{?!cond:text}`` when
                        it doesn't; ``{?a&b:text}`` when both hold.  Blocks may
                        nest and may span lines.  A line left empty because
                        its blocks were skipped is dropped entirely.
* ``{blank}``           expands to nothing - use it for an action that should
                        emit a single empty line (a blank action emits nothing)

See ``REFERENCE`` below for the actions, their placeholders and the
conditions; the flavour editor shows the same text.
"""
from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass, asdict, fields as dc_fields
from pathlib import Path
from typing import Dict, List, Optional


# --------------------------------------------------------------------------- #
#  Template model
# --------------------------------------------------------------------------- #
@dataclass
class FlavourTemplate:
    name: str = "Custom"
    description: str = ""
    comment_prefix: str = ";"
    # -- file --
    header: str = "{name} g-code\nG21\nG90"   # before the user start g-code
    setup: str = ""                           # after the user start g-code
    footer: str = "; end of print"            # after the user end g-code
    trailer: str = ""                         # after the settings block
    # -- layers --
    layer_change: str = "; layer {layer} z={z}\nG1 Z{z} F{f}"
    layer_end: str = ""
    # -- moves --
    travel: str = "G0 X{x} Y{y} F{f}"
    extrude: str = "G1 X{x} Y{y} E{e} F{f}"
    coast: str = ""          # blank -> the travel template at print speed
    # -- flow --
    extruder_on: str = ""
    extruder_off: str = ""
    stroke_start: str = ""
    stroke_end: str = ""
    dwell: str = "G4 P{sec}"  # start dwell (and end dwell if that is blank)
    end_dwell: str = ""
    # -- travel safe height --
    hop_up: str = "G1 Z{zup} F{f}"
    hop_down: str = "G1 Z{z} F{f}"
    # -- tool change --
    tool_leave: str = ""
    tool_enter: str = ""
    tool_change: str = "T{tool} ; offset {offx},{offy}"

    # ---- (de)serialisation ----
    def to_dict(self) -> dict:
        """Multi-line templates are stored as lists of lines (readable JSON)."""
        out = {}
        for k, v in asdict(self).items():
            out[k] = v.split("\n") if isinstance(v, str) and "\n" in v else v
        return out

    @classmethod
    def from_dict(cls, d: dict) -> "FlavourTemplate":
        known = {f.name for f in dc_fields(cls)}
        kw = {}
        for k, v in d.items():
            if k not in known:
                continue
            if isinstance(v, list):
                v = "\n".join(str(x) for x in v)
            kw[k] = "" if v is None else str(v)
        return cls(**kw)


# Editor layout: (group, [(attribute, label, placeholders)]).  Placeholders
# listed here are the action-specific ones; the globals in REFERENCE work in
# every action.
ACTIONS = [
    ("File", [
        ("header", "Header", "{layer_count} {first_z}"),
        ("setup", "Setup (after start g-code)", ""),
        ("footer", "Footer (after end g-code)", "{z_max} {safe_z}"),
        ("trailer", "Trailer (after settings block)", ""),
    ]),
    ("Layers", [
        ("layer_change", "Layer start", "{layer} {z} {height} {f}=Z speed"),
        ("layer_end", "Layer end", "{layer} {z} {rise} {f}=Z speed"),
    ]),
    ("Moves", [
        ("travel", "Travel", "{x} {y} {f}=travel speed"),
        ("extrude", "Extrude", "{x} {y} {e} {de} {da} {length} {f}=print speed"),
        ("coast", "Coast (extrusion off, print speed)", "{x} {y} {f}  — blank: uses Travel"),
    ]),
    ("Flow", [
        ("extruder_on", "Extruder / valve on", "{tool} {port}"),
        ("extruder_off", "Extruder / valve off", "{tool} {port}"),
        ("stroke_start", "Stroke start", "before the first extruding move of a stroke"),
        ("stroke_end", "Stroke end", "after the last extruding move of a stroke"),
        ("dwell", "Start dwell", "{sec}  (only when start dwell > 0)"),
        ("end_dwell", "End dwell", "{sec}  — blank: uses Start dwell"),
    ]),
    ("Travel safe height", [
        ("hop_up", "Up", "{z} {zup} {hop} {f}=Z speed"),
        ("hop_down", "Down", "{z} {zup} {hop} {f}=Z speed"),
    ]),
    ("Tool change", [
        ("tool_leave", "Leave extruder", "{tool} {tool0} {offx} {offy} {offx_var} {offy_var}"),
        ("tool_enter", "Enter extruder", "{tool} {tool0} {offx} {offy} {offx_var} {offy_var}"),
        ("tool_change", "Tool change (after enter)", "{tool} {prev} {offx} {offy}"),
    ]),
]

REFERENCE = """\
SYNTAX
  {name}            placeholder; unknown names are left as text
  {?cond:text}      text only if cond holds; {?!cond:..} if not; {?a&b:..} both
                    (blocks nest and may span lines; a line left empty by a
                    skipped block is dropped)
  {blank}           nothing - for an action that is just one empty line

ORDER (per move)
  tool leave/enter/change -> extruder off (non-extruding move) -> hop up (travel)
  -> extruder on (extruding) -> stroke start + dwell -> travel/extrude/coast
  -> stroke end -> hop down (travel) -> extruder off + end dwell
  Layer: layer start ... moves ... extruder off, layer end.
  File: header, start g-code, setup, layers, return to extruder 1,
        end g-code, footer, settings block, trailer.

GLOBAL PLACEHOLDERS (every action)
  {name} {layer_count} {first_z} {z_max} {safe_z}=z_max+safe height
  {safe_hop}=safe height  {f_print} {f_travel} {f_z}  {hop}=travel safe height
  {ramp} {start_ramp} {end_retract}  {valve}=pressure x10
  {e2x} {e2y} {e3x} {e3y}=extruder offsets  {axis} {axisvar}=metered axis
  (A/_a, B/_b, C/_c - the active extruder's while printing)
  {port}=valve output  {tool} {tool0}=active extruder (1-based / 0-based)
  {blank}

CONDITIONS
  piston  pneumatic  tool_change  zero_xy  flow_control
  ramp  start_ramp  end_retract  start_dwell  end_dwell  travel_lift   (value > 0)
  first_layer  last_layer                         (layer and move actions)
  stroke_start  stroke_end                        (move actions)
  reference (tool is extruder 1)  final (return to extruder 1 at the end)
"""


# --------------------------------------------------------------------------- #
#  Filling
# --------------------------------------------------------------------------- #
class _SafeDict(dict):
    """Leaves unknown {placeholders} untouched instead of raising KeyError."""

    def __missing__(self, key):
        return "{" + key + "}"


_SKIPPED = "\x00"   # marks where a conditional block produced nothing


def _holds(expr: str, conditions: dict) -> bool:
    for part in expr.split("&"):
        part = part.strip()
        neg = part.startswith("!")
        name = part[1:].strip() if neg else part
        if bool(conditions.get(name, False)) == neg:
            return False
    return True


def _conditionals(text: str, conditions: dict) -> str:
    out: List[str] = []
    i, n = 0, len(text)
    while i < n:
        j = text.find("{?", i)
        if j < 0:
            out.append(text[i:])
            break
        out.append(text[i:j])
        depth, k = 0, j
        while k < n:
            if text[k] == "{":
                depth += 1
            elif text[k] == "}":
                depth -= 1
                if depth == 0:
                    break
            k += 1
        if k >= n:                      # unbalanced: leave the rest as typed
            out.append(text[j:])
            break
        expr, _sep, body = text[j + 2:k].partition(":")
        body = _conditionals(body, conditions) if _holds(expr, conditions) else ""
        out.append(body or _SKIPPED)
        i = k + 1
    return "".join(out)


def fill(template: str, conditions: Optional[dict] = None, **values) -> List[str]:
    """Format a template and split it into individual g-code lines.

    Blank templates yield no lines, so an unused action emits nothing.
    """
    if not template:
        return []
    text = _conditionals(template, conditions or {}) if "{?" in template else template
    values.setdefault("blank", "")
    try:
        text = text.format_map(_SafeDict(**values))
    except (ValueError, IndexError):
        # malformed template (e.g. stray brace) - emit verbatim so the user
        # can see and fix it rather than crashing the generator.
        pass
    lines = []
    for line in text.split("\n"):
        if _SKIPPED in line:
            line = line.replace(_SKIPPED, "")
            if not line.strip():
                continue
        lines.append(line)
    return lines


# --------------------------------------------------------------------------- #
#  On-disk storage
# --------------------------------------------------------------------------- #
APP_DIR = Path(__file__).resolve().parent.parent.parent
_LEGACY_DIR = Path.home() / ".bioprintgen" / "flavours"
_migrated = False


def flavours_dir() -> Path:
    """Saved flavours: ``<app>/flavours`` (or ``$BIOPRINTGEN_FLAVOURS``)."""
    env = os.environ.get("BIOPRINTGEN_FLAVOURS")
    d = Path(env) if env else APP_DIR / "flavours"
    d.mkdir(parents=True, exist_ok=True)
    if not env:
        _migrate_legacy(d)
    return d


def templates_dir() -> Path:
    """Shipped starting points (read-only by convention)."""
    return APP_DIR / "flavours" / "templates"


def _migrate_legacy(d: Path) -> None:
    """Earlier versions kept flavours in ~/.bioprintgen/flavours: copy any
    that the app folder does not have yet (once per run, originals kept)."""
    global _migrated
    if _migrated:
        return
    _migrated = True
    try:
        for p in _LEGACY_DIR.glob("*.json"):
            if not (d / p.name).exists():
                shutil.copy2(p, d / p.name)
    except OSError:
        pass


def _safe_name(name: str) -> str:
    keep = "-_. "
    return "".join(c for c in name if c.isalnum() or c in keep).strip() or "flavour"


def _dump(t: FlavourTemplate) -> str:
    return json.dumps(t.to_dict(), indent=2, ensure_ascii=False) + "\n"


def save_flavour(t: FlavourTemplate) -> Path:
    path = flavours_dir() / f"{_safe_name(t.name)}.json"
    path.write_text(_dump(t), encoding="utf-8")
    return path


def load_flavour(path) -> FlavourTemplate:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return FlavourTemplate.from_dict(data)


def _load_all(folder: Path) -> Dict[str, FlavourTemplate]:
    out: Dict[str, FlavourTemplate] = {}
    if not folder.is_dir():
        return out
    for p in sorted(folder.glob("*.json")):
        try:
            t = load_flavour(p)
            out[t.name] = t
        except Exception:
            continue
    return out


def list_flavours() -> Dict[str, FlavourTemplate]:
    """Return {name: FlavourTemplate} for every saved flavour."""
    return _load_all(flavours_dir())


def list_templates() -> Dict[str, FlavourTemplate]:
    """Return {name: FlavourTemplate} for the shipped templates."""
    return _load_all(templates_dir())


def delete_flavour(name: str) -> None:
    path = flavours_dir() / f"{_safe_name(name)}.json"
    if path.exists():
        path.unlink()


def import_flavour(src) -> FlavourTemplate:
    """Copy an external flavour JSON into the store and return it."""
    t = load_flavour(src)
    save_flavour(t)
    return t


def export_flavour(t: FlavourTemplate, dest) -> Path:
    dest = Path(dest)
    dest.write_text(_dump(t), encoding="utf-8")
    return dest
