"""Primitive solids (cuboid, cylinder) expressed as sliced layers.

We deliberately produce the *same* Layer objects the STL slicer produces, so the
infill / planning / gcode stages never need to know whether the source was a
parametric primitive or an imported mesh.
"""
from __future__ import annotations

import math
from typing import List

import numpy as np
from shapely.geometry import Polygon, Point

from ..model import Layer, PrintSettings, build_z_levels


def _z_levels(total_height: float, settings: PrintSettings) -> List[float]:
    """Return [(z_top, height), ...] honouring variable-height sections."""
    return build_z_levels(total_height, settings)


def cuboid_layers(width: float, depth: float, height: float,
                  settings: PrintSettings, center: bool = False) -> List[Layer]:
    """Axis-aligned rectangular prism.

    Origin at (0,0) corner unless `center` is set. Matches the reference where
    the scaffold starts at the coordinate origin after G92 X0 Y0.
    """
    if center:
        x0, y0 = -width / 2.0, -depth / 2.0
    else:
        x0, y0 = 0.0, 0.0
    poly = Polygon([(x0, y0), (x0 + width, y0),
                    (x0 + width, y0 + depth), (x0, y0 + depth)])
    layers = []
    for i, (z, h) in enumerate(_z_levels(height, settings)):
        layers.append(Layer(z=round(z, 6), index=i, regions=poly, height=h))
    return layers


def cylinder_layers(diameter: float, height: float, settings: PrintSettings,
                    segments: int = 128, center: bool = True) -> List[Layer]:
    """Right circular cylinder, discretised as a fine polygon per layer."""
    r = diameter / 2.0
    cx, cy = (0.0, 0.0) if center else (r, r)
    pts = [(cx + r * math.cos(2 * math.pi * k / segments),
            cy + r * math.sin(2 * math.pi * k / segments))
           for k in range(segments)]
    poly = Polygon(pts)
    layers = []
    for i, (z, h) in enumerate(_z_levels(height, settings)):
        layers.append(Layer(z=round(z, 6), index=i, regions=poly, height=h))
    return layers
