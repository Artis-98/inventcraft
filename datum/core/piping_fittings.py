"""Pipe fittings, put in by themselves where pipes meet.

Wherever the ends of separate pipes meet at one point:

* two at a right angle or at 45 degrees: an elbow (what pipes left
  unmerged at a corner get; merged, a run is bent instead);
* two in one straight line: a coupling, or a reducer when their sizes
  differ;
* three, two in line and one square to them: a tee, a reducing one when
  the branch is smaller.

Each pipe is cut back so its end sits at the bottom of the fitting's
socket, so a pipe's Length and the cut list are what to cut.  Anything
else that meets (another angle, a reducing elbow, four at a point) is
told, not guessed at.

A fitting is a part of its own, one file per kind and size, placed as
often as it is needed, so the BOM counts them.  Its sizes come from the
standard library's fitting table (datum/stdlib/fittings): the socket
depths of EN 1254-1, the rest typical, and between two sizes in the table
the depth is read off between them.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import kernel
from .kernel import KernelError

INLINE = 0.9995              # cos of the angle two ends count as in line
SQUARE = 0.01                # and square to each other
ANGLE_TOL = 0.5              # degrees an elbow's corner may be off

NAMES = {"elbow90": "Elbow 90", "elbow45": "Elbow 45", "tee": "Tee",
         "coupling": "Coupling", "reducer": "Reducer"}


def _sub(a, b):
    return tuple(a[i] - b[i] for i in range(3))


def _dot(a, b):
    return sum(a[i] * b[i] for i in range(3))


def _unit(a):
    n = math.sqrt(_dot(a, a)) or 1.0
    return tuple(c / n for c in a)


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


# ------------------------------------------------------------ the table

def table():
    from . import stdlib
    found = [t for t in stdlib.fittings() if t.kind == "socket"]
    if not found:
        raise KernelError("the standard library has no fitting table")
    return found[0]


def socket(d: float) -> Dict[str, float]:
    """A socket's sizes for tube of outside diameter ``d``: d, the depth
    L, wall s, elbow radius R, tee centre to bottom zt, coupling stop zc.
    Between two sizes in the table, read off between them."""
    t = table()
    rows = sorted((dict(zip(t.columns, r[1:])) for r in t.rows),
                  key=lambda r: r["d"])
    for r in rows:
        if abs(r["d"] - d) < 0.05:
            return dict(r)
    if d < rows[0]["d"] or d > rows[-1]["d"]:
        raise KernelError("there are no fittings for %g mm tube" % d)
    lo = max((r for r in rows if r["d"] < d), key=lambda r: r["d"])
    hi = min((r for r in rows if r["d"] > d), key=lambda r: r["d"])
    k = (d - lo["d"]) / (hi["d"] - lo["d"])
    depth = lo["L"] + k * (hi["L"] - lo["L"])
    wall = round(max(0.8, 0.04 * d + 0.5), 1)
    return {"d": d, "L": round(depth, 1), "s": wall, "R": d,
            "zt": round(d / 2 + wall + 1, 1), "zc": lo["zc"]}


def setback(kind: str, sockets: Sequence[Dict[str, float]]) -> List[float]:
    """How far each socket's bottom is from the fitting's centre point:
    how much the pipe in it is cut back."""
    if kind == "elbow90":
        return [sockets[0]["R"]] * 2
    if kind == "elbow45":
        return [sockets[0]["R"] * math.tan(math.radians(22.5))] * 2
    if kind == "tee":
        return [sockets[0]["zt"]] * 3
    if kind == "coupling":
        return [sockets[0]["zc"]] * 2
    if kind == "reducer":
        gap = (sockets[0]["d"] - sockets[1]["d"]) / 2.0 \
            + 2.0 * sockets[0]["zc"]
        return [gap / 2.0] * 2
    raise KernelError("there is no fitting %s" % kind)


# --------------------------------------------------------- the shapes

def _revolved(points):
    """A closed outline in the XZ plane, (r, z) pairs, turned round Z."""
    from OCP.BRepBuilderAPI import (BRepBuilderAPI_MakeFace,
                                    BRepBuilderAPI_MakePolygon)
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeRevol
    from OCP.gp import gp_Ax1, gp_Dir, gp_Pnt
    poly = BRepBuilderAPI_MakePolygon()
    for r, z in points:
        poly.Add(gp_Pnt(r, 0.0, z))
    poly.Close()
    face = BRepBuilderAPI_MakeFace(poly.Wire(), True).Face()
    return BRepPrimAPI_MakeRevol(face, gp_Ax1(gp_Pnt(0, 0, 0),
                                              gp_Dir(0, 0, 1))).Shape()


def solid(kind: str, sockets: Sequence[Dict[str, float]]):
    """The fitting in its own coordinates, its centre point at the
    origin: an elbow's first socket up +Z and its second in XZ; a tee's
    run along Z and its branch along +X; a coupling's or reducer's first
    socket down -Z, its second (the smaller) up +Z."""
    first = sockets[0]
    d, depth, wall = first["d"], first["L"], first["s"]
    out = d + 2 * wall
    zs = setback(kind, sockets)
    if kind in ("elbow90", "elbow45"):
        from . import piping
        turn = 90.0 if kind == "elbow90" else 45.0
        open_ = math.radians(180.0 - turn)
        reach = zs[0] + depth
        a2 = (math.sin(open_), 0.0, math.cos(open_))
        return piping.tube_solid([(0.0, 0.0, reach), (0.0, 0.0, 0.0),
                                  tuple(c * reach for c in a2)],
                                 out, wall, first["R"])
    if kind == "tee":
        branch = sockets[1] if len(sockets) > 1 else first
        reach = zs[0] + depth
        body = kernel.cylinder(out / 2.0, 2 * reach, (0.0, 0.0, -reach))
        b_out = branch["d"] + 2 * branch["s"]
        b_reach = zs[0] + branch["L"]
        arm = kernel.cylinder(b_out / 2.0, b_reach, (0.0, 0.0, 0.0),
                              (1.0, 0.0, 0.0))
        shape = kernel.boolean(body, arm, "join")
        shape = kernel.boolean(shape, kernel.cylinder(
            d / 2.0, 2 * reach + 2, (0.0, 0.0, -reach - 1)), "cut")
        shape = kernel.boolean(shape, kernel.cylinder(
            branch["d"] / 2.0, b_reach + 1, (0.0, 0.0, 0.0),
            (1.0, 0.0, 0.0)), "cut")
        return shape
    if kind in ("coupling", "reducer"):
        second = sockets[1] if len(sockets) > 1 else first
        g = zs[0]
        r1, r2 = d / 2.0, second["d"] / 2.0
        o1, o2 = r1 + wall, r2 + second["s"]
        bore = max(0.5, r2 - second["s"])
        z0, z3 = -g - depth, g + second["L"]
        # the outline: up the outside, back down the inside, the sockets'
        # bottoms the steps the tubes stop at
        pts = [(r1, z0), (o1, z0), (o1, -g), (o2, g), (o2, z3), (r2, z3),
               (r2, g), (bore, g), (bore, -g), (r1, -g)]
        if g < 1e-6:
            raise KernelError("a coupling needs a stop between its sockets")
        return _revolved(pts)
    raise KernelError("there is no fitting %s" % kind)


# --------------------------------------------------- where they go

@dataclass
class Fitting:
    kind: str
    sockets: List[Dict[str, float]]
    point: Tuple[float, float, float]
    axes: Any                          # columns X, Y, Z in the frame
    ends: List[Tuple[int, str]] = field(default_factory=list)

    @property
    def sizes(self) -> List[float]:
        return [s["d"] for s in self.sockets]

    @property
    def label(self) -> str:
        sizes = "x".join("%g" % d for d in dict.fromkeys(self.sizes))
        return "%s %s" % (NAMES[self.kind], sizes)

    @property
    def part_name(self) -> str:
        return re.sub(r"[^A-Za-z0-9_.-]+", " ", self.label).strip() \
            + ".icpart"

    @property
    def key(self) -> str:
        return "%s@%s" % (self.label, ",".join("%.2f" % c
                                               for c in self.point))

    def placement(self):
        from .constraints3d import Placement, rotation_vector
        return Placement([float(c) for c in self.point],
                         [float(c) for c in rotation_vector(self.axes)])


def _axes(z, x):
    """The fitting's axes from two pipe ends' outward directions: its Z
    socket into the first pipe, its X (or its second socket's side) into
    the second.  Outward points out of a pipe at its end, toward the
    fitting, so into the pipe is the other way."""
    import numpy as np
    z = _unit(tuple(-c for c in z))
    x = tuple(-c for c in x)
    x = _unit(_sub(x, tuple(c * _dot(x, z) for c in z)))
    y = _cross(z, x)
    return np.array([x, y, z]).T


def _any_square(z):
    a = (1.0, 0.0, 0.0) if abs(z[0]) < 0.9 else (0.0, 1.0, 0.0)
    return a


def _key(p, tol: float = 1e-3):
    return tuple(round(c / tol) for c in p)


def pipe_ends(geos) -> List[Tuple[int, str, Tuple, Tuple, float]]:
    """Every pipe's two ends: (member id, "a" or "b", where in the frame,
    which way out of the pipe, its outside diameter)."""
    out = []
    for mid, geo in geos.items():
        pts = getattr(geo, "local_points", None)
        if getattr(geo, "route", None) is None or not pts:
            continue
        d = float(geo.dims["d"])
        for end, here, there in (("a", pts[0], pts[1]),
                                 ("b", pts[-1], pts[-2])):
            out.append((mid, end, geo.to_world(here),
                        _unit(geo.dir_world(_unit(_sub(here, there)))), d))
    return out


def plan(geos, problems: List[str]) -> Tuple[List[Fitting],
                                             Dict[int, Dict[str, float]]]:
    """The fittings where the pipes meet, and how far each pipe end is cut
    back for them: ({member id: {"a": mm, "b": mm}})."""
    groups: Dict[Any, list] = {}
    for e in pipe_ends(geos):
        groups.setdefault(_key(e[2]), []).append(e)
    fittings, trims = [], {}

    def same(a, b):
        return abs(a - b) < 0.05

    for ends in groups.values():
        if len(ends) < 2:
            continue
        at = ends[0][2]
        where = "at %s" % ", ".join("%.0f" % c for c in at)
        try:
            if len(ends) == 2:
                (m1, e1, _p1, u1, d1), (m2, e2, _p2, u2, d2) = ends
                dot = _dot(u1, u2)
                if dot > INLINE:
                    raise KernelError("two pipes lie on top of each other "
                                      "%s" % where)
                if dot < -INLINE:
                    if same(d1, d2):
                        f = Fitting("coupling", [socket(d1), socket(d2)], at,
                                    _axes(u2, _any_square(u2)),
                                    [(m1, e1), (m2, e2)])
                    else:
                        big, small = (ends[0], ends[1]) if d1 > d2 \
                            else (ends[1], ends[0])
                        f = Fitting("reducer", [socket(big[4]),
                                                socket(small[4])], at,
                                    _axes(small[3], _any_square(small[3])),
                                    [big[:2], small[:2]])
                else:
                    turn = 180.0 - math.degrees(math.acos(max(-1.0, min(
                        1.0, dot))))
                    kind = "elbow90" if abs(turn - 90) < ANGLE_TOL else \
                        "elbow45" if abs(turn - 45) < ANGLE_TOL else ""
                    if not kind:
                        raise KernelError(
                            "two pipes meet at %.1f degrees %s: there are "
                            "elbows of 90 and 45, so tick Merge to bend it"
                            % (turn, where))
                    if not same(d1, d2):
                        raise KernelError(
                            "a %g and a %g pipe meet at a corner %s: put a "
                            "reducer before the elbow" % (d1, d2, where))
                    f = Fitting(kind, [socket(d1), socket(d2)], at,
                                _axes(u1, u2), [(m1, e1), (m2, e2)])
            elif len(ends) == 3:
                pair = next(((i, j) for i in range(3) for j in range(i + 1, 3)
                             if _dot(ends[i][3], ends[j][3]) < -INLINE), None)
                if pair is None:
                    raise KernelError("three pipes meet %s with none of "
                                      "them in line: no tee fits" % where)
                branch = ends[3 - pair[0] - pair[1]]
                run = [ends[pair[0]], ends[pair[1]]]
                if any(abs(_dot(branch[3], r[3])) > SQUARE for r in run):
                    raise KernelError("the branch %s is not square to the "
                                      "run: tees are 90 degrees" % where)
                if not same(run[0][4], run[1][4]):
                    raise KernelError("the run through the tee %s changes "
                                      "size: put a reducer next to it"
                                      % where)
                if branch[4] > run[0][4] + 0.05:
                    raise KernelError("the branch %s is bigger than the "
                                      "run" % where)
                f = Fitting("tee", [socket(run[0][4]), socket(branch[4])], at,
                            _axes(run[0][3], branch[3]),
                            [run[0][:2], run[1][:2], branch[:2]])
            else:
                raise KernelError("%d pipes meet %s: no fitting takes that "
                                  "many" % (len(ends), where))
        except KernelError as exc:
            problems.append(str(exc))
            continue
        for (mid, end), back in zip(f.ends, setback(f.kind, f.sockets)):
            trims.setdefault(mid, {})[end] = back
        fittings.append(f)
    return fittings, trims


def trim(points, back_a: float, back_b: float):
    """A route's ends brought back along its first and last legs."""
    pts = [tuple(p) for p in points]
    for index, nxt, back in ((0, 1, back_a), (-1, -2, back_b)):
        if back <= 0:
            continue
        leg = _sub(pts[nxt], pts[index])
        n = math.sqrt(_dot(leg, leg))
        if back >= n - 1e-6:
            raise KernelError("its end leg is %.1f mm, shorter than the %.1f "
                              "mm its fitting takes" % (n, back))
        u = tuple(c / n for c in leg)
        pts[index] = tuple(pts[index][i] + u[i] * back for i in range(3))
    return pts
