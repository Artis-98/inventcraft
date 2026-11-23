"""One ``build`` call: a list of ops applied to a part, in order.

Every feature type in ``core.features.FEATURE_TYPES`` is an op, with the
fields its ``to_dict()`` has (see ``ir``). On top of that sit a few
conveniences an agent needs because it cannot click: a sketch drawn from
named entities with constraints and dimensions (``sketchir``), regions
picked by rule, edges picked by a query, faces picked by a query or a
role (``"$e1.end"``). The tree ops ``parameter``, ``edit``, ``remove``
and ``move`` change what is already there.

References between ops: an op may carry an ``id``; a later op refers to
the feature it made as ``"$id"``, and to what is in it as
``"$id.region[0]"`` (a sketch's regions, largest first), ``"$id.c1"`` (a
named sketch entity or point), ``"$id.end"`` / ``"$id.start"`` (an
extrusion's end and start faces). A feature already in the part can be
named by its name instead.
"""

from __future__ import annotations

import ast
import math
import re
from typing import Any, Dict, List, Optional, Tuple

from ..core import edgequery, kernel
from ..core import units as ucore
from ..core.document import Document
from ..core.features import (
    CUT, FEATURE_TYPES, INTERSECT, JOIN, NEW_BODY, BuildContext, Feature,
    SketchFeature, collect_regions, plane_from_face)
from ..core.naming import RefSet, ShapeRef
from ..core.params import evaluate, referenced_names
from ..core.sketch import STANDARD_PLANES, Sketch, SketchPlane
from . import ir
from .errors import BridgeError
from .sketchir import SketchBuilder
from .workspace import Entry

ANGLE_FIELDS = ("taper", "taper2", "rx", "ry", "rz")
REF_RE = re.compile(r"^\$([^.\[]+)(?:\.(.+))?$")
FACE_KEYS = ("at", "normal", "kind", "near", "count", "largest",
             "min_area")
SURFACES = ("plane", "cylinder", "cone", "sphere", "torus")


def field_unit(name: str) -> str:
    if "angle" in name or name in ANGLE_FIELDS:
        return "angle"
    if name.startswith("count"):
        return "count"
    return "length"


def mm_explicit(text: str) -> str:
    """An expression with every bare length in it written as mm, so a
    person reading it in an inch part cannot take 5 for 5 in."""
    if ucore._plain(text) is not None or ucore._has_units(text):
        return text
    try:
        tree = ast.parse(text, mode="eval")
    except SyntaxError:
        return text
    found: List[ast.Constant] = []
    ucore._lengths(tree.body, True, found)
    out = text
    for node in sorted(found, key=lambda n: n.end_col_offset, reverse=True):
        end = node.end_col_offset
        out = out[:end] + " mm" + out[end:]
    return out


