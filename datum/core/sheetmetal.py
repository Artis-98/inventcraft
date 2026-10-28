"""Sheet metal: a part of constant thickness, bent along cylinders.

Inventor's way.  A part is converted to sheet metal and keeps its file and
its features; it gains a thickness, a bend radius and a K-factor (Sheet
Metal Defaults), and the Sheet Metal tab.  A Face is a profile given the
thickness, a Flange bends a wall up from an edge, and the Flat Pattern
unrolls whatever the body has become, so the plate can be cut flat and
bent.

The flat pattern works on the body, not on the features that made it: one
side of the sheet, the A side, is followed from a base face across every
tangent edge, through planar faces and cylindrical bends; each bend is laid
flat at the length of its neutral fibre, ``(inner radius + K x thickness)
x angle``, and everything beyond it turns with it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from OCP.BRep import BRep_Tool
from OCP.BRepAdaptor import BRepAdaptor_Curve, BRepAdaptor_Surface
from OCP.BRepBuilderAPI import (BRepBuilderAPI_MakeFace,
                                BRepBuilderAPI_MakePolygon,
                                BRepBuilderAPI_Transform)
from OCP.BRepClass3d import BRepClass3d_SolidClassifier
from OCP.BRepLProp import BRepLProp_SLProps
from OCP.BRepPrimAPI import BRepPrimAPI_MakePrism, BRepPrimAPI_MakeRevol
from OCP.GeomAbs import GeomAbs_Cylinder, GeomAbs_Line, GeomAbs_Plane
from OCP.ShapeAnalysis import ShapeAnalysis_Surface
from OCP.TopAbs import (TopAbs_EDGE, TopAbs_FACE, TopAbs_IN, TopAbs_REVERSED,
                        TopAbs_SOLID, TopAbs_WIRE)
from OCP.TopExp import TopExp
from OCP.TopTools import TopTools_IndexedDataMapOfShapeListOfShape
from OCP.TopoDS import TopoDS, TopoDS_Shape
from OCP.gp import gp_Ax1, gp_Ax3, gp_Dir, gp_Pnt, gp_Trsf, gp_Vec

from . import kernel
from .kernel import KernelError

# Inventor's Default sheet metal style, as its API reports a new part's
DEFAULT_THICKNESS = "0.5"
DEFAULT_RADIUS = "Thickness"
DEFAULT_K = "0.44"


@dataclass
class SheetMetalDefaults:
    """Sheet Metal Defaults: what every sheet metal feature starts from.
    Expressions, so the thickness can be a parameter like any other."""

    thickness: str = DEFAULT_THICKNESS
    bend_radius: str = DEFAULT_RADIUS
    k_factor: str = DEFAULT_K

    def to_dict(self) -> Dict[str, Any]:
        return {"thickness": self.thickness, "bend_radius": self.bend_radius,
                "k_factor": self.k_factor}

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]
                  ) -> Optional["SheetMetalDefaults"]:
        if not isinstance(data, dict):
            return None
        return cls(str(data.get("thickness", DEFAULT_THICKNESS)),
                   str(data.get("bend_radius", DEFAULT_RADIUS)),
                   str(data.get("k_factor", DEFAULT_K)))


# ------------------------------------------------------------------ helpers


def _v(p) -> Tuple[float, float, float]:
    return (p.X(), p.Y(), p.Z())


def _dot(a, b) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _add(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _mul(a, k):
    return (a[0] * k, a[1] * k, a[2] * k)


def _unit(a):
    n = math.sqrt(_dot(a, a)) or 1.0
    return (a[0] / n, a[1] / n, a[2] / n)


def face_normal(face, at: Sequence[float]) -> Tuple[float, float, float]:
    """The face's normal out of the solid, at the point nearest ``at``."""
    face = TopoDS.Face_s(face)
    surface = BRepAdaptor_Surface(face)
    uv = ShapeAnalysis_Surface(BRep_Tool.Surface_s(face)).ValueOfUV(
        gp_Pnt(*at), 1e-6)
    props = BRepLProp_SLProps(surface, uv.X(), uv.Y(), 1, 1e-6)
    n = props.Normal()
    if face.Orientation() == TopAbs_REVERSED:
        n.Reverse()
    return (n.X(), n.Y(), n.Z())


