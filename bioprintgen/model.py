"""Core data structures shared across the whole pipeline.

The pipeline is:  geometry/slicer -> Layer(regions)  ->  infill + perimeters
-> Toolpath (ordered Moves)  ->  gcode writer -> text.

Everything downstream of slicing works purely on 2D polygons (shapely) plus a
z height, which keeps the STL path and the primitive path (cuboid/cylinder)
identical from the infill stage onward.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

from .placement import Placement


# --------------------------------------------------------------------------- #
#  Enums
# --------------------------------------------------------------------------- #
class Dialect(str, Enum):
    PLANET_CNC = "planet_cnc"      # matches the Vitaprint reference generator
    MARLIN_ABS_E = "marlin_abs_e"  # generic Marlin, absolute extrusion (M82)
    CUSTOM = "custom"              # user-defined template flavour (see gcode.flavour)


class DriveMode(str, Enum):
    PNEUMATIC = "pneumatic"        # valve on/off (M63) - no metered E
    PISTON = "piston"              # metered volumetric extrusion (A/B/C or E)


class InfillType(str, Enum):
    RECTILINEAR_CONNECTED = "rectilinear_connected"
    RECTILINEAR_SEPARATE = "rectilinear_separate"
    GYROID = "gyroid"


def pattern_id(v) -> str:
    """Infill pattern id as a plain string.  Built-ins are `InfillType` members
    (str enums, so they compare equal to their id); user patterns from the
    patterns folder are plain strings such as "schwarz_p"."""
    return str(getattr(v, "value", v))


def parse_pattern(v):
    """An `InfillType` for a built-in id, otherwise the id string itself."""
    try:
        return InfillType(pattern_id(v))
    except ValueError:
        return pattern_id(v)


def _pattern_kind(v) -> Optional[str]:
    from .infill import patterns          # lazy: the registry imports this module
    return patterns.kind_of(v)


class MoveKind(str, Enum):
    TRAVEL = "travel"      # non-extruding reposition
    PERIMETER = "perimeter"
    INFILL = "infill"
    SKIRT = "skirt"


# --------------------------------------------------------------------------- #
#  Sections (variable layer height / per-extruder z ranges)
# --------------------------------------------------------------------------- #
@dataclass
class LayerHeightSection:
    """A z-range [z_start, z_end] that overrides the default layer height."""
    z_start: float
    z_end: float
    height: float


@dataclass
class ToolLineRange:
    """A range of generated g-code lines [start_line, end_line] (1-based,
    inclusive, referring to the *clean* generation) printed with a specific
    extruder (1/2/3).  Tool changes are placed by line position, not by z."""
    start_line: int
    end_line: int
    extruder: int = 2


@dataclass
class InfillSection:
    """A z-range [z_start, z_end] printed with its own infill pattern/density.

    Density is a percentage so it means the same for every pattern; 0 keeps the
    main infill's density (converted to the equivalent percentage)."""
    z_start: float
    z_end: float
    infill_type: InfillType = InfillType.GYROID
    percent: float = 0.0


COMPONENT_SHAPES = ("cuboid", "cylinder", "stl")
COMPONENT_OPERATIONS = ("add", "subtract")
CYLINDER_AXES = ("vertical", "horizontal")
WALLS_MERGE = 0      # Component.walls: no walls of its own, part of the main body


