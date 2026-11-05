"""Trim, the way Inventor's does it: the piece under the cursor goes, up to
the nearest geometry on either side, whatever that geometry is.

A line stops where another crosses it, where a circle or an arc crosses it
or only touches it (a line drawn tangent to a circle stops at the tangent
point), and where another line ends on it. An arc or a circle is cut the
same way, and a circle cut twice becomes the arc that is left.

What is kept is the same entity, shortened, so what holds it stays: a
coincident on the end that is not trimmed, a tangent, a horizontal. The
new end is held on the geometry it was cut at.
"""
import math
from typing import List, Tuple

EPS = 1e-6
# how near a line has to come to a circle to count as touching it: the
# solver leaves a tangent a hair off, and a hair is all that is forgiven
TOUCH = 1e-5

Point = Tuple[float, float]


def _arc_span(sketch, eid) -> Tuple[float, float]:
    """An arc's start angle and its sweep, positive, counter-clockwise."""
    a0, a1 = sketch.arc_angles(eid)
    if a1 >= a0:
        return a0, a1 - a0
    # clockwise arcs run backwards; the same arc read the other way
    return a1, a0 - a1


def _on_arc(sketch, eid, p: Point, slack: float = 1e-7) -> bool:
    ent = sketch.entities[eid]
    if ent.kind == "circle":
        return True
    c = sketch.points[ent.points[0]]
    start, sweep = _arc_span(sketch, eid)
    angle = (math.atan2(p[1] - c.y, p[0] - c.x) - start) % (2 * math.pi)
    tol = slack + EPS / max(ent.radius, EPS)
    return angle <= sweep + tol or angle >= 2 * math.pi - tol


def _line(sketch, eid):
    ent = sketch.entities[eid]
    a, b = sketch.points[ent.points[0]], sketch.points[ent.points[1]]
    return (a.x, a.y), (b.x, b.y)


def _circle(sketch, eid):
    ent = sketch.entities[eid]
    c = sketch.points[ent.points[0]]
    return (c.x, c.y), ent.radius


def _line_line(p, q) -> List[Point]:
    (ax, ay), (bx, by) = p
    (cx, cy), (dx_, dy_) = q
    rx, ry = bx - ax, by - ay
    sx, sy = dx_ - cx, dy_ - cy
    denom = rx * sy - ry * sx
    if abs(denom) < 1e-12:
        return []
    t = ((cx - ax) * sy - (cy - ay) * sx) / denom
    u = ((cx - ax) * ry - (cy - ay) * rx) / denom
    lt = EPS / max(math.hypot(rx, ry), EPS)
    lu = EPS / max(math.hypot(sx, sy), EPS)
    if -lt <= t <= 1 + lt and -lu <= u <= 1 + lu:
        return [(ax + rx * t, ay + ry * t)]
    return []


def _line_circle(p, centre, r) -> List[Point]:
    (ax, ay), (bx, by) = p
    dx, dy = bx - ax, by - ay
    fx, fy = ax - centre[0], ay - centre[1]
    a = dx * dx + dy * dy
    if a < 1e-18:
        return []
    b = 2 * (fx * dx + fy * dy)
    c = fx * fx + fy * fy - r * r
    disc = b * b - 4 * a * c
    length = math.sqrt(a)
    # how far the infinite line passes from the centre, against the radius
    gap = abs(fx * dy - fy * dx) / length - r
    if disc < 0:
        if gap > TOUCH:
            return []
        roots = [-b / (2 * a)]
    elif gap > -TOUCH:
        # touching, or as good as: one point, not two a hair apart
        roots = [-b / (2 * a)]
    else:
        s = math.sqrt(disc)
        roots = [(-b - s) / (2 * a), (-b + s) / (2 * a)]
    lt = EPS / length
    return [(ax + dx * t, ay + dy * t) for t in roots if -lt <= t <= 1 + lt]


