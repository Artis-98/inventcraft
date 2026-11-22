"""Pictures of a model for an agent to look at, made without a screen.

The lines come from the same hidden line removal the drawings use
(``core.hlr``), so a view needs no graphics card, no window and no Qt:
it works in a headless host, on a build machine and over a remote shell.
Line drawings are also what an agent reads best. An edge it is about to
fillet is an edge, not a change of shading.

The rasteriser is a few dozen lines of Wu's antialiased line algorithm and
a hand-written PNG encoder, which keeps the host free of any imaging
library. A model of a few thousand edges draws in well under a second.
"""

from __future__ import annotations

import math
import struct
import zlib
from typing import Dict, List, Optional, Sequence, Tuple

# what each kind of line looks like: colour, and dash length in pixels
# (0 is solid); drawn in this order, so visible lines land on top
STYLE: Dict[str, Tuple[Tuple[int, int, int], int]] = {
    "hidden": ((178, 184, 194), 6),
    "smooth": ((150, 158, 170), 0),
    "outline": ((40, 44, 52), 0),
    "visible": ((24, 28, 36), 0),
    "cut": ((200, 60, 40), 0),
    "bend": ((60, 120, 200), 4),
    "highlight": ((230, 110, 20), 0),
}
ORDER = ("hidden", "smooth", "bend", "outline", "visible", "cut",
         "highlight")
BACKGROUND = (255, 255, 255)


class Canvas:
    def __init__(self, width: int, height: int) -> None:
        self.w = int(width)
        self.h = int(height)
        self.px = bytearray(bytes(BACKGROUND) * (self.w * self.h))

    def _plot(self, x: int, y: int, colour, alpha: float) -> None:
        if 0 <= x < self.w and 0 <= y < self.h and alpha > 0.0:
            i = (y * self.w + x) * 3
            a = min(1.0, alpha)
            for k in range(3):
                self.px[i + k] = int(self.px[i + k] * (1.0 - a)
                                     + colour[k] * a)

    def line(self, x0: float, y0: float, x1: float, y1: float, colour,
             width: float = 1.0) -> None:
        """Wu's antialiased line; ``width`` above 1 draws it again beside
        itself, which is enough to make the visible edges read as bolder."""
        self._wu(x0, y0, x1, y1, colour)
        if width > 1.0:
            dx, dy = x1 - x0, y1 - y0
            n = math.hypot(dx, dy) or 1.0
            ox, oy = -dy / n * 0.6, dx / n * 0.6
            self._wu(x0 + ox, y0 + oy, x1 + ox, y1 + oy, colour, 0.55)

    def _wu(self, x0, y0, x1, y1, colour, strength: float = 1.0) -> None:
        steep = abs(y1 - y0) > abs(x1 - x0)
        if steep:
            x0, y0, x1, y1 = y0, x0, y1, x1
        if x0 > x1:
            x0, x1, y0, y1 = x1, x0, y1, y0
        dx = x1 - x0
        grad = (y1 - y0) / dx if dx else 1.0
        x = math.floor(x0 + 0.5)
        y = y0 + grad * (x - x0)
        end = math.floor(x1 + 0.5)
        plot = self._plot
        while x <= end:
            fy = math.floor(y)
            frac = y - fy
            if steep:
                plot(fy, x, colour, (1 - frac) * strength)
                plot(fy + 1, x, colour, frac * strength)
            else:
                plot(x, fy, colour, (1 - frac) * strength)
                plot(x, fy + 1, colour, frac * strength)
            y += grad
            x += 1

    def png(self) -> bytes:
        raw = bytearray()
        stride = self.w * 3
        for row in range(self.h):
            raw.append(0)
            raw.extend(self.px[row * stride:(row + 1) * stride])

        def chunk(tag: bytes, data: bytes) -> bytes:
            return (struct.pack(">I", len(data)) + tag + data
                    + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

        header = struct.pack(">IIBBBBB", self.w, self.h, 8, 2, 0, 0, 0)
        return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
                + chunk(b"IDAT", zlib.compress(bytes(raw), 6))
                + chunk(b"IEND", b""))


