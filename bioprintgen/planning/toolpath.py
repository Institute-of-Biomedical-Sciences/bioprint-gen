"""Toolpath planning.

Turns a sliced Layer into an ordered list of Moves:

  1. optional perimeter walls
  2. infill strokes (rectilinear connected / separate / gyroid / user patterns)
  3. ordering that keeps single-layer crossings to a minimum

A layer composed of several components (see geometry.components) is planned
per owner: the main body (main shape + "merge" components) gets the main walls
along the part's outline and one infill zone per owner; a component with walls
of its own is planned as a separate region, and its walls are the only ones
between it and the body.  Moves are grouped by extruder.

True minimum-crossing routing is NP-hard, so we use a greedy nearest-endpoint
ordering.  For the parallel-strand patterns this reproduces the natural
sweep order (adjacent strands are always nearest), so travels never cross laid
material; for gyroid it minimises travel length, which in practice minimises
crossings between disjoint contour curves.
"""
from __future__ import annotations

import math
from typing import List, Optional, Tuple

from shapely.geometry import LineString, MultiLineString
from shapely.ops import linemerge, unary_union

from ..model import (
    Layer, LayerToolpath, Move, MoveKind, PrintSettings, InfillType, pattern_id,
    WALLS_MERGE,
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
    infill_strokes = infill_strokes_for(inner, layer, settings)

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


def infill_strokes_for(inner, layer: Layer, settings: PrintSettings) -> List[Stroke]:
    if inner is None or inner.is_empty:
        return []
    if settings.infill_type == InfillType.RECTILINEAR_CONNECTED:
        return rectilinear.generate(inner, layer, settings, connected=True)
    if settings.infill_type == InfillType.RECTILINEAR_SEPARATE:
        return rectilinear.generate(inner, layer, settings, connected=False)
    if settings.infill_type == InfillType.GYROID:
        return gyroid.generate(inner, layer, settings)
    pattern = patterns.get(settings.infill_type)
    if pattern is None:
        raise patterns.PatternError(
            f"infill pattern '{pattern_id(settings.infill_type)}' is not available")
    return patterns.generate_user(pattern, inner, layer, settings)


# --------------------------------------------------------------------------- #
#  Composed layers (components)
# --------------------------------------------------------------------------- #
def _zone_tasks(inner, owners, layer, settings, split: bool):
    """Infill tasks for the owners sharing one walled region.  When several
    owners share it, each zone stops half a strand short of the shared
    boundary, so strands from both sides end one strand width apart."""
    tasks = []
    if inner is None or inner.is_empty:
        return tasks
    w = settings.line_width
    for region, comp in owners:
        zone = inner.intersection(region.buffer(-w / 2.0, join_style=2)) if split else inner
        if zone.is_empty:
            continue
        zs = settings.for_component(comp)
        ext = comp.extruder if comp is not None else 1
        tasks.append((ext, 1, MoveKind.INFILL, infill_strokes_for(zone, layer, zs)))
    return tasks


def _walls_outside(walls: List[Stroke], cut, min_len: float) -> List[Stroke]:
    """The parts of wall loops that lie outside `cut` (merged back into as
    few polylines as possible; scraps shorter than `min_len` dropped)."""
    out: List[Stroke] = []
    for wall in walls:
        if len(wall) < 2:
            continue
        rest = LineString(wall).difference(cut)
        if rest.is_empty:
            continue
        if isinstance(rest, MultiLineString):
            rest = linemerge(rest)
        pieces = list(rest.geoms) if hasattr(rest, "geoms") else [rest]
        for g in pieces:
            if isinstance(g, LineString) and g.length >= min_len:
                out.append(list(g.coords))
    return out


def plan_composed_layer(layer: Layer, settings: PrintSettings,
                        start_pos: Optional[Point] = None,
                        seed: Optional[Point] = None,
                        start_extruder: int = 1) -> LayerToolpath:
    lt = LayerToolpath(z=layer.z, index=layer.index, height=layer.height)
    cur: Point = start_pos if start_pos is not None else (0.0, 0.0)
    anchor: Point = seed if seed is not None else cur
    comps = settings.components
    w = settings.line_width

    body, own = [], []
    for part in layer.parts:
        comp = comps[part.component] if part.component is not None else None
        if comp is not None:            # outline even when fully covered
            ext = 0 if part.void else comp.extruder
            for poly in getattr(part.shape, "geoms", [part.shape]):
                if poly.is_empty or not hasattr(poly, "exterior"):
                    continue
                lt.outlines.append((list(poly.exterior.coords), ext))
                for hole in poly.interiors:
                    lt.outlines.append((list(hole.coords), ext))
        if part.void or part.region is None or part.region.is_empty:
            continue                    # a void's edges are walled by its neighbours
        (body if comp is None or int(comp.walls) <= WALLS_MERGE else own).append(
            (part.region, comp))

    # tasks: (extruder, 0 = walls / 1 = infill, kind, strokes)
    tasks = []
    if body:
        body_region = unary_union([r for r, _ in body])
        if not own:
            inner, walls = perimeter_strokes(body_region, settings.perimeters, w)
        else:
            # main walls follow the outline of the whole part, but not along a
            # component with walls of its own (its walls are the separation);
            # body infill runs up to half a strand from that shared edge
            own_region = unary_union([r for r, _ in own])
            whole = unary_union([body_region, own_region])
            inner, walls = perimeter_strokes(whole, settings.perimeters, w)
            walls = _walls_outside(walls, own_region.buffer(w / 2.0, join_style=2), w)
            inner = inner.intersection(body_region.buffer(-w / 2.0, join_style=2))
        tasks.append((1, 0, MoveKind.PERIMETER, walls))
        tasks += _zone_tasks(inner, body, layer, settings, split=len(body) > 1)
    for region, comp in own:
        inner, walls = perimeter_strokes(region, int(comp.walls), w)
        tasks.append((comp.extruder, 0, MoveKind.PERIMETER, walls))
        tasks += _zone_tasks(inner, [(region, comp)], layer, settings, split=False)

    # one visit per extruder (the one already loaded first), walls before infill
    order = sorted({t[0] for t in tasks}, key=lambda e: (e != start_extruder, e))
    first = True
    for ext in order:
        for stage in (0, 1):
            strokes = [s for t in tasks if t[0] == ext and t[1] == stage for s in t[3]]
            if not strokes:
                continue
            kind = MoveKind.PERIMETER if stage == 0 else MoveKind.INFILL
            if stage == 0 and seed is not None:
                strokes = [_rotate_loop(st, anchor) for st in strokes]
            strokes = _order_strokes(strokes, anchor if first else cur,
                                     settings.minimize_crossings)
            first = False
            n0 = len(lt.moves)
            for st in strokes:
                cur = _emit_stroke(lt.moves, st, kind, cur)
            for m in lt.moves[n0:]:
                m.extruder = m.base_extruder = ext
    return lt


def plan_all(layers: List[Layer], settings: PrintSettings) -> List[LayerToolpath]:
    out: List[LayerToolpath] = []
    cur: Optional[Point] = None
    ext = 1
    for i, layer in enumerate(layers):
        seed = None
        if settings.rotate_start and layer.regions is not None \
                and not layer.regions.is_empty:
            seed = layer_start_corner(layer.regions, i)
        # per-layer pattern/density from the infill sections (if any cover it)
        layer_settings = settings.for_layer(layer.z - layer.height)
        if getattr(layer, "parts", None):
            lt = plan_composed_layer(layer, layer_settings, start_pos=cur, seed=seed,
                                     start_extruder=ext)
        else:
            lt = plan_layer(layer, layer_settings, start_pos=cur, seed=seed)
        out.append(lt)
        if lt.moves:
            cur = lt.moves[-1].end
            ext = lt.moves[-1].base_extruder
    return out
