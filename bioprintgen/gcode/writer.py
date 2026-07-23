"""G-code emission.

Three flavours:

* PLANET_CNC  - matches the Vitaprint reference generator: `%` delimiters,
  tab-separated fields, PlanetCNC expression variables for relative Z
  (`Z[#<_z> +h]`) and metered piston axes (`A[#<_a> +da]`), and M63 digital
  valve control for pneumatic drive.  Multi-extruder tool changes are done with
  offset variables (#102..#105) + a G92 frame shift (see `PlanetCNCWriter`).

* MARLIN_ABS_E - generic Marlin: G21/G90/M82, absolute extrusion with a running
  E accumulator (volumetric), G0 travels, absolute Z per layer, T0/T1/T2 tool
  changes with G10 L1 tool offsets.

* CUSTOM - a user-defined `flavour.FlavourTemplate`: per-action text templates
  filled in per move.

Every emitted line is a GLine carrying an optional (layer, move) tag so the GUI
can map a selected toolpath segment to its text line and back.  On top of the
machine header each file can carry a commented settings block, user start
g-code, and user end g-code.
"""
from __future__ import annotations

from dataclasses import dataclass, fields
from typing import List, Optional, Tuple

from ..model import (
    LayerToolpath, Move, MoveKind, PrintSettings, Dialect, DriveMode,
)
from .flavour import FlavourTemplate, fill


@dataclass
class GLine:
    text: str
    layer: Optional[int] = None
    move: Optional[int] = None
    kind: str = "code"   # header | layer | move | travel | valve | toolchange
                         # | comment | startgcode | endgcode | footer | blank


def _fmt(v: float, nd: int = 4) -> str:
    s = f"{v:.{nd}f}"
    if "." in s:                      # only trim fractional zeros
        s = s.rstrip("0").rstrip(".")
    return s if s not in ("", "-0", "-") else "0"


def _wrap(strs, kind: str, layer=None, move=None) -> List[GLine]:
    return [GLine(s, layer=layer, move=move, kind=kind) for s in strs]


def _user_lines(text: str) -> List[str]:
    if not text or not text.strip():
        return []
    return text.replace("\r\n", "\n").split("\n")


# --------------------------------------------------------------------------- #
#  Flow control (start dwell + end coast)
# --------------------------------------------------------------------------- #
@dataclass
class _Emit:
    mi: int            # original move index (keeps GLine tags stable)
    move: Move         # the (possibly split) piece to emit
    stroke_start: bool  # first extruding piece of a stroke (prime ramp / dwell go here)
    coast: bool        # non-extruding tail of a stroke (moves at print speed)
    stroke_end: bool = False  # last piece of a stroke (end retract goes here)


def _as_coast(m: Move) -> Move:
    return Move(start=m.start, end=m.end, kind=m.kind, extrude=False,
                radius=m.radius, ccw=m.ccw, extruder=m.extruder)


def _split_move(m: Move, t: float):
    """Split a move into an extruding head [0, t] and a coasting tail [t, len]."""
    L = m.length
    if L <= 1e-12:
        return None, _as_coast(m)
    r = max(0.0, min(1.0, t / L))
    p = (m.start[0] + (m.end[0] - m.start[0]) * r,
         m.start[1] + (m.end[1] - m.start[1]) * r)
    head = Move(start=m.start, end=p, kind=m.kind, extrude=True,
                radius=None, ccw=m.ccw, extruder=m.extruder)
    tail = Move(start=p, end=m.end, kind=m.kind, extrude=False,
                radius=None, ccw=m.ccw, extruder=m.extruder)
    return head, tail


