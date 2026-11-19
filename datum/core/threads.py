"""Threads, cosmetic as Inventor draws them: the part's solid is left as it
is, and the thread is a picture over the face it is on.

A thread is put on a round face, a shaft (external) or a hole (internal).
Its size is matched to the face: a 16 mm face is M16.  The size can be
changed, or set to Custom with any diameter, for tube that is not exactly
a standard size and has to be tapped anyway; the pitch and the hand (right
or left) are the user's to choose.

What a thread needs to be drawn is kept as marks: where its axis is, its
radius, from where to where along it, its pitch and hand, and whether it
is inside or out.  A part's Thread features write them when they build,
so an assembly can draw its parts' threads from their files without
building them.

The sizes are ISO 261's metric threads, coarse and fine, and ISO 228's
G (BSP) pipe threads, typed in from the standards.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

METRIC = "ISO Metric"
PIPE = "G (BSP) Pipe"
CUSTOM = "Custom"

# ISO 261: nominal diameter, coarse pitch, the usual fine pitches
ISO_261 = [
    (1.6, 0.35, ()), (2, 0.4, (0.25,)), (2.5, 0.45, (0.35,)),
    (3, 0.5, (0.35,)), (4, 0.7, (0.5,)), (5, 0.8, (0.5,)),
    (6, 1.0, (0.75,)), (8, 1.25, (1.0, 0.75)), (10, 1.5, (1.25, 1.0)),
    (12, 1.75, (1.5, 1.25)), (14, 2.0, (1.5,)), (16, 2.0, (1.5,)),
    (18, 2.5, (2.0, 1.5)), (20, 2.5, (2.0, 1.5)), (22, 2.5, (2.0, 1.5)),
    (24, 3.0, (2.0, 1.5)), (27, 3.0, (2.0,)), (30, 3.5, (2.0,)),
    (33, 3.5, (2.0,)), (36, 4.0, (3.0,)), (39, 4.0, (3.0,)),
    (42, 4.5, (3.0,)), (45, 4.5, (3.0,)), (48, 5.0, (3.0,)),
    (52, 5.0, (4.0,)), (56, 5.5, (4.0,)), (60, 5.5, (4.0,)),
    (64, 6.0, (4.0,)),
]
# ISO 228-1: size, major diameter (mm), threads per inch
ISO_228 = [
    ("1/8", 9.728, 28), ("1/4", 13.157, 19), ("3/8", 16.662, 19),
    ("1/2", 20.955, 14), ("5/8", 22.911, 14), ("3/4", 26.441, 14),
    ("7/8", 30.201, 14), ("1", 33.249, 11), ("1-1/4", 41.910, 11),
    ("1-1/2", 47.803, 11), ("2", 59.614, 11), ("2-1/2", 75.184, 11),
    ("3", 87.884, 11), ("4", 113.030, 11),
]


@dataclass
class Size:
    standard: str
    designation: str          # M16, M16x1.5, G1/2, or Custom
    diameter: float           # nominal (major) diameter, mm
    pitch: float              # mm
    pitches: Tuple[float, ...] = ()


def sizes(standard: str) -> List[Size]:
    if standard == METRIC:
        return [Size(METRIC, "M%g" % d, float(d), p, (p,) + tuple(f))
                for d, p, f in ISO_261]
    if standard == PIPE:
        return [Size(PIPE, "G%s" % n, dia, round(25.4 / tpi, 4),
                     (round(25.4 / tpi, 4),)) for n, dia, tpi in ISO_228]
    return []


def designation(size: Size, pitch: float) -> str:
    """M16 with its coarse pitch, M16x1.5 with a fine one."""
    if size.standard == METRIC and size.pitches and \
            abs(pitch - size.pitches[0]) > 1e-6:
        return "%sx%g" % (size.designation, pitch)
    return size.designation


def match(diameter: float, standard: str = METRIC,
          tolerance: float = 0.03) -> Size:
    """The standard size a face of ``diameter`` takes: the nearest, or
    Custom at that diameter when none is within ``tolerance`` of it."""
    best = min(sizes(standard), key=lambda s: abs(s.diameter - diameter),
               default=None)
    if best is not None and abs(best.diameter - diameter) \
            <= tolerance * max(best.diameter, 1.0):
        return best
    return Size(CUSTOM, CUSTOM, float(diameter), default_pitch(diameter),
                (default_pitch(diameter),))


def default_pitch(diameter: float) -> float:
    """A custom diameter's pitch to start from: the coarse pitch of the
    metric size nearest it."""
    nearest = min(ISO_261, key=lambda row: abs(row[0] - diameter))
    return nearest[1]


# ---------------------------------------------------------------- marks

@dataclass
class Mark:
    """One thread as it is drawn, in the part's coordinates."""
    origin: Tuple[float, float, float]     # on the axis, where it starts
    axis: Tuple[float, float, float]       # unit, the way it runs
    radius: float                          # the face's radius
    length: float
    pitch: float
    internal: bool = False
    left_hand: bool = False

    def to_list(self) -> List[float]:
        return list(self.origin) + list(self.axis) + [
            self.radius, self.length, self.pitch,
            1.0 if self.internal else 0.0, 1.0 if self.left_hand else 0.0]

    @classmethod
    def from_list(cls, v: Sequence[float]) -> "Mark":
        return cls(tuple(v[0:3]), tuple(v[3:6]), v[6], v[7], v[8],
                   v[9] > 0.5, v[10] > 0.5)


