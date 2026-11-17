"""Guided plate calibration inside the Planet CNC program.

The calibration is g-code arithmetic, so these tests *run* it: a tiny
interpreter replays the parameter assignments with simulated jog positions and
the results are compared with the app's own calibration maths.  A lint test
guards against the parser pitfalls found on the machine (parentheses start
comments; no arithmetic inside function arguments; '%' ends a program; very
long lines make the program "empty").
"""
from __future__ import annotations

import dataclasses
import math
import re

import pytest

from bioprintgen import placement as plc
from bioprintgen.gcode.writer import render
from bioprintgen.model import Dialect, PrintSettings
from bioprintgen.pipeline import Project

FUNCS = {"ATAN2": lambda y, x: math.degrees(math.atan2(y, x)), "SQRT": math.sqrt,
         "COS": lambda a: math.cos(math.radians(a)), "SIN": lambda a: math.sin(math.radians(a))}


def _rim(cx, cy, r=7.8, angles=(15, 140, 260)):
    return [(cx + r * math.cos(math.radians(a)), cy + r * math.sin(math.radians(a)))
            for a in angles]


def _settings(**kw) -> PrintSettings:
    s = PrintSettings()
    s.layer_height = 0.2
    pl = s.placement
    pl.enabled, pl.guided = True, True
    pl.plate = dataclasses.replace(plc.PLATE_PRESETS["24-well"])
    pl.wells = ["A1", "A2", "B1", "D6"]
    for k, v in kw.items():
        setattr(pl, k, v)
    return s


def _program(s):
    p = Project.from_cylinder(8, 0.6, s)
    p.plan()
    return p, [g.text for g in render(p.toolpath, s)]


# --------------------------------------------------------------------------- #
#  a tiny interpreter for the generated parameter arithmetic
# --------------------------------------------------------------------------- #
def _eval(expr: str, P: dict) -> float:
    """G-code expression -> Python: functions first (their [] become ()),
    then grouping [] -> (), and only then the parameter look-ups (which use
    [] themselves)."""
    e = re.sub(r"\b(ATAN2|SQRT|COS|SIN)\[([^\[\]]*)\]", r"_F_\1(\2)", expr)
    e = e.replace("[", "(").replace("]", ")").replace(" EQ ", " == ").replace(" GT ", " > ")
    e = re.sub(r"#<(\w+)>", lambda m: f"P[{m.group(1)!r}]", e)
    e = re.sub(r"#(\d+)", lambda m: f"P['#{m.group(1)}']", e)
    env = {f"_F_{k}": f for k, f in FUNCS.items()}
    env["P"] = P
    return float(eval(e, env))


def run(lines, jogs, offsets=(0, 0, 0, 0)):
    """Replay the program up to M2.  Each 'Point k of 4' prompt + M0 moves the
    simulated head to the next (x, y, z) in `jogs`.  Returns (params,
    [(well, wx, wy, angle)])."""
    P = {"#102": offsets[0], "#103": offsets[1], "#104": offsets[2], "#105": offsets[3]}
    pos = {"_x": 0.0, "_y": 0.0, "_z": 0.0}
    jogs = list(jogs)
    pending = False
    wells, current = [], None
    for line in lines:
        if line.startswith("(msg,Point "):
            pending = True
        elif line == "M0" and pending:
            x, y, z = jogs.pop(0)
            pos.update(_x=x, _y=y, _z=z)
            pending = False
        elif line.startswith("; ===== well "):
            current = line.split()[3]
        elif line.startswith("G52\tX#<pc_wx>"):
            wells.append((current, P["pc_wx"], P["pc_wy"], P["pc_ang"]))
        elif line == "M2":
            break
        m = re.match(r"^#<(\w+)> = (.+)$", line)
        if m:
            P.update(pos)
            P[m.group(1)] = _eval(m.group(2), P)
    assert not jogs, "every simulated point should have been asked for"
    return P, wells


def _jogs(a1, rim_z, d6, floor_z, angles=(15, 140, 260)):
    pts = _rim(*a1, angles=angles)
    return [(*pts[0], rim_z), (*pts[1], 0.0), (*pts[2], 0.0), (*d6, floor_z)]


