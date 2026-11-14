"""Model annotations: dimensions and hole notes on the 3D part.

Inventor's Annotate tab puts the sizes on the model itself rather than on
a drawing, which is what model based definition means: a shop that works
from the 3D model reads them there.  Two kinds cover most of what is
asked for, and are what is here:

* a dimension: between two picks (faces, edges or corners), the length of
  a straight edge, or the diameter of a round edge or face;
* a hole note: picked on the bore of a hole, the same note a drawing
  gives it, Ø8 THRU or Ø6.6 DEPTH 12 CBORE Ø11 DEPTH 6.8.

Each keeps what it was measured on as references, so it follows the part
when the part changes, and says so when what it measured is gone rather
than going on showing a number that no longer means anything.  Where its
text sits is kept as an offset from what it measures, so it moves with it
too.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

LINEAR = "linear"
DIAMETER = "diameter"
HOLE = "hole"
NOTE = "note"

KIND_LABELS = {LINEAR: "Dimension", DIAMETER: "Diameter",
               HOLE: "Hole Note", NOTE: "Note"}


def _mm(value: float) -> str:
    text = "%.3f" % value
    text = text.rstrip("0").rstrip(".")
    return text if text not in ("-0", "") else "0"


@dataclass
class ModelAnnotation:
    """One dimension or note on the model."""

    id: int = 0
    kind: str = LINEAR
    name: str = ""
    refs: List[Dict[str, Any]] = field(default_factory=list)
    ref_kinds: List[str] = field(default_factory=list)
    # where the text and dimension line stand off what is measured, in mm
    offset: List[float] = field(default_factory=lambda: [0.0, 0.0, 10.0])
    # typed in: replaces the measured text, or with "<>" in it, wraps it
    text: str = ""
    tolerance: str = ""
    hidden: bool = False
    # worked out by evaluate, never saved
    value: float = 0.0
    display: str = ""
    points: List[Tuple[float, float, float]] = field(default_factory=list)
    anchor: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    lost: bool = False

    def label(self) -> str:
        return self.name or "%s:%d" % (KIND_LABELS.get(self.kind, "Note"),
                                       self.id)

    def to_dict(self) -> Dict[str, Any]:
        out = {"id": self.id, "kind": self.kind, "name": self.name,
               "refs": [dict(r) for r in self.refs],
               "ref_kinds": list(self.ref_kinds),
               "offset": [float(v) for v in self.offset]}
        if self.text:
            out["text"] = self.text
        if self.tolerance:
            out["tolerance"] = self.tolerance
        if self.hidden:
            out["hidden"] = True
        return out

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ModelAnnotation":
        return cls(id=int(data.get("id", 0)),
                   kind=str(data.get("kind", LINEAR)),
                   name=str(data.get("name", "")),
                   refs=[dict(r) for r in data.get("refs") or []],
                   ref_kinds=[str(k) for k in data.get("ref_kinds") or []],
                   offset=[float(v) for v in
                           (data.get("offset") or [0.0, 0.0, 10.0])][:3],
                   text=str(data.get("text", "")),
                   tolerance=str(data.get("tolerance", "")),
                   hidden=bool(data.get("hidden", False)))

    # -- what it says ---------------------------------------------------------

    def wrap(self, measured: str) -> str:
        """The text shown: the measured one, or what was typed round it."""
        text = measured
        if self.text:
            text = (self.text.replace("<>", measured) if "<>" in self.text
                    else self.text)
        if self.tolerance:
            text += " " + self.tolerance
        return text


def capture(shape, picks: Sequence[Any]) -> Tuple[List[Dict[str, Any]],
                                                  List[str]]:
    """References to picked faces, edges or corners of a part's body."""
    from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_VERTEX

    from .naming import RefSet

    refs, kinds = [], []
    for pick in picks:
        kind = {TopAbs_FACE: "face", TopAbs_EDGE: "edge",
                TopAbs_VERTEX: "vertex"}.get(pick.ShapeType())
        if kind is None:
            continue
        captured = RefSet()
        captured.capture_from(shape, kind, [pick])
        if captured.refs:
            refs.append(captured.refs[0].to_dict())
            kinds.append(kind)
    return refs, kinds


