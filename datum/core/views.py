"""Generating a drawing's views from the models it references.

The document says what the views *are*; this works out what they look like.
It is the only place that loads a referenced file, so a drawing that is
merely being read - printed, exported, listed - never touches a model at
all: the cached projections in the file are enough.
"""

from __future__ import annotations

import math
import os
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

from OCP.BRepAlgoAPI import BRepAlgoAPI_Common
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
from OCP.TopoDS import TopoDS_Shape

from . import bom, drawing, fileformat, hlr, kernel, partial, projcache
from .drawing import (
    AUXILIARY, BASE, DETAIL, DrawingDocument, DrawingReport, PROJECTED,
    SECTION, Sheet, View, WITH_HIDDEN,
)
from .naming import ShapeRef
from .parts import PartLibrary


def _unit(v: Sequence[float]) -> Tuple[float, float, float]:
    n = math.sqrt(sum(float(c) * float(c) for c in v))
    if n < 1e-12:
        return (0.0, 0.0, 1.0)
    return (float(v[0]) / n, float(v[1]) / n, float(v[2]) / n)


def _cross(a: Sequence[float], b: Sequence[float]
           ) -> Tuple[float, float, float]:
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def _negate(v: Sequence[float]) -> Tuple[float, float, float]:
    return (-v[0], -v[1], -v[2])


def orientation_of(view: View) -> Tuple[Tuple[float, float, float],
                                        Tuple[float, float, float]]:
    """Which way a base view looks, and which way is up on the paper."""
    if len(view.direction) >= 3 and len(view.up) >= 3:
        return (_unit(view.direction), _unit(view.up))
    return hlr.ORIENTATIONS.get(view.orientation, hlr.ORIENTATIONS["front"])


def projected_orientation(parent_dir: Sequence[float],
                          parent_up: Sequence[float],
                          dx: float, dy: float,
                          angle: str = drawing.FIRST_ANGLE
                          ) -> Tuple[Tuple[float, float, float],
                                     Tuple[float, float, float]]:
    """Which way a projected view looks, from where it was dragged.

    Third angle puts the view on the side you looked from: drag right and
    you get the right-hand side, because that is where you were standing.
    First angle puts it on the far side, which is why an ISO drawing's right
    view sits on the left.  One sign, and the whole sheet changes meaning.

    A diagonal drag is not an orthographic view at all; it is the isometric,
    and it is handled by the caller.
    """
    look = _unit(parent_dir)
    up = _unit(parent_up)
    right = _unit(_cross(up, _negate(look)))   # across the page, to the right

    flip = 1.0 if angle == drawing.THIRD_ANGLE else -1.0
    if abs(dx) >= abs(dy):
        if dx == 0:
            return (look, up)
        side = math.copysign(1.0, dx) * flip
        # standing to the right of the part means looking back along -right
        return (_unit([-side * c for c in right]), up)

    side = math.copysign(1.0, dy) * flip
    # standing above means looking down; what was the viewing direction
    # becomes the up direction on the new page
    new_look = _unit([-side * c for c in up])
    new_up = _unit([side * c for c in look])
    return (new_look, new_up)


def iso_orientation(parent_dir: Sequence[float],
                    parent_up: Sequence[float], dx: float, dy: float
                    ) -> Tuple[Tuple[float, float, float],
                               Tuple[float, float, float]]:
    """The isometric a view dragged off a corner of its parent shows.

    Taken from the parent, not from the model's own axes: off the top
    right of a front view it is the model seen from the front, the right
    and above, and off the top right of a top view it is the top view
    tipped the same way.  The corner it is put towards is the corner it is
    seen from, so turning the parent turns it too.
    """
    look = _unit(parent_dir)
    up = _unit(parent_up)
    right = _unit(_cross(up, _negate(look)))
    sx = math.copysign(1.0, dx)
    sy = math.copysign(1.0, dy)
    direction = _unit([look[i] - sx * right[i] - sy * up[i]
                       for i in range(3)])
    along = sum(up[i] * direction[i] for i in range(3))
    new_up = _unit([up[i] - along * direction[i] for i in range(3)])
    return (direction, new_up)


def outline(box: Sequence[float], direction: Sequence[float],
            up: Sequence[float]) -> Tuple[float, float]:
    """How big a model's box looks from this direction: across, and up.

    Its eight corners projected onto the page.  Cheap, so a view can be
    shown where it will land while the cursor is still moving, long before
    its lines have been worked out.
    """
    look = _unit(direction)
    up = _unit(up)
    right = _unit(_cross(up, _negate(look)))
    across, upward = [], []
    for x in (box[0], box[3]):
        for y in (box[1], box[4]):
            for z in (box[2], box[5]):
                across.append(x * right[0] + y * right[1] + z * right[2])
                upward.append(x * up[0] + y * up[1] + z * up[2])
    return (max(across) - min(across), max(upward) - min(upward))


def named_orientation(direction: Sequence[float], setup=None) -> str:
    """Which standard view looks this way, "front" and so on, or "".

    ``setup`` is the model's own Front and Top (core.viewsetup), when it
    has moved them; the names follow it."""
    look = _unit(direction)
    for name in hlr.ORIENTATIONS:
        d = (setup.orientation(name)[0] if setup is not None
             else hlr.ORIENTATIONS[name][0])
        if math.dist(look, _unit(d)) < 1e-6:
            return name
    return ""


def auxiliary_orientation(parent_dir: Sequence[float],
                          parent_up: Sequence[float],
                          edge_angle_deg: float
                          ) -> Tuple[Tuple[float, float, float],
                                     Tuple[float, float, float]]:
    """Look square onto a face whose edge lies at this angle on the parent."""
    look = _unit(parent_dir)
    up = _unit(parent_up)
    right = _unit(_cross(up, _negate(look)))
    theta = math.radians(edge_angle_deg)
    # the edge direction on the parent's paper, and the view looks along its
    # normal - which is the edge turned a quarter turn
    along = _unit([right[i] * math.cos(theta) + up[i] * math.sin(theta)
                   for i in range(3)])
    new_look = _unit([right[i] * math.cos(theta + math.pi / 2.0)
                      + up[i] * math.sin(theta + math.pi / 2.0)
                      for i in range(3)])
    return (new_look, along)


# --------------------------------------------------------------- properties


_MEASURED: Dict[Any, Tuple[float, float]] = {}


def model_properties(path: str, shape: Optional[TopoDS_Shape],
                     document=None, library=None) -> Dict[str, str]:
    """What a title block can ask of a model, whether part or assembly.

    Duck-typed on purpose: a part and an assembly answer the same questions
    without either of them having to know that drawings exist.
    """
    name = os.path.splitext(os.path.basename(path))[0] if path else ""
    out = {
        "Model.Name": name,
        "Model.PartNumber": name,
        "Model.Material": "",
        "Model.Mass": "",
        "Model.Volume": "",
        "Model.Area": "",
        "Model.Units": "mm",
    }
    if document is not None:
        # what somebody typed into the part's own properties wins over the
        # file name: that is what those fields are for
        held = getattr(document, "properties", None) or {}
        # every property the part holds can be asked for by its own name,
        # {Model.Vendor} and so on; the named ones below then take over
        for prop, value in held.items():
            if str(value):
                out.setdefault("Model." + str(prop), str(value))
        for key, prop in (("Model.Name", "Title"),
                          ("Model.PartNumber", "PartNumber"),
                          ("Model.Designer", "Designer")):
            if held.get(prop):
                out[key] = str(held[prop])
        out["Model.Material"] = str(getattr(document, "material", "") or "")
        out["Model.Units"] = str(getattr(document, "units", "mm") or "mm")
        number = ""
        params = getattr(document, "params", None)
        if params is not None:
            try:
                scope = params.scope()
                if "part_number" in scope:
                    number = "%g" % scope["part_number"]
            except Exception:
                number = ""
        if number:
            out["Model.PartNumber"] = number

    if shape is not None and not shape.IsNull():
        # measured once per file as it stands: every drawing rebuild asked
        # again, and on a big assembly that was a good part of the rebuild
        try:
            stamp = os.stat(path)
            key = (os.path.normcase(os.path.abspath(path)),
                   stamp.st_mtime_ns, stamp.st_size, id(shape))
        except (OSError, TypeError):
            key = None
        held = _MEASURED.get(key) if key else None
        if held is None:
            try:
                held = (kernel.volume(shape), kernel.surface_area(shape))
            except Exception:
                held = None
            if key and held is not None:
                if len(_MEASURED) > 256:
                    _MEASURED.clear()
                _MEASURED[key] = held
        if held is not None:
            volume, area = held
            out["Model.Volume"] = "%.1f cm3" % (volume / 1000.0)
            out["Model.Area"] = "%.1f cm2" % (area / 100.0)
            mass = None
            if getattr(document, "occurrences", None) is not None:
                # an assembly weighs what its parts weigh, each in its
                # own material, not its volume in one density
                try:
                    from . import bom
                    mass = bom.mass_grams(path, library)
                except Exception:
                    mass = None
            if mass is None:
                density = float(getattr(document, "density", 1.0) or 1.0)
                mass = volume / 1000.0 * density
            out["Model.Mass"] = "%.1f g" % mass
    return out


def load_model(path: str, library: PartLibrary):
    """The body and the document behind a reference, or (None, None)."""
    from .assembly import AssemblyDocument
    from .document import Document

    shape = library.shape(path)
    document = None
    try:
        kind = fileformat.peek(path).type
        if kind == fileformat.ASSEMBLY:
            document = AssemblyDocument.load(path)
        else:
            document = Document.load(path)
    except Exception:
        document = None
    return shape, document