class Build:
    """The ops of one build call, what each became, and the document."""

    def __init__(self, entry: Entry) -> None:
        self.entry = entry
        self.doc: Document = entry.document
        self.names: Dict[str, int] = {}
        self.sketch_names: Dict[int, Dict[str, Any]] = {
            k: dict(v) for k, v in entry.sketch_names.items()}
        self.created: List[Dict[str, Any]] = []
        self.changed: List[Dict[str, Any]] = []
        self.removed: List[Dict[str, Any]] = []
        self.notes: List[str] = []
        self.literals: List[Tuple[float, str]] = []
        # how each reference a pick used was resolved (refs: via)
        self.vias: List[Dict[str, Any]] = []
        # code features this build could not run: their source is not
        # trusted (one the agent did not write)
        self.waiting: List[str] = []

    def commit(self) -> None:
        self.entry.sketch_names = self.sketch_names

    # values -----------------------------------------------------------

    def scope(self) -> Dict[str, float]:
        return self.doc.parameter_scope()

    def number(self, value: Any, what: str) -> float:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
        try:
            return float(evaluate(str(value), self.scope()))
        except Exception as exc:
            raise BridgeError("BAD_EXPRESSION",
                              "%s: cannot evaluate %r (%s)" % (what, value, exc),
                              ["Define parameters first with a parameter op."]
                              ) from exc

    @staticmethod
    def text(value: Any) -> str:
        if isinstance(value, bool):
            raise BridgeError("BAD_VALUE", "a number was expected, not %r"
                              % value)
        if isinstance(value, float) and value.is_integer():
            return str(int(value))
        return str(value)

    def stored(self, value: Any, unit: str = "length", what: str = "") -> str:
        """What is kept for a value: a plain number (mm or degrees, as the
        core reads one) or an expression. Arithmetic with no names in it
        is worked out; in a part that is not in mm every bare length in an
        expression is marked mm, so nothing can be read in inches."""
        t = self.text(value).strip()
        if not t:
            raise BridgeError("BAD_VALUE", "%s is empty" % (what or "a value"))
        try:
            names = referenced_names(t)
        except Exception:
            names = None
        if names is not None and not names and ucore._plain(t) is None \
                and not ucore._has_units(t):
            try:
                t = self.text(round(float(evaluate(t, {})), 10))
            except Exception:
                pass
        plain = ucore._plain(t)
        if plain is not None:
            if unit != "count":
                self.literals.append((plain, unit))
            return t
        if unit == "length" and getattr(self.doc, "units", "mm") != "mm":
            return mm_explicit(t)
        return t

    # references --------------------------------------------------------

    def _token(self, tok: str) -> Optional[int]:
        if tok in self.names:
            return self.names[tok]
        for f in self.doc.features:
            if f.name == tok:
                return f.id
        taken: set = set()
        for f in self.doc.features:
            if ir.token_for(f.name, taken) == tok:
                return f.id
        return None

    def split(self, ref: Any, what: str) -> Tuple[int, Optional[str]]:
        """A reference as (feature id, what is asked of it)."""
        if isinstance(ref, bool):
            raise BridgeError("BAD_REF", "%s: %r is not a feature" % (what, ref))
        if isinstance(ref, int):
            if self.doc.feature(ref) is None:
                raise BridgeError("BAD_REF", "%s: no feature has id %d"
                                  % (what, ref))
            return ref, None
        text = str(ref)
        m = REF_RE.match(text)
        if m:
            fid = self._token(m.group(1))
            if fid is None:
                raise BridgeError(
                    "BAD_REF", "%s: no earlier op or feature is %r"
                    % (what, m.group(1)),
                    ["Op ids so far: %s" % (", ".join(self.names) or "none")])
            return fid, m.group(2)
        fid = self._token(text)
        if fid is None:
            raise BridgeError(
                "BAD_REF", "%s: no feature named %r" % (what, text),
                ["Features: %s" % ", ".join(f.name for f in self.doc.features)])
        return fid, None

    def feature_id(self, ref: Any, what: str) -> int:
        fid, rest = self.split(ref, what)
        if rest:
            raise BridgeError("BAD_REF", "%s takes a feature, not %r"
                              % (what, ref))
        return fid

    def feature(self, ref: Any, what: str) -> Feature:
        return self.doc.feature(self.feature_id(ref, what))

    def sketch_part(self, ref: Any, sketch_id: int, what: str
                    ) -> Tuple[str, int]:
        """A named point or entity of a sketch: ``"$s1.c1.center"``, or
        ``"c1.center"`` in the sketch the op already uses."""
        if isinstance(ref, int):
            return ("id", ref)
        text = str(ref)
        if text.startswith("$"):
            sketch_id, rest = self.split(text, what)
            if not rest:
                raise BridgeError("BAD_REF", "%s: name a point or line in "
                                  "the sketch, e.g. $s1.c1.center" % what)
            text = rest
        names = self.sketch_names.get(sketch_id) or {}
        if text not in names:
            raise BridgeError(
                "BAD_REF", "%s: the sketch has nothing named %r" % (what, text),
                ["Names: %s" % (", ".join(sorted(names)) or
                                "none (only names given by a build are "
                                "known; use ids from sketch_status)")])
        return tuple(names[text])

    # geometry ------------------------------------------------------------

    def regions(self, sketch_id: int) -> List[Dict[str, Any]]:
        self.doc.rebuild()
        ctx = BuildContext(self.doc.params.scope())
        ctx.sketches = dict(self.doc.all_sketches())
        found = [r for r in collect_regions(ctx)
                 if r["sketch_id"] == sketch_id]
        return sorted(found, key=lambda r: -r["area"])

    def profiles(self, value: Any, sketch_id: int) -> List[List[float]]:
        items: List[Tuple[int, Tuple[float, float]]] = []

        def from_sketch(sid, how):
            regions = self.regions(sid)
            if not regions:
                raise BridgeError(
                    "PROFILE_NOT_CLOSED", "the sketch has no closed region",
                    ["Use rect, circle or polygon, or a closed polyline; "
                     "sketch_status shows what is open."])
            return [(sid, r["centre"]) for r in pick_regions(regions, how)]

        if value is None or isinstance(value, str) and not \
                value.startswith("$"):
            if not sketch_id:
                raise BridgeError("BAD_OP", "profiles: say which sketch "
                                  "(sketch: \"$s1\")")
            how = value or "outer"
            items = from_sketch(sketch_id, how)
            if how == "outer":
                # the whole sketch, outlines less the holes in them, is
                # what a feature with no regions picked takes; kept that
                # way it is worked out again on every rebuild, so a region
                # whose middle a parameter moves far is not lost
                return []
        else:
            for v in (value if isinstance(value, list) else [value]):
                if isinstance(v, list) and len(v) == 3:
                    items.append((self.feature_id(v[0], "profile sketch"),
                                  (float(v[1]), float(v[2]))))
                elif isinstance(v, int):
                    items += from_sketch(sketch_id, [v])
                elif isinstance(v, str) and v.startswith("$"):
                    sid, rest = self.split(v, "profiles")
                    m = re.match(r"^region(?:\[(\d+)\])?$", rest or "region")
                    if not m:
                        raise BridgeError(
                            "BAD_REF", "profiles: %r is not a region" % v,
                            ['Write "$s1.region[0]" (largest first) or '
                             '"$s1.region" for the outer regions.'])
                    items += from_sketch(sid, [int(m.group(1))]
                                         if m.group(1) else "outer")
                else:
                    raise BridgeError("BAD_OP", "profiles: cannot use %r" % v)
        return [[sid, round(c[0], 9), round(c[1], 9)] for sid, c in items]

    def shape(self):
        if self.doc.shape is None:
            raise BridgeError("NO_BODY", "there is no solid to pick on yet")
        return self.doc.shape

    def faces(self, query: Any) -> List[Any]:
        return select_faces(self.shape(), query)

    def role(self, fid: int, role: str) -> List[Any]:
        """Faces a feature made, by what they are to it."""
        f = self.doc.feature(fid)
        if f is None or f.type_name != "extrude" or role not in ("start",
                                                                  "end"):
            raise BridgeError(
                "BAD_REF", "no face %r on %s" % (role, getattr(f, "name", fid)),
                ["Roles now: start and end of an extrusion. For others "
                 "use {\"faces\": {\"normal\": \"+z\", ...}}."])
        sid = (f.profiles.sketch_ids() or [f.sketch_id])[0]
        sketch = self.doc.all_sketches().get(sid)
        if sketch is None:
            raise BridgeError("BAD_REF", "%s has no sketch" % f.name)
        plane = sketch.plane
        n = plane.normal
        sign = -1.0 if f.reversed else 1.0
        if f.extent == "symmetric":
            d = self.number(f.distance, "distance") / 2.0
            at = d if role == "end" else -d
        elif f.extent == "distance":
            at = sign * self.number(f.distance, "distance") \
                if role == "end" else 0.0
        elif f.extent == "asymmetric":
            at = sign * self.number(f.distance, "distance") if role == "end" \
                else -sign * self.number(f.distance2, "distance2")
        else:
            raise BridgeError("NO_PROVENANCE", "%s: start and end are known "
                              "for distance, symmetric and asymmetric "
                              "extrusions" % f.name,
                              ["Use find_geometry with created_by."])
        point = tuple(plane.origin[i] + n[i] * at for i in range(3))
        found = []
        for face in kernel.faces(self.shape()):
            p = plane_from_face(face)
            if p is None:
                continue
            if abs(abs(sum(a * b for a, b in zip(p.normal, n))) - 1) > 1e-6:
                continue
            if abs(p.distance_to(point)) > 1e-4:
                continue
            found.append(face)
        if not found:
            raise BridgeError("NO_MATCH", "%s.%s: that face is not on the "
                              "body any more" % (f.name, role))
        found.sort(key=lambda fc: -kernel.face_area(fc))
        return found[:1]

    def picks(self, value: Any, what: str) -> Tuple[str, List[Any]]:
        """Faces or edges from roles and queries: (kind, shapes)."""
        from .refs import Resolver
        items = value if isinstance(value, list) else [value]
        kind, out = "", []
        for v in items:
            if isinstance(v, str):
                # any readable reference: $e1.end, Extrusion1.side(a),
                # Hole1.wall[0], @F:... (see refs)
                r = Resolver(self.entry, self).resolve(
                    v, what, ("face", "edge", "vertex"))
                got, k = r.shapes, r.kind
                self.vias.append({"ref": v, "via": r.via, "kind": k,
                                  "count": len(got)})
            elif isinstance(v, dict) and "faces" in v:
                got, k = self.faces(v["faces"]), "face"
            elif isinstance(v, dict) and "edges" in v:
                try:
                    got = edgequery.edges(self.shape(), v["edges"])
                except edgequery.QueryError as exc:
                    raise BridgeError(exc.kind, str(exc), exc.hints) from exc
                k = "edge"
            else:
                raise BridgeError(
                    "BAD_OP", "%s: cannot pick %r" % (what, v),
                    ['Use a reference ("$e1.end", "Hole1.wall[0]", '
                     '"@F:..."), {"faces": {...}} or {"edges": {...}}.'])
            if kind and k != kind:
                raise BridgeError("BAD_OP", "%s: faces and edges mixed" % what)
            kind = k
            out += [s for s in got if not any(s.IsSame(o) for o in out)]
        return kind, out

    @staticmethod
    def stored_refs(value: Any) -> bool:
        return isinstance(value, list) and all(
            isinstance(v, dict) and "kind" in v and "centre" in v
            for v in value)

    def refset(self, value: Any, what: str) -> List[Dict[str, Any]]:
        if value in (None, []):
            return []
        if self.stored_refs(value):
            return value
        kind, shapes = self.picks(value, what)
        refs = RefSet()
        refs.capture_from(self.shape(), kind, shapes)
        self.notes.append("%s: %d %s(s)" % (what, len(shapes), kind))
        return refs.to_list()

    def shaperef(self, value: Any, what: str) -> Optional[Dict[str, Any]]:
        if value is None:
            return None
        if isinstance(value, dict) and "kind" in value and "centre" in value:
            return value
        refs = self.refset(value, what)
        return refs[0] if refs else None

    # ops ---------------------------------------------------------------

    def run(self, spec: Dict[str, Any], index: int) -> None:
        kind = spec.get("op")
        handler = getattr(self, "op_%s" % kind, None)
        if handler is not None:
            handler(spec)
        elif kind in FEATURE_TYPES:
            if kind == "sketch" and is_placed(spec.get("plane")):
                spec = self.plane_for(spec)
            self.add(spec)
        else:
            raise BridgeError(
                "UNKNOWN_OP", "op %d: unknown op %r" % (index, kind),
                ["Ops: %s; and the tree ops %s. Each has a schema at "
                 "ic://schema/op/{type}." % (
                     ", ".join(FEATURE_TYPES), ", ".join(ir.TREE_OPS))])

    def plane_for(self, spec: Dict[str, Any]) -> Dict[str, Any]:
        """A sketch on a plane given by numbers gets a work plane of its
        own, so the plane shows in the tree and follows its parameters."""
        given = dict(spec["plane"])
        extra = set(given) - {"origin", "normal", "x", "xdir", "name"}
        if extra or "normal" not in given:
            raise BridgeError(
                "BAD_OP", "a plane by numbers takes normal, and origin and "
                "x if wanted",
                ['"plane": {"origin": ["x1", 0, 0], "normal": [1, 0, 0], '
                 '"x": [0, 1, 0]}'])
        op = {"op": "workplane", "mode": "placed",
              "name": given.get("name") or "%s plane" % (
                  spec.get("name") or spec.get("id") or "Sketch"),
              "origin": given.get("origin", [0, 0, 0]),
              "normal": given["normal"]}
        across = given.get("x", given.get("xdir"))
        if across is not None:
            op["xdir"] = across
        self.add(op)
        made = self.created[-1]["id"]
        token = "plane#%d" % made
        self.names[token] = made
        return dict(spec, plane="$" + token)

    def _record(self, spec, feature) -> None:
        if spec.get("id"):
            self.names[str(spec["id"])] = feature.id
        self.created.append({"op_id": spec.get("id"), "id": feature.id,
                             "name": feature.name,
                             "type": feature.type_name})

    def check_keys(self, type_name: str, keys) -> None:
        allowed = set(ir.allowed_keys(type_name))
        unknown = [k for k in keys if k not in allowed]
        if unknown:
            raise BridgeError(
                "BAD_OP", "%s: unknown field(s) %s" % (
                    type_name, ", ".join(sorted(unknown))),
                ["%s takes: %s. Schema: ic://schema/op/%s" % (
                    type_name, ", ".join(sorted(allowed - {"op"})),
                    type_name)])

    def fields(self, type_name: str, spec: Dict[str, Any],
               data: Dict[str, Any]) -> Dict[str, Any]:
        """``data`` (a feature's dict) with the op's fields written in."""
        kinds = ir.kinds(type_name)
        if "sketch" in spec and "sketch_id" in kinds:
            data["sketch_id"] = self.feature_id(spec["sketch"], "sketch")
        if "sketch_id" in spec:
            data["sketch_id"] = self.feature_id(spec["sketch_id"], "sketch_id")
        for key in ("name", "suppressed"):
            if key in spec:
                data[key] = spec[key] if key == "suppressed" else str(spec[key])
        if "suppressed" in data:
            data["suppressed"] = bool(data["suppressed"])
        if "solids" in spec:
            data["solids"] = [str(s) for s in spec["solids"] or []]
        if "param_names" in spec:
            data["param_names"] = dict(spec["param_names"] or {})
        if "comments" in spec:
            comments = dict(data.get("param_comments") or {})
            for k, v in (spec["comments"] or {}).items():
                if k not in kinds:
                    raise BridgeError("BAD_OP", "comments: %s has no field %r"
                                      % (type_name, k))
                if v:
                    comments[str(k)] = str(v)
                else:
                    comments.pop(str(k), None)
            data["param_comments"] = comments
        sid = int(data.get("sketch_id") or 0)
        for key, value in spec.items():
            kind = kinds.get(key)
            if kind is None or key == "sketch_id":
                continue
            data[key] = self.convert(type_name, key, kind, value, sid, data)
        if "profiles" in kinds and "profiles" not in spec and sid and (
                "sketch" in spec or "sketch_id" in spec):
            data["profiles"] = self.profiles("outer", sid)
        return data

    def convert(self, type_name, key, kind, value, sid, data):
        what = "%s %s" % (type_name, key)
        if kind == "expr":
            if isinstance(value, (bool, dict, list)) or value is None:
                raise BridgeError("BAD_VALUE", "%s: a number or expression, "
                                  "not %r" % (what, value))
            return self.stored(value, field_unit(key), what)
        if kind == "exprs":
            if not isinstance(value, (list, tuple)) or len(value) != 3:
                raise BridgeError("BAD_VALUE", "%s: three values [x, y, z], "
                                  "not %r" % (what, value))
            return [self.stored(v, "length", what) for v in value]
        if kind == "text":
            if type_name == "revolve" and key == "axis":
                return self.axis(value, sid, data)
            if key in ("plane", "base", "plane_a", "plane_b", "dir1", "dir2",
                       "axis", "origin_axis") and isinstance(value, str) \
                    and value.startswith("$"):
                return self.feature(value, what).name
            return str(value)
        if kind == "bool":
            return bool(value)
        if kind == "int":
            if type_name == "fold" and key == "line" and isinstance(value, str):
                return self.sketch_part(value, sid, what)[1]
            try:
                return int(value)
            except (TypeError, ValueError) as exc:
                raise BridgeError("BAD_VALUE", "%s: an integer, not %r"
                                  % (what, value)) from exc
        if kind == "number":
            return float(self.number(value, what))
        if kind == "feature":
            return self.feature_id(value, what) if value else 0
        if kind == "features":
            return [self.feature_id(v, what) for v in (value or [])]
        if kind == "profiles":
            return self.profiles(value, sid)
        if kind == "refs":
            return self.refset(value, what)
        if kind == "shaperef":
            return self.shaperef(value, what)
        if kind == "sketch":
            return self.raw_sketch(value)
        if type_name == "hole" and key == "points":
            return [self.sketch_part(v, sid, what)[1] for v in value or []]
        if type_name == "workplane" and key == "refs":
            return [dict(r, sketch=self.feature_id(r["sketch"], what))
                    if isinstance(r, dict) and "sketch" in r else r
                    for r in value or []]
        return value

    def axis(self, value, sid, data) -> str:
        text = str(value)
        if text.upper() in ("X", "Y"):
            return text.upper()
        if text.startswith("axis:") or text in ("entity",):
            return text
        if text.upper() == "Z":
            return "axis:Z"
        if text.startswith("$"):
            fid, rest = self.split(text, "revolve axis")
            f = self.doc.feature(fid)
            if not rest and f is not None and f.type_name == "workaxis":
                return "axis:" + f.name
        kind, eid = self.sketch_part(text, sid, "revolve axis")
        if kind not in ("entity", "id"):
            raise BridgeError("BAD_REF", "revolve axis: %r is a point, not a "
                              "line" % value)
        data["axis_entity"] = eid
        return "entity"

    def raw_sketch(self, value: Dict[str, Any]) -> Dict[str, Any]:
        out = dict(value)
        projections = []
        for p in out.get("projections", []) or []:
            p = dict(p)
            src = dict(p.get("source") or {})
            if isinstance(src.get("sketch"), str):
                src["sketch"] = self.feature_id(src["sketch"], "projection")
            p["source"] = src
            projections.append(p)
        if projections:
            out["projections"] = projections
        return out

    # feature ops -------------------------------------------------------

    def add(self, spec: Dict[str, Any]) -> None:
        type_name = spec["op"]
        self.check_keys(type_name, spec)
        data = ir.defaults(type_name)
        data["type"] = type_name
        data["name"] = FEATURE_TYPES[type_name]().name
        data = self.fields(type_name, spec, data)
        feature = Feature.from_dict(data)
        feature.id = 0
        sugar = getattr(self, "sugar_%s" % type_name, None)
        if sugar is not None:
            sugar(spec, feature, new=True)
        self.doc.add_feature(feature)
        if isinstance(feature, SketchFeature):
            feature.sketch.name = feature.name
            pending = getattr(feature, "_names", None)
            if pending is not None:
                self.sketch_names[feature.id] = pending
                del feature._names
        self._record(spec, feature)

    def sugar_extrude(self, spec, feature, new=False) -> None:
        op = spec.get("operation")
        if op is not None:
            op = {"new_body": NEW_BODY, "new": NEW_BODY}.get(op, op)
            if op not in (JOIN, CUT, INTERSECT, NEW_BODY):
                raise BridgeError("BAD_OP", "unknown operation %r" % op,
                                  ["join, cut, intersect, new"])
            feature.operation = op
        if not new:
            return
        if not feature.profiles and not feature.sketch_id:
            raise BridgeError("BAD_OP", "extrude needs a sketch",
                              ['"sketch": "$s1"'])
        if feature.extent in ("distance", "symmetric", "asymmetric"):
            if "distance" not in spec:
                raise BridgeError("BAD_OP", "extrude needs a distance")
            if self.number(feature.distance, "distance") <= 0:
                raise BridgeError("BAD_VALUE", "distance must be positive",
                                  ["Use reversed: true to go the other way."])

    def sugar_revolve(self, spec, feature, new=False) -> None:
        op = spec.get("operation")
        if op in ("new_body",):
            feature.operation = NEW_BODY

    def _edges(self, spec, feature, value_key) -> None:
        if value_key in spec and self.number(
                getattr(feature, value_key), value_key) <= 0:
            raise BridgeError("BAD_VALUE", "%s must be positive" % value_key)
        if "edges" not in spec:
            return
        where = spec["edges"]
        if where == "all":
            feature.all_edges, feature.query = True, None
            feature.refs = RefSet()
            return
        if isinstance(where, str) or (isinstance(where, list) and any(
                isinstance(w, str) for w in where)):
            # references rather than a rule: kept as references, the way a
            # click is; a face given here stands for the edges round it
            kind, shapes = self.picks(where, "%s edges" % feature.name)
            if kind == "face":
                edges = []
                for face in shapes:
                    for e in kernel.edges(face):
                        if not any(e.IsSame(x) for x in edges):
                            edges.append(e)
                pool = kernel.edges(self.shape())
                shapes = [p for p in pool if any(p.IsSame(e) for e in edges)]
            elif kind != "edge":
                raise BridgeError("BAD_REF", "%s: edges are edges or faces"
                                  % feature.name)
            feature.all_edges, feature.query = False, None
            feature.refs = RefSet()
            feature.refs.capture_from(self.shape(), "edge", shapes)
            self.notes.append("%s: %d edge(s) by reference (kept as "
                              "references, not re-run as a rule)"
                              % (feature.name, len(shapes)))
            return
        try:
            picked = edgequery.edges(self.shape(), where)
        except edgequery.QueryError as exc:
            raise BridgeError(exc.kind, str(exc), exc.hints) from exc
        # the rule is what the feature keeps, so a parameter change finds
        # the edges again; the references are what the window shows if
        # somebody opens the feature to edit it by hand
        feature.all_edges = False
        feature.query = where
        feature.refs = RefSet()
        feature.refs.capture_from(self.shape(), "edge", picked)
        self.notes.append("%s: %d edge(s) by %s" % (
            feature.name, len(picked), _short(where)))

    def sugar_code(self, spec, feature, new=False) -> None:
        """A code feature the agent writes is trusted, for this session, by
        the hash of its source: it is the agent's own code, which it could
        as well run with run_script. Code that came in with an opened file
        is not, written again or not: that is the user's to allow."""
        op = spec.get("operation")
        if op is not None:
            op = {"new_body": NEW_BODY}.get(op, op)
            if op not in (JOIN, CUT, INTERSECT, NEW_BODY):
                raise BridgeError("BAD_OP", "unknown operation %r" % op,
                                  ["join, cut, intersect, new"])
            feature.operation = op
        if "source" not in spec:
            if new:
                raise BridgeError("BAD_OP", "a code op needs source",
                                  ['"source": "body = box(10, 10, 10)"'])
            return
        source = feature.source
        try:
            compile(source, "<%s>" % feature.name, "exec")
        except SyntaxError as exc:
            raise BridgeError("BAD_CODE", "%s: line %d: %s" % (
                feature.name, exc.lineno or 0, exc.msg),
                ["The source is Python; it hands back its solid with "
                 "result(solid) or a variable body."]) from exc
        from ..core import rules
        if rules.code_hash(source) in self.entry.foreign_code:
            self.notes.append(
                "%s: this source came with the file and is not trusted; "
                "it waits for the user to allow it in the app" % feature.name)
            return
        gate = self.entry.code_gate
        if gate is not None and not rules.code_trusted(source):
            # the app: the person reads the source and decides, once per
            # source. Until they allow it the feature waits for trust, as
            # code that came in a file does, and the build still lands.
            if not gate(feature.name, source):
                self.notes.append(
                    "%s: the user has not allowed this code to run; it "
                    "waits for trust until they do (ask them to allow it "
                    "in the app)" % feature.name)
                return
        checked = ""
        if gate is None:
            # headless: the server's --code decides (see codepolicy)
            from . import codepolicy, safemode
            policy = codepolicy.mode()
            if policy == "off":
                self.notes.append(
                    "%s: agent code is off on this server (--code off); the "
                    "feature waits for trust until the user allows it in "
                    "the app" % feature.name)
                return
            # after "allow for this session" code runs unasked, so code
            # the user has not seen runs in safe mode even with --code full
            unseen = (policy == "full" and codepolicy.unseen_runs_safe()
                      and not rules.code_trusted(source))
            if policy == "safe" or unseen:
                try:
                    safemode.check(source)
                except safemode.SafeModeViolation as exc:
                    raise BridgeError("SAFE_MODE", "%s: line %d: %s" % (
                        feature.name, exc.line, exc), [
                        "The user allowed agent code for this session, and "
                        "code that runs without a prompt runs in safe mode: "
                        "math-like imports only, no file access, no eval or "
                        "exec, no dunders. Rewrite it with the helpers in "
                        "scope, or ask the user to allow this code by "
                        "itself (run it as a script, which asks)."
                        if unseen else
                        "This server checks code features in safe mode "
                        "(--code safe): math-like imports only, no file "
                        "access, no eval or exec, no dunders. Rewrite it "
                        "with the helpers in scope, or ask the user to "
                        "start the server with --code full."]) from exc
                checked = (", checked in safe mode (allowed for the "
                           "session, not by itself)" if unseen
                           else ", checked in safe mode")
            if codepolicy.asks() and not rules.code_trusted(source):
                # the server asks the user first (codepolicy, "asking
                # first"); until they allow it, it waits for trust
                codepolicy.pending.append({
                    "feature": feature.name, "hash": rules.code_hash(source),
                    "source": source, "doc": self.entry.handle})
                self.notes.append(
                    "%s: waits for the user to allow this code%s"
                    % (feature.name, checked))
                return
        rules.trust_code(source)
        self.notes.append("%s: agent code will run%s; trusted for this "
                          "session by its source hash, and a person opening "
                          "the saved file is asked again"
                          % (feature.name, checked))

    def sugar_frame_member(self, spec, feature, new=False) -> None:
        """A member sized from a profile family ("family" and "size", the
        family's kind and dims filled in), or from "kind" and "dims" given
        outright; either way every column of its kind must be there, or
        the build fails saying which, not with a bare KeyError."""
        from ..core import frames
        if feature.family and feature.size and (new or "family" in spec
                                                or "size" in spec):
            try:
                fam = frames.family(feature.family)
                feature.dims = fam.row(feature.size)
            except KeyError as exc:
                known = ", ".join(f.id for f in frames.families())
                raise BridgeError(
                    "BAD_VALUE", str(exc).strip("'\""),
                    ["Families: %s." % known,
                     "Or give kind and dims outright, e.g. "
                     '"kind":"square_tube","dims":{"b":40,"t":3,"ro":6}.'
                     ]) from exc
            if "kind" not in spec:
                feature.kind = fam.kind
        need = frames.COLUMNS.get(feature.kind)
        if need is None and feature.kind != "sketch":
            raise BridgeError("BAD_VALUE", "there is no profile kind %r"
                              % feature.kind,
                              ["Kinds: %s." % ", ".join(frames.COLUMNS)])
        missing = [c for c in need or [] if c not in (feature.dims or {})
                   and c not in ("r", "r1", "r2", "ro", "slope")]
        if missing:
            raise BridgeError(
                "BAD_VALUE", "a %s member needs dims %s (missing %s)" % (
                    feature.kind, ", ".join(need), ", ".join(missing)),
                ['"dims":{%s}' % ", ".join('"%s":..' % c for c in need),
                 "Or name a family and size from the library: \"family\":"
                 " %r, \"size\": ..." % frames.families()[0].id])

    def sugar_fillet(self, spec, feature, new=False) -> None:
        self._edges(spec, feature, "radius")

    def sugar_chamfer(self, spec, feature, new=False) -> None:
        self._edges(spec, feature, "distance")

    def sugar_sketch(self, spec, feature, new=False) -> None:
        names = None
        if not new:
            names = dict(self.sketch_names.get(feature.id) or {})
        if "plane" in spec:
            self.place_sketch(feature, spec["plane"])
        elif new and "sketch" not in spec:
            self.place_sketch(feature, "XY")
        draws = any(k in spec for k in ("entities", "constraints",
                                        "dimensions"))
        if not draws:
            return
        old_names: Dict[str, Tuple[str, int]] = {}
        if "entities" in spec or names is None:
            old_names = dict(names or {})
            feature.sketch = Sketch(feature.sketch.plane, feature.name)
            names = {}
        sb = SketchBuilder(self, feature.sketch, names)
        sb.job_auto = bool(spec.get("auto_constrain", True))
        # New dimensions get d-names nobody in the part has, as in the
        # sketcher: a parameter the agent called d1 is otherwise shadowed
        # by the sketch's own first dimension, and "d": "d1" means itself.
        from ..core.modelparams import taken_names
        feature.sketch.name_pool = lambda: taken_names(self.doc)
        try:
            for n, ent in enumerate(spec.get("entities") or []):
                sb.entity(ent, n)
            for n, c in enumerate(spec.get("constraints") or []):
                sb.constraint(c, n)
            for n, c in enumerate(spec.get("dimensions") or []):
                sb.constraint(c, n, need_value=True)
        finally:
            feature.sketch.name_pool = None
        sk = feature.sketch
        sk.solve(self.doc.parameter_scope())
        if sk.conflicting or sk.solve_message.startswith("over"):
            from .sketchir import constraint_text
            pn = {o: k for k, (t, o) in names.items() if t == "point"}
            en = {o: k for k, (t, o) in names.items() if t == "entity"}
            bad = [constraint_text(sk.constraints[c],
                                   lambda p: pn.get(p, "#p%d" % p),
                                   lambda e: en.get(e, "#e%d" % e))
                   for c in sk.conflicting if c in sk.constraints]
            raise BridgeError(
                "OVER_CONSTRAINED",
                "%s cannot be solved: %s" % (feature.name,
                                             "; ".join(bad) or sk.solve_message),
                ["Remove a constraint or dimension that repeats another, "
                 "or one that asks for something impossible."],
                conflicts=bad)
        if old_names:
            sk = self.keep_ids(feature, sk, old_names, names)
        self._driven(feature, sk, sb.new_dims, names)
        if sk.dof:
            self.notes.append("%s: %d DOF left (sketch_status says what can "
                              "move)" % (feature.name, sk.dof))
        if new:
            feature._names = names
        else:
            self.sketch_names[feature.id] = names

    def keep_ids(self, feature, sk: Sketch, old_names, names) -> Sketch:
        """A sketch written out again keeps the ids of what it had before.

        The ops draw a sketch from nothing, so every point and entity got
        a new id, in the order they were written: add one first and all the
        others moved up by one. A hole's points, a revolve's axis and every
        role of the kind "the side swept from entity 6" are kept by id, so
        they were left pointing at something else. What the agent named it
        has named before, here and in the last version, so a point or
        entity that keeps its name keeps its id, and what is new gets one
        no old id used."""
        maps = {"point": {}, "entity": {}}
        for name, (kind, now) in names.items():
            was = old_names.get(name)
            if kind in maps and was and was[0] == kind and was[1] != now:
                maps[kind][now] = was[1]
        if not maps["point"] and not maps["entity"]:
            return sk
        data = sk.to_dict()
        taken = {k: {p["id"] for p in data["points"]} if k == "point"
                 else {e["id"] for e in data["entities"]} for k in maps}
        top = max([data.get("next_id", 1)] + [v[1] for v in old_names.values()]
                  + list(taken["point"]) + list(taken["entity"])) + 1
        full: Dict[str, Dict[int, int]] = {}
        for kind, kept in maps.items():
            keep_to = set(kept.values())
            out = dict(kept)
            for now in sorted(taken[kind]):
                if now in out:
                    continue
                if now in keep_to:
                    out[now] = top      # its number is somebody's, moved
                    top += 1
                else:
                    out[now] = now
            full[kind] = out
        pm, em = full["point"], full["entity"]
        for p in data["points"]:
            p["id"] = pm.get(p["id"], p["id"])
        for e in data["entities"]:
            e["id"] = em.get(e["id"], e["id"])
            e["points"] = [pm.get(i, i) for i in e["points"]]
        for c in data["constraints"]:
            c["points"] = [pm.get(i, i) for i in c["points"]]
            c["entities"] = [em.get(i, i) for i in c["entities"]]
        for p in data.get("projections", []):
            p["entities"] = [em.get(i, i) for i in p["entities"]]
        for t in data.get("texts", []):
            if "point" in t:
                t["point"] = pm.get(t["point"], t["point"])
        data["next_id"] = top
        moved = Sketch.from_dict(data)
        feature.sketch = moved
        for name, (kind, now) in list(names.items()):
            if kind == "point":
                names[name] = (kind, pm.get(now, now))
            elif kind == "entity":
                names[name] = (kind, em.get(now, now))
        return moved

    def _driven(self, feature, sk: Sketch, new_dims: List[int],
                names) -> None:
        """A dimension that holds nothing the sketch had not already
        fixed agrees with it today and fights it after the next parameter
        change, so it is made driven, as Inventor offers to: it reads the
        size instead of setting it."""
        scope = self.doc.parameter_scope()
        for cid in new_dims:
            c = sk.constraints.get(cid)
            if c is None or not c.driving:
                continue
            # Without it, is the size it sets still fixed? Asked of the
            # geometry rather than of the solver's rank, which redundant
            # rows can inflate: nudge every free point and radius, solve
            # again, and see whether the size comes back.
            trial = sk.copy()
            trial.constraints[cid].driving = False
            for pid, p in trial.points.items():
                if not p.fixed:
                    p.x += 0.05 * math.sin(pid * 12.9898 + 1.0)
                    p.y += 0.05 * math.cos(pid * 78.233 + 2.0)
            for eid, e in trial.entities.items():
                if e.kind in ("circle", "arc", "ellipse"):
                    e.radius += 0.03 * (1 + math.sin(eid * 3.7))
            trial.solve(scope)
            if abs(abs(trial.measure(trial.constraints[cid]))
                   - abs(c.value)) < 1e-6:
                from .sketchir import constraint_text
                pn = {o: k for k, (t, o) in names.items() if t == "point"}
                en = {o: k for k, (t, o) in names.items() if t == "entity"}
                self.notes.append(
                    "%s: %s repeats what is already fixed, so it was made "
                    "driven (it measures, it does not set)" % (
                        feature.name, constraint_text(
                            c, lambda p: pn.get(p, "#p%d" % p),
                            lambda e: en.get(e, "#e%d" % e))))
                c.driving = False
                c.expression = ""
        sk.solve(scope)

    def place_sketch(self, feature: SketchFeature, plane: Any) -> None:
        feature.face_ref = None
        feature.reverse_face = False
        feature.plane_ref = ""
        feature.reverse_plane = False
        if is_placed(plane):
            raise BridgeError(
                "BAD_OP", "a sketch that exists cannot take a plane by "
                "numbers in an edit: the plane has to come before it",
                ['Add {"op":"workplane","mode":"placed","origin":..,'
                 '"normal":..}, move it before the sketch, then set the '
                 "sketch's plane to it."])
        if isinstance(plane, str) and plane.upper() in STANDARD_PLANES:
            key = plane.upper()
            feature.plane_ref = key
            feature.sketch.plane = SketchPlane.from_dict(
                STANDARD_PLANES[key].to_dict())
            return
        if isinstance(plane, str) and not plane.startswith("$") \
                and plane in self.doc.planes:
            feature.plane_ref = plane
            feature.sketch.plane = SketchPlane.from_dict(
                self.doc.planes[plane].to_dict())
            return
        if isinstance(plane, str) and plane.startswith("$"):
            fid, rest = self.split(plane, "sketch plane")
            f = self.doc.feature(fid)
            if not rest and f is not None and f.type_name == "workplane":
                self.doc.rebuild()
                if f.name not in self.doc.planes:
                    raise BridgeError("BAD_REF", "work plane %s did not "
                                      "build" % f.name)
                feature.plane_ref = f.name
                feature.sketch.plane = SketchPlane.from_dict(
                    self.doc.planes[f.name].to_dict())
                return
        kind, faces = self.picks(plane, "sketch plane")
        if kind != "face" or not faces:
            raise BridgeError("BAD_REF", "a sketch goes on a plane or a "
                              "flat face")
        from OCP.TopAbs import TopAbs_REVERSED
        from OCP.TopoDS import TopoDS
        face = TopoDS.Face_s(faces[0])
        derived = plane_from_face(face)
        if derived is None:
            raise BridgeError("NOT_FLAT", "that face is not flat",
                              ["Pick a planar face."])
        reverse = face.Orientation() == TopAbs_REVERSED
        if reverse:
            derived = SketchPlane(derived.origin,
                                  tuple(-c for c in derived.normal),
                                  derived.xdir, "Face")
        index = next((i for i, f in enumerate(kernel.faces(self.shape()))
                      if f.IsSame(face)), 0)
        feature.face_ref = ShapeRef.capture(face, "face", index)
        feature.reverse_face = reverse
        feature.sketch.plane = derived
        self.notes.append(
            "%s on a face: origin %s, normal %s, x along %s" % (
                feature.name, _vec(derived.origin), _vec(derived.normal),
                _vec(derived.xdir)))

    # tree ops ----------------------------------------------------------

    def op_parameter(self, spec) -> None:
        name = spec.get("name")
        if spec.get("remove"):
            if name not in self.doc.params:
                raise BridgeError("BAD_OP", "no parameter %r to remove" % name)
            self.doc.params.remove(name)
            return
        if "expression" in spec:
            # properties() reports a parameter's "expression", so agents
            # write it back that way; it is the same thing as value
            spec = dict(spec)
            expr = spec.pop("expression")
            if "value" in spec and str(spec["value"]) != str(expr):
                raise BridgeError(
                    "BAD_OP", "parameter %s: value %r and expression %r "
                    "disagree" % (name, spec["value"], expr),
                    ["Give one: value takes a number or an expression "
                     "string, such as \"s/cos(30)\"."])
            spec["value"] = expr
        if not name or "value" not in spec:
            raise BridgeError("BAD_OP", "a parameter op needs name and value",
                              ["value takes a number or an expression "
                               "string: {\"op\":\"parameter\",\"name\":\"w\","
                               "\"value\":\"2*h\"}"])
        extra = set(spec) - {"op", "name", "value", "comment", "unit", "id",
                             "remove"}
        if extra:
            raise BridgeError("BAD_OP", "parameter: unknown field(s) %s"
                              % ", ".join(sorted(extra)))
        params = self.doc.params
        unit = str(spec.get("unit", "mm"))
        kind = {"deg": "angle", "ul": "count"}.get(unit, "length")
        value = self.stored(spec["value"], kind, name)
        if name in params:
            params.set_expression(name, value)
        else:
            params.add(name, value, comment=str(spec.get("comment", "")))
        if spec.get("comment") is not None and name in params:
            params[name].comment = str(spec["comment"])
        if "unit" in spec and hasattr(params[name], "unit"):
            params[name].unit = unit
        params.evaluate_all()
        if params[name].error:
            raise BridgeError("BAD_EXPRESSION", "%s: %s"
                              % (name, params[name].error))

    def op_properties(self, spec) -> None:
        extra = set(spec) - {"op", "id", "material", "appearance", "props"}
        if extra:
            raise BridgeError("BAD_OP", "properties: unknown field(s) %s"
                              % ", ".join(sorted(extra)),
                              ["It takes appearance, material and props."])
        set_properties(self.doc, spec.get("props"), spec.get("material"),
                       spec.get("appearance"))
        self.doc.modified = True
        self.notes.append("properties set: %s" % ", ".join(
            k for k in ("appearance", "material", "props") if k in spec))

    def op_edit(self, spec) -> None:
        f = self.feature(spec.get("feature"), "edit")
        changes = dict(spec.get("set") or {})
        changes.update({k: v for k, v in spec.items()
                        if k not in ("op", "feature", "set", "id")})
        if not changes:
            raise BridgeError("BAD_OP", "edit: nothing to change",
                              ['{"op":"edit","feature":"Extrusion1",'
                               '"set":{"distance":"t*2"}}'])
        self.check_keys(f.type_name, changes)
        if "id" in changes or "op" in changes:
            raise BridgeError("BAD_OP", "edit: id and op cannot change")
        index = self.doc.index_of(f.id)
        data = f.to_dict()
        before = f.to_dict()
        data = self.fields(f.type_name, changes, data)
        new = Feature.from_dict(data)
        new.id = f.id
        sugar = getattr(self, "sugar_%s" % f.type_name, None)
        if sugar is not None:
            sugar(changes, new, new=False)
        if "name" in changes and changes["name"] != f.name:
            new.name = self.doc.unique_name(str(changes["name"]))
        if isinstance(new, SketchFeature):
            new.sketch.name = new.name
        self.doc.features[index] = new
        self.doc.modified = True
        after = new.to_dict()
        diff = sorted(k for k in set(before) | set(after)
                      if before.get(k) != after.get(k))
        self.changed.append({"id": f.id, "name": new.name,
                             "type": f.type_name, "fields": diff})
        if spec.get("id"):
            self.names[str(spec["id"])] = f.id

    def dependents(self, fid: int) -> List[Feature]:
        """Everything that uses fid, directly or through another."""
        out: List[Feature] = []
        todo = [fid]
        while todo:
            here = todo.pop()
            for f in self.doc.dependents_of(here):
                if f not in out:
                    out.append(f)
                    todo.append(f.id)
        return out

    def op_remove(self, spec) -> None:
        f = self.feature(spec.get("feature"), "remove")
        mode = spec.get("dependents", "refuse")
        deps = self.dependents(f.id)
        if deps and mode != "remove":
            raise BridgeError(
                "HAS_DEPENDENTS", "%s is used by %s" % (
                    f.name, ", ".join(d.name for d in deps)),
                ['Remove those too with "dependents": "remove", or edit '
                 "them to use something else first."],
                dependents=[{"id": d.id, "name": d.name, "type": d.type_name}
                            for d in deps])
        for gone in [f] + deps:
            self.doc.remove_feature(gone.id)
            self.sketch_names.pop(gone.id, None)
            self.removed.append({"id": gone.id, "name": gone.name,
                                 "type": gone.type_name})

    def op_move(self, spec) -> None:
        f = self.feature(spec.get("feature"), "move")
        feats = self.doc.features
        feats.remove(f)
        if "before" in spec:
            index = self.doc.index_of(self.feature_id(spec["before"], "before"))
        elif "after" in spec:
            index = self.doc.index_of(self.feature_id(spec["after"],
                                                      "after")) + 1
        elif spec.get("to") in ("end", None):
            index = len(feats)
        elif spec.get("to") == "start":
            index = 0
        else:
            index = max(0, min(len(feats), int(spec["to"])))
        feats.insert(index, f)
        self.doc.modified = True
        order = {g.id: i for i, g in enumerate(feats)}
        late = [self.doc.feature(d).name for d in f.depends_on()
                if order.get(d, -1) > index]
        users = [g.name for g in feats[:index] if f.id in g.depends_on()]
        if late or users:
            raise BridgeError(
                "BAD_ORDER", "%s would come %s" % (
                    f.name, ("before %s, which it uses" % ", ".join(late))
                    if late else ("after %s, which use it"
                                  % ", ".join(users))),
                ["A feature has to come after what it is built from."])
        self.changed.append({"id": f.id, "name": f.name,
                             "type": f.type_name, "moved_to": index})

    # lint ----------------------------------------------------------------

    def lint(self, threshold: int = 3) -> List[str]:
        """Numbers written out again and again, which want a name."""
        counts: Dict[Tuple[float, str], int] = {}
        for value, unit in self.literals:
            if abs(value) < 1e-12 or abs(abs(value) - 1) < 1e-12:
                continue
            key = (round(abs(value), 6), unit)
            counts[key] = counts.get(key, 0) + 1
        values = {}
        for name in self.doc.params.names():
            try:
                values[round(abs(self.doc.params[name].value), 6)] = name
            except Exception:
                pass
        out = []
        for (value, unit), n in sorted(counts.items(), key=lambda kv: -kv[1]):
            if n < threshold:
                continue
            u = "deg" if unit == "angle" else "mm"
            same = values.get(value)
            out.append("%s %s used %d times; %s" % (
                _num(value), u, n,
                "parameter %s has that value: use it?" % same if same
                else "make it a parameter?"))
        return out