def kind_for(picks: Sequence[Any]) -> Optional[str]:
    """What a set of picks measures: a hole note on a bore, a diameter on a
    round edge or face, a length on a straight edge, a distance between
    two.  None when they make no sense together."""
    from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE

    from .constraints3d import AXIS, CIRCLE, frame_from_shape

    if len(picks) == 2:
        return LINEAR
    if len(picks) != 1:
        return None
    pick = picks[0]
    frame = frame_from_shape(pick)
    round_ = (frame is not None and frame.kind in (AXIS, CIRCLE)
              and frame.radius > 0)
    if pick.ShapeType() == TopAbs_FACE and round_:
        return DIAMETER
    if pick.ShapeType() == TopAbs_EDGE:
        return DIAMETER if round_ else LINEAR
    return None


def _resolve(annotation: ModelAnnotation, shape) -> Optional[List[Any]]:
    from .naming import ShapeRef

    found = []
    for data in annotation.refs:
        try:
            reference = ShapeRef.from_dict(data)
            hit = reference.rebind(shape)
        except Exception:
            hit = None
        if hit is None:
            return None
        found.append(hit)
    return found


def _points(shape) -> Tuple[Tuple[float, ...], Tuple[float, ...]]:
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.TopoDS import TopoDS

    curve = BRepAdaptor_Curve(TopoDS.Edge_s(shape))
    a = curve.Value(curve.FirstParameter())
    b = curve.Value(curve.LastParameter())
    return (a.X(), a.Y(), a.Z()), (b.X(), b.Y(), b.Z())


def _hole_text(body, face) -> str:
    """The drawing's hole note for the bore a face belongs to."""
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.TopoDS import TopoDS

    from . import hlr
    from .views import hole_notes

    surface = BRepAdaptor_Surface(TopoDS.Face_s(face))
    axis = surface.Cylinder().Axis()
    d = axis.Direction()
    direction = (d.X(), d.Y(), d.Z())
    up = (0.0, 0.0, 1.0) if abs(direction[2]) < 0.9 else (0.0, 1.0, 0.0)
    loc = axis.Location()
    frame = hlr.camera(direction, up)
    spot = hlr.to_paper((loc.X(), loc.Y(), loc.Z()), frame, (0.0, 0.0))
    centres: List[Any] = []
    hole_notes(body, direction, up, (0.0, 0.0), 1.0, centres_out=centres)
    best, best_d = "", 0.05
    for at, label in centres:
        gap = math.dist(at, spot)
        if gap <= best_d:
            best, best_d = label, gap
    if best:
        return best
    return "Ø%s" % _mm(2.0 * surface.Cylinder().Radius())


def evaluate(annotation: ModelAnnotation, shape) -> ModelAnnotation:
    """Measure it again on the part as it is now."""
    from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE

    from .constraints3d import AXIS, CIRCLE, frame_from_shape
    from . import kernel

    annotation.lost = False
    if shape is None or shape.IsNull():
        annotation.lost = True
        annotation.display = annotation.wrap(annotation.display or "?")
        return annotation
    if annotation.kind == NOTE:
        annotation.display = annotation.text or "Note"
        return annotation
    found = _resolve(annotation, shape)
    if not found:
        annotation.lost = True
        # the last number it showed, marked, rather than nothing
        annotation.display = annotation.display or "?"
        return annotation

    try:
        if annotation.kind == LINEAR and len(found) == 2:
            measured = _closest(found[0], found[1])
            if measured is None:
                raise ValueError("no distance")
            value, a, b = measured
            annotation.value = value
            annotation.points = [a, b]
            annotation.anchor = tuple((a[i] + b[i]) / 2 for i in range(3))
            annotation.display = annotation.wrap(_mm(value))
        elif annotation.kind == LINEAR and len(found) == 1 \
                and found[0].ShapeType() == TopAbs_EDGE:
            a, b = _points(found[0])
            annotation.value = kernel.edge_length(found[0])
            annotation.points = [a, b]
            annotation.anchor = tuple((a[i] + b[i]) / 2 for i in range(3))
            annotation.display = annotation.wrap(_mm(annotation.value))
        elif annotation.kind in (DIAMETER, HOLE):
            pick = found[0]
            frame = frame_from_shape(pick)
            if (frame is None or frame.kind not in (AXIS, CIRCLE)
                    or frame.radius <= 0):
                raise ValueError("not round")
            centre = kernel.shape_centre(pick)
            if pick.ShapeType() == TopAbs_EDGE:
                rim, _ = _points(pick)
                centre = frame.origin
            else:
                # a point on the bore, out from its axis by the radius
                axis = frame.direction
                origin = frame.origin
                t = sum((centre[i] - origin[i]) * axis[i] for i in range(3))
                on_axis = [origin[i] + t * axis[i] for i in range(3)]
                side = _perpendicular(axis)
                rim = tuple(on_axis[i] + side[i] * frame.radius
                            for i in range(3))
                centre = tuple(on_axis)
            annotation.value = 2.0 * frame.radius
            annotation.points = [tuple(centre), tuple(rim)]
            annotation.anchor = tuple(rim)
            if annotation.kind == HOLE and pick.ShapeType() == TopAbs_FACE:
                annotation.display = annotation.wrap(_hole_text(shape, pick))
            else:
                annotation.display = annotation.wrap(
                    "Ø" + _mm(annotation.value))
        else:
            raise ValueError("cannot measure")
    except Exception:
        annotation.lost = True
        annotation.display = annotation.display or "?"
    return annotation