# ------------------------------------------------------------- snapping


def projected_vertices(shape, direction, up, centre=(0.0, 0.0),
                       scale: float = 1.0):
    """Every model vertex, where it lands on this view's paper.

    Returned with the index it had in the model, because that index plus a
    fingerprint is what makes a reference that survives a rebuild.
    """
    frame = hlr.camera(direction, up)
    out = []
    for index, vertex in enumerate(kernel.vertices(shape)):
        x, y = hlr.to_paper(kernel.shape_centre(vertex), frame, centre)
        out.append(((x * scale, y * scale), index))
    return out


def snap(shape, direction, up, point, centre=(0.0, 0.0), scale: float = 1.0,
         tolerance: float = 6.0):
    """The model vertex nearest a point on the paper, and a reference to it.

    Returns ``(point, ShapeRef)`` snapped to the vertex, or ``(point, None)``
    when nothing is near enough - an unanchored dimension is still a
    perfectly good dimension, it just will not follow the model.
    """
    best, best_index, best_distance = None, -1, tolerance
    for where, index in projected_vertices(shape, direction, up, centre,
                                           scale):
        distance = math.hypot(where[0] - point[0], where[1] - point[1])
        if distance < best_distance:
            best, best_index, best_distance = where, index, distance
    if best is None:
        return (list(point), None)
    pool = kernel.vertices(shape)
    return ([best[0], best[1]],
            ShapeRef.capture(pool[best_index], "vertex", best_index,
                             within=shape))


def _circle_of(edge, whole: bool = False):
    """A circular edge's centre and radius, or None for any other edge.

    ``whole`` asks for a full circle only: its centre is then also its
    middle, which is what a point tied to it is put back at.
    """
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.GeomAbs import GeomAbs_Circle
    from OCP.TopoDS import TopoDS

    try:
        curve = BRepAdaptor_Curve(TopoDS.Edge_s(edge))
        if curve.GetType() != GeomAbs_Circle:
            return None
        if whole and abs(curve.LastParameter() - curve.FirstParameter()
                         - 2.0 * math.pi) > 1e-6:
            return None
        circle = curve.Circle()
    except Exception:
        return None
    centre = circle.Location()
    return (centre.X(), centre.Y(), centre.Z()), circle.Radius()


def snap_circle(shape, direction, up, centre, radius, middle=(0.0, 0.0),
                scale: float = 1.0, tolerance: float = 0.05,
                whole: bool = False):
    """The model circle seen as this one on the paper, and a reference to it.

    A diameter tied to it follows the hole when the hole changes; one that
    finds nothing, a circle seen at a slant, is still a dimension, it only
    stays the size it was.  ``radius`` None takes any circle centred there,
    for a dimension measured from a hole's centre.
    """
    if shape is None:
        return None
    frame = hlr.camera(direction, up)
    for index, edge in enumerate(kernel.edges(shape)):
        found = _circle_of(edge, whole)
        if found is None:
            continue
        where, r = found
        x, y = hlr.to_paper(where, frame, middle)
        if (math.hypot(x * scale - centre[0], y * scale - centre[1])
                <= tolerance and (radius is None
                                  or abs(r * scale - radius) <= tolerance)):
            return ShapeRef.capture(edge, "edge", index, within=shape)
    return None


def centre_features(shape, direction, up, middle=(0.0, 0.0),
                    scale: float = 1.0, overhang: float = 2.0):
    """Inventor's Automated Centerlines for one view: a centre mark on
    every hole and round boss seen end on, and a centre line down every
    one seen from the side.

    Returns ``(marks, lines)``: marks as ((x, y), half length) on the
    view's paper, lines as two points on it, each run ``overhang``
    millimetres past what it marks, as a drawing has them.
    """
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_Cylinder
    from OCP.TopoDS import TopoDS

    if shape is None:
        return [], []
    d = _unit(direction)
    frame = hlr.camera(direction, up)
    marks, lines = [], []

    def paper(p):
        x, y = hlr.to_paper(p, frame, middle)
        return (x * scale, y * scale)

    for face in kernel.faces(shape):
        try:
            surface = BRepAdaptor_Surface(TopoDS.Face_s(face))
            if surface.GetType() != GeomAbs_Cylinder:
                continue
            cylinder = surface.Cylinder()
        except Exception:
            continue
        axis = cylinder.Axis()
        a = axis.Direction()
        a = (a.X(), a.Y(), a.Z())
        loc = axis.Location()
        loc = (loc.X(), loc.Y(), loc.Z())
        r = cylinder.Radius() * scale
        along = sum(a[i] * d[i] for i in range(3))
        if abs(along) > 0.999:
            centre = paper(loc)
            reach = r + overhang
            if not any(math.dist(centre, m[0]) < 1e-3
                       and abs(m[1] - reach) < 1e-3 for m in marks):
                # the biggest of several circles round one centre, a
                # counterbore's, is the one marked
                same = [m for m in marks if math.dist(centre, m[0]) < 1e-3]
                if same:
                    if reach > same[0][1]:
                        marks.remove(same[0])
                        marks.append((centre, reach))
                else:
                    marks.append((centre, reach))
        elif abs(along) < 1e-3:
            v0, v1 = surface.FirstVParameter(), surface.LastVParameter()
            p0 = [loc[i] + a[i] * v0 for i in range(3)]
            p1 = [loc[i] + a[i] * v1 for i in range(3)]
            s, e = paper(p0), paper(p1)
            length = math.dist(s, e)
            if length < 1e-6:
                continue
            ux, uy = (e[0] - s[0]) / length, (e[1] - s[1]) / length
            s = (s[0] - ux * overhang, s[1] - uy * overhang)
            e = (e[0] + ux * overhang, e[1] + uy * overhang)
            merged = False
            for i, (q0, q1) in enumerate(lines):
                # one line down a shaft of several diameters, not one each
                cross = abs((q0[0] - s[0]) * uy - (q0[1] - s[1]) * ux)
                lx, ly = q1[0] - q0[0], q1[1] - q0[1]
                parallel = abs(lx * uy - ly * ux) < 1e-6 * max(
                    1.0, math.hypot(lx, ly))
                if parallel and cross < 1e-3:
                    ts = sorted([(p[0] * ux + p[1] * uy, p)
                                 for p in (q0, q1, s, e)])
                    lines[i] = (ts[0][1], ts[-1][1])
                    merged = True
                    break
            if not merged:
                lines.append((s, e))
    return marks, lines


def _mm(value: float) -> str:
    text = ("%.2f" % value).rstrip("0").rstrip(".")
    return text or "0"


def hole_notes(shape, direction, up, middle=(0.0, 0.0), scale: float = 1.0,
               centres_out=None):
    """Inventor's Hole Notes for one view, read off the model: every hole
    seen end on, grouped by size, with its note.

    Returns ``[(text, (x, y) on the circle, count)]``. A hole is THRU when
    there is no material past either end of it, otherwise its depth is
    given; a wider, shallower hole round the same axis is its counterbore.
    """
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_Cylinder
    from OCP.TopoDS import TopoDS

    if shape is None:
        return []
    d = _unit(direction)
    frame = hlr.camera(direction, up)
    bores = []                  # (axis point, axis, radius, v0, v1)
    for face in kernel.faces(shape):
        try:
            surface = BRepAdaptor_Surface(TopoDS.Face_s(face))
            if surface.GetType() != GeomAbs_Cylinder:
                continue
            cylinder = surface.Cylinder()
        except Exception:
            continue
        axis = cylinder.Axis()
        a = axis.Direction()
        a = (a.X(), a.Y(), a.Z())
        if abs(sum(a[i] * d[i] for i in range(3))) < 0.999:
            continue
        loc = axis.Location()
        loc = (loc.X(), loc.Y(), loc.Z())
        v0, v1 = sorted((surface.FirstVParameter(), surface.LastVParameter()))
        mid = [loc[i] + a[i] * (v0 + v1) / 2 for i in range(3)]
        # a hole has nothing on its axis; a boss is solid there
        if kernel.point_inside(shape, mid):
            continue
        # the same bore met twice, split by a seam, counts once
        if any(abs(b[2] - cylinder.Radius()) < 1e-6
               and math.dist(b[0], loc) < 1e-6 and abs(b[3] - v0) < 1e-6
               for b in bores):
            continue
        bores.append((loc, a, cylinder.Radius(), v0, v1))

    def axis_key(b):
        x, y = hlr.to_paper(b[0], frame, middle)
        return (round(x, 4), round(y, 4))

    holes = {}
    for b in bores:
        holes.setdefault(axis_key(b), []).append(b)

    notes = {}
    for key, group in holes.items():
        group.sort(key=lambda b: b[2])
        hole = group[0]
        loc, a, r, v0, v1 = hole
        span = (min(b[3] for b in group), max(b[4] for b in group))
        step = 0.05
        past = [[loc[i] + a[i] * (span[0] - step) for i in range(3)],
                [loc[i] + a[i] * (span[1] + step) for i in range(3)]]
        through = not any(kernel.point_inside(shape, p) for p in past)
        text = "%s%s" % ("\u00d8", _mm(2 * r))
        text += " THRU" if through else " DEPTH %s" % _mm(v1 - v0)
        wider = [b for b in group[1:] if b[2] > r + 1e-6]
        if wider:
            bore = wider[-1]
            text += "  CBORE %s%s DEPTH %s" % ("\u00d8", _mm(2 * bore[2]),
                                               _mm(bore[4] - bore[3]))
        centre = hlr.to_paper(loc, frame, middle)
        widest = max(b[2] for b in group)
        at = (centre[0] * scale + widest * scale * 0.7071,
              centre[1] * scale + widest * scale * 0.7071)
        spot = (centre[0] * scale, centre[1] * scale)
        if text in notes:
            notes[text][2] += 1
            notes[text][3].append(spot)
        else:
            notes[text] = [text, at, 1, [spot]]
    if centres_out is not None:
        for text, _at, n, spots in notes.values():
            label = ("%dx " % n if n > 1 else "") + text
            centres_out.extend((spot, label) for spot in spots)
    return [(("%dx " % n if n > 1 else "") + text, at, n)
            for text, at, n, _spots in notes.values()]