# ---------------------------------------------------------------- helpers


def _num(v: float) -> str:
    return ("%.6f" % v).rstrip("0").rstrip(".")


def _vec(v) -> str:
    return "[%s]" % ", ".join(_num(round(c, 6)) for c in v)


def _short(where: Any) -> str:
    import json
    return json.dumps(where)


def _outer_point_in(point, polygon) -> bool:
    x, y = point
    inside = False
    for (x0, y0), (x1, y1) in zip(polygon, polygon[1:] + polygon[:1]):
        if (y0 > y) != (y1 > y):
            if x < x0 + (y - y0) * (x1 - x0) / (y1 - y0):
                inside = not inside
    return inside


def _outline(region) -> List[Tuple[float, float]]:
    """A region's outer boundary as a polygon in sketch coordinates."""
    from OCP.BRepTools import BRepTools
    from OCP.TopoDS import TopoDS
    from ..core import hlr

    face = region["face"]
    sketch = region["sketch"]
    try:
        wire = BRepTools.OuterWire_s(TopoDS.Face_s(face))
    except Exception:
        return []
    pts: List[Tuple[float, float]] = []
    for edge in kernel.edges(wire):
        for run in hlr._flatten_3d(edge):
            pts.extend(sketch.plane.to_2d(p) for p in run)
    return pts