@dataclass
class Component:
    """An extra shape added to the part, with its own infill / extruder / walls.

    Placed by its *centre* (x, y) in the print frame and its bottom z; for a
    cylinder `size_x` is the diameter.  Where shapes overlap, the component
    higher in `PrintSettings.components` owns the area (the main shape is
    lowest).  `walls` is the number of walls between the component and the
    rest of the part (and round its exposed edge); 0 = `WALLS_MERGE`, joined
    seamlessly to the main body, whose walls then go round both.  (Files from
    the first version used -1 for merge; anything <= 0 means merge.)
    """
    shape: str = "cuboid"
    size_x: float = 4.0
    size_y: float = 4.0
    height: float = 2.0
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    rotation: float = 0.0          # degrees about Z (cuboid)
    extruder: int = 1
    pattern: str = ""              # "" = the main infill pattern
    percent: float = 0.0           # 0 = the main infill density
    walls: int = WALLS_MERGE
    name: str = ""
    enabled: bool = True
    # "subtract" removes its area from everything lower in the list (a void /
    # channel); extruder, pattern, % and walls then don't apply
    operation: str = "add"
    # cylinders only: "horizontal" lies along the rotation direction (0° = +X),
    # with size_x = diameter and size_y = length; z is its bottom
    axis: str = "vertical"
    # shape "stl": a mesh file, scaled (%) and turned about X, then Y, then Z
    # (`rotation`); its bounding-box centre goes to (x, y), its bottom to z
    stl_path: str = ""
    scale: float = 100.0
    rot_x: float = 0.0
    rot_y: float = 0.0

    @property
    def subtract(self) -> bool:
        return self.operation == "subtract"

    @property
    def horizontal(self) -> bool:
        return self.shape == "cylinder" and self.axis == "horizontal"

    def z_top(self) -> float:
        """Top of a primitive (an STL's height comes from its mesh - see
        geometry.components.component_top)."""
        return self.z + (self.size_x if self.horizontal else self.height)

    def label(self, index: int) -> str:
        if self.shape == "stl":
            fname = self.stl_path.replace("\\", "/").rsplit("/", 1)[-1] or "no file"
            size = f"{fname} {self.scale:g}%"
        elif self.horizontal:
            size = f"Ø{self.size_x:g} ↔{self.size_y:g}"
        elif self.shape == "cylinder":
            size = f"Ø{self.size_x:g}×{self.height:g}"
        else:
            size = f"{self.size_x:g}×{self.size_y:g}×{self.height:g}"
        op = "− " if self.subtract else ""
        return op + (self.name or f"{index + 1} · {self.shape} {size}") + \
            ("" if self.enabled else " (off)")


# --------------------------------------------------------------------------- #
#  Settings
# --------------------------------------------------------------------------- #
# mm of gyroid section line per mm^2, per mm of period (measured on the generator
# over a full period in z; constant across periods). Used for percent-mode infill.
GYROID_LINE_DENSITY = 2.494

