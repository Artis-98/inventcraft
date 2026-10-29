"""Vector icons drawn at runtime.

Everything is painted with QPainter on a 24x24 grid, so the application ships
with no image assets and the icons stay crisp at any device pixel ratio.
"""

from __future__ import annotations

import math
import os
from typing import Callable, Dict, Optional, Tuple

from PySide6 import QtCore, QtGui

from .theme import C

GRID = 24.0

# Three tones of the mark's silver rather than two and a blue.  They have
# to stay a clear step apart or a 16 pixel icon turns into one grey smudge,
# so the middle one is well below the outline and the solid one below that.
# The light scheme's tones; ``use_theme`` swaps them for the dark one.
_LINE = "#2b3540"
_ACCENT = "#b9820f"
_SOLID = "#7a8693"
# Amber and green stay: they are the two places an icon says something
# rather than draws something, and a silver warning is no warning at all.
_WARM = "#e0a355"
_GREEN = "#69c26b"

_cache: Dict[Tuple[str, int, str], QtGui.QIcon] = {}


# --------------------------------------------------------------------------
# drawing helpers
# --------------------------------------------------------------------------


def _pen(p: QtGui.QPainter, colour: str, width: float = 1.6,
         dashed: bool = False) -> None:
    pen = QtGui.QPen(QtGui.QColor(colour))
    pen.setWidthF(width)
    pen.setCapStyle(QtCore.Qt.RoundCap)
    pen.setJoinStyle(QtCore.Qt.RoundJoin)
    if dashed:
        pen.setStyle(QtCore.Qt.DashLine)
        pen.setDashPattern([2.4, 2.0])
    p.setPen(pen)
    p.setBrush(QtCore.Qt.NoBrush)


def _fill(p: QtGui.QPainter, colour: str, alpha: int = 255) -> None:
    col = QtGui.QColor(colour)
    col.setAlpha(alpha)
    p.setBrush(QtGui.QBrush(col))
    p.setPen(QtCore.Qt.NoPen)


def _poly(*pts) -> QtGui.QPolygonF:
    return QtGui.QPolygonF([QtCore.QPointF(x, y) for x, y in pts])


def _face(p: QtGui.QPainter, pts, colour: Optional[str] = None,
          alpha: int = 90, outline: Optional[str] = "line") -> None:
    # resolved here, not in the signature, so a change of scheme reaches it
    colour = _SOLID if colour is None else colour
    outline = _LINE if outline == "line" else outline
    col = QtGui.QColor(colour)
    col.setAlpha(alpha)
    p.setBrush(QtGui.QBrush(col))
    if outline:
        pen = QtGui.QPen(QtGui.QColor(outline))
        pen.setWidthF(1.5)
        pen.setJoinStyle(QtCore.Qt.RoundJoin)
        p.setPen(pen)
    else:
        p.setPen(QtCore.Qt.NoPen)
    p.drawPolygon(_poly(*pts))


def _arrow(p: QtGui.QPainter, x1, y1, x2, y2,
           colour: Optional[str] = None,
           head: float = 3.2, width: float = 1.7) -> None:
    colour = _ACCENT if colour is None else colour
    _pen(p, colour, width)
    p.drawLine(QtCore.QPointF(x1, y1), QtCore.QPointF(x2, y2))
    ang = math.atan2(y2 - y1, x2 - x1)
    _fill(p, colour)
    p.drawPolygon(_poly(
        (x2, y2),
        (x2 - head * math.cos(ang - 0.45), y2 - head * math.sin(ang - 0.45)),
        (x2 - head * math.cos(ang + 0.45), y2 - head * math.sin(ang + 0.45)),
    ))


def _box_iso(p: QtGui.QPainter, cx=12.0, cy=12.0, edge=8.0,
             colour=None) -> None:
    """A cube in true isometric, every edge the same length.

    It used to be a block squashed to two thirds of its width, which read
    as a slab rather than as a part.
    """
    colour = _SOLID if colour is None else colour
    half = edge * 0.866                 # half the width, at 30 degrees
    y0 = cy - edge                      # the top corner
    top = [(cx, y0), (cx + half, y0 + edge * 0.5), (cx, y0 + edge),
           (cx - half, y0 + edge * 0.5)]
    left = [(cx - half, y0 + edge * 0.5), (cx, y0 + edge),
            (cx, y0 + edge * 2.0), (cx - half, y0 + edge * 1.5)]
    right = [(cx + half, y0 + edge * 0.5), (cx, y0 + edge),
             (cx, y0 + edge * 2.0), (cx + half, y0 + edge * 1.5)]
    _face(p, left, colour, 70)
    _face(p, right, colour, 110)
    _face(p, top, colour, 150)


# --------------------------------------------------------------------------
# icon painters
# --------------------------------------------------------------------------


def _i_new(p):
    _face(p, [(6, 3), (14, 3), (18, 7), (18, 21), (6, 21)], _SOLID, 60)
    _pen(p, _LINE, 1.5)
    p.drawPolyline(_poly((14, 3), (14, 7), (18, 7)))


def _i_open(p):
    _face(p, [(3, 6), (10, 6), (12, 8.5), (21, 8.5), (21, 19), (3, 19)],
          _WARM, 70)


def _i_save(p):
    _face(p, [(4, 4), (17, 4), (20, 7), (20, 20), (4, 20)], _ACCENT, 60)
    _fill(p, _LINE, 210)
    p.drawRect(QtCore.QRectF(8, 4, 8, 5.5))
    p.drawRect(QtCore.QRectF(7, 13, 10, 7))


def _i_undo(p):
    _pen(p, _LINE, 1.9)
    path = QtGui.QPainterPath(QtCore.QPointF(5, 12))
    path.arcTo(QtCore.QRectF(5, 6, 14, 12), 180, -230)
    p.drawPath(path)
    _fill(p, _LINE)
    p.drawPolygon(_poly((5, 12), (9, 9.5), (9, 14.5)))


def _i_redo(p):
    p.save()
    p.translate(24, 0)
    p.scale(-1, 1)
    _i_undo(p)
    p.restore()


def _i_sketch(p):
    _pen(p, _ACCENT, 1.5, dashed=True)
    p.drawRect(QtCore.QRectF(3.5, 6.5, 17, 13))
    _pen(p, _LINE, 1.9)
    p.drawPolyline(_poly((6, 16), (10, 10), (14, 14), (18, 8)))
    _fill(p, _WARM)
    for x, y in ((6, 16), (10, 10), (14, 14), (18, 8)):
        p.drawEllipse(QtCore.QPointF(x, y), 1.5, 1.5)


def _i_sketch_shared(p):
    _pen(p, _ACCENT, 1.4, dashed=True)
    p.drawRect(QtCore.QRectF(3.0, 6.0, 14.0, 12.0))
    _pen(p, _LINE, 1.8)
    p.drawPolyline(_poly((5.5, 15), (9, 10), (12.5, 13.5)))
    # the share badge: two nodes joined by a link
    _fill(p, _GREEN)
    p.drawEllipse(QtCore.QPointF(19.5, 8.5), 2.6, 2.6)
    p.drawEllipse(QtCore.QPointF(15.0, 19.0), 2.4, 2.4)
    _pen(p, _GREEN, 1.7)
    p.drawLine(QtCore.QPointF(18.4, 10.9), QtCore.QPointF(16.1, 16.7))


def _i_spacemouse(p):
    _fill(p, _SOLID, 130)
    p.drawEllipse(QtCore.QPointF(12, 16), 8.5, 4.2)
    _pen(p, _LINE, 1.5)
    p.drawEllipse(QtCore.QPointF(12, 16), 8.5, 4.2)
    _fill(p, _ACCENT, 190)
    p.drawEllipse(QtCore.QPointF(12, 10.5), 6.0, 3.2)
    _pen(p, _LINE, 1.4)
    p.drawEllipse(QtCore.QPointF(12, 10.5), 6.0, 3.2)
    p.drawLine(QtCore.QPointF(6, 10.5), QtCore.QPointF(6, 16))
    p.drawLine(QtCore.QPointF(18, 10.5), QtCore.QPointF(18, 16))
    _arrow(p, 12, 8.5, 12, 3.5, _WARM, 2.6, 1.4)


def _i_line(p):
    _pen(p, _LINE, 1.9)
    p.drawLine(QtCore.QPointF(5, 18), QtCore.QPointF(19, 6))
    _fill(p, _ACCENT)
    p.drawEllipse(QtCore.QPointF(5, 18), 2.1, 2.1)
    p.drawEllipse(QtCore.QPointF(19, 6), 2.1, 2.1)


def _i_rect(p):
    _pen(p, _LINE, 1.9)
    p.drawRect(QtCore.QRectF(4.5, 7, 15, 11))
    _fill(p, _ACCENT)
    p.drawEllipse(QtCore.QPointF(4.5, 7), 2.0, 2.0)
    p.drawEllipse(QtCore.QPointF(19.5, 18), 2.0, 2.0)


def _i_circle(p):
    _pen(p, _LINE, 1.9)
    p.drawEllipse(QtCore.QPointF(12, 12), 7.5, 7.5)
    _fill(p, _ACCENT)
    p.drawEllipse(QtCore.QPointF(12, 12), 1.7, 1.7)


