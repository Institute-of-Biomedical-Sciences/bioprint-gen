"""Planet CNC emission: feedrates, relative Z rises, file structure."""
from __future__ import annotations

import re

import pytest

from bioprintgen.model import PrintSettings, LayerHeightSection, DriveMode
from bioprintgen.pipeline import Project


def _project(settings, w=10, d=10, h=0.4):
    p = Project.from_cuboid(w, d, h, settings)
    p.plan()
    return p


# --------------------------------------------------------------------------- #
#  Feedrates:  travels are G0 rapids; every stroke restates the print feed.
# --------------------------------------------------------------------------- #
def test_travels_are_g0_with_travel_feed(settings):
    p = _project(settings)
    travels = [g.text for g in p.glines() if g.kind == "travel"]
    assert travels
    for t in travels:
        assert t.startswith("G0\t"), f"travel is not a rapid: {t}"
        assert f"F{int(settings.travel_speed)}" in t


def test_printing_moves_are_g1(settings):
    p = _project(settings)
    moves = [g.text for g in p.glines() if g.kind == "move"]
    assert moves
    assert all(m.startswith("G1\t") for m in moves)


def test_first_move_of_each_stroke_restates_print_feed(settings):
    """F is modal, so each stroke must set it or it inherits the travel feed."""
    p = _project(settings)
    glines = [g for g in p.glines() if g.kind in ("move", "travel", "coast")]
    expect_feed = True          # the first printing move after any travel
    seen = 0
    for g in glines:
        if g.kind == "travel":
            expect_feed = True
            continue
        if g.kind == "move" and expect_feed:
            assert f"F{int(settings.print_speed)}" in g.text, \
                f"stroke starts without the print feed: {g.text}"
            seen += 1
            expect_feed = False
    assert seen >= 2, "expected several strokes in this part"


def test_print_feed_is_not_the_travel_feed(settings):
    """Guards the original bug: printing must not run at travel speed."""
    settings.print_speed, settings.travel_speed = 500.0, 1600.0
    p = _project(settings)
    firsts = [g.text for g in p.glines() if g.kind == "move" and "F" in g.text]
    assert firsts
    assert all("F500" in t and "F1600" not in t for t in firsts)


# --------------------------------------------------------------------------- #
#  Relative Z rises must match the gap to the next layer
# --------------------------------------------------------------------------- #
def _layer_z_and_rises(p):
    """([layer comment z...], [relative Z rise...]).

    Filtered on kind == "layer" so the footer's safe-Z lift is excluded.
    """
    zs, rises = [], []
    for g in p.glines():
        if g.kind != "layer":
            continue
        m = re.match(r"; layer \d+\s+z=([\d.]+)", g.text)
        if m:
            zs.append(float(m.group(1)))
        r = re.match(r"G1\tZ\[#<_z> \+([\d.]+)\]", g.text)
        if r:
            rises.append(float(r.group(1)))
    return zs, rises


def test_z_rise_matches_gap_to_next_layer(settings):
    settings.layer_sections = [LayerHeightSection(1.0, 2.0, 0.5)]
    p = _project(settings, h=2.2)
    zs, rises = _layer_z_and_rises(p)
    assert len(zs) == len(rises)
    for i in range(len(zs) - 1):
        expected = round(zs[i + 1] - zs[i], 4)
        assert abs(rises[i] - expected) < 1e-6, (
            f"layer at z={zs[i]} rises {rises[i]} but the next layer is at "
            f"{zs[i+1]} (gap {expected})")


def test_z_moves_carry_the_z_feedrate(settings):
    """z_speed used to be inert on Planet CNC: the Z lines had no feedrate."""
    settings.z_speed = 275.0
    p = _project(settings, h=0.6)
    z_moves = [g.text for g in p.glines()
               if g.kind in ("layer", "footer") and "Z[#<_z>" in g.text]
    assert z_moves
    for t in z_moves:
        assert "F275" in t, f"Z move without the Z feedrate: {t}"


def test_z_feedrate_does_not_leak_into_the_next_stroke(settings):
    """Setting F on the Z move must not make the next stroke print at z_speed."""
    settings.z_speed = 275.0
    p = _project(settings, h=0.6)
    seen_z = False
    for g in p.glines():
        if g.kind == "layer" and "Z[#<_z>" in g.text:
            seen_z = True
        elif seen_z and g.kind == "move":
            assert f"F{int(settings.print_speed)}" in g.text, \
                "first stroke after a Z move must restate the print feed"
            seen_z = False


def test_section_boundary_steps_by_the_custom_height(settings):
    """Entering a 0.5 mm section, the rise at its start must be 0.5."""
    settings.layer_sections = [LayerHeightSection(1.0, 2.0, 0.5)]
    p = _project(settings, h=2.2)
    zs, rises = _layer_z_and_rises(p)
    at_boundary = rises[zs.index(1.0)]
    assert abs(at_boundary - 0.5) < 1e-6


# --------------------------------------------------------------------------- #
#  File structure
# --------------------------------------------------------------------------- #
def test_program_delimiters(settings):
    lines = _project(settings).gcode_text().splitlines()
    assert lines[0] == "%"
    assert lines[-1] == "%"


def test_settings_block_is_at_the_end(settings):
    settings.write_settings_header = True
    text = _project(settings).gcode_text()
    assert "BioprintGEN settings" in text
    head = text.split("; layer 0")[0]
    assert "BioprintGEN settings" not in head, "settings block must not be at the top"


def test_settings_block_can_be_disabled(settings):
    settings.write_settings_header = False
    assert "BioprintGEN settings" not in _project(settings).gcode_text()


def test_start_and_end_gcode_are_injected_in_order(settings):
    settings.start_gcode = "M104 S25"
    settings.end_gcode = "M104 S0"
    text = _project(settings).gcode_text()
    assert "M104 S25" in text and "M104 S0" in text
    assert text.index("M104 S25") < text.index("; layer 0") < text.index("M104 S0")


def test_pneumatic_uses_valve_instead_of_metered_axis(settings):
    settings.drive = DriveMode.PNEUMATIC
    text = _project(settings).gcode_text()
    assert "M63 P1" in text
    assert "A[#<_a>" not in text
