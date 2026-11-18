"""Bolts, screws, nuts, washers, pins, rings and bearings as ordinary
parts, the way Inventor's Content Center draws them: the true outline and
drive, no thread.

Every one is sketches and features a person could have made: round parts
are a half section revolved about Z, heads and nuts with flats are
extruded, the drive is cut into the top.  Its sizes go into the part's
parameters, and the length is the parameter L wherever a length is
extruded, so it can be changed in the part as well as through Change
Size.

The head sits on the XY plane and the shank runs down -Z, so it drops
onto a face head up.  A countersunk head is below the plane, its top
flush with it, as it sits in its countersink.
"""
from __future__ import annotations

import math
from typing import Dict, List, Sequence, Tuple

from .document import Document
from .features import (CUT, JOIN, ExtrudeFeature, RevolveFeature,
                       SketchFeature)
from .sketch import Sketch, SketchPlane

HEXAGON = 2.0 / math.sqrt(3.0)          # across corners over across flats


def _xy(z: float) -> SketchPlane:
    return SketchPlane((0.0, 0.0, z), (0.0, 0.0, 1.0), (1.0, 0.0, 0.0),
                       name="XY Plane")


def _xz() -> SketchPlane:
    """A plane through the Z axis, its x along Z and its y outwards, for
    half sections: a point (z, r) is at height z, radius r."""
    return SketchPlane((0.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0),
                       name="XZ Plane")


class _Builder:
    def __init__(self, doc: Document) -> None:
        self.doc = doc

    def _sketch(self, name: str, sketch: Sketch) -> SketchFeature:
        feature = SketchFeature(name=name)
        feature.sketch = sketch
        self.doc.add_feature(feature)
        return feature

    def extrude(self, name: str, sketch: Sketch, distance: str,
                operation: str = JOIN, down: bool = False) -> None:
        feature = self._sketch(name + " Sketch", sketch)
        solid = ExtrudeFeature(name=name)
        solid.sketch_id = feature.id
        solid.distance = distance
        solid.operation = operation
        solid.reversed = down
        self.doc.add_feature(solid)

    def revolve(self, name: str, points: Sequence[Tuple[float, float]],
                arcs: Sequence[Tuple] = (), operation: str = JOIN) -> None:
        """A half section revolved about Z: ``points`` (z, r) in order
        round the outline, a line between each and the next unless
        ``arcs`` has (i, centre_z, radius) for the step from point i, an
        arc about a centre on the axis."""
        sketch = Sketch(_xz(), name + " Sketch")
        bent = {a[0]: a for a in arcs}
        n = len(points)
        for i in range(n):
            p, q = points[i], points[(i + 1) % n]
            if i in bent:
                _i, cz, radius = bent[i]
                a0 = math.atan2(p[1], p[0] - cz)
                a1 = math.atan2(q[1], q[0] - cz)
                lo, hi = sorted((a0, a1))
                sketch.add_arc((cz, 0.0), radius, lo, hi)
            else:
                sketch.add_line(p, q)
        feature = self._sketch(name + " Sketch", sketch)
        solid = RevolveFeature(name=name)
        solid.sketch_id = feature.id
        solid.axis = "X"
        solid.operation = operation
        self.doc.add_feature(solid)

    def outline(self, name: str, z: float, points: Sequence[Tuple[float,
                                                                  float]],
                depth: str, operation: str = CUT, down: bool = True) -> None:
        sketch = Sketch(_xy(z), name + " Sketch")
        n = len(points)
        for i in range(n):
            sketch.add_line(points[i], points[(i + 1) % n])
        self.extrude(name, sketch, depth, operation, down)


# ----------------------------------------------------------- the drives

def _star(s: float) -> List[Tuple[float, float]]:
    """A six lobed socket, as a twelve pointed outline: ``s`` across its
    points."""
    out = []
    for i in range(12):
        r = s / 2.0 if i % 2 == 0 else s / 2.0 * 0.72
        a = math.pi * i / 6.0
        out.append((r * math.cos(a), r * math.sin(a)))
    return out


def _cross(s: float) -> List[Tuple[float, float]]:
    """A cross recess: two arms ``s`` long, a fifth of that wide."""
    a, w = s / 2.0, s / 10.0
    return [(a, w), (w, w), (w, a), (-w, a), (-w, w), (-a, w), (-a, -w),
            (-w, -w), (-w, -a), (w, -a), (w, -w), (a, -w)]


def _slot(width: float, across: float) -> List[Tuple[float, float]]:
    a, w = across / 2.0, width / 2.0
    return [(a, w), (-a, w), (-a, -w), (a, -w)]


def drive(b: _Builder, kind: str, dims: Dict[str, float], top: float,
          across: float) -> None:
    """The drive cut into a head whose top is at ``top``."""
    s, t = dims.get("s", 0.0), dims.get("t", 0.0)
    if not kind or s <= 0 or t <= 0:
        return
    if kind == "hex":
        sketch = Sketch(_xy(top), "Socket Sketch")
        sketch.add_polygon((0.0, 0.0), s * HEXAGON / 2.0, 6)
        b.extrude("Socket", sketch, "%g" % t, CUT, down=True)
    elif kind == "torx":
        b.outline("Socket", top, _star(s), "%g" % t)
    elif kind == "cross":
        b.outline("Recess", top, _cross(s), "%g" % t)
    elif kind == "slot":
        b.outline("Slot", top, _slot(s, across + 2.0), "%g" % t)


