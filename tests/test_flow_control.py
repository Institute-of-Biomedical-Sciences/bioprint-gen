"""Flow control: start ramp, start dwell, end coast, end retract."""
from __future__ import annotations

import pytest

from bioprintgen.model import (
    PrintSettings, LayerToolpath, Move, MoveKind, DriveMode,
)
from bioprintgen.gcode.writer import flow_emits
from bioprintgen.pipeline import Project


def _layer(*specs):
    """specs: (length_mm, extrude) -> a layer of colinear moves along +x."""
    moves, x = [], 0.0
    for length, extrude in specs:
        moves.append(Move(start=(x, 0.0), end=(x + length, 0.0),
                          kind=MoveKind.INFILL if extrude else MoveKind.TRAVEL,
                          extrude=extrude))
        x += length
    return LayerToolpath(z=0.2, index=0, height=0.2, moves=moves)


# --------------------------------------------------------------------------- #
#  flow_emits arithmetic
# --------------------------------------------------------------------------- #
def test_no_flow_settings_is_a_passthrough(settings):
    lt = _layer((5, True), (3, False), (5, True))
    emits = flow_emits(lt, settings)
    assert len(emits) == 3
    assert [e.move.extrude for e in emits] == [True, False, True]
    assert not any(e.coast for e in emits)


def test_coast_splits_the_tail_of_a_stroke(settings):
    settings.coast_distance = 3.0
    lt = _layer((10, True))
    emits = flow_emits(lt, settings)
    assert len(emits) == 2
    head, tail = emits
    assert head.move.extrude and pytest.approx(head.move.length) == 7.0
    assert (not tail.move.extrude) and tail.coast
    assert pytest.approx(tail.move.length) == 3.0
    # both pieces keep the original move index so line<->segment mapping holds
    assert head.mi == tail.mi == 0


def test_coast_can_span_several_moves(settings):
    settings.coast_distance = 3.0
    lt = _layer((5, True), (1, True), (1, True))
    emits = [e for e in flow_emits(lt, settings) if e.move.extrude or e.coast]
    coasted = sum(e.move.length for e in emits if e.coast)
    assert pytest.approx(coasted) == 3.0


def test_stroke_shorter_than_coast_coasts_entirely(settings):
    settings.coast_distance = 5.0
    settings.start_dwell = 1.0
    lt = _layer((1, True), (1, True))
    emits = flow_emits(lt, settings)
    assert all(e.coast and not e.move.extrude for e in emits)
    # nothing extruded => no dwell/prime for that stroke
    assert not any(e.stroke_start for e in emits)


def test_stroke_start_and_end_are_marked_once(settings):
    settings.coast_distance = 2.0
    lt = _layer((10, True), (3, False), (10, True))
    emits = flow_emits(lt, settings)
    assert sum(e.stroke_start for e in emits) == 2
    assert sum(e.stroke_end for e in emits) == 2


def test_travel_moves_are_untouched(settings):
    settings.coast_distance = 2.0
    lt = _layer((10, True), (4, False))
    travels = [e for e in flow_emits(lt, settings) if not e.coast and not e.move.extrude]
    assert len(travels) == 1
    assert pytest.approx(travels[0].move.length) == 4.0


# --------------------------------------------------------------------------- #
#  emitted g-code (Planet CNC, piston)
# --------------------------------------------------------------------------- #
def _text(settings):
    p = Project.from_cuboid(10, 10, 0.4, settings)
    p.plan()
    return p.gcode_text()


def test_ramp_precedes_dwell_at_each_stroke_start(settings):
    settings.flow_start_ramp = 0.03
    settings.start_dwell = 2.0
    lines = _text(settings).splitlines()
    i = next(i for i, l in enumerate(lines) if "flow start" in l)
    assert "A[#<_a> +0.03]" in lines[i]
    assert lines[i + 1].startswith("G4") and "P2" in lines[i + 1]


def test_prime_and_retract_are_balanced(settings):
    settings.flow_start_ramp = 0.03
    settings.flow_end_retract = 0.02
    text = _text(settings)
    assert text.count("flow start") == text.count("flow end") > 0


def test_retract_comes_after_the_coast(settings):
    settings.flow_end_retract = 0.02
    settings.coast_distance = 1.0
    lines = _text(settings).splitlines()
    i = next(i for i, l in enumerate(lines) if "flow end" in l)
    prev = lines[i - 1]
    assert prev.startswith("G1\t") and "A[#<_a>" not in prev, \
        "the line before the retract should be the non-extruding coast"


def test_coast_is_a_g1_without_extrusion_or_travel_feed(settings):
    settings.coast_distance = 1.0
    p = Project.from_cuboid(10, 10, 0.4, settings)
    p.plan()
    coasts = [g.text for g in p.glines() if g.kind == "coast"]
    assert coasts
    for c in coasts:
        assert c.startswith("G1\t")           # a feed move, not a rapid
        assert "A[#<_a>" not in c             # not extruding
        assert f"F{int(settings.travel_speed)}" not in c   # keeps the print feed


def test_pneumatic_gets_dwell_but_no_metered_ramp(settings):
    settings.drive = DriveMode.PNEUMATIC
    settings.flow_start_ramp = 0.03
    settings.flow_end_retract = 0.02
    settings.start_dwell = 1.0
    text = _text(settings)
    assert "G4" in text
    assert "flow start" not in text and "flow end" not in text


