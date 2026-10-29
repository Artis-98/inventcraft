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
    # the base face picked when a body was converted (Inventor's A side):
    # the flat pattern lies on it.  A RefSet's list; empty for the biggest
    # flat face
    base: List[Any] = field(default_factory=list)
    # the Flat Pattern's own features, after the folded part's: Inventor
    # keeps a second tree there.  Each a FlatFeature
    flat_features: List[Any] = field(default_factory=list)
    # the corner gap of flanges meeting at a corner (Inventor's GapSize)
    gap: str = "Thickness"

    def to_dict(self) -> Dict[str, Any]:
        return {"thickness": self.thickness, "bend_radius": self.bend_radius,
                "k_factor": self.k_factor, "base": list(self.base),
                "gap": self.gap,
                "flat_features": [f.to_dict() for f in self.flat_features]}

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]
                  ) -> Optional["SheetMetalDefaults"]:
        if not isinstance(data, dict):
            return None
        out = cls(str(data.get("thickness", DEFAULT_THICKNESS)),
                  str(data.get("bend_radius", DEFAULT_RADIUS)),
                  str(data.get("k_factor", DEFAULT_K)))
        out.base = list(data.get("base") or [])
        out.gap = str(data.get("gap", "Thickness"))
        out.flat_features = [FlatFeature.from_dict(f)
                             for f in data.get("flat_features") or []
                             if isinstance(f, dict)]
        return out


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
    # a point's coordinates in the base face's own frame: the base face
    # lands on XY, facing up.  (The two-frame form maps the other way, which
    # went unnoticed while every base face lay at height nought.)
    to_xy.SetTransformation(gp_Ax3(gp_Pnt(*centre), gp_Dir(*normal),
                                   gp_Dir(*xdir)))
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
    # Everything the walk reached, laid flat and given the thickness, is
    # the body again but for the small difference the bends make.  A
    # sharp corner, a bend that is not a cylinder, or a body that is not
    # one thickness leaves a great deal behind; Inventor will not lay
    # those flat, and neither does this.
    flat_area = sum(kernel.face_area(f) for f in result.faces)
    body = kernel.volume(solid)
    if body > 0 and abs(body - flat_area * t) > 0.03 * body:
        raise KernelError(
            "the body cannot be laid flat: it has a corner that is not a "
            "bend (sharp, or not round), or it is not all one thickness")
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
            # a face turned over by a half bend comes back facing down; its
            # loops then run the wrong way round for an upward face, and
            # are turned back first
            at = kernel.point_on_face(face) or kernel.shape_centre(face)
            down = face_normal(face, at)[2] < 0
            outer = BRepTools.OuterWire_s(TopoDS.Face_s(face))
            maker = BRepBuilderAPI_MakeFace(
                plane, TopoDS.Wire_s(outer.Reversed() if down else outer),
                True)
            for wire in kernel.explore(face, TopAbs_WIRE):
                if not wire.IsSame(outer):
                    maker.Add(TopoDS.Wire_s(wire.Reversed() if down
                                            else wire))
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


def _has_cylinder(solid, location, axis_dir, radius: float) -> bool:
    """Whether the solid has a cylindrical face of this radius about this
    axis."""
    for face in kernel.faces(solid):
        if _kind(face) != GeomAbs_Cylinder:
            continue
        cylinder = BRepAdaptor_Surface(TopoDS.Face_s(face)).Cylinder()
        if abs(cylinder.Radius() - radius) > 1e-4:
            continue
        axis = cylinder.Axis()
        d = _v(axis.Direction())
        if abs(abs(_dot(d, axis_dir)) - 1.0) > 1e-6:
            continue
        off = _sub(_v(axis.Location()), location)
        across = _sub(off, _mul(axis_dir, _dot(off, axis_dir)))
        if math.sqrt(_dot(across, across)) < 1e-4:
            return True
    return False


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
    if angle < 1e-9 or angle > 2.0 * math.pi - 1e-6:
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
    # The bend's other side must be the same cylinder a thickness further
    # in or out, about the same axis: a bend whose two sides do not share
    # a centre is not a bend of this sheet, and Inventor will not lay it
    # flat either
    other = radius - t if not inner else radius + t
    if not _has_cylinder(solid, a_loc, a_dir, other):
        raise KernelError(
            "a bend's inside and outside are not about the same centre, "
            "so it cannot be laid flat")
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


# ------------------------------------------------------------------ strips
#
# A flange, and each kind of hem, is the end of the sheet carried on as a
# strip: a bend, a straight, another bend.  The strip is walked one step at
# a time from the cross-section at the end of the sheet; every bend turns
# towards the strip's inner side, which turns with it, so the steps curl
# the way the sheet does.


