"""Turning a solid into the lines a drawing is made of.

One job: look at a shape from a direction and come back with 2D polylines,
each labelled with what sort of edge it came from.  Nothing here knows about
sheets, scales or paper - a projection is in model millimetres, centred on
the model, and whoever places it decides where on the page it lands.

Hidden line removal is OpenCASCADE's.  ``HLRBRep_Algo`` is the exact one,
working on the real curves; ``HLRBRep_PolyAlgo`` works on the tessellation
and is much faster on a big assembly but tells you less.  The exact one is
used by default because a drawing is a deliverable, and it is quick enough:
a five-part assembly projects in about fifty milliseconds.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from OCP.BRep import BRep_Tool
from OCP.BRepAdaptor import BRepAdaptor_Curve
from OCP.GCPnts import GCPnts_QuasiUniformDeflection
from OCP.HLRAlgo import HLRAlgo_Projector
from OCP.HLRBRep import HLRBRep_Algo, HLRBRep_HLRToShape
from OCP.TopAbs import TopAbs_EDGE
from OCP.TopoDS import TopoDS, TopoDS_Shape
from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt, gp_Trsf, gp_Vec

from . import kernel

# Edge kinds, in the order they should be drawn: hidden underneath, visible
# on top, so a coincident pair reads as visible.
HIDDEN = "hidden"
SMOOTH = "smooth"          # tangent joins - a softened edge, drawn thin
OUTLINE = "outline"        # silhouette of a curved face
VISIBLE = "visible"
# The boundary of a face the cutting plane passed through.  Kept apart from
# the rest because it is the only thing on a section that gets hatched, and
# hatching the wrong face is how a section stops meaning anything.
CUT = "cut"
# a sheet metal flat pattern's bend centre lines, to be marked, not cut
BEND = "bend"
# a cosmetic thread as ISO 6410 draws it: thin continuous lines at the
# root of an external thread or the crest of an internal one
THREAD = "thread"
KINDS = (HIDDEN, SMOOTH, OUTLINE, VISIBLE, CUT, BEND, THREAD)

# how finely a curved edge is broken into straight segments, in millimetres
# of allowed deviation.  Small enough that a 3 mm fillet still reads round.
DEFLECTION = 0.02

# The standard views, as the direction you look *along* plus which way is up
# on the paper.  Front looks down -Y with Z up, which is the convention every
# drawing in an engineering office uses.
ORIENTATIONS: Dict[str, Tuple[Tuple[float, float, float],
                              Tuple[float, float, float]]] = {
    "front":  ((0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
    "back":   ((0.0, -1.0, 0.0), (0.0, 0.0, 1.0)),
    "left":   ((1.0, 0.0, 0.0), (0.0, 0.0, 1.0)),
    "right":  ((-1.0, 0.0, 0.0), (0.0, 0.0, 1.0)),
    "top":    ((0.0, 0.0, -1.0), (0.0, 1.0, 0.0)),
    "bottom": ((0.0, 0.0, 1.0), (0.0, 1.0, 0.0)),
    "iso":    ((-1.0, 1.0, -1.0), (0.0, 0.0, 1.0)),
}

ORIENTATION_LABELS = {
    "front": "Front", "back": "Back", "left": "Left", "right": "Right",
    "top": "Top", "bottom": "Bottom", "iso": "Isometric",
}


def _unit(v: Sequence[float]) -> Tuple[float, float, float]:
    n = math.sqrt(sum(float(c) * float(c) for c in v))
    if n < 1e-12:
        return (0.0, 0.0, 1.0)
    return (float(v[0]) / n, float(v[1]) / n, float(v[2]) / n)


@dataclass
class Polyline:
    """One projected edge, already flattened to straight segments."""

    points: List[Tuple[float, float]] = field(default_factory=list)
    kind: str = VISIBLE

    def bounds(self) -> Tuple[float, float, float, float]:
        xs = [p[0] for p in self.points]
        ys = [p[1] for p in self.points]
        return (min(xs), min(ys), max(xs), max(ys)) if xs else (0, 0, 0, 0)


@dataclass
class Projection:
    """What a view looks like, in model millimetres about its own centre."""

    lines: List[Polyline] = field(default_factory=list)
    # the model-space box the projection was taken from, so a child view can
    # be aligned to the same centre as its parent
    box: Tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    # which fill the cut faces want, resolved when the view was generated
    hatch: str = ""
    # what was subtracted to centre it, in the projection's own frame, so a
    # point projected later lands in the same place as the lines did
    centre: Tuple[float, float] = (0.0, 0.0)
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error

    @property
    def width(self) -> float:
        return self.box[2] - self.box[0]

    @property
    def height(self) -> float:
        return self.box[3] - self.box[1]

    def of_kind(self, kind: str) -> List[Polyline]:
        return [line for line in self.lines if line.kind == kind]

    def to_dict(self) -> Dict:
        return {"box": list(self.box), "centre": list(self.centre),
                "error": self.error, "hatch": self.hatch,
                "lines": [{"k": line.kind,
                           "p": [[round(x, 4), round(y, 4)]
                                 for x, y in line.points]}
                          for line in self.lines]}

    @classmethod
    def from_dict(cls, data: Dict) -> "Projection":
        lines = []
        for raw in data.get("lines", []):
            points = [(float(p[0]), float(p[1])) for p in raw.get("p", [])
                      if len(p) >= 2]
            if len(points) >= 2:
                lines.append(Polyline(points, str(raw.get("k", VISIBLE))))
        box = data.get("box", [0, 0, 0, 0])
        middle = data.get("centre", [0.0, 0.0])
        return cls(lines=lines, hatch=str(data.get("hatch", "")),
                   box=tuple(float(v) for v in box[:4]) if len(box) >= 4
                   else (0.0, 0.0, 0.0, 0.0),
                   centre=(float(middle[0]), float(middle[1]))
                   if len(middle) >= 2 else (0.0, 0.0),
                   error=str(data.get("error", "")))


def camera(direction: Sequence[float],
           up: Sequence[float] = (0.0, 0.0, 1.0)) -> gp_Ax2:
    """The frame a projection is taken in.

    ``direction`` is the way the *viewer* faces, so a front view looks along
    +Y at a model whose front is -Y.  The axis handed to OCCT is the reverse
    of that, because its projector wants the direction pointing out of the
    paper towards you.
    """
    look = _unit(direction)
    out = (-look[0], -look[1], -look[2])
    upward = _unit(up)
    # an up vector parallel to the view direction says nothing; fall back to
    # something that is not, so the frame is still well defined
    if abs(sum(out[i] * upward[i] for i in range(3))) > 0.999:
        upward = (0.0, 0.0, 1.0) if abs(out[2]) < 0.9 else (0.0, 1.0, 0.0)
    return gp_Ax2(gp_Pnt(0.0, 0.0, 0.0), gp_Dir(*out), _side(out, upward))


def _side(out: Sequence[float], up: Sequence[float]) -> gp_Dir:
    """The paper's X axis: across the page, to the right."""
    right = (up[1] * out[2] - up[2] * out[1],
             up[2] * out[0] - up[0] * out[2],
             up[0] * out[1] - up[1] * out[0])
    return gp_Dir(*_unit(right))


