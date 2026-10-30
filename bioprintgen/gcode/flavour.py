"""User-defined g-code flavours (templates).

A *flavour* is a set of small text templates, one per common action (travel,
extrude, layer change, tool change, ...).  Each template is a Python
``str.format`` string with named placeholders; the writer fills them in per
move.  Flavours are stored as JSON files under ``~/.bioprintgen/flavours`` so
they persist across sessions, and can be imported/exported as plain files.

Available placeholders per action
---------------------------------
* header      : {name} {layer_count} {first_z}
* footer      : {name} {z_max} {safe_z}
* layer_change: {layer} {z} {height} {f}
* travel      : {x} {y} {f}
* extrude     : {x} {y} {e} {de} {f} {length}
* tool_change : {tool} {offx} {offy}
* extruder_on / extruder_off : {tool}
* dwell       : {sec}                      (start and end dwell)
* hop_up / hop_down : {z} {zup} {hop} {f}  (travel safe height; zup = z + hop)

Any placeholder a template does not use is simply ignored, and any unknown
placeholder is left as literal text rather than raising.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Dict, List


# --------------------------------------------------------------------------- #
#  Template model
# --------------------------------------------------------------------------- #
@dataclass
class FlavourTemplate:
    name: str = "Custom"
    comment_prefix: str = ";"
    header: str = "{name} g-code\nG21\nG90"
    footer: str = "; end of print"
    layer_change: str = "; layer {layer} z={z}\nG1 Z{z} F{f}"
    travel: str = "G0 X{x} Y{y} F{f}"
    extrude: str = "G1 X{x} Y{y} E{e} F{f}"
    tool_change: str = "T{tool} ; offset {offx},{offy}"
    extruder_on: str = ""
    extruder_off: str = ""
    dwell: str = "G4 P{sec}"        # start/end pause; {sec} seconds
    hop_up: str = "G1 Z{zup} F{f}"    # safe-height lift before a travel; {zup}=z+lift {z} {hop} {f}
    hop_down: str = "G1 Z{z} F{f}"    # drop back after the travel

    # ---- (de)serialisation ----
    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "FlavourTemplate":
        fields = {f: d[f] for f in cls().to_dict().keys() if f in d}
        return cls(**fields)


class _SafeDict(dict):
    """Leaves unknown {placeholders} untouched instead of raising KeyError."""

    def __missing__(self, key):
        return "{" + key + "}"


def fill(template: str, **values) -> List[str]:
    """Format a template and split it into individual g-code lines.

    Blank templates yield no lines, so an unused action emits nothing.
    """
    if not template:
        return []
    try:
        text = template.format_map(_SafeDict(**values))
    except (ValueError, IndexError):
        # malformed template (e.g. stray brace) - emit verbatim so the user
        # can see and fix it rather than crashing the generator.
        text = template
    return text.split("\n")


# --------------------------------------------------------------------------- #
#  On-disk storage
# --------------------------------------------------------------------------- #
def flavours_dir() -> Path:
    d = Path(os.environ.get("BIOPRINTGEN_FLAVOURS", Path.home() / ".bioprintgen" / "flavours"))
    d.mkdir(parents=True, exist_ok=True)
    return d


def _safe_name(name: str) -> str:
    keep = "-_. "
    return "".join(c for c in name if c.isalnum() or c in keep).strip() or "flavour"


def save_flavour(t: FlavourTemplate) -> Path:
    path = flavours_dir() / f"{_safe_name(t.name)}.json"
    path.write_text(json.dumps(t.to_dict(), indent=2), encoding="utf-8")
    return path


def load_flavour(path) -> FlavourTemplate:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return FlavourTemplate.from_dict(data)


def list_flavours() -> Dict[str, FlavourTemplate]:
    """Return {name: FlavourTemplate} for every saved flavour."""
    out: Dict[str, FlavourTemplate] = {}
    for p in sorted(flavours_dir().glob("*.json")):
        try:
            t = load_flavour(p)
            out[t.name] = t
        except Exception:
            continue
    return out


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
    dest.write_text(json.dumps(t.to_dict(), indent=2), encoding="utf-8")
    return dest