def _i_arc(p):
    _pen(p, _LINE, 1.9)
    path = QtGui.QPainterPath(QtCore.QPointF(4, 18))
    path.arcTo(QtCore.QRectF(4, 4, 16, 16), 180, -180)
    p.drawPath(path)
    _fill(p, _ACCENT)
    p.drawEllipse(QtCore.QPointF(4, 18), 2.0, 2.0)
    p.drawEllipse(QtCore.QPointF(20, 18), 2.0, 2.0)


def _i_text(p):
    _pen(p, _LINE, 1.9)
    p.drawLine(QtCore.QPointF(5, 5.5), QtCore.QPointF(19, 5.5))
    p.drawLine(QtCore.QPointF(12, 5.5), QtCore.QPointF(12, 19.5))
    _pen(p, _ACCENT, 1.9)
    p.drawLine(QtCore.QPointF(8.5, 19.5), QtCore.QPointF(15.5, 19.5))


def _i_polygon(p):
    _pen(p, _LINE, 1.9)
    pts = [(12 + 8 * math.cos(a), 12 + 8 * math.sin(a))
           for a in [math.radians(-90 + 60 * i) for i in range(6)]]
    p.drawPolygon(_poly(*pts))


def _i_slot(p):
    _pen(p, _LINE, 1.9)
    path = QtGui.QPainterPath()
    path.addRoundedRect(QtCore.QRectF(3.5, 8, 17, 8), 4, 4)
    p.drawPath(path)
    _fill(p, _ACCENT)
    p.drawEllipse(QtCore.QPointF(7.5, 12), 1.4, 1.4)
    p.drawEllipse(QtCore.QPointF(16.5, 12), 1.4, 1.4)


def _i_spline(p):
    _pen(p, _LINE, 1.9)
    path = QtGui.QPainterPath(QtCore.QPointF(4, 17))
    path.cubicTo(9, 3, 15, 21, 20, 7)
    p.drawPath(path)
    _fill(p, _ACCENT)
    for x, y in ((4, 17), (20, 7)):
        p.drawEllipse(QtCore.QPointF(x, y), 1.8, 1.8)


def _i_point(p):
    _pen(p, _LINE, 1.5)
    p.drawLine(QtCore.QPointF(12, 4), QtCore.QPointF(12, 20))
    p.drawLine(QtCore.QPointF(4, 12), QtCore.QPointF(20, 12))
    _fill(p, _ACCENT)
    p.drawEllipse(QtCore.QPointF(12, 12), 2.8, 2.8)


def _i_fillet2d(p):
    _pen(p, _LINE, 1.5, dashed=True)
    p.drawPolyline(_poly((5, 5), (19, 5), (19, 19)))
    _pen(p, _ACCENT, 2.2)
    path = QtGui.QPainterPath(QtCore.QPointF(5, 5))
    path.lineTo(11, 5)
    path.arcTo(QtCore.QRectF(11, 5, 16, 16), 90, -90)
    path.lineTo(19, 19)
    p.drawPath(path)


def _i_trim(p):
    _pen(p, _LINE, 1.5, dashed=True)
    p.drawLine(QtCore.QPointF(13, 4), QtCore.QPointF(20, 20))
    _pen(p, _ACCENT, 2.0)
    p.drawLine(QtCore.QPointF(4, 17), QtCore.QPointF(13, 17))
    _pen(p, C.error, 1.8)
    p.drawLine(QtCore.QPointF(14.5, 14), QtCore.QPointF(19.5, 19))
    p.drawLine(QtCore.QPointF(19.5, 14), QtCore.QPointF(14.5, 19))


def _i_offset(p):
    _pen(p, _LINE, 1.8)
    p.drawRect(QtCore.QRectF(7, 8, 10, 8))
    _pen(p, _ACCENT, 1.5, dashed=True)
    p.drawRect(QtCore.QRectF(3.5, 5, 17, 14))


def _i_dimension(p):
    _pen(p, _LINE, 1.3)
    p.drawLine(QtCore.QPointF(5, 6), QtCore.QPointF(5, 18))
    p.drawLine(QtCore.QPointF(19, 6), QtCore.QPointF(19, 18))
    _arrow(p, 11, 15, 5, 15, _WARM, 3.0, 1.4)
    _arrow(p, 13, 15, 19, 15, _WARM, 3.0, 1.4)
    _fill(p, _WARM)
    p.drawRect(QtCore.QRectF(9.5, 6.5, 5, 5))


def _i_measure(p):
    p.save()
    p.translate(12, 12)
    p.rotate(-35)
    _face(p, [(-9, -3.5), (9, -3.5), (9, 3.5), (-9, 3.5)], _WARM, 80)
    _pen(p, _LINE, 1.2)
    for i in range(-6, 9, 3):
        p.drawLine(QtCore.QPointF(i, -3.5), QtCore.QPointF(i, -0.5))
    p.restore()


def _i_params(p):
    _pen(p, _LINE, 1.6)
    p.drawRect(QtCore.QRectF(3.5, 5.5, 17, 13))
    p.drawLine(QtCore.QPointF(3.5, 9.5), QtCore.QPointF(20.5, 9.5))
    p.drawLine(QtCore.QPointF(11, 9.5), QtCore.QPointF(11, 18.5))
    _fill(p, _ACCENT, 150)
    p.drawRect(QtCore.QRectF(3.5, 5.5, 17, 4))


def _i_extrude(p):
    _pen(p, _ACCENT, 1.5, dashed=True)
    p.drawPolygon(_poly((5, 17), (12, 20), (19, 17), (12, 14)))
    _face(p, [(5, 9), (12, 12), (12, 20), (5, 17)], _SOLID, 80)
    _face(p, [(19, 9), (12, 12), (12, 20), (19, 17)], _SOLID, 120)
    _face(p, [(5, 9), (12, 12), (19, 9), (12, 6)], _SOLID, 165)
    _arrow(p, 12, 12, 12, 3.5, _ACCENT, 3.0, 1.6)


def _i_emboss(p):
    """A block with a letter standing up out of its top."""
    _face(p, [(3, 13), (12, 17), (21, 13), (12, 9)], _SOLID, 150)
    _face(p, [(3, 13), (12, 17), (12, 21), (3, 17)], _SOLID, 80)
    _face(p, [(21, 13), (12, 17), (12, 21), (21, 17)], _SOLID, 120)
    _pen(p, _ACCENT, 2.2)
    p.drawLine(QtCore.QPointF(8.5, 4.5), QtCore.QPointF(15.5, 4.5))
    p.drawLine(QtCore.QPointF(12, 4.5), QtCore.QPointF(12, 13))


def _i_engrave(p):
    """A block with a letter cut into its top."""
    _face(p, [(3, 13), (12, 17), (21, 13), (12, 9)], _SOLID, 150)
    _face(p, [(3, 13), (12, 17), (12, 21), (3, 17)], _SOLID, 80)
    _face(p, [(21, 13), (12, 17), (12, 21), (21, 17)], _SOLID, 120)
    _pen(p, _ACCENT, 1.8)
    p.drawLine(QtCore.QPointF(9, 11.6), QtCore.QPointF(15, 14.4))
    p.drawLine(QtCore.QPointF(12, 13), QtCore.QPointF(9.8, 14.6))


def _i_dof(p):
    """Degrees of freedom: a point and the ways it can go."""
    _pen(p, _ACCENT, 1.6)
    for ax, ay, bx, by in ((12, 4, 12, 20), (4, 12, 20, 12)):
        p.drawLine(QtCore.QPointF(ax, ay), QtCore.QPointF(bx, by))
    for tip, a, b in (((12, 3.5), (9.5, 6.5), (14.5, 6.5)),
                      ((12, 20.5), (9.5, 17.5), (14.5, 17.5)),
                      ((3.5, 12), (6.5, 9.5), (6.5, 14.5)),
                      ((20.5, 12), (17.5, 9.5), (17.5, 14.5))):
        p.drawPolygon(_poly(tip, a, b))
    _fill(p, _LINE)
    p.drawEllipse(QtCore.QPointF(12, 12), 2.2, 2.2)


def _sheet(p, pts, shade):
    _face(p, pts, _SOLID, shade)


def _i_sm_face(p):
    """A thin plate."""
    _sheet(p, [(3, 12), (12, 16), (21, 12), (12, 8)], 160)
    _sheet(p, [(3, 12), (12, 16), (12, 18), (3, 14)], 90)
    _sheet(p, [(21, 12), (12, 16), (12, 18), (21, 14)], 125)


def _i_sm_flange(p):
    """A plate with a wall bent up from its back edge."""
    _sheet(p, [(3, 14), (12, 18), (21, 14), (12, 10)], 160)
    _sheet(p, [(3, 14), (12, 18), (12, 20), (3, 16)], 90)
    _sheet(p, [(12, 10), (21, 14), (21, 4), (12, 0.5)], 120)
    _pen(p, _ACCENT, 1.8)
    p.drawLine(QtCore.QPointF(16.5, 6), QtCore.QPointF(16.5, 1.5))


def _i_sm_flat(p):
    """The sheet laid flat, its bend line dashed."""
    _pen(p, _LINE, 1.6)
    p.drawRect(QtCore.QRectF(3.5, 5.5, 17, 13))
    _pen(p, _ACCENT, 1.4, dashed=True)
    p.drawLine(QtCore.QPointF(3.5, 11), QtCore.QPointF(20.5, 11))


