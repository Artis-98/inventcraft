"""Shaded pictures of a model, made without a screen.

``render`` draws the lines of a hidden line removal, which is what to read
an edge off. What something looks like (a flat spot in a loft, a part in
the wrong colour, a window floating off its body) only shows shaded. So
the model is meshed and drawn here by a small numpy rasteriser: a depth
buffer, a normal per pixel, the part's own appearance, outlines found in
the picture itself, see-through parts laid over what is behind, and a
section plane. No Qt and no graphics card, so it works in a headless host.
"""

from __future__ import annotations

import math
import struct
import zlib
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from OCP.BRep import BRep_Tool
from OCP.BRepBuilderAPI import BRepBuilderAPI_Copy
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.TopAbs import TopAbs_REVERSED
from OCP.TopLoc import TopLoc_Location
from OCP.TopoDS import TopoDS

from ..core import hlr, kernel
from .errors import BridgeError

SKY = ((246, 248, 251), (212, 219, 228))        # top and bottom of the picture
CUT_FACE = np.array((214, 92, 70), float) / 255.0
HIGHLIGHT = "#e66e14"
EDGE = 0.42             # what an outline leaves of the colour under it
FRAGMENTS = 2_000_000   # drawn at a time, to bound the memory
LAYERS = 24             # see-through parts drawn one by one, at most