def _kind(face) -> Any:
    return BRepAdaptor_Surface(TopoDS.Face_s(face)).GetType()


def _edge_ends(edge):
    curve = BRepAdaptor_Curve(TopoDS.Edge_s(edge))
    return (_v(curve.Value(curve.FirstParameter())),
            _v(curve.Value(curve.LastParameter())))


def _is_line(edge) -> bool:
    return BRepAdaptor_Curve(TopoDS.Edge_s(edge)).GetType() == GeomAbs_Line


def _mid(edge):
    curve = BRepAdaptor_Curve(TopoDS.Edge_s(edge))
    return _v(curve.Value((curve.FirstParameter()
                           + curve.LastParameter()) / 2.0))


def _neighbours(solid):
    """{edge: [faces]} for every edge of the solid."""
    found = TopTools_IndexedDataMapOfShapeListOfShape()
    TopExp.MapShapesAndAncestors_s(solid, TopAbs_EDGE, TopAbs_FACE, found)
    return found


def _faces_of(found, edge) -> List[TopoDS_Shape]:
    index = found.FindIndex(edge)
    if not index:
        return []
    out = []
    for face in found.FindFromIndex(index):
        if not any(face.IsSame(o) for o in out):
            out.append(face)
    return out


def _tangent(found, face_a, face_b, edge) -> bool:
    at = _mid(edge)
    return _dot(face_normal(face_a, at), face_normal(face_b, at)) > 0.999


def _inside(solid, point) -> bool:
    classifier = BRepClass3d_SolidClassifier(solid, gp_Pnt(*point), 1e-7)
    return classifier.State() == TopAbs_IN


# ----------------------------------------------------------------- unfolding


@dataclass
class FlatPattern:
    """The sheet laid flat: its outline as faces on the XY plane, the bend
    lines down the middle of each bend, the thickness, and the flat solid."""

    faces: List[TopoDS_Shape] = field(default_factory=list)
    bends: List[Tuple[Tuple[float, float], Tuple[float, float], float]] = \
        field(default_factory=list)       # (start, end, angle in degrees)
    thickness: float = 0.0
    solid: Optional[TopoDS_Shape] = None

    def outline(self) -> TopoDS_Shape:
        return (self.faces[0] if len(self.faces) == 1
                else kernel.compound(self.faces))

    def box(self) -> Tuple[float, float, float, float]:
        """(x min, y min, x max, y max) of the outline, exactly: a plain
        bounding box pads by the edges' tolerance."""
        from OCP.Bnd import Bnd_Box
        from OCP.BRepBndLib import BRepBndLib
        found = Bnd_Box()
        BRepBndLib.AddOptimal_s(self.outline(), found, False, False)
        lo, hi = found.CornerMin(), found.CornerMax()
        return (lo.X(), lo.Y(), hi.X(), hi.Y())

    def extents(self) -> Tuple[float, float]:
        x0, y0, x1, y1 = self.box()
        return (x1 - x0, y1 - y0)


def base_face(solid) -> TopoDS_Shape:
    """The biggest flat face: where Inventor's flat pattern lies by default."""
    flat = [f for f in kernel.faces(solid) if _kind(f) == GeomAbs_Plane]
    if not flat:
        raise KernelError("the body has no flat face to lay out from")
    return max(flat, key=kernel.face_area)


