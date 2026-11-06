"""Sketching on a drawing, as Inventor does, with the same sketch editor a
part's sketch uses and the whole Sketch tab.

Start Sketch, then click: on empty sheet the sketch is the sheet's, on a
view it is that view's and moves with it, and Project Geometry takes only
that view's lines. A title block is edited the same way, in place on the
sheet. These sketches live in the drawing alone; nothing goes to the part
or the assembly.

The editor draws through a handful of calls and is driven by a handful of
signals from the 3D view. The surface here answers the same calls and
sends the same signals from the sheet, so the editor runs on the drawing
unchanged.
"""
from __future__ import annotations

import math
from typing import List, Optional, Tuple

from PySide6 import QtCore, QtGui

from ..core import drawing as dwg
from ..core.sketch import Sketch, SketchPlane
from . import drawpick

Primitive = Tuple[str, tuple, str, float, bool]


class _Drawn:
    """What a draw call hands back: the editor sometimes asks it to sit on
    top, which the sheet does already."""

    def SetZLayer(self, *_a) -> None:
        pass


class SheetSketchSurface(QtCore.QObject):
    """The sheet, as the sketch editor sees a view to sketch in."""

    plane_point_clicked = QtCore.Signal(float, float, object)
    plane_point_moved = QtCore.Signal(float, float, object)
    plane_double_clicked = QtCore.Signal(float, float)
    plane_key_pressed = QtCore.Signal(int, str)
    plane_drag_started = QtCore.Signal(float, float)
    plane_drag_moved = QtCore.Signal(float, float)
    plane_drag_finished = QtCore.Signal()
    escape_pressed = QtCore.Signal()
    delete_pressed = QtCore.Signal()

    BOX_WINDOW = "#e05a5a"
    BOX_CROSSING = "#4ee08a"
    BOX_FILL = 0.85
    TOPMOST_LAYER = 0
    DRAG_PIXELS = 4

    def __init__(self, canvas, origin: Tuple[float, float]) -> None:
        super().__init__(canvas)
        self.canvas = canvas
        self.origin = origin
        self._overlay: List[Primitive] = []
        self._preview: List[Primitive] = []
        self.plane_drag_allowed = True
        self.grid_unit = "mm"
        self.fit_extra = None
        self._press = None
        self._dragging = False
        # a click on a view's line while Project Geometry is on
        self.project_hook = None
        self.plane_press_hits = None

    # -- where things are --------------------------------------------------

    def _sheet(self, p) -> Tuple[float, float]:
        return (self.origin[0] + p[0], self.origin[1] + p[1])

    def _uv(self, pos: QtCore.QPoint) -> Tuple[float, float]:
        x, y = self.canvas.layout().to_sheet(pos.x(), pos.y())
        return (x - self.origin[0], y - self.origin[1])

    def pixel_scale(self) -> float:
        return 1.0 / max(self.canvas.layout().scale, 1e-9)

    def project(self, p) -> Tuple[int, int]:
        x, y = self.canvas.layout().to_device(*self._sheet(p))
        return int(round(x)), int(round(y))

    # -- drawing, as the editor asks ---------------------------------------

    def _keep(self, item: Primitive, preview: bool) -> _Drawn:
        (self._preview if preview else self._overlay).append(item)
        return _Drawn()

    def draw_edge(self, p1, p2, colour, width=1.8, preview=False,
                  dashed=False):
        if math.dist(p1[:2], p2[:2]) < 1e-12:
            return None
        return self._keep(("line", (tuple(p1[:2]), tuple(p2[:2])), colour,
                           width, dashed), preview)

    def draw_shape(self, shape, colour, width=1.8, preview=False,
                   dashed=False, fittable=False):
        from OCP.BRepAdaptor import BRepAdaptor_Curve
        from OCP.GeomAbs import GeomAbs_Line
        from OCP.TopAbs import TopAbs_EDGE
        from OCP.TopExp import TopExp_Explorer
        from OCP.TopoDS import TopoDS
        explorer = TopExp_Explorer(shape, TopAbs_EDGE)
        while explorer.More():
            try:
                curve = BRepAdaptor_Curve(TopoDS.Edge_s(explorer.Current()))
                a, b = curve.FirstParameter(), curve.LastParameter()
                steps = 1 if curve.GetType() == GeomAbs_Line else 48
                pts = []
                for i in range(steps + 1):
                    q = curve.Value(a + (b - a) * i / steps)
                    pts.append((q.X(), q.Y()))
                self._keep(("poly", tuple(pts), colour, width, dashed),
                           preview)
            except Exception:
                pass
            explorer.Next()
        return _Drawn()

    def draw_point(self, p, colour, size=3.0, preview=False, marker=None):
        return self._keep(("point", (tuple(p[:2]),), colour, size, False),
                          preview)

    def draw_text(self, text, position, colour, height=14.0, preview=False):
        return self._keep(("text", (tuple(position[:2]), str(text)), colour,
                           height, False), preview)

    def draw_fill(self, corners, colour, transparency=0.85, preview=True,
                  layer=None):
        return self._keep(("fill", tuple(tuple(c[:2]) for c in corners),
                           colour, transparency, False), preview)

    def clear_overlay(self) -> None:
        self._overlay = []

    def clear_preview(self) -> None:
        self._preview = []

    def redraw(self) -> None:
        self.canvas.update()

    # -- what the 3D view does and the sheet need not ------------------------

    def refresh_grid(self, *_a) -> None:
        pass

    def set_grid(self, *_a, **_k) -> None:
        pass

    def set_edge_picking(self, *_a, **_k) -> None:
        pass

    def enter_plane_mode(self, *_a, **_k) -> None:
        pass

    def leave_plane_mode(self, *_a, **_k) -> None:
        pass

    def fit_all(self, *_a, **_k) -> None:
        pass

    def setFocus(self) -> None:
        self.canvas.setFocus()

    def window(self):
        return self.canvas.window()

    # -- painting -----------------------------------------------------------

    def paint(self, painter: QtGui.QPainter, layout) -> None:
        painter.save()
        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)

        def at(p):
            return QtCore.QPointF(*layout.to_device(*self._sheet(p)))
        for kind, data, colour, size, dashed in self._overlay + self._preview:
            if kind == "fill":
                fill = QtGui.QColor(colour)
                fill.setAlphaF(max(0.0, 1.0 - size))
                painter.setPen(QtCore.Qt.NoPen)
                painter.setBrush(fill)
                painter.drawPolygon(QtGui.QPolygonF([at(c) for c in data]))
                continue
            pen = QtGui.QPen(QtGui.QColor(colour), max(1.0, size * 0.8))
            if dashed:
                pen.setStyle(QtCore.Qt.DashLine)
            painter.setPen(pen)
            painter.setBrush(QtCore.Qt.NoBrush)
            if kind == "line":
                painter.drawLine(at(data[0]), at(data[1]))
            elif kind == "poly":
                painter.drawPolyline(QtGui.QPolygonF([at(p) for p in data]))
            elif kind == "point":
                painter.setBrush(QtGui.QColor(colour))
                painter.drawEllipse(at(data[0]), size * 0.35, size * 0.35)
            elif kind == "text":
                font = painter.font()
                font.setPixelSize(max(8, int(size * 0.8)))
                painter.setFont(font)
                painter.drawText(at(data[0]), data[1])
        painter.restore()

    # -- the mouse and keys, sent on as the 3D view sends them ---------------

    def press(self, event) -> None:
        self._press = event.position().toPoint()
        self._dragging = False

    def move(self, event) -> None:
        pos = event.position().toPoint()
        uv = self._uv(pos)
        held = bool(event.buttons() & QtCore.Qt.LeftButton)
        if held and self._press is not None and not self._dragging \
                and self.plane_drag_allowed \
                and (pos - self._press).manhattanLength() > self.DRAG_PIXELS:
            self._dragging = True
            self.plane_drag_started.emit(*self._uv(self._press))
        if self._dragging:
            self.plane_drag_moved.emit(*uv)
        else:
            self.plane_point_moved.emit(uv[0], uv[1], event.modifiers())

    def release(self, event) -> None:
        if self._press is None:
            return
        pos = event.position().toPoint()
        if self._dragging:
            self.plane_drag_finished.emit()
        else:
            uv = self._uv(pos)
            if self.project_hook is not None and self.project_hook(uv):
                pass
            else:
                self.plane_point_clicked.emit(uv[0], uv[1],
                                              event.modifiers())
        self._press = None
        self._dragging = False

    def double_click(self, event) -> None:
        self.plane_double_clicked.emit(*self._uv(event.position().toPoint()))

    def key(self, event) -> bool:
        key = event.key()
        if key == QtCore.Qt.Key_Escape:
            self.escape_pressed.emit()
        elif key in (QtCore.Qt.Key_Delete,):
            self.delete_pressed.emit()
        else:
            self.plane_key_pressed.emit(key, event.text())
        return True