def flow_emits(lt: LayerToolpath, s: PrintSettings) -> List[_Emit]:
    """Expand a layer's moves into emission pieces honouring the flow settings:
    a start dwell at each stroke start and an end coast (extrusion off `d` mm
    before a stroke ends).  Original move indices are preserved on every piece so
    g-code line <-> toolpath-segment mapping (and tool-change ranges) still work.
    """
    moves = lt.moves
    n = len(moves)
    coast_d = max(0.0, s.coast_distance)
    out: List[_Emit] = []
    i = 0
    while i < n:
        if not moves[i].extrude:
            out.append(_Emit(i, moves[i], False, False))
            i += 1
            continue
        # maximal run of consecutive extruding moves = one stroke
        j = i
        while j < n and moves[j].extrude:
            j += 1
        run = list(range(i, j))
        run_len = sum(moves[k].length for k in run)

        coast_full = set()      # move indices emitted entirely as coast
        split_at = {}           # move index -> extrude length before the coast tail
        if coast_d > 0:
            if coast_d >= run_len - 1e-9:
                coast_full = set(run)          # whole stroke coasts
            else:
                remaining = coast_d
                for k in reversed(run):
                    if remaining <= 1e-9:
                        break
                    L = moves[k].length
                    if L <= remaining + 1e-9:
                        coast_full.add(k)
                        remaining -= L
                    else:
                        split_at[k] = L - remaining
                        remaining = 0.0

        whole_coast = len(coast_full) == len(run)
        start_pending = not whole_coast     # mark the first actually-extruding piece
        run_first = len(out)
        for k in run:
            m = moves[k]
            if k in coast_full:
                out.append(_Emit(k, _as_coast(m), False, True))
            elif k in split_at:
                head, tail = _split_move(m, split_at[k])
                if head is not None:
                    out.append(_Emit(k, head, start_pending, False))
                    start_pending = False
                out.append(_Emit(k, tail, False, True))
            else:
                out.append(_Emit(k, m, start_pending, False))
                start_pending = False
        # mark the last piece of a stroke that actually extruded (for end retract)
        if not whole_coast and len(out) > run_first:
            out[-1].stroke_end = True
        i = j
    return out


# --------------------------------------------------------------------------- #
#  Settings comment block
# --------------------------------------------------------------------------- #
_HEADER_SKIP = {"custom_flavour", "layer_sections", "tool_line_ranges",
                "start_gcode", "end_gcode"}


def settings_header_lines(s: PrintSettings, cp: str = ";") -> List[str]:
    """A commented dump of the settings, for reproducing the print later."""
    lines = [f"{cp} ===== BioprintGEN settings ====="]
    for f in fields(s):
        if f.name in _HEADER_SKIP:
            continue
        v = getattr(s, f.name)
        if hasattr(v, "value"):          # Enum -> its value
            v = v.value
        lines.append(f"{cp} {f.name} = {v}")
    if s.layer_sections:
        lines.append(f"{cp} layer_sections:")
        for sec in s.layer_sections:
            lines.append(f"{cp}   z[{sec.z_start} .. {sec.z_end}] height={sec.height}")
    if s.tool_line_ranges:
        lines.append(f"{cp} tool_line_ranges (clean-baseline lines):")
        for r in s.tool_line_ranges:
            lines.append(f"{cp}   lines {r.start_line}..{r.end_line} -> extruder {r.extruder}")
    if s.custom_flavour is not None:
        lines.append(f"{cp} custom_flavour = {getattr(s.custom_flavour, 'name', '?')}")
    lines.append(f"{cp} ===============================")
    return lines


def _preamble(s: PrintSettings, cp: str, layers: List[LayerToolpath]) -> List[GLine]:
    """User start g-code, shared by all writers (emitted after the machine header)."""
    out: List[GLine] = []
    if s.start_gcode.strip():
        out += _wrap([f"{cp} --- start g-code ---"], "comment")
        out += _wrap(_user_lines(s.start_gcode), "startgcode")
        out.append(GLine("", kind="blank"))
    return out


def _postamble(s: PrintSettings, cp: str) -> List[GLine]:
    """User end g-code, shared by all writers (emitted before the footer)."""
    if not s.end_gcode.strip():
        return []
    out = _wrap([f"{cp} --- end g-code ---"], "comment")
    out += _wrap(_user_lines(s.end_gcode), "endgcode")
    out.append(GLine("", kind="blank"))
    return out