def hole_note_at(shape, direction, up, middle, scale, point,
                 tolerance: float = 0.05) -> str:
    """Inventor's Hole and Thread note for the hole whose centre is at
    ``point`` on the view, counted with the holes the same: ``4x Ø8
    THRU``. Empty when no hole is seen end on there."""
    centres = []
    hole_notes(shape, direction, up, middle, scale, centres_out=centres)
    for spot, label in centres:
        if math.dist(spot, point) <= tolerance:
            return label
    return ""


# ---------------------------------------------------------------- cutting


def half_space(shape: TopoDS_Shape, point: Sequence[float],
               normal: Sequence[float]) -> Optional[TopoDS_Shape]:
    """The part of ``shape`` behind the plane through ``point``.

    Built as an oversized box placed on the far side, because a bounded
    solid is what booleans are reliable with.
    """
    try:
        box = kernel.bounding_box(shape)
    except Exception:
        return None
    span = max(box[3] - box[0], box[4] - box[1], box[5] - box[2], 1.0)
    reach = span * 3.0
    n = _unit(normal)

    # a frame on the plane: n is its Z, so the box can be built in local
    # coordinates and moved in one go
    from OCP.gp import gp_Ax2, gp_Ax3, gp_Dir, gp_Pnt, gp_Trsf
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
    origin = gp_Pnt(float(point[0]), float(point[1]), float(point[2]))
    try:
        frame = gp_Ax2(origin, gp_Dir(*n))
    except Exception:
        return None
    local = BRepPrimAPI_MakeBox(
        gp_Pnt(-reach, -reach, -reach), 2 * reach, 2 * reach, reach).Shape()
    trsf = gp_Trsf()
    trsf.SetTransformation(gp_Ax3(frame), gp_Ax3())
    placed = BRepBuilderAPI_Transform(local, trsf, True).Shape()

    try:
        common = BRepAlgoAPI_Common(shape, placed)
        common.Build()
        if common.IsDone() and not common.Shape().IsNull():
            return common.Shape()
    except Exception:
        return None
    return None


# --------------------------------------------------------------- generating