def _circle_circle(c1, r1, c2, r2) -> List[Point]:
    dx, dy = c2[0] - c1[0], c2[1] - c1[1]
    d = math.hypot(dx, dy)
    if d < 1e-12 or d > r1 + r2 + TOUCH or d < abs(r1 - r2) - TOUCH:
        return []
    a = (r1 * r1 - r2 * r2 + d * d) / (2 * d)
    h2 = r1 * r1 - a * a
    mx, my = c1[0] + dx * a / d, c1[1] + dy * a / d
    if h2 <= (TOUCH * max(r1, 1.0)) ** 2:
        return [(mx, my)]
    h = math.sqrt(h2)
    return [(mx - dy * h / d, my + dx * h / d),
            (mx + dy * h / d, my - dx * h / d)]


def _polyline_hits(sketch, eid, poly) -> List[Point]:
    ent = sketch.entities[eid]
    out: List[Point] = []
    for i in range(len(poly) - 1):
        seg = (poly[i], poly[i + 1])
        if ent.kind == "line":
            out += _line_line(_line(sketch, eid), seg)
        else:
            centre, r = _circle(sketch, eid)
            out += [p for p in _line_circle(seg, centre, r)
                    if _on_arc(sketch, eid, p)]
    return out


def crossings(sketch, eid, other) -> List[Point]:
    """Where entity ``other`` meets entity ``eid``: crossing, touching, or
    ending on it."""
    me, it = sketch.entities[eid], sketch.entities[other]
    curved = ("arc", "circle")
    if it.kind == "spline" or it.kind not in ("line",) + curved:
        if it.kind != "spline":
            return []
        return _polyline_hits(sketch, eid, sketch.entity_polyline(other, 64))
    if me.kind == "line" and it.kind == "line":
        return _line_line(_line(sketch, eid), _line(sketch, other))
    if me.kind == "line":
        centre, r = _circle(sketch, other)
        return [p for p in _line_circle(_line(sketch, eid), centre, r)
                if _on_arc(sketch, other, p)]
    if it.kind == "line":
        centre, r = _circle(sketch, eid)
        return [p for p in _line_circle(_line(sketch, other), centre, r)
                if _on_arc(sketch, eid, p)]
    c1, r1 = _circle(sketch, eid)
    c2, r2 = _circle(sketch, other)
    return [p for p in _circle_circle(c1, r1, c2, r2)
            if _on_arc(sketch, eid, p) and _on_arc(sketch, other, p)]


def _param(sketch, eid, p: Point) -> float:
    """Where a point lies along an entity: 0 to 1 along a line or an arc,
    an angle from 0 to 2 pi round a circle."""
    ent = sketch.entities[eid]
    if ent.kind == "line":
        (ax, ay), (bx, by) = _line(sketch, eid)
        dx, dy = bx - ax, by - ay
        return ((p[0] - ax) * dx + (p[1] - ay) * dy) / (dx * dx + dy * dy)
    c = sketch.points[ent.points[0]]
    angle = math.atan2(p[1] - c.y, p[0] - c.x)
    if ent.kind == "circle":
        return angle % (2 * math.pi)
    start, sweep = _arc_span(sketch, eid)
    along = (angle - start) % (2 * math.pi)
    if along > sweep + (2 * math.pi - sweep) / 2:
        along -= 2 * math.pi
    t = along / sweep if sweep > 1e-12 else 0.0
    a0, a1 = sketch.arc_angles(eid)
    # read from the arc's own first point, whichever way it runs
    return t if a1 >= a0 else 1.0 - t


def cuts(sketch, eid) -> List[Tuple[float, int]]:
    """Every place the entity is cut, as (parameter, the entity cutting
    it), in order, its own ends left out."""
    ent = sketch.entities[eid]
    found: List[Tuple[float, int]] = []
    closed = ent.kind == "circle"
    length = _length(sketch, eid)
    for other in sketch.entities:
        if other == eid:
            continue
        for p in crossings(sketch, eid, other):
            t = _param(sketch, eid, p)
            if not closed:
                margin = EPS / max(length, EPS)
                if t <= margin or t >= 1 - margin:
                    continue
            near = 1e-9 if closed else EPS / max(length, EPS)
            if all(abs(t - u) > near for u, _o in found):
                found.append((t, other))
    found.sort()
    return found