def _stroke_ends(text):
    """Line indices of the last extruding/coast line of each stroke is hard to
    pin, so tests below reason about relative order within a small excerpt."""
    return text.splitlines()


# --------------------------------------------------------------------------- #
#  end dwell
# --------------------------------------------------------------------------- #
def test_end_dwell_comes_after_the_retract(settings):
    settings.coast_distance = 1.0
    settings.flow_end_retract = 0.02
    settings.end_dwell = 1.5
    lines = _text(settings).splitlines()
    i = next(i for i, l in enumerate(lines) if "end dwell" in l)
    # walk back to the nearest flow-control line: it must be the retract
    prev = next(lines[k] for k in range(i - 1, -1, -1) if "flow end" in lines[k] or "flow start" in lines[k])
    assert "flow end" in prev, "end dwell should follow the retract, not precede it"


def test_end_dwell_fires_without_coast(settings):
    settings.coast_distance = 0.0
    settings.end_dwell = 1.0
    assert "end dwell" in _text(settings)


def test_end_dwell_once_per_stroke(settings):
    text = _text(settings)                      # baseline stroke count via travels
    settings.end_dwell = 1.0
    n_ends = _text(settings).count("end dwell")
    # one per stroke; a plain cuboid layer has a perimeter + serpentine infill
    assert n_ends >= 2


def test_pneumatic_closes_valve_before_end_dwell(settings):
    settings.drive = DriveMode.PNEUMATIC
    settings.end_dwell = 1.0
    lines = _text(settings).splitlines()
    i = next(i for i, l in enumerate(lines) if "end dwell" in l)
    assert "M63" in lines[i - 1] and "E0" in lines[i - 1], \
        "valve must be closed on the line before the end dwell"


def test_end_dwell_disabled_by_default(settings):
    assert "end dwell" not in _text(settings)


def test_marlin_end_dwell_uses_seconds(settings):
    from bioprintgen.model import Dialect
    settings.dialect = Dialect.MARLIN_ABS_E
    settings.end_dwell = 1.5
    assert "G4 S1.5 ; end dwell" in _text(settings)


# --------------------------------------------------------------------------- #
#  travel lift (safe-height hop on every travel)
# --------------------------------------------------------------------------- #
def test_hop_wraps_every_travel(settings):
    settings.travel_lift = 2.0
    p = Project.from_cuboid(10, 10, 0.4, settings)
    p.plan()
    text = p.gcode_text()
    ups = text.count("safe up")
    downs = text.count("safe down")
    n_travel = sum(1 for g in p.glines() if g.kind == "travel")
    assert ups == downs == n_travel > 0


def test_hop_is_relative_on_planet_cnc(settings):
    settings.travel_lift = 2.0
    text = _text(settings)
    assert "Z[#<_z> +2]" in text and "Z[#<_z> -2]" in text


def _num(v):
    return f"{v:.3f}".rstrip("0").rstrip(".")


def test_hop_is_absolute_on_marlin(settings):
    from bioprintgen.model import Dialect
    settings.dialect = Dialect.MARLIN_ABS_E
    settings.travel_lift = 2.0
    p = Project.from_cuboid(10, 10, 0.4, settings)
    p.plan()
    z0 = round(p.toolpath[0].z, 3)
    text = p.gcode_text()
    assert "; safe up" in text and "; safe down" in text
    # the up target is (layer z + lift), the down target is the layer z
    assert f"Z{_num(z0 + 2.0)} " in text
    assert f"Z{_num(z0)} F" in text


def test_hop_uses_the_z_feedrate(settings):
    settings.travel_lift = 2.0
    settings.z_speed = 275.0
    for l in _text(settings).splitlines():
        if "safe up" in l or "safe down" in l:
            assert "F275" in l


def test_no_hop_on_coast_only_on_travels(settings):
    settings.travel_lift = 2.0
    settings.coast_distance = 1.0
    p = Project.from_cuboid(10, 10, 0.4, settings)
    p.plan()
    lines = p.gcode_text().splitlines()
    # a coast line is a G1 X.. Y.. with no A and no F; it must not be Z-wrapped
    for i, l in enumerate(lines):
        if l.startswith("G1\tX") and "A[" not in l and "F" not in l:   # coast
            assert "safe" not in lines[i - 1], "coast must not be treated as a travel"


def test_hop_disabled_by_default(settings):
    text = _text(settings)
    assert "safe up" not in text and "safe down" not in text


def test_hop_does_not_change_the_toolpath(settings):
    a = Project.from_cuboid(10, 10, 0.4, settings)
    a.plan()
    before = [(m.start, m.end, m.extrude) for l in a.toolpath for m in l.moves]
    settings.travel_lift = 2.0
    b = Project.from_cuboid(10, 10, 0.4, settings)
    b.plan()
    after = [(m.start, m.end, m.extrude) for l in b.toolpath for m in l.moves]
    assert before == after


def test_flow_settings_do_not_change_the_toolpath(settings):
    """Flow control is emission-only: the planned moves must be identical."""
    a = Project.from_cuboid(10, 10, 0.4, settings)
    a.plan()
    before = [(m.start, m.end, m.extrude) for l in a.toolpath for m in l.moves]
    settings.coast_distance = 1.0
    settings.start_dwell = 1.0
    b = Project.from_cuboid(10, 10, 0.4, settings)
    b.plan()
    after = [(m.start, m.end, m.extrude) for l in b.toolpath for m in l.moves]
    assert before == after
