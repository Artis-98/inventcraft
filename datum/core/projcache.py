"""Projections already worked out, kept to be used again.

Hidden line removal is the slow part of a drawing: eight seconds a view
on the walking excavator.  And most of the time a view asks for lines it
has had before: its scale changed, it was renamed, a step was undone, a
second view looks the same way, or hidden lines were switched off.  None
of that changes what the model looks like from that side, so the lines
are kept here in model millimetres, keyed by what they do depend on: the
model as it is, which way it is seen, and what kinds of edge were asked
for.

Kept compact, one flat array of doubles a line, because a big view is
half a million points and a Python tuple a point would cost a hundred
bytes each.  The oldest are let go past a budget of points.
"""

from __future__ import annotations

import threading
from array import array
from collections import OrderedDict
from typing import Any, Dict, Hashable, List, Optional, Tuple

from . import hlr

# about 16 bytes a point: 6 million points is under a hundred megabytes
BUDGET_POINTS = 6_000_000


class _Packed:
    __slots__ = ("lines", "box", "centre", "hatch", "points", "keep")

    def __init__(self, projection: hlr.Projection, keep: Any = None) -> None:
        self.lines: List[Tuple[str, array, int]] = []
        count = 0
        for line in projection.lines:
            flat = array("d")
            for x, y in line.points:
                flat.append(x)
                flat.append(y)
            self.lines.append((line.kind, flat, line.group, line.arc))
            count += len(line.points)
        self.box = tuple(projection.box)
        self.centre = tuple(projection.centre)
        self.hatch = projection.hatch
        self.points = count
        # whatever must outlive the key (a live shape, whose id is in it)
        self.keep = keep

    def unpack(self, scale: float = 1.0,
               without: Tuple[str, ...] = ()) -> hlr.Projection:
        lines = []
        s = float(scale) if scale and scale > 0 else 1.0
        for kind, flat, group, arc in self.lines:
            if kind in without:
                continue
            xs = flat[0::2]
            ys = flat[1::2]
            if s != 1.0:
                points = [(x * s, y * s) for x, y in zip(xs, ys)]
            else:
                points = list(zip(xs, ys))
            line = hlr.Polyline(points, kind, group, arc)
            if arc is not None and s != 1.0:
                line.arc = hlr.arc_scaled(arc, s)
            lines.append(line)
        box = tuple(c * s for c in self.box)
        projection = hlr.Projection(lines=lines, box=box, hatch=self.hatch,
                                    centre=self.centre)
        if without:
            _recentre(projection, s)
        return projection


def _recentre(projection: hlr.Projection, scale: float) -> None:
    """Centred again on what is left, as a projection drawn without the
    left out kinds would have been."""
    xs = [p[0] for line in projection.lines for p in line.points]
    ys = [p[1] for line in projection.lines for p in line.points]
    if not xs:
        return
    dx = (min(xs) + max(xs)) / 2.0
    dy = (min(ys) + max(ys)) / 2.0
    if abs(dx) > 1e-12 or abs(dy) > 1e-12:
        for line in projection.lines:
            line.moved(-dx, -dy)
    half_w = (max(xs) - min(xs)) / 2.0
    half_h = (max(ys) - min(ys)) / 2.0
    projection.box = (-half_w, -half_h, half_w, half_h)
    cx, cy = projection.centre
    projection.centre = (cx + dx / scale, cy + dy / scale)


class ProjectionCache:
    def __init__(self, budget: int = BUDGET_POINTS) -> None:
        self.budget = budget
        self._held: "OrderedDict[Hashable, _Packed]" = OrderedDict()
        self._points = 0
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    def __len__(self) -> int:
        return len(self._held)

    def clear(self) -> None:
        with self._lock:
            self._held.clear()
            self._points = 0

    def put(self, key: Hashable, projection: hlr.Projection,
            keep: Any = None) -> None:
        """Keep a projection, in model millimetres, under ``key``."""
        if projection is None or not projection.ok:
            return
        packed = _Packed(projection, keep)
        if packed.points > self.budget:
            return
        with self._lock:
            old = self._held.pop(key, None)
            if old is not None:
                self._points -= old.points
            self._held[key] = packed
            self._points += packed.points
            while self._points > self.budget and self._held:
                _k, gone = self._held.popitem(last=False)
                self._points -= gone.points

    def get(self, key: Hashable, scale: float = 1.0) -> Optional[
            hlr.Projection]:
        """A fresh copy, at ``scale``, of what is kept under ``key``."""
        with self._lock:
            packed = self._held.get(key)
            if packed is not None:
                self._held.move_to_end(key)
        if packed is None:
            self.misses += 1
            return None
        self.hits += 1
        return packed.unpack(scale)

    def has(self, key: Hashable) -> bool:
        with self._lock:
            return key in self._held

    def get_without(self, key: Hashable, kinds: Tuple[str, ...],
                    scale: float = 1.0) -> Optional[hlr.Projection]:
        """What is under ``key`` with some kinds of line left out."""
        with self._lock:
            packed = self._held.get(key)
            if packed is not None:
                self._held.move_to_end(key)
        if packed is None:
            return None
        self.hits += 1
        return packed.unpack(scale, without=kinds)


_SHARED: Optional[ProjectionCache] = None


def shared() -> ProjectionCache:
    """The one cache every drawing in the window uses."""
    global _SHARED
    if _SHARED is None:
        _SHARED = ProjectionCache()
    return _SHARED


def plain_key(model: Hashable, direction, up, hidden: bool,
              tangents: bool, fast: bool = False) -> Tuple:
    """The key of a plain view: the model as it is, and how it is seen."""
    def r(v):
        return tuple(round(float(c), 9) + 0.0 for c in v)
    return ("plain", model, r(direction), r(up), bool(hidden),
            bool(tangents), bool(fast))


def stats() -> Dict[str, int]:
    c = shared()
    return {"entries": len(c), "points": c._points, "hits": c.hits,
            "misses": c.misses}
