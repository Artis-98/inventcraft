"""Sketches as an agent writes them: named entities, constraints and
dimensions, all values numbers or expressions.

An entity can carry an ``id``; it and its parts are then named inside the
sketch (``l1``, ``l1.start``, ``c1.center``, ``r1.top``, ``p.s2``,
``p.p0``), and the constraints and dimensions refer to them by those
names. ``origin`` is the sketch's grounded origin point. The names live
as long as the host does (they are kept on the workspace entry), so a
later build can say ``$Sketch1.c1.center``; ``sketch_status`` shows them.

What a sketch says about itself afterwards, its degrees of freedom, what
is still loose and what conflicts, comes from the core solver
(``Sketch.solve``), which works it out from the null space of the
constraint Jacobian.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

from ..core.sketch import CONSTRAINT_KINDS, DIMENSION_KINDS, Sketch
from .errors import BridgeError

# kind -> what its refs must be, in order: p a point, e an entity, l a line
SIGNATURES: Dict[str, Tuple[str, ...]] = {
    "coincident": ("p", "p"),
    "concentric": ("e", "e"),
    "parallel": ("l", "l"),
    "perpendicular": ("l", "l"),
    "collinear": ("l", "l"),
    "equal": ("e", "e"),
    "tangent": ("e", "e"),
    "point_on": ("p", "e"),
    "midpoint": ("p", "l"),
    "symmetric": ("p", "p", "l"),
    "radius": ("e",),
    "diameter": ("e",),
    "radial_gap": ("e", "e"),
    "distance_x": ("p", "p"),
    "distance_y": ("p", "p"),
}
# kinds whose refs may take more than one shape
FLEXIBLE = ("horizontal", "vertical", "distance", "distance_pl", "angle",
            "fix", "ground", "length")
DIMENSIONS = tuple(DIMENSION_KINDS) + ("length",)
KINDS = tuple(CONSTRAINT_KINDS) + ("length",)

ENTITY_SHAPES = ("rect", "circle", "arc", "line", "polyline", "point",
                 "polygon", "spline", "ellipse")


class SketchBuilder:
    """Draws one sketch from an op, for one build."""

    def __init__(self, job, sketch: Sketch, names: Dict[str, Tuple[str, int]]
                 ) -> None:
        self.job = job
        self.sketch = sketch
        self.names = names
        self.origin = sketch.ensure_origin_point()
        self.names.setdefault("origin", ("point", self.origin))
        self.dimensioned = {self.origin}
        self.loose = 0
        # dimensions the agent wrote out, checked for repeating others
        self.new_dims: List[int] = []

    # values -----------------------------------------------------------

    def num(self, value: Any, what: str) -> float:
        return self.job.number(value, what)

    def text(self, value: Any, angle: bool = False) -> str:
        return self.job.stored(value, "angle" if angle else "length")

    def dim(self, kind: str, points=None, entities=None, value: Any = 0,
            comment: str = "") -> int:
        cid = self.sketch.add_constraint(
            kind, points=points, entities=entities,
            value=self.num(value, kind),
            expression=self.text(value, kind == "angle"))
        if comment:
            self.sketch.constraints[cid].comment = str(comment)
        return cid

    def place(self, pid: int, x: Any, y: Any) -> None:
        """Hold a point where its coordinates say, as dimensions from the
        origin, so a parameter in them moves it."""
        if pid in self.dimensioned or self.sketch.points[pid].fixed:
            return
        self.dimensioned.add(pid)
        self.dim("distance_x", [self.origin, pid], value=x)
        self.dim("distance_y", [self.origin, pid], value=y)

    def name(self, key: Optional[str], kind: str, oid: int) -> None:
        if not key:
            return
        key = str(key)
        if key in self.names and key != "origin":
            raise BridgeError("BAD_OP", "sketch name %r is used twice" % key)
        self.names[key] = (kind, oid)

    # entities ------------------------------------------------------------

    def entity(self, ent: Dict[str, Any], n: int) -> None:
        if not isinstance(ent, dict):
            raise BridgeError("BAD_OP", "entity %d is not an object" % n)
        shapes = [k for k in ENTITY_SHAPES if k in ent]
        if len(shapes) != 1:
            raise BridgeError(
                "BAD_OP", "entity %d: give exactly one shape, not %s"
                % (n, sorted(ent)),
                ["Entities: %s." % ", ".join(ENTITY_SHAPES)])
        getattr(self, "_" + shapes[0])(ent, ent[shapes[0]],
                                       bool(ent.get("construction")),
                                       ent.get("id"))

    def _rect(self, ent, r, construction, key) -> None:
        if not isinstance(r, dict) or "size" not in r:
            raise BridgeError("BAD_OP", "a rect needs size and center or "
                              "corner")
        w, h = r["size"]
        t = self.job.text
        if "center" in r:
            cx, cy = r["center"]
            x0 = "(%s) - (%s) / 2" % (t(cx), t(w))
            y0 = "(%s) - (%s) / 2" % (t(cy), t(h))
        else:
            x0, y0 = r.get("corner", [0, 0])
        ax, ay = self.num(x0, "rect x"), self.num(y0, "rect y")
        ww, hh = self.num(w, "rect width"), self.num(h, "rect height")
        if ww <= 0 or hh <= 0:
            raise BridgeError("BAD_VALUE", "a rect needs a positive size")
        ids = self.sketch.add_rectangle((ax, ay), (ax + ww, ay + hh),
                                        construction)
        a, b = self.sketch.entities[ids[0]].points
        _b, c = self.sketch.entities[ids[1]].points
        _c, d = self.sketch.entities[ids[2]].points
        self.place(a, x0, y0)
        self.dimensioned.update((b, c, d))
        self.dim("distance_x", [a, b], value=w)
        self.dim("distance_y", [b, c], value=h)
        if key:
            for side, eid in zip(("bottom", "right", "top", "left"), ids):
                self.name("%s.%s" % (key, side), "entity", eid)
            for corner, pid in zip(("bl", "br", "tr", "tl"), (a, b, c, d)):
                self.name("%s.%s" % (key, corner), "point", pid)

    def _circle(self, ent, c, construction, key) -> None:
        cx, cy = c.get("center", [0, 0])
        if "d" in c:
            dia = c["d"]
        elif "r" in c:
            dia = "2 * (%s)" % self.job.text(c["r"])
        else:
            raise BridgeError("BAD_OP", "a circle needs d or r")
        size = self.num(dia, "circle diameter")
        if size <= 0:
            raise BridgeError("BAD_VALUE", "a circle needs a positive size")
        eid = self.sketch.add_circle((self.num(cx, "circle x"),
                                      self.num(cy, "circle y")),
                                     size / 2.0, construction)
        centre = self.sketch.entities[eid].points[0]
        self.place(centre, cx, cy)
        self.dim("diameter", entities=[eid], value=dia)
        self.name(key, "entity", eid)
        if key:
            self.name("%s.center" % key, "point", centre)

    def _arc(self, ent, a, construction, key) -> None:
        cx, cy = a.get("center", [0, 0])
        if "r" not in a:
            raise BridgeError("BAD_OP", "an arc needs center, r, start and "
                              "end (degrees, anticlockwise)")
        r = a["r"]
        start = math.radians(self.num(a.get("start", 0), "arc start"))
        end = math.radians(self.num(a.get("end", 90), "arc end"))
        eid = self.sketch.add_arc((self.num(cx, "arc x"),
                                   self.num(cy, "arc y")),
                                  self.num(r, "arc radius"), start, end,
                                  construction)
        c, p1, p2 = self.sketch.entities[eid].points
        self.place(c, cx, cy)
        self.dim("radius", entities=[eid], value=r)
        self.name(key, "entity", eid)
        if key:
            self.name("%s.center" % key, "point", c)
            self.name("%s.start" % key, "point", p1)
            self.name("%s.end" % key, "point", p2)
        # where it starts and stops is left to constraints: a sweep pinned
        # by numbers alone would fight the tangent or coincident that is
        # usually what an arc is drawn for
        self.loose += 1

    def _point(self, ent, p, construction, key) -> None:
        x, y = p
        pid = self.sketch.add_point(self.num(x, "point x"),
                                    self.num(y, "point y"))
        self.place(pid, x, y)
        self.name(key, "point", pid)

    def _polygon(self, ent, g, construction, key) -> None:
        sides = int(g.get("sides", 6))
        if sides < 3:
            raise BridgeError("BAD_VALUE", "a polygon needs 3 sides or more")
        cx, cy = g.get("center", [0, 0])
        t = self.job.text
        if "across_flats" in g:
            corners = "(%s) / cos(180 / %d)" % (t(g["across_flats"]), sides)
        elif "d" in g:
            corners = g["d"]
        elif "r" in g:
            corners = "2 * (%s)" % t(g["r"])
        else:
            raise BridgeError("BAD_OP", "a polygon needs across_flats, d "
                              "(across corners) or r")
        radius = self.num(corners, "polygon size") / 2.0
        # a flat at the bottom and top, as a nut is drawn
        rotation = math.pi / 2 - math.pi / sides if sides % 2 == 0 \
            else -math.pi / 2
        rotation = math.radians(self.num(g.get("rotation", 0), "rotation")) \
            + rotation
        ids = self.sketch.add_polygon((self.num(cx, "x"), self.num(cy, "y")),
                                      radius, sides, rotation, construction)
        ring = max(self.sketch.entities)
        centre = self.sketch.entities[ring].points[0]
        self.place(centre, cx, cy)
        self.dim("diameter", entities=[ring], value=corners)
        level = None
        for eid in ids:
            a, b = (self.sketch.points[p] for p in
                    self.sketch.entities[eid].points)
            if abs(a.y - b.y) < 1e-9:
                level = ("horizontal", eid)
                break
            if abs(a.x - b.x) < 1e-9:
                level = ("vertical", eid)
        if level and not g.get("rotation"):
            self.sketch.add_constraint(level[0], entities=[level[1]])
        else:
            self.dim("angle", entities=[ids[0]],
                     value=math.degrees(math.atan2(
                         *reversed(self._direction(ids[0])))) % 360.0)
        self.name(key, "entity", ring)
        if key:
            self.name("%s.center" % key, "point", centre)
            for i, eid in enumerate(ids):
                self.name("%s.s%d" % (key, i), "entity", eid)
                self.name("%s.p%d" % (key, i), "point",
                          self.sketch.entities[eid].points[0])

    def _direction(self, eid):
        a, b = (self.sketch.points[p] for p in self.sketch.entities[eid].points)
        return (b.x - a.x, b.y - a.y)

    def _line(self, ent, pts, construction, key) -> None:
        self._chain(ent, list(pts), False, construction, key, "line")

    def _polyline(self, ent, pts, construction, key) -> None:
        self._chain(ent, list(pts), bool(ent.get("closed", True)),
                    construction, key, "polyline")

    def _chain(self, ent, raw, closed, construction, key, shape) -> None:
        if len(raw) < 2:
            raise BridgeError("BAD_OP", "a %s needs two points or more"
                              % shape)
        pts = [tuple(self.num(v, shape) for v in p) for p in raw]
        if closed and pts[0] != pts[-1]:
            pts.append(pts[0])
            raw = raw + [raw[0]]
        ids = [self.sketch.add_line(p, q, construction)
               for p, q in zip(pts, pts[1:])]
        dimension = ent.get("dimension")
        if dimension is None:
            # expressions in the coordinates mean the agent wants them to
            # drive the shape; plain numbers are left to constraints
            dimension = any(isinstance(v, str) for p in raw for v in p)
        points = [self.sketch.entities[ids[0]].points[0]] + [
            self.sketch.entities[e].points[1] for e in ids]
        if dimension:
            for pid, (x, y) in zip(points, raw):
                self.place(pid, x, y)
        elif ent.get("auto_constrain", self.job_auto):
            self.sketch.auto_constrain_new(ids, angle_tol_deg=1e-6)
            self.loose += 1
        else:
            self.loose += 1
        if key:
            if shape == "line":
                self.name(key, "entity", ids[0])
                self.name("%s.start" % key, "point", points[0])
                self.name("%s.end" % key, "point", points[1])
            else:
                for i, eid in enumerate(ids):
                    self.name("%s.s%d" % (key, i), "entity", eid)
                for i, pid in enumerate(points[:len(ids) + (0 if closed
                                                             else 1)]):
                    self.name("%s.p%d" % (key, i), "point", pid)

    def _spline(self, ent, raw, construction, key) -> None:
        if not isinstance(raw, (list, tuple)) or not all(
                isinstance(p, (list, tuple)) and len(p) == 2 for p in raw):
            raise BridgeError(
                "BAD_OP", "a spline is a list of [x, y] points",
                ['{"spline": [[0, 0], [10, 5], [20, 0]], "closed": "line"}'])
        raw = list(raw)
        closed = ent.get("closed", False)
        if closed not in (False, True, "line"):
            raise BridgeError(
                "BAD_OP", "a spline's closed is true (smooth all round), "
                '"line" (shut by a straight line) or false, not %r' % closed)
        pts = [tuple(self.num(v, "spline") for v in p) for p in raw]
        if closed and len(pts) > 1 and math.dist(pts[0], pts[-1]) < 1e-6:
            pts.pop()
            raw.pop()
        if len(pts) < (3 if closed else 2):
            raise BridgeError("BAD_OP", "a spline needs two points or more, "
                              "three if it is closed")
        for i, (p, q) in enumerate(zip(pts, pts[1:])):
            if math.dist(p, q) < 1e-6:
                raise BridgeError("BAD_VALUE", "spline points %d and %d are "
                                  "the same point" % (i, i + 1))
        eid = self.sketch.add_spline(pts, construction, closed is True)
        points = list(self.sketch.entities[eid].points[:len(pts)])
        line = None
        if closed == "line":
            line = self.sketch.add_line(pts[-1], pts[0], construction)
            own = self.sketch.entities[line].points
            self.sketch.entities[line].points = [points[-1], points[0]]
            for pid in own:
                if pid not in points:
                    self.sketch.points.pop(pid, None)
        dimension = ent.get("dimension")
        if dimension is None:
            dimension = any(isinstance(v, str) for p in raw for v in p)
        if dimension:
            for pid, (x, y) in zip(points, raw):
                self.place(pid, x, y)
        else:
            self.loose += 1
        self.name(key, "entity", eid)
        if key:
            if line is not None:
                self.name("%s.chord" % key, "entity", line)
            for i, pid in enumerate(points):
                self.name("%s.p%d" % (key, i), "point", pid)

    def _ellipse(self, ent, e, construction, key) -> None:
        if not isinstance(e, dict) or "rx" not in e or "ry" not in e:
            raise BridgeError(
                "BAD_OP", "an ellipse needs rx and ry, its two half sizes",
                ['{"ellipse": {"center": [0, 0], "rx": 40, "ry": 25, '
                 '"rotation": 0}}'])
        extra = set(e) - {"center", "rx", "ry", "rotation"}
        if extra:
            raise BridgeError("BAD_OP", "ellipse: unknown key(s) %s"
                              % ", ".join(sorted(extra)))
        cx, cy = e.get("center", [0, 0])
        turn = e.get("rotation", 0)
        t = self.job.text
        rx, ry = self.num(e["rx"], "ellipse rx"), self.num(e["ry"],
                                                           "ellipse ry")
        if rx <= 0 or ry <= 0:
            raise BridgeError("BAD_VALUE", "an ellipse needs positive sizes")
        x, y = self.num(cx, "ellipse x"), self.num(cy, "ellipse y")
        angle = math.radians(self.num(turn, "ellipse rotation"))
        eid = self.sketch.add_ellipse(
            (x, y), (x + rx * math.cos(angle), y + rx * math.sin(angle)),
            ry, construction)
        centre, end = self.sketch.entities[eid].points
        self.place(centre, cx, cy)
        if isinstance(turn, str) or turn:
            ex = "(%s) + (%s) * cos(%s)" % (t(cx), t(e["rx"]), t(turn))
            ey = "(%s) + (%s) * sin(%s)" % (t(cy), t(e["rx"]), t(turn))
        else:
            ex = "(%s) + (%s)" % (t(cx), t(e["rx"]))
            ey = cy
        self.place(end, ex, ey)
        self.dim("radius", entities=[eid], value=e["ry"])
        self.name(key, "entity", eid)
        if key:
            self.name("%s.center" % key, "point", centre)
            self.name("%s.major" % key, "point", end)

    job_auto = True

    # constraints -----------------------------------------------------------

    def ref(self, name: Any) -> Tuple[str, int]:
        key = str(name)
        if key in self.names:
            return self.names[key]
        raise BridgeError(
            "BAD_REF", "the sketch has nothing named %r" % key,
            ["Names here: %s" % ", ".join(sorted(self.names))])

    def constraint(self, item: Dict[str, Any], n: int,
                   need_value: bool = False) -> int:
        if not isinstance(item, dict):
            raise BridgeError("BAD_OP", "constraint %d is not an object" % n)
        item = dict(item)
        kind = item.pop("kind", None)
        refs = item.pop("refs", None)
        if kind is None:
            named = [k for k in item if k in KINDS]
            if len(named) != 1:
                raise BridgeError(
                    "BAD_OP", "constraint %d: say which kind, e.g. "
                    '{"perpendicular": ["l1", "l2"]}' % n,
                    ["Kinds: %s" % ", ".join(KINDS)])
            kind = named[0]
            refs = item.pop(kind)
        if kind not in KINDS:
            raise BridgeError("BAD_OP", "unknown constraint %r" % kind,
                              ["Kinds: %s" % ", ".join(KINDS)])
        refs = [refs] if isinstance(refs, str) else list(refs or [])
        value = item.pop("value", None)
        comment = item.pop("comment", "")
        flip = bool(item.pop("flip", False))
        if item:
            raise BridgeError("BAD_OP", "constraint %d: unknown key(s) %s"
                              % (n, ", ".join(sorted(item))))
        is_dim = kind in DIMENSIONS
        if is_dim and value is None:
            raise BridgeError("BAD_OP", "the %s dimension needs a value"
                              % kind)
        if need_value and not is_dim:
            raise BridgeError("BAD_OP", "%s is a constraint, not a "
                              "dimension; put it in constraints" % kind)
        if not is_dim and value is not None:
            raise BridgeError("BAD_OP", "%s takes no value" % kind)
        resolved = [self.ref(r) for r in refs]
        points, entities = self._fit(kind, resolved, refs)
        if kind == "length":
            kind = "distance"
        if kind in ("distance_x", "distance_y", "distance_pl"):
            points = self._oriented(kind, points, self.num(value, kind))
        if is_dim:
            cid = self.dim(kind, points, entities, value, comment)
            self.new_dims.append(cid)
        else:
            cid = self.sketch.add_constraint(kind, points=points,
                                             entities=entities)
        if flip:
            self.sketch.constraints[cid].flip = True
        return cid

    def _oriented(self, kind, points, value: float) -> List[int]:
        """The solver reads these dimensions signed, the way they point; a
        value is a size, so the points are put in the order that makes it
        come out positive where they are drawn, rather than the shape
        being flipped to fit."""
        pts = self.sketch.points
        if kind == "distance_pl":
            p, a, b = (pts[i] for i in points)
            dx, dy = b.x - a.x, b.y - a.y
            signed = (p.x - a.x) * dy - (p.y - a.y) * dx
            if signed * value < 0:
                return [points[0], points[2], points[1]]
            return points
        a, b = pts[points[0]], pts[points[1]]
        measured = (b.x - a.x) if kind == "distance_x" else (b.y - a.y)
        if measured * value < 0:
            return [points[1], points[0]]
        return points

    def _fit(self, kind, resolved, refs):
        """Points and entities in the order the solver reads them."""
        def kinds():
            return "".join("p" if k == "point" else "e" for k, _ in resolved)

        def line(oid):
            ent = self.sketch.entities.get(oid)
            return ent is not None and ent.kind == "line"

        sig = SIGNATURES.get(kind)
        if sig is not None:
            if len(resolved) != len(sig):
                raise BridgeError("BAD_OP", "%s takes %d reference(s), not %d"
                                  % (kind, len(sig), len(resolved)))
            points, entities = [], []
            for (k, oid), want, label in zip(resolved, sig, refs):
                if want == "p":
                    if k != "point":
                        raise BridgeError("BAD_REF", "%s: %r is not a point"
                                          % (kind, label))
                    points.append(oid)
                else:
                    if k != "entity" or (want == "l" and not line(oid)):
                        raise BridgeError(
                            "BAD_REF", "%s: %r is not a %s" % (
                                kind, label,
                                "line" if want == "l" else "curve or line"))
                    entities.append(oid)
            return points, entities
        shape = kinds()
        if kind in ("horizontal", "vertical"):
            if shape == "e" and line(resolved[0][1]):
                return [], [resolved[0][1]]
            if shape == "pp":
                return [r[1] for r in resolved], []
        elif kind in ("distance", "length"):
            if shape == "pp":
                return [r[1] for r in resolved], []
            if shape == "e" and line(resolved[0][1]):
                return list(self.sketch.entities[resolved[0][1]].points), []
        elif kind == "distance_pl":
            if shape == "pe" and line(resolved[1][1]):
                a, b = self.sketch.entities[resolved[1][1]].points
                return [resolved[0][1], a, b], []
        elif kind == "angle":
            if shape in ("e", "ee") and all(line(o) for _k, o in resolved):
                return [], [o for _k, o in resolved]
        elif kind in ("fix", "ground"):
            return ([o for k, o in resolved if k == "point"],
                    [o for k, o in resolved if k == "entity"])
        raise BridgeError(
            "BAD_REF", "%s cannot take %s" % (kind, ", ".join(map(str, refs))),
            [USAGE.get(kind, "See the build tool's description.")])


USAGE = {
    "horizontal": "horizontal takes a line, or two points.",
    "vertical": "vertical takes a line, or two points.",
    "distance": "distance takes two points, or a line (its length).",
    "length": "length takes a line.",
    "distance_pl": "distance_pl takes a point and a line.",
    "angle": "angle takes one line (from horizontal) or two lines.",
}


# ---------------------------------------------------------------- status


def describe(sketch: Sketch, names: Dict[str, Tuple[str, int]]
             ) -> Dict[str, Any]:
    """What the solver says about a sketch, in the sketch's own names."""
    point_name = {oid: k for k, (kind, oid) in names.items()
                  if kind == "point"}
    entity_name = {oid: k for k, (kind, oid) in names.items()
                   if kind == "entity"}

    def ename(eid):
        return entity_name.get(eid, "#e%d" % eid)

    def pname(pid):
        return point_name.get(pid, "#p%d" % pid)

    loose = []
    for eid in sorted(sketch.entities):
        ent = sketch.entities[eid]
        if sketch.entity_constrained(eid):
            continue
        item = {"entity": ename(eid), "kind": ent.kind}
        free = [pname(p) for p in ent.points if p in sketch.free_points]
        if free:
            item["free_points"] = free
        if eid in sketch.free_radii:
            item["free_size"] = True
        if eid in sketch.free_turn:
            item["can_turn"] = True
        if ent.construction:
            item["construction"] = True
        loose.append(item)
    conflicts = []
    for cid in sketch.conflicting:
        c = sketch.constraints.get(cid)
        if c is None:
            continue
        conflicts.append(constraint_text(c, pname, ename))
    dims = []
    for cid in sorted(sketch.constraints):
        c = sketch.constraints[cid]
        if not c.is_dimension:
            continue
        item = {"name": c.name, "kind": c.kind,
                "on": [pname(p) for p in c.points]
                + [ename(e) for e in c.entities],
                "value": round(c.value, 6)}
        if c.expression:
            item["expression"] = c.expression
        if not c.driving:
            item["driven"] = True
        if c.comment:
            item["comment"] = c.comment
        dims.append(item)
    return {"dof": sketch.dof, "status": sketch.solve_message,
            "fully_constrained": sketch.dof == 0 and not sketch.conflicting,
            "entities": len(sketch.entities),
            "constraints": sum(1 for c in sketch.constraints.values()
                               if not c.is_dimension),
            "underconstrained": loose, "conflicts": conflicts,
            "dimensions": dims,
            "names": sorted(k for k in names if k != "origin")}


def constraint_text(c, pname, ename) -> str:
    on = [pname(p) for p in c.points] + [ename(e) for e in c.entities]
    head = "%s %s" % (c.kind, ", ".join(on))
    if c.is_dimension:
        head += " = %s" % (c.expression or round(c.value, 6))
    return head