def thickness_of(solid, base=None) -> float:
    """How thick the sheet is: from the base face straight through."""
    base = base if base is not None else base_face(solid)
    centre = kernel.point_on_face(base) or kernel.shape_centre(base)
    n = face_normal(base, centre)
    hits = kernel.ray_hits(solid, _add(centre, _mul(n, -1e-6)),
                           _mul(n, -1.0))
    if not hits:
        raise KernelError("could not measure the sheet's thickness")
    return hits[0] + 1e-6


def unfold(shape: TopoDS_Shape, k_factor: float = 0.44,
           base: Optional[TopoDS_Shape] = None,
           thickness: Optional[float] = None) -> FlatPattern:
    """Lay a sheet metal body flat.  See the module's description."""
    solids = kernel.explore(shape, TopAbs_SOLID)
    if not solids:
        raise KernelError("there is no solid to lay flat")
    solid = max(solids, key=kernel.volume) if base is None else next(
        (s for s in solids if any(f.IsSame(base) for f in kernel.faces(s))),
        solids[0])
    base = base if base is not None else base_face(solid)
    t = thickness if thickness is not None else thickness_of(solid, base)
    found = _neighbours(solid)

    centre = kernel.point_on_face(base) or kernel.shape_centre(base)
    normal = face_normal(base, centre)
    # the flat lies on the XY plane: the base face's plane, seen from its
    # outside, with Z its normal
    xdir = _unit(_cross(normal, (0.0, 0.0, 1.0))) if abs(normal[2]) < 0.9 \
        else _unit(_cross(normal, (1.0, 0.0, 0.0)))
    to_xy = gp_Trsf()
    to_xy.SetTransformation(gp_Ax3(gp_Pnt(*centre), gp_Dir(*normal),
                                   gp_Dir(*xdir)), gp_Ax3())
    # SetTransformation(a, b) maps a onto b's coordinates: here, the base
    # plane's frame onto XY
    placed: Dict[int, gp_Trsf] = {}
    order: List[Tuple[TopoDS_Shape, gp_Trsf]] = []
    strips: List[TopoDS_Shape] = []
    bends = []

    def key(face) -> int:
        return hash(face)

    def seen(face) -> bool:
        return any(face.IsSame(f) for f, _t in order)

    queue = [(base, gp_Trsf())]
    order.append((base, gp_Trsf()))
    while queue:
        face, where = queue.pop(0)
        for edge in kernel.explore(face, TopAbs_EDGE):
            for other in _faces_of(found, edge):
                if other.IsSame(face) or seen(other):
                    continue
                if not _tangent(found, face, other, edge):
                    continue
                kind = _kind(other)
                if kind == GeomAbs_Plane:
                    order.append((other, where))
                    queue.append((other, where))
                elif kind == GeomAbs_Cylinder and _kind(face) == GeomAbs_Plane:
                    made = _unbend(solid, found, face, other, edge, where, t,
                                   k_factor)
                    if made is None:
                        continue
                    child, child_where, strip, bend = made
                    order.append((other, where))      # marks it done
                    strips.append(strip)
                    bends.append(bend)
                    if child is not None and not seen(child):
                        order.append((child, child_where))
                        queue.append((child, child_where))

    flat_faces = []
    for face, where in order:
        if _kind(face) != GeomAbs_Plane:
            continue
        moved = BRepBuilderAPI_Transform(face, where, True).Shape()
        flat_faces.append(moved)
    flat_faces.extend(strips)
    on_xy = _merge_flat([BRepBuilderAPI_Transform(f, to_xy, True).Shape()
                         for f in flat_faces])
    result = FlatPattern(faces=kernel.faces(on_xy), thickness=t)
    for (a, b), angle in bends:
        pa = gp_Pnt(*a).Transformed(to_xy)
        pb = gp_Pnt(*b).Transformed(to_xy)
        result.bends.append(((pa.X(), pa.Y()), (pb.X(), pb.Y()), angle))
    try:
        result.solid = BRepPrimAPI_MakePrism(
            result.outline(), gp_Vec(0.0, 0.0, -t)).Shape()
    except Exception:
        result.solid = None
    return result