class Generator:
    """Fills in every view's projection, reusing what it can."""

    def __init__(self, library: Optional[PartLibrary] = None) -> None:
        self.library = library or PartLibrary()
        # plain views drawn now are drafts (hlr.project fast), marked so
        # with view.draft for the real lines to replace them after
        self.draft = False

    def rebuild(self, doc: DrawingDocument, base_dir: Optional[str] = None,
                force: bool = False, draft: bool = False,
                handed: Optional[Dict] = None) -> DrawingReport:
        """Fill in what needs drawing.  ``draft`` draws plain views rough
        and quick; ``handed`` are projections already asked of the
        workers (exact_jobs), keyed as _hand_out keys them."""
        started = time.perf_counter()
        report = DrawingReport()
        base = base_dir if base_dir is not None else doc.base_dir

        models: Dict[int, Tuple[Optional[TopoDS_Shape], object, str]] = {}
        self.draft = draft
        try:
            self._pending = (dict(handed) if handed is not None
                             else self._hand_out(doc, base, force))
            for sheet in doc.sheets:
                # parents first, so a child can read what its parent
                # resolved to
                for view in self._in_order(sheet):
                    had = view.projection
                    self._one(doc, sheet, view, base, models, report, force)
                    if view.projection is not None and (
                            view.projection is not had
                            or getattr(view, "drawn_as", None) is None):
                        view.drawn_as = self._drawn_direction(doc, sheet,
                                                              view)
                    if view.projection is not had:
                        view.draft = getattr(view, "_drew_fast", False)
                    view._drew_fast = False
                self._reanchor(doc, sheet, models, report)
                self._recount(doc, sheet, base, models, report)
        finally:
            self.draft = False
            self._pending = {}
        report.duration = time.perf_counter() - started
        report.ok = not report.missing and not report.errors
        doc.last_report = report
        return report

    def forget_models(self, doc: DrawingDocument,
                      base_dir: Optional[str] = None) -> None:
        """Load every model again, here and in the workers, the next
        time a view asks.  For Update: a part placed in an assembly can
        change while the assembly's own file does not, and the bodies
        are kept by that file."""
        base = base_dir if base_dir is not None else doc.base_dir
        held = getattr(self, "_signatures", None)
        if held is None:
            held = self._signatures = {}
        changed = False
        for path in self._model_paths(doc, base):
            now = self._signature(path)
            key = os.path.normcase(os.path.abspath(path))
            if held.get(key) != now:
                held[key] = now
                changed = True
        if not changed and held:
            # nothing it is made of has moved: the bodies and the lines
            # worked out from them are still the truth
            return
        self.library.forget()
        self._warmed = {}
        self.warm(doc, base_dir, fresh=True)

    def _model_paths(self, doc: DrawingDocument, base: str) -> List[str]:
        out = []
        for sheet in doc.sheets:
            for view in sheet.views:
                if view.kind != BASE or not view.ref.path:
                    continue
                path = view.ref.resolve(base) if base else None
                if path and os.path.exists(path) and path not in out:
                    out.append(path)
        return out

    def _signature(self, path: str) -> Tuple:
        """What a model is made of as it stands: every file in it with
        its time, and any of them open in a tab with the body the tab
        has published."""
        files = [path]
        try:
            if fileformat.is_assembly(path):
                from .parts import leaf_parts
                files += leaf_parts(path)
                files += _subassemblies(path)
        except Exception:
            pass
        provider = getattr(self.library, "provider", None)
        out = []
        for name in sorted(set(os.path.normcase(os.path.abspath(f))
                               for f in files)):
            try:
                stamp = os.path.getmtime(name)
            except OSError:
                stamp = None
            live = 0
            if provider is not None:
                try:
                    shape = provider(name)
                    live = id(shape) if shape is not None else 0
                except Exception:
                    live = 0
            out.append((name, stamp, live))
        return tuple(out)

    def warm(self, doc: DrawingDocument,
             base_dir: Optional[str] = None, fresh: bool = False) -> int:
        """Have every worker load the models this drawing is drawn from,
        once per model as it is on disk, so the next view placed or
        updated does not start by loading them.  How many were sent."""
        from . import rules, workers

        helpers = workers.pool()
        if helpers is None:
            return 0
        base = base_dir if base_dir is not None else doc.base_dir
        sent = getattr(self, "_warmed", None)
        if sent is None:
            sent = self._warmed = {}
        count = 0
        trusted = None
        for sheet in doc.sheets:
            for view in sheet.views:
                if view.kind != BASE or not view.ref.path:
                    continue
                path = view.ref.resolve(base) if base else None
                if not path or not os.path.exists(path):
                    continue
                key = os.path.normcase(os.path.abspath(path))
                try:
                    stamp = os.path.getmtime(path)
                except OSError:
                    continue
                if sent.get(key) == stamp:
                    continue
                sent[key] = stamp
                if trusted is None:
                    trusted = sorted(rules.trusted_paths())
                helpers.broadcast("hold", path=os.path.abspath(path),
                                  trusted=trusted, fresh=fresh)
                count += 1
        return count

    def exact_jobs(self, doc: DrawingDocument,
                   base_dir: Optional[str] = None) -> Dict:
        """The real lines of every draft view, asked of the workers; the
        futures, keyed for rebuild(handed=...).  Empty without workers."""
        base = base_dir if base_dir is not None else doc.base_dir
        return self._hand_out(doc, base, False, drafts=True)

    # -- after a view is moved --------------------------------------------

    def _drawn_direction(self, doc: DrawingDocument, sheet: Sheet,
                         view: View):
        """Which way a view looks, to remember it was drawn that way."""
        if view.kind in (SECTION, DETAIL):
            return None
        try:
            return self._plain_direction(doc, sheet, view)
        except Exception:
            return None

    def turned(self, doc: DrawingDocument, sheet: Sheet) -> List[View]:
        """The views that now look a different way from how they are drawn.

        A projected view looks whichever way it sits from its parent, so
        dragging one across to the other side turns it.  Nearly every move
        turns nothing: a view slid along its line, or a parent dragged with
        its projections, looks the way it did, and has nothing to redraw.
        Whatever comes from a turned view turns with it.
        """
        out: List[View] = []
        for view in self._in_order(sheet):
            if view.parent and any(v.id == view.parent for v in out):
                out.append(view)
                continue
            drawn = getattr(view, "drawn_as", None)
            if view.kind != PROJECTED or view.projection is None                     or drawn is None:
                continue
            now = self._drawn_direction(doc, sheet, view)
            if now is None:
                continue
            if any(abs(a - b) > 1e-9 for pair in zip(now, drawn)
                   for a, b in zip(pair[0], pair[1])):
                out.append(view)
        return out

    def redraw(self, doc: DrawingDocument, sheet: Sheet,
               views: Sequence[View],
               base_dir: Optional[str] = None) -> DrawingReport:
        """Draw these views again, and only these."""
        report = DrawingReport()
        base = base_dir if base_dir is not None else doc.base_dir
        wanted = {id(v) for v in views}
        models: Dict[int, Tuple[Optional[TopoDS_Shape], object, str]] = {}
        for view in self._in_order(sheet):
            if id(view) not in wanted:
                continue
            self._one(doc, sheet, view, base, models, report, True)
            if view.projection is not None:
                view.drawn_as = self._drawn_direction(doc, sheet, view)
        report.ok = not report.missing and not report.errors
        return report

    def _reanchor(self, doc: DrawingDocument, sheet: Sheet, models: Dict,
                  report: DrawingReport) -> None:
        """Put every anchored dimension back where its geometry now is.

        A dimension that was snapped to model vertices is a statement about
        the part, not about the paper: make the part longer and the
        dimension should grow with it and go on reading the truth.  One that
        can no longer find what it was attached to is marked sick and left
        on the sheet, because silently deleting somebody's dimension is a
        far worse answer than showing it in red.
        """
        for note in sheet.annotations:
            if not note.anchored:
                continue
            view = sheet.view(note.view)
            if view is None:
                note.sick = True
                continue
            origin = doc.view_model(sheet, view)
            entry = models.get(origin.id) if origin is not None else None
            if entry is None or entry[0] is None or view.projection is None:
                # nothing was reloaded this pass, so there is nothing new to
                # say; leave the dimension exactly as it was
                continue

            shape = entry[0]
            scale = doc.view_scale(sheet, view)
            frame = hlr.camera(*self._resolved_orientation(doc, sheet, view))
            middle = view.projection.centre

            first = note.anchors[0] if note.anchors else None
            if note.kind in (drawing.RADIUS, drawing.DIAMETER) \
                    and first is not None and first.kind == "edge":
                # a circle's centre and size, read off the model again;
                # the label stays the same way round from it
                found = first.rebind(shape)
                circle = _circle_of(found) if found is not None else None
                if circle is None or not first.resolved:
                    if not note.sick:
                        report.errors.append(
                            "%s: the circle it measured is gone"
                            % (note.text or note.kind))
                    note.sick = True
                    continue
                where, r = circle
                cx, cy = hlr.to_paper(where, frame, middle)
                cx, cy, r = cx * scale, cy * scale, r * scale
                old = note.points
                dx, dy = ((old[1][0] - old[0][0], old[1][1] - old[0][1])
                          if len(old) >= 2 else (1.0, 0.0))
                length = math.hypot(dx, dy) or 1.0
                note.points = [[cx, cy], [cx + dx / length * r,
                                          cy + dy / length * r]]
                note.sick = False
                continue

            moved, lost = [], False
            for index, ref in enumerate(note.anchors):
                if ref is None:
                    moved.append(note.points[index]
                                 if index < len(note.points) else [0.0, 0.0])
                    continue
                found = ref.rebind(shape)
                if found is None or not ref.resolved:
                    lost = True
                    break
                x, y = hlr.to_paper(kernel.shape_centre(found), frame, middle)
                moved.append([x * scale, y * scale])

            if lost:
                if not note.sick:
                    report.errors.append(
                        "%s: what it measured is no longer on the model"
                        % (note.text or note.kind))
                note.sick = True
                continue
            note.sick = False
            note.points = moved

    def _recount(self, doc: DrawingDocument, sheet: Sheet, base: str,
                 models: Dict, report: DrawingReport) -> None:
        """Read the assembly again, so a parts list is never out of date.

        The rows are not stored in the file as truth, only as the last thing
        seen: the assembly is what a parts list is about, and if somebody
        adds a bracket upstairs the list should say so without being asked.
        A drawing opened away from its models keeps the old rows, which is
        the whole reason they are written out at all.
        """
        for table in sheet.parts_lists:
            view = sheet.view(table.view) or sheet.base_view()
            if view is None:
                table.error = "it has no view to list"
                continue
            if table.kind == "holes":
                self._hole_rows(doc, sheet, view, table, base, models)
                continue
            origin = doc.view_model(sheet, view)
            entry = models.get(origin.id) if origin is not None else None
            if entry is None and not table.rows:
                # nothing was reloaded this pass and the table has never
                # been filled, so go and get the model just for it
                entry = self._load_for(doc, origin, base)
            if entry is None or entry[1] is None:
                if not table.rows:
                    table.error = "its model is not loaded"
                continue
            folder = os.path.dirname(os.path.abspath(entry[2]))
            try:
                table.rows = bom.rows_for(entry[1], folder, self.library,
                                          table.recurse)
                table.error = ""
            except Exception as exc:
                table.error = str(exc)
                report.errors.append("parts list: %s" % exc)

        # Write each balloon's number onto the balloon.  The sheet asks the
        # parts list every time it is painted, but the tree and anything
        # else holding only the annotation cannot, and a balloon that reads
        # one number on the paper and another in the browser is worse than
        # useless.
        for note in sheet.annotations:
            if note.kind == drawing.BALLOON and note.component:
                found = doc.balloon_number(sheet, note)
                note.sick = found == 0
                note.item = found

    def _hole_rows(self, doc: DrawingDocument, sheet: Sheet, view: View,
                   table, base: str, models: Dict) -> None:
        """Inventor's Hole Table: every hole the view sees end on, a tag
        each, A1, A2 for the first size, B1 for the next, with where it
        is from the table's datum in model millimetres and its note."""
        origin = doc.view_model(sheet, view)
        entry = models.get(origin.id) if origin is not None else None
        if entry is None:
            if table.rows:
                return              # nothing reloaded: the rows stand
            entry = self._load_for(doc, origin, base)
        if entry is None or entry[0] is None or view.projection is None:
            if not table.rows:
                table.error = "its model is not loaded"
            return
        try:
            direction, up = self._resolved_orientation(doc, sheet, view)
        except Exception:
            return
        scale = doc.view_scale(sheet, view) or 1.0
        spots: List = []
        hole_notes(entry[0], direction, up, view.projection.centre, scale,
                   centres_out=spots)
        groups: Dict[str, List] = {}
        for spot, label in spots:
            words = label.split("x ", 1)[1] if "x " in label.split(
                "Ø")[0] else label
            groups.setdefault(words, []).append(spot)
        dx, dy = table.datum[0], table.datum[1]
        rows = []
        for letter, (words, places) in zip(
                "ABCDEFGHJKLMNPRSTUVWXYZ", groups.items()):
            places.sort(key=lambda p: (-round(p[1], 3), round(p[0], 3)))
            try:
                # the hole's size on the paper, for its tag to stand clear
                size = float(words.split("Ø", 1)[1].split()[0])
            except (IndexError, ValueError):
                size = 0.0
            for number, (x, y) in enumerate(places, 1):
                rows.append(bom.Row(
                    item=len(rows) + 1, quantity=1,
                    extra={"HOLE": "%s%d" % (letter, number),
                           "XDIM": _mm((x - dx) / scale + 0.0),
                           "YDIM": _mm((y - dy) / scale + 0.0),
                           "DESCRIPTION": words,
                           "_x": "%.6f" % x, "_y": "%.6f" % y,
                           "_r": "%.6f" % (size / 2.0 * scale)}))
        table.rows = rows
        table.error = "" if rows else "no hole is seen end on in %s"             % view.label

    def _load_for(self, doc: DrawingDocument, origin: Optional[View],
                  base: str):
        """The (shape, document, path) behind a base view, loaded on demand."""
        if origin is None or not origin.ref.path:
            return None
        path = origin.ref.resolve(base) if base else None
        if path is None or not os.path.exists(path):
            return None
        try:
            return load_model(path, self.library) + (path,)
        except Exception:
            return None

    def balloon_targets(self, doc: DrawingDocument, sheet: Sheet, view: View,
                        base_dir: Optional[str] = None
                        ) -> List[Tuple[str, Tuple[float, float], List]]:
        """Where each component of a view's assembly sits on the paper.

        Gives back one (file, middle, corners) triple per placed component.
        The middle is a fallback; the corners are that component's own
        vertices projected onto the paper, and a balloon should land on
        whichever of them is nearest the bubble.  A leader that points at
        the middle of a part is pointing at a spot buried inside the
        assembly, which on an isometric means the arrow crosses everything
        else to get there.
        """
        origin = doc.view_model(sheet, view)
        if origin is None or not origin.ref.path:
            return []
        folder = base_dir if base_dir is not None else doc.base_dir
        path = origin.ref.resolve(folder) if folder else None
        if path is None or not os.path.exists(path):
            return []
        try:
            from .assembly import AssemblyDocument

            if fileformat.peek(path).type != fileformat.ASSEMBLY:
                return []
            document = AssemblyDocument.load(path)
            document.library = self.library
            document.rebuild()
        except Exception:
            return []
        occurrences = getattr(document, "occurrences", None)
        if not occurrences:
            return []

        scale = doc.view_scale(sheet, view)
        middle = view.projection.centre if view.projection else (0.0, 0.0)
        frame = hlr.camera(*self._resolved_orientation(doc, sheet, view))
        inner = os.path.dirname(os.path.abspath(path))

        out: List[Tuple[str, Tuple[float, float]]] = []
        seen = set()
        for occurrence in occurrences:
            if occurrence.suppressed or not occurrence.visible:
                continue
            placed = occurrence.placed()
            if placed is None:
                continue
            key = bom.key_for(occurrence.ref.resolve(inner) or "")
            if key in seen:
                continue           # one balloon per part, not per instance
            seen.add(key)
            try:
                centre = kernel.shape_centre(placed)
            except Exception:
                continue
            x, y = hlr.to_paper(centre, frame, middle)
            corners = []
            try:
                for vertex in kernel.vertices(placed):
                    vx, vy = hlr.to_paper(kernel.shape_centre(vertex), frame,
                                          middle)
                    corners.append((vx * scale, vy * scale))
            except Exception:
                corners = []
            out.append((occurrence.ref.resolve(inner) or occurrence.ref.path,
                        (x * scale, y * scale), corners))
        return out
    def model_of(self, doc: DrawingDocument, sheet: Sheet, view: View,
                 base_dir: Optional[str] = None):
        """The body a view is drawn from, for snapping and measuring."""
        origin = doc.view_model(sheet, view)
        if origin is None or not origin.ref.path:
            return None
        base = base_dir if base_dir is not None else doc.base_dir
        path = origin.ref.resolve(base) if base else None
        if path is None or not os.path.exists(path):
            return None
        try:
            return self.library.shape(path)
        except Exception:
            return None

    @staticmethod
    def _in_order(sheet: Sheet) -> List[View]:
        """Views with every parent ahead of its children."""
        done: List[View] = []
        placed = set()
        remaining = list(sheet.views)
        while remaining:
            progressed = False
            for view in list(remaining):
                if view.parent and view.parent not in placed:
                    continue
                done.append(view)
                placed.add(view.id)
                remaining.remove(view)
                progressed = True
            if not progressed:          # a cycle; take what is left as it is
                done.extend(remaining)
                break
        return done

    def _one(self, doc: DrawingDocument, sheet: Sheet, view: View,
             base: str, models: Dict, report: DrawingReport,
             force: bool) -> None:
        view.error = ""
        view.stale = False

        origin = doc.view_model(sheet, view)
        if origin is None or not origin.ref.path:
            view.error = "no model"
            report.errors.append("%s has no model" % view.label)
            return

        path = origin.ref.resolve(base) if base else (
            origin.ref.path if os.path.isabs(origin.ref.path) else None)
        if path is None or not os.path.exists(path):
            view.error = "cannot find %s" % (origin.ref.name
                                             or origin.ref.path)
            report.missing.append(view.label)
            return

        # has the model changed since this view was generated?
        stamp = drawing.file_hash(path)
        key = os.path.normcase(os.path.abspath(path))
        known = doc.hashes.get(key)
        changed = known is not None and known != stamp

        if view.projection is not None and not force and not changed:
            report.cached += 1
            return
        if changed and not force:
            view.stale = True
            report.stale.append(view.label)
            if view.projection is not None:
                return

        if origin.id not in models:
            models[origin.id] = load_model(path, self.library) + (path,)
            # what it was made of when loaded, for Update to compare with
            held = getattr(self, "_signatures", None)
            if held is None:
                held = self._signatures = {}
            mark = os.path.normcase(os.path.abspath(path))
            if mark not in held:
                try:
                    held[mark] = self._signature(path)
                except Exception:
                    pass
        shape, document, _p = models[origin.id]
        if shape is None:
            view.error = "%s has no body to draw" % os.path.basename(path)
            report.errors.append(view.error)
            return
        self._shape_now = shape
        self._path_now = os.path.normcase(os.path.abspath(path))

        try:
            if view.flat and view.kind == BASE:
                projection = self._flat(doc, sheet, view, document)
            else:
                projection = self._project(doc, sheet, view, shape)
        except Exception as exc:
            view.error = str(exc)
            report.errors.append("%s: %s" % (view.label, exc))
            return

        if not projection.ok:
            view.error = projection.error
            report.errors.append("%s: %s" % (view.label, projection.error))
            return

        self._add_threads(doc, sheet, view, document, projection)
        if len(view.crop) >= 4:
            cropped = cropped_projection(projection, view.crop)
            if cropped is None:
                view.error = "nothing of it is inside the crop"
                report.errors.append("%s: %s" % (view.label, view.error))
                return
            projection = cropped
        if projection.of_kind(hlr.CUT):
            projection.hatch = view.hatch_pattern or drawing.hatch_for_material(
                getattr(document, "material", "")) or "steel"
        view.projection = projection
        doc.hashes[key] = stamp
        report.generated += 1

    def _add_threads(self, doc: DrawingDocument, sheet: Sheet, view: View,
                     document, projection: hlr.Projection) -> None:
        """A part's cosmetic threads, drawn on its plain views as ISO
        6410 has them.  Not on an assembly's views, where another part
        may stand in front of them, nor on sections and details: a detail
        takes them from its parent with the rest of its lines."""
        if view.kind in (SECTION, DETAIL) or view.flat or view.breakout:
            return
        if document is None or getattr(document, "occurrences", None)                 is not None:
            return
        from . import threads
        try:
            marks = threads.marks_of(document)
        except Exception:
            marks = []
        if not marks:
            return
        try:
            direction, up = self._plain_direction(doc, sheet, view)
        except Exception:
            return
        scale = doc.view_scale(sheet, view) or 1.0
        hidden = doc.view_display(sheet, view) == WITH_HIDDEN
        lines = hlr.thread_lines(marks, direction, up, projection.centre,
                                 hidden=hidden)
        for line in lines:
            line.points = [(x * scale, y * scale) for x, y in line.points]
        projection.lines.extend(lines)

    @staticmethod
    def _tangents(doc: DrawingDocument, sheet: Sheet, view: View) -> bool:
        """Tangent edges as the base view a view comes from says."""
        base = doc.view_model(sheet, view)
        return getattr(base if base is not None else view, "tangents", True)

    def _flat(self, doc: DrawingDocument, sheet: Sheet, view: View,
              document) -> hlr.Projection:
        """A sheet metal part laid flat, seen from above, with its bend
        centre lines, as Inventor's flat pattern view is drawn."""
        from . import sheetmetal
        if document is None or getattr(document, "sheet_metal", None) is None:
            raise ValueError("the part is not sheet metal, so it has no "
                             "flat pattern")
        if getattr(document, "shape", None) is None:
            document.rebuild()
        flat = sheetmetal.flat_pattern(document)
        body = flat.solid if flat.solid is not None else flat.outline()
        direction, up = (0.0, 0.0, -1.0), (0.0, 1.0, 0.0)
        projection = hlr.project(body, direction, up, hidden=False)
        if not projection.ok:
            return projection
        frame = hlr.camera(direction, up)
        top = max((p[2] for p in [kernel.bounding_box(body)[3:]]),
                  default=0.0)
        for a, b, _angle in flat.bends:
            projection.lines.append(hlr.Polyline(
                [hlr.to_paper((a[0], a[1], top), frame, projection.centre),
                 hlr.to_paper((b[0], b[1], top), frame, projection.centre)],
                hlr.BEND))
        return _scaled(projection, doc.view_scale(sheet, view))

    def _hand_out(self, doc: DrawingDocument, base: str,
                  force: bool, drafts: bool = False) -> Dict:
        """Send every plain view that needs drawing to the workers at once.

        Hidden line removal is the slow part of a drawing, a third of a
        second a view on the excavator, and every plain view of a sheet is
        independent of the others: each is the model seen from one way.
        So they are all worked out together, one per worker, while the
        sheet is put together here. Sections and details depend on the
        view they are cut from, so they stay here, after.
        """
        from . import rules, workers

        if self.draft and not drafts:
            # drafts are drawn here: quick enough, and only for a big model
            return {}
        helpers = workers.pool()
        if helpers is None:
            return {}
        jobs = []
        for sheet in doc.sheets:
            for view in self._in_order(sheet):
                if view.kind in (SECTION, DETAIL) or view.flat:
                    continue
                if drafts:
                    if not getattr(view, "draft", False):
                        continue
                elif view.projection is not None and not force:
                    continue
                origin = doc.view_model(sheet, view)
                if origin is None or not origin.ref.path:
                    continue
                path = origin.ref.resolve(base) if base else (
                    origin.ref.path if os.path.isabs(origin.ref.path)
                    else None)
                if not path or not os.path.exists(path):
                    continue
                # A model open in a tab is drawn here, from the part as it
                # is in the tab: a worker reads the file, which does not
                # have what was changed since it was saved, and Update
                # showed the old part while opening the view showed the new
                if self._live_inside(path):
                    continue
                try:
                    direction, up = self._plain_direction(doc, sheet, view)
                except Exception:
                    continue
                held = self.library.peek(path)
                hidden = doc.view_display(sheet, view) == WITH_HIDDEN
                tangents = self._tangents(doc, sheet, view)
                if held is not None and self._known(projcache.plain_key(
                        id(held), direction, up, hidden, tangents)):
                    continue        # already worked out once
                if self._will_mend(path, direction, up, hidden, tangents):
                    continue        # drawn here, only where it changed
                jobs.append(((id(sheet), view.id), {
                    "path": os.path.abspath(path),
                    "direction": list(direction), "up": list(up),
                    "hidden": doc.view_display(sheet, view) == WITH_HIDDEN,
                    "tangents": self._tangents(doc, sheet, view)}))
        # one view is quicker drawn here than posted anywhere, and workers
        # not yet running cost more to start than a few views take; the
        # real lines behind a draft always go, the window is not waiting
        if not drafts and (len(jobs) < 2
                           or (helpers.running == 0 and len(jobs) < 4)):
            return {}
        trusted = sorted(rules.trusted_paths())
        return {key: helpers.submit("project", trusted=trusted, **args)
                for key, args in jobs}

    def _live_inside(self, path: str) -> bool:
        """Whether the model, or any part it places, is open in a tab:
        drawn here then, from the part as the tab has it, for a worker
        reads the file, which has not got the edit."""
        provider = getattr(self.library, "provider", None)
        if provider is None:
            return False
        try:
            if provider(path) is not None:
                return True
            if not fileformat.is_assembly(path):
                return False
            from .parts import leaf_parts
            return any(provider(leaf) is not None
                       for leaf in leaf_parts(path))
        except Exception:
            return False

    def _plain_direction(self, doc: DrawingDocument, sheet: Sheet,
                         view: View):
        """Which way a view that is not a section or a detail looks."""
        if view.kind == BASE:
            return orientation_of(view)
        if view.kind == PROJECTED:
            parent = sheet.view(view.parent)
            if parent is None:
                raise ValueError("its parent view is gone")
            pd, pu = self._resolved_orientation(doc, sheet, parent)
            dx, dy = view.x - parent.x, view.y - parent.y
            if abs(dx) > 1e-6 and abs(dy) > 1e-6:
                return iso_orientation(pd, pu, dx, dy)
            return projected_orientation(pd, pu, dx, dy, doc.angle)
        if view.kind == AUXILIARY:
            parent = sheet.view(view.parent)
            if parent is None:
                raise ValueError("its parent view is gone")
            pd, pu = self._resolved_orientation(doc, sheet, parent)
            return auxiliary_orientation(pd, pu, view.radius)
        return orientation_of(view)

    def _will_mend(self, path, direction, up, hidden, tangents) -> bool:
        """Whether a view handed out would be better mended here: it was
        drawn before and little of its model has changed."""
        held = getattr(self, "_previous", {}) or {}
        probe = projcache.plain_key(0, direction, up, hidden, tangents)
        before = held.get((os.path.normcase(os.path.abspath(path)),)
                          + tuple(probe[2:6]))
        if before is None:
            return False
        try:
            shape = self.library.shape(path)
        except Exception:
            return False
        if shape is None or shape is before:
            return False
        if not projcache.shared().has((probe[0], id(before))
                                      + tuple(probe[2:])):
            return False
        try:
            return partial.plan(before, shape, direction, up) is not None
        except Exception:
            return False

    def _view_key(self, key) -> Tuple:
        """A plain view's key without the body: which model, seen how."""
        return (getattr(self, "_path_now", ""),) + tuple(key[2:6])

    def _remember(self, key, shape) -> None:
        """The body this view of this model was last drawn exactly from,
        for the next change to be drawn against."""
        held = getattr(self, "_previous", None)
        if held is None:
            held = self._previous = {}
        held[self._view_key(key)] = shape

    def _mended(self, key, shape, direction, up):
        """The view drawn again only round what changed since it was
        last drawn exactly (see partial), or None to draw it whole."""
        held = getattr(self, "_previous", {}) or {}
        before = held.get(self._view_key(key))
        if before is None or before is shape:
            return None
        cache = projcache.shared()
        old_key = (key[0], id(before)) + tuple(key[2:])
        old = cache.get(old_key, 1.0)
        if old is None:
            return None
        try:
            plan = partial.plan(before, shape, direction, up)
            if plan is None:
                return None
            region, involved = plan
            if region is None:
                mended = old            # nothing in it changed
            else:
                mended = partial.redraw(old, shape, region, involved,
                                        direction, up, key[4], key[5])
        except Exception:
            return None
        if mended is None:
            return None
        cache.put(key, mended, keep=shape)
        self._remember(key, shape)
        # a copy to hand out, the kept one stays as it is
        return cache.get(key, 1.0)

    @staticmethod
    def _known(key) -> bool:
        """Whether _kept would find the exact lines, without copying them."""
        cache = projcache.shared()
        if cache.has(key):
            return True
        return not key[4] and cache.has(key[:4] + (True,) + key[5:])

    @staticmethod
    def _kept(key, scale: float, allow_fast: bool = False):
        """(projection, is a draft) from the cache, or None.  The exact
        lines are best; with hidden lines off, the exact lines with them
        are as good; a draft does only when a draft was asked for."""
        cache = projcache.shared()
        found = cache.get(key, scale)
        if found is not None:
            return found, False
        hidden = key[4]
        if not hidden:
            withhidden = key[:4] + (True,) + key[5:]
            found = cache.get_without(withhidden, (hlr.HIDDEN,), scale)
            if found is not None:
                return found, False
        if allow_fast:
            draft = key[:-1] + (True,)
            found = cache.get(draft, scale)
            if found is not None:
                return found, True
        return None

    def _project(self, doc: DrawingDocument, sheet: Sheet, view: View,
                 shape: TopoDS_Shape) -> hlr.Projection:
        show_hidden = doc.view_display(sheet, view) == WITH_HIDDEN
        scale = doc.view_scale(sheet, view)

        plain = view.kind not in (SECTION, DETAIL) and not view.breakout
        key = None
        if plain:
            try:
                direction, up = self._plain_direction(doc, sheet, view)
                key = projcache.plain_key(
                    id(shape), direction, up, show_hidden,
                    self._tangents(doc, sheet, view))
            except Exception:
                key = None
        if key is not None:
            kept = self._kept(key, scale, allow_fast=self.draft)
            if kept is not None:
                # nothing to wait for: drop what was asked of a worker
                getattr(self, "_pending", {}).pop((id(sheet), view.id),
                                                  None)
                view._drew_fast = kept[1]
                return kept[0]
            # the model changed a little since this view was last seen:
            # drawn again only where it changed
            mended = self._mended(key, shape, direction, up)
            if mended is not None:
                getattr(self, "_pending", {}).pop((id(sheet), view.id),
                                                  None)
                view._drew_fast = False
                return _scaled(mended, scale)
        if plain:
            handed = getattr(self, "_pending", {}).pop(
                (id(sheet), view.id), None)
            if handed is not None:
                try:
                    lines = hlr.Projection.from_dict(
                        handed.result(timeout=600))
                    if key is not None:
                        projcache.shared().put(key, lines, keep=shape)
                        self._remember(key, shape)
                    return _scaled(lines, scale)
                except Exception:
                    pass        # drawn here instead, as it always was

        if view.kind == BASE:
            direction, up = orientation_of(view)
        elif view.kind == PROJECTED:
            parent = sheet.view(view.parent)
            if parent is None:
                raise ValueError("its parent view is gone")
            pd, pu = self._resolved_orientation(doc, sheet, parent)
            dx, dy = view.x - parent.x, view.y - parent.y
            if abs(dx) > 1e-6 and abs(dy) > 1e-6:
                direction, up = iso_orientation(pd, pu, dx, dy)
            else:
                direction, up = projected_orientation(pd, pu, dx, dy,
                                                      doc.angle)
        elif view.kind == AUXILIARY:
            parent = sheet.view(view.parent)
            if parent is None:
                raise ValueError("its parent view is gone")
            pd, pu = self._resolved_orientation(doc, sheet, parent)
            angle = view.radius       # reused: the edge angle, in degrees
            direction, up = auxiliary_orientation(pd, pu, angle)
        elif view.kind == SECTION:
            parent = sheet.view(view.parent)
            if parent is None:
                raise ValueError("its parent view is gone")
            return self._section(doc, sheet, view, parent, shape, show_hidden,
                                 scale)
        elif view.kind == DETAIL:
            parent = sheet.view(view.parent)
            if parent is None:
                raise ValueError("its parent view is gone")
            return self._detail(doc, sheet, view, parent, scale)
        else:
            direction, up = orientation_of(view)

        fast = (self.draft and not view.breakout and not view.flat
                and _big(shape))
        view._drew_fast = fast
        if fast:
            projection = hlr.outlines(shape, direction, up)
            if not projection.ok:
                fast = False
                view._drew_fast = False
        if not fast:
            projection = hlr.project(shape, direction, up,
                                     hidden=show_hidden,
                                     tangents=self._tangents(doc, sheet,
                                                             view))
        if key is not None and projection.ok:
            projcache.shared().put(key[:-1] + (fast,), projection,
                                   keep=shape)
            if not fast:
                self._remember(key, shape)
        if len(view.breakout) >= 3 and projection.ok:
            opened = self._break_out(doc, sheet, view, shape, direction, up,
                                     show_hidden, scale, projection)
            if opened is not None:
                projection = opened
        return _scaled(projection, scale)

    def _break_out(self, doc, sheet, view, shape, direction, up,
                   show_hidden: bool, scale: float, whole):
        """Inventor's Break Out: the material inside an outline drawn on
        the view taken away, from the front of the part to a depth, and
        the view drawn again with what that lays bare hatched.  Kept
        centred where the whole view was, so nothing on it moves."""
        from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
        from OCP.BRepBuilderAPI import (BRepBuilderAPI_MakeFace,
                                        BRepBuilderAPI_MakePolygon)
        from OCP.BRepPrimAPI import BRepPrimAPI_MakePrism
        from OCP.gp import gp_Pnt, gp_Vec

        frame = hlr.camera(direction, up)
        xd, yd, zd = frame.XDirection(), frame.YDirection(), frame.Direction()
        xd = (xd.X(), xd.Y(), xd.Z())
        yd = (yd.X(), yd.Y(), yd.Z())
        out = (zd.X(), zd.Y(), zd.Z())          # towards the viewer
        cx, cy = whole.centre
        try:
            front = max(sum(kernel.shape_centre(v)[i] * out[i]
                            for i in range(3))
                        for v in kernel.vertices(shape))
        except Exception:
            return None
        depth = max(0.01, view.breakout_depth)
        start = front + 1.0
        polygon = BRepBuilderAPI_MakePolygon()
        for u, v in view.breakout:
            u, v = u / (scale or 1.0) + cx, v / (scale or 1.0) + cy
            p = [xd[i] * u + yd[i] * v + out[i] * start for i in range(3)]
            polygon.Add(gp_Pnt(*p))
        polygon.Close()
        try:
            face = BRepBuilderAPI_MakeFace(polygon.Wire(), True).Face()
            reach = start - (front - depth)
            tool = BRepPrimAPI_MakePrism(
                face, gp_Vec(*[-out[i] * reach for i in range(3)])).Shape()
            cut = BRepAlgoAPI_Cut(shape, tool)
            cut.Build()
            if not cut.IsDone():
                return None
            opened = cut.Shape()
        except Exception:
            return None
        floor = [out[i] * (front - depth) for i in range(3)]
        faces = hlr.cut_faces(opened, floor, out) if view.hatch else []
        projection = hlr.project(opened, direction, up, hidden=show_hidden,
                                 hatch=faces,
                                 tangents=self._tangents(doc, sheet, view))
        if not projection.ok:
            return None
        dx = projection.centre[0] - cx
        dy = projection.centre[1] - cy
        for line in projection.lines:
            line.moved(dx, dy)
        box = projection.box
        projection.box = (box[0] + dx, box[1] + dy, box[2] + dx, box[3] + dy)
        projection.centre = (cx, cy)
        return projection

    def orientation(self, doc: DrawingDocument, sheet: Sheet,
                    view: View):
        """Which way a view ends up looking, publicly."""
        return self._resolved_orientation(doc, sheet, view)

    def _resolved_orientation(self, doc: DrawingDocument, sheet: Sheet,
                              view: View
                              ) -> Tuple[Tuple[float, float, float],
                                         Tuple[float, float, float]]:
        """Which way a view ends up looking, following projections back."""
        if view.kind == BASE or not view.parent:
            return orientation_of(view)
        parent = sheet.view(view.parent)
        if parent is None:
            return orientation_of(view)
        pd, pu = self._resolved_orientation(doc, sheet, parent)
        if view.kind == PROJECTED:
            dx, dy = view.x - parent.x, view.y - parent.y
            if abs(dx) > 1e-6 and abs(dy) > 1e-6:
                return iso_orientation(pd, pu, dx, dy)
            return projected_orientation(pd, pu, dx, dy, doc.angle)
        return (pd, pu)

    def _section(self, doc: DrawingDocument, sheet: Sheet, view: View,
                 parent: View, shape: TopoDS_Shape, show_hidden: bool,
                 scale: float) -> hlr.Projection:
        """Cut the model on the line drawn across the parent, and look at it.

        The cut line is in the parent's own paper millimetres, so it has to
        be lifted back into the model before it means anything.
        """
        if len(view.cut) < 4:
            raise ValueError("it has no cut line")
        pd, pu = self._resolved_orientation(doc, sheet, parent)
        parent_scale = doc.view_scale(sheet, parent)
        right = _unit(_cross(_unit(pu), _negate(_unit(pd))))

        x1, y1, x2, y2 = [c / (parent_scale or 1.0) for c in view.cut[:4]]
        mid = ((x1 + x2) / 2.0, (y1 + y2) / 2.0)
        along = (x2 - x1, y2 - y1)
        length = math.hypot(*along) or 1.0
        along = (along[0] / length, along[1] / length)

        # the plane's normal lies on the paper, square to the cut line
        normal = _unit([right[i] * -along[1] + pu[i] * along[0]
                        for i in range(3)])
        # a point on the paper is its place in the parent's own frame less
        # the middle the projection was centred on (hlr.project), so the
        # line is lifted back by adding that middle: with the centre of
        # mass in its place, as this once did, the cut was off by however
        # far the part's centre of mass lies from the middle of its view
        # (a plane drawn through the middle of an L cut it elsewhere)
        if parent.projection is not None:
            middle = parent.projection.centre
            lift = [right[i] * middle[0] + pu[i] * middle[1]
                    for i in range(3)]
        else:
            try:
                lift = list(kernel.shape_centre(shape))
            except Exception:
                lift = [0.0, 0.0, 0.0]
        point = [right[i] * mid[0] + pu[i] * mid[1] + lift[i]
                 for i in range(3)]

        cut = half_space(shape, point, normal)
        if cut is None or cut.IsNull():
            raise ValueError("the cut line does not pass through the model")
        if view.bounded:
            # only as wide as the line: the part past either end is left
            # out, by a plane square to the line through each end
            side = _unit([right[i] * along[0] + pu[i] * along[1]
                          for i in range(3)])
            for (ex, ey), sign in (((x1, y1), -1.0), ((x2, y2), 1.0)):
                end = [right[i] * ex + pu[i] * ey + lift[i]
                       for i in range(3)]
                cut = half_space(cut, end, [c * sign for c in side])
                if cut is None or cut.IsNull():
                    raise ValueError("the cut line does not pass through "
                                     "the model")

        # Look along the cut normal.  Which way is up then follows the same
        # rule a projected view uses, because a section is read exactly like
        # one: a horizontal cut on a front view is laid out like a top view,
        # and taking the parent's up unchanged would stand it on its side.
        direction = _negate(normal)
        if abs(sum(direction[i] * pu[i] for i in range(3))) > 0.9:
            # the section looks along the parent's up, so what was the
            # parent's viewing direction becomes up on this page
            facing = -1.0 if sum(direction[i] * pu[i]
                                 for i in range(3)) > 0 else 1.0
            up = _unit([facing * c for c in pd])
        else:
            up = pu
        # The faces the knife made are the ones that get hatched.  They are
        # found on the cut solid rather than assumed, because a cut through
        # a hollow part makes several of them and misses others entirely.
        faces = _cut_faces_by_body(cut, point, normal) if view.hatch \
            else []
        projection = hlr.project(cut, direction, up, hidden=show_hidden,
                                 hatch=faces,
                                 tangents=self._tangents(doc, sheet, view))
        return _scaled(projection, scale)

    def _detail(self, doc: DrawingDocument, sheet: Sheet, view: View,
                parent: View, scale: float) -> hlr.Projection:
        """Enlarge a circle of the parent, clipping its lines to the circle."""
        if parent.projection is None:
            raise ValueError("its parent has not been drawn")
        if len(view.centre) < 2:
            raise ValueError("it has no area marked on the parent")

        parent_scale = doc.view_scale(sheet, parent)
        cx, cy = view.centre[0], view.centre[1]
        radius = max(1.0, view.radius)
        factor = (scale or 1.0) / (parent_scale or 1.0)

        lines: List[hlr.Polyline] = []
        for line in parent.projection.lines:
            if line.kind == hlr.CUT:
                # A cut face is an area, not a run of lines.  Clipping it the
                # way an edge is clipped would leave it open at the circle
                # and the fill would leak out through the gap, so it is cut
                # as a polygon and closed along the circle instead.
                piece = _clip_loop_to_circle(line.points, cx, cy, radius)
                if len(piece) >= 3:
                    lines.append(hlr.Polyline(
                        [((x - cx) * factor, (y - cy) * factor)
                         for x, y in piece], line.kind, line.group))
                continue
            for piece in _clip_to_circle(line.points, cx, cy, radius):
                lines.append(hlr.Polyline(
                    [((x - cx) * factor, (y - cy) * factor) for x, y in piece],
                    line.kind))
        if not lines:
            raise ValueError("there is nothing inside the detail circle")
        # a detail of a section is still a section: it keeps the fill
        # the box is what is actually in the circle, not the circle: a detail
        # of a corner should not carry a lot of empty paper around with it
        xs = [p[0] for line in lines for p in line.points]
        ys = [p[1] for line in lines for p in line.points]
        return hlr.Projection(lines=lines,
                              box=(min(xs), min(ys), max(xs), max(ys)),
                              hatch=parent.projection.hatch)


