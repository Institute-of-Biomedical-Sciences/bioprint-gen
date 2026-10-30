"""Load user-editable defaults from `default_settings.json`.

The file sits next to `main.py` and is **read-only** as far as the app is
concerned: edit it in a text editor to change the values the GUI starts with.
Unknown keys are ignored and missing keys fall back to the built-in defaults, so
a partial file is fine.

Layout:

    {
      "ui":             {"theme": "dark", "expanded_panels": ["Design"]},
      "source":         {"kind": "cuboid", "width": 10, ...},
      "print_settings": {"layer_height": 0.2, ...}
    }
"""
from __future__ import annotations

import ast
import json
import re
from dataclasses import fields
from pathlib import Path
from typing import Optional, Tuple

from .model import (
    PrintSettings, Dialect, DriveMode,
    LayerHeightSection, ToolLineRange, InfillSection, pattern_id, parse_pattern,
)

FILENAME = "default_settings.json"

# infill_type is not an enum any more: user patterns have plain string ids
_ENUMS = {"dialect": Dialect, "infill_type": parse_pattern, "drive": DriveMode}
_TUPLES = ("extruder2_offset", "extruder3_offset")
# carried separately (top-level "source" in both the defaults file and the
# exported settings block), never inside print_settings
_NOT_SERIALISED = {"source"}
# marker of the machine-readable line in an exported file's settings block
GCODE_JSON_MARKER = "BIOPRINTGEN_JSON"



def default_settings_path() -> Path:
    """`default_settings.json` in the project root (next to main.py)."""
    return Path(__file__).resolve().parent.parent / FILENAME


# --------------------------------------------------------------------------- #
#  (de)serialisation
# --------------------------------------------------------------------------- #
def settings_to_dict(s: PrintSettings) -> dict:
    out = {}
    for f in fields(s):
        if f.name in _NOT_SERIALISED:
            continue
        v = getattr(s, f.name)
        if f.name == "custom_flavour":
            out[f.name] = getattr(v, "name", None)
        elif f.name == "layer_sections":
            out[f.name] = [[x.z_start, x.z_end, x.height] for x in v]
        elif f.name == "tool_line_ranges":
            out[f.name] = [[x.start_line, x.end_line, x.extruder] for x in v]
        elif f.name == "infill_sections":
            out[f.name] = [[x.z_start, x.z_end, pattern_id(x.infill_type), x.percent]
                           for x in v]
        elif f.name == "infill_type":
            out[f.name] = pattern_id(v)
        elif hasattr(v, "value"):            # Enum
            out[f.name] = v.value
        elif isinstance(v, tuple):
            out[f.name] = list(v)
        else:
            out[f.name] = v
    return out


def dict_to_settings(d: dict) -> PrintSettings:
    s = PrintSettings()
    if not isinstance(d, dict):
        return s
    for f in fields(s):
        if f.name not in d:
            continue
        v = d[f.name]
        try:
            if f.name == "custom_flavour" or f.name in _NOT_SERIALISED:
                continue                     # flavour resolved by name in the GUI
            if f.name in _ENUMS:
                setattr(s, f.name, _ENUMS[f.name](v))
            elif f.name == "layer_sections":
                s.layer_sections = [LayerHeightSection(float(r[0]), float(r[1]), float(r[2]))
                                    for r in (v or [])]
            elif f.name == "infill_sections":
                s.infill_sections = [InfillSection(float(r[0]), float(r[1]),
                                                   parse_pattern(r[2]), float(r[3]))
                                     for r in (v or [])]
            elif f.name == "tool_line_ranges":
                s.tool_line_ranges = [ToolLineRange(int(r[0]), int(r[1]), int(r[2]))
                                      for r in (v or [])]
            elif f.name in _TUPLES:
                setattr(s, f.name, (float(v[0]), float(v[1])))
            else:
                setattr(s, f.name, v)
        except Exception:
            continue                         # bad value -> keep the built-in default
    return s


# --------------------------------------------------------------------------- #
#  Loading
# --------------------------------------------------------------------------- #
def load_defaults(path: Optional[Path] = None) -> Optional[Tuple[PrintSettings, dict, dict]]:
    """Return (settings, source_dict, ui_dict) or None if the file is absent/broken."""
    p = Path(path) if path else default_settings_path()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    settings = dict_to_settings(data.get("print_settings", {}))
    source = data.get("source", {}) or {}
    ui = data.get("ui", {}) or {}
    return settings, (source if isinstance(source, dict) else {}), \
           (ui if isinstance(ui, dict) else {})


_COMMENT = ("Edit these values to change what BioprintGEN starts with. The app "
            "only writes ui.scale here (from the toolbar zoom control); everything "
            "else is yours to hand-edit. Unknown keys are ignored; missing keys use "
            "built-in defaults.")


