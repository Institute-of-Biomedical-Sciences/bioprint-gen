"""Defaults file round-tripping, export formatting, and custom flavours."""
from __future__ import annotations

import json

import pytest

from bioprintgen import settingsio
from bioprintgen.model import (
    PrintSettings, Dialect, DriveMode, InfillType,
    LayerHeightSection, ToolLineRange,
)
from bioprintgen.gcode import flavour as fl
from bioprintgen.pipeline import Project


# --------------------------------------------------------------------------- #
#  default_settings.json
# --------------------------------------------------------------------------- #
def test_settings_round_trip():
    s = PrintSettings()
    s.layer_height = 0.35
    s.dialect = Dialect.MARLIN_ABS_E
    s.drive = DriveMode.PNEUMATIC
    s.infill_type = InfillType.GYROID
    s.extruder2_offset = (-77.3, 0.1)
    s.layer_sections = [LayerHeightSection(0.4, 1.0, 0.5)]
    s.tool_line_ranges = [ToolLineRange(10, 20, 2)]
    back = settingsio.dict_to_settings(settingsio.settings_to_dict(s))
    assert back.layer_height == 0.35
    assert back.dialect is Dialect.MARLIN_ABS_E
    assert back.drive is DriveMode.PNEUMATIC
    assert back.infill_type is InfillType.GYROID
    assert back.extruder2_offset == (-77.3, 0.1)
    assert [(x.z_start, x.z_end, x.height) for x in back.layer_sections] == [(0.4, 1.0, 0.5)]
    assert [(x.start_line, x.end_line, x.extruder) for x in back.tool_line_ranges] == [(10, 20, 2)]


def test_unknown_keys_are_ignored():
    s = settingsio.dict_to_settings({"layer_height": 0.4, "not_a_real_setting": 1})
    assert s.layer_height == 0.4


def test_missing_keys_keep_built_in_defaults():
    default = PrintSettings()
    s = settingsio.dict_to_settings({"layer_height": 0.4})
    assert s.print_speed == default.print_speed


def test_bad_value_falls_back_instead_of_raising():
    default = PrintSettings()
    s = settingsio.dict_to_settings({"dialect": "not-a-dialect"})
    assert s.dialect == default.dialect


def test_shipped_defaults_file_parses():
    loaded = settingsio.load_defaults()
    assert loaded is not None, "default_settings.json should ship with the project"
    s, source, ui = loaded
    assert isinstance(s, PrintSettings)
    assert "kind" in source
    assert ui.get("theme") in ("dark", "light")


def test_missing_defaults_file_is_tolerated(tmp_path):
    assert settingsio.load_defaults(tmp_path / "nope.json") is None


# --------------------------------------------------------------------------- #
#  ui.scale persistence (the one key the app writes back)
# --------------------------------------------------------------------------- #
def test_save_ui_scale_preserves_every_other_key(tmp_path):
    p = tmp_path / "default_settings.json"
    original = {
        "_comment": "mine",
        "ui": {"theme": "light", "expanded_panels": ["Source", "Infill"]},
        "source": {"kind": "cylinder", "diameter": 22.0},
        "print_settings": {"layer_height": 0.33},
    }
    p.write_text(json.dumps(original, indent=2), encoding="utf-8")
    assert settingsio.save_ui_scale(1.4, p) is True
    back = json.loads(p.read_text(encoding="utf-8"))
    assert back["ui"]["scale"] == 1.4
    assert back["ui"]["theme"] == "light"                 # untouched
    assert back["ui"]["expanded_panels"] == ["Source", "Infill"]
    assert back["source"] == {"kind": "cylinder", "diameter": 22.0}
    assert back["print_settings"] == {"layer_height": 0.33}
    assert back["_comment"] == "mine"


def test_save_ui_scale_seeds_a_missing_file(tmp_path):
    p = tmp_path / "default_settings.json"
    assert settingsio.save_ui_scale(1.25, p) is True
    loaded = settingsio.load_defaults(p)
    assert loaded is not None
    assert loaded[2]["scale"] == 1.25
    # seeded into a full, hand-editable document
    assert "print_settings" in json.loads(p.read_text(encoding="utf-8"))