def _settings_tail(s: PrintSettings, cp: str) -> List[GLine]:
    """The commented settings dump, placed at the end of the file."""
    if not s.write_settings_header:
        return []
    out = [GLine("", kind="blank")]
    out += _wrap(settings_header_lines(s, cp), "comment")
    return out


# --------------------------------------------------------------------------- #
#  Planet CNC
# --------------------------------------------------------------------------- #
class PlanetCNCWriter:
    # metered piston axis per extruder (tool 1/2/3 -> A/B/C, matching #<_a/_b/_c>)
    AXIS = {1: ("A", "_a"), 2: ("B", "_b"), 3: ("C", "_c"), 6: ("C", "_c")}
    # offset variable pairs (X, Y) per extruder
    OFFVAR = {2: ("#102", "#103"), 3: ("#104", "#105")}

    def __init__(self, settings: PrintSettings):
        self.s = settings
        self.axis_letter, self.axis_var = self.AXIS.get(settings.extruder_index,
                                                         ("A", "_a"))

    def _flow(self) -> str:
        return " * #<_hw_jogpot>/511" if self.s.flow_control else ""

    def _axis_for(self, extruder: int) -> Tuple[str, str]:
        if self.s.tool_change_enabled:
            return self.AXIS.get(extruder, ("A", "_a"))
        return self.axis_letter, self.axis_var

    # -- tool-change blocks (offset variable + G92 frame shift) --
    def _tc_open(self, e: int, li: int) -> List[GLine]:
        ox, oy = self.OFFVAR[e]
        return _wrap([
            f"; --- tool change: extruder {e} ---",
            "#5 = #<_x>",
            "#6 = #<_y>",
            f"G0\tX[#<_x> + {ox}]\tY[#<_y> + {oy}]",
            "G92\tX#5\tY#6",
        ], "toolchange", layer=li)

    def _tc_close(self, e: int, li: int) -> List[GLine]:
        ox, oy = self.OFFVAR[e]
        return _wrap([
            f"G92\tX[#<_x> + {ox}]\tY[#<_y> + {oy}] ; remove extruder {e} offset",
        ], "toolchange", layer=li)

    def _tc(self, prev: int, new: int, li: int) -> List[GLine]:
        """Built-in transition prev -> new: drop the old XY offset frame, apply
        the new one (extruder 1 is the (0,0) reference, so no frame for it)."""
        out: List[GLine] = []
        if prev != 1:
            out += self._tc_close(prev, li)
        if new != 1:
            out += self._tc_open(new, li)
        return out

    def write(self, layers: List[LayerToolpath]) -> List[GLine]:
        s = self.s
        out: List[GLine] = []
        out.append(GLine("%", kind="header"))
        out += _preamble(s, ";", layers)
        if s.zero_xy_at_start:
            out.append(GLine("G92\tX0\tY0", kind="header"))
        out.append(GLine(f"G1\tZ0\tF{_fmt(s.print_speed,0)}", kind="header"))
        if s.tool_change_enabled:
            out.append(GLine("", kind="blank"))
            out += _wrap(self._offset_defs(), "header")
        out.append(GLine("", kind="blank"))
        if s.drive == DriveMode.PISTON and s.ramp:
            out.append(GLine(f"G1\t{self.axis_letter}[#<{self.axis_var}> +{_fmt(s.ramp,4)}] ;ramp",
                             kind="header"))
            out.append(GLine("", kind="blank"))

        active = 1
        for li, lt in enumerate(layers):
            out.append(GLine(f"; layer {lt.index}  z={_fmt(lt.z,3)}", kind="layer", layer=li))
            valve_open = False
            for emit in flow_emits(lt, s):
                mi, m = emit.mi, emit.move
                tool = m.extruder if s.tool_change_enabled else 1
                if tool != active:
                    if s.drive == DriveMode.PNEUMATIC and valve_open:
                        out.append(GLine(f"M63 P{active} Q10000 E0", kind="valve", layer=li))
                        valve_open = False
                    out += self._tc(active, tool, li)
                    active = tool
                axis_letter, axis_var = self._axis_for(active)
                valve_p = active if s.tool_change_enabled else s.extruder_index
                if s.drive == DriveMode.PNEUMATIC:
                    if m.extrude and not valve_open:
                        out.append(GLine(
                            f"M63 P{valve_p} Q10000 E{_fmt(s.valve_value*10,3)}",
                            kind="valve", layer=li))
                        valve_open = True
                    elif (not m.extrude) and valve_open:
                        out.append(GLine(f"M63 P{valve_p} Q10000 E0",
                                         kind="valve", layer=li))
                        valve_open = False
                    if emit.stroke_start and s.start_dwell > 0:
                        out.append(GLine(f"G4\tP{_fmt(s.start_dwell,3)} ;dwell", kind="dwell", layer=li))
                    out.append(self._xy_line(m, li, mi, extr=False, coast=emit.coast,
                                             axis_letter=axis_letter, axis_var=axis_var,
                                             first_extrude=emit.stroke_start))
                else:  # piston
                    if emit.stroke_start:
                        if s.flow_start_ramp > 0:
                            out.append(GLine(
                                f"G1\t{axis_letter}[#<{axis_var}> +{_fmt(s.flow_start_ramp,4)}] ;flow start",
                                kind="dwell", layer=li))
                        if s.start_dwell > 0:
                            out.append(GLine(f"G4\tP{_fmt(s.start_dwell,3)} ;dwell", kind="dwell", layer=li))
                    out.append(self._xy_line(m, li, mi, extr=m.extrude, coast=emit.coast,
                                             axis_letter=axis_letter, axis_var=axis_var,
                                             first_extrude=emit.stroke_start))
                    if emit.stroke_end and s.flow_end_retract > 0:
                        out.append(GLine(
                            f"G1\t{axis_letter}[#<{axis_var}> -{_fmt(s.flow_end_retract,4)}] ;flow end",
                            kind="dwell", layer=li))
            if s.drive == DriveMode.PNEUMATIC and valve_open:
                out.append(GLine(f"M63 P{active} Q10000 E0", kind="valve", layer=li))
            # relative Z rise to the *next* layer: use the gap between this
            # layer's z and the next one's so it stays correct across variable-
            # height section boundaries (the next layer's height, not this one's).
            if li + 1 < len(layers):
                rise = layers[li + 1].z - lt.z
            else:
                rise = lt.height
            out.append(GLine("", kind="blank"))
            out.append(GLine(f"G1\tZ[#<_z> +{_fmt(rise,4)}]\tF{_fmt(s.z_speed,0)}",
                             kind="layer", layer=li))
            out.append(GLine("", kind="blank"))

        # return to the reference extruder before the footer
        if s.tool_change_enabled and active != 1:
            out += self._tc(active, 1, len(layers) - 1)

        out += _postamble(s, ";")

        # footer
        if s.drive == DriveMode.PISTON and s.ramp:
            out.append(GLine(f"G1\t{self.axis_letter}[#<{self.axis_var}> -{_fmt(s.ramp,4)}] ;retract",
                             kind="footer"))
        out.append(GLine(f"G1\tZ[#<_z> +{_fmt(s.safe_z,3)}]\tF{_fmt(s.z_speed,0)}"
                         " ;go to safe height", kind="footer"))
        out += _settings_tail(s, ";")
        out.append(GLine("%", kind="footer"))
        return out

    def _offset_defs(self) -> List[str]:
        s = self.s
        e2x, e2y = s.extruder2_offset
        e3x, e3y = s.extruder3_offset
        return [
            "#101 = 0 ; offset extruder 1 XY (reference)",
            f"#102 = {_fmt(e2x,4)} ; offset extruder 2 X",
            f"#103 = {_fmt(e2y,4)} ; offset extruder 2 Y",
            f"#104 = {_fmt(e3x,4)} ; offset extruder 3 X",
            f"#105 = {_fmt(e3y,4)} ; offset extruder 3 Y",
        ]

    def _xy_line(self, m: Move, li: int, mi: int, extr: bool,
                 axis_letter: str, axis_var: str, coast: bool = False,
                 first_extrude: bool = False) -> GLine:
        """Emit one motion line.

        Travels are rapids (G0) per the Planet CNC convention; printing moves are
        G1.  Because F is modal (and a travel's F would otherwise carry into the
        next G1), the print feedrate is restated explicitly on the first printing
        move of every stroke.  A coast then inherits that print feed.
        """
        s = self.s
        x, y = _fmt(m.end[0]), _fmt(m.end[1])
        is_travel = (not m.extrude) and not coast
        if m.radius is not None:
            # Arc support is retained but currently unreachable: no generator
            # sets Move.radius (curves are discretised into line segments).
            g = "G3" if m.ccw else "G2"
            base = f"{g}\tX{x}\tY{y}\tR{_fmt(m.radius,4)}"
        else:
            base = f"{'G0' if is_travel else 'G1'}\tX{x}\tY{y}"
        if extr:
            da = m.length / 10.0 * s.ext_per_10mm
            base += f"\t{axis_letter}[#<{axis_var}> +{_fmt(da,5)}{self._flow()}]"
        if is_travel:
            base += f"\tF{_fmt(s.travel_speed,0)}"
        elif first_extrude:
            base += f"\tF{_fmt(s.print_speed,0)}"
        kind = "move" if m.extrude else ("coast" if coast else "travel")
        return GLine(base, kind=kind, layer=li, move=mi)


