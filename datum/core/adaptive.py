"""Adaptive parts: a sketch that follows another part's geometry.

Edited in place, a part can project an edge of the part beside it onto one
of its sketches, the way Inventor does.  The part stays a part: its sketch
holds the projected lines as ordinary geometry, and opened on its own it
shows them where they last were.  What ties them to the other part lives in
the assembly, which is the only place both parts and where each one sits
are known: an AdaptiveLink names the sketch's projection, the part it came
from, and the edge on that part.

Every time the assembly is built, each live link finds its edge on the
source part again, carries it from where that part sits to where the
target part sits, flattens it onto the sketch, and moves the projected
lines there.  The target part is then built again, so a hole projected off
a plate follows the plate.  Turning a link's adaptive flag off freezes it
where it is, as does deleting the source: nothing breaks, the geometry
simply stops moving.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

# the projection record's source, as the part file stores it: the link it
# belongs to is in the assembly, so a part opened on its own keeps the
# lines where they are rather than looking for an edge it cannot reach
ADAPTIVE_KEY = "adaptive"


@dataclass
class AdaptiveLink:
    """One sketch projection in one part, following an edge of another."""

    id: int = 0
    target: int = 0          # the occurrence whose part holds the sketch
    feature: int = 0         # the sketch feature, in that part
    record: int = 0          # its projection record
    source: int = 0          # the occurrence the edge belongs to
    ref: Dict[str, Any] = field(default_factory=dict)   # ShapeRef, part frame
    adaptive: bool = True
    # filled in by an update
    error: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {"id": self.id, "target": self.target, "feature": self.feature,
                "record": self.record, "source": self.source,
                "ref": dict(self.ref), "adaptive": self.adaptive}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AdaptiveLink":
        return cls(id=int(data.get("id", 0)),
                   target=int(data.get("target", 0)),
                   feature=int(data.get("feature", 0)),
                   record=int(data.get("record", 0)),
                   source=int(data.get("source", 0)),
                   ref=dict(data.get("ref") or {}),
                   adaptive=bool(data.get("adaptive", True)))


def is_adaptive_source(source: Optional[Dict[str, Any]]) -> bool:
    return bool(source) and ADAPTIVE_KEY in source


def to_part_frame(picked, source_placement, target_placement):
    """An edge as drawn in the target part's frame, back in the source
    part's own frame, where it can be found on that part's body."""
    there = target_placement.location().Inverted().Multiplied(
        source_placement.location())
    return picked.Located(there.Inverted().Multiplied(picked.Location()))


def in_target_frame(edge, source_placement, target_placement):
    """An edge of the source part, carried to where the target part sees
    it."""
    there = target_placement.location().Inverted().Multiplied(
        source_placement.location())
    return edge.Moved(there)


def _snapshot(sketch, record) -> List[float]:
    out: List[float] = []
    for eid in record.entities:
        entity = sketch.entities.get(eid)
        if entity is None:
            continue
        for pid in entity.points:
            point = sketch.points.get(pid)
            if point is not None:
                out += [point.x, point.y]
        out.append(float(getattr(entity, "radius", 0.0) or 0.0))
    return out


def update(assembly, open_part: Callable[[str], Any]) -> List[Any]:
    """Bring every live link up to date.  Returns the part documents that
    changed, built again, for the assembly to place afresh."""
    from . import kernel
    from .features import SketchFeature, _reshape
    from .naming import ShapeRef

    changed: List[Any] = []
    gone: List[Any] = []
    for link in getattr(assembly, "adaptive", None) or []:
        link.error = ""
        if not link.adaptive:
            continue
        target = assembly.occurrence(link.target)
        source = assembly.occurrence(link.source)
        if target is None or target.suppressed:
            continue
        if source is None or source.suppressed or source.shape is None:
            link.error = "its source is gone; frozen where it was"
            continue
        path = assembly.component_path(target)
        if not path:
            continue
        try:
            document = open_part(path)
        except Exception as exc:
            link.error = "cannot open %s: %s" % (target.label, exc)
            continue
        feature = document.feature(link.feature) \
            if document is not None and hasattr(document, "feature") else None
        if not isinstance(feature, SketchFeature):
            gone.append(link)       # the sketch was deleted: nothing to move
            continue
        sketch = feature.sketch
        record = next((r for r in sketch.projections
                       if r.id == link.record), None)
        if record is None:
            gone.append(link)       # the lines were deleted, or undone
            continue
        try:
            reference = ShapeRef.from_dict(link.ref)
            edge = reference.rebind(source.shape)
        except Exception:
            edge = None
        if edge is None:
            link.error = ("the edge on %s cannot be found; frozen where it "
                          "was" % source.label)
            record.stale = True
            continue
        link.ref = reference.to_dict()
        try:
            cast = kernel.project_to_plane(
                in_target_frame(edge, source.placement, target.placement),
                sketch.plane)
        except Exception:
            cast = None
        before = _snapshot(sketch, record)
        if not cast or not _reshape(sketch, record, cast):
            link.error = "the edge no longer projects the same way"
            record.stale = True
            continue
        record.stale = False
        after = _snapshot(sketch, record)
        if len(before) == len(after) and all(
                math.isclose(a, b, abs_tol=1e-9)
                for a, b in zip(before, after)):
            continue
        document.modified = True
        if document not in changed:
            changed.append(document)
    if gone:
        assembly.adaptive = [link for link in assembly.adaptive
                             if link not in gone]
    for document in changed:
        document.rebuild()
    return changed


def links_for(assembly, occurrence_id: int) -> List[AdaptiveLink]:
    """The links a component takes part in, either end."""
    return [link for link in getattr(assembly, "adaptive", None) or []
            if occurrence_id in (link.target, link.source)]