def _i_sm_defaults(p):
    """A plate and its thickness."""
    _sheet(p, [(3, 13), (12, 17), (21, 13), (12, 9)], 160)
    _sheet(p, [(3, 13), (12, 17), (12, 20), (3, 16)], 90)
    _pen(p, _ACCENT, 1.6)
    p.drawLine(QtCore.QPointF(22, 13), QtCore.QPointF(22, 16))
    p.drawLine(QtCore.QPointF(20.5, 13), QtCore.QPointF(23.5, 13))
    p.drawLine(QtCore.QPointF(20.5, 16), QtCore.QPointF(23.5, 16))


def _i_sm_convert(p):
    """A block becoming a bent sheet."""
    _sheet(p, [(2, 10), (8, 13), (8, 20), (2, 17)], 110)
    _sheet(p, [(13, 14), (22, 18), (22, 20), (13, 16)], 150)
    _sheet(p, [(13, 14), (13, 4), (15, 4), (15, 14.8)], 100)
    _pen(p, _ACCENT, 1.6)
    p.drawLine(QtCore.QPointF(9, 8), QtCore.QPointF(12, 8))


def _i_sm_hem(p):
    """Single hem: the sheet folded back flat over itself."""
    _pen(p, _LINE, 2.0)
    path = QtGui.QPainterPath(QtCore.QPointF(21, 15))
    path.lineTo(7, 15)
    path.arcTo(QtCore.QRectF(3, 9, 8, 6), 270, -180)
    path.lineTo(17, 9)
    p.drawPath(path)


def _i_sm_hem_teardrop(p):
    _pen(p, _LINE, 2.0)
    path = QtGui.QPainterPath(QtCore.QPointF(21, 16))
    path.lineTo(10, 16)
    path.arcTo(QtCore.QRectF(3, 6, 10, 10), 270, -250)
    p.drawPath(path)


def _i_sm_hem_rolled(p):
    _pen(p, _LINE, 2.0)
    path = QtGui.QPainterPath(QtCore.QPointF(21, 16))
    path.lineTo(10, 16)
    path.arcTo(QtCore.QRectF(4, 6, 10, 10), 270, -180)
    p.drawPath(path)


def _i_sm_hem_double(p):
    _pen(p, _LINE, 1.8)
    path = QtGui.QPainterPath(QtCore.QPointF(21, 18))
    path.lineTo(6, 18)
    path.lineTo(6, 8)
    path.lineTo(18, 8)
    path.lineTo(18, 13)
    path.lineTo(9, 13)
    p.drawPath(path)


def _i_sm_fold(p):
    """A sheet folded up along a dashed line."""
    _sheet(p, [(3, 15), (11, 19), (15, 17), (7, 13)], 160)
    _sheet(p, [(7, 13), (15, 17), (21, 7), (13, 3)], 120)
    _pen(p, _ACCENT, 1.4, dashed=True)
    p.drawLine(QtCore.QPointF(6.5, 13), QtCore.QPointF(15.5, 17))


def _i_sm_contour(p):
    """A U channel drawn from an open path."""
    _pen(p, _LINE, 2.2)
    path = QtGui.QPainterPath(QtCore.QPointF(5, 5))
    path.lineTo(5, 17)
    path.quadTo(5, 19, 7, 19)
    path.lineTo(17, 19)
    path.quadTo(19, 19, 19, 17)
    path.lineTo(19, 5)
    p.drawPath(path)
    _pen(p, _ACCENT, 1.2, dashed=True)
    p.drawLine(QtCore.QPointF(8, 5), QtCore.QPointF(8, 16))


def _i_sm_corner(p):
    """Two walls meeting at a closed corner."""
    _sheet(p, [(4, 8), (12, 12), (12, 21), (4, 17)], 100)
    _sheet(p, [(13, 12), (21, 8), (21, 17), (13, 21)], 140)
    _pen(p, _ACCENT, 1.6)
    p.drawLine(QtCore.QPointF(12.5, 11), QtCore.QPointF(12.5, 22))


def _i_sm_perforation(p):
    """A bend line cut through by V slots with bridges between."""
    _pen(p, _LINE, 1.4)
    p.drawRect(QtCore.QRectF(3, 4, 18, 16))
    _pen(p, _ACCENT, 1.8)
    for y in (6, 12.5):
        p.drawPolyline(_poly((10, y), (13, y + 2.5), (10, y + 5)))


def _i_sm_perforation_trapezoid(p):
    """Open trapezoids along a bend line, every other one turned over."""
    _pen(p, _LINE, 1.4)
    p.drawRect(QtCore.QRectF(3, 4, 18, 16))
    _pen(p, _ACCENT, 1.8)
    p.drawPolyline(_poly((9.5, 4.5), (12, 7), (12, 11), (9.5, 13.5)))
    p.drawPolyline(_poly((14.5, 11.5), (12, 14), (12, 17.5), (14.5, 20)))


def _i_sm_perforation_straight(p):
    _pen(p, _LINE, 1.4)
    p.drawRect(QtCore.QRectF(3, 4, 18, 16))
    _pen(p, _ACCENT, 2.0)
    for y0, y1 in ((6, 10.5), (13.5, 18)):
        p.drawLine(QtCore.QPointF(12, y0), QtCore.QPointF(12, y1))


def _i_frame_insert(p):
    """A frame: a rectangle of members on legs."""
    _pen(p, _LINE, 2.2)
    p.drawPolyline(_poly((4, 20), (4, 7), (20, 7), (20, 20)))
    p.drawLine(QtCore.QPointF(4, 12), QtCore.QPointF(20, 12))
    _pen(p, _ACCENT, 1.4, dashed=True)
    p.drawLine(QtCore.QPointF(2, 4), QtCore.QPointF(22, 4))


def _i_frame_library(p):
    """A square tube's end and an angle's."""
    _pen(p, _LINE, 1.8)
    p.drawRoundedRect(QtCore.QRectF(3, 5, 9, 9), 2, 2)
    p.drawRoundedRect(QtCore.QRectF(5, 7, 5, 5), 1, 1)
    _pen(p, _ACCENT, 1.8)
    p.drawPolygon(_poly((13, 20), (13, 9), (15.5, 9), (15.5, 17.5),
                        (22, 17.5), (22, 20)))


def _i_frame_assembly(p):
    """A welded frame: a top of tubes on two legs, in the solid colour."""
    _sheet(p, [(2, 9), (14, 4), (22, 7), (10, 12)], 165)
    _sheet(p, [(5, 9), (14, 5.5), (19, 7), (10, 10.5)], 40)
    _sheet(p, [(2, 9), (4, 9.8), (4, 21), (2, 20)], 110)
    _sheet(p, [(20, 7.8), (22, 7), (22, 18), (20, 19)], 110)
    _sheet(p, [(9, 11.6), (11, 12), (11, 22), (9, 21.5)], 130)


def _i_frame_change(p):
    """A member and the arrows of a swap: a different size."""
    _sheet(p, [(3, 15), (13, 9), (17, 11), (7, 17)], 150)
    _sheet(p, [(3, 15), (7, 17), (7, 20), (3, 18)], 90)
    _pen(p, _ACCENT, 1.8)
    p.drawLine(QtCore.QPointF(15, 4), QtCore.QPointF(21, 4))
    p.drawLine(QtCore.QPointF(21, 4), QtCore.QPointF(18.5, 2))
    p.drawLine(QtCore.QPointF(21, 7), QtCore.QPointF(15, 7))
    p.drawLine(QtCore.QPointF(15, 7), QtCore.QPointF(17.5, 9))


def _i_frame_miter(p):
    """Two members meeting on a 45 degree cut."""
    _sheet(p, [(3, 20), (3, 13), (11, 13), (18, 20)], 140)
    _sheet(p, [(11, 13), (11, 3), (18, 3), (18, 20)], 105)
    _pen(p, _ACCENT, 1.6)
    p.drawLine(QtCore.QPointF(10, 12), QtCore.QPointF(19, 21))


def _i_frame_corner(p):
    """A butt joint: one member stopped against the other's side."""
    _sheet(p, [(3, 20), (3, 13), (13, 13), (13, 20)], 140)
    _sheet(p, [(13, 21), (13, 3), (20, 3), (20, 21)], 105)
    _pen(p, _ACCENT, 1.6)
    p.drawLine(QtCore.QPointF(13, 11), QtCore.QPointF(13, 22))


def _i_frame_trim(p):
    """A member run on to a face."""
    _sheet(p, [(2, 15), (2, 9), (15, 9), (15, 15)], 140)
    _sheet(p, [(17, 3), (21, 3), (21, 21), (17, 21)], 60)
    _pen(p, _ACCENT, 1.6)
    p.drawLine(QtCore.QPointF(15, 12), QtCore.QPointF(17, 12))


def _i_frame_notch(p):
    """A member with the other's outline cut out of its end."""
    _sheet(p, [(2, 16), (2, 8), (17, 8), (17, 11), (14, 11), (14, 13),
               (17, 13), (17, 16)], 140)
    _pen(p, _ACCENT, 1.6)
    p.drawRoundedRect(QtCore.QRectF(14, 4, 7, 16), 1.5, 1.5)


