"""Assemblies through the bridge: place, constrain, check, bill of materials.

An assembly holds no geometry of its own. It is a list of *occurrences*
(placed instances of a part or sub-assembly file) and a list of
*constraints* between faces and edges of two of them, which a solver turns
into the occurrences' placements (``core/constraints3d.py``). It has no
feature tree, so there are no build ops here: a change is one of the calls
below, each atomic (a failure puts the assembly back as it was) and each
one undo step, exactly as a ``build`` is for a part.

Occurrence references
---------------------

A face or edge of a placed component is named ``<occurrence>/<reference>``::

    Wheel:1/Hole1.wall[0]        the first hole's bore of the part Wheel,
                                 as placed in occurrence Wheel:1
    Axle:1/Extrusion2.end        the end cap of Axle's second extrusion
    #7/Extrusion1.side(a)        the occurrence with id 7
    Wheel/Hole1.wall[0]          allowed while only one occurrence is Wheel
    Wheel:1/@F:3a7c0e            a handle from find_geometry on the part
    Wheel:1/origin.XY            the part's own XY origin plane (also XZ,
                                 YZ), or an axis: origin.X, origin.Y,
                                 origin.Z, or the origin.point
    Wheel:1                      the whole component (measure, render_view)

The part's own reference (everything after the slash) is the ordinary
reference grammar of ``ic://schema/ref``, resolved *in the component's
part*: by the roles the kernel's history gives each face first, then by
definition, then by fingerprint. The face found is then taken on the body
the assembly placed, and the constraint keeps its roles, so it follows the
part through any change that keeps the face, as a constraint picked by a
person does. Everything is mm and degrees.
"""

from __future__ import annotations

import json
import math
import os
import re
import time
from fnmatch import fnmatchcase
from typing import Any, Dict, List, Optional, Tuple

from ..core import bom as core_bom
from ..core import constraints3d as c3
from ..core import fileformat, kernel
from ..core.assembly import (AssemblyConstraint, AssemblyDocument,
                             AssemblyReport, Attachment, Occurrence)
from ..core.naming import ShapeRef
from ..core.params import ExpressionError, evaluate
from . import ops, refs
from .build import set_properties
from .errors import BridgeError
from .workspace import Entry, Workspace, same_path

op = ops.op

ORIGIN_PLANES = ("XY", "XZ", "YZ")
ORIGIN_AXES = ("X", "Y", "Z")
ORIGIN_RE = re.compile(r"^origin\.(XY|XZ|YZ|X|Y|Z|point)$", re.IGNORECASE)

# what each pairing of geometry can be constrained with, for hints
FRAME_WORDS = {c3.PLANE: "a flat face", c3.AXIS: "a cylinder or straight "
               "edge (an axis)", c3.CIRCLE: "a circular edge",
               c3.POINT: "a point"}


# ---------------------------------------------------------------- helpers


def need_assembly(entry: Entry) -> AssemblyDocument:
    if entry.doc_type != "assembly":
        raise BridgeError(
            "WRONG_TYPE", "%s is a %s; this works on assemblies"
            % (entry.handle, entry.doc_type),
            ["new_document(type=\"assembly\") makes one; open_document() "
             "opens an .icasm."])
    d = entry.document
    if any(o.shape is None and not o.error and not o.suppressed
           for o in d.occurrences):
        # an undo (or a reload) leaves the placements and no bodies:
        # read them again before anything looks at the geometry
        d.rebuild()
    return d


def _num(v: float, n: int = 4) -> float:
    return round(float(v), n) + 0.0


def find_occurrence(d: AssemblyDocument, text: Any,
                    what: str = "occurrence") -> Occurrence:
    """An occurrence by name (``Wheel:1``), by id (``#7`` or 7), or by the
    part's name when only one occurrence has it (``Wheel``)."""
    if isinstance(text, int) and not isinstance(text, bool):
        found = d.occurrence(text)
        if found is not None:
            return found
    t = str(text).strip()
    if t.startswith("#") and t[1:].isdigit():
        found = d.occurrence(int(t[1:]))
        if found is not None:
            return found
    for o in d.occurrences:
        if o.name == t:
            return o
    low = t.lower()
    same = [o for o in d.occurrences if o.name.lower() == low]
    if not same:
        same = [o for o in d.occurrences
                if o.name.rsplit(":", 1)[0].lower() == low]
    if len(same) == 1:
        return same[0]
    names = [o.name for o in d.occurrences]
    if len(same) > 1:
        raise BridgeError(
            "NO_OCCURRENCE", "%s: %r names %d occurrences (%s)"
            % (what, t, len(same), ", ".join(o.name for o in same)),
            ["Use the full name, such as %s." % same[0].name])
    raise BridgeError(
        "NO_OCCURRENCE", "%s: no occurrence called %r" % (what, t),
        ["Occurrences: %s" % (", ".join(names) or "none placed yet"),
         "place_component() adds one."])


def split_ref(text: Any, what: str = "ref") -> Tuple[str, str]:
    """``Wheel:1/Hole1.wall[0]`` -> (``Wheel:1``, ``Hole1.wall[0]``)."""
    if not isinstance(text, str) or not text.strip():
        raise BridgeError(
            "BAD_REF", "%s: %r is not a reference" % (what, text),
            ["An occurrence reference is <occurrence>/<reference>, e.g. "
             "Wheel:1/Hole1.wall[0]; see ic://schema/ref."])
    head, slash, rest = text.strip().partition("/")
    return head.strip(), rest.strip()


def component_file(d: AssemblyDocument, o: Occurrence) -> str:
    path = d.component_path(o)
    if not path:
        raise BridgeError(
            "NO_COMPONENT", "%s: its file is not found (%s)"
            % (o.name, o.ref.path or "no path"),
            ["Save the assembly next to its parts, or place the file "
             "again with an absolute path."])
    return path


def part_entry(entry: Entry, o: Occurrence) -> Entry:
    """The component's part as a document (to resolve references in),
    built from the file the assembly reads, kept until the file changes."""
    d = entry.document
    path = component_file(d, o)
    if fileformat.is_assembly(path):
        raise BridgeError(
            "NOT_YET", "%s is a sub-assembly: its faces cannot be named "
            "from here yet" % o.name,
            ["Constrain to its origin planes and axes (%s/origin.XY), or "
             "constrain the parts inside it in their own assembly."
             % o.name])
    key = os.path.normcase(os.path.abspath(path))
    try:
        stamp = (os.path.getmtime(path), o.model_state)
    except OSError:
        raise BridgeError("NO_COMPONENT", "%s: file not found: %s"
                          % (o.name, path))
    held = entry.parts.get(key)
    if held is not None and held[0] == stamp:
        return held[1]
    from ..core.document import Document
    part = Document.load(path)
    if o.model_state:
        try:
            part.model_states.activate(part, o.model_state)
            part.rebuild()
        except Exception:
            pass
    made = Entry("", part, "part")
    entry.parts[key] = (stamp, made)
    return made