def _perpendicular(v: Sequence[float]) -> Tuple[float, float, float]:
    """A unit vector square to v, the same one every time."""
    helper = (0.0, 0.0, 1.0) if abs(v[2]) < 0.9 else (1.0, 0.0, 0.0)
    x = (v[1] * helper[2] - v[2] * helper[1],
         v[2] * helper[0] - v[0] * helper[2],
         v[0] * helper[1] - v[1] * helper[0])
    n = math.sqrt(sum(c * c for c in x)) or 1.0
    return tuple(c / n for c in x)


def _closest(a, b):
    """The shortest distance between two shapes and its two end points."""
    from OCP.BRepExtrema import BRepExtrema_DistShapeShape

    probe = BRepExtrema_DistShapeShape(a, b)
    if not probe.IsDone() or probe.NbSolution() < 1:
        return None
    pa, pb = probe.PointOnShape1(1), probe.PointOnShape2(1)
    return (probe.Value(), (pa.X(), pa.Y(), pa.Z()),
            (pb.X(), pb.Y(), pb.Z()))


def evaluate_all(document) -> int:
    """Measure every annotation of a part again.  Returns how many are
    lost."""
    lost = 0
    for annotation in getattr(document, "annotations", None) or []:
        evaluate(annotation, document.shape)
        lost += annotation.lost
    return lost


def default_offset(annotation: ModelAnnotation, shape,
                   view_dir: Optional[Sequence[float]] = None
                   ) -> List[float]:
    """Where a new annotation's text goes: out from the part's middle,
    past what it measures, so it does not sit inside the body."""
    from . import kernel

    try:
        middle = kernel.shape_centre(shape)
    except Exception:
        middle = (0.0, 0.0, 0.0)
    a = annotation.anchor
    out = [a[i] - middle[i] for i in range(3)]
    if annotation.kind == LINEAR and len(annotation.points) == 2:
        p, q = annotation.points
        span = [q[i] - p[i] for i in range(3)]
        n = math.sqrt(sum(c * c for c in span)) or 1.0
        span = [c / n for c in span]
        along = sum(out[i] * span[i] for i in range(3))
        out = [out[i] - along * span[i] for i in range(3)]
    if view_dir is not None:
        towards = sum(out[i] * view_dir[i] for i in range(3))
        out = [out[i] - towards * view_dir[i] for i in range(3)]
    n = math.sqrt(sum(c * c for c in out))
    if n < 1e-6:
        out, n = [0.0, 0.0, 1.0], 1.0
    try:
        box = kernel.bounding_box(shape)
        size = max(box[3] - box[0], box[4] - box[1], box[5] - box[2])
    except Exception:
        size = 50.0
    reach = max(8.0, size * 0.18)
    return [c / n * reach for c in out]
