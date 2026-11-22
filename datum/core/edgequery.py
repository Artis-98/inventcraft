"""Edges picked by a rule, so the pick follows the rule through a rebuild.

A pick stored as a reference (``core.naming``) remembers where an edge
was. That is right for a click, and it is what goes wrong when a
parameter moves the edge further than the reference can follow: make a
plate 40 mm wider and the fillet on its corners no longer finds them.

A query remembers what the edges *are*: "the edges along Z", "the edges
round the top", "the circles". It is run again on every rebuild against
the body as it is then, so the fillet stays on the corners however wide
the plate becomes. This is how an agent picks edges, since it cannot
click, and a feature that has a query uses it in preference to its stored
references.

A query is a dict of conditions that must all hold; a list of queries
takes the edges any of them finds; ``"all"`` takes every edge.

    {"along": "z"}                  straight edges parallel to an axis
    {"at": "+z"}                    edges lying on the top of the body's box
    {"kind": "circle"}              line or circle
    {"near": [x, y, z], "count": 2} the nearest few
    {"min_length": 5, "max_length": 50}

Seam edges, the line a cylinder's surface is cut along to unroll it, are
never found: they are a fact of how the surface is stored, not an edge
anyone can see or round over.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence

from OCP.BRep import BRep_Tool
from OCP.BRepAdaptor import BRepAdaptor_Curve
from OCP.GeomAbs import GeomAbs_CurveType
from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE
from OCP.TopExp import TopExp
from OCP.TopTools import TopTools_IndexedDataMapOfShapeListOfShape
from OCP.TopoDS import TopoDS

from . import kernel

AXES = {"x": 0, "y": 1, "z": 2}
KINDS = {"line": GeomAbs_CurveType.GeomAbs_Line,
         "circle": GeomAbs_CurveType.GeomAbs_Circle}
KNOWN = ("along", "at", "kind", "near", "count", "min_length", "max_length")


class QueryError(ValueError):
    """A query that cannot be run, or that found nothing."""

    def __init__(self, kind: str, message: str,
                 hints: Optional[List[str]] = None) -> None:
        super().__init__(message)
        self.kind = kind
        self.hints = list(hints or [])


def _axis(text: str):
    """``"+z"`` or ``"z"`` as (axis index, sign)."""
    t = str(text).strip().lower()
    sign = -1 if t.startswith("-") else 1
    t = t.lstrip("+-")
    if t not in AXES:
        raise QueryError("BAD_QUERY", "unknown axis %r" % text,
                         ["Axes are x, y, z, optionally signed: +z, -x."])
    return AXES[t], sign


def _seams(shape) -> List[Any]:
    """Edges that are only a seam of the one face they belong to."""
    found = []
    ancestry = TopTools_IndexedDataMapOfShapeListOfShape()
    TopExp.MapShapesAndAncestors_s(shape, TopAbs_EDGE, TopAbs_FACE, ancestry)
    for i in range(1, ancestry.Extent() + 1):
        edge = TopoDS.Edge_s(ancestry.FindKey(i))
        faces = list(ancestry.FindFromIndex(i))
        for face in faces:
            try:
                if BRep_Tool.IsClosed_s(edge, TopoDS.Face_s(face)):
                    found.append(edge)
                    break
            except Exception:
                pass
    return found


def _facts(edge) -> Dict[str, Any]:
    curve = BRepAdaptor_Curve(TopoDS.Edge_s(edge))
    kind = curve.GetType()
    facts = {"kind": kind, "box": kernel.bounding_box(edge),
             "centre": kernel.shape_centre(edge),
             "length": kernel.edge_length(edge), "dir": None}
    if kind == GeomAbs_CurveType.GeomAbs_Line:
        d = curve.Line().Direction()
        facts["dir"] = (d.X(), d.Y(), d.Z())
    return facts


def _matches(facts, query: Dict[str, Any], body_box, tol: float) -> bool:
    if "kind" in query:
        want = KINDS.get(str(query["kind"]).lower())
        if want is None:
            raise QueryError("BAD_QUERY", "unknown kind %r" % query["kind"],
                             ["kind is line or circle."])
        if facts["kind"] != want:
            return False
    if "along" in query:
        axis, _sign = _axis(query["along"])
        d = facts["dir"]
        if d is None or abs(abs(d[axis]) - 1.0) > 1e-6:
            return False
    if "at" in query:
        axis, sign = _axis(query["at"])
        lo, hi = facts["box"][axis], facts["box"][axis + 3]
        if sign > 0 and lo < body_box[axis + 3] - tol:
            return False
        if sign < 0 and hi > body_box[axis] + tol:
            return False
    if "min_length" in query and facts["length"] < float(query["min_length"]):
        return False
    if "max_length" in query and facts["length"] > float(query["max_length"]):
        return False
    return True


def check(where: Any) -> None:
    """Raise if ``where`` is not a query this module understands."""
    if where in ("all", None, True):
        return
    for query in (where if isinstance(where, list) else [where]):
        if not isinstance(query, dict):
            raise QueryError("BAD_QUERY", "an edge query is a dict",
                             ['e.g. {"along": "z"} or {"at": "+z"}'])
        unknown = set(query) - set(KNOWN)
        if unknown:
            raise QueryError(
                "BAD_QUERY", "unknown edge condition(s): %s"
                % ", ".join(sorted(unknown)),
                ["Known: %s" % ", ".join(KNOWN)])


def edges(shape, where: Any) -> List[Any]:
    """The edges of ``shape`` that ``where`` asks for, in a stable order."""
    if shape is None:
        raise QueryError("NO_BODY", "there is no solid to pick edges on",
                         ["Extrude a sketch before a fillet or chamfer."])
    check(where)
    seams = _seams(shape)
    pool = [e for e in kernel.edges(shape)
            if not any(e.IsSame(s) for s in seams)]
    if where in ("all", None, True):
        return pool
    queries = where if isinstance(where, list) else [where]
    box = kernel.bounding_box(shape)
    tol = 1e-4 * max(1.0, max(box[3] - box[0], box[4] - box[1],
                              box[5] - box[2]))
    found: List[Any] = []
    for query in queries:
        hits = [(e, _facts(e)) for e in pool]
        hits = [(e, f) for e, f in hits if _matches(f, query, box, tol)]
        if "near" in query:
            p = [float(v) for v in query["near"]]
            hits.sort(key=lambda h: math.dist(h[1]["centre"], p))
            hits = hits[:int(query.get("count", 1))]
        for e, _f in hits:
            if not any(e.IsSame(x) for x in found):
                found.append(e)
    if not found:
        raise QueryError("NO_MATCH", "no edge matches %s" % (where,),
                         ["Render the part, or loosen the query."])
    return found


def describe(edge_list: Sequence[Any]) -> List[Dict[str, Any]]:
    out = []
    for e in edge_list:
        f = _facts(e)
        kind = next((k for k, v in KINDS.items() if v == f["kind"]), "curve")
        out.append({"kind": kind, "length": round(f["length"], 4),
                    "centre": [round(c, 4) for c in f["centre"]]})
    return out