def _length(sketch, eid) -> float:
    ent = sketch.entities[eid]
    if ent.kind == "line":
        (ax, ay), (bx, by) = _line(sketch, eid)
        return math.hypot(bx - ax, by - ay)
    if ent.kind == "circle":
        return 2 * math.pi * ent.radius
    return ent.radius * _arc_span(sketch, eid)[1]


def _at(sketch, eid, t: float) -> Point:
    ent = sketch.entities[eid]
    if ent.kind == "line":
        (ax, ay), (bx, by) = _line(sketch, eid)
        return (ax + (bx - ax) * t, ay + (by - ay) * t)
    c = sketch.points[ent.points[0]]
    if ent.kind == "circle":
        angle = t
    else:
        a0, a1 = sketch.arc_angles(eid)
        angle = a0 + (a1 - a0) * t
    return (c.x + ent.radius * math.cos(angle),
            c.y + ent.radius * math.sin(angle))


def _hold(sketch, pid: int, eid: int, cutter: int) -> None:
    """The new end stays on what it was cut at, unless something already
    ties the two together in a way that would make it say so twice."""
    if cutter not in sketch.entities:
        return
    for c in sketch.constraints.values():
        if c.kind == "tangent" and set(c.entities) == {eid, cutter}:
            # a tangent line's end on the circle is the tangent itself
            # said again, and the solver reads that as over-constrained
            return
    sketch.add_constraint("point_on", points=[pid], entities=[cutter])


def _let_go(sketch, pid: int) -> None:
    """A point the trim cut loose: what held it goes with it, unless it is
    still the end of something else."""
    if any(pid in e.points for e in sketch.entities.values()):
        return
    for cid in [c.id for c in sketch.constraints.values() if pid in c.points]:
        sketch.constraints.pop(cid, None)
    point = sketch.points.get(pid)
    if point is not None and not point.origin:
        sketch.points.pop(pid, None)


def trim(sketch, eid: int, click: Point) -> bool:
    """Trim the piece of entity ``eid`` nearest ``click``. Removes the whole
    entity when nothing cuts it, as Inventor does. False when nothing
    happened."""
    ent = sketch.entities.get(eid)
    if ent is None:
        return False
    if ent.kind not in ("line", "arc", "circle"):
        sketch.remove_entity(eid)
        return True
    found = cuts(sketch, eid)
    if ent.kind == "circle":
        return _trim_circle(sketch, eid, click, found)
    if not found:
        sketch.remove_entity(eid)
        return True
    t_click = min(1.0, max(0.0, _param(sketch, eid, click)))
    bounds = [(0.0, None)] + found + [(1.0, None)]
    for i in range(len(bounds) - 1):
        lo, lo_by = bounds[i]
        hi, hi_by = bounds[i + 1]
        if lo - 1e-9 <= t_click <= hi + 1e-9:
            break
    first, last = i == 0, i == len(bounds) - 2
    if first and last:
        sketch.remove_entity(eid)
        return True
    if ent.kind == "line":
        a, b = ent.points
    else:
        _c, a, b = ent.points
    if first:
        # the start goes: the entity now starts where it was cut
        _move_end(sketch, eid, 0, hi, hi_by)
        _let_go(sketch, a)
    elif last:
        _move_end(sketch, eid, 1, lo, lo_by)
        _let_go(sketch, b)
    else:
        # a piece out of the middle: the entity keeps its start and runs
        # to the first cut, and a new one from the second cut takes its end
        far = _at(sketch, eid, hi)
        twin = _split_off(sketch, eid, far, b)
        _hold(sketch, sketch.entities[twin].points[-2 if ent.kind == "arc"
                                                  else 0], twin, hi_by)
        _move_end(sketch, eid, 1, lo, lo_by)
    return True