class Located:
    """A face, edge or origin feature of a placed component, found."""

    def __init__(self, occurrence: Occurrence, text: str, kind: str,
                 local: Any = None, frame: Optional[c3.Frame] = None,
                 via: str = "", note: str = "") -> None:
        self.occurrence = occurrence
        self.text = text                  # as written
        self.kind = kind                  # face, edge or body
        self.local = local                # in the occurrence's own body
        self.frame = frame                # set for origin planes and axes
        self.via = via
        self.note = note


class AssemblyResolver:
    """Turns occurrence references into geometry, for one assembly.

    ``locate`` finds the piece on the body the assembly placed (in the
    component's own coordinates, which is what a constraint stores);
    ``resolve`` answers as ``refs.Resolver`` does, with shapes where the
    component sits, so ``measure`` and ``render_view`` take them too."""

    def __init__(self, entry: Entry, job: Any = None) -> None:
        self.entry = entry
        self.doc = need_assembly(entry)

    # the shape of the answer measure, render_view and the like expect
    def resolve(self, ref: Any, what: str = "ref",
                allow: Tuple[str, ...] = ("face", "edge", "vertex")
                ) -> "refs.Resolved":
        got = self.locate(ref, what, allow=allow)
        if got.frame is not None:
            raise BridgeError(
                "BAD_REF", "%s: %s is an origin plane or axis, which has "
                "no geometry to measure or draw; it is for constrain()"
                % (what, got.text))
        if got.kind not in allow:
            raise BridgeError(
                "BAD_REF", "%s: %s is a %s; this takes %s"
                % (what, got.text, got.kind, " or ".join(allow)))
        world = got.occurrence.placement.location()
        shape = got.local.Moved(world) if got.local is not None \
            else got.occurrence.placed()
        return refs.Resolved(got.text, got.kind, [shape], got.via, got.note)

    def locate(self, ref: Any, what: str = "ref",
               allow: Tuple[str, ...] = ("face", "edge")) -> Located:
        d = self.doc
        head, rest = split_ref(ref, what)
        occ = find_occurrence(d, head, what)
        text = "%s/%s" % (occ.name, rest) if rest else occ.name
        if occ.shape is None or occ.shape.IsNull():
            raise BridgeError(
                "NO_BODY", "%s: %s has no body (%s)" % (
                    what, occ.name, occ.error or "not built"),
                ["assembly_check() shows which components failed to "
                 "load."])
        if not rest:
            return Located(occ, text, "body", None, None, "definition")
        m = ORIGIN_RE.match(rest)
        if m:
            return self._origin(occ, text, m.group(1))
        part = part_entry(self.entry, occ)
        if self.entry.workspace is not None:
            # the part is also open in this host: its handles (from
            # find_geometry) and the names its build gave sketch entities
            # are kept with that document, not in the file
            held = self.entry.workspace.by_path(component_file(d, occ))
            if held is not None and held is not part:
                part.handles.update(held.handles)
                part.sketch_names.update(held.sketch_names)
        res = refs.Resolver(part)
        # a reference in a component is the ordinary one, with the same
        # ways of failing; say whose it was
        try:
            found = res.resolve(rest, "%s (in %s)" % (what, occ.name),
                                ("face", "edge"))
        except BridgeError as exc:
            exc.hints = list(exc.hints) + [
                "%s is the part %s; its references are listed in "
                "ic://schema/ref, and find_geometry(doc=<the part>) "
                "finds faces" % (occ.name,
                                 os.path.basename(component_file(d, occ)))]
            raise
        if len(found.shapes) != 1:
            raise BridgeError(
                "AMBIGUOUS_REF", "%s: %s names %d %ss; a constraint takes "
                "exactly one" % (what, text, len(found.shapes), found.kind),
                ["Add an index, such as %s[0], or use a more specific "
                 "reference or a handle." % rest.split("[")[0]])
        local = self._on_placed(occ, part, found.shapes[0], found.kind, text)
        return Located(occ, text, found.kind, local, None, found.via,
                       found.note)

    def _origin(self, occ: Occurrence, text: str, what: str) -> Located:
        from ..core.sketch import STANDARD_PLANES
        w = what.upper() if what.lower() != "point" else "point"
        if w in ORIGIN_PLANES:
            n = STANDARD_PLANES[w].normal
            frame = c3.Frame(c3.PLANE, (0.0, 0.0, 0.0),
                             tuple(float(c) for c in n), 0.0,
                             "origin %s plane" % w)
            kind = "face"
        elif w in ORIGIN_AXES:
            axis = {"X": (1.0, 0.0, 0.0), "Y": (0.0, 1.0, 0.0),
                    "Z": (0.0, 0.0, 1.0)}[w]
            frame = c3.Frame(c3.AXIS, (0.0, 0.0, 0.0), axis, 0.0,
                             "origin %s axis" % w)
            kind = "edge"
        else:
            frame = c3.Frame(c3.POINT, (0.0, 0.0, 0.0), (0.0, 0.0, 1.0),
                             0.0, "origin point")
            kind = "face"
        return Located(occ, text, kind, None, frame, "definition")

    def _on_placed(self, occ: Occurrence, part: Entry, found: Any,
                   kind: str, text: str) -> Any:
        """The piece the part's reference named, on the body the assembly
        placed (the same part, as that file was last built)."""
        make = kernel.faces if kind == "face" else kernel.edges
        mine = make(part.document.shape)
        index = next((i for i, c in enumerate(mine) if c.IsSame(found)),
                     None)
        theirs = make(occ.shape)
        scale = 1e-3 * max(1.0, *(kernel.bounding_box(occ.shape)[3:]))
        if index is not None and len(theirs) == len(mine):
            cand = theirs[index]
            if math.dist(kernel.shape_centre(cand),
                         kernel.shape_centre(found)) <= scale:
                return cand
        # the body the assembly shows is not quite the file as just built
        # (a model state, or a part open in the app with edits): find the
        # piece by what it is
        ref = ShapeRef.capture(found, kind, index or 0)
        hit = ref.resolve(occ.shape)
        if hit is None or not ref.resolved:
            raise BridgeError(
                "STALE_COMPONENT", "%s: the body placed in the assembly "
                "no longer has the piece %s names" % (text, text),
                ["Save the part, then assembly_check() to rebuild the "
                 "assembly from the files."])
        return hit


# ---------------------------------------------------------------- views


def _frame_word(frame: Optional[c3.Frame]) -> str:
    return frame.kind if frame is not None else ""


