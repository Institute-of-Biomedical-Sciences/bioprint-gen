"""Which settings are shown for a given selection.

Settings that don't apply are hidden (field and caption together).  This is the
Qt-dependent module in the suite; it runs headless via the offscreen platform
and skips cleanly if Qt cannot start at all.
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6", reason="PySide6 not installed")

from PySide6.QtWidgets import QApplication, QFormLayout  # noqa: E402


@pytest.fixture(scope="module")
def app():
    inst = QApplication.instance() or QApplication([])
    yield inst


@pytest.fixture
def panel(app):
    from bioprintgen.gui import theme
    from bioprintgen.gui.controls import ParameterPanel
    theme.set_theme("dark")
    return ParameterPanel()


def _label_of(widget):
    lay = widget.parentWidget().layout()
    if isinstance(lay, QFormLayout):
        return lay.labelForField(widget)
    return None


def assert_row(widget, shown: bool, what: str):
    assert widget.isHidden() is (not shown), f"{what}: field should be shown={shown}"
    label = _label_of(widget)
    if label is not None:
        assert label.isHidden() is (not shown), \
            f"{what}: caption should follow its field (shown={shown})"


# --------------------------------------------------------------------------- #
#  Panel structure
# --------------------------------------------------------------------------- #
def test_panel_order(panel):
    assert list(panel.sections) == ["Printer", "Design", "Layers", "Extrusion",
                                    "Printing process", "Well plate", "Advanced options"]


def test_only_design_is_expanded_by_default(panel):
    assert panel.expanded_panels() == ["Design"]


def test_old_panel_names_fall_back_to_design(panel):
    panel.set_expanded_panels(["Source"])          # name from an older defaults file
    assert panel.expanded_panels() == ["Design"]


def test_removed_settings_are_still_honoured(panel):
    """Minimise-crossings and filament area left the panel but must survive a
    load -> build round trip (e.g. from default_settings.json)."""
    from bioprintgen.model import PrintSettings
    s = PrintSettings()
    s.minimize_crossings = False
    s.filament_area = 3.5
    panel.apply_settings(s)
    back = panel.build_settings()
    assert back.minimize_crossings is False
    assert back.filament_area == 3.5


def test_perimeter_cap_allows_walls_only(panel):
    panel.perimeters.setValue(500)
    assert panel.build_settings().perimeters == 500


# --------------------------------------------------------------------------- #
#  Design: only the dimensions the shape actually uses
# --------------------------------------------------------------------------- #
def test_cuboid_shows_width_and_depth(panel):
    panel.shape.setCurrentIndex(0)
    assert_row(panel.width, True, "cuboid width")
    assert_row(panel.depth, True, "cuboid depth")
    assert_row(panel.diameter, False, "cuboid diameter")
    assert_row(panel.height, True, "cuboid height")
    assert panel.stl_btn.isHidden()


def test_cylinder_shows_diameter(panel):
    panel.shape.setCurrentIndex(1)
    assert_row(panel.width, False, "cylinder width")
    assert_row(panel.depth, False, "cylinder depth")
    assert_row(panel.diameter, True, "cylinder diameter")
    assert_row(panel.height, True, "cylinder height")


def test_stl_shows_only_the_file_picker(panel):
    panel.shape.setCurrentIndex(2)
    for w, name in ((panel.width, "width"), (panel.depth, "depth"),
                    (panel.diameter, "diameter"), (panel.height, "height")):
        assert_row(w, False, f"stl {name}")
    assert not panel.stl_btn.isHidden()


# --------------------------------------------------------------------------- #
#  Layers / infill
# --------------------------------------------------------------------------- #
def test_rectilinear_spacing_mode(panel):
    panel.infill.setCurrentIndex(0)
    panel.infill_mode.setCurrentIndex(0)
    assert_row(panel.spacing, True, "rect spacing")
    assert_row(panel.gyroid_period, False, "rect period")
    assert_row(panel.infill_pct, False, "rect %")
    assert_row(panel.infill_angle, True, "rect base angle")


def test_gyroid_spacing_mode_uses_period(panel):
    panel.infill.setCurrentIndex(2)
    panel.infill_mode.setCurrentIndex(0)
    assert_row(panel.gyroid_period, True, "gyroid period")
    assert_row(panel.spacing, False, "gyroid spacing")
    assert_row(panel.infill_angle, False, "gyroid base angle")
    assert_row(panel.layer_rot, False, "gyroid layer rotation")


def test_percent_mode_replaces_spacing_and_period(panel):
    panel.infill_mode.setCurrentIndex(1)
    for idx in (0, 2):
        panel.infill.setCurrentIndex(idx)
        assert_row(panel.infill_pct, True, "% field")
        assert_row(panel.spacing, False, "spacing in % mode")
        assert_row(panel.gyroid_period, False, "period in % mode")
        assert not panel.infill_info.isHidden()


def test_percent_mode_shows_the_derived_value(panel):
    panel.line_width.setValue(0.4)
    panel.infill_mode.setCurrentIndex(1)
    panel.infill_pct.setValue(50.0)
    panel.infill.setCurrentIndex(0)
    assert "0.80 mm strand spacing" in panel.infill_info.text()
    panel.infill.setCurrentIndex(2)
    assert "gyroid period" in panel.infill_info.text()


def test_percent_mode_reaches_the_settings(panel):
    panel.infill_mode.setCurrentIndex(1)
    panel.infill_pct.setValue(25.0)
    s = panel.build_settings()
    assert s.infill_mode == "percent" and s.infill_percent == 25.0


# --------------------------------------------------------------------------- #
#  Printer / Extrusion
# --------------------------------------------------------------------------- #
def test_piston_shows_metered_settings(panel):
    panel.dialect.setCurrentIndex(0)     # Planet CNC
    panel.drive.setCurrentIndex(0)       # piston
    assert_row(panel.ext10, True, "piston ink flow")
    assert_row(panel.valve, False, "piston valve")
    for w, name in ((panel.ramp, "ramp/retract"), (panel.flow_start_ramp, "start ramp"),
                    (panel.flow_end_retract, "end retract")):
        assert_row(w, True, f"piston {name}")
    assert not panel.flow.isHidden()


def test_pneumatic_hides_ramp_and_retract(panel):
    panel.dialect.setCurrentIndex(0)
    panel.drive.setCurrentIndex(1)       # pneumatic
    assert_row(panel.ext10, False, "pneumatic piston flow")
    assert_row(panel.valve, True, "pneumatic ink flow")
    for w, name in ((panel.ramp, "ramp/retract"), (panel.flow_start_ramp, "start ramp"),
                    (panel.flow_end_retract, "end retract")):
        assert_row(w, False, f"pneumatic {name}")
    assert panel.flow.isHidden()


def test_ink_flow_units_follow_the_drive(panel):
    assert "mm/10mm" in panel.ext10.suffix()
    assert "bar" in panel.valve.suffix()


def test_marlin_hides_planet_cnc_only_settings(panel):
    panel.dialect.setCurrentIndex(1)     # Marlin
    for w, name in ((panel.drive, "drive"), (panel.extruder, "extruder"),
                    (panel.ramp, "ramp"), (panel.ext10, "piston flow"),
                    (panel.valve, "valve")):
        assert_row(w, False, f"marlin {name}")


# --------------------------------------------------------------------------- #
#  Printing process: tool change
# --------------------------------------------------------------------------- #
def test_tool_change_details_follow_the_checkbox(panel):
    panel.tool_change.setChecked(False)
    assert_row(panel.ext2x, False, "offset with tool change off")
    assert panel.tool_ranges.isHidden() and panel._sel_row.isHidden()
    panel.tool_change.setChecked(True)
    assert_row(panel.ext2x, True, "offset with tool change on")
    assert not panel.tool_ranges.isHidden() and not panel._sel_row.isHidden()


def test_infill_sections_table_has_a_pattern_dropdown(panel):
    from PySide6.QtWidgets import QComboBox
    from bioprintgen.model import InfillType
    panel.infill_sections._add_row((0.4, 1.0, 2, 0.0))
    cell = panel.infill_sections.table.cellWidget(0, 2)
    assert isinstance(cell, QComboBox) and cell.currentText() == "Gyroid"
    panel.infill_sections.set_current_cell(2, 1)          # -> separate bars
    sec = panel.build_settings().infill_sections[0]
    assert sec.infill_type == InfillType.RECTILINEAR_SEPARATE
    assert (sec.z_start, sec.z_end, sec.percent) == (0.4, 1.0, 0.0)


def test_hidden_fields_still_report_values(panel):
    """Hiding is cosmetic: build_settings still reads every control, so
    switching shapes can never silently lose a value you typed."""
    panel.shape.setCurrentIndex(1)          # diameter shown, width hidden
    panel.width.setValue(42.0)
    assert panel.source_spec().width == 42.0
    assert panel.build_settings().source["width"] == 42.0


# --------------------------------------------------------------------------- #
#  UI scale (surrounding chrome only)
# --------------------------------------------------------------------------- #
def test_px_scales_with_the_factor(app):
    from bioprintgen.gui import theme
    theme.set_scale(1.0)
    assert theme.px(12) == 12
    theme.set_scale(2.0)
    assert theme.px(12) == 24
    theme.set_scale(1.0)


def test_px_never_returns_zero_for_positive_bases(app):
    from bioprintgen.gui import theme
    theme.set_scale(theme.SCALE_MIN)
    assert theme.px(1) >= 1
    theme.set_scale(1.0)


def test_scale_is_clamped(app):
    from bioprintgen.gui import theme
    assert theme.set_scale(99.0) == theme.SCALE_MAX
    assert theme.set_scale(0.01) == theme.SCALE_MIN
    assert theme.set_scale("nonsense") == 1.0
    theme.set_scale(1.0)


def test_qss_font_size_tracks_the_scale(app):
    from bioprintgen.gui import theme
    theme.set_scale(1.0)
    assert "font-size: 12px" in theme.build_qss()
    theme.set_scale(2.0)
    assert "font-size: 24px" in theme.build_qss()
    theme.set_scale(1.0)


def test_panel_scaled_sizes_grow(app):
    from bioprintgen.gui import theme
    from bioprintgen.gui.controls import ParameterPanel
    theme.set_scale(1.0)
    p = ParameterPanel()
    small = p.start_gcode.maximumHeight()
    theme.set_scale(2.0)
    p.apply_scaled_sizes()
    assert p.start_gcode.maximumHeight() > small
    theme.set_scale(1.0)


# --------------------------------------------------------------------------- #
#  Flavour editor
# --------------------------------------------------------------------------- #
def test_flavour_dialog_starts_from_a_template_and_saves_a_copy(app, tmp_path, monkeypatch):
    """Template -> editor form -> saved flavour must keep every character
    (tabs, multi-line blocks), so the copy still matches the built-in writer."""
    monkeypatch.setenv("BIOPRINTGEN_FLAVOURS", str(tmp_path))
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    from bioprintgen.gcode import flavour as fl
    from bioprintgen.gui.flavourdialog import FlavourDialog
    dlg = FlavourDialog()
    names = [a.text() for a in dlg.new_menu.actions()]
    assert "Blank" in names and "Planet CNC (template)" in names and "Marlin (template)" in names
    tpl = fl.list_templates()["Planet CNC (template)"]
    next(a for a in dlg.new_menu.actions() if a.text() == tpl.name).trigger()
    assert dlg.name_edit.text() == "Planet CNC (custom)"
    dlg._save()
    saved = fl.list_flavours()["Planet CNC (custom)"]
    assert {k: v for k, v in saved.to_dict().items() if k != "name"} == \
           {k: v for k, v in tpl.to_dict().items() if k != "name"}
    assert not (fl.templates_dir() / "Planet CNC (custom).json").exists()


def test_custom_flavour_keeps_the_drive_settings(panel, tmp_path, monkeypatch):
    """Templates read drive / ramp / valve values, so a custom flavour shows them."""
    monkeypatch.setenv("BIOPRINTGEN_FLAVOURS", str(tmp_path))
    from bioprintgen.gcode import flavour as fl
    fl.save_flavour(fl.list_templates()["Planet CNC (template)"])
    panel._refresh_flavours(select_name="Planet CNC (template)")
    assert panel.dialect.currentText() == "Custom: Planet CNC (template)"
    panel.drive.setCurrentIndex(0)
    for w, name in ((panel.drive, "drive"), (panel.ramp, "ramp"), (panel.ext10, "piston flow")):
        assert_row(w, True, f"custom {name}")


# --------------------------------------------------------------------------- #
#  User infill patterns
# --------------------------------------------------------------------------- #
def _select_pattern(panel, pid):
    panel.infill.setCurrentIndex(panel._pattern_ids.index(pid))


def test_equation_pattern_behaves_like_the_gyroid(panel):
    panel.infill_mode.setCurrentIndex(0)
    _select_pattern(panel, "schwarz_p")
    assert_row(panel.gyroid_period, True, "equation period")
    assert_row(panel.spacing, False, "equation spacing")
    assert_row(panel.infill_angle, False, "equation base angle")
    assert _label_of(panel.gyroid_period).text() == "Schwarz P period"
    assert panel.build_settings().infill_type == "schwarz_p"


def test_path_plugin_uses_spacing_and_angle(panel):
    panel.infill_mode.setCurrentIndex(0)
    _select_pattern(panel, "honeycomb")
    assert_row(panel.spacing, True, "plugin spacing")
    assert_row(panel.infill_angle, True, "plugin base angle")
    assert_row(panel.gyroid_period, False, "plugin period")


def test_sections_list_user_patterns_too(panel):
    from PySide6.QtWidgets import QComboBox
    panel.infill_sections._add_row()
    cell = panel.infill_sections.table.cellWidget(0, 2)
    assert isinstance(cell, QComboBox)
    names = [cell.itemText(i) for i in range(cell.count())]
    assert "Schwarz P" in names and "Honeycomb" in names
    panel.infill_sections.set_current_cell(2, panel._pattern_ids.index("neovius"))
    assert panel.build_settings().infill_sections[0].infill_type == "neovius"


def test_reload_keeps_the_selection_by_id(panel):
    _select_pattern(panel, "lidinoid")
    panel.infill_sections._add_row((0.0, 1.0, panel._pattern_ids.index("iwp"), 0.0))
    panel.reload_patterns(quiet=True)
    s = panel.build_settings()
    assert s.infill_type == "lidinoid" and s.infill_sections[0].infill_type == "iwp"


def test_missing_pattern_is_kept_and_reported(panel):
    from bioprintgen.model import PrintSettings, parse_pattern
    s = PrintSettings()
    s.infill_type = parse_pattern("gone_pattern")
    panel.apply_settings(s)
    assert panel.infill.currentText() == "gone_pattern (missing)"
    back = panel.build_settings()
    assert back.infill_type == "gone_pattern"
    assert any("gone_pattern" in m for m in back.validate())


def test_pattern_embedded_in_an_import_shows_by_name(panel, tmp_path, monkeypatch):
    from bioprintgen.infill import patterns
    from bioprintgen import settingsio
    from bioprintgen.model import PrintSettings, parse_pattern
    monkeypatch.setenv("BIOPRINTGEN_PATTERNS", str(tmp_path))
    try:
        patterns.reload()
        patterns.register_embedded({"emb": {"kind": "levelset", "name": "Embedded one",
                                            "equation": "cos(x)+cos(y)+cos(z)", "level": 0}})
        s = PrintSettings()
        s.infill_type = parse_pattern("emb")
        panel.apply_settings(s)
        assert panel.infill.currentText() == "Embedded one"
    finally:
        monkeypatch.delenv("BIOPRINTGEN_PATTERNS")
        patterns.reload()


# --------------------------------------------------------------------------- #
#  Components
# --------------------------------------------------------------------------- #
def test_component_editor_round_trip(panel):
    from bioprintgen.model import Component, PrintSettings
    ed = panel.components
    ed.add_btn.click()
    assert not ed.form_box.isHidden()
    ed.shape.setCurrentIndex(1)                      # cylinder
    assert ed._form.isRowVisible(ed.diameter) and not ed._form.isRowVisible(ed.size_y)
    ed.diameter.setValue(3.5)
    ed.cx.setValue(5.0)
    ed.extruder.setCurrentIndex(1)
    ed.walls.setValue(2)
    ed.pattern.setCurrentIndex(ed._pattern_ids.index("gyroid"))
    c = panel.build_settings().components[0]
    assert (c.shape, c.size_x, c.x, c.extruder, c.walls, c.pattern) == \
        ("cylinder", 3.5, 5.0, 2, 2, "gyroid")
    s = PrintSettings()
    s.components = [Component(name="core", walls=-1), c]
    panel.apply_settings(s)
    assert panel.build_settings().components == s.components
    assert ed.walls.text() == "merge with part"


def test_component_reorder_changes_priority(panel):
    from bioprintgen.model import Component, PrintSettings
    s = PrintSettings()
    s.components = [Component(name="a"), Component(name="b")]
    panel.apply_settings(s)
    ed = panel.components
    ed.list.setCurrentRow(1)
    ed.up_btn.click()
    assert [c.name for c in panel.build_settings().components] == ["b", "a"]
    ed.rem_btn.click()
    assert [c.name for c in panel.build_settings().components] == ["a"]


def test_added_components_go_on_top_and_never_stack(panel):
    """A second '+ Add' used to land exactly under the first and vanish."""
    from bioprintgen.model import PrintSettings
    panel.apply_settings(PrintSettings())
    ed = panel.components
    ed.set_main_bounds((0.0, 0.0, 10.0, 10.0))
    ed.add_btn.click()
    ed.name.setText("first")
    ed.add_btn.click()
    comps = panel.build_settings().components
    assert comps[1].name == "first" and ed.list.currentRow() == 0   # newest on top
    assert (comps[1].x, comps[1].y) == (5.0, 5.0)                    # main centre
    assert (comps[0].x, comps[0].y) != (comps[1].x, comps[1].y)
    ed.dup_btn.click()
    comps = panel.build_settings().components
    assert len({(c.x, c.y) for c in comps}) == 3


def test_walls_spinner_counts_walls(panel):
    from bioprintgen.model import Component, PrintSettings
    s = PrintSettings()
    s.components = [Component(walls=-1)]           # file from the first version
    panel.apply_settings(s)
    ed = panel.components
    assert ed.walls.value() == 0 and ed.walls.text() == "merge with part"
    ed.walls.stepBy(1)
    assert ed.walls.text() == "1" and panel.build_settings().components[0].walls == 1


def test_subtract_hides_material_fields_and_axis_shows_length(panel):
    from bioprintgen.model import Component, PrintSettings
    s = PrintSettings()
    s.components = [Component()]
    panel.apply_settings(s)
    ed = panel.components
    vis = ed._form.isRowVisible
    assert vis(ed.extruder) and vis(ed.walls) and not vis(ed.axis)
    ed.operation.setCurrentIndex(1)
    assert not vis(ed.extruder) and not vis(ed.pattern) and not vis(ed.walls)
    ed.shape.setCurrentIndex(1)
    assert vis(ed.axis) and vis(ed.height) and not vis(ed.length) and not vis(ed.rotation)
    ed.axis.setCurrentIndex(1)
    assert vis(ed.length) and not vis(ed.height) and vis(ed.rotation)
    ed.length.setValue(12.0)
    c = panel.build_settings().components[0]
    assert (c.operation, c.shape, c.axis, c.size_y) == ("subtract", "cylinder", "horizontal", 12.0)
    assert ed.list.item(0).text().startswith("− ")


def test_stl_component_in_the_editor(panel, tmp_path):
    import trimesh
    from bioprintgen.model import Component, PrintSettings
    path = tmp_path / "part.stl"
    trimesh.creation.box(extents=(2.0, 3.0, 4.0)).export(path)
    s = PrintSettings()
    s.components = [Component()]
    panel.apply_settings(s)
    ed = panel.components
    ed.set_stl_path(str(path))
    vis = ed._form.isRowVisible
    assert vis(ed.stl_row) and vis(ed.scale) and vis(ed.rot_x) and vis(ed.rotation)
    assert not vis(ed.size_x) and not vis(ed.height) and not vis(ed.diameter)
    assert "2.00 × 3.00 × 4.00 mm" in ed.stl_size.text()
    ed.scale.setValue(50)
    assert "1.00 × 1.50 × 2.00 mm" in ed.stl_size.text()
    c = panel.build_settings().components[0]
    assert (c.shape, c.stl_path, c.scale) == ("stl", str(path), 50.0)
    assert ed.stl_name.text() == "part.stl"


# --------------------------------------------------------------------------- #
#  Well plate
# --------------------------------------------------------------------------- #
def _set_point(spins, *values):
    for s, v in zip(spins, values):
        s.setValue(v)


def test_plate_dialog_round_trip_and_live_calibration(app):
    import math
    from bioprintgen import placement as plc
    from bioprintgen.gui.platedialog import PlateDialog
    dlg = PlateDialog(plc.Placement(enabled=True, wells=["A1", "B2"]), part_radius=4.0)
    assert len(dlg._cells) == 24 and dlg._cells["B2"].isChecked()
    assert (dlg.rim_well.currentText(), dlg.centre_well.currentText()) == ("A1", "D6")
    dlg.preset.setCurrentIndex(0)                       # 6-well
    assert len(dlg._cells) == 6 and dlg.pitch_x.value() == 39.12
    assert dlg.centre_well.currentText() == "B3"         # D6 is gone: opposite corner
    dlg._toggle_line(row=0)                             # all of row A
    rim = [(50 + 17.4 * math.cos(math.radians(a)), 60 + 17.4 * math.sin(math.radians(a)))
           for a in (0, 120, 240)]
    _set_point(dlg.p1, *rim[0], 21.0)
    _set_point(dlg.p2, *rim[1])
    _set_point(dlg.p3, *rim[2])
    _set_point(dlg.p4, 50 + 2 * 39.12, 60 - 39.12, 3.5)  # B3 centre, unrotated
    text = dlg.result.text()
    assert "A1 centre: X 50.000, Y 60.000" in text and "Plate angle +0.00°" in text
    assert "measured Ø" not in text and "check" not in text   # no diameter check
    dlg.between.setCurrentIndex(2)
    assert dlg._run_form.isRowVisible(dlg.dwell)
    out = dlg.placement()
    assert out.plate.name == "6-well" and sorted(out.wells) == ["A1", "A2", "A3", "B2"]
    assert out.rim_z == 21.0 and out.floor_z == 3.5 and out.centre_well == "B3"
    assert out.between == "dwell"


def test_calibration_wells_can_be_picked(app):
    from bioprintgen import placement as plc
    from bioprintgen.gui.platedialog import PlateDialog
    dlg = PlateDialog(plc.Placement(enabled=True, wells=["A1"]))
    dlg.rim_well.setCurrentText("B2")
    dlg.centre_well.setCurrentText("C5")
    assert "rim of B2" in dlg.hint.text() and "centre of C5" in dlg.hint.text()
    out = dlg.placement()
    assert (out.rim_well, out.centre_well) == ("B2", "C5")
    dlg.centre_well.setCurrentText("B2")
    assert "must be different" in dlg.result.text()


def test_plate_dialog_flags_a_part_that_does_not_fit(app):
    from bioprintgen import placement as plc
    from bioprintgen.gui.platedialog import PlateDialog
    pl = plc.Placement(enabled=True, wells=["A1"], guided=True)
    dlg = PlateDialog(pl, part_radius=9.0)
    assert "will not fit" in dlg.result.text()


def test_plate_dialog_guided_mode_hides_the_coordinates(app):
    from bioprintgen import placement as plc
    from bioprintgen.gui.platedialog import PlateDialog
    dlg = PlateDialog(plc.Placement(enabled=True, wells=["A1", "A2"]), part_radius=3.0)
    assert all(dlg._cal_form.isRowVisible(r) for r in dlg._typed_rows)
    dlg.mode.setCurrentIndex(1)
    assert not any(dlg._cal_form.isRowVisible(r) for r in dlg._typed_rows)
    assert dlg._cal_form.isRowVisible(dlg.rim_well) and dlg._cal_form.isRowVisible(dlg.centre_well)
    assert "asks for each point" in dlg.hint.text()
    assert "summary" in dlg.result.text()
    assert dlg.placement().guided


def test_plate_panel_section(panel):
    from bioprintgen.model import PrintSettings
    assert panel.plate_btn.isEnabled() is False
    s = PrintSettings()
    s.placement.enabled = True
    s.placement.wells = ["A1", "A2"]
    s.placement.guided = True
    panel.apply_settings(s)
    assert panel.plate_on.isChecked() and panel.plate_btn.isEnabled()
    assert "2 well(s)" in panel.plate_summary.text()
    assert "rim of A1 + centre of D6" in panel.plate_summary.text()
    assert_row(panel.zero_xy, False, "G92 zero on a plate")
    back = panel.build_settings()
    assert back.placement == s.placement
    panel.plate_on.setChecked(False)
    assert panel.build_settings().placement.enabled is False
    assert_row(panel.zero_xy, True, "G92 zero without a plate")
