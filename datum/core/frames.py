"""The Frame Generator, Inventor's way.

A skeleton, a part with a sketch of lines (a table: a rectangle and four
legs), is placed in an assembly.  Insert Frame puts a frame member on each
line picked: a part of its own, the profile chosen from the library run
the line's length.  The members live in a frame subassembly of their own,
which follows the skeleton wherever it is placed, and when the skeleton's
sketch changes the members grow, shrink and move with it on the next
rebuild.  That is how Inventor's Frame Generator is laid out too: a frame
assembly holding the members, each bound to the skeleton's geometry.

The profiles come from a library of families: a family is a kind of shape
(an equal angle, a square tube, or a closed sketch of your own) and a table
of sizes, one row each.
"""

from __future__ import annotations

import json
import math
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from OCP.BRepBuilderAPI import (BRepBuilderAPI_MakeEdge,
                                BRepBuilderAPI_MakeFace,
                                BRepBuilderAPI_MakeWire)
from OCP.GC import GC_MakeArcOfCircle
from OCP.gp import gp_Pnt

from . import kernel
from .kernel import KernelError

# ------------------------------------------------------------------ profiles


def _wire(segments) -> Any:
    """A closed wire on XY from lines ("line", a, b) and arcs ("arc", a,
    through, b)."""
    maker = BRepBuilderAPI_MakeWire()
    for seg in segments:
        if seg[0] == "line":
            a, b = seg[1], seg[2]
            if math.dist(a, b) < 1e-9:
                continue
            maker.Add(BRepBuilderAPI_MakeEdge(gp_Pnt(a[0], a[1], 0.0),
                                              gp_Pnt(b[0], b[1], 0.0)).Edge())
        else:
            a, m, b = seg[1], seg[2], seg[3]
            maker.Add(BRepBuilderAPI_MakeEdge(GC_MakeArcOfCircle(
                gp_Pnt(a[0], a[1], 0.0), gp_Pnt(m[0], m[1], 0.0),
                gp_Pnt(b[0], b[1], 0.0)).Value()).Edge())
    if not maker.IsDone():
        raise KernelError("the profile's outline does not close")
    return maker.Wire()


def _corner(cx, cy, r, start_deg, end_deg):
    """An arc about (cx, cy) as ("arc", a, middle, b)."""
    def at(deg):
        return (cx + r * math.cos(math.radians(deg)),
                cy + r * math.sin(math.radians(deg)))
    return ("arc", at(start_deg), at((start_deg + end_deg) / 2.0),
            at(end_deg))


def rounded_square(side: float, radius: float) -> Any:
    """A square of ``side`` about the origin, its corners rounded."""
    h = side / 2.0
    r = max(0.0, min(radius, h))
    if r < 1e-9:
        return _wire([("line", (-h, -h), (h, -h)), ("line", (h, -h), (h, h)),
                      ("line", (h, h), (-h, h)), ("line", (-h, h), (-h, -h))])
    return _wire([
        ("line", (-h + r, -h), (h - r, -h)), _corner(h - r, -h + r, r, -90, 0),
        ("line", (h, -h + r), (h, h - r)), _corner(h - r, h - r, r, 0, 90),
        ("line", (h - r, h), (-h + r, h)), _corner(-h + r, h - r, r, 90, 180),
        ("line", (-h, h - r), (-h, -h + r)),
        _corner(-h + r, -h + r, r, 180, 270)])


def square_tube(b: float, t: float, ro: float) -> Any:
    """A square hollow section: side ``b``, wall ``t``, outside corner
    radius ``ro``; the inside radius is ``ro - t``, as the standard has it."""
    if b <= 0 or t <= 0 or 2 * t >= b:
        raise KernelError("a tube needs a wall thinner than half its side")
    outer = rounded_square(b, ro)
    inner = rounded_square(b - 2 * t, max(ro - t, 0.0))
    maker = BRepBuilderAPI_MakeFace(outer, True)
    from OCP.TopoDS import TopoDS
    maker.Add(TopoDS.Wire_s(inner.Reversed()))
    from OCP.ShapeFix import ShapeFix_Face
    fixer = ShapeFix_Face(maker.Face())
    fixer.FixOrientation()
    fixer.Perform()
    return fixer.Face()


def equal_angle(b: float, t: float, r1: float, r2: float) -> Any:
    """An equal angle: legs ``b`` along +X and +Y from the heel at the
    origin, ``t`` thick, the root filleted at ``r1`` and the toes rounded
    at ``r2``."""
    if b <= 0 or t <= 0 or t >= b:
        raise KernelError("an angle's legs must be longer than they are thick")
    s45 = math.sqrt(0.5)
    segs = [("line", (0.0, 0.0), (b, 0.0))]
    if r2 > 1e-9:
        segs += [("line", (b, 0.0), (b, t - r2)),
                 _corner(b - r2, t - r2, r2, 0, 90),
                 ("line", (b - r2, t), (t + r1, t))]
    else:
        segs += [("line", (b, 0.0), (b, t)), ("line", (b, t), (t + r1, t))]
    if r1 > 1e-9:
        # the root fillet is concave: about a centre outside the section
        segs.append(("arc", (t + r1, t),
                     (t + r1 - r1 * s45, t + r1 - r1 * s45), (t, t + r1)))
    if r2 > 1e-9:
        segs += [("line", (t, t + r1), (t, b - r2)),
                 _corner(t - r2, b - r2, r2, 0, 90),
                 ("line", (t - r2, b), (0.0, b))]
    else:
        segs += [("line", (t, t + r1), (t, b)), ("line", (t, b), (0.0, b))]
    segs.append(("line", (0.0, b), (0.0, 0.0)))
    return BRepBuilderAPI_MakeFace(_wire(segs), True).Face()


# --------------------------------------------------------------- the library


@dataclass
class ProfileFamily:
    """A family of profiles: a kind of shape and a table of sizes.

    ``kind`` is "angle" (columns b, t, r1, r2), "square_tube" (b, t, ro) or
    "sketch": then ``source`` is a part file whose sketch is the profile,
    and the columns are its parameters, set row by row.
    """

    id: str
    name: str
    standard: str = ""
    category: str = ""
    kind: str = "angle"
    columns: List[str] = field(default_factory=list)
    rows: List[List[Any]] = field(default_factory=list)   # [designation, ...]
    source: str = ""
    builtin: bool = False

    def sizes(self) -> List[str]:
        return [str(r[0]) for r in self.rows]

    def row(self, size: str) -> Dict[str, float]:
        for r in self.rows:
            if str(r[0]) == size:
                return {c: float(v) for c, v in zip(self.columns, r[1:])}
        raise KeyError("%s has no size %s" % (self.name, size))

    def to_dict(self) -> Dict[str, Any]:
        return {"id": self.id, "name": self.name, "standard": self.standard,
                "category": self.category, "kind": self.kind,
                "columns": list(self.columns),
                "rows": [list(r) for r in self.rows], "source": self.source}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ProfileFamily":
        return cls(id=str(data["id"]), name=str(data.get("name", data["id"])),
                   standard=str(data.get("standard", "")),
                   category=str(data.get("category", "")),
                   kind=str(data.get("kind", "angle")),
                   columns=[str(c) for c in data.get("columns", [])],
                   rows=[list(r) for r in data.get("rows", [])],
                   source=str(data.get("source", "")))