# --------------------------------------------------------------------------- #
#  Marlin (absolute E)
# --------------------------------------------------------------------------- #
class MarlinWriter:
    def __init__(self, settings: PrintSettings):
        self.s = settings
        self.e = 0.0

    def _e_delta(self, m: Move, layer_height: float) -> float:
        """Volumetric E for one move.  Uses the *layer's own* height so that
        variable-height sections extrude the right amount."""
        s = self.s
        area = s.filament_area if s.filament_area > 0 else 1.0
        h = layer_height if layer_height > 0 else s.layer_height
        return m.length * s.line_width * h / area

    def write(self, layers: List[LayerToolpath]) -> List[GLine]:
        s = self.s
        self.e = 0.0
        out: List[GLine] = []
        out.append(GLine("; generated by BioprintGEN - Marlin, absolute E", kind="header"))
        out += _preamble(s, ";", layers)
        out.append(GLine("G21 ; mm", kind="header"))
        out.append(GLine("G90 ; absolute XYZ", kind="header"))
        out.append(GLine("M82 ; absolute extrusion", kind="header"))
        if s.tool_change_enabled:
            out += _wrap(self._offset_defs(), "header")
        if s.zero_xy_at_start:
            out.append(GLine("G92 X0 Y0 Z0 E0", kind="header"))
        else:
            out.append(GLine("G92 E0", kind="header"))
        out.append(GLine("", kind="blank"))

        active = 1
        for li, lt in enumerate(layers):
            out.append(GLine(f"; layer {lt.index} z={_fmt(lt.z,3)}", kind="layer", layer=li))
            out.append(GLine(f"G1 Z{_fmt(lt.z,3)} F{_fmt(s.z_speed,0)}", kind="layer", layer=li))
            for emit in flow_emits(lt, s):
                mi, m = emit.mi, emit.move
                tool = m.extruder if s.tool_change_enabled else 1
                if tool != active:
                    out.append(GLine(f"T{tool - 1} ; extruder {tool}",
                                     kind="toolchange", layer=li))
                    active = tool
                if emit.stroke_start and s.start_dwell > 0:
                    out.append(GLine(f"G4 S{_fmt(s.start_dwell,3)} ; dwell", kind="dwell", layer=li))
                if m.extrude:
                    self.e += self._e_delta(m, lt.height)
                    out.append(GLine(
                        f"G1 X{_fmt(m.end[0])} Y{_fmt(m.end[1])} "
                        f"E{_fmt(self.e,5)} F{_fmt(s.print_speed,0)}",
                        kind="move", layer=li, move=mi))
                elif emit.coast:
                    # finish the line without extruding, at print speed
                    out.append(GLine(
                        f"G1 X{_fmt(m.end[0])} Y{_fmt(m.end[1])} F{_fmt(s.print_speed,0)}",
                        kind="coast", layer=li, move=mi))
                else:
                    out.append(GLine(
                        f"G0 X{_fmt(m.end[0])} Y{_fmt(m.end[1])} F{_fmt(s.travel_speed,0)}",
                        kind="travel", layer=li, move=mi))
            out.append(GLine("", kind="blank"))

        if s.tool_change_enabled and active != 1:
            out.append(GLine("T0 ; back to extruder 1", kind="toolchange"))

        out += _postamble(s, ";")

        zmax = layers[-1].z if layers else 0.0
        out.append(GLine(f"G1 Z{_fmt(zmax + s.safe_z,3)} F{_fmt(s.z_speed,0)} ; safe height",
                         kind="footer"))
        out.append(GLine("M400", kind="footer"))
        out += _settings_tail(s, ";")
        return out

    def _offset_defs(self) -> List[str]:
        s = self.s
        e2x, e2y = s.extruder2_offset
        e3x, e3y = s.extruder3_offset
        return [
            f"G10 L1 P1 X0 Y0 ; extruder 1 (reference)",
            f"G10 L1 P2 X{_fmt(e2x,4)} Y{_fmt(e2y,4)} ; extruder 2 offset",
            f"G10 L1 P3 X{_fmt(e3x,4)} Y{_fmt(e3y,4)} ; extruder 3 offset",
        ]


