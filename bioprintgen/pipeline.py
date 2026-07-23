"""High-level façade used by the GUI and by scripts/tests.

    project = Project.from_cuboid(w, d, h, settings)
    project.plan()          # build the toolpath
    text = project.gcode_text()
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from .model import Layer, LayerToolpath, PrintSettings
from .geometry import primitives, stlslicer
from .planning import toolpath as planner
from .gcode import writer as gwriter
from .gcode.writer import GLine


@dataclass
class Project:
    settings: PrintSettings
    layers: List[Layer] = field(default_factory=list)
    toolpath: List[LayerToolpath] = field(default_factory=list)
    source_desc: str = ""
    _model: Optional[stlslicer.SlicedModel] = None

    # ---- constructors ----
    @classmethod
    def from_cuboid(cls, width, depth, height, settings, center=False):
        layers = primitives.cuboid_layers(width, depth, height, settings, center)
        return cls(settings=settings, layers=layers,
                   source_desc=f"cuboid {width}x{depth}x{height} mm")

    @classmethod
    def from_cylinder(cls, diameter, height, settings, center=True):
        layers = primitives.cylinder_layers(diameter, height, settings, center=center)
        return cls(settings=settings, layers=layers,
                   source_desc=f"cylinder d{diameter} h{height} mm")

    @classmethod
    def from_stl(cls, path, settings):
        model = stlslicer.load_stl(path)
        layers = stlslicer.slice_model(model, settings)
        p = cls(settings=settings, layers=layers, source_desc=f"STL {path}")
        p._model = model
        return p

    # ---- pipeline ----
    def reslice(self):
        """Re-run slicing for an STL source after settings change."""
        if self._model is not None:
            self.layers = stlslicer.slice_model(self._model, self.settings)

    def plan(self):
        self.toolpath = planner.plan_all(self.layers, self.settings)
        return self.toolpath

    def glines(self) -> List[GLine]:
        return gwriter.render(self.toolpath, self.settings)

    def gcode_text(self) -> str:
        return gwriter.lines_to_text(self.glines())

    # ---- stats ----
    def stats(self) -> dict:
        n_moves = sum(len(l.moves) for l in self.toolpath)
        extrude_len = sum(m.length for l in self.toolpath for m in l.moves if m.extrude)
        travel_len = sum(m.length for l in self.toolpath for m in l.moves if not m.extrude)
        return {
            "layers": len(self.toolpath),
            "moves": n_moves,
            "extrude_mm": round(extrude_len, 2),
            "travel_mm": round(travel_len, 2),
        }
