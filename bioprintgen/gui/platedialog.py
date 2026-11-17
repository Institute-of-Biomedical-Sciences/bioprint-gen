"""Plate setup: plate geometry, which wells to print, and position calibration.

Calibration is four points (see `bioprintgen.placement`): three on the rim of
one well - the first on the rim's top edge, which also gives the rim height -
and the centre of a second well with the nozzle on its floor.  They are either
typed in here (work coordinates read off the controller's display) or, on
Planet CNC, asked for by the program at print time.
"""
from __future__ import annotations

import copy
from typing import List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QGridLayout, QGroupBox, QLabel,
    QPushButton, QToolButton, QCheckBox, QScrollArea, QWidget, QDialogButtonBox,
    QComboBox,
)

from .. import placement as plc
from . import theme
from .controls import Combo, DoubleSpin, Spin

MODES = ("Typed in here", "Guided at print time (Planet CNC)")
BETWEEN = (("none", "Go straight on"), ("pause", "Pause (M0) - resume by hand"),
           ("dwell", "Wait (dwell)"))


def _spin(lo=-1000.0, hi=1000.0, val=0.0, dec=3, suffix=" mm", step=0.1):
    s = DoubleSpin()
    s.setRange(lo, hi)
    s.setDecimals(dec)
    s.setSingleStep(step)
    s.setValue(val)
    if suffix:
        s.setSuffix(suffix)
    return s


def _narrow(*widgets):
    """Let fields shrink below their content-based minimum (a spin box sized
    for '-1000.000', a combo for its longest entry), so both columns fit."""
    for w in widgets:
        if isinstance(w, QComboBox):
            w.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
            w.setMinimumContentsLength(8)
        else:
            w.setMinimumWidth(theme.px(56))


def _xyz_row(*spins) -> QWidget:
    _narrow(*spins)
    row = QWidget()
    h = QHBoxLayout(row)
    h.setContentsMargins(0, 0, 0, 0)
    for axis, sp in zip("XYZ", spins):
        h.addWidget(QLabel(axis))
        h.addWidget(sp, 1)
    return row