COLUMNS = {"angle": ["b", "t", "r1", "r2"],
           "square_tube": ["b", "t", "ro"]}
CATEGORIES = {"angle": "Angles", "square_tube": "Square Tubes",
              "sketch": "Custom"}


def builtin_families() -> List[ProfileFamily]:
    from . import profile_tables as tables
    return [
        ProfileFamily("din-en-10056-1-equal", "DIN EN 10056-1 Equal Angles",
                      "DIN EN 10056-1", "Angles", "angle", COLUMNS["angle"],
                      [list(r) for r in tables.EQUAL_ANGLES_DIN_EN_10056_1],
                      builtin=True),
        ProfileFamily("din-en-10219-2-square",
                      "DIN EN 10219-2 Square Hollow Sections",
                      "DIN EN 10219-2", "Square Tubes", "square_tube",
                      COLUMNS["square_tube"],
                      [list(r) for r in tables.SQUARE_HOLLOW_DIN_EN_10219_2],
                      builtin=True),
    ]


def library_folder() -> str:
    """Where your own profile families are kept, one JSON file each."""
    base = os.environ.get("DATUM_PROFILE_LIBRARY")
    if base:
        return base
    root = os.environ.get("APPDATA") or os.path.expanduser("~/.config")
    return os.path.join(root, "IITEG", "DATUM", "profiles")


def families() -> List[ProfileFamily]:
    """Every family: those that come with InventCraft, then your own."""
    out = builtin_families()
    folder = library_folder()
    if os.path.isdir(folder):
        for name in sorted(os.listdir(folder)):
            if not name.lower().endswith(".json"):
                continue
            try:
                with open(os.path.join(folder, name), encoding="utf-8") as f:
                    out.append(ProfileFamily.from_dict(json.load(f)))
            except (OSError, ValueError, KeyError):
                continue
    return out


def family(family_id: str) -> ProfileFamily:
    for f in families():
        if f.id == family_id:
            return f
    raise KeyError("there is no profile family %s" % family_id)


def save_family(fam: ProfileFamily) -> str:
    """Keep one of your own families in the library."""
    if fam.builtin:
        raise ValueError("the families that come with InventCraft are "
                         "fixed; copy one to change it")
    folder = library_folder()
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, re.sub(r"[^A-Za-z0-9_.-]+", "-", fam.id)
                        + ".json")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(fam.to_dict(), handle, indent=1)
    return path


def delete_family(family_id: str) -> None:
    for name in os.listdir(library_folder()):
        path = os.path.join(library_folder(), name)
        try:
            with open(path, encoding="utf-8") as handle:
                if json.load(handle).get("id") == family_id:
                    os.remove(path)
        except (OSError, ValueError):
            continue


def sketch_parameters(path: str) -> List[str]:
    """The names a sketch profile's table can set: the part's own
    parameters and its dimensions' names."""
    doc = _open_part(path)
    names = [p.name for p in doc.params]
    for sketch in doc.all_sketches().values():
        for c in sketch.constraints.values():
            if c.is_dimension and c.name and c.name not in names:
                names.append(c.name)
    return names


# The window sets this: the document behind a file as it is being edited
# now, unsaved edits and all, or None.  A skeleton edited in place in the
# assembly is read from there, so the frame follows the sketch as it is
# on screen rather than as it was last saved.
live_document = None


def _open_part(path: str):
    if live_document is not None:
        try:
            held = live_document(path)
        except Exception:
            held = None
        if held is not None and hasattr(held, "all_sketches"):
            return held
    from .document import Document
    doc = Document.load(path)
    doc.rebuild()
    return doc


def profile_face(kind: str, dims: Dict[str, float], source: str = ""):
    """The profile as a face on XY."""
    if kind == "angle":
        return equal_angle(dims["b"], dims["t"], dims.get("r1", 0.0),
                           dims.get("r2", 0.0))
    if kind == "square_tube":
        return square_tube(dims["b"], dims["t"], dims.get("ro", 0.0))
    if kind == "sketch":
        doc = _open_part(source)
        for name, value in dims.items():
            try:
                doc.set_parameter(name, repr(float(value)))
            except Exception:
                raise KernelError("the profile sketch has nothing called %s"
                                  % name)
        doc.rebuild()
        sketches = list(doc.all_sketches().values())
        if not sketches:
            raise KernelError("the profile part has no sketch")
        sketch = sketches[0]
        faces = kernel.sketch_faces(sketch)
        if not faces:
            raise KernelError("the profile sketch is not closed")
        face = faces[0] if len(faces) == 1 else max(faces,
                                                    key=kernel.face_area)
        # into the sketch's own coordinates, on XY
        from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
        from OCP.gp import gp_Ax3, gp_Dir, gp_Trsf
        p = sketch.plane
        move = gp_Trsf()
        move.SetTransformation(gp_Ax3(gp_Pnt(*p.origin), gp_Dir(*p.normal),
                                      gp_Dir(*p.xdir)))
        return kernel.faces(BRepBuilderAPI_Transform(face, move,
                                                     True).Shape())[0]
    raise KernelError("there is no profile kind %s" % kind)


# where a member's line runs through its profile: a box's corners, edge
# middles and middle, as Inventor's nine points
ANCHORS = ("tl", "tc", "tr", "ml", "mc", "mr", "bl", "bc", "br")


def anchor_point(face, anchor: str) -> Tuple[float, float]:
    x0, y0, _z0, x1, y1, _z1 = kernel.bounding_box(face)
    xs = {"l": x0, "c": (x0 + x1) / 2.0, "r": x1}
    ys = {"b": y0, "m": (y0 + y1) / 2.0, "t": y1}
    return xs[anchor[1]], ys[anchor[0]]


# ------------------------------------------------------------- the frame


