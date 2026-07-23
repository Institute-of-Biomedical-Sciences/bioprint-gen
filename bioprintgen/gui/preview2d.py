"""Interactive per-layer toolpath preview with drag-and-drop line editing.

* extrude moves are drawn in the accent colour, travels dim/dashed
* every vertex is a draggable handle (constant screen size, zoom-independent);
  for very dense layers (e.g. gyroid) handles are spawned on demand when a
  segment is clicked, keeping interaction responsive
* dragging a vertex rewrites the underlying Move endpoints and emits `edited`,
  which the main window uses to regenerate the g-code for that layer
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import Qt, QPointF, QRectF, Signal, QObject
from PySide6.QtGui import QPen, QColor, QBrush, QPainter
from PySide6.QtWidgets import (
    QGraphicsView, QGraphicsScene, QGraphicsLineItem, QGraphicsEllipseItem,
    QGraphicsItem,
)

from ..model import LayerToolpath, Move, MoveKind
from . import theme

MAX_PERSISTENT_HANDLES = 700
HANDLE_R = 4.0


def _key(p: Tuple[float, float]) -> Tuple[float, float]:
    return (round(p[0], 4), round(p[1], 4))


class NodeHandle(QGraphicsEllipseItem):
    """A draggable toolpath vertex. Knows every (move_index, endpoint) it drives."""

    def __init__(self, scene_ref: "PreviewScene", pos: Tuple[float, float]):
        super().__init__(-HANDLE_R, -HANDLE_R, 2 * HANDLE_R, 2 * HANDLE_R)
        self._scene = scene_ref
        self.refs: List[Tuple[int, str]] = []       # (move_index, 'start'|'end')
        self.seg_ends: List[Tuple["SegmentItem", str]] = []
        self.setZValue(20)
        self.setBrush(QBrush(QColor(theme.SELECT)))
        self.setPen(QPen(QColor("white"), 0))
        self.setFlag(QGraphicsItem.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.ItemSendsScenePositionChanges, True)
        self.setFlag(QGraphicsItem.ItemIgnoresTransformations, True)
        self.setPos(pos[0], pos[1])
        self.setCursor(Qt.SizeAllCursor)

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemScenePositionHasChanged and self._scene.live:
            p = self.scenePos()
            self._scene.apply_node_move(self, (p.x(), p.y()))
        return super().itemChange(change, value)


class SegmentItem(QGraphicsLineItem):
    def __init__(self, move_index: int, extrude: bool, kind: MoveKind,
                 extruder: int = 1):
        super().__init__()
        self.move_index = move_index
        self.extrude = extrude
        self.kind = kind
        self.extruder = extruder
        self._base_pen()

    def _base_pen(self):
        if not self.extrude:
            pen = QPen(QColor(theme.TRAVEL), 0, Qt.DashLine)
        elif self.kind == MoveKind.PERIMETER:
            pen = QPen(QColor(theme.tool_perim_color(self.extruder)), 0)
        else:
            pen = QPen(QColor(theme.tool_extrude_color(self.extruder)), 0)
        pen.setCosmetic(True)
        pen.setWidthF(2.0 if self.extrude else 1.0)
        self.setPen(pen)
        self.setZValue(5 if self.extrude else 2)

    def highlight(self, on: bool):
        if on:
            pen = QPen(QColor(theme.SELECT), 0)
            pen.setCosmetic(True)
            pen.setWidthF(3.0)
            self.setPen(pen)
            self.setZValue(10)
        else:
            self._base_pen()


class PreviewScene(QGraphicsScene):
    edited = Signal(int)            # layer index whose geometry changed
    segment_selected = Signal(int)  # move index

    def __init__(self):
        super().__init__()
        self.setBackgroundBrush(QBrush(QColor(theme.BG)))
        self.lt: Optional[LayerToolpath] = None
        self.segments: List[SegmentItem] = []
        self.nodes: Dict[Tuple[float, float], NodeHandle] = {}
        self.live = True
        self.dense = False
        self._selected: Optional[SegmentItem] = None
        self._adhoc: List[NodeHandle] = []

    # ---------------------------------------------------------------- build
    def set_layer(self, lt: LayerToolpath):
        self.live = False
        self.clear()
        self.segments = []
        self.nodes = {}
        self._adhoc = []
        self._selected = None
        self.lt = lt
        if lt is None:
            self.live = True
            return

        node_keys = set()
        for m in lt.moves:
            node_keys.add(_key(m.start))
            node_keys.add(_key(m.end))
        self.dense = len(node_keys) > MAX_PERSISTENT_HANDLES

        for mi, m in enumerate(lt.moves):
            seg = SegmentItem(mi, m.extrude, m.kind, getattr(m, "extruder", 1))
            seg.setLine(m.start[0], m.start[1], m.end[0], m.end[1])
            self.addItem(seg)
            self.segments.append(seg)

        if not self.dense:
            for mi, m in enumerate(lt.moves):
                sn = self._ensure_node(m.start)
                en = self._ensure_node(m.end)
                sn.refs.append((mi, "start"))
                en.refs.append((mi, "end"))
                sn.seg_ends.append((self.segments[mi], "start"))
                en.seg_ends.append((self.segments[mi], "end"))

        self.setSceneRect(self.itemsBoundingRect().adjusted(-5, -5, 5, 5))
        self.live = True

    def _ensure_node(self, pos) -> NodeHandle:
        k = _key(pos)
        if k not in self.nodes:
            h = NodeHandle(self, pos)
            self.addItem(h)
            self.nodes[k] = h
        return self.nodes[k]

    # ---------------------------------------------------------------- edit
    def apply_node_move(self, node: NodeHandle, new_pos):
        if self.lt is None:
            return
        for (mi, which) in node.refs:
            m = self.lt.moves[mi]
            if which == "start":
                m.start = (new_pos[0], new_pos[1])
            else:
                m.end = (new_pos[0], new_pos[1])
        for seg, which in node.seg_ends:
            ln = seg.line()
            if which == "start":
                seg.setLine(new_pos[0], new_pos[1], ln.x2(), ln.y2())
            else:
                seg.setLine(ln.x1(), ln.y1(), new_pos[0], new_pos[1])
        self.edited.emit(self.lt.index)

    # ---------------------------------------------------------------- add/remove nodes
    def insert_node(self, mi: int, pos: Tuple[float, float]):
        """Split move `mi` at `pos`, creating a new vertex between its ends."""
        if self.lt is None or mi < 0 or mi >= len(self.lt.moves):
            return
        m = self.lt.moves[mi]
        p = (float(pos[0]), float(pos[1]))
        if p == tuple(m.start) or p == tuple(m.end):
            return
        # the split halves inherit the original move's tool assignment
        new = Move(start=p, end=m.end, kind=m.kind, extrude=m.extrude,
                   radius=None, ccw=m.ccw, extruder=getattr(m, "extruder", 1))
        m.end = p
        m.radius = None
        self.lt.moves.insert(mi + 1, new)
        self.set_layer(self.lt)          # rebuild handles/segments
        self.edited.emit(self.lt.index)

    def delete_node(self, node: "NodeHandle"):
        """Remove a vertex: merge the two segments meeting at it when possible,
        otherwise drop the segment(s) incident to it."""
        if self.lt is None:
            return
        moves = self.lt.moves
        ends = [mi for (mi, w) in node.refs if w == "end"]
        starts = [mi for (mi, w) in node.refs if w == "start"]
        merged = False
        for a in ends:
            for b in starts:
                if b == a + 1 and moves[a].extrude == moves[b].extrude:
                    moves[a] = Move(start=moves[a].start, end=moves[b].end,
                                    kind=moves[a].kind, extrude=moves[a].extrude,
                                    radius=None, ccw=moves[a].ccw,
                                    extruder=getattr(moves[a], "extruder", 1))
                    del moves[b]
                    merged = True
                    break
            if merged:
                break
        if not merged:
            incident = sorted(set(ends + starts))
            if len(incident) == 1:
                # a lone terminal vertex: drop its single segment
                del moves[incident[0]]
            else:
                # a junction of several segments: ambiguous, leave it alone
                return
        self.set_layer(self.lt)
        self.edited.emit(self.lt.index)

    def select_segment(self, mi: Optional[int]):
        if self._selected is not None:
            self._selected.highlight(False)
        for h in self._adhoc:
            self.removeItem(h)
        self._adhoc = []
        if mi is None or self.lt is None:
            self._selected = None
            return
        seg = self.segments[mi]
        seg.highlight(True)
        self._selected = seg
        self.segment_selected.emit(mi)
        if self.dense:
            m = self.lt.moves[mi]
            for which, pos in (("start", m.start), ("end", m.end)):
                h = NodeHandle(self, pos)
                h.refs.append((mi, which))
                h.seg_ends.append((seg, which))
                self.addItem(h)
                self._adhoc.append(h)


class PreviewView(QGraphicsView):
    def __init__(self, scene: PreviewScene):
        super().__init__(scene)
        self._scene = scene
        self.setRenderHint(QPainter.Antialiasing, True)
        self.setDragMode(QGraphicsView.NoDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.scale(1, -1)   # flip so model +Y is up
        self._panning = False
        self._pan_start = QPointF()

    # -- zoom --
    def wheelEvent(self, e):
        f = 1.2 if e.angleDelta().y() > 0 else 1 / 1.2
        self.scale(f, f)

    def fit(self):
        r = self._scene.itemsBoundingRect()
        if not r.isEmpty():
            self.fitInView(r.adjusted(-3, -3, 3, 3), Qt.KeepAspectRatio)

    # -- pan + select --
    def mousePressEvent(self, e):
        if e.button() == Qt.MiddleButton or (
                e.button() == Qt.LeftButton and e.modifiers() & Qt.ShiftModifier):
            self._panning = True
            self._pan_start = e.position()
            self.setCursor(Qt.ClosedHandCursor)
            return
        if e.button() == Qt.RightButton:
            # right-click a vertex to delete it
            item = self.itemAt(e.position().toPoint())
            if isinstance(item, NodeHandle):
                self._scene.delete_node(item)
                return
            super().mousePressEvent(e)
            return
        if e.button() == Qt.LeftButton:
            item = self.itemAt(e.position().toPoint())
            if isinstance(item, NodeHandle):
                return super().mousePressEvent(e)  # start drag
            mi = self._nearest_segment(e.position())
            self._scene.select_segment(mi)
            return
        super().mousePressEvent(e)

    def mouseDoubleClickEvent(self, e):
        # double-click on a line to insert a new vertex at that point
        if e.button() == Qt.LeftButton:
            mi = self._nearest_segment(e.position())
            if mi is not None:
                sp = self.mapToScene(e.position().toPoint())
                seg = self._scene.segments[mi]
                ln = seg.line()
                cx, cy = _project_point_on_seg(sp.x(), sp.y(),
                                               ln.x1(), ln.y1(), ln.x2(), ln.y2())
                self._scene.insert_node(mi, (cx, cy))
                return
        super().mouseDoubleClickEvent(e)

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

    def _nearest_segment(self, view_pos) -> Optional[int]:
        sp = self.mapToScene(view_pos.toPoint())
        px, py = sp.x(), sp.y()
        thresh = 8.0 / max(self.transform().m11(), 1e-6)  # 8px in scene units
        best, best_d = None, thresh
        for seg in self._scene.segments:
            ln = seg.line()
            d = _point_seg_dist(px, py, ln.x1(), ln.y1(), ln.x2(), ln.y2())
            if d < best_d:
                best_d, best = d, seg.move_index
        return best


def _project_point_on_seg(px, py, x1, y1, x2, y2) -> Tuple[float, float]:
    """Closest point on segment (x1,y1)-(x2,y2) to (px,py), clamped to the ends."""
    dx, dy = x2 - x1, y2 - y1
    if dx == 0 and dy == 0:
        return x1, y1
    t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)))
    return x1 + t * dx, y1 + t * dy


def _point_seg_dist(px, py, x1, y1, x2, y2) -> float:
    cx, cy = _project_point_on_seg(px, py, x1, y1, x2, y2)
    return ((px - cx) ** 2 + (py - cy) ** 2) ** 0.5