@dataclass
class PrintSettings:
    # --- shape / model ---
    layer_height: float = 0.2
    first_layer_height: Optional[float] = None   # None -> use layer_height
    # z-range overrides for layer height; any z not covered uses layer_height
    layer_sections: List[LayerHeightSection] = field(default_factory=list)

    # --- extrusion geometry ---
    line_width: float = 0.41            # nozzle/needle inner effective track width
    strand_spacing: float = 1.0         # centre-to-centre distance between infill strands
    infill_angle: float = 0.0           # base angle of layer 0 strands (deg)
    layer_rotation: float = 90.0        # "x-to-y angle": rotation added each layer (deg)

    infill_type: InfillType = InfillType.RECTILINEAR_CONNECTED
    gyroid_period: float = 6.0          # mm, spatial period of the gyroid cell
    # how infill density is specified: "spacing" (strand_spacing / gyroid_period
    # as given) or "percent" (infill_percent of the area, derived from line_width)
    infill_mode: str = "spacing"
    infill_percent: float = 40.0
    # z-ranges with their own pattern/density; anything uncovered uses the above
    infill_sections: List[InfillSection] = field(default_factory=list)
    # extra shapes with their own infill / extruder / walls (see Component)
    components: List[Component] = field(default_factory=list)
    # print the part into the wells of a multi-well plate (see placement.py)
    placement: Placement = field(default_factory=Placement)
    perimeters: int = 1                 # number of contour walls before infill
    # cycle each layer's start point (perimeter seam + infill start) around the
    # four bounding-box corners, so start/stop artefacts don't stack up
    rotate_start: bool = True

    # --- speeds ---
    print_speed: float = 500.0          # mm/min  (matches reference feedrate)
    travel_speed: float = 1600.0        # mm/min
    z_speed: float = 300.0              # mm/min

    # --- extrusion model ---
    dialect: Dialect = Dialect.PLANET_CNC
    # custom template flavour (a gcode.flavour.FlavourTemplate) used when
    # dialect == CUSTOM.  Kept as `object` here to avoid a circular import.
    custom_flavour: Optional[object] = None
    drive: DriveMode = DriveMode.PISTON
    extruder_index: int = 1             # 1/2/6 -> A/B/C on Planet CNC piston
    ext_per_10mm: float = 0.1           # piston: plunger mm per 10 mm of travel (reference "E")
    ramp: float = 0.05                  # priming amount at start of a bar
    flow_control: bool = False          # Planet CNC jogpot live flow multiplier
    valve_value: float = 1.0            # pneumatic: E argument scale for M63 (x10 as in ref)

    # marlin volumetric: extrusion cross-section / filament area ratio.
    # E_delta = length * line_width * layer_height / filament_area
    filament_area: float = 1.0          # mm^2 (1.0 -> volumetric mm^3 tracked directly)

    # --- tool change / multiple extruders ---
    tool_change_enabled: bool = False
    # physical XY offset (mm) of extruders 2 and 3 relative to extruder 1 (0,0).
    extruder2_offset: Tuple[float, float] = (0.0, 0.0)
    extruder3_offset: Tuple[float, float] = (0.0, 0.0)
    # g-code line ranges assigned to a given extruder (see ToolLineRange).
    # Anything outside every range stays on extruder 1.
    tool_line_ranges: List[ToolLineRange] = field(default_factory=list)

    # --- flow control / start-stop behaviour ---
    flow_start_ramp: float = 0.0       # piston: prime the metered axis at each stroke start
    flow_end_retract: float = 0.0      # piston: retract the metered axis at each stroke end
    start_dwell: float = 0.0            # seconds to pause (G4) each time extrusion starts
    end_dwell: float = 0.0             # seconds to pause (G4) after a stroke ends (post-retract)
    coast_distance: float = 0.0        # mm before a stroke's end to stop extruding (coast)
    travel_lift: float = 0.0           # mm to hop up (relative) before every travel, then back down

    # --- start / end ---
    zero_xy_at_start: bool = True       # emit G92 X0 Y0
    safe_z: float = 2.0                 # lift after print
    skirt: bool = False
    skirt_distance: float = 2.0
    skirt_loops: int = 1
    # verbatim user g-code injected after the header / before the footer
    start_gcode: str = ""
    end_gcode: str = ""
    # write a commented block of all settings at the top of the file
    write_settings_header: bool = True
    # line ending used when exporting: "crlf" (default, what a Windows export has
    # always produced) or "lf".  Pinned explicitly so the exported file is
    # byte-identical no matter which OS generated it.
    gcode_line_ending: str = "crlf"

    def line_terminator(self) -> str:
        return "\n" if str(self.gcode_line_ending).lower() in ("lf", "\n") else "\r\n"

    # --- planning ---
    minimize_crossings: bool = True
    # where the geometry came from (shape + dimensions / STL path); written into
    # the exported settings block so "Import g-code" can rebuild the part
    source: Dict = field(default_factory=dict)

    # -- infill density --
    def percent_mode(self) -> bool:
        return str(self.infill_mode).lower() == "percent"

    def effective_spacing(self) -> float:
        """Strand centre spacing actually used by rectilinear infill."""
        if self.percent_mode() and self.infill_percent > 0:
            return self.line_width / (self.infill_percent / 100.0)
        return self.strand_spacing

    def is_levelset(self) -> bool:
        """Gyroid or an equation pattern: sized by a period, not a spacing."""
        if self.infill_type == InfillType.GYROID:
            return True
        if isinstance(self.infill_type, InfillType):
            return False
        return _pattern_kind(self.infill_type) == "levelset"

    def line_density(self) -> float:
        """Line density constant k of a level-set pattern (period = k*w/fraction)."""
        if self.infill_type == InfillType.GYROID or isinstance(self.infill_type, InfillType):
            return GYROID_LINE_DENSITY
        from .infill import patterns
        return patterns.line_density(self.infill_type)

    def effective_gyroid_period(self) -> float:
        """Level-set (gyroid / equation pattern) period actually used.  In
        percent mode it is chosen so the laid-down line covers the same area
        fraction as rectilinear at that % (measured: a gyroid section has
        GYROID_LINE_DENSITY / period mm of line per mm^2; equation patterns are
        measured when they load)."""
        if self.percent_mode() and self.infill_percent > 0:
            return self.line_density() * self.line_width / (self.infill_percent / 100.0)
        return self.gyroid_period

    def main_density_fraction(self) -> float:
        """Area fraction covered by the *main* infill, whichever way it is set."""
        w = self.line_width
        if self.percent_mode():
            return self.infill_percent / 100.0
        if self.is_levelset():
            return self.line_density() * w / self.gyroid_period if self.gyroid_period > 0 else 0.0
        return w / self.strand_spacing if self.strand_spacing > 0 else 0.0

    def infill_section_for(self, z_bottom: float) -> Optional["InfillSection"]:
        """Section covering a layer whose bottom sits at `z_bottom` (first match
        wins), using the same convention as the layer-height sections."""
        for sec in self.infill_sections:
            lo, hi = min(sec.z_start, sec.z_end), max(sec.z_start, sec.z_end)
            if lo - 1e-9 <= z_bottom < hi - 1e-9:
                return sec
        return None

    def for_layer(self, z_bottom: float) -> "PrintSettings":
        """Settings to plan one layer with: the main settings, or a copy with the
        pattern and density of the infill section covering that layer."""
        sec = self.infill_section_for(z_bottom)
        if sec is None:
            return self
        frac = sec.percent / 100.0 if sec.percent > 0 else self.main_density_fraction()
        return replace(self, infill_type=sec.infill_type,
                       infill_mode="percent", infill_percent=frac * 100.0)

    def for_component(self, c: Optional["Component"]) -> "PrintSettings":
        """Settings for a component's infill: its own pattern and %, falling
        back to these (already per-layer) settings for whatever it leaves at
        "same as main"."""
        if c is None or (not c.pattern and c.percent <= 0):
            return self
        pat = parse_pattern(c.pattern) if c.pattern else self.infill_type
        frac = c.percent / 100.0 if c.percent > 0 else self.main_density_fraction()
        return replace(self, infill_type=pat, infill_mode="percent",
                       infill_percent=frac * 100.0)

    def component_extruders(self) -> set:
        return {c.extruder for c in self.components if c.enabled and not c.subtract}

    def eff_first_layer_height(self) -> float:
        return self.first_layer_height if self.first_layer_height else self.layer_height

    # -- variable layer height / extruder lookups --
    def height_for_z(self, z: float) -> float:
        """Layer height applicable to a layer whose bottom sits at `z`.

        First match among `layer_sections` wins; otherwise the default height.
        """
        for sec in self.layer_sections:
            lo, hi = min(sec.z_start, sec.z_end), max(sec.z_start, sec.z_end)
            if lo - 1e-9 <= z < hi - 1e-9:
                return sec.height
        return self.layer_height

    def validate(self) -> List[str]:
        """Human-readable problems that would make generation fail or produce
        nonsense.  Empty list == good to go.

        Values normally come from spin boxes with sane ranges, but
        `default_settings.json` is hand-edited and the pipeline is usable from
        scripts, so both routes need checking.
        """
        p: List[str] = []
        if self.layer_height <= 0:
            p.append("Layer height must be greater than 0.")
        if self.first_layer_height is not None and self.first_layer_height < 0:
            p.append("First layer height cannot be negative.")
        if self.line_width <= 0:
            p.append("Nozzle diameter must be greater than 0.")
        if self.percent_mode():
            if not (0 < self.infill_percent <= 100):
                p.append("Infill % must be between 0 and 100.")
        else:
            if self.strand_spacing <= 0:
                p.append("Strand spacing must be greater than 0.")
            if self.is_levelset() and self.gyroid_period <= 0:
                p.append("Period must be greater than 0.")
        if self.print_speed <= 0:
            p.append("Print speed must be greater than 0.")
        if self.travel_speed <= 0:
            p.append("Travel speed must be greater than 0.")
        if self.z_speed <= 0:
            p.append("Layer change speed must be greater than 0.")
        if int(self.perimeters) < 0:
            p.append("Perimeters cannot be negative.")
        if self.coast_distance < 0:
            p.append("Coast distance cannot be negative.")
        if self.start_dwell < 0:
            p.append("Start dwell cannot be negative.")
        if self.end_dwell < 0:
            p.append("End dwell cannot be negative.")
        if self.travel_lift < 0:
            p.append("Travel safe height cannot be negative.")
        if self.filament_area <= 0:
            p.append("Filament area must be greater than 0.")
        for i, sec in enumerate(self.layer_sections, 1):
            if sec.height <= 0:
                p.append(f"Layer-height section {i}: height must be greater than 0.")
        if _pattern_kind(self.infill_type) is None:
            p.append(f"Infill pattern '{pattern_id(self.infill_type)}' is not available "
                     "(not in the patterns folder, or it failed to load).")
        for i, sec in enumerate(self.infill_sections, 1):
            if _pattern_kind(sec.infill_type) is None:
                p.append(f"Infill section {i}: pattern '{pattern_id(sec.infill_type)}' "
                         "is not available.")
            if not (0 <= sec.percent <= 100):
                p.append(f"Infill section {i}: % must be between 0 and 100 "
                         "(0 = same density as the main infill).")
        from .placement import problems as placement_problems
        p += placement_problems(self.placement)
        if self.placement.enabled and self.placement.guided \
                and self.dialect != Dialect.PLANET_CNC:
            p.append("Plate: guided calibration in the g-code needs the Planet CNC "
                     "flavour - use typed coordinates for other flavours.")
        for i, c in enumerate(self.components, 1):
            if not c.enabled:
                continue
            what = f"Component {i}"
            if c.shape not in COMPONENT_SHAPES:
                p.append(f"{what}: unknown shape '{c.shape}'.")
            if c.operation not in COMPONENT_OPERATIONS:
                p.append(f"{what}: operation must be 'add' or 'subtract'.")
            if c.shape == "cylinder" and c.axis not in CYLINDER_AXES:
                p.append(f"{what}: axis must be 'vertical' or 'horizontal'.")
            if c.shape == "stl":
                if not c.stl_path:
                    p.append(f"{what}: choose an STL file.")
                elif not Path(c.stl_path).is_file():
                    p.append(f"{what}: STL file not found: {c.stl_path}")
                if c.scale <= 0:
                    p.append(f"{what}: scale must be greater than 0 %.")
            elif c.size_x <= 0 or (c.shape == "cuboid" and c.size_y <= 0) or \
                    (c.horizontal and c.size_y <= 0) or \
                    (not c.horizontal and c.height <= 0):
                p.append(f"{what}: size and height must be greater than 0.")
            if c.subtract:
                continue                # a void has no extruder / infill / walls
            if c.z < 0:
                p.append(f"{what}: Z start cannot be negative.")
            if c.extruder not in (1, 2, 3):
                p.append(f"{what}: extruder must be 1, 2 or 3.")
            elif c.extruder != 1 and not self.tool_change_enabled:
                p.append(f"{what} uses extruder {c.extruder}: turn on Tool change "
                         "(Printing process) so its offset is applied.")
            if not (0 <= c.percent <= 100):
                p.append(f"{what}: infill % must be between 0 and 100 (0 = main density).")
            if int(c.walls) < -1:
                p.append(f"{what}: walls must be 'merge' (0) or a number of walls.")
            if c.pattern and _pattern_kind(c.pattern) is None:
                p.append(f"{what}: pattern '{c.pattern}' is not available.")
        return p

    def offset_for_extruder(self, extruder: int) -> Tuple[float, float]:
        if extruder == 2:
            return self.extruder2_offset
        if extruder == 3:
            return self.extruder3_offset
        return (0.0, 0.0)