@dataclass
class Member:
    """One frame member: the skeleton lines it runs along (one, or a
    straight run of several merged), its profile and how it sits."""

    id: int = 0
    sketch: int = 0             # the skeleton sketch its lines are in
    lines: List[int] = field(default_factory=list)
    family: str = ""
    size: str = ""
    anchor: str = "mc"
    offset_a: float = 0.0
    offset_b: float = 0.0
    rotate: float = 0.0
    mirror: bool = False
    material: str = ""
    part: str = ""              # the member's part file, from the frame's
    occurrence: int = 0
    error: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {"id": self.id, "sketch": self.sketch,
                "lines": list(self.lines),
                "family": self.family, "size": self.size,
                "anchor": self.anchor, "offset_a": self.offset_a,
                "offset_b": self.offset_b, "rotate": self.rotate,
                "mirror": self.mirror, "material": self.material,
                "part": self.part, "occurrence": self.occurrence}

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Member":
        return cls(id=int(d.get("id", 0)),
                   sketch=int(d.get("sketch", 0)),
                   lines=[int(x) for x in d.get("lines", [])],
                   family=str(d.get("family", "")),
                   size=str(d.get("size", "")),
                   anchor=str(d.get("anchor", "mc")),
                   offset_a=float(d.get("offset_a", 0.0)),
                   offset_b=float(d.get("offset_b", 0.0)),
                   rotate=float(d.get("rotate", 0.0)),
                   mirror=bool(d.get("mirror", False)),
                   material=str(d.get("material", "")),
                   part=str(d.get("part", "")),
                   occurrence=int(d.get("occurrence", 0)))


@dataclass
class FrameDefinition:
    """What makes a frame assembly a frame: its skeleton (a part file and
    the sketch in it) and its members."""

    skeleton: str = ""          # the skeleton part, relative to the frame
    sketch: int = 0             # the sketch feature's id in that part
    sketch_name: str = ""
    members: List[Member] = field(default_factory=list)
    treatments: List["Treatment"] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {"skeleton": self.skeleton, "sketch": self.sketch,
                "sketch_name": self.sketch_name,
                "members": [m.to_dict() for m in self.members],
                "treatments": [t.to_dict() for t in self.treatments]}

    def member(self, member_id: int) -> Optional[Member]:
        return next((m for m in self.members if m.id == member_id), None)

    @classmethod
    def from_dict(cls, d: Optional[Dict[str, Any]]
                  ) -> Optional["FrameDefinition"]:
        if not isinstance(d, dict):
            return None
        return cls(skeleton=str(d.get("skeleton", "")),
                   sketch=int(d.get("sketch", 0)),
                   sketch_name=str(d.get("sketch_name", "")),
                   members=[Member.from_dict(m) for m in d.get("members", [])],
                   treatments=[Treatment.from_dict(t)
                               for t in d.get("treatments", [])])


def skeleton_sketches(path: str) -> Dict[int, Tuple[Any, str, Dict[int, Any]]]:
    """Every sketch of a skeleton part as it stands now, by its feature's
    id: (its plane, its name, {line id: (start, end)} in the part's
    coordinates)."""
    doc = _open_part(path)
    out = {}
    for sketch_id, sketch in doc.all_sketches().items():
        lines = {}
        for eid, entity in sketch.entities.items():
            if entity.kind != "line" or entity.construction:
                continue
            a = sketch.points[entity.points[0]]
            b = sketch.points[entity.points[1]]
            lines[eid] = (sketch.plane.to_3d(a.x, a.y),
                          sketch.plane.to_3d(b.x, b.y))
        owner = doc.feature(sketch_id)
        out[sketch_id] = (sketch.plane, getattr(owner, "name", sketch.name),
                          lines)
    return out


def skeleton_lines(path: str, sketch_id: int, sketch_name: str = ""):
    """One skeleton sketch's lines: (its plane, {line id: (start, end)})."""
    sketches = skeleton_sketches(path)
    found = sketches.get(sketch_id)
    if found is None and sketch_name:
        found = next((s for s in sketches.values() if s[1] == sketch_name),
                     None)
    if found is None:
        raise KernelError("the skeleton has no sketch %s"
                          % (sketch_name or sketch_id))
    return found[0], found[2]


def run_of(lines, ids: Sequence[int]):
    """The two ends of a member's lines: one line's, or a straight run of
    several merged into one."""
    points = []
    for i in ids:
        if i not in lines:
            raise KernelError("a line it runs along is gone from the "
                              "skeleton")
        points += list(lines[i])
    if len(ids) == 1:
        return lines[ids[0]]
    a, b = lines[ids[0]]
    d = _unit(_sub(b, a))
    for p in points:
        off = _sub(p, a)
        across = _sub(off, _mul(d, _dot(off, d)))
        if math.sqrt(_dot(across, across)) > 1e-6:
            raise KernelError("merged lines must run in one straight line")
    along = sorted(points, key=lambda p: _dot(_sub(p, a), d))
    return along[0], along[-1]


def mergeable_runs(lines, ids: Sequence[int]) -> List[List[int]]:
    """Merge Frame Members: the picked lines grouped into straight runs,
    each run touching end to end, in the order they were picked."""
    left = list(ids)
    runs = []
    while left:
        run = [left.pop(0)]
        grown = True
        while grown:
            grown = False
            for other in list(left):
                try:
                    run_of(lines, run + [other])
                except KernelError:
                    continue
                ends = [p for i in run for p in lines[i]]
                if any(math.dist(p, q) < 1e-6 for p in ends
                       for q in lines[other]):
                    run.append(other)
                    left.remove(other)
                    grown = True
        runs.append(run)
    return runs


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _mul(a, k):
    return (a[0] * k, a[1] * k, a[2] * k)


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def _unit(a):
    n = math.sqrt(_dot(a, a)) or 1.0
    return (a[0] / n, a[1] / n, a[2] / n)


def member_frame(start, end, plane_normal, rotate_deg: float = 0.0):
    """The member's axes in the skeleton: Z along the line, Y up out of
    the skeleton's sketch plane (or across it, for a line standing on it),
    X across; turned ``rotate_deg`` about Z.  Columns X, Y, Z."""
    import numpy as np
    z = _unit(_sub(end, start))
    up = _unit(plane_normal)
    if abs(_dot(up, z)) > 0.99:
        # a leg, standing on the plane: its Y keeps to the plane's X
        up = (1.0, 0.0, 0.0) if abs(z[0]) < 0.9 else (0.0, 1.0, 0.0)
        up = _unit(_sub(up, _mul(z, _dot(up, z))))
    y = _unit(_sub(up, _mul(z, _dot(up, z))))
    x = _cross(y, z)
    a = math.radians(rotate_deg)
    c, s = math.cos(a), math.sin(a)
    x, y = (tuple(c * x[i] + s * y[i] for i in range(3)),
            tuple(-s * x[i] + c * y[i] for i in range(3)))
    return np.array([x, y, z]).T