def _i_frame_lengthen(p):
    """A member and how much longer it gets."""
    _sheet(p, [(2, 15), (2, 9), (14, 9), (14, 15)], 140)
    _pen(p, _ACCENT, 1.6, dashed=True)
    p.drawRect(QtCore.QRectF(14, 9, 6, 6))
    _pen(p, _ACCENT, 1.6)
    p.drawLine(QtCore.QPointF(14, 19), QtCore.QPointF(21, 19))
    p.drawLine(QtCore.QPointF(21, 19), QtCore.QPointF(19, 17))


def _i_frame_member(p):
    """A length of square tube."""
    _sheet(p, [(3, 14), (15, 6), (21, 9), (9, 17)], 150)
    _sheet(p, [(3, 14), (9, 17), (9, 21), (3, 18)], 90)
    _sheet(p, [(9, 17), (21, 9), (21, 13), (9, 21)], 120)


def _i_sm_inside(p):
    """Bend Position: inside the base face's extents."""
    _pen(p, _LINE, 1.8)
    p.drawLine(QtCore.QPointF(3, 18), QtCore.QPointF(16, 18))
    p.drawLine(QtCore.QPointF(16, 18), QtCore.QPointF(16, 4))
    _pen(p, _ACCENT, 1.2, dashed=True)
    p.drawLine(QtCore.QPointF(16, 21), QtCore.QPointF(16, 2))


def _i_sm_adjacent(p):
    """Bend Position: from the adjacent face."""
    _pen(p, _LINE, 1.8)
    p.drawLine(QtCore.QPointF(3, 18), QtCore.QPointF(16, 18))
    p.drawLine(QtCore.QPointF(20, 14), QtCore.QPointF(20, 3))
    path = QtGui.QPainterPath(QtCore.QPointF(16, 18))
    path.quadTo(20, 18, 20, 14)
    p.drawPath(path)
    _pen(p, _ACCENT, 1.2, dashed=True)
    p.drawLine(QtCore.QPointF(16, 21), QtCore.QPointF(16, 2))


def _dir_profile(p, cy):
    """The flat profile the direction icons push out of."""
    _face(p, [(4, cy), (12, cy + 3.5), (20, cy), (12, cy - 3.5)], _SOLID, 150)


def _i_dir_default(p):
    """Extrude direction Default: out of the sketch, along its normal."""
    _dir_profile(p, 17)
    _arrow(p, 12, 17, 12, 3.5, _ACCENT, 3.4, 1.7)


def _i_dir_flipped(p):
    """Extrude direction Flipped: the other way."""
    _dir_profile(p, 7)
    _arrow(p, 12, 7, 12, 20.5, _ACCENT, 3.4, 1.7)


def _i_dir_symmetric(p):
    """Extrude direction Symmetric: half each way."""
    _dir_profile(p, 12)
    _arrow(p, 12, 12, 12, 2.5, _ACCENT, 3.2, 1.7)
    _arrow(p, 12, 12, 12, 21.5, _ACCENT, 3.2, 1.7)


def _i_dir_asymmetric(p):
    """Extrude direction Asymmetric: a long way one side, a short the
    other."""
    _dir_profile(p, 14)
    _arrow(p, 12, 14, 12, 2.5, _ACCENT, 3.2, 1.7)
    _arrow(p, 12, 14, 12, 21.0, _WARM, 3.0, 1.6)


def _i_revolve(p):
    _pen(p, _ACCENT, 1.4, dashed=True)
    p.drawLine(QtCore.QPointF(12, 2.5), QtCore.QPointF(12, 21.5))
    _face(p, [(13.5, 8), (19, 8), (19, 17), (13.5, 17)], _SOLID, 120)
    _pen(p, _ACCENT, 1.7)
    path = QtGui.QPainterPath(QtCore.QPointF(13.5, 6))
    path.arcTo(QtCore.QRectF(4.5, 3.5, 18, 7), 60, 130)
    p.drawPath(path)
    _fill(p, _ACCENT)
    p.drawPolygon(_poly((4.8, 6.4), (8.3, 4.4), (8.0, 8.6)))


def _i_sweep(p):
    _pen(p, _ACCENT, 1.5, dashed=True)
    path = QtGui.QPainterPath(QtCore.QPointF(5, 19))
    path.cubicTo(7, 8, 16, 16, 20, 5)
    p.drawPath(path)
    _face(p, [(3, 17), (7, 15), (7, 21), (3, 23)], _SOLID, 120)
    _face(p, [(17, 6), (21, 4), (21, 9), (17, 11)], _SOLID, 150)
    _pen(p, _LINE, 1.4)
    p.drawLine(QtCore.QPointF(5, 16), QtCore.QPointF(19, 5))


def _i_loft(p):
    _face(p, [(4, 17), (12, 20), (20, 17), (12, 14)], _SOLID, 150)
    _face(p, [(7, 7), (12, 8.8), (17, 7), (12, 5.2)], _SOLID, 190)
    _pen(p, _ACCENT, 1.5, dashed=True)
    p.drawLine(QtCore.QPointF(4, 17), QtCore.QPointF(7, 7))
    p.drawLine(QtCore.QPointF(20, 17), QtCore.QPointF(17, 7))
    p.drawLine(QtCore.QPointF(12, 20), QtCore.QPointF(12, 8.8))


def _i_file(p):
    _face(p, [(5, 3), (14, 3), (19, 8), (19, 21), (5, 21)], _ACCENT, 110)
    _pen(p, _LINE, 1.4)
    p.drawPolyline(_poly((14, 3), (14, 8), (19, 8)))
    p.drawLine(QtCore.QPointF(8, 12), QtCore.QPointF(16, 12))
    p.drawLine(QtCore.QPointF(8, 16), QtCore.QPointF(16, 16))


def _i_exit(p):
    _face(p, [(4, 4), (13, 4), (13, 20), (4, 20)], _SOLID, 80)
    _arrow(p, 14, 12, 21, 12, C.error, 3.4, 1.8)


def _i_hole(p):
    _face(p, [(4, 9), (12, 5), (20, 9), (20, 17), (12, 21), (4, 17)], _SOLID, 95)
    _fill(p, "#141719", 230)
    p.drawEllipse(QtCore.QPointF(12, 10.5), 4.2, 2.4)
    _pen(p, _ACCENT, 1.5)
    p.drawLine(QtCore.QPointF(7.8, 10.5), QtCore.QPointF(7.8, 16))
    p.drawLine(QtCore.QPointF(16.2, 10.5), QtCore.QPointF(16.2, 16))


def _i_fillet(p):
    _face(p, [(4, 20), (4, 11), (11, 4), (20, 4), (20, 20)], _SOLID, 90)
    _pen(p, _ACCENT, 2.2)
    path = QtGui.QPainterPath(QtCore.QPointF(4, 11))
    path.arcTo(QtCore.QRectF(4, 4, 14, 14), 180, -90)
    p.drawPath(path)


def _i_chamfer(p):
    _face(p, [(4, 20), (4, 11), (11, 4), (20, 4), (20, 20)], _SOLID, 90)
    _pen(p, _ACCENT, 2.2)
    p.drawLine(QtCore.QPointF(4, 11), QtCore.QPointF(11, 4))


def _i_shell(p):
    _face(p, [(4, 8), (12, 4), (20, 8), (20, 18), (12, 22), (4, 18)], _SOLID, 70)
    _fill(p, "#171a1d", 240)
    p.drawPolygon(_poly((7, 9.4), (12, 6.9), (17, 9.4), (12, 11.9)))
    _pen(p, _ACCENT, 1.6)
    p.drawPolygon(_poly((7, 9.4), (12, 6.9), (17, 9.4), (12, 11.9)))


def _i_split(p):
    # a block, and the plane that splits it, dashed across
    _block(p, 5, 9, 12, 10, 3.5)
    _pen(p, _ACCENT, 1.6, dashed=True)
    p.drawLine(QtCore.QPointF(2.5, 14.5), QtCore.QPointF(21.5, 11.0))


def _i_split_faces(p):
    # one block, its face drawn in two by the line across it
    _block(p, 5, 7, 12, 12, 3.5)
    _pen(p, _ACCENT, 1.9)
    p.drawLine(QtCore.QPointF(5.0, 13.0), QtCore.QPointF(17.0, 13.0))


def _i_split_solid(p):
    # the block cut through, its two halves pulled apart
    _block(p, 5, 3, 12, 7, 3.0)
    _block(p, 5, 13, 12, 7, 3.0, top=_WARM)


def _i_pattern_rect(p):
    for i in range(3):
        for j in range(2):
            colour = _ACCENT if (i or j) else _WARM
            _fill(p, colour, 200 if (i or j) else 255)
            p.drawRoundedRect(QtCore.QRectF(4 + i * 6.4, 6 + j * 7.5, 4.6, 4.6),
                              1, 1)


def _i_pattern_circ(p):
    _pen(p, _ACCENT, 1.2, dashed=True)
    p.drawEllipse(QtCore.QPointF(12, 12), 7.5, 7.5)
    for i in range(6):
        a = math.radians(-90 + 60 * i)
        _fill(p, _WARM if i == 0 else _ACCENT, 255 if i == 0 else 200)
        p.drawEllipse(QtCore.QPointF(12 + 7.5 * math.cos(a),
                                     12 + 7.5 * math.sin(a)), 2.1, 2.1)


