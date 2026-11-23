"""``recognize`` and ``parametrize``: a dumb solid back into a feature tree.

A STEP file brings a body with no history. ``recognize`` reads the body
(read-only) and says which features it can see, each with measured values
and the faces it accounts for, and how much of the body that explains.
``parametrize`` writes those features as an ordinary tree, with named
parameters, checks the result against the original with a volume and a
boolean difference, and only then replaces the import with it.

How it recognises (an attributed-adjacency view of the B-rep: faces are
nodes, shared edges are arcs, and a face's surface type and orientation
are its attributes; the idea is the classic one):

1. Fillets and chamfers first, as the feature-recognition literature
   does: a cylinder, sphere or torus patch tangent to both neighbours, or a
   narrow 45 degree strip between two perpendicular planes. They are
   removed with OpenCASCADE's ``BOPAlgo_RemoveFeatures``, which extends the
   neighbouring faces, and what is left is a *sharp* body. Where the edge
   of each one was is found on the sharp body.
2. The sharp body is read as a prism: the axis (x, y or z) along which most
   of the surface is a side (a plane parallel to it, a cylinder along it) or
   one of two ends. The base is the end face's outline extruded the length
   of the body.
3. Concave cylinders along an axis, with the cones and flat rings that are
   coaxial with them, are holes: simple, counterbore, countersink, through
   or blind. Identical holes are then looked at as a grid or a circle.
4. Planar faces across the axis at a level between the ends are steps:
   a pocket's floor or the shoulder round a boss. A pocket is a cut from
   the end; a boss standing on a plate is a join.

The answer says what it could not explain; nothing is guessed about those
faces.
"""

from __future__ import annotations

import math
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

from OCP.BRepAdaptor import BRepAdaptor_Curve, BRepAdaptor_Surface
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace
from OCP.BRepGProp import BRepGProp
from OCP.BRepTools import BRepTools, BRepTools_WireExplorer
from OCP.GeomAbs import GeomAbs_CurveType, GeomAbs_SurfaceType
from OCP.GProp import GProp_GProps
from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_REVERSED, TopAbs_WIRE
from OCP.TopExp import TopExp
from OCP.TopoDS import TopoDS
from OCP.TopTools import (TopTools_IndexedDataMapOfShapeListOfShape,
                          TopTools_IndexedMapOfShape)

from ..core import edgequery, kernel
from ..core.document import Document
from . import ops
from .errors import BridgeError
from .workspace import Entry, Workspace

op = ops.op

TOL = 1e-3          # mm, for "the same place"
LINE = GeomAbs_CurveType.GeomAbs_Line
CIRCLE = GeomAbs_CurveType.GeomAbs_Circle
PLANE = GeomAbs_SurfaceType.GeomAbs_Plane
CYL = GeomAbs_SurfaceType.GeomAbs_Cylinder
CONE = GeomAbs_SurfaceType.GeomAbs_Cone
SPHERE = GeomAbs_SurfaceType.GeomAbs_Sphere
TORUS = GeomAbs_SurfaceType.GeomAbs_Torus

LET = "xyz"
UV = {0: (1, 2), 1: (0, 2), 2: (0, 1)}          # axis -> world axes of u, v
SKETCH_PLANE = {0: "YZ", 1: "XZ", 2: "XY"}
PLANE_SIGN = {0: 1, 1: -1, 2: 1}                # the plane normal against +axis


