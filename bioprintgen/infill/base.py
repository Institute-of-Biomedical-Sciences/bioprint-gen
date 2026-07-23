"""Shared helpers for infill generation.

An infill generator returns a list of *strokes*.  A stroke is a polyline
(list of (x, y) points) that is meant to be extruded in one continuous motion.
The toolpath planner decides ordering and where travels / extruder toggles go.
"""
from __future__ import annotations

import math
from typing import List, Sequence, Tuple

import numpy as np
from shapely.geometry import (
    LineString, MultiLineString, Polygon, MultiPolygon, GeometryCollection,
)
from shapely import affinity

Point = Tuple[float, float]
Stroke = List[Point]


def as_polygons(region) -> List[Polygon]:
    if region is None or region.is_empty:
        return []
    if isinstance(region, Polygon):
        return [region]
    if isinstance(region, (MultiPolygon, GeometryCollection)):
        return [g for g in region.geoms if isinstance(g, Polygon) and not g.is_empty]
    return []


def perimeter_strokes(region, count: int, line_width: float) -> Tuple[object, List[Stroke]]:
    """Generate `count` inset wall loops.

    Returns (inner_region_for_infill, list_of_wall_strokes).  The infill region
    is shrunk by the walls so infill sits inside the innermost wall.
    """
    walls: List[Stroke] = []
    count = int(count)          # a hand-edited JSON can supply 2.0 instead of 2
    if count <= 0:
        # still inset by half a line width so infill lines stay inside the part
        inner = region.buffer(-line_width / 2.0, join_style=2)
        return inner, walls

    current = region
    for i in range(count):
        offset = -line_width * (i + 0.5)
        ring = region.buffer(offset, join_style=2)
        for poly in as_polygons(ring):
            walls.append(list(poly.exterior.coords))
            for hole in poly.interiors:
                walls.append(list(hole.coords))
    inner = region.buffer(-line_width * (count + 0.5), join_style=2)
    return inner, walls


def clip_lines_to_region(lines: Sequence[LineString], region) -> List[Stroke]:
    """Intersect a set of infinite-ish lines with the region; return polylines."""
    out: List[Stroke] = []
    polys = as_polygons(region)
    if not polys:
        return out
    area = region
    for line in lines:
        clipped = line.intersection(area)
        if clipped.is_empty:
            continue
        if isinstance(clipped, LineString):
            out.append(list(clipped.coords))
        elif isinstance(clipped, MultiLineString):
            for seg in clipped.geoms:
                out.append(list(seg.coords))
        elif isinstance(clipped, GeometryCollection):
            for g in clipped.geoms:
                if isinstance(g, LineString) and not g.is_empty:
                    out.append(list(g.coords))
    return out


def parallel_line_set(region, angle_deg: float, spacing: float) -> List[LineString]:
    """Build parallel lines covering the region's bounding box at `angle_deg`.

    Implemented by generating axis-aligned horizontal lines over a rotated copy
    of the bounding box, then we return lines already rotated into place.
    """
    if spacing <= 0:
        raise ValueError("Strand spacing must be greater than 0.")
    minx, miny, maxx, maxy = region.bounds
    cx, cy = (minx + maxx) / 2.0, (miny + maxy) / 2.0
    # diagonal covers any rotation
    diag = math.hypot(maxx - minx, maxy - miny) / 2.0 + spacing
    theta = math.radians(angle_deg)
    # direction along the strand, and the normal we step along
    dx, dy = math.cos(theta), math.sin(theta)
    nx, ny = -dy, dx
    lines: List[LineString] = []
    n = int(math.ceil(2 * diag / spacing)) + 1
    start = -((n - 1) / 2.0) * spacing
    for k in range(n):
        off = start + k * spacing
        # centre point of this line
        px, py = cx + nx * off, cy + ny * off
        p0 = (px - dx * diag, py - dy * diag)
        p1 = (px + dx * diag, py + dy * diag)
        lines.append(LineString([p0, p1]))
    return lines


def layer_angle(base_angle: float, rotation: float, layer_index: int) -> float:
    """Angle for a given layer: base + rotation*index (the 'x-to-y' stepping)."""
    return base_angle + rotation * layer_index
