"""Degenerate inputs must fail fast and clearly — never hang, never traceback.

These values can't come from the GUI's spin boxes, but `default_settings.json`
is hand-edited and the pipeline is usable from scripts, so both routes matter.
"""
from __future__ import annotations

import pytest

from bioprintgen.model import (
    PrintSettings, LayerHeightSection, InfillType, build_z_levels, MAX_LAYERS,
)
from bioprintgen.infill.base import parallel_line_set, perimeter_strokes
from bioprintgen.pipeline import Project
from shapely.geometry import Polygon


# --------------------------------------------------------------------------- #
#  validate()
# --------------------------------------------------------------------------- #
def test_default_settings_are_valid():
    assert PrintSettings().validate() == []


@pytest.mark.parametrize("field,value", [
    ("layer_height", 0.0),
    ("layer_height", -0.2),
    ("line_width", 0.0),
    ("strand_spacing", 0.0),
    ("strand_spacing", -1.0),
    ("print_speed", 0.0),
    ("travel_speed", 0.0),
    ("z_speed", 0.0),
    ("filament_area", 0.0),
    ("coast_distance", -1.0),
    ("start_dwell", -1.0),
    ("perimeters", -1),
])
def test_bad_values_are_reported(field, value):
    s = PrintSettings()
    setattr(s, field, value)
    problems = s.validate()
    assert problems, f"{field}={value} should have been flagged"
    assert all(isinstance(m, str) and m.endswith(".") for m in problems)


def test_bad_section_height_is_reported():
    s = PrintSettings()
    s.layer_sections = [LayerHeightSection(0.0, 1.0, 0.0)]
    assert any("section 1" in m for m in s.validate())


def test_gyroid_period_only_checked_for_gyroid():
    s = PrintSettings()
    s.gyroid_period = 0.0
    assert s.validate() == []                 # irrelevant for rectilinear
    s.infill_type = InfillType.GYROID
    assert any("Gyroid" in m for m in s.validate())


# --------------------------------------------------------------------------- #
#  hard guards: these used to hang or raise something opaque
# --------------------------------------------------------------------------- #
def test_zero_layer_height_raises_instead_of_hanging():
    s = PrintSettings()
    s.layer_height = 0.0
    with pytest.raises(ValueError, match="Layer height"):
        build_z_levels(10.0, s)


def test_negative_layer_height_raises():
    s = PrintSettings()
    s.layer_height = -0.5
    with pytest.raises(ValueError, match="Layer height"):
        build_z_levels(10.0, s)


def test_layer_count_is_capped():
    """A tiny height on a tall part must not exhaust memory."""
    s = PrintSettings()
    s.layer_height = 1e-6
    levels = build_z_levels(1000.0, s)
    assert len(levels) <= MAX_LAYERS


def test_malformed_section_falls_back_to_the_default_height():
    s = PrintSettings()
    s.layer_height = 0.2
    s.layer_sections = [LayerHeightSection(0.0, 5.0, 0.0)]
    levels = build_z_levels(1.0, s)
    assert len(levels) == 5


def test_zero_spacing_raises_clearly():
    region = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
    with pytest.raises(ValueError, match="Strand spacing"):
        parallel_line_set(region, 0.0, 0.0)


def test_float_perimeter_count_is_tolerated():
    """A hand-edited JSON can supply 2.0 where an int is expected."""
    region = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
    inner, walls = perimeter_strokes(region, 2.0, 0.4)
    assert walls


# --------------------------------------------------------------------------- #
#  the writer refuses to emit physically dangerous g-code
# --------------------------------------------------------------------------- #
def _planned(**kw):
    """Plan with valid settings, then corrupt them before emitting."""
    s = PrintSettings()
    p = Project.from_cuboid(10, 10, 0.4, s)
    p.plan()
    for k, v in kw.items():
        setattr(p.settings, k, v)
    return p


@pytest.mark.parametrize("field,value", [
    ("print_speed", 0.0),     # F0 stalls the head mid-print
    ("travel_speed", 0.0),
    ("z_speed", 0.0),
    ("print_speed", -100.0),
    ("filament_area", 0.0),
])
def test_writer_refuses_invalid_output_settings(field, value):
    p = _planned(**{field: value})
    with pytest.raises(ValueError, match="invalid settings"):
        p.gcode_text()


def test_refusal_message_names_the_problem():
    p = _planned(print_speed=0.0)
    with pytest.raises(ValueError) as e:
        p.gcode_text()
    assert "Print speed" in str(e.value)


def test_valid_settings_still_emit():
    p = _planned()
    assert p.gcode_text().startswith("%")


def test_f0_never_reaches_the_gcode():
    """The concrete hazard this guard exists for."""
    p = _planned(print_speed=0.0)
    with pytest.raises(ValueError):
        text = p.gcode_text()
        assert "F0" not in text      # unreachable; documents the intent


# --------------------------------------------------------------------------- #
#  end to end: awkward but legal geometry should still produce something sane
# --------------------------------------------------------------------------- #
def test_perimeters_larger_than_the_part_still_generates():
    s = PrintSettings()
    s.perimeters = 50
    p = Project.from_cuboid(5, 5, 0.4, s)
    p.plan()
    p.gcode_text()          # must not raise; infill may legitimately be empty


def test_line_width_larger_than_the_part_still_generates():
    s = PrintSettings()
    s.line_width = 100.0
    p = Project.from_cuboid(5, 5, 0.4, s)
    p.plan()
    p.gcode_text()


def test_part_thinner_than_one_layer_still_generates():
    s = PrintSettings()
    s.layer_height = 0.2
    p = Project.from_cuboid(10, 10, 0.05, s)
    p.plan()
    assert p.gcode_text()


def test_spacing_larger_than_the_part_still_generates():
    s = PrintSettings()
    s.strand_spacing = 500.0
    p = Project.from_cuboid(5, 5, 0.4, s)
    p.plan()
    p.gcode_text()
