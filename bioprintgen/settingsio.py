"""Load user-editable defaults from `default_settings.json`.

The file sits next to `main.py` and is **read-only** as far as the app is
concerned: edit it in a text editor to change the values the GUI starts with.
Unknown keys are ignored and missing keys fall back to the built-in defaults, so
a partial file is fine.

Layout:

    {
      "ui":             {"theme": "dark", "expanded_panels": ["Source"]},
      "source":         {"kind": "cuboid", "width": 10, ...},
      "print_settings": {"layer_height": 0.2, ...}
    }
"""
from __future__ import annotations

import json
from dataclasses import fields
from pathlib import Path
from typing import Optional, Tuple

from .model import (
    PrintSettings, Dialect, DriveMode, InfillType,
    LayerHeightSection, ToolLineRange,
)

FILENAME = "default_settings.json"

_ENUMS = {"dialect": Dialect, "infill_type": InfillType, "drive": DriveMode}
_TUPLES = ("extruder2_offset", "extruder3_offset")


def default_settings_path() -> Path:
    """`default_settings.json` in the project root (next to main.py)."""
    return Path(__file__).resolve().parent.parent / FILENAME


# --------------------------------------------------------------------------- #
#  (de)serialisation
# --------------------------------------------------------------------------- #
def settings_to_dict(s: PrintSettings) -> dict:
    out = {}
    for f in fields(s):
        v = getattr(s, f.name)
        if f.name == "custom_flavour":
            out[f.name] = getattr(v, "name", None)
        elif f.name == "layer_sections":
            out[f.name] = [[x.z_start, x.z_end, x.height] for x in v]
        elif f.name == "tool_line_ranges":
            out[f.name] = [[x.start_line, x.end_line, x.extruder] for x in v]
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
            if f.name == "custom_flavour":
                continue                     # resolved by name in the GUI
            if f.name in _ENUMS:
                setattr(s, f.name, _ENUMS[f.name](v))
            elif f.name == "layer_sections":
                s.layer_sections = [LayerHeightSection(float(r[0]), float(r[1]), float(r[2]))
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


def write_template(path: Optional[Path] = None) -> Path:
    """Write a fully-populated defaults file (used to seed the shipped file)."""
    p = Path(path) if path else default_settings_path()
    doc = {
        "_comment": "Edit these values to change what BioprintGEN starts with. "
                    "The app only reads this file, it never writes it. "
                    "Unknown keys are ignored; missing keys use built-in defaults.",
        "ui": {"theme": "dark", "expanded_panels": ["Source"]},
        "source": {"kind": "cuboid", "width": 10.0, "depth": 10.0,
                   "height": 5.0, "diameter": 12.0, "stl_path": None},
        "print_settings": settings_to_dict(PrintSettings()),
    }
    p.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return p