def _section(e0, e1, n, thickness):
    """The strip's cross-section: the inner edge e0-e1, the thickness
    behind it, away from ``n``."""
    poly = BRepBuilderAPI_MakePolygon()
    for c in (e0, e1, _add(e1, _mul(n, -thickness)),
              _add(e0, _mul(n, -thickness))):
        poly.Add(gp_Pnt(*c))
    poly.Close()
    return BRepBuilderAPI_MakeFace(poly.Wire(), True).Face()


def _walk(e0, e1, n, s, thickness: float, steps) -> List[TopoDS_Shape]:
    """The solids of a strip that starts at the section e0-e1 heading along
    ``s`` with its inner side towards ``n``.  ``steps`` are ("bend", angle
    in degrees, inner radius) and ("straight", length)."""
    d = _unit(_sub(e1, e0))
    pieces = []
    for step in steps:
        if step[0] == "straight":
            length = step[1]
            if length > 1e-9:
                pieces.append(BRepPrimAPI_MakePrism(
                    _section(e0, e1, n, thickness),
                    gp_Vec(*_mul(s, length))).Shape())
                e0, e1 = _add(e0, _mul(s, length)), _add(e1, _mul(s, length))
            continue
        _kind_, angle, radius = step
        a = math.radians(abs(angle))
        towards = n if angle >= 0 else _mul(n, -1.0)
        start = e0 if angle >= 0 else _add(e0, _mul(n, -thickness))
        centre = _add(start, _mul(towards, radius))
        axis = gp_Ax1(gp_Pnt(*centre), gp_Dir(*d))
        sign = 1.0 if _dot(_v(gp_Vec(*s).Rotated(axis, min(a, math.pi / 2)
                                                 / 2)), towards) > 0 else -1.0
        axis = gp_Ax1(gp_Pnt(*centre), gp_Dir(*_mul(d, sign)))
        pieces.append(BRepPrimAPI_MakeRevol(
            _section(e0, e1, n, thickness), axis, a).Shape())
        turn = gp_Trsf()
        turn.SetRotation(axis, a)
        e0 = _v(gp_Pnt(*e0).Transformed(turn))
        e1 = _v(gp_Pnt(*e1).Transformed(turn))
        n = _v(gp_Vec(*n).Transformed(turn))
        s = _v(gp_Vec(*s).Transformed(turn))
    return pieces


def _sheet_edge(shape, edge, thickness, flip):
    """For a straight edge where a face of the sheet meets its thickness:
    its ends, the sheet's face normal (the side a strip turns to) and the
    thickness face's outward normal, with ``flip`` taking the edge on the
    sheet's other face instead."""
    if not _is_line(edge):
        raise KernelError("it needs a straight edge")
    found = _neighbours(shape)
    beside = [f for f in _faces_of(found, edge) if _kind(f) == GeomAbs_Plane]
    if len(beside) < 2:
        raise KernelError("the edge must lie between two flat faces")
    sheet, side = sorted(beside, key=kernel.face_area, reverse=True)[:2]
    mid = _mid(edge)
    n = face_normal(sheet, mid)
    s = face_normal(side, mid)
    if abs(_dot(n, s)) > 1e-6:
        raise KernelError("the edge's faces must meet square")
    e0, e1 = edge_ends_ordered(edge)
    if flip:
        e0, e1 = _add(e0, _mul(n, -thickness)), _add(e1, _mul(n, -thickness))
        n = _mul(n, -1.0)
    return e0, e1, n, s


def _trim_back(e0, e1, n, s, thickness, back):
    """What the sheet gives up to a bend that starts ``back`` from its
    edge: the slab to cut, and the edge moved back."""
    poly = BRepBuilderAPI_MakePolygon()
    for c in (e0, e1, _add(e1, _mul(s, -back)), _add(e0, _mul(s, -back))):
        poly.Add(gp_Pnt(*c))
    poly.Close()
    strip = BRepBuilderAPI_MakeFace(poly.Wire(), True).Face()
    lift = gp_Trsf()
    lift.SetTranslation(gp_Vec(*_mul(n, 1e-4)))
    strip = BRepBuilderAPI_Transform(strip, lift, True).Shape()
    cut = BRepPrimAPI_MakePrism(
        strip, gp_Vec(*_mul(n, -(thickness + 2e-4)))).Shape()
    return cut, _add(e0, _mul(s, -back)), _add(e1, _mul(s, -back))


# Inventor's four hems, as its API names them, and what each one's two
# values are: Single and Double take a gap and a length, Teardrop and
# Rolled a radius and an angle.
SINGLE, DOUBLE, TEARDROP, ROLLED = "single", "double", "teardrop", "rolled"
HEMS = (SINGLE, DOUBLE, TEARDROP, ROLLED)