def piece(sketch, eid: int, click: Point) -> List[Point]:
    """What a trim at ``click`` would take away, as points along it: what
    the cursor lights up before the click."""
    ent = sketch.entities.get(eid)
    if ent is None or ent.kind not in ("line", "arc", "circle"):
        return sketch.entity_polyline(eid, 48) if ent is not None else []
    found = cuts(sketch, eid)
    if ent.kind == "circle":
        if len(found) < 2:
            return sketch.entity_polyline(eid, 64)
        c = sketch.points[ent.points[0]]
        angle = math.atan2(click[1] - c.y, click[0] - c.x) % (2 * math.pi)
        angles = [t for t, _o in found]
        k = 0
        while k < len(angles) and angles[k] <= angle:
            k += 1
        lo, hi = angles[(k - 1) % len(angles)], angles[k % len(angles)]
        if hi <= lo:
            hi += 2 * math.pi
        return [_at(sketch, eid, lo + (hi - lo) * i / 32) for i in range(33)]
    t_click = min(1.0, max(0.0, _param(sketch, eid, click)))
    ts = [0.0] + [t for t, _o in found] + [1.0]
    for i in range(len(ts) - 1):
        if ts[i] - 1e-9 <= t_click <= ts[i + 1] + 1e-9:
            break
    lo, hi = ts[i], ts[i + 1]
    steps = 1 if ent.kind == "line" else 32
    return [_at(sketch, eid, lo + (hi - lo) * j / steps)
            for j in range(steps + 1)]


def _move_end(sketch, eid: int, end: int, t: float, cutter) -> None:
    """Give an entity a new point at parameter ``t`` in place of its start
    (``end`` 0) or its end (1), held on the cutter."""
    ent = sketch.entities[eid]
    x, y = _at(sketch, eid, t)
    pid = sketch.add_point(x, y)
    slot = end if ent.kind == "line" else end + 1
    ent.points[slot] = pid
    if cutter is not None:
        _hold(sketch, pid, eid, cutter)


def _split_off(sketch, eid: int, start: Point, end_pid: int) -> int:
    """A copy of a line or an arc from ``start`` to the point ``end_pid``,
    standing where the original did."""
    from .sketch import Entity
    ent = sketch.entities[eid]
    pid = sketch.add_point(*start)
    new_id = sketch._new_id()
    if ent.kind == "line":
        sketch.entities[new_id] = Entity(new_id, "line", [pid, end_pid],
                                         construction=ent.construction)
        for c in list(sketch.constraints.values()):
            if c.kind in ("horizontal", "vertical") and c.entities == [eid]:
                sketch.add_constraint(c.kind, entities=[new_id])
        sketch.add_constraint("collinear", entities=[eid, new_id])
    else:
        centre = ent.points[0]
        sketch.entities[new_id] = Entity(new_id, "arc", [centre, pid, end_pid],
                                         radius=ent.radius, ccw=ent.ccw,
                                         construction=ent.construction)
        sketch.add_constraint("equal", entities=[eid, new_id])
    return new_id


def _trim_circle(sketch, eid: int, click: Point, found) -> bool:
    """A circle cut in two places or more: the piece clicked goes and the
    rest of it stays, as an arc. Cut once or not at all, it all goes."""
    if len(found) < 2:
        sketch.remove_entity(eid)
        return True
    ent = sketch.entities[eid]
    c = sketch.points[ent.points[0]]
    angle = math.atan2(click[1] - c.y, click[0] - c.x) % (2 * math.pi)
    angles = [t for t, _o in found]
    # the gap the click is in, between two cuts, going round
    k = 0
    while k < len(angles) and angles[k] <= angle:
        k += 1
    gone_from = found[(k - 1) % len(found)]
    gone_to = found[k % len(found)]
    # what is left runs from the end of the gap, counter-clockwise, to its
    # start
    keep_from, keep_to = gone_to, gone_from
    p1 = sketch.add_point(c.x + ent.radius * math.cos(keep_from[0]),
                          c.y + ent.radius * math.sin(keep_from[0]))
    p2 = sketch.add_point(c.x + ent.radius * math.cos(keep_to[0]),
                          c.y + ent.radius * math.sin(keep_to[0]))
    ent.kind = "arc"
    ent.points = [ent.points[0], p1, p2]
    ent.ccw = True
    _hold(sketch, p1, eid, keep_from[1])
    _hold(sketch, p2, eid, keep_to[1])
    return True
