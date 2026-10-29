"""Thin, well-behaved wrapper around the OpenCASCADE modelling calls.

Everything that touches OCCT lives here so the rest of the application deals
in plain Python.  Each operation validates its result and raises
:class:`KernelError` with a readable message instead of letting a failed
algorithm return a null shape that explodes three calls later.
"""

from __future__ import annotations

import math
from collections import OrderedDict
import os
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from OCP.BRep import BRep_Builder, BRep_Tool
from OCP.BRepAlgoAPI import (
    BRepAlgoAPI_Common, BRepAlgoAPI_Cut, BRepAlgoAPI_Fuse, BRepAlgoAPI_Section,
)
from OCP.BRepBuilderAPI import (
    BRepBuilderAPI_Copy, BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeFace,
    BRepBuilderAPI_MakePolygon, BRepBuilderAPI_MakeVertex,
    BRepBuilderAPI_MakeWire, BRepBuilderAPI_Sewing, BRepBuilderAPI_Transform,
)
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepFilletAPI import BRepFilletAPI_MakeChamfer, BRepFilletAPI_MakeFillet
from OCP.BRepGProp import BRepGProp
from OCP.BRepOffsetAPI import BRepOffsetAPI_MakeThickSolid, BRepOffsetAPI_MakePipe
from OCP.BRepPrimAPI import (
    BRepPrimAPI_MakeBox, BRepPrimAPI_MakeCone, BRepPrimAPI_MakeCylinder,
    BRepPrimAPI_MakePrism, BRepPrimAPI_MakeRevol, BRepPrimAPI_MakeSphere,
    BRepPrimAPI_MakeTorus,
)
from OCP.BRepOffset import BRepOffset_Mode
from OCP.Bnd import Bnd_Box
from OCP.BRepBndLib import BRepBndLib
from OCP.GProp import GProp_GProps
from OCP.GeomAPI import GeomAPI_PointsToBSpline
from OCP.GeomAbs import GeomAbs_JoinType
from OCP.ShapeFix import ShapeFix_Face, ShapeFix_Shape
from OCP.TColgp import TColgp_Array1OfPnt
from OCP.TopAbs import (
    TopAbs_EDGE, TopAbs_FACE, TopAbs_ShapeEnum, TopAbs_SOLID, TopAbs_VERTEX,
    TopAbs_WIRE, TopAbs_COMPOUND,
)
from OCP.TopExp import TopExp, TopExp_Explorer
from OCP.ShapeUpgrade import ShapeUpgrade_UnifySameDomain
from OCP.TopTools import TopTools_IndexedMapOfShape, TopTools_ListOfShape
from OCP.TopoDS import (TopoDS, TopoDS_Compound, TopoDS_Edge, TopoDS_Face,
                        TopoDS_Iterator, TopoDS_Shape)
from OCP.gp import (
    gp_Ax1, gp_Ax2, gp_Ax3, gp_Circ, gp_Dir, gp_Pln, gp_Pnt, gp_Trsf, gp_Vec,
)

from .sketch import Sketch, SketchPlane, point_in_polygon, polygon_area

MakePolygon = BRepBuilderAPI_MakePolygon

TOL = 1e-7


# OpenCASCADE will run a boolean across cores if it is told to, and it is
# not told to by default.  Measured on the excavator: the whole assembly
# builds about 7 per cent faster and the result is identical to the last
# decimal, which is the only reason to take it.  Off by setting
# DATUM_SERIAL_BOOLEANS, because parallel evaluation is the sort of thing
# that turns out to matter on one machine in a thousand.
def _enable_parallel_booleans() -> None:
    if os.environ.get("DATUM_SERIAL_BOOLEANS"):
        return
    try:
        from OCP.BOPAlgo import BOPAlgo_Options

        BOPAlgo_Options.SetParallelMode_s(True)
    except Exception:
        pass


_enable_parallel_booleans()

# and meshing, which is most of what drawing a body costs; see mesh.py
from . import mesh as _mesh                                   # noqa: E402

_mesh.enable_parallel_default()


class KernelError(RuntimeError):
    """A modelling operation failed."""


# ==========================================================================
# small helpers
# ==========================================================================


def pnt(xyz: Sequence[float]) -> gp_Pnt:
    return gp_Pnt(float(xyz[0]), float(xyz[1]), float(xyz[2]))


def vec(xyz: Sequence[float]) -> gp_Vec:
    return gp_Vec(float(xyz[0]), float(xyz[1]), float(xyz[2]))


def direction(xyz: Sequence[float]) -> gp_Dir:
    return gp_Dir(float(xyz[0]), float(xyz[1]), float(xyz[2]))


def plane_ax2(plane: SketchPlane) -> gp_Ax2:
    return gp_Ax2(pnt(plane.origin), direction(plane.normal), direction(plane.xdir))


def plane_gp(plane: SketchPlane) -> gp_Pln:
    return gp_Pln(gp_Ax3(plane_ax2(plane)))


def explore(shape: TopoDS_Shape, kind: TopAbs_ShapeEnum) -> List[TopoDS_Shape]:
    """All sub-shapes of ``kind``, de-duplicated, in deterministic order.

    OpenCASCADE's indexed map, not a list searched for each new one. The
    list compared every edge with every edge before it, which on an
    assembly of 48 components was eighteen million comparisons and seven
    seconds of every open. The map hashes instead, and gives the same
    shapes in the same order, first met first, by the same test of
    sameness, which matters because naming hangs off this order.
    """
    found = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(shape, kind, found)
    return [found.FindKey(i) for i in range(1, found.Extent() + 1)]


def faces(shape: TopoDS_Shape) -> List[TopoDS_Face]:
    return [TopoDS.Face_s(f) for f in explore(shape, TopAbs_FACE)]


def edges(shape: TopoDS_Shape) -> List[TopoDS_Edge]:
    return [TopoDS.Edge_s(e) for e in explore(shape, TopAbs_EDGE)]


def vertices(shape: TopoDS_Shape) -> List[TopoDS_Shape]:
    return explore(shape, TopAbs_VERTEX)


def same_shape(a: Optional[TopoDS_Shape],
               b: Optional[TopoDS_Shape]) -> bool:
    """Whether two shapes are the same geometry, not merely equal-looking.

    A multibody part is a fresh compound every rebuild even when every
    body in it is the one it was, so a compound is compared by what it
    holds, one level down.
    """
    if a is None or b is None or a.IsNull() or b.IsNull():
        return False
    if a.IsEqual(b):
        return True
    if (a.ShapeType() != TopAbs_COMPOUND
            or b.ShapeType() != TopAbs_COMPOUND):
        return False
    left, right = TopoDS_Iterator(a), TopoDS_Iterator(b)
    while left.More() and right.More():
        if not left.Value().IsEqual(right.Value()):
            return False
        left.Next()
        right.Next()
    return not left.More() and not right.More()


def is_valid(shape: Optional[TopoDS_Shape]) -> bool:
    return shape is not None and not shape.IsNull()


def bounding_box(shape: TopoDS_Shape) -> Tuple[float, float, float, float, float, float]:
    if shape.ShapeType() == TopAbs_COMPOUND:
        # a compound of many pieces, measured a piece at a time and each
        # piece only once: most of them are the same pieces as last time
        parts = pieces(shape)
        if len(parts) > 1:
            boxes = [b for b in map(_box_of, parts) if b != _NO_BOX]
            if not boxes:
                return _NO_BOX
            return (min(b[0] for b in boxes), min(b[1] for b in boxes),
                    min(b[2] for b in boxes), max(b[3] for b in boxes),
                    max(b[4] for b in boxes), max(b[5] for b in boxes))
    box = Bnd_Box()
    BRepBndLib.Add_s(shape, box, True)
    if box.IsVoid():
        return _NO_BOX
    return box.Get()


_NO_BOX = (0.0, 0.0, 0.0, 0.0, 0.0, 0.0)


def volume(shape: TopoDS_Shape) -> float:
    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, props)
    return props.Mass()


def surface_area(shape: TopoDS_Shape) -> float:
    props = GProp_GProps()
    BRepGProp.SurfaceProperties_s(shape, props)
    return props.Mass()


def volume_and_centre(shape: TopoDS_Shape
                      ) -> Tuple[float, Tuple[float, float, float]]:
    """Volume and centre of mass from the one integration that gives both.

    Asking for them separately integrates the whole body twice, which on a
    15 000 face import is two seconds each. And a body of many pieces is
    integrated a piece at a time, each piece once: after a hole through a
    300 solid import only the solids it cut are measured again, which is
    the difference between four and a half seconds and a few hundredths.
    Volume and first moments add up, so the sum is the whole.
    """
    total = 0.0
    moment = [0.0, 0.0, 0.0]
    for part in _measured_pieces(shape):
        volume, first = _measure(part, "volume")
        total += volume
        for axis in range(3):
            moment[axis] += first[axis]
    if abs(total) < 1e-12:
        # nothing to weigh the centre by: a sheet, or nothing at all
        props = GProp_GProps()
        BRepGProp.VolumeProperties_s(shape, props)
        p = props.CentreOfMass()
        return props.Mass(), (p.X(), p.Y(), p.Z())
    return total, (moment[0] / total, moment[1] / total, moment[2] / total)


def total_area(shape: TopoDS_Shape) -> float:
    """Surface area, a piece at a time and each piece once; see above."""
    return sum(_measure(part, "area")[0] for part in _measured_pieces(shape))


# Pieces already integrated, by what was asked of them: hash -> entries of
# (piece, what, answer). Kept to a size, oldest first out.
_MEASURES: "OrderedDict[int, list]" = OrderedDict()
_MEASURES_KEEP = 8192


def forget() -> None:
    """Let go of every piece measured or boxed, and whatever it keeps alive.

    A piece holds its mesh, so these would otherwise keep a closed import's
    three hundred solids in memory until eight thousand others pushed them
    out. They are worked out again when asked for.
    """
    _BOXES.clear()
    _MEASURES.clear()


def _measured_pieces(shape: TopoDS_Shape) -> List[TopoDS_Shape]:
    if shape.ShapeType() == TopAbs_COMPOUND:
        found = pieces(shape)
        if len(found) > 1:
            return found
    return [shape]


def _measured(piece: TopoDS_Shape, what: str):
    for held, kind, answer in _MEASURES.get(hash(piece), ()):
        if kind == what and held.IsEqual(piece):
            return answer
    return None


def unmeasured(shape: TopoDS_Shape) -> Tuple[List[TopoDS_Shape], List[int]]:
    """A body's pieces, and which of them have not been measured yet."""
    parts = _measured_pieces(shape)
    return parts, [i for i, part in enumerate(parts)
                   if _measured(part, "volume") is None
                   or _measured(part, "area") is None]


def remember_measure(piece: TopoDS_Shape, what: str, answer) -> None:
    """Take a measurement made elsewhere, a worker say, as made here."""
    if _measured(piece, what) is None:
        _keep_measure(piece, what, tuple(answer))


def _keep_measure(piece: TopoDS_Shape, what: str, answer) -> None:
    key = hash(piece)
    _MEASURES.setdefault(key, []).append((piece, what, answer))
    _MEASURES.move_to_end(key)
    while len(_MEASURES) > _MEASURES_KEEP:
        _MEASURES.popitem(last=False)


def _measure(piece: TopoDS_Shape, what: str):
    known = _measured(piece, what)
    if known is not None:
        return known
    props = GProp_GProps()
    if what == "volume":
        BRepGProp.VolumeProperties_s(piece, props)
        volume = props.Mass()
        p = props.CentreOfMass()
        answer = (volume, (volume * p.X(), volume * p.Y(), volume * p.Z()))
    else:
        BRepGProp.SurfaceProperties_s(piece, props)
        answer = (props.Mass(),)
    _keep_measure(piece, what, answer)
    return answer


