"""A profile's real outline, drawn as you pick it.

Insert Frame, the Profile Library and Place from Library all show the
section of the size chosen, built from its numbers the way the member will
be: a filled outline with its width and height beside it.  The library's
family icons are the same drawing of a size from the middle of the table,
so an I beam looks like an I beam and a tube like a tube before anything
is opened.
"""
from __future__ import annotations

from typing import Dict, Optional, Tuple

from PySide6 import QtCore, QtGui, QtWidgets

from .theme import C

FILL = "#3589e0"


def _outline(face) -> Tuple[QtGui.QPainterPath, Tuple[float, float, float,
                                                      float]]:
    """The face's wires as one path in its own millimetres, Y up, and its
    box (x0, y0, x1, y1)."""
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.BRepTools import BRepTools_WireExplorer
    from OCP.GeomAbs import GeomAbs_Line
    from OCP.TopAbs import TopAbs_REVERSED, TopAbs_WIRE
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS

    path = QtGui.QPainterPath()
    path.setFillRule(QtCore.Qt.OddEvenFill)
    xs, ys = [], []
    wires = TopExp_Explorer(face, TopAbs_WIRE)
    while wires.More():
        walk = BRepTools_WireExplorer(TopoDS.Wire_s(wires.Current()))
        first = True
        while walk.More():
            edge = walk.Current()
            curve = BRepAdaptor_Curve(edge)
            u0, u1 = curve.FirstParameter(), curve.LastParameter()
            steps = 1 if curve.GetType() == GeomAbs_Line else 24
            params = [u0 + (u1 - u0) * i / steps for i in range(steps + 1)]
            if edge.Orientation() == TopAbs_REVERSED:
                params.reverse()
            for i, u in enumerate(params):
                p = curve.Value(u)
                x, y = p.X(), -p.Y()
                xs.append(x)
                ys.append(-y)
                if first:
                    path.moveTo(x, y)
                    first = False
                else:
                    path.lineTo(x, y)
            walk.Next()
        path.closeSubpath()
        wires.Next()
    if not xs:
        return path, (0.0, 0.0, 0.0, 0.0)
    return path, (min(xs), min(ys), max(xs), max(ys))


_cache: Dict[Tuple, Tuple[QtGui.QPainterPath, Tuple]] = {}


def outline(kind: str, dims: Dict[str, float], source: str = ""):
    """The profile's outline and box, built once per size."""
    key = (kind, source, tuple(sorted(dims.items())))
    if key not in _cache:
        from ..core import frames
        try:
            face = frames.profile_face(kind, dims, source)
            _cache[key] = _outline(face)
        except Exception:
            _cache[key] = (QtGui.QPainterPath(), (0.0, 0.0, 0.0, 0.0))
    return _cache[key]