def nearest_corner(target, seat: Sequence[float]) -> Tuple[float, float]:
    """The spot on a component a balloon at ``seat`` should point at.

    One of the component's own corners, whichever is closest to where the
    bubble is going - so the arrow lands on the edge of the part facing the
    balloon rather than reaching through the middle of the assembly.
    """
    _path, centre, corners = target
    if not corners:
        return centre
    return min(corners, key=lambda c: math.dist(c, seat))


# A model of at least this many faces goes on as a placeholder first, the
# outline of each of its parts, and its real lines follow from the workers.
# Below it the exact lines are quick enough to wait for: a thousand faces
# project in a third of a second.  Measured on the walking excavator, ten
# thousand faces: exact 7.5 s a view, the tessellated draft that used to go
# first 10.9 s, the outlines a few milliseconds.
DRAFT_FACES = 2500
_FACE_COUNTS: Dict[int, int] = {}


def _subassemblies(path: str, depth: int = 0, seen=None) -> List[str]:
    """The assembly files inside an assembly, read from the files."""
    seen = set() if seen is None else seen
    key = os.path.normcase(os.path.abspath(path))
    if key in seen or depth > 32 or not os.path.isfile(path):
        return []
    seen.add(key)
    out: List[str] = []
    try:
        opened = fileformat.read(path)
        base = os.path.dirname(os.path.abspath(path))
        for component in (opened.geometry or {}).get("components") or []:
            place = str(component.get("path") or "")
            if not place:
                continue
            if not os.path.isabs(place):
                place = os.path.normpath(os.path.join(base, place))
            if fileformat.is_assembly(place):
                out.append(place)
                out += _subassemblies(place, depth + 1, seen)
    except Exception:
        pass
    return out