def to_paper(point: Sequence[float], frame: gp_Ax2,
             centre: Sequence[float] = (0.0, 0.0)) -> Tuple[float, float]:
    """Where a model point lands on the paper, in the same space a
    projection's lines are in.

    A projection is centred on its own geometry rather than on the model's
    origin, so anything measured against it has to have the same centre
    taken off.  That centre travels with the projection for exactly this.
    """
    origin = frame.Location()
    x_axis = frame.XDirection()
    y_axis = frame.YDirection()
    dx = float(point[0]) - origin.X()
    dy = float(point[1]) - origin.Y()
    dz = float(point[2]) - origin.Z()
    return (dx * x_axis.X() + dy * x_axis.Y() + dz * x_axis.Z() - centre[0],
            dx * y_axis.X() + dy * y_axis.Y() + dz * y_axis.Z() - centre[1])


def cut_faces(shape: TopoDS_Shape, point: Sequence[float],
              normal: Sequence[float], tolerance: float = 1e-4) -> List:
    """The faces of a cut solid that lie in the cutting plane.

    These are the faces the knife made, and they are the ones a section
    hatches.  Found by asking which planar faces sit in the plane and face
    the way it does, which is exactly what being cut by it means.
    """
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_SurfaceType
    from OCP.TopAbs import TopAbs_FACE

    n = _unit(normal)
    out = []
    for face in kernel.explore(shape, TopAbs_FACE):
        try:
            surface = BRepAdaptor_Surface(TopoDS.Face_s(face))
            if surface.GetType() != GeomAbs_SurfaceType.GeomAbs_Plane:
                continue
            axis = surface.Plane().Axis()
            d = axis.Direction()
        except Exception:
            continue
        if abs(abs(d.X() * n[0] + d.Y() * n[1] + d.Z() * n[2]) - 1.0) > 1e-3:
            continue
        centre = kernel.shape_centre(face)
        offset = sum((centre[i] - point[i]) * n[i] for i in range(3))
        if abs(offset) <= max(tolerance, 1e-4):
            out.append(face)
    return out


