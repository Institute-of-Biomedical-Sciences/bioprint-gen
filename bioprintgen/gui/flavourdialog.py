"""Editor dialog for custom g-code flavours.

Lets the user define per-action templates (travel, extrude, layer change, tool
change, ...), save them to the on-disk store, and import/export flavour files.
See `bioprintgen.gcode.flavour` for the template model and placeholders.
"""
from __future__ import annotations

from typing import Dict, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QComboBox, QLineEdit,
    QPlainTextEdit, QPushButton, QLabel, QFileDialog, QMessageBox, QWidget,
    QScrollArea,
)

from ..gcode import flavour as flavourmod
from ..gcode.flavour import FlavourTemplate


# (attribute, label, placeholder hint)
_FIELDS = [
    ("header", "Header", "{name} {layer_count} {first_z}"),
    ("layer_change", "Layer change", "{layer} {z} {height} {f}"),
    ("travel", "Travel move", "{x} {y} {f}"),
    ("extrude", "Extrude move", "{x} {y} {e} {de} {f} {length}"),
    ("tool_change", "Tool change", "{tool} {offx} {offy}"),
    ("extruder_on", "Extruder on (optional)", "{tool}"),
    ("extruder_off", "Extruder off (optional)", "{tool}"),
    ("footer", "Footer", "{name} {z_max} {safe_z}"),
]


class FlavourDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Custom g-code flavours")
        self.resize(560, 640)
        self.last_saved_name: Optional[str] = None
        self._edits: Dict[str, QPlainTextEdit] = {}

        root = QVBoxLayout(self)

        top = QHBoxLayout()
        self.picker = QComboBox()
        self.picker.currentIndexChanged.connect(self._load_selected)
        new_btn = QPushButton("New")
        new_btn.clicked.connect(self._new)
        top.addWidget(QLabel("Flavour"))
        top.addWidget(self.picker, 1)
        top.addWidget(new_btn)
        root.addLayout(top)

        # scrollable form of template fields
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        form = QFormLayout(inner)
        self.name_edit = QLineEdit()
        self.prefix_edit = QLineEdit(";")
        form.addRow("Name", self.name_edit)
        form.addRow("Comment prefix", self.prefix_edit)
        for attr, label, hint in _FIELDS:
            ed = QPlainTextEdit()
            ed.setMaximumHeight(70)
            ed.setPlaceholderText(hint)
            self._edits[attr] = ed
            form.addRow(label, ed)
            h = QLabel(f"placeholders: {hint}")
            h.setObjectName("hint")
            form.addRow("", h)
        scroll.setWidget(inner)
        root.addWidget(scroll, 1)

        note = QLabel("Leave a field blank to emit nothing for that action. "
                      "Use \\n in a template box by pressing Enter for multiple lines.")
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
            self._new()

    # ------------------------------------------------------------------ helpers
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
                            comment_prefix=self.prefix_edit.text() or ";")
        for attr, ed in self._edits.items():
            setattr(t, attr, ed.toPlainText())
        return t

    def _fill_form(self, t: FlavourTemplate):
        self.name_edit.setText(t.name)
        self.prefix_edit.setText(t.comment_prefix)
        for attr, ed in self._edits.items():
            ed.setPlainText(getattr(t, attr, ""))

    # ------------------------------------------------------------------ slots
    def _new(self):
        self._fill_form(FlavourTemplate(name="New flavour"))

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
