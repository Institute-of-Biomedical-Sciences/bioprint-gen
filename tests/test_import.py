"""Import g-code: settings + source survive an export and rebuild identically."""
from __future__ import annotations

from bioprintgen import settingsio
from bioprintgen.model import (
    PrintSettings, LayerHeightSection, ToolLineRange, DriveMode,
)
from bioprintgen.pipeline import Project


def _motion(text):
    return [l.strip() for l in text.replace("\r\n", "\n").split("\n")
            if l.strip() and not l.strip().startswith(";")]


def _rich_settings():
    s = PrintSettings()
    s.layer_height = 0.3
    s.infill_mode, s.infill_percent = "percent", 35.0
    s.layer_sections = [LayerHeightSection(0.6, 1.2, 0.15)]
    s.tool_change_enabled = True
    s.extruder2_offset = (-77.3, 0.1)
    s.start_dwell, s.coast_distance, s.travel_lift = 1.0, 0.8, 1.5
    s.start_gcode = "M104 S25\nG4 P1"
    s.end_gcode = "M104 S0"
    s.source = {"kind": "cylinder", "width": 10.0, "depth": 10.0,
                "height": 1.8, "diameter": 14.0, "stl_path": None}
    return s


def _rebuild(settings, source):
    if source["kind"] == "cylinder":
        p = Project.from_cylinder(source["diameter"], source["height"], settings)
    else:
        p = Project.from_cuboid(source["width"], source["depth"], source["height"], settings)
    p.plan()
    return p


def test_settings_block_carries_a_machine_readable_line():
    s = _rich_settings()
    text = _rebuild(s, s.source).gcode_text()
    assert settingsio.GCODE_JSON_MARKER in text


def test_round_trip_restores_settings_and_source():
    s = _rich_settings()
    text = _rebuild(s, s.source).gcode_text()
    back, source, _flavour, complete = settingsio.parse_gcode_settings(text)
    assert complete
    assert source == s.source
    assert back.infill_mode == "percent" and back.infill_percent == 35.0
    assert back.start_gcode == "M104 S25\nG4 P1"
    assert [(x.z_start, x.z_end, x.height) for x in back.layer_sections] == [(0.6, 1.2, 0.15)]
    assert back.extruder2_offset == (-77.3, 0.1)


def test_rebuild_from_import_reproduces_the_file_exactly():
    """The core promise of Restore & regenerate."""
    s = _rich_settings()
    original = _rebuild(s, s.source).gcode_text()
    back, source, _f, _c = settingsio.parse_gcode_settings(original)
    back.source = source
    rebuilt = _rebuild(back, source).gcode_text()
    assert _motion(rebuilt) == _motion(original)


def test_tool_ranges_survive_the_round_trip():
    s = _rich_settings()
    p = _rebuild(s, s.source)
    clean = p.glines()
    lines = [i + 1 for i, g in enumerate(clean) if g.move is not None]
    s.tool_line_ranges = [ToolLineRange(lines[3], lines[9], 2)]
    p = _rebuild(s, s.source)
    from bioprintgen.gcode import writer as gw
    gw.apply_line_ranges(p.toolpath, p.glines(), s.tool_line_ranges)
    text = p.gcode_text()
    back, *_ = settingsio.parse_gcode_settings(text)
    assert [(r.start_line, r.end_line, r.extruder) for r in back.tool_line_ranges] == \
        [(lines[3], lines[9], 2)]


def test_legacy_human_readable_block_still_restores_print_settings():
    s = _rich_settings()
    text = _rebuild(s, s.source).gcode_text()
    legacy = "\n".join(l for l in text.splitlines()
                       if settingsio.GCODE_JSON_MARKER not in l)
    back, source, _f, complete = settingsio.parse_gcode_settings(legacy)
    assert not complete and source == {}
    assert back.layer_height == 0.3
    assert back.infill_percent == 35.0
    assert back.extruder2_offset == (-77.3, 0.1)


def test_file_without_settings_is_not_importable():
    assert settingsio.parse_gcode_settings("G0 X1 Y1\nG1 X2 Y2 E1\n") is None


def test_disabling_the_block_disables_import():
    s = _rich_settings()
    s.write_settings_header = False
    text = _rebuild(s, s.source).gcode_text()
    assert settingsio.parse_gcode_settings(text) is None


def test_pneumatic_ink_flow_is_bar_times_ten():
    s = PrintSettings()
    s.drive, s.valve_value = DriveMode.PNEUMATIC, 1.5
    p = Project.from_cuboid(8, 8, 0.4, s)
    p.plan()
    assert "M63 P1 Q10000 E15" in p.gcode_text()