def transform_of(o: Occurrence) -> Dict[str, Any]:
    p = o.placement
    w = [float(c) for c in p.rotation]
    angle = math.sqrt(sum(c * c for c in w))
    out: Dict[str, Any] = {"position": [_num(c) for c in p.position]}
    if angle > 1e-9:
        out["rotate"] = {"axis": [_num(c / angle, 5) for c in w],
                         "angle": _num(math.degrees(angle), 4)}
    return out


def parse_transform(spec: Any, what: str = "transform") -> c3.Placement:
    """``{"position": [x,y,z], "rotate": {"axis": [..], "angle": deg}}``,
    or ``"euler": [rx, ry, rz]`` (degrees, about the world X, then Y, then
    Z). Everything optional; mm and degrees."""
    import numpy as np
    if spec in (None, {}):
        return c3.Placement()
    if not isinstance(spec, dict):
        raise BridgeError("BAD_TRANSFORM", "%s must be an object" % what,
                          ["{\"position\":[100,0,0], \"rotate\":{\"axis\":"
                           "[0,0,1], \"angle\":90}}"])
    unknown = set(spec) - {"position", "rotate", "euler"}
    if unknown:
        raise BridgeError(
            "BAD_TRANSFORM", "%s: unknown keys %s" % (
                what, ", ".join(sorted(unknown))),
            ["Keys: position [x,y,z] mm, rotate {axis, angle deg}, "
             "euler [rx,ry,rz] deg."])
    pos = spec.get("position", [0, 0, 0])
    try:
        pos = [float(c) for c in pos]
        assert len(pos) == 3
    except Exception:
        raise BridgeError("BAD_TRANSFORM", "%s.position must be three "
                          "numbers (mm)" % what)
    rotation = [0.0, 0.0, 0.0]
    if "rotate" in spec and "euler" in spec:
        raise BridgeError("BAD_TRANSFORM", "give rotate or euler, not both")
    if "rotate" in spec:
        r = spec["rotate"]
        try:
            axis = np.array([float(c) for c in r["axis"]])
            angle = math.radians(float(r["angle"]))
            norm = float(np.linalg.norm(axis))
            assert len(axis) == 3 and norm > 0
        except Exception:
            raise BridgeError(
                "BAD_TRANSFORM", "%s.rotate needs an axis [x,y,z] and an "
                "angle in degrees" % what)
        rotation = [float(c) for c in axis / norm * angle]
    elif "euler" in spec:
        try:
            rx, ry, rz = [math.radians(float(c)) for c in spec["euler"]]
        except Exception:
            raise BridgeError("BAD_TRANSFORM", "%s.euler must be three "
                              "angles in degrees" % what)
        R = (c3.rotation_matrix([0, 0, rz]) @ c3.rotation_matrix([0, ry, 0])
             @ c3.rotation_matrix([rx, 0, 0]))
        rotation = [float(c) for c in c3.rotation_vector(R)]
    return c3.Placement(pos, rotation)


def occurrence_info(d: AssemblyDocument, o: Occurrence,
                    dof: Optional[int] = None) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "id": o.id, "name": o.name,
        "file": os.path.basename(o.ref.path or o.ref.name or ""),
        "grounded": o.grounded}
    out.update(transform_of(o))
    if o.suppressed:
        out["suppressed"] = True
    if not o.visible:
        out["hidden"] = True
    if o.model_state:
        out["model_state"] = o.model_state
    if o.follows:
        target = d.occurrence(o.follows)
        out["follows"] = target.name if target else o.follows
    if o.error:
        out["error"] = o.error
    if dof is not None:
        out["dof"] = dof
    return out


def describe_attachment(d: AssemblyDocument, a: Attachment) -> Dict[str, Any]:
    o = d.occurrence(a.occurrence)
    out: Dict[str, Any] = {"occurrence": o.name if o else a.occurrence}
    if a.text:
        out["ref"] = "%s/%s" % (o.name, a.text) if o else a.text
    if a.frame is not None and a.frame.kind:
        out["geometry"] = a.frame.label or a.frame.kind
    if a.named:
        out["named"] = a.named
    return out


def constraint_info(d: AssemblyDocument, c: AssemblyConstraint
                    ) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "id": c.id, "name": c.name, "kind": c.kind,
        "a": describe_attachment(d, c.a), "b": describe_attachment(d, c.b),
        "offset": c.offset, "summary": c.summary()}
    if c.flip:
        out["flip"] = True
    if c.suppressed:
        out["suppressed"] = True
    if c.error:
        out["error"] = c.error
    return out


def report_info(report: AssemblyReport) -> Dict[str, Any]:
    out: Dict[str, Any] = {"ok": report.ok, "dof": report.dof,
                           "placed": report.placed,
                           "solver": report.solver}
    if report.missing:
        out["missing"] = list(report.missing)
    if report.errors:
        out["errors"] = list(report.errors)
    if report.warnings:
        out["warnings"] = list(report.warnings)
    return out


def tree(entry: Entry) -> Dict[str, Any]:
    """model_tree's assembly part."""
    d = need_assembly(entry)
    out: Dict[str, Any] = {}
    out["occurrences"] = [dict(occurrence_info(d, o), label=o.label,
                               path=o.ref.path,
                               constraints=len(d.constraints_on(o.id)))
                          for o in d.occurrences]
    out["constraints"] = [constraint_info(d, c) for c in d.constraints]
    out["parameters"] = ops._parameters(d)
    out["rebuild"] = report_info(d.last_report)
    out["unsaved"] = bool(getattr(d, "modified", False))
    return out


# ---------------------------------------------------------------- change


def _problems(d: AssemblyDocument) -> Dict[int, str]:
    def held(c) -> bool:
        # a constraint on a suppressed component is simply not in force
        return all(d.occurrence(att.occurrence) is not None
                   and not d.occurrence(att.occurrence).suppressed
                   for att in (c.a, c.b))
    return {c.id: c.error for c in d.constraints
            if c.error and not c.suppressed and held(c)}