def _merge_flat(pieces: Sequence[TopoDS_Shape]) -> TopoDS_Shape:
    """Pieces lying on the XY plane, made into as few faces as they cover:
    the faces of the sheet and the strips of its bends become one outline,
    with no line left across a bend for a cutter to follow.

    Each piece is made again on one and the same plane first.  Turned flat
    from wherever it was, a piece may face up or down, and faces on
    planes that face opposite ways are never merged."""
    from OCP.BRepTools import BRepTools
    from OCP.ShapeFix import ShapeFix_Face
    from OCP.ShapeUpgrade import ShapeUpgrade_UnifySameDomain
    from OCP.gp import gp_Pln
    plane = gp_Pln(gp_Pnt(0.0, 0.0, 0.0), gp_Dir(0.0, 0.0, 1.0))
    remade = []
    for piece in pieces:
        for face in kernel.faces(piece):
            outer = BRepTools.OuterWire_s(TopoDS.Face_s(face))
            maker = BRepBuilderAPI_MakeFace(plane, outer, True)
            for wire in kernel.explore(face, TopAbs_WIRE):
                if not wire.IsSame(outer):
                    maker.Add(TopoDS.Wire_s(wire))
            if not maker.IsDone():
                continue
            fixer = ShapeFix_Face(maker.Face())
            fixer.FixOrientation()
            fixer.Perform()
            remade.append(fixer.Face())
    if not remade:
        raise KernelError("the flat pattern came out empty")
    merged = remade[0] if len(remade) == 1 else kernel.fuse_all(remade)
    unify = ShapeUpgrade_UnifySameDomain(merged, True, True, True)
    unify.Build()
    return unify.Shape()


def _unbend(solid, found, face, bend, edge, where: gp_Trsf, t: float,
            k: float):
    """Lay one bend flat: the strip it becomes, the face beyond it and how
    that face moves, and the bend line.  None for a bend it cannot read."""
    surface = BRepAdaptor_Surface(TopoDS.Face_s(bend))
    cylinder = surface.Cylinder()
    radius = cylinder.Radius()
    axis = cylinder.Axis()
    a_loc, a_dir = _v(axis.Location()), _v(axis.Direction())
    angle = abs(surface.LastUParameter() - surface.FirstUParameter())
    if angle < 1e-9 or angle > math.pi + 1e-6:
        return None

    # the far straight edge of the bend, and the face beyond it
    lines = [e for e in kernel.explore(bend, TopAbs_EDGE)
             if _is_line(e) and not e.IsSame(edge)]
    near_mid = _mid(edge)
    far = None
    for e in lines:
        m = _mid(e)
        off = _sub(m, a_loc)
        radial = _sub(off, _mul(a_dir, _dot(off, a_dir)))
        if abs(math.sqrt(_dot(radial, radial)) - radius) < 1e-4 \
                and math.dist(m, near_mid) > 1e-6:
            far = e
            break
    if far is None:
        return None
    child = None
    for other in _faces_of(found, far):
        if not other.IsSame(bend) and _kind(other) == GeomAbs_Plane \
                and _tangent(found, bend, other, far):
            child = other

    # inner or outer side: material just outside this radius means inner
    mid_u = (surface.FirstUParameter() + surface.LastUParameter()) / 2.0
    mid_v = (surface.FirstVParameter() + surface.LastVParameter()) / 2.0
    p = _v(surface.Value(mid_u, mid_v))
    off = _sub(p, a_loc)
    radial = _unit(_sub(off, _mul(a_dir, _dot(off, a_dir))))
    inner = _inside(solid, _add(p, _mul(radial, t / 2.0)))
    r_inner = radius if inner else radius - t
    length = angle * (r_inner + k * t)

    # which way is away from the face, in its plane, across the edge
    n_face = face_normal(face, near_mid)
    e0, e1 = _edge_ends(edge)
    d = _unit(_sub(e1, e0))
    u = _unit(_cross(d, n_face))
    if _dot(_sub(p, near_mid), u) < 0:
        u = _mul(u, -1.0)

    # turn the far side back about the bend's axis until its edge lies on
    # the near one, then slide it out by the bend's flat length
    best = None
    for sign in (1.0, -1.0):
        turn = gp_Trsf()
        turn.SetRotation(gp_Ax1(gp_Pnt(*a_loc), gp_Dir(*a_dir)),
                         sign * angle)
        m = gp_Pnt(*_mid(far)).Transformed(turn)
        rel = _sub(_v(m), e0)
        miss = _sub(rel, _mul(d, _dot(rel, d)))
        gap = math.sqrt(_dot(miss, miss))
        if best is None or gap < best[0]:
            best = (gap, turn)
    turn = best[1]
    slide = gp_Trsf()
    slide.SetTranslation(gp_Vec(*_mul(u, length)))
    local = slide.Multiplied(turn)
    child_where = where.Multiplied(local)

    # the strip, between the near edge and where it has slid to
    corners = [e0, e1, _add(e1, _mul(u, length)), _add(e0, _mul(u, length))]
    poly = BRepBuilderAPI_MakePolygon()
    for c in corners:
        poly.Add(gp_Pnt(*c).Transformed(where))
    poly.Close()
    strip = BRepBuilderAPI_MakeFace(poly.Wire(), True).Face()
    half = _mul(u, length / 2.0)
    line = (_v(gp_Pnt(*_add(e0, half)).Transformed(where)),
            _v(gp_Pnt(*_add(e1, half)).Transformed(where)))
    return child, child_where, strip, (line, math.degrees(angle))


