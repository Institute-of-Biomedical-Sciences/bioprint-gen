"""Multi-well plate placement: calibration maths, well positions and output."""
from __future__ import annotations

import dataclasses
import math
import re

import pytest

from bioprintgen import placement as plc, settingsio
from bioprintgen.gcode import flavour as fl
from bioprintgen.gcode.writer import render, move_line_map
from bioprintgen.model import Dialect, DriveMode, PrintSettings
from bioprintgen.pipeline import Project

R24 = 7.8                                         # 24-well radius


def _rim(cx, cy, r=R24, angles=(10, 130, 250)):
    return [[cx + r * math.cos(math.radians(a)), cy + r * math.sin(math.radians(a))]
            for a in angles]


def plate_points(a1=(100.0, 150.0), angle=0.0, scale=1.0, centre="D6"):
    """Rim points of A1 and the centre of `centre` for a plate at `a1`,
    turned by `angle` with its spacing scaled by `scale`."""
    plate = plc.PLATE_PRESETS["24-well"]
    r, c = plc.parse_well(centre, plate)
    lx, ly = c * 19.3 * scale, -r * 19.3 * scale
    t = math.radians(angle)
    return _rim(*a1), (a1[0] + lx * math.cos(t) - ly * math.sin(t),
                       a1[1] + lx * math.sin(t) + ly * math.cos(t))


def _settings(**pl_kw) -> PrintSettings:
    s = PrintSettings()
    s.layer_height = 0.2
    pl = s.placement
    pl.enabled = True
    pl.plate = dataclasses.replace(plc.PLATE_PRESETS["24-well"])
    pl.wells = ["A1", "A2", "B1", "B2"]
    rim, (cx, cy) = plate_points()
    pl.rim_well, pl.rim_points, pl.rim_z = "A1", rim, 22.0
    pl.centre_well, pl.centre_x, pl.centre_y, pl.floor_z = "D6", cx, cy, 5.0
    for k, v in pl_kw.items():
        setattr(pl, k, v)
    return s


def _project(s):
    p = Project.from_cylinder(8, 0.6, s)
    p.plan()
    return p


# --------------------------------------------------------------------------- #
#  calibration maths
# --------------------------------------------------------------------------- #
def test_circle_through_three_rim_points():
    centre, r = plc.circle_from_3(*[tuple(p) for p in _rim(12.5, -3.0)])
    assert centre == pytest.approx((12.5, -3.0)) and r == pytest.approx(R24)


def test_rim_point_order_does_not_matter():
    pts = [tuple(p) for p in _rim(40.0, 60.0, angles=(5, 170, 290))]
    a, _ = plc.circle_from_3(*pts)
    b, _ = plc.circle_from_3(pts[2], pts[0], pts[1])
    assert a == pytest.approx(b)


def test_collinear_rim_points_are_rejected():
    with pytest.raises(ValueError, match="in a line"):
        plc.circle_from_3((0, 0), (1, 1), (2, 2))


def test_well_names_order_and_default_centre_well():
    plate = plc.PLATE_PRESETS["24-well"]
    assert plc.parse_well("b3", plate) == (1, 2)
    with pytest.raises(ValueError):
        plc.parse_well("E1", plate)                  # 24-well has rows A-D
    assert plc.print_order(["B1", "A2", "B3", "A1", "B2"], plate) == \
        ["A1", "A2", "B3", "B2", "B1"]
    assert plc.opposite_corner(plate) == "D6"
    assert plc.centre_well(plc.Placement()) == "D6"


def test_unrotated_plate_positions():
    c = plc.well_centres(_settings().placement)
    assert c["A1"] == pytest.approx((100.0, 150.0))
    assert c["A2"] == pytest.approx((119.3, 150.0))       # columns along +X
    assert c["B1"] == pytest.approx((100.0, 130.7))       # rows along -Y


