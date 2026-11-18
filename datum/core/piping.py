"""Piping: tube runs along a skeleton's lines, bent at the corners.

A pipe is a frame member whose family is of kind ``pipe`` (columns d, t
and r, the outside diameter, the wall and the bend radius a size is
usually bent to).  Where a member of any other kind is one straight
line, a pipe takes the picked lines as runs: lines meeting end to end
become one pipe, bent at each corner to its bend radius, so one run is
one part, one piece of tube to cut.  A corner where three or more lines
meet ends the runs there, which is where a tee will go.

Insulation is a property of the run: a thickness and a material.  It is
a part of its own beside the tube, swept along the same path, so it
follows the bends and comes in the BOM as what it is.

Everything here is in the member part's own coordinates: the run starts
at the origin and its first leg runs up Z, as a straight member's does.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import kernel
from .kernel import KernelError

TOL = 1e-6
INSULATION_MATERIAL = "Elastomeric Foam"


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _add(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _mul(a, k):
    return (a[0] * k, a[1] * k, a[2] * k)


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _len(a):
    return math.sqrt(_dot(a, a))


def _unit(a):
    n = _len(a) or 1.0
    return (a[0] / n, a[1] / n, a[2] / n)


def _key(p, tol: float = 1e-4):
    return tuple(round(c / tol) for c in p)


# ------------------------------------------------------------ the runs

def runs(lines: Dict[int, Tuple[Any, Any]], ids: Sequence[int]
         ) -> List[List[int]]:
    """The picked lines grouped into runs: lines that meet end to end,
    each in the order it is walked.  A point where three or more picked
    lines meet ends every run there."""
    ids = [i for i in dict.fromkeys(ids) if i in lines]
    at: Dict[Any, List[int]] = {}
    for i in ids:
        for p in lines[i]:
            at.setdefault(_key(p), []).append(i)
    left = list(ids)
    out: List[List[int]] = []

    def walk(first: int, start_key) -> List[int]:
        run, here, line = [first], start_key, first
        left.remove(first)
        while True:
            a, b = lines[line]
            here = _key(b) if _key(a) == here else _key(a)
            nxt = [j for j in at.get(here, []) if j != line]
            if len(at.get(here, [])) != 2 or not nxt or nxt[0] not in left:
                return run
            line = nxt[0]
            run.append(line)
            left.remove(line)

    # start at the free ends and the branch points first, in pick order
    for i in ids:
        if i not in left:
            continue
        for p in lines[i]:
            if len(at[_key(p)]) != 2 and i in left:
                out.append(walk(i, _key(p)))
    # what is left is closed loops: start anywhere
    while left:
        i = left[0]
        out.append(walk(i, _key(lines[i][0])))
    return out


def run_points(lines: Dict[int, Tuple[Any, Any]], ids: Sequence[int]
               ) -> List[Tuple[float, float, float]]:
    """A run's corner points in order, from one end to the other; legs
    running on in one straight line are one leg."""
    if not ids:
        raise KernelError("a pipe needs at least one line")
    for i in ids:
        if i not in lines:
            raise KernelError("a line it runs along is gone from the "
                              "skeleton")
    if len(ids) == 1:
        pts = [tuple(map(float, p)) for p in lines[ids[0]]]
    else:
        a0, b0 = lines[ids[0]]
        a1, b1 = lines[ids[1]]
        # the first line's far end is the one the second does not touch
        shared = [p for p in (a0, b0) if any(math.dist(p, q) < 1e-4
                                             for q in (a1, b1))]
        if not shared:
            raise KernelError("the lines of a pipe must meet end to end")
        start = b0 if shared[0] is a0 else a0
        pts = [tuple(map(float, start))]
        here = shared[0]
        pts.append(tuple(map(float, here)))
        for i in ids[1:]:
            a, b = lines[i]
            if math.dist(a, here) < 1e-4:
                here = b
            elif math.dist(b, here) < 1e-4:
                here = a
            else:
                raise KernelError("the lines of a pipe must meet end to end")
            pts.append(tuple(map(float, here)))
    # drop points in the middle of a straight leg
    out = [pts[0]]
    for i in range(1, len(pts) - 1):
        u = _unit(_sub(pts[i], out[-1]))
        v = _unit(_sub(pts[i + 1], pts[i]))
        if _len(_sub(pts[i], out[-1])) < TOL:
            continue
        if _dot(u, v) > 1 - 1e-9:
            continue
        out.append(pts[i])
    out.append(pts[-1])
    if any(_len(_sub(b, a)) < TOL for a, b in zip(out, out[1:])):
        raise KernelError("a leg of the pipe has no length")
    return out


# ------------------------------------------------------------ the bends

@dataclass
class Bend:
    corner: int            # which point of the run it is at
    angle: float           # degrees turned, 90 for a right angle
    radius: float
    setback: float         # from the corner to where the bend starts
    arc: float             # the length of tube in the bend


@dataclass
class Route:
    """A run worked out: its points, the bends at its corners and the
    straight lengths between them."""
    points: List[Tuple[float, float, float]]
    radius: float
    bends: List[Bend] = field(default_factory=list)
    straights: List[float] = field(default_factory=list)

    @property
    def length(self) -> float:
        """The developed length: the straight tube and the bends' arcs,
        what it takes to make the run from one piece."""
        return sum(self.straights) + sum(b.arc for b in self.bends)


def route(points: Sequence[Sequence[float]], radius: float) -> Route:
    """A run's bends at ``radius`` (to the tube's centre line) and the
    straight tube left between them; an error when a leg is too short
    for the bends at its two ends."""
    pts = [tuple(float(c) for c in p) for p in points]
    out = Route(points=pts, radius=radius)
    setbacks = [0.0] * len(pts)
    for i in range(1, len(pts) - 1):
        u = _unit(_sub(pts[i], pts[i - 1]))
        v = _unit(_sub(pts[i + 1], pts[i]))
        turn = math.acos(max(-1.0, min(1.0, _dot(u, v))))
        if turn > math.radians(179.0):
            raise KernelError("the pipe turns back on itself at corner %d"
                              % i)
        if radius <= 0:
            raise KernelError("a bend needs a radius more than 0")
        setback = radius * math.tan(turn / 2.0)
        setbacks[i] = setback
        out.bends.append(Bend(corner=i, angle=math.degrees(turn),
                              radius=radius, setback=setback,
                              arc=radius * turn))
    for i in range(len(pts) - 1):
        leg = _len(_sub(pts[i + 1], pts[i]))
        straight = leg - setbacks[i] - setbacks[i + 1]
        if straight < -1e-6:
            need = setbacks[i] + setbacks[i + 1]
            raise KernelError(
                "leg %d is %.1f mm, too short for its bends at %.0f mm "
                "radius: they need %.1f mm. Make the radius smaller or the "
                "leg longer" % (i + 1, leg, radius, need))
        out.straights.append(max(0.0, straight))
    return out


def path_wire(r: Route):
    """The run's centre line as one wire: straight legs and tangent arcs."""
    from OCP.BRepBuilderAPI import (BRepBuilderAPI_MakeEdge,
                                    BRepBuilderAPI_MakeWire)
    from OCP.GC import GC_MakeArcOfCircle
    from OCP.gp import gp_Pnt
    pts = r.points
    mk = BRepBuilderAPI_MakeWire()
    setback = {b.corner: b.setback for b in r.bends}
    here = pts[0]
    for i in range(1, len(pts)):
        u = _unit(_sub(pts[i], pts[i - 1]))
        if i < len(pts) - 1:
            stop = _sub(pts[i], _mul(u, setback[i]))
        else:
            stop = pts[i]
        if _len(_sub(stop, here)) > 1e-7:
            mk.Add(BRepBuilderAPI_MakeEdge(gp_Pnt(*here),
                                           gp_Pnt(*stop)).Edge())
        if i < len(pts) - 1:
            v = _unit(_sub(pts[i + 1], pts[i]))
            out = _add(pts[i], _mul(v, setback[i]))
            # the arc's middle: from the corner toward the bend's centre
            inward = _unit(_sub(v, u))
            half = math.acos(max(-1.0, min(1.0, _dot(u, v)))) / 2.0
            centre = _add(pts[i], _mul(inward, r.radius / math.cos(half)))
            mid = _add(centre, _mul(_unit(_sub(pts[i], centre)), r.radius))
            arc = GC_MakeArcOfCircle(gp_Pnt(*stop), gp_Pnt(*mid),
                                     gp_Pnt(*out)).Value()
            mk.Add(BRepBuilderAPI_MakeEdge(arc).Edge())
            here = out
        else:
            here = stop
    if not mk.IsDone():
        raise KernelError("the pipe's path did not join up")
    return mk.Wire()


