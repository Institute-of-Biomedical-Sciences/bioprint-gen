"""Infill defined as a percentage, the rotating layer start, and walls-only parts."""
from __future__ import annotations

import pytest
from shapely.geometry import LineString, Polygon

from bioprintgen.model import (
    PrintSettings, InfillType, Layer, GYROID_LINE_DENSITY,
)
from bioprintgen.infill import gyroid, rectilinear
from bioprintgen.pipeline import Project


# --------------------------------------------------------------------------- #
#  infill %
# --------------------------------------------------------------------------- #
def test_spacing_mode_uses_the_given_values():
    s = PrintSettings()
    s.strand_spacing, s.gyroid_period = 1.7, 5.5
    assert s.effective_spacing() == 1.7
    assert s.effective_gyroid_period() == 5.5


@pytest.mark.parametrize("pct", [10, 25, 50, 100])
def test_percent_mode_spacing(pct):
    s = PrintSettings()
    s.line_width, s.infill_mode, s.infill_percent = 0.4, "percent", pct
    assert s.effective_spacing() == pytest.approx(0.4 / (pct / 100))
    assert s.effective_gyroid_period() == pytest.approx(
        GYROID_LINE_DENSITY * 0.4 / (pct / 100))


def test_hundred_percent_means_touching_lines():
    s = PrintSettings()
    s.line_width, s.infill_mode, s.infill_percent = 0.41, "percent", 100
    assert s.effective_spacing() == pytest.approx(0.41)


def _coverage(strokes, area, line_width):
    return sum(LineString(st).length for st in strokes) * line_width / area


@pytest.mark.parametrize("pct", [20, 40])
def test_percent_actually_deposits_that_density(pct):
    """Measured on the real generators: covered fraction ~= the requested %,
    for both rectilinear and gyroid (the latter via the measured constant)."""
    side = 60.0
    reg = Polygon([(0, 0), (side, 0), (side, side), (0, side)])
    s = PrintSettings()
    s.line_width, s.infill_mode, s.infill_percent = 0.4, "percent", pct

    rect = rectilinear.generate(reg, Layer(z=0.2, index=0, regions=reg, height=0.2),
                                s, connected=False)
    assert _coverage(rect, side * side, 0.4) == pytest.approx(pct / 100, rel=0.05)

    period = s.effective_gyroid_period()
    covs = []
    for k in range(12):                       # average over one period in z
        lay = Layer(z=period * k / 12, index=k, regions=reg, height=0.2)
        covs.append(_coverage(gyroid.generate(reg, lay, s), side * side, 0.4))
    assert sum(covs) / len(covs) == pytest.approx(pct / 100, rel=0.05)


@pytest.mark.parametrize("pct", [0, -5, 150])
def test_invalid_percent_is_rejected(pct):
    s = PrintSettings()
    s.infill_mode, s.infill_percent = "percent", pct
    assert any("Infill %" in m for m in s.validate())


def test_spacing_checks_are_skipped_in_percent_mode():
    s = PrintSettings()
    s.infill_mode, s.infill_percent, s.strand_spacing = "percent", 40, 0.0
    assert s.validate() == []


# --------------------------------------------------------------------------- #
#  rotating layer start
# --------------------------------------------------------------------------- #
def _seams(settings, h=1.0):
    p = Project.from_cuboid(10, 10, h, settings)
    p.plan()
    return p, [next(m for m in lt.moves if m.extrude).start for lt in p.toolpath]


def test_start_cycles_through_the_four_corners():
    s = PrintSettings()
    s.rotate_start = True
    _, seams = _seams(s)
    xs = [round(x) for x, _ in seams]
    ys = [round(y) for _, y in seams]
    # bottom-left, bottom-right, top-right, top-left, bottom-left
    assert list(zip(xs, ys)) == [(0, 0), (10, 0), (10, 10), (0, 10), (0, 0)]


def test_start_stays_put_when_disabled():
    s = PrintSettings()
    s.rotate_start = False
    _, seams = _seams(s)
    assert len(set((round(x, 3), round(y, 3)) for x, y in seams)) == 1


def test_rotation_does_not_invent_a_travel():
    """Each layer's first travel must start where the nozzle actually is."""
    s = PrintSettings()
    s.rotate_start = True
    p, _ = _seams(s)
    for prev, cur in zip(p.toolpath, p.toolpath[1:]):
        assert cur.moves[0].start == prev.moves[-1].end


def test_rotation_also_moves_the_infill_start_without_walls():
    s = PrintSettings()
    s.rotate_start, s.perimeters = True, 0
    _, seams = _seams(s)
    assert len(set((round(x), round(y)) for x, y in seams[:4])) == 4


def test_rotation_keeps_the_same_material():
    """Only the start point moves: total extruded length is unchanged."""
    a = PrintSettings(); a.rotate_start = False
    b = PrintSettings(); b.rotate_start = True
    pa = Project.from_cuboid(10, 10, 1.0, a); pa.plan()
    pb = Project.from_cuboid(10, 10, 1.0, b); pb.plan()
    assert pa.stats()["extrude_mm"] == pytest.approx(pb.stats()["extrude_mm"], rel=1e-6)


# --------------------------------------------------------------------------- #
#  walls only
# --------------------------------------------------------------------------- #
def test_huge_perimeter_count_fills_the_part_with_walls_only():
    s = PrintSettings()
    s.perimeters = 999
    p = Project.from_cuboid(10, 10, 0.4, s)
    p.plan()
    kinds = {m.kind.value for lt in p.toolpath for m in lt.moves if m.extrude}
    assert kinds == {"perimeter"}
    assert p.gcode_text()
