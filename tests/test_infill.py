"""Infill correctness, above all: connected rectilinear must never extrude
across a hole.  This is the regression that motivated the connector check."""
from __future__ import annotations

import pytest
from shapely.geometry import Point, Polygon

from bioprintgen.model import PrintSettings, InfillType, Layer
from bioprintgen.geometry import stlslicer
from bioprintgen.planning import toolpath as planner
from bioprintgen.infill.base import as_polygons


def _ring_layer(outer_r=10.0, inner_r=4.0, index=0):
    """An annulus: the classic case where connected infill used to bridge the bore."""
    import math
    outer = [(outer_r * math.cos(t), outer_r * math.sin(t))
             for t in [i * 2 * math.pi / 128 for i in range(128)]]
    inner = [(inner_r * math.cos(t), inner_r * math.sin(t))
             for t in [i * 2 * math.pi / 128 for i in range(128)]]
    return Layer(z=0.2, index=index, regions=Polygon(outer, [inner]), height=0.2)


def _two_lobes_layer(gap=6.0, index=0):
    """Two disjoint squares.  Any extruded segment joining them crosses empty
    space, so this catches a chaining bug that an annulus can hide (a ring is a
    *connected* region, so a chain can walk around the bore without bridging)."""
    from shapely.geometry import MultiPolygon
    a = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
    b = Polygon([(10 + gap, 0), (20 + gap, 0), (20 + gap, 10), (10 + gap, 10)])
    return Layer(z=0.2, index=index, regions=MultiPolygon([a, b]), height=0.2)


def _hole_crossings(layer, settings, tol=0.3):
    """Count extruded segments whose midpoint lies outside the solid region."""
    lt = planner.plan_layer(layer, settings)
    region = layer.regions.buffer(tol)
    bad = 0
    for m in lt.moves:
        if not m.extrude:
            continue
        mid = Point((m.start[0] + m.end[0]) / 2, (m.start[1] + m.end[1]) / 2)
        if not region.contains(mid):
            bad += 1
    return bad, lt


@pytest.mark.parametrize("infill", [
    InfillType.RECTILINEAR_CONNECTED,
    InfillType.RECTILINEAR_SEPARATE,
    InfillType.GYROID,
])
def test_no_extrusion_across_a_bore(settings, infill):
    """No pattern may lay material where the hole is."""
    settings.infill_type = infill
    bad, lt = _hole_crossings(_ring_layer(), settings)
    assert bad == 0, f"{infill.value} extruded {bad} segment(s) across the bore"
    assert lt.moves, "layer produced no moves at all"


def test_connected_still_connects_on_a_solid_layer(settings):
    """The hole fix must not fragment a plain solid layer into separate bars."""
    settings.infill_type = InfillType.RECTILINEAR_CONNECTED
    solid = Layer(z=0.2, index=0, regions=Polygon(
        [(0, 0), (20, 0), (20, 20), (0, 20)]), height=0.2)
    lt = planner.plan_layer(solid, settings)
    polys = lt.polylines()
    # perimeter + one continuous serpentine is the expectation; allow a little slack
    assert len(polys) <= 3, f"solid layer fragmented into {len(polys)} polylines"


def test_connected_breaks_into_more_pieces_when_a_hole_is_present(settings):
    """Sanity: the ring *should* need more polylines than the solid square."""
    settings.infill_type = InfillType.RECTILINEAR_CONNECTED
    solid = Layer(z=0.2, index=0, regions=Polygon(
        [(-10, -10), (10, -10), (10, 10), (-10, 10)]), height=0.2)
    n_solid = len(planner.plan_layer(solid, settings).polylines())
    n_ring = len(planner.plan_layer(_ring_layer(), settings).polylines())
    assert n_ring > n_solid


@pytest.mark.parametrize("infill", [
    InfillType.RECTILINEAR_CONNECTED,
    InfillType.RECTILINEAR_SEPARATE,
])
def test_no_extrusion_between_disjoint_islands(settings, infill):
    """Material must never be laid in the gap between two separate islands."""
    settings.infill_type = infill
    bad, lt = _hole_crossings(_two_lobes_layer(), settings)
    assert bad == 0, f"{infill.value} extruded {bad} segment(s) across the gap"
    assert lt.moves


def test_real_stl_has_no_hole_crossings(settings, stl_path):
    """End-to-end regression on the mesh that exposed the bug."""
    settings.infill_type = InfillType.RECTILINEAR_CONNECTED
    settings.layer_height = 1.0            # coarse: keep the test quick
    model = stlslicer.load_stl(str(stl_path))
    layers = stlslicer.slice_model(model, settings)
    holed = [L for L in layers
             if any(len(p.interiors) > 0 for p in as_polygons(L.regions))]
    assert holed, "expected this mesh to have layers with interior holes"
    total = sum(_hole_crossings(L, settings)[0] for L in holed)
    assert total == 0, f"{total} extruded segment(s) crossed a hole"
