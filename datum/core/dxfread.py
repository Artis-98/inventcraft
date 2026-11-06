"""Reading a DXF's flat geometry: enough to bring a title block drawn in
AutoCAD into a drawing's title block.

Lines, polylines, circles, arcs and single line text from the ENTITIES
section, in the file's own units, with arcs and circles broken into short
straight pieces, since a title block is lines and text. Blocks are not
expanded; explode them in AutoCAD first.
"""
from __future__ import annotations

import math
from typing import Dict, List, Tuple

Segment = Tuple[float, float, float, float]


def _pairs(text: str):
    lines = text.splitlines()
    for i in range(0, len(lines) - 1, 2):
        try:
            code = int(lines[i].strip())
        except ValueError:
            continue
        yield code, lines[i + 1].strip()


def _arc(cx, cy, r, a0, a1, step_deg: float = 10.0) -> List[Segment]:
    if a1 <= a0:
        a1 += 360.0
    n = max(2, int(math.ceil((a1 - a0) / step_deg)))
    pts = [(cx + r * math.cos(math.radians(a0 + (a1 - a0) * i / n)),
            cy + r * math.sin(math.radians(a0 + (a1 - a0) * i / n)))
           for i in range(n + 1)]
    return [(p[0], p[1], q[0], q[1]) for p, q in zip(pts, pts[1:])]


def read(path: str) -> Dict[str, list]:
    """``{"lines": [(x1, y1, x2, y2)], "texts": [(x, y, height, text)]}``."""
    with open(path, encoding="utf-8", errors="replace") as handle:
        text = handle.read()
    lines: List[Segment] = []
    texts: List[Tuple[float, float, float, str]] = []
    in_entities = False
    entity = None
    data: Dict[int, list] = {}

    def finish():
        if entity is None:
            return
        g = lambda c, d=0.0: float(data.get(c, [d])[0])  # noqa: E731
        if entity == "LINE":
            lines.append((g(10), g(20), g(11), g(21)))
        elif entity == "LWPOLYLINE":
            xs = [float(v) for v in data.get(10, [])]
            ys = [float(v) for v in data.get(20, [])]
            pts = list(zip(xs, ys))
            closed = int(g(70)) & 1
            if closed and len(pts) > 2:
                pts.append(pts[0])
            lines.extend((p[0], p[1], q[0], q[1])
                         for p, q in zip(pts, pts[1:]))
        elif entity == "CIRCLE":
            lines.extend(_arc(g(10), g(20), g(40), 0.0, 360.0))
        elif entity == "ARC":
            lines.extend(_arc(g(10), g(20), g(40), g(50), g(51)))
        elif entity in ("TEXT", "MTEXT"):
            words = " ".join(str(v) for v in data.get(1, []))
            if entity == "MTEXT":
                words = words.replace("\\P", " ")
            if words.strip():
                texts.append((g(10), g(20), g(40, 2.5), words.strip()))

    polyline: List[Tuple[float, float]] = []
    in_polyline = False
    for code, value in _pairs(text):
        if code == 0:
            if value == "SECTION":
                finish()
                entity, data = None, {}
                continue
            if value == "ENDSEC":
                finish()
                entity, data = None, {}
                in_entities = False
                continue
            if not in_entities:
                continue
            finish()
            if value == "POLYLINE":
                in_polyline, polyline = True, []
                entity, data = None, {}
                continue
            if value == "VERTEX" and in_polyline:
                entity, data = "VERTEX", {}
                continue
            if value == "SEQEND" and in_polyline:
                lines.extend((p[0], p[1], q[0], q[1])
                             for p, q in zip(polyline, polyline[1:]))
                in_polyline = False
                entity, data = None, {}
                continue
            entity, data = value, {}
            continue
        if code == 2 and value == "ENTITIES" and entity is None:
            in_entities = True
            continue
        if entity == "VERTEX" and in_polyline:
            if code == 10:
                polyline.append((float(value), 0.0))
            elif code == 20 and polyline:
                polyline[-1] = (polyline[-1][0], float(value))
            continue
        if entity is not None:
            data.setdefault(code, []).append(value)
    finish()
    return {"lines": lines, "texts": texts}
