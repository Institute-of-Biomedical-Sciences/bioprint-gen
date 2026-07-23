"""Rectilinear infill.

Two variants, both single-direction *within a layer* (so there are zero strand
crossings inside any single layer) and rotated between layers by the
'x-to-y angle' (settings.layer_rotation, default 90 deg = classic woodpile).

* connected  -> parallel strands joined end-to-end into a boustrophedon path,
                but only where the joining connector stays inside the region, so
                holes and concavities are never bridged with extruded material.
* separate   -> each strand is its own bar (planner lifts/travels between them).
"""
from __future__ import annotations

import math
from typing import List

from shapely.geometry import LineString

from ..model import Layer, PrintSettings
from .base import (
    Stroke, parallel_line_set, clip_lines_to_region, layer_angle,
)


def _ordered_strands(region, angle_deg: float, spacing: float) -> List[Stroke]:
    """All clipped strands for a layer, ordered across the sweep direction."""
    lines = parallel_line_set(region, angle_deg, spacing)
    strands: List[Stroke] = []
    for line in lines:
        segs = clip_lines_to_region([line], region)
        # sort segments belonging to one sweep line along the strand direction
        segs.sort(key=lambda s: (s[0][0], s[0][1]))
        strands.extend(segs)
    return [s for s in strands if len(s) >= 2]


def _dist2(a, b) -> float:
    return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2


def _connected(strands: List[Stroke], region, spacing: float) -> List[Stroke]:
    """Greedy nearest-endpoint chaining into as few polylines as possible.

    Two strands are joined into one continuous (extruded) polyline only when the
    straight connector between them stays inside the region; otherwise a new
    polyline is started and the planner bridges it with a (non-extruding) travel.
    This is what keeps the connected pattern from drawing across a hole/bore or
    across a concave gap.
    """
    if not strands:
        return []
    remaining = [list(s) for s in strands]
    # buffer tolerates the tiny sagitta of connectors that hug a discretised
    # (polygonal) boundary, while a real hole/gap is far larger and still breaks.
    reg = region.buffer(max(spacing, 0.2) * 0.5)
    max_conn = spacing * 3.0
    polylines: List[Stroke] = []
    running: Stroke = remaining.pop(0)
    while remaining:
        end = running[-1]
        best_i, best_rev, best_d = 0, False, math.inf
        for i, seg in enumerate(remaining):
            d0 = _dist2(end, seg[0])
            d1 = _dist2(end, seg[-1])
            if d0 < best_d:
                best_d, best_i, best_rev = d0, i, False
            if d1 < best_d:
                best_d, best_i, best_rev = d1, i, True
        seg = remaining.pop(best_i)
        if best_rev:
            seg = list(reversed(seg))
        conn = LineString([end, seg[0]])
        if conn.length <= max_conn and reg.covers(conn):
            running.extend(seg)
        else:
            polylines.append(running)
            running = seg
    polylines.append(running)
    return polylines


def generate(region, layer: Layer, settings: PrintSettings, connected: bool) -> List[Stroke]:
    angle = layer_angle(settings.infill_angle, settings.layer_rotation, layer.index)
    strands = _ordered_strands(region, angle, settings.strand_spacing)
    if not strands:
        return []
    if connected:
        return _connected(strands, region, settings.strand_spacing)
    return strands
