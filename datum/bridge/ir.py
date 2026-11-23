"""The feature tree as ops: the one format every route writes and reads.

An op is a feature's ``to_dict()`` with three changes, so an agent can
write it and a person can read it: the feature's own id is replaced by an
``id`` the op chooses (``"s1"``), other features are referred to as
``"$s1"`` (or by name), and fields left at their default are left out.
``read_ir`` returns a part in exactly this form and ``build`` takes it
back, so a part read from one document builds the same part in another.

The schema of every op is **generated** here from ``FEATURE_TYPES`` and
each type's ``field_dict()``: a feature type added to the core reaches the
agent with no code in this package. A field's kind is worked out from its
default value and from ``core.modelparams.EXPRESSION_ATTRS``; a few
hand-written conveniences (a sketch's entities and dimensions, an
extrude's ``sketch`` and region picking, a fillet's edge query) sit on top
and are listed in the schema as such.
"""

from __future__ import annotations

import dataclasses
import json
import re
from functools import lru_cache
from typing import Any, Dict, List, Optional

from ..core.features import FEATURE_TYPES, Feature
from ..core.modelparams import EXPRESSION_ATTRS
from ..core.naming import RefSet, ShapeRef
from ..core.sketch import Sketch

BASE_KEYS = ("op", "id", "name", "suppressed", "comments", "solids",
             "param_names")
FEATURE_LISTS = ("parents", "sections")

DESCRIPTIONS = {
    "sketch": "A 2D sketch on a plane or a flat face: entities, "
              "constraints and dimensions, solved by the core solver.",
    "extrude": "A sketch's regions pushed along the sketch normal: join, "
               "cut, intersect or a new solid.",
    "revolve": "A sketch's regions turned about an axis.",
    "primitive": "A box, cylinder, sphere, cone or torus.",
    "fillet": "Rounded edges.",
    "chamfer": "Bevelled edges.",
    "shell": "The solid hollowed to a wall thickness, open where faces "
             "are picked.",
    "mirror": "Features or the whole body mirrored about a plane.",
}

NOTES = {
    "operation": "join | cut | intersect | new",
    "extent": "distance | symmetric | through_all | asymmetric | to_plane "
              "| to_next | from_to",
    "hole_type": "simple | counterbore | countersink",
    "mode": "depends on the type; see the type's own docs",
    "normal": "for a workplane of mode placed: the way it faces",
    "xdir": "for a workplane of mode placed: the way its X runs",
    "plane": "an origin plane (XY, XZ, YZ) or a work plane by name",
    "axis": "an origin axis (X, Y, Z) or a work axis by name; revolve "
            "also takes a sketch line as \"$s1.l1\"",
    "body_name": "the name the new solid gets",
    "query": "an edge query, run again on every rebuild",
    "closed": "true (default) caps the ends and gives a solid; false gives "
              "an open surface, which cannot join, cut or intersect",
    "ruled": "true joins matching sections with straight lines (a tapered "
             "wing); false blends smoothly",
}

# hand-written conveniences, by type; each value is a JSON schema
SUGAR: Dict[str, Dict[str, Any]] = {
    "sketch": {
        "plane": {"description": "XY, XZ or YZ; a work plane by name or "
                  "$id; or a flat face: \"$e1.end\", \"$e1.start\", or "
                  "{\"faces\": face query}; or any plane by numbers or "
                  "expressions, {\"origin\": [x,y,z], \"normal\": [x,y,z], "
                  "\"x\": [x,y,z]}, which makes its work plane"},
        "entities": {"type": "array", "description":
                     "rect, circle, arc, line, polyline, point, polygon, "
                     "spline ([[x,y],..]; closed true = smooth all round, "
                     "\"line\" = shut by a straight line), ellipse "
                     "({center, rx, ry, rotation}); "
                     "each may have an id to name it"},
        "constraints": {"type": "array", "description":
                        "e.g. {\"perpendicular\": [\"l1\", \"l2\"]}"},
        "dimensions": {"type": "array", "description":
                       "e.g. {\"distance\": [\"origin\", \"c1.center\"], "
                       "\"value\": \"w/2\"}"},
        "auto_constrain": {"type": "boolean", "default": True,
                           "description": "horizontal and vertical on "
                           "lines drawn exactly so"},
    },
    "fillet": {"edges": {"description": "\"all\", an edge query, or a "
                         "list of queries"}},
    "chamfer": {"edges": {"description": "\"all\", an edge query, or a "
                          "list of queries"}},
}
SKETCH_ALIAS = {"sketch": {"type": ["string", "integer"],
                           "description": "the sketch: $id or its name "
                           "(sets sketch_id)"}}