def member_placement(member: Member, face, start, end, plane_normal):
    """Where a member's part sits in the frame: its profile's anchor on
    the line's start, offset, turned, the part's Z along the line."""
    import numpy as np
    from .constraints3d import Placement, rotation_vector
    m = member_frame(start, end, plane_normal, member.rotate)
    ax, ay = anchor_point(face, member.anchor)
    local = np.array([ax - member.offset_a, ay - member.offset_b, 0.0])
    position = np.array(start, dtype=float) - m @ local
    return Placement([float(c) for c in position],
                     [float(c) for c in rotation_vector(m)])


def member_part_name(member: Member, fam: ProfileFamily) -> str:
    stem = re.sub(r"[^A-Za-z0-9_.-]+", " ", "%s %s" % (
        fam.standard or fam.name, member.size)).strip()
    return "%s %05d" % (stem, member.id)


def write_member_part(path: str, member: Member, fam: ProfileFamily,
                      length: float, ends: Optional[Dict[str, Any]] = None
                      ) -> bool:
    """The member's part: one Frame Member feature, the profile run the
    length, its ends as the end treatments leave them.  Written only when
    something in it changed; True when it was."""
    from .document import Document
    from .features import FrameMemberFeature
    dims = fam.row(member.size)
    ends = ends or {}
    wanted = {"family": fam.id, "size": member.size, "kind": fam.kind,
              "dims": dims, "length": "%.6f" % length,
              "mirror": member.mirror,
              "source": fam.source,
              "extend_a": float(ends.get("extend_a", 0.0)),
              "extend_b": float(ends.get("extend_b", 0.0)),
              "cuts": [list(c) for c in ends.get("cuts", [])],
              "notches": [dict(n) for n in ends.get("notches", [])]}
    if os.path.exists(path):
        try:
            doc = Document.load(path)
            current = next((f for f in doc.features
                            if isinstance(f, FrameMemberFeature)), None)
            if current is not None and all(
                    getattr(current, k) == v for k, v in wanted.items()):
                return False
        except Exception:
            pass
    doc = Document()
    feature = FrameMemberFeature(name="%s %s" % (fam.standard or fam.name,
                                                 member.size))
    for key, value in wanted.items():
        setattr(feature, key, value)
    doc.add_feature(feature)
    if member.material:
        doc.material = member.material
    doc.properties["Description"] = "%s %s" % (fam.name, member.size)
    doc.properties["Stock Number"] = member.size
    doc.rebuild()
    # the length to cut it to: the longest it is, ends and all
    shape = getattr(doc, "shape", None)
    cut_length = length
    if shape is not None and not shape.IsNull():
        box = kernel.bounding_box(shape)
        cut_length = box[5] - box[2]
    doc.properties["Length"] = "%.3f" % cut_length
    doc.save(path)
    return True


def sync(frame_doc) -> List[str]:
    """Bring a frame assembly's members up to its skeleton as it is now:
    each member's part at its line's length, and its place on the line.
    Returns what went wrong, member by member."""
    fd = frame_doc.frame
    if fd is None:
        return []
    base = frame_doc.base_dir
    skeleton = os.path.normpath(os.path.join(base, fd.skeleton)) \
        if base and not os.path.isabs(fd.skeleton) else fd.skeleton
    problems = []
    try:
        sketches = skeleton_sketches(skeleton)
    except Exception as exc:
        for member in fd.members:
            member.error = "the skeleton cannot be read: %s" % exc
        return [str(exc)]
    by_id = {o.id: o for o in frame_doc.occurrences}
    frame_doc.frame_changed = False
    geos = member_geometries(fd, sketches, problems)
    ends = resolve(fd, geos, problems)
    for member in fd.members:
        if member.id not in geos:
            continue
        try:
            geo = geos[member.id]
            fam = geo.fam
            length = geo.length
            if not member.part:
                member.part = member_part_name(member, fam) + ".icpart"
            path = os.path.join(base, member.part) if base else member.part
            if write_member_part(path, member, fam, length,
                                 ends.get(member.id)):
                frame_doc.frame_changed = True
            occurrence = by_id.get(member.occurrence)
            if occurrence is None:
                occurrence = frame_doc.place(path)
                member.occurrence = occurrence.id
                frame_doc.frame_changed = True
            occurrence.grounded = True
            placed = geo.placement
            if (occurrence.placement.to_dict() != placed.to_dict()):
                occurrence.placement = placed
                frame_doc.frame_changed = True
        except (KernelError, KeyError, ValueError) as exc:
            member.error = str(exc)
            problems.append("member %d: %s" % (member.id, exc))
    return problems


def member_geometries(fd: FrameDefinition, sketches, problems: List[str]
                      ) -> Dict[int, "MemberGeometry"]:
    """Each member as the skeleton places it now, by its id; what cannot
    be placed is told in ``problems`` and on the member."""
    out = {}
    for member in fd.members:
        member.error = ""
        try:
            fam = family(member.family)
            found = sketches.get(member.sketch or fd.sketch)
            if found is None:
                raise KernelError("its sketch is gone from the skeleton")
            plane, _name, lines = found
            start, end = run_of(lines, member.lines)
            if math.dist(start, end) < 1e-6:
                raise KernelError("its line has no length")
            out[member.id] = MemberGeometry(member, fam, start, end,
                                            plane.normal)
        except (KernelError, KeyError, ValueError) as exc:
            member.error = str(exc)
            problems.append("member %d: %s" % (member.id, exc))
    return out


_FRAME_CACHE: Dict[str, Tuple[float, Optional[FrameDefinition]]] = {}


def read_frame(path: str) -> Optional[FrameDefinition]:
    """A frame assembly's definition, read once per change of the file;
    None for an assembly that is not a frame."""
    from . import fileformat
    try:
        stamp = os.path.getmtime(path)
    except OSError:
        return None
    key = os.path.normcase(os.path.abspath(path))
    held = _FRAME_CACHE.get(key)
    if held is not None and held[0] == stamp:
        return held[1]
    try:
        fd = FrameDefinition.from_dict(
            (fileformat.read(path).geometry or {}).get("frame"))
    except Exception:
        fd = None
    _FRAME_CACHE[key] = (stamp, fd)
    return fd


def is_frame(path: str) -> bool:
    """Whether an assembly file is a frame assembly."""
    return read_frame(path) is not None


_MEMBER_CACHE: Dict[str, Tuple[float, bool]] = {}


def is_member_part(path: str) -> bool:
    """Whether a part file is a frame member's, made by the Frame
    Generator."""
    from . import fileformat
    try:
        stamp = os.path.getmtime(path)
    except OSError:
        return False
    key = os.path.normcase(os.path.abspath(path))
    held = _MEMBER_CACHE.get(key)
    if held is not None and held[0] == stamp:
        return held[1]
    try:
        features = (fileformat.read(path).geometry or {}).get("features", [])
        found = any(isinstance(f, dict) and f.get("type") == "frame_member"
                    for f in features)
    except Exception:
        found = False
    _MEMBER_CACHE[key] = (stamp, found)
    return found


