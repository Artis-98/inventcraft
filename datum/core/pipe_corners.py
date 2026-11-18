"""A pipe's corners, each a bend or an elbow fitting, switched one by one.

Every corner of the pipes in a frame is one of two things: a bend in a
pipe (a merged run turning there), or an elbow where two pipes meet.  A
bend switched to an elbow splits its pipe at that corner into two, and
the elbow goes in by itself where they now meet; an elbow switched to a
bend joins its two pipes into one again, bent there.  So the whole of a
frame's piping stays as Insert Pipe makes it, members and fittings,
and the choice is the user's at each corner.
"""

from __future__ import annotations

import copy
import math
import os
from dataclasses import dataclass, field
from typing import Any, List, Optional, Sequence, Tuple

from .kernel import KernelError

BEND, ELBOW = "bend", "elbow"


@dataclass
class Corner:
    point: Tuple[float, float, float]      # in the frame
    kind: str                              # "bend", or a fitting's kind
    angle: float                           # degrees turned
    members: List[int] = field(default_factory=list)
    label: str = ""

    @property
    def choices(self) -> List[str]:
        """What it can be switched to: a bend or elbow at 90 or 45, either;
        a bend at another angle has no elbow; tees and the rest stay."""
        if self.kind == BEND:
            return [BEND, ELBOW] if any(abs(self.angle - a) < 0.5
                                        for a in (90.0, 45.0)) else [BEND]
        if self.kind in ("elbow90", "elbow45"):
            return [BEND, ELBOW]
        return []

    @property
    def now(self) -> str:
        return BEND if self.kind == BEND else ELBOW


def corners(frame_doc) -> List[Corner]:
    """Every corner of the frame's pipes: each bend in a pipe, and each
    fitting where pipes meet."""
    from . import frames
    fd = frame_doc.frame
    if fd is None:
        return []
    geos = frames.member_geometries(fd, frames.skeleton_sketches(
        frames.skeleton_path(frame_doc)), [])
    out = []
    for mid, geo in geos.items():
        if not frames.is_pipe(geo):
            continue
        for b in geo.route.bends:
            out.append(Corner(geo.to_world(geo.route.points[b.corner]),
                              BEND, b.angle, [mid],
                              "Bend %.0f° R%g" % (b.angle, b.radius)))
    for f in getattr(fd, "planned_fittings", []):
        angle = 90.0 if f.kind == "elbow90" else 45.0 \
            if f.kind == "elbow45" else 0.0
        out.append(Corner(tuple(f.point), f.kind, angle,
                          [m for m, _e in f.ends], f.label))
    return out


def _keys(member) -> List[Tuple[int, int]]:
    """A member's lines as (sketch, line), in the order they are walked."""
    if member.segments:
        return [tuple(k) for k in member.segments]
    return [(member.sketch, i) for i in member.lines]


def _set_keys(member, keys: Sequence[Tuple[int, int]]) -> None:
    keys = [tuple(k) for k in keys]
    member.sketch = keys[0][0]
    if all(k[0] == member.sketch for k in keys):
        member.segments, member.lines = [], [k[1] for k in keys]
    else:
        member.segments = [list(k) for k in keys]
        member.lines = [k[1] for k in keys]


def _walked(lines, keys) -> List[Tuple[float, ...]]:
    """The points a run passes, one after each of its lines."""
    if len(keys) == 1:
        return [tuple(p) for p in lines[keys[0]]]
    a0, b0 = lines[keys[0]]
    a1, b1 = lines[keys[1]]
    here = a0 if any(math.dist(a0, q) < 1e-3 for q in (a1, b1)) else b0
    out = [b0 if here is a0 else a0, here]
    for k in keys[1:]:
        a, b = lines[k]
        here = b if math.dist(a, here) < 1e-3 else a
        out.append(here)
    return [tuple(p) for p in out]


def _remove_member(frame_doc, member) -> None:
    fd = frame_doc.frame
    base = frame_doc.base_dir
    for oid in (member.occurrence, member.insulation_occurrence):
        if oid:
            try:
                frame_doc.remove_occurrence(oid)
            except Exception:
                pass
    for part in (member.part, member.insulation_part):
        if part:
            try:
                os.remove(os.path.join(base, part) if base else part)
            except OSError:
                pass
    fd.members = [m for m in fd.members if m.id != member.id]


def set_corner(frame_doc, point, want: str) -> List[str]:
    """Make the corner at ``point`` (in the frame) a bend or an elbow.
    Returns what went wrong once the frame is brought up to it."""
    from . import frames
    fd = frame_doc.frame
    if fd is None:
        raise ValueError("that is not a frame")
    found = min(corners(frame_doc), key=lambda c: math.dist(c.point, point),
                default=None)
    if found is None or math.dist(found.point, point) > 1e-3:
        raise ValueError("there is no pipe corner there")
    if want not in found.choices:
        raise ValueError("%s cannot be made a%s %s" % (
            found.label, "n" if want == ELBOW else "", want))
    if want == found.now:
        return []
    lines = frames.all_lines(frames.skeleton_sketches(
        frames.skeleton_path(frame_doc)))
    if want == ELBOW:
        member = fd.member(found.members[0])
        keys = _keys(member)
        pts = _walked(lines, keys)
        # the line whose far end is the corner: the split comes after it
        # the frame follows its skeleton, so a corner in the frame is where
        # the skeleton's lines have it
        at = next((i for i in range(len(keys))
                   if math.dist(pts[i + 1], found.point) < 1e-3), None)
        if at is None or at >= len(keys) - 1:
            raise ValueError("the bend is not between two of its lines")
        second = copy.deepcopy(member)
        second.id = max(m.id for m in fd.members) + 1
        second.part, second.occurrence = "", 0
        second.insulation_part, second.insulation_occurrence = "", 0
        _set_keys(member, keys[:at + 1])
        _set_keys(second, keys[at + 1:])
        fd.members.insert(fd.members.index(member) + 1, second)
    else:
        first, other = (fd.member(m) for m in found.members[:2])
        if first.size != other.size or first.family != other.family:
            raise ValueError("the two pipes are not the same tube")
        k1, k2 = _keys(first), _keys(other)
        corner = tuple(found.point)
        p1, p2 = _walked(lines, k1), _walked(lines, k2)
        if math.dist(p1[0], corner) < 1e-3:
            k1.reverse()
        if math.dist(p2[-1], corner) < 1e-3:
            k2.reverse()
        _set_keys(first, k1 + k2)
        _remove_member(frame_doc, other)
    problems = frames.sync(frame_doc)
    frame_doc.save(frame_doc.path)
    return problems
