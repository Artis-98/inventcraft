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

    def to_dict(self) -> Dict[str, Any]:
        return {"skeleton": self.skeleton, "sketch": self.sketch,
                "sketch_name": self.sketch_name,
                "members": [m.to_dict() for m in self.members]}

    @classmethod
    def from_dict(cls, d: Optional[Dict[str, Any]]
                  ) -> Optional["FrameDefinition"]:
        if not isinstance(d, dict):
            return None
        return cls(skeleton=str(d.get("skeleton", "")),
                   sketch=int(d.get("sketch", 0)),
                   sketch_name=str(d.get("sketch_name", "")),
                   members=[Member.from_dict(m) for m in d.get("members", [])])


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
                      length: float) -> bool:
    """The member's part: one Frame Member feature, the profile run the
    length.  Written only when something in it changed; True when it was."""
    from .document import Document
    from .features import FrameMemberFeature
    dims = fam.row(member.size)
    wanted = {"family": fam.id, "size": member.size, "kind": fam.kind,
              "dims": dims, "length": "%.6f" % length,
              "mirror": member.mirror,
              "source": fam.source}
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
    doc.properties["Length"] = "%.3f" % length
    doc.rebuild()
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
    for member in fd.members:
        member.error = ""
        try:
            fam = family(member.family)
            found = sketches.get(member.sketch or fd.sketch)
            if found is None:
                raise KernelError("its sketch is gone from the skeleton")
            plane, _name, lines = found
            start, end = run_of(lines, member.lines)
            length = math.dist(start, end)
            if length < 1e-6:
                raise KernelError("its line has no length")
            face = profile_face(fam.kind, fam.row(member.size), fam.source)
            if not member.part:
                member.part = member_part_name(member, fam) + ".icpart"
            path = os.path.join(base, member.part) if base else member.part
            if write_member_part(path, member, fam, length):
                frame_doc.frame_changed = True
            occurrence = by_id.get(member.occurrence)
            if occurrence is None:
                occurrence = frame_doc.place(path)
                member.occurrence = occurrence.id
                frame_doc.frame_changed = True
            occurrence.grounded = True
            placed = member_placement(member, face, start, end, plane.normal)
            if (occurrence.placement.to_dict() != placed.to_dict()):
                occurrence.placement = placed
                frame_doc.frame_changed = True
        except (KernelError, KeyError, ValueError) as exc:
            member.error = str(exc)
            problems.append("member %d: %s" % (member.id, exc))
    return problems


def is_frame(path: str) -> bool:
    """Whether an assembly file is a frame assembly."""
    from . import fileformat
    try:
        return bool((fileformat.read(path).geometry or {}).get("frame"))
    except Exception:
        return False


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