def refresh(path: str) -> List[str]:
    """A frame assembly brought up to its skeleton, and saved when that
    changed anything: what an assembly placing it does before it builds,
    so a skeleton edited since moves the members."""
    from .assembly import AssemblyDocument
    frame_doc = AssemblyDocument.load(path)
    problems = sync(frame_doc)
    if getattr(frame_doc, "frame_changed", False):
        frame_doc.save(path)
    return problems


def insert(parent, skeleton_occurrence, sketch_id: int, line_ids,
           family_id: str, size: str, anchor: str = "mc",
           offset_a: float = 0.0, offset_b: float = 0.0, rotate: float = 0.0,
           mirror: bool = False, merge: bool = False, material: str = "",
           frame_occurrence=None):
    """Insert Frame: members on the picked skeleton lines.  The first
    insert on a skeleton makes the frame assembly, beside the parent in a
    folder of its own, and places it in the parent following the
    skeleton; later ones add to it.  Returns the frame assembly."""
    from .assembly import AssemblyDocument
    if not parent.path:
        raise ValueError("save the assembly first: the frame's files go "
                         "beside it")
    fam = family(family_id)
    fam.row(size)
    skeleton = parent.component_path(skeleton_occurrence)
    if skeleton is None:
        raise ValueError("the skeleton's file cannot be found")
    sketches = skeleton_sketches(skeleton)
    if sketch_id not in sketches:
        raise ValueError("the skeleton has no sketch %s" % sketch_id)
    if frame_occurrence is not None:
        frame_path = parent.component_path(frame_occurrence)
        frame_doc = AssemblyDocument.load(frame_path)
    else:
        number = 1
        while os.path.exists(os.path.join(parent.base_dir, "Frames",
                                          "Frame%04d" % number)):
            number += 1
        folder = os.path.join(parent.base_dir, "Frames", "Frame%04d" % number)
        os.makedirs(folder)
        frame_doc = AssemblyDocument()
        frame_doc.path = os.path.join(folder, "Frame%04d.icasm" % number)
        frame_doc.frame = FrameDefinition(
            skeleton=os.path.relpath(skeleton, folder).replace(os.sep, "/"),
            sketch=sketch_id, sketch_name=sketches[sketch_id][1])
    fd = frame_doc.frame
    lines = sketches[sketch_id][2]
    runs = mergeable_runs(lines, list(line_ids)) if merge \
        else [[i] for i in line_ids]
    next_id = max([m.id for m in fd.members] + [0]) + 1
    for run in runs:
        fd.members.append(Member(id=next_id, sketch=sketch_id, lines=run,
                                 family=family_id,
                                 size=size, anchor=anchor,
                                 offset_a=offset_a, offset_b=offset_b,
                                 rotate=rotate, mirror=mirror,
                                 material=material))
        next_id += 1
    problems = sync(frame_doc)
    frame_doc.save(frame_doc.path)
    if frame_occurrence is None:
        frame_occurrence = parent.place(frame_doc.path)
        frame_occurrence.grounded = True
    frame_occurrence.follows = skeleton_occurrence.id
    frame_occurrence.placement = skeleton_occurrence.placement.copy()
    parent.modified = True
    return frame_doc, frame_occurrence, problems


# ------------------------------------------------------- end treatments
#
# Inventor's Frame panel: Miter, Corner Joint, Trim - Extend To Face, Notch
# and Lengthen - Shorten.  Each is kept in the frame, by the members it
# joins, and worked out afresh from the skeleton every time the frame is
# brought up to it, so a treated corner follows a sketch edit as the bare
# members do.  What a treatment does to a member lands in that member's
# part: how far each end runs past its line, the planes it is cut off at,
# and the shapes notched out of it.  A later treatment on the same end of a
# member replaces an earlier one there, as Inventor's does; a Lengthen -
# Shorten adds to whatever the end has.

TREATMENTS = ("miter", "corner", "trim_face", "notch", "lengthen")


@dataclass
class Treatment:
    id: int = 0
    kind: str = "miter"
    members: List[int] = field(default_factory=list)
    others: List[int] = field(default_factory=list)
    params: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {"id": self.id, "kind": self.kind,
                "members": list(self.members), "others": list(self.others),
                "params": dict(self.params)}

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Treatment":
        return cls(id=int(d.get("id", 0)), kind=str(d.get("kind", "miter")),
                   members=[int(x) for x in d.get("members", [])],
                   others=[int(x) for x in d.get("others", [])],
                   params=dict(d.get("params") or {}))


def built_face(kind: str, dims: Dict[str, float], source: str = "",
               mirror: bool = False):
    """The profile as a member's part has it: mirrored if it is."""
    face = profile_face(kind, dims, source)
    if mirror:
        from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
        from OCP.gp import gp_Ax2, gp_Dir, gp_Trsf
        flip = gp_Trsf()
        flip.SetMirror(gp_Ax2(gp_Pnt(0, 0, 0), gp_Dir(1, 0, 0)))
        face = kernel.faces(BRepBuilderAPI_Transform(face, flip,
                                                     True).Shape())[0]
    return face


def _samples(face, per_edge: int = 12) -> List[Tuple[float, float]]:
    """Points round a profile's edges, enough to find how far it reaches
    in any direction."""
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.TopAbs import TopAbs_EDGE
    from OCP.TopoDS import TopoDS
    out = []
    for edge in kernel.explore(face, TopAbs_EDGE):
        curve = BRepAdaptor_Curve(TopoDS.Edge_s(edge))
        u0, u1 = curve.FirstParameter(), curve.LastParameter()
        for i in range(per_edge + 1):
            p = curve.Value(u0 + (u1 - u0) * i / per_edge)
            out.append((p.X(), p.Y()))
    return out