# --------------------------------------------------------------------------- #
#  Custom template flavour
# --------------------------------------------------------------------------- #
class TemplateWriter:
    def __init__(self, settings: PrintSettings):
        self.s = settings
        self.t: FlavourTemplate = settings.custom_flavour or FlavourTemplate()
        self.e = 0.0

    def _e_delta(self, m: Move, layer_height: float) -> float:
        """Volumetric E for one move.  Uses the *layer's own* height so that
        variable-height sections extrude the right amount."""
        s = self.s
        area = s.filament_area if s.filament_area > 0 else 1.0
        h = layer_height if layer_height > 0 else s.layer_height
        return m.length * s.line_width * h / area

    def write(self, layers: List[LayerToolpath]) -> List[GLine]:
        s, t = self.s, self.t
        cp = t.comment_prefix or ";"
        self.e = 0.0
        out: List[GLine] = []
        first_z = layers[0].z if layers else 0.0
        out += _wrap(fill(t.header, name=t.name, layer_count=len(layers),
                          first_z=_fmt(first_z, 3)), "header")
        out += _preamble(s, cp, layers)

        active = 1
        for li, lt in enumerate(layers):
            out += _wrap(fill(t.layer_change, layer=lt.index, z=_fmt(lt.z, 3),
                              height=_fmt(lt.height, 4), f=_fmt(s.z_speed, 0)),
                         "layer", layer=li)

            valve_open = False
            for emit in flow_emits(lt, s):
                mi, m = emit.mi, emit.move
                tool = m.extruder if s.tool_change_enabled else 1
                if tool != active:
                    if valve_open and t.extruder_off:
                        out += _wrap(fill(t.extruder_off, tool=active), "valve", layer=li)
                        valve_open = False
                    ox, oy = s.offset_for_extruder(tool)
                    out += _wrap(fill(t.tool_change, tool=tool,
                                      offx=_fmt(ox, 4), offy=_fmt(oy, 4)),
                                 "toolchange", layer=li)
                    active = tool
                if m.extrude:
                    if not valve_open and t.extruder_on:
                        out += _wrap(fill(t.extruder_on, tool=active), "valve", layer=li)
                        valve_open = True
                    if emit.stroke_start and s.start_dwell > 0:
                        out += _wrap(fill(t.dwell, sec=_fmt(s.start_dwell, 3)), "dwell", layer=li)
                    de = self._e_delta(m, lt.height)
                    self.e += de
                    out += _wrap(fill(t.extrude, x=_fmt(m.end[0]), y=_fmt(m.end[1]),
                                      e=_fmt(self.e, 5), de=_fmt(de, 5),
                                      f=_fmt(s.print_speed, 0), length=_fmt(m.length)),
                                 "move", layer=li, move=mi)
                else:
                    if valve_open and t.extruder_off:
                        out += _wrap(fill(t.extruder_off, tool=active), "valve", layer=li)
                        valve_open = False
                    # coast finishes the stroke at print speed; travel repositions
                    f = s.print_speed if emit.coast else s.travel_speed
                    out += _wrap(fill(t.travel, x=_fmt(m.end[0]), y=_fmt(m.end[1]),
                                      f=_fmt(f, 0)),
                                 "coast" if emit.coast else "travel", layer=li, move=mi)
            if valve_open and t.extruder_off:
                out += _wrap(fill(t.extruder_off, tool=active), "valve", layer=li)

        out += _postamble(s, cp)
        zmax = layers[-1].z if layers else 0.0
        out += _wrap(fill(t.footer, name=t.name, z_max=_fmt(zmax, 3),
                          safe_z=_fmt(zmax + s.safe_z, 3)), "footer")
        out += _settings_tail(s, cp)
        return out


