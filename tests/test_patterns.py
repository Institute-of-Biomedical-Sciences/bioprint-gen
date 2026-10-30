"""User infill patterns: equation (level-set) patterns and Python path plugins."""
from __future__ import annotations

import time

import pytest
from shapely.geometry import Point

from bioprintgen import settingsio
from bioprintgen.infill import patterns
from bioprintgen.infill.base import perimeter_strokes
from bioprintgen.model import InfillSection, InfillType, PrintSettings, parse_pattern
from bioprintgen.pipeline import Project

SHIPPED = {"schwarz_p", "schwarz_d", "neovius", "lidinoid", "iwp", "concentric", "honeycomb"}


@pytest.fixture
def user_dir(tmp_path, monkeypatch):
    """An empty patterns folder; the shipped registry is restored afterwards."""
    monkeypatch.setenv("BIOPRINTGEN_PATTERNS", str(tmp_path))
    patterns.reload()
    yield tmp_path
    monkeypatch.delenv("BIOPRINTGEN_PATTERNS")
    patterns.reload()


def _settings(pid, pct=30.0) -> PrintSettings:
    s = PrintSettings()
    s.layer_height = 0.2
    s.line_width = 0.4
    s.perimeters = 1
    s.infill_type = parse_pattern(pid)
    s.infill_mode, s.infill_percent = "percent", pct
    return s


def _coverage(project, s) -> float:
    """Mean fraction of the infill area covered by strands (w * length / area)."""
    fr = []
    for layer, lt in zip(project.layers, project.toolpath):
        inner, _ = perimeter_strokes(layer.regions, s.perimeters, s.line_width)
        length = sum(m.length for m in lt.moves if m.extrude and m.kind.value == "infill")
        fr.append(s.line_width * length / inner.area)
    return sum(fr) / len(fr)


# --------------------------------------------------------------------------- #
#  registry
# --------------------------------------------------------------------------- #
def test_builtins_come_first_and_shipped_patterns_load():
    patterns.reload()
    ids = [p.id for p in patterns.available()]
    assert ids[:3] == ["rectilinear_connected", "rectilinear_separate", "gyroid"]
    assert SHIPPED <= set(ids)
    assert patterns.errors() == {}


def test_templates_folder_is_not_loaded():
    ids = {p.id for p in patterns.available()}
    assert "equation_template" not in ids and "path_template" not in ids


@pytest.mark.parametrize("pid", sorted(SHIPPED))
def test_shipped_pattern_hits_the_requested_density(pid):
    s = _settings(pid, 30.0)
    p = Project.from_cuboid(30, 30, 1.0, s)
    p.plan()
    assert _coverage(p, s) == pytest.approx(0.30, rel=0.12)


@pytest.mark.parametrize("pid", sorted(SHIPPED))
def test_shipped_pattern_stays_inside_the_part(pid):
    s = _settings(pid)
    p = Project.from_cylinder(20, 0.6, s)
    p.plan()
    region = p.layers[0].regions.buffer(1e-6)
    for lt in p.toolpath:
        for m in lt.moves:
            if m.extrude:
                assert region.contains(Point(m.end)), f"{pid} left the part at {m.end}"


def test_equation_density_is_measured_not_assumed():
    k = {pid: patterns.line_density(pid) for pid in ("schwarz_p", "schwarz_d", "lidinoid")}
    assert k["schwarz_p"] < 2.2 < k["schwarz_d"] < k["lidinoid"]


def test_spacing_mode_uses_the_period_field():
    s = _settings("schwarz_p")
    s.infill_mode, s.gyroid_period = "spacing", 5.0
    assert s.is_levelset() and s.effective_gyroid_period() == 5.0
    s.infill_type = parse_pattern("honeycomb")
    assert not s.is_levelset()


# --------------------------------------------------------------------------- #
#  equations are parsed, never executed
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("bad", [
    "__import__('os').system('echo hi')", "x.real", "[x, y]", "(lambda: 1)()",
    "open('f')", "y if x else z", "x < y", "sin(x=1)", "globals()", "x; y", "",
])
def test_unsafe_or_invalid_equations_are_rejected(bad):
    with pytest.raises(patterns.PatternError):
        patterns.compile_equation(bad)


def test_caret_means_power_and_constants_work():
    import numpy as np
    fn = patterns.compile_equation("x^2 + tau - 2*pi")
    assert float(fn(np.array([[3.0]]), np.array([[0.0]]), 0.0)[0, 0]) == pytest.approx(9.0)


def test_huge_powers_fail_fast():
    t = time.time()
    with pytest.raises((patterns.PatternError, OverflowError)):
        patterns.compile_equation("9**9**9")
    assert time.time() - t < 1.0


def test_level_without_curves_is_reported(user_dir):
    (user_dir / "flat.json").write_text('{"equation": "cos(x)", "level": 5}')
    errors = patterns.reload()
    assert "flat.json" in errors and "no curves" in errors["flat.json"]