class MemberGeometry:
    """A member as the skeleton places it: its line, its axes, where its
    part sits, and its profile in the part's own coordinates."""

    def __init__(self, member: Member, fam: "ProfileFamily", start, end,
                 normal) -> None:
        import numpy as np
        self.member = member
        self.fam = fam
        self.start = tuple(float(c) for c in start)
        self.end = tuple(float(c) for c in end)
        self.length = math.dist(self.start, self.end)
        self.dir = _unit(_sub(self.end, self.start))
        self.normal = normal
        dims = fam.row(member.size)
        self.dims = dims
        plain = profile_face(fam.kind, dims, fam.source)
        self.face = built_face(fam.kind, dims, fam.source, member.mirror)
        self.placement = member_placement(member, plain, self.start,
                                          self.end, normal)
        self.m = self.placement.matrix()
        self.pos = np.array(self.placement.position, dtype=float)
        ax, ay = anchor_point(plain, member.anchor)
        self.line_xy = (ax - member.offset_a, ay - member.offset_b)
        self.points = _samples(self.face)
        self.reach = max(math.hypot(x - self.line_xy[0], y - self.line_xy[1])
                         for x, y in self.points) if self.points else 0.0

    def to_local(self, w):
        import numpy as np
        return tuple(float(c) for c in self.m.T @ (np.asarray(w, float)
                                                   - self.pos))

    def dir_local(self, d):
        import numpy as np
        return tuple(float(c) for c in self.m.T @ np.asarray(d, float))

    def to_world(self, q):
        import numpy as np
        return tuple(float(c) for c in self.pos + self.m @ np.asarray(q,
                                                                      float))

    def dir_world(self, d):
        import numpy as np
        return tuple(float(c) for c in self.m @ np.asarray(d, float))

    def end_point(self, end: str):
        return self.start if end == "a" else self.end

    def outward(self, end: str):
        return _mul(self.dir, -1.0) if end == "a" else self.dir

    def nearer_end(self, point) -> str:
        return "a" if math.dist(self.start, point) <= math.dist(
            self.end, point) else "b"

    def face_plane(self, toward, far: bool = False):
        """The plane of this member's side facing ``toward`` (a world
        direction), or the far side: (a point, the direction out of it),
        both in the world, running along the member."""
        u = self.dir_local(toward)
        ux, uy = u[0], u[1]
        n = math.hypot(ux, uy)
        if n < 1e-9:
            raise KernelError("the members run the same way")
        ux, uy = ux / n, uy / n
        reach = [x * ux + y * uy for x, y in self.points]
        s = min(reach) if far else max(reach)
        point = self.to_world((s * ux, s * uy, 0.0))
        out = self.dir_world((ux, uy, 0.0))
        return point, (out if not far else _mul(out, -1.0))


def _closest(a0, da, b0, db):
    """The nearest points of two lines, and their parameters."""
    w = _sub(a0, b0)
    a, b, c = _dot(da, da), _dot(da, db), _dot(db, db)
    d, e = _dot(da, w), _dot(db, w)
    den = a * c - b * b
    if abs(den) < 1e-12:
        raise KernelError("the members are parallel")
    s = (b * e - c * d) / den
    t = (a * e - b * d) / den
    pa = tuple(a0[i] + s * da[i] for i in range(3))
    pb = tuple(b0[i] + t * db[i] for i in range(3))
    return pa, pb, s, t


def _reach_to(geo: MemberGeometry, end: str, point, cut) -> float:
    """How far an end must run past its line for all of its profile to
    get to the plane through ``point`` with ``cut`` the side cut away."""
    out = geo.outward(end)
    c = _dot(out, cut)
    if c < 0.05:
        raise KernelError("member %d does not run into that plane"
                          % geo.member.id)
    t = _dot(_sub(point, geo.end_point(end)), cut) / c
    spread = geo.reach * math.sqrt(max(0.0, 1.0 - c * c)) / c
    return max(0.0, t + spread + 1.0)


def _corner_of(a: MemberGeometry, b: MemberGeometry):
    """Where two members meet: the point, the end of each at it, and each
    one's direction from it into its own length."""
    pa, pb, _s, _t = _closest(a.start, a.dir, b.start, b.dir)
    corner = tuple((pa[i] + pb[i]) / 2.0 for i in range(3))
    ea, eb = a.nearer_end(corner), b.nearer_end(corner)
    return corner, ea, eb, _mul(a.outward(ea), -1.0), \
        _mul(b.outward(eb), -1.0)


def _miter(a, b, gap: float, split: bool):
    corner, ea, eb, da, db = _corner_of(a, b)
    n = _sub(da, db)
    if math.sqrt(_dot(n, n)) < 1e-9:
        raise KernelError("members %d and %d run on in one line"
                          % (a.member.id, b.member.id))
    n = _unit(n)
    ga, gb = (gap / 2.0, gap / 2.0) if split else (gap, 0.0)
    pa = tuple(corner[i] + n[i] * ga for i in range(3))
    pb = tuple(corner[i] - n[i] * gb for i in range(3))
    return [(a, ea, pa, _mul(n, -1.0)), (b, eb, pb, n)]


def _corner_joint(a, b, gap: float, extend: bool):
    """``a`` trimmed to ``b``'s near side, ``b`` run on to ``a``'s far
    side: a butt joint."""
    corner, ea, eb, da, db = _corner_of(a, b)
    point, out = b.face_plane(da)
    point = tuple(point[i] + out[i] * gap for i in range(3))
    cuts = [(a, ea, point, _mul(out, -1.0))]
    if extend:
        far, far_out = a.face_plane(db, far=True)
        cuts.append((b, eb, far, far_out))
    return cuts


def _trim_face(geo, point, normal, offset: float):
    """A member's nearer end run to, or cut back to, a plane."""
    n = _unit(normal)
    t = [_dot(_sub(geo.end_point(e), point), n) for e in ("a", "b")]
    # the end nearer the plane, and the side of it away from the member
    end = "a" if abs(t[0]) <= abs(t[1]) else "b"
    keep = t[1] if end == "a" else t[0]
    cut = n if keep < 0 else _mul(n, -1.0)
    p = tuple(point[i] - cut[i] * offset for i in range(3))
    return [(geo, end, p, cut)]