# ---------------------------------------------------------- the pieces

def _shank(b: _Builder, d: float, z: float = 0.0,
           length: str = "L") -> None:
    sketch = Sketch(_xy(z), "Shank Sketch")
    sketch.add_circle((0.0, 0.0), d / 2.0)
    b.extrude("Shank", sketch, length, JOIN, down=True)


def _prism(b: _Builder, name: str, sides: int, across: float,
           height: float, z: float = 0.0, hole: float = 0.0) -> None:
    sketch = Sketch(_xy(z), name + " Sketch")
    if sides == 4:
        sketch.add_polygon((0.0, 0.0), across * math.sqrt(2.0) / 2.0, 4,
                           rotation=math.pi / 4.0)
    else:
        sketch.add_polygon((0.0, 0.0), across * HEXAGON / 2.0, 6)
    if hole > 0:
        sketch.add_circle((0.0, 0.0), hole / 2.0)
    b.extrude(name, sketch, "%g" % height, JOIN)


def _disc(b: _Builder, name: str, outer: float, height: float,
          z: float = 0.0, hole: float = 0.0) -> None:
    sketch = Sketch(_xy(z), name + " Sketch")
    sketch.add_circle((0.0, 0.0), outer / 2.0)
    if hole > 0:
        sketch.add_circle((0.0, 0.0), hole / 2.0)
    b.extrude(name, sketch, "%g" % height, JOIN)


def _dome(b: _Builder, name: str, z0: float, dk: float, side: float,
          top: float) -> None:
    """A round topped head from ``z0``: straight for ``side``, then a
    spherical cap up to ``top`` on the axis."""
    r = dk / 2.0
    rise = max(top - (z0 + side), 1e-3)
    radius = (r * r + rise * rise) / (2.0 * rise)
    cz = top - radius
    if side > 1e-3:
        b.revolve(name, [(z0, 0.0), (z0, r), (z0 + side, r), (top, 0.0)],
                  arcs=[(2, cz, radius)])
    else:
        b.revolve(name, [(z0, 0.0), (z0, r), (top, 0.0)],
                  arcs=[(1, cz, radius)])


def _hole(b: _Builder, d: float, top: float, depth: float,
          down: bool = True) -> None:
    sketch = Sketch(_xy(top), "Hole Sketch")
    sketch.add_circle((0.0, 0.0), d / 2.0)
    b.extrude("Hole", sketch, "%g" % depth, CUT, down=down)


# ---------------------------------------------------------- the kinds