def hem_defaults(kind: str) -> Tuple[str, str]:
    """A new hem's two values, as Inventor gives them."""
    return {SINGLE: ("Thickness * 0.5", "Thickness * 4"),
            DOUBLE: ("Thickness * 0.5", "Thickness * 4"),
            TEARDROP: ("Thickness", "300"),
            ROLLED: ("Thickness", "180")}[kind]


def hem_steps(kind: str, thickness: float, first: float, second: float):
    """(setback, steps) for a hem, read from Inventor's own: the sheet is
    trimmed back by the bend, then folded back over its face.

    Single: a half turn of inner radius gap / 2, then a return reaching
    ``length`` from the edge.  Double: a quarter turn, a rise of thickness
    plus gap, a quarter turn, the top layer to ``length``, a half turn and
    the middle layer back.  Teardrop: a turn of ``angle`` at ``radius`` and
    a short straight that stops a quarter of the thickness off the face it
    comes back to.  Rolled: the turn alone.
    """
    t = thickness
    if kind == SINGLE:
        gap, length = first, second
        if gap <= 0 or length <= 0:
            raise KernelError("a hem's gap and length must be more than 0")
        r = gap / 2.0
        back = r + t
        return back, [("bend", 180.0, r), ("straight", length - back)]
    if kind == DOUBLE:
        gap, length = first, second
        if gap <= 0 or length <= 0:
            raise KernelError("a hem's gap and length must be more than 0")
        r = gap / 2.0
        back = r + t
        layer = length - 2.0 * back
        if layer < -1e-9:
            raise KernelError("a double hem needs a length of at least "
                              "%.3f" % (2.0 * back))
        return back, [("bend", 90.0, r), ("straight", t + gap),
                      ("bend", 90.0, r), ("straight", layer),
                      ("bend", 180.0, r), ("straight", layer)]
    if kind in (TEARDROP, ROLLED):
        r, angle = first, second
        if r <= 0 or not 0 < angle < 360:
            raise KernelError("a hem's radius must be more than 0 and its "
                              "angle between 0 and 360")
        back = r + t
        steps = [("bend", angle, r)]
        if kind == TEARDROP:
            # past the half turn the strip heads back at the sheet: it
            # runs on until its inner face is t / 4 off the sheet's face
            a = math.radians(angle)
            # the inner edge, measured from the sheet's face, at the bend's
            # end, and how fast the straight closes on it
            height = r - r * math.cos(a)
            closing = -math.sin(a - math.pi / 2) if angle > 180 else 0.0
            closing = math.sin(a) * -1.0
            if angle > 180 and closing > 1e-9:
                run = (height + 0.0 - t / 4.0) / closing
                if run > 1e-9:
                    steps.append(("straight", run))
        return back, steps
    raise KernelError("there is no %s hem" % kind)


def hem_tools(shape: TopoDS_Shape, edge: TopoDS_Shape, kind: str,
              thickness: float, first: float, second: float,
              flip: bool = False) -> Tuple[TopoDS_Shape, TopoDS_Shape]:
    """A Hem as Inventor makes it, as (what to cut away, what to add)."""
    e0, e1, n, s = _sheet_edge(shape, edge, thickness, flip)
    back, steps = hem_steps(kind, thickness, first, second)
    cut, e0, e1 = _trim_back(e0, e1, n, s, thickness, back)
    pieces = _walk(e0, e1, n, s, thickness, steps)
    tool = pieces[0] if len(pieces) == 1 else kernel.fuse_all(pieces)
    return cut, tool


def hem(shape: TopoDS_Shape, edge: TopoDS_Shape, kind: str,
        thickness: float, first: float, second: float,
        flip: bool = False) -> TopoDS_Shape:
    cut, tool = hem_tools(shape, edge, kind, thickness, first, second, flip)
    return kernel.boolean(kernel.boolean(shape, cut, "cut"), tool, "join")


# ---------------------------------------------------------- contour flange


