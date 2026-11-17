"""Combine the main shape with the user's extra components, layer by layer.

Slicing commutes with boolean operations, so instead of 3D mesh booleans each
component is reduced to its 2D cross-section per layer and the areas are
combined there.  Overlaps are resolved by priority: the component higher in
`PrintSettings.components` owns a shared area, the main shape is lowest.  The
result is ordinary `Layer` objects whose `regions` is the whole part and whose
`parts` say who owns what; the planner turns parts into walls + infill.
"""
from __future__ import annotations

import math
from collections import OrderedDict
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np

from shapely import affinity
from shapely.geometry import MultiPolygon, Polygon, box
from shapely.ops import unary_union

from ..model import Component, Layer, LayerPart, PrintSettings, build_z_levels

CYLINDER_SEGMENTS = 128     # same discretisation as the main cylinder
_MESH_CACHE: "OrderedDict[tuple, object]" = OrderedDict()
_MESH_CACHE_SIZE = 8


def _stl_mesh(c: Component):
    """The component's mesh, scaled and turned (X, then Y, then Z), with its
    bounding-box centre at the XY origin and its bottom at z = 0.  Cached on
    the file (path + modification time) and the transform, so regenerating
    after unrelated changes does not reload or re-transform it."""
    from . import stlslicer
    import trimesh
    path = Path(c.stl_path)
    try:
        mtime = path.stat().st_mtime
    except OSError:
        raise ValueError(f"STL file not found: {c.stl_path}") from None
    key = (str(path.resolve()), mtime, float(c.scale), float(c.rot_x),
           float(c.rot_y), float(c.rotation))
    mesh = _MESH_CACHE.get(key)
    if mesh is not None:
        _MESH_CACHE.move_to_end(key)
        return mesh
    mesh = stlslicer.load_stl(str(path), drop_to_bed=False, center_xy=False).mesh.copy()
    mesh.apply_scale(c.scale / 100.0)
    for angle, axis in ((c.rot_x, [1, 0, 0]), (c.rot_y, [0, 1, 0]), (c.rotation, [0, 0, 1])):
        if angle:
            mesh.apply_transform(trimesh.transformations.rotation_matrix(
                math.radians(angle), axis))
    (x0, y0, z0), (x1, y1, _z1) = mesh.bounds
    mesh.apply_translation([-(x0 + x1) / 2.0, -(y0 + y1) / 2.0, -z0])
    _MESH_CACHE[key] = mesh
    while len(_MESH_CACHE) > _MESH_CACHE_SIZE:
        _MESH_CACHE.popitem(last=False)
    return mesh


def stl_extents(c: Component) -> Tuple[float, float, float]:
    """Size (X, Y, Z) in mm of an STL component after scale and rotation."""
    e = _stl_mesh(c).extents
    return float(e[0]), float(e[1]), float(e[2])


def component_top(c: Component) -> float:
    if c.shape == "stl":
        return c.z + stl_extents(c)[2]
    return c.z_top()


def component_polygon(c: Component, z_mid: Optional[float] = None) -> Polygon:
    """The component's cross-section in the print frame - at height `z_mid`
    for a horizontal cylinder, whose slice is a slot that narrows towards its
    top and bottom (empty outside its span), and for an STL (its mesh section)."""
    if c.shape == "stl":
        from .stlslicer import _section_to_polygon
        mesh = _stl_mesh(c)
        local = (z_mid if z_mid is not None else c.z) - c.z
        if not (0.0 < local < float(mesh.extents[2])):
            return Polygon()
        geom = _section_to_polygon(mesh, local)
        if geom is None:
            return Polygon()
        return _solid(affinity.translate(geom.buffer(0), c.x, c.y))
    if c.horizontal:
        r = c.size_x / 2.0
        dz = (z_mid if z_mid is not None else c.z + r) - (c.z + r)
        if abs(dz) >= r:
            return Polygon()
        half = math.sqrt(r * r - dz * dz)
        poly = box(c.x - c.size_y / 2.0, c.y - half, c.x + c.size_y / 2.0, c.y + half)
        return affinity.rotate(poly, c.rotation, origin=(c.x, c.y)) if c.rotation else poly
    if c.shape == "cylinder":
        r = c.size_x / 2.0
        return Polygon([(c.x + r * math.cos(2 * math.pi * k / CYLINDER_SEGMENTS),
                         c.y + r * math.sin(2 * math.pi * k / CYLINDER_SEGMENTS))
                        for k in range(CYLINDER_SEGMENTS)])
    poly = box(c.x - c.size_x / 2.0, c.y - c.size_y / 2.0,
               c.x + c.size_x / 2.0, c.y + c.size_y / 2.0)
    if c.rotation:
        poly = affinity.rotate(poly, c.rotation, origin=(c.x, c.y))
    return poly


