"""Main application window.

Layout: parameter panel (left dock) | preview + layer slider (centre) |
g-code view (right dock).  A drag-edit in the preview rewrites the toolpath and
re-renders only the g-code text (no reslice/replan), so editing stays instant.
"""
from __future__ import annotations

import difflib
import os
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import (
    QAction, QTextCursor, QColor, QTextCharFormat, QBrush, QShortcut, QKeySequence,
)
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QDockWidget, QSlider,
    QLabel, QPlainTextEdit, QFileDialog, QMessageBox, QPushButton, QToolBar,
    QToolButton, QMenu, QSizePolicy, QApplication,
)

from ..model import PrintSettings, Dialect, DriveMode
from ..pipeline import Project
from ..geometry import stlslicer
from ..gcode import writer as gwriter
from ..gcode import flavour as flavourmod
from ..infill import patterns
from .. import settingsio
from .controls import ParameterPanel, SourceSpec
from .preview2d import PreviewScene, PreviewView
from .sideview import SideScene, SideInset
from .codeview import NumberedTextEdit
from .helpview import MarkdownViewer
from . import theme


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("BioprintGEN — extrusion bioprinting g-code")
        self.resize(1500, 920)

        self.project: Optional[Project] = None
        self.glines: List[gwriter.GLine] = []
        self._stl_model: Optional[stlslicer.SlicedModel] = None
        self._line_starts: List[int] = []      # char offset of each gline
        # tool-change bookkeeping
        self._clean_glines: List[gwriter.GLine] = []      # before tool-change insertion
        self._applied_glines: List[gwriter.GLine] = []    # after
        self._move_to_line: dict = {}                     # (layer, move) -> clean line no.
        self._last_sel_line: Optional[int] = None
        # panel shows the clean baseline by default so typed line numbers stay
        # stable; the toolbar toggle switches to the applied (tool-change) view.
        self._show_tc = False
        self._geom_sig = None                             # last geometry signature
        self._syncing = False          # guards preview <-> g-code selection sync
        self._suppress_scroll = False  # don't yank the cursor while syncing from g-code

        self._build_ui()
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(250)
        self._debounce.timeout.connect(self.generate)

        self.panel.changed.connect(self._on_param_changed)
        self.panel.stl_requested.connect(self.import_stl)
        self.panel.line_from_selection.connect(self._on_line_from_selection)
        self.scene.edited.connect(self._on_layer_edited)
        self.scene.segment_selected.connect(self._on_segment_selected)
        self.gcode_view.cursorPositionChanged.connect(self._on_gcode_cursor)

        self._load_defaults()
        self.generate()

    # ------------------------------------------------------------------ defaults
    def _load_defaults(self):
        """Apply `default_settings.json` (read-only) to the panel, if present."""
        loaded = settingsio.load_defaults()
        if not loaded:
            return
        settings, source, ui = loaded
        try:
            self.panel.apply_settings(settings)
            if source:
                self.panel.apply_source(SourceSpec(
                    kind=source.get("kind", "cuboid"),
                    width=float(source.get("width", 10.0)),
                    depth=float(source.get("depth", 10.0)),
                    height=float(source.get("height", 5.0)),
                    diameter=float(source.get("diameter", 12.0)),
                    stl_path=source.get("stl_path") or None,
                ))
            panels = ui.get("expanded_panels")
            if panels:
                self.panel.set_expanded_panels(panels)
        except Exception as e:  # noqa
            self.statusBar().showMessage(f"default_settings.json: {e}")

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        # panel dock
        self.panel = ParameterPanel()
        self._param_dock = QDockWidget("Parameters", self)
        self._param_dock.setWidget(self.panel)
        self._param_dock.setFeatures(QDockWidget.DockWidgetMovable)
        self.addDockWidget(Qt.LeftDockWidgetArea, self._param_dock)

        # centre: preview + slider
        centre = QWidget()
        v = QVBoxLayout(centre)
        v.setContentsMargins(8, 8, 8, 8)
        self.scene = PreviewScene()
        self.view = PreviewView(self.scene)
        v.addWidget(self.view, 1)

        row = QHBoxLayout()
        self.layer_slider = QSlider(Qt.Horizontal)
        self.layer_slider.setMinimum(0)
        self.layer_slider.valueChanged.connect(self._on_layer_change)
        self.layer_label = QLabel("layer 0")
        self.layer_label.setObjectName("stat")
        prev_btn = QToolButton()
        prev_btn.setArrowType(Qt.LeftArrow)
        prev_btn.setToolTip("Previous layer")
        prev_btn.clicked.connect(lambda: self._step_layer(-1))
        next_btn = QToolButton()
        next_btn.setArrowType(Qt.RightArrow)
        next_btn.setToolTip("Next layer")
        next_btn.clicked.connect(lambda: self._step_layer(1))
        fit_btn = QPushButton("Fit")
        fit_btn.clicked.connect(self.view.fit)
        row.addWidget(QLabel("Layer"))
        row.addWidget(prev_btn)
        row.addWidget(self.layer_slider, 1)
        row.addWidget(next_btn)
        row.addWidget(self.layer_label)
        row.addWidget(fit_btn)
        v.addLayout(row)

        self.stats = QLabel("")
        self.stats.setObjectName("stat")
        v.addWidget(self.stats)
        self.setCentralWidget(centre)

        # gcode dock: toggle bar on top of the code view
        self.gcode_view = NumberedTextEdit()
        self.gcode_view.setReadOnly(True)
        self.gcode_view.setLineWrapMode(QPlainTextEdit.NoWrap)
        gpanel = QWidget()
        gv = QVBoxLayout(gpanel)
        gv.setContentsMargins(6, 6, 6, 6)
        gv.setSpacing(6)
        self.btn_show_tc = QToolButton()
        self.btn_show_tc.setText("Toggle – show tool change")
        self.btn_show_tc.setCheckable(True)
        self.btn_show_tc.setChecked(False)
        self.btn_show_tc.setToolTip(
            "On: shows the g-code with tool changes inserted (the offset sequence).\n"
            "Off: shows the clean baseline whose line numbers the tool-section "
            "ranges refer to (use when typing start/end line numbers by hand).\n"
            "Export always includes the tool changes.")
        self.btn_show_tc.toggled.connect(self._toggle_show_tc)
        gv.addWidget(self.btn_show_tc)
        gv.addWidget(self.gcode_view, 1)
        self.gdock = QDockWidget("G-code", self)
        self.gdock.setWidget(gpanel)
        self.gdock.setFeatures(QDockWidget.DockWidgetMovable)
        self.addDockWidget(Qt.RightDockWidgetArea, self.gdock)

        # side-view (elevation) inset, floating over the top-right of the preview
        self.side_scene = SideScene()
        self.side_inset = SideInset(self.view, self.side_scene)
        self.side_view = self.side_inset.view
        self.side_inset.show()

        self._build_toolbar()
        self._apply_scaled_sizes()
        self.statusBar().showMessage("Ready")

    def _apply_scaled_sizes(self):
        """Re-apply the Python-set widget sizes at the current UI scale (the
        stylesheet handles the rest).  Called at build time and on every zoom."""
        self._param_dock.setMinimumWidth(theme.px(310))
        self.gdock.setMinimumWidth(theme.px(360))
        self.layer_label.setMinimumWidth(theme.px(120))
        self.panel.apply_scaled_sizes()

    def _build_toolbar(self):
        tb = QToolBar()
        tb.setMovable(False)
        self.addToolBar(tb)
        gen = QPushButton("Generate")
        gen.setObjectName("primary")
        gen.clicked.connect(self.generate)
        tb.addWidget(gen)
        act_imp = QAction("Import g-code", self)
        act_imp.setToolTip("Open a previously exported file and restore its settings")
        act_imp.triggered.connect(self.import_gcode)
        tb.addAction(act_imp)
        act_exp = QAction("Export g-code", self)
        act_exp.triggered.connect(self.export_gcode)
        tb.addAction(act_exp)
        tb.addSeparator()

        # Help with two entries, both rendering markdown live from disk
        help_btn = QToolButton()
        help_btn.setText("Help")
        help_btn.setPopupMode(QToolButton.InstantPopup)
        menu = QMenu(help_btn)
        act_readme = QAction("README", self)
        act_readme.triggered.connect(lambda: self._show_doc("README.md", "README"))
        act_manual = QAction("User manual", self)
        act_manual.triggered.connect(lambda: self._show_doc("MANUAL.md", "User manual"))
        menu.addAction(act_readme)
        menu.addAction(act_manual)
        help_btn.setMenu(menu)
        tb.addWidget(help_btn)

        # push the zoom + theme controls to the far right
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        tb.addWidget(spacer)

        # UI scale control (persisted to default_settings.json)
        zoom_out = QToolButton()
        zoom_out.setText("A−")
        zoom_out.setToolTip("Smaller interface (Ctrl+-)")
        zoom_out.clicked.connect(lambda: self._nudge_ui_scale(-theme.SCALE_STEP))
        tb.addWidget(zoom_out)
        self.scale_label = QLabel(f"{round(theme.current_scale() * 100)}%")
        self.scale_label.setObjectName("stat")
        self.scale_label.setAlignment(Qt.AlignCenter)
        self.scale_label.setMinimumWidth(theme.px(46))
        tb.addWidget(self.scale_label)
        zoom_in = QToolButton()
        zoom_in.setText("A+")
        zoom_in.setToolTip("Larger interface (Ctrl+=)")
        zoom_in.clicked.connect(lambda: self._nudge_ui_scale(theme.SCALE_STEP))
        tb.addWidget(zoom_in)
        for keys in ("Ctrl+=", "Ctrl++"):
            QShortcut(QKeySequence(keys), self, activated=lambda: self._nudge_ui_scale(theme.SCALE_STEP))
        QShortcut(QKeySequence("Ctrl+-"), self, activated=lambda: self._nudge_ui_scale(-theme.SCALE_STEP))
        QShortcut(QKeySequence("Ctrl+0"), self, activated=lambda: self._set_ui_scale(1.0))
        tb.addSeparator()

        self.theme_btn = QToolButton()
        self.theme_btn.setCheckable(True)
        self.theme_btn.setChecked(theme.current_theme() == "light")
        self.theme_btn.setText("Light mode" if theme.current_theme() == "dark"
                               else "Dark mode")
        self.theme_btn.setToolTip("Switch between light and dark appearance")
        self.theme_btn.toggled.connect(self._toggle_theme)
        tb.addWidget(self.theme_btn)

    # ------------------------------------------------------------------ docs
    def _show_doc(self, filename: str, title: str):
        root = Path(__file__).resolve().parent.parent.parent
        path = root / filename
        dlg = MarkdownViewer(path, title, self)
        dlg.exec()

    # ------------------------------------------------------------------ ui scale
    def _nudge_ui_scale(self, delta: float):
        self._set_ui_scale(theme.current_scale() + delta)

    def _set_ui_scale(self, scale: float):
        applied = theme.set_scale(scale)
        QApplication.instance().setStyleSheet(theme.build_qss())
        self._apply_scaled_sizes()
        self.scale_label.setText(f"{round(applied * 100)}%")
        if settingsio.save_ui_scale(applied):
            self.statusBar().showMessage(f"Interface scale {round(applied * 100)}%")
        else:
            self.statusBar().showMessage(
                f"Interface scale {round(applied * 100)}% "
                "(could not save to default_settings.json)")

    # ------------------------------------------------------------------ theme
    def _toggle_theme(self, light: bool):
        name = "light" if light else "dark"
        theme.apply_theme(QApplication.instance(), name)
        self.theme_btn.setText("Dark mode" if light else "Light mode")
        # scenes cache colours in their items, so rebuild them
        self.scene.setBackgroundBrush(QBrush(QColor(theme.BG)))
        self.side_scene.setBackgroundBrush(QBrush(QColor(theme.BG)))
        self.side_inset.refresh_theme()
        if self.project and self.project.toolpath:
            self.side_scene.set_toolpath(self.project.toolpath)
            self._show_layer(self.layer_slider.value())

    # ------------------------------------------------------------------ actions
    def _on_param_changed(self):
        self._debounce.start()

    def import_stl(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Import STL", "", "Mesh files (*.stl *.obj *.ply *.off);;All files (*)")
        if not path:
            return
        try:
            self._stl_model = stlslicer.load_stl(path)
        except Exception as e:  # noqa
            QMessageBox.critical(self, "STL error", f"Could not load mesh:\n{e}")
            return
        self.panel.set_stl_path(path)
        # switch shape to STL
        self.panel.shape.setCurrentIndex(2)
        self.generate()

    # ------------------------------------------------------------------ import
    def import_gcode(self):
        """Open an exported file, restore its settings + source into the panel,
        rebuild the toolpath from them, and report whether the rebuild matches."""
        path, _ = QFileDialog.getOpenFileName(
            self, "Import g-code", "",
            "G-code (*.gcode *.nc *.txt);;All files (*)")
        if not path:
            return
        try:
            text = Path(path).read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            QMessageBox.critical(self, "Import failed", f"Could not read {path}:\n{e}")
            return
        parsed = settingsio.parse_gcode_settings(text)
        if parsed is None:
            QMessageBox.warning(
                self, "Nothing to restore",
                "This file contains no BioprintGEN settings block, so its "
                "settings can't be restored.\n\nOnly files exported with "
                "'Write settings as comment block' enabled can be imported.")
            return
        settings, source, flavour_name, complete = parsed
        notes: List[str] = []

        # custom flavours are stored by name; resolve against the local library
        if settings.dialect == Dialect.CUSTOM:
            tmpl = flavourmod.list_flavours().get(flavour_name or "")
            if tmpl is None:
                settings.dialect = Dialect.PLANET_CNC
                notes.append(f"Custom flavour “{flavour_name}” isn't in your flavour "
                             "library — switched to Planet CNC.")
            settings.custom_flavour = tmpl

        spec = None
        if complete and source:
            spec = SourceSpec(
                kind=source.get("kind", "cuboid"),
                width=float(source.get("width", 10.0)),
                depth=float(source.get("depth", 10.0)),
                height=float(source.get("height", 5.0)),
                diameter=float(source.get("diameter", 12.0)),
                stl_path=source.get("stl_path") or None,
            )
            if spec.kind == "stl":
                stl = self._locate_stl(spec.stl_path, Path(path).parent)
                if stl is None:
                    spec = None
                    notes.append("The STL used for this file wasn't found — choose "
                                 "it in Design → Choose STL file to rebuild the part.")
                else:
                    try:
                        self._stl_model = stlslicer.load_stl(str(stl))
                        spec.stl_path = str(stl)
                    except Exception as e:  # noqa
                        spec = None
                        notes.append(f"Could not load the STL ({e}).")
        elif not complete:
            notes.append("This file was exported by an older version that didn't "
                         "record its shape. Print settings were restored; the part "
                         "was rebuilt with the shape currently set in Design.")

        self.panel.apply_settings(settings)
        if spec is not None:
            self.panel.apply_source(spec)
        self._geom_sig = None                      # always rebuild from the file
        self.generate()
        if not self.project:
            return

        name = os.path.basename(path)
        if spec is not None and self.project.toolpath:
            diff = self._count_motion_differences(text, self.project.gcode_text())
            if diff == 0:
                self.statusBar().showMessage(
                    f"Imported {name} — settings restored, rebuilt toolpath matches the file")
            else:
                notes.insert(0, f"The rebuilt g-code differs from the file in {diff} "
                                "motion line(s). The file probably contains manual "
                                "vertex edits, which aren't stored in its settings, or "
                                "was made by a different version. The preview and code "
                                "panel show the rebuilt version; the file on disk is "
                                "unchanged.")
        if notes:
            QMessageBox.information(self, f"Imported {name}", "\n\n".join(notes))
            self.statusBar().showMessage(f"Imported {name} — see notes")

    def _locate_stl(self, stl_path: Optional[str], gcode_dir: Path) -> Optional[Path]:
        """Find the STL a file was made from: its stored path, then next to the
        g-code file, then ask the user."""
        if stl_path:
            p = Path(stl_path)
            if p.is_file():
                return p
            beside = gcode_dir / p.name
            if beside.is_file():
                return beside
        hint = Path(stl_path).name if stl_path else "the STL"
        chosen, _ = QFileDialog.getOpenFileName(
            self, f"Locate {hint}", str(gcode_dir),
            "Mesh files (*.stl *.obj *.ply *.off);;All files (*)")
        return Path(chosen) if chosen else None

    @staticmethod
    def _count_motion_differences(a: str, b: str) -> int:
        """Lines that differ once comments, blanks and line endings are ignored."""
        def motion(text):
            out = []
            for line in text.replace("\r\n", "\n").split("\n"):
                s = line.strip()
                if s and not s.startswith(";"):
                    out.append(s)
            return out
        # a real diff, so one inserted line counts once instead of shifting
        # every line after it
        ops = difflib.SequenceMatcher(None, motion(a), motion(b),
                                      autojunk=False).get_opcodes()
        return sum(max(i2 - i1, j2 - j1) for tag, i1, i2, j1, j2 in ops
                   if tag != "equal")

    def _current_settings(self) -> PrintSettings:
        return self.panel.build_settings()

    def _geom_signature(self, spec, s: PrintSettings):
        """Everything that changes the sliced/planned toolpath. If this is
        unchanged we reuse the existing toolpath (preserving manual vertex edits
        and tool assignments) and only re-render / re-apply tool sections."""
        return (
            spec.kind, spec.width, spec.depth, spec.height, spec.diameter, spec.stl_path,
            s.layer_height, s.first_layer_height,
            tuple((x.z_start, x.z_end, x.height) for x in s.layer_sections),
            s.line_width, s.infill_angle, s.layer_rotation, s.infill_type,
            s.effective_spacing(), s.effective_gyroid_period(),
            s.perimeters, s.minimize_crossings, s.rotate_start,
            tuple((x.z_start, x.z_end, x.infill_type, x.percent)
                  for x in s.infill_sections),
            patterns.generation(),
        )

    def generate(self):
        spec = self.panel.source_spec()
        settings = self._current_settings()
        problems = settings.validate()
        if problems:
            extra = f"  (+{len(problems) - 1} more)" if len(problems) > 1 else ""
            self.statusBar().showMessage(f"Cannot generate — {problems[0]}{extra}")
            return
        geom_sig = self._geom_signature(spec, settings)
        rebuild = self.project is None or geom_sig != self._geom_sig
        # slicing a fine/large mesh takes seconds on the UI thread; show a busy
        # cursor so it reads as "working", not "frozen"
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self._generate_inner(spec, settings, geom_sig, rebuild)
        finally:
            QApplication.restoreOverrideCursor()

    def _generate_inner(self, spec, settings, geom_sig, rebuild):
        try:
            if rebuild:
                if spec.kind == "cuboid":
                    self.project = Project.from_cuboid(spec.width, spec.depth, spec.height, settings)
                elif spec.kind == "cylinder":
                    self.project = Project.from_cylinder(spec.diameter, spec.height, settings)
                else:
                    if self._stl_model is None:
                        self.statusBar().showMessage("Choose an STL file first")
                        return
                    layers = stlslicer.slice_model(self._stl_model, settings)
                    self.project = Project(settings=settings, layers=layers,
                                           source_desc=f"STL {spec.stl_path}")
                    self.project._model = self._stl_model
                self.project.plan()
                self._geom_sig = geom_sig
            else:
                # geometry unchanged: keep the toolpath (and manual edits), just
                # swap in the new settings for rendering / tool-section apply.
                self.project.settings = settings
        except Exception as e:  # noqa
            self.statusBar().showMessage(f"Generation failed: {e}")
            return
        self._regenerate_gcode(settings)
        self.side_scene.set_toolpath(self.project.toolpath)
        n = len(self.project.toolpath)
        self.layer_slider.setMaximum(max(0, n - 1))
        cur = min(self.layer_slider.value(), n - 1)
        self.layer_slider.setValue(cur)
        self._show_layer(cur)
        if rebuild:
            self.view.fit()
        self.side_view.fit()
        self._update_stats()
        msg = f"Generated {self.project.source_desc}"
        if settings.tool_change_enabled and settings.tool_line_ranges and not self._show_tc:
            msg += (f"  ·  {len(settings.tool_line_ranges)} tool section(s) applied — "
                    "enable 'Show tool changes' or export to see the offset sequence")
        self.statusBar().showMessage(msg)

    def _regenerate_gcode(self, settings):
        """Reset per-move tools and (re)apply the line-range tool sections, then
        render.  Used on parameter/tool-section changes (a deliberate re-mark)."""
        tp = self.project.toolpath
        for lt in tp:
            for m in lt.moves:
                m.extruder = 1
        self._clean_glines = self.project.glines()          # truly clean (all tool 1)
        self._move_to_line = gwriter.move_line_map(self._clean_glines)
        if settings.tool_change_enabled and settings.tool_line_ranges:
            gwriter.apply_line_ranges(tp, self._clean_glines, settings.tool_line_ranges)
            self._applied_glines = self.project.glines()
        else:
            self._applied_glines = self._clean_glines
        self.glines = self._applied_glines if self._show_tc else self._clean_glines
        self._render_gcode_text()

    def _rerender_gcode(self):
        """Re-render after a geometry edit *without* touching per-move tools, so
        split/merged vertices keep the tool they inherited."""
        tp = self.project.toolpath
        saved = [m.extruder for lt in tp for m in lt.moves]
        for lt in tp:
            for m in lt.moves:
                m.extruder = 1
        self._clean_glines = self.project.glines()
        self._move_to_line = gwriter.move_line_map(self._clean_glines)
        it = iter(saved)
        for lt in tp:
            for m in lt.moves:
                m.extruder = next(it)
        self._applied_glines = self.project.glines()
        self.glines = self._applied_glines if self._show_tc else self._clean_glines
        self._render_gcode_text()

    def _update_gcode_title(self):
        s = self.project.settings if self.project else None
        has_tc = bool(s and s.tool_change_enabled and s.tool_line_ranges)
        if not has_tc:
            self.gdock.setWindowTitle("G-code")
        elif self._show_tc:
            self.gdock.setWindowTitle("G-code — with tool changes")
        else:
            self.gdock.setWindowTitle("G-code — clean view (tool changes hidden — "
                                      "toggle 'Show tool changes')")

    def _render_gcode_text(self):
        self._update_gcode_title()
        text_parts, offsets, off = [], [], 0
        for g in self.glines:
            offsets.append(off)
            text_parts.append(g.text)
            off += len(g.text) + 1
        self._line_starts = offsets
        self.gcode_view.setPlainText("\n".join(text_parts))

    def _on_layer_change(self, i):
        self._show_layer(i)

    def _step_layer(self, delta):
        self.layer_slider.setValue(self.layer_slider.value() + delta)

    def _show_layer(self, i):
        if not self.project or not self.project.toolpath:
            return
        i = max(0, min(i, len(self.project.toolpath) - 1))
        lt = self.project.toolpath[i]
        self.scene.set_layer(lt)
        self.side_scene.set_current(i)
        self.layer_label.setText(f"layer {lt.index}   z={lt.z:.3f} mm")
        if not self._suppress_scroll:
            self._scroll_gcode_to_layer(i)

    def _on_layer_edited(self, layer_index):
        # geometry changed in-place; re-render but keep per-move tool assignments
        self._rerender_gcode()
        self.side_scene.set_toolpath(self.project.toolpath)
        self.side_scene.set_current(self.layer_slider.value())
        self._update_stats()
        self.statusBar().showMessage(f"Edited layer {layer_index} — g-code updated")

    def _on_segment_selected(self, mi):
        cur = self.layer_slider.value()
        # remember the clean-baseline line for the tool-range "set from selection" buttons
        self._last_sel_line = self._move_to_line.get((cur, mi))
        if self._syncing:
            return
        for idx, g in enumerate(self.glines):
            if g.layer == cur and g.move == mi:
                self._select_gcode_line(idx)
                break

    def _on_gcode_cursor(self):
        """Clicking a g-code line selects the matching segment in the preview,
        switching to its layer first if it isn't the one on screen."""
        if self._syncing or not self.project:
            return
        cursor = self.gcode_view.textCursor()
        idx = cursor.blockNumber()
        if idx < 0 or idx >= len(self.glines):
            return
        # highlight the clicked line itself (a plain click, not a drag-selection)
        if not cursor.hasSelection():
            self._syncing = True
            try:
                cursor.select(QTextCursor.LineUnderCursor)
                self.gcode_view.setTextCursor(cursor)
            finally:
                self._syncing = False
        g = self.glines[idx]
        if g.layer is None:
            return
        self._suppress_scroll = True     # keep the cursor where the user clicked
        try:
            if g.layer != self.layer_slider.value():
                self.layer_slider.setValue(g.layer)
            if g.move is not None:
                self._syncing = True
                try:
                    self.scene.select_segment(g.move)
                finally:
                    self._syncing = False
        finally:
            self._suppress_scroll = False

    def _on_line_from_selection(self, which):
        if self._last_sel_line is None:
            self.statusBar().showMessage("Select a segment in the preview first")
            return
        col = 0 if which == "start" else 1
        self.panel.tool_ranges.set_current_cell(col, self._last_sel_line)
        self.statusBar().showMessage(f"Set {which} line to {self._last_sel_line}")

    def _toggle_show_tc(self, on):
        self._show_tc = bool(on)
        if not self.project:
            return
        self.glines = self._applied_glines if self._show_tc else self._clean_glines
        self._render_gcode_text()
        self._scroll_gcode_to_layer(self.layer_slider.value())

    # ------------------------------------------------------------------ gcode nav
    def _select_gcode_line(self, idx):
        if idx >= len(self._line_starts):
            return
        self._syncing = True             # programmatic move: don't echo back
        try:
            cur = self.gcode_view.textCursor()
            cur.setPosition(self._line_starts[idx])
            cur.select(QTextCursor.LineUnderCursor)
            self.gcode_view.setTextCursor(cur)
            self.gcode_view.centerCursor()
        finally:
            self._syncing = False

    def _scroll_gcode_to_layer(self, layer_index):
        for idx, g in enumerate(self.glines):
            if g.kind == "layer" and g.layer == layer_index:
                self._select_gcode_line(idx)
                break

    def _update_stats(self):
        if not self.project:
            return
        st = self.project.stats()
        self.stats.setText(
            f"layers {st['layers']}   moves {st['moves']}   "
            f"extrude {st['extrude_mm']} mm   travel {st['travel_mm']} mm")

    def _default_export_name(self) -> str:
        """<shape>_<flavour>[_<drive>]_<date>.gcode

        shape   = STL file stem, or 'cuboid' / 'cylinder'
        flavour = planetcnc / marlin / the custom flavour's name
        drive   = piston / pneumatic (Planet CNC only)
        """
        spec = self.panel.source_spec()
        if spec.kind == "stl" and spec.stl_path:
            shape = Path(spec.stl_path).stem
        else:
            shape = spec.kind or "part"

        s = self.project.settings if self.project else self._current_settings()
        if s.dialect == Dialect.PLANET_CNC:
            flavour = "planetcnc"
        elif s.dialect == Dialect.MARLIN_ABS_E:
            flavour = "marlin"
        else:
            flavour = getattr(s.custom_flavour, "name", None) or "custom"

        parts = [shape, flavour]
        if s.dialect == Dialect.PLANET_CNC:
            parts.append("piston" if s.drive == DriveMode.PISTON else "pneumatic")
        parts.append(datetime.now().strftime("%Y-%m-%d"))

        def clean(p: str) -> str:
            keep = "-_."
            return "".join(c for c in str(p).replace(" ", "-")
                           if c.isalnum() or c in keep).strip("-_.") or "part"

        return "_".join(clean(p) for p in parts) + ".gcode"

    def export_gcode(self):
        if not self.project:
            return
        default = self._default_export_name()
        path, _ = QFileDialog.getSaveFileName(self, "Export g-code", default,
                                              "G-code (*.gcode *.nc *.txt)")
        if not path:
            return
        # Write platform-independently: UTF-8 regardless of the machine locale
        # (the locale codec can't represent every character and would otherwise
        # raise), and an explicit line terminator so the file is byte-identical
        # whichever OS generated it.
        s = self.project.settings
        try:
            with open(path, "w", encoding="utf-8", newline=s.line_terminator()) as f:
                f.write(self.project.gcode_text())
        except OSError as e:
            QMessageBox.critical(self, "Export failed", f"Could not write {path}:\n{e}")
            return
        ending = "CRLF" if s.line_terminator() == "\r\n" else "LF"
        self.statusBar().showMessage(
            f"Saved {os.path.basename(path)}  (UTF-8, {ending})")


def run():
    import sys
    app = QApplication(sys.argv)
    # startup theme + scale come from default_settings.json (ui.theme, ui.scale)
    name, scale = "dark", 1.0
    loaded = settingsio.load_defaults()
    if loaded:
        ui = loaded[2]
        name = (ui.get("theme") or "dark").lower()
        scale = ui.get("scale", 1.0)
    theme.apply_theme(app, name if name in theme.THEMES else "dark", scale)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())