# -------------------------------------------------------------- the flange


# Inventor's Bend Position for a flange: inside the base face's extents
# (its default: the wall's outside lines up with the edge and the base is
# trimmed back by the bend), or bent from the adjacent face (the base is
# left whole and the bend starts at the edge)
INSIDE = "inside"
ADJACENT = "adjacent"
POSITIONS = (INSIDE, ADJACENT)


def setback(thickness: float, radius: float, angle_deg: float) -> float:
    """How far back from where the outer faces meet a bend begins."""
    if angle_deg >= 180.0 - 1e-9:
        return radius + thickness
    return (radius + thickness) * math.tan(math.radians(angle_deg) / 2.0)


def flange_tools(shape: TopoDS_Shape, edge: TopoDS_Shape, thickness: float,
                 radius: float, angle_deg: float, height: float,
                 flip: bool = False, position: str = INSIDE,
                 trim: Tuple[float, float] = (0.0, 0.0)
                 ) -> Tuple[Optional[TopoDS_Shape], TopoDS_Shape]:
    """A Flange as Inventor makes it, as (what to cut away, what to add).

    A bend of ``radius`` up from ``edge`` through ``angle_deg``, then a
    wall.  The height is Inventor's default: along the wall, from where the
    outer faces of the sheet and the wall would meet.  ``edge`` is a
    straight edge where a face of the sheet meets its thickness; the wall
    bends towards that face's side, or away with ``flip``.
    ``trim`` shortens the wall at each end of the edge, where it would run
    into another flange's at a corner.
    """
    if not _is_line(edge):
        raise KernelError("a flange needs a straight edge")
    if thickness <= 0 or radius < 0 or height <= 0:
        raise KernelError("thickness and height must be more than 0")
    if not 0.0 < angle_deg <= 180.0:
        raise KernelError("the flange angle must be between 0 and 180")
    found = _neighbours(shape)
    beside = [f for f in _faces_of(found, edge) if _kind(f) == GeomAbs_Plane]
    if len(beside) < 2:
        raise KernelError("the edge must lie between two flat faces")
    e0, e1 = edge_ends_ordered(edge)
    # the sheet's face is the broad one; the other is the thickness
    sheet, side = sorted(beside, key=kernel.face_area, reverse=True)[:2]
    mid = _mid(edge)
    n = face_normal(sheet, mid)
    s = face_normal(side, mid)
    if abs(_dot(n, s)) > 1e-6:
        raise KernelError("the edge's faces must meet square")
    if flip:
        # the same edge on the other face of the sheet, bending the other way
        e0, e1 = _add(e0, _mul(n, -thickness)), _add(e1, _mul(n, -thickness))
        n = _mul(n, -1.0)
    d = _unit(_sub(e1, e0))
    back = setback(thickness, radius, angle_deg)

    cut = None
    if position == INSIDE:
        # the base gives up the length the bend takes
        poly = BRepBuilderAPI_MakePolygon()
        for c in (e0, e1, _add(e1, _mul(s, -back)), _add(e0, _mul(s, -back))):
            poly.Add(gp_Pnt(*c))
        poly.Close()
        strip = BRepBuilderAPI_MakeFace(poly.Wire(), True).Face()
        # a hair wider than the sheet, so nothing is left on its faces
        lift = gp_Trsf()
        lift.SetTranslation(gp_Vec(*_mul(n, 1e-4)))
        strip = BRepBuilderAPI_Transform(strip, lift, True).Shape()
        cut = BRepPrimAPI_MakePrism(
            strip, gp_Vec(*_mul(n, -(thickness + 2e-4)))).Shape()
        e0, e1 = _add(e0, _mul(s, -back)), _add(e1, _mul(s, -back))

    # The end of the sheet, square across its thickness, less any trim at
    # a corner.  The wall stops at the trim; the bend stops there too, or
    # at its own setback where that is further, so two bends meeting at a
    # corner never touch (Inventor's corner, measured).
    def end_face(t0: float, t1: float):
        a0, a1 = _add(e0, _mul(d, t0)), _add(e1, _mul(d, -t1))
        if math.dist(e0, e1) - t0 - t1 <= 1e-6:
            raise KernelError("the flange is trimmed away at its corners")
        poly = BRepBuilderAPI_MakePolygon()
        for c in (a0, a1, _add(a1, _mul(n, -thickness)),
                  _add(a0, _mul(n, -thickness))):
            poly.Add(gp_Pnt(*c))
        poly.Close()
        return BRepBuilderAPI_MakeFace(poly.Wire(), True).Face()

    bend_back = setback(thickness, radius, angle_deg)
    bend_trim = tuple(max(x, bend_back) if x > 0 else 0.0 for x in trim)
    end = end_face(*bend_trim)
    wall_start = end_face(*trim)

    a = math.radians(angle_deg)
    centre = _add(e0, _mul(n, radius))
    axis = gp_Ax1(gp_Pnt(*centre), gp_Dir(*d))
    sign = 1.0 if _dot(_v(gp_Vec(*s).Rotated(axis, a / 2)), n) > 0 else -1.0
    axis = gp_Ax1(gp_Pnt(*centre), gp_Dir(*_mul(d, sign)))
    pieces = []
    if radius + thickness > 0:
        pieces.append(BRepPrimAPI_MakeRevol(end, axis, a).Shape())
    turn = gp_Trsf()
    turn.SetRotation(axis, a)
    wall_end = BRepBuilderAPI_Transform(wall_start, turn, True).Shape()
    out = _v(gp_Vec(*s).Transformed(turn))
    straight = height - back
    if straight > 1e-6:
        pieces.append(BRepPrimAPI_MakePrism(
            wall_end, gp_Vec(*_mul(out, straight))).Shape())
    if not pieces:
        raise KernelError("the flange is too short for its bend")
    tool = pieces[0] if len(pieces) == 1 else kernel.fuse_all(pieces)
    return cut, tool