def contour_steps(points, thickness: float, radius: float,
                  flip: bool = False):
    """A Contour Flange's open path as strip steps, Inventor's way: the
    path is one face of the sheet and the thickness goes to the outside of
    its first corner (the other way with ``flip``); every corner is bent
    at the bend radius on its inner side, the path's side or the far one.

    ``points`` are the path's corners in order, in 3D on one plane, whose
    normal is ``normal``.  Returns (start, first direction, the side the
    material is not on, steps)."""
    pts = [tuple(float(c) for c in p) for p in points]
    if len(pts) < 2:
        raise KernelError("a contour flange needs a path of one line or more")
    dirs = []
    lengths = []
    for a, b in zip(pts, pts[1:]):
        v = _sub(b, a)
        length = math.sqrt(_dot(v, v))
        if length < 1e-9:
            raise KernelError("the path has a line of no length")
        dirs.append(_mul(v, 1.0 / length))
        lengths.append(length)
    if len(dirs) > 1:
        normal = _unit(_cross(dirs[0], dirs[1]))
    else:
        raise KernelError("a contour flange needs a path with a corner, or "
                          "a plane to stand on")
    # the side away from the material: towards the first corner's inside
    away = _unit(_cross(normal, dirs[0]))
    if flip:
        away = _mul(away, -1.0)
    steps = []
    turns = []
    for i in range(1, len(dirs)):
        c = _dot(dirs[i - 1], dirs[i])
        turn = math.degrees(math.acos(max(-1.0, min(1.0, c))))
        if turn < 1e-6:
            turns.append((0.0, 0.0))
            continue
        side = _dot(_cross(dirs[i - 1], dirs[i]), normal)
        # whether this corner turns to the path's side (away from the
        # material), as the first does unless flipped
        left = side > 0
        first_left = _dot(_cross(dirs[0], dirs[1]), normal) > 0 \
            if len(dirs) > 1 else True
        to_path = (left == first_left) != flip
        tangent = (radius if to_path else radius + thickness) \
            * math.tan(math.radians(turn) / 2.0)
        turns.append((turn if to_path else -turn, tangent))
    for i, length in enumerate(lengths):
        before = turns[i - 1][1] if i > 0 else 0.0
        after = turns[i][1] if i < len(turns) else 0.0
        run = length - before - after
        if run < -1e-6:
            raise KernelError("a line of the path is too short for the "
                              "bends at its ends")
        steps.append(("straight", max(0.0, run)))
        if i < len(turns) and turns[i][0]:
            steps.append(("bend", turns[i][0], radius))
    return pts[0], dirs[0], away, normal, steps


def contour_flange(points, width: float, thickness: float, radius: float,
                   flip: bool = False, direction: str = "positive"
                   ) -> TopoDS_Shape:
    """Inventor's Contour Flange: an open path drawn on a plane, given the
    thickness, bent at its corners, and run ``width`` along the plane's
    normal: "positive", "negative" or "symmetric"."""
    if width <= 0:
        raise KernelError("the width must be more than 0")
    start, first, away, normal, steps = contour_steps(points, thickness,
                                                      radius, flip)
    if direction == "negative":
        e0, e1 = _add(start, _mul(normal, -width)), start
    elif direction == "symmetric":
        e0 = _add(start, _mul(normal, -width / 2.0))
        e1 = _add(start, _mul(normal, width / 2.0))
    else:
        e0, e1 = start, _add(start, _mul(normal, width))
    pieces = _walk(e0, e1, away, first, thickness, steps)
    return pieces[0] if len(pieces) == 1 else kernel.fuse_all(pieces)


# ------------------------------------------------------------- corner seam


def _wall_of(shape, found, edge, h):
    """The broad flat face beside an edge, square to ``h``: the wall the
    edge ends."""
    faces = [f for f in _faces_of(found, edge) if _kind(f) == GeomAbs_Plane]
    walls = [f for f in faces
             if abs(_dot(face_normal(f, _mid(edge)), h)) < 1e-6]
    if not walls:
        raise KernelError("the edge is not the end of a wall")
    return max(walls, key=kernel.face_area)


