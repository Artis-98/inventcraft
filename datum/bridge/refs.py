"""Geometry references an agent can read and write: plan §5.

A reference is a string, never an index into the topology:

    Extrusion3.end          the end cap of an extrusion (also revolve, sweep,
                            loft: .start and .end)
    Extrusion3.start        its start cap
    Extrusion3.side(a)      the side face swept from sketch entity a
    Extrusion3.end.edge(side(a))
                            the edge between two faces (any two roles; the
                            second may be another feature's, in full)
    Hole2.wall[0]           the wall of the first hole (wall: every hole)
    Hole2.cbore[0]          the counterbore wall of the first hole
    Hole2.shoulder[0] .floor[0] .csink[0]
                            the step of a counterbore, the floor of a blind
                            hole, the cone of a countersink
    Fillet5.face[0]         the round made from its first edge (also chamfer)
    Sketch1.region[0]       a sketch's closed region, largest first
    Sketch1.c1.center       a named sketch point (or entity, #p3 / #e4 by id)
    @F:3a7c0e  @E:..  @V:.. a handle find_geometry gave: a face, edge, vertex
    body:Solid1   part      a whole body, or the whole part (measure)

``$`` in front (``$e1.end``) names an op in the same build, as before.

How each resolves is reported as ``via``:

    role         provenance: the kernel's own history says which feature made
                 which face (core/provenance.py), so the face is found by
                 what made it. Follows any parameter change, a feature added
                 earlier in the tree, and a sketch written out again, for as
                 long as the face exists. Tried first
    definition   worked out from the feature's own inputs (its sketch, its
                 distance, its hole centres): the second route, for a part
                 whose provenance is not there (a body too big to tag, a
                 face a feature changed without saying how)
    fingerprint  an ``@`` handle, rebound by ``core.naming.ShapeRef``: where
                 the face was, how big, what surface. A handle also keeps
                 the roles of the face it was made on, so it is followed by
                 those first and falls back to where it was; the answer then
                 says so. Fails plainly rather than guessing after a big
                 change

A handle is minted from a fingerprint, so the same face gets the same
handle every time it is found, and the handles live with the document in
the host for as long as it is open.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from typing import Any, Dict, List, Optional, Tuple

from ..core import edgequery, kernel, provenance
from ..core import requirements as reqs
from ..core.features import BuildContext, collect_regions, plane_from_face
from ..core.naming import ShapeRef
from .errors import BridgeError

HANDLE_RE = re.compile(r"^@([FEV]):([0-9a-fA-F]{4,16})$")
FEATURE_RE = re.compile(r"^\$?([^.\[\]()]+?)(?:\.(.+))?$")
INDEXED_RE = re.compile(r"^(region|wall|cbore)(?:\[(\d+)\])?$")
SIDE_RE = re.compile(r"^side\(([^)]*)\)(.*)$")
LETTER = {"face": "F", "edge": "E", "vertex": "V"}
KIND = {v: k for k, v in LETTER.items()}

GRAMMAR = {
    "forms": {
        "Extrusion3.end / .start": "end and start caps of an extrusion, "
        "revolve, sweep or loft (via role, else definition)",
        "Extrusion3.side(a)": "the side face swept from sketch entity a "
        "(a build name, or #e4 by id; via role, or definition for an "
        "untapered extrusion)",
        "Extrusion3.end.edge(side(a))": "the edge between two faces: any "
        "face role, then .edge(another role of the same feature, or a "
        "whole reference such as Hole2.wall[0])",
        "Hole2.wall[0] / Hole2.wall": "a hole's bore, by the order of its "
        "centres; every hole without an index",
        "Hole2.cbore[0]": "a counterbore's wall",
        "Hole2.shoulder[0] / .floor[0] / .csink[0]": "a counterbore's step, "
        "a blind hole's floor, a countersink's cone (via role)",
        "Fillet5.face[0] / Chamfer6.face[0]": "the round or bevel made from "
        "the feature's first edge, in the order the edges were given (via "
        "role). The faces are also kept by the edge they round, which an "
        "edge added earlier in the tree does not renumber",
        "Sketch1.region[0] / Sketch1.region": "a sketch's closed regions, "
        "largest first (a flat face of the sketch, not of the body)",
        "Sketch1.c1.center": "a named sketch point or entity, in 3D",
        "@F:xxxxxx @E:xxxxxx @V:xxxxxx": "handles from find_geometry, "
        "rebound by fingerprint",
        "body:Name / part": "a whole body, or the whole part (measure)",
        "Wheel:1/Hole1.wall[0]": "in an assembly: <occurrence>/<any "
        "reference above>, resolved in that component's part and taken on "
        "the placed body (an occurrence is its name, #id, or the part's "
        "name while only one is placed)",
        "Wheel:1/origin.XY": "in an assembly: the component's own origin "
        "plane (XY, XZ, YZ), axis (X, Y, Z) or origin.point; for "
        "constrain() only",
        "Wheel:1": "in an assembly: a whole component (measure, "
        "render_view highlight)",
        "[x, y, z]": "a point (measure only)",
        "$id.<any of these>": "an op of the same build",
    },
    "via": {
        "role": "provenance: the kernel's history says which feature made "
        "the face. Tried first; follows parameter changes, features added "
        "earlier and a sketch written out again",
        "definition": "worked out from the feature's own inputs; the second "
        "route, where the part has no provenance for the face",
        "fingerprint": "an @ handle rebound by where and what it was, after "
        "its roles (kept with the handle) found nothing; the answer's note "
        "says so",
    },
    "examples": ["Extrusion1.end", "Extrusion1.side(r.top)", "Hole1.wall[2]",
                 "Sketch1.region[0]", "@F:9c41a2", "Wheel:1/Hole1.wall[0]"],
}


# ---------------------------------------------------------------- handles


def _fingerprint_key(ref: Dict[str, Any]) -> str:
    text = json.dumps([ref["kind"], [round(c, 4) for c in ref["centre"]],
                       round(ref["size"], 4), ref["geom"]])
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def handle_for(entry, sub, kind: str, shape) -> str:
    """The handle for one face, edge or vertex of ``shape``."""
    pool = (kernel.faces(shape) if kind == "face" else kernel.edges(shape)
            if kind == "edge" else kernel.vertices(shape))
    index = next((i for i, c in enumerate(pool) if c.IsSame(sub)), 0)
    ref = ShapeRef.capture(sub, kind, index,
                           within=shape if kind == "vertex" else None)
    ref.attach_roles(shape, sub)
    data = ref.to_dict()
    key = _fingerprint_key(data)
    handles = entry.handles
    for n in (6, 8, 10, 12, 16):
        code = key[:n]
        held = handles.get(code)
        if held is None or _fingerprint_key(held) == key:
            if held is not None and (held.get("roles") or held.get(
                    "adjacent")) and not (data.get("roles")
                                          or data.get("adjacent")):
                # asked again where nothing is known of the face: the
                # roles it had are not thrown away for that
                data = dict(data, roles=held.get("roles", []),
                            adjacent=held.get("adjacent", []))
            handles[code] = data
            return "@%s:%s" % (LETTER[kind], code)
    handles[key] = data
    return "@%s:%s" % (LETTER[kind], key)


# ---------------------------------------------------------------- results


class Resolved:
    """What a reference came to: shapes of one kind, and how."""

    def __init__(self, text: str, kind: str, shapes: List[Any], via: str,
                 note: str = "") -> None:
        self.text, self.kind, self.shapes, self.via = text, kind, shapes, via
        self.note = note

    def describe(self) -> Dict[str, Any]:
        out = {"ref": self.text, "kind": self.kind, "via": self.via,
               "count": len(self.shapes)}
        if self.note:
            out["note"] = self.note
        return out


def _vertex(point):
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeVertex
    from OCP.gp import gp_Pnt
    return BRepBuilderAPI_MakeVertex(gp_Pnt(*[float(c) for c in point])
                                     ).Vertex()


def _polyline_edge(points3):
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakePolygon
    from OCP.gp import gp_Pnt
    poly = BRepBuilderAPI_MakePolygon()
    for p in points3:
        poly.Add(gp_Pnt(*p))
    return poly.Wire()


def _point_face_distance(point, face) -> float:
    return reqs.min_distance(_vertex(point), face)["distance"]


# ---------------------------------------------------------------- resolver


class Resolver:
    """Turns reference strings into shapes, for one document.

    ``job`` is the build the reference is written in, for ``$id`` names;
    any other use makes its own."""

    def __init__(self, entry, job=None) -> None:
        from .build import Build
        self.entry = entry
        self.doc = entry.document
        self.job = job or Build(entry)

    def shape(self):
        if self.doc.shape is None or self.doc.shape.IsNull():
            raise BridgeError("NO_BODY", "there is no solid yet")
        return self.doc.shape

    def tolerance(self) -> float:
        box = kernel.bounding_box(self.shape())
        return 1e-4 * max(1.0, box[3] - box[0], box[4] - box[1],
                          box[5] - box[2])

    # entry point ---------------------------------------------------------

    def resolve(self, ref: Any, what: str = "ref",
                allow: Tuple[str, ...] = ("face", "edge", "vertex")
                ) -> Resolved:
        if isinstance(ref, (list, tuple)) and len(ref) == 3 and all(
                isinstance(c, (int, float)) for c in ref):
            if "point" not in allow:
                raise BridgeError("BAD_REF", "%s: a point is not a face or "
                                  "edge" % what)
            return Resolved(json.dumps(list(ref)), "point",
                            [_vertex(ref)], "given")
        if not isinstance(ref, str) or not ref.strip():
            raise BridgeError("BAD_REF", "%s: %r is not a reference" % (
                what, ref), ["See ic://schema/ref for the forms."])
        text = ref.strip()
        out = self._resolve(text, what, allow)
        if out.kind not in allow:
            raise BridgeError(
                "BAD_REF", "%s: %s is a %s; this takes %s" % (
                    what, text, out.kind, " or ".join(allow)))
        if not out.shapes:
            raise BridgeError("NO_MATCH", "%s: %s matches nothing on the "
                              "body now" % (what, text),
                              ["find_geometry shows what is there."])
        return out

    def _resolve(self, text: str, what: str, allow) -> Resolved:
        m = HANDLE_RE.match(text)
        if m:
            return self.handle(text, KIND[m.group(1).upper()],
                               m.group(2).lower(), what)
        if text == "part":
            return Resolved(text, "body", [self.shape()], "definition")
        if text.startswith("body:"):
            name = text[5:]
            for body in self.doc.bodies:
                if getattr(body, "name", "") == name:
                    return Resolved(text, "body", [body.shape], "definition")
            raise BridgeError("BAD_REF", "%s: no body %r" % (what, name),
                              ["Bodies: %s" % ", ".join(
                                  getattr(b, "name", "?")
                                  for b in self.doc.bodies)])
        m = FEATURE_RE.match(text)
        if not m:
            raise BridgeError("BAD_REF", "%s: cannot read %r" % (what, text),
                              ["See ic://schema/ref for the forms."])
        head = m.group(1)
        fid = self.job._token(head)
        if fid is None:
            if not text.startswith("$"):
                for body in self.doc.bodies:
                    if getattr(body, "name", "") == text:
                        return Resolved(text, "body", [body.shape],
                                        "definition")
            raise BridgeError(
                "BAD_REF", "%s: no feature or op is %r" % (what, head),
                ["Features: %s" % ", ".join(
                    f.name for f in self.doc.features)])
        feature = self.doc.feature(fid)
        rest = m.group(2) or ""
        return self.role(feature, rest, text)

    # handles -------------------------------------------------------------

    def handle(self, text: str, kind: str, code: str, what: str
               ) -> Resolved:
        data = self.entry.handles.get(code)
        if data is None:
            raise BridgeError(
                "STALE_REF", "%s: no handle %s in this document" % (what,
                                                                     text),
                ["Handles come from find_geometry on the same document; "
                 "run it again."])
        ref = ShapeRef.from_dict(data)
        found = ref.resolve(self.shape())
        if found is None or not ref.resolved:
            raise BridgeError(
                "STALE_REF", "%s: %s is not on the body any more (it moved "
                "or changed too much to be followed)" % (what, text),
                ["Run find_geometry again, or use a reference by "
                 "definition such as Extrusion1.end or Hole1.wall[0]."])
        moved = math.dist(kernel.shape_centre(found), data["centre"])
        note = "moved %.3f mm since it was found" % moved \
            if moved > 1e-6 and kind != "vertex" else ""
        if ref.fell_back:
            note = ("its roles found nothing, so it was followed by "
                    "position%s" % ("; " + note if note else ""))
        return Resolved(text, kind, [found], ref.via or "fingerprint", note)

    # roles ---------------------------------------------------------------

    # provenance -----------------------------------------------------------

    EDGE_RE = re.compile(r"^(?P<face>.+?)\.edge\((?P<other>.+)\)$")
    SKETCH_OF = {"extrude": "profile", "revolve": "profile",
                 "sweep": "profile", "loft": "sections"}

    def _sketch_id(self, f) -> Optional[int]:
        if f.type_name == "loft":
            return f.sections[0] if f.sections else None
        ids = f.profiles.sketch_ids() or ([f.sketch_id] if f.sketch_id
                                          else [])
        return ids[0] if ids else None

    def role_names(self, f, rest: str, text: str) -> Optional[List[str]]:
        """The stored role strings a face reference means, or None when this
        feature makes no such role. ``wall`` without an index is every one."""
        t = f.type_name
        if t in self.SKETCH_OF and rest in ("start", "end"):
            return ["%d:%s" % (f.id, rest)]
        side = SIDE_RE.match(rest)
        if side and not side.group(2) and t in self.SKETCH_OF:
            sid = self._sketch_id(f)
            if sid is None:
                return None
            by_id = re.match(r"^#e(\d+)$", side.group(1).strip())
            if by_id:
                kind, eid = "entity", int(by_id.group(1))
            else:
                kind, eid = self.job.sketch_part(side.group(1), sid,
                                                 "%s.side" % f.name)
            if kind not in ("entity", "id"):
                raise BridgeError("BAD_REF", "%s: name a line, arc or circle"
                                  " of its sketch" % text)
            return ["%d:side:e%d" % (f.id, eid)]
        m = re.match(r"^(wall|cbore|floor|shoulder|csink)(?:\[(\d+)\])?$",
                     rest)
        if m and t == "hole":
            sk = self._sketch_of(f.sketch_id)
            pids = f.centres(sk)
            if m.group(2) is not None:
                i = int(m.group(2))
                if i >= len(pids):
                    raise BridgeError("NO_MATCH", "%s has %d hole(s)" % (
                        f.name, len(pids)))
                pids = [pids[i]]
            return ["%d:%s:p%d" % (f.id, m.group(1), p) for p in pids]
        m = re.match(r"^face(?:\[(\d+)\])?$", rest)
        if m and t in ("fillet", "chamfer"):
            if m.group(1) is not None:
                return ["%d:face:%s" % (f.id, m.group(1))]
            n = 0
            out = []
            body = self.doc.shape
            if body is not None:
                tags = provenance.lookup(body)
                prefix = "%d:face:" % f.id
                for tg in tags:
                    out += [r for r in tg.all_roles() if r.startswith(prefix)]
            return sorted(set(out)) or None
        return None

    def by_provenance(self, feature, rest: str, text: str
                      ) -> Optional[Resolved]:
        """A role the kernel's history names: its faces, or with ``.edge()``
        the edges between two such faces. None when the part has no
        provenance for it (an older file, a body too big to tag, a face
        cut away), and the caller goes on to the definition."""
        if not provenance.lookup(self.doc.shape):
            return None
        shape = self.shape()
        edge = self.EDGE_RE.match(rest)
        if edge:
            left = self.role_names(feature, edge.group("face"), text)
            if not left:
                return None
            other = edge.group("other")
            right = self.role_names(feature, other, text)
            if right is None:
                # another feature's face, written in full
                try:
                    got = self._resolve(other, "edge(%s)" % other, ("face",))
                except BridgeError:
                    return None
                if got.kind != "face":
                    return None
                faces_b = list(got.shapes)
            else:
                faces_b = [f for r in right
                           for f in provenance.faces_with(shape, r)]
            faces_a = [f for r in left
                       for f in provenance.faces_with(shape, r)]
            if not faces_a or not faces_b:
                return None
            found: List[Any] = []
            for e in kernel.edges(shape):
                sides = provenance.adjacent_faces(shape, e)
                if any(s.IsSame(a) for s in sides for a in faces_a) and any(
                        s.IsSame(b) for s in sides for b in faces_b):
                    if not any(e.IsSame(o) for o in found):
                        found.append(e)
            return Resolved(text, "edge", found, "role") if found else None
        names = self.role_names(feature, rest, text)
        if not names:
            return None
        faces = [f for r in names for f in provenance.faces_with(shape, r)]
        return Resolved(text, "face", faces, "role") if faces else None

    def role(self, feature, rest: str, text: str) -> Resolved:
        t = feature.type_name
        if rest:
            found = self.by_provenance(feature, rest, text)
            if found is not None:
                return found
        if not rest:
            if t == "sketch":
                return Resolved(text, "region",
                                [r["face"] for r in self.job.regions(
                                    feature.id)], "definition")
            raise BridgeError(
                "BAD_REF", "%s is a whole feature; name a face of it" % text,
                ["e.g. %s.end, %s.side(a), or find_geometry with "
                 "created_by" % (feature.name, feature.name)])
        m = INDEXED_RE.match(rest)
        if m and m.group(1) == "region" and t == "sketch":
            regions = self.job.regions(feature.id)
            if m.group(2) is None:
                return Resolved(text, "region", [r["face"] for r in regions],
                                "definition")
            i = int(m.group(2))
            if i >= len(regions):
                raise BridgeError("NO_MATCH", "%s: the sketch has %d "
                                  "region(s)" % (text, len(regions)))
            return Resolved(text, "region", [regions[i]["face"]],
                            "definition")
        if m and m.group(1) in ("wall", "cbore") and t == "hole":
            index = int(m.group(2)) if m.group(2) is not None else None
            return Resolved(text, "face",
                            self.hole_walls(feature, index, m.group(1)),
                            "definition")
        if t == "extrude" and rest in ("start", "end"):
            return Resolved(text, "face", self.job.role(feature.id, rest),
                            "definition")
        side = SIDE_RE.match(rest)
        if side and t == "extrude":
            if side.group(2):
                raise BridgeError(
                    "NO_PROVENANCE", "%s: %s on a side face needs the "
                    "kernel's history (Phase 2)" % (text, side.group(2)),
                    ["find_geometry with {\"on\": \"%s.side(%s)\"} lists "
                     "its edges." % (feature.name, side.group(1))])
            return Resolved(text, "face",
                            [self.extrude_side(feature, side.group(1))],
                            "definition")
        if t == "sketch":
            sub = self.sketch_part(feature, rest)
            if sub is not None:
                return sub
        raise BridgeError(
            "NO_PROVENANCE",
            "%s: %s has no %r known by definition; roles from the kernel's "
            "own history come in Phase 2" % (text, feature.name, rest),
            ["By definition now: extrusions .start .end .side(entity), "
             "holes .wall[i] .cbore[i], sketches .region[i] and named "
             "points. Anything else: find_geometry (created_by, normal, "
             "near...) gives an @F handle."])

    def _sketch_of(self, sketch_id: int):
        self.doc.rebuild()
        sk = self.doc.all_sketches().get(sketch_id)
        if sk is None:
            raise BridgeError("BAD_REF", "the sketch %d is missing"
                              % sketch_id)
        return sk

    def extrude_side(self, f, name: str):
        if self.job.number(getattr(f, "taper", 0) or 0, "taper") or \
                self.job.number(getattr(f, "taper2", 0) or 0, "taper2"):
            raise BridgeError("NO_PROVENANCE", "%s.side(): a tapered "
                              "extrusion's sides need the kernel's history "
                              "(Phase 2)" % f.name,
                              ["Use find_geometry with created_by."])
        sid = (f.profiles.sketch_ids() or [f.sketch_id])[0]
        sk = self._sketch_of(sid)
        kind, eid = self.job.sketch_part(name, sid, "%s.side" % f.name)
        if kind not in ("entity", "id") or eid not in sk.entities:
            raise BridgeError("BAD_REF", "%s.side(%s): name a line, arc or "
                              "circle of its sketch" % (f.name, name))
        poly = sk.entity_polyline(eid)
        if len(poly) < 2:
            raise BridgeError("BAD_REF", "%s.side(%s): that entity sweeps "
                              "no face" % (f.name, name))
        # the point halfway along the entity, halfway up the extrusion
        lengths = [math.dist(a, b) for a, b in zip(poly, poly[1:])]
        half, run = sum(lengths) / 2.0, 0.0
        mid = poly[0]
        for (a, b), ln in zip(zip(poly, poly[1:]), lengths):
            if run + ln >= half and ln > 0:
                k = (half - run) / ln
                mid = (a[0] + (b[0] - a[0]) * k, a[1] + (b[1] - a[1]) * k)
                break
            run += ln
        sign = -1.0 if f.reversed else 1.0
        d = self.job.number(f.distance, "distance")
        if f.extent == "symmetric":
            t = 0.0
        elif f.extent == "distance":
            t = sign * d / 2.0
        elif f.extent == "asymmetric":
            d2 = self.job.number(f.distance2, "distance2")
            t = sign * (d - d2) / 2.0
        else:
            raise BridgeError("NO_PROVENANCE", "%s.side(): known for "
                              "distance, symmetric and asymmetric extents"
                              % f.name, ["Use find_geometry."])
        p = sk.plane.to_3d(*mid)
        n = sk.plane.normal
        point = tuple(p[i] + n[i] * t for i in range(3))
        best, gap = None, math.inf
        for face in kernel.faces(self.shape()):
            g = _point_face_distance(point, face)
            if g < gap:
                best, gap = face, g
        if best is None or gap > self.tolerance() * 10:
            raise BridgeError("NO_MATCH", "%s.side(%s): that side is not on "
                              "the body any more (cut away?)" % (f.name, name))
        return best

    def hole_walls(self, f, index: Optional[int], which: str) -> List[Any]:
        sk = self._sketch_of(f.sketch_id)
        pids = f.centres(sk)
        if index is not None and index >= len(pids):
            raise BridgeError("NO_MATCH", "%s has %d hole(s)" % (f.name,
                                                                len(pids)))
        dia = self.job.number(f.diameter, "diameter")
        if which == "cbore":
            if f.hole_type != "counterbore":
                raise BridgeError("BAD_REF", "%s is not counterbored"
                                  % f.name)
            dia = self.job.number(f.cb_diameter, "cb_diameter")
        n = sk.plane.normal
        tol = self.tolerance() * 10
        out: List[Any] = []
        chosen = pids if index is None else [pids[index]]
        for pid in chosen:
            pt = sk.points[pid]
            base = sk.plane.to_3d(pt.x, pt.y)
            hit = []
            for face in kernel.faces(self.shape()):
                c = reqs.cylinder_facts(face)
                if c is None or not c["hole"] or abs(2 * c["radius"] - dia) \
                        > max(1e-6, 1e-4 * dia):
                    continue
                if abs(abs(sum(a * b for a, b in zip(c["axis"], n))) - 1) \
                        > 1e-6:
                    continue
                rel = [base[i] - c["origin"][i] for i in range(3)]
                along = sum(r * a for r, a in zip(rel, c["axis"]))
                off = math.sqrt(max(0.0, sum(r * r for r in rel) - along ** 2))
                if off < tol:
                    hit.append(face)
            out += hit
        if not out:
            raise BridgeError("NO_MATCH", "%s.%s: no such bore on the body"
                              % (f.name, which))
        return out

    def sketch_part(self, f, rest: str) -> Optional[Resolved]:
        text = "%s.%s" % (f.name, rest)
        try:
            kind, oid = self.job.sketch_part(rest, f.id, text)
        except BridgeError:
            m = re.match(r"^#([pe])(\d+)$", rest)
            if not m:
                if "(" in rest or "[" in rest:
                    return None
                raise
            kind = "point" if m.group(1) == "p" else "entity"
            oid = int(m.group(2))
        sk = self._sketch_of(f.id)
        if kind == "point" and oid in sk.points:
            p = sk.points[oid]
            return Resolved(text, "vertex", [_vertex(sk.plane.to_3d(p.x, p.y))],
                            "definition")
        if kind in ("entity", "id") and oid in sk.entities:
            pts = [sk.plane.to_3d(*q) for q in sk.entity_polyline(oid)]
            if len(pts) < 2:
                return None
            return Resolved(text, "edge", [_polyline_edge(pts)],
                            "definition",
                            "a curve is drawn as a polyline: lengths are "
                            "close, not exact")
        return None


def resolver_for(entry, job=None):
    """A resolver for the document: occurrence references in an assembly,
    the ordinary ones in a part."""
    if getattr(entry, "doc_type", "") == "assembly":
        from .assembly_ops import AssemblyResolver
        return AssemblyResolver(entry, job)
    return Resolver(entry, job)


def _text_resolver(document, text: str):
    """For the core's requirement check: a reference by its text."""
    from .workspace import Entry, entry_of
    entry = entry_of(document) or Entry("", document)
    r = Resolver(entry).resolve(text, "requirement",
                                ("face", "edge", "vertex", "body"))
    return r.shapes[0] if len(r.shapes) == 1 else kernel.compound(r.shapes)