def edge_ends_ordered(edge) -> Tuple[Tuple[float, float, float],
                                     Tuple[float, float, float]]:
    """An edge's ends, first and last, the same way whatever its
    orientation: what ``trim`` counts from."""
    a, b = _edge_ends(edge)
    return (a, b) if a <= b else (b, a)


def flange_wall_tip(shape: TopoDS_Shape, edge: TopoDS_Shape,
                    thickness: float, radius: float, angle_deg: float,
                    flip: bool = False, position: str = INSIDE):
    """Where a flange's height is measured from, at the middle of its
    edge, and the way its wall runs: (base, direction), for the arrow that
    drags the height.  The base is where the outer faces meet, Inventor's
    height datum, so base + direction x height is the tip.  None when the
    edge is not one a flange can stand on."""
    found = _neighbours(shape)
    beside = [f for f in _faces_of(found, edge) if _kind(f) == GeomAbs_Plane]
    if len(beside) < 2:
        return None
    sheet, side = sorted(beside, key=kernel.face_area, reverse=True)[:2]
    mid = _mid(edge)
    n = face_normal(sheet, mid)
    s = face_normal(side, mid)
    if flip:
        mid = _add(mid, _mul(n, -thickness))
        n = _mul(n, -1.0)
    a = math.radians(angle_deg)
    # the wall runs as the side's normal does, turned up through the angle
    out = _add(_mul(s, math.cos(a)), _mul(n, math.sin(a)))
    base = _add(mid, _mul(n, -thickness))      # the outer face, at the edge
    if position == ADJACENT:
        base = _add(base, _mul(s, setback(thickness, radius, angle_deg)))
    return base, _unit(out)