def corner_seam(shape: TopoDS_Shape, edge_a: TopoDS_Shape,
                edge_b: TopoDS_Shape, thickness: float, radius: float,
                gap: Optional[float] = None) -> TopoDS_Shape:
    """Inventor's Corner Seam on two flanges that meet at a corner: the
    open corner between their walls made as one Flange on both edges
    makes it, each wall stopping the thickness plus the gap over root two
    from the corner, its bend at its own setback if that is further, and
    the corner of the sheet they bend from kept square.

    ``edge_a`` and ``edge_b`` are the ends of the two walls, picked as in
    Inventor: straight, parallel, one on each wall.
    """
    if not (_is_line(edge_a) and _is_line(edge_b)):
        raise KernelError("a corner seam needs two straight edges")
    gap = thickness if gap is None else gap
    a0, a1 = _edge_ends(edge_a)
    b0, b1 = _edge_ends(edge_b)
    h = _unit(_sub(a1, a0))
    if abs(abs(_dot(h, _unit(_sub(b1, b0)))) - 1.0) > 1e-6:
        raise KernelError("the two edges must be parallel")
    found = _neighbours(shape)
    wall_a = _wall_of(shape, found, edge_a, h)
    wall_b = _wall_of(shape, found, edge_b, h)
    wa = face_normal(wall_a, _mid(edge_a))
    wb = face_normal(wall_b, _mid(edge_b))
    if abs(_dot(wa, wb)) > 1e-6:
        raise KernelError("the two walls must meet square")
    # the walls rise along +h from the sheet they bend from
    box = kernel.bounding_box(shape)
    corners = [(x, y, z) for x in (box[0], box[3]) for y in (box[1], box[4])
               for z in (box[2], box[5])]
    low = min(_dot(c, h) for c in corners)
    high = max(_dot(c, h) for c in corners)
    if _dot(_mid(edge_a), h) - low < (high - _dot(_mid(edge_a), h)):
        h = _mul(h, -1.0)
        low, high = -high, -low
    # each wall's outside: the face of its two that is away from the part
    ma, mb = _mid(edge_a), _mid(edge_b)
    middle = kernel.volume_and_centre(shape)[1]

    def outside(wall_normal, here, there, wall_face):
        if _dot(_sub(middle, here), wall_normal) > 0:
            wall_normal = _mul(wall_normal, -1.0)
        plane_at = _dot(here, wall_normal)
        # the wall's outer face is the one of its pair further out
        best = plane_at
        for f in kernel.faces(shape):
            if _kind(f) != GeomAbs_Plane:
                continue
            c = kernel.shape_centre(f)
            if abs(_dot(face_normal(f, c), wall_normal) - 1.0) < 1e-6 \
                    and abs(_dot(c, wall_normal) - plane_at) <= thickness \
                    + 1e-6 and math.dist(c, here) < 4 * (high - low) + 1:
                best = max(best, _dot(c, wall_normal))
        return wall_normal, best

    na, pa = outside(wa, ma, mb, wall_a)
    nb, pb = outside(wb, mb, ma, wall_b)
    # the corner where the outsides and the sheet's outside meet
    # solve x.na = pa, x.nb = pb, x.h = low
    m = [na, nb, h]
    rhs = [pa, pb, low]
    det = _dot(m[0], _cross(m[1], m[2]))
    if abs(det) < 1e-12:
        raise KernelError("the corner cannot be found")
    c = _mul(_add(_add(_mul(_cross(m[1], m[2]), rhs[0]),
                       _mul(_cross(m[2], m[0]), rhs[1])),
                  _mul(_cross(m[0], m[1]), rhs[2])), 1.0 / det)
    # along each wall, into the part
    ua = _mul(nb, -1.0)          # wall a runs away from wall b's outside
    ub = _mul(na, -1.0)
    trim = thickness + gap / math.sqrt(2.0)
    back = setback(thickness, radius, 90.0)
    span = high - low

    def block(u0, u1, v0, v1, h0, h1):
        corners = []
        for uu, vv in ((u0, v0), (u1, v0), (u1, v1), (u0, v1)):
            corners.append(_add(_add(_add(c, _mul(ua, uu)), _mul(ub, vv)),
                                _mul(h, h0)))
        poly = BRepBuilderAPI_MakePolygon()
        for q in corners:
            poly.Add(gp_Pnt(*q))
        poly.Close()
        face = BRepBuilderAPI_MakeFace(poly.Wire(), True).Face()
        return BRepPrimAPI_MakePrism(face, gp_Vec(*_mul(h, h1 - h0))).Shape()

    # the bends stop at their own setback when that is further than the
    # walls' trim, so the two never meet; the walls stop at the trim
    bend_trim = max(trim, back)
    rise = radius + thickness
    cutter = kernel.fuse_all([
        block(-1.0, bend_trim, -1.0, bend_trim, -1.0, rise),
        block(-1.0, trim, -1.0, trim, rise, span + 1.0)])
    if bend_trim > back + 1e-9:
        # the corner of the sheet the two bend from stays
        cutter = kernel.boolean(
            cutter, block(back, bend_trim, back, bend_trim, -1.0, thickness),
            "cut")
    result = kernel.boolean(shape, cutter, "cut")
    if trim < back - 1e-9:
        # Above its bend a wall reaches in to the trim, past where a flange
        # made on its own could start it: the seam carries each wall on to
        # there, as the same corner made in one Flange has it
        def top(edge):
            return max(_dot(q, h) for q in _edge_ends(edge)) - low
        fills = [block(trim, back, 0.0, thickness, rise, top(edge_a)),
                 block(0.0, thickness, trim, back, rise, top(edge_b))]
        result = kernel.boolean(result, kernel.fuse_all(fills), "join")
    return result


# ------------------------------------------------------------------- fold


def _half_space(origin, normal, size):
    """A big box on the side of a plane its normal points to."""
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeHalfSpace
    from OCP.gp import gp_Pln
    plane = BRepBuilderAPI_MakeFace(
        gp_Pln(gp_Pnt(*origin), gp_Dir(*normal))).Face()
    reference = gp_Pnt(*_add(origin, _mul(normal, 1.0)))
    return BRepPrimAPI_MakeHalfSpace(plane, reference).Solid()


