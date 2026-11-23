"""Which feature made which face: the part's own memory of where faces came from.

A fingerprint (`naming.ShapeRef`) finds a face again by where it sits and how
big it is, and a parameter change of fifty per cent moves it out of reach. What
does not move is the *story*: this face is the end cap of Extrusion3, that one
is the wall of the first hole in Hole2. OpenCASCADE already knows the story,
because every operation says what each face it was given became (`Generated`,
`Modified`, `IsDeleted`). `kernel` hands that over as a :class:`History`;
this module folds it through the whole feature tree.

Each body carries a :class:`FaceTags`: for every face that has a role, the
roles it holds, as ``"<feature id>:<role>"`` strings (``"7:end"``,
``"7:side:e12"``, ``"9:wall:p3"``). A face may hold several (a boss fused
flush with a plate: one face, the roles of both), and a face a boolean split
gives every piece the roles of the face it came from. Roles are kept by
feature *id* and by sketch entity or point *id*, so renaming a feature or
adding an entity before another does not disturb them.

What is kept is an *index map*, never a shape handle: ``{role: [face index]}``
with a small fingerprint of each face as a check, written beside the body
wherever a body travels (a worker's answer, the body cache). A tag set is only
ever trusted for the very shape it was made for, so a feature that changes a
body and says nothing about it costs the roles on the faces it touched, never
a wrong answer: the tags are carried over by geometry
(:meth:`FaceTags.transfer`) or dropped.

Two ways a face is *found* again from a role, in :func:`faces_with`: by this
map, and, where a ref carries one, by the fingerprint. Which was used is
reported, so a caller can warn when a role had to give way to a fingerprint.
"""

from __future__ import annotations

import math
import os
from collections import OrderedDict
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from OCP.TopAbs import TopAbs_FACE
from OCP.TopExp import TopExp
from OCP.TopTools import TopTools_IndexedMapOfShape
from OCP.TopoDS import TopoDS_Shape

from . import kernel

# Past this many faces a body is not tagged at all: the history of every
# boolean is asked face by face, and a three hundred solid import would pay
# for roles nobody will name. Such a body keeps the fingerprint path.
MAX_FACES = int(os.environ.get("DATUM_PROVENANCE_FACES", "2500"))
ENABLED = not os.environ.get("DATUM_NO_PROVENANCE")


def role_name(feature_id: int, role: str) -> str:
    return "%d:%s" % (feature_id, role)


def split_role(text: str) -> Tuple[int, str]:
    head, _, rest = text.partition(":")
    return int(head), rest