def _typed(s, jogs):
    """The same calibration as typed coordinates, for the app's own maths."""
    (x1, y1, z1), (x2, y2, _), (x3, y3, _), (x4, y4, z4) = jogs
    return dataclasses.replace(s.placement, guided=False,
                               rim_points=[[x1, y1], [x2, y2], [x3, y3]], rim_z=z1,
                               centre_x=x4, centre_y=y4, floor_z=z4)


def _d6(a1, angle=0.0, scale=1.0):
    t = math.radians(angle)
    lx, ly = 5 * 19.3 * scale, -3 * 19.3 * scale
    return (a1[0] + lx * math.cos(t) - ly * math.sin(t), a1[1] + lx * math.sin(t) + ly * math.cos(t))


# --------------------------------------------------------------------------- #
def test_program_structure():
    s = _settings(between="pause")
    _p, lines = _program(s)
    text = "\n".join(lines)
    assert "G92\tX0\tY0" not in text and "\nG1\tZ0\t" not in text
    i_m2, i_sub, i_ret = lines.index("M2"), lines.index("O1000"), lines.index("M99")
    assert i_m2 < i_sub < i_ret
    assert lines[i_ret + 1:] == ["%"]          # the subprogram is the last thing
    assert any("BIOPRINTGEN_JSON" in l for l in lines[:i_m2])
    assert text.count("; layer 0 ") == 1                     # the print is written once
    assert text.count("M98\tP1000") == 4
    assert text.count("G68\tX0\tY0\tR#<pc_ang>") == 4 and text.count("G69") == 4
    assert text.count("done - press Resume") == 3             # no pause after the last


def test_four_prompts_in_order_with_the_chosen_wells():
    s = _settings(rim_well="B2", centre_well="C5")
    _p, lines = _program(s)
    prompts = [l for l in lines if l.startswith("(msg,Point ")]
    assert [p.split(":")[0] for p in prompts] == [f"(msg,Point {k} of 4" for k in (1, 2, 3, 4)]
    assert "top edge of the rim of well B2" in prompts[0] and "travel height" in prompts[0]
    assert all("rim of well B2" in p for p in prompts[1:3])
    assert "centre of well C5" in prompts[3] and "floor" in prompts[3]
    intro = next(l for l in lines if l.startswith("(msg,Plate calibration"))
    assert "any order" in intro and "B2" in intro and "C5" in intro
    assert not any("check:" in l for l in lines)              # no diameter check


def test_generated_lines_avoid_the_parser_pitfalls():
    s = _settings(use_measured_pitch=True)
    s.tool_change_enabled = True
    _p, lines = _program(s)
    for line in lines:
        assert len(line) <= 255, f"line too long for Planet CNC: {line[:60]!r}"
        if line.startswith("; ") and "BIOPRINTGEN_JSON" in line:
            continue                                          # the settings record
        assert "%" not in line or line == "%", f"'%' ends a Planet program: {line!r}"
        code = line.split(";", 1)[0]
        if code.startswith("("):
            # a Planet comment command: one ')' only, at the end
            assert code.count("(") == 1 and code.count(")") == 1 and code.endswith(")"), \
                f"nested parentheses end the comment early: {line!r}"
            continue
        assert "(" not in code, f"parenthesis outside a comment: {line!r}"
        for m in re.finditer(r"\b([A-Z][A-Z0-9]*)\[([^\[\]]*)\]", code):
            if m.group(1) in FUNCS:
                assert not re.search(r"[-+*/]", m.group(2)), f"arithmetic in arguments: {line!r}"


def test_calibration_matches_the_apps_own_maths():
    """A plate turned by -1.5° with 0.4 % smaller spacing, measured spacing on."""
    a1 = (90.0, 160.0)
    jogs = _jogs(a1, 21.5, _d6(a1, -1.5, 0.996), 4.0)
    s = _settings(use_measured_pitch=True)
    _p, lines = _program(s)
    P, wells = run(lines, jogs)
    typed = _typed(s, jogs)
    centres, cal = plc.well_centres(typed), plc.calibrate(typed)
    assert P["pc_acx"] == pytest.approx(a1[0]) and P["pc_acy"] == pytest.approx(a1[1])
    assert P["pc_ang"] == pytest.approx(-1.5) and P["pc_err"] == pytest.approx(-0.4)
    assert len(wells) == 4
    # constants are written with 6 decimals: agreement to 10 nm is exact enough
    for well, wx, wy, ang in wells:
        assert (wx, wy) == pytest.approx(centres[well], abs=1e-5)
        assert ang == pytest.approx(cal.angle)


