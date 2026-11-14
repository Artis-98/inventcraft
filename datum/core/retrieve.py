"""Retrieve Model Annotations: a part's own dimensions onto a drawing view.

Inventor's Retrieve brings the dimensions that were put on the 3D model
onto a view of it, the ones that view can show truly.  So does this: each
of the part's model annotations (annotations.py) is measured on the body,
carried onto the view's paper the way its lines were, and kept only where
the view sees it at its real size.  A length seen foreshortened, or a
hole seen from the side, is left for a view that looks at it square on.

What comes onto the sheet is an ordinary drawing dimension, tied to the
model like one placed by hand, and marked with the model annotation it
came from so retrieving again does not add it twice.
"""
from __future__ import annotations

import math
from typing import List, Optional, Sequence, Tuple

from . import annotations as model
from . import hlr
from .drawing import ALIGNED, DIAMETER, LEADER, LINEAR, Annotation

TRUE_LENGTH = 1e-3      # how close seen and real must be, as a fraction
SQUARE_ON = 0.999       # how nearly an axis must point at the viewer


def _paper(point, frame, middle, scale) -> Tuple[float, float]:
    x, y = hlr.to_paper(point, frame, middle)
    return (x * scale, y * scale)


def _axis_of(note, shape) -> Optional[Tuple[float, float, float]]:
    """A round annotation's axis, from the face or edge it measured."""
    from .constraints3d import AXIS, CIRCLE, frame_from_shape

    found = model._resolve(note, shape)
    if not found:
        return None
    frame = frame_from_shape(found[0])
    if frame is None or frame.kind not in (AXIS, CIRCLE):
        return None
    return tuple(frame.direction)


def candidates(part, shape, direction, up, middle, scale
               ) -> List[Tuple[object, Annotation]]:
    """Every model annotation the view can show, as the drawing
    annotation it would become: [(model annotation, drawing one)]."""
    frame = hlr.camera(direction, up)
    d = direction
    out = []
    for note in getattr(part, "annotations", None) or []:
        if note.hidden:
            continue
        model.evaluate(note, shape)
        if note.lost or len(note.points) < 2:
            continue
        if note.kind == model.LINEAR:
            p, q = note.points
            pp = _paper(p, frame, middle, scale)
            qq = _paper(q, frame, middle, scale)
            seen = math.dist(pp, qq) / (scale or 1.0)
            if note.value <= 1e-9 or abs(seen - note.value) > \
                    TRUE_LENGTH * max(1.0, note.value):
                continue            # foreshortened here: not this view's
            dx, dy = qq[0] - pp[0], qq[1] - pp[1]
            span = math.hypot(dx, dy) or 1.0
            if abs(dy) < 1e-6 * span:
                kind, axis = LINEAR, "x"
            elif abs(dx) < 1e-6 * span:
                kind, axis = LINEAR, "y"
            else:
                kind, axis = ALIGNED, ""
            # where it stood off the part, as the view sees that
            tip = [p[i] + note.offset[i] for i in range(3)]
            moved = _paper(tip, frame, middle, scale)
            off = (moved[0] - pp[0], moved[1] - pp[1])
            if axis == "x":
                reach = off[1] if abs(off[1]) > 2.0 else 8.0
                offset = [0.0, reach]
            elif axis == "y":
                reach = off[0] if abs(off[0]) > 2.0 else 8.0
                offset = [reach, 0.0]
            else:
                nx, ny = -dy / span, dx / span
                reach = off[0] * nx + off[1] * ny
                offset = [0.0, reach if abs(reach) > 2.0 else 8.0]
            out.append((note, Annotation(kind=kind, points=[list(pp),
                                                           list(qq)],
                                         offset=offset, axis=axis,
                                         text=_typed(note))))
            continue
        axis = _axis_of(note, shape)
        if axis is None or abs(sum(axis[i] * d[i] for i in range(3))) \
                < SQUARE_ON:
            continue                # seen from the side: not a circle here
        centre, rim = note.points
        cc = _paper(centre, frame, middle, scale)
        rr = _paper(rim, frame, middle, scale)
        if note.kind == model.HOLE:
            out.append((note, Annotation(kind=LEADER, points=[list(rr)],
                                         offset=[8.0, 8.0],
                                         text=note.display)))
        else:
            out.append((note, Annotation(kind=DIAMETER,
                                         points=[list(cc), list(rr)],
                                         offset=[6.0, 6.0],
                                         text=_typed(note))))
    return out


def _typed(note) -> str:
    """What was typed on the model annotation, carried over as it reads
    there; empty when it shows just its value, so the drawing measures."""
    if not note.text and not note.tolerance:
        return ""
    return note.display


def already(sheet, view_id: int) -> set:
    """The model annotations a view already has, by id."""
    return {n.retrieved for n in sheet.annotations
            if n.view == view_id and getattr(n, "retrieved", 0)}