class FaceTags:
    """The roles of the faces of one shape."""

    __slots__ = ("shape", "faces", "map", "tags")

    def __init__(self, shape: TopoDS_Shape) -> None:
        self.shape = shape
        self.map = TopTools_IndexedMapOfShape()
        TopExp.MapShapes_s(shape, TopAbs_FACE, self.map)
        self.faces: Optional[List[TopoDS_Shape]] = None
        # face index (0-based) -> its roles; only faces that have any
        self.tags: Dict[int, Set[str]] = {}

    # -- the shape ----------------------------------------------------------

    @property
    def count(self) -> int:
        return self.map.Extent()

    def face(self, index: int) -> TopoDS_Shape:
        return self.map.FindKey(index + 1)

    def index_of(self, face: TopoDS_Shape) -> int:
        return self.map.FindIndex(face) - 1

    def is_for(self, shape: TopoDS_Shape) -> bool:
        return shape is self.shape or (shape is not None
                                       and self.shape.IsSame(shape))

    # -- reading and writing --------------------------------------------------

    def add(self, face: TopoDS_Shape, role: str) -> bool:
        i = self.index_of(face)
        if i < 0:
            return False
        self.tags.setdefault(i, set()).add(role)
        return True

    def roles(self, face: TopoDS_Shape) -> Set[str]:
        i = self.index_of(face)
        return self.tags.get(i, set()) if i >= 0 else set()

    def faces_for(self, role: str) -> List[TopoDS_Shape]:
        return [self.face(i) for i in sorted(self.tags)
                if role in self.tags[i]]

    def all_roles(self) -> Dict[str, List[int]]:
        out: Dict[str, List[int]] = {}
        for i in sorted(self.tags):
            for role in sorted(self.tags[i]):
                out.setdefault(role, []).append(i)
        return out

    def __bool__(self) -> bool:
        return bool(self.tags)

    # -- carrying them over ---------------------------------------------------

    def through(self, history: "kernel.History",
                shape: TopoDS_Shape) -> "FaceTags":
        """The roles on ``shape``, the result of an operation whose history
        this is the faces' story for. Falls back on geometry when the
        operation could not say what became of its faces."""
        if not history.known:
            return self.transfer(shape)
        out = FaceTags(shape)
        self.fold_into(out, history)
        return out

    def fold_into(self, out: "FaceTags", history: "kernel.History") -> None:
        """Add to ``out`` the roles these faces' images hold."""
        if not history.known:
            out.merged(self.transfer(out.shape))
            return
        for i, roles in self.tags.items():
            for new in history.image(self.face(i)) or ():
                j = out.index_of(new)
                if j >= 0:
                    out.tags.setdefault(j, set()).update(roles)

    def absorb(self, other: "FaceTags") -> None:
        """Add another set's roles by face, for a shape that holds the faces
        of the other's (a compound of tools, each tagged on its own)."""
        for i, roles in other.tags.items():
            face = other.face(i)
            for role in roles:
                self.add(face, role)

    def transfer(self, shape: TopoDS_Shape) -> "FaceTags":
        """The same roles on a shape that has the same faces, found again by
        sameness, else by position, surface and area. A face that changed
        (cut, rounded) is not there, so it loses its roles: nothing is
        guessed."""
        out = FaceTags(shape)
        if not self.tags:
            return out
        lookup = kernel.remap_history(self.shape, shape)
        for i, roles in self.tags.items():
            for new in lookup.image(self.face(i)) or ():
                j = out.index_of(new)
                if j >= 0:
                    out.tags.setdefault(j, set()).update(roles)
        return out

    def merged(self, other: "FaceTags") -> None:
        """Add another set's roles, for the same shape."""
        for i, roles in other.tags.items():
            self.tags.setdefault(i, set()).update(roles)

    # -- persistence --------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Index maps and a fingerprint per tagged face; no shapes."""
        marks = {}
        for i in self.tags:
            c, size, geom = _brief(self.face(i))
            marks[str(i)] = [round(c[0], 4), round(c[1], 4), round(c[2], 4),
                             round(size, 3), geom]
        return {"n": self.count,
                "roles": {r: ix for r, ix in self.all_roles().items()},
                "marks": marks}

    @classmethod
    def from_dict(cls, shape: TopoDS_Shape, data: Dict[str, Any]
                  ) -> Optional["FaceTags"]:
        """Tags for ``shape`` from a stored map, or None when they do not
        describe it. A face whose fingerprint no longer matches its index is
        looked for by fingerprint; one that cannot be found is dropped."""
        out = cls(shape)
        if int(data.get("n", -1)) != out.count:
            return None
        marks = data.get("marks", {})
        wrong: Dict[int, List[str]] = {}
        for role, indices in data.get("roles", {}).items():
            for i in indices:
                if 0 <= i < out.count and _matches(out.face(i),
                                                  marks.get(str(i))):
                    out.tags.setdefault(i, set()).add(role)
                else:
                    wrong.setdefault(i, []).append(role)
        if wrong:
            # the order of the faces changed (a file read back by another
            # build of the kernel): find each by what it was
            keyed: Dict[Tuple, List[int]] = {}
            for i in range(out.count):
                keyed.setdefault(_key(*_brief(out.face(i))), []).append(i)
            for i, roles in wrong.items():
                m = marks.get(str(i))
                hit = keyed.get(_key((m[0], m[1], m[2]), m[3], m[4])) \
                    if m else None
                if hit and len(hit) == 1:
                    out.tags.setdefault(hit[0], set()).update(roles)
        return out


def _brief(face: TopoDS_Shape) -> Tuple[Tuple[float, float, float], float, str]:
    from .naming import _surface_kind
    from OCP.GProp import GProp_GProps
    from OCP.BRepGProp import BRepGProp
    props = GProp_GProps()
    BRepGProp.SurfaceProperties_s(face, props)
    p = props.CentreOfMass()
    return (p.X(), p.Y(), p.Z()), props.Mass(), _surface_kind(face)


