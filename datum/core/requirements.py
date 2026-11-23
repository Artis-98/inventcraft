"""Requirements: what a part has to be, kept in the part and checked always.

An inspection with expectations checks once and forgets. A requirement is
written down in the document, beside its rules, and checked on every
rebuild: "the part weighs no more than 1.2 kg", "the bore clears the bolt
by 0.5 mm", "it has six holes", "the width stays between 80 and 200". A
change that breaks one says so the moment it is made, whoever made it, so
the person and the agent working on a part share one definition of done.

A requirement is a name, a metric, and either a target with a tolerance
or a range:

    {"name": "light", "metric": "mass", "max": 1200}          grams
    {"name": "fits", "metric": "bbox", "axis": "x", "max": 150}
    {"name": "box", "metric": "bbox", "target": [120, 80, 10]}  sorted
    {"name": "vol", "metric": "volume", "target": 9e4, "tolerance": 0.02}
    {"name": "gap", "metric": "clearance", "a": {...}, "b": {...},
     "min": 0.5}                                              mm
    {"name": "holes", "metric": "hole_count", "target": 6, "diameter": 6.6}
    {"name": "w", "metric": "parameter", "param": "w", "min": 80,
     "max": 200}

``tolerance`` is relative (default 0.01) and only applies to a target.
The two ends of a clearance are stored references (``core.naming``
fingerprints, captured by whoever wrote the requirement), a body by name
(``{"body": "Solid1"}``) or a point (``{"point": [x, y, z]}``), so the
core checks it with nothing else to hand.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

METRICS = ("bbox", "mass", "volume", "clearance", "hole_count",
           "parameter", "solids", "faces")
KEYS = ("name", "metric", "target", "min", "max", "tolerance", "axis",
        "a", "b", "param", "diameter", "note", "enabled")
DEFAULT_TOLERANCE = 0.01


class RequirementError(ValueError):
    """A requirement that cannot be stored as written."""

    def __init__(self, message: str, hints: Optional[List[str]] = None):
        super().__init__(message)
        self.kind = "BAD_REQUIREMENT"
        self.hints = list(hints or [])


@dataclass
class Requirement:
    name: str = ""
    metric: str = "mass"
    target: Any = None
    min: Optional[float] = None
    max: Optional[float] = None
    tolerance: float = DEFAULT_TOLERANCE
    axis: str = ""
    a: Optional[Dict[str, Any]] = None
    b: Optional[Dict[str, Any]] = None
    param: str = ""
    diameter: Optional[float] = None
    note: str = ""
    enabled: bool = True

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {"name": self.name, "metric": self.metric}
        for key in ("target", "min", "max", "a", "b", "diameter"):
            value = getattr(self, key)
            if value is not None:
                out[key] = value
        for key in ("axis", "param", "note"):
            if getattr(self, key):
                out[key] = getattr(self, key)
        if self.tolerance != DEFAULT_TOLERANCE:
            out["tolerance"] = self.tolerance
        if not self.enabled:
            out["enabled"] = False
        return out

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Requirement":
        if not isinstance(data, dict):
            raise RequirementError("a requirement is an object")
        unknown = set(data) - set(KEYS)
        if unknown:
            raise RequirementError(
                "unknown requirement field(s): %s" % ", ".join(sorted(unknown)),
                ["Fields: %s" % ", ".join(KEYS)])
        metric = str(data.get("metric", ""))
        if metric not in METRICS:
            raise RequirementError("unknown metric %r" % metric,
                                   ["Metrics: %s" % ", ".join(METRICS)])
        name = str(data.get("name") or "")
        if not name:
            raise RequirementError("a requirement needs a name")

        def num(key):
            v = data.get(key)
            return None if v is None else float(v)

        target = data.get("target")
        if isinstance(target, (list, tuple)):
            target = [float(v) for v in target]
        elif target is not None:
            target = float(target)
        req = cls(name=name, metric=metric, target=target, min=num("min"),
                  max=num("max"),
                  tolerance=float(data.get("tolerance", DEFAULT_TOLERANCE)),
                  axis=str(data.get("axis", "") or "").lower(),
                  a=data.get("a"), b=data.get("b"),
                  param=str(data.get("param", "") or ""),
                  diameter=num("diameter"),
                  note=str(data.get("note", "") or ""),
                  enabled=bool(data.get("enabled", True)))
        if req.target is None and req.min is None and req.max is None:
            raise RequirementError("%s: give a target, a min or a max" % name)
        if metric == "bbox" and isinstance(req.target, list) and req.axis:
            raise RequirementError("%s: an axis takes one number" % name)
        if metric == "bbox" and req.axis and req.axis not in "xyz":
            raise RequirementError("%s: axis is x, y or z" % name)
        if metric == "bbox" and not req.axis and not isinstance(
                req.target, list):
            raise RequirementError(
                "%s: a bbox without an axis takes target [x, y, z]" % name,
                ['Or add "axis": "x" for one size.'])
        if metric == "clearance" and (not req.a or not req.b):
            raise RequirementError("%s: a clearance needs a and b" % name)
        if metric == "parameter" and not req.param:
            raise RequirementError("%s: name the parameter (param)" % name)
        return req


@dataclass
class RequirementSet:
    items: List[Requirement] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.items)

    def __iter__(self):
        return iter(self.items)

    def __bool__(self) -> bool:
        return bool(self.items)

    def get(self, name: str) -> Optional[Requirement]:
        return next((r for r in self.items if r.name == name), None)

    def put(self, req: Requirement) -> None:
        """Add it, or replace the one of the same name in its place."""
        for i, held in enumerate(self.items):
            if held.name == req.name:
                self.items[i] = req
                return
        self.items.append(req)

    def remove(self, name: str) -> bool:
        held = self.get(name)
        if held is None:
            return False
        self.items.remove(held)
        return True

    def to_list(self) -> List[Dict[str, Any]]:
        return [r.to_dict() for r in self.items]

    def load(self, data: Any) -> None:
        self.items = []
        for d in data or []:
            try:
                self.items.append(Requirement.from_dict(d))
            except (RequirementError, TypeError, ValueError):
                # a requirement this version cannot read is not a reason
                # to refuse the part
                continue


# ------------------------------------------------------------- measuring


def min_distance(a, b) -> Dict[str, Any]:
    """The least distance between two shapes, and where it is."""
    from OCP.BRepExtrema import BRepExtrema_DistShapeShape
    dss = BRepExtrema_DistShapeShape(a, b)
    if not dss.IsDone() or dss.NbSolution() < 1:
        raise ValueError("could not measure the distance")
    p, q = dss.PointOnShape1(1), dss.PointOnShape2(1)
    return {"distance": float(dss.Value()),
            "from": (p.X(), p.Y(), p.Z()), "to": (q.X(), q.Y(), q.Z()),
            "inside": bool(getattr(dss, "InnerSolution", lambda: False)())}


def cylinder_facts(face) -> Optional[Dict[str, Any]]:
    """Axis, radius and whether a cylindrical face is a hole (material
    outside it) or a boss."""
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.BRepLProp import BRepLProp_SLProps
    from OCP.GeomAbs import GeomAbs_SurfaceType
    from OCP.TopAbs import TopAbs_REVERSED
    from OCP.TopoDS import TopoDS
    face = TopoDS.Face_s(face)
    surf = BRepAdaptor_Surface(face)
    if surf.GetType() != GeomAbs_SurfaceType.GeomAbs_Cylinder:
        return None
    cyl = surf.Cylinder()
    ax = cyl.Axis()
    loc, d = ax.Location(), ax.Direction()
    origin = (loc.X(), loc.Y(), loc.Z())
    direction = (d.X(), d.Y(), d.Z())
    u = 0.5 * (surf.FirstUParameter() + surf.LastUParameter())
    v = 0.5 * (surf.FirstVParameter() + surf.LastVParameter())
    props = BRepLProp_SLProps(surf, u, v, 1, 1e-6)
    hole = False
    if props.IsNormalDefined():
        p, n = props.Value(), props.Normal()
        normal = [n.X(), n.Y(), n.Z()]
        if face.Orientation() == TopAbs_REVERSED:
            normal = [-c for c in normal]
        rel = [p.X() - origin[0], p.Y() - origin[1], p.Z() - origin[2]]
        along = sum(r * c for r, c in zip(rel, direction))
        radial = [r - along * c for r, c in zip(rel, direction)]
        # the face looks towards its axis: the material is outside it
        hole = sum(r * c for r, c in zip(radial, normal)) < 0
    return {"origin": origin, "axis": direction, "radius": cyl.Radius(),
            "hole": hole}


def holes(shape, diameter: Optional[float] = None,
          tolerance: float = 0.01) -> List[Dict[str, Any]]:
    """Every hole in a body: concave cylinders, one per axis and size, so
    a bore OCC splits into two half faces counts once."""
    from . import kernel
    found: List[Dict[str, Any]] = []
    for face in kernel.faces(shape):
        facts = cylinder_facts(face)
        if facts is None or not facts["hole"]:
            continue
        dia = 2.0 * facts["radius"]
        if diameter is not None and abs(dia - diameter) > max(
                tolerance * diameter, 1e-6):
            continue
        d = facts["axis"]
        # where the axis crosses the plane through the origin square to it
        o = facts["origin"]
        t = sum(a * b for a, b in zip(o, d))
        foot = tuple(o[i] - t * d[i] for i in range(3))
        same = next((h for h in found
                     if abs(h["diameter"] - dia) < 1e-6
                     and abs(abs(sum(a * b for a, b in zip(h["axis"], d)))
                             - 1) < 1e-6
                     and math.dist(h["foot"], foot) < 1e-5), None)
        if same is not None:
            same["faces"] += 1
            continue
        found.append({"diameter": dia, "axis": d, "foot": foot, "faces": 1,
                      "centre": kernel.shape_centre(face)})
    return found


# Set by whoever can read references as text (the MCP bridge): takes
# (document, text) and returns a shape or None. A reference by role or by
# definition, "Extrusion1.side(r.right)", then follows any parameter change;
# without one, as in the app, the stored reference is what is checked, which
# follows by role where it has them and by fingerprint where it has not.
resolve_text = None


def _end(document, spec: Dict[str, Any]):
    """One end of a clearance as a shape."""
    from . import kernel
    from .naming import ShapeRef
    if not isinstance(spec, dict):
        raise ValueError("not a reference")
    text = spec.get("text")
    if text and resolve_text is not None and spec.get("via") in (
            "definition", "role"):
        try:
            found = resolve_text(document, text)
        except Exception:                                   # noqa: BLE001
            found = None
        if found is not None:
            return found
    if "point" in spec:
        from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeVertex
        from OCP.gp import gp_Pnt
        return BRepBuilderAPI_MakeVertex(
            gp_Pnt(*[float(v) for v in spec["point"]])).Vertex()
    if "body" in spec:
        for body in document.bodies:
            if getattr(body, "name", "") == spec["body"]:
                return body.shape
        raise ValueError("no body %r" % spec["body"])
    if document.shape is None:
        raise ValueError("there is no body")
    found = []
    for ref in spec.get("refs") or [spec.get("ref", spec)]:
        held = ShapeRef.from_dict(ref)
        sub = held.resolve(document.shape)
        if sub is None or not held.resolved:
            raise ValueError("%s is not on the body any more"
                             % spec.get("text", "the reference"))
        found.append(sub)
    return found[0] if len(found) == 1 else kernel.compound(found)


def value_of(document, req: Requirement) -> Any:
    """What the metric reads on the part as it stands."""
    from . import kernel
    shape = document.shape
    m = req.metric
    if m == "parameter":
        if req.param not in document.params:
            raise ValueError("no parameter %r" % req.param)
        document.params.evaluate_all()
        return float(document.params[req.param].value)
    if shape is None or shape.IsNull():
        raise ValueError("there is no body")
    if m == "bbox":
        x0, y0, z0, x1, y1, z1 = kernel.exact_bounding_box(shape)
        size = [x1 - x0, y1 - y0, z1 - z0]
        if req.axis:
            return size["xyz".index(req.axis)]
        return sorted(size)
    if m == "mass":
        return float(document.mass_properties().get("mass_g", 0.0))
    if m == "volume":
        return float(document.mass_properties().get("volume_mm3", 0.0))
    if m == "solids":
        return float(len(kernel.solids(shape)))
    if m == "faces":
        return float(len(kernel.faces(shape)))
    if m == "hole_count":
        return float(len(holes(shape, req.diameter)))
    if m == "clearance":
        return min_distance(_end(document, req.a),
                            _end(document, req.b))["distance"]
    raise ValueError("unknown metric %r" % m)


def _fmt(v: float) -> str:
    if abs(v - round(v)) < 1e-9:
        return str(int(round(v)))
    return ("%.3f" % v).rstrip("0").rstrip(".")


def _shown(req: Requirement, v: float) -> str:
    """A value in the unit a person reads it in."""
    if req.metric == "mass":
        return "%s kg" % _fmt(v / 1000.0) if v >= 1000 else "%s g" % _fmt(v)
    if req.metric == "volume":
        return "%s mm³" % _fmt(v)
    if req.metric in ("hole_count", "solids", "faces", "parameter"):
        return _fmt(v)
    return "%s mm" % _fmt(v)


def _bound(req: Requirement, v: float) -> str:
    if req.metric == "mass" and abs(v) >= 1000:
        return _fmt(v / 1000.0)
    return _fmt(v)


def check_one(document, req: Requirement) -> Dict[str, Any]:
    out: Dict[str, Any] = {"name": req.name, "metric": req.metric}
    try:
        value = value_of(document, req)
    except Exception as exc:                                # noqa: BLE001
        out.update({"pass": False, "error": str(exc),
                    "text": "%s: cannot measure (%s)" % (req.name, exc)})
        return out
    label = req.name
    if isinstance(value, list):
        want = sorted(req.target)
        ok = all(abs(a - b) <= max(req.tolerance * abs(b), 1e-6)
                 for a, b in zip(value, want))
        out.update({"value": [round(v, 4) for v in value], "pass": ok,
                    "text": "%s %s %s [%s]" % (
                        label, "[%s]" % ", ".join(_fmt(v) for v in value),
                        "=" if ok else "!=",
                        ", ".join(_fmt(v) for v in want))})
        return out
    problems = []
    if req.target is not None:
        if abs(value - req.target) > max(req.tolerance * abs(req.target),
                                         1e-6):
            problems.append("%s %s" % ("<" if value < req.target else ">",
                                       _bound(req, req.target)))
    if req.min is not None and value < req.min - 1e-9:
        problems.append("< %s" % _bound(req, req.min))
    if req.max is not None and value > req.max + 1e-9:
        problems.append("> %s" % _bound(req, req.max))
    ok = not problems
    out.update({"value": round(value, 6), "pass": ok,
                "text": "%s %s%s" % (label, _shown(req, value),
                                     (" " + ", ".join(problems))
                                     if problems else " ok")})
    return out


def check(document) -> List[Dict[str, Any]]:
    """Every enabled requirement of the document, checked now."""
    held = getattr(document, "requirements", None)
    if not held:
        return []
    return [check_one(document, r) for r in held if r.enabled]


def summary(results: Sequence[Dict[str, Any]]) -> str:
    """``reqs 5/6 ✓`` or ``reqs 5/6, mass 1.32 kg > 1.2``."""
    if not results:
        return ""
    passed = sum(1 for r in results if r.get("pass"))
    text = "reqs %d/%d" % (passed, len(results))
    failing = [r for r in results if not r.get("pass")]
    if not failing:
        return text + " ✓"
    return text + ", " + "; ".join(r["text"] for r in failing[:2]) + (
        " (+%d more)" % (len(failing) - 2) if len(failing) > 2 else "")


def shortfall(req: Requirement, value: Any) -> float:
    """How far a measured value is outside what a requirement asks, as a
    fraction of the bound it misses (0 when it passes): the number a
    search follows toward a design that clears. A list (a box) adds the
    sizes' misses up."""
    def miss(v: float, bound: float, below: bool) -> float:
        scale = max(abs(bound), 1e-6)
        return max(0.0, (bound - v) / scale if below else (v - bound) / scale)

    if isinstance(value, (list, tuple)):
        want = sorted(req.target or [])
        return sum(max(0.0, abs(a - b) - max(req.tolerance * abs(b), 1e-6))
                   / max(abs(b), 1e-6) for a, b in zip(value, want))
    total = 0.0
    if req.target is not None:
        slack = max(req.tolerance * abs(req.target), 1e-6)
        total += max(0.0, abs(value - req.target) - slack) / max(
            abs(req.target), 1e-6)
    if req.min is not None:
        total += miss(value, req.min, True)
    if req.max is not None:
        total += miss(value, req.max, False)
    return total
