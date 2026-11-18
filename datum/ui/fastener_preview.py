"""A fastener drawn from its numbers, the way the profiles are.

Bolts, screws and pins are drawn from the side, head up, as they stand in
the hole; nuts, washers, rings and bearings from above, where their shape
is.  The same drawing is the family's icon in Place from Library and the
picture beside the sizes, so what is about to be placed is plain before
it is.  Nothing is built for it: the outline comes straight from the
table, so a thousand icons cost nothing.
"""
from __future__ import annotations

import math
from typing import Dict, Optional, Tuple

from PySide6 import QtCore, QtGui

HEXAGON = 2.0 / math.sqrt(3.0)
Box = Tuple[float, float, float, float]


def _poly(path: QtGui.QPainterPath, pts) -> None:
    path.moveTo(*pts[0])
    for p in pts[1:]:
        path.lineTo(*p)
    path.closeSubpath()


def _rect(path, x0, y0, x1, y1) -> None:
    _poly(path, [(x0, y0), (x1, y0), (x1, y1), (x0, y1)])


def _dome(path, r, y0, side, top) -> None:
    """A round topped head, from the side: straight up for ``side``, then
    an arc over to the other side."""
    path.moveTo(-r, y0)
    path.lineTo(r, y0)
    path.lineTo(r, y0 + side)
    rise = max(top - (y0 + side), 1e-3)
    radius = (r * r + rise * rise) / (2.0 * rise)
    cy = top - radius
    start = math.degrees(math.atan2(y0 + side - cy, r))
    path.arcTo(QtCore.QRectF(-radius, cy - radius, 2 * radius, 2 * radius),
               -start, -(180.0 - 2 * start))
    path.lineTo(-r, y0)
    path.closeSubpath()


def _ngon(path, sides, across, rotation=0.0) -> None:
    r = across * (HEXAGON if sides == 6 else math.sqrt(2.0)) / 2.0
    _poly(path, [(r * math.cos(rotation + 2 * math.pi * i / sides),
                  r * math.sin(rotation + 2 * math.pi * i / sides))
                 for i in range(sides)])


def _circle(path, d) -> None:
    path.addEllipse(QtCore.QPointF(0.0, 0.0), d / 2.0, d / 2.0)


def _ring(path, outer, inner, gap) -> None:
    """A retaining ring from above: a C."""
    half_o = math.degrees(math.asin(min(gap / outer, 0.9)))
    half_i = math.degrees(math.asin(min(gap / inner, 0.9)))
    ro, ri = outer, inner
    path.arcMoveTo(QtCore.QRectF(-ro, -ro, 2 * ro, 2 * ro), half_o)
    path.arcTo(QtCore.QRectF(-ro, -ro, 2 * ro, 2 * ro), half_o,
               360 - 2 * half_o)
    path.arcTo(QtCore.QRectF(-ri, -ri, 2 * ri, 2 * ri), -half_i,
               -(360 - 2 * half_i))
    path.closeSubpath()