def _annulus(points, d: float, t: float):
    """The tube's section where the run starts, square to its first leg."""
    from OCP.BRepBuilderAPI import (BRepBuilderAPI_MakeEdge,
                                    BRepBuilderAPI_MakeFace,
                                    BRepBuilderAPI_MakeWire)
    from OCP.gp import gp_Ax2, gp_Circ, gp_Dir, gp_Pnt
    if not (t > 0 and 2 * t < d):
        raise KernelError("a tube needs a wall thinner than its radius")
    p0 = points[0]
    n = _unit(_sub(points[1], points[0]))
    ax = gp_Ax2(gp_Pnt(*p0), gp_Dir(*n))

    def circle(dia):
        edge = BRepBuilderAPI_MakeEdge(gp_Circ(ax, dia / 2.0)).Edge()
        return BRepBuilderAPI_MakeWire(edge).Wire()

    mk = BRepBuilderAPI_MakeFace(circle(d), True)
    inner = circle(d - 2 * t)
    inner.Reverse()
    mk.Add(inner)
    return mk.Face()


def tube_solid(points, d: float, t: float, radius: float):
    """A tube of outside diameter ``d`` and wall ``t`` along the run,
    bent at ``radius``."""
    if len(points) > 2 and radius <= d / 2.0 + 1e-6:
        raise KernelError("the bend radius must be more than the tube's "
                          "outside radius, %.1f mm" % (d / 2.0))
    r = route(points, radius)
    return kernel.sweep(_annulus(r.points, d, t), path_wire(r))


