"""Toolpath planning.

Turns a sliced Layer into an ordered list of Moves:

  1. optional perimeter walls
  2. infill strokes (rectilinear connected / separate / gyroid)
  3. ordering that keeps single-layer crossings to a minimum

True minimum-crossing routing is NP-hard, so we use a greedy nearest-endpoint
ordering.  For the parallel-strand patterns this reproduces the natural
sweep order (adjacent strands are always nearest), so travels never cross laid
material; for gyroid it minimises travel length, which in practice minimises
crossings between disjoint contour curves.
"""
from __future__ import annotations

import math
from typing import List, Optional, Tuple

from ..model import (
    Layer, LayerToolpath, Move, MoveKind, PrintSettings, InfillType, pattern_id,
)
from ..infill.base import perimeter_strokes, Stroke
from ..infill import rectilinear, gyroid, patterns

Point = Tuple[float, float]


def _dist2(a: Point, b: Point) -> float:
    return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2


def _order_strokes(strokes: List[Stroke], start: Point,
                   minimize: bool) -> List[Stroke]:
    """Greedy nearest-endpoint ordering. Each stroke is oriented so its chosen
    start endpoint is the one nearest the current position."""
    if not minimize:
        return strokes
    remaining = list(strokes)
    ordered: List[Stroke] = []
    cur = start
    while remaining:
        best_i = 0
        best_rev = False
        best_d = math.inf
        for i, s in enumerate(remaining):
            d0 = _dist2(cur, s[0])
            d1 = _dist2(cur, s[-1])
            if d0 < best_d:
                best_d, best_i, best_rev = d0, i, False
            if d1 < best_d:
                best_d, best_i, best_rev = d1, i, True
        s = remaining.pop(best_i)
        if best_rev:
            s = list(reversed(s))
        ordered.append(s)
        cur = s[-1]
    return ordered


def _emit_stroke(moves: List[Move], stroke: Stroke, kind: MoveKind,
                 cur: Point) -> Point:
    # travel to the stroke start
    if cur != tuple(stroke[0]):
        moves.append(Move(start=cur, end=tuple(stroke[0]),
                          kind=MoveKind.TRAVEL, extrude=False))
    prev = tuple(stroke[0])
    for pt in stroke[1:]:
        p = tuple(pt)
        if p == prev:
            continue
        moves.append(Move(start=prev, end=p, kind=kind, extrude=True))
        prev = p
    return prev


def _rotate_loop(stroke: Stroke, anchor: Point) -> Stroke:
    """Re-start a closed loop at the vertex nearest `anchor` (moves the seam).
    Open strokes are returned unchanged."""
    if len(stroke) < 4 or tuple(stroke[0]) != tuple(stroke[-1]):
        return stroke
    pts = list(stroke[:-1])
    k = min(range(len(pts)), key=lambda i: _dist2(pts[i], anchor))
    rot = pts[k:] + pts[:k]
    return rot + [rot[0]]


def layer_start_corner(region, index: int) -> Point:
    """Corner of the layer's bounding box that layer `index` starts nearest:
    bottom-left, bottom-right, top-right, top-left, repeating."""
    minx, miny, maxx, maxy = region.bounds
    return [(minx, miny), (maxx, miny), (maxx, maxy), (minx, maxy)][index % 4]


def plan_layer(layer: Layer, settings: PrintSettings,
               start_pos: Optional[Point] = None,
               seed: Optional[Point] = None) -> LayerToolpath:
    """Plan one layer.

    `start_pos` is where the nozzle actually is (the travel starts there);
    `seed`, if given, is the point the layer should *begin* nearest to — used to
    rotate the start/seam between layers without inventing a fake travel.
    """
    lt = LayerToolpath(z=layer.z, index=layer.index, height=layer.height,
                       extruder=getattr(layer, "extruder", 1))
    cur: Point = start_pos if start_pos is not None else (0.0, 0.0)
    anchor: Point = seed if seed is not None else cur

    # 1. perimeters + shrink region for infill
    inner, walls = perimeter_strokes(layer.regions, settings.perimeters,
                                     settings.line_width)

    # 2. infill strokes
    if inner is None or inner.is_empty:
        infill_strokes: List[Stroke] = []
    elif settings.infill_type == InfillType.RECTILINEAR_CONNECTED:
        infill_strokes = rectilinear.generate(inner, layer, settings, connected=True)
    elif settings.infill_type == InfillType.RECTILINEAR_SEPARATE:
        infill_strokes = rectilinear.generate(inner, layer, settings, connected=False)
    elif settings.infill_type == InfillType.GYROID:
        infill_strokes = gyroid.generate(inner, layer, settings)
    else:
        pattern = patterns.get(settings.infill_type)
        if pattern is None:
            raise patterns.PatternError(
                f"infill pattern '{pattern_id(settings.infill_type)}' is not available")
        infill_strokes = patterns.generate_user(pattern, inner, layer, settings)

    # 3. order and emit. Walls first, then ordered infill.  With a seed, each
    #    closed wall's seam is moved to the vertex nearest it.
    if seed is not None:
        walls = [_rotate_loop(w, anchor) for w in walls]
    walls = _order_strokes(walls, anchor, settings.minimize_crossings)
    for w in walls:
        cur = _emit_stroke(lt.moves, w, MoveKind.PERIMETER, cur)

    infill_from = cur if walls else anchor
    infill_strokes = _order_strokes(infill_strokes, infill_from, settings.minimize_crossings)
    for s in infill_strokes:
        cur = _emit_stroke(lt.moves, s, MoveKind.INFILL, cur)

    return lt


def plan_all(layers: List[Layer], settings: PrintSettings) -> List[LayerToolpath]:
    out: List[LayerToolpath] = []
    cur: Optional[Point] = None
    for i, layer in enumerate(layers):
        seed = None
        if settings.rotate_start and layer.regions is not None                 and not layer.regions.is_empty:
            seed = layer_start_corner(layer.regions, i)
        # per-layer pattern/density from the infill sections (if any cover it)
        layer_settings = settings.for_layer(layer.z - layer.height)
        lt = plan_layer(layer, layer_settings, start_pos=cur, seed=seed)
        out.append(lt)
        if lt.moves:
            cur = lt.moves[-1].end
    return out