def _apply(entry: Entry, mutate, finish, dry_run: bool = False,
           what: str = "change", expected_revision: Optional[int] = None
           ) -> Dict[str, Any]:
    """One atomic change to an assembly.

    ``mutate()`` edits the document and returns what it made; the
    assembly is then solved. Anything wrong that was not wrong before (a
    component that will not load, a constraint nothing can satisfy) rolls
    the whole change back and raises. ``finish(made, report)`` builds the
    answer while the change is in place. On success the change is one undo
    step (the document's own, so Ctrl+Z in the app takes it back whole)."""
    d = need_assembly(entry)
    ops._check_revision(entry, expected_revision)
    before_state = d.snapshot()
    known = _problems(d)
    known_errors = set(d.last_report.errors) | set(d.last_report.missing)
    failure: Optional[Exception] = None
    result: Dict[str, Any] = {}
    try:
        made = mutate()
        report = d.resolve()
        fresh = {i: m for i, m in _problems(d).items() if i not in known}
        new_errors = [e for e in list(report.errors) + list(report.missing)
                      if e not in known_errors]
        if fresh or new_errors:
            names = []
            for i, msg in fresh.items():
                c = d.constraint(i)
                names.append("%s (%s)" % (c.name if c else i, msg))
            message = "; ".join(names + new_errors)
            raise BridgeError(
                "CONSTRAINT_FAILED", "%s: %s" % (what, message),
                ["Nothing was changed. Is the offset or the flip what "
                 "you meant, or does another constraint already place "
                 "this component? assembly_check() lists what each "
                 "component still has free and what conflicts.",
                 "Try flip, a different kind, or remove the older "
                 "constraint first with edit_feature(delete=true)."],
                failed=[c.name for c in d.constraints
                        if c.id in fresh])
        result = finish(made, report)
    except Exception as exc:                         # noqa: BLE001
        failure = exc
    if failure is not None or dry_run:
        d.load_dict(json.loads(before_state))
        d.rebuild()
        if failure is not None:
            raise failure
        result["dry_run"] = True
        result["doc"] = entry.handle
        result["revision"] = entry.revision
        return result
    d._undo.append(before_state)
    del d._undo[:-60]
    d._redo.clear()
    d.modified = True
    entry.touch()
    result["doc"] = entry.handle
    result["revision"] = entry.revision
    result["units"] = ops._units(entry)
    return result


def _stamped(result: Dict[str, Any]) -> Dict[str, Any]:
    """The summary line names the revision the change landed on."""
    result["summary"] = result["summary"].replace(
        "@REV@", str(result["revision"]))
    return result


def _freedom_by_name(d: AssemblyDocument) -> Dict[str, int]:
    f = d.freedom()
    return {o.name: (0 if o.grounded else f.dof.get(o.id, 6))
            for o in d.active() if o.shape is not None}


def _counts(d: AssemblyDocument) -> str:
    return "%d component%s, %d constraint%s" % (
        len(d.occurrences), "" if len(d.occurrences) == 1 else "s",
        len(d.constraints), "" if len(d.constraints) == 1 else "s")


# ---------------------------------------------------------------- place


@op
def place_component(ws: Workspace, doc: str = "", file: str = "",
                    part_doc: str = "", name: str = "",
                    transform: Any = None, grounded: Optional[bool] = None,
                    model_state: str = "", dry_run: bool = False,
                    expected_revision: Optional[int] = None
                    ) -> Dict[str, Any]:
    """Place a part or sub-assembly file in an assembly."""
    entry = ws.get(doc)
    d = need_assembly(entry)
    path = ""
    if part_doc and not file:
        held = ws.get(part_doc)
        path = held.path
        if not path:
            raise BridgeError(
                "BAD_PATH", "%s has never been saved, and an assembly "
                "places files" % held.handle,
                ["save_document(doc=%r, path=<absolute .icpart>) first, "
                 "then place_component(file=that path)." % held.handle])
    elif file:
        path = file
    else:
        raise BridgeError("BAD_VALUE", "give file (an absolute .icpart or "
                          ".icasm path) or part_doc (an open, saved part)")
    path = ops._absolute(path, "place_component")
    if not os.path.exists(path):
        raise BridgeError("NOT_FOUND", "no such file: %s" % path)
    kind = fileformat.type_for_path(path)
    if kind not in (fileformat.PART, fileformat.ASSEMBLY):
        raise BridgeError(
            "BAD_FILE", "%s is not a part or an assembly" % path,
            ["An assembly places .icpart and .icasm files."])
    if d.path and same_path(path, d.path):
        raise BridgeError("BAD_FILE", "an assembly cannot place itself")
    placement = parse_transform(transform)
    label = name.strip() if name else ""
    if label and not re.fullmatch(r"[^/\\]+", label):
        raise BridgeError("BAD_NAME", "name %r cannot hold a slash" % label)

    def mutate():
        o = d.place(path, label=label)
        if transform not in (None, {}):
            o.placement = placement
        if grounded is not None:
            o.grounded = bool(grounded)
        if model_state:
            o.model_state = model_state
        return o

    def finish(o: Occurrence, report: AssemblyReport):
        if o.error:
            raise BridgeError(
                "NO_COMPONENT", "%s: %s" % (o.name, o.error),
                ["Is the file a part that builds? open_document() on it "
                 "shows its errors."])
        dof = _freedom_by_name(d).get(o.name)
        out: Dict[str, Any] = {"occurrence": occurrence_info(d, o, dof)}
        box = kernel.exact_bounding_box(o.placed()) if o.placed() is not None \
            else None
        if box:
            out["bbox"] = [_num(c) for c in box]
        out["assembly"] = report_info(report)
        held = ws.by_path(path)
        if held is not None and getattr(held.document, "modified", False):
            out["warnings"] = [
                "%s has unsaved changes; the assembly places the file as "
                "last saved. save_document it, then assembly_check() "
                "reads the new version" % held.handle]
        out["summary"] = "placed %s (%s) | %s | %s | rev @REV@" % (
            o.name, "grounded" if o.grounded else "free, DOF %s"
            % (dof if dof is not None else "?"), _counts(d),
            report.solver or "placed")
        return out

    return _stamped(_apply(entry, mutate, finish, dry_run,
                           "place_component", expected_revision))


# ---------------------------------------------------------------- constrain


def _offset_text(kind: str, offset: Any, angle: Any) -> str:
    if angle is not None:
        if kind != c3.ANGLE:
            raise BridgeError(
                "BAD_VALUE", "angle is for kind=\"angle\"; use offset for "
                "%s" % kind)
        offset = angle
    if offset is None or offset == "":
        return "0"
    if isinstance(offset, bool):
        raise BridgeError("BAD_VALUE", "offset must be a number or an "
                          "expression")
    return str(offset)


def _check_offset(d: AssemblyDocument, text: str, what: str) -> None:
    if not d.component_values:
        # an expression may name a part's parameter (Skeleton_L) before
        # anything in the assembly has used one
        d.refresh_component_values(force=True)
    scope = dict(d.component_values or {})
    try:
        scope.update(d.params.scope())
        evaluate(text, scope)
    except ExpressionError as exc:
        raise BridgeError(
            "BAD_EXPRESSION", "%s %r: %s" % (what, text, exc),
            ["An offset is a number (mm; degrees for an angle) or an "
             "expression over the assembly's parameters "
             "(properties(parameters={...})) and its parts' "
             "(<part>_<name>)."])