reqs.resolve_text = _text_resolver


# ---------------------------------------------------------------- find

FIND_KEYS = ("type", "normal", "along", "at", "near", "count", "largest",
             "smallest", "area", "length", "radius", "created_by", "on",
             "hole", "limit")
FACE_TYPES = ("plane", "cylinder", "cone", "sphere", "torus", "bspline",
              "other")
EDGE_TYPES = ("line", "circle", "ellipse", "bspline", "other")


def _face_type(face) -> str:
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_SurfaceType as T
    kind = BRepAdaptor_Surface(face).GetType()
    return {T.GeomAbs_Plane: "plane", T.GeomAbs_Cylinder: "cylinder",
            T.GeomAbs_Cone: "cone", T.GeomAbs_Sphere: "sphere",
            T.GeomAbs_Torus: "torus", T.GeomAbs_BSplineSurface: "bspline"
            }.get(kind, "other")


def _edge_type(edge) -> str:
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.GeomAbs import GeomAbs_CurveType as T
    kind = BRepAdaptor_Curve(edge).GetType()
    return {T.GeomAbs_Line: "line", T.GeomAbs_Circle: "circle",
            T.GeomAbs_Ellipse: "ellipse", T.GeomAbs_BSplineCurve: "bspline"
            }.get(kind, "other")