def _cut_faces_by_body(cut, point, normal) -> List:
    """The faces the knife made, each with which body it is of: an
    assembly's parts cut side by side are hatched differently, so where
    one stops and the next starts can be read."""
    from OCP.TopAbs import TopAbs_SOLID
    solids = list(kernel.explore(cut, TopAbs_SOLID))
    if len(solids) <= 1:
        return hlr.cut_faces(cut, point, normal)
    out = []
    for group, solid in enumerate(solids):
        out += [(face, group) for face in hlr.cut_faces(solid, point,
                                                         normal)]
    return out


def _big(shape) -> bool:
    key = id(shape)
    if key not in _FACE_COUNTS:
        from OCP.TopAbs import TopAbs_FACE
        from OCP.TopExp import TopExp_Explorer
        n, ex = 0, TopExp_Explorer(shape, TopAbs_FACE)
        while ex.More() and n < DRAFT_FACES:
            n += 1
            ex.Next()
        if len(_FACE_COUNTS) > 64:
            _FACE_COUNTS.clear()
        _FACE_COUNTS[key] = n
    return _FACE_COUNTS[key] >= DRAFT_FACES


def _scaled(projection: hlr.Projection, scale: float) -> hlr.Projection:
    """A projection in paper millimetres rather than model ones."""
    if abs(scale - 1.0) < 1e-9 or scale <= 0:
        return projection
    for line in projection.lines:
        line.scaled(scale)
    projection.box = tuple(c * scale for c in projection.box)
    return projection