def _attach(res: AssemblyResolver, ref: Any, what: str) -> Attachment:
    got = res.locate(ref, what, allow=("face", "edge"))
    if got.kind == "body":
        raise BridgeError(
            "BAD_REF", "%s: %s is a whole component; a constraint holds "
            "on a face or an edge of it" % (what, got.text),
            ["Name a face or edge: %s/Extrusion1.end, or an origin plane "
             "%s/origin.XY." % (got.occurrence.name, got.occurrence.name)])
    d = res.doc
    if got.frame is not None:
        att = Attachment(occurrence=got.occurrence.id, kind=got.kind,
                         ref=None, frame=got.frame)
    else:
        att = d.attach(got.occurrence, got.kind, got.local)
        if att is None:
            raise BridgeError(
                "NOT_MATEABLE", "%s: %s is not a flat face, a cylinder or "
                "cone, or a straight or circular edge, so there is "
                "nothing to constrain with" % (what, got.text),
                ["Pick a flat face, a hole or shaft wall, or a circular "
                 "edge; find_geometry on the part lists them."])
    att.text = got.text.split("/", 1)[1] if "/" in got.text else ""
    return att


def _via(att: Attachment) -> str:
    if att.ref is None:
        return "definition"
    return "role" if att.ref.has_roles else "fingerprint"


@op
def constrain(ws: Workspace, doc: str = "", kind: str = "mate",
              a: Any = None, b: Any = None, offset: Any = None,
              angle: Any = None, flip: bool = False, name: str = "",
              dry_run: bool = False,
              expected_revision: Optional[int] = None) -> Dict[str, Any]:
    """Constrain a face or edge of one occurrence to one of another."""
    entry = ws.get(doc)
    d = need_assembly(entry)
    if kind not in c3.KINDS:
        raise BridgeError(
            "BAD_KIND", "no constraint kind %r" % kind,
            ["Kinds: %s" % "; ".join("%s (%s)" % (k, c3.KIND_HINTS[k])
                                     for k in c3.KINDS)])
    text = _offset_text(kind, offset, angle)
    _check_offset(d, text, "offset")
    res = AssemblyResolver(entry)

    def mutate():
        aa = _attach(res, a, "a")
        bb = _attach(res, b, "b")
        if aa.occurrence == bb.occurrence:
            raise BridgeError(
                "SAME_OCCURRENCE", "a and b are both on %s; a constraint "
                "ties two different components"
                % d.occurrence(aa.occurrence).name,
                ["Constrain to another occurrence, or to its origin "
                 "planes."])
        if not c3.compatible(aa.frame, bb.frame, kind):
            raise BridgeError(
                "BAD_PAIRING", "%s does not apply to %s and %s" % (
                    kind, aa.frame.label, bb.frame.label),
                ["a is %s, b is %s." % (FRAME_WORDS.get(aa.frame.kind),
                                        FRAME_WORDS.get(bb.frame.kind)),
                 "mate and flush take any pair except two points (flush "
                 "needs a face or an axis); insert needs two axes or "
                 "circles; tangent a round and a flat or round; angle and "
                 "parallel anything with a direction."])
        c = AssemblyConstraint(kind=kind, a=aa, b=bb, offset=text,
                               flip=bool(flip), name=name or "")
        if name and any(x.name == name for x in d.constraints):
            raise BridgeError("BAD_NAME", "a constraint is already "
                              "called %r" % name)
        before = _freedom_by_name(d)
        d.add_constraint(c)
        return c, before

    def finish(made, report: AssemblyReport):
        c, before = made
        after = _freedom_by_name(d)
        names = [d.occurrence(c.a.occurrence).name,
                 d.occurrence(c.b.occurrence).name]
        moved = {n: (before.get(n), after.get(n)) for n in names
                 if before.get(n) != after.get(n)}
        out: Dict[str, Any] = {
            "constraint": constraint_info(d, c),
            "via": {"a": _via(c.a), "b": _via(c.b)},
            "dof": {n: after.get(n) for n in names},
            "assembly": report_info(report)}
        warns: List[str] = []
        if sum(before.get(n, 0) for n in names) == sum(
                after.get(n, 0) for n in names):
            warns.append(
                "%s took no freedom away: it repeats what the others "
                "already hold, or the components were already placed "
                "so" % c.name)
        if c.error:
            warns.append("%s: %s" % (c.name, c.error))
        if warns:
            out["warnings"] = warns
        out["occurrences"] = [occurrence_info(d, d.occurrence(i), after.get(
            d.occurrence(i).name)) for i in (c.a.occurrence, c.b.occurrence)]
        change = ", ".join("%s DOF %s -> %s" % (n, v[0], v[1])
                           for n, v in moved.items()) or "no DOF change"
        out["summary"] = "%s %s %s <-> %s ok | %s | rev @REV@" % (
            c.name, "(%s)" % kind if c.name.lower() != kind else "",
            c.a.text and "%s/%s" % (names[0], c.a.text) or names[0],
            c.b.text and "%s/%s" % (names[1], c.b.text) or names[1],
            change)
        return out

    return _stamped(_apply(entry, mutate, finish, dry_run, "constrain",
                           expected_revision))


# ---------------------------------------------------------------- edit


def _find_item(d: AssemblyDocument, feature: Any):
    """An occurrence or a constraint, by name or id."""
    t = str(feature).strip()
    for c in d.constraints:
        if c.name == t:
            return "constraint", c
    if t.startswith("#") and t[1:].isdigit():
        i = int(t[1:])
        c = d.constraint(i)
        if c is not None:
            return "constraint", c
    try:
        return "occurrence", find_occurrence(d, feature, "feature")
    except BridgeError as exc:
        low = t.lower()
        for c in d.constraints:
            if c.name.lower() == low:
                return "constraint", c
        exc.hints = ["Constraints: %s" % (", ".join(c.name for c in
                                                    d.constraints)
                                          or "none")] + exc.hints
        raise