def drawing(kind: str, dims: Dict[str, float],
            length: float = 0.0) -> Tuple[QtGui.QPainterPath, Box]:
    """The outline, in millimetres with Y up, and its box."""
    p = QtGui.QPainterPath()
    p.setFillRule(QtCore.Qt.OddEvenFill)
    d = dims.get("d", 0.0)
    L = length or max(3.0 * d, 1.0)
    dc, c = dims.get("dc", 0.0), dims.get("c", 0.0)
    shank = lambda top=0.0, bottom=None, dd=None: _rect(
        p, -(dd or d) / 2.0, bottom if bottom is not None else -L,
        (dd or d) / 2.0, top)
    try:
        if kind in ("hex_bolt", "square_bolt"):
            shank()
            e = dims["s"] * (HEXAGON if kind == "hex_bolt" else 1.0)
            z = 0.0
            if dc > 0 and c > 0:
                _rect(p, -dc / 2.0, 0.0, dc / 2.0, c)
                z = c
            _rect(p, -e / 2.0, z, e / 2.0, dims["k"])
            if kind == "hex_bolt":
                for x in (-dims["s"] / 2.0 * 0.5, dims["s"] / 2.0 * 0.5):
                    p.moveTo(x, z)
                    p.lineTo(x, dims["k"])
        elif kind in ("socket_head", "cheese"):
            shank()
            r, k = dims["dk"] / 2.0, dims["k"]
            e = 0.1 * k
            _poly(p, [(-r, 0), (r, 0), (r, k - e), (r - e, k), (-r + e, k),
                      (-r, k - e)])
        elif kind in ("dome", "pan"):
            shank()
            z = 0.0
            if dc > 0 and c > 0:
                _rect(p, -dc / 2.0, 0.0, dc / 2.0, c)
                z = c
            k = dims["k"]
            _dome(p, dims["dk"] / 2.0, z, (k - z) * (0.55 if kind == "pan"
                                                     else 0.12), k)
        elif kind == "countersunk":
            k, r = dims["k"], dims["dk"] / 2.0
            _poly(p, [(-d / 2.0, -k), (d / 2.0, -k), (r, 0.0), (-r, 0.0)])
            shank(-k, -L)
        elif kind == "shoulder":
            lt, k = dims["lt"], dims["k"]
            shank(0.0, -L, dims["d1"])
            shank(-L, -L - lt)
            _rect(p, -dims["dk"] / 2.0, 0.0, dims["dk"] / 2.0, k)
        elif kind == "set_screw":
            r = d / 2.0
            point = int(dims.get("point", 0))
            if point == 1:
                tip = min(r, 0.45 * L)
                _poly(p, [(-r, 0), (r, 0), (r, -(L - tip)), (0.1 * r, -L),
                          (-0.1 * r, -L), (-r, -(L - tip))])
            elif point == 2:
                z, dp = min(0.4 * d, 0.4 * L), 0.65 * d / 2.0
                _poly(p, [(-r, 0), (r, 0), (r, -(L - z)), (dp, -(L - z)),
                          (dp, -L), (-dp, -L), (-dp, -(L - z)),
                          (-r, -(L - z))])
            else:
                _rect(p, -r, -L, r, 0)
        elif kind in ("nut", "lock_nut", "cap_nut"):
            if dc > 0:
                _circle(p, dc)
            _ngon(p, 6, dims["s"])
            if kind != "cap_nut":
                _circle(p, d)
            else:
                _circle(p, min(dims.get("dk", d), dims["s"]))
        elif kind == "square_nut":
            _ngon(p, 4, dims["s"], math.pi / 4.0)
            _circle(p, d)
        elif kind == "washer":
            _circle(p, dims["d2"])
            _circle(p, dims["d1"])
        elif kind in ("pin", "rod", "spring_pin"):
            shank()
        elif kind == "taper_pin":
            r0, r1 = d / 2.0, d / 2.0 + L / 100.0
            _poly(p, [(-r0, 0), (r0, 0), (r1, -L), (-r1, -L)])
        elif kind == "headed_pin":
            shank()
            _rect(p, -dims["dk"] / 2.0, 0.0, dims["dk"] / 2.0, dims["k"])
        elif kind in ("ring_external", "ring_internal"):
            d3 = dims["d3"]
            width = (dims["a"] + dims["b"]) / 2.0
            if kind == "ring_external":
                inner, outer = d3 / 2.0, d3 / 2.0 + width
            else:
                inner, outer = d3 / 2.0 - width, d3 / 2.0
            _ring(p, outer, inner, 0.3 * d3 / 2.0)
        elif kind == "bearing":
            bore, D = dims["d"], dims["D"]
            w = (D - bore) * 0.18
            _circle(p, D)
            _circle(p, D - 2 * w)
            _circle(p, bore + 2 * w)
            _circle(p, bore)
    except (KeyError, ValueError, ZeroDivisionError):
        return QtGui.QPainterPath(), (0.0, 0.0, 0.0, 0.0)
    flipped = QtGui.QTransform().scale(1.0, -1.0).map(p)
    r = flipped.boundingRect()
    return flipped, (r.left(), -r.bottom(), r.right(), -r.top())


def icon(fam, size: int = 40) -> Optional[QtGui.QIcon]:
    """A size from the middle of a family's table, drawn."""
    from .profile_preview import _paint

    if not fam.rows:
        return None
    row = fam.rows[len(fam.rows) // 2]
    dims = {c: float(v) for c, v in zip(fam.columns, row[1:])}
    length = fam.default_length_for(str(row[0])) if fam.needs_length else 0
    path, box = drawing(fam.kind, dims, length)
    if path.isEmpty():
        return None
    ratio = 2.0
    picture = QtGui.QPixmap(int(size * ratio), int(size * ratio))
    picture.setDevicePixelRatio(ratio)
    picture.fill(QtCore.Qt.transparent)
    painter = QtGui.QPainter(picture)
    painter.setRenderHint(QtGui.QPainter.Antialiasing)
    _paint(painter, QtCore.QRectF(2, 2, size - 4, size - 4), path, box, 0.8)
    painter.end()
    return QtGui.QIcon(picture)