# ------------------------------------------------------------------ vectors


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _add(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _mul(a, s):
    return (a[0] * s, a[1] * s, a[2] * s)


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _norm(a):
    return math.sqrt(_dot(a, a))


def _unit(a):
    n = _norm(a) or 1.0
    return (a[0] / n, a[1] / n, a[2] / n)


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def _xyz(p) -> Tuple[float, float, float]:
    return (p.X(), p.Y(), p.Z())


def _aligned(v) -> Optional[Tuple[int, int]]:
    """(axis index, sign) when the vector is along x, y or z."""
    for k in range(3):
        if abs(abs(v[k]) - 1.0) < 1e-6:
            return k, 1 if v[k] > 0 else -1
    return None


def _uv(k: int, p) -> Tuple[float, float]:
    a, b = UV[k]
    return (p[a], p[b])


def _r(v: float, n: int = 4) -> float:
    v = round(float(v), n)
    return 0.0 if v == 0 else v


def _num(v: float) -> str:
    return ("%.6f" % v).rstrip("0").rstrip(".") or "0"


# ------------------------------------------------------------------ faces


class Fc:
    """One face and what recognition needs of it."""

    def __init__(self, i: int, face) -> None:
        self.i = i
        self.face = face
        ad = BRepAdaptor_Surface(face, True)
        t = ad.GetType()
        rev = face.Orientation() == TopAbs_REVERSED
        props = GProp_GProps()
        BRepGProp.SurfaceProperties_s(face, props)
        self.area = props.Mass()
        self.com = _xyz(props.CentreOfMass())
        self.kind = "other"
        self.n: Optional[Tuple[float, float, float]] = None   # plane, outward
        self.loc = (0.0, 0.0, 0.0)
        self.axis: Optional[Tuple[float, float, float]] = None
        self.r = 0.0
        self.big_r = 0.0
        self.semi = 0.0
        self.convex = True
        self.span = 0.0
        self.k: Optional[int] = None      # axis index when axis aligned
        self.v0 = self.v1 = 0.0
        if t == PLANE:
            pl = ad.Plane()
            nat = _cross(_xyz(pl.XAxis().Direction()),
                         _xyz(pl.YAxis().Direction()))
            self.kind = "plane"
            self.n = _unit(_mul(nat, -1.0 if rev else 1.0))
            self.loc = _xyz(pl.Location())
            al = _aligned(self.n)
            self.k = al[0] if al else None
        elif t in (CYL, CONE, SPHERE, TORUS):
            direct = True
            if t == CYL:
                s = ad.Cylinder()
                self.kind, self.r = "cyl", s.Radius()
            elif t == CONE:
                s = ad.Cone()
                self.kind, self.r = "cone", s.RefRadius()
                self.semi = abs(s.SemiAngle())
            elif t == SPHERE:
                s = ad.Sphere()
                self.kind, self.r = "sphere", s.Radius()
            else:
                s = ad.Torus()
                self.kind, self.r, self.big_r = ("torus", s.MinorRadius(),
                                                 s.MajorRadius())
            pos = s.Position()
            direct = pos.Direct()
            self.loc = _xyz(pos.Location())
            self.axis = _unit(_xyz(pos.Direction()))
            self.convex = (not rev) == bool(direct)
            self.span = ad.LastUParameter() - ad.FirstUParameter()
            self.v0, self.v1 = ad.FirstVParameter(), ad.LastVParameter()
            if self.kind in ("cyl", "cone", "torus"):
                al = _aligned(self.axis)
                self.k = al[0] if al else None
        pts = [kernel.vertex_point(v) for v in kernel.vertices(face)]
        self.pts = pts
        self.lo = tuple(min(p[c] for p in pts) for c in range(3)) if pts \
            else self.com
        self.hi = tuple(max(p[c] for p in pts) for c in range(3)) if pts \
            else self.com

    @property
    def level(self) -> float:
        return self.com[self.k] if self.k is not None else 0.0

    def line_dist(self, p) -> float:
        """Distance from a point to this face's axis line."""
        d = _sub(p, self.loc)
        along = _dot(d, self.axis)
        return _norm(_sub(d, _mul(self.axis, along)))

    def describe(self) -> Dict[str, Any]:
        out = {"index": self.i, "kind": {"cyl": "cylinder"}.get(
            self.kind, self.kind), "area": _r(self.area, 3),
            "centre": [_r(c, 3) for c in self.com]}
        if self.kind == "cyl" or self.kind == "sphere":
            out["radius"] = _r(self.r, 4)
            out["concave"] = not self.convex
        if self.kind == "plane":
            out["normal"] = [_r(c, 3) for c in self.n]
        if self.kind == "cone":
            out["half_angle_deg"] = _r(math.degrees(self.semi), 2)
        return out


def _faces(shape) -> Tuple[List[Fc], List[Dict[int, List[Any]]]]:
    fmap = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(shape, TopAbs_FACE, fmap)
    flist = [TopoDS.Face_s(fmap.FindKey(i)) for i in range(1, fmap.Extent() + 1)]
    fcs = [Fc(i, f) for i, f in enumerate(flist)]
    amap = TopTools_IndexedDataMapOfShapeListOfShape()
    TopExp.MapShapesAndAncestors_s(shape, TopAbs_EDGE, TopAbs_FACE, amap)
    adj: List[Dict[int, List[Any]]] = [dict() for _ in fcs]
    for n in range(1, amap.Extent() + 1):
        edge = TopoDS.Edge_s(amap.FindKey(n))
        ids = [fmap.FindIndex(face) - 1 for face in amap.FindFromIndex(n)]
        ids = [i for i in dict.fromkeys(ids) if i >= 0]
        if len(ids) == 2:
            a, b = ids
            adj[a].setdefault(b, []).append(edge)
            adj[b].setdefault(a, []).append(edge)
    return fcs, adj


class Ed:
    """An edge: kind, ends, middle."""

    def __init__(self, edge) -> None:
        self.edge = edge
        c = BRepAdaptor_Curve(edge)
        self.kind = {LINE: "line", CIRCLE: "circle"}.get(c.GetType(),
                                                         "other")
        f, l = c.FirstParameter(), c.LastParameter()
        self.a = _xyz(c.Value(f))
        self.b = _xyz(c.Value(l))
        self.m = _xyz(c.Value((f + l) / 2.0))
        self.dir = None
        self.centre = None
        self.r = 0.0
        self.axis = None
        self.full = False
        if self.kind == "line":
            self.dir = _unit(_sub(self.b, self.a))
        elif self.kind == "circle":
            ci = c.Circle()
            self.centre = _xyz(ci.Location())
            self.r = ci.Radius()
            self.axis = _xyz(ci.Axis().Direction())
            self.full = abs(abs(l - f) - 2 * math.pi) < 1e-6
        self.length = kernel.edge_length(edge)


def _normal_at(fc: Fc, p):
    if fc.kind == "plane":
        return fc.n
    if fc.kind == "cyl":
        d = _sub(p, fc.loc)
        rad = _sub(d, _mul(fc.axis, _dot(d, fc.axis)))
        return _mul(_unit(rad), 1.0 if fc.convex else -1.0)
    if fc.kind == "sphere":
        return _mul(_unit(_sub(p, fc.loc)), 1.0 if fc.convex else -1.0)
    if fc.kind == "torus":
        d = _sub(p, fc.loc)
        rad = _unit(_sub(d, _mul(fc.axis, _dot(d, fc.axis))))
        c = _add(fc.loc, _mul(rad, fc.big_r))
        return _mul(_unit(_sub(p, c)), 1.0 if fc.convex else -1.0)
    return None


def _tangent(fcs, adj, i: int, j: int) -> bool:
    """Whether faces i and j meet smoothly along every shared edge."""
    edges = adj[i].get(j) or []
    if not edges:
        return False
    for e in edges:
        p = Ed(e).m
        a, b = _normal_at(fcs[i], p), _normal_at(fcs[j], p)
        if a is None or b is None or _dot(a, b) < 0.9995:
            return False
    return True


# ------------------------------------------------------------ fillets


class Blend:
    """A fillet or a chamfer found on the original body."""

    def __init__(self, kind: str, value: float, face: Fc) -> None:
        self.kind = kind            # "fillet" | "chamfer"
        self.value = value          # radius, or the leg of the chamfer
        self.face = face
        self.faces = [face]
        self.edges: List[Any] = []  # edges of the sharp body
        self.located = False

    @property
    def concave(self) -> bool:
        return not self.face.convex


def find_blends(fcs, adj) -> List[Blend]:
    out: List[Blend] = []
    patches = set()
    for f in fcs:
        if f.kind == "cyl" and 0 < f.span < 2.4:
            seams = [Ed(e) for js in adj[f.i].values() for e in js]
            seams = [e for e in seams if e.kind == "line"
                     and abs(abs(_dot(e.dir, f.axis)) - 1) < 1e-6]
            nbs = [j for j, es in adj[f.i].items()
                   if any(Ed(e).kind == "line"
                          and abs(abs(_dot(Ed(e).dir, f.axis)) - 1) < 1e-6
                          for e in es)]
            if len(seams) < 2 or len(nbs) < 2:
                continue
            ok = True
            for j in nbs:
                g = fcs[j]
                if g.kind == "cyl" and abs(g.r - f.r) < TOL and g.k == f.k \
                        and g.axis and abs(abs(_dot(g.axis, f.axis)) - 1) \
                        < 1e-6 and g.line_dist(f.loc) < TOL:
                    ok = False          # the other half of the same bore
                if not _tangent(fcs, adj, f.i, j):
                    ok = False
            if ok:
                out.append(Blend("fillet", f.r, f))
                patches.add(f.i)
        elif f.kind == "torus" and f.r > 0 and f.span > 0:
            nbs = list(adj[f.i])
            if nbs and all(_tangent(fcs, adj, f.i, j) for j in nbs):
                out.append(Blend("fillet", f.r, f))
                patches.add(f.i)
    # a sphere that only joins fillets of its own radius is their corner
    for f in fcs:
        if f.kind == "sphere":
            nbs = list(adj[f.i])
            rr = [b for b in out if b.face.i in nbs]
            if len(rr) >= 2 and all(abs(b.value - f.r) < TOL for b in rr) \
                    and all(_tangent(fcs, adj, f.i, j) for j in nbs
                            if j in patches):
                rr[0].faces.append(f)
    # chamfers: a narrow plane between two perpendicular planes at 45 degrees
    taken = {id(x) for b in out for x in b.faces}
    for f in fcs:
        if f.kind != "plane" or id(f) in taken:
            continue
        lines = sorted((Ed(e) for js in adj[f.i].values() for e in js
                        if Ed(e).kind == "line"),
                       key=lambda e: -e.length)
        if len(lines) < 2 or len(lines) > 4:
            continue
        e1 = lines[0]
        e2 = next((e for e in lines[1:] if abs(abs(_dot(e.dir, e1.dir)) - 1)
                   < 1e-6 and e.length > 0.5 * e1.length), None)
        if e2 is None:
            continue
        nb = []
        for e in (e1, e2):
            for j, es in adj[f.i].items():
                if any(x.IsSame(e.edge) for x in es):
                    nb.append(fcs[j])
        if len(nb) != 2 or nb[0].i == nb[1].i:
            continue
        g1, g2 = nb
        if g1.kind != "plane" or g2.kind != "plane":
            continue
        if abs(_dot(g1.n, g2.n)) > 0.01:
            continue
        mid = _unit(_add(g1.n, g2.n))
        if _dot(mid, f.n) < 1 - 1e-3:
            continue
        # distance between the two long edges
        w = _norm(_cross(_sub(e2.a, e1.a), e1.dir))
        if w <= TOL or w > 0.9 * e1.length:
            continue
        # a chamfer is narrow against the faces it joins; a flat strip
        # between two other chamfers (a top face) is not one
        if any(_width(g) < 1.5 * w for g in (g1, g2)):
            continue
        out.append(Blend("chamfer", w / math.sqrt(2.0), f))
    # a chamfer round a round edge is a cone at 45 degrees, convex, between a
    # flat and a cylinder that share its axis
    for f in fcs:
        if f.kind == "cone" and f.convex and abs(math.degrees(f.semi)
                                                 - 45.0) < 0.5                 and f.k is not None:
            nbs = [fcs[j] for j in adj[f.i]]
            if len(nbs) != 2:
                continue
            flat = [g for g in nbs if g.kind == "plane" and g.k == f.k]
            cyl = [g for g in nbs if g.kind == "cyl" and g.k == f.k
                   and g.line_dist(f.loc) < TOL]
            if len(flat) != 1 or len(cyl) != 1:
                continue
            slant = abs(f.v1 - f.v0)
            if slant <= TOL:
                continue
            out.append(Blend("chamfer", slant / math.sqrt(2.0), f))
    return out


def _width(fc: Fc) -> float:
    """Area over the longest edge: the short side of a strip."""
    longest = max((Ed(e).length for e in kernel.edges(fc.face)), default=0.0)
    return fc.area / longest if longest > 0 else 0.0


def remove_blends(shape, blends: List[Blend]):
    """The body with the blends taken out (sharp), or None."""
    if not blends:
        return None
    from OCP.BOPAlgo import BOPAlgo_RemoveFeatures
    try:
        rf = BOPAlgo_RemoveFeatures()
        rf.SetShape(shape)
        for b in blends:
            for f in b.faces:
                rf.AddFaceToRemove(f.face)
        rf.SetRunParallel(False)
        rf.Perform()
        if rf.HasErrors():
            return None
        out = rf.Shape()
        if out is None or out.IsNull() or not kernel.is_valid(out):
            return None
        if len(kernel.solids(out)) != len(kernel.solids(shape)):
            return None
        return out
    except Exception:                                       # noqa: BLE001
        return None


def locate_blends(blends: List[Blend], sharp, fcs, adj) -> None:
    """Where each blend's edge is on the sharp body."""
    edges = [Ed(e) for e in kernel.edges(sharp)]
    for b in blends:
        f = b.face
        best = None
        if f.kind in ("torus", "cone"):
            nbs = [fcs[j] for j in adj[f.i]]
            fl = [g for g in nbs if g.kind == "plane" and g.k == f.k]
            cy = [g for g in nbs if g.kind == "cyl" and g.k == f.k
                  and g.line_dist(f.loc) < TOL]
            cands = [e for e in edges if e.kind == "circle"
                     and abs(abs(_dot(e.axis, f.axis)) - 1) < 1e-6
                     and f.line_dist(e.centre) < TOL]
            if fl and cy:
                # the circle where the flat meets the cylinder
                cands = [e for e in cands if abs(e.r - cy[0].r) < TOL
                         and abs(e.m[f.k] - fl[0].level) < TOL]
            if cands:
                best = min(cands, key=lambda e: abs(e.m[f.k] - f.com[f.k]))
        elif f.kind == "cyl":
            cands = [e for e in edges if e.kind == "line"
                     and abs(abs(_dot(e.dir, f.axis)) - 1) < 1e-6
                     and _point_seg(f.com, e) <= 3 * b.value + 3 * TOL]
            if cands:
                best = min(cands, key=lambda e: _point_seg(f.com, e))
        elif f.kind == "plane":
            cands = [e for e in edges if e.kind == "line"
                     and _point_seg(f.com, e) < b.value * 3 + TOL
                     and _chamfer_parallel(f, e)]
            if cands:
                best = min(cands, key=lambda e: _point_seg(f.com, e))
        if best is not None:
            b.edges = [best.edge]
            b.located = True


def _chamfer_parallel(f: Fc, e: Ed) -> bool:
    """A line of the sharp body lying along the chamfer's own edges."""
    lines = [Ed(x) for x in kernel.edges(f.face)]
    return any(x.kind == "line" and abs(abs(_dot(x.dir, e.dir)) - 1) < 1e-6
               for x in lines)


def _point_seg(p, e: Ed) -> float:
    if e.kind == "line":
        ab = _sub(e.b, e.a)
        t = max(0.0, min(1.0, _dot(_sub(p, e.a), ab) / (_dot(ab, ab) or 1)))
        return _norm(_sub(p, _add(e.a, _mul(ab, t))))
    return _norm(_sub(p, e.m))


# ------------------------------------------------------------ loops


def _wire_loop(wire, k: int) -> Dict[str, Any]:
    """A planar wire as 2D segments in the frame of axis ``k``."""
    segs: List[Dict[str, Any]] = []
    ex = BRepTools_WireExplorer(wire)
    while ex.More():
        e = TopoDS.Edge_s(ex.Current())
        c = BRepAdaptor_Curve(e)
        f, l = c.FirstParameter(), c.LastParameter()
        p0, p1, pm = _xyz(c.Value(f)), _xyz(c.Value(l)), \
            _xyz(c.Value((f + l) / 2.0))
        if e.Orientation() == TopAbs_REVERSED:
            p0, p1 = p1, p0
        a, b, m = _uv(k, p0), _uv(k, p1), _uv(k, pm)
        t = c.GetType()
        if t == LINE:
            segs.append({"k": "L", "a": a, "b": b})
        elif t == CIRCLE:
            ci = c.Circle()
            cu = _uv(k, _xyz(ci.Location()))
            r = ci.Radius()
            if abs(abs(l - f) - 2 * math.pi) < 1e-6:
                segs.append({"k": "C", "c": cu, "r": r})
            else:
                cross = ((m[0] - a[0]) * (b[1] - m[1])
                         - (m[1] - a[1]) * (b[0] - m[0]))
                ccw = cross > 0
                ang = lambda p: math.degrees(                 # noqa: E731
                    math.atan2(p[1] - cu[1], p[0] - cu[0]))
                s, en = (ang(a), ang(b)) if ccw else (ang(b), ang(a))
                segs.append({"k": "A", "c": cu, "r": r, "a": a, "b": b,
                             "ccw": ccw, "s": s, "e": en})
        else:
            segs.append({"k": "?", "a": a, "b": b})
        ex.Next()
    return {"segs": segs}


def _loops(fc: Fc, k: int) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    outer = BRepTools.OuterWire_s(fc.face)
    inner = [TopoDS.Wire_s(w) for w in kernel.explore(fc.face, TopAbs_WIRE)
             if not w.IsSame(outer)]
    return _wire_loop(outer, k), [_wire_loop(w, k) for w in inner]


def _outer_area(fc: Fc) -> float:
    try:
        mk = BRepBuilderAPI_MakeFace(BRepTools.OuterWire_s(fc.face), True)
        props = GProp_GProps()
        BRepGProp.SurfaceProperties_s(mk.Face(), props)
        return props.Mass()
    except Exception:                                       # noqa: BLE001
        return fc.area


def _is_circle(loop) -> bool:
    return len(loop["segs"]) == 1 and loop["segs"][0]["k"] == "C"


def _loop_key(loop) -> Tuple:
    """A loop's shape and place, for telling two loops are the same."""
    if _is_circle(loop):
        s = loop["segs"][0]
        return ("C", _r(s["c"][0], 2), _r(s["c"][1], 2), _r(s["r"], 2))
    pts = sorted((_r(s["a"][0], 2), _r(s["a"][1], 2)) for s in loop["segs"])
    return ("P",) + tuple(pts)


# ------------------------------------------------------------ holes


class Hole:
    def __init__(self) -> None:
        self.kind = "simple"        # simple | counterbore | countersink
        self.k = 2                  # world axis of the bore
        self.uv = (0.0, 0.0)
        self.d = 0.0
        self.through = True
        self.depth = 0.0
        self.cb_d = 0.0
        self.cb_depth = 0.0
        self.angle = 90.0
        self.mouth = 0.0            # coordinate along k of the entry
        self.lo = 0.0               # coordinates of the two ends along k
        self.hi = 0.0
        self.into = 1               # direction from the mouth into the part
        self.faces: List[int] = []
        self.tips: List[int] = []   # drill points, not explained
        self.ok = True
        self.mouths: List[Tuple] = []

    def key(self) -> Tuple:
        return (self.k, self.kind, _r(self.d, 3), _r(self.cb_d, 3),
                _r(self.cb_depth, 3), _r(self.angle, 2), self.through,
                _r(self.depth, 3),
                (_r(self.lo, 3), _r(self.hi, 3)) if self.through
                else (_r(self.mouth, 3), self.into))


def _coaxial(a: Fc, b: Fc) -> bool:
    return (a.k is not None and a.k == b.k
            and a.line_dist(b.loc) < TOL and (_dot(a.axis, a.axis) > 0))


def find_holes(fcs, adj) -> List[Hole]:
    seeds = [f for f in fcs if f.kind == "cyl" and not f.convex
             and f.k is not None]
    seen: set = set()
    holes: List[Hole] = []
    for s in seeds:
        if s.i in seen:
            continue
        members = {s.i}
        queue = [s]
        while queue:
            cur = queue.pop()
            for j, edges in adj[cur.i].items():
                if j in members:
                    continue
                g = fcs[j]
                take = False
                if g.kind == "cyl" and not g.convex and _coaxial(s, g):
                    take = True
                elif g.kind == "cone" and not g.convex and _coaxial(s, g):
                    take = True
                elif g.kind == "plane" and g.k == s.k and _ring(fcs, adj, g,
                                                                 s):
                    take = True
                if take:
                    members.add(j)
                    queue.append(g)
        seen |= members
        h = _read_hole(fcs, adj, s, sorted(members))
        if h is not None:
            holes.append(h)
    return holes


def _ring(fcs, adj, g: Fc, s: Fc) -> bool:
    """A flat ring or disc whose every neighbour is a bore of the same
    axis: the step of a counterbore, or a blind hole's floor."""
    loops_ok = all(Ed(e).kind == "circle" and
                   s.line_dist(Ed(e).centre) < TOL
                   for js in adj[g.i].values() for e in js)
    if not loops_ok:
        return False
    for j in adj[g.i]:
        n = fcs[j]
        if not (n.kind in ("cyl", "cone") and not n.convex
                and _coaxial(s, n)):
            return False
    return True


def _read_hole(fcs, adj, seed: Fc, ids: List[int]) -> Optional[Hole]:
    k = seed.k
    members = [fcs[i] for i in ids]
    mset = set(ids)
    h = Hole()
    h.k = k
    h.uv = _uv(k, seed.loc)
    h.faces = list(ids)
    # where the stack meets the rest of the body: its open ends
    opens = []            # (level, circle centre uv, radius, member)
    for m in members:
        if m.kind in ("cyl", "cone"):
            for j, es in adj[m.i].items():
                if j in mset:
                    continue
                for e in es:
                    ed = Ed(e)
                    if ed.kind == "circle":
                        opens.append((ed.m[k], _uv(k, ed.centre), ed.r, m))
    coords = [p[k] for m in members for p in m.pts]
    if not coords:
        return None
    h.lo, h.hi = min(coords), max(coords)
    h.mouths = [(o[0], o[1], o[2]) for o in opens]
    open_levels = sorted({_r(o[0], 3) for o in opens})
    radii = sorted({_r(m.r, 4) for m in members if m.kind == "cyl"})
    cyls = [m for m in members if m.kind == "cyl"]
    cones = [m for m in members if m.kind == "cone"]
    flats = [m for m in members if m.kind == "plane"]
    if not cyls:
        return None
    if len(open_levels) == 2 and abs(open_levels[0] - h.lo) < TOL \
            and abs(open_levels[1] - h.hi) < TOL:
        h.through = True
    elif len(open_levels) == 1:
        h.through = False
    else:
        h.ok = False
        return h
    # a cone with no open end is a drill point
    for c in list(cones):
        if not any(o[3] is c for o in opens):
            cones.remove(c)
            h.tips.append(c.i)
    cone_open = [o for o in opens if o[3] in cones]
    if h.through:
        if cone_open:
            h.mouth = cone_open[0][0]
        elif len(radii) == 2:
            h.mouth = next(o[0] for o in opens
                           if o[3].kind == "cyl" and o[3].r >= max(radii) - 1e-6)
        else:
            h.mouth = h.lo
        h.into = 1 if abs(h.mouth - h.lo) < TOL else -1
    else:
        h.mouth = open_levels[0]
        h.into = 1 if abs(h.mouth - h.lo) < TOL else -1
    far = h.hi if h.into == 1 else h.lo
    h.depth = abs(far - h.mouth)
    if len(radii) == 1 and not cones:
        h.kind = "simple"
        h.d = 2 * radii[0]
    elif len(radii) == 2 and not cones and flats:
        big = max(cyls, key=lambda m: m.r)
        if min(abs(p[k] - h.mouth) for p in big.pts) > TOL:
            h.ok = False
            return h
        h.kind = "counterbore"
        h.d, h.cb_d = 2 * radii[0], 2 * radii[1]
        h.cb_depth = abs(flats[0].com[k] - h.mouth)
    elif len(radii) == 1 and len(cones) == 1 and cone_open:
        h.kind = "countersink"
        h.d = 2 * radii[0]
        mouth_edges = [o for o in cone_open if abs(o[0] - h.mouth) < TOL]
        if not mouth_edges:
            h.ok = False
            return h
        h.cb_d = 2 * mouth_edges[0][2]
        h.angle = 2.0 * math.degrees(cones[0].semi)
    else:
        h.ok = False
    return h


# ------------------------------------------------------------ patterns


def _cluster(vals: List[float]) -> List[float]:
    """Values that agree to 5 micrometres are one value (their mean)."""
    out: List[List[float]] = []
    for v in sorted(vals):
        if out and v - out[-1][-1] < 5e-3:
            out[-1].append(v)
        else:
            out.append([v])
    return [sum(c) / len(c) for c in out]


def _near(levels: List[float], v: float) -> int:
    return min(range(len(levels)), key=lambda i: abs(levels[i] - v))


def arrange(points: List[Tuple[float, float]]) -> Dict[str, Any]:
    """What the centres of identical features make: a grid, a circle, or
    just a list."""
    n = len(points)
    if n == 1:
        return {"type": "single"}
    us = _cluster([p[0] for p in points])
    vs = _cluster([p[1] for p in points])

    def even(vals):
        if len(vals) < 2:
            return 0.0
        step = vals[1] - vals[0]
        ok = all(abs((vals[i + 1] - vals[i]) - step) < 5e-3
                 for i in range(len(vals) - 1))
        return step if ok else None

    su, sv = even(us), even(vs)
    if su is not None and sv is not None and len(us) * len(vs) == n \
            and len({(_near(us, p[0]), _near(vs, p[1])) for p in points}) == n:
        return {"type": "grid", "origin": (us[0], vs[0]), "n1": len(us),
                "s1": su, "n2": len(vs), "s2": sv}
    if n >= 3:
        a, b, c = points[0], points[1], points[2]
        ax, ay = a
        bx, by = b
        cx, cy = c
        d = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
        if abs(d) > 1e-9:
            ux = ((ax * ax + ay * ay) * (by - cy)
                  + (bx * bx + by * by) * (cy - ay)
                  + (cx * cx + cy * cy) * (ay - by)) / d
            uy = ((ax * ax + ay * ay) * (cx - bx)
                  + (bx * bx + by * by) * (ax - cx)
                  + (cx * cx + cy * cy) * (bx - ax)) / d
            rad = math.hypot(ax - ux, ay - uy)
            if all(abs(math.hypot(p[0] - ux, p[1] - uy) - rad) < 5e-3
                   for p in points):
                ang = sorted(math.degrees(math.atan2(p[1] - uy, p[0] - ux))
                             % 360.0 for p in points)
                gaps = [(ang[(i + 1) % n] - ang[i]) % 360.0
                        for i in range(n)]
                if all(abs(g - 360.0 / n) < 0.05 for g in gaps):
                    first = min(points, key=lambda p: (
                        math.degrees(math.atan2(p[1] - uy, p[0] - ux))
                        % 360.0))
                    return {"type": "circle", "centre": (ux, uy),
                            "r": rad, "n": n, "first": first,
                            "angle": math.degrees(math.atan2(
                                first[1] - uy, first[0] - ux))}
    return {"type": "list"}


# ------------------------------------------------------------ recognition


class Rec:
    """Everything recognition found, kept for parametrize."""

    def __init__(self, shape) -> None:
        self.shape = shape
        self.fcs: List[Fc] = []
        self.adj: List[Dict[int, List[Any]]] = []
        self.blends: List[Blend] = []
        self.sharp = shape
        self.sharp_done = False
        self.fc0: List[Fc] = []
        self.adj0: List[Dict[int, List[Any]]] = []
        self.k: Optional[int] = None            # extrusion axis
        self.f = 1                              # direction profile -> far
        self.lvl_p = 0.0
        self.lvl_far = 0.0
        self.length = 0.0
        self.base_loops: List[Tuple[Dict, List[Dict]]] = []
        self.base_faces: List[int] = []
        self.holes: List[Hole] = []
        self.hole_groups: List[Dict[str, Any]] = []
        self.steps: List[Dict[str, Any]] = []
        self.bosses: List[Dict[str, Any]] = []
        self.explained: set = set()             # indices into fc0
        self.unexplained_why: Dict[int, str] = {}
        self.notes: List[str] = []
        self.prismatic = False
        self.boss_base: Optional[Dict[str, Any]] = None
        self.boss_level = 0.0
        self.axis_scores: List[Tuple[float, int]] = []
        self.box = (0.0,) * 6


def recognise_shape(shape, axis: Optional[int] = None) -> Rec:
    rec = Rec(shape)
    rec.fcs, rec.adj = _faces(shape)
    rec.blends = find_blends(rec.fcs, rec.adj)
    sharp = remove_blends(shape, rec.blends)
    if sharp is not None:
        rec.sharp = sharp
        rec.sharp_done = True
        locate_blends(rec.blends, sharp, rec.fcs, rec.adj)
        for b in list(rec.blends):
            if not b.located:
                rec.notes.append(
                    "a %s of %.4g mm could not be placed on the sharp body"
                    % (b.kind, b.value))
    else:
        if rec.blends:
            rec.notes.append("fillets and chamfers could not be taken off "
                             "the body; they stay unexplained")
        rec.blends = []
    rec.fc0, rec.adj0 = _faces(rec.sharp)
    rec.box = kernel.exact_bounding_box(rec.sharp)
    rec.holes = [h for h in find_holes(rec.fc0, rec.adj0)]
    interpret(rec, axis)
    return rec


def interpret(rec: Rec, axis: Optional[int] = None) -> None:
    """Read the sharp body as a prism along ``axis`` (the best if None)."""
    rec.k, rec.f, rec.prismatic = None, 1, False
    rec.steps, rec.bosses, rec.boss_base = [], [], None
    rec.explained, rec.unexplained_why, rec.hole_groups = set(), {}, []
    rec.base_loops, rec.base_faces, rec.length = [], [], 0.0
    _find_prism(rec, axis)
    _claim_holes(rec)
    if rec.prismatic:
        _find_steps(rec)
    _coverage(rec)


def _find_prism(rec: Rec, force: Optional[int] = None) -> None:
    fc = rec.fc0
    total = sum(f.area for f in fc) or 1.0
    scored = []
    for k in (2, 1, 0):
        lo, hi = rec.box[k], rec.box[k + 3]
        ends_lo = [f for f in fc if f.kind == "plane" and f.k == k
                   and abs(f.level - lo) < TOL and f.n[k] < 0]
        ends_hi = [f for f in fc if f.kind == "plane" and f.k == k
                   and abs(f.level - hi) < TOL and f.n[k] > 0]
        if not ends_lo or not ends_hi:
            continue
        score = 0.0
        for f in fc:
            if f.kind == "plane":
                score += f.area     # aligned or a vertical oblique wall
                if f.k is None and abs(f.n[k]) > 1e-6:
                    score -= f.area
            elif f.kind == "cyl" and f.k == k:
                score += f.area
            elif f.kind == "cyl" and not f.convex and f.k is not None:
                score += f.area     # a cross bore: a hole, not the prism
        scored.append((score, k, ends_lo, ends_hi))
    scored.sort(key=lambda t: -t[0])
    rec.axis_scores = [(round(sc / total, 4), k) for sc, k, _a, _b in scored]
    if force is not None:
        scored = [t for t in scored if t[1] == force]
    if not scored or (force is None and scored[0][0] < 0.5 * total):
        rec.notes.append("the body is not a prism along x, y or z")
        return
    _score, k, ends_lo, ends_hi = scored[0]
    rec.k = k
    area_lo = sum(_outer_area(f) for f in ends_lo)
    area_hi = sum(_outer_area(f) for f in ends_hi)
    if area_lo >= area_hi - 1e-6:
        rec.f, rec.lvl_p, rec.lvl_far = 1, rec.box[k], rec.box[k + 3]
        profile = ends_lo
    else:
        rec.f, rec.lvl_p, rec.lvl_far = -1, rec.box[k + 3], rec.box[k]
        profile = ends_hi
    rec.length = abs(rec.lvl_far - rec.lvl_p)
    rec.base_loops = [_loops(f, k) for f in profile]
    rec.prismatic = True
    rec.base_faces = [f.i for f in profile]


def _claim_holes(rec: Rec) -> None:
    for h in rec.holes:
        if h.ok:
            rec.explained.update(h.faces)
            for t in h.tips:
                rec.explained.discard(t)
                rec.unexplained_why[t] = ("the drill point at the bottom of "
                                          "a blind hole (the hole feature "
                                          "has a flat bottom)")
        else:
            for i in h.faces:
                rec.unexplained_why.setdefault(
                    i, "part of a hole stack this tool does not read "
                       "(an undercut or an odd stack)")
    for f in rec.fc0:
        if f.kind == "cyl" and not f.convex and f.k is None:
            rec.unexplained_why.setdefault(f.i, "a bore that is not along "
                                           "x, y or z")


def _on_loop(loop, p) -> bool:
    for sg in loop["segs"]:
        if sg["k"] == "L":
            ax, ay = sg["a"]
            bx, by = sg["b"]
            dx, dy = bx - ax, by - ay
            t = ((p[0] - ax) * dx + (p[1] - ay) * dy) / ((dx * dx + dy * dy)
                                                         or 1.0)
            t = max(0.0, min(1.0, t))
            if math.hypot(p[0] - ax - t * dx, p[1] - ay - t * dy) < 5 * TOL:
                return True
        elif sg["k"] in ("C", "A"):
            if abs(math.hypot(p[0] - sg["c"][0], p[1] - sg["c"][1])
                   - sg["r"]) < 5 * TOL:
                return True
    return False


def _find_steps(rec: Rec) -> None:
    """Flat faces across the axis at a level between the two ends."""
    k = rec.k
    lo, hi = min(rec.lvl_p, rec.lvl_far), max(rec.lvl_p, rec.lvl_far)
    claimed = set(rec.explained)
    for f in rec.fc0:
        if f.kind == "plane" and f.k == k and f.i not in claimed \
                and TOL < f.level - lo and f.level < hi - TOL:
            outer, inner = _loops(f, k)
            d = 1 if f.n[k] > 0 else -1             # its outward normal
            islands, openings = [], []
            for lp in inner:
                rises = falls = False
                for j, es in rec.adj0[f.i].items():
                    w = rec.fc0[j]
                    for e in es:
                        if _on_loop(lp, _uv(k, Ed(e).m)):
                            if w.hi[k] * d > f.level * d + TOL \
                                    if d > 0 else w.lo[k] < f.level - TOL:
                                rises = True
                            else:
                                falls = True
                (islands if rises and not falls else openings).append(lp)
            rec.steps.append({"face": f, "outer": outer, "inner": inner,
                              "islands": islands, "openings": openings,
                              "dir": d, "level": f.level})
    # a boss left standing: the step facing the far end whose outer loop is
    # the base outline and whose islands are topped at the far end
    far_faces = [f for f in rec.fc0 if f.kind == "plane" and f.k == k
                 and abs(f.level - rec.lvl_far) < TOL
                 and f.n[k] * rec.f > 0]
    tops = {_loop_key(_loops(f, k)[0]): f for f in far_faces}
    if len(rec.base_loops) != 1:
        return
    base_key = _loop_key(rec.base_loops[0][0])
    for s in rec.steps:
        if s["dir"] != rec.f or not s["islands"]:
            continue
        if _loop_key(s["outer"]) != base_key:
            continue
        keys = [_loop_key(l) for l in s["islands"]]
        if not all(kk in tops for kk in keys) or len(far_faces) != len(keys):
            continue
        rec.bosses = [{"loop": l, "face": tops[_loop_key(l)]}
                      for l in s["islands"]]
        rec.boss_base = s
        rec.steps.remove(s)
        rec.length = abs(s["level"] - rec.lvl_p)
        rec.boss_level = s["level"]
        break


def _coverage(rec: Rec) -> None:
    k = rec.k
    ex = rec.explained
    for b in rec.blends:
        if b.located:
            pass
    if rec.prismatic:
        lo, hi = min(rec.lvl_p, rec.lvl_far), max(rec.lvl_p, rec.lvl_far)
        for f in rec.fc0:
            if f.kind == "plane" and f.k == k and (
                    abs(f.level - lo) < TOL or abs(f.level - hi) < TOL):
                ex.add(f.i)
            elif f.kind == "plane" and f.k is None and abs(f.n[k]) < 1e-6:
                ex.add(f.i)
            elif f.kind == "plane" and f.k is not None and f.k != k:
                ex.add(f.i)
            elif f.kind == "cyl" and f.k == k and f.i not in ex \
                    and f.i not in rec.unexplained_why:
                ex.add(f.i)
        for s in rec.steps:
            ex.add(s["face"].i)
        if rec.boss_base is not None:
            ex.add(rec.boss_base["face"].i)
    # what the blends explain is counted from the original body
    for f in rec.fc0:
        if f.i not in ex and f.i not in rec.unexplained_why:
            if f.kind == "plane" and f.k is None:
                rec.unexplained_why[f.i] = "an oblique plane"
            elif f.kind == "cyl" and f.k is not None and not rec.prismatic:
                rec.unexplained_why[f.i] = "a cylinder (no base found)"
            elif f.kind in ("cone", "sphere", "torus"):
                rec.unexplained_why[f.i] = "a %s face" % f.kind
            elif f.kind == "other":
                rec.unexplained_why[f.i] = "a freeform surface"
            elif f.kind == "cyl":
                rec.unexplained_why[f.i] = ("a cylinder that is neither a "
                                            "bore nor along the base axis")
            else:
                rec.unexplained_why[f.i] = "a face no feature explains"
    # the hole groups, with arrangements
    groups: Dict[Tuple, List[Hole]] = {}
    for h in rec.holes:
        if h.ok:
            groups.setdefault(h.key(), []).append(h)
    for key, hs in groups.items():
        pts = [h.uv for h in hs]
        arr = arrange(pts)
        rec.hole_groups.append({"holes": hs, "arrange": arr})


# ------------------------------------------------------------ the plan


class Unplannable(Exception):
    pass


class Book:
    """Parameter names that do not clash with each other or the part's."""

    def __init__(self, existing: Sequence[str] = (),
                 rename: Optional[Dict[str, str]] = None) -> None:
        self.names = set(existing)
        self.ops: List[Dict[str, Any]] = []
        self.values: Dict[str, Any] = {}
        self.rename = dict(rename or {})

    def add(self, base: str, value: Any, comment: str = "",
            unit: str = "mm") -> str:
        name = self.rename.get(base, base)
        n = 2
        stem = name
        while name in self.names:
            name = "%s_%d" % (stem, n)
            n += 1
        self.names.add(name)
        op_ = {"op": "parameter", "name": name,
               "value": _r(value, 6) if isinstance(value, float) else value,
               "comment": comment}
        if unit != "mm":
            op_["unit"] = unit
        self.ops.append(op_)
        self.values[name] = op_["value"]
        return name


def _segment_entities(loop, prefix: str, express=None
                      ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Sketch entities and constraints that draw a loop."""
    segs = loop["segs"]
    if len(segs) == 1 and segs[0]["k"] == "C":
        s = segs[0]
        return [{"circle": {"center": [_r(s["c"][0], 5), _r(s["c"][1], 5)],
                            "d": _r(2 * s["r"], 5)}, "id": prefix}], []
    ex = express or (lambda axis, v: _r(v, 5))
    if all(s["k"] == "L" for s in segs):
        pts = [[ex(0, s["a"][0]), ex(1, s["a"][1])] for s in segs]
        return [{"polyline": pts, "closed": True, "id": prefix}], []
    ents, cons = [], []
    ends = []
    for i, s in enumerate(segs):
        eid = "%s_%d" % (prefix, i)
        if s["k"] == "L":
            ents.append({"line": [[_r(s["a"][0], 5), _r(s["a"][1], 5)],
                                  [_r(s["b"][0], 5), _r(s["b"][1], 5)]],
                         "id": eid})
            ends.append((eid + ".start", eid + ".end"))
        elif s["k"] == "A":
            ents.append({"arc": {"center": [_r(s["c"][0], 5),
                                            _r(s["c"][1], 5)],
                                 "r": _r(s["r"], 5), "start": _r(s["s"], 4),
                                 "end": _r(s["e"], 4)}, "id": eid})
            ends.append((eid + ".start", eid + ".end") if s["ccw"]
                        else (eid + ".end", eid + ".start"))
        else:
            raise Unplannable("an outline edge that is neither a line nor "
                              "an arc")
    for i, (_a, b) in enumerate(ends):
        cons.append({"coincident": [b, ends[(i + 1) % len(ends)][0]]})
    return ents, cons


def _rectilinear(loop) -> bool:
    segs = loop["segs"]
    if not all(s["k"] == "L" for s in segs):
        return False
    return all(abs(s["a"][0] - s["b"][0]) < 1e-6
               or abs(s["a"][1] - s["b"][1]) < 1e-6 for s in segs)


class Plan:
    def __init__(self) -> None:
        self.ops: List[Dict[str, Any]] = []
        self.params: Dict[str, Any] = {}
        self.features: List[Dict[str, Any]] = []


def make_plan(rec: Rec, existing: Sequence[str] = (),
              rename: Optional[Dict[str, str]] = None) -> Plan:
    if not rec.prismatic or not rec.base_loops:
        raise Unplannable("no base: the body is not a prism along x, y or z")
    k, f = rec.k, rec.f
    ps = PLANE_SIGN[k]
    P = Book(existing, rename)
    body: List[Dict[str, Any]] = []
    plan = Plan()
    ua, va = LET[UV[k][0]], LET[UV[k][1]]
    dims = sorted(rec.box[c + 3] - rec.box[c] for c in range(3))
    L = rec.length
    tname = P.add("thickness" if abs(L - dims[0]) < 1e-6 else "length", L,
                  "base extrusion length along %s" % LET[k])
    levels: List[Tuple[float, str]] = []     # coordinate -> offset expression
    p_expr = _num(ps * rec.lvl_p)
    levels.append((rec.lvl_p, p_expr))
    far_expr = "(%s) + (%d) * %s" % (p_expr, ps * f, tname)
    boss_mode = bool(rec.bosses)
    bh = ""
    if boss_mode:
        # the bosses are joined from the shoulder: far end = shoulder + height
        bh = P.add("boss_height", abs(rec.lvl_far - rec.boss_level),
                   "boss height above the plate")
        levels.append((rec.boss_level, far_expr))
        far_expr = "(%s) + (%d) * %s" % (far_expr, ps * f, bh)
    levels.append((rec.lvl_far, far_expr))

    def off(coord: float, axis: int) -> str:
        if axis == k:
            for c, e in levels:
                if abs(c - coord) < TOL:
                    return e
        return _num(PLANE_SIGN[axis] * coord)

    def wp(wid: str, axis: int, coord: float, name: str) -> None:
        body.append({"op": "workplane", "id": wid, "base": SKETCH_PLANE[axis],
                     "offset": off(coord, axis), "name": name})

    def rev(world_dir: int) -> bool:
        return world_dir != ps

    # ---- the base
    wp("wp_base", k, rec.lvl_p, "Base plane")
    ents: List[Dict[str, Any]] = []
    cons: List[Dict[str, Any]] = []
    far_keys = set()
    for fc in rec.fc0:
        if fc.kind == "plane" and fc.k == k and abs(fc.level - rec.lvl_far) \
                < TOL and fc.n[k] * f > 0:
            o, ins = _loops(fc, k)
            far_keys.add(_loop_key(o))
            far_keys.update(_loop_key(x) for x in ins)
    mouth_circles = set()
    for h in rec.holes:
        if h.ok and h.k == k:
            for lv, uv, r in h.mouths:
                if abs(lv - rec.lvl_p) < TOL:
                    mouth_circles.add(("C", _r(uv[0], 2), _r(uv[1], 2),
                                       _r(r, 2)))
    express = None
    if len(rec.base_loops) == 1 and _rectilinear(rec.base_loops[0][0]):
        us = sorted({_r(s["a"][0], 5) for s in rec.base_loops[0][0]["segs"]})
        vs = sorted({_r(s["a"][1], 5) for s in rec.base_loops[0][0]["segs"]})
        if len(us) + len(vs) <= 10:
            tabs = []
            for vals, letter in ((us, ua), (vs, va)):
                names = []
                for j in range(1, len(vals)):
                    nm = ("%s_size" % letter) if len(vals) == 2 else \
                        "%s_step%d" % (letter, j)
                    names.append(P.add(nm, vals[j] - vals[j - 1],
                                       "profile: %s from %s to %s"
                                       % (letter, _num(vals[j - 1]),
                                          _num(vals[j]))))
                tabs.append((vals, names))

            def express(axis_i, v, tabs=tabs):
                vals, names = tabs[axis_i]
                j = min(range(len(vals)), key=lambda t: abs(vals[t] - v))
                if j == 0:
                    return _r(vals[0], 5)
                return "%s + %s" % (_num(vals[0]), " + ".join(names[:j]))
    n_loops = 0
    for outer, inner in rec.base_loops:
        e, c = _segment_entities(outer, "o%d" % n_loops, express)
        ents += e
        cons += c
        n_loops += 1
        for lp in inner:
            key = _loop_key(lp)
            if key in mouth_circles:
                continue
            if key not in far_keys:
                continue            # a blind pocket: its floor will cut it
            e, c = _segment_entities(lp, "i%d" % n_loops)
            ents += e
            cons += c
            n_loops += 1
    sk = {"op": "sketch", "id": "sk_base", "plane": "$wp_base",
          "name": "Base profile", "entities": ents}
    if cons:
        sk["constraints"] = cons
    body.append(sk)
    body.append({"op": "extrude", "id": "base", "sketch": "$sk_base",
                 "distance": tname, "reversed": rev(f), "name": "Base"})
    plan.features.append({
        "id": "base", "type": "extrude", "name": "Base",
        "axis": LET[k], "length": _r(L, 4),
        "outline": "%d loop(s), %d edge(s)" % (
            n_loops, sum(len(lp["segs"]) for o, i in rec.base_loops
                         for lp in [o] + i)),
        "parameters": [tname]})

    def pattern_ops(arr, parent: str, label: str, short: str,
                    pitch_base: str, count_base: str, k_: int
                    ) -> Tuple[List[Dict], List[str], Any]:
        """Pattern ops for ``arr``; returns (ops, parameters, first point)."""
        extra: List[Dict[str, Any]] = []
        used: List[str] = []
        first = None
        if arr["type"] == "grid":
            o = arr["origin"]
            first = [_r(o[0], 5), _r(o[1], 5)]
            spec = {"op": "pattern", "mode": "rectangular",
                    "parents": ["$" + parent], "name": label + " pattern"}
            u_axis, v_axis = LET[UV[k_][0]].upper(), LET[UV[k_][1]].upper()
            if arr["n1"] > 1:
                cn = P.add(count_base, arr["n1"], "%s: how many" % label,
                           "ul")
                pn = P.add(pitch_base, abs(arr["s1"]),
                           "%s: spacing along %s" % (label, u_axis.lower()))
                spec.update({"dir1": u_axis, "count1": cn, "spacing1": pn})
                used += [cn, pn]
                if arr["n2"] > 1:
                    cn2 = P.add(count_base + "_2", arr["n2"],
                                "%s: how many the other way" % label, "ul")
                    pn2 = P.add(pitch_base + "_2", abs(arr["s2"]),
                                "%s: spacing along %s"
                                % (label, v_axis.lower()))
                    spec.update({"dir2": v_axis, "count2": cn2,
                                 "spacing2": pn2})
                    used += [cn2, pn2]
            else:
                cn = P.add(count_base, arr["n2"], "%s: how many" % label,
                           "ul")
                pn = P.add(pitch_base, abs(arr["s2"]),
                           "%s: spacing along %s" % (label, v_axis.lower()))
                spec.update({"dir1": v_axis, "count1": cn, "spacing1": pn})
                used += [cn, pn]
            extra.append(spec)
        else:           # a circle
            cu, cv = arr["centre"]
            rn = P.add(short + "_circle_r", arr["r"],
                       "%s: radius of the circle they sit on" % label)
            cn = P.add(count_base, arr["n"], "%s: how many" % label, "ul")
            used += [rn, cn]
            first = ["%s + %s * cos(%s)" % (_num(cu), rn,
                                            _num(arr["angle"])),
                     "%s + %s * sin(%s)" % (_num(cv), rn,
                                            _num(arr["angle"]))]
            (a_axis, a_coord), (b_axis, b_coord) = _axis_planes(k_, cu, cv)
            extra += [
                {"op": "workplane", "id": parent + "_pa", "base": a_axis,
                 "offset": _num(a_coord), "name": label + " axis plane A"},
                {"op": "workplane", "id": parent + "_pb", "base": b_axis,
                 "offset": _num(b_coord), "name": label + " axis plane B"},
                {"op": "workaxis", "id": parent + "_ax", "mode": "planes",
                 "plane_a": "$" + parent + "_pa",
                 "plane_b": "$" + parent + "_pb",
                 "name": label + " axis"},
                {"op": "pattern", "mode": "circular", "id": parent + "_pat",
                 "parents": ["$" + parent], "count1": cn,
                 "axis": "$" + parent + "_ax", "name": label + " pattern"}]
        return extra, used, first

    # ---- bosses (joined from the shoulder)
    if boss_mode:
        groups: Dict[Tuple, List[Dict[str, Any]]] = {}
        for b in rec.bosses:
            if _is_circle(b["loop"]):
                key = ("C", _r(b["loop"]["segs"][0]["r"], 3))
            else:
                key = ("P", id(b))
            groups.setdefault(key, []).append(b)
        n = 0
        for key, bs in groups.items():
            n += 1
            wid, sid, eid = "wp_boss%d" % n, "sk_boss%d" % n, "boss%d" % n
            wp(wid, k, rec.boss_level, "Boss %d plane" % n)
            used = [bh]
            if key[0] == "C":
                dn = P.add("boss_d" if n == 1 else "boss%d_d" % n,
                           2 * key[1], "boss diameter")
                used.append(dn)
                pts = [b["loop"]["segs"][0]["c"] for b in bs]
                arr = arrange(pts) if len(pts) > 1 else {"type": "single"}
                extra: List[Dict[str, Any]] = []
                if arr["type"] in ("grid", "circle"):
                    extra, pu, first = pattern_ops(
                        arr, eid, "Boss %d" % n, "boss", "boss_pitch",
                        "boss_count", k)
                    used += pu
                    centres = [first]
                else:
                    centres = [[_r(c[0], 5), _r(c[1], 5)] for c in pts]
                body.append({"op": "sketch", "id": sid, "plane": "$" + wid,
                             "name": "Boss %d sketch" % n, "entities": [
                                 {"circle": {"center": c, "d": dn},
                                  "id": "c%d" % i}
                                 for i, c in enumerate(centres)]})
                body.append({"op": "extrude", "id": eid, "sketch": "$" + sid,
                             "distance": bh, "operation": "join",
                             "reversed": rev(f), "name": "Boss %d" % n})
                body += extra
                plan.features.append({
                    "id": eid, "type": "boss", "name": "Boss %d" % n,
                    "shape": "round", "diameter": _r(2 * key[1], 4),
                    "count": len(bs), "arrangement": arr["type"],
                    "parameters": used})
            else:
                b = bs[0]
                e, c = _segment_entities(b["loop"], "b%d" % n)
                sk2 = {"op": "sketch", "id": sid, "plane": "$" + wid,
                       "name": "Boss %d sketch" % n, "entities": e}
                if c:
                    sk2["constraints"] = c
                body.append(sk2)
                body.append({"op": "extrude", "id": eid, "sketch": "$" + sid,
                             "distance": bh, "operation": "join",
                             "reversed": rev(f), "name": "Boss %d" % n})
                plan.features.append({
                    "id": eid, "type": "boss", "name": "Boss %d" % n,
                    "shape": "outline", "count": 1, "parameters": used})

    # ---- steps: pockets, and shoulders round something that stands
    lo, hi = min(rec.lvl_p, rec.lvl_far), max(rec.lvl_p, rec.lvl_far)
    n = 0
    step_levels: List[Tuple[float, str]] = []
    for s in sorted(rec.steps, key=lambda s: -abs(s["level"] - (
            hi if s["dir"] > 0 else lo))):
        n += 1
        d_ = s["dir"]
        end = hi if d_ > 0 else lo
        if boss_mode and d_ == f:
            end = rec.boss_level        # cut from the shoulder, not the top
        depth = abs(end - s["level"])
        dn = P.add("pocket%d_depth" % n if n > 1 else "pocket_depth", depth,
                   "depth of the cut from the %s end"
                   % ("shoulder" if boss_mode and d_ == f else
                      "far" if end == rec.lvl_far else "near"))
        wid, sid, eid = "wp_step%d" % n, "sk_step%d" % n, "step%d" % n
        wp(wid, k, end, "Cut %d plane" % n)
        end_expr = off(end, k)
        step_levels.append((s["level"], "(%s) - (%d) * %s" % (
            end_expr, ps * d_, dn)))
        e, c = _segment_entities(s["outer"], "s%d" % n)
        for j, lp in enumerate(s["islands"]):
            e2, c2 = _segment_entities(lp, "s%d_%d" % (n, j))
            e += e2
            c += c2
        sk2 = {"op": "sketch", "id": sid, "plane": "$" + wid,
               "name": "Cut %d sketch" % n, "entities": e}
        if c:
            sk2["constraints"] = c
        body.append(sk2)
        label = "Pocket %d" % n if not s["islands"] else "Step %d" % n
        body.append({"op": "extrude", "id": eid, "sketch": "$" + sid,
                     "distance": dn, "operation": "cut", "reversed": rev(-d_),
                     "name": label})
        plan.features.append({
            "id": eid, "type": "pocket" if not s["islands"] else "step",
            "name": label, "depth": _r(depth, 4),
            "from": ("the shoulder" if boss_mode and d_ == f else
                     "far end" if end == rec.lvl_far else "near end"),
            "parameters": [dn],
            "note": "" if not s["islands"] else
            "a shoulder: material is left standing inside it"})
    levels += step_levels

    # ---- holes
    for gi, grp in enumerate(rec.hole_groups, start=1):
        hs: List[Hole] = grp["holes"]
        h0 = hs[0]
        arr = grp["arrange"]
        hk = h0.k
        mouth = h0.mouth
        if h0.through and h0.kind == "simple":
            # the end that is a known level, if either is
            for c in (h0.lo, h0.hi):
                if hk == k and any(abs(c - lv) < TOL for lv, _e in levels):
                    mouth = c
                    break
        sfx = "" if gi == 1 else str(gi)
        wid, sid, hid = "wp_hole%d" % gi, "sk_hole%d" % gi, "hole%d" % gi
        wp(wid, hk, mouth, "Hole %d plane" % gi)
        used = []
        dn = P.add("hole%s_d" % sfx, h0.d, "hole %d diameter" % gi)
        used.append(dn)
        spec: Dict[str, Any] = {"op": "hole", "id": hid, "sketch": "$" + sid,
                                "diameter": dn, "name": "Hole %d" % gi}
        if h0.through:
            spec["through"] = True
        else:
            dp = P.add("hole%s_depth" % sfx, h0.depth,
                       "hole %d depth" % gi)
            spec.update({"through": False, "depth": dp})
            used.append(dp)
        if h0.kind == "counterbore":
            cd = P.add("hole%s_cb_d" % sfx, h0.cb_d, "counterbore diameter")
            cz = P.add("hole%s_cb_depth" % sfx, h0.cb_depth,
                       "counterbore depth")
            spec.update({"hole_type": "counterbore", "cb_diameter": cd,
                         "cb_depth": cz})
            used += [cd, cz]
        elif h0.kind == "countersink":
            cd = P.add("hole%s_csk_d" % sfx, h0.cb_d, "countersink diameter")
            ca = P.add("hole%s_csk_angle" % sfx, h0.angle,
                       "countersink angle", "deg")
            spec.update({"hole_type": "countersink", "cb_diameter": cd,
                         "cs_angle": ca})
            used += [cd, ca]
        extra = []
        if arr["type"] in ("grid", "circle"):
            extra, pu, first = pattern_ops(
                arr, hid, "Hole %d" % gi, "hole%s" % sfx,
                "pitch" if gi == 1 else "pitch%d" % gi,
                "hole_count" if gi == 1 else "hole%d_count" % gi, hk)
            used += pu
            pts = [first]
        else:
            pts = [[_r(h.uv[0], 5), _r(h.uv[1], 5)] for h in hs]
        ids = ["p%d" % (i + 1) for i in range(len(pts))]
        body.append({"op": "sketch", "id": sid, "plane": "$" + wid,
                     "name": "Hole %d centres" % gi,
                     "entities": [{"point": c, "id": i}
                                  for c, i in zip(pts, ids)]})
        spec["points"] = ids
        body.append(spec)
        body += extra
        plan.features.append({
            "id": hid, "type": "hole", "name": "Hole %d" % gi,
            "kind": h0.kind, "diameter": _r(h0.d, 4),
            "through": h0.through, "depth": None if h0.through
            else _r(h0.depth, 4), "axis": LET[hk],
            "count": len(hs), "arrangement": arr["type"],
            "counterbore_d": _r(h0.cb_d, 4) if h0.kind == "counterbore"
            else None, "counterbore_depth": _r(h0.cb_depth, 4)
            if h0.kind == "counterbore" else None,
            "countersink_d": _r(h0.cb_d, 4) if h0.kind == "countersink"
            else None, "countersink_angle": _r(h0.angle, 3)
            if h0.kind == "countersink" else None,
            "parameters": used})

    # ---- chamfers and fillets last
    gcount = {"fillet": 0, "chamfer": 0}
    byval: Dict[Tuple, List[Blend]] = {}
    for b in rec.blends:
        if b.located:
            byval.setdefault((b.kind, _r(b.value, 3)), []).append(b)
    for (kind, value), bl in sorted(byval.items(),
                                    key=lambda kv: (kv[0][0] != "chamfer",
                                                    kv[0][1])):
        gcount[kind] += 1
        n = gcount[kind]
        picks: List[Any] = []
        for b in bl:
            for e in b.edges:
                if not any(e.IsSame(x) for x in picks):
                    picks.append(e)
        query = _edge_query(rec.sharp, picks)
        pname = P.add(("fillet_r" if kind == "fillet" else "chamfer_d")
                      + ("" if n == 1 else str(n)), bl[0].value,
                      "%s %s" % (kind, "radius" if kind == "fillet"
                                 else "distance"))
        spec = {"op": kind, "id": "%s%d" % (kind, n), "edges": query,
                "name": "%s %d" % (kind.title(), n)}
        spec["radius" if kind == "fillet" else "distance"] = pname
        body.append(spec)
        plan.features.append({
            "id": spec["id"], "type": kind, "name": spec["name"],
            "radius" if kind == "fillet" else "distance": _r(bl[0].value, 4),
            "edges": len(picks), "selected_by": "rule" if isinstance(
                query, dict) else "position",
            "concave": any(b.concave for b in bl),
            "parameters": [pname]})
    plan.ops = P.ops + body
    plan.params = dict(P.values)
    return plan


def _axis_planes(k: int, cu: float, cv: float):
    """Two origin-plane offsets whose meeting line runs along axis k through
    (cu, cv) of that axis's sketch frame."""
    if k == 2:      # x = cu, y = cv
        return ("YZ", cu), ("XZ", -cv)
    if k == 1:      # x = cu, z = cv
        return ("YZ", cu), ("XY", cv)
    return ("XZ", -cu), ("XY", cv)      # k == 0: y = cu, z = cv


def _edge_query(sharp, picks: List[Any]):
    """The shortest rule that finds exactly ``picks`` on the sharp body."""
    cands: List[Any] = [{"along": a} for a in LET]
    for s in "+-":
        for a in LET:
            cands.append({"at": s + a})
    for q in cands:
        try:
            got = edgequery.edges(sharp, q)
        except edgequery.QueryError:
            continue
        if len(got) == len(picks) and all(
                any(g.IsSame(p) for p in picks) for g in got):
            return q
    return [{"near": [_r(c, 4) for c in kernel.shape_centre(e)], "count": 1}
            for e in picks]


# ------------------------------------------------------------ checking


MAX_FACES = 5000


def _compare(original, rebuilt) -> Dict[str, Any]:
    """Volume, box and the boolean difference both ways."""
    v0, v1 = kernel.volume(original), kernel.volume(rebuilt)
    b0 = kernel.exact_bounding_box(original)
    b1 = kernel.exact_bounding_box(rebuilt)
    box_gap = max(abs(a - b) for a, b in zip(b0, b1))
    try:
        only_old = kernel.volume(kernel.boolean(original, rebuilt, "cut"))
        only_new = kernel.volume(kernel.boolean(rebuilt, original, "cut"))
    except Exception:                                       # noqa: BLE001
        only_old = only_new = abs(v0 - v1)
    return {"volume_original": v0, "volume_rebuilt": v1,
            "only_in_original": only_old, "only_in_rebuilt": only_new,
            "residual": only_old + only_new, "box_gap": box_gap}


def _match_faces(orig_fcs: List[Fc], new_fcs: List[Fc]) -> List[bool]:
    """Which faces of the original have a twin in the rebuilt body."""
    out = []
    for f in orig_fcs:
        hit = False
        for g in new_fcs:
            if g.kind != f.kind:
                continue
            if abs(g.area - f.area) > 1e-3 * f.area + 1e-3:
                continue
            if _norm(_sub(g.com, f.com)) > 0.01:
                continue
            if f.kind == "plane" and _dot(f.n, g.n) < 0.9999:
                continue
            if f.kind in ("cyl", "sphere", "torus") and \
                    abs(f.r - g.r) > 1e-3:
                continue
            hit = True
            break
        out.append(hit)
    return out


def scratch_build(plan: Plan, units: Any = None) -> Tuple[Any, Dict[str, Any]]:
    """The plan built in a document of its own; (shape, build answer)."""
    ws = Workspace()
    doc = Document()
    if units is not None:
        doc.units = units
    entry = ws.add(doc)
    try:
        res = ops.build(ws, ops=plan.ops, doc=entry.handle)
    except BridgeError as exc:
        return None, {"ok": False, "error": {"kind": exc.kind,
                                             "message": str(exc)}}
    shapes = [b.shape for b in doc.bodies if b.valid and b.shape is not None]
    return (shapes[0] if len(shapes) == 1 else None), res


def _pick_body(d: Document, body: Optional[str]):
    live = [b for b in d.bodies if b.valid and b.shape is not None
            and not b.shape.IsNull()]
    if not live:
        raise BridgeError("NO_BODY", "the part has no solid to recognise",
                          ["Import a STEP file first: "
                           "build [{\"op\":\"import\",\"path\":...}]."])
    if body:
        for b in live:
            if b.name == body:
                return b.shape, b
        raise BridgeError("BAD_VALUE", "no body %r (the bodies are: %s)"
                          % (body, ", ".join(b.name for b in live)))
    if len(live) > 1:
        raise BridgeError(
            "AMBIGUOUS", "the part has %d bodies: %s"
            % (len(live), ", ".join(b.name for b in live)),
            ["Name one with body=, or split the import into parts."])
    return live[0].shape, live[0]


def _faces_count(shape) -> int:
    return kernel.face_count(shape)


def analyse(shape, existing: Sequence[str] = (), rename=None,
            check: bool = True, units: Any = None) -> Dict[str, Any]:
    """Recognise, plan, rebuild in a scratch document and compare."""
    n = _faces_count(shape)
    if n > MAX_FACES:
        raise BridgeError("TOO_COMPLEX", "%d faces (the most read is %d)"
                          % (n, MAX_FACES),
                          ["Recognition reads prismatic parts of a few "
                           "hundred faces; split a large import first."])
    t0 = time.perf_counter()
    rec = recognise_shape(shape)
    tries = [rec.k] if rec.k is not None else [None]
    if rec.k is not None and check:
        # a prism along another axis may reproduce the body better (a block
        # with a cross pocket reads equally well three ways)
        top = rec.axis_scores[0][0]
        tries += [k for sc, k in rec.axis_scores[1:] if sc >= top - 0.02]
    best: Optional[Dict[str, Any]] = None
    for k in tries:
        if k is not None and k != rec.k:
            interpret(rec, k)
        out = _one(rec, shape, existing, rename, check, units)
        cmp_ = out.get("compare")
        pl = out.get("plan")
        vol = max(cmp_["volume_original"], 1.0) if cmp_ else 1.0
        exact = bool(cmp_) and cmp_["residual"] <= 1e-6 * vol
        # the closest first; among exact ones the fewest features
        score = (0 if exact else 1,
                 0.0 if exact else (cmp_["residual"] if cmp_ else 1e30),
                 len(pl.features) if pl else 1e9)
        if best is None or score < best["_score"]:
            out["_score"] = score
            out["_axis"] = rec.k
            best = out
    if best is not None and best["_axis"] != rec.k:
        interpret(rec, best["_axis"])
        best = _one(rec, shape, existing, rename, check, units)
    best["rec"] = rec
    best["seconds"] = round(time.perf_counter() - t0, 2)
    return best


def _one(rec: Rec, shape, existing, rename, check, units) -> Dict[str, Any]:
    out: Dict[str, Any] = {"rec": rec, "plan": None, "built": None,
                           "compare": None, "why": None}
    try:
        plan = make_plan(rec, existing, rename)
    except Unplannable as exc:
        out["why"] = str(exc)
        return out
    out["plan"] = plan
    if check:
        new, res = scratch_build(plan, units)
        out["build"] = res
        if new is None:
            out["why"] = ("the recognised tree did not build: %s"
                          % ((res.get("error") or {}).get("message")
                             or "no single solid"))
        else:
            out["built"] = new
            out["compare"] = _compare(shape, new)
    return out


def _coverage_numbers(rec: Rec, built) -> Dict[str, Any]:
    """The share of the faces explained, counted on the original body: a
    face is explained when the rebuilt body has the same face. Without a
    rebuilt body, what the recogniser claimed."""
    fcs = rec.fcs
    total_area = sum(f.area for f in fcs) or 1.0
    if built is not None:
        new_fcs, _ = _faces(built)
        match = _match_faces(fcs, new_fcs)
        basis = "rebuilt"
    else:
        claimed = set(rec.explained)
        blend_faces = {id(f.face) for b in rec.blends if b.located
                       for f in b.faces}
        match = [(f.i in claimed and False) or (id(f.face) in blend_faces)
                 for f in fcs]
        basis = "claimed"
    got = sum(1 for m in match if m)
    area = sum(f.area for f, m in zip(fcs, match) if m)
    return {"basis": basis, "faces": {"explained": got, "total": len(fcs),
                                      "share": _r(got / max(1, len(fcs)), 4)},
            "area": {"explained": _r(area, 3), "total": _r(total_area, 3),
                     "share": _r(area / total_area, 4)},
            "match": match}


def _unexplained(entry: Entry, rec: Rec, cov: Dict[str, Any], shape,
                 limit: int = 20) -> List[Dict[str, Any]]:
    out = []
    flist = kernel.faces(shape)
    for f, m in zip(rec.fcs, cov["match"]):
        if m:
            continue
        why = "no recognised feature reproduces this face"
        # the reason, from the sharp body's reading when it has one
        for g in rec.fc0:
            if g.kind == f.kind and _norm(_sub(g.com, f.com)) < 0.01 \
                    and g.i in rec.unexplained_why:
                why = rec.unexplained_why[g.i]
                break
        row = f.describe()
        row["why"] = why
        try:
            row["handle"] = refs_mod.handle_for(entry, flist[f.i], "face",
                                                shape)
        except Exception:                                   # noqa: BLE001
            pass
        out.append(row)
        if len(out) >= limit:
            break
    return out


def _report(entry: Entry, shape, got: Dict[str, Any], detail: bool
            ) -> Dict[str, Any]:
    rec: Rec = got["rec"]
    plan: Optional[Plan] = got["plan"]
    cov = _coverage_numbers(rec, got.get("built"))
    cmp_ = got.get("compare")
    out: Dict[str, Any] = {
        "ok": True, "prismatic": rec.prismatic,
        "axis": LET[rec.k] if rec.k is not None else None,
        "features": plan.features if plan else [],
        "coverage": {k: v for k, v in cov.items() if k != "match"},
        "unexplained": _unexplained(entry, rec, cov, shape),
        "notes": list(rec.notes),
    }
    if got.get("why"):
        out["notes"].append(got["why"])
    if plan:
        out["parameters"] = plan.params
    if cmp_:
        vol = max(cmp_["volume_original"], 1e-9)
        out["check"] = {
            "volume_original": _r(cmp_["volume_original"], 3),
            "volume_rebuilt": _r(cmp_["volume_rebuilt"], 3),
            "residual_volume": _r(cmp_["residual"], 4),
            "residual_share": _r(cmp_["residual"] / vol, 6),
            "only_in_original": _r(cmp_["only_in_original"], 4),
            "only_in_rebuilt": _r(cmp_["only_in_rebuilt"], 4),
            "bbox_gap": _r(cmp_["box_gap"], 5)}
    if detail and plan:
        out["ops"] = plan.ops
    share = cov["faces"]["share"]
    feat = plan.features if plan else []
    counts: Dict[str, int] = {}
    for f_ in feat:
        counts[f_["type"]] = counts.get(f_["type"], 0) + max(
            1, f_.get("count") or 1) if f_["type"] == "hole" else \
            counts.get(f_["type"], 0) + 1
    bits = ["%d %s%s" % (v, t, "" if v == 1 else "s")
            for t, v in counts.items() if t != "extrude"]
    base = "base: prism along %s, %.4g long" % (
        LET[rec.k], rec.length) if rec.prismatic else "no base found"
    out["summary"] = ("recognize ok | %s | %s | %d/%d faces explained "
                      "(%.0f %% of the area)%s" % (
                          base, ", ".join(bits) or "no other features",
                          cov["faces"]["explained"], cov["faces"]["total"],
                          100 * cov["area"]["share"],
                          "" if cmp_ is None else " | residual %.4g mm3"
                          % cmp_["residual"]))
    return out


# ------------------------------------------------------------ the ops


@op
def recognize(ws: Workspace, doc: str = "", body: Optional[str] = None,
              detail: bool = False, check: bool = True) -> Dict[str, Any]:
    """Read a dumb solid and report the features it is made of. Changes
    nothing."""
    entry = ws.get(doc)
    d = ops._need_part(entry)
    shape, b = _pick_body(d, body)
    got = analyse(shape, existing=list(d.params.names())
                  if hasattr(d.params, "names") else [], check=check,
                  units=d.units)
    out = _report(entry, shape, got, detail)
    out["doc"] = entry.handle
    out["body"] = b.name
    out["revision"] = entry.revision
    return out


def _tolerance(vol: float, tol: float) -> float:
    return max(1e-6, tol * vol)


@op
def parametrize(ws: Workspace, doc: str = "", body: Optional[str] = None,
                plan: Optional[Dict[str, Any]] = None, verify: bool = True,
                tolerance: float = 0.001, dry_run: bool = False,
                detail: bool = False, replace_tree: bool = False,
                expected_revision: Optional[int] = None) -> Dict[str, Any]:
    """Rebuild a dumb solid as an editable feature tree, or refuse.

    A part that already has a feature tree (anything besides imported
    bodies) is only rewritten with replace_tree=true: its features, sketches
    and everything standing on them are removed first.

    Partial coverage is refused (nothing changes): a tree that does not
    reproduce the body is not offered as if it did. The answer says what
    could not be explained."""
    entry = ws.get(doc)
    d = ops._need_part(entry)
    ops._check_revision(entry, expected_revision)
    shape, b = _pick_body(d, body)
    live = [x for x in d.bodies if x.valid and x.shape is not None]
    if len(live) > 1:
        raise BridgeError("AMBIGUOUS", "the part has %d bodies; parametrize "
                          "rewrites the whole tree" % len(live),
                          ["Split the import so each part has one body."])
    plan_in = plan or {}
    rename = plan_in.get("names") or plan_in.get("rename")
    user_ops = plan_in.get("ops")
    keep = [n for n in d.params.names()] if hasattr(d.params, "names") else []
    got = analyse(shape, existing=keep, rename=rename, check=bool(verify),
                  units=d.units)
    if user_ops:
        # the agent's own ops stand in for the recognised ones
        p2 = Plan()
        p2.ops = list(user_ops)
        new, res = scratch_build(p2, d.units)
        got["plan"], got["built"] = p2, new
        got["compare"] = _compare(shape, new) if new is not None else None
        got["why"] = None if new is not None else "the given ops did not build"
    report = _report(entry, shape, got, detail)
    rec: Rec = got["rec"]
    p: Optional[Plan] = got["plan"]
    cmp_ = got.get("compare")
    report["policy"] = ("partial coverage is refused (nothing is changed); "
                        "see docs/MCP.md")

    def refuse(kind: str, message: str, hints: List[str]) -> None:
        report["ok"] = False
        report["refused"] = True
        report["summary"] = "parametrize REFUSED: %s | %s" % (
            message, report["summary"].split("| ", 1)[-1])
        raise BridgeError(kind, message, hints, report=report)

    if p is None:
        refuse("NOT_PARAMETRIC", got.get("why") or "no feature tree found",
               ["recognize() lists what was found and what was not.",
                "Rebuild it by hand with find_geometry and measure; "
                "ic://guide/import says how."])
    if verify:
        if cmp_ is None:
            refuse("NOT_VERIFIED", got.get("why") or "could not be checked",
                   ["recognize(detail=true) gives the ops it tried."])
        vol = cmp_["volume_original"]
        if cmp_["residual"] > _tolerance(vol, tolerance) \
                or cmp_["box_gap"] > 1e-2:
            cov = report["coverage"]["faces"]
            refuse("PARTIAL_COVERAGE",
                   "the recognised tree reproduces %d of %d faces and is "
                   "%.4g mm3 away from the original (%.3f %%); the part is "
                   "left as it was" % (
                       cov["explained"], cov["total"], cmp_["residual"],
                       100 * cmp_["residual"] / max(vol, 1e-9)),
                   ["See unexplained: the faces nothing explains, with "
                    "handles for find_geometry and measure.",
                    "Keep the import as the base and add what you can "
                    "by hand, or pass plan={\"ops\": [...]} of your own."])
    own = [f for f in d.features
           if getattr(f, "type_name", "") != "import"]
    if own:
        report["has_tree"] = [str(getattr(f, "name", "")) for f in own][:12]
    if dry_run:
        report["dry_run"] = True
        report["summary"] = report["summary"].replace(
            "recognize ok", "parametrize dry run ok")
        if own and not replace_tree:
            report["summary"] += (" | the part has %d features of its own: "
                                  "replace_tree=true is needed" % len(own))
        return dict(report, doc=entry.handle, revision=entry.revision)
    if own and not replace_tree:
        raise BridgeError(
            "REPLACE_TREE_REQUIRED",
            "the part already has a feature tree (%d features besides "
            "imports, e.g. %s); parametrize would delete it" % (
                len(own), ", ".join(str(getattr(f, "name", ""))
                                    for f in own[:4])),
            ["Pass replace_tree=true only if the user wants that tree "
             "replaced (one undo step brings it back in the app).",
             "parametrize is for a dumb solid: a STEP import with no "
             "features of its own."], report=report)
    # applied: remove the old tree, make the new one, one change
    # last first, so nothing is left standing on a feature already gone
    removes = [{"op": "remove", "feature": int(f.id)}
               for f in reversed(list(d.features))]
    try:
        res = ops.build(ws, ops=removes + p.ops, doc=entry.handle)
    except BridgeError as exc:
        raise BridgeError(exc.kind, "the tree did not build in the part: "
                          "%s" % exc, exc.hints, report=report)
    if not res.get("ok"):
        raise BridgeError("FEATURE_FAILED", res["summary"], [],
                          report=report)
    after = _pick_body(d, None)[0]
    again = _compare(shape, after)
    report["after"] = {"volume": _r(kernel.volume(after), 4),
                       "residual_volume": _r(again["residual"], 4)}
    report["revision"] = res["revision"]
    report["doc"] = entry.handle
    report["rebuild"] = {"applied": res.get("applied"),
                         "summary": res.get("summary")}
    if res.get("requirements"):
        report["reqs"] = res.get("reqs")
    report["summary"] = report["summary"].replace(
        "recognize ok", "parametrize ok: the import is now %d features and "
        "%d parameters (one undo step)" % (len(d.features), len(p.params)))
    return report


refs_mod = None


def _late() -> None:
    global refs_mod
    from . import refs as r
    refs_mod = r


_late()
