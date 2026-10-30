"""Z-range infill sections: a band of layers with its own pattern / density."""
from __future__ import annotations

import pytest

from bioprintgen import settingsio
from bioprintgen.model import (
    PrintSettings, InfillSection, InfillType, GYROID_LINE_DENSITY,
)
from bioprintgen.planning import toolpath as planner
from bioprintgen.pipeline import Project


def _project(s, h=1.4):
    p = Project.from_cuboid(15, 15, h, s)
    p.plan()
    return p


def _pattern_per_layer(p, s):
    return [s.for_layer(lt.z - lt.height).infill_type for lt in p.toolpath]


def test_no_sections_leaves_settings_untouched():
    s = PrintSettings()
    assert s.for_layer(0.4) is s


def test_band_uses_the_layer_bottom_like_height_sections():
    """[0.4, 1.0] covers the layers whose material lies in 0.4..1.0."""
    s = PrintSettings()
    s.layer_height = 0.2
    s.infill_sections = [InfillSection(0.4, 1.0, InfillType.GYROID, 0)]
    p = _project(s)
    tops = [round(lt.z, 3) for lt in p.toolpath]
    pats = _pattern_per_layer(p, s)
    gyroid_tops = [z for z, t in zip(tops, pats) if t == InfillType.GYROID]
    assert gyroid_tops == [0.6, 0.8, 1.0]
    assert pats[0] == InfillType.RECTILINEAR_CONNECTED
    assert pats[-1] == InfillType.RECTILINEAR_CONNECTED


def test_first_matching_section_wins():
    s = PrintSettings()
    s.infill_sections = [InfillSection(0.0, 2.0, InfillType.GYROID, 0),
                         InfillSection(0.0, 2.0, InfillType.RECTILINEAR_SEPARATE, 0)]
    assert s.for_layer(0.5).infill_type == InfillType.GYROID


def test_zero_percent_keeps_the_main_density_across_patterns():
    """Main = rectilinear at 1.0 mm spacing with a 0.41 nozzle (41 %); a gyroid
    band at 0 % must use the gyroid period that gives the same 41 %."""
    s = PrintSettings()
    s.line_width, s.strand_spacing = 0.41, 1.0
    s.infill_sections = [InfillSection(0.0, 1.0, InfillType.GYROID, 0)]
    band = s.for_layer(0.2)
    assert band.infill_percent == pytest.approx(41.0)
    assert band.effective_gyroid_period() == pytest.approx(
        GYROID_LINE_DENSITY * 0.41 / 0.41)


def test_explicit_percent_is_used():
    s = PrintSettings()
    s.line_width = 0.4
    s.infill_sections = [InfillSection(0.0, 1.0, InfillType.RECTILINEAR_SEPARATE, 80)]
    band = s.for_layer(0.2)
    assert band.infill_type == InfillType.RECTILINEAR_SEPARATE
    assert band.effective_spacing() == pytest.approx(0.5)


def test_main_density_follows_percent_mode_too():
    s = PrintSettings()
    s.infill_mode, s.infill_percent = "percent", 25
    s.infill_sections = [InfillSection(0.0, 1.0, InfillType.GYROID, 0)]
    assert s.for_layer(0.2).infill_percent == pytest.approx(25)


def test_band_really_prints_the_section_pattern():
    """The planner must use the band's settings, not the main ones."""
    s = PrintSettings()
    s.layer_height = 0.2
    s.infill_sections = [InfillSection(0.4, 1.0, InfillType.GYROID, 0)]
    p = _project(s)
    band_layer = next(lt for lt in p.toolpath if round(lt.z, 3) == 0.6)
    gyroid_only = PrintSettings()
    gyroid_only.layer_height = 0.2
    gyroid_only.infill_type = InfillType.GYROID
    gyroid_only.infill_mode, gyroid_only.infill_percent = "percent", 41.0
    ref = Project.from_cuboid(15, 15, 1.4, gyroid_only)
    ref.layers = [L for L in ref.layers if round(L.z, 3) == 0.6]
    expected = planner.plan_layer(ref.layers[0], gyroid_only)
    def infill_len(lt):
        return sum(m.length for m in lt.moves if m.extrude and m.kind.value == "infill")
    assert infill_len(band_layer) == pytest.approx(infill_len(expected), rel=1e-6)


def test_layers_and_walls_are_unaffected():
    a = PrintSettings()
    b = PrintSettings()
    b.infill_sections = [InfillSection(0.0, 5.0, InfillType.GYROID, 0)]
    pa, pb = _project(a), _project(b)
    assert [lt.z for lt in pa.toolpath] == [lt.z for lt in pb.toolpath]
    walls = lambda p: [round(sum(m.length for m in lt.moves
                                 if m.kind.value == "perimeter"), 6) for lt in p.toolpath]
    assert walls(pa) == walls(pb)


@pytest.mark.parametrize("pct", [-1, 101])
def test_out_of_range_percent_is_rejected(pct):
    s = PrintSettings()
    s.infill_sections = [InfillSection(0.0, 1.0, InfillType.GYROID, pct)]
    assert any("Infill section 1" in m for m in s.validate())


def test_zero_percent_is_valid():
    s = PrintSettings()
    s.infill_sections = [InfillSection(0.0, 1.0, InfillType.GYROID, 0)]
    assert s.validate() == []


# --------------------------------------------------------------------------- #
#  persistence and import
# --------------------------------------------------------------------------- #
def _sections(s):
    return [(x.z_start, x.z_end, x.infill_type, x.percent) for x in s.infill_sections]


def test_defaults_file_round_trip():
    s = PrintSettings()
    s.infill_sections = [InfillSection(0.4, 1.0, InfillType.GYROID, 0),
                         InfillSection(1.0, 2.0, InfillType.RECTILINEAR_SEPARATE, 60)]
    back = settingsio.dict_to_settings(settingsio.settings_to_dict(s))
    assert _sections(back) == _sections(s)


def test_export_import_round_trip_and_identical_rebuild():
    s = PrintSettings()
    s.layer_height = 0.2
    s.infill_sections = [InfillSection(0.4, 1.0, InfillType.GYROID, 0)]
    s.source = {"kind": "cuboid", "width": 15.0, "depth": 15.0, "height": 1.4,
                "diameter": 12.0, "stl_path": None}
    text = _project(s).gcode_text()
    back, source, _f, complete = settingsio.parse_gcode_settings(text)
    assert complete and _sections(back) == _sections(s)
    rebuilt = Project.from_cuboid(source["width"], source["depth"], source["height"], back)
    rebuilt.plan()
    motion = lambda t: [l for l in t.splitlines() if l.strip() and not l.startswith(";")]
    assert motion(rebuilt.gcode_text()) == motion(text)


def test_legacy_human_readable_block_restores_sections():
    s = PrintSettings()
    s.infill_sections = [InfillSection(0.4, 1.0, InfillType.GYROID, 35.0)]
    text = _project(s).gcode_text()
    legacy = "\n".join(l for l in text.splitlines()
                       if settingsio.GCODE_JSON_MARKER not in l)
    back, _src, _f, complete = settingsio.parse_gcode_settings(legacy)
    assert not complete
    assert _sections(back) == [(0.4, 1.0, InfillType.GYROID, 35.0)]