def _rnd(v, n=4):
    if isinstance(v, (list, tuple)):
        return [_rnd(c, n) for c in v]
    r = round(float(v), n)
    return 0.0 if r == 0 else r


def facts(sub, kind: str) -> Dict[str, Any]:
    """What a face, edge or vertex is, briefly."""
    from OCP.BRep import BRep_Tool
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.TopoDS import TopoDS
    if kind == "vertex":
        p = BRep_Tool.Pnt_s(TopoDS.Vertex_s(sub))
        return {"type": "vertex", "point": _rnd([p.X(), p.Y(), p.Z()])}
    if kind == "face":
        face = TopoDS.Face_s(sub)
        out: Dict[str, Any] = {"type": _face_type(face),
                               "area": _rnd(kernel.surface_area(face), 3),
                               "centre": _rnd(kernel.shape_centre(face))}
        if out["type"] == "plane":
            from .build import outward_normal
            n = outward_normal(face)
            if n is not None:
                out["normal"] = _rnd(n, 6)
        elif out["type"] == "cylinder":
            c = reqs.cylinder_facts(face)
            out.update({"radius": _rnd(c["radius"]), "axis": _rnd(c["axis"], 6),
                        "hole": c["hole"]})
        return out
    edge = TopoDS.Edge_s(sub)
    out = {"type": _edge_type(edge),
           "length": _rnd(kernel.edge_length(edge), 3),
           "centre": _rnd(kernel.shape_centre(edge))}
    curve = BRepAdaptor_Curve(edge)
    if out["type"] == "line":
        d = curve.Line().Direction()
        out["direction"] = _rnd([d.X(), d.Y(), d.Z()], 6)
    elif out["type"] == "circle":
        c = curve.Circle()
        loc = c.Location()
        out["radius"] = _rnd(c.Radius())
        out["circle_centre"] = _rnd([loc.X(), loc.Y(), loc.Z()])
    return out


