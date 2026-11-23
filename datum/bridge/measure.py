"""``measure``: sizes of one reference, and how two relate.

One reference: a face's area (and normal, or radius and axis), an edge's
length (and radius), a vertex's position, a sketch region's area, a body's
volume, area and box. Two: the least distance between them and where it
is, and whichever of these apply: the angle between two flat faces or two
lines, the gap between two parallel planes, the distance between two
parallel axes (hole spacing), and between their centres.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List

from ..core import kernel
from ..core import requirements as reqs
from .errors import BridgeError
from .refs import _num, _rnd, facts, resolver_for

ALLOW = ("face", "edge", "vertex", "region", "body", "point")


def _one(r) -> Dict[str, Any]:
    out: Dict[str, Any] = r.describe()
    shapes = r.shapes
    if r.kind in ("body",):
        props = kernel.geometry_properties(shapes[0])
        out.update({"volume": _rnd(props["volume_mm3"], 3),
                    "area": _rnd(props["area_mm2"], 3),
                    "bbox": _rnd(props["bbox"]),
                    "bbox_min": _rnd(props["bbox_min"]),
                    "centre_of_volume": _rnd(props["centre"])})
        return out
    if r.kind == "point":
        out["point"] = _rnd(kernel.shape_centre(shapes[0]))
        return out
    kind = {"region": "face"}.get(r.kind, r.kind)
    rows = [facts(s, kind) for s in shapes]
    if len(rows) == 1:
        out.update(rows[0])
    else:
        out["parts"] = rows
        if kind == "face":
            out["area"] = _rnd(sum(f["area"] for f in rows), 3)
        elif kind == "edge":
            out["length"] = _rnd(sum(f["length"] for f in rows), 3)
        radii = {f.get("radius") for f in rows}
        if len(radii) == 1 and None not in radii:
            out["radius"] = radii.pop()
    if "radius" in out:
        out["diameter"] = _rnd(2 * out["radius"])
    return out


def _unit(v):
    n = math.sqrt(sum(c * c for c in v)) or 1.0
    return [c / n for c in v]


def _angle(u, v, lines: bool) -> float:
    d = max(-1.0, min(1.0, sum(a * b for a, b in zip(_unit(u), _unit(v)))))
    ang = math.degrees(math.acos(d))
    return min(ang, 180 - ang) if lines else ang


def _pair(ra, rb, fa, fb) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    a = ra.shapes[0] if len(ra.shapes) == 1 else kernel.compound(ra.shapes)
    b = rb.shapes[0] if len(rb.shapes) == 1 else kernel.compound(rb.shapes)
    try:
        d = reqs.min_distance(a, b)
        out["min_distance"] = _rnd(d["distance"])
        out["closest"] = [_rnd(d["from"]), _rnd(d["to"])]
    except ValueError as exc:
        out["min_distance_error"] = str(exc)
    na, nb = fa.get("normal"), fb.get("normal")
    la = fa.get("direction") or fa.get("axis")
    lb = fb.get("direction") or fb.get("axis")
    if na and nb:
        out["angle"] = _rnd(_angle(na, nb, False), 6)
        if out["angle"] < 1e-6 or abs(out["angle"] - 180) < 1e-6:
            gap = abs(sum((p - q) * n for p, q, n in
                          zip(fb["centre"], fa["centre"], na)))
            out["plane_gap"] = _rnd(gap)
    elif la and lb:
        out["angle"] = _rnd(_angle(la, lb, True), 6)
        if out["angle"] < 1e-6:
            ca = fa.get("circle_centre") or fa.get("centre")
            cb = fb.get("circle_centre") or fb.get("centre")
            u = _unit(la)
            rel = [q - p for p, q in zip(ca, cb)]
            along = sum(r * c for r, c in zip(rel, u))
            out["axis_distance"] = _rnd(math.sqrt(max(
                0.0, sum(r * r for r in rel) - along * along)))
    elif (na and lb) or (nb and la):
        n, l = (na, lb) if na else (nb, la)
        out["angle"] = _rnd(90 - _angle(n, l, True), 6)
    ca = fa.get("circle_centre") or fa.get("centre") or fa.get("point")
    cb = fb.get("circle_centre") or fb.get("centre") or fb.get("point")
    if ca and cb:
        out["centre_distance"] = _rnd(math.dist(ca, cb))
    return out


def measure(entry, a: Any, b: Any = None) -> Dict[str, Any]:
    res = resolver_for(entry)
    ra = res.resolve(a, "a", ALLOW)
    fa = _one(ra)
    out: Dict[str, Any] = {"doc": entry.handle, "revision": entry.revision,
                           "a": fa}
    if b is None:
        out["summary"] = _line(fa)
        return out
    rb = res.resolve(b, "b", ALLOW)
    fb = _one(rb)
    out["b"] = fb
    pair = _pair(ra, rb, fa, fb)
    out.update(pair)
    bits = ["%s to %s" % (ra.text, rb.text)]
    if "min_distance" in pair:
        bits.append("min %s mm" % _num(pair["min_distance"]))
    for key, unit in (("plane_gap", "mm"), ("axis_distance", "mm"),
                      ("angle", "deg")):
        if key in pair:
            bits.append("%s %s %s" % (key.replace("_", " "),
                                      _num(pair[key]), unit))
    out["summary"] = " | ".join(bits)
    return out


def _line(f: Dict[str, Any]) -> str:
    bits = [f["ref"], f.get("type", f["kind"])]
    for key, unit in (("volume", "mm³"), ("area", "mm²"),
                      ("length", "mm"), ("diameter", "mm")):
        if key in f:
            bits.append("%s %s %s" % (key, _num(f[key]), unit))
    if "bbox" in f:
        bits.append("bbox %s" % " x ".join(_num(v) for v in f["bbox"]))
    if "point" in f:
        bits.append("at [%s]" % ", ".join(_num(v) for v in f["point"]))
    bits.append("via %s" % f["via"])
    return " | ".join(bits)


def capture_end(entry, ref: Any) -> Dict[str, Any]:
    """One end of a clearance requirement, stored so the core can check
    it alone: a body by name, a point, or a fingerprint of the face, edge
    or vertex the reference resolves to now."""
    from ..core.naming import ShapeRef
    if isinstance(ref, dict):
        return ref
    res = resolver_for(entry)
    r = res.resolve(ref, "clearance", ("face", "edge", "vertex", "body",
                                       "point"))
    if r.kind == "point":
        return {"point": list(ref), "text": r.text}
    if r.kind == "body":
        if ref == "part":
            raise BridgeError("BAD_REF", "a clearance is between two "
                              "things; name bodies (body:Name) or faces")
        name = ref[5:] if ref.startswith("body:") else ref
        return {"body": name, "text": r.text}
    shape = res.shape()
    kind = r.kind
    pool = (kernel.faces(shape) if kind == "face" else kernel.edges(shape)
            if kind == "edge" else kernel.vertices(shape))
    stored = []
    for sub in r.shapes:
        index = next((i for i, c in enumerate(pool) if c.IsSame(sub)), 0)
        held = ShapeRef.capture(
            sub, kind, index, within=shape if kind == "vertex" else None)
        held.attach_roles(shape, sub)
        stored.append(held.to_dict())
    # a bore OCC keeps as two half faces is one end, of two references
    out = {"ref": stored[0]} if len(stored) == 1 else {"refs": stored}
    out.update({"text": r.text, "via": r.via})
    return out


__all__: List[str] = ["measure", "capture_end"]