def _paint(painter: QtGui.QPainter, rect: QtCore.QRectF, path, box,
           line_width: float) -> Optional[QtCore.QRectF]:
    """The outline fitted into ``rect``, filled; where it landed."""
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    if w <= 0 or h <= 0:
        return None
    k = min(rect.width() / w, rect.height() / h)
    painter.save()
    painter.translate(rect.center().x() - (x0 + w / 2.0) * k,
                      rect.center().y() + (y0 + h / 2.0) * k)
    painter.scale(k, k)
    pen = QtGui.QPen(QtGui.QColor(C.text), line_width / k)
    pen.setJoinStyle(QtCore.Qt.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(QtGui.QColor(FILL))
    painter.drawPath(path)
    painter.restore()
    return QtCore.QRectF(rect.center().x() - w * k / 2.0,
                         rect.center().y() - h * k / 2.0, w * k, h * k)


def icon(kind: str, dims: Dict[str, float], size: int = 40,
         source: str = "") -> QtGui.QIcon:
    """A family's picture: one of its sizes, drawn."""
    path, box = outline(kind, dims, source)
    ratio = 2.0
    picture = QtGui.QPixmap(int(size * ratio), int(size * ratio))
    picture.setDevicePixelRatio(ratio)
    picture.fill(QtCore.Qt.transparent)
    painter = QtGui.QPainter(picture)
    painter.setRenderHint(QtGui.QPainter.Antialiasing)
    _paint(painter, QtCore.QRectF(2, 2, size - 4, size - 4), path, box, 0.8)
    painter.end()
    return QtGui.QIcon(picture)


def family_icon(fam, size: int = 40) -> Optional[QtGui.QIcon]:
    """A size from the middle of a family's table, drawn; None if it has
    no sizes or will not build."""
    if not fam.rows:
        return None
    row = fam.rows[len(fam.rows) // 2]
    dims = {c: float(v) for c, v in zip(fam.columns, row[1:])}
    path, box = outline(fam.kind, dims, getattr(fam, "source", ""))
    if path.isEmpty():
        return None
    return icon(fam.kind, dims, size, getattr(fam, "source", ""))


class ProfilePreview(QtWidgets.QWidget):
    """The section of the size picked, with its overall width and height."""

    def __init__(self, parent=None, height: int = 170) -> None:
        super().__init__(parent)
        self.setMinimumHeight(height)
        self.setMinimumWidth(160)
        self._path = QtGui.QPainterPath()
        self._box = (0.0, 0.0, 0.0, 0.0)
        self.setToolTip("The section of the size picked")

    def show_profile(self, kind: str, dims: Dict[str, float],
                     source: str = "") -> None:
        self._path, self._box = outline(kind, dims, source)
        self.update()

    def show_path(self, path: QtGui.QPainterPath, box) -> None:
        """Any outline already drawn, a fastener's say."""
        self._path, self._box = path, box
        self.update()

    def clear(self) -> None:
        self._path, self._box = QtGui.QPainterPath(), (0.0, 0.0, 0.0, 0.0)
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        r = QtCore.QRectF(self.rect()).adjusted(46, 10, -10, -30)
        if self._path.isEmpty() or r.width() <= 0 or r.height() <= 0:
            painter.setPen(QtGui.QColor(C.text_dim))
            painter.drawText(self.rect(), QtCore.Qt.AlignCenter,
                             "No preview")
            return
        drawn = _paint(painter, r, self._path, self._box, 1.2)
        if drawn is None:
            return
        x0, y0, x1, y1 = self._box
        dim = QtGui.QColor(C.text_dim)
        painter.setPen(QtGui.QPen(dim, 1))
        # the width under it and the height to its left, as a drawing has
        yb = drawn.bottom() + 12
        painter.drawLine(QtCore.QPointF(drawn.left(), yb),
                         QtCore.QPointF(drawn.right(), yb))
        for x in (drawn.left(), drawn.right()):
            painter.drawLine(QtCore.QPointF(x, yb - 4),
                             QtCore.QPointF(x, yb + 4))
        xl = drawn.left() - 12
        painter.drawLine(QtCore.QPointF(xl, drawn.top()),
                         QtCore.QPointF(xl, drawn.bottom()))
        for y in (drawn.top(), drawn.bottom()):
            painter.drawLine(QtCore.QPointF(xl - 4, y),
                             QtCore.QPointF(xl + 4, y))
        painter.setPen(QtGui.QColor(C.text))
        painter.drawText(QtCore.QRectF(drawn.left(), yb + 2,
                                       drawn.width(), 16),
                         QtCore.Qt.AlignHCenter | QtCore.Qt.AlignTop,
                         "%g" % round(x1 - x0, 2))
        painter.save()
        painter.translate(xl - 6, drawn.center().y())
        painter.rotate(-90)
        painter.drawText(QtCore.QRectF(-60, -16, 120, 16),
                         QtCore.Qt.AlignHCenter | QtCore.Qt.AlignBottom,
                         "%g" % round(y1 - y0, 2))
        painter.restore()