def resolve(fd: "FrameDefinition", geos: Dict[int, MemberGeometry],
            problems: List[str]) -> Dict[int, Dict[str, Any]]:
    """Every member's ends as the treatments leave them: how far each runs
    past its line, the planes it is cut off at, in its part's coordinates,
    and what is notched out of it."""
    ends: Dict[int, Dict[str, Any]] = {
        mid: {"cut": {}, "shift": {"a": 0.0, "b": 0.0}, "notch": []}
        for mid in geos}
    notches = []
    for t in fd.treatments:
        try:
            p = t.params
            gap = float(p.get("gap", 0.0))
            cuts = []
            if t.kind == "miter":
                for a_id, b_id in zip(t.members[0::2], t.members[1::2]):
                    cuts += _miter(geos[a_id], geos[b_id], gap,
                                   bool(p.get("split", True)))
            elif t.kind == "corner":
                for a_id in t.members:
                    for b_id in t.others:
                        cuts += _corner_joint(geos[a_id], geos[b_id], gap,
                                              bool(p.get("extend", True)))
            elif t.kind == "trim_face":
                for a_id in t.members:
                    cuts += _trim_face(geos[a_id], p["point"], p["normal"],
                                       float(p.get("offset", 0.0)))
            elif t.kind == "notch":
                notches.append(t)
            elif t.kind == "lengthen":
                amount = float(p.get("amount", 0.0))
                side = p.get("side", "b")
                for mid in t.members:
                    shift = ends[mid]["shift"]
                    if side == "both":
                        shift["a"] += amount / 2.0
                        shift["b"] += amount / 2.0
                    else:
                        shift[side] += amount
            for geo, end, point, cut in cuts:
                ends[geo.member.id]["cut"][end] = (point, cut)
        except (KeyError, KernelError, ValueError, TypeError) as exc:
            problems.append("%s %d: %s" % (t.kind, t.id, exc))
    out: Dict[int, Dict[str, Any]] = {}
    for mid, geo in geos.items():
        e = ends[mid]
        ext = {"a": e["shift"]["a"], "b": e["shift"]["b"]}
        planes = []
        for end, (point, cut) in e["cut"].items():
            try:
                ext[end] = _reach_to(geo, end, point, cut) + e["shift"][end]
            except KernelError as exc:
                problems.append(str(exc))
                continue
            # a lengthened end takes its cut along with it
            moved = _mul(geo.outward(end), e["shift"][end])
            point = tuple(point[i] + moved[i] for i in range(3))
            planes.append([round(c, 6) for c in geo.to_local(point)]
                          + [round(c, 9) for c in geo.dir_local(cut)])
        out[mid] = {"extend_a": round(ext["a"], 6),
                    "extend_b": round(ext["b"], 6),
                    "cuts": planes, "notches": []}
    for t in notches:
        for a_id in t.members:
            for b_id in t.others:
                try:
                    _notch(geos[a_id], geos[b_id], out,
                           float(t.params.get("gap", 0.0)))
                except (KeyError, KernelError) as exc:
                    problems.append("notch %d: %s" % (t.id, exc))
    return out


def _notch(a: MemberGeometry, b: MemberGeometry, out, gap: float) -> None:
    """``b``'s outline cut out of ``a``; when ``b`` crosses ``a`` at its
    end, ``a``'s end run on to ``b``'s far side first."""
    _pa, _pb, s, _t = _closest(a.start, a.dir, b.start, b.dir)
    near_end = None
    if s < b.reach + 1.0:
        near_end = "a"
    elif s > a.length - b.reach - 1.0:
        near_end = "b"
    if near_end is not None:
        into = _mul(a.outward(near_end), -1.0)
        far, far_out = b.face_plane(into, far=True)
        ext = _reach_to(a, near_end, far, far_out)
        key = "extend_a" if near_end == "a" else "extend_b"
        out[a.member.id][key] = round(max(out[a.member.id][key], ext), 6)
        out[a.member.id]["cuts"].append(
            [round(c, 6) for c in a.to_local(far)]
            + [round(c, 9) for c in a.dir_local(far_out)])
    nb = out[b.member.id]
    # b's part coordinates into a's
    rot = a.m.T @ b.m
    move = a.m.T @ (b.pos - a.pos)
    matrix = [float(rot[i, j]) for i in range(3) for j in range(3)] + \
        [float(c) for c in move]
    out[a.member.id]["notches"].append({
        "kind": b.fam.kind, "dims": dict(b.dims), "source": b.fam.source,
        "mirror": b.member.mirror, "gap": gap,
        "z0": -nb["extend_a"], "z1": b.length + nb["extend_b"],
        "matrix": [round(c, 9) for c in matrix]})


def notch_tool(n: Dict[str, Any]):
    """A notching member's outline, grown by the gap and filled, run its
    length, in the notched member's coordinates."""
    from OCP.BRepBuilderAPI import (BRepBuilderAPI_MakeFace,
                                    BRepBuilderAPI_Transform)
    from OCP.BRepOffsetAPI import BRepOffsetAPI_MakeOffset
    from OCP.BRepTools import BRepTools
    from OCP.GeomAbs import GeomAbs_Arc
    from OCP.gp import gp_Trsf
    face = built_face(n["kind"], n["dims"], n.get("source", ""),
                      bool(n.get("mirror", False)))
    outer = BRepTools.OuterWire_s(face)
    gap = float(n.get("gap", 0.0))
    if gap > 1e-9:
        grow = BRepOffsetAPI_MakeOffset(outer, GeomAbs_Arc)
        grow.Perform(gap)
        from OCP.TopAbs import TopAbs_WIRE
        from OCP.TopoDS import TopoDS
        outer = TopoDS.Wire_s(kernel.explore(grow.Shape(), TopAbs_WIRE)[0])
    filled = BRepBuilderAPI_MakeFace(outer, True).Face()
    z0, z1 = float(n["z0"]), float(n["z1"])
    solid = kernel.extrude(kernel.translate(filled, (0.0, 0.0, z0)),
                           (0.0, 0.0, 1.0), z1 - z0)
    m = n["matrix"]
    trsf = gp_Trsf()
    trsf.SetValues(m[0], m[1], m[2], m[9], m[3], m[4], m[5], m[10],
                   m[6], m[7], m[8], m[11])
    return BRepBuilderAPI_Transform(solid, trsf, True).Shape()


def half_space(cut: Sequence[float]):
    """What a cut plane takes away: everything past it, as a solid."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeHalfSpace
    from OCP.gp import gp_Dir, gp_Pln
    p, n = cut[:3], cut[3:6]
    face = BRepBuilderAPI_MakeFace(gp_Pln(gp_Pnt(*p), gp_Dir(*n))).Face()
    ref = gp_Pnt(p[0] + n[0], p[1] + n[1], p[2] + n[2])
    return BRepPrimAPI_MakeHalfSpace(face, ref).Solid()


def member_solid(kind, dims, source, mirror, length, extend_a=0.0,
                 extend_b=0.0, cuts=(), notches=()):
    """A member as its part builds it, in the part's coordinates."""
    face = built_face(kind, dims, source, mirror)
    total = length + extend_a + extend_b
    if total <= 1e-6:
        raise KernelError("it is shortened to nothing")
    solid = kernel.extrude(kernel.translate(face, (0.0, 0.0, -extend_a)),
                           (0.0, 0.0, 1.0), total)
    for cut in cuts:
        solid = kernel.boolean(solid, half_space(cut), "cut")
    for n in notches:
        solid = kernel.boolean(solid, notch_tool(n), "cut")
    return solid


# ----------------------------------------------- changing a frame after

CHANGEABLE = ("family", "size", "anchor", "offset_a", "offset_b", "rotate",
              "mirror", "material")