def test_heights_from_the_rim_and_the_floor():
    a1 = (100.0, 150.0)
    s = _settings(clearance=2.5)
    p, lines = _program(s)                                    # part 0.6 mm tall
    P, _w = run(lines, _jogs(a1, 21.0, _d6(a1), 3.4))
    assert P["pc_z1"] == pytest.approx(3.4 + 0.2)              # floor + first layer
    assert P["pc_tz"] == pytest.approx(21.0 + 2.5)             # rim + clearance
    assert P["pc_tz"] == pytest.approx(plc.travel_z(_typed(s, _jogs(a1, 21.0, _d6(a1), 3.4)),
                                                    p.toolpath))
    P, _w = run(lines, _jogs(a1, 3.5, _d6(a1), 3.4))           # rim below the part's top
    assert P["pc_tz"] == pytest.approx(3.4 + 0.6 + 2.5)
    text = "\n".join(lines)
    assert "G0\tZ#<pc_z1>" in text and "G0\tZ#<pc_tz>" in text


def test_rim_points_in_any_order():
    a1 = (100.0, 150.0)
    s = _settings()
    _p, lines = _program(s)
    a = run(lines, _jogs(a1, 20, _d6(a1), 3, angles=(15, 140, 260)))[0]
    b = run(lines, _jogs(a1, 20, _d6(a1), 3, angles=(260, 15, 140)))[0]
    assert (a["pc_acx"], a["pc_acy"]) == pytest.approx((b["pc_acx"], b["pc_acy"]))


def test_tool_change_offsets_are_counter_rotated():
    """Inside a G68 frame the tool-change offset move is rotated too; the
    program pre-rotates the offsets by -angle so the physical move is right."""
    s = _settings()
    s.tool_change_enabled = True
    s.extruder2_offset = (77.0, 0.0)
    _p, lines = _program(s)
    a1 = (100.0, 150.0)
    P, _w = run(lines, _jogs(a1, 20, _d6(a1, 2.0), 3), offsets=(77.0, 0.0, -77.0, 0.0))
    rx, ry = P["pc_r2x"], P["pc_r2y"]
    a = math.radians(2.0)
    ca, sa = math.cos(a), math.sin(a)
    assert (rx * ca - ry * sa, rx * sa + ry * ca) == pytest.approx((77.0, 0.0), abs=1e-5)
    text = "\n".join(lines)
    assert "#<pc_r2x>" in text and "G0\tX[#<_x> + #102]" not in text


def test_load_time_simulation_does_not_divide_by_zero():
    """With every 'jogged' point at the same position the calibration must
    still run through (a zero divisor stops Planet CNC with an error)."""
    s = _settings(use_measured_pitch=True)
    s.tool_change_enabled = True
    _p, lines = _program(s)
    P, wells = run(lines, [(12.0, 34.0, 5.0)] * 4)
    assert len(wells) == 4
    assert all(math.isfinite(v) for _w, x, y, a in wells for v in (x, y, a))


def test_guided_needs_planet_cnc_and_ignores_typed_coordinates():
    s = _settings(rim_points=[[0, 0], [1, 1], [2, 2]])          # collinear, but unused
    assert s.validate() == []
    s.placement.centre_well = "A1"                              # same as the rim well
    assert any("must be different" in m for m in s.validate())
    s.placement.centre_well = "D6"
    s.dialect = Dialect.MARLIN_ABS_E
    assert any("needs the Planet CNC" in m for m in s.validate())


@pytest.mark.parametrize("mode", ["single", "plate", "guided"])
def test_planet_program_never_starts_with_a_blank_line(mode):
    s = _settings()
    s.placement.enabled = mode != "single"
    s.placement.guided = mode == "guided"
    s.placement.rim_points = [list(p) for p in _rim(100.0, 150.0)]
    s.placement.centre_x, s.placement.centre_y = _d6((100.0, 150.0))
    _p, lines = _program(s)
    assert lines[0] == "%" and lines[1].strip() != ""
    if mode != "single":
        assert lines[1].startswith("G21\tG90")