def set_properties(document, props=None, material=None,
                   appearance=None) -> None:
    """Write iProperties, material and appearance, each checked."""
    from ..core import materials
    lib = materials.library()
    if material:
        if material not in lib.materials:
            from .ops import _material_hints
            raise BridgeError("UNKNOWN_MATERIAL", "no material %r" % material,
                              _material_hints(material, lib.materials))
    look = None
    if appearance is not None and appearance != "":
        look = str(appearance).strip()
        if look.lower() in ("none", "material"):
            look = ""               # back to what the material looks like
        elif look not in lib.appearances:
            named = {n.lower(): n for n in lib.appearances}
            look = named.get(look.lower()) or materials.plain_colour(look)
            if not look:
                raise BridgeError(
                    "BAD_VALUE", "no appearance %r" % appearance,
                    ['A colour is "#rrggbb"; "material" follows the '
                     "material again.",
                     "By name: %s" % ", ".join(sorted(lib.appearances))])
    for key, value in (props or {}).items():
        document.properties[str(key)] = str(value)
    if material:
        document.material = material
    if look is not None:
        document.appearance = look


def is_placed(plane: Any) -> bool:
    """A plane given by numbers, rather than named or picked."""
    return (isinstance(plane, dict) and "faces" not in plane
            and ("normal" in plane or "origin" in plane))