def fold(shape: TopoDS_Shape, plane_origin, plane_normal, p0, p1,
         thickness: float, radius: float, angle_deg: float, k: float,
         flip_side: bool = False, flip_direction: bool = False
         ) -> TopoDS_Shape:
    """Inventor's Fold: the sheet bent along a line drawn on its face.

    The line is the bend's centre line, Inventor's default: the bend takes
    half its flat length from each side, so the flat pattern is the sheet
    as it was.  The side of the line to the left of p0 -> p1, seen from the
    face, turns towards the face's outside, unless flipped.
    """
    if not 0 < angle_deg <= 180:
        raise KernelError("a fold's angle must be between 0 and 180")
    if thickness <= 0 or radius < 0:
        raise KernelError("thickness and radius must be more than 0")
    n = _unit(plane_normal)
    d = _sub(p1, p0)
    d = _sub(d, _mul(n, _dot(d, n)))
    if math.sqrt(_dot(d, d)) < 1e-9:
        raise KernelError("the fold line has no length")
    d = _unit(d)
    # n points out of the sheet, away from its material
    probe = _add(_add(p0, _mul(_sub(p1, p0), 0.5)), _mul(n, -thickness / 2))
    solids = kernel.explore(shape, TopAbs_SOLID)
    if not any(_inside(sol, probe) for sol in solids):
        n = _mul(n, -1.0)
    face_point = _add(p0, _mul(n, _dot(_sub(plane_origin, p0), n)))
    u = _cross(n, d)
    if flip_side:
        u = _mul(u, -1.0)
    towards = _mul(n, -1.0) if flip_direction else n
    a = math.radians(angle_deg)
    allowance = a * (radius + k * thickness)
    half = allowance / 2.0

    near = _add(face_point, _mul(u, -half))
    far = _add(face_point, _mul(u, half))
    box = kernel.bounding_box(shape)
    size = 4.0 * math.dist(box[:3], box[3:]) + 10.0
    keep = kernel.boolean(shape, _half_space(near, _mul(u, -1.0), size),
                          "intersect")
    moving = kernel.boolean(shape, _half_space(far, u, size), "intersect")

    # the bend: the cut face of what stays, turned about the bend's axis
    inner = face_point if not flip_direction \
        else _add(face_point, _mul(n, -thickness))
    axis_point = _add(_add(inner, _mul(u, -half)), _mul(towards, radius))
    axis = gp_Ax1(gp_Pnt(*axis_point), gp_Dir(*d))
    sign = 1.0 if _dot(_v(gp_Vec(*u).Rotated(axis, 0.1)), towards) > 0 \
        else -1.0
    axis = gp_Ax1(gp_Pnt(*axis_point), gp_Dir(*_mul(d, sign)))
    sections = [f for f in kernel.faces(keep)
                if _kind(f) == GeomAbs_Plane
                and abs(_dot(face_normal(f, kernel.shape_centre(f)), u)
                        - 1.0) < 1e-6
                and abs(_dot(_sub(kernel.shape_centre(f), near), u)) < 1e-6]
    if not sections:
        raise KernelError("the fold line does not cross the sheet")
    pieces = [keep]
    for face in sections:
        pieces.append(BRepPrimAPI_MakeRevol(face, axis, a).Shape())
    move = gp_Trsf()
    move.SetTranslation(gp_Vec(*_mul(u, -allowance)))
    turn = gp_Trsf()
    turn.SetRotation(axis, a)
    placed = BRepBuilderAPI_Transform(moving, turn.Multiplied(move),
                                      True).Shape()
    pieces.append(placed)
    result = kernel.fuse_all(pieces)
    try:
        from OCP.ShapeUpgrade import ShapeUpgrade_UnifySameDomain
        unify = ShapeUpgrade_UnifySameDomain(result, True, True, True)
        unify.Build()
        result = unify.Shape()
    except Exception:
        pass
    return result


# ------------------------------------------------------------- the document


def measure(doc, base_face=None) -> Optional[float]:
    """The thickness of the part's body, from a base face as Inventor
    takes it when a body is converted, or from its biggest flat face."""
    shape = getattr(doc, "shape", None)
    if shape is None or not kernel.is_valid(shape):
        return None
    solids = kernel.explore(shape, TopAbs_SOLID)
    if base_face is not None:
        solid = next((sol for sol in solids
                      if any(f.IsSame(base_face) for f in kernel.faces(sol))),
                     None)
        if solid is None:
            raise KernelError("that face is not on the body")
        return thickness_of(solid, base_face)
    return thickness_of(max(solids, key=kernel.volume))