def _is_number_text(value: Any) -> bool:
    try:
        float(value)
        return isinstance(value, str)
    except (TypeError, ValueError):
        return False


@lru_cache(maxsize=None)
def kinds(type_name: str) -> Dict[str, str]:
    """Field name -> what it holds, for one feature type."""
    cls = FEATURE_TYPES[type_name]
    inst = cls()
    fields = dict(inst.field_dict())
    base = {f.name for f in dataclasses.fields(Feature)}
    for f in dataclasses.fields(cls):
        if f.name not in fields and f.name not in base \
                and not f.name.startswith("_"):
            fields[f.name] = getattr(inst, f.name)
    exprs = set(EXPRESSION_ATTRS.get(type_name, ()))
    out: Dict[str, str] = {}
    for name, default in fields.items():
        attr = getattr(inst, name, default)
        if name in ("solids",):
            continue
        if name == "profiles":
            out[name] = "profiles"
        elif isinstance(attr, Sketch):
            out[name] = "sketch"
        elif isinstance(attr, RefSet):
            out[name] = "refs"
        elif isinstance(attr, ShapeRef) or (
                attr is None and "ShapeRef" in str(
                    next(f.type for f in dataclasses.fields(cls)
                         if f.name == name))):
            out[name] = "shaperef"
        elif name in FEATURE_LISTS:
            out[name] = "features"
        elif name.endswith("_id") and isinstance(attr, int):
            out[name] = "feature"
        elif isinstance(attr, bool):
            out[name] = "bool"
        elif isinstance(attr, int):
            out[name] = "int"
        elif isinstance(attr, float):
            out[name] = "number"
        elif isinstance(attr, str):
            out[name] = "expr" if (name in exprs or _is_number_text(attr)) \
                else "text"
        elif isinstance(attr, tuple) and all(_is_number_text(v)
                                             for v in attr):
            out[name] = "exprs"
        else:
            out[name] = "json"
    return out


def defaults(type_name: str) -> Dict[str, Any]:
    inst = FEATURE_TYPES[type_name]()
    d = inst.to_dict()
    for k in ("id", "name", "type", "suppressed"):
        d.pop(k, None)
    return d


_JSON = {
    "expr": {"type": ["number", "string"],
             "description": "mm or degrees, or an expression"},
    "text": {"type": "string"},
    "bool": {"type": "boolean"},
    "int": {"type": "integer"},
    "number": {"type": "number"},
    "feature": {"type": ["string", "integer"],
                "description": "a feature: \"$id\" of an earlier op, or a "
                "feature name"},
    "features": {"type": "array", "items": {"type": ["string", "integer"]},
                 "description": "features, each \"$id\" or a name"},
    "profiles": {"description": "regions of a sketch: \"outer\" (default: "
                 "circles inside an outline become holes), \"all\", "
                 "\"largest\", \"smallest\", a list of region indices "
                 "(largest first), \"$s1.region[0]\", or stored "
                 "[sketch, u, v] triples"},
    "refs": {"description": "faces or edges: \"$e1.end\", "
             "{\"faces\": face query}, {\"edges\": edge query}, a list "
             "of these, or stored references as read_ir returns them"},
    "shaperef": {"description": "one face or edge, as for refs"},
    "sketch": {"type": "object",
               "description": "a stored sketch, as read_ir returns it"},
    "exprs": {"type": "array", "items": {"type": ["number", "string"]}},
    "json": {},
}


@lru_cache(maxsize=None)
def schema(type_name: str) -> Dict[str, Any]:
    """The JSON schema of one op."""
    if type_name not in FEATURE_TYPES:
        raise KeyError(type_name)
    cls = FEATURE_TYPES[type_name]
    doc = (cls.__doc__ or "").strip()
    if doc.startswith(cls.__name__ + "("):
        doc = ""
    description = DESCRIPTIONS.get(type_name) or \
        " ".join(doc.split("\n\n")[0].split())
    dflt = defaults(type_name)
    props: Dict[str, Any] = {
        "op": {"const": type_name},
        "id": {"type": "string",
               "description": "a name for later ops: \"$<id>\""},
        "name": {"type": "string", "description": "the feature's name in "
                 "the tree"},
        "suppressed": {"type": "boolean"},
        "comments": {"type": "object", "description": "field -> a comment, "
                     "shown in the Parameters table"},
        "solids": {"type": "array", "items": {"type": "string"},
                   "description": "the solids it works on, by name; empty: "
                   "the one its material meets"},
        "param_names": {"type": "object", "description": "field -> the "
                        "model parameter name (d7...), kept by read_ir"},
    }
    for name, kind in kinds(type_name).items():
        p = dict(_JSON[kind])
        if name in NOTES:
            p["description"] = (p.get("description", "") + "; "
                                + NOTES[name]).lstrip("; ")
        if name in dflt and kind not in ("sketch",):
            p["default"] = dflt[name]
        props[name] = p
    sugar = dict(SUGAR.get(type_name, {}))
    if "sketch_id" in props and type_name != "sketch":
        sugar.update(SKETCH_ALIAS)
    for name, p in sugar.items():
        q = dict(p)
        q["description"] = "(convenience) " + q.get("description", "")
        props[name] = q
    return {"$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "ic://schema/op/%s" % type_name,
            "title": type_name, "description": description,
            "type": "object", "properties": props, "required": ["op"],
            "additionalProperties": False}


