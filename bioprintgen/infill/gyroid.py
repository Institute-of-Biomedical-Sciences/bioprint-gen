"""Gyroid infill.

The gyroid is the triply-periodic minimal surface

    g(x,y,z) = sin(x)cos(y) + sin(y)cos(z) + sin(z)cos(x) = 0

Per layer we fix z and extract the *zero isocontour* of g over the layer's
bounding box, then clip it to the region.  Because it is the level set of a
smooth function, the resulting curves never self-cross inside a layer, and the
pattern naturally rotates/advances from one z to the next - giving the strong,
isotropic, open-pore lattice that makes gyroid popular for scaffolds.

Coordinates are scaled by f = 2*pi / period so `gyroid_period` is the real cell
size in millimetres.
"""
from __future__ import annotations

import math
from typing import List

import numpy as np
from contourpy import contour_generator
from shapely.geometry import LineString, MultiLineString, GeometryCollection

from ..model import Layer, PrintSettings
from .base import Stroke, as_polygons


def _field(xs: np.ndarray, ys: np.ndarray, z: float, f: float) -> np.ndarray:
    X, Y = np.meshgrid(xs * f, ys * f)
    Z = z * f
    return (np.sin(X) * np.cos(Y)
            + np.sin(Y) * math.cos(Z)
            + math.sin(Z) * np.cos(X))


def generate(region, layer: Layer, settings: PrintSettings) -> List[Stroke]:
    period = max(settings.effective_gyroid_period(), 1e-3)
    return levelset_strokes(region, layer.z, period, _field)


def levelset_strokes(region, z: float, period: float, field_fn,
                     level: float = 0.0) -> List[Stroke]:
    """Strokes along the `level` isocontour of `field_fn(xs, ys, z, f)` (with
    f = 2*pi / period) over the region's bounding box, clipped to the region.
    Shared by the gyroid and the user's equation patterns."""
    polys = as_polygons(region)
    if not polys:
        return []
    minx, miny, maxx, maxy = region.bounds
    f = 2.0 * math.pi / period

    # sample density: enough points per cell to resolve the wave smoothly
    per_cell = 24
    nx = max(8, int((maxx - minx) / period * per_cell))
    ny = max(8, int((maxy - miny) / period * per_cell))
    nx = min(nx, 1200)
    ny = min(ny, 1200)
    xs = np.linspace(minx, maxx, nx)
    ys = np.linspace(miny, maxy, ny)

    field = field_fn(xs, ys, z, f)
    gen = contour_generator(xs, ys, field)
    raw_lines = gen.lines(level)  # list of (N,2) arrays, ordered

    strokes: List[Stroke] = []
    for arr in raw_lines:
        if len(arr) < 2:
            continue
        ls = LineString(arr)
        clipped = ls.intersection(region)
        if clipped.is_empty:
            continue
        geoms = []
        if isinstance(clipped, LineString):
            geoms = [clipped]
        elif isinstance(clipped, MultiLineString):
            geoms = list(clipped.geoms)
        elif isinstance(clipped, GeometryCollection):
            geoms = [g for g in clipped.geoms if isinstance(g, LineString)]
        for g in geoms:
            if not g.is_empty and len(g.coords) >= 2:
                strokes.append(list(g.coords))
    return strokes