def geometry_properties(shape: TopoDS_Shape) -> Dict[str, Any]:
    """Everything about a body's size that does not depend on its material."""
    vol, centre = volume_and_centre(shape)
    xmin, ymin, zmin, xmax, ymax, zmax = bounding_box(shape)
    return {
        "volume_mm3": vol,
        "area_mm2": total_area(shape),
        "centre": centre,
        "bbox": (xmax - xmin, ymax - ymin, zmax - zmin),
        "bbox_min": (xmin, ymin, zmin),
        "bbox_max": (xmax, ymax, zmax),
        "faces": len(faces(shape)),
        "edges": len(edges(shape)),
    }


def centre_of_mass(shape: TopoDS_Shape) -> Tuple[float, float, float]:
    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, props)
    p = props.CentreOfMass()
    return (p.X(), p.Y(), p.Z())


def edge_length(edge: TopoDS_Edge) -> float:
    props = GProp_GProps()
    BRepGProp.LinearProperties_s(edge, props)
    return props.Mass()


def face_area(face: TopoDS_Face) -> float:
    props = GProp_GProps()
    BRepGProp.SurfaceProperties_s(face, props)
    return props.Mass()


def shape_centre(shape: TopoDS_Shape) -> Tuple[float, float, float]:
    """Geometric centre of a sub-shape, used for persistent naming."""
    props = GProp_GProps()
    if shape.ShapeType() == TopAbs_VERTEX:
        p = BRep_Tool.Pnt_s(TopoDS.Vertex_s(shape))
        return (p.X(), p.Y(), p.Z())
    if shape.ShapeType() == TopAbs_EDGE:
        BRepGProp.LinearProperties_s(shape, props)
    else:
        BRepGProp.SurfaceProperties_s(shape, props)
    p = props.CentreOfMass()
    return (p.X(), p.Y(), p.Z())


def copy_shape(shape: TopoDS_Shape) -> TopoDS_Shape:
    return BRepBuilderAPI_Copy(shape).Shape()


def compound(shapes: Sequence[TopoDS_Shape]) -> TopoDS_Compound:
    comp = TopoDS_Compound()
    builder = BRep_Builder()
    builder.MakeCompound(comp)
    for s in shapes:
        if is_valid(s):
            builder.Add(comp, s)
    return comp


def heal(shape: TopoDS_Shape) -> TopoDS_Shape:
    """Repair small inconsistencies that upstream algorithms can leave.

    On a copy. ShapeFix mends faces where they stand, and the faces of a
    boolean's result are shared with the shapes that went into it, so
    healing a cut late in the tree was rewriting the body as it had been
    several features earlier: on one sample part its volume dropped by
    an eighth after the fact. Nothing looked back at earlier shapes, so
    it went unseen until results started being kept. A copy costs a
    little; a history that edits itself costs correctness.
    """
    try:
        work = BRepBuilderAPI_Copy(shape).Shape()
        fixer = ShapeFix_Shape(work)
        fixer.Perform()
        fixed = fixer.Shape()
        return fixed if is_valid(fixed) else shape
    except Exception:
        return shape


def check(shape: TopoDS_Shape, what: str) -> TopoDS_Shape:
    if not is_valid(shape):
        raise KernelError("%s produced no geometry" % what)
    if not BRepCheck_Analyzer(shape).IsValid():
        shape = heal(shape)
        if not BRepCheck_Analyzer(shape).IsValid():
            raise KernelError("%s produced an invalid solid" % what)
    return shape


# ==========================================================================
# sketch -> topology
# ==========================================================================


def _sketch_edge(sketch: Sketch, eid: int) -> Optional[TopoDS_Edge]:
    ent = sketch.entities[eid]
    plane = sketch.plane

    if ent.kind == "line":
        a = sketch.points[ent.points[0]]
        b = sketch.points[ent.points[1]]
        if math.hypot(b.x - a.x, b.y - a.y) < 1e-9:
            return None
        mk = BRepBuilderAPI_MakeEdge(pnt(plane.to_3d(a.x, a.y)),
                                     pnt(plane.to_3d(b.x, b.y)))
        return mk.Edge() if mk.IsDone() else None

    if ent.kind in ("circle", "arc"):
        if ent.radius < 1e-9:
            return None
        c = sketch.points[ent.points[0]]
        ax2 = gp_Ax2(pnt(plane.to_3d(c.x, c.y)),
                     direction(plane.normal), direction(plane.xdir))
        circ = gp_Circ(ax2, ent.radius)
        if ent.kind == "circle":
            mk = BRepBuilderAPI_MakeEdge(circ)
        else:
            a0, a1 = sketch.arc_angles(eid)
            if abs(a1 - a0) < 1e-9:
                return None
            mk = BRepBuilderAPI_MakeEdge(circ, a0, a1)
        return mk.Edge() if mk.IsDone() else None

    if ent.kind == "spline":
        pts = [sketch.points[p] for p in ent.points]
        if len(pts) < 2:
            return None
        arr = TColgp_Array1OfPnt(1, len(pts))
        for i, p in enumerate(pts, start=1):
            arr.SetValue(i, pnt(plane.to_3d(p.x, p.y)))
        curve = GeomAPI_PointsToBSpline(arr).Curve()
        mk = BRepBuilderAPI_MakeEdge(curve)
        return mk.Edge() if mk.IsDone() else None

    return None


def _chains(sketch: Sketch) -> Tuple[List[List[int]], List[List[int]]]:
    """Split a sketch's geometry into (closed loops, open chains)."""
    ents = {eid: e for eid, e in sketch.entities.items()
            if not e.construction and e.kind in ("line", "arc", "circle", "spline")}

    loops: List[List[int]] = []
    open_chains: List[List[int]] = []

    # circles are self-closed
    for eid, e in list(ents.items()):
        if e.kind == "circle":
            loops.append([eid])
            del ents[eid]

    def ends(eid: int) -> Tuple[int, int]:
        e = ents[eid]
        if e.kind == "arc":
            return e.points[1], e.points[2]
        return e.points[0], e.points[-1]

    adjacency: Dict[int, List[int]] = {}
    for eid in ents:
        a, b = ends(eid)
        adjacency.setdefault(a, []).append(eid)
        adjacency.setdefault(b, []).append(eid)

    unused = set(ents)
    while unused:
        start = min(unused)
        chain = [start]
        unused.discard(start)
        a, b = ends(start)
        head, tail = a, b

        while True:
            nxt = None
            for cand in adjacency.get(tail, []):
                if cand in unused:
                    nxt = cand
                    break
            if nxt is None:
                break
            unused.discard(nxt)
            chain.append(nxt)
            ca, cb = ends(nxt)
            tail = cb if ca == tail else ca
            if tail == head:
                break

        while tail != head:
            prev = None
            for cand in adjacency.get(head, []):
                if cand in unused:
                    prev = cand
                    break
            if prev is None:
                break
            unused.discard(prev)
            chain.insert(0, prev)
            ca, cb = ends(prev)
            head = cb if ca == head else ca

        if tail == head and len(chain) >= 2:
            loops.append(chain)
        elif chain:
            open_chains.append(chain)

    return loops, open_chains


def _loops(sketch: Sketch) -> List[List[int]]:
    """Closed chains of sketch entities, walking the connectivity graph."""
    return _chains(sketch)[0]


def sketch_path_wire(sketch: Sketch) -> Any:
    """The longest open chain in a sketch, as a wire - a sweep path.

    A closed loop is accepted too, so a sweep can follow a full profile.
    """
    loops, open_chains = _chains(sketch)
    candidates = sorted(open_chains + loops, key=len, reverse=True)
    for chain in candidates:
        mk = BRepBuilderAPI_MakeWire()
        ok = True
        for eid in chain:
            edge = _sketch_edge(sketch, eid)
            if edge is None:
                ok = False
                break
            mk.Add(edge)
        if ok and mk.IsDone():
            return mk.Wire()
    raise KernelError("sketch '%s' has no usable path curve" % sketch.name)


def open_chain_wire(sketch: Sketch) -> Any:
    """The longest open chain of a sketch as a wire, Match Shape's profile;
    None when every curve in it closes on itself."""
    _closed, open_chains = _chains(sketch)
    for chain in sorted(open_chains, key=len, reverse=True):
        mk = BRepBuilderAPI_MakeWire()
        ok = True
        for eid in chain:
            edge = _sketch_edge(sketch, eid)
            if edge is None:
                ok = False
                break
            mk.Add(edge)
        if ok and mk.IsDone():
            return mk.Wire()
    return None


def sketch_wires(sketch: Sketch) -> List[Any]:
    """Closed wires built from a sketch's non-construction geometry."""
    out = []
    for loop in _loops(sketch):
        mk = BRepBuilderAPI_MakeWire()
        ok = True
        for eid in loop:
            e = _sketch_edge(sketch, eid)
            if e is None:
                ok = False
                break
            mk.Add(e)
        if ok and mk.IsDone():
            out.append(mk.Wire())
    return out


def _loop_polyline(sketch: Sketch, loop: Sequence[int]) -> List[Tuple[float, float]]:
    pts: List[Tuple[float, float]] = []
    for eid in loop:
        pts.extend(sketch.entity_polyline(eid, 24))
    return pts


def _iterate_shapes(collection) -> List[TopoDS_Shape]:
    """OCCT shape lists are not uniformly iterable from Python."""
    try:
        return [s for s in collection]
    except TypeError:
        pass
    out: List[TopoDS_Shape] = []
    try:
        from OCP.TopTools import TopTools_ListIteratorOfListOfShape

        it = TopTools_ListIteratorOfListOfShape(collection)
        while it.More():
            out.append(it.Value())
            it.Next()
    except Exception:
        pass
    return out


def _split_at_intersections(edge_list: Sequence[TopoDS_Edge]
                            ) -> List[TopoDS_Edge]:
    """Cut every edge where another crosses it.

    Without this, three overlapping circles are three closed curves; with
    it they become the twelve arcs that bound the seven regions a Venn
    diagram actually has.
    """
    if len(edge_list) < 2:
        return list(edge_list)

    from OCP.BOPAlgo import BOPAlgo_Builder

    try:
        builder = BOPAlgo_Builder()
        for edge in edge_list:
            builder.AddArgument(edge)
        builder.SetRunParallel(False)
        builder.SetFuzzyValue(1e-7)
        builder.Perform()
        if builder.HasErrors():
            return list(edge_list)
        result = builder.Shape()
        if not is_valid(result):
            return list(edge_list)
        split = edges(result)
        return split or list(edge_list)
    except Exception:
        return list(edge_list)