def project(shape: Optional[TopoDS_Shape],
            direction: Sequence[float] = (0.0, 1.0, 0.0),
            up: Sequence[float] = (0.0, 0.0, 1.0),
            hidden: bool = True,
            tangents: bool = True,
            hatch: Optional[Sequence] = None,
            fast: bool = False) -> Projection:
    """Flatten a shape into drawing lines, seen from ``direction``.

    The result is centred on the projected geometry rather than on the
    model's origin, so a view lands where it is put and not wherever the
    part happens to sit in space.

    ``fast`` works on a coarse tessellation instead of the real curves
    (``HLRBRep_PolyAlgo``): rough round the curves, many times quicker on
    a big model.  Inventor's way with a view being placed: a quick draft
    while it is set up, the real lines once it is.
    """
    if shape is None or shape.IsNull():
        return Projection(error="there is no geometry to draw")

    # an unmarked seam would be drawn as a line down every cylinder
    kernel.mark_seams(shape)
    frame = camera(direction, up)
    if fast:
        try:
            result = _fast_hlr(shape, frame)
        except Exception:
            result = None
        if result is None:
            fast = False
    if not fast:
        try:
            algo = HLRBRep_Algo()
            algo.Add(shape)
            algo.Projector(HLRAlgo_Projector(frame))
            algo.Update()
            algo.Hide()
            result = HLRBRep_HLRToShape(algo)
        except Exception as exc:
            return Projection(error="could not project this shape: %s" % exc)

    wanted = [(result.VCompound(), VISIBLE),
              (result.OutLineVCompound(), OUTLINE)]
    hatched: List[Polyline] = []
    if hatch:
        frame_for_hatch = frame
        for face in hatch:
            for wire in _face_loops(face, frame_for_hatch):
                hatched.append(Polyline(wire, CUT))
    if tangents:
        wanted.append((result.Rg1LineVCompound(), SMOOTH))
    if hidden:
        wanted.append((result.HCompound(), HIDDEN))
        wanted.append((result.OutLineHCompound(), HIDDEN))

    # HLR hands back its result already flattened onto the projection plane,
    # in the frame's own coordinates: X across the page, Y up it, Z zero.
    lines: List[Polyline] = []
    flatten = _flatten_poly if fast else _flatten
    for compound, kind in wanted:
        if compound is None or compound.IsNull():
            continue
        for edge in kernel.explore(compound, TopAbs_EDGE):
            for points in flatten(edge):
                if len(points) >= 2:
                    lines.append(Polyline(points, kind))

    if fast:
        lines = _chain(lines)
    lines.extend(hatched)
    if not lines:
        return Projection(error="nothing is visible from this direction")

    xs = [p[0] for line in lines for p in line.points]
    ys = [p[1] for line in lines for p in line.points]
    cx = (min(xs) + max(xs)) / 2.0
    cy = (min(ys) + max(ys)) / 2.0
    for line in lines:
        line.points = [(x - cx, y - cy) for x, y in line.points]

    half_w = (max(xs) - min(xs)) / 2.0
    half_h = (max(ys) - min(ys)) / 2.0
    return Projection(lines=lines, centre=(cx, cy),
                      box=(-half_w, -half_h, half_w, half_h))