def describe(f: Dict[str, Any]) -> str:
    """One short line: "plane 4800 mm² at [0, 0, 10] facing +z"."""
    t = f["type"]
    if t == "vertex":
        return "vertex at %s" % _short(f["point"])
    if "area" in f:
        bits = ["%s %s mm²" % (t, _num(f["area"]))]
        if "radius" in f:
            bits.append("%s r%s" % ("hole" if f.get("hole") else "boss",
                                    _num(f["radius"])))
        bits.append("at %s" % _short(f["centre"]))
        if "normal" in f:
            bits.append("facing %s" % _dir(f["normal"]))
        elif "axis" in f:
            bits.append("axis %s" % _dir(f["axis"], signed=False))
        return " ".join(bits)
    bits = ["%s %s mm" % (t, _num(f["length"]))]
    if "radius" in f:
        bits.append("r%s" % _num(f["radius"]))
    bits.append("at %s" % _short(f["centre"]))
    if "direction" in f:
        bits.append("along %s" % _dir(f["direction"], signed=False))
    return " ".join(bits)


def _num(v) -> str:
    return ("%.3f" % v).rstrip("0").rstrip(".")


def _short(p) -> str:
    return "[%s]" % ", ".join(_num(c) for c in p)


def _dir(v, signed: bool = True) -> str:
    for i, name in enumerate("xyz"):
        if abs(abs(v[i]) - 1) < 1e-6:
            if not signed:
                return name
            return ("+" if v[i] > 0 else "-") + name
    return _short(v)