def _i_mirror(p):
    _pen(p, _ACCENT, 1.4, dashed=True)
    p.drawLine(QtCore.QPointF(12, 3), QtCore.QPointF(12, 21))
    _face(p, [(3, 7), (10, 7), (10, 17), (3, 17)], _WARM, 130)
    _face(p, [(21, 7), (14, 7), (14, 17), (21, 17)], _SOLID, 90)


def _i_move(p):
    _arrow(p, 12, 12, 12, 3.5, _ACCENT, 3.0, 1.5)
    _arrow(p, 12, 12, 20.5, 12, _GREEN, 3.0, 1.5)
    _arrow(p, 12, 12, 5, 19, C.error, 3.0, 1.5)


def _i_box(p):
    _box_iso(p)


def _i_cylinder(p):
    _face(p, [(6, 8), (18, 8), (18, 17), (6, 17)], _SOLID, 105, None)
    _pen(p, _LINE, 1.5)
    p.drawLine(QtCore.QPointF(6, 8), QtCore.QPointF(6, 17))
    p.drawLine(QtCore.QPointF(18, 8), QtCore.QPointF(18, 17))
    _face(p, [], _SOLID, 0, None)
    _fill(p, _SOLID, 165)
    p.drawEllipse(QtCore.QRectF(6, 4.5, 12, 7))
    _pen(p, _LINE, 1.5)
    p.drawEllipse(QtCore.QRectF(6, 4.5, 12, 7))
    p.drawArc(QtCore.QRectF(6, 13.5, 12, 7), 180 * 16, 180 * 16)


def _i_sphere(p):
    _fill(p, _SOLID, 130)
    p.drawEllipse(QtCore.QPointF(12, 12), 8, 8)
    _pen(p, _LINE, 1.4)
    p.drawEllipse(QtCore.QPointF(12, 12), 8, 8)
    p.drawArc(QtCore.QRectF(4, 8.5, 16, 7), 0, 180 * 16)
    p.drawEllipse(QtCore.QRectF(8.5, 4, 7, 16))


def _i_plane(p):
    _face(p, [(3, 15), (11, 7), (21, 9), (13, 17)], _ACCENT, 70)
    _pen(p, _ACCENT, 1.3)
    p.drawLine(QtCore.QPointF(12, 12), QtCore.QPointF(15.5, 4))


def _i_axis(p):
    # a line running through, with the dashes of a centre line
    _pen(p, _ACCENT, 1.6)
    p.drawLine(QtCore.QPointF(4, 20), QtCore.QPointF(20, 4))
    _pen(p, _LINE, 1.0, dashed=True)
    p.drawEllipse(QtCore.QPointF(12, 12), 5.5, 2.6)


def _i_import(p):
    _face(p, [(4, 5), (13, 5), (13, 19), (4, 19)], _SOLID, 70)
    _arrow(p, 21, 12, 14.5, 12, _GREEN, 3.4, 1.8)


def _i_export(p):
    _face(p, [(4, 5), (13, 5), (13, 19), (4, 19)], _SOLID, 70)
    _arrow(p, 14.5, 12, 21, 12, _ACCENT, 3.4, 1.8)


def _i_delete(p):
    _fill(p, C.error, 170)
    p.drawRoundedRect(QtCore.QRectF(6, 7, 12, 13), 1.5, 1.5)
    _pen(p, _LINE, 1.5)
    p.drawLine(QtCore.QPointF(4.5, 6.5), QtCore.QPointF(19.5, 6.5))
    p.drawLine(QtCore.QPointF(9.5, 4.5), QtCore.QPointF(14.5, 4.5))


def _i_edit(p):
    p.save()
    p.translate(1, 0)
    _face(p, [(4, 20), (5.5, 15.5), (16, 5), (19, 8), (8.5, 18.5)], _WARM, 150)
    p.restore()


def _i_suppress(p):
    _pen(p, _LINE, 1.6, dashed=True)
    p.drawRect(QtCore.QRectF(5, 7, 14, 10))
    _pen(p, C.error, 2.0)
    p.drawLine(QtCore.QPointF(5, 19), QtCore.QPointF(19, 5))


def _i_rollback(p):
    _pen(p, _ACCENT, 2.0)
    p.drawLine(QtCore.QPointF(3, 12), QtCore.QPointF(21, 12))
    _fill(p, _WARM)
    p.drawPolygon(_poly((13, 6), (20, 12), (13, 18)))
    _pen(p, _LINE, 1.6)
    p.drawLine(QtCore.QPointF(4.5, 6), QtCore.QPointF(4.5, 18))


def _i_update(p):
    """Local Update: Inventor's lightning bolt over a part."""
    _face(p, ((3, 8), (9, 5), (9, 15), (3, 18)), _SOLID, 70)
    _fill(p, _WARM)
    p.drawPolygon(_poly((15, 3), (10.5, 12), (13.5, 12),
                        (10, 21), (19, 10), (15.5, 10), (19, 3)))
    _pen(p, _WARM, 1.2)
    p.drawPolyline(_poly((15, 3), (10.5, 12), (13.5, 12),
                         (10, 21), (19, 10), (15.5, 10), (19, 3)))


def _i_rect3(p):
    """Three-point rectangle: a leaning box with its base edge picked out."""
    _pen(p, _LINE, 1.6)
    p.drawPolygon(_poly((4, 15), (13, 6), (20, 13), (11, 22)))
    _pen(p, _ACCENT, 2.2)
    p.drawLine(QtCore.QPointF(4, 15), QtCore.QPointF(13, 6))


def _i_rect_centre(p):
    _pen(p, _LINE, 1.6)
    p.drawRect(QtCore.QRectF(4, 7, 16, 11))
    _fill(p, _ACCENT)
    p.drawEllipse(QtCore.QPointF(12, 12.5), 1.9, 1.9)


def _i_rect3_centre(p):
    _pen(p, _LINE, 1.6)
    p.drawPolygon(_poly((4, 15), (13, 6), (20, 13), (11, 22)))
    _fill(p, _ACCENT)
    p.drawEllipse(QtCore.QPointF(12, 14), 1.9, 1.9)


def _slot_body(p, colour=None, width=1.6):
    colour = _LINE if colour is None else colour
    _pen(p, colour, width)
    p.drawArc(QtCore.QRectF(3, 8, 8, 8), 90 * 16, 180 * 16)
    p.drawArc(QtCore.QRectF(13, 8, 8, 8), -90 * 16, 180 * 16)
    p.drawLine(QtCore.QPointF(7, 8), QtCore.QPointF(17, 8))
    p.drawLine(QtCore.QPointF(7, 16), QtCore.QPointF(17, 16))


def _i_slot_overall(p):
    _slot_body(p)
    _pen(p, _ACCENT, 1.5)
    p.drawLine(QtCore.QPointF(3, 20), QtCore.QPointF(21, 20))
    p.drawLine(QtCore.QPointF(3, 18), QtCore.QPointF(3, 22))
    p.drawLine(QtCore.QPointF(21, 18), QtCore.QPointF(21, 22))


def _i_slot_centre(p):
    _slot_body(p)
    _fill(p, _ACCENT)
    p.drawEllipse(QtCore.QPointF(12, 12), 1.9, 1.9)


def _i_slot_arc(p):
    """A slot bent round an arc."""
    _pen(p, _LINE, 1.6)
    p.drawArc(QtCore.QRectF(2, 4, 20, 20), 20 * 16, 140 * 16)
    p.drawArc(QtCore.QRectF(5, 7, 14, 14), 20 * 16, 140 * 16)
    _pen(p, _LINE, 1.6)
    p.drawArc(QtCore.QRectF(16.0, 6.0, 4.2, 4.2), -70 * 16, 180 * 16)
    p.drawArc(QtCore.QRectF(3.8, 6.0, 4.2, 4.2), 70 * 16, 180 * 16)


def _i_slot_arc_centre(p):
    _i_slot_arc(p)
    _fill(p, _ACCENT)
    p.drawEllipse(QtCore.QPointF(12, 14), 1.9, 1.9)


def _i_fit(p):
    _pen(p, _ACCENT, 1.7)
    for sx, sy in ((1, 1), (-1, 1), (1, -1), (-1, -1)):
        x = 12 + sx * 8
        y = 12 + sy * 8
        p.drawLine(QtCore.QPointF(x, y), QtCore.QPointF(x - sx * 4, y))
        p.drawLine(QtCore.QPointF(x, y), QtCore.QPointF(x, y - sy * 4))
    _fill(p, _SOLID, 130)
    p.drawRect(QtCore.QRectF(9, 9, 6, 6))


def _view_icon(front, top, right):
    def draw(p):
        _face(p, [(12, 4), (20, 8), (12, 12), (4, 8)], _SOLID,
              200 if top else 45)
        _face(p, [(4, 8), (12, 12), (12, 21), (4, 17)], _SOLID,
              200 if front else 45)
        _face(p, [(20, 8), (12, 12), (12, 21), (20, 17)], _SOLID,
              200 if right else 45)
    return draw


def _i_iso(p):
    _box_iso(p, colour=_ACCENT)


def _i_shaded(p):
    _box_iso(p)


def _i_shaded_edges(p):
    _box_iso(p)
    _pen(p, _LINE, 1.4)
    p.drawPolygon(_poly((12, 4), (18.93, 8), (12, 12), (5.07, 8)))
    p.drawLine(QtCore.QPointF(12, 12), QtCore.QPointF(12, 20))


