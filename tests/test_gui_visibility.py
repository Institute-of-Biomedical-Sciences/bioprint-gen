"""Which settings are greyed out for a given selection.

This is the one Qt-dependent module in the suite; it runs headless via the
offscreen platform and skips cleanly if Qt cannot start at all.
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
    try:
        yield inst
    finally:
        pass


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


def assert_row(widget, enabled: bool, what: str):
    assert widget.isEnabled() is enabled, f"{what}: field should be enabled={enabled}"
    label = _label_of(widget)
    if label is not None:
        assert label.isEnabled() is enabled, \
            f"{what}: label should follow its field (enabled={enabled})"


# --------------------------------------------------------------------------- #
#  Source: only the dimensions the shape actually uses
# --------------------------------------------------------------------------- #
def test_cuboid_uses_width_and_depth(panel):
    panel.shape.setCurrentIndex(0)
    assert_row(panel.width, True, "cuboid width")
    assert_row(panel.depth, True, "cuboid depth")
    assert_row(panel.diameter, False, "cuboid diameter")
    assert_row(panel.height, True, "cuboid height")


def test_cylinder_uses_diameter(panel):
    panel.shape.setCurrentIndex(1)
    assert_row(panel.width, False, "cylinder width")
    assert_row(panel.depth, False, "cylinder depth")
    assert_row(panel.diameter, True, "cylinder diameter")
    assert_row(panel.height, True, "cylinder height")


def test_stl_uses_none_of_the_primitive_dimensions(panel):
    panel.shape.setCurrentIndex(2)
    for w, name in ((panel.width, "width"), (panel.depth, "depth"),
                    (panel.diameter, "diameter"), (panel.height, "height")):
        assert_row(w, False, f"stl {name}")
    assert panel.stl_btn.isEnabled()


# --------------------------------------------------------------------------- #
#  Infill
# --------------------------------------------------------------------------- #
def test_gyroid_uses_period_not_spacing(panel):
    """gyroid.generate() reads gyroid_period only — spacing/angles don't apply."""
    panel.infill.setCurrentIndex(2)
    assert_row(panel.gyroid_period, True, "gyroid period")
    assert_row(panel.spacing, False, "gyroid spacing")
    assert_row(panel.infill_angle, False, "gyroid base angle")
    assert_row(panel.layer_rot, False, "gyroid layer rotation")


def test_rectilinear_uses_spacing_not_period(panel):
    panel.infill.setCurrentIndex(0)
    assert_row(panel.gyroid_period, False, "rectilinear period")
    assert_row(panel.spacing, True, "rectilinear spacing")
    assert_row(panel.infill_angle, True, "rectilinear base angle")


# --------------------------------------------------------------------------- #
#  Extrusion / flow control
# --------------------------------------------------------------------------- #
def test_piston_fields(panel):
    panel.dialect.setCurrentIndex(0)     # Planet CNC
    panel.drive.setCurrentIndex(0)       # piston
    assert_row(panel.ext10, True, "piston extrusion rate")
    assert_row(panel.valve, False, "piston valve value")
    assert_row(panel.flow_start_ramp, True, "piston start ramp")
    assert_row(panel.flow_end_retract, True, "piston end retract")


def test_pneumatic_fields(panel):
    panel.dialect.setCurrentIndex(0)
    panel.drive.setCurrentIndex(1)       # pneumatic
    assert_row(panel.ext10, False, "pneumatic extrusion rate")
    assert_row(panel.valve, True, "pneumatic valve value")
    # the metered prime/retract have no meaning without a plunger axis
    assert_row(panel.flow_start_ramp, False, "pneumatic start ramp")
    assert_row(panel.flow_end_retract, False, "pneumatic end retract")


def test_marlin_uses_filament_area(panel):
    panel.dialect.setCurrentIndex(1)     # Marlin
    assert_row(panel.fil_area, True, "marlin filament area")
    assert_row(panel.ramp, False, "marlin ramp")
    assert_row(panel.drive, False, "marlin drive")


# --------------------------------------------------------------------------- #
#  Tool change
# --------------------------------------------------------------------------- #
def test_tool_change_fields_follow_the_checkbox(panel):
    panel.tool_change.setChecked(False)
    assert_row(panel.ext2x, False, "offset with tool change off")
    assert not panel.set_start_btn.isEnabled()
    panel.tool_change.setChecked(True)
    assert_row(panel.ext2x, True, "offset with tool change on")
    assert panel.set_start_btn.isEnabled()


def test_disabled_fields_still_report_values(panel):
    """Greying is cosmetic: build_settings must still read every control, so
    switching shapes can never silently corrupt unrelated settings."""
    panel.shape.setCurrentIndex(1)          # diameter active, width greyed
    panel.width.setValue(42.0)
    assert panel.source_spec().width == 42.0
    assert panel.build_settings().layer_height > 0