def corner_trims(edges: Sequence[TopoDS_Shape], thickness: float,
                 radius: float, angle_deg: float,
                 position: str = INSIDE,
                 gap: Optional[float] = None) -> List[Tuple[float, float]]:
    """How far each of several flanges stops short of a corner it shares
    with another, so their bends and walls do not run into each other.

    Inventor's rule, measured: the wall and its bend end the thickness
    plus the corner gap over root two from the corner, whatever the bend
    radius, leaving the gap between the walls across the mitre.  The gap
    is Inventor's GapSize, the thickness unless given.
    """
    gap = thickness if gap is None else gap
    trim = thickness + gap / math.sqrt(2.0)
    ends = [edge_ends_ordered(e) for e in edges]
    out = []
    for i, (a, b) in enumerate(ends):
        trims = []
        for point in (a, b):
            shared = any(j != i and (math.dist(point, o[0]) < 1e-6
                                     or math.dist(point, o[1]) < 1e-6)
                         for j, o in enumerate(ends))
            trims.append(trim if shared else 0.0)
        out.append((trims[0], trims[1]))
    return out


def flanges(shape: TopoDS_Shape, edges: Sequence[TopoDS_Shape],
            thickness: float, radius: float, angle_deg: float,
            height: float, flip: bool = False,
            position: str = INSIDE,
            gap: Optional[float] = None) -> TopoDS_Shape:
    """The body with a flange on every edge, as one Flange feature makes
    them: worked out on the body as it was, then cut and added together,
    stopping short of one another at shared corners."""
    trims = corner_trims(edges, thickness, radius, angle_deg, position, gap)
    made = [flange_tools(shape, e, thickness, radius, angle_deg, height,
                         flip, position, trim)
            for e, trim in zip(edges, trims)]
    body = shape
    cuts = [c for c, _t in made if c is not None]
    if cuts:
        body = kernel.boolean(body, cuts[0] if len(cuts) == 1
                              else kernel.fuse_all(cuts), "cut")
    adds = [t for _c, t in made]
    return kernel.boolean(body, adds[0] if len(adds) == 1
                          else kernel.fuse_all(adds), "join")


