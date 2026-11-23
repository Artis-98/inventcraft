"""A view of an assembly drawn again where a part changed, and only there.

Hidden lines cross parts: a bracket made longer can hide an edge of the
frame behind it, so a changed part has always meant the whole assembly
seen again, eight seconds a view on the walking excavator.  But what a
point on the paper shows depends only on what lands on that point.  A
part that changed lands only inside the box its old and new shapes make
on the paper, so outside that box nothing on the view can have changed,
and inside it only the parts that land there take any part in it.

So: the old lines are kept outside the box, the parts that land in the
box are seen again on their own, and their lines are kept inside it.
Joined at the edge of the box, the two make the view exactly as seeing
the whole assembly again would have, for a fraction of the work when
the change is small.  When it is not small, nothing here is used.

Which parts changed is found by looking, not by being told: every solid
of the old body and the new is given a fingerprint of where its corners
and the middles of its edges are, and a solid whose fingerprint is not
on the other side has moved or changed.
"""

from __future__ import annotations

import math
from collections import Counter
from typing import Dict, List, Optional, Sequence, Tuple

from OCP.BRepAdaptor import BRepAdaptor_Curve
from OCP.BRep import BRep_Builder, BRep_Tool
from OCP.TopAbs import TopAbs_EDGE, TopAbs_SOLID, TopAbs_VERTEX
from OCP.TopoDS import TopoDS, TopoDS_Compound

from . import hlr, kernel

# Past this share of the solids changed, the whole view is seen again:
# the box would cover most of it, and seeing part of it twice is waste.
MOST = 0.35
# what is too few solids to be worth it
FEWEST = 8

_PRINTS: Dict[int, Tuple] = {}


def _solids(shape) -> List:
    return list(kernel.explore(shape, TopAbs_SOLID))


def fingerprint(solid) -> Tuple:
    """Where a solid's corners and the middles of its edges are, to a
    micron, as one comparable thing."""
    # the same solid in the same place: OCCT's own hash of the shape
    key = hash(solid)
    held = _PRINTS.get(key)
    if held is not None and held[0].IsSame(solid):
        return held[1]
    marks = []
    for vertex in kernel.explore(solid, TopAbs_VERTEX):
        p = BRep_Tool.Pnt_s(TopoDS.Vertex_s(vertex))
        marks.append((round(p.X(), 3), round(p.Y(), 3), round(p.Z(), 3)))
    for edge in kernel.explore(solid, TopAbs_EDGE):
        try:
            curve = BRepAdaptor_Curve(TopoDS.Edge_s(edge))
            p = curve.Value(0.5 * (curve.FirstParameter()
                                   + curve.LastParameter()))
        except Exception:
            continue
        marks.append((round(p.X(), 3), round(p.Y(), 3), round(p.Z(), 3)))
    print_ = tuple(sorted(marks))
    if len(_PRINTS) > 20000:
        _PRINTS.clear()
    # the solid is kept with it, so its address cannot be handed to
    # another solid while the fingerprint is held
    _PRINTS[key] = (solid, print_)
    return print_


def changed(old_shape, new_shape):
    """(the old solids that are gone, the new solids that are new, every
    new solid), or None when either body is not a set of solids."""
    old, new = _solids(old_shape), _solids(new_shape)
    if not old or not new:
        return None
    old_prints = [fingerprint(s) for s in old]
    new_prints = [fingerprint(s) for s in new]
    left = Counter(old_prints)
    left.subtract(Counter(new_prints))
    gone = []
    want = Counter({k: n for k, n in left.items() if n > 0})
    for solid, mark in zip(old, old_prints):
        if want.get(mark, 0) > 0:
            gone.append(solid)
            want[mark] -= 1
    right = Counter(new_prints)
    right.subtract(Counter(old_prints))
    want = Counter({k: n for k, n in right.items() if n > 0})
    arrived = []
    for solid, mark in zip(new, new_prints):
        if want.get(mark, 0) > 0:
            arrived.append(solid)
            want[mark] -= 1
    return gone, arrived, new


def _paper_box(solid, frame) -> Optional[Tuple[float, float, float, float]]:
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib
    box = Bnd_Box()
    try:
        BRepBndLib.Add_s(solid, box, False)
    except Exception:
        return None
    if box.IsVoid():
        return None
    x0, y0, z0, x1, y1, z1 = box.Get()
    pts = [hlr.to_paper((x, y, z), frame)
           for x in (x0, x1) for y in (y0, y1) for z in (z0, z1)]
    return (min(p[0] for p in pts), min(p[1] for p in pts),
            max(p[0] for p in pts), max(p[1] for p in pts))


def _overlap(a, b) -> bool:
    return not (a[2] < b[0] or b[2] < a[0] or a[3] < b[1] or b[3] < a[1])