def outlines(shape: Optional[TopoDS_Shape],
             direction: Sequence[float] = (0.0, 1.0, 0.0),
             up: Sequence[float] = (0.0, 0.0, 1.0)) -> Projection:
    """A placeholder for a view of a big model: each solid's box, seen
    from ``direction``, as the outline it makes on the paper.

    Nothing is hidden and nothing curved is followed, so it takes
    milliseconds where the real lines take seconds, and it is already the
    size and shape of the view, near enough to place and align by.
    Drawn thin, as smooth edges are, so it does not pass for the real
    thing.
    """
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib
    from OCP.TopAbs import TopAbs_SOLID

    if shape is None or shape.IsNull():
        return Projection(error="there is no geometry to draw")
    frame = camera(direction, up)
    solids = list(kernel.explore(shape, TopAbs_SOLID)) or [shape]
    lines: List[Polyline] = []
    for solid in solids:
        box = Bnd_Box()
        try:
            BRepBndLib.Add_s(solid, box, True)
        except Exception:
            continue
        if box.IsVoid():
            continue
        x0, y0, z0, x1, y1, z1 = box.Get()
        corners = [to_paper((x, y, z), frame)
                   for x in (x0, x1) for y in (y0, y1) for z in (z0, z1)]
        hull = _hull(corners)
        if len(hull) >= 2:
            lines.append(Polyline(hull + hull[:1], SMOOTH))
    if not lines:
        return Projection(error="nothing is visible from this direction")
    xs = [p[0] for line in lines for p in line.points]
    ys = [p[1] for line in lines for p in line.points]
    cx = (min(xs) + max(xs)) / 2.0
    cy = (min(ys) + max(ys)) / 2.0
    for line in lines:
        line.points = [(x - cx, y - cy) for x, y in line.points]
    half_w = (max(xs) - min(xs)) / 2.0
    half_h = (max(ys) - min(ys)) / 2.0
    return Projection(lines=lines, centre=(cx, cy),
                      box=(-half_w, -half_h, half_w, half_h))


