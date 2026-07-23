"""Shared fixtures.

The suite is deliberately Qt-free so it runs fast and headless on any machine;
it exercises the model / geometry / infill / writer / settings layers, which is
where the g-code correctness actually lives.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from bioprintgen.model import PrintSettings

ROOT = Path(__file__).resolve().parent.parent
STL = ROOT / "falcon-kartusa.stl"


@pytest.fixture
def settings() -> PrintSettings:
    """A predictable baseline: no flow control, no tool change, known speeds."""
    s = PrintSettings()
    s.layer_height = 0.2
    s.print_speed = 500.0
    s.travel_speed = 1600.0
    return s


@pytest.fixture
def stl_path() -> Path:
    if not STL.exists():
        pytest.skip(f"{STL.name} not present")
    return STL


def gcode_lines(project) -> list[str]:
    return project.gcode_text().splitlines()


def extrude_lines(project) -> list[str]:
    return [g.text for g in project.glines() if g.kind == "move"]
