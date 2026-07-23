"""A small markdown viewer used for the Help menu.

The document is re-read from disk every time the window is opened (and via the
Reload button), so editing the .md file on disk is reflected without restarting.
Relative image paths resolve against the file's own folder.
"""
from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QUrl, Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTextBrowser, QPushButton, QLabel,
)


class MarkdownViewer(QDialog):
    def __init__(self, path, title: str, parent=None):
        super().__init__(parent)
        self._path = Path(path)
        self.setWindowTitle(title)
        self.resize(900, 720)

        v = QVBoxLayout(self)
        self.browser = QTextBrowser()
        self.browser.setOpenExternalLinks(True)
        v.addWidget(self.browser, 1)

        row = QHBoxLayout()
        self.path_label = QLabel(str(self._path))
        self.path_label.setObjectName("hint")
        self.path_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        row.addWidget(self.path_label, 1)
        reload_btn = QPushButton("Reload")
        reload_btn.clicked.connect(self.reload)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        row.addWidget(reload_btn)
        row.addWidget(close_btn)
        v.addLayout(row)

        self.reload()

    def reload(self):
        folder = str(self._path.parent)
        # let relative ![](images/x.png) resolve next to the markdown file
        self.browser.setSearchPaths([folder])
        self.browser.document().setBaseUrl(QUrl.fromLocalFile(folder + os.sep))
        try:
            text = self._path.read_text(encoding="utf-8")
        except Exception as e:  # noqa
            self.browser.setPlainText(f"Could not read {self._path}:\n{e}")
            return
        self.browser.setMarkdown(text)
        self.browser.moveCursor(QTextCursor.Start)