def allowed_keys(type_name: str) -> List[str]:
    return list(schema(type_name)["properties"])


def index() -> List[Dict[str, Any]]:
    """Every op type, one line each."""
    out = []
    for name in FEATURE_TYPES:
        s = schema(name)
        out.append({"op": name, "uri": s["$id"],
                    "description": s["description"],
                    "fields": [k for k in s["properties"]
                               if k not in BASE_KEYS]})
    for name, text in TREE_OPS.items():
        out.append({"op": name, "description": text})
    return out


TREE_OPS = {
    "properties": "{op, appearance?, material?, props?}: the part's colour "
                  "(\"#rrggbb\", an appearance by name, or \"material\"), "
                  "material and iProperties",
    "parameter": "{op, name, value, comment?, unit?}: create or change a "
                 "user parameter",
    "edit": "{op, feature, set: {field: value}}: change a feature's fields "
            "(any field its op takes, and name, suppressed)",
    "remove": "{op, feature, dependents?: \"refuse\"|\"remove\"}: delete a "
              "feature; refused if others use it, unless dependents is "
              "\"remove\"",
    "move": "{op, feature, before?|after?: feature, to?: index|\"end\"}: "
            "reorder the tree",
}


# ---------------------------------------------------------------- reading


def token_for(name: str, taken: set) -> str:
    base = re.sub(r"\W+", "_", name).strip("_") or "f"
    if base[0].isdigit():
        base = "f_" + base
    tok, n = base, 2
    while tok in taken:
        tok = "%s_%d" % (base, n)
        n += 1
    taken.add(tok)
    return tok


def to_ir(document, feature_ids: Optional[List[int]] = None,
          parameters: bool = True) -> List[Dict[str, Any]]:
    """A part's tree as build ops, defaults left out."""
    taken: set = set()
    tokens = {f.id: token_for(f.name, taken) for f in document.features}
    ops: List[Dict[str, Any]] = []
    if parameters:
        for name in document.params.names():
            p = document.params[name]
            item: Dict[str, Any] = {"op": "parameter", "name": name,
                                    "value": p.expression}
            if p.comment:
                item["comment"] = p.comment
            if getattr(p, "unit", "mm") not in ("mm", ""):
                item["unit"] = p.unit
            ops.append(item)
        if getattr(document, "appearance", ""):
            ops.append({"op": "properties",
                        "appearance": document.appearance})

    def ref(fid):
        return "$" + tokens[fid] if fid in tokens else fid

    for f in document.features:
        if feature_ids is not None and f.id not in feature_ids:
            continue
        d = f.to_dict()
        item = {"op": f.type_name, "id": tokens[f.id], "name": f.name}
        if f.suppressed:
            item["suppressed"] = True
        if f.param_comments:
            item["comments"] = dict(f.param_comments)
        if f.param_names:
            item["param_names"] = dict(f.param_names)
        if f.solids:
            item["solids"] = list(f.solids)
        dflt = defaults(f.type_name)
        for name, kind in kinds(f.type_name).items():
            if name not in d:
                continue
            value = d[name]
            if kind != "sketch" and name in dflt and dflt[name] == value:
                continue
            if kind == "feature":
                value = ref(value) if value else value
            elif kind == "features":
                value = [ref(v) for v in value]
            elif kind == "profiles":
                value = [[ref(int(s)), u, v] for s, u, v in value]
            elif kind == "sketch":
                value = json.loads(json.dumps(value))
                for p in value.get("projections", []):
                    src = p.get("source") or {}
                    if isinstance(src.get("sketch"), int):
                        src["sketch"] = ref(src["sketch"])
            elif name == "refs" and f.type_name == "workplane":
                value = [dict(r, sketch=ref(r["sketch"])) if "sketch" in r
                         else r for r in value]
            item[name] = value
        ops.append(item)
    return ops