def _unit(v: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(v, axis=-1, keepdims=True)
    return v / np.where(n < 1e-12, 1.0, n)


def mesh(shape, deflection: float, angle: float = 0.3):
    """Triangles of a copy: (points, normals, triangles wound outwards)."""
    work = BRepBuilderAPI_Copy(shape, True, False).Shape()
    BRepMesh_IncrementalMesh(work, max(deflection, 1e-4), False, angle, True)
    all_p: List[np.ndarray] = []
    all_n: List[np.ndarray] = []
    all_t: List[np.ndarray] = []
    base = 0
    for face in kernel.explore(work, kernel.TopAbs_FACE):
        loc = TopLoc_Location()
        net = BRep_Tool.Triangulation_s(TopoDS.Face_s(face), loc)
        if net is None or not net.NbTriangles():
            continue
        move = loc.Transformation()
        pts = np.array([
            (q.X(), q.Y(), q.Z()) for q in
            (net.Node(i).Transformed(move)
             for i in range(1, net.NbNodes() + 1))])
        tri = np.array([net.Triangle(i).Get()
                        for i in range(1, net.NbTriangles() + 1)],
                       dtype=np.int64) - 1
        if (face.Orientation() == TopAbs_REVERSED) != move.IsNegative():
            tri = tri[:, [0, 2, 1]]
        flat = np.cross(pts[tri[:, 1]] - pts[tri[:, 0]],
                        pts[tri[:, 2]] - pts[tri[:, 0]])
        normals = np.zeros_like(pts)
        for k in range(3):
            # Max's weights: right on a sphere however thin the triangles,
            # which a loft's are, and by area alone they came out mottled
            out = pts[tri[:, (k + 1) % 3]] - pts[tri[:, k]]
            back = pts[tri[:, (k + 2) % 3]] - pts[tri[:, k]]
            spread = (out * out).sum(axis=1) * (back * back).sum(axis=1)
            np.add.at(normals, tri[:, k],
                      flat / np.maximum(spread, 1e-24)[:, None])
        all_p.append(pts)
        all_n.append(_unit(normals))
        all_t.append(tri + base)
        base += len(pts)
    if not all_p:
        return None
    return np.vstack(all_p), np.vstack(all_n), np.vstack(all_t)


class Buffer:
    """What is nearest at each pixel: depth, normal, whose, and whether
    it is the inside of something cut open."""

    def __init__(self, width: int, height: int) -> None:
        self.w, self.h = width, height
        count = width * height
        self.depth = np.full(count, -np.inf, np.float32)
        self.normal = np.zeros((count, 3), np.float32)
        self.who = np.full(count, -1, np.int32)
        self.inside = np.zeros(count, bool)
        # how many more backs than fronts a ray meets: for capping a cut
        self.turns: Optional[np.ndarray] = None

    def draw(self, xyz: np.ndarray, normals: np.ndarray, tri: np.ndarray,
             who: int, clip: Optional[np.ndarray] = None,
             behind: Optional["Buffer"] = None, lift: float = 0.0) -> None:
        """Triangles in pixels (x, y down, z towards the viewer).

        ``clip`` is how far each point is past the section plane. Only
        what is in front of ``behind`` is drawn."""
        a, b, c = xyz[tri[:, 0]], xyz[tri[:, 1]], xyz[tri[:, 2]]
        low = np.minimum(np.minimum(a, b), c)
        high = np.maximum(np.maximum(a, b), c)
        first = np.maximum(np.ceil(low[:, 1] - 0.5), 0).astype(np.int64)
        # half open, so two triangles never both own a pixel on their edge
        last = np.minimum(np.ceil(high[:, 1] - 0.5) - 1,
                          self.h - 1).astype(np.int64)
        area = ((b[:, 0] - a[:, 0]) * (c[:, 1] - a[:, 1])
                - (b[:, 1] - a[:, 1]) * (c[:, 0] - a[:, 0]))
        keep = np.nonzero((last >= first) & (np.abs(area) > 1e-12)
                          & (high[:, 0] >= 0) & (low[:, 0] < self.w))[0]
        if not len(keep):
            return
        rows = last[keep] - first[keep] + 1
        across = np.minimum(high[keep, 0] - low[keep, 0], self.w) + 1.0
        load = np.cumsum(rows * across)
        marks = np.searchsorted(
            load, np.arange(FRAGMENTS, load[-1], FRAGMENTS))
        for part in np.split(keep, np.unique(marks)):
            if len(part):
                self._fill(a[part], b[part], c[part], area[part],
                           first[part], last[part] - first[part] + 1,
                           normals, tri[part], who, clip, behind, lift)

    def _fill(self, a, b, c, area, first, rows, normals, tri, who, clip,
              behind, lift) -> None:
        # a span per row of each triangle, from its three edges
        t = np.repeat(np.arange(len(a)), rows)
        step = np.arange(len(t)) - np.repeat(np.cumsum(rows) - rows, rows)
        row = first[t] + step
        y = row + 0.5
        left = np.full(len(t), -0.5)
        right = np.full(len(t), self.w + 0.5)
        sign = np.sign(area)[t]
        for p, q in ((a, b), (b, c), (c, a)):
            dx, dy = (q[t, 0] - p[t, 0]) * sign, (q[t, 1] - p[t, 1]) * sign
            # inside is dx * (y - py) - dy * (x - px) >= 0
            room = dx * (y - p[t, 1])
            with np.errstate(divide="ignore", invalid="ignore"):
                at = p[t, 0] + room / dy
            up, down = dy > 0, dy < 0
            right[up] = np.minimum(right[up], at[up])
            left[down] = np.maximum(left[down], at[down])
            right[(dy == 0) & (room < 0)] = -1.0
        start = np.maximum(np.ceil(left - 0.5), 0)
        stop = np.minimum(np.ceil(right - 0.5) - 1, self.w - 1)
        count = np.maximum(stop - start + 1, 0).astype(np.int64)
        if not count.sum():
            return
        span = np.repeat(np.arange(len(t)), count)
        x = (start[span].astype(np.int64) + np.arange(len(span))
             - np.repeat(np.cumsum(count) - count, count))
        t, row = t[span], row[span]
        px, py = x + 0.5, row + 0.5
        u = ((b[t, 0] - px) * (c[t, 1] - py)
             - (b[t, 1] - py) * (c[t, 0] - px)) / area[t]
        v = ((c[t, 0] - px) * (a[t, 1] - py)
             - (c[t, 1] - py) * (a[t, 0] - px)) / area[t]
        w = 1.0 - u - v
        depth = u * a[t, 2] + v * b[t, 2] + w * c[t, 2] + lift
        pixel = row * self.w + x
        good = depth > self.depth[pixel]
        if behind is not None:
            good &= depth > behind.depth[pixel]
        if clip is not None:
            past = (u * clip[tri[t, 0]] + v * clip[tri[t, 1]]
                    + w * clip[tri[t, 2]])
            kept = past <= 0
            good &= kept
            if self.turns is not None:
                facing = np.where(area[t[kept]] > 0, 1, -1)
                self.turns += np.bincount(
                    pixel[kept], facing, len(self.turns)).astype(np.int16)
        pick = np.nonzero(good)[0]
        if not len(pick):
            return
        order = np.lexsort((-depth[pick], pixel[pick]))
        pick = pick[order]
        at = pixel[pick]
        head = np.concatenate(([True], at[1:] != at[:-1]))
        pick, at = pick[head], at[head]
        t = t[pick]
        self.depth[at] = depth[pick]
        self.normal[at] = (u[pick, None] * normals[tri[t, 0]]
                           + v[pick, None] * normals[tri[t, 1]]
                           + w[pick, None] * normals[tri[t, 2]])
        self.who[at] = who
        self.inside[at] = False

    def cap(self, depth: np.ndarray, normal: np.ndarray, who: int) -> None:
        """Close what the section cut open: where a ray reaches the plane
        inside a solid, the plane is what is seen."""
        at = np.nonzero((self.turns > 0) & (depth > self.depth))[0]
        self.depth[at] = depth[at]
        self.normal[at] = normal
        self.who[at] = who
        self.inside[at] = True
        self.turns[:] = 0


def light(normal: np.ndarray, looks: np.ndarray, who: np.ndarray,
          up: np.ndarray) -> np.ndarray:
    """Colour per pixel, from normals as the camera sees them."""
    n = _unit(normal.astype(np.float64))
    n[n[:, 2] < 0] *= -1.0              # both sides of a face are lit
    base, rough, metal = looks[who, :3], looks[who, 3], looks[who, 4]
    key = _unit(np.array((-0.45, 0.7, 0.65)))
    fill = _unit(np.array((0.75, 0.05, 0.6)))
    rim = _unit(np.array((0.2, -0.8, 0.3)))
    sky = 0.5 + 0.5 * n.dot(up)
    lit = (0.22 + 0.2 * sky + 0.5 * np.clip(n.dot(key), 0, 1)
           + 0.2 * np.clip(n.dot(fill), 0, 1)
           + 0.07 * np.clip(n.dot(rim), 0, 1))
    half = _unit(key + np.array((0.0, 0.0, 1.0)))
    sharp = 6.0 + 110.0 * (1.0 - rough) ** 2
    shine = np.clip(n.dot(half), 0, 1) ** sharp * (0.08 + 0.38 * (1 - rough))
    edge_on = (1.0 - n[:, 2]) ** 4 * 0.1 * (1 - rough)
    tint = np.where(metal[:, None] > 0.5, 0.45 + 0.55 * base, 1.0)
    return np.clip(base * lit[:, None]
                   + tint * (shine + edge_on)[:, None], 0.0, 1.0)


def outlines(buf: Buffer, pixel: float) -> np.ndarray:
    """Where the picture has an edge: a silhouette, a crease or a step."""
    who = buf.who.reshape(buf.h, buf.w)
    depth = np.where(np.isfinite(buf.depth), buf.depth,
                     0.0).reshape(buf.h, buf.w)
    normal = _unit(buf.normal).reshape(buf.h, buf.w, 3)
    seen = who >= 0
    out = np.zeros(who.shape, bool)
    for axis in (0, 1):
        a = [slice(None), slice(None)]
        b = [slice(None), slice(None)]
        a[axis], b[axis] = slice(None, -1), slice(1, None)
        a, b = tuple(a), tuple(b)
        both = seen[a] & seen[b]
        other = who[a] != who[b]
        crease = both & (np.abs((normal[a] * normal[b]).sum(axis=-1)) < 0.86)
        # further apart than the slope of either face explains
        slope = np.minimum(np.abs(normal[a][..., 2]),
                           np.abs(normal[b][..., 2]))
        jump = both & (np.abs(depth[a] - depth[b])
                       > pixel * (3.0 + 2.5 / np.maximum(slope, 0.06)))
        out[a] |= other | crease | jump
    return out.ravel()


def png(image: np.ndarray) -> bytes:
    height, width, _ = image.shape
    moved = image.copy()
    moved[:, 1:] = image[:, 1:] - image[:, :-1]     # the "sub" filter
    raw = np.hstack((np.ones((height, 1), np.uint8),
                     moved.reshape(height, width * 3))).tobytes()

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
            + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


def section_plane(spec: Any, towards: np.ndarray
                  ) -> Tuple[np.ndarray, float]:
    """(normal, distance): what is further along the normal is taken away,
    which is the half towards the viewer unless flipped."""
    if isinstance(spec, str):
        spec = {"plane": spec}
    if not isinstance(spec, dict) or (set(spec) - {
            "plane", "offset", "origin", "normal", "flip"}):
        raise BridgeError(
            "BAD_VALUE", "a section is a plane to cut at, not %r" % (spec,),
            ['"XZ", {"plane": "YZ", "offset": 120}, or {"origin": [x,y,z], '
             '"normal": [x,y,z]}; "flip": true keeps the other half.'])
    named = {"XY": (0, 0, 1), "XZ": (0, 1, 0), "YZ": (1, 0, 0)}
    normal = spec.get("normal", named.get(str(spec.get("plane", "")).upper()))
    if normal is None:
        raise BridgeError("BAD_VALUE", "a section needs plane (XY, XZ or "
                          "YZ) or a normal")
    n = np.asarray(normal, float)
    origin = np.asarray(spec.get("origin", (0, 0, 0)), float)
    if (n.shape != (3,) or origin.shape != (3,)
            or np.linalg.norm(n) < 1e-9):
        raise BridgeError("BAD_VALUE", "a section's origin and normal are "
                          "[x, y, z], and the normal has a length")
    n = _unit(n)
    at = float(origin.dot(n)) + float(spec.get("offset", 0.0))
    if (n.dot(towards) < 0) != bool(spec.get("flip")):
        n, at = -n, -at
    return n, at


def render_items(items: Sequence[Dict[str, Any]], direction, up,
                 size: Tuple[int, int] = (800, 600), edges: bool = True,
                 section: Any = None, highlight: Optional[Sequence] = None,
                 focus: Optional[Sequence[float]] = None
                 ) -> Tuple[bytes, Dict[str, Any]]:
    """``items`` are {shape, look} (a materials.Appearance); ``focus`` is a
    box [x0, y0, z0, x1, y1, z1] to fill the picture with."""
    width, height = size
    over = 2 if width * height <= 2_200_000 else 1
    w, h = width * over, height * over
    frame = hlr.camera(direction, up)
    axes = [frame.XDirection(), frame.YDirection(), frame.Direction()]
    cam = np.array([(d.X(), d.Y(), d.Z()) for d in axes])
    if not items:
        raise BridgeError("NO_BODY", "there is nothing to draw yet")

    def flat(box) -> np.ndarray:
        return np.array([(box[i], box[1 + j], box[2 + k]) for i in (0, 3)
                         for j in (0, 3) for k in (0, 3)]).dot(cam.T)

    def fit(points: np.ndarray) -> Tuple[float, np.ndarray]:
        low, high = points[:, :2].min(axis=0), points[:, :2].max(axis=0)
        room = 1.0 - 2 * 0.035
        scale = min(w * room / max(high[0] - low[0], 1e-6),
                    h * room / max(high[1] - low[1], 1e-6))
        return float(scale), (low + high) / 2.0

    boxes = [kernel.bounding_box(it["shape"]) for it in items]
    rough_scale, rough_middle = fit(flat(focus) if focus is not None
                                    else np.vstack([flat(b) for b in boxes]))
    sag = 0.35 * over / rough_scale     # about a third of a pixel
    meshes = []
    window = np.array((w, h), float) / 2.0 / rough_scale
    for it, box in zip(items, boxes):
        if focus is not None:
            corners = flat(box)[:, :2] - rough_middle
            if ((corners.min(axis=0) > window).any()
                    or (corners.max(axis=0) < -window).any()):
                continue            # wholly outside what was zoomed to
        # never coarser than a small part needs to look round
        own = max(math.dist(box[:3], box[3:]) * 4e-3, 1e-3)
        got = mesh(it["shape"], min(sag, own))
        if got is not None:
            meshes.append((it["look"], got, 0.0))
    if not meshes:
        raise BridgeError("RENDER_FAILED", "nothing in the model would mesh")
    flats = [got[0].dot(cam.T) for _look, got, _lift in meshes]
    scale, middle = fit(flat(focus) if focus is not None
                        else np.vstack(flats))

    lit_edges = []
    if highlight:
        from ..core import materials
        orange = materials.Appearance(name="highlight", colour=HIGHLIGHT)
        for sub in highlight:
            if kernel.explore(sub, kernel.TopAbs_FACE):
                got = mesh(sub, sag)
                if got is not None:
                    meshes.append((orange, got, 2.0 * over / scale))
                    flats.append(got[0].dot(cam.T))
            else:
                for edge in kernel.edges(sub):
                    lit_edges += list(hlr._flatten_3d(edge))

    cut = None
    if section:
        cut = section_plane(section, cam[2])
    looks = np.array([
        [int(look.colour[i:i + 2], 16) / 255.0 for i in (1, 3, 5)]
        + [look.roughness, float(look.metallic)]
        for look, _got, _lift in meshes])
    solid = Buffer(w, h)
    plane = None
    if cut:
        facing = cut[0].dot(cam.T)
        if facing[2] > 1e-3:        # the open side is towards the viewer
            solid.turns = np.zeros(w * h, np.int16)
            xs = (np.arange(w) + 0.5 - w / 2.0) / scale + middle[0]
            ys = (h / 2.0 - np.arange(h) - 0.5) / scale + middle[1]
            plane = ((cut[1] - facing[0] * xs[None, :]
                      - facing[1] * ys[:, None]) / facing[2]
                     ).astype(np.float32).ravel()
    glass = []
    for who, ((look, (pts, normals, tri), lift), p) in enumerate(
            zip(meshes, flats)):
        xyz = np.column_stack(((p[:, 0] - middle[0]) * scale + w / 2.0,
                               h / 2.0 - (p[:, 1] - middle[1]) * scale,
                               p[:, 2]))
        job = (xyz, normals.dot(cam.T), tri, who,
               pts.dot(cut[0]) - cut[1] if cut else None)
        if look.opacity < 0.995:
            glass.append((float(p[:, 2].mean()), look.opacity, lift, job))
        else:
            solid.draw(*job, lift=lift)
            if plane is not None:
                solid.cap(plane, facing, who)

    down = np.linspace(0.0, 1.0, h)[:, None]
    top, bottom = (np.array(c, float) / 255.0 for c in SKY)
    image = np.repeat(top * (1 - down) + bottom * down, w, axis=0)
    world_up = cam[:, 2]
    seen = np.nonzero(solid.who >= 0)[0]
    if len(seen):
        image[seen] = light(solid.normal[seen], looks, solid.who[seen],
                            world_up)
        if cut:
            shown = seen[solid.inside[seen]]
            stripe = ((shown % w + shown // w) // (4 * over)) % 2
            image[shown] = CUT_FACE * (1.0 - 0.14 * stripe)[:, None]
        if edges:
            image[outlines(solid, 1.0 / scale)] *= EDGE

    # see-through parts, the furthest first
    glass.sort(key=lambda g: g[0])
    for n, (_z, opacity, lift, job) in enumerate(glass[-LAYERS:]):
        layer = Buffer(w, h)
        layer.draw(*job, behind=solid, lift=lift)
        at = np.nonzero(layer.who >= 0)[0]
        if len(at):
            colour = light(layer.normal[at], looks, layer.who[at], world_up)
            a = max(float(opacity), 0.12)
            image[at] = image[at] * (1 - a) + colour * a
            if edges:
                image[outlines(layer, 1.0 / scale)] *= 0.8

    paint = np.array([int(HIGHLIGHT[i:i + 2], 16) / 255.0 for i in (1, 3, 5)])
    for line in lit_edges:
        p = np.asarray(line, float).dot(cam.T)
        sx = (p[:, 0] - middle[0]) * scale + w / 2.0
        sy = h / 2.0 - (p[:, 1] - middle[1]) * scale
        for i in range(len(p) - 1):
            steps = int(min(math.hypot(sx[i + 1] - sx[i],
                                       sy[i + 1] - sy[i]), 4 * (w + h))) + 2
            xs = np.linspace(sx[i], sx[i + 1], steps).astype(np.int64)
            ys = np.linspace(sy[i], sy[i + 1], steps).astype(np.int64)
            for ox in range(-over, over + 1):
                for oy in range(-over, over + 1):
                    x, y = xs + ox, ys + oy
                    on = (x >= 0) & (x < w) & (y >= 0) & (y < h)
                    image[y[on] * w + x[on]] = paint

    picture = image.reshape(h, w, 3)
    if over > 1:
        picture = picture.reshape(height, over, width, over, 3).mean(
            axis=(1, 3))
    info = {"size": list(size), "px_per_mm": round(scale / over, 4),
            "triangles": int(sum(len(g[2]) for _l, g, _x in meshes)),
            "items": len(items)}
    if len(glass) > LAYERS:
        info["see_through_not_drawn"] = len(glass) - LAYERS
    return png((picture * 255.0 + 0.5).clip(0, 255).astype(np.uint8)), info