def test_save_ui_scale_never_clobbers_a_malformed_file(tmp_path):
    p = tmp_path / "default_settings.json"
    p.write_text("{ not valid json", encoding="utf-8")
    assert settingsio.save_ui_scale(1.4, p) is False
    assert p.read_text(encoding="utf-8") == "{ not valid json"


def test_load_defaults_reads_ui_scale(tmp_path):
    p = tmp_path / "default_settings.json"
    p.write_text(json.dumps({"ui": {"scale": 1.75}}), encoding="utf-8")
    _s, _src, ui = settingsio.load_defaults(p)
    assert ui["scale"] == 1.75


def test_shipped_defaults_file_has_a_valid_scale():
    """The user may have zoomed (the app writes ui.scale back), so only check
    that the value is present and in range — never that it's the default."""
    loaded = settingsio.load_defaults()
    assert loaded is not None
    scale = loaded[2].get("scale")
    assert scale is not None and 0.7 <= float(scale) <= 2.5


def test_malformed_defaults_file_is_tolerated(tmp_path):
    bad = tmp_path / "default_settings.json"
    bad.write_text("{ not json", encoding="utf-8")
    assert settingsio.load_defaults(bad) is None


# --------------------------------------------------------------------------- #
#  export formatting
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("setting,expected", [
    ("crlf", "\r\n"), ("lf", "\n"), ("CRLF", "\r\n"), ("weird", "\r\n"),
])
def test_line_terminator(setting, expected):
    s = PrintSettings()
    s.gcode_line_ending = setting
    assert s.line_terminator() == expected


def test_export_is_utf8_and_uses_the_chosen_terminator(tmp_path, settings):
    settings.start_gcode = "; flow ≈ 5 µL/s"      # cp1250 cannot encode U+2248
    p = Project.from_cuboid(8, 8, 0.4, settings)
    p.plan()
    out = tmp_path / "out.gcode"
    with open(out, "w", encoding="utf-8", newline=settings.line_terminator()) as f:
        f.write(p.gcode_text())
    raw = out.read_bytes()
    assert "≈".encode("utf-8") in raw
    assert raw.count(b"\r\n") > 0
    assert raw.count(b"\n") == raw.count(b"\r\n"), "no stray bare LFs"


# --------------------------------------------------------------------------- #
#  custom flavours
# --------------------------------------------------------------------------- #
def test_flavour_json_round_trip(tmp_path, monkeypatch):
    monkeypatch.setenv("BIOPRINTGEN_FLAVOURS", str(tmp_path))
    t = fl.FlavourTemplate(name="Unit Test", extrude="G1 X{x} Y{y} E{e}")
    fl.save_flavour(t)
    got = fl.list_flavours()
    assert "Unit Test" in got
    assert got["Unit Test"].extrude == "G1 X{x} Y{y} E{e}"
    fl.delete_flavour("Unit Test")
    assert "Unit Test" not in fl.list_flavours()


def test_fill_leaves_unknown_placeholders_alone():
    assert fl.fill("G1 X{x} Q{nope}", x="1") == ["G1 X1 Q{nope}"]


def test_fill_of_blank_template_emits_nothing():
    assert fl.fill("", x="1") == []


def test_malformed_template_does_not_crash():
    assert fl.fill("G1 X{", x="1") == ["G1 X{"]


def test_custom_flavour_drives_the_writer(settings):
    settings.dialect = Dialect.CUSTOM
    settings.custom_flavour = fl.FlavourTemplate(
        name="T", header="; hi", layer_change="; L{layer}",
        travel="G0 X{x} Y{y}", extrude="G1 X{x} Y{y} E{e}", footer="M2")
    settings.write_settings_header = False
    p = Project.from_cuboid(6, 6, 0.4, settings)
    p.plan()
    lines = p.gcode_text().splitlines()
    assert lines[0] == "; hi"
    assert lines[-1] == "M2"
    assert any(l.startswith("G1 X") and " E" in l for l in lines)
