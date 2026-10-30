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
                                    "Printing process", "Advanced options"]


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