def change_members(frame_doc, member_ids: Sequence[int], **fields
                   ) -> List[str]:
    """Change Frame: new values for some members, the rest left as they
    are.  A member that changes family or size gets a part named for what
    it is now, and the old one goes.  Returns what went wrong."""
    fd = frame_doc.frame
    if fd is None:
        raise ValueError("that is not a frame")
    unknown = set(fields) - set(CHANGEABLE)
    if unknown:
        raise ValueError("cannot change %s" % ", ".join(sorted(unknown)))
    if "family" in fields or "size" in fields:
        fam = family(fields.get("family") or fd.member(member_ids[0]).family)
        if "size" in fields:
            fam.row(fields["size"])
    base = frame_doc.base_dir
    for mid in member_ids:
        member = fd.member(mid)
        if member is None:
            continue
        renamed = any(k in fields and fields[k] != getattr(member, k)
                      for k in ("family", "size"))
        for key, value in fields.items():
            setattr(member, key, value)
        if renamed and member.part:
            old = os.path.join(base, member.part) if base else member.part
            if member.occurrence:
                frame_doc.remove_occurrence(member.occurrence)
            member.occurrence = 0
            member.part = ""
            try:
                os.remove(old)
            except OSError:
                pass
    problems = sync(frame_doc)
    frame_doc.save(frame_doc.path)
    return problems


def add_treatment(frame_doc, kind: str, members: Sequence[int],
                  others: Sequence[int] = (), **params) -> Tuple[
                      "Treatment", List[str]]:
    """An end treatment on some members, kept in the frame and made
    straight away.  Returns it and what went wrong."""
    fd = frame_doc.frame
    if fd is None:
        raise ValueError("that is not a frame")
    if kind not in TREATMENTS:
        raise ValueError("there is no end treatment %s" % kind)
    known = {m.id for m in fd.members}
    for mid in list(members) + list(others):
        if mid not in known:
            raise ValueError("the frame has no member %d" % mid)
    if kind == "miter" and (len(members) < 2 or len(members) % 2):
        raise ValueError("a miter joins members two by two")
    if kind in ("corner", "notch") and not (members and others):
        raise ValueError("pick the members to cut and the ones they meet")
    if kind == "trim_face" and ("point" not in params
                                or "normal" not in params):
        raise ValueError("pick the face to trim or extend to")
    treatment = Treatment(id=max([t.id for t in fd.treatments] + [0]) + 1,
                          kind=kind, members=list(members),
                          others=list(others), params=dict(params))
    fd.treatments.append(treatment)
    problems = sync(frame_doc)
    frame_doc.save(frame_doc.path)
    return treatment, problems


def remove_treatments(frame_doc, member_ids: Sequence[int]) -> int:
    """Remove End Treatments: every treatment on these members goes, and
    the members are as Insert Frame made them again.  Returns how many."""
    fd = frame_doc.frame
    picked = set(member_ids)
    keep = [t for t in fd.treatments
            if not (picked & (set(t.members) | set(t.others)))]
    gone = len(fd.treatments) - len(keep)
    fd.treatments = keep
    sync(frame_doc)
    frame_doc.save(frame_doc.path)
    return gone


def treatments_on(fd: "FrameDefinition", member_id: int) -> List["Treatment"]:
    return [t for t in fd.treatments
            if member_id in t.members or member_id in t.others]


def member_world_solids(frame_doc, member_ids: Optional[Sequence[int]] = None,
                        changes: Optional[Dict[str, Any]] = None,
                        extra: Optional["Treatment"] = None):
    """{member id: its solid where it sits in the frame}, the treatments
    worked out, as they would be with ``changes`` made to those members
    and ``extra`` added to the treatments: what a preview shows before
    anything is written."""
    import copy as _copy
    fd = _copy.deepcopy(frame_doc.frame)
    if fd is None:
        return {}
    if changes:
        for mid in member_ids or []:
            member = fd.member(mid)
            for key, value in changes.items():
                setattr(member, key, value)
    if extra is not None:
        fd.treatments.append(extra)
    base = frame_doc.base_dir
    skeleton = os.path.normpath(os.path.join(base, fd.skeleton)) \
        if base and not os.path.isabs(fd.skeleton) else fd.skeleton
    problems: List[str] = []
    geos = member_geometries(fd, skeleton_sketches(skeleton), problems)
    ends = resolve(fd, geos, problems)
    out = {}
    for mid in (member_ids if member_ids is not None else list(geos)):
        geo = geos.get(mid)
        if geo is None:
            continue
        e = ends.get(mid, {})
        try:
            solid = member_solid(geo.fam.kind, geo.dims, geo.fam.source,
                                 geo.member.mirror, geo.length,
                                 e.get("extend_a", 0.0), e.get("extend_b", 0.0),
                                 e.get("cuts", []), e.get("notches", []))
        except KernelError:
            continue
        out[mid] = solid.Moved(geo.placement.location())
    return out


def preview_solids(parent, skeleton_occurrence, line_ids_by_sketch,
                   family_id: str, size: str, anchor: str = "mc",
                   offset_a: float = 0.0, offset_b: float = 0.0,
                   rotate: float = 0.0, mirror: bool = False,
                   merge: bool = False):
    """The members Insert Frame would make, as solids where they would
    sit in the parent assembly, nothing written."""
    skeleton = parent.component_path(skeleton_occurrence)
    sketches = skeleton_sketches(skeleton)
    fam = family(family_id)
    fam.row(size)
    out = []
    location = skeleton_occurrence.placement.location()
    for sketch_id, line_ids in line_ids_by_sketch.items():
        found = sketches.get(sketch_id)
        if found is None:
            continue
        plane, _name, lines = found
        runs = mergeable_runs(lines, list(line_ids)) if merge \
            else [[i] for i in line_ids]
        for run in runs:
            member = Member(id=0, sketch=sketch_id, lines=run,
                            family=family_id, size=size, anchor=anchor,
                            offset_a=offset_a, offset_b=offset_b,
                            rotate=rotate, mirror=mirror)
            try:
                start, end = run_of(lines, run)
                geo = MemberGeometry(member, fam, start, end, plane.normal)
                solid = member_solid(fam.kind, geo.dims, fam.source, mirror,
                                     geo.length)
            except (KernelError, KeyError, ValueError):
                continue
            out.append(solid.Moved(geo.placement.location()).Moved(location))
    return out


def member_axes(frame_doc) -> Dict[int, Tuple[Any, Any, float]]:
    """{member id: (start, end, how far its profile reaches from it)}: the
    line down the middle of each member's profile, in the frame, for
    picking members in the view."""
    fd = frame_doc.frame
    if fd is None:
        return {}
    base = frame_doc.base_dir
    skeleton = os.path.normpath(os.path.join(base, fd.skeleton)) \
        if base and not os.path.isabs(fd.skeleton) else fd.skeleton
    out = {}
    for mid, geo in member_geometries(fd, skeleton_sketches(skeleton),
                                      []).items():
        x0, y0, _z0, x1, y1, _z1 = kernel.bounding_box(geo.face)
        cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
        reach = max(math.hypot(x - cx, y - cy) for x, y in geo.points)
        out[mid] = (geo.to_world((cx, cy, 0.0)),
                    geo.to_world((cx, cy, geo.length)), reach)
    return out