def edit_item(ws: Workspace, entry: Entry, feature: Any,
              params: Optional[Dict[str, Any]], suppress: Optional[bool],
              delete: bool, delete_dependents: bool, rename: str,
              dry_run: bool, expected_revision: Optional[int]
              ) -> Dict[str, Any]:
    """edit_feature on an assembly: an occurrence or a constraint."""
    d = need_assembly(entry)
    what, item = _find_item(d, feature)
    params = dict(params or {})
    users = ([c for c in d.constraints if c.uses(item.id)]
             if what == "occurrence" else [])
    dependents = [{"id": c.id, "name": c.name, "type": "constraint"}
                  for c in users]
    changing = bool(params or suppress is not None or delete or rename)
    if not changing:
        info = (occurrence_info(d, item) if what == "occurrence"
                else constraint_info(d, item))
        return {"doc": entry.handle, "revision": entry.revision,
                "feature": dict(info, type=what), "dependents": dependents,
                "summary": "%s %s" % (what, getattr(item, "name", ""))}
    if delete and users and not delete_dependents:
        raise BridgeError(
            "HAS_DEPENDENTS", "%s is used by %s" % (
                item.name, ", ".join(c.name for c in users)),
            ["Pass delete_dependents: true to remove those constraints as "
             "well."], dependents=dependents)
    allowed = ({"transform", "grounded", "visible", "model_state"}
               if what == "occurrence" else
               {"offset", "angle", "flip", "kind", "a", "b"})
    unknown = set(params) - allowed
    if unknown:
        raise BridgeError(
            "BAD_VALUE", "%s has no field %s" % (
                what, ", ".join(sorted(unknown))),
            ["An %s takes %s in params." % (what, ", ".join(sorted(
                allowed)))])
    res = AssemblyResolver(entry)
    gone: List[str] = []

    def mutate():
        if delete:
            if what == "occurrence":
                gone.extend(c.name for c in users)
                d.remove_occurrence(item.id)
            else:
                d.remove_constraint(item.id)
            return None
        if rename:
            if what == "occurrence":
                if any(o is not item and o.name == rename
                       for o in d.occurrences):
                    raise BridgeError("BAD_NAME", "%r is taken" % rename)
                item.name = rename
            else:
                if any(c is not item and c.name == rename
                       for c in d.constraints):
                    raise BridgeError("BAD_NAME", "%r is taken" % rename)
                item.name = rename
        if suppress is not None:
            item.suppressed = bool(suppress)
        if what == "occurrence":
            if "transform" in params:
                item.placement = parse_transform(params["transform"],
                                                 "params.transform")
            if "grounded" in params:
                item.grounded = bool(params["grounded"])
            if "visible" in params:
                item.visible = bool(params["visible"])
            if "model_state" in params:
                item.model_state = str(params["model_state"] or "")
        else:
            kind = params.get("kind", item.kind)
            if kind not in c3.KINDS:
                raise BridgeError("BAD_KIND", "no constraint kind %r"
                                  % kind)
            item.kind = kind
            if "offset" in params or "angle" in params:
                text = _offset_text(kind, params.get("offset"),
                                    params.get("angle"))
                _check_offset(d, text, "offset")
                item.offset = text
            if "flip" in params:
                item.flip = bool(params["flip"])
            for side in ("a", "b"):
                if side in params:
                    att = _attach(res, params[side], side)
                    setattr(item, side, att)
            if item.a.occurrence == item.b.occurrence:
                raise BridgeError("SAME_OCCURRENCE",
                                  "a and b are on one component")
            if not c3.compatible(item.a.frame, item.b.frame, item.kind):
                raise BridgeError(
                    "BAD_PAIRING", "%s does not apply to %s and %s" % (
                        item.kind, item.a.frame.label, item.b.frame.label))
        return None

    def finish(_made, report: AssemblyReport):
        out: Dict[str, Any] = {"assembly": report_info(report),
                               "dependents": dependents}
        if delete:
            out["removed"] = [item.name] + gone
            out["summary"] = "removed %s%s | %s | %s | rev @REV@" % (
                item.name, (" and " + ", ".join(gone)) if gone else "",
                _counts(d), report.solver or "solved")
        else:
            info = (occurrence_info(d, item) if what == "occurrence"
                    else constraint_info(d, item))
            out["changed"] = [item.name]
            out["feature"] = dict(info, type=what)
            out["summary"] = "changed %s | %s | %s | rev @REV@" % (
                item.name, _counts(d), report.solver or "solved")
        return out

    return _stamped(_apply(entry, mutate, finish, dry_run, "edit_feature",
                           expected_revision))


def properties(ws: Workspace, entry: Entry, parameters: Optional[Dict],
               remove: Optional[List[str]], props: Optional[Dict],
               material: str, expected_revision: Optional[int],
               appearance: str = "") -> Dict[str, Any]:
    """properties() on an assembly: its own parameters (offsets and angles
    may be expressions over them), iProperties and material."""
    d = need_assembly(entry)
    changed = bool(parameters or remove or props or material or appearance)
    if changed:
        def mutate():
            for pname, spec in (parameters or {}).items():
                expr, comment = ((spec.get("expression", spec.get("value")),
                                  spec.get("comment"))
                                 if isinstance(spec, dict) else (spec, None))
                if pname in d.params:
                    if expr is not None:
                        d.params.set_expression(pname, str(expr))
                    if comment is not None:
                        d.params[pname].comment = str(comment)
                elif expr is not None:
                    d.params.add(pname, str(expr), comment=comment or "")
                else:
                    raise BridgeError("BAD_VALUE",
                                      "%s needs an expression" % pname)
            for pname in (remove or []):
                if pname in d.params:
                    d.params.remove(pname)
            set_properties(d, props, material, appearance)
            d.params.evaluate_all()
            bad = [p for p in ops._parameters(d) if p.get("error")]
            if bad:
                raise BridgeError("BAD_EXPRESSION", "; ".join(
                    "%s: %s" % (p["name"], p["error"]) for p in bad))
            return None

        def finish(_made, report):
            return {"assembly": report_info(report)}

        _apply(entry, mutate, finish, False, "properties",
               expected_revision)
    return {"doc": entry.handle, "revision": entry.revision,
            "parameters": ops._parameters(d),
            "properties": dict(d.properties), "material": d.material,
            "appearance": d.appearance,
            "rebuild": report_info(d.last_report)}


# ---------------------------------------------------------------- check


def _pair_patterns(allow: Any) -> List[Tuple[str, str]]:
    """``allow`` as pairs of name patterns."""
    out = []
    for item in allow or ():
        if (not isinstance(item, (list, tuple)) or len(item) != 2
                or not all(isinstance(v, str) for v in item)):
            raise BridgeError(
                "BAD_VALUE", "allow is a list of name pairs, not %r" % (item,),
                ['[["Wing:1", "Fuselage:1"], ["*rim*", "*piston*"]]: * '
                 "matches anything."])
        out.append((item[0], item[1]))
    return out


