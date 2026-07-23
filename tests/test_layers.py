"""Layer stack construction: variable layer-height sections."""
from __future__ import annotations

import pytest

from bioprintgen.model import PrintSettings, LayerHeightSection, build_z_levels
from bioprintgen.pipeline import Project


def heights(levels):
    return [round(h, 6) for _z, h in levels]


def zs(levels):
    return [round(z, 6) for z, _h in levels]


def test_uniform_stack(settings):
    levels = build_z_levels(1.0, settings)
    assert zs(levels) == [0.2, 0.4, 0.6, 0.8, 1.0]
    assert heights(levels) == [0.2] * 5


def test_first_layer_height_is_honoured(settings):
    settings.first_layer_height = 0.5
    levels = build_z_levels(1.1, settings)
    assert zs(levels)[0] == 0.5
    assert heights(levels)[0] == 0.5
    assert heights(levels)[1] == 0.2


def test_section_overrides_default_height(settings):
    """A section [1.0, 2.0] with h=0.5 must produce 0.5 steps inside it."""
    settings.layer_sections = [LayerHeightSection(1.0, 2.0, 0.5)]
    levels = build_z_levels(2.2, settings)
    assert zs(levels) == [0.2, 0.4, 0.6, 0.8, 1.0, 1.5, 2.0, 2.2]
    # the layer whose *bottom* sits at 1.0 is the first one 0.5 thick
    assert dict(zip(zs(levels), heights(levels)))[1.5] == 0.5
    assert dict(zip(zs(levels), heights(levels)))[2.0] == 0.5
    # back to the default above the section
    assert dict(zip(zs(levels), heights(levels)))[2.2] == 0.2


def test_uncovered_z_uses_default(settings):
    settings.layer_sections = [LayerHeightSection(5.0, 6.0, 0.9)]
    levels = build_z_levels(1.0, settings)
    assert heights(levels) == [0.2] * 5


def test_zero_height_section_falls_back(settings):
    """A malformed 0-height section must not hang the generator."""
    settings.layer_sections = [LayerHeightSection(0.0, 5.0, 0.0)]
    levels = build_z_levels(1.0, settings)
    assert len(levels) == 5


def test_layer_heights_reach_the_toolpath(settings):
    settings.layer_sections = [LayerHeightSection(0.4, 1.0, 0.3)]
    p = Project.from_cuboid(8, 8, 1.0, settings)
    p.plan()
    assert [round(l.height, 3) for l in p.toolpath] == [0.2, 0.2, 0.3, 0.3]