def _clip_to_rect(points, box):
    """A polyline cut down to the parts inside a rectangle (Liang-Barsky
    on each segment, joined back up where they run on)."""
    x0, y0, x1, y1 = box
    pieces: List[List[Tuple[float, float]]] = []
    current: List[Tuple[float, float]] = []
    for a, b in zip(points, points[1:]):
        dx, dy = b[0] - a[0], b[1] - a[1]
        t0, t1 = 0.0, 1.0
        inside = True
        for p, q in ((-dx, a[0] - x0), (dx, x1 - a[0]),
                     (-dy, a[1] - y0), (dy, y1 - a[1])):
            if abs(p) < 1e-12:
                if q < 0:
                    inside = False
                    break
                continue
            t = q / p
            if p < 0:
                t0 = max(t0, t)
            else:
                t1 = min(t1, t)
        if not inside or t0 > t1:
            if len(current) >= 2:
                pieces.append(current)
            current = []
            continue
        start = (a[0] + dx * t0, a[1] + dy * t0)
        end = (a[0] + dx * t1, a[1] + dy * t1)
        if current and math.dist(current[-1], start) < 1e-9:
            current.append(end)
        else:
            if len(current) >= 2:
                pieces.append(current)
            current = [start, end]
        if t1 < 1.0:
            pieces.append(current)
            current = []
    if len(current) >= 2:
        pieces.append(current)
    return pieces