def _i_wireframe(p):
    _pen(p, _LINE, 1.4)
    p.drawPolygon(_poly((12, 5.5), (19, 8), (12, 10.5), (5, 8)))
    p.drawPolygon(_poly((5, 8), (12, 10.5), (12, 18.5), (5, 15.5)))
    p.drawPolygon(_poly((19, 8), (12, 10.5), (12, 18.5), (19, 15.5)))


def _i_section(p):
    _face(p, [(4, 9), (12, 5), (12, 14), (4, 18)], _SOLID, 110)
    _pen(p, C.error, 1.6, dashed=True)
    p.drawLine(QtCore.QPointF(12, 3), QtCore.QPointF(12, 21))
    _face(p, [(12, 5), (20, 9), (20, 18), (12, 14)], _SOLID, 35)


def _i_ortho(p):
    _pen(p, _LINE, 1.6)
    p.drawRect(QtCore.QRectF(4.5, 6.5, 15, 11))
    p.drawLine(QtCore.QPointF(4.5, 12), QtCore.QPointF(19.5, 12))
    p.drawLine(QtCore.QPointF(12, 6.5), QtCore.QPointF(12, 17.5))


def _i_grid(p):
    _pen(p, _LINE, 1.2)
    for i in range(4):
        v = 4.5 + i * 5
        p.drawLine(QtCore.QPointF(v, 4.5), QtCore.QPointF(v, 19.5))
        p.drawLine(QtCore.QPointF(4.5, v), QtCore.QPointF(19.5, v))


def _i_finish(p):
    _pen(p, _GREEN, 2.4)
    p.drawPolyline(_poly((4.5, 12.5), (10, 18), (19.5, 6.5)))


def _i_cancel(p):
    _pen(p, C.error, 2.2)
    p.drawLine(QtCore.QPointF(6, 6), QtCore.QPointF(18, 18))
    p.drawLine(QtCore.QPointF(18, 6), QtCore.QPointF(6, 18))


def _i_select(p):
    _fill(p, _LINE, 230)
    p.drawPolygon(_poly((7, 3.5), (7, 18.5), (11, 14.8), (13.6, 20.5),
                        (16.2, 19.2), (13.6, 13.8), (18.5, 13.4)))


def _i_material(p):
    _fill(p, _WARM, 140)
    p.drawEllipse(QtCore.QPointF(9.5, 9.5), 5.5, 5.5)
    _fill(p, _ACCENT, 140)
    p.drawEllipse(QtCore.QPointF(15, 15), 5.5, 5.5)


# constraint glyphs -------------------------------------------------------


def _i_c_coincident(p):
    _pen(p, _LINE, 1.6)
    p.drawLine(QtCore.QPointF(4, 18), QtCore.QPointF(12, 12))
    p.drawLine(QtCore.QPointF(20, 18), QtCore.QPointF(12, 12))
    _fill(p, _WARM)
    p.drawEllipse(QtCore.QPointF(12, 12), 3.0, 3.0)


def _i_c_horizontal(p):
    _pen(p, _LINE, 2.0)
    p.drawLine(QtCore.QPointF(4, 12), QtCore.QPointF(20, 12))
    _fill(p, _ACCENT)
    p.drawEllipse(QtCore.QPointF(4, 12), 2.0, 2.0)
    p.drawEllipse(QtCore.QPointF(20, 12), 2.0, 2.0)


def _i_c_vertical(p):
    _pen(p, _LINE, 2.0)
    p.drawLine(QtCore.QPointF(12, 4), QtCore.QPointF(12, 20))
    _fill(p, _ACCENT)
    p.drawEllipse(QtCore.QPointF(12, 4), 2.0, 2.0)
    p.drawEllipse(QtCore.QPointF(12, 20), 2.0, 2.0)


def _i_c_parallel(p):
    _pen(p, _LINE, 2.0)
    p.drawLine(QtCore.QPointF(6, 20), QtCore.QPointF(11, 4))
    p.drawLine(QtCore.QPointF(14, 20), QtCore.QPointF(19, 4))


def _i_c_collinear(p):
    # two segments on one line, with the gap between them saying they are
    # separate edges rather than one long one
    _pen(p, _LINE, 2.0)
    p.drawLine(QtCore.QPointF(4, 12), QtCore.QPointF(10, 12))
    p.drawLine(QtCore.QPointF(14, 12), QtCore.QPointF(20, 12))
    _pen(p, _ACCENT, 1.2)
    p.drawLine(QtCore.QPointF(10, 12), QtCore.QPointF(14, 12))


def _i_c_perpendicular(p):
    _pen(p, _LINE, 2.0)
    p.drawLine(QtCore.QPointF(6, 19), QtCore.QPointF(20, 19))
    p.drawLine(QtCore.QPointF(9, 19), QtCore.QPointF(9, 5))
    _pen(p, _ACCENT, 1.4)
    p.drawPolyline(_poly((9, 15), (13, 15), (13, 19)))


def _i_c_tangent(p):
    _pen(p, _LINE, 1.8)
    p.drawEllipse(QtCore.QPointF(12, 14), 6, 6)
    _pen(p, _ACCENT, 2.0)
    p.drawLine(QtCore.QPointF(3, 8), QtCore.QPointF(21, 8))


def _i_c_equal(p):
    _pen(p, _LINE, 2.2)
    p.drawLine(QtCore.QPointF(5, 9.5), QtCore.QPointF(19, 9.5))
    p.drawLine(QtCore.QPointF(5, 15), QtCore.QPointF(19, 15))


def _i_c_concentric(p):
    _pen(p, _LINE, 1.8)
    p.drawEllipse(QtCore.QPointF(12, 12), 8, 8)
    p.drawEllipse(QtCore.QPointF(12, 12), 3.8, 3.8)
    _fill(p, _WARM)
    p.drawEllipse(QtCore.QPointF(12, 12), 1.4, 1.4)


def _i_c_midpoint(p):
    _pen(p, _LINE, 1.8)
    p.drawLine(QtCore.QPointF(4, 12), QtCore.QPointF(20, 12))
    _fill(p, _WARM)
    p.drawEllipse(QtCore.QPointF(12, 12), 3.0, 3.0)
    _fill(p, _ACCENT)
    p.drawEllipse(QtCore.QPointF(4, 12), 1.8, 1.8)
    p.drawEllipse(QtCore.QPointF(20, 12), 1.8, 1.8)


def _i_c_symmetric(p):
    _pen(p, _ACCENT, 1.4, dashed=True)
    p.drawLine(QtCore.QPointF(12, 3), QtCore.QPointF(12, 21))
    _fill(p, _LINE)
    p.drawEllipse(QtCore.QPointF(5, 12), 2.4, 2.4)
    p.drawEllipse(QtCore.QPointF(19, 12), 2.4, 2.4)


def _i_c_fix(p):
    _pen(p, _GREEN, 2.0)
    p.drawLine(QtCore.QPointF(6, 6), QtCore.QPointF(18, 18))
    p.drawLine(QtCore.QPointF(18, 6), QtCore.QPointF(6, 18))
    _fill(p, _GREEN)
    p.drawEllipse(QtCore.QPointF(12, 12), 2.6, 2.6)


def _i_c_pointon(p):
    _pen(p, _LINE, 1.8)
    p.drawLine(QtCore.QPointF(4, 17), QtCore.QPointF(20, 7))
    _fill(p, _WARM)
    p.drawEllipse(QtCore.QPointF(12, 12), 3.0, 3.0)


def _i_code(p):
    # a block with brackets over it: a solid a script builds
    _face(p, [(4, 15), (10, 18), (16, 15), (10, 12)], _SOLID, 165)
    _face(p, [(4, 15), (10, 18), (10, 21), (4, 18)], _SOLID, 80)
    _face(p, [(16, 15), (10, 18), (10, 21), (16, 18)], _SOLID, 120)
    _pen(p, _WARM, 1.7)
    p.drawPolyline(_poly((8, 3.5), (4.5, 7), (8, 10.5)))
    p.drawPolyline(_poly((16, 3.5), (19.5, 7), (16, 10.5)))
    _pen(p, _ACCENT, 1.5)
    p.drawLine(QtCore.QPointF(13.3, 3), QtCore.QPointF(10.7, 11))


def _i_auto(p):
    _pen(p, _ACCENT, 1.7)
    p.drawPolyline(_poly((4, 16), (10, 8), (16, 14), (20, 8)))
    _fill(p, _WARM)
    p.drawPolygon(_poly((16, 3), (18, 8), (23, 8.5), (19, 12), (20, 17),
                        (16, 14.3), (12, 17), (13, 12), (9, 8.5), (14, 8)))



# --------------------------------------------------------------------------
# assembly relationships
#
# These are not the sketch constraints with a different label on them, and
# they must not look like them: the sketch pair say something about two
# lines on a plane, these say something about two solids in space. The
# complaint that prompted them was exact - Insert was drawn with the
# concentric glyph and Flush with the parallel one, so of course they read
# as concentric and parallel.
#
# So each of these is a little isometric picture of what the constraint
# does to two blocks, the way Inventor's Place Constraint dialog draws
# them, and Mate and Flush share a motif on purpose: same two blocks, the
# arrows opposed for Mate and aligned for Flush, because that is the only
# difference between them.
# --------------------------------------------------------------------------