class PlateDialog(QDialog):
    def __init__(self, pl: plc.Placement, part_radius: float = 0.0, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Well plate setup")
        self.resize(theme.px(980), theme.px(740))
        self._pl = copy.deepcopy(pl)
        self._part_radius = part_radius
        self._loading = True
        self._cells = {}

        outer = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body = QWidget()
        cols = QHBoxLayout(body)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)

        # ---- left: plate + wells
        left = QVBoxLayout()
        cols.addLayout(left, 4)
        g = QGroupBox("Plate")
        f = QFormLayout(g)
        self.preset = Combo()
        self.preset.addItems(list(plc.PLATE_PRESETS) + ["Custom (edited values)"])
        self.rows, self.cols = Spin(), Spin()
        self.rows.setRange(1, 16)
        self.cols.setRange(1, 24)
        self.pitch_x = _spin(0.1, 200, 19.3)
        self.pitch_y = _spin(0.1, 200, 19.3)
        self.diam = _spin(0.1, 200, 15.6)
        for label, w in (("Preset", self.preset), ("Rows", self.rows), ("Columns", self.cols),
                         ("Spacing A1 → A2", self.pitch_x), ("Spacing A1 → B1", self.pitch_y),
                         ("Well diameter", self.diam)):
            f.addRow(label, w)
        note = QLabel("Typical values for standard plates — check your vendor's drawing, "
                      "or use the spacing measured during calibration.")
        note.setObjectName("hint")
        note.setWordWrap(True)
        f.addRow(note)
        left.addWidget(g)

        wg = QGroupBox("Wells to print")
        wl = QVBoxLayout(wg)
        tip = QLabel("Click a well to select it; a letter or number selects the whole "
                     "row / column.")
        tip.setObjectName("hint")
        tip.setWordWrap(True)
        wl.addWidget(tip)
        self.grid_host = QWidget()
        self.grid = QGridLayout(self.grid_host)
        self.grid.setSpacing(theme.px(3))
        wl.addWidget(self.grid_host)
        btns = QHBoxLayout()
        for text, on in (("All", True), ("None", False)):
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, on=on: self._set_all(on))
            btns.addWidget(b)
        btns.addStretch(1)
        wl.addLayout(btns)
        self.selected_label = QLabel("")
        self.selected_label.setObjectName("hint")
        self.selected_label.setWordWrap(True)
        wl.addWidget(self.selected_label)
        left.addWidget(wg)
        left.addStretch(1)

        # ---- right: calibration + run options
        right = QVBoxLayout()
        cols.addLayout(right, 5)
        cg = QGroupBox("Calibration — 4 points")
        cf = QFormLayout(cg)
        cf.setRowWrapPolicy(QFormLayout.WrapAllRows)      # caption above: room for X Y Z
        self._cal_form = cf
        self.mode = Combo()
        self.mode.addItems(MODES)
        self.mode.setToolTip("Typed: jog and copy the coordinates into this dialog "
                             "before exporting.\nGuided: the program asks you to jog to "
                             "each point when the print starts, so one file works "
                             "wherever the plate sits.")
        cf.addRow(self.mode)
        self.hint = QLabel("")
        self.hint.setObjectName("hint")
        self.hint.setWordWrap(True)
        cf.addRow(self.hint)
        self.rim_well = Combo()
        self.rim_well.setToolTip("Points 1-3 go on this well's rim")
        self.centre_well = Combo()
        self.centre_well.setToolTip("Point 4 is this well's centre, on its floor. The "
                                    "farther from the rim well, the more precise the "
                                    "plate rotation.")
        cf.addRow("Rim well (points 1–3)", self.rim_well)
        cf.addRow("Centre well (point 4)", self.centre_well)
        # typed coordinates
        # no " mm" suffix: keeps three fields side by side narrow enough
        self.p1 = (_spin(suffix=""), _spin(suffix=""), _spin(-200, 200, suffix=""))
        self.p2 = (_spin(suffix=""), _spin(suffix=""))
        self.p3 = (_spin(suffix=""), _spin(suffix=""))
        self.p4 = (_spin(suffix=""), _spin(suffix=""), _spin(-200, 200, suffix=""))
        self._typed_rows = [_xyz_row(*self.p1), _xyz_row(*self.p2),
                            _xyz_row(*self.p3), _xyz_row(*self.p4)]
        for label, row in zip(("Point 1 · rim, top edge (mm)", "Point 2 · rim",
                               "Point 3 · rim", "Point 4 · centre, on the floor"),
                              self._typed_rows):
            cf.addRow(label, row)
        self.measured_pitch = QCheckBox("Use the measured spacing")
        self.measured_pitch.setToolTip("Scale the plate's well spacing by the distance "
                                       "measured between the two wells")
        cf.addRow(self.measured_pitch)
        self.result = QLabel("")
        self.result.setWordWrap(True)
        cf.addRow(self.result)
        right.addWidget(cg)

        rg = QGroupBox("Printing")
        rf = QFormLayout(rg)
        self.clearance = _spin(0, 100, 3.0)
        self.clearance.setToolTip("Height above the rim (or the part, if taller) for "
                                  "moves between wells")
        self.between = Combo()
        self.between.addItems([t for _k, t in BETWEEN])
        self.dwell = _spin(0, 3600, 10.0, 1, " s", 1.0)
        rf.addRow("Travel clearance", self.clearance)
        rf.addRow("Between wells", self.between)
        rf.addRow("Wait", self.dwell)
        self._run_form = rf
        right.addWidget(rg)
        right.addStretch(1)

        _narrow(self.preset, self.mode, self.rim_well, self.centre_well, self.between,
                self.pitch_x, self.pitch_y, self.diam, self.clearance, self.dwell)

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        outer.addWidget(bb)

        spins = [s for p in (self.p1, self.p2, self.p3, self.p4) for s in p]
        for w in [self.rows, self.cols, self.pitch_x, self.pitch_y, self.diam,
                  self.clearance, self.dwell] + spins:
            w.valueChanged.connect(self._changed)
        for w in (self.between, self.mode, self.rim_well, self.centre_well):
            w.currentIndexChanged.connect(self._changed)
        self.measured_pitch.toggled.connect(self._changed)
        self.preset.currentIndexChanged.connect(self._preset_chosen)

        self._load(self._pl)

    # ------------------------------------------------------------------ load / save
    def _load(self, pl: plc.Placement):
        self._loading = True
        p = pl.plate
        names = list(plc.PLATE_PRESETS)
        same = plc.PLATE_PRESETS.get(p.name)
        self.preset.setCurrentIndex(names.index(p.name) if same == p else len(names))
        self._plate_fields(p)
        self._fill_well_combos(pl.rim_well, plc.centre_well(pl))
        pts = (list(pl.rim_points) + [[0.0, 0.0]] * 3)[:3]
        for spins, pt in zip((self.p1, self.p2, self.p3), pts):
            spins[0].setValue(pt[0])
            spins[1].setValue(pt[1])
        self.p1[2].setValue(pl.rim_z)
        self.p4[0].setValue(pl.centre_x)
        self.p4[1].setValue(pl.centre_y)
        self.p4[2].setValue(pl.floor_z)
        self.measured_pitch.setChecked(pl.use_measured_pitch)
        self.mode.setCurrentIndex(1 if pl.guided else 0)
        self.clearance.setValue(pl.clearance)
        keys = [k for k, _t in BETWEEN]
        self.between.setCurrentIndex(keys.index(pl.between) if pl.between in keys else 0)
        self.dwell.setValue(pl.dwell)
        self._loading = False
        self._build_grid(set(pl.wells))
        self._changed()

    def _plate_fields(self, p: plc.PlateSpec):
        self.rows.setValue(p.rows)
        self.cols.setValue(p.cols)
        self.pitch_x.setValue(p.pitch_x)
        self.pitch_y.setValue(p.pitch_y)
        self.diam.setValue(p.well_diameter)

    def _current_plate(self) -> plc.PlateSpec:
        names = list(plc.PLATE_PRESETS)
        k = self.preset.currentIndex()
        base = plc.PLATE_PRESETS[names[k]] if k < len(names) else self._pl.plate
        plate = plc.PlateSpec(
            name=base.name if k < len(names) else "Custom",
            rows=self.rows.value(), cols=self.cols.value(),
            pitch_x=self.pitch_x.value(), pitch_y=self.pitch_y.value(),
            well_diameter=self.diam.value(), well_depth=base.well_depth,
            a1_x=base.a1_x, a1_y=base.a1_y)
        if k < len(names) and plate != plc.PLATE_PRESETS[names[k]]:
            plate.name = f"{names[k]} (edited)"
        return plate

    def _fill_well_combos(self, rim: str, centre: str):
        """Both dropdowns list the plate's wells; a choice no longer on the
        plate falls back to A1 / the opposite corner."""
        plate = self._current_plate()
        wells = plc.all_wells(plate)
        for combo, want, fallback in ((self.rim_well, rim, wells[0]),
                                      (self.centre_well, centre, plc.opposite_corner(plate))):
            combo.blockSignals(True)
            combo.clear()
            combo.addItems(wells)
            combo.setCurrentIndex(wells.index(want) if want in wells else wells.index(fallback))
            combo.blockSignals(False)

    def placement(self) -> plc.Placement:
        pl = copy.deepcopy(self._pl)
        pl.plate = self._current_plate()
        pl.rim_well = self.rim_well.currentText()
        pl.centre_well = self.centre_well.currentText()
        pl.rim_points = [[s[0].value(), s[1].value()] for s in (self.p1, self.p2, self.p3)]
        pl.rim_z = self.p1[2].value()
        pl.centre_x, pl.centre_y, pl.floor_z = (s.value() for s in self.p4)
        pl.use_measured_pitch = self.measured_pitch.isChecked()
        pl.guided = self.mode.currentIndex() == 1
        pl.clearance = self.clearance.value()
        pl.between = BETWEEN[self.between.currentIndex()][0]
        pl.dwell = self.dwell.value()
        pl.wells = [w for w, b in self._cells.items() if b.isChecked()]
        return pl

    # ------------------------------------------------------------------ wells grid
    def _build_grid(self, selected: set):
        while self.grid.count():
            item = self.grid.takeAt(0)
            if item.widget():
                item.widget().setParent(None)      # gone now, not at the next event loop
        self._cells = {}
        rows, cols = self.rows.value(), self.cols.value()
        size = theme.px(30)
        for c in range(cols):
            b = QToolButton()
            b.setText(str(c + 1))
            b.setAutoRaise(True)
            b.clicked.connect(lambda _=False, c=c: self._toggle_line(col=c))
            self.grid.addWidget(b, 0, c + 1)
        for r in range(rows):
            b = QToolButton()
            b.setText(plc.ROW_LETTERS[r])
            b.setAutoRaise(True)
            b.clicked.connect(lambda _=False, r=r: self._toggle_line(row=r))
            self.grid.addWidget(b, r + 1, 0)
            for c in range(cols):
                name = plc.well_label(r, c)
                cell = QToolButton()
                cell.setCheckable(True)
                cell.setChecked(name in selected)
                cell.setFixedSize(size, size)
                cell.setToolTip(name)
                cell.setStyleSheet(
                    f"QToolButton {{ border: 1px solid {theme.TEXT_DIM}; border-radius: {size // 2}px; }}"
                    f"QToolButton:checked {{ background: {theme.EXTRUDE}; }}")
                cell.toggled.connect(self._changed)
                self.grid.addWidget(cell, r + 1, c + 1)
                self._cells[name] = cell
        # keep the wells together at the top-left instead of spread over the box
        for k in range(self.grid.columnCount()):
            self.grid.setColumnStretch(k, 0)
        self.grid.setColumnStretch(cols + 1, 1)

    def _toggle_line(self, row: Optional[int] = None, col: Optional[int] = None):
        cells = [b for name, b in self._cells.items()
                 if (row is not None and name[0] == plc.ROW_LETTERS[row])
                 or (col is not None and name[1:] == str(col + 1))]
        on = not all(b.isChecked() for b in cells)
        for b in cells:
            b.setChecked(on)

    def _set_all(self, on: bool):
        for b in self._cells.values():
            b.setChecked(on)

    # ------------------------------------------------------------------ live feedback
    def _preset_chosen(self, k: int):
        names = list(plc.PLATE_PRESETS)
        if k < len(names):
            self._loading = True
            self._plate_fields(plc.PLATE_PRESETS[names[k]])
            self._loading = False
            self._changed()

    def _changed(self, *_):
        if self._loading:
            return
        if (self.rows.value(), self.cols.value()) != self._grid_shape():
            keep = {w for w, b in self._cells.items() if b.isChecked()}
            self._build_grid(keep)
            self._fill_well_combos(self.rim_well.currentText(), self.centre_well.currentText())
        guided = self.mode.currentIndex() == 1
        for row in self._typed_rows:
            self._cal_form.setRowVisible(row, not guided)
        rim, centre = self.rim_well.currentText(), self.centre_well.currentText()
        self.hint.setText(
            f"Points 1–3: the rim of {rim}, spread around it, in any order — point 1 on "
            f"the rim's top edge (its height sets the safe travel height). Point 4: the "
            f"centre of {centre} with the nozzle on its floor (the floor sets the first "
            f"layer). " + ("The program asks for each point when the print starts: jog "
                           "there and press Resume." if guided else
                           "Jog to each point and copy X / Y (and Z for 1 and 4) from "
                           "the controller."))
        self._run_form.setRowVisible(self.dwell, self.between.currentIndex() == 2)
        pl = self.placement()
        order = plc.print_order(pl.wells, pl.plate) if pl.wells else []
        self.selected_label.setText(
            f"{len(order)} well(s), printed in this order: {' '.join(order)}" if order
            else "No wells selected.")
        self.result.setText(self._calibration_text(pl))

    def _grid_shape(self):
        if not self._cells:
            return (0, 0)
        return (len({n[0] for n in self._cells}), len({n[1:] for n in self._cells}))

    def _fit_line(self, pl: plc.Placement) -> List[str]:
        if not self._part_radius:
            return []
        room = pl.plate.well_diameter / 2.0
        ok = self._part_radius <= room
        colour = theme.TEXT_DIM if ok else theme.SELECT
        return [f"<span style='color:{colour}'>Part reaches "
                f"{self._part_radius:.2f} mm from its centre; a well has "
                f"{room:.2f} mm{'' if ok else ' — it will not fit'}</span>"]

    def _calibration_text(self, pl: plc.Placement) -> str:
        bad = [m for m in plc.problems(pl) if m.startswith("Plate calibration")]
        if pl.guided:
            if bad:
                return f"<span style='color:{theme.SELECT}'>⚠ {bad[0]}</span>"
            return "<br>".join(["A summary (centre, plate angle, spacing, rim and floor "
                                "height) is shown before printing starts."]
                               + self._fit_line(pl))
        try:
            plc._well_pair(pl)
        except ValueError as e:
            return f"<span style='color:{theme.SELECT}'>⚠ {e}</span>"
        pts = [tuple(p) for p in pl.rim_points]
        if len(set(pts)) == 1 and (pl.centre_x, pl.centre_y) == (0.0, 0.0):
            return "Enter the four measured points."            # nothing typed yet
        try:
            cal = plc.calibrate(pl)
        except ValueError as e:
            return f"<span style='color:{theme.SELECT}'>⚠ {e}</span>"
        lines = [f"{pl.rim_well} centre: X {cal.ref_centre[0]:.3f}, Y {cal.ref_centre[1]:.3f}",
                 f"Plate angle {cal.angle:+.2f}° · spacing {cal.spacing_error:+.2f} % vs "
                 f"the plate values",
                 f"Layer 1 on the floor at Z {pl.floor_z:g} · travel above Z "
                 f"{max(pl.rim_z, pl.floor_z):g} + clearance"]
        return "<br>".join(lines + self._fit_line(pl))