def _key(centre, size, geom) -> Tuple:
    return (round(centre[0], 3), round(centre[1], 3), round(centre[2], 3),
            round(size, 1), geom)


def _matches(face: TopoDS_Shape, mark) -> bool:
    if not mark:
        return False
    c, size, geom = _brief(face)
    return (math.dist(c, mark[:3]) < 1e-3
            and abs(size - mark[3]) <= 1e-3 * max(1.0, abs(size))
            and geom == mark[4])


# ----------------------------------------------------------------- registry

# Shapes carry no attributes of ours, so tags are found by the shape they
# describe: the registry maps a body's shape to its tags. A reference being
# resolved (a fillet's edges, a constraint's face) only has the shape, and
# this is how it reaches the story of it. Bounded, newest first: the bodies
# in use are registered again every time a feature finishes.
_REGISTRY: "OrderedDict[int, List[Tuple[TopoDS_Shape, FaceTags]]]" = \
    OrderedDict()
_KEEP = 512


def register(shape: Optional[TopoDS_Shape], tags: Optional[FaceTags]) -> None:
    if shape is None or tags is None or shape.IsNull() or not tags:
        return
    key = hash(shape)
    bucket = [(s, t) for s, t in _REGISTRY.pop(key, [])
              if not s.IsEqual(shape)]
    bucket.append((shape, tags))
    _REGISTRY[key] = bucket
    while len(_REGISTRY) > _KEEP:
        _REGISTRY.popitem(last=False)


def _held(shape: TopoDS_Shape) -> Optional[FaceTags]:
    for s, t in _REGISTRY.get(hash(shape), ()):
        if s.IsEqual(shape):
            return t
    return None


def lookup(shape: Optional[TopoDS_Shape]) -> List[FaceTags]:
    """The tags of a shape: its own, or, for a compound of bodies, those of
    each body in it."""
    if shape is None or shape.IsNull() or not ENABLED:
        return []
    held = _held(shape)
    if held is not None:
        return [held]
    out = []
    for piece in kernel.pieces(shape):
        held = _held(piece)
        if held is not None:
            out.append(held)
    return out


def forget() -> None:
    _REGISTRY.clear()


def for_shape(shape: Optional[TopoDS_Shape]) -> Optional[FaceTags]:
    """One tag set for a shape that is a compound of tagged bodies (or a
    single tagged body), for storing it beside the shape."""
    parts = lookup(shape)
    if not parts:
        return None
    if len(parts) == 1 and parts[0].is_for(shape):
        return parts[0]
    out = FaceTags(shape)
    for t in parts:
        out.absorb(t)
    return out if out else None


def dump(shape: Optional[TopoDS_Shape]) -> Optional[Dict[str, Any]]:
    """The index map of a shape's roles, as JSON-ready data; None when it
    has none."""
    try:
        tags = for_shape(shape)
        return tags.to_dict() if tags else None
    except Exception:
        return None


def restore(shape: TopoDS_Shape, data: Optional[Dict[str, Any]]
            ) -> Optional[FaceTags]:
    """Tags for ``shape`` from what ``dump`` wrote, registered for lookups.
    Quietly nothing when the map does not describe the shape."""
    if not data or not ENABLED or shape is None or shape.IsNull():
        return None
    try:
        tags = FaceTags.from_dict(shape, data)
    except Exception:
        return None
    if tags:
        register(shape, tags)
    return tags or None


def roles_of(shape: TopoDS_Shape, face: TopoDS_Shape) -> Set[str]:
    out: Set[str] = set()
    for tags in lookup(shape):
        out |= tags.roles(face)
    return out


def faces_with(shape: Optional[TopoDS_Shape], role: str
               ) -> List[TopoDS_Shape]:
    """The faces of ``shape`` that carry a role."""
    out: List[TopoDS_Shape] = []
    for tags in lookup(shape):
        out.extend(tags.faces_for(role))
    return out


# ------------------------------------------------------- tagging a new tool