def _bounding_only(edge_list: Sequence[TopoDS_Edge]) -> List[TopoDS_Edge]:
    """The pieces of curve that bound something, loose ends pruned away.

    A line with an end hanging free inside a region does not divide it,
    and handed to the splitter anyway it is sewn into the region's face as
    an edge of its own: the extrusion then carries it into the solid as a
    line across the top, fillets trip over it, and the regions round it can
    come out wrong.  So any piece with an end nothing else meets is dropped,
    and again, until every piece left is part of some loop.  The edges have
    been cut where they cross already, so a line crossing a circle right
    through still divides it, as it should.
    """
    from OCP.BRep import BRep_Tool
    from OCP.TopExp import TopExp

    def key(vertex) -> Tuple[float, float, float]:
        p = BRep_Tool.Pnt_s(vertex)
        return (round(p.X(), 6), round(p.Y(), 6), round(p.Z(), 6))

    pieces = list(edge_list)
    ends = []
    for edge in pieces:
        try:
            ends.append((key(TopExp.FirstVertex_s(edge)),
                         key(TopExp.LastVertex_s(edge))))
        except Exception:
            ends.append(None)
    while True:
        degree: Dict[Tuple[float, float, float], int] = {}
        for pair in ends:
            if pair is None:
                continue
            for point in pair:
                degree[point] = degree.get(point, 0) + 1
        keep = [i for i, pair in enumerate(ends)
                if pair is None or pair[0] == pair[1]
                or (degree[pair[0]] > 1 and degree[pair[1]] > 1)]
        if len(keep) == len(pieces):
            return pieces
        pieces = [pieces[i] for i in keep]
        ends = [ends[i] for i in keep]


def _host_face(sketch: Sketch, margin: float = 1.6):
    """A rectangle on the sketch plane comfortably bigger than the sketch."""
    umin, vmin, umax, vmax = sketch.bounds()
    du = max(umax - umin, 1.0) * margin
    dv = max(vmax - vmin, 1.0) * margin
    cu, cv = (umin + umax) / 2.0, (vmin + vmax) / 2.0

    poly = BRepBuilderAPI_MakePolygon()
    for u, v in ((cu - du, cv - dv), (cu + du, cv - dv),
                 (cu + du, cv + dv), (cu - du, cv + dv)):
        poly.Add(pnt(sketch.plane.to_3d(u, v)))
    poly.Close()
    if not poly.IsDone():
        raise KernelError("could not build the sketch's working plane")
    return BRepBuilderAPI_MakeFace(poly.Wire()).Face(), (cu, cv, du, dv)


def sketch_regions_faces(sketch: Sketch) -> List[TopoDS_Face]:
    """Every smallest closed region the sketch's curves bound.

    This is a real planar decomposition rather than a walk over closed
    loops: a sheet covering the sketch is split by every curve, and the
    pieces that do not reach the sheet's border are the enclosed regions.
    Three overlapping circles come back as seven separately selectable
    areas, which is what you would expect to be able to extrude.
    """
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Splitter

    curves: List[TopoDS_Edge] = []
    for eid, entity in sketch.entities.items():
        if entity.construction:
            continue
        edge = _sketch_edge(sketch, eid)
        if edge is not None:
            curves.append(edge)
    if not curves:
        return []
    # only what encloses something divides the sheet
    split = _split_at_intersections(curves)
    curves = _bounding_only(split)
    if not curves:
        return []
    pruned = len(curves) < len(split)

    try:
        host, (cu, cv, du, dv) = _host_face(sketch)

        arguments = TopTools_ListOfShape()
        arguments.Append(host)
        tools = TopTools_ListOfShape()
        for edge in curves:
            tools.Append(edge)

        splitter = BRepAlgoAPI_Splitter()
        splitter.SetArguments(arguments)
        splitter.SetTools(tools)
        splitter.SetFuzzyValue(1e-7)
        splitter.SetRunParallel(False)
        splitter.Build()
        if not splitter.IsDone():
            return []
        pieces = faces(splitter.Shape())
    except Exception:
        return []

    out: List[TopoDS_Face] = []
    for face in pieces:
        if face_area(face) < 1e-9:
            continue
        if _touches_border(face, sketch, cu, cv, du, dv):
            continue                  # leftover sheet outside the sketch
        out.append(_whole_edges(face) if pruned else face)

    # deterministic order, so a region keeps its place between rebuilds
    out.sort(key=lambda f: (round(-face_area(f), 6),
                            round(shape_centre(f)[0], 6),
                            round(shape_centre(f)[1], 6),
                            round(shape_centre(f)[2], 6)))
    return out


def _whole_edges(face: TopoDS_Face) -> TopoDS_Face:
    """A region with its outline in as few edges as its curves allow.

    Where a loose line was pruned away, the point it crossed the outline
    at is left behind, cutting a circle into two arcs or a side into two
    lines.  Extruded, that point is an edge down the side of the solid.
    Joining the pieces of one curve back up gets rid of it.
    """
    try:
        joined = unify(face)
    except Exception:
        return face
    if joined is face or joined.IsNull():
        return face
    if joined.ShapeType() == TopAbs_FACE:
        return TopoDS.Face_s(joined)
    found = faces(joined)
    return found[0] if len(found) == 1 else face


def _touches_border(face: TopoDS_Face, sketch: Sketch, cu: float, cv: float,
                    du: float, dv: float) -> bool:
    for vertex in vertices(face):
        u, v = sketch.plane.to_2d(shape_centre(vertex))
        if abs(abs(u - cu) - du) < 1e-6 or abs(abs(v - cv) - dv) < 1e-6:
            return True
    return False


# ---------------------------------------------------------------- text

_TEXT_CACHE: Dict[Tuple, TopoDS_Shape] = {}


def _text_raw(text: str, font: str, size: float, bold: bool, italic: bool,
              top: bool = False) -> Optional[TopoDS_Shape]:
    """OpenCASCADE's letters for ``text``, the bottom of the block (or its
    top) on the X axis."""
    from OCP.Font import Font_FontAspect
    from OCP.Graphic3d import (Graphic3d_HorizontalTextAlignment,
                               Graphic3d_VerticalTextAlignment)
    from OCP.NCollection import NCollection_Utf8String
    from OCP.StdPrs import StdPrs_BRepFont, StdPrs_BRepTextBuilder
    from OCP.TCollection import TCollection_AsciiString

    aspect = (Font_FontAspect.Font_FontAspect_BoldItalic if bold and italic
              else Font_FontAspect.Font_FontAspect_Bold if bold
              else Font_FontAspect.Font_FontAspect_Italic if italic
              else Font_FontAspect.Font_FontAspect_Regular)
    brep_font = StdPrs_BRepFont()
    if not brep_font.FindAndInit(TCollection_AsciiString(font or "Arial"),
                                 aspect, float(size)):
        return None
    try:
        shape = StdPrs_BRepTextBuilder().Perform(
            brep_font, NCollection_Utf8String(text), gp_Ax3(),
            Graphic3d_HorizontalTextAlignment.Graphic3d_HTA_LEFT,
            Graphic3d_VerticalTextAlignment.Graphic3d_VTA_TOP if top
            else Graphic3d_VerticalTextAlignment.Graphic3d_VTA_BOTTOM)
    except Exception:
        return None
    if shape is None or shape.IsNull() or not faces(shape):
        return None
    return shape


def _text_outline(text: str, font: str, size: float, bold: bool,
                  italic: bool) -> Optional[TopoDS_Shape]:
    """The letters of ``text`` as planar faces, holes and all, on the XY
    plane with the bottom of the first line at the origin; lines broken at
    newlines go down from it.  Made by OpenCASCADE from the font itself,
    and kept, since the same text comes up on every rebuild."""
    key = (text, font, round(float(size), 9), bool(bold), bool(italic))
    if key in _TEXT_CACHE:
        return _TEXT_CACHE[key]
    if not text.strip() or size <= 0:
        return None
    lines = text.split("\n")
    first = lines[0] if lines[0].strip() else "x"
    shape = _text_raw(text, font, size, bold, italic, top=len(lines) > 1)
    if shape is not None and len(lines) > 1:
        # the block hangs from its top, as the first line alone does: the
        # first line put where it sits on its own carries the rest along
        on_own = _text_raw(first, font, size, bold, italic)
        hung = _text_raw(first, font, size, bold, italic, top=True)
        if on_own is not None and hung is not None:
            low, high = Bnd_Box(), Bnd_Box()
            BRepBndLib.Add_s(on_own, low)
            BRepBndLib.Add_s(hung, high)
            drop = low.CornerMax().Y() - high.CornerMax().Y()
            shape = BRepBuilderAPI_Transform(
                shape, _translation((0.0, drop, 0.0)), True).Shape()
    if len(_TEXT_CACHE) > 200:
        _TEXT_CACHE.clear()
    _TEXT_CACHE[key] = shape
    return shape


def text_faces(sketch: Sketch, tid: int) -> List[TopoDS_Face]:
    """The faces of one sketch text, in place on the sketch's plane."""
    record = sketch.texts.get(tid)
    if record is None or record.point not in sketch.points:
        return []
    outline = _text_outline(record.text, record.font, record.size,
                            record.bold, record.italic)
    if outline is None:
        return []
    anchor = sketch.points[record.point]
    plane = sketch.plane
    a = math.radians(record.angle)
    xd = [math.cos(a) * x + math.sin(a) * y
          for x, y in zip(plane.xdir, plane.ydir)]
    place = gp_Trsf()
    place.SetTransformation(
        gp_Ax3(pnt(plane.to_3d(anchor.x, anchor.y)), direction(plane.normal),
               direction(xd)),
        gp_Ax3())
    placed = BRepBuilderAPI_Transform(outline, place, True).Shape()
    return faces(placed)


def sketch_text_faces(sketch: Sketch) -> Dict[int, List[TopoDS_Face]]:
    """Every text of a sketch, as its faces, by text id."""
    out: Dict[int, List[TopoDS_Face]] = {}
    for tid in getattr(sketch, "texts", {}):
        found = text_faces(sketch, tid)
        if found:
            out[tid] = found
    return out


def text_box(sketch: Sketch, tid: int
             ) -> Optional[List[Tuple[float, float]]]:
    """The four corners of a text's box, in sketch coordinates, anticlockwise
    from its bottom left: what is drawn round it and picked."""
    record = sketch.texts.get(tid)
    if record is None or record.point not in sketch.points:
        return None
    outline = _text_outline(record.text, record.font, record.size,
                            record.bold, record.italic)
    if outline is None:
        x0, y0, x1, y1 = 0.0, 0.0, record.size * 2.0, record.size * 0.7
    else:
        box = Bnd_Box()
        BRepBndLib.Add_s(outline, box)
        x0, y0 = min(0.0, box.CornerMin().X()), box.CornerMin().Y()
        x1, y1 = box.CornerMax().X(), box.CornerMax().Y()
    anchor = sketch.points[record.point]
    a = math.radians(record.angle)
    c, s = math.cos(a), math.sin(a)
    return [(anchor.x + x * c - y * s, anchor.y + x * s + y * c)
            for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1))]


def sketch_faces(sketch: Sketch) -> List[TopoDS_Face]:
    """Planar faces from a sketch, with nested loops turned into holes.

    Nesting is resolved in 2D on the sketch itself (parity of containment),
    which is far more reliable than trying to infer it from the built wires.
    Text adds its letters.
    """
    lettering = [f for found in sketch_text_faces(sketch).values()
                 for f in found]
    return _loop_faces(sketch) + lettering