def _block(p, x, y, w, h, depth=3.0, tone=None, top=None):
    """A little isometric box: front face, top face, side face."""
    tone = _SOLID if tone is None else tone
    top = _ACCENT if top is None else top
    _fill(p, tone)
    p.drawPolygon(_poly((x, y), (x + w, y), (x + w, y + h), (x, y + h)))
    _fill(p, top)
    p.drawPolygon(_poly((x, y), (x + depth, y - depth),
                        (x + w + depth, y - depth), (x + w, y)))
    _fill(p, tone, 170)
    p.drawPolygon(_poly((x + w, y), (x + w + depth, y - depth),
                        (x + w + depth, y + h - depth), (x + w, y + h)))


def _face_arrow(p, x, y, dx, colour=_WARM, length=3.4):
    """A short arrow at (x, y) pointing along dx, which is 1 or -1.

    Named apart from the general _arrow above, which takes two points.
    """
    _pen(p, colour, 1.7)
    p.drawLine(QtCore.QPointF(x, y), QtCore.QPointF(x + dx * length, y))
    _fill(p, colour)
    tip = x + dx * length
    p.drawPolygon(_poly((tip + dx * 1.8, y), (tip, y - 1.7), (tip, y + 1.7)))


def _i_c3d_mate(p):
    # two faces brought together, so the arrows point at each other
    _block(p, 2.5, 8, 6.5, 10)
    _block(p, 15, 8, 6.5, 10)
    _face_arrow(p, 9.8, 13.5, 1)
    _face_arrow(p, 14.2, 13.5, -1)


def _i_c3d_flush(p):
    # the same two faces, but facing the same way: lined up, not meeting
    _block(p, 2.5, 8, 6.5, 10)
    _block(p, 12, 8, 6.5, 10)
    _face_arrow(p, 9.4, 13.5, 1, length=2.6)
    _face_arrow(p, 19, 13.5, 1, length=2.6)
    _pen(p, _LINE, 1.0, dashed=True)
    p.drawLine(QtCore.QPointF(2.5, 20.4), QtCore.QPointF(21.5, 20.4))


def _i_c3d_angle(p):
    # one face held at an angle to another, with the angle called out
    _fill(p, _SOLID)
    p.drawPolygon(_poly((3, 19), (17, 19), (17, 21.5), (3, 21.5)))
    _fill(p, _SOLID, 200)
    p.drawPolygon(_poly((4.5, 18.4), (13.5, 5.5), (16, 7.2), (7, 20)))
    _pen(p, _WARM, 1.5)
    rect = QtCore.QRectF(1.0, 12.5, 13.0, 13.0)
    p.drawArc(rect, 0 * 16, 58 * 16)


def _i_c3d_parallel(p):
    # two faces at different heights, both looking the same way
    _block(p, 2.5, 11, 6.5, 8)
    _block(p, 12, 5, 6.5, 8)
    _face_arrow(p, 9.4, 15, 1, length=2.6)
    _face_arrow(p, 19, 9, 1, length=2.6)
    _pen(p, _LINE, 1.0, dashed=True)
    p.drawLine(QtCore.QPointF(2.5, 21.4), QtCore.QPointF(21.5, 21.4))


def _i_c3d_tangent(p):
    # a round face resting on a flat one, touching at a point
    _fill(p, _SOLID)
    p.drawPolygon(_poly((2.5, 18), (21.5, 18), (21.5, 21), (2.5, 21)))
    _pen(p, _LINE, 1.7)
    _fill(p, _ACCENT, 90)
    p.drawEllipse(QtCore.QPointF(12, 11.4), 6.4, 6.4)
    _fill(p, _WARM)
    p.drawEllipse(QtCore.QPointF(12, 17.9), 1.5, 1.5)


def _i_c3d_insert(p):
    # a shaft dropped into a bore: two rings seen from the side, one going
    # into the other, which is what Insert actually does
    _pen(p, _ACCENT, 1.1, dashed=True)
    p.drawLine(QtCore.QPointF(12, 2.5), QtCore.QPointF(12, 21.5))
    # the bore, as a block with a mouth
    _fill(p, _SOLID)
    p.drawPolygon(_poly((4, 13), (20, 13), (20, 21), (4, 21)))
    _fill(p, "#1e2124")
    p.drawPolygon(_poly((9, 13), (15, 13), (15, 21), (9, 21)))
    # the shaft above it, on its way in
    _fill(p, _LINE)
    p.drawPolygon(_poly((9.6, 4), (14.4, 4), (14.4, 15.5), (9.6, 15.5)))
    _pen(p, _LINE, 1.4)
    _fill(p, _ACCENT)
    p.drawEllipse(QtCore.QPointF(12, 4), 2.4, 1.2)


def _i_c3d_symmetry(p):
    _pen(p, _WARM, 1.2, dashed=True)
    p.drawLine(QtCore.QPointF(12, 2.5), QtCore.QPointF(12, 21.5))
    _block(p, 2.5, 9, 6.0, 9)
    _block(p, 15.5, 9, 6.0, 9)
    _pen(p, _ACCENT, 1.3)
    p.drawLine(QtCore.QPointF(9.4, 6.5), QtCore.QPointF(14.6, 6.5))

PAINTERS: Dict[str, Callable[[QtGui.QPainter], None]] = {
    "new": _i_new, "open": _i_open, "save": _i_save, "undo": _i_undo,
    "redo": _i_redo, "sketch": _i_sketch, "sketch_shared": _i_sketch_shared,
    "spacemouse": _i_spacemouse, "line": _i_line, "rect": _i_rect,
    "circle": _i_circle, "arc": _i_arc, "polygon": _i_polygon,
    "text": _i_text, "slot": _i_slot,
    "spline": _i_spline, "point": _i_point, "fillet2d": _i_fillet2d,
    "trim": _i_trim, "offset": _i_offset, "dimension": _i_dimension,
    "measure": _i_measure, "params": _i_params, "extrude": _i_extrude,
    "emboss": _i_emboss, "engrave": _i_engrave,
    "dof": _i_dof,
    "sm_face": _i_sm_face, "sm_flange": _i_sm_flange, "sm_flat": _i_sm_flat,
    "sm_defaults": _i_sm_defaults, "sm_convert": _i_sm_convert,
    "sm_inside": _i_sm_inside, "sm_adjacent": _i_sm_adjacent,
    "frame_insert": _i_frame_insert, "frame_library": _i_frame_library,
    "frame_member": _i_frame_member, "frame_assembly": _i_frame_assembly,
    "frame_change": _i_frame_change, "frame_miter": _i_frame_miter,
    "frame_corner": _i_frame_corner, "frame_trim": _i_frame_trim,
    "frame_notch": _i_frame_notch, "frame_lengthen": _i_frame_lengthen,
    "sm_hem": _i_sm_hem, "sm_hem_teardrop": _i_sm_hem_teardrop,
    "sm_hem_rolled": _i_sm_hem_rolled, "sm_hem_double": _i_sm_hem_double,
    "sm_fold": _i_sm_fold, "sm_contour": _i_sm_contour,
    "sm_corner": _i_sm_corner, "sm_perforation": _i_sm_perforation,
    "sm_perforation_straight": _i_sm_perforation_straight,
    "sm_perforation_trapezoid": _i_sm_perforation_trapezoid,
    "revolve": _i_revolve, "sweep": _i_sweep, "loft": _i_loft,
    "file": _i_file, "exit": _i_exit,
    "hole": _i_hole, "fillet": _i_fillet,
    "chamfer": _i_chamfer, "shell": _i_shell, "pattern": _i_pattern_rect,
    "split": _i_split, "split_faces": _i_split_faces,
    "split_solid": _i_split_solid,
    "pattern_circ": _i_pattern_circ, "mirror": _i_mirror, "move": _i_move,
    "box": _i_box, "cylinder": _i_cylinder, "sphere": _i_sphere,
    "plane": _i_plane, "axis": _i_axis, "import": _i_import, "export": _i_export,
    "delete": _i_delete, "edit": _i_edit, "suppress": _i_suppress,
    "rollback": _i_rollback, "update": _i_update, "fit": _i_fit,
    "rect3": _i_rect3, "rect_centre": _i_rect_centre,
    "rect3_centre": _i_rect3_centre,
    "slot_overall": _i_slot_overall, "slot_centre": _i_slot_centre,
    "slot_arc3": _i_slot_arc, "slot_arc_centre": _i_slot_arc_centre,
    "iso": _i_iso,
    "front": _view_icon(True, False, False),
    "top": _view_icon(False, True, False),
    "right": _view_icon(False, False, True),
    "shaded": _i_shaded, "shaded_edges": _i_shaded_edges,
    "wireframe": _i_wireframe, "section": _i_section, "ortho": _i_ortho,
    "grid": _i_grid, "finish": _i_finish, "cancel": _i_cancel,
    "select": _i_select, "material": _i_material,
    "c_coincident": _i_c_coincident, "c_horizontal": _i_c_horizontal,
    "c_vertical": _i_c_vertical, "c_parallel": _i_c_parallel,
    "c_collinear": _i_c_collinear,
    "c_perpendicular": _i_c_perpendicular, "c_tangent": _i_c_tangent,
    "c_equal": _i_c_equal, "c_concentric": _i_c_concentric,
    "c_midpoint": _i_c_midpoint, "c_symmetric": _i_c_symmetric,
    "c_fix": _i_c_fix, "c_pointon": _i_c_pointon, "auto": _i_auto,
    "code": _i_code,
    # the assembly ones, which are a different thing from the sketch ones
    "c3d_mate": _i_c3d_mate, "c3d_flush": _i_c3d_flush,
    "c3d_angle": _i_c3d_angle, "c3d_tangent": _i_c3d_tangent,
    "c3d_parallel": _i_c3d_parallel,
    "c3d_insert": _i_c3d_insert, "c3d_symmetry": _i_c3d_symmetry,
    "feature": _i_box,
    "dir_default": _i_dir_default, "dir_flipped": _i_dir_flipped,
    "dir_symmetric": _i_dir_symmetric,
    "dir_asymmetric": _i_dir_asymmetric,
}