def tag_prism(tool: TopoDS_Shape, history: "kernel.History", profile,
              fid: int, sketch, plane, role_start: str = "start",
              role_end: str = "end") -> FaceTags:
    """Tags for a solid made by ``extrude_h`` or ``revolve_h``: its caps, and
    each side face by the sketch entity it was swept from."""
    tags = FaceTags(tool)
    for f in history.first_faces():
        tags.add(f, role_name(fid, role_start))
    for f in history.last_faces():
        tags.add(f, role_name(fid, role_end))
    if sketch is not None:
        lines = _polylines(sketch)
        for edge in kernel.edges(profile):
            eid = entity_of_edge(sketch, edge, lines)
            if eid is None:
                continue
            for f in history.generated(edge):
                if f.ShapeType() == TopAbs_FACE:
                    tags.add(f, role_name(fid, "side:e%d" % eid))
    return tags


def classify_extrusion(tool: TopoDS_Shape, fid: int, sketch, plane,
                       forward: float = 1.0) -> FaceTags:
    """Tags for an extrusion that was not made by one prism (to a face, to
    next, tapered, asymmetric): its caps by where they stand along the
    sketch's normal, each side by the sketch entity it lies over."""
    from .features import plane_from_face
    tags = FaceTags(tool)
    n = plane.normal
    caps: List[Tuple[float, TopoDS_Shape]] = []
    sides: List[TopoDS_Shape] = []
    for f in kernel.faces(tool):
        p = plane_from_face(f)
        if p is not None and abs(abs(sum(a * b for a, b in zip(p.normal, n)))
                                 - 1.0) < 1e-6:
            caps.append((forward * plane.distance_to(p.origin), f))
        else:
            sides.append(f)
    if caps:
        low = min(c[0] for c in caps)
        high = max(c[0] for c in caps)
        for at, f in caps:
            if abs(at - low) < 1e-6 * max(1.0, abs(low)) + 1e-6:
                tags.add(f, role_name(fid, "start"))
            if abs(at - high) < 1e-6 * max(1.0, abs(high)) + 1e-6 \
                    and high > low + 1e-6:
                tags.add(f, role_name(fid, "end"))
    if sketch is not None:
        lines = _polylines(sketch)
        for f in sides:
            where = kernel.point_on_face(f)
            if where is None:
                continue
            eid = _entity_near(sketch, plane.to_2d(where), lines=lines)
            if eid is not None:
                tags.add(f, role_name(fid, "side:e%d" % eid))
    return tags


def _polylines(sketch) -> Dict[int, List[Tuple[float, float]]]:
    """Each drawn entity of a sketch as a polyline, as it is now (a
    parameter changes where they are, so this is worked out per feature,
    never kept)."""
    lines = {}
    for eid, e in sketch.entities.items():
        if e.construction:
            continue
        try:
            poly = sketch.entity_polyline(eid)
        except Exception:
            continue
        if len(poly) >= 2:
            lines[eid] = poly
    return lines


