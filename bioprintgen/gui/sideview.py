"""Non-editable side elevation of the whole toolpath (X across, Z up).

Each layer is drawn as a band at its z height spanning that layer's X extent,
with a thickness equal to the layer height and coloured by its extruder.  This
makes variable layer heights, the overall silhouette, and tool changes visible
at a glance.  The layer currently shown in the top preview is highlighted.
"""
from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import Qt, QPointF, QRectF, QEvent
from PySide6.QtGui import QPen, QColor, QBrush, QPainter
from PySide6.QtWidgets import (
    QGraphicsView, QGraphicsScene, QGraphicsRectItem, QFrame, QWidget,
    QVBoxLayout, QLabel,
)

from ..model import LayerToolpath
from . import theme


def _layer_extruder(lt: LayerToolpath) -> int:
    """The most-used extruder among a layer's extrude moves (for the band colour)."""
    counts: dict = {}
    for m in lt.moves:
        if m.extrude:
            counts[getattr(m, "extruder", 1)] = counts.get(getattr(m, "extruder", 1), 0) + 1
    if not counts:
        return 1
    return max(counts, key=counts.get)


class SideScene(QGraphicsScene):
    def __init__(self):
        super().__init__()
        self.setBackgroundBrush(QBrush(QColor(theme.BG)))
        self._bands: List[QGraphicsRectItem] = []
        self._current: Optional[int] = None

    def set_toolpath(self, layers: List[LayerToolpath]):
        self.clear()
        self._bands = []
        self._current = None
        for lt in layers:
            xs = [p for m in lt.moves if m.extrude for p in (m.start[0], m.end[0])]
            if not xs:
                xs = [p for m in lt.moves for p in (m.start[0], m.end[0])]
            if not xs:
                self._bands.append(None)
                continue
            x0, x1 = min(xs), max(xs)
            h = lt.height if lt.height > 0 else 0.05
            rect = QGraphicsRectItem(QRectF(x0, lt.z - h, max(x1 - x0, 1e-3), h))
            col = QColor(theme.tool_extrude_color(_layer_extruder(lt)))
            fill = QColor(col)
            fill.setAlpha(120)
            rect.setBrush(QBrush(fill))
            pen = QPen(col, 0)
            pen.setCosmetic(True)
            rect.setPen(pen)
            self.addItem(rect)
            self._bands.append(rect)
        if self.items():
            self.setSceneRect(self.itemsBoundingRect().adjusted(-2, -2, 2, 2))

    def set_current(self, index: int):
        if self._current is not None and 0 <= self._current < len(self._bands):
            r = self._bands[self._current]
            if r is not None:
                pen = r.pen()
                pen.setWidthF(0.0)
                pen.setColor(pen.color())
                r.setPen(pen)
                r.setZValue(0)
        if 0 <= index < len(self._bands):
            r = self._bands[index]
            if r is not None:
                pen = QPen(QColor(theme.SELECT), 0)
                pen.setCosmetic(True)
                pen.setWidthF(2.5)
                r.setPen(pen)
                r.setZValue(10)
        self._current = index


class SideView(QGraphicsView):
    def __init__(self, scene: SideScene):
        super().__init__(scene)
        self._scene = scene
        self.setRenderHint(QPainter.Antialiasing, True)
        self.setDragMode(QGraphicsView.NoDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.scale(1, -1)          # Z up
        self._panning = False
        self._pan_start = QPointF()

    def wheelEvent(self, e):
        f = 1.2 if e.angleDelta().y() > 0 else 1 / 1.2
        self.scale(f, f)

    def fit(self):
        r = self._scene.itemsBoundingRect()
        if not r.isEmpty():
            self.fitInView(r.adjusted(-2, -2, 2, 2), Qt.KeepAspectRatio)

    def mousePressEvent(self, e):
        if e.button() in (Qt.MiddleButton, Qt.LeftButton):
            self._panning = True
            self._pan_start = e.position()
            self.setCursor(Qt.ClosedHandCursor)
            return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._panning:
            d = e.position() - self._pan_start
            self._pan_start = e.position()
            self.horizontalScrollBar().setValue(
                self.horizontalScrollBar().value() - int(d.x()))
            self.verticalScrollBar().setValue(
                self.verticalScrollBar().value() - int(d.y()))
            return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if self._panning:
            self._panning = False
            self.setCursor(Qt.ArrowCursor)
            return
        super().mouseReleaseEvent(e)


class _CornerGrip(QWidget):
    """Bottom-left drag handle that resizes the SideInset (top-right stays put)."""

    def __init__(self, target: "SideInset"):
        super().__init__(target)
        self._target = target
        self.setFixedSize(14, 14)
        self.setCursor(Qt.SizeBDiagCursor)
        self._press = None

    def mousePressEvent(self, e):
        self._press = (e.globalPosition().toPoint(),
                       self._target.width(), self._target.height())

    def mouseMoveEvent(self, e):
        if self._press is None:
            return
        gp0, w0, h0 = self._press
        d = e.globalPosition().toPoint() - gp0
        neww = max(140, w0 - d.x())      # drag left -> wider (grows toward the left)
        newh = max(140, h0 + d.y())      # drag down -> taller
        self._target.resize(neww, newh)

    def mouseReleaseEvent(self, e):
        self._press = None

    def paintEvent(self, e):
        p = QPainter(self)
        p.setPen(QPen(QColor(theme.TEXT_DIM), 1))
        for off in (3, 7, 11):
            p.drawLine(off, self.height() - 2, 2, self.height() - off)


class SideInset(QFrame):
    """A floating, resizable inset that hosts the SideView in the top-right
    corner of a host widget (the preview view)."""

    def __init__(self, host: QWidget, scene: SideScene):
        super().__init__(host)
        self._host = host
        self.setObjectName("inset")
        self.refresh_theme()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 2, 4, 4)
        lay.setSpacing(2)
        cap = QLabel("Side view (X–Z)  ·  drag corner to resize")
        cap.setObjectName("hint")
        lay.addWidget(cap)
        self.view = SideView(scene)
        self.view.setStyleSheet("border: none;")
        lay.addWidget(self.view, 1)
        self.grip = _CornerGrip(self)
        self.resize(210, 240)
        host.installEventFilter(self)
        self._reanchor()

    def refresh_theme(self):
        """Re-apply the inline stylesheet after a light/dark switch."""
        self.setStyleSheet(
            f"#inset {{ background: {theme.BG_ELEV}; border: 1px solid {theme.BORDER};"
            f" border-radius: 6px; }}")

    def eventFilter(self, obj, ev):
        if obj is self._host and ev.type() == QEvent.Resize:
            self._reanchor()
        return False

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self.grip.move(4, self.height() - self.grip.height() - 4)
        self._reanchor()

    def _reanchor(self):
        m = 10
        self.move(max(0, self._host.width() - self.width() - m), m)
        self.raise_()