def _range(value, what: str) -> Tuple[float, float]:
    if isinstance(value, (int, float)):
        return float(value), float(value)
    if isinstance(value, (list, tuple)) and len(value) == 2:
        lo = -math.inf if value[0] is None else float(value[0])
        hi = math.inf if value[1] is None else float(value[1])
        return lo, hi
    raise BridgeError("BAD_QUERY", "%s: a number or [min, max]" % what,
                      ["e.g. {\"area\": [100, null]}"])


def _direction(value, what: str):
    if isinstance(value, str):
        try:
            axis, sign = edgequery._axis(value)
        except edgequery.QueryError as exc:
            raise BridgeError(exc.kind, str(exc), exc.hints) from exc
        v = [0.0, 0.0, 0.0]
        v[axis] = float(sign)
        return v, value.strip()[:1] in "+-"
    if isinstance(value, (list, tuple)) and len(value) == 3:
        norm = math.sqrt(sum(float(c) ** 2 for c in value)) or 1.0
        return [float(c) / norm for c in value], True
    raise BridgeError("BAD_QUERY", "%s: an axis (\"+z\", \"x\") or [x, y, z]"
                      % what)


def created_by(entry, feature, kind: str) -> List[Dict[str, Any]]:
    """Fingerprints of what ``feature`` added: there after it, not
    before it. Built on a copy, so the document's own rebuild state is not
    disturbed. A face a later feature changed counts as that one's."""
    from ..core.document import Document
    d = entry.document
    index = d.index_of(feature.id)
    copy = Document()
    copy.path = d.path
    copy.load_dict(d.to_dict())
    copy.rules.trusted = d.rules.trusted
    shapes = []
    for limit in (index, index + 1):
        copy.rollback_index = limit
        copy.rebuild()
        shapes.append(copy.shape)

    def pool(shape):
        if shape is None or shape.IsNull():
            return []
        subs = (kernel.faces(shape) if kind == "face" else
                kernel.edges(shape) if kind == "edge" else
                kernel.vertices(shape))
        return [ShapeRef.capture(s, kind, i) for i, s in enumerate(subs)]

    before, after = pool(shapes[0]), pool(shapes[1])
    return [r for r in after if not any(r.same_as(b) for b in before)]