# --------------------------------------------------------------------------- #
#  Line-range -> per-move tool assignment
# --------------------------------------------------------------------------- #
def move_line_map(clean_glines: List[GLine]) -> dict:
    """(layer, move) -> 1-based line number in the clean generation."""
    out = {}
    for i, g in enumerate(clean_glines):
        if g.move is not None and g.layer is not None:
            out[(g.layer, g.move)] = i + 1
    return out


def apply_line_ranges(layers: List[LayerToolpath], clean_glines: List[GLine],
                      ranges) -> None:
    """Set each move's extruder from `ranges` (start/end are 1-based line numbers
    in the clean generation `clean_glines`).  Resets all moves to extruder 1 first,
    so this is idempotent and safe to call on every regenerate."""
    for lt in layers:
        for m in lt.moves:
            m.extruder = 1
    line_to_move = {}
    for i, g in enumerate(clean_glines):
        if g.move is not None and g.layer is not None:
            line_to_move[i + 1] = (g.layer, g.move)
    for r in ranges:
        lo, hi = min(r.start_line, r.end_line), max(r.start_line, r.end_line)
        for ln in range(lo, hi + 1):
            lm = line_to_move.get(ln)
            if lm is None:
                continue
            li, mi = lm
            if 0 <= li < len(layers) and 0 <= mi < len(layers[li].moves):
                layers[li].moves[mi].extruder = r.extruder


def make_writer(settings: PrintSettings):
    if settings.dialect == Dialect.PLANET_CNC:
        return PlanetCNCWriter(settings)
    if settings.dialect == Dialect.CUSTOM:
        return TemplateWriter(settings)
    return MarlinWriter(settings)


def render(layers: List[LayerToolpath], settings: PrintSettings) -> List[GLine]:
    """Emit g-code for a planned toolpath.

    Settings are validated here rather than at planning time because speeds and
    extrusion factors don't affect the toolpath at all — they only affect the
    emitted text, which is what reaches the machine.  An invalid value would
    otherwise produce something physically harmful (e.g. `F0`, which stalls the
    head mid-print) with no warning.  The GUI validates before it gets here, so
    this is the backstop for headless/script use.
    """
    problems = settings.validate()
    if problems:
        raise ValueError("Refusing to emit g-code with invalid settings:\n  - "
                         + "\n  - ".join(problems))
    return make_writer(settings).write(layers)


def lines_to_text(glines: List[GLine]) -> str:
    return "\n".join(g.text for g in glines)