def _hull(points: Sequence[Tuple[float, float]]) -> List[Tuple[float, float]]:
    """The convex hull, anticlockwise (Andrew's monotone chain)."""
    pts = sorted(set((round(x, 9), round(y, 9)) for x, y in points))
    if len(pts) <= 2:
        return list(pts)

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower: List[Tuple[float, float]] = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    upper: List[Tuple[float, float]] = []
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def thread_lines(marks, direction, up, centre=(0.0, 0.0),
                 hidden: bool = True) -> List[Polyline]:
    """Threads drawn the ISO 6410 way, in a projection's own frame
    (model millimetres about ``centre``).

    Seen from the side, an external thread is two thin lines at its root
    diameter and a wide line across where the full thread ends; an
    internal one is the same at its crest diameter, hidden, since a hole
    seen from outside is. Seen end on, a thin three-quarter circle. Seen
    at a slant, nothing: the convention has no picture for that.
    """
    from . import threads as _threads

    frame = camera(direction, up)
    look = _unit(direction)
    out: List[Polyline] = []
    for mark in marks:
        axis = _unit(mark.axis)
        along = abs(sum(axis[i] * look[i] for i in range(3)))
        pitch = max(1e-3, float(mark.pitch))
        r = float(mark.radius)
        if mark.internal:
            nominal = _threads.match(2.0 * r).diameter / 2.0
            thin = max(nominal, r)
            if thin - r < 0.1 * pitch:
                # the face was drawn at the nominal size, not the tap
                # drill: the crest line still has to show outside it
                thin = r + 0.54 * pitch
            wide = r
        else:
            thin = r - 0.6134 * pitch
            wide = r
        if thin <= 0:
            continue
        start = mark.origin
        end = tuple(start[i] + axis[i] * mark.length for i in range(3))
        a = to_paper(start, frame, centre)
        b = to_paper(end, frame, centre)
        if along < 0.02:
            # the axis lies on the paper: the side view
            dx, dy = b[0] - a[0], b[1] - a[1]
            span = math.hypot(dx, dy)
            if span < 1e-9:
                continue
            nx, ny = -dy / span, dx / span
            kind = HIDDEN if mark.internal else THREAD
            if mark.internal and not hidden:
                continue
            for side in (1.0, -1.0):
                out.append(Polyline(
                    [(a[0] + nx * thin * side, a[1] + ny * thin * side),
                     (b[0] + nx * thin * side, b[1] + ny * thin * side)],
                    kind))
            if not mark.internal:
                # where the full thread stops, across the shaft
                out.append(Polyline(
                    [(b[0] + nx * wide, b[1] + ny * wide),
                     (b[0] - nx * wide, b[1] - ny * wide)], VISIBLE))
        elif along > 0.98:
            # end on: three quarters of a circle, the gap up and right
            cx, cy = a
            steps = 54
            points = []
            for k in range(steps + 1):
                t = math.radians(100.0 + 270.0 * k / steps)
                points.append((cx + thin * math.cos(t),
                               cy + thin * math.sin(t)))
            out.append(Polyline(points, THREAD))
    return out


# how coarse the draft tessellation is, as a share of the model's size
FAST_DEFLECTION = 0.004


def _fast_hlr(shape: TopoDS_Shape, frame: gp_Ax2):
    """Hidden lines from the tessellation, for a draft of a view."""
    from OCP.BRepMesh import BRepMesh_IncrementalMesh
    from OCP.HLRBRep import HLRBRep_PolyAlgo, HLRBRep_PolyHLRToShape

    box = kernel.bounding_box(shape)
    size = max(box[3] - box[0], box[4] - box[1], box[5] - box[2], 1.0)
    # meshes a body only where it has none fine enough already, which a
    # model shown on screen nearly always has
    BRepMesh_IncrementalMesh(shape, size * FAST_DEFLECTION, False, 0.5, True)
    algo = HLRBRep_PolyAlgo(shape)
    algo.Projector(HLRAlgo_Projector(frame))
    algo.Update()
    result = HLRBRep_PolyHLRToShape()
    result.Update(algo)
    return result


def _chain(lines: List[Polyline]) -> List[Polyline]:
    """Join a draft's loose segments end to end into polylines, so the
    sheet has hundreds of lines to draw rather than tens of thousands."""
    def key(p):
        return (round(p[0], 4), round(p[1], 4))

    out: List[Polyline] = []
    for kind in KINDS:
        segs = [line.points for line in lines if line.kind == kind]
        if not segs:
            continue
        ends: Dict[Tuple[float, float], List[int]] = {}
        for i, s in enumerate(segs):
            ends.setdefault(key(s[0]), []).append(i)
            ends.setdefault(key(s[-1]), []).append(i)
        used = [False] * len(segs)

        def take(at):
            for j in ends.get(key(at), ()):
                if not used[j]:
                    used[j] = True
                    s = segs[j]
                    return s if key(s[0]) == key(at) else s[::-1]
            return None

        for i, s in enumerate(segs):
            if used[i]:
                continue
            used[i] = True
            path = list(s)
            while True:
                nxt = take(path[-1])
                if nxt is None:
                    break
                path.extend(nxt[1:])
            while True:
                prv = take(path[0])
                if prv is None:
                    break
                path[:0] = prv[::-1][:-1]
            out.append(Polyline(path, kind))
    return out


