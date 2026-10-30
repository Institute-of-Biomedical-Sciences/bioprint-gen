"""The left-hand parameter panel.

Groups: Printer, Design, Layers, Extrusion, Printing process, Advanced options.
Exposes `build_settings()` -> PrintSettings and `source_spec()` describing what
to generate, plus a `changed` signal so the preview can auto-refresh.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QFormLayout, QGroupBox, QComboBox, QDoubleSpinBox,
    QSpinBox, QCheckBox, QPushButton, QLabel, QScrollArea, QFileDialog,
    QHBoxLayout, QTableWidget, QHeaderView, QPlainTextEdit, QToolButton,
    QSizePolicy,
)

from ..model import (
    PrintSettings, InfillType, Dialect, DriveMode,
    LayerHeightSection, ToolLineRange, InfillSection, GYROID_LINE_DENSITY,
)
from ..gcode import flavour as flavourmod
from .flavourdialog import FlavourDialog
from . import theme


# pattern dropdown order, shared by the main pattern and the infill sections
INFILL_LABELS = ("Rectilinear – connected", "Rectilinear – separate bars", "Gyroid")
INFILL_TYPES = (InfillType.RECTILINEAR_CONNECTED, InfillType.RECTILINEAR_SEPARATE,
                InfillType.GYROID)


@dataclass
class SourceSpec:
    kind: str                      # "cuboid" | "cylinder" | "stl"
    width: float = 10.0
    depth: float = 10.0
    height: float = 5.0
    diameter: float = 10.0
    stl_path: Optional[str] = None


# --------------------------------------------------------------------------- #
#  Inputs that ignore the wheel until clicked (so scrolling the panel is safe)
# --------------------------------------------------------------------------- #
class _NoWheel:
    """Only react to the mouse wheel once the widget has keyboard focus,
    i.e. after the user deliberately clicks it."""

    def wheelEvent(self, e):  # noqa: N802 (Qt naming)
        if self.hasFocus():
            super().wheelEvent(e)
        else:
            e.ignore()


class DoubleSpin(_NoWheel, QDoubleSpinBox):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.setFocusPolicy(Qt.StrongFocus)


class Spin(_NoWheel, QSpinBox):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.setFocusPolicy(Qt.StrongFocus)


class Combo(_NoWheel, QComboBox):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.setFocusPolicy(Qt.StrongFocus)


class CollapsibleSection(QWidget):
    """A titled header button that shows/hides its content widget."""
    toggled_state = Signal(str, bool)

    def __init__(self, title: str, content: QWidget, expanded: bool = False):
        super().__init__()
        self.title = title
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(4)
        self.btn = QToolButton()
        self.btn.setText(title)
        self.btn.setObjectName("section")
        self.btn.setCheckable(True)
        self.btn.setChecked(expanded)
        self.btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.btn.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
        self.btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.btn.toggled.connect(self._on_toggled)
        v.addWidget(self.btn)
        self.content = content
        self.content.setVisible(expanded)
        v.addWidget(self.content)

    def _on_toggled(self, on: bool):
        self.btn.setArrowType(Qt.DownArrow if on else Qt.RightArrow)
        self.content.setVisible(on)
        self.toggled_state.emit(self.title, on)

    def set_expanded(self, on: bool):
        self.btn.setChecked(bool(on))

    def is_expanded(self) -> bool:
        return self.btn.isChecked()


def _dspin(lo, hi, val, step=0.1, dec=3, suffix=" mm"):
    s = DoubleSpin()
    s.setRange(lo, hi)
    s.setValue(val)
    s.setSingleStep(step)
    s.setDecimals(dec)
    if suffix:
        s.setSuffix(suffix)
    return s


@dataclass
class _Col:
    label: str
    lo: float
    hi: float
    step: float
    dec: int          # 0 -> integer spin box
    default: float
    choices: Optional[List[str]] = None   # -> dropdown; value is the index


class SectionTable(QWidget):
    """A small add/remove table of numeric rows (used for z-range sections).

    Each cell is a spin box so values validate live; `changed` fires on any
    edit or row add/remove.  `rows()` returns the current values as tuples.
    """
    changed = Signal()

    def __init__(self, cols: List[_Col]):
        super().__init__()
        self._cols = cols
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        self.table = QTableWidget(0, len(cols))
        self.table.setHorizontalHeaderLabels([c.label for c in cols])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setMaximumHeight(theme.px(150))
        lay.addWidget(self.table)
        btns = QHBoxLayout()
        add = QPushButton("+ Add")
        rem = QPushButton("− Remove")
        add.clicked.connect(lambda: self._add_row())
        rem.clicked.connect(self._remove_row)
        btns.addWidget(add)
        btns.addWidget(rem)
        btns.addStretch(1)
        lay.addLayout(btns)

    def _add_row(self, values: Optional[Tuple[float, ...]] = None):
        r = self.table.rowCount()
        self.table.insertRow(r)
        for c, col in enumerate(self._cols):
            v = values[c] if values is not None else col.default
            if col.choices:
                sp = Combo()
                sp.addItems(col.choices)
                sp.setCurrentIndex(int(v))
                sp.currentIndexChanged.connect(lambda *_: self.changed.emit())
            elif col.dec == 0:
                sp = Spin()
                sp.setRange(int(col.lo), int(col.hi))
                sp.setValue(int(v))
                sp.valueChanged.connect(lambda *_: self.changed.emit())
            else:
                sp = DoubleSpin()
                sp.setRange(col.lo, col.hi)
                sp.setDecimals(col.dec)
                sp.setSingleStep(col.step)
                sp.setValue(float(v))
                sp.valueChanged.connect(lambda *_: self.changed.emit())
            self.table.setCellWidget(r, c, sp)
        self.changed.emit()

    def _remove_row(self):
        r = self.table.currentRow()
        if r < 0:
            r = self.table.rowCount() - 1
        if r >= 0:
            self.table.removeRow(r)
            self.changed.emit()

    def rows(self) -> List[Tuple[float, ...]]:
        out = []
        for r in range(self.table.rowCount()):
            vals = []
            for c in range(len(self._cols)):
                w = self.table.cellWidget(r, c)
                vals.append(w.currentIndex() if isinstance(w, QComboBox) else w.value())
            out.append(tuple(vals))
        return out

    def clear_rows(self):
        while self.table.rowCount():
            self.table.removeRow(0)

    def apply_scale(self):
        self.table.setMaximumHeight(theme.px(150))

    def set_current_cell(self, col: int, value: float):
        """Set column `col` of the selected (or last) row; adds a row if empty."""
        r = self.table.currentRow()
        if r < 0:
            r = self.table.rowCount() - 1
        if r < 0:
            self._add_row()
            r = self.table.rowCount() - 1
        w = self.table.cellWidget(r, col)
        if isinstance(w, QComboBox):
            w.setCurrentIndex(int(value))
        elif w is not None:
            w.setValue(value)


class ParameterPanel(QScrollArea):
    changed = Signal()
    stl_requested = Signal()
    line_from_selection = Signal(str)   # 'start' | 'end' — fill from preview selection

    def __init__(self):
        super().__init__()
        self._loading = False          # suppress `changed` while applying defaults
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        root = QWidget()
        self.setWidget(root)
        lay = QVBoxLayout(root)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(10)

        # settings that are no longer shown in the panel but are still honoured
        # (from default_settings.json or an imported file)
        self._hidden = {"minimize_crossings": True, "filament_area": 1.0}

        self.sections = {}
        for build in (self._printer_group, self._design_group, self._layers_group,
                      self._extrusion_group, self._process_group,
                      self._advanced_group):
            g = build()
            title = g.title()
            g.setTitle("")                       # header lives in the section button
            sec = CollapsibleSection(title, g, expanded=False)
            self.sections[title] = sec
            lay.addWidget(sec)
        lay.addStretch(1)
        # sensible default: only Design open (overridden by the defaults file)
        self.set_expanded_panels(["Design"])

        self._wire()
        self._refresh_flavours()
        self._update_visibility()

    # ------------------------------------------------------------------ sections
    def set_expanded_panels(self, names):
        wanted = set(names or [])
        if not wanted & set(self.sections):
            wanted = {"Design"}                  # e.g. an old file naming "Source"
        for title, sec in self.sections.items():
            sec.set_expanded(title in wanted)

    def expanded_panels(self) -> List[str]:
        return [t for t, s in self.sections.items() if s.is_expanded()]

    def apply_scaled_sizes(self):
        """Re-apply the panel's Python-set widget sizes at the current UI scale."""
        self.layer_sections.apply_scale()
        self.infill_sections.apply_scale()
        self.tool_ranges.apply_scale()
        self.start_gcode.setMaximumHeight(theme.px(90))
        self.end_gcode.setMaximumHeight(theme.px(90))

    @staticmethod
    def _hint(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setObjectName("hint")
        lbl.setWordWrap(True)
        return lbl

    # ------------------------------------------------------------------ groups
    def _printer_group(self):
        g = QGroupBox("Printer")
        f = QFormLayout(g)
        self.drive = Combo()
        self.drive.addItems(["Piston (metered)", "Pneumatic (valve)"])
        f.addRow("Drive", self.drive)
        self.extruder = Combo()
        self.extruder.addItems(["1 (A)", "2 (B)", "6 (C)"])
        f.addRow("Extruder", self.extruder)
        self.line_width = _dspin(0.05, 5, 0.41, 0.01, 3)
        self.line_width.setToolTip("Effective inner diameter of the nozzle / needle. "
                                   "Used as the deposited line width: it sets the "
                                   "perimeter inset and converts infill % to spacing.")
        f.addRow("Nozzle diameter", self.line_width)
        self.dialect = Combo()
        # populated by _refresh_flavours(): built-ins + saved custom flavours
        self._dialect_options: List[Tuple[Dialect, object]] = []
        f.addRow("G-code flavour", self.dialect)
        self.manage_flavours = QPushButton("Manage flavours…")
        self.manage_flavours.clicked.connect(self._open_flavour_dialog)
        f.addRow(self.manage_flavours)
        return g

    def _design_group(self):
        g = QGroupBox("Design")
        f = QFormLayout(g)
        self.shape = Combo()
        self.shape.addItems(["Cuboid", "Cylinder", "STL file"])
        f.addRow("Shape", self.shape)
        self.width = _dspin(1, 500, 10)
        self.depth = _dspin(1, 500, 10)
        self.diameter = _dspin(1, 500, 12)
        self.height = _dspin(0.1, 500, 5)
        f.addRow("Width X", self.width)
        f.addRow("Depth Y", self.depth)
        f.addRow("Diameter", self.diameter)
        f.addRow("Height Z", self.height)
        self.stl_btn = QPushButton("Choose STL file…")
        self.stl_label = QLabel("no file")
        self.stl_label.setObjectName("hint")
        self.stl_label.setWordWrap(True)
        f.addRow(self.stl_btn)
        f.addRow(self.stl_label)
        return g

    def _layers_group(self):
        g = QGroupBox("Layers")
        f = QFormLayout(g)
        self.layer_h = _dspin(0.02, 5, 0.2, 0.02, 3)
        self.first_h = _dspin(0.0, 5, 0.0, 0.02, 3)
        self.first_h.setToolTip("0 = same as the general layer height")
        f.addRow("General layer height", self.layer_h)
        f.addRow("First layer height", self.first_h)
        f.addRow(self._hint("Variable-height sections (Z range → height). "
                            "Any Z not covered uses the general layer height."))
        self.layer_sections = SectionTable([
            _Col("Z start", 0, 1000, 0.1, 3, 0.0),
            _Col("Z end", 0, 1000, 0.1, 3, 1.0),
            _Col("Height", 0.02, 5, 0.02, 3, 0.2),
        ])
        f.addRow(self.layer_sections)

        self.infill = Combo()
        self.infill.addItems(list(INFILL_LABELS))
        f.addRow("Infill pattern", self.infill)
        self.infill_mode = Combo()
        self.infill_mode.addItems(["Strand spacing", "Infill %"])
        self.infill_mode.setToolTip("Set infill density directly (strand spacing / "
                                    "gyroid period) or as a % of the area, derived "
                                    "from the nozzle diameter")
        f.addRow("Infill defined by", self.infill_mode)
        self.spacing = _dspin(0.2, 20, 1.0, 0.1, 3)
        f.addRow("Strand spacing", self.spacing)
        self.gyroid_period = _dspin(1, 40, 6.0, 0.5, 2)
        f.addRow("Gyroid period", self.gyroid_period)
        self.infill_pct = _dspin(1, 100, 40.0, 5, 1, " %")
        self.infill_pct.setToolTip("Fraction of each layer's area covered by infill "
                                   "lines. 100 % = lines touching (spacing = nozzle "
                                   "diameter).")
        f.addRow("Infill %", self.infill_pct)
        self.infill_info = self._hint("")
        f.addRow(self.infill_info)
        self.infill_angle = _dspin(-180, 180, 0.0, 5, 1, "°")
        f.addRow("Base angle", self.infill_angle)
        self.layer_rot = _dspin(0, 180, 90.0, 5, 1, "°")
        self.layer_rot.setToolTip("X-to-Y angle added to strand direction each layer")
        f.addRow("Layer rotation", self.layer_rot)
        f.addRow(self._hint("Infill sections (Z range → pattern, %). Density is a % so "
                            "it means the same for every pattern; 0 % keeps the main "
                            "infill's density. Any Z not covered uses the main infill."))
        self.infill_sections = SectionTable([
            _Col("Z start", 0, 1000, 0.1, 3, 0.0),
            _Col("Z end", 0, 1000, 0.1, 3, 1.0),
            _Col("Pattern", 0, 2, 1, 0, 2, choices=list(INFILL_LABELS)),
            _Col("Infill %", 0, 100, 5, 1, 0.0),
        ])
        f.addRow(self.infill_sections)
        self.perimeters = Spin()
        self.perimeters.setRange(0, 999)
        self.perimeters.setValue(1)
        self.perimeters.setToolTip("Contour walls before infill. A high number fills "
                                   "the part with walls only — loops stop by "
                                   "themselves once the part is full.")
        f.addRow("Perimeters", self.perimeters)
        self.rotate_start = QCheckBox("Rotate layer start point (4 corners)")
        self.rotate_start.setChecked(True)
        self.rotate_start.setToolTip("Each layer starts at the next bounding-box "
                                     "corner (perimeter seam and infill start), so "
                                     "start/stop artefacts are spread out.")
        f.addRow(self.rotate_start)
        return g

    def _extrusion_group(self):
        g = QGroupBox("Extrusion")
        f = QFormLayout(g)
        # "Ink flow": one row per drive, only the matching one is shown
        self.ext10 = _dspin(0, 5, 0.1, 0.01, 4, " mm/10mm")
        self.ext10.setToolTip("Piston: plunger travel per 10 mm of nozzle motion")
        f.addRow("Ink flow", self.ext10)
        self.valve = _dspin(0, 10, 1.0, 0.1, 3, " bar")
        self.valve.setToolTip("Pneumatic: valve pressure in bar "
                              "(written as M63 … E = bar × 10)")
        f.addRow("Ink flow", self.valve)
        self.ramp = _dspin(0, 5, 0.05, 0.01, 3)
        self.ramp.setToolTip("Piston: prime once at the start of the print and "
                             "retract once at the end")
        f.addRow("Ramp / retract", self.ramp)
        self.flow_start_ramp = _dspin(0, 5, 0.0, 0.01, 4, "")
        self.flow_start_ramp.setToolTip("Piston: prime the extrusion axis by this "
                                        "amount at each stroke start (before the "
                                        "dwell). Separate from the print-start ramp.")
        f.addRow("Start ramp", self.flow_start_ramp)
        self.flow_end_retract = _dspin(0, 5, 0.0, 0.01, 4, "")
        self.flow_end_retract.setToolTip("Piston: retract the extrusion axis by this "
                                         "amount at each stroke end (balances the "
                                         "start ramp). Keep at 0 if not needed.")
        f.addRow("End retract", self.flow_end_retract)
        self.start_dwell = _dspin(0, 60, 0.0, 0.1, 2, " s")
        self.start_dwell.setToolTip("Pause (G4) each time extrusion starts, to let "
                                    "material begin flowing before moving")
        f.addRow("Start dwell", self.start_dwell)
        self.end_dwell = _dspin(0, 60, 0.0, 0.1, 2, " s")
        self.end_dwell.setToolTip("Pause (G4) after each stroke ends (after the coast "
                                  "and retract), to let material stop before travelling")
        f.addRow("End dwell", self.end_dwell)
        self.coast_distance = _dspin(0, 50, 0.0, 0.1, 2)
        self.coast_distance.setToolTip("Stop extruding this far before each stroke's "
                                       "end and coast, to counter ooze. Strokes shorter "
                                       "than this coast entirely.")
        f.addRow("Coast distance", self.coast_distance)
        return g

    def _process_group(self):
        g = QGroupBox("Printing process")
        f = QFormLayout(g)
        self.print_speed = _dspin(10, 20000, 500, 50, 0, " mm/min")
        self.travel_speed = _dspin(10, 20000, 1600, 50, 0, " mm/min")
        self.z_speed = _dspin(10, 20000, 300, 50, 0, " mm/min")
        self.z_speed.setToolTip("Feedrate of every Z move: layer changes, travel "
                                "lifts and the final lift")
        f.addRow("Printing speed", self.print_speed)
        f.addRow("Travel speed", self.travel_speed)
        f.addRow("Layer change speed", self.z_speed)
        self.travel_lift = _dspin(0, 100, 0.0, 0.1, 2)
        self.travel_lift.setToolTip("Hop the nozzle up by this much (relative) before "
                                    "every travel between strokes, then drop back "
                                    "down. 0 = no hop.")
        f.addRow("Travel safe height", self.travel_lift)
        self.safe_z = _dspin(0, 100, 2.0, 0.5, 2)
        self.safe_z.setToolTip("Lift at the very end of the print")
        f.addRow("Final safe height", self.safe_z)

        self.tool_change = QCheckBox("Enable tool change (multiple extruders)")
        f.addRow(self.tool_change)
        self.ext2x = _dspin(-1000, 1000, 0.0, 0.1, 3)
        self.ext2y = _dspin(-1000, 1000, 0.0, 0.1, 3)
        self.ext3x = _dspin(-1000, 1000, 0.0, 0.1, 3)
        self.ext3y = _dspin(-1000, 1000, 0.0, 0.1, 3)
        f.addRow("Extruder 2 X offset", self.ext2x)
        f.addRow("Extruder 2 Y offset", self.ext2y)
        f.addRow("Extruder 3 X offset", self.ext3x)
        f.addRow("Extruder 3 Y offset", self.ext3y)
        self._tc_hint = self._hint(
            "Extruder 1 is the (0,0) reference. Tool changes are placed by g-code "
            "line range (from the clean generation). Read the line numbers in the "
            "G-code panel, or select a segment in the preview and use the buttons "
            "below.")
        f.addRow(self._tc_hint)
        self.tool_ranges = SectionTable([
            _Col("Start line", 1, 10_000_000, 1, 0, 1),
            _Col("End line", 1, 10_000_000, 1, 0, 1),
            _Col("Extruder", 1, 3, 1, 0, 2),
        ])
        f.addRow(self.tool_ranges)
        selrow = QHBoxLayout()
        selrow.setContentsMargins(0, 0, 0, 0)
        self.set_start_btn = QPushButton("Set start ← selection")
        self.set_end_btn = QPushButton("Set end ← selection")
        self.set_start_btn.clicked.connect(lambda: self.line_from_selection.emit("start"))
        self.set_end_btn.clicked.connect(lambda: self.line_from_selection.emit("end"))
        selrow.addWidget(self.set_start_btn)
        selrow.addWidget(self.set_end_btn)
        self._sel_row = QWidget()
        self._sel_row.setLayout(selrow)
        f.addRow(self._sel_row)

        self.zero_xy = QCheckBox("Set XY = 0 at current position (G92)")
        self.zero_xy.setChecked(True)
        f.addRow(self.zero_xy)
        return g

    def _advanced_group(self):
        g = QGroupBox("Advanced options")
        f = QFormLayout(g)
        self.settings_header = QCheckBox("Write settings as comment block")
        self.settings_header.setChecked(True)
        self.settings_header.setToolTip("Appends every setting as comments at the end "
                                        "of the file. Needed to restore the session "
                                        "with Import g-code.")
        f.addRow(self.settings_header)
        self.flow = QCheckBox("Live flow control (jogpot)")
        self.flow.setToolTip("Piston: scale extrusion live with the Planet CNC jog "
                             "potentiometer")
        f.addRow(self.flow)
        self.start_gcode = QPlainTextEdit()
        self.start_gcode.setPlaceholderText("Injected after the machine header, "
                                            "before the first layer")
        self.start_gcode.setMaximumHeight(theme.px(90))
        self.end_gcode = QPlainTextEdit()
        self.end_gcode.setPlaceholderText("Injected before the footer / final lift")
        self.end_gcode.setMaximumHeight(theme.px(90))
        f.addRow("Start g-code", self.start_gcode)
        f.addRow("End g-code", self.end_gcode)
        return g

    # ------------------------------------------------------------------ flavours
    def _refresh_flavours(self, select_name: Optional[str] = None):
        """Rebuild the flavour combo from built-ins + saved custom flavours."""
        prev = None
        if self._dialect_options and self.dialect.currentIndex() >= 0:
            prev = self.dialect.currentText()
        self.dialect.blockSignals(True)
        self.dialect.clear()
        self._dialect_options = [
            (Dialect.PLANET_CNC, None),
            (Dialect.MARLIN_ABS_E, None),
        ]
        self.dialect.addItems(["Planet CNC", "Marlin (absolute E)"])
        try:
            flavs = flavourmod.list_flavours()
        except Exception:
            flavs = {}
        for name, tmpl in flavs.items():
            self._dialect_options.append((Dialect.CUSTOM, tmpl))
            self.dialect.addItem(f"Custom: {name}")
        target = select_name or prev
        if target:
            i = self.dialect.findText(target)
            if i < 0 and select_name:
                i = self.dialect.findText(f"Custom: {select_name}")
            if i >= 0:
                self.dialect.setCurrentIndex(i)
        self.dialect.blockSignals(False)
        self._update_visibility()

    def _open_flavour_dialog(self):
        dlg = FlavourDialog(self)
        dlg.exec()
        self._refresh_flavours(select_name=dlg.last_saved_name)
        self.changed.emit()

    # ------------------------------------------------------------------ wiring
    def _wire(self):
        for w in (self.shape, self.infill, self.infill_mode, self.dialect, self.drive):
            w.currentIndexChanged.connect(self._update_visibility)
        self.tool_change.toggled.connect(self._update_visibility)
        # the derived-density readout follows these
        self.infill_pct.valueChanged.connect(self._update_visibility)
        self.line_width.valueChanged.connect(self._update_visibility)
        self.stl_btn.clicked.connect(self.stl_requested.emit)
        widgets = [
            self.shape, self.width, self.depth, self.height, self.diameter,
            self.infill, self.infill_mode, self.spacing, self.infill_pct,
            self.infill_angle, self.layer_rot, self.gyroid_period, self.perimeters,
            self.rotate_start, self.dialect, self.drive, self.extruder,
            self.line_width, self.ext10, self.ramp, self.valve, self.flow,
            self.print_speed, self.travel_speed, self.z_speed, self.layer_h,
            self.first_h, self.safe_z, self.zero_xy, self.settings_header,
            self.tool_change, self.ext2x, self.ext2y, self.ext3x, self.ext3y,
            self.flow_start_ramp, self.flow_end_retract, self.start_dwell,
            self.end_dwell, self.coast_distance, self.travel_lift,
        ]
        def emit(*_):                            # discard Qt's arg
            if not self._loading:
                self.changed.emit()
        for w in widgets:
            if isinstance(w, QComboBox):
                w.currentIndexChanged.connect(emit)
            elif isinstance(w, (QDoubleSpinBox, QSpinBox)):
                w.valueChanged.connect(emit)
            elif isinstance(w, QCheckBox):
                w.toggled.connect(emit)
        self.layer_sections.changed.connect(emit)
        self.infill_sections.changed.connect(emit)
        self.tool_ranges.changed.connect(emit)
        self.start_gcode.textChanged.connect(emit)
        self.end_gcode.textChanged.connect(emit)

    def _show(self, widget, on: bool):
        """Show or hide a setting's whole row (field *and* caption), so settings
        that don't apply to the current selection simply aren't listed."""
        parent = widget.parentWidget()
        lay = parent.layout() if parent is not None else None
        if isinstance(lay, QFormLayout) and lay.indexOf(widget) >= 0:
            lay.setRowVisible(widget, on)
        else:
            widget.setVisible(on)

    def _update_visibility(self):
        # -- Design: only the dimensions the chosen shape actually uses --
        shp = self.shape.currentIndex()   # 0 cuboid 1 cyl 2 stl
        is_cuboid, is_cyl, is_stl = shp == 0, shp == 1, shp == 2
        self._show(self.width, is_cuboid)
        self._show(self.depth, is_cuboid)
        self._show(self.diameter, is_cyl)
        self._show(self.height, not is_stl)      # an STL brings its own height
        self._show(self.stl_btn, is_stl)
        self._show(self.stl_label, is_stl)

        # -- Layers / infill --
        is_gyroid = self.infill.currentIndex() == 2
        percent = self.infill_mode.currentIndex() == 1
        self._show(self.spacing, not percent and not is_gyroid)
        self._show(self.gyroid_period, not percent and is_gyroid)
        self._show(self.infill_pct, percent)
        self._show(self.infill_info, percent)
        self._show(self.infill_angle, not is_gyroid)
        self._show(self.layer_rot, not is_gyroid)
        if percent and self.infill_pct.value() > 0:
            d = self.infill_pct.value() / 100.0
            w = self.line_width.value()
            if is_gyroid:
                self.infill_info.setText(
                    f"≈ {GYROID_LINE_DENSITY * w / d:.2f} mm gyroid period")
            else:
                self.infill_info.setText(f"≈ {w / d:.2f} mm strand spacing")

        # -- Printer / Extrusion: flavour + drive specific --
        planet = self.dialect.currentIndex() == 0
        piston = self.drive.currentIndex() == 0
        metered = planet and piston
        self._show(self.drive, planet)
        # per-layer extruder is chosen automatically when tool change is on
        self._show(self.extruder, planet and not self.tool_change.isChecked())
        self._show(self.ext10, metered)
        self._show(self.valve, planet and not piston)
        self._show(self.ramp, metered)
        self._show(self.flow_start_ramp, metered)
        self._show(self.flow_end_retract, metered)
        self._show(self.flow, metered)

        # -- Printing process: tool change details only when enabled --
        tc = self.tool_change.isChecked()
        for w in (self.ext2x, self.ext2y, self.ext3x, self.ext3y,
                  self._tc_hint, self.tool_ranges, self._sel_row):
            self._show(w, tc)

    # ------------------------------------------------------------------ output
    def set_stl_path(self, path: str):
        self._stl_path = path
        self.stl_label.setText(path.split("/")[-1] if path else "no file")

    def source_spec(self) -> SourceSpec:
        kinds = ["cuboid", "cylinder", "stl"]
        return SourceSpec(
            kind=kinds[self.shape.currentIndex()],
            width=self.width.value(), depth=self.depth.value(),
            height=self.height.value(), diameter=self.diameter.value(),
            stl_path=getattr(self, "_stl_path", None),
        )

    def apply_source(self, spec: SourceSpec):
        """Populate the Source group from a SourceSpec (used for defaults)."""
        self._loading = True
        try:
            kinds = ["cuboid", "cylinder", "stl"]
            if spec.kind in kinds:
                self.shape.setCurrentIndex(kinds.index(spec.kind))
            self.width.setValue(spec.width)
            self.depth.setValue(spec.depth)
            self.height.setValue(spec.height)
            self.diameter.setValue(spec.diameter)
            if spec.stl_path:
                self.set_stl_path(spec.stl_path)
        finally:
            self._loading = False
        self._update_visibility()

    def apply_settings(self, s: PrintSettings):
        """Populate every control from a PrintSettings (used for defaults)."""
        self._loading = True
        try:
            self.layer_h.setValue(s.layer_height)
            self.first_h.setValue(s.first_layer_height or 0.0)
            self.line_width.setValue(s.line_width)
            self.spacing.setValue(s.strand_spacing)
            self.infill_mode.setCurrentIndex(1 if s.percent_mode() else 0)
            self.infill_pct.setValue(s.infill_percent)
            self.rotate_start.setChecked(bool(s.rotate_start))
            self.infill_angle.setValue(s.infill_angle)
            self.layer_rot.setValue(s.layer_rotation)
            if s.infill_type in INFILL_TYPES:
                self.infill.setCurrentIndex(INFILL_TYPES.index(s.infill_type))
            self.gyroid_period.setValue(s.gyroid_period)
            self.perimeters.setValue(s.perimeters)
            self.print_speed.setValue(s.print_speed)
            self.travel_speed.setValue(s.travel_speed)
            self.z_speed.setValue(s.z_speed)
            # dialect: match built-ins, or a custom flavour by name
            want_name = getattr(s.custom_flavour, "name", None)
            for i, (d, tmpl) in enumerate(self._dialect_options):
                if d == s.dialect and (d != Dialect.CUSTOM or
                                       getattr(tmpl, "name", None) == want_name):
                    self.dialect.setCurrentIndex(i)
                    break
            self.drive.setCurrentIndex(0 if s.drive == DriveMode.PISTON else 1)
            if s.extruder_index in (1, 2, 6):
                self.extruder.setCurrentIndex([1, 2, 6].index(s.extruder_index))
            self.ext10.setValue(s.ext_per_10mm)
            self.ramp.setValue(s.ramp)
            self.flow.setChecked(s.flow_control)
            self.valve.setValue(s.valve_value)
            self._hidden["filament_area"] = s.filament_area
            self.safe_z.setValue(s.safe_z)
            self.zero_xy.setChecked(s.zero_xy_at_start)
            self._hidden["minimize_crossings"] = bool(s.minimize_crossings)
            # flow control
            self.flow_start_ramp.setValue(s.flow_start_ramp)
            self.flow_end_retract.setValue(s.flow_end_retract)
            self.start_dwell.setValue(s.start_dwell)
            self.end_dwell.setValue(s.end_dwell)
            self.coast_distance.setValue(s.coast_distance)
            self.travel_lift.setValue(s.travel_lift)
            # tool change
            self.tool_change.setChecked(s.tool_change_enabled)
            self.ext2x.setValue(s.extruder2_offset[0])
            self.ext2y.setValue(s.extruder2_offset[1])
            self.ext3x.setValue(s.extruder3_offset[0])
            self.ext3y.setValue(s.extruder3_offset[1])
            # tables
            self.layer_sections.clear_rows()
            for sec in s.layer_sections:
                self.layer_sections._add_row((sec.z_start, sec.z_end, sec.height))
            self.infill_sections.clear_rows()
            for sec in s.infill_sections:
                self.infill_sections._add_row(
                    (sec.z_start, sec.z_end, INFILL_TYPES.index(sec.infill_type), sec.percent))
            self.tool_ranges.clear_rows()
            for r in s.tool_line_ranges:
                self.tool_ranges._add_row((r.start_line, r.end_line, r.extruder))
            # text
            self.start_gcode.setPlainText(s.start_gcode)
            self.end_gcode.setPlainText(s.end_gcode)
            self.settings_header.setChecked(s.write_settings_header)
        finally:
            self._loading = False
        self._update_visibility()

    def build_settings(self) -> PrintSettings:
        s = PrintSettings()
        s.layer_height = self.layer_h.value()
        s.first_layer_height = self.first_h.value() or None
        s.line_width = self.line_width.value()
        s.strand_spacing = self.spacing.value()
        s.infill_mode = "percent" if self.infill_mode.currentIndex() == 1 else "spacing"
        s.infill_percent = self.infill_pct.value()
        s.rotate_start = self.rotate_start.isChecked()
        s.infill_angle = self.infill_angle.value()
        s.layer_rotation = self.layer_rot.value()
        s.infill_type = INFILL_TYPES[self.infill.currentIndex()]
        s.gyroid_period = self.gyroid_period.value()
        s.perimeters = self.perimeters.value()
        s.print_speed = self.print_speed.value()
        s.travel_speed = self.travel_speed.value()
        s.z_speed = self.z_speed.value()
        idx = self.dialect.currentIndex()
        if 0 <= idx < len(self._dialect_options):
            s.dialect, s.custom_flavour = self._dialect_options[idx]
        else:
            s.dialect, s.custom_flavour = Dialect.PLANET_CNC, None
        s.drive = DriveMode.PISTON if self.drive.currentIndex() == 0 else DriveMode.PNEUMATIC
        s.extruder_index = [1, 2, 6][self.extruder.currentIndex()]
        s.ext_per_10mm = self.ext10.value()
        s.ramp = self.ramp.value()
        s.flow_control = self.flow.isChecked()
        s.valve_value = self.valve.value()
        s.filament_area = self._hidden["filament_area"]
        s.safe_z = self.safe_z.value()
        s.zero_xy_at_start = self.zero_xy.isChecked()
        s.minimize_crossings = self._hidden["minimize_crossings"]
        s.flow_start_ramp = self.flow_start_ramp.value()
        s.flow_end_retract = self.flow_end_retract.value()
        s.start_dwell = self.start_dwell.value()
        s.end_dwell = self.end_dwell.value()
        s.coast_distance = self.coast_distance.value()
        s.travel_lift = self.travel_lift.value()

        # variable-height sections
        s.layer_sections = [LayerHeightSection(a, b, h)
                            for (a, b, h) in self.layer_sections.rows()]
        s.infill_sections = [InfillSection(a, b, INFILL_TYPES[int(k)], pct)
                             for (a, b, k, pct) in self.infill_sections.rows()]
        # tool change / extruders
        s.tool_change_enabled = self.tool_change.isChecked()
        s.extruder2_offset = (self.ext2x.value(), self.ext2y.value())
        s.extruder3_offset = (self.ext3x.value(), self.ext3y.value())
        s.tool_line_ranges = [ToolLineRange(int(a), int(b), int(e))
                              for (a, b, e) in self.tool_ranges.rows()]
        # start / end g-code + header
        s.start_gcode = self.start_gcode.toPlainText()
        s.end_gcode = self.end_gcode.toPlainText()
        s.write_settings_header = self.settings_header.isChecked()
        spec = self.source_spec()
        s.source = {"kind": spec.kind, "width": spec.width, "depth": spec.depth,
                    "height": spec.height, "diameter": spec.diameter,
                    "stl_path": spec.stl_path}
        return s