def build(doc: Document, kind: str, drive_kind: str,
          dims: Dict[str, float], length: float) -> None:
    b = _Builder(doc)
    d = dims.get("d", 0.0)
    dc, c = dims.get("dc", 0.0), dims.get("c", 0.0)

    if kind in ("hex_bolt", "square_bolt"):
        _shank(b, d)
        if dc > 0 and c > 0:
            _disc(b, "Flange", dc, c)
        _prism(b, "Head", 4 if kind == "square_bolt" else 6, dims["s"],
               dims["k"])
    elif kind == "socket_head":
        _shank(b, d)
        k, r = dims["k"], dims["dk"] / 2.0
        e = min(0.08 * dims["dk"], k * 0.2)
        b.revolve("Head", [(0.0, 0.0), (0.0, r), (k - e, r), (k, r - e),
                           (k, 0.0)])
        drive(b, drive_kind, dims, k, dims["dk"])
    elif kind in ("dome", "pan"):
        _shank(b, d)
        z = 0.0
        if dc > 0 and c > 0:
            _disc(b, "Collar", dc, c)
            z = c
        k = dims["k"]
        side = (k - z) * (0.55 if kind == "pan" else 0.12)
        _dome(b, "Head", z, dims["dk"], side, k)
        drive(b, drive_kind, dims, k, dims["dk"])
    elif kind == "cheese":
        _shank(b, d)
        k, r = dims["k"], dims["dk"] / 2.0
        e = 0.1 * k
        b.revolve("Head", [(0.0, 0.0), (0.0, r), (k - e, r), (k, r - e),
                           (k, 0.0)])
        drive(b, drive_kind, dims, k, dims["dk"])
    elif kind == "countersunk":
        k, r = dims["k"], dims["dk"] / 2.0
        b.revolve("Head", [(-k, 0.0), (-k, d / 2.0), (0.0, r), (0.0, 0.0)])
        _shank(b, d, -k, "L - %g" % k)
        drive(b, drive_kind, dims, 0.0, dims["dk"])
    elif kind == "shoulder":
        # L is the shoulder; the thread goes on below it
        lt, k = dims["lt"], dims["k"]
        _shank(b, dims["d1"])
        _shank(b, d, -length, "%g" % lt)
        b.revolve("Head", [(0.0, 0.0), (0.0, dims["dk"] / 2.0),
                           (k, dims["dk"] / 2.0), (k, 0.0)])
        drive(b, drive_kind, dims, k, dims["dk"])
    elif kind == "set_screw":
        r, L = d / 2.0, length
        point = int(dims.get("point", 0))
        e = min(0.15 * d, 0.3 * L)
        top = [(0.0, 0.0), (0.0, r - e), (-e, r)]
        if point == 1:          # cone
            tip = min(r, 0.45 * L)
            body = [(-(L - tip), r), (-L, 0.1 * r)]
        elif point == 2:        # dog
            dp, z = 0.65 * d, min(0.4 * d, 0.4 * L)
            body = [(-(L - z), r), (-(L - z), dp / 2.0), (-L, dp / 2.0)]
        else:                   # flat and cup
            body = [(-(L - e), r), (-L, r - e)]
        b.revolve("Screw", top + body + [(-L, 0.0)])
        drive(b, drive_kind, dims, 0.0, d)
    elif kind == "nut":
        m = dims["m"]
        if dc > 0 and c > 0:
            _disc(b, "Flange", dc, c)
        _prism(b, "Nut", 6, dims["s"], m)
        _hole(b, d, m, m)
    elif kind == "lock_nut":
        m, h = dims["m"], dims["h"]
        if dc > 0 and c > 0:
            _disc(b, "Flange", dc, c)
        _prism(b, "Nut", 6, dims["s"], m)
        if h > m:
            _disc(b, "Collar", min(dims.get("dw", dims["s"]), dims["s"]),
                  h - m, z=m)
        _hole(b, d, h, h)
    elif kind == "cap_nut":
        m, h, dk = dims["m"], dims["h"], dims["dk"]
        _prism(b, "Nut", 6, dims["s"], m)
        _dome(b, "Cap", m, min(dk, dims["s"]), 0.0, h)
        _hole(b, d, 0.0, m + 0.4 * (h - m), down=False)
    elif kind == "square_nut":
        m = dims["m"]
        _prism(b, "Nut", 4, dims["s"], m, hole=d)
    elif kind == "washer":
        _disc(b, "Washer", dims["d2"], dims["h"], hole=dims["d1"])
    elif kind in ("pin", "rod"):
        _shank(b, d)
    elif kind == "taper_pin":
        r0, L = d / 2.0, length
        r1 = r0 + L / 100.0                  # 1:50 on the diameter
        b.revolve("Pin", [(0.0, 0.0), (0.0, r0), (-L, r1), (-L, 0.0)])
    elif kind == "headed_pin":
        _shank(b, d)
        _disc(b, "Head", dims["dk"], dims["k"])
    elif kind == "spring_pin":
        r, s = d / 2.0, dims["s"]
        gap = max(0.25 * d, s)
        half = math.asin(min(gap / 2.0 / r, 0.9))
        sketch = Sketch(_xy(0.0), "Pin Sketch")
        sketch.add_arc((0.0, 0.0), r, half, 2 * math.pi - half)
        sketch.add_arc((0.0, 0.0), r - s, half, 2 * math.pi - half)
        for a in (half, -half):
            sketch.add_line((r * math.cos(a), r * math.sin(a)),
                            ((r - s) * math.cos(a), (r - s) * math.sin(a)))
        b.extrude("Pin", sketch, "L", JOIN, down=True)
    elif kind in ("ring_external", "ring_internal"):
        d3, s = dims["d3"], dims["s"]
        width = (dims["a"] + dims["b"]) / 2.0
        if kind == "ring_external":
            inner, outer = d3 / 2.0, d3 / 2.0 + width
        else:
            inner, outer = d3 / 2.0 - width, d3 / 2.0
        gap = 0.3 * d3 / 2.0
        half = math.asin(min(gap / outer, 0.9))
        half_in = math.asin(min(gap / inner, 0.9))
        sketch = Sketch(_xy(0.0), "Ring Sketch")
        sketch.add_arc((0.0, 0.0), outer, half, 2 * math.pi - half)
        sketch.add_arc((0.0, 0.0), inner, half_in, 2 * math.pi - half_in)
        for a_out, a_in in ((half, half_in), (-half, -half_in)):
            sketch.add_line((outer * math.cos(a_out), outer * math.sin(a_out)),
                            (inner * math.cos(a_in), inner * math.sin(a_in)))
        b.extrude("Ring", sketch, "%g" % s, JOIN)
    elif kind == "bearing":
        bore, D, B = dims["d"], dims["D"], dims["B"]
        w = (D - bore) * 0.18
        e = B * 0.12
        ri, ro = bore / 2.0, D / 2.0
        b.revolve("Bearing", [
            (0.0, ri), (0.0, ri + w), (e, ri + w), (e, ro - w), (0.0, ro - w),
            (0.0, ro), (B, ro), (B, ro - w), (B - e, ro - w), (B - e, ri + w),
            (B, ri + w), (B, ri)])
    else:
        raise ValueError("no way to draw a %s yet" % kind)