def _flatten_poly(edge) -> List[List[Tuple[float, float]]]:
    """A draft edge is already straight segments: its two ends."""
    from OCP.BRep import BRep_Tool as _T
    from OCP.TopExp import TopExp
    from OCP.TopoDS import TopoDS as _D
    edge = _D.Edge_s(edge)
    first, last = TopExp.FirstVertex_s(edge), TopExp.LastVertex_s(edge)
    if first.IsNull() or last.IsNull():
        return _flatten(edge)
    a, b = _T.Pnt_s(first), _T.Pnt_s(last)
    return [[(a.X(), a.Y()), (b.X(), b.Y())]]


def _face_loops(face, frame: gp_Ax2) -> List[List[Tuple[float, float]]]:
    """A face's wires, projected flat, ready to be filled.

    Each edge is walked the way the wire runs through it. A curve is
    sampled from its first parameter to its last whichever way round the
    wire uses it, so an edge the wire takes backwards has to be read
    backwards: read forwards, the outline doubled back on itself at every
    such edge, and the hatch of an L shaped cut came out as wedges.
    """
    from OCP.BRepTools import BRepTools_WireExplorer
    from OCP.TopAbs import TopAbs_REVERSED, TopAbs_WIRE

    out: List[List[Tuple[float, float]]] = []
    for wire in kernel.explore(face, TopAbs_WIRE):
        points: List[Tuple[float, float]] = []
        try:
            walker = BRepTools_WireExplorer(TopoDS.Wire_s(wire))
            while walker.More():
                edge = walker.Current()
                backwards = edge.Orientation() == TopAbs_REVERSED
                for piece in _flatten_3d(edge):
                    if backwards:
                        piece = piece[::-1]
                    for p in piece:
                        here = to_paper(p, frame)
                        if not points or math.dist(points[-1], here) > 1e-9:
                            points.append(here)
                walker.Next()
        except Exception:
            continue
        if len(points) >= 3:
            out.append(points)
    return out


def _flatten_3d(edge) -> List[List[Tuple[float, float, float]]]:
    """An edge as 3D points, before anything is projected."""
    try:
        curve = BRepAdaptor_Curve(TopoDS.Edge_s(edge))
    except Exception:
        return []
    try:
        sampler = GCPnts_QuasiUniformDeflection(curve, DEFLECTION)
        if not sampler.IsDone() or sampler.NbPoints() < 2:
            raise RuntimeError
        points = [sampler.Value(i) for i in range(1, sampler.NbPoints() + 1)]
    except Exception:
        try:
            first, last = curve.FirstParameter(), curve.LastParameter()
            points = [curve.Value(first), curve.Value(last)]
        except Exception:
            return []
    return [[(p.X(), p.Y(), p.Z()) for p in points]]


def _flatten(edge) -> List[List[Tuple[float, float]]]:
    """One projected edge as a list of points, curves broken into segments."""
    try:
        curve = BRepAdaptor_Curve(TopoDS.Edge_s(edge))
    except Exception:
        return []

    try:
        sampler = GCPnts_QuasiUniformDeflection(curve, DEFLECTION)
        if not sampler.IsDone() or sampler.NbPoints() < 2:
            raise RuntimeError
        points = [sampler.Value(i) for i in range(1, sampler.NbPoints() + 1)]
    except Exception:
        try:
            first, last = curve.FirstParameter(), curve.LastParameter()
            points = [curve.Value(first), curve.Value(last)]
        except Exception:
            return []

    return [[(p.X(), p.Y()) for p in points]]