# ----------------------------------------------- default sizes and words

def default_radius(dims: Dict[str, float]) -> float:
    """The bend radius a size comes with: its table's r, or three times
    its diameter."""
    r = float(dims.get("r", 0.0) or 0.0)
    return r if r > 0 else 3.0 * float(dims["d"])


def radius_of(member, dims: Dict[str, float]) -> float:
    r = float(getattr(member, "bend_radius", 0.0) or 0.0)
    return r if r > 0 else default_radius(dims)


def size_label(dims: Dict[str, float]) -> str:
    return "%g x %g" % (dims["d"], dims["t"])


# ------------------------------------------------------- the cut list

@dataclass
class CutRow:
    member: int
    part: str
    size: str
    length: float
    bends: List[Bend]
    straights: List[float]
    insulation: float = 0.0
    insulation_material: str = ""


def cut_list(frame_doc) -> Tuple[List[CutRow], List[str]]:
    """Every pipe of a frame: its size, the length of tube it is cut
    from, its bends and straights, and its insulation; and what went
    wrong."""
    from . import frames
    fd = frame_doc.frame
    if fd is None:
        return [], []
    problems: List[str] = []
    geos = frames.member_geometries(fd, frames.skeleton_sketches(
        frames.skeleton_path(frame_doc)), problems)
    rows = []
    for member in fd.members:
        geo = geos.get(member.id)
        if geo is None or getattr(geo, "route", None) is None:
            continue
        r = geo.route
        rows.append(CutRow(member=member.id, part=member.part,
                           size=member.size, length=r.length,
                           bends=list(r.bends), straights=list(r.straights),
                           insulation=member.insulation,
                           insulation_material=(member.insulation_material
                                                or INSULATION_MATERIAL)
                           if member.insulation > 0 else ""))
    return rows, problems


def fittings_of(frame_doc) -> Dict[str, int]:
    """How many of each fitting a frame's pipes take: {label: count}."""
    from . import frames
    fd = frame_doc.frame
    if fd is None:
        return {}
    frames.member_geometries(fd, frames.skeleton_sketches(
        frames.skeleton_path(frame_doc)), [])
    out: Dict[str, int] = {}
    for f in getattr(fd, "planned_fittings", []):
        out[f.label] = out.get(f.label, 0) + 1
    return out


def totals(rows: Sequence[CutRow]) -> Dict[str, Any]:
    """Total tube per size, and insulation per size and thickness:
    {"tube": {size: (pieces, length)}, "insulation":
    {(size, thickness, material): length}}."""
    tube: Dict[str, List[float]] = {}
    lagging: Dict[Tuple[str, float, str], float] = {}
    for row in rows:
        held = tube.setdefault(row.size, [0, 0.0])
        held[0] += 1
        held[1] += row.length
        if row.insulation > 0:
            key = (row.size, row.insulation, row.insulation_material)
            lagging[key] = lagging.get(key, 0.0) + row.length
    return {"tube": {k: (int(v[0]), v[1]) for k, v in tube.items()},
            "insulation": lagging}


def cut_list_csv(rows: Sequence[CutRow],
                 fittings: Optional[Dict[str, int]] = None) -> str:
    """The cut list as a spreadsheet would take it."""
    import csv
    import io
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["Member", "Size", "Cut length mm", "Bends", "Straights mm",
                "Insulation mm", "Insulation material"])
    for row in rows:
        w.writerow([row.member, row.size, "%.1f" % row.length,
                    "; ".join("%.0f deg R%.0f" % (b.angle, b.radius)
                              for b in row.bends),
                    "; ".join("%.1f" % s for s in row.straights),
                    "%g" % row.insulation if row.insulation else "",
                    row.insulation_material])
    t = totals(rows)
    w.writerow([])
    w.writerow(["Size", "Pieces", "Total tube m"])
    for size, (n, length) in sorted(t["tube"].items()):
        w.writerow([size, n, "%.3f" % (length / 1000.0)])
    if t["insulation"]:
        w.writerow([])
        w.writerow(["Insulation for", "Thickness mm", "Material", "Total m"])
        for (size, thk, mat), length in sorted(t["insulation"].items()):
            w.writerow([size, "%g" % thk, mat, "%.3f" % (length / 1000.0)])
    if fittings:
        w.writerow([])
        w.writerow(["Fitting", "Count"])
        for label, n in sorted(fittings.items()):
            w.writerow([label, n])
    return out.getvalue()