def pick_regions(regions: List[Dict[str, Any]], how: Any):
    """Which regions are taken, from regions sorted largest first.

    ``outer`` (the default) takes every region that is not a hole: a
    region inside the outline of an odd number of others is one, which is
    how a plate with a circle in it extrudes as a plate with a hole and an
    island inside that hole comes back as material.
    """
    if how == "all":
        return regions
    if how in ("largest", "smallest"):
        pick = max if how == "largest" else min
        return [pick(regions, key=lambda r: r["area"])]
    if how == "outer":
        outlines = [_outline(r) for r in regions]
        keep = []
        for i, r in enumerate(regions):
            depth = sum(1 for j, poly in enumerate(outlines)
                        if j != i and len(poly) > 2
                        and _outer_point_in(r["centre"], poly))
            if depth % 2 == 0:
                keep.append(r)
        return keep or regions
    if isinstance(how, list):
        try:
            return [regions[int(i)] for i in how]
        except (IndexError, ValueError) as exc:
            raise BridgeError(
                "BAD_OP", "profile index out of range",
                ["The sketch has %d regions, largest first: %s" % (
                    len(regions), [round(r["area"], 2) for r in regions])]
            ) from exc
    raise BridgeError("BAD_OP", "profiles must be outer, all, largest, "
                      "smallest or a list of indices (largest first)")


