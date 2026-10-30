"""The shipped flavour templates must reproduce the built-in writers exactly.

flavours/templates/planet_cnc.json and marlin.json are the starting points
users copy to build their own flavours, so they are held to byte-for-byte
equality with PlanetCNCWriter / MarlinWriter across every feature that changes
the emitted code.  The settings block is the one expected difference (it names
the flavour), so most cases compare with it switched off and one case checks
everything around it.
"""
from __future__ import annotations

import dataclasses

import pytest

from bioprintgen.gcode import flavour as fl
from bioprintgen.gcode.writer import render
from bioprintgen.model import (
    Dialect, DriveMode, InfillType, LayerHeightSection, PrintSettings,
)
from bioprintgen.pipeline import Project

TEMPLATES = fl.templates_dir()


def _template(file_name):
    return fl.load_flavour(TEMPLATES / file_name)


def _texts(s: PrintSettings, template_file: str, builtin: Dialect, shape=None):
    """(built-in text, template text) for the same toolpath."""
    s.dialect = builtin
    s.custom_flavour = None
    p = Project.from_cuboid(10, 8, 0.8, s) if shape is None else shape(s)
    p.plan()
    layers = p.toolpath
    if s.tool_change_enabled:
        _cycle_extruders(layers)
    ref = "\n".join(g.text for g in render(layers, s))
    t = dataclasses.replace(s, dialect=Dialect.CUSTOM, custom_flavour=_template(template_file))
    got = "\n".join(g.text for g in render(layers, t))
    return ref, got


def _assert_same(ref: str, got: str):
    if ref != got:
        r, g = ref.splitlines(), got.splitlines()
        for i, (a, b) in enumerate(zip(r, g)):
            if a != b:
                pytest.fail(f"first difference at line {i + 1}:\n"
                            f"  built-in: {a!r}\n  template: {b!r}")
        pytest.fail(f"length differs: built-in {len(r)} lines, template {len(g)}")


def _base(**kw) -> PrintSettings:
    s = PrintSettings()
    s.layer_height = 0.2
    s.write_settings_header = False
    for k, v in kw.items():
        setattr(s, k, v)
    return s


def _tool_change(s: PrintSettings) -> PrintSettings:
    s.tool_change_enabled = True
    s.extruder2_offset = (12.5, -3.25)
    s.extruder3_offset = (-7.0, 4.0)
    return s