# --------------------------------------------------------------- sessions


class SketchPicker:
    """Start Sketch's one question, asked by a click: on a view, or on the
    sheet."""

    def __init__(self, controller, sheet) -> None:
        self.controller = controller
        self.sheet = sheet
        controller.host.status_message.setStyleSheet("")
        controller.host.status_message.setText(
            "Start Sketch: click a view to sketch on it, or the sheet. Esc "
            "to cancel.")

    def press(self, point, device) -> None:
        view = None
        for candidate in reversed(self.sheet.views):
            box = candidate.projection.box if candidate.projection else None
            if box and box[0] <= point[0] - candidate.x <= box[2] \
                    and box[1] <= point[1] - candidate.y <= box[3]:
                view = candidate
                break
        self.controller.end_placement()
        self.controller.begin_drawing_sketch(self.sheet, view)

    def move(self, point, device, held) -> None:
        pass

    def release(self, point, device) -> None:
        pass

    def right_click(self, point, device) -> bool:
        return False

    def escape(self) -> bool:
        return False

    def cursor_shape(self, point, device):
        return QtCore.Qt.CrossCursor

    def paint(self, painter, layout) -> None:
        pass

    def close(self) -> None:
        pass


def project_from_view(sheet, view, sketch: Sketch, uv,
                      tolerance: float) -> bool:
    """Project Geometry in a view's sketch: the view's line, circle or arc
    under the click, into the sketch as reference geometry held where the
    view has it. Only that view's lines can be taken."""
    item = drawpick.nearest(sheet, (view.x + uv[0], view.y + uv[1]),
                            tolerance, only_view=view.id,
                            kinds=(drawpick.LINE, drawpick.CIRCLE))
    if item is None:
        return False
    if item.kind == drawpick.LINE:
        eid = sketch.add_line(item.a, item.b, construction=True)
    else:
        eid = sketch.add_circle(item.a, item.radius, construction=True)
    for pid in sketch.entities[eid].points:
        sketch.points[pid].fixed = True
    return True


def signal_pairs(surface, editor):
    """The surface's signals and the editor's slots they drive, the same
    pairs the 3D view drives."""
    return ((surface.plane_point_clicked, editor._on_click),
            (surface.plane_point_moved, editor._on_move),
            (surface.plane_drag_started, editor._on_drag_start),
            (surface.plane_drag_moved, editor._on_drag_move),
            (surface.plane_drag_finished, editor._on_drag_end),
            (surface.escape_pressed, editor.escape),
            (surface.delete_pressed, editor.delete_selected),
            (surface.plane_double_clicked, editor._on_double_click),
            (surface.plane_key_pressed, editor._on_key))


def new_sketch() -> Sketch:
    return Sketch(SketchPlane(), "Sketch")