def flange(shape: TopoDS_Shape, edge: TopoDS_Shape, thickness: float,
           radius: float, angle_deg: float, height: float,
           flip: bool = False, position: str = INSIDE) -> TopoDS_Shape:
    """The body with a flange on ``edge``: see :func:`flange_tools`."""
    cut, tool = flange_tools(shape, edge, thickness, radius, angle_deg,
                             height, flip, position)
    body = kernel.boolean(shape, cut, "cut") if cut is not None else shape
    return kernel.boolean(body, tool, "join")


# ------------------------------------------------------------- the document


def convert(doc, thickness: Optional[str] = None) -> SheetMetalDefaults:
    """Convert to Sheet Metal: the part keeps its file and its features
    and gains Sheet Metal Defaults, with the Thickness and BendRadius
    parameters every sheet metal feature reads.

    A part that already has a body takes its thickness from it, as
    Inventor does from the base face; an empty one starts at Inventor's
    default.
    """
    if doc.sheet_metal is not None:
        return doc.sheet_metal
    if thickness is None:
        thickness = DEFAULT_THICKNESS if doc.units != "in" else "0.12"
        shape = getattr(doc, "shape", None)
        if shape is not None and kernel.is_valid(shape):
            try:
                measured = thickness_of(max(
                    kernel.explore(shape, TopAbs_SOLID), key=kernel.volume))
                thickness = ("%.4f" % measured).rstrip("0").rstrip(".")
            except (KernelError, ValueError):
                pass
    names = set(doc.params.names())
    if "Thickness" not in names:
        doc.params.add("Thickness", thickness, doc.units,
                       "Sheet metal thickness")
    if "BendRadius" not in names:
        doc.params.add("BendRadius", "Thickness", doc.units,
                       "Sheet metal bend radius")
    doc.sheet_metal = SheetMetalDefaults("Thickness", "BendRadius",
                                         DEFAULT_K)
    doc.modified = True
    return doc.sheet_metal


def convert_to_standard(doc) -> None:
    """Convert to Standard Part: the features stay, the Sheet Metal tab
    goes, and the flat pattern with it."""
    doc.sheet_metal = None
    doc.modified = True


def flat_pattern(doc) -> FlatPattern:
    """The part's body laid flat with its K-factor."""
    if doc.sheet_metal is None:
        raise KernelError("the part is not sheet metal")
    shape = getattr(doc, "shape", None)
    if shape is None or not kernel.is_valid(shape):
        raise KernelError("there is no body to lay flat yet")
    scope = doc.parameter_scope()
    from .params import evaluate
    k = float(evaluate(doc.sheet_metal.k_factor, scope))
    t = float(evaluate(doc.sheet_metal.thickness, scope))
    if not 0.0 <= k <= 1.0:
        raise KernelError("the K-factor must be between 0 and 1")
    return unfold(shape, k, thickness=t)


def flat_to_dxf(flat: FlatPattern, path: str, bend_lines: bool = True,
                units: str = "mm") -> str:
    """The flat pattern as a DXF to cut from, the way Inventor writes one:
    the outline and any holes on layer OUTER_PROFILE, and, when wanted,
    each bend's centre line on BEND_CENTERLINE, to be marked rather than
    cut.  Laid with its lower left corner on the origin."""
    from . import dxf
    from .sketch import SketchPlane
    x0, y0, _x1, _y1 = flat.box()
    plane = SketchPlane((x0, y0, 0.0), (0.0, 0.0, 1.0), (1.0, 0.0, 0.0))
    document = dxf.DxfDocument(units)
    for edge in kernel.explore(flat.outline(), TopAbs_EDGE):
        dxf._write_edge(document, TopoDS.Edge_s(edge), plane,
                        "OUTER_PROFILE")
    if bend_lines:
        for a, b, _angle in flat.bends:
            document.line((a[0] - x0, a[1] - y0), (b[0] - x0, b[1] - y0),
                          "BEND_CENTERLINE")
    return document.save(path)
