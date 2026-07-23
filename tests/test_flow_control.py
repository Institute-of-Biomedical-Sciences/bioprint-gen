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