def _template_doc() -> dict:
    return {
        "_comment": _COMMENT,
        "ui": {"theme": "dark", "scale": 1.0, "expanded_panels": ["Design"]},
        "source": {"kind": "cuboid", "width": 10.0, "depth": 10.0,
                   "height": 5.0, "diameter": 12.0, "stl_path": None},
        "print_settings": settings_to_dict(PrintSettings()),
    }


def write_template(path: Optional[Path] = None) -> Path:
    """Write a fully-populated defaults file (used to seed the shipped file)."""
    p = Path(path) if path else default_settings_path()
    p.write_text(json.dumps(_template_doc(), indent=2), encoding="utf-8")
    return p


def save_ui_scale(scale: float, path: Optional[Path] = None) -> bool:
    """Persist just `ui.scale`, preserving every other (hand-edited) key.

    Refuses to touch a file it cannot parse, so a malformed file is never
    clobbered.  If the file is absent it is seeded from the template so it stays
    a complete, hand-editable document.  Returns True on success.
    """
    p = Path(path) if path else default_settings_path()
    data = None
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return False
        if not isinstance(data, dict):
            return False
    if data is None:
        data = _template_doc()
    ui = data.get("ui")
    if not isinstance(ui, dict):
        ui = {}
    ui["scale"] = round(float(scale), 3)
    data["ui"] = ui
    try:
        p.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return True
    except OSError:
        return False


# --------------------------------------------------------------------------- #
#  Reading settings back out of an exported g-code file
# --------------------------------------------------------------------------- #
_RE_SECTION = re.compile(r"z\[([-\d.]+)\s*\.\.\s*([-\d.]+)\]\s*height=([-\d.]+)")
_RE_INFILL = re.compile(r"infill z\[([-\d.]+)\s*\.\.\s*([-\d.]+)\]\s*"
                        r"pattern=(\w+)\s+percent=([-\d.]+)")
_RE_RANGE = re.compile(r"lines\s+(\d+)\.\.(\d+)\s*->\s*extruder\s+(\d+)")
_RE_KEYVAL = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$")


def gcode_settings_payload(s: PrintSettings) -> str:
    """One-line JSON written into an export's settings block."""
    doc = {"version": 1, "print_settings": settings_to_dict(s),
           "source": dict(s.source or {})}
    embedded = used_pattern_definitions(s)
    if embedded:
        doc["patterns"] = embedded
    return json.dumps(doc, separators=(",", ":"), ensure_ascii=False)


def used_pattern_definitions(s: PrintSettings) -> dict:
    """{id: definition} of the user equation patterns a print uses, so an
    import can rebuild it on a machine that lacks the pattern file."""
    from .infill import patterns
    out = {}
    for v in [s.infill_type] + [sec.infill_type for sec in s.infill_sections]:
        p = patterns.get(v)
        if p is not None and not p.builtin and p.kind == "levelset":
            out[p.id] = p.definition()
    return out


def parse_gcode_settings(text: str):
    """Recover settings from an exported file.

    Returns (settings, source_dict, flavour_name, complete), or None when the
    file holds no BioprintGEN settings at all.  `complete` is True when the
    machine-readable JSON line was found (exports from this version on); older
    exports only carry the human-readable ``; key = value`` lines, which restore
    the print settings but not the source shape.
    """
    lines = text.replace("\r\n", "\n").split("\n")
    for line in lines:
        i = line.find(GCODE_JSON_MARKER)
        if i < 0:
            continue
        try:
            doc = json.loads(line[i + len(GCODE_JSON_MARKER):].strip())
        except Exception:
            continue
        ps = doc.get("print_settings", {}) or {}
        if doc.get("patterns"):
            from .infill import patterns
            patterns.register_embedded(doc["patterns"])
        return (dict_to_settings(ps), doc.get("source", {}) or {},
                ps.get("custom_flavour"), True)

    # --- fallback: the human-readable block of older exports ---
    names = {f.name for f in fields(PrintSettings())}
    raw: dict = {}
    sections, ranges, infills = [], [], []
    in_block = False
    for line in lines:
        body = line.strip().lstrip(";#/").strip()
        if "BioprintGEN settings" in body:
            in_block = True
            continue
        if not in_block:
            continue
        m = _RE_INFILL.match(body)
        if m:
            infills.append([float(m.group(1)), float(m.group(2)),
                            m.group(3), float(m.group(4))])
            continue
        m = _RE_SECTION.match(body)
        if m:
            sections.append([float(g) for g in m.groups()])
            continue
        m = _RE_RANGE.match(body)
        if m:
            ranges.append([int(g) for g in m.groups()])
            continue
        m = _RE_KEYVAL.match(body)
        if m and m.group(1) in names:
            val = m.group(2).strip()
            try:
                raw[m.group(1)] = ast.literal_eval(val)
            except Exception:
                raw[m.group(1)] = val          # enum value strings etc.
    if not raw:
        return None
    if sections:
        raw["layer_sections"] = sections
    if ranges:
        raw["tool_line_ranges"] = ranges
    if infills:
        raw["infill_sections"] = infills
    return dict_to_settings(raw), {}, raw.get("custom_flavour"), False

