"""Editor dialog for custom g-code flavours.

Lets the user define per-action templates (travel, extrude, layer change, tool
change, ...), start from a shipped template (Planet CNC / Marlin reproduce the
built-in writers exactly), save them to the app folder, and import/export
flavour files.  See `bioprintgen.gcode.flavour` for the template model, the
placeholders and the {?condition:...} syntax.
"""
from __future__ import annotations

from typing import Dict, Optional

from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QComboBox, QLineEdit,
    QPlainTextEdit, QPushButton, QLabel, QFileDialog, QMessageBox, QWidget,
    QScrollArea, QMenu,
)

from ..gcode import flavour as flavourmod
from ..gcode.flavour import FlavourTemplate, ACTIONS, REFERENCE
from . import theme


class FlavourDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Custom g-code flavours")
        self.resize(theme.px(640), theme.px(720))
        self.last_saved_name: Optional[str] = None
        self._edits: Dict[str, QPlainTextEdit] = {}
        mono = QFontDatabase.systemFont(QFontDatabase.FixedFont)

        root = QVBoxLayout(self)

        top = QHBoxLayout()
        self.picker = QComboBox()
        self.picker.currentIndexChanged.connect(self._load_selected)
        self.new_btn = QPushButton("New from…")
        self.new_menu = QMenu(self.new_btn)
        self.new_btn.setMenu(self.new_menu)
        self._build_new_menu()
        help_btn = QPushButton("Syntax…")
        help_btn.clicked.connect(self._show_reference)
        top.addWidget(QLabel("Flavour"))
        top.addWidget(self.picker, 1)
        top.addWidget(self.new_btn)
        top.addWidget(help_btn)
        root.addLayout(top)

        # scrollable form of template fields, grouped like the writer's events
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        form = QFormLayout(inner)
        form.setRowWrapPolicy(QFormLayout.WrapAllRows)   # caption above the box
        self.name_edit = QLineEdit()
        self.desc_edit = QLineEdit()
        self.prefix_edit = QLineEdit(";")
        form.addRow("Name", self.name_edit)
        form.addRow("Description", self.desc_edit)
        form.addRow("Comment prefix", self.prefix_edit)
        for group, actions in ACTIONS:
            title = QLabel(group)
            title.setObjectName("groupTitle")
            title.setStyleSheet("font-weight: bold; margin-top: 8px;")
            form.addRow(title)
            for attr, label, hint in actions:
                ed = QPlainTextEdit()
                ed.setFont(mono)
                ed.setMaximumHeight(theme.px(78))
                ed.setTabStopDistance(theme.px(28))
                ed.setLineWrapMode(QPlainTextEdit.NoWrap)
                self._edits[attr] = ed
                form.addRow(label, ed)
                if hint:
                    h = QLabel(hint)
                    h.setObjectName("hint")
                    h.setWordWrap(True)
                    form.addRow(h)
        scroll.setWidget(inner)
        root.addWidget(scroll, 1)

        note = QLabel("A blank field emits nothing. {?cond:text} emits text only when "
                      "cond holds (e.g. {?pneumatic:…}, {?!zero_xy:…}); see Syntax… "
                      f"Saved in {flavourmod.flavours_dir()}")
        note.setObjectName("hint")
        note.setWordWrap(True)
        root.addWidget(note)

        # action buttons
        btns = QHBoxLayout()
        for text, slot in (("Save", self._save), ("Delete", self._delete),
                           ("Import…", self._import), ("Export…", self._export),
                           ("Close", self.accept)):
            b = QPushButton(text)
            b.clicked.connect(slot)
            if text == "Save":
                b.setObjectName("primary")
            btns.addWidget(b)
        root.addLayout(btns)

        self._reload_picker()
        if self.picker.count() > 0:
            self._load_selected()
        else:
            self._new_from(FlavourTemplate(name="New flavour", description=""))

    # ------------------------------------------------------------------ helpers
    def _build_new_menu(self):
        self.new_menu.clear()
        blank = self.new_menu.addAction("Blank")
        blank.triggered.connect(lambda: self._new_from(FlavourTemplate(name="New flavour")))
        templates = flavourmod.list_templates()
        if templates:
            self.new_menu.addSeparator()
        for name, t in templates.items():
            act = self.new_menu.addAction(name)
            act.setToolTip(t.description)
            act.triggered.connect(lambda _=False, t=t: self._new_from(t))

    def _reload_picker(self, select: Optional[str] = None):
        self.picker.blockSignals(True)
        self.picker.clear()
        self._flavours = flavourmod.list_flavours()
        for name in self._flavours:
            self.picker.addItem(name)
        if select:
            i = self.picker.findText(select)
            if i >= 0:
                self.picker.setCurrentIndex(i)
        self.picker.blockSignals(False)

    def _template_from_form(self) -> FlavourTemplate:
        t = FlavourTemplate(name=self.name_edit.text().strip() or "Custom",
                            description=self.desc_edit.text().strip(),
                            comment_prefix=self.prefix_edit.text() or ";")
        for attr, ed in self._edits.items():
            setattr(t, attr, ed.toPlainText())
        return t

    def _fill_form(self, t: FlavourTemplate):
        self.name_edit.setText(t.name)
        self.desc_edit.setText(t.description)
        self.prefix_edit.setText(t.comment_prefix)
        for attr, ed in self._edits.items():
            ed.setPlainText(getattr(t, attr, ""))

    # ------------------------------------------------------------------ slots
    def _new_from(self, t: FlavourTemplate):
        """Load a copy of `t` under a new name (saving never touches the template)."""
        copy = FlavourTemplate.from_dict(t.to_dict())
        if copy.name.endswith(" (template)"):
            copy.name = copy.name[: -len(" (template)")] + " (custom)"
        self.picker.blockSignals(True)
        self.picker.setCurrentIndex(-1)
        self.picker.blockSignals(False)
        self._fill_form(copy)

    def _new(self):
        self._new_from(FlavourTemplate(name="New flavour"))

    def _show_reference(self):
        box = QMessageBox(self)
        box.setWindowTitle("Flavour template syntax")
        box.setText("Placeholders, conditions and the order of events:")
        box.setInformativeText(f"<pre>{_html_escape(REFERENCE)}</pre>")
        box.exec()

    def _load_selected(self):
        name = self.picker.currentText()
        if name and name in getattr(self, "_flavours", {}):
            self._fill_form(self._flavours[name])

    def _save(self):
        t = self._template_from_form()
        flavourmod.save_flavour(t)
        self.last_saved_name = t.name
        self._reload_picker(select=t.name)
        QMessageBox.information(self, "Saved", f"Flavour “{t.name}” saved.")

    def _delete(self):
        name = self.name_edit.text().strip()
        if not name:
            return
        if QMessageBox.question(self, "Delete", f"Delete flavour “{name}”?") \
                == QMessageBox.Yes:
            flavourmod.delete_flavour(name)
            self._reload_picker()
            self._new()

    def _import(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Import flavour", "", "Flavour JSON (*.json);;All files (*)")
        if not path:
            return
        try:
            t = flavourmod.import_flavour(path)
        except Exception as e:  # noqa
            QMessageBox.critical(self, "Import error", str(e))
            return
        self.last_saved_name = t.name
        self._reload_picker(select=t.name)
        self._fill_form(t)

    def _export(self):
        t = self._template_from_form()
        path, _ = QFileDialog.getSaveFileName(
            self, "Export flavour", f"{t.name}.json",
            "Flavour JSON (*.json);;All files (*)")
        if not path:
            return
        try:
            flavourmod.export_flavour(t, path)
        except Exception as e:  # noqa
            QMessageBox.critical(self, "Export error", str(e))


def _html_escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
