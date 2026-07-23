"""Marlin emission."""
from __future__ import annotations

import re

import pytest

from bioprintgen.model import PrintSettings, Dialect, LayerHeightSection
from bioprintgen.pipeline import Project


@pytest.fixture
def marlin(settings):
    settings.dialect = Dialect.MARLIN_ABS_E
    return settings


def _project(settings, h=0.4):
    p = Project.from_cuboid(10, 10, h, settings)
    p.plan()
    return p


def test_header_is_present(marlin):
    text = _project(marlin).gcode_text()
    for expected in ("G21", "G90", "M82"):
        assert expected in text


def test_every_move_states_its_feedrate(marlin):
    """Marlin is immune to the modal-feed trap because F is always explicit."""
    p = _project(marlin)
    for g in p.glines():
        if g.kind in ("move", "travel"):
            assert " F" in g.text, f"move without a feedrate: {g.text}"


def test_travels_are_g0_and_prints_are_g1(marlin):
    p = _project(marlin)
    for g in p.glines():
        if g.kind == "travel":
            assert g.text.startswith("G0 ")
        elif g.kind == "move":
            assert g.text.startswith("G1 ") and " E" in g.text


def test_extrusion_is_monotonic(marlin):
    """Absolute E must never go backwards."""
    p = _project(marlin)
    es = [float(m.group(1)) for g in p.glines()
          if (m := re.search(r" E([\d.]+)", g.text))]
    assert es == sorted(es)
    assert es[-1] > 0


def test_layers_use_absolute_z(marlin):
    p = _project(marlin, h=0.6)
    # only the per-layer Z moves, not the footer's safe-height lift
    zs = [float(m.group(1)) for g in p.glines() if g.kind == "layer"
          and (m := re.match(r"G1 Z([\d.]+) ", g.text))]
    assert zs == sorted(zs)
    assert zs == [round(l.z, 3) for l in p.toolpath]


def test_variable_layer_height_scales_extrusion(marlin):
    """E per mm of travel should scale with the layer's actual height."""
    marlin.layer_height = 0.2
    marlin.layer_sections = [LayerHeightSection(0.4, 1.2, 0.6)]
    p = _project(marlin, h=1.2)

    per_layer = {}
    for g in p.glines():
        if g.kind == "move" and g.layer is not None:
            e = float(re.search(r" E([\d.]+)", g.text).group(1))
            mv = p.toolpath[g.layer].moves[g.move]
            per_layer.setdefault(g.layer, []).append((mv.length, e))

    # E delta per mm on a 0.2 layer vs a 0.6 layer should differ 3x
    def rate(layer):
        pts = per_layer[layer]
        (l0, e0), (l1, e1) = pts[0], pts[1]
        return (e1 - e0) / l1

    thin = next(i for i, l in enumerate(p.toolpath) if abs(l.height - 0.2) < 1e-9)
    thick = next(i for i, l in enumerate(p.toolpath) if abs(l.height - 0.6) < 1e-9)
    assert rate(thick) == pytest.approx(rate(thin) * 3, rel=0.05)