def _seg_distance(p, a, b) -> float:
    dx, dy = b[0] - a[0], b[1] - a[1]
    ln = dx * dx + dy * dy
    t = 0.0 if ln < 1e-18 else max(0.0, min(1.0, (
        (p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / ln))
    return math.hypot(p[0] - (a[0] + t * dx), p[1] - (a[1] + t * dy))


def _entity_near(sketch, point, tol: float = 0.05,
                 lines=None) -> Optional[int]:
    best, gap = None, math.inf
    for eid, poly in (lines if lines is not None
                      else _polylines(sketch)).items():
        d = min(_seg_distance(point, a, b) for a, b in zip(poly, poly[1:]))
        if d < gap:
            best, gap = eid, d
    # a polyline stands in for an arc, so the allowance follows its size
    return best if best is not None and gap < tol + 1e-3 else None


def entity_of_edge(sketch, edge: TopoDS_Shape,
                   lines=None) -> Optional[int]:
    """The sketch entity an edge of the profile was drawn from."""
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    try:
        curve = BRepAdaptor_Curve(edge)
        mid = curve.Value(0.5 * (curve.FirstParameter()
                                 + curve.LastParameter()))
    except Exception:
        return None
    return _entity_near(sketch, sketch.plane.to_2d((mid.X(), mid.Y(),
                                                    mid.Z())), lines=lines)


# ------------------------------------------------- finding and describing


_ANCESTORS: "OrderedDict[int, Tuple[TopoDS_Shape, Any]]" = OrderedDict()


def _ancestors(shape: TopoDS_Shape):
    """Which faces each edge of a shape lies on, kept for the last few."""
    from OCP.TopAbs import TopAbs_EDGE
    from OCP.TopTools import TopTools_IndexedDataMapOfShapeListOfShape
    key = hash(shape)
    held = _ANCESTORS.get(key)
    if held is not None and held[0].IsEqual(shape):
        return held[1]
    amap = TopTools_IndexedDataMapOfShapeListOfShape()
    TopExp.MapShapesAndAncestors_s(shape, TopAbs_EDGE, TopAbs_FACE, amap)
    _ANCESTORS[key] = (shape, amap)
    while len(_ANCESTORS) > 8:
        _ANCESTORS.popitem(last=False)
    return amap


def adjacent_faces(shape: TopoDS_Shape, edge: TopoDS_Shape
                   ) -> List[TopoDS_Shape]:
    """The distinct faces of ``shape`` an edge lies between."""
    amap = _ancestors(shape)
    if not amap.Contains(edge):
        return []
    out: List[TopoDS_Shape] = []
    for f in amap.FindFromKey(edge):
        if not any(f.IsSame(o) for o in out):
            out.append(f)
    return out


def edge_key(old: Optional[FaceTags], edge: TopoDS_Shape) -> str:
    """A name for an edge of a tagged shape: the roles of the two faces it
    lies between, in a fixed order. Empty when either face has none."""
    if old is None or not old.tags:
        return ""
    sides = []
    for f in adjacent_faces(old.shape, edge):
        roles = sorted(old.roles(f))
        if not roles:
            return ""
        sides.append("+".join(roles))
    if len(sides) != 2:
        return ""
    return "|".join(sorted(sides))


# A role that only says "the k-th one" is the weakest evidence there is: an
# edge added earlier in the tree renumbers it. It counts for less than a
# role that says what the face lay between.
def _weight(role: str) -> float:
    tail = role.rsplit(":", 1)[-1]
    return 0.5 if (":face:" in role and tail.isdigit()) else 1.0


def describe(shape: TopoDS_Shape, sub: TopoDS_Shape, kind: str
             ) -> Optional[List]:
    """What a reference should remember of a face or edge: the face's roles,
    or the roles of each face the edge lies between. None when the part
    knows nothing about it."""
    if not lookup(shape):
        return None
    if kind == "face":
        return sorted(roles_of(shape, sub)) or None
    sides = [sorted(roles_of(shape, f)) for f in adjacent_faces(shape, sub)]
    return sides if any(sides) else None


def _fits(stored: List[List[str]], faces_roles: List[Set[str]]) -> bool:
    """Whether an edge's neighbouring faces carry the stored roles, in
    either order: a stored side with roles needs a face holding one of them,
    an empty one a face holding none."""
    if len(stored) != len(faces_roles):
        return False
    import itertools
    for order in itertools.permutations(range(len(faces_roles))):
        if all((bool(set(stored[i]) & faces_roles[j]) if stored[i]
                else not faces_roles[j])
               for i, j in enumerate(order)):
            return True
    return False


def find(shape: TopoDS_Shape, kind: str, roles: Sequence[str] = (),
         adjacent: Sequence[Sequence[str]] = ()) -> List[TopoDS_Shape]:
    """The faces or edges of ``shape`` that carry those roles (a face: any
    of them, those with most first; an edge: lying between faces that carry
    each stored side's roles)."""
    if not lookup(shape):
        return []
    if kind == "face":
        scored: Dict[int, Tuple[float, TopoDS_Shape]] = {}
        for r in roles:
            for f in faces_with(shape, r):
                k = hash(f)
                n, _f = scored.get(k, (0.0, f))
                scored[k] = (n + _weight(r), f)
        if not scored:
            return []
        top = max(n for n, _f in scored.values())
        return [f for n, f in scored.values() if n == top]
    named = [list(a) for a in adjacent if a]
    if not named:
        return []
    start = [f for r in named[0] for f in faces_with(shape, r)]
    stored = [list(a) for a in adjacent]
    out: List[TopoDS_Shape] = []
    for f in start:
        for e in kernel.edges(f):
            if any(e.IsSame(o) for o in out):
                continue
            sides = [roles_of(shape, g) for g in adjacent_faces(shape, e)]
            if _fits(stored, sides):
                out.append(e)
    return out