def _cycle_extruders(layers):
    """Hand every extruder a turn (1 -> 2 -> 3 -> 2 -> ...), switching mid-layer
    and across layers, and finish on a non-reference extruder so the final
    return to extruder 1 is exercised too."""
    k = 0
    for lt in layers:
        for m in lt.moves:
            m.extruder = (1, 2, 3, 2)[(k // 7) % 4]
            k += 1
    layers[-1].moves[-1].extruder = 3


CASES = {
    "defaults": dict(),
    "no_zero_xy": dict(zero_xy_at_start=False),
    "ramp_and_flow_pot": dict(ramp=0.5, flow_control=True),
    "no_ramp": dict(ramp=0.0),
    "extruder_2": dict(extruder_index=2),
    "extruder_3_ramp": dict(extruder_index=3, ramp=0.3),
    "stroke_ramp_retract": dict(flow_start_ramp=0.05, flow_end_retract=0.07),
    "dwells": dict(start_dwell=0.25, end_dwell=0.4),
    "coast": dict(coast_distance=1.5),
    "travel_lift": dict(travel_lift=1.2),
    "everything": dict(ramp=0.4, flow_control=True, flow_start_ramp=0.05,
                       flow_end_retract=0.06, start_dwell=0.2, end_dwell=0.3,
                       coast_distance=0.8, travel_lift=0.9),
    "gyroid": dict(infill_type=InfillType.GYROID),
    "start_end_gcode": dict(start_gcode="M3 S100\n; hello", end_gcode="M5"),
}

DRIVES = [DriveMode.PISTON, DriveMode.PNEUMATIC]


@pytest.mark.parametrize("drive", DRIVES, ids=lambda d: d.value)
@pytest.mark.parametrize("case", list(CASES))
def test_planet_cnc_template_matches_builtin(case, drive):
    s = _base(drive=drive, **CASES[case])
    _assert_same(*_texts(s, "planet_cnc.json", Dialect.PLANET_CNC))


@pytest.mark.parametrize("case", list(CASES))
def test_marlin_template_matches_builtin(case):
    s = _base(**CASES[case])
    _assert_same(*_texts(s, "marlin.json", Dialect.MARLIN_ABS_E))


@pytest.mark.parametrize("drive", DRIVES, ids=lambda d: d.value)
@pytest.mark.parametrize("extra", [dict(), dict(start_dwell=0.2, end_dwell=0.3,
                                                travel_lift=1.0, coast_distance=1.0)],
                         ids=["plain", "flow"])
def test_tool_change_matches_builtin(drive, extra):
    for template_file, dialect in (("planet_cnc.json", Dialect.PLANET_CNC),
                                   ("marlin.json", Dialect.MARLIN_ABS_E)):
        s = _tool_change(_base(drive=drive, **extra))
        ref, got = _texts(s, template_file, dialect)
        # test setup: every transition kind is really in there
        if dialect == Dialect.PLANET_CNC:
            assert ref.count("tool change: extruder 3") > 1
            assert ref.count("remove extruder 2 offset") > 1
        else:
            assert "T2 ; extruder 3" in ref and "T0 ; back to extruder 1" in ref
        _assert_same(ref, got)


def test_variable_layer_heights_match():
    for template_file, dialect in (("planet_cnc.json", Dialect.PLANET_CNC),
                                   ("marlin.json", Dialect.MARLIN_ABS_E)):
        s = _base(layer_sections=[LayerHeightSection(0.0, 0.4, 0.1)])
        _assert_same(*_texts(s, template_file, dialect))


def test_cylinder_matches():
    shape = lambda s: Project.from_cylinder(9, 0.6, s)
    for template_file, dialect in (("planet_cnc.json", Dialect.PLANET_CNC),
                                   ("marlin.json", Dialect.MARLIN_ABS_E)):
        _assert_same(*_texts(_base(), template_file, dialect, shape=shape))


@pytest.mark.parametrize("template_file,dialect", [("planet_cnc.json", Dialect.PLANET_CNC),
                                                   ("marlin.json", Dialect.MARLIN_ABS_E)])
def test_only_the_settings_block_differs(template_file, dialect):
    s = _base(write_settings_header=True)
    ref, got = _texts(s, template_file, dialect)
    marker = "; ===== BioprintGEN settings ====="
    assert marker in ref and marker in got
    ref_head, ref_tail = ref.split(marker)
    got_head, got_tail = got.split(marker)
    _assert_same(ref_head, got_head)
    end = "; ==============================="
    assert ref_tail.split(end)[1] == got_tail.split(end)[1]      # e.g. Planet's closing %
    assert "custom_flavour = " + _template(template_file).name in got_tail


# --------------------------------------------------------------------------- #
#  the template language itself
# --------------------------------------------------------------------------- #
def test_conditional_block_inline_and_negated():
    c = {"a": True, "b": False}
    assert fl.fill("G1{?a: X1}{?b: Y2}{?!b: Z3}", c) == ["G1 X1 Z3"]


def test_all_of_conditions():
    assert fl.fill("{?a&b:yes}{?a&!b:no}", {"a": True, "b": False}) == ["no"]


def test_skipped_block_drops_its_line_but_real_blanks_stay():
    assert fl.fill("A\n{?x:B}\n\nC", {"x": False}) == ["A", "", "C"]


def test_multiline_block_and_nesting():
    tpl = "{?a:L1\nL2{?b: tail}}\nEND"
    assert fl.fill(tpl, {"a": True, "b": True}) == ["L1", "L2 tail", "END"]
    assert fl.fill(tpl, {"a": False, "b": True}) == ["END"]


def test_placeholders_inside_blocks_are_filled():
    assert fl.fill("G1{?s:\tF{f}}", {"s": True}, f="500") == ["G1\tF500"]


def test_blank_placeholder_gives_one_empty_line():
    assert fl.fill("{blank}") == [""]


def test_unknown_condition_is_false_and_unbalanced_block_is_kept():
    assert fl.fill("A{?nope:B}") == ["A"]
    assert fl.fill("A {?x:B") == ["A {?x:B"]


# --------------------------------------------------------------------------- #
#  storage
# --------------------------------------------------------------------------- #
def test_shipped_templates_are_listed():
    names = set(fl.list_templates())
    assert {"Planet CNC (template)", "Marlin (template)"} <= names


def test_templates_are_not_listed_as_saved_flavours(tmp_path, monkeypatch):
    monkeypatch.setenv("BIOPRINTGEN_FLAVOURS", str(tmp_path))
    assert fl.list_flavours() == {}


def test_multiline_templates_round_trip_through_json(tmp_path, monkeypatch):
    monkeypatch.setenv("BIOPRINTGEN_FLAVOURS", str(tmp_path))
    t = _template("planet_cnc.json")
    t.name = "Copy"
    fl.save_flavour(t)
    back = fl.list_flavours()["Copy"]
    assert back == t
    assert isinstance(fl.FlavourTemplate.to_dict(t)["setup"], list)


def test_old_flat_flavour_files_still_load():
    old = {"name": "Old", "header": "G21\nG90", "travel": "G0 X{x} Y{y}",
           "tool_change": "T{tool}", "dwell": "G4 P{sec}"}
    t = fl.FlavourTemplate.from_dict(old)
    assert t.header == "G21\nG90" and t.tool_enter == "" and t.coast == ""


def test_default_store_is_the_app_folder(monkeypatch):
    monkeypatch.delenv("BIOPRINTGEN_FLAVOURS", raising=False)
    assert fl.flavours_dir() == fl.APP_DIR / "flavours"
    assert fl.templates_dir().parent == fl.flavours_dir()