def convert(doc, thickness: Optional[str] = None, base_face=None,
            bend_radius: Optional[str] = None,
            k_factor: Optional[str] = None) -> SheetMetalDefaults:
    """Convert to Sheet Metal: the part keeps its file and its features
    and gains Sheet Metal Defaults, with the Thickness and BendRadius
    parameters every sheet metal feature reads.

    A part with a body already, a STEP file opened, is converted from a
    base face, as Inventor asks for one: its thickness is measured from
    there and the flat pattern lies on it.  Without one, the biggest flat
    face; an empty part starts at Inventor's default thickness.
    """
    if doc.sheet_metal is not None:
        return doc.sheet_metal
    if thickness is None:
        thickness = DEFAULT_THICKNESS if doc.units != "in" else "0.12"
        try:
            measured = measure(doc, base_face)
            if measured is not None:
                thickness = ("%.4f" % measured).rstrip("0").rstrip(".")
        except (KernelError, ValueError):
            pass
    base = []
    if base_face is not None:
        from .naming import RefSet
        refs = RefSet()
        refs.capture_from(doc.shape, "face", [base_face])
        base = refs.to_list()
    names = set(doc.params.names())
    if "Thickness" not in names:
        doc.params.add("Thickness", thickness, doc.units,
                       "Sheet metal thickness")
    if "BendRadius" not in names:
        doc.params.add("BendRadius", "Thickness", doc.units,
                       "Sheet metal bend radius")
    else:
        doc.params.set_expression("Thickness", thickness)
    if bend_radius is not None:
        doc.params.set_expression("BendRadius", bend_radius)
    doc.sheet_metal = SheetMetalDefaults("Thickness", "BendRadius",
                                         k_factor or DEFAULT_K)
    doc.sheet_metal.base = base
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
    base = None
    if doc.sheet_metal.base:
        from .naming import RefSet
        found = RefSet.from_list(doc.sheet_metal.base).resolve_all(shape)[0]
        if not found:
            raise KernelError("the base face it was converted from is gone; "
                              "convert it again")
        base = found[0]
    flat = unfold(shape, k, base=base, thickness=t)
    for feature in doc.sheet_metal.flat_features:
        if feature.suppressed:
            continue
        feature.error = ""
        try:
            flat = feature.apply(flat, scope)
        except (KernelError, ValueError) as exc:
            feature.error = str(exc)
    return flat


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


# ------------------------------------------------------- the flat's features


