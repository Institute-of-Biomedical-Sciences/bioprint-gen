"""Printing one part into several wells of a multi-well plate.

Placement is the very last step: the toolpath is planned once, in the part's
own coordinates, and `expand()` copies it into every selected well - moved so
the part's footprint is centred on the well, and turned with the plate.  The
writers then only add a short block between wells (lift above the plate, move,
descend, optional pause / dwell).

Plate frame: looking down on the plate with A1 top-left, columns (A1 -> A2)
run "right" and rows (A1 -> B1) run "down".

Calibration: four points, in the controller's work coordinates -
  1  a point on the top edge of the rim of the *rim well*   -> X, Y and the rim
     height (moves between wells clear it)
  2, 3  two more points on that rim, spread around it, any order
        -> the rim well's centre (the circle through points 1-3)
  4  the centre of a second, *centre well*, nozzle touching its floor
     -> its centre (plate rotation + spacing check) and the floor height
        (layer 1 prints at floor + the first layer's height)
The points are either typed into the app (measured beforehand) or, on Planet
CNC, asked for by the program itself at print time ("guided").
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from typing import Dict, List, Optional, Tuple

Point = Tuple[float, float]


@dataclass
class PlateSpec:
    name: str = "24-well"
    rows: int = 4
    cols: int = 6
    pitch_x: float = 19.3          # centre distance along a row (A1 -> A2)
    pitch_y: float = 19.3          # centre distance down a column (A1 -> B1)
    well_diameter: float = 15.6
    well_depth: float = 17.4       # floor to rim
    a1_x: float = 17.05            # A1 centre from the plate's left edge (drawing only)
    a1_y: float = 13.67            # A1 centre from the plate's top edge (drawing only)


# Typical values for standard SBS-footprint plates (Corning-style); vendors
# differ by fractions of a millimetre - edit them, or use the measured spacing.
PLATE_PRESETS: Dict[str, PlateSpec] = {
    "6-well": PlateSpec("6-well", 2, 3, 39.12, 39.12, 34.8, 17.4, 24.76, 23.16),
    "12-well": PlateSpec("12-well", 3, 4, 26.01, 26.01, 22.1, 17.5, 24.94, 16.79),
    "24-well": PlateSpec("24-well", 4, 6, 19.3, 19.3, 15.6, 17.4, 17.05, 13.67),
}
PLATE_SIZE = (127.76, 85.48)       # SBS footprint, mm


@dataclass
class Placement:
    enabled: bool = False
    plate: PlateSpec = field(default_factory=lambda: replace(PLATE_PRESETS["24-well"]))
    wells: List[str] = field(default_factory=list)   # e.g. ["A1", "A2"]
    # points 1-3: the rim well (point 1 also gives the rim height)
    rim_well: str = "A1"
    rim_points: List[List[float]] = field(default_factory=lambda: [[0.0, 0.0]] * 3)
    rim_z: float = 0.0
    # point 4: the centre well's centre, nozzle on its floor ("" = opposite corner)
    centre_well: str = ""
    centre_x: float = 0.0
    centre_y: float = 0.0
    floor_z: float = 0.0
    use_measured_pitch: bool = False
    clearance: float = 3.0          # above the rim (or the part) for moves between wells
    between: str = "none"           # "none" | "pause" | "dwell"
    dwell: float = 10.0             # seconds, for "dwell"
    # Planet CNC only: the program asks for the four points at print time
    # (jog + Resume) and computes the placement itself, so one file works
    # wherever the plate sits; the typed coordinates are then unused
    guided: bool = False


# --------------------------------------------------------------------------- #
#  Wells
# --------------------------------------------------------------------------- #
ROW_LETTERS = "ABCDEFGHIJKLMNOP"


def well_label(r: int, c: int) -> str:
    return f"{ROW_LETTERS[r]}{c + 1}"


def parse_well(label: str, plate: PlateSpec) -> Tuple[int, int]:
    """'B3' -> (1, 2); raises ValueError for a label not on the plate."""
    s = (label or "").strip().upper()
    if len(s) < 2 or s[0] not in ROW_LETTERS or not s[1:].isdigit():
        raise ValueError(f"'{label}' is not a well name (e.g. A1)")
    r, c = ROW_LETTERS.index(s[0]), int(s[1:]) - 1
    if not (0 <= r < plate.rows and 0 <= c < plate.cols):
        raise ValueError(f"well {s} is not on a {plate.name} plate")
    return r, c


def all_wells(plate: PlateSpec) -> List[str]:
    return [well_label(r, c) for r in range(plate.rows) for c in range(plate.cols)]


def opposite_corner(plate: PlateSpec) -> str:
    """The well farthest from A1 - the best default centre well (the longer
    the distance between the two wells, the more precise the rotation)."""
    return well_label(plate.rows - 1, plate.cols - 1)


def centre_well(pl: Placement) -> str:
    return pl.centre_well or opposite_corner(pl.plate)


def print_order(wells: List[str], plate: PlateSpec) -> List[str]:
    """Row by row, alternating direction (A1 A2 A3, B3 B2 B1, ...), so the
    head never travels back across the whole plate."""
    rc = sorted({parse_well(w, plate) for w in wells})
    return [well_label(r, c) for r, c in sorted(rc, key=lambda t: (t[0], t[1] if t[0] % 2 == 0 else -t[1]))]


# --------------------------------------------------------------------------- #
#  Calibration
# --------------------------------------------------------------------------- #
def circle_from_3(p1: Point, p2: Point, p3: Point) -> Tuple[Point, float]:
    """Centre and radius of the circle through three rim points."""
    (ax, ay), (bx, by), (cx, cy) = p1, p2, p3
    d = 2.0 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    span = max(math.dist(p1, p2), math.dist(p2, p3), math.dist(p1, p3), 1e-9)
    if abs(d) < 1e-6 * span * span:
        raise ValueError("the three rim points are (almost) in a line - "
                         "spread them around the well")
    a2, b2, c2 = ax * ax + ay * ay, bx * bx + by * by, cx * cx + cy * cy
    ux = (a2 * (by - cy) + b2 * (cy - ay) + c2 * (ay - by)) / d
    uy = (a2 * (cx - bx) + b2 * (ax - cx) + c2 * (bx - ax)) / d
    return (ux, uy), math.dist((ux, uy), p1)


@dataclass
class Calibration:
    ref_rc: Tuple[int, int]          # the rim well
    ref_centre: Point
    angle: float                     # plate rotation (A1 -> A2 direction), deg
    spacing_error: float             # measured vs the plate's spacing, %
    scale: float = 1.0               # spacing factor used (measured / plate)


def _local(dc: float, dr: float, plate: PlateSpec) -> Point:
    """Plate-frame offset (columns along +x, rows along -y) of a well step."""
    return dc * plate.pitch_x, -dr * plate.pitch_y


def _well_pair(pl: Placement):
    r1, c1 = parse_well(pl.rim_well, pl.plate)
    r2, c2 = parse_well(centre_well(pl), pl.plate)
    if (r2, c2) == (r1, c1):
        raise ValueError("the rim well and the centre well must be different wells")
    return (r1, c1), (r2, c2)


def calibrate(pl: Placement) -> Calibration:
    (r1, c1), (r2, c2) = _well_pair(pl)
    pts = [tuple(p[:2]) for p in (pl.rim_points or [])]
    if len(pts) < 3:
        raise ValueError("three points on the rim are needed")
    m1, _radius = circle_from_3(pts[0], pts[1], pts[2])
    lx, ly = _local(c2 - c1, r2 - r1, pl.plate)
    mx, my = pl.centre_x - m1[0], pl.centre_y - m1[1]
    nominal, measured = math.hypot(lx, ly), math.hypot(mx, my)
    angle = math.degrees(math.atan2(my, mx) - math.atan2(ly, lx))
    angle = (angle + 180.0) % 360.0 - 180.0
    return Calibration((r1, c1), m1, angle, 100.0 * (measured - nominal) / nominal,
                       measured / nominal if pl.use_measured_pitch else 1.0)


def well_centres(pl: Placement, cal: Optional[Calibration] = None) -> Dict[str, Point]:
    """Work-coordinate centre of every well on the plate."""
    cal = cal or calibrate(pl)
    r1, c1 = cal.ref_rc
    t = math.radians(cal.angle)
    ct, st = math.cos(t), math.sin(t)
    out = {}
    for r in range(pl.plate.rows):
        for c in range(pl.plate.cols):
            lx, ly = _local(c - c1, r - r1, pl.plate)
            lx, ly = lx * cal.scale, ly * cal.scale
            out[well_label(r, c)] = (cal.ref_centre[0] + lx * ct - ly * st,
                                     cal.ref_centre[1] + lx * st + ly * ct)
    return out


def problems(pl: Placement) -> List[str]:
    """Validation messages for an enabled placement (empty = fine)."""
    if not pl.enabled:
        return []
    p, plate = [], pl.plate
    if plate.rows < 1 or plate.cols < 1 or plate.rows > len(ROW_LETTERS):
        p.append("Plate: rows and columns must be at least 1 (and at most 16 rows).")
    if plate.rows * plate.cols < 2:
        p.append("Plate: calibration needs at least two wells on the plate.")
    if plate.pitch_x <= 0 or plate.pitch_y <= 0 or plate.well_diameter <= 0:
        p.append("Plate: well spacing and diameter must be greater than 0.")
    if pl.clearance < 0:
        p.append("Plate: travel clearance cannot be negative.")
    if not pl.wells:
        p.append("Plate: no wells selected.")
    if pl.between == "dwell" and pl.dwell < 0:
        p.append("Plate: dwell between wells cannot be negative.")
    for w in pl.wells:
        try:
            parse_well(w, plate)
        except ValueError as e:
            p.append(f"Plate: {e}.")
            break
    try:
        if pl.guided:                   # the points are measured at print time
            _well_pair(pl)
        else:
            calibrate(pl)
    except ValueError as e:
        p.append(f"Plate calibration: {e}.")
    return p


# --------------------------------------------------------------------------- #
#  Expansion
# --------------------------------------------------------------------------- #
def part_frame(layers) -> Tuple[Point, float]:
    """Centre of the part's footprint (bounding box of extruded moves) and the
    radius of the smallest circle around that centre containing them."""
    pts = [p for lt in layers for m in lt.moves if m.extrude for p in (m.start, m.end)]
    if not pts:
        return (0.0, 0.0), 0.0
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    c = ((min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0)
    return c, max(math.dist(c, p) for p in pts)


def part_top(layers) -> float:
    return max((lt.z for lt in layers), default=0.0)


def travel_z(pl: Placement, layers) -> float:
    """Height for moves between wells: clear of the rim and of the part."""
    return max(pl.rim_z, pl.floor_z + part_top(layers)) + pl.clearance


def expand(layers, pl: Placement):
    """The planned toolpath copied into each selected well, in print order.

    Each copy is moved so the part's footprint centre sits on the well centre
    and turned with the plate; z is raised by the floor height, so layer 1
    prints at floor + its own height.  Copies carry `src_index` (the original
    layer, for g-code <-> preview mapping), `well`, `well_index`,
    `well_count`, `well_first`, `well_last`.
    """
    from .model import LayerToolpath, Move
    if not layers:
        return []
    cal = calibrate(pl)
    centres = well_centres(pl, cal)
    order = print_order(pl.wells, pl.plate)
    (pcx, pcy), _r = part_frame(layers)
    t = math.radians(cal.angle)
    ct, st = math.cos(t), math.sin(t)

    def move_pt(p, wc):
        x, y = p[0] - pcx, p[1] - pcy
        return (wc[0] + x * ct - y * st, wc[1] + x * st + y * ct)

    out = []
    for k, well in enumerate(order):
        wc = centres[well]
        for i, lt in enumerate(layers):
            copy = LayerToolpath(z=round(lt.z + pl.floor_z, 6), index=lt.index,
                                 height=lt.height, extruder=lt.extruder)
            copy.moves = [Move(start=move_pt(m.start, wc), end=move_pt(m.end, wc),
                               kind=m.kind, extrude=m.extrude, radius=m.radius, ccw=m.ccw,
                               extruder=m.extruder, base_extruder=m.base_extruder)
                          for m in lt.moves]
            copy.src_index = i
            copy.well, copy.well_index, copy.well_count = well, k, len(order)
            copy.well_first, copy.well_last = i == 0, i == len(layers) - 1
            out.append(copy)
    return out


def fit_warning(pl: Placement, layers) -> Optional[str]:
    """A message when the part is wider than the wells it goes into."""
    _c, radius = part_frame(layers)
    room = pl.plate.well_diameter / 2.0
    if radius > room + 1e-9:
        return (f"the part reaches {radius:.2f} mm from its centre but a {pl.plate.name} "
                f"well is only {room:.2f} mm in radius")
    return None


# --------------------------------------------------------------------------- #
#  Guided calibration inside the g-code (Planet CNC)
# --------------------------------------------------------------------------- #
# Verified on the machine: jogging during M0 and reading #<_x>/#<_y>/#<_z>
# after G09, G52 offsets, G68 rotation (counter-clockwise for +R), M98 P<n>
# with the subprogram after M2, the tool-change G92 trick inside G52, and the
# EQ operator.  The parser does not take arithmetic inside function arguments
# (ATAN2[#<a> - #<b>, ..] fails), so every expression below is a single
# operation on plain parameters; and very long lines make Planet CNC report
# "program is empty", so messages stay short.
SUBPROGRAM = 1000


def _num(v: float) -> str:
    s = f"{v:.6f}".rstrip("0").rstrip(".")
    return s if s not in ("", "-0") else "0"


class _Expr:
    """Emits one-operation parameter assignments (`#<pc_x> = [#<a> - #<b>]`)."""

    def __init__(self):
        self.lines: List[str] = []

    @staticmethod
    def v(name: str) -> str:
        return name if name.startswith("#") else f"#<pc_{name}>"

    def const(self, name: str, value: float):
        txt = _num(abs(value))
        self.lines.append(f"{self.v(name)} = {txt}" if value >= 0
                          else f"{self.v(name)} = [0 - {txt}]")

    def op(self, name: str, a: str, sign: str, b: str):
        self.lines.append(f"{self.v(name)} = [{self.v(a)} {sign} {self.v(b)}]")

    def fn(self, name: str, func: str, *args: str):
        self.lines.append(f"{self.v(name)} = {func}[{','.join(self.v(a) for a in args)}]")

    def copy(self, name: str, src: str):
        self.lines.append(f"{self.v(name)} = {src}")


def _ask_point(e: _Expr, k: int, text: str, x: str, y: str, z: Optional[str] = None):
    """Prompt for calibration point k (of 4), then read the position."""
    e.lines += [f"(msg,Point {k} of 4: {text}. Then press Resume.)", "M0", "G09"]
    e.copy(x, "#<_x>")
    e.copy(y, "#<_y>")
    if z:
        e.copy(z, "#<_z>")


def _circle(e: _Expr):
    """Centre (acx, acy) of the circle through the rim points a1, a2, a3 -
    the formula of circle_from_3, one step at a time."""
    x = [f"a{k}x" for k in (1, 2, 3)]
    y = [f"a{k}y" for k in (1, 2, 3)]
    e.op("dy23", y[1], "-", y[2])
    e.op("dy31", y[2], "-", y[0])
    e.op("dy12", y[0], "-", y[1])
    e.op("dx32", x[2], "-", x[1])
    e.op("dx13", x[0], "-", x[2])
    e.op("dx21", x[1], "-", x[0])
    for k in range(3):                               # q_k = x_k^2 + y_k^2
        e.op("t1", x[k], "*", x[k])
        e.op("t2", y[k], "*", y[k])
        e.op(f"q{k + 1}", "t1", "+", "t2")
    # d = 2 * (x1*dy23 + x2*dy31 + x3*dy12)
    e.op("t1", x[0], "*", "dy23")
    e.op("t2", x[1], "*", "dy31")
    e.op("t3", x[2], "*", "dy12")
    e.op("t4", "t1", "+", "t2")
    e.op("t4", "t4", "+", "t3")
    e.const("two", 2.0)
    e.op("d", "two", "*", "t4")
    # Guard: with all three points at one place d is 0, and Planet CNC stops
    # with "invalid argument for '/'".  d EQ 0 is 1 or 0: a zero d becomes 1.
    e.const("zero", 0.0)
    e.op("dz", "d", "EQ", "zero")
    e.op("d", "d", "+", "dz")
    for out, terms in (("acx", ("dy23", "dy31", "dy12")), ("acy", ("dx32", "dx13", "dx21"))):
        e.op("t1", "q1", "*", terms[0])
        e.op("t2", "q2", "*", terms[1])
        e.op("t3", "q3", "*", terms[2])
        e.op("t4", "t1", "+", "t2")
        e.op("t4", "t4", "+", "t3")
        e.op(out, "t4", "/", "d")


def guided_calibration(pl: Placement, tool_change: bool, layers) -> List[str]:
    """The interactive calibration at the start of the program: four points,
    then a summary.  Leaves #<pc_acx>/#<pc_acy> (rim well centre),
    #<pc_ang> (plate angle), #<pc_ca>/#<pc_sa>, #<pc_sc> (spacing scale),
    #<pc_tz> (travel height), #<pc_z1> (first-layer height) and, with tool
    change, counter-rotated extruder offsets #<pc_r2x> ... (a G68-rotated
    frame would otherwise rotate the physical offsets too)."""
    plate = pl.plate
    rim, cw = pl.rim_well, centre_well(pl)
    (r1, c1), (r2, c2) = _well_pair(pl)
    e = _Expr()
    e.lines += [
        "; ===== plate calibration (guided) =====",
        f"G0\tZ[#<_z> + {_num(max(pl.clearance, 1.0))}] ;lift clear before calibration",
        f"(msg,Plate calibration, 4 points: 1 to 3 on the rim of well {rim}, spread "
        f"around it, any order - then 4, the centre of well {cw} on its floor. Jog to "
        f"each and press Resume.)"]
    _ask_point(e, 1, f"jog to the top edge of the rim of well {rim}. Its height "
                     f"sets the safe travel height", "a1x", "a1y", "rz")
    _ask_point(e, 2, f"another point on the rim of well {rim}, away from point 1",
               "a2x", "a2y")
    _ask_point(e, 3, f"a third point on the rim of well {rim}, spread from the others",
               "a3x", "a3y")
    _ask_point(e, 4, f"the centre of well {cw}, nozzle touching its floor. The floor "
                     f"height sets the first layer", "bcx", "bcy", "fz")
    _circle(e)
    # plate rotation and spacing from the two centres
    lx, ly = _local(c2 - c1, r2 - r1, plate)
    e.op("mx", "bcx", "-", "acx")
    e.op("my", "bcy", "-", "acy")
    e.fn("ma", "ATAN2", "my", "mx")
    e.const("na", math.degrees(math.atan2(ly, lx)))
    e.op("ang", "ma", "-", "na")
    e.op("t1", "mx", "*", "mx")
    e.op("t2", "my", "*", "my")
    e.op("t3", "t1", "+", "t2")
    e.fn("md", "SQRT", "t3")
    e.const("nd", math.hypot(lx, ly))
    e.op("ratio", "md", "/", "nd")
    e.const("hundred", 100.0)
    e.op("t1", "ratio", "*", "hundred")
    e.op("err", "t1", "-", "hundred")
    if pl.use_measured_pitch:
        e.copy("sc", "#<pc_ratio>")
    else:
        e.const("sc", 1.0)
    e.fn("ca", "COS", "ang")
    e.fn("sa", "SIN", "ang")
    # heights: layer 1 at floor + its own height; travel clear of the rim and
    # of the part: max(rim, floor + part top) + clearance, max via GT (1 / 0)
    e.const("h1", layers[0].z if layers else 0.0)
    e.op("z1", "fz", "+", "h1")
    e.const("top", part_top(layers))
    e.op("t1", "fz", "+", "top")
    e.op("gt", "t1", "GT", "rz")
    e.op("t2", "t1", "-", "rz")
    e.op("t2", "t2", "*", "gt")
    e.op("tz", "rz", "+", "t2")
    e.const("clr", pl.clearance)
    e.op("tz", "tz", "+", "clr")
    if tool_change:
        for n, (vx, vy) in ((2, ("#102", "#103")), (3, ("#104", "#105"))):
            e.op("t1", vx, "*", "ca")
            e.op("t2", vy, "*", "sa")
            e.op(f"r{n}x", "t1", "+", "t2")
            e.op("t1", vy, "*", "ca")
            e.op("t2", vx, "*", "sa")
            e.op(f"r{n}y", "t1", "-", "t2")
    scale = ", measured spacing used" if pl.use_measured_pitch else ""
    summary = (f"well {rim} centre X=#<pc_acx> Y=#<pc_acy>, plate angle #<pc_ang> deg, "
               f"spacing off by #<pc_err> percent{scale}, rim Z=#<pc_rz>, floor Z=#<pc_fz>")
    e.lines += [f"(print,Calibrated: {summary})",
                f"(msg,Calibrated: {summary}. Resume to print, Stop to cancel.)",
                "M0"]
    return e.lines


def guided_well_calls(pl: Placement, layers_local) -> List[Tuple[str, List[str]]]:
    """[(well, lines)] - for each well: its centre from the calibration
    variables, lift, frame (G52 + G68), descend, call the print subprogram,
    restore the frame, lift, then the pause / dwell."""
    plate = pl.plate
    r1, c1 = parse_well(pl.rim_well, plate)
    order = print_order(pl.wells, plate)
    first = layers_local[0].moves[0].end if layers_local and layers_local[0].moves else (0, 0)
    up = "G0\tZ#<pc_tz>"
    out = []
    for k, well in enumerate(order):
        r, c = parse_well(well, plate)
        lx, ly = _local(c - c1, r - r1, plate)
        e = _Expr()
        e.lines.append(f"; ===== well {well} ({k + 1}/{len(order)}) =====")
        e.const("lx", lx)
        e.const("ly", ly)
        for out_name, (a, sgn, b), base in (("wx", ("ca", "-", "sa"), "acx"),
                                            ("wy", ("sa", "+", "ca"), "acy")):
            e.op("t1", "lx", "*", a)
            e.op("t2", "ly", "*", b)
            e.op("t3", "t1", sgn, "t2")
            e.op("t4", "sc", "*", "t3")
            e.op(out_name, base, "+", "t4")
        e.lines += [up, "G52\tX#<pc_wx>\tY#<pc_wy>", "G68\tX0\tY0\tR#<pc_ang>",
                    f"G0\tX{_num(first[0])}\tY{_num(first[1])}", "G0\tZ#<pc_z1>",
                    f"M98\tP{SUBPROGRAM}", "G69", "G52.1", up]
        if k + 1 < len(order):
            if pl.between == "pause":
                e.lines += [f"(msg,Well {well} done - press Resume to continue)", "M0"]
            elif pl.between == "dwell":
                e.lines.append(f"G4\tP{_num(pl.dwell)} ;well dwell")
        out.append((well, e.lines))
    return out


def localize(layers):
    """The planned layers moved so the part's footprint centre is at (0, 0) -
    the print subprogram is written in this frame (G52/G68 place it)."""
    from .model import LayerToolpath, Move
    (pcx, pcy), _r = part_frame(layers)
    out = []
    for lt in layers:
        copy = LayerToolpath(z=lt.z, index=lt.index, height=lt.height, extruder=lt.extruder)
        copy.moves = [Move(start=(m.start[0] - pcx, m.start[1] - pcy),
                           end=(m.end[0] - pcx, m.end[1] - pcy), kind=m.kind,
                           extrude=m.extrude, radius=m.radius, ccw=m.ccw,
                           extruder=m.extruder, base_extruder=m.base_extruder)
                      for m in lt.moves]
        out.append(copy)
    return out