def find(entry, what: str, where: Dict[str, Any], job=None
         ) -> Dict[str, Any]:
    """Faces, edges or vertices of a part by rule, each with a handle."""
    from OCP.TopoDS import TopoDS
    kind = {"face": "face", "faces": "face", "edge": "edge",
            "edges": "edge", "vertex": "vertex", "vertices": "vertex"
            }.get(str(what).lower())
    if kind is None:
        raise BridgeError("BAD_QUERY", "what is face, edge or vertex")
    where = dict(where or {})
    unknown = set(where) - set(FIND_KEYS)
    if unknown:
        raise BridgeError("BAD_QUERY", "unknown condition(s): %s"
                          % ", ".join(sorted(unknown)),
                          ["Known: %s" % ", ".join(FIND_KEYS)])
    res = Resolver(entry, job)
    shape = res.shape()
    tol = res.tolerance()
    box = kernel.bounding_box(shape)

    if "on" in where:
        base = res.resolve(where["on"], "on", ("face", "edge", "region"))
        pool = []
        for s in base.shapes:
            subs = (kernel.edges(s) if kind == "edge" else kernel.vertices(s)
                    if kind == "vertex" else [])
            if kind == "face":
                raise BridgeError("BAD_QUERY", "on: lists the edges or "
                                  "vertices of a face or edge")
            # the body's own sub-shapes, so handles bind to the body
            body = (kernel.edges(shape) if kind == "edge"
                    else kernel.vertices(shape))
            for sub in subs:
                hit = next((b for b in body if b.IsSame(sub)), None)
                if hit is not None and not any(hit.IsSame(p) for p in pool):
                    pool.append(hit)
    elif kind == "face":
        pool = [TopoDS.Face_s(f) for f in kernel.faces(shape)]
    elif kind == "edge":
        seams = edgequery._seams(shape)
        pool = [e for e in kernel.edges(shape)
                if not any(e.IsSame(s) for s in seams)]
    else:
        pool = list(kernel.vertices(shape))

    if "created_by" in where:
        fid = res.job.feature_id(where["created_by"], "created_by")
        made = created_by(entry, entry.document.feature(fid), kind)
        pool = [s for i, s in enumerate(pool)
                if any(ShapeRef.capture(s, kind, 0).same_as(m)
                       for m in made)]

    rows = [(s, facts(s, kind)) for s in pool]

    def keep(f) -> bool:
        if "type" in where:
            types = FACE_TYPES if kind == "face" else EDGE_TYPES
            if kind != "vertex" and where["type"] not in types:
                raise BridgeError("BAD_QUERY", "unknown type %r"
                                  % where["type"],
                                  ["Types: %s" % ", ".join(types)])
            if f["type"] != where["type"]:
                return False
        if "normal" in where:
            v, signed = _direction(where["normal"], "normal")
            n = f.get("normal")
            if n is None:
                return False
            dot = sum(a * b for a, b in zip(n, v))
            if (dot if signed else abs(dot)) < 1 - 1e-6:
                return False
        if "along" in where:
            v, _s = _direction(where["along"], "along")
            d = f.get("direction") or f.get("axis")
            if d is None or abs(sum(a * b for a, b in zip(d, v))) < 1 - 1e-6:
                return False
        if "at" in where:
            axis, sign = edgequery._axis(where["at"])
            c = f.get("centre") or f.get("point")
            if sign > 0 and c[axis] < box[axis + 3] - tol:
                return False
            if sign < 0 and c[axis] > box[axis] + tol:
                return False
        if "area" in where:
            lo, hi = _range(where["area"], "area")
            if "area" not in f or not lo - 1e-9 <= f["area"] <= hi + 1e-9:
                return False
        if "length" in where:
            lo, hi = _range(where["length"], "length")
            if "length" not in f or not lo - 1e-9 <= f["length"] <= hi + 1e-9:
                return False
        if "radius" in where:
            lo, hi = _range(where["radius"], "radius")
            if "radius" not in f or not lo - 1e-6 <= f["radius"] <= hi + 1e-6:
                return False
        if "hole" in where and bool(f.get("hole")) != bool(where["hole"]):
            return False
        return True

    rows = [(s, f) for s, f in rows if keep(f)]
    total = len(rows)

    def size(f):
        return f.get("area", f.get("length", 0.0))

    count = where.get("count")
    if "near" in where:
        p = [float(c) for c in where["near"]]
        rows.sort(key=lambda r: math.dist(
            r[1].get("centre") or r[1].get("point"), p))
        count = int(count or 1)
    elif where.get("largest"):
        rows.sort(key=lambda r: -size(r[1]))
        count = int(count or 1)
    elif where.get("smallest"):
        rows.sort(key=lambda r: size(r[1]))
        count = int(count or 1)
    if count:
        rows = rows[:int(count)]
    limit = int(where.get("limit", 25))
    shown = rows[:limit]
    items = []
    for s, f in shown:
        item = {"ref": handle_for(entry, s, kind, shape)}
        item.update(f)
        item["what"] = describe(f)
        items.append(item)
    out = {"doc": entry.handle, "revision": entry.revision, "kind": kind,
           "matched": total, "found": len(rows), "items": items}
    if len(rows) > limit:
        out["truncated"] = "%d more; narrow the query or raise limit" % (
            len(rows) - limit)
    return out