# --------------------------------------------------------------------------- #
#  Layer-stack z construction (shared by primitives + STL slicer)
# --------------------------------------------------------------------------- #
MAX_LAYERS = 100_000
     # sanity cap so a degenerate height can't exhaust memory


def build_z_levels(total_height: float, settings: PrintSettings
                   ) -> List[Tuple[float, float]]:
    """Return [(z_top, layer_height), ...] honouring variable-height sections.

    The first layer always uses `eff_first_layer_height()`; every layer above it
    takes the height applicable at its own bottom z (see `height_for_z`).
    """
    fh = settings.eff_first_layer_height()
    if fh <= 0 or settings.layer_height <= 0:
        # would never advance -> guard against an unbounded loop (a hand-edited
        # default_settings.json can get here even though the GUI cannot).
        raise ValueError("Layer height must be greater than 0.")
    levels: List[Tuple[float, float]] = []
    z = fh
    levels.append((round(z, 6), fh))
    while len(levels) < MAX_LAYERS:
        h = settings.height_for_z(z)
        if h <= 0:                       # malformed section -> fall back
            h = settings.layer_height
        if z + h > total_height + 1e-9:
            break
        z += h
        levels.append((round(z, 6), h))
    return levels


# --------------------------------------------------------------------------- #
#  Geometry containers
# --------------------------------------------------------------------------- #
@dataclass
class Layer:
    """A sliced layer: a z height and one or more solid regions (shapely).

    `regions` are shapely Polygons/MultiPolygon already in the print XY frame.
    """
    z: float
    index: int
    regions: object            # shapely (Multi)Polygon
    height: float              # this layer's own height (first layer may differ)
    extruder: int = 1          # active extruder (tool) for this layer
    # with components: who owns which area (None = a plain single-part layer)
    parts: Optional[List["LayerPart"]] = None