def _clip_loop_to_rect(points, box):
    """A closed area cut down to a rectangle (Sutherland-Hodgman), so a
    cut face stays closed and its hatching does not leak."""
    x0, y0, x1, y1 = box
    loop = list(points)
    for inside, cross in (
            (lambda p: p[0] >= x0,
             lambda a, b: (x0, a[1] + (b[1] - a[1]) * (x0 - a[0])
                           / (b[0] - a[0]))),
            (lambda p: p[0] <= x1,
             lambda a, b: (x1, a[1] + (b[1] - a[1]) * (x1 - a[0])
                           / (b[0] - a[0]))),
            (lambda p: p[1] >= y0,
             lambda a, b: (a[0] + (b[0] - a[0]) * (y0 - a[1])
                           / (b[1] - a[1]), y0)),
            (lambda p: p[1] <= y1,
             lambda a, b: (a[0] + (b[0] - a[0]) * (y1 - a[1])
                           / (b[1] - a[1]), y1))):
        if not loop:
            break
        out = []
        for i, here in enumerate(loop):
            before = loop[i - 1]
            if inside(here):
                if not inside(before):
                    out.append(cross(before, here))
                out.append(here)
            elif inside(before):
                out.append(cross(before, here))
        loop = out
    return loop


def cropped_projection(projection: hlr.Projection, crop):
    """Only what is inside the crop rectangle of a view; None when none of
    it is.  The view keeps its place: only its lines and box change."""
    box = (min(crop[0], crop[2]), min(crop[1], crop[3]),
           max(crop[0], crop[2]), max(crop[1], crop[3]))
    lines: List[hlr.Polyline] = []
    for line in projection.lines:
        if line.kind == hlr.CUT:
            piece = _clip_loop_to_rect(line.points, box)
            if len(piece) >= 3:
                lines.append(hlr.Polyline(piece, line.kind, line.group))
            continue
        for piece in _clip_to_rect(line.points, box):
            lines.append(hlr.Polyline(piece, line.kind))
    if not lines:
        return None
    xs = [p[0] for line in lines for p in line.points]
    ys = [p[1] for line in lines for p in line.points]
    projection.lines = lines
    projection.box = (min(xs), min(ys), max(xs), max(ys))
    return projection


def _clip_loop_to_circle(points: Sequence[Tuple[float, float]],
                         cx: float, cy: float, radius: float,
                         sides: int = 64) -> List[Tuple[float, float]]:
    """A closed loop trimmed to a circle, still closed.

    The circle is treated as a many-sided polygon and the loop is cut
    against one edge of it at a time, which is the old Sutherland-Hodgman
    trick.  It only works on a convex clip region, and a circle is about as
    convex as they come.
    """
    loop = [(float(x), float(y)) for x, y in points]
    if len(loop) >= 2 and math.dist(loop[0], loop[-1]) < 1e-9:
        loop = loop[:-1]
    if len(loop) < 3:
        return []
    for i in range(sides):
        angle = 2.0 * math.pi * i / sides
        nx, ny = math.cos(angle), math.sin(angle)
        limit = radius + (cx * nx + cy * ny)
        out: List[Tuple[float, float]] = []
        for j, current in enumerate(loop):
            previous = loop[j - 1]
            here = current[0] * nx + current[1] * ny - limit
            there = previous[0] * nx + previous[1] * ny - limit
            if (here <= 0.0) != (there <= 0.0):
                t = there / (there - here)
                out.append((previous[0] + (current[0] - previous[0]) * t,
                            previous[1] + (current[1] - previous[1]) * t))
            if here <= 0.0:
                out.append(current)
        loop = out
        if not loop:
            return []
    return loop


def _clip_to_circle(points: Sequence[Tuple[float, float]],
                    cx: float, cy: float, radius: float
                    ) -> List[List[Tuple[float, float]]]:
    """The parts of a polyline inside a circle, as separate runs.

    Worked out segment by segment rather than point by point, because the
    interesting cases are the ones with no point inside the circle at all:
    a long outline edge stored as its two ends, crossing clean through a
    small detail circle.  Testing the points would throw that edge away,
    and it is usually the edge the detail was taken to show.
    """
    out: List[List[Tuple[float, float]]] = []
    run: List[Tuple[float, float]] = []

    def flush() -> None:
        if len(run) >= 2:
            out.append(list(run))

    for a, b in zip(points, points[1:]):
        piece = _segment_in_circle(a, b, cx, cy, radius)
        if piece is None:
            flush()
            run.clear()
            continue
        head, tail = piece
        if run and math.dist(run[-1], head) < 1e-9:
            run.append(tail)
        else:
            flush()
            run.clear()
            run.extend((head, tail))
    flush()
    return out


def _segment_in_circle(a: Tuple[float, float], b: Tuple[float, float],
                       cx: float, cy: float, radius: float):
    """The piece of a-b inside the circle, or None if it misses entirely."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    fx, fy = a[0] - cx, a[1] - cy
    qa = dx * dx + dy * dy
    if qa < 1e-18:
        return (a, b) if math.hypot(fx, fy) <= radius else None

    qb = 2.0 * (fx * dx + fy * dy)
    qc = fx * fx + fy * fy - radius * radius
    disc = qb * qb - 4.0 * qa * qc
    if disc < 0.0:
        return None
    root = math.sqrt(disc)
    t0 = max(0.0, (-qb - root) / (2.0 * qa))
    t1 = min(1.0, (-qb + root) / (2.0 * qa))
    if t1 <= t0:
        return None
    return ((a[0] + dx * t0, a[1] + dy * t0),
            (a[0] + dx * t1, a[1] + dy * t1))