def find_interference(d: AssemblyDocument, min_volume: float = 0.01,
                      budget: float = 45.0, start: int = 0,
                      allow: Any = None, progress=None,
                      cancelled=None) -> Dict[str, Any]:
    """Which placed components share volume, and how much.

    The pairs whose boxes meet are numbered in a fixed order. A check
    that runs out of ``budget`` says where to ``start`` the next from, so
    one of any size can be finished. An overlap that matches a pair in
    ``allow`` is meant: it is reported apart and is not a fault.
    """
    meant = _pair_patterns(allow)
    used = set()
    live = [o for o in d.active() if o.shape is not None and o.visible]
    placed = {o.id: o.placed() for o in live}
    boxes = {i: kernel.bounding_box(s) for i, s in placed.items()
             if s is not None}
    names = {o.id: o.name for o in live}
    ids = list(boxes)
    near: List[Tuple[Any, Any]] = []
    for i, a in enumerate(ids):
        ba = boxes[a]
        for b in ids[i + 1:]:
            bb = boxes[b]
            if (ba[3] < bb[0] + 1e-6 or bb[3] < ba[0] + 1e-6
                    or ba[4] < bb[1] + 1e-6 or bb[4] < ba[1] + 1e-6
                    or ba[5] < bb[2] + 1e-6 or bb[5] < ba[2] + 1e-6):
                continue
            near.append((a, b))
    first = int(start or 0)
    if not 0 <= first <= len(near):
        raise BridgeError("BAD_VALUE", "start is %d; there are %d pairs"
                          % (first, len(near)))
    started = time.perf_counter()
    pairs: List[Dict[str, Any]] = []
    expected: List[Dict[str, Any]] = []
    failed: List[str] = []
    at = first
    while at < len(near):
        # one at least, so a resumed check always gets further
        if at > first and (time.perf_counter() - started > budget
                           or (cancelled and cancelled())):
            break
        a, b = near[at]
        at += 1
        if progress:
            progress(at, len(near), "%s / %s" % (names[a], names[b]))
        try:
            common = kernel.boolean(placed[a], placed[b], "intersect")
            vol = (kernel.volume(common)
                   if common is not None and not common.IsNull()
                   else 0.0)
        except Exception as exc:                     # noqa: BLE001
            if "removed all material" in str(exc):
                continue                       # nothing in common
            failed.append("%s / %s" % (names[a], names[b]))
            continue
        if vol <= min_volume:
            continue
        # the quick box of a piece of a spline face is that whole face's:
        # an overlap 1 long was reported as 20
        each = [kernel.exact_bounding_box(s)
                for s in kernel.pieces(common)]
        box = ([min(b[k] for b in each) for k in range(3)]
               + [max(b[k] for b in each) for k in range(3, 6)])
        # a mirrored pair overlaps twice: point at one, not between them
        main = max(each, key=lambda b: sum((b[k + 3] - b[k]) ** 2
                                           for k in range(3)))
        found = {"a": names[a], "b": names[b],
                 "volume_mm3": _num(vol, 3),
                 "overlap_bbox": [_num(c, 3) for c in box],
                 "at": [_num((main[k] + main[k + 3]) / 2, 2)
                        for k in range(3)]}
        match = [n for n, (p, q) in enumerate(meant)
                 if fnmatchcase(names[a], p) and fnmatchcase(names[b], q)
                 or fnmatchcase(names[a], q) and fnmatchcase(names[b], p)]
        used.update(match)
        (expected if match else pairs).append(found)
    pairs.sort(key=lambda p: -p["volume_mm3"])
    out: Dict[str, Any] = {
        "count": len(pairs), "pairs": pairs, "pairs_tested": at - first,
        "pairs_total": len(near), "complete": at >= len(near),
        "components": len(live), "min_volume_mm3": min_volume}
    if meant:
        out["allowed"] = {"count": len(expected),
                          "pairs": sorted({"%s / %s" % (p["a"], p["b"])
                                           for p in expected})}
        if not first and at >= len(near):
            unused = [list(meant[n]) for n in range(len(meant))
                      if n not in used]
            if unused:
                out["allow_unused"] = unused
    if first:
        out["from"] = first         # the ones before were an earlier call's
    if at < len(near):
        out["not_tested"] = len(near) - at
        out["next_start"] = at
        out["note"] = ("stopped after %.0f s; %d pairs not tested: call "
                       "again with start=%d, or a longer budget"
                       % (time.perf_counter() - started, len(near) - at, at))
    if failed:
        out["failed"] = failed
    return out


@op
def assembly_check(ws: Workspace, doc: str = "", interference: bool = True,
                   min_volume: float = 0.01, rebuild: bool = True,
                   interference_budget: float = 45.0, start: int = 0,
                   allow: Any = None) -> Dict[str, Any]:
    """Degrees of freedom per component, failing or redundant constraints,
    and interference between components."""
    entry = ws.get(doc)
    d = need_assembly(entry)
    report = d.rebuild() if rebuild else d.resolve()
    f = d.freedom()
    occurrences = []
    for o in d.occurrences:
        info = occurrence_info(d, o)
        if o.suppressed:
            info["status"] = "suppressed"
        elif o.shape is None:
            info["status"] = "no body"
        elif o.grounded:
            info["dof"] = 0
            info["status"] = "grounded"
        else:
            dof = f.dof.get(o.id, 6)
            info["dof"] = dof
            info["status"] = ("fully constrained" if dof == 0
                              else "under-constrained"
                              if d.constraints_on(o.id) else "unconstrained")
            if o.follows:
                info["status"] = "follows another component"
        info["constraints"] = len(d.constraints_on(o.id))
        occurrences.append(info)
    failed = [dict(constraint_info(d, c), error=c.error)
              for c in d.constraints if c.error and not c.suppressed]
    redundant = [d.constraint(i).name for i in f.redundant
                 if d.constraint(i) is not None]
    loose = [o["name"] for o in occurrences
             if o.get("status") in ("under-constrained", "unconstrained")]
    out: Dict[str, Any] = {
        "doc": entry.handle, "revision": entry.revision,
        "components": len(d.occurrences),
        "constraints": len(d.constraints),
        "dof": report.dof, "fully_constrained": (
            report.dof == 0 and not loose and bool(d.occurrences)),
        "occurrences": occurrences, "failed": failed,
        "redundant": redundant, "solver": report.solver,
        "rebuild": report_info(report)}
    if loose:
        out["free"] = {o["name"]: o["dof"] for o in occurrences
                       if o["name"] in loose}
    inter = None
    if interference:
        inter = find_interference(
            d, float(min_volume), float(interference_budget), start, allow,
            progress=ws.progress, cancelled=ws.should_cancel)
        out["interference"] = inter
    bits = ["%d component%s" % (len(d.occurrences),
                                "" if len(d.occurrences) == 1 else "s"),
            "%d constraint%s" % (len(d.constraints),
                                 "" if len(d.constraints) == 1 else "s"),
            "DOF %d" % report.dof
            + (" (%s)" % ", ".join("%s %d" % (k, v) for k, v in
                                   list(out.get("free", {}).items())[:4])
               if loose else "")]
    bits.append("%d failed" % len(failed) if failed else "0 failed")
    if redundant:
        bits.append("%d redundant" % len(redundant))
    if inter is not None:
        bits.append("%d interference%s" % (
            inter["count"], "" if inter["count"] == 1 else "s"))
    if inter is not None and inter.get("not_tested"):
        bits.append("INCOMPLETE: %d pairs not tested, next start=%d"
                    % (inter["not_tested"], inter["next_start"]))
    if inter is not None and inter.get("failed"):
        bits.append("%d pairs could not be tested" % len(inter["failed"]))
    out["ok"] = (report.ok and not failed
                 and (inter is None
                      or (inter["count"] == 0 and inter["complete"]
                          and not inter.get("failed"))))
    out["summary"] = "%s | %s" % ("ok" if out["ok"] else "attention",
                                  " | ".join(bits))
    return out