def mark_for_face(face, start_offset: float = 0.0,
                  length: Optional[float] = None, pitch: float = 1.0,
                  left_hand: bool = False) -> Optional[Mark]:
    """The thread's mark on a cylindrical face: its axis, its radius,
    where it runs along the axis, inside or out; None for a face that is
    not a cylinder."""
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_SurfaceType
    from OCP.TopAbs import TopAbs_REVERSED
    from OCP.TopoDS import TopoDS
    f = TopoDS.Face_s(face)
    surf = BRepAdaptor_Surface(f)
    if surf.GetType() != GeomAbs_SurfaceType.GeomAbs_Cylinder:
        return None
    cyl = surf.Cylinder()
    ax = cyl.Axis()
    o, d = ax.Location(), ax.Direction()
    o = (o.X(), o.Y(), o.Z())
    d = (d.X(), d.Y(), d.Z())
    r = cyl.Radius()
    # how far along the axis the face reaches: its points' projections
    from OCP.BRepTools import BRepTools
    u0, u1, v0, v1 = BRepTools.UVBounds_s(f)
    ts = []
    for u in (u0, (u0 + u1) / 2.0, u1):
        for v in (v0, v1):
            p = surf.Value(u, v)
            ts.append(sum((c - oc) * dc for c, oc, dc in
                          zip((p.X(), p.Y(), p.Z()), o, d)))
    t0, t1 = min(ts), max(ts)
    # inside or out: the face's outward side points to the axis for a hole
    um, vm = (u0 + u1) / 2.0, (v0 + v1) / 2.0
    from OCP.gp import gp_Pnt, gp_Vec
    p, du, dv = gp_Pnt(), gp_Vec(), gp_Vec()
    surf.D1(um, vm, p, du, dv)
    n = du.Crossed(dv)
    if f.Orientation() == TopAbs_REVERSED:
        n.Reverse()
    t = sum((c - oc) * dc for c, oc, dc in zip((p.X(), p.Y(), p.Z()), o, d))
    on_axis = [oc + dc * t for oc, dc in zip(o, d)]
    radial = (p.X() - on_axis[0], p.Y() - on_axis[1], p.Z() - on_axis[2])
    internal = (n.X() * radial[0] + n.Y() * radial[1] + n.Z() * radial[2]) < 0
    span = t1 - t0
    start = t0 + max(0.0, min(start_offset, span))
    run = span - (start - t0) if length is None else \
        max(0.0, min(length, t1 - start))
    return Mark(tuple(oc + dc * start for oc, dc in zip(o, d)), d, r, run,
                pitch, internal, left_hand)


def helix(mark: Mark, per_turn: int = 18):
    """The mark drawn: a helix on the face, a hair off it so it is not
    lost in the surface, at the thread's pitch and hand; and a ring at
    each end."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakePolygon
    from OCP.gp import gp_Pnt
    d = mark.axis
    # two directions square to the axis
    a = (1.0, 0.0, 0.0) if abs(d[0]) < 0.9 else (0.0, 1.0, 0.0)
    u = _unit(_sub(a, _mul(d, _dot(a, d))))
    v = _cross(d, u)
    lift = max(0.02, mark.radius * 0.006)
    r = mark.radius - lift if mark.internal else mark.radius + lift
    turns = mark.length / mark.pitch if mark.pitch > 0 else 0.0
    steps = max(2, int(turns * per_turn))
    hand = -1.0 if mark.left_hand else 1.0
    poly = BRepBuilderAPI_MakePolygon()
    for k in range(steps + 1):
        t = k / steps
        ang = hand * 2 * math.pi * turns * t
        along = mark.length * t
        c, s = math.cos(ang), math.sin(ang)
        p = [mark.origin[i] + d[i] * along + r * (c * u[i] + s * v[i])
             for i in range(3)]
        poly.Add(gp_Pnt(*p))
    out = [poly.Wire()]
    for along in (0.0, mark.length):
        ring = BRepBuilderAPI_MakePolygon()
        for k in range(49):
            ang = 2 * math.pi * k / 48
            c, s = math.cos(ang), math.sin(ang)
            ring.Add(gp_Pnt(*[mark.origin[i] + d[i] * along
                              + r * (c * u[i] + s * v[i])
                              for i in range(3)]))
        out.append(ring.Wire())
    return out


def _sub(a, b):
    return tuple(a[i] - b[i] for i in range(3))


def _mul(a, k):
    return tuple(c * k for c in a)


def _dot(a, b):
    return sum(a[i] * b[i] for i in range(3))


def _unit(a):
    n = math.sqrt(_dot(a, a)) or 1.0
    return tuple(c / n for c in a)


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def marks_of(document) -> List[Mark]:
    """Every thread on a part, from its Thread features as last built."""
    out = []
    for f in getattr(document, "features", []):
        if getattr(f, "type_name", "") == "thread" and not f.suppressed:
            out += [Mark.from_list(m) for m in getattr(f, "marks", [])]
    return out


def marks_in_file(path: str) -> List[Mark]:
    """A part file's threads, read from it without building it."""
    from . import fileformat
    try:
        features = (fileformat.read(path).geometry or {}).get("features", [])
    except Exception:  # noqa: BLE001
        return []
    out = []
    for f in features:
        if isinstance(f, dict) and f.get("type") == "thread" \
                and not f.get("suppressed"):
            out += [Mark.from_list(m) for m in f.get("marks", [])]
    return out
