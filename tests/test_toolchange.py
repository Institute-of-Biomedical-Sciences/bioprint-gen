"""Line-range tool changes: mapping, offsets, and mechanism switching."""
from __future__ import annotations

import pytest

from bioprintgen.model import PrintSettings, ToolLineRange, DriveMode, Dialect
from bioprintgen.gcode import writer as gw
from bioprintgen.pipeline import Project


@pytest.fixture
def tc_settings(settings):
    settings.tool_change_enabled = True
    settings.extruder2_offset = (-77.3, 0.1)
    settings.extruder3_offset = (-153.1, 0.2)
    return settings


def _project(settings):
    p = Project.from_cuboid(10, 10, 0.4, settings)
    p.plan()
    return p


def _mark(p, settings, first, last, extruder=2):
    """Assign clean-baseline move lines [first..last] (by ordinal) to `extruder`."""
    clean = p.glines()
    move_lines = [i + 1 for i, g in enumerate(clean) if g.move is not None]
    settings.tool_line_ranges = [
        ToolLineRange(move_lines[first], move_lines[last], extruder)]
    gw.apply_line_ranges(p.toolpath, clean, settings.tool_line_ranges)
    return clean


# --------------------------------------------------------------------------- #
#  line <-> move mapping
# --------------------------------------------------------------------------- #
def test_move_line_map_round_trip(tc_settings):
    p = _project(tc_settings)
    clean = p.glines()
    m = gw.move_line_map(clean)
    for (layer, move), line in list(m.items())[:20]:
        g = clean[line - 1]
        assert (g.layer, g.move) == (layer, move)


def test_apply_line_ranges_assigns_exactly_the_marked_moves(tc_settings):
    p = _project(tc_settings)
    _mark(p, tc_settings, 3, 7)
    assigned = [(li, mi) for li, lt in enumerate(p.toolpath)
                for mi, mv in enumerate(lt.moves) if mv.extruder == 2]
    assert len(assigned) == 5


def test_apply_line_ranges_is_idempotent(tc_settings):
    p = _project(tc_settings)
    clean = _mark(p, tc_settings, 3, 7)
    first = [m.extruder for l in p.toolpath for m in l.moves]
    gw.apply_line_ranges(p.toolpath, clean, tc_settings.tool_line_ranges)
    assert [m.extruder for l in p.toolpath for m in l.moves] == first


def test_empty_ranges_reset_everything_to_tool_one(tc_settings):
    p = _project(tc_settings)
    clean = _mark(p, tc_settings, 3, 7)
    gw.apply_line_ranges(p.toolpath, clean, [])
    assert all(m.extruder == 1 for l in p.toolpath for m in l.moves)


def test_out_of_range_lines_are_ignored(tc_settings):
    p = _project(tc_settings)
    clean = p.glines()
    gw.apply_line_ranges(p.toolpath, clean, [ToolLineRange(10 ** 6, 10 ** 6 + 5, 2)])
    assert all(m.extruder == 1 for l in p.toolpath for m in l.moves)


# --------------------------------------------------------------------------- #
#  emitted Planet CNC tool change
# --------------------------------------------------------------------------- #
def test_offset_variables_are_declared(tc_settings):
    p = _project(tc_settings)
    text = p.gcode_text()
    assert "#102 = -77.3" in text and "#103 = 0.1" in text
    assert "#104 = -153.1" in text and "#105 = 0.2" in text


def test_offset_frame_is_opened_and_closed(tc_settings):
    p = _project(tc_settings)
    _mark(p, tc_settings, 3, 7)
    text = p.gcode_text()
    assert "tool change: extruder 2" in text
    assert "G92\tX#5\tY#6" in text                       # frame shift
    assert "remove extruder 2 offset" in text            # recalibrate on exit
    assert text.count("tool change: extruder 2") == text.count("remove extruder 2 offset")


def test_piston_axis_switches_for_the_marked_moves(tc_settings):
    p = _project(tc_settings)
    _mark(p, tc_settings, 3, 7)
    text = p.gcode_text()
    assert "B[#<_b>" in text, "extruder 2 should meter on the B axis"
    assert "A[#<_a>" in text, "extruder 1 moves should still meter on A"


def test_pneumatic_valve_switches_for_the_marked_moves(tc_settings):
    tc_settings.drive = DriveMode.PNEUMATIC
    p = _project(tc_settings)
    _mark(p, tc_settings, 3, 7)
    text = p.gcode_text()
    assert "M63 P2" in text and "M63 P1" in text


def test_returns_to_extruder_one_before_the_footer(tc_settings):
    p = _project(tc_settings)
    clean = p.glines()
    move_lines = [i + 1 for i, g in enumerate(clean) if g.move is not None]
    # mark right through to the last move so the file ends on extruder 2
    tc_settings.tool_line_ranges = [ToolLineRange(move_lines[3], move_lines[-1], 2)]
    gw.apply_line_ranges(p.toolpath, clean, tc_settings.tool_line_ranges)
    text = p.gcode_text()
    assert "remove extruder 2 offset" in text
    assert text.rstrip().endswith("%")


def test_disabling_tool_change_suppresses_everything(tc_settings):
    p = _project(tc_settings)
    _mark(p, tc_settings, 3, 7)
    tc_settings.tool_change_enabled = False
    text = p.gcode_text()
    assert "tool change" not in text and "#102" not in text
    assert "B[#<_b>" not in text


def test_marlin_emits_t_commands(tc_settings):
    tc_settings.dialect = Dialect.MARLIN_ABS_E
    p = _project(tc_settings)
    _mark(p, tc_settings, 3, 7)
    text = p.gcode_text()
    assert "T1 ; extruder 2" in text
    assert "G10 L1 P2" in text