# ---------------------------------------------------------------- bom


def _line(path: str, library, qty: int, label: str) -> Dict[str, Any]:
    document = core_bom._open(path, library) if path else None
    name = os.path.splitext(os.path.basename(path or label))[0]
    pn = core_bom._property(document, "part_number", "")
    material = core_bom._property(document, "material", "") or str(
        getattr(document, "material", "") or "")
    each = core_bom.mass_grams(path, library) if path else None
    line: Dict[str, Any] = {
        "name": name, "qty": qty, "part_number": pn or name,
        "description": core_bom._property(document, "description", ""),
        "material": material,
        "mass_g": None if each is None else _num(each, 3),
        "mass_total_g": None if each is None else _num(each * qty, 3),
        "file": os.path.basename(path or ""),
        "kind": ("assembly" if path and fileformat.is_assembly(path)
                 else "part")}
    if not pn:
        line["no_part_number"] = True
    return line


def _collect(d: AssemblyDocument, library, out: Dict[str, Dict[str, Any]],
             order: List[str], names: Dict[str, List[str]], multiplier: int,
             depth: int, structured: bool, trail: str = "") -> List[Dict]:
    """Group one assembly's occurrences by file. Flat: parts only, the
    sub-assemblies opened and counted through; structured: one line per
    file with the sub-assembly's own lines as ``children``."""
    rows: Dict[str, Dict[str, Any]] = {}
    sequence: List[str] = []
    for o in d.occurrences:
        if o.suppressed:
            continue
        path = d.component_path(o) or ""
        key = core_bom.key_for(path) or o.name
        sub = bool(path) and fileformat.is_assembly(path)
        if sub and depth < 6 and not structured:
            try:
                from ..core.assembly import open_any
                inner = open_any(path)
                _collect(inner, library, out, order, names, multiplier,
                         depth + 1, False, trail + o.name + "/")
                continue
            except Exception:                              # noqa: BLE001
                pass
        if key in rows:
            rows[key]["qty"] += 1
            rows[key]["occurrences"].append(trail + o.name)
            continue
        rows[key] = {"path": path, "qty": 1, "label": o.label,
                     "occurrences": [trail + o.name], "sub": sub}
        sequence.append(key)
    result: List[Dict[str, Any]] = []
    for key in sequence:
        r = rows[key]
        if structured:
            line = _line(r["path"], library, r["qty"], r["label"])
            line["occurrences"] = r["occurrences"]
            if r["sub"] and depth < 6:
                try:
                    from ..core.assembly import open_any
                    inner = open_any(r["path"])
                    line["children"] = _collect(
                        inner, library, out, order, names, 1, depth + 1,
                        True)
                except Exception:                          # noqa: BLE001
                    line["children"] = []
            result.append(line)
        else:
            total = r["qty"] * multiplier
            if key in out:
                out[key]["qty"] += total
                names[key].extend(r["occurrences"])
            else:
                out[key] = _line(r["path"], library, total, r["label"])
                names[key] = list(r["occurrences"])
                order.append(key)
    return result


@op
def bom(ws: Workspace, doc: str = "", structure: str = "both"
        ) -> Dict[str, Any]:
    """The bill of materials: flat (every part, counted through
    sub-assemblies) and structured (one line per file, a sub-assembly's
    parts under it), with quantities, part numbers, materials and mass."""
    entry = ws.get(doc)
    d = need_assembly(entry)
    if structure not in ("flat", "structured", "both"):
        raise BridgeError("BAD_VALUE", "structure is flat, structured or "
                          "both")
    if d.occurrences and not any(o.shape is not None for o in d.occurrences):
        d.rebuild()
    out: Dict[str, Any] = {"doc": entry.handle, "revision": entry.revision}
    flat_map: Dict[str, Dict[str, Any]] = {}
    order: List[str] = []
    names: Dict[str, List[str]] = {}
    _collect(d, d.library, flat_map, order, names, 1, 0, False)
    flat = []
    for n, key in enumerate(order, 1):
        line = flat_map[key]
        if line["mass_g"] is not None:
            line["mass_total_g"] = _num(line["mass_g"] * line["qty"], 3)
        line["item"] = n
        line["occurrences"] = names[key]
        flat.append(line)
    if structure in ("flat", "both"):
        out["flat"] = flat
    if structure in ("structured", "both"):
        tree_rows = _collect(d, d.library, {}, [], {}, 1, 0, True)
        for n, line in enumerate(tree_rows, 1):
            line["item"] = n
        out["structured"] = tree_rows
    parts = sum(line["qty"] for line in flat)
    known = [line for line in flat if line["mass_total_g"] is not None]
    total = sum(line["mass_total_g"] for line in known)
    out["totals"] = {"line_items": len(flat), "parts": parts,
                     "mass_g": _num(total, 3),
                     "mass_kg": _num(total / 1000.0, 4)}
    warns = []
    unknown = [line["name"] for line in flat
               if line["mass_total_g"] is None]
    if unknown:
        warns.append("mass unknown for %s (no body or unreadable file); "
                     "the total leaves them out" % ", ".join(unknown))
    nopn = [line["name"] for line in flat if line.get("no_part_number")]
    if nopn:
        warns.append("no Part Number property on %s: the file name is "
                     "used (properties(props={\"Part Number\": ...}) on "
                     "the part sets it)" % ", ".join(nopn[:8]))
    generic = [line["name"] for line in flat
               if line["material"] in ("", "Generic")]
    if generic:
        warns.append("material is Generic or unset on %s, so their mass "
                     "uses a default density" % ", ".join(generic[:8]))
    if warns:
        out["warnings"] = warns
    out["summary"] = "%d line item%s | %d part%s | %.3f kg" % (
        len(flat), "" if len(flat) == 1 else "s", parts,
        "" if parts == 1 else "s", total / 1000.0)
    return out