def test_rotation_and_spacing_from_the_two_wells():
    """A plate turned by 3° with 0.5 % larger spacing than the preset."""
    rim, (cx, cy) = plate_points(angle=3.0, scale=1.005)
    s = _settings(rim_points=rim, centre_x=cx, centre_y=cy)
    cal = plc.calibrate(s.placement)
    assert cal.angle == pytest.approx(3.0) and cal.spacing_error == pytest.approx(0.5)
    assert cal.scale == 1.0                               # preset spacing kept by default
    s.placement.use_measured_pitch = True
    assert plc.well_centres(s.placement)["D6"] == pytest.approx((cx, cy))


def test_any_two_wells_and_orientation_come_from_the_points():
    """Plate sitting the other way round (180°), calibrated on B2 + C5."""
    plate = plc.PLATE_PRESETS["24-well"]
    t = math.radians(180.0)

    def centre(w):
        r, c = plc.parse_well(w, plate)
        lx, ly = c * 19.3, -r * 19.3
        return (200 + lx * math.cos(t) - ly * math.sin(t), 100 + lx * math.sin(t) + ly * math.cos(t))
    s = _settings(rim_well="B2", rim_points=_rim(*centre("B2")), centre_well="C5",
                  centre_x=centre("C5")[0], centre_y=centre("C5")[1])
    cal = plc.calibrate(s.placement)
    assert abs(cal.angle) == pytest.approx(180.0)
    assert plc.well_centres(s.placement)["A1"] == pytest.approx(centre("A1"))


@pytest.mark.parametrize("bad,msg", [
    (dict(wells=[]), "no wells"), (dict(wells=["Z9"]), "not a well"),
    (dict(rim_well="E1"), "not on a"), (dict(rim_points=[[0, 0], [1, 1], [2, 2]]), "in a line"),
    (dict(centre_well="A1"), "must be different"), (dict(rim_points=[[0, 0]]), "three points"),
])
def test_placement_validation(bad, msg):
    s = _settings(**bad)
    assert any(msg in m for m in s.validate())


def test_disabled_placement_is_ignored():
    s = _settings(wells=[])
    s.placement.enabled = False
    assert s.validate() == []


# --------------------------------------------------------------------------- #
#  expansion / output
# --------------------------------------------------------------------------- #
def test_each_well_gets_the_part_centred_on_it():
    s = _settings()
    p = _project(s)
    copies = plc.expand(p.toolpath, s.placement)
    centres = plc.well_centres(s.placement)
    n = len(p.toolpath)
    assert len(copies) == 4 * n
    for k, well in enumerate(plc.print_order(s.placement.wells, s.placement.plate)):
        chunk = copies[k * n:(k + 1) * n]
        (cx, cy), r = plc.part_frame(chunk)
        assert (cx, cy) == pytest.approx(centres[well], abs=1e-6)
        assert chunk[0].z == pytest.approx(5.0 + 0.2)     # floor + first layer
        assert chunk[0].well_first and chunk[-1].well_last


def test_rotated_plate_turns_the_part_too():
    rim, (cx, cy) = plate_points(angle=90.0)
    s = _settings(rim_points=rim, centre_x=cx, centre_y=cy)
    p = Project.from_cuboid(6, 2, 0.4, s)
    p.plan()
    one = plc.expand(p.toolpath, s.placement)[:len(p.toolpath)]
    xs = [q[0] for lt in one for m in lt.moves if m.extrude for q in (m.start, m.end)]
    ys = [q[1] for lt in one for m in lt.moves if m.extrude for q in (m.start, m.end)]
    assert max(xs) - min(xs) < max(ys) - min(ys)          # the long side now runs along Y


def test_travel_height_clears_the_rim_or_the_part():
    s = _settings()
    layers = _project(s).toolpath                          # part top 0.6
    assert plc.travel_z(s.placement, layers) == pytest.approx(22.0 + 3.0)   # rim higher
    s.placement.rim_z = 5.2                                # rim below the part's top
    assert plc.travel_z(s.placement, layers) == pytest.approx(5.0 + 0.6 + 3.0)


def _gcode(s):
    return "\n".join(g.text for g in render(_project(s).toolpath, s))