def _loop_faces(sketch: Sketch) -> List[TopoDS_Face]:
    loops = _loops(sketch)
    if not loops:
        return []

    polys = [_loop_polyline(sketch, lp) for lp in loops]
    wires = []
    for lp in loops:
        mk = BRepBuilderAPI_MakeWire()
        ok = True
        for eid in lp:
            e = _sketch_edge(sketch, eid)
            if e is None:
                ok = False
                break
            mk.Add(e)
        wires.append(mk.Wire() if ok and mk.IsDone() else None)

    # depth[i] = how many other loops contain loop i
    depth = [0] * len(loops)
    for i, poly_i in enumerate(polys):
        if not poly_i:
            continue
        probe = poly_i[len(poly_i) // 3]
        for j, poly_j in enumerate(polys):
            if i == j or len(poly_j) < 3:
                continue
            if point_in_polygon(probe, poly_j):
                depth[i] += 1

    pln = plane_gp(sketch.plane)
    result: List[TopoDS_Face] = []

    for i, wire in enumerate(wires):
        if wire is None or depth[i] % 2 == 1:
            continue  # None = unbuildable, odd depth = a hole in someone else
        mk = BRepBuilderAPI_MakeFace(pln, wire)
        if not mk.IsDone():
            continue
        face = mk.Face()
        # add every loop that sits directly inside this one as a hole
        for j, inner in enumerate(wires):
            if inner is None or j == i or depth[j] != depth[i] + 1:
                continue
            if not polys[j] or not point_in_polygon(
                    polys[j][len(polys[j]) // 3], polys[i]):
                continue
            addition = BRepBuilderAPI_MakeFace(face)
            addition.Add(inner)
            if addition.IsDone():
                face = addition.Face()
        fixer = ShapeFix_Face(face)
        fixer.FixOrientation()
        result.append(fixer.Face())

    return result


def sketch_regions(sketch: Sketch) -> List[Dict[str, Any]]:
    """Every closed region of a sketch, with a fingerprint to identify it.

    Regions come from a planar decomposition, so overlapping curves give the
    smallest enclosed areas - three overlapping circles yield seven regions,
    each selectable on its own.
    """
    faces = sketch_regions_faces(sketch)
    if not faces:
        faces = _loop_faces(sketch)       # fall back to whole closed loops
    # each text is one region, every letter of it, so one click takes the
    # whole word
    for tid, letters in sketch_text_faces(sketch).items():
        faces = list(faces) + [letters[0] if len(letters) == 1
                               else compound(letters)]

    out: List[Dict[str, Any]] = []
    for index, face in enumerate(faces):
        # the identity point is one guaranteed to lie *on* the region: a
        # crescent's centre of mass falls outside it, which would make two
        # regions indistinguishable
        inside = _inside_point(
            face if face.ShapeType() == TopAbs_FACE
            else TopoDS.Face_s(explore(face, TopAbs_FACE)[0]), sketch)
        out.append({
            "index": index,
            "face": face,
            "centre": inside,
            "centroid": sketch.plane.to_2d(shape_centre(face)),
            "area": face_area(face),
        })
    return out


def _inside_point(face: TopoDS_Face, sketch: Sketch) -> Tuple[float, float]:
    """A point that really lies on the face, in sketch coordinates.

    A crescent's centre of mass falls outside it, so the centroid alone is
    not enough to tell two regions apart or to hit-test one.
    """
    from OCP.BRepTopAdaptor import BRepTopAdaptor_FClass2d
    from OCP.TopAbs import TopAbs_OUT
    from OCP.BRepTools import BRepTools
    from OCP.ElSLib import ElSLib
    from OCP.gp import gp_Pnt2d

    from OCP.BRepAdaptor import BRepAdaptor_Surface

    centre = sketch.plane.to_2d(shape_centre(face))
    try:
        classifier = BRepTopAdaptor_FClass2d(face, 1e-6)
        surface = BRepAdaptor_Surface(face)

        # the centre of mass is the natural choice whenever it is on the
        # face; only a concave region needs the search below
        try:
            projected = surface.Plane()
            location = gp_Pnt(*sketch.plane.to_3d(centre[0], centre[1]))
            u, v = ElSLib.Parameters_s(projected, location)
            if classifier.Perform(gp_Pnt2d(u, v)) != TopAbs_OUT:
                return centre
        except Exception:
            pass

        umin, umax, vmin, vmax = BRepTools.UVBounds_s(face)
        # coarse first, then finer: a tube's wall is a thin ring round a
        # hole the centre falls in, and a coarse grid can miss it entirely
        for steps in (12, 48, 192):
            for i in range(1, steps):
                for j in range(1, steps):
                    u = umin + (umax - umin) * i / steps
                    v = vmin + (vmax - vmin) * j / steps
                    if classifier.Perform(gp_Pnt2d(u, v)) != TopAbs_OUT:
                        point = surface.Value(u, v)
                        return sketch.plane.to_2d((point.X(), point.Y(),
                                                   point.Z()))
    except Exception:
        pass
    return centre


def _angle_between(angle: float, start: float, end: float) -> bool:
    """Whether ``angle`` lies on the anticlockwise sweep from start to end."""
    full = 2.0 * math.pi
    return (angle - start) % full <= (end - start) % full


def project_to_plane(shape: TopoDS_Shape, plane: SketchPlane
                     ) -> List[Tuple[str, Any]]:
    """Flatten a model edge onto a sketch plane, as sketch-space geometry.

    Returns primitives the sketcher can turn into real entities: straight
    edges stay lines, circles stay circles when they are parallel to the
    plane, and anything else is approximated by a polyline.  A circle seen
    edge-on collapses to a line, which is the geometrically honest answer.
    """
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.GCPnts import GCPnts_QuasiUniformDeflection
    from OCP.GeomAbs import GeomAbs_CurveType

    results: List[Tuple[str, Any]] = []

    for edge in edges(shape):
        try:
            curve = BRepAdaptor_Curve(TopoDS.Edge_s(edge))
            kind = curve.GetType()
            first, last = curve.FirstParameter(), curve.LastParameter()
        except Exception:
            continue

        def flat(point):
            return plane.to_2d((point.X(), point.Y(), point.Z()))

        if kind == GeomAbs_CurveType.GeomAbs_Line:
            a, b = flat(curve.Value(first)), flat(curve.Value(last))
            if math.dist(a, b) > 1e-9:
                results.append(("line", (a, b)))
            continue

        if kind == GeomAbs_CurveType.GeomAbs_Circle:
            circ = curve.Circle()
            axis = circ.Axis().Direction()
            alignment = abs(axis.X() * plane.normal[0]
                            + axis.Y() * plane.normal[1]
                            + axis.Z() * plane.normal[2])
            if abs(alignment - 1.0) < 1e-6:
                centre = flat(circ.Location())
                if abs((last - first) - 2 * math.pi) < 1e-6:
                    results.append(("circle", (centre, circ.Radius())))
                else:
                    start, end = flat(curve.Value(first)), flat(curve.Value(last))
                    mid = flat(curve.Value(0.5 * (first + last)))
                    a0 = math.atan2(start[1] - centre[1], start[0] - centre[0])
                    a1 = math.atan2(end[1] - centre[1], end[0] - centre[0])
                    am = math.atan2(mid[1] - centre[1], mid[0] - centre[0])
                    # A sketch arc runs anticlockwise from its start to its
                    # end.  A circle facing the other way from the sketch
                    # runs clockwise in it, and taken as it came the sketch
                    # drew the rest of the circle instead: a rounded corner
                    # bulging the long way round.  Whichever way the arc
                    # really goes, its own middle has to be on it.
                    if not _angle_between(am, a0, a1):
                        a0, a1 = a1, a0
                    results.append(("arc", (centre, circ.Radius(), a0, a1)))
                continue

        try:
            sampler = GCPnts_QuasiUniformDeflection(curve, 0.02)
            if sampler.IsDone() and sampler.NbPoints() >= 2:
                points = [flat(sampler.Value(i))
                          for i in range(1, sampler.NbPoints() + 1)]
                results.append(("polyline", points))
                continue
        except Exception:
            pass

        a, b = flat(curve.Value(first)), flat(curve.Value(last))
        if math.dist(a, b) > 1e-9:
            results.append(("line", (a, b)))

    return results


def sketch_profile(sketch: Sketch,
                   regions: Optional[Sequence[Dict[str, Any]]] = None
                   ) -> TopoDS_Shape:
    """The material a sketch contributes, optionally only chosen regions."""
    if regions is not None:
        fs = [r["face"] for r in regions]
    else:
        fs = sketch_faces(sketch)
    if not fs:
        raise KernelError("sketch '%s' has no closed profile" % sketch.name)
    if len(fs) == 1:
        return fs[0]
    return compound(fs)


# ==========================================================================
# modelling operations
# ==========================================================================


def extrude(profile: TopoDS_Shape, dir_vec: Sequence[float], distance: float,
            taper_deg: float = 0.0) -> TopoDS_Shape:
    if abs(distance) < 1e-9:
        raise KernelError("extrude distance is zero")
    v = vec((dir_vec[0] * distance, dir_vec[1] * distance, dir_vec[2] * distance))

    if abs(taper_deg) > 1e-9:
        return _tapered_extrude(profile, dir_vec, distance, taper_deg)

    mk = BRepPrimAPI_MakePrism(profile, v)
    if not mk.IsDone():
        raise KernelError("extrude failed")
    return check(mk.Shape(), "Extrude")


def _tapered_extrude(profile: TopoDS_Shape, dir_vec: Sequence[float],
                     distance: float, taper_deg: float) -> TopoDS_Shape:
    """Draft-angled extrusion, built as a loft between scaled profiles."""
    from OCP.BRepOffsetAPI import BRepOffsetAPI_ThruSections

    src_faces = faces(profile) or [profile]
    solids = []
    for face in src_faces:
        wires_ = explore(face, TopAbs_WIRE)
        if not wires_:
            continue
        outer = TopoDS.Wire_s(wires_[0])
        cx, cy, cz = shape_centre(outer)

        # approximate offset: scale the profile about its own centre so the
        # wall leans by the requested angle over the extrusion length
        radius = max(
            (math.dist((cx, cy, cz), shape_centre(e)) for e in edges(outer)),
            default=1.0,
        ) or 1.0
        grow = distance * math.tan(math.radians(taper_deg))
        scale = max(0.02, (radius + grow) / radius)

        trsf = gp_Trsf()
        trsf.SetScale(gp_Pnt(cx, cy, cz), scale)
        top = BRepBuilderAPI_Transform(outer, trsf, True).Shape()
        move = gp_Trsf()
        move.SetTranslation(vec((dir_vec[0] * distance, dir_vec[1] * distance,
                                 dir_vec[2] * distance)))
        top = BRepBuilderAPI_Transform(top, move, True).Shape()

        loft = BRepOffsetAPI_ThruSections(True, True, 1e-6)
        loft.AddWire(outer)
        loft.AddWire(TopoDS.Wire_s(top))
        loft.Build()
        if loft.IsDone():
            solids.append(loft.Shape())

    if not solids:
        raise KernelError("tapered extrude failed")
    if len(solids) == 1:
        return check(solids[0], "Extrude")
    result = solids[0]
    for s in solids[1:]:
        result = boolean(result, s, "join")
    return result


def revolve(profile: TopoDS_Shape, axis_origin: Sequence[float],
            axis_dir: Sequence[float], angle_deg: float) -> TopoDS_Shape:
    if abs(angle_deg) < 1e-9:
        raise KernelError("revolve angle is zero")
    ax = gp_Ax1(pnt(axis_origin), direction(axis_dir))
    mk = BRepPrimAPI_MakeRevol(profile, ax, math.radians(angle_deg))
    if not mk.IsDone():
        raise KernelError("revolve failed")
    return check(mk.Shape(), "Revolve")


def sweep(profile: TopoDS_Shape, path_wire: Any) -> TopoDS_Shape:
    mk = BRepOffsetAPI_MakePipe(path_wire, profile)
    mk.Build()
    if not mk.IsDone():
        raise KernelError("sweep failed")
    return check(mk.Shape(), "Sweep")


def loft(profiles: Sequence[Any], solid: bool = True,
         ruled: bool = False) -> TopoDS_Shape:
    from OCP.BRepOffsetAPI import BRepOffsetAPI_ThruSections

    if len(profiles) < 2:
        raise KernelError("loft needs at least two profiles")
    mk = BRepOffsetAPI_ThruSections(solid, ruled, 1e-6)
    for prof in profiles:
        wires_ = explore(prof, TopAbs_WIRE)
        if not wires_:
            raise KernelError("loft profile has no wire")
        mk.AddWire(TopoDS.Wire_s(wires_[0]))
    mk.Build()
    if not mk.IsDone():
        raise KernelError("loft failed")
    return check(mk.Shape(), "Loft")


def boolean(base: TopoDS_Shape, tool: TopoDS_Shape, op: str) -> TopoDS_Shape:
    """``op`` is one of join / cut / intersect."""
    if not is_valid(base):
        return tool
    if not is_valid(tool):
        return base
    builders = {
        "join": BRepAlgoAPI_Fuse,
        "cut": BRepAlgoAPI_Cut,
        "intersect": BRepAlgoAPI_Common,
    }
    if op not in builders:
        raise KernelError("unknown boolean operation %r" % op)
    algo = builders[op]()
    arguments = TopTools_ListOfShape()
    arguments.Append(base)
    tools = TopTools_ListOfShape()
    tools.Append(tool)
    algo.SetArguments(arguments)
    algo.SetTools(tools)
    algo.SetRunParallel(True)
    algo.SetFuzzyValue(1e-6)
    # Left to itself a boolean may rework the faces of the shapes it was
    # given, in place, and those faces are shared: a cut late in the tree
    # was quietly changing the body as it stood several features earlier.
    # Nothing used to look back, so nothing noticed. Kept results do.
    algo.SetNonDestructive(True)
    algo.Build()
    if not algo.IsDone():
        raise KernelError("%s operation failed" % op)
    result = algo.Shape()
    if not is_valid(result) or not explore(result, TopAbs_SOLID):
        raise KernelError("%s removed all material" % op)
    return heal(result)


def boolean_many(base: TopoDS_Shape, tools: Sequence[TopoDS_Shape],
                 op: str) -> TopoDS_Shape:
    """One boolean with many tools: every copy of a pattern at once.

    The same as applying the tools one after another, for a join or a cut,
    and far quicker: the result is worked out once, rather than once per
    tool on a body that grows more complicated each time, and healed once
    at the end.  A hundred teeth round a sprocket went from one boolean
    each to one in all.  An intersection is not the same thing done this
    way, the common part of the base with all the tools at once being
    another answer, so it is still done one at a time.
    """
    tools = [t for t in tools if is_valid(t)]
    if not tools:
        return base
    if op == "intersect" or len(tools) == 1 or not is_valid(base):
        for tool in tools:
            base = boolean(base, tool, op)
        return base
    builders = {"join": BRepAlgoAPI_Fuse, "cut": BRepAlgoAPI_Cut}
    if op not in builders:
        raise KernelError("unknown boolean operation %r" % op)
    algo = builders[op]()
    arguments = TopTools_ListOfShape()
    arguments.Append(base)
    listed = TopTools_ListOfShape()
    for tool in tools:
        listed.Append(tool)
    algo.SetArguments(arguments)
    algo.SetTools(listed)
    algo.SetRunParallel(True)
    algo.SetFuzzyValue(1e-6)
    algo.SetNonDestructive(True)        # see boolean()
    algo.Build()
    if not algo.IsDone():
        raise KernelError("%s operation failed" % op)
    result = algo.Shape()
    if not is_valid(result) or not explore(result, TopAbs_SOLID):
        raise KernelError("%s removed all material" % op)
    return heal(result)


def point_on_face(face: TopoDS_Shape) -> Optional[Tuple[float, float, float]]:
    """A point that lies on a face's surface: the middle of its parameters.

    Not its centre of area, which for a ring or a curved face lies off it.
    """
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.BRepTools import BRepTools

    try:
        f = TopoDS.Face_s(face)
        u0, u1, v0, v1 = BRepTools.UVBounds_s(f)
        p = BRepAdaptor_Surface(f).Value((u0 + u1) / 2.0, (v0 + v1) / 2.0)
        return (p.X(), p.Y(), p.Z())
    except Exception:
        return None


def distance_to_point(shape: TopoDS_Shape, p: Sequence[float]) -> float:
    """How far a point is from a shape's nearest surface, edge or corner."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeVertex
    from OCP.BRepExtrema import BRepExtrema_DistShapeShape

    try:
        probe = BRepExtrema_DistShapeShape(
            BRepBuilderAPI_MakeVertex(pnt(p)).Vertex(), shape)
        if probe.IsDone():
            return probe.Value()
    except Exception:
        pass
    return float("inf")


def _cutting_face(shape: TopoDS_Shape, origin: Sequence[float],
                  normal: Sequence[float]) -> TopoDS_Face:
    """A square of the plane big enough to cross the whole shape."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace

    x0, y0, z0, x1, y1, z1 = bounding_box(shape)
    size = math.dist((x0, y0, z0), (x1, y1, z1)) * 2.0 + 10.0
    centre = ((x0 + x1) / 2.0, (y0 + y1) / 2.0, (z0 + z1) / 2.0)
    n = list(normal)
    # the shape's middle, dropped onto the plane, is where the square goes
    off = sum((centre[i] - origin[i]) * n[i] for i in range(3))
    foot = [centre[i] - off * n[i] for i in range(3)]
    plane = gp_Pln(pnt(foot), direction(normal))
    return BRepBuilderAPI_MakeFace(plane, -size, size, -size, size).Face()


def split_solid(shape: TopoDS_Shape, origin: Sequence[float],
                normal: Sequence[float]) -> List[TopoDS_Shape]:
    """The solids a plane cuts a shape into: the side the normal points to
    first.  One solid back means the plane missed it."""
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Splitter

    splitter = BRepAlgoAPI_Splitter()
    arguments = TopTools_ListOfShape()
    arguments.Append(shape)
    tools = TopTools_ListOfShape()
    tools.Append(_cutting_face(shape, origin, normal))
    splitter.SetArguments(arguments)
    splitter.SetTools(tools)
    splitter.SetRunParallel(True)
    splitter.SetNonDestructive(True)
    splitter.SetFuzzyValue(1e-6)
    splitter.Build()
    if not splitter.IsDone():
        raise KernelError("the split failed")
    pieces = explore(splitter.Shape(), TopAbs_SOLID)

    def side(piece):
        c = shape_centre(piece)
        return sum((c[i] - origin[i]) * normal[i] for i in range(3))

    return sorted(pieces, key=side, reverse=True)


def split_faces(shape: TopoDS_Shape, faces: Sequence[TopoDS_Shape],
                origin: Sequence[float],
                normal: Sequence[float]) -> Tuple[TopoDS_Shape, int]:
    """The shape with these faces split where the plane crosses them, and
    how many lines were cut.  The solid itself is one piece still."""
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Section
    from OCP.BRepFeat import BRepFeat_SplitShape
    from OCP.TopTools import TopTools_SequenceOfShape

    if not faces:
        return shape, 0
    plane = gp_Pln(pnt(origin), direction(normal))
    section = BRepAlgoAPI_Section(compound(list(faces)), plane, False)
    section.ComputePCurveOn1(True)
    section.Approximation(True)
    section.Build()
    if not section.IsDone():
        raise KernelError("the plane could not be crossed with the faces")
    cuts = explore(section.Shape(), TopAbs_EDGE)
    if not cuts:
        return shape, 0
    # handed over all together: OCCT then finds each line's face itself,
    # and a line ending where two faces meet splits both consistently
    edges_in = TopTools_SequenceOfShape()
    for edge in cuts:
        edges_in.Append(edge)
    splitter = BRepFeat_SplitShape(shape)
    if not splitter.Add(edges_in):
        raise KernelError("the split lines do not lie on the faces")
    splitter.Build()
    if not splitter.IsDone() or not is_valid(splitter.Shape()):
        raise KernelError("the faces could not be split")
    return splitter.Shape(), len(cuts)


def distance_between(a: TopoDS_Shape, b: TopoDS_Shape) -> float:
    """How far apart two shapes are at their nearest; 0 where they touch."""
    from OCP.BRepExtrema import BRepExtrema_DistShapeShape

    try:
        probe = BRepExtrema_DistShapeShape(a, b)
        if probe.IsDone():
            return probe.Value()
    except Exception:
        pass
    return float("inf")


def depth_range(shape: TopoDS_Shape, origin: Sequence[float],
                direction: Sequence[float]) -> Tuple[float, float]:
    """How far along a direction from a point a shape's corners reach, the
    nearest and the farthest."""
    from OCP.BRep import BRep_Tool

    depths = []
    for vertex in vertices(shape):
        p = BRep_Tool.Pnt_s(TopoDS.Vertex_s(vertex))
        depths.append((p.X() - origin[0]) * direction[0]
                      + (p.Y() - origin[1]) * direction[1]
                      + (p.Z() - origin[2]) * direction[2])
    if not depths:
        return 0.0, 0.0
    return min(depths), max(depths)


def split_pieces(shape: TopoDS_Shape, tools: Sequence[TopoDS_Shape]
                 ) -> List[TopoDS_Shape]:
    """The solids a shape falls into when faces cut it.  A face that does
    not reach right across leaves it in one piece."""
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Splitter

    splitter = BRepAlgoAPI_Splitter()
    arguments = TopTools_ListOfShape()
    arguments.Append(shape)
    cutters = TopTools_ListOfShape()
    for tool in tools:
        cutters.Append(tool)
    splitter.SetArguments(arguments)
    splitter.SetTools(cutters)
    splitter.SetNonDestructive(True)
    splitter.SetFuzzyValue(1e-6)
    splitter.Build()
    if not splitter.IsDone():
        raise KernelError("the split failed")
    return explore(splitter.Shape(), TopAbs_SOLID)


def plane_face(around: TopoDS_Shape, origin: Sequence[float],
               normal: Sequence[float]) -> TopoDS_Face:
    """A square of a plane big enough to cross the whole of a shape."""
    return _cutting_face(around, origin, normal)


def extended_face(face: TopoDS_Shape, size: float) -> TopoDS_Face:
    """A face's surface run out well past its edges: Inventor's Extend Face.

    A flat face becomes a square of its plane, ``size`` each way of its
    middle; a cylinder or a cone goes all the way round and ``size`` along
    its axis; a surface with edges of its own, a sphere or a spline, is all
    of itself there is.
    """
    from OCP.BRep import BRep_Tool
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_SurfaceType

    face = TopoDS.Face_s(face)
    surface = BRepAdaptor_Surface(face)
    if surface.GetType() == GeomAbs_SurfaceType.GeomAbs_Plane:
        axis = surface.Plane().Axis().Direction()
        plane = gp_Pln(pnt(shape_centre(face)), axis)
        return BRepBuilderAPI_MakeFace(plane, -size, size, -size,
                                       size).Face()
    geom = BRep_Tool.Surface_s(face)
    u0, u1, v0, v1 = geom.Bounds()

    def clamp(x):
        return max(-size, min(size, x))

    made = BRepBuilderAPI_MakeFace(geom, clamp(u0), clamp(u1), clamp(v0),
                                   clamp(v1), 1e-6)
    if not made.IsDone():
        raise KernelError("the face could not be run out")
    return made.Face()


def _walk(wire: TopoDS_Shape) -> List[TopoDS_Shape]:
    """A wire's edges in the order it runs through them."""
    from OCP.BRepTools import BRepTools_WireExplorer

    out = []
    walker = BRepTools_WireExplorer(TopoDS.Wire_s(wire))
    while walker.More():
        out.append(walker.Current())
        walker.Next()
    return out


def _point_and_tangent(edge: TopoDS_Shape, where: str):
    """A point of an edge, "start", "end" or "middle" as the wire runs it,
    and the way the wire runs there."""
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.TopAbs import TopAbs_REVERSED

    curve = BRepAdaptor_Curve(TopoDS.Edge_s(edge))
    first, last = curve.FirstParameter(), curve.LastParameter()
    backwards = edge.Orientation() == TopAbs_REVERSED
    if where == "middle":
        u = (first + last) / 2.0
    elif where == "start":
        u = last if backwards else first
    else:
        u = first if backwards else last
    p, v = gp_Pnt(), gp_Vec()
    curve.D1(u, p, v)
    t = [v.X(), v.Y(), v.Z()]
    if backwards:
        t = [-c for c in t]
    size = math.sqrt(sum(c * c for c in t)) or 1.0
    return (p.X(), p.Y(), p.Z()), tuple(c / size for c in t)


def match_region(wire: TopoDS_Shape, origin: Sequence[float],
                 normal: Sequence[float], around: TopoDS_Shape,
                 flip: bool) -> Tuple[TopoDS_Face, TopoDS_Face]:
    """Match Shape's profile: the sketch plane on one side of an open
    profile whose ends run straight on until they are clear of the part.

    Returns that region and the square of the plane it was cut from.  The
    side is the left of the profile as it runs, or the right with ``flip``.
    """
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Splitter

    square = _cutting_face(compound([around, wire]), origin, normal)
    x0, y0, z0, x1, y1, z1 = bounding_box(square)
    size = math.dist((x0, y0, z0), (x1, y1, z1))
    ordered = _walk(wire)
    if not ordered:
        raise KernelError("the open profile has no curves")
    cutters = TopTools_ListOfShape()
    for edge in ordered:
        cutters.Append(edge)
    for edge, where, outward in ((ordered[0], "start", -1.0),
                                 (ordered[-1], "end", 1.0)):
        point, tangent = _point_and_tangent(edge, where)
        far = [point[i] + outward * tangent[i] * size for i in range(3)]
        cutters.Append(BRepBuilderAPI_MakeEdge(pnt(point), pnt(far)).Edge())
    splitter = BRepAlgoAPI_Splitter()
    arguments = TopTools_ListOfShape()
    arguments.Append(square)
    splitter.SetArguments(arguments)
    splitter.SetTools(cutters)
    splitter.SetFuzzyValue(1e-6)
    splitter.Build()
    if not splitter.IsDone():
        raise KernelError("the open profile could not divide the plane")
    pieces = explore(splitter.Shape(), TopAbs_FACE)
    if len(pieces) < 2:
        raise KernelError("the open profile does not divide the part in two")
    # a step off the middle of the first curve, square to it, says which
    point, tangent = _point_and_tangent(ordered[0], "middle")
    left = [normal[1] * tangent[2] - normal[2] * tangent[1],
            normal[2] * tangent[0] - normal[0] * tangent[2],
            normal[0] * tangent[1] - normal[1] * tangent[0]]
    step = max(1e-3, size * 1e-5) * (-1.0 if flip else 1.0)
    probe = [point[i] + left[i] * step for i in range(3)]
    region = min(pieces, key=lambda f: distance_to_point(f, probe))
    return TopoDS.Face_s(region), square


def walls(face: TopoDS_Shape, normal: Sequence[float],
          reach: float) -> TopoDS_Shape:
    """A face's outline run out both ways along a normal: the sides of a
    box with no top or bottom, for telling what reaches its edge."""
    from OCP.BRepTools import BRepTools

    outline = BRepTools.OuterWire_s(TopoDS.Face_s(face))
    start = translate(outline, [-normal[i] * reach for i in range(3)])
    made = BRepPrimAPI_MakePrism(
        start, vec([normal[i] * 2.0 * reach for i in range(3)]))
    if not made.IsDone():
        raise KernelError("the outline could not be run out")
    return made.Shape()


def edges_along(shape: TopoDS_Shape, guides: Sequence[TopoDS_Shape],
                tol: float = 1e-3) -> List[TopoDS_Edge]:
    """The edges of a shape that lie along some guide edges.

    How a fillet is repeated on a copy: the edges it rounded are moved to
    where the copy is, and the copy's own edges found under them.  Found
    by where they run rather than by matching one to one, because a copy
    can come out split differently, a rim crossing a cylinder's seam in
    one place and not in another.
    """
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeVertex
    from OCP.BRepExtrema import BRepExtrema_DistShapeShape

    if not guides:
        return []
    guide = compound(list(guides))
    gx0, gy0, gz0, gx1, gy1, gz1 = bounding_box(guide)
    out: List[TopoDS_Edge] = []
    for edge in edges(shape):
        try:
            x0, y0, z0, x1, y1, z1 = bounding_box(edge)
        except Exception:
            continue
        if (x1 < gx0 - tol or x0 > gx1 + tol or y1 < gy0 - tol
                or y0 > gy1 + tol or z1 < gz0 - tol or z0 > gz1 + tol):
            continue
        try:
            curve = BRepAdaptor_Curve(TopoDS.Edge_s(edge))
            first, last = curve.FirstParameter(), curve.LastParameter()
        except Exception:
            continue
        along = True
        for t in (0.0, 0.25, 0.5, 0.75, 1.0):
            point = curve.Value(first + (last - first) * t)
            probe = BRepExtrema_DistShapeShape(
                BRepBuilderAPI_MakeVertex(point).Vertex(), guide)
            if not probe.IsDone() or probe.Value() > tol:
                along = False
                break
        if along:
            out.append(TopoDS.Edge_s(edge))
    return out


def half_box(origin: Sequence[float], normal: Sequence[float],
             keep: Sequence[float], size: float) -> TopoDS_Shape:
    """A big block standing on a plane, on the side ``keep`` is on.

    What a trim to a plane intersects with.  A real half-space would do the
    same job, but an infinite solid is where booleans go to misbehave, and
    a block bigger than anything it meets is indistinguishable from one.
    """
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace

    side = sum(normal[i] * (keep[i] - origin[i]) for i in range(3))
    towards = list(normal) if side >= 0 else [-c for c in normal]
    # centre the block's footprint under the point being kept
    foot = [keep[i] - side * normal[i] for i in range(3)]
    plane = gp_Pln(pnt(foot), direction(normal))
    face = BRepBuilderAPI_MakeFace(plane, -size, size, -size, size).Face()
    return extrude(face, towards, size, 0.0)


def is_seam(edge: TopoDS_Shape) -> bool:
    """Whether an edge is a join nobody would call an edge.

    A cylinder's side is one face wrapped round, and where it meets itself
    there is an edge OCCT needs and a person does not: there is no corner
    there to see or to fillet.  OCCT marks such an edge as smooth to any
    order, which is the test, so a seam left between two pieces of the same
    surface that a boolean did not merge is caught too.  A tangent edge, a
    fillet running into a flat, is only smooth to the first order and stays
    an edge, as it does in Inventor.
    """
    from OCP.GeomAbs import GeomAbs_Shape
    try:
        smooth = BRep_Tool.MaxContinuity_s(TopoDS.Edge_s(edge))
        return smooth.value > GeomAbs_Shape.GeomAbs_C2.value
    except Exception:
        return False


def mark_seams(shape: Optional[TopoDS_Shape]) -> None:
    """Make sure every seam on a shape is marked as one.

    The bodies built here come out marked; one read from a STEP file often
    does not, and an unmarked seam is drawn down the side of every cylinder,
    can be picked like a corner and turns up in the drawings.  Only the
    edges a closed face meets itself along are looked at, so this costs
    little even on a big import, and marking an edge twice does nothing.
    """
    if shape is None or shape.IsNull():
        return
    from OCP.BRepLib import BRepLib
    from OCP.GeomAbs import GeomAbs_Shape

    loose = TopTools_ListOfShape()
    found = False
    builder = None
    faces_of = TopExp_Explorer(shape, TopAbs_FACE)
    while faces_of.More():
        face = TopoDS.Face_s(faces_of.Current())
        faces_of.Next()
        try:
            surface = BRep_Tool.Surface_s(face)
            if not (surface.IsUClosed() or surface.IsVClosed()):
                continue
        except Exception:
            continue
        edges_of = TopExp_Explorer(face, TopAbs_EDGE)
        while edges_of.More():
            edge = TopoDS.Edge_s(edges_of.Current())
            edges_of.Next()
            if not BRep_Tool.IsClosed_s(edge, face):
                continue
            smooth = BRep_Tool.MaxContinuity_s(edge)
            if smooth == GeomAbs_Shape.GeomAbs_C0:
                loose.Append(edge)
                found = True
            elif smooth.value <= GeomAbs_Shape.GeomAbs_C2.value:
                # A face closing on itself: a fillet round a hole in a
                # cylinder is a freeform surface whose seam OCCT reports
                # as only tangent, so it was drawn as a line across the
                # fillet and could be picked.  It is the same surface on
                # both sides, so it is as smooth as the surface is.
                from OCP.BRep import BRep_Builder
                builder = builder or BRep_Builder()
                try:
                    builder.Continuity(edge, face, face,
                                       GeomAbs_Shape.GeomAbs_CN)
                except Exception:
                    pass
    if found:
        try:
            BRepLib.EncodeRegularity_s(shape, loose, 1e-10)
        except Exception:
            pass


def unify(shape: TopoDS_Shape) -> TopoDS_Shape:
    """Merge faces that lie in the same surface, and edges in the same curve.

    A boolean leaves its seams behind: fuse a boss onto a plate at the same
    height and the top comes back as two coplanar faces with a line between
    them.  The line is real topology, not a drawing artefact - it splits the
    face you want to sketch on and it exports to DXF.  Inventor merges them,
    so this does too.

    Failure is not an error.  A shape that will not unify is returned as it
    was, because a visible seam is a much smaller problem than a rebuild
    that stops.
    """
    if not is_valid(shape):
        return shape
    solid = bool(explore(shape, TopAbs_SOLID))
    try:
        before = volume(shape) if solid else surface_area(shape)
        tool = ShapeUpgrade_UnifySameDomain(shape, True, True, False)
        tool.SetSafeInputMode(True)
        tool.Build()
        result = tool.Shape()
    except Exception:
        return shape
    if not is_valid(result):
        return shape
    if solid and not explore(result, TopAbs_SOLID):
        return shape
    try:
        # a unify that changed the size has done something other than tidy
        # the topology, and is not to be trusted
        after = volume(result) if solid else surface_area(result)
        if abs(after - before) > max(1e-6, abs(before) * 1e-9):
            return shape
    except Exception:
        return shape
    return result


# A body made of at least this many separate solids is combined with a tool
# one neighbourhood at a time.  Below it, splitting costs more than it saves.
LOCAL_SOLIDS = 8


# Boxes of solids already measured.  A body of three hundred solids is
# combined with tool after tool, and all but a few of its solids are the
# same objects every time; measuring them again was a sixth of a cut.
_BOXES: "OrderedDict[int, Tuple[TopoDS_Shape, Tuple]]" = OrderedDict()
_BOXES_KEEP = 8192


def _box_of(shape: TopoDS_Shape):
    key = hash(shape)
    held = _BOXES.get(key)
    if held is not None and held[0].IsEqual(shape):
        return held[1]
    box = bounding_box(shape)
    _BOXES[key] = (shape, box)
    while len(_BOXES) > _BOXES_KEEP:
        _BOXES.popitem(last=False)
    return box


def pieces(shape: Optional[TopoDS_Shape]) -> List[TopoDS_Shape]:
    """A shape's separate pieces: compounds opened up, down to what is in them."""
    out: List[TopoDS_Shape] = []
    if shape is None or shape.IsNull():
        return out
    if shape.ShapeType() != TopAbs_COMPOUND:
        return [shape]
    pending = [shape]
    while pending:
        here = pending.pop(0)
        children = TopoDS_Iterator(here)
        while children.More():
            child = children.Value()
            if child.ShapeType() == TopAbs_COMPOUND:
                pending.append(child)
            else:
                out.append(child)
            children.Next()
    return out


def _boxes_meet(a, b, margin: float) -> bool:
    return not (a[3] + margin < b[0] or b[3] + margin < a[0]
                or a[4] + margin < b[1] or b[4] + margin < a[1]
                or a[5] + margin < b[2] or b[5] + margin < a[2])


def combine(base: TopoDS_Shape, tool: TopoDS_Shape, op: str) -> TopoDS_Shape:
    """A boolean and a tidy-up, touching only what the tool can reach.

    An imported model is often one body of hundreds of solids, and a hole
    drilled through it meets three of them. Handing the whole body to the
    boolean meant intersecting, repairing, merging faces and measuring the
    volume of all of them: twenty seconds on a 300 solid Inventor export,
    for a hole. The solids whose boxes the tool does not reach cannot be
    changed by it, so they are left exactly as they were, meshes and all,
    and only the neighbourhood goes through the boolean.
    """
    if not is_valid(base) or not is_valid(tool):
        return unify(boolean(base, tool, op))
    parts = explore(base, TopAbs_SOLID)
    if len(parts) < LOCAL_SOLIDS:
        return unify(boolean(base, tool, op))

    reach = bounding_box(tool)
    size = max(reach[3] - reach[0], reach[4] - reach[1], reach[5] - reach[2])
    margin = max(1e-3, size * 1e-6)
    near, far = [], []
    for part in parts:
        (near if _boxes_meet(_box_of(part), reach, margin)
         else far).append(part)
    if not far:
        return unify(boolean(base, tool, op))

    if not near:
        # the tool meets nothing: a cut changes nothing, a join adds the
        # tool beside the rest, and an intersection leaves nothing at all
        if op == "cut":
            return base
        if op == "join":
            return compound(far + [tool])
        raise KernelError("intersect removed all material")

    neighbourhood = near[0] if len(near) == 1 else compound(near)
    try:
        changed = unify(boolean(neighbourhood, tool, op))
    except KernelError as exc:
        if op == "cut" and "removed all material" in str(exc):
            # the cut took the whole neighbourhood away, not the whole body
            return compound(far)
        raise
    if op == "intersect":
        return changed
    return compound(far + explore(changed, TopAbs_SOLID))


def fuse_all(shapes: Sequence[TopoDS_Shape]) -> Optional[TopoDS_Shape]:
    """Fuse a list into one shape, merging anything that touches.

    Pieces that do not touch stay separate inside the result, which is what
    lets one extrude cover several islands of a sketch.
    """
    live = [s for s in shapes if is_valid(s)]
    if not live:
        return None
    if len(live) == 1:
        return live[0]

    arguments = TopTools_ListOfShape()
    arguments.Append(live[0])
    tools = TopTools_ListOfShape()
    for shape in live[1:]:
        tools.Append(shape)

    try:
        algo = BRepAlgoAPI_Fuse()
        algo.SetArguments(arguments)
        algo.SetTools(tools)
        algo.SetRunParallel(True)
        algo.SetFuzzyValue(1e-6)
        algo.SetNonDestructive(True)
        algo.Build()
        if algo.IsDone() and is_valid(algo.Shape()):
            return algo.Shape()
    except Exception:
        pass
    return compound(live)


def fillet(shape: TopoDS_Shape, edge_list: Sequence[TopoDS_Edge],
           radius: float) -> TopoDS_Shape:
    if radius <= 0:
        raise KernelError("fillet radius must be positive")
    if not edge_list:
        raise KernelError("no edges selected for fillet")
    # A radius that is exactly half a wall, rounding both of its edges, is
    # a full round: the two fillets meet in a line with nothing flat left
    # between them.  OCCT will not build two surfaces that touch along an
    # edge it then has to make, and refuses outright.  A hair less leaves
    # a band too thin to see or measure, which is the full round anyone
    # asking for one wants, so that is tried before giving up.
    for shrink in (0.0, 1e-5, 1e-4, 1e-3):
        size = float(radius) * (1.0 - shrink)
        mk = BRepFilletAPI_MakeFillet(shape)
        for e in edge_list:
            mk.Add(size, e)
        try:
            mk.Build()
        except Exception:
            continue
        if mk.IsDone() and is_valid(mk.Shape()):
            return check(mk.Shape(), "Fillet")
    raise KernelError("fillet failed - radius %.3f is probably too large"
                      % radius)


def chamfer(shape: TopoDS_Shape, edge_list: Sequence[TopoDS_Edge],
            distance: float) -> TopoDS_Shape:
    if distance <= 0:
        raise KernelError("chamfer distance must be positive")
    if not edge_list:
        raise KernelError("no edges selected for chamfer")
    mk = BRepFilletAPI_MakeChamfer(shape)
    for e in edge_list:
        mk.Add(float(distance), e)
    mk.Build()
    if not mk.IsDone():
        raise KernelError("chamfer failed - distance %.3f is probably too large"
                          % distance)
    return check(mk.Shape(), "Chamfer")


def shell(shape: TopoDS_Shape, open_faces: Sequence[TopoDS_Face],
          thickness: float) -> TopoDS_Shape:
    """Hollow a solid out, leaving ``open_faces`` removed.

    OCCT's thick-solid builder is fussy - whether it succeeds depends on the
    tolerance, whether self-intersections are resolved, and the join style.
    Rather than surface the first failure, work through the settings that are
    known to rescue awkward cases before giving up.
    """
    if abs(thickness) < 1e-9:
        raise KernelError("shell thickness is zero")

    removed = TopTools_ListOfShape()
    for f in open_faces:
        removed.Append(f)

    attempts = (
        (1e-4, False, GeomAbs_JoinType.GeomAbs_Arc),
        (1e-4, True, GeomAbs_JoinType.GeomAbs_Arc),
        (1e-3, True, GeomAbs_JoinType.GeomAbs_Arc),
        (1e-3, True, GeomAbs_JoinType.GeomAbs_Intersection),
        (1e-5, True, GeomAbs_JoinType.GeomAbs_Intersection),
    )

    last_error = ""
    for tolerance, intersect, join in attempts:
        try:
            mk = BRepOffsetAPI_MakeThickSolid()
            mk.MakeThickSolidByJoin(shape, removed, -abs(thickness), tolerance,
                                    BRepOffset_Mode.BRepOffset_Skin,
                                    intersect, False, join, False)
            mk.Build()
            if not mk.IsDone():
                continue
            result = mk.Shape()
            if not is_valid(result) or not explore(result, TopAbs_SOLID):
                continue
            return check(result, "Shell")
        except Exception as exc:
            last_error = str(exc)
            continue

    raise KernelError(
        "shell failed - the wall is probably too thick for the smallest "
        "feature on the body%s" % (": %s" % last_error if last_error else ""))


def translate(shape: TopoDS_Shape, delta: Sequence[float]) -> TopoDS_Shape:
    t = gp_Trsf()
    t.SetTranslation(vec(delta))
    return BRepBuilderAPI_Transform(shape, t, True).Shape()


def rotate(shape: TopoDS_Shape, axis_origin: Sequence[float],
           axis_dir: Sequence[float], angle_deg: float) -> TopoDS_Shape:
    t = gp_Trsf()
    t.SetRotation(gp_Ax1(pnt(axis_origin), direction(axis_dir)),
                  math.radians(angle_deg))
    return BRepBuilderAPI_Transform(shape, t, True).Shape()


def mirror(shape: TopoDS_Shape, plane: SketchPlane) -> TopoDS_Shape:
    t = gp_Trsf()
    t.SetMirror(gp_Ax2(pnt(plane.origin), direction(plane.normal),
                       direction(plane.xdir)))
    return BRepBuilderAPI_Transform(shape, t, True).Shape()


def scale(shape: TopoDS_Shape, factor: float,
          about: Sequence[float] = (0, 0, 0)) -> TopoDS_Shape:
    t = gp_Trsf()
    t.SetScale(pnt(about), float(factor))
    return BRepBuilderAPI_Transform(shape, t, True).Shape()


# -- primitives -------------------------------------------------------------


def box(dx: float, dy: float, dz: float,
        origin: Sequence[float] = (0, 0, 0), centred: bool = False) -> TopoDS_Shape:
    if min(dx, dy, dz) <= 0:
        raise KernelError("box dimensions must be positive")
    o = list(origin)
    if centred:
        o = [o[0] - dx / 2, o[1] - dy / 2, o[2] - dz / 2]
    return BRepPrimAPI_MakeBox(pnt(o), dx, dy, dz).Shape()


def cylinder(radius: float, height: float, origin: Sequence[float] = (0, 0, 0),
             axis: Sequence[float] = (0, 0, 1)) -> TopoDS_Shape:
    if radius <= 0 or height <= 0:
        raise KernelError("cylinder radius and height must be positive")
    ax2 = gp_Ax2(pnt(origin), direction(axis))
    return BRepPrimAPI_MakeCylinder(ax2, radius, height).Shape()


def cone(r1: float, r2: float, height: float,
         origin: Sequence[float] = (0, 0, 0),
         axis: Sequence[float] = (0, 0, 1)) -> TopoDS_Shape:
    if height <= 0 or (r1 <= 0 and r2 <= 0):
        raise KernelError("invalid cone dimensions")
    ax2 = gp_Ax2(pnt(origin), direction(axis))
    return BRepPrimAPI_MakeCone(ax2, r1, r2, height).Shape()


def sphere(radius: float, origin: Sequence[float] = (0, 0, 0)) -> TopoDS_Shape:
    if radius <= 0:
        raise KernelError("sphere radius must be positive")
    return BRepPrimAPI_MakeSphere(pnt(origin), radius).Shape()


def torus(r1: float, r2: float, origin: Sequence[float] = (0, 0, 0),
          axis: Sequence[float] = (0, 0, 1)) -> TopoDS_Shape:
    if r1 <= 0 or r2 <= 0:
        raise KernelError("torus radii must be positive")
    return BRepPrimAPI_MakeTorus(gp_Ax2(pnt(origin), direction(axis)),
                                 r1, r2).Shape()


# ==========================================================================
# emboss and engrave
# ==========================================================================


def thicken_face(face: TopoDS_Shape, thickness: float) -> TopoDS_Shape:
    """A solid of one face thickened along its own normal: outwards for a
    positive thickness, inwards for a negative one.  Curved faces too."""
    from OCP.BRepLib import BRepLib
    from OCP.BRepOffsetAPI import BRepOffsetAPI_MakeThickSolid
    maker = BRepOffsetAPI_MakeThickSolid()
    maker.MakeThickSolidBySimple(face, float(thickness))
    if not maker.IsDone():
        raise KernelError("could not thicken the face")
    shape = maker.Shape()
    for solid in explore(shape, TopAbs_SOLID):
        BRepLib.OrientClosedSolid_s(TopoDS.Solid_s(solid))
    if volume(shape) < 0:
        shape.Reverse()
    return shape


def first_hit(shape: TopoDS_Shape, origin: Sequence[float],
              direction_: Sequence[float]
              ) -> Optional[Tuple[TopoDS_Face, Tuple[float, float, float]]]:
    """The first face of ``shape`` a ray from ``origin`` meets going along
    ``direction_``, and where; None when it meets nothing."""
    from OCP.BRepIntCurveSurface import BRepIntCurveSurface_Inter
    from OCP.gp import gp_Lin
    finder = BRepIntCurveSurface_Inter()
    finder.Init(shape, gp_Lin(pnt(origin), direction(direction_)), 1e-7)
    best = None
    while finder.More():
        w = finder.W()
        if w >= -1e-7 and (best is None or w < best[0]):
            p = finder.Pnt()
            best = (w, finder.Face(), (p.X(), p.Y(), p.Z()))
        finder.Next()
    if best is None:
        return None
    return best[1], best[2]


def ray_hits(shape: TopoDS_Shape, origin: Sequence[float],
             direction_: Sequence[float]) -> List[float]:
    """How far along a ray from ``origin`` it crosses ``shape``'s faces,
    nearest first."""
    from OCP.BRepIntCurveSurface import BRepIntCurveSurface_Inter
    from OCP.gp import gp_Lin
    finder = BRepIntCurveSurface_Inter()
    finder.Init(shape, gp_Lin(pnt(origin), direction(direction_)), 1e-7)
    found = []
    while finder.More():
        if finder.W() >= -1e-7:
            found.append(finder.W())
        finder.Next()
    return sorted(found)


def _affine_uv(plane_pts, uv_pts):
    """The affine map taking three points in space (on a plane) to three
    (u, v): as a function of a point in space."""
    import numpy as np
    a = np.array(plane_pts[0], dtype=float)
    e1 = np.array(plane_pts[1], dtype=float) - a
    e2 = np.array(plane_pts[2], dtype=float) - a
    gram = np.array([[e1 @ e1, e1 @ e2], [e1 @ e2, e2 @ e2]])
    inv = np.linalg.inv(gram)
    u0 = np.array(uv_pts[0], dtype=float)
    d1 = np.array(uv_pts[1], dtype=float) - u0
    d2 = np.array(uv_pts[2], dtype=float) - u0

    def mapped(p):
        r = np.array(p, dtype=float) - a
        s, t = inv @ np.array([r @ e1, r @ e2])
        return tuple(u0 + s * d1 + t * d2)
    return mapped


def wrap_to_cylinder(profile: TopoDS_Shape, plane: SketchPlane,
                     face: TopoDS_Shape) -> List[TopoDS_Face]:
    """The faces of a flat profile wrapped round a cylindrical face, as a
    label goes round a bottle: lengths across the axis become lengths
    round it, lengths along the axis stay.  The profile is taken where it
    lies square to the cylinder's nearest line."""
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.BRepLib import BRepLib
    from OCP.BRepTools import BRepTools_WireExplorer
    from OCP.ElSLib import ElSLib
    from OCP.Geom import Geom_CylindricalSurface
    from OCP.Geom2d import Geom2d_BSplineCurve
    from OCP.GeomAbs import GeomAbs_Cylinder
    from OCP.GeomConvert import GeomConvert
    from OCP.Geom import Geom_TrimmedCurve
    from OCP.TColgp import TColgp_Array1OfPnt2d
    from OCP.TColStd import TColStd_Array1OfReal
    from OCP.BRep import BRep_Tool
    from OCP.BRepTools import BRepTools
    from OCP.gp import gp_Pnt2d

    adaptor = BRepAdaptor_Surface(TopoDS.Face_s(face))
    if adaptor.GetType() != GeomAbs_Cylinder:
        raise KernelError("Wrap to Face needs a cylindrical face")
    cylinder = adaptor.Cylinder()
    radius = cylinder.Radius()
    axis = cylinder.Axis()
    ad = axis.Direction()
    axis_dir = (ad.X(), ad.Y(), ad.Z())
    loc = axis.Location()

    centre = shape_centre(profile)
    # where the profile's middle meets the cylinder, square to the axis
    u0, v0 = ElSLib.Parameters_s(cylinder, pnt(centre))
    # across the axis on the sketch plane is round it; along it is along
    across = [axis_dir[1] * plane.normal[2] - axis_dir[2] * plane.normal[1],
              axis_dir[2] * plane.normal[0] - axis_dir[0] * plane.normal[2],
              axis_dir[0] * plane.normal[1] - axis_dir[1] * plane.normal[0]]
    length = math.sqrt(sum(c * c for c in across))
    if length < 1e-9:
        raise KernelError("the sketch is square to the cylinder's axis, so "
                          "there is no way round it to wrap along")
    across = [c / length for c in across]
    # round the cylinder the way u grows
    tangent = cylinder.Position().XDirection().Rotated(axis, u0)
    du = ad.Crossed(tangent)
    if du.X() * across[0] + du.Y() * across[1] + du.Z() * across[2] < 0:
        across = [-c for c in across]

    def uv_of(p):
        r = [p[i] - centre[i] for i in range(3)]
        s = sum(r[i] * across[i] for i in range(3))
        h = sum((p[i] - loc.Coord(i + 1)) * axis_dir[i] for i in range(3))
        return (u0 + s / radius, h)

    a = centre
    b = tuple(centre[i] + across[i] for i in range(3))
    c = tuple(centre[i] + axis_dir[i] for i in range(3))
    flat = [tuple(p) for p in (a, b, c)]
    mapped = _affine_uv(flat, [uv_of(p) for p in flat])
    surface = Geom_CylindricalSurface(cylinder)

    def edge_on_cylinder(edge):
        from OCP.BRepAdaptor import BRepAdaptor_Curve
        reader = BRepAdaptor_Curve(TopoDS.Edge_s(edge))
        curve = reader.Curve().Curve()
        spline = GeomConvert.CurveToBSplineCurve_s(
            Geom_TrimmedCurve(curve, reader.FirstParameter(),
                              reader.LastParameter()))
        poles3 = spline.Poles()
        poles = TColgp_Array1OfPnt2d(1, poles3.Length())
        for i in range(1, poles3.Length() + 1):
            p = poles3.Value(i)
            u, v = mapped((p.X(), p.Y(), p.Z()))
            poles.SetValue(i, gp_Pnt2d(u, v))
        weights = TColStd_Array1OfReal(1, poles3.Length())
        for i in range(1, poles3.Length() + 1):
            weights.SetValue(i, spline.Weight(i))
        curve2d = Geom2d_BSplineCurve(poles, weights, spline.Knots(),
                                      spline.Multiplicities(),
                                      spline.Degree(), spline.IsPeriodic())
        made = BRepBuilderAPI_MakeEdge(curve2d, surface,
                                       curve2d.FirstParameter(),
                                       curve2d.LastParameter())
        if not made.IsDone():
            raise KernelError("could not wrap a curve of the profile")
        out = made.Edge()
        BRepLib.BuildCurves3d_s(out)
        return out

    wrapped: List[TopoDS_Face] = []
    for flat_face in faces(profile):
        wires = explore(flat_face, TopAbs_WIRE)
        outer = BRepTools.OuterWire_s(TopoDS.Face_s(flat_face))
        built = []
        for wire in [outer] + [w for w in wires if not w.IsSame(outer)]:
            maker = BRepBuilderAPI_MakeWire()
            walker = BRepTools_WireExplorer(TopoDS.Wire_s(wire))
            while walker.More():
                maker.Add(edge_on_cylinder(walker.Current()))
                walker.Next()
            if not maker.IsDone():
                raise KernelError("could not wrap a loop of the profile")
            built.append(maker.Wire())
        made = BRepBuilderAPI_MakeFace(surface, built[0], True)
        for hole in built[1:]:
            made.Add(hole)
        if not made.IsDone():
            raise KernelError("could not wrap the profile")
        fixer = ShapeFix_Face(made.Face())
        fixer.FixOrientation()
        fixer.Perform()
        wrapped.append(TopoDS.Face_s(fixer.Face()))
    return wrapped


def emboss_tool(profile: TopoDS_Shape, plane: SketchPlane,
                face: TopoDS_Shape, depth: float, engrave: bool,
                towards: Sequence[float], wrap: bool = False
                ) -> TopoDS_Shape:
    """What Emboss adds, or Engrave takes away: the profile carried onto
    ``face`` and given ``depth``, out of the face or into it.

    Without ``wrap`` the profile is cast onto the face along ``towards``,
    the way Inventor's Emboss from Face is, so lettering on a curved face
    keeps its shape seen from the sketch.  With it the profile is wrapped
    round a cylindrical face, its widths becoming lengths round it.
    """
    if depth <= 0:
        raise KernelError("the depth must be more than nothing")
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.BRepLProp import BRepLProp_SLProps
    from OCP.TopAbs import TopAbs_REVERSED
    if wrap:
        letters = wrap_to_cylinder(profile, plane, face)
        layers = []
        for letter in letters:
            # the face's own normal, out of the cylinder or into it
            surface = BRepAdaptor_Surface(letter)
            u = (surface.FirstUParameter() + surface.LastUParameter()) / 2
            v = (surface.FirstVParameter() + surface.LastVParameter()) / 2
            props = BRepLProp_SLProps(surface, u, v, 1, 1e-6)
            n = props.Normal()
            if letter.Orientation() == TopAbs_REVERSED:
                n.Reverse()
            p = props.Value()
            axis = surface.Cylinder().Axis()
            radial = gp_Vec(axis.Location(), p)
            along = gp_Vec(axis.Direction())
            radial = radial - along.Multiplied(radial.Dot(along))
            outward = radial.Dot(gp_Vec(n)) > 0
            amount = depth if outward else -depth
            layers.append(thicken_face(letter, -amount if engrave
                                       else amount))
        return layers[0] if len(layers) == 1 else fuse_all(layers)

    box = bounding_box(compound([profile, face]))
    reach = 2.0 * math.dist(box[:3], box[3:]) + 1.0
    t = [float(c) for c in towards]
    start = [-c * reach for c in t]
    shifted = BRepBuilderAPI_Transform(
        profile, _translation(start), True).Shape()
    prism = extrude(shifted, t, 2.0 * reach)

    # a face's own normal points out of the part it bounds
    layer = thicken_face(face, -depth if engrave else depth)
    tool = boolean(prism, layer, "intersect")
    # The prism runs right through, so on a face that curves round, a
    # cylinder's, it meets the far side too.  Only the near side is
    # embossed: a piece is kept where the face is the first thing met
    # going from the sketch towards it.
    pieces = explore(tool, TopAbs_SOLID)
    if len(pieces) > 1:
        normal = [float(c) for c in plane.normal]
        flip = 1.0 if sum(a * b for a, b in zip(normal, t)) >= 0 else -1.0
        kept = []
        for piece in pieces:
            middle = shape_centre(piece)
            back = plane.distance_to(middle) * flip
            foot = [middle[i] - t[i] * back for i in range(3)]
            # of every place the ray crosses the face, the piece belongs to
            # the one it is nearest; it stays if that is the first
            crossings = ray_hits(face, foot, t)
            if not crossings:
                continue
            nearest = min(crossings, key=lambda w: abs(w - back))
            if nearest == crossings[0]:
                kept.append(piece)
        if not kept:
            raise KernelError("the profile does not meet the face")
        tool = kept[0] if len(kept) == 1 else compound(kept)
    return tool


def _translation(offset: Sequence[float]) -> gp_Trsf:
    move = gp_Trsf()
    move.SetTranslation(vec(offset))
    return move