def _surface(face) -> str:
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_SurfaceType as T
    kind = BRepAdaptor_Surface(face).GetType()
    return {T.GeomAbs_Plane: "plane", T.GeomAbs_Cylinder: "cylinder",
            T.GeomAbs_Cone: "cone", T.GeomAbs_Sphere: "sphere",
            T.GeomAbs_Torus: "torus"}.get(kind, "other")


def outward_normal(face):
    from OCP.TopAbs import TopAbs_REVERSED
    plane = plane_from_face(face)
    if plane is None:
        return None
    n = plane.normal
    if face.Orientation() == TopAbs_REVERSED:
        n = tuple(-c for c in n)
    return n


def select_faces(shape, where: Any) -> List[Any]:
    """Faces by rule, as edgequery picks edges: all conditions of a dict
    must hold, a list takes the union.

        {"normal": "+z"}     flat faces looking along +z
        {"at": "-x"}         faces on that side of the bounding box
        {"kind": "cylinder"} plane, cylinder, cone, sphere, torus
        {"near": [x,y,z], "count": 1}, {"largest": true}, {"min_area": 5}
    """
    from OCP.TopoDS import TopoDS
    queries = where if isinstance(where, list) else [where]
    pool = [TopoDS.Face_s(f) for f in kernel.faces(shape)]
    box = kernel.bounding_box(shape)
    tol = 1e-4 * max(1.0, box[3] - box[0], box[4] - box[1], box[5] - box[2])
    found: List[Any] = []
    for q in queries:
        if not isinstance(q, dict):
            raise BridgeError("BAD_QUERY", "a face query is a dict",
                              ['e.g. {"normal": "+z"}'])
        unknown = set(q) - set(FACE_KEYS)
        if unknown:
            raise BridgeError("BAD_QUERY", "unknown face condition(s): %s"
                              % ", ".join(sorted(unknown)),
                              ["Known: %s" % ", ".join(FACE_KEYS)])
        hits = []
        for f in pool:
            if "kind" in q:
                if q["kind"] not in SURFACES:
                    raise BridgeError("BAD_QUERY", "unknown kind %r"
                                      % q["kind"],
                                      ["Kinds: %s" % ", ".join(SURFACES)])
                if _surface(f) != q["kind"]:
                    continue
            if "normal" in q:
                axis, sign = edgequery._axis(q["normal"])
                n = outward_normal(f)
                if n is None or abs(n[axis] - sign) > 1e-6:
                    continue
            if "at" in q:
                axis, sign = edgequery._axis(q["at"])
                fb = kernel.bounding_box(f)
                if sign > 0 and fb[axis] < box[axis + 3] - tol:
                    continue
                if sign < 0 and fb[axis + 3] > box[axis] + tol:
                    continue
            if "min_area" in q and kernel.face_area(f) < float(q["min_area"]):
                continue
            hits.append(f)
        if "near" in q:
            p = [float(v) for v in q["near"]]
            hits.sort(key=lambda f: math.dist(kernel.shape_centre(f), p))
            hits = hits[:int(q.get("count", 1))]
        elif q.get("largest"):
            hits.sort(key=lambda f: -kernel.face_area(f))
            hits = hits[:int(q.get("count", 1))]
        for f in hits:
            if not any(f.IsSame(x) for x in found):
                found.append(f)
    if not found:
        raise BridgeError("NO_MATCH", "no face matches %s" % (where,),
                          ["Render the part, or loosen the query."])
    return found