@dataclass
class FlatFeature:
    """A feature of the Flat Pattern's own tree, applied to the sheet laid
    flat after everything the folded part does.  Only the Bend Perforation
    so far."""

    kind: str = "perforation"
    name: str = "Bend Perforation"
    suppressed: bool = False
    # Bend Perforation: slots down each bend line, with bridges of sheet
    # between them, so a plate cut flat can be bent by hand along them
    bends: str = "all"              # "all", or bend numbers "1, 3"
    style: str = "zigzag"           # zigzag (V shaped slots) or straight
    width: str = "1.5"              # the slot, as the cutter leaves it
    slot: str = "20"                # each slot's length along the bend
    bridge: str = "3"               # the sheet left between two slots
    margin: str = "Thickness * 2"   # sheet left whole at each end
    depth: str = "Thickness"        # how far a zigzag reaches off the line
    error: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {"kind": self.kind, "name": self.name,
                "suppressed": self.suppressed, "bends": self.bends,
                "style": self.style, "width": self.width, "slot": self.slot,
                "bridge": self.bridge, "margin": self.margin,
                "depth": self.depth}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FlatFeature":
        out = cls()
        for key in ("kind", "name", "bends", "style", "width", "slot",
                    "bridge", "margin", "depth"):
            if key in data:
                setattr(out, key, str(data[key]))
        out.suppressed = bool(data.get("suppressed", False))
        return out

    def chosen(self, count: int) -> List[int]:
        """Which bends, by index from 0."""
        text = (self.bends or "all").strip().lower()
        if text == "all":
            return list(range(count))
        out = []
        for part in text.replace(";", ",").split(","):
            part = part.strip()
            if not part:
                continue
            number = int(part)
            if not 1 <= number <= count:
                raise ValueError("there is no bend %d; the flat has %d"
                                 % (number, count))
            out.append(number - 1)
        return out

    def slots(self, flat: FlatPattern, scope: Dict[str, float]
              ) -> List[TopoDS_Shape]:
        """The slots, as faces on the flat."""
        from .params import evaluate
        width = float(evaluate(self.width, scope))
        slot = float(evaluate(self.slot, scope))
        bridge = float(evaluate(self.bridge, scope))
        margin = float(evaluate(self.margin, scope))
        depth = float(evaluate(self.depth, scope))
        if width <= 0 or slot <= 0 or bridge <= 0 or margin < 0:
            raise ValueError("the slot, its width and the bridges must be "
                             "more than 0")
        faces = []
        for index in self.chosen(len(flat.bends)):
            a, b, _angle = flat.bends[index]
            length = math.dist(a, b)
            usable = length - 2.0 * margin
            if usable < slot * 0.5:
                raise ValueError("bend %d is too short for its margins"
                                 % (index + 1))
            count = max(1, int((usable + bridge) // (slot + bridge)))
            each = (usable - (count - 1) * bridge) / count
            along = ((b[0] - a[0]) / length, (b[1] - a[1]) / length)
            across = (-along[1], along[0])
            for i in range(count):
                start = margin + i * (each + bridge)
                end = start + each
                p0 = (a[0] + along[0] * start, a[1] + along[1] * start)
                p1 = (a[0] + along[0] * end, a[1] + along[1] * end)
                if self.style == "zigzag":
                    mid = ((p0[0] + p1[0]) / 2 - across[0] * depth,
                           (p0[1] + p1[1]) / 2 - across[1] * depth)
                    points = [(p0[0] + across[0] * depth,
                               p0[1] + across[1] * depth), mid,
                              (p1[0] + across[0] * depth,
                               p1[1] + across[1] * depth)]
                else:
                    points = [p0, p1]
                faces.append(_slot_face(points, width))
        return faces

    def apply(self, flat: FlatPattern, scope: Dict[str, float]
              ) -> FlatPattern:
        faces = self.slots(flat, scope)
        if not faces:
            return flat
        cutter = faces[0] if len(faces) == 1 else kernel.compound(faces)
        outline = _cut_faces(flat.outline(), cutter)
        out = FlatPattern(faces=kernel.faces(outline), bends=list(flat.bends),
                          thickness=flat.thickness)
        try:
            out.solid = BRepPrimAPI_MakePrism(
                out.outline(), gp_Vec(0.0, 0.0, -flat.thickness)).Shape()
        except Exception:
            out.solid = None
        return out


def _slot_face(points, width: float) -> TopoDS_Shape:
    """A slot round a polyline on XY, ``width`` across, its ends round as
    a cutter leaves them."""
    from OCP.BRepOffsetAPI import BRepOffsetAPI_MakeOffset
    from OCP.GeomAbs import GeomAbs_Arc
    if len(points) == 2:
        # one straight line gives an offset no plane to work in: the
        # rounded slot is drawn as it is, two lines and two half circles
        from OCP.BRepBuilderAPI import (BRepBuilderAPI_MakeEdge,
                                        BRepBuilderAPI_MakeWire)
        from OCP.GC import GC_MakeArcOfCircle
        (x0, y0), (x1, y1) = points
        length = math.hypot(x1 - x0, y1 - y0)
        ux, uy = (x1 - x0) / length, (y1 - y0) / length
        nx, ny = -uy * width / 2.0, ux * width / 2.0
        r = width / 2.0
        a = gp_Pnt(x0 + nx, y0 + ny, 0.0)
        b = gp_Pnt(x1 + nx, y1 + ny, 0.0)
        c = gp_Pnt(x1 - nx, y1 - ny, 0.0)
        d = gp_Pnt(x0 - nx, y0 - ny, 0.0)
        tip1 = gp_Pnt(x1 + ux * r, y1 + uy * r, 0.0)
        tip0 = gp_Pnt(x0 - ux * r, y0 - uy * r, 0.0)
        wire = BRepBuilderAPI_MakeWire()
        wire.Add(BRepBuilderAPI_MakeEdge(a, b).Edge())
        wire.Add(BRepBuilderAPI_MakeEdge(
            GC_MakeArcOfCircle(b, tip1, c).Value()).Edge())
        wire.Add(BRepBuilderAPI_MakeEdge(c, d).Edge())
        wire.Add(BRepBuilderAPI_MakeEdge(
            GC_MakeArcOfCircle(d, tip0, a).Value()).Edge())
        return BRepBuilderAPI_MakeFace(wire.Wire(), True).Face()
    poly = BRepBuilderAPI_MakePolygon()
    for x, y in points:
        poly.Add(gp_Pnt(x, y, 0.0))
    wire = poly.Wire()
    maker = BRepOffsetAPI_MakeOffset()
    maker.Init(GeomAbs_Arc, False)
    maker.AddWire(wire)
    maker.Perform(width / 2.0)
    if not maker.IsDone():
        raise KernelError("could not draw a slot")
    loops = kernel.explore(maker.Shape(), TopAbs_WIRE)
    if not loops:
        raise KernelError("could not draw a slot")
    return BRepBuilderAPI_MakeFace(TopoDS.Wire_s(loops[0]), True).Face()


def _cut_faces(outline: TopoDS_Shape, cutter: TopoDS_Shape) -> TopoDS_Shape:
    """Flat faces less flat faces, on one plane."""
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
    algo = BRepAlgoAPI_Cut(outline, cutter)
    if not algo.IsDone():
        raise KernelError("the slots could not be cut")
    return algo.Shape()