# --------------------------------------------------------------------------- #
#  user files
# --------------------------------------------------------------------------- #
def test_user_equation_pattern(user_dir):
    (user_dir / "waves.json").write_text(
        '{"name": "Waves", "equation": "sin(x) + cos(y) + 0*z", "level": 0}')
    assert patterns.reload() == {}
    p = patterns.get("waves")
    assert p.kind == "levelset" and p.name == "Waves"
    s = _settings("waves")
    pr = Project.from_cuboid(20, 20, 0.4, s)
    pr.plan()
    assert any(m.extrude and m.kind.value == "infill" for m in pr.toolpath[0].moves)


def test_plugin_strokes_are_clipped_to_the_region(user_dir):
    (user_dir / "cross.py").write_text(
        "PATTERN = {'name': 'Big cross'}\n"
        "def generate(region, layer, settings, spacing):\n"
        "    return [[(-500, 0), (500, 0)], [(0, -500), (0, 500)], [(1, 1)], 'junk']\n")
    assert patterns.reload() == {}
    s = _settings("cross")
    pr = Project.from_cylinder(10, 0.2, s)
    pr.plan()
    infill = [m for m in pr.toolpath[0].moves if m.extrude and m.kind.value == "infill"]
    assert len(infill) == 2                       # degenerate + junk strokes dropped
    for m in infill:
        assert max(abs(c) for c in m.start + m.end) < 5.0


def test_plugin_crash_names_the_pattern_and_layer(user_dir):
    (user_dir / "boom.py").write_text(
        "def generate(region, layer, settings, spacing):\n    raise ValueError('nope')\n")
    patterns.reload()
    s = _settings("boom")
    pr = Project.from_cuboid(10, 10, 0.4, s)
    with pytest.raises(patterns.PatternError, match="boom.*layer 0.*nope"):
        pr.plan()


def test_broken_files_are_listed_not_fatal(user_dir):
    (user_dir / "nogen.py").write_text("X = 1\n")
    (user_dir / "syntax.py").write_text("def (\n")
    (user_dir / "notjson.json").write_text("{nope")
    (user_dir / "gyroid.json").write_text('{"equation": "cos(x)"}')    # id clash
    errors = patterns.reload()
    assert set(errors) == {"nogen.py", "syntax.py", "notjson.json", "gyroid.json"}
    assert [p.id for p in patterns.available()] == \
        ["rectilinear_connected", "rectilinear_separate", "gyroid"]


def test_unknown_pattern_fails_validation():
    s = PrintSettings()
    s.infill_type = parse_pattern("does_not_exist")
    assert any("does_not_exist" in m for m in s.validate())
    s = PrintSettings()
    s.infill_sections = [InfillSection(0, 1, parse_pattern("nope"), 0)]
    assert any("section 1" in m and "nope" in m for m in s.validate())


# --------------------------------------------------------------------------- #
#  persistence / import
# --------------------------------------------------------------------------- #
def test_ids_round_trip_through_the_defaults_file():
    s = _settings("schwarz_d")
    s.infill_sections = [InfillSection(0.2, 1.0, parse_pattern("honeycomb"), 50),
                         InfillSection(1.0, 2.0, InfillType.GYROID, 0)]
    back = settingsio.dict_to_settings(settingsio.settings_to_dict(s))
    assert back.infill_type == "schwarz_d"
    assert [x.infill_type for x in back.infill_sections] == ["honeycomb", InfillType.GYROID]
    assert isinstance(back.infill_sections[1].infill_type, InfillType)


def test_section_with_a_user_pattern_prints_it():
    s = PrintSettings()
    s.layer_height = 0.2
    s.infill_sections = [InfillSection(0.0, 0.4, parse_pattern("concentric"), 40)]
    assert s.for_layer(0.2).infill_type == "concentric"
    assert s.for_layer(0.6).infill_type == InfillType.RECTILINEAR_CONNECTED


def test_export_embeds_the_equation_and_import_rebuilds_without_the_file(user_dir):
    (user_dir / "mine.json").write_text(
        '{"name": "Mine", "equation": "cos(x) + cos(y) + cos(z)", "level": 0.3}')
    patterns.reload()
    s = _settings("mine")
    s.source = {"kind": "cuboid", "width": 12.0, "depth": 12.0, "height": 0.6,
                "diameter": 12.0, "stl_path": None}
    pr = Project.from_cuboid(12, 12, 0.6, s)
    pr.plan()
    text = pr.gcode_text()
    assert "; pattern mine: cos(x) + cos(y) + cos(z) = 0.3  (Mine)" in text

    (user_dir / "mine.json").unlink()                 # another machine, no file
    patterns.reload()
    assert patterns.get("mine") is None
    back, source, _f, complete = settingsio.parse_gcode_settings(text)
    assert complete and patterns.get("mine") is not None
    assert patterns.get("mine").level == 0.3
    rebuilt = Project.from_cuboid(12, 12, 0.6, back)
    rebuilt.plan()
    motion = lambda t: [l for l in t.splitlines() if l.strip() and not l.startswith(";")]
    assert motion(rebuilt.gcode_text()) == motion(text)