def plan(old_shape, new_shape, direction, up):
    """What redrawing part of a view would take: (the box on the paper,
    the solids to see again), or None when the whole view should be seen
    again instead."""
    found = changed(old_shape, new_shape)
    if found is None:
        return None
    gone, arrived, new = found
    if len(new) < FEWEST:
        return None
    if not gone and not arrived:
        return (None, [])            # nothing changed at all
    if len(gone) + len(arrived) > MOST * len(new):
        return None
    frame = hlr.camera(direction, up)
    boxes = [_paper_box(s, frame) for s in gone + arrived]
    if any(b is None for b in boxes):
        return None
    size = max(max(b[2] - b[0], b[3] - b[1]) for b in boxes)
    pad = 0.05 + size * 1e-3
    region = (min(b[0] for b in boxes) - pad, min(b[1] for b in boxes) - pad,
              max(b[2] for b in boxes) + pad, max(b[3] for b in boxes) + pad)
    involved = []
    for solid in new:
        b = _paper_box(solid, frame)
        if b is None or _overlap(b, region):
            involved.append(solid)
    if len(involved) > MOST * 2 * len(new):
        return None
    return region, involved


def redraw(old: hlr.Projection, new_shape, region, involved, direction, up,
           hidden: bool, tangents: bool) -> Optional[hlr.Projection]:
    """The view of ``new_shape``: ``old``'s lines outside ``region``, and
    the ``involved`` solids seen again inside it."""
    ox, oy = old.centre
    kept: List[hlr.Polyline] = []
    for line in old.lines:
        moved = [(x + ox, y + oy) for x, y in line.points]
        _keep(kept, line, moved, region, inside=False, shift=(ox, oy))
    if involved:
        builder = BRep_Builder()
        bunch = TopoDS_Compound()
        builder.MakeCompound(bunch)
        for solid in involved:
            builder.Add(bunch, solid)
        fresh = hlr.project(bunch, direction, up, hidden=hidden,
                            tangents=tangents)
        if not fresh.ok and fresh.error != \
                "nothing is visible from this direction":
            return None
        if fresh.ok:
            fx, fy = fresh.centre
            for line in fresh.lines:
                moved = [(x + fx, y + fy) for x, y in line.points]
                _keep(kept, line, moved, region, inside=True,
                      shift=(fx, fy))
    if not kept:
        return None
    xs = [p[0] for line in kept for p in line.points]
    ys = [p[1] for line in kept for p in line.points]
    cx = (min(xs) + max(xs)) / 2.0
    cy = (min(ys) + max(ys)) / 2.0
    for line in kept:
        line.moved(-cx, -cy)
    half_w = (max(xs) - min(xs)) / 2.0
    half_h = (max(ys) - min(ys)) / 2.0
    return hlr.Projection(lines=kept, centre=(cx, cy),
                          box=(-half_w, -half_h, half_w, half_h))


def _keep(out, line, points, region, inside: bool, shift) -> None:
    """The pieces of a line on one side of the region, in the frame's own
    coordinates.  A line wholly on that side is kept whole, arc and all."""
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    box = (min(xs), min(ys), max(xs), max(ys))
    whole_in = (box[0] >= region[0] and box[2] <= region[2]
                and box[1] >= region[1] and box[3] <= region[3])
    whole_out = not _overlap(box, region)
    if (inside and whole_in) or (not inside and whole_out):
        piece = hlr.Polyline(points, line.kind, line.group, None)
        piece.arc = hlr.arc_moved(line.arc, shift[0], shift[1])
        out.append(piece)
        return
    if (inside and whole_out) or (not inside and whole_in):
        return
    for part in split(points, region, inside):
        if len(part) >= 2:
            out.append(hlr.Polyline(part, line.kind, line.group))


def split(points: Sequence[Tuple[float, float]], region,
          inside: bool) -> List[List[Tuple[float, float]]]:
    """The runs of a polyline inside (or outside) a rectangle."""
    x0, y0, x1, y1 = region
    runs: List[List[Tuple[float, float]]] = []
    current: List[Tuple[float, float]] = []

    def flush():
        nonlocal current
        if len(current) >= 2:
            runs.append(current)
        current = []

    for a, b in zip(points, points[1:]):
        cuts = _crossings(a, b, x0, y0, x1, y1)
        ts = [0.0] + cuts + [1.0]
        for t0, t1 in zip(ts, ts[1:]):
            if t1 - t0 < 1e-12:
                continue
            tm = 0.5 * (t0 + t1)
            mid = (a[0] + (b[0] - a[0]) * tm, a[1] + (b[1] - a[1]) * tm)
            within = x0 <= mid[0] <= x1 and y0 <= mid[1] <= y1
            p = (a[0] + (b[0] - a[0]) * t0, a[1] + (b[1] - a[1]) * t0)
            q = (a[0] + (b[0] - a[0]) * t1, a[1] + (b[1] - a[1]) * t1)
            if within == inside:
                if not current or math.dist(current[-1], p) > 1e-12:
                    flush()
                    current = [p]
                current.append(q)
            else:
                flush()
    flush()
    return runs


def _crossings(a, b, x0, y0, x1, y1) -> List[float]:
    """Where along a to b (0 to 1) it crosses the rectangle's sides."""
    out = []
    dx, dy = b[0] - a[0], b[1] - a[1]
    for edge, d, start in ((x0, dx, a[0]), (x1, dx, a[0]),
                           (y0, dy, a[1]), (y1, dy, a[1])):
        if abs(d) < 1e-15:
            continue
        t = (edge - start) / d
        if 0.0 < t < 1.0:
            out.append(t)
    return sorted(out)