def test_planet_output_structure():
    s = _settings(between="pause")
    text = _gcode(s)
    assert "G92\tX0\tY0" not in text and "\nG1\tZ0\t" not in text
    assert text.count("; ===== well ") == 4
    assert text.count("G0\tZ25") == 8                      # up before and after each well
    assert text.count("\nM0") == 3                          # not after the last well
    assert re.findall(r"; ===== well (\w+)", text) == ["A1", "A2", "B2", "B1"]


def test_well_comes_back_down_to_the_first_layer_height():
    blocks = _gcode(_settings()).split("; ===== well ")[1:]
    for b in blocks:
        assert b.splitlines()[3] == "G0\tZ5.2"


def test_dwell_between_wells_and_marlin_output():
    s = _settings(between="dwell", dwell=12.5)
    s.dialect = Dialect.MARLIN_ABS_E
    text = _gcode(s)
    assert text.count("G4 S12.5 ; well dwell") == 3
    assert "G92 X0 Y0 Z0 E0" not in text
    zs = [float(m) for m in re.findall(r"^G1 Z([\d.]+) F", text, re.M)]
    assert min(zs) == pytest.approx(5.2)                    # floor + first layer


def test_tags_point_at_the_planned_layer():
    s = _settings()
    p = _project(s)
    gl = render(p.toolpath, s)
    assert {g.layer for g in gl if g.layer is not None} == set(range(len(p.toolpath)))
    mp = move_line_map(gl)
    first_well_end = next(i for i, g in enumerate(gl) if g.text.startswith("; ===== well A2"))
    assert all(line <= first_well_end for line in mp.values())


def test_fit_warning():
    s = _settings()
    assert plc.fit_warning(s.placement, _project(s).toolpath) is None
    big = Project.from_cylinder(20, 0.4, s)
    big.plan()
    assert "only 7.80 mm" in plc.fit_warning(s.placement, big.toolpath)


# --------------------------------------------------------------------------- #
#  templates stay identical to the built-ins in plate mode
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("between", ["none", "pause", "dwell"])
@pytest.mark.parametrize("drive", [DriveMode.PISTON, DriveMode.PNEUMATIC], ids=lambda d: d.value)
def test_templates_match_builtins_on_a_plate(between, drive):
    for file, dialect in (("planet_cnc.json", Dialect.PLANET_CNC),
                          ("marlin.json", Dialect.MARLIN_ABS_E)):
        s = _settings(between=between)
        s.drive, s.dialect, s.write_settings_header = drive, dialect, False
        s.travel_lift, s.start_dwell = 0.5, 0.2
        p = _project(s)
        ref = "\n".join(g.text for g in render(p.toolpath, s))
        t = dataclasses.replace(s, dialect=Dialect.CUSTOM,
                                custom_flavour=fl.load_flavour(fl.templates_dir() / file))
        got = "\n".join(g.text for g in render(p.toolpath, t))
        assert got == ref, file


# --------------------------------------------------------------------------- #
#  persistence
# --------------------------------------------------------------------------- #
def test_placement_round_trip_and_import_rebuild():
    s = _settings(between="dwell", dwell=4.0, use_measured_pitch=True)
    back = settingsio.dict_to_settings(settingsio.settings_to_dict(s))
    assert back.placement == s.placement
    s.source = {"kind": "cylinder", "width": 10.0, "depth": 10.0, "height": 0.6,
                "diameter": 8.0, "stl_path": None}
    text = _project(s).gcode_text()
    parsed, source, _f, complete = settingsio.parse_gcode_settings(text)
    assert complete and parsed.placement == s.placement
    rebuilt = Project.from_cylinder(source["diameter"], source["height"], parsed)
    rebuilt.plan()
    motion = lambda t: [l for l in t.splitlines() if l.strip() and not l.startswith(";")]
    assert motion(rebuilt.gcode_text()) == motion(text)


def test_malformed_placement_values_keep_defaults():
    pl = settingsio.dict_to_placement({"enabled": True, "floor_z": "high",
                                       "plate": {"rows": "x", "cols": 3}, "wells": ["A1"],
                                       "ref_well": "B2"})        # a key from an older version
    assert pl.enabled and pl.floor_z == 0.0 and pl.plate.rows == 4 and pl.plate.cols == 3
    assert pl.rim_well == "A1"