def _solid(geom):
    """Only the real area of a boolean result: drops the slivers, lines and
    points that overlapping / touching shapes leave behind."""
    if geom is None or geom.is_empty:
        return Polygon()
    polys = [g for g in getattr(geom, "geoms", [geom])
             if isinstance(g, Polygon) and g.area > 1e-6]
    if not polys:
        return Polygon()
    return polys[0] if len(polys) == 1 else MultiPolygon(polys)


def _present(c: Component, z_top: float, h: float) -> bool:
    """A layer belongs to a component when its mid-height lies in the
    component's Z span (so a 2 mm tall component on 0.2 mm layers gets 10)."""
    mid = z_top - h / 2.0
    return c.z - 1e-9 <= mid <= component_top(c) + 1e-9


def compose_layers(main_layers: List[Layer], settings: PrintSettings) -> List[Layer]:
    """Main-shape layers -> composed layers.  Without enabled components the
    input is returned untouched (so a plain part plans exactly as before).

    Priority runs down the list: each entry claims what is left of its shape.
    An *add* owns that area; a *subtract* claims it as void, so it is removed
    from everything below it (and the main shape) while entries above it keep
    theirs."""
    comps = [(i, c) for i, c in enumerate(settings.components) if c.enabled]
    if not comps:
        return main_layers
    if any(getattr(L, "parts", None) for L in main_layers):
        return main_layers                       # already composed

    main_top = main_layers[-1].z if main_layers else 0.0
    try:
        adds_top = [component_top(c) for _i, c in comps if not c.subtract]
        fixed = {i: component_polygon(c) for i, c in comps
                 if not c.horizontal and c.shape != "stl"}
    except ValueError as e:
        raise ValueError(f"Component: {e}") from None
    top = max([main_top] + adds_top)             # a void never raises the part
    # the z sequence is the same as the main shape's (same rule, longer run)
    levels = build_z_levels(top, settings)
    main_at = {round(L.z, 6): L.regions for L in main_layers}

    out: List[Layer] = []
    for z, h in levels:
        z = round(z, 6)
        mid = z - h / 2.0
        parts: List[LayerPart] = []
        taken = None
        for i, c in comps:                       # highest priority first
            if not _present(c, z, h):
                continue
            try:
                shape = fixed[i] if i in fixed else component_polygon(c, mid)
            except Exception as e:  # noqa: BLE001 - a mesh that won't section
                raise ValueError(f"Component {i + 1}: {e}") from None
            if shape.is_empty:
                continue
            owned = shape if taken is None else _solid(shape.difference(taken))
            taken = shape if taken is None else taken.union(shape)
            parts.append(LayerPart(i, owned, shape, void=c.subtract))
        main = main_at.get(z)
        if main is not None and not main.is_empty:
            owned = main if taken is None else _solid(main.difference(taken))
            parts.append(LayerPart(None, owned, main))
        # a void's region becomes what it really removes: its claim, where
        # there is material below it in the list
        for k, part in enumerate(parts):
            if part.void and not part.region.is_empty:
                below = [q.shape for q in parts[k + 1:] if not q.void]
                part.region = _solid(part.region.intersection(unary_union(below))) \
                    if below else Polygon()
        # a fully covered component keeps its (empty) part, so the preview can
        # still draw its outline and the app can say it has no effect
        solid = [p.region for p in parts if not p.void and not p.region.is_empty]
        if not solid:
            continue                             # nothing at this height
        region = unary_union(solid)
        out.append(Layer(z=z, index=len(out), regions=region, height=h, parts=parts))
    return out


def main_bounds(main_layers: List[Layer]):
    """(minx, miny, maxx, maxy) of the main shape, or None."""
    b = [L.regions.bounds for L in main_layers
         if L.regions is not None and not L.regions.is_empty]
    if not b:
        return None
    return (min(v[0] for v in b), min(v[1] for v in b),
            max(v[2] for v in b), max(v[3] for v in b))


def hidden_components(layers: List[Layer]) -> List[int]:
    """Indices of components that have no effect on any layer: an add that is
    completely covered by entries higher in the list, or a subtract that
    removes nothing (outside the part, or covered)."""
    seen, visible = set(), set()
    for L in layers:
        for p in L.parts or []:
            if p.component is None:
                continue
            seen.add(p.component)
            if not p.region.is_empty:
                visible.add(p.component)
    return sorted(seen - visible)