@dataclass
class LayerPart:
    """One owner's share of a composed layer."""
    component: Optional[int]   # index into PrintSettings.components; None = main shape
    region: object             # area it owns here (overlaps resolved by priority);
                               # for a void: the material it actually removes
    shape: object              # its full cross-section (for preview outlines)
    void: bool = False         # a subtract component


@dataclass
class Move:
    """A single straight toolpath segment from `start` to `end`.

    Arc moves (used by the Planet CNC cylinder path) carry an optional radius;
    `ccw` selects G3 vs G2.  For the generic infill/perimeter path arcs are not
    used, keeping the drag-edit model a pure polyline.
    """
    start: Tuple[float, float]
    end: Tuple[float, float]
    kind: MoveKind
    extrude: bool
    radius: Optional[float] = None
    ccw: bool = True
    extruder: int = 1          # active tool for this move (set by line-range tool changes)
    base_extruder: int = 1     # tool before line-range overrides (a component's extruder)

    @property
    def length(self) -> float:
        return float(np.hypot(self.end[0] - self.start[0], self.end[1] - self.start[1]))


@dataclass
class LayerToolpath:
    z: float
    index: int
    height: float
    extruder: int = 1
    moves: List[Move] = field(default_factory=list)
    # component outlines for the preview: [(points, extruder)]
    outlines: List[Tuple[list, int]] = field(default_factory=list)
    # set on the copies placement.expand() makes for multi-well printing
    src_index: Optional[int] = None    # the planned layer this copy comes from
    well: str = ""
    well_index: int = 0
    well_count: int = 0
    well_first: bool = False
    well_last: bool = False
    travel_z: float = 0.0              # height for the move to the next well

    def polylines(self) -> List[List[Tuple[float, float]]]:
        """Group consecutive extruding moves into polylines for preview."""
        lines: List[List[Tuple[float, float]]] = []
        cur: List[Tuple[float, float]] = []
        for m in self.moves:
            if m.extrude:
                if not cur:
                    cur = [m.start, m.end]
                elif cur[-1] == m.start:
                    cur.append(m.end)
                else:
                    lines.append(cur)
                    cur = [m.start, m.end]
            else:
                if cur:
                    lines.append(cur)
                    cur = []
        if cur:
            lines.append(cur)
        return lines


@dataclass
class Toolpath:
    layers: List[LayerToolpath] = field(default_factory=list)

    def bounds(self) -> Tuple[float, float, float, float]:
        xs, ys = [], []
        for lt in self.layers:
            for m in lt.moves:
                xs += [m.start[0], m.end[0]]
                ys += [m.start[1], m.end[1]]
        if not xs:
            return (0.0, 0.0, 0.0, 0.0)
        return (min(xs), min(ys), max(xs), max(ys))