def pixmap(name: str, size: int = 24, ratio: float = 1.0) -> QtGui.QPixmap:
    px = QtGui.QPixmap(int(size * ratio), int(size * ratio))
    px.setDevicePixelRatio(ratio)
    px.fill(QtCore.Qt.transparent)
    painter = QtGui.QPainter(px)
    painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
    painter.scale(size / GRID, size / GRID)
    fn = PAINTERS.get(name)
    if fn is not None:
        fn(painter)
    painter.end()
    return px


def use_theme(name: str) -> None:
    """Draw icons in a colour scheme's tones from now on."""
    from .theme import ICON_TONES
    global _LINE, _ACCENT, _SOLID
    _LINE, _ACCENT, _SOLID = ICON_TONES.get(name, ICON_TONES["light"])
    _cache.clear()


def window_glyph_colour() -> str:
    return _LINE


def icon(name: str, size: int = 24) -> QtGui.QIcon:
    key = (name, size, "n")
    if key not in _cache:
        ic = QtGui.QIcon()
        for ratio in (1.0, 2.0):
            ic.addPixmap(pixmap(name, size, ratio))
        # a dimmed copy for the disabled state
        dis = pixmap(name, size, 2.0)
        img = dis.toImage()
        for y in range(img.height()):
            for x in range(img.width()):
                c = img.pixelColor(x, y)
                if c.alpha():
                    grey = int(0.35 * c.red() + 0.45 * c.green() + 0.2 * c.blue())
                    c.setRgb(grey, grey, grey, int(c.alpha() * 0.45))
                    img.setPixelColor(x, y, c)
        dim = QtGui.QPixmap.fromImage(img)
        dim.setDevicePixelRatio(2.0)
        ic.addPixmap(dim, QtGui.QIcon.Disabled)
        _cache[key] = ic
    return _cache[key]


# The DATUM mark, taken straight off the drawing rather than redrawn by
# eye: two closed polygons, no curves anywhere, so they port exactly.  The
# coordinates are the artwork's own; _mark_point maps them onto the 24 unit
# grid the rest of this icon set works in.
# Brushed metal rather than a colour: the artwork was a soft neutral, and a
# neutral is what suits a tool named after a machining reference.  The face
# carries a slight sheen across it so the front plate catches light, and the
# hook behind takes a cool mid-grey so it reads as the shadow it is.
MARK_FACE = "#d5dee8"
MARK_SHEEN = "#ffffff"
MARK_BACK = "#69788b"
MARK_FIELD = "#171a20"

# the hook that sits up and to the right
_MARK_PLATE = ((51, 38), (105, 38), (144, 60), (145, 105), (127, 114),
               (128, 75), (96, 54), (51, 54))
# and the body, which folds round on itself to leave the counter
_MARK_BODY = ((51, 62), (94, 62), (119, 77), (119, 118), (74, 143),
              (36, 143), (25, 137), (25, 100), (45, 89), (45, 128),
              (47, 129), (79, 111), (100, 111), (100, 84), (93, 79),
              (51, 79))

_MARK_BOX = (25.0, 38.0, 145.0, 143.0)      # what the artwork spans
_MARK_SPAN = 17.0                           # how much of the grid it fills


def _mark_point(x: float, y: float) -> tuple:
    x0, y0, x1, y1 = _MARK_BOX
    scale = _MARK_SPAN / (x1 - x0)
    return (12.0 + (x - (x0 + x1) / 2.0) * scale,
            12.0 + (y - (y0 + y1) / 2.0) * scale)


def draw_mark(p: QtGui.QPainter, field: bool = True) -> None:
    """Paint the DATUM mark on the 24 unit grid."""
    p.setRenderHint(QtGui.QPainter.Antialiasing, True)
    p.setPen(QtCore.Qt.NoPen)

    if field:
        p.setBrush(QtGui.QColor(MARK_FIELD))
        p.drawRoundedRect(QtCore.QRectF(1, 1, 22, 22), 4, 4)

    # the hook behind takes the darker tone, so the two read as one shape
    # with a side to it rather than as a flat cut-out
    p.setBrush(QtGui.QColor(MARK_BACK))
    p.drawPolygon(_poly(*[_mark_point(x, y) for x, y in _MARK_PLATE]))

    sheen = QtGui.QLinearGradient(4.0, 4.0, 20.0, 20.0)
    sheen.setColorAt(0.0, QtGui.QColor(MARK_SHEEN))
    sheen.setColorAt(1.0, QtGui.QColor(MARK_FACE))
    p.setBrush(QtGui.QBrush(sheen))
    p.drawPolygon(_poly(*[_mark_point(x, y) for x, y in _MARK_BODY]))


def mark_pixmap(size: int, field: bool = True,
                ratio: float = 1.0) -> QtGui.QPixmap:
    """The mark on its own, for the start page and anywhere else it is shown."""
    px = QtGui.QPixmap(int(size * ratio), int(size * ratio))
    px.setDevicePixelRatio(ratio)
    px.fill(QtCore.Qt.transparent)
    p = QtGui.QPainter(px)
    p.scale(size * ratio / GRID, size * ratio / GRID)
    draw_mark(p, field)
    p.end()
    return px


def _window_glyph(kind: str, size: int, colour: str) -> QtGui.QIcon:
    """The minimise, maximise, restore and close marks, thin as Windows'."""
    ic = QtGui.QIcon()
    for ratio in (1.0, 2.0):
        px = QtGui.QPixmap(int(size * ratio), int(size * ratio))
        px.setDevicePixelRatio(ratio)
        px.fill(QtCore.Qt.transparent)
        p = QtGui.QPainter(px)
        p.setRenderHint(QtGui.QPainter.Antialiasing, True)
        pen = QtGui.QPen(QtGui.QColor(colour))
        pen.setWidthF(1.0)
        p.setPen(pen)
        s = float(size)
        a, b = s * 0.25, s * 0.75
        if kind == "min":
            p.drawLine(QtCore.QPointF(a, s * 0.5), QtCore.QPointF(b, s * 0.5))
        elif kind == "max":
            p.drawRect(QtCore.QRectF(a, a, b - a, b - a))
        elif kind == "restore":
            d = s * 0.12
            p.drawRect(QtCore.QRectF(a, a + d, b - a - d, b - a - d))
            p.drawPolyline(_poly((a + d, a + d), (a + d, a), (b, a),
                                 (b, b - d), (b - d, b - d)))
        elif kind == "close":
            p.drawLine(QtCore.QPointF(a, a), QtCore.QPointF(b, b))
            p.drawLine(QtCore.QPointF(a, b), QtCore.QPointF(b, a))
        p.end()
        ic.addPixmap(px)
    return ic


def window_icon(kind: str, size: int = 12,
                colour: Optional[str] = None) -> QtGui.QIcon:
    """One of the title bar's window buttons: min, max, restore, close."""
    return _window_glyph(kind, size, colour or _LINE)


# The InventCraft beaver, drawn once by hand and kept as pictures, one per
# size, so each size is scaled from the nearest larger one rather than from
# a single big image.
BRAND_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "brand")
BRAND_SIZES = (16, 24, 32, 48, 64, 128, 256, 512)
_brand_cache: Dict[Tuple[int, float], QtGui.QPixmap] = {}


def brand_pixmap(size: int, ratio: float = 1.0) -> QtGui.QPixmap:
    """The beaver tile at a size, sharp on a scaled display too."""
    key = (size, ratio)
    if key not in _brand_cache:
        want = int(round(size * ratio))
        pick = next((s for s in BRAND_SIZES if s >= want), BRAND_SIZES[-1])
        source = QtGui.QPixmap(os.path.join(
            BRAND_FOLDER, "inventcraft-%d.png" % pick))
        if source.isNull():
            # the pictures missing: the old drawn mark rather than nothing
            return mark_pixmap(size, ratio=ratio)
        px = source.scaled(want, want, QtCore.Qt.KeepAspectRatio,
                           QtCore.Qt.SmoothTransformation)
        px.setDevicePixelRatio(ratio)
        _brand_cache[key] = px
    return _brand_cache[key]


def app_icon() -> QtGui.QIcon:
    """Window and taskbar icon: the InventCraft beaver."""
    ic = QtGui.QIcon()
    for size in BRAND_SIZES:
        px = QtGui.QPixmap(os.path.join(BRAND_FOLDER,
                                        "inventcraft-%d.png" % size))
        if not px.isNull():
            ic.addPixmap(px)
    if ic.isNull():
        for size in (16, 32, 48, 64, 128, 256):
            ic.addPixmap(mark_pixmap(size))
    return ic