def _dashed(points, dash: float):
    """Split a polyline into the pieces of a dashed line, in pixels."""
    on, left = True, dash
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        seg = math.hypot(x1 - x0, y1 - y0)
        t = 0.0
        while seg > 1e-9 and t < seg:
            step = min(left, seg - t)
            if on:
                a, b = t / seg, (t + step) / seg
                yield (x0 + (x1 - x0) * a, y0 + (y1 - y0) * a,
                       x0 + (x1 - x0) * b, y0 + (y1 - y0) * b)
            t += step
            left -= step
            if left <= 1e-9:
                on, left = not on, dash


def draw(lines: Sequence[Tuple[str, Sequence[Tuple[float, float]]]],
         size: Tuple[int, int] = (800, 600), margin: int = 24
         ) -> Tuple[bytes, float]:
    """Fit ``(kind, points)`` lines in model millimetres onto a picture.

    Returns the PNG and the scale in pixels per millimetre."""
    width, height = size
    canvas = Canvas(width, height)
    xs = [p[0] for _k, pts in lines for p in pts]
    ys = [p[1] for _k, pts in lines for p in pts]
    if not xs:
        return canvas.png(), 0.0
    span_x = max(max(xs) - min(xs), 1e-6)
    span_y = max(max(ys) - min(ys), 1e-6)
    scale = min((width - 2 * margin) / span_x, (height - 2 * margin) / span_y)
    cx = (max(xs) + min(xs)) / 2.0
    cy = (max(ys) + min(ys)) / 2.0

    def to_px(p):
        return (width / 2.0 + (p[0] - cx) * scale,
                height / 2.0 - (p[1] - cy) * scale)

    by_kind: Dict[str, List] = {}
    for kind, pts in lines:
        by_kind.setdefault(kind if kind in STYLE else "visible", []).append(
            [to_px(p) for p in pts])
    for kind in ORDER:
        colour, dash = STYLE[kind]
        bold = 2.0 if kind in ("visible", "outline", "highlight") else 1.0
        for pts in by_kind.get(kind, []):
            if dash:
                for seg in _dashed(pts, dash):
                    canvas.line(*seg, colour)
            else:
                for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
                    canvas.line(x0, y0, x1, y1, colour, bold)
    return canvas.png(), scale


def view_direction(view) -> Tuple[Tuple[float, float, float],
                                  Tuple[float, float, float]]:
    """A named view, or a direction to look along, as (direction, up)."""
    from ..core import hlr  # the host has the kernel; the proxy never calls this

    if isinstance(view, str):
        key = view.strip().lower()
        if key == "isometric":
            key = "iso"
        if key not in hlr.ORIENTATIONS:
            from .errors import BridgeError
            raise BridgeError(
                "BAD_VIEW", "unknown view %r" % view,
                ["Use one of: %s, or a direction [x, y, z] to look along."
                 % ", ".join(sorted(hlr.ORIENTATIONS))])
        return hlr.ORIENTATIONS[key]
    d = [float(v) for v in view]
    up = (0.0, 0.0, 1.0)
    if abs(d[2]) > 0.95 * math.sqrt(d[0] ** 2 + d[1] ** 2 + d[2] ** 2):
        up = (0.0, 1.0, 0.0)
    return (d[0], d[1], d[2]), up


def render_shape(shape, view="iso", size=(800, 600), hidden: bool = True,
                 highlight: Optional[Sequence] = None) -> Tuple[bytes, Dict]:
    """A line picture of ``shape`` from ``view``; highlighted sub-shapes
    (edges or faces) are drawn on top in the accent colour."""
    from ..core import hlr, kernel

    direction, up = view_direction(view)
    projection = hlr.project(shape, direction, up, hidden=hidden)
    if projection.error:
        from .errors import BridgeError
        raise BridgeError("RENDER_FAILED", projection.error)
    lines = [(pl.kind, pl.points) for pl in projection.lines]
    if highlight:
        frame = hlr.camera(direction, up)
        cx, cy = projection.centre
        for sub in highlight:
            # an edge explored for edges is itself; a face gives its rim
            for edge in kernel.edges(sub):
                for pts in hlr._flatten_3d(edge):
                    flat = [hlr.to_paper(p, frame) for p in pts]
                    lines.append(("highlight",
                                  [(x - cx, y - cy) for x, y in flat]))
    png, scale = draw(lines, size)
    return png, {"view": view if isinstance(view, str) else list(view),
                 "size": list(size), "px_per_mm": round(scale, 4),
                 "lines": len(lines)}
