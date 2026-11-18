"""Redrawn icons, November 2026: the ones that read badly at toolbar size.

Each is drawn here from scratch on the 24 unit grid in the icon set's
three tones (outline, accent, solid; icons.py swaps them for the dark
scheme), plus the set's green for Finish.  Solids are lit as the rest of
the set is: top face full, left face 7/8, right face half.

    python tools/icons/redraw_2026_11.py          writes them all
    python tools/icons/redraw_2026_11.py sweep    writes the ones named
"""
import math
import os
import sys

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "datum", "ui", "assets", "icons")

LINE, ACCENT, SOLID, GREEN = "#2b3540", "#b9820f", "#7a8693", "#69c26b"
C30, S30 = math.cos(math.radians(30)), 0.5


def iso(x, y, z, ox=12.0, oy=12.0, k=1.0):
    """A point in the icon's isometric: x runs down right, y down left,
    z up."""
    return (ox + (x - y) * C30 * k, oy + (x + y) * S30 * k - z * k)


def pts(points):
    return " ".join("%.3f,%.3f" % p for p in points)


def poly(points, colour, opacity=1.0):
    return ('<polygon points="%s" fill="%s" fill-opacity="%g" />'
            % (pts(points), colour, opacity))


def path(d, colour, width=1.6, dash="", fill="none", opacity=1.0, cap="round"):
    extra = ' stroke-dasharray="%s"' % dash if dash else ""
    return ('<path d="%s" fill="%s" stroke="%s" stroke-width="%g" '
            'stroke-opacity="%g" stroke-linecap="%s" stroke-linejoin="round"%s />'
            % (d, fill, colour, width, opacity, cap, extra))


def box(x, y, z, dx, dy, dz, colour, **kw):
    """An isometric box's three faces we see."""
    P = lambda a, b, c: iso(x + a, y + b, z + c, **kw)  # noqa: E731
    top = [P(0, 0, dz), P(dx, 0, dz), P(dx, dy, dz), P(0, dy, dz)]
    left = [P(0, dy, 0), P(dx, dy, 0), P(dx, dy, dz), P(0, dy, dz)]
    right = [P(dx, 0, 0), P(dx, dy, 0), P(dx, dy, dz), P(dx, 0, dz)]
    return poly(top, colour) + poly(left, colour, 0.875) + \
        poly(right, colour, 0.5)


def svg(*parts):
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
            + "".join(parts) + "</svg>")


def arrow_head(x, y, angle_deg, size=2.6, colour=LINE):
    """A filled head with its tip at (x, y), pointing ``angle_deg``.  Big
    and wide on purpose: at 18 pixels a narrow head is a blob and which
    way the arrow points is lost.  Shafts that meet it are drawn thin."""
    size = max(size * 1.4, 3.4)
    a = math.radians(angle_deg)
    l = (x - size * math.cos(a - 0.62), y - size * math.sin(a - 0.62))
    r = (x - size * math.cos(a + 0.62), y - size * math.sin(a + 0.62))
    return poly([l, (x, y), r], colour)


ICONS = {}


def icon(fn):
    ICONS[fn.__name__] = fn
    return fn


# --------------------------------------------------------- yes and no

@icon
def finish():
    # a clean tick in a ring, the set's green, no filled disc behind it
    return svg(path("M12 3.2a8.8 8.8 0 1 0 0.01 0Z", GREEN, 1.6),
               path("M7.4 12.3l3.2 3.2l6-6.4", GREEN, 2.2))


@icon
def cancel():
    return svg(path("M12 3.2a8.8 8.8 0 1 0 0.01 0Z", LINE, 1.6),
               path("M8.6 8.6l6.8 6.8M15.4 8.6l-6.8 6.8", ACCENT, 2.0))


@icon
def delete():
    # a bin in outline, its lid in the accent, lifted a little
    return svg(path("M6.5 7.5h11l-1 12.2a1.4 1.4 0 0 1 -1.4 1.3h-6.2"
                    "a1.4 1.4 0 0 1 -1.4 -1.3Z", LINE, 1.6),
               path("M10.2 10.8v6.8M13.8 10.8v6.8", SOLID, 1.5),
               path("M4.8 5.4h14.4M9.6 5.2V3.6h4.8v1.6", ACCENT, 1.7))


# ------------------------------------------------------ solid features

@icon
def extrude():
    # a profile on the plane and the solid it makes, pulled up from it
    base = [iso(-6, -3, 0, oy=14), iso(3, -3, 0, oy=14),
            iso(3, 6, 0, oy=14), iso(-6, 6, 0, oy=14)]
    return svg(poly(base, ACCENT, 0.5),
               box(-4.5, -1.5, 0, 6, 6, 7, SOLID, oy=14),
               path("M19.5 14.5V5.4", LINE, 1.2),
               arrow_head(19.5, 3.4, -90))


# revolve and sweep keep their 0.3.9 drawings: the user prefers them


@icon
def emboss():
    slab = box(-7, -7, 0, 14, 14, 2.4, SOLID, oy=13)
    letter = box(-3, -3, 2.4, 6, 6, 3.2, ACCENT, oy=13)
    return svg(slab, letter, path("M19.6 9.4V4.6", LINE, 1.2),
               arrow_head(19.6, 2.8, -90, 2.3))


@icon
def engrave():
    slab = box(-7, -7, 0, 14, 14, 3.6, SOLID, oy=13)
    # the cut into the top: its floor, and the two walls we see inside it
    t = lambda a, b, c: iso(a, b, c, oy=13)  # noqa: E731
    floor = [t(-3, -3, 1.2), t(3, -3, 1.2), t(3, 3, 1.2), t(-3, 3, 1.2)]
    back_l = [t(-3, -3, 3.6), t(-3, 3, 3.6), t(-3, 3, 1.2), t(-3, -3, 1.2)]
    back_r = [t(-3, -3, 3.6), t(3, -3, 3.6), t(3, -3, 1.2), t(-3, -3, 1.2)]
    return svg(slab, poly(back_l, LINE, 0.55), poly(back_r, LINE, 0.35),
               poly(floor, ACCENT), path("M19.6 3.2V8.0", LINE, 1.2),
               arrow_head(19.6, 9.8, 90, 2.3))


@icon
def bodies():
    # two solids, one behind the other, a body each
    return svg(box(-1, -7, 0, 7, 7, 7, SOLID, oy=12.5),
               box(-5.5, 0, 0, 7, 7, 7, ACCENT, oy=12.5))


@icon
def features():
    # the feature tree: a trunk and three features off it
    return svg(path("M5 4V18.5M5 7.5H9.5M5 13H9.5M5 18.5H9.5", LINE, 1.5),
               box(-2, -2, 0, 4, 4, 3, SOLID, ox=13.6, oy=7.2),
               box(-2, -2, 0, 4, 4, 3, ACCENT, ox=13.6, oy=12.7),
               box(-2, -2, 0, 4, 4, 3, SOLID, ox=13.6, oy=18.2),
               path("M17.6 6.4H21M17.6 11.9H21M17.6 17.4H21", SOLID, 1.4))


@icon
def mirror():
    # the plane, a shape on one side and its reflection on the other
    return svg(path("M12 2.6V21.4", LINE, 1.5, dash="2.2 1.6"),
               poly([(9.6, 5), (9.6, 19), (3, 19), (3, 13)], SOLID),
               path("M14.4 5V19H21V13Z", ACCENT, 1.7),
               path("M7.4 3.2C9.4 2.0 12.6 1.8 14.8 2.6", LINE, 1.1),
               arrow_head(16.9, 3.4, 30, 2.0))


# -------------------------------------------------------------- tools

@icon
def measure():
    # a dimension between two witness lines, over a ruler
    ticks = "".join("M%.2f 15.2V%.2f" % (x, 17.4 if i % 2 else 18.4)
                    for i, x in enumerate([4.5 + 1.875 * k for k in range(9)]))
    return svg('<rect x="3" y="14" width="18" height="6" rx="1" fill="%s" '
               'fill-opacity="0.875" />' % SOLID,
               path(ticks, LINE, 1.0),
               path("M3.6 4V11.4M20.4 4V11.4", LINE, 1.3),
               path("M6.4 7.6H17.6", ACCENT, 1.2),
               arrow_head(4.2, 7.6, 180, 2.4, ACCENT),
               arrow_head(19.8, 7.6, 0, 2.4, ACCENT))


@icon
def material():
    # the material ball on its shadow
    return svg('<ellipse cx="12" cy="20" rx="7" ry="1.8" fill="%s" '
               'fill-opacity="0.5" />' % SOLID,
               '<circle cx="12" cy="11.2" r="7.4" fill="%s" />' % ACCENT,
               '<path d="M12 3.8a7.4 7.4 0 0 1 7.4 7.4a7.4 7.4 0 0 1 -7.4 7.4'
               'a5.4 7.4 0 0 0 0 -14.8Z" fill="%s" fill-opacity="0.45" />'
               % LINE,
               '<ellipse cx="9.4" cy="8.2" rx="2" ry="1.3" fill="#ffffff" '
               'fill-opacity="0.55" transform="rotate(-35 9.4 8.2)" />')


@icon
def spacemouse():
    # the puck: a heavy base and the cap on it, the cap's six ways
    return svg('<ellipse cx="12" cy="17.4" rx="8.6" ry="3.4" fill="%s" />'
               % SOLID,
               '<rect x="3.4" y="14" width="17.2" height="3.4" fill="%s" />'
               % SOLID,
               '<ellipse cx="12" cy="14" rx="8.6" ry="3.4" fill="%s" '
               'fill-opacity="0.875" />' % SOLID,
               '<ellipse cx="12" cy="11.6" rx="5" ry="2" fill="%s" />'
               % ACCENT,
               '<rect x="7" y="8.6" width="10" height="3" fill="%s" />'
               % ACCENT,
               '<ellipse cx="12" cy="8.6" rx="5" ry="2" fill="%s" '
               'fill-opacity="0.6" />' % ACCENT,
               path("M12 6.2V3.2", LINE, 1.1), arrow_head(12, 0.6, -90, 1.9))


def _cube_edges(dashed_hidden):
    # an oblique cube, its back set up and right, so the hidden corner
    # sits clear of every edge in sight (in isometric it lands on one)
    f = [(3.5, 8.5), (15.5, 8.5), (15.5, 20.5), (3.5, 20.5)]
    d = (5.0, -5.0)
    b = [(x + d[0], y + d[1]) for x, y in f]

    def seg(p, q):
        return "M%.2f %.2fL%.2f %.2f" % (p + q)
    seen = "".join(seg(f[i], f[(i + 1) % 4]) for i in range(4))
    seen += seg(f[0], b[0]) + seg(f[1], b[1]) + seg(f[2], b[2])
    seen += seg(b[0], b[1]) + seg(b[1], b[2])
    hidden = seg(b[3], b[0]) + seg(b[3], b[2]) + seg(b[3], f[3])
    out = [path(seen, LINE, 1.6)]
    if dashed_hidden:
        out.append(path(hidden, ACCENT, 1.4, dash="1.6 1.4"))
    return out


@icon
def view_visible():
    return svg(*_cube_edges(False))


@icon
def view_hidden():
    return svg(*_cube_edges(True))


# ------------------------------------------------- assembly constraints
#
# Side views, two parts and one sign each: the first part grey, the
# second in the accent.  They sit in the Place Constraint window's Type
# row at 18 pixels, where an isometric pair of blocks is a smudge; and
# once, borrowed from the sketch set, Insert read as concentric and Flush
# as parallel (r/AutodeskInventor).  Each here says what happens to two
# solids.

def face_arrow(x, y_from, y_to, colour):
    """A face's direction, up or down the icon: a thin shaft and a big
    wide head, so which way it points is plain at 18 pixels."""
    down = y_to > y_from
    head_len, half = 4.4, 2.9
    base = y_to - head_len if down else y_to + head_len
    return (path("M%g %gV%g" % (x, y_from, base), colour, 1.3, cap="butt")
            + poly([(x - half, base), (x + half, base), (x, y_to)], colour))


def rect(x0, y0, x1, y1, colour, opacity=1.0, r=0.8):
    return ('<rect x="%g" y="%g" width="%g" height="%g" rx="%g" fill="%s" '
            'fill-opacity="%g" />' % (x0, y0, x1 - x0, y1 - y0, r, colour,
                                      opacity))


@icon
def c3d_mate():
    # face to face: each face's arrow points at the other's, as Inventor
    # draws a mate, the first's dark, the second's in its accent
    return svg(rect(2.5, 17.5, 21.5, 21.5, SOLID),
               rect(2.5, 2.5, 21.5, 6.5, ACCENT),
               face_arrow(7, 6.5, 16, ACCENT),
               face_arrow(17, 17.5, 8, LINE))


@icon
def c3d_flush():
    # side by side, their faces on one plane and turned the same way: both
    # arrows up
    return svg(rect(2.5, 12, 10.8, 21.5, SOLID),
               rect(13.2, 12, 21.5, 19, ACCENT),
               path("M0.8 12H23.2", LINE, 1.1, dash="1.8 1.2"),
               face_arrow(6.6, 11.4, 1.6, LINE),
               face_arrow(17.4, 11.4, 1.6, ACCENT))


@icon
def c3d_angle():
    # a plate swung up off the other, the angle between them
    a = math.radians(38)
    x0, y0, L = 3.0, 16.5, 17.0
    tip = (x0 + L * math.cos(a), y0 - L * math.sin(a))
    n = (math.sin(a) * 3.2, math.cos(a) * 3.2)
    flap = [(x0, y0), tip, (tip[0] - n[0], tip[1] - n[1]),
            (x0 - n[0], y0 - n[1])]
    # the arc between the two, round the hinge, stopping short of the flap
    r, end = 11.0, math.radians(28)
    ex, ey = x0 + r * math.cos(end), y0 - r * math.sin(end)
    head = math.degrees(math.atan2(-math.cos(end), -math.sin(end)))
    return svg(rect(2.5, 16.5, 21.5, 21, SOLID),
               poly(flap, ACCENT),
               path("M%.2f %.2fA%g %g 0 0 0 %.2f %.2f"
                    % (x0 + r, y0 - 0.2, r, r, ex, ey), LINE, 1.2),
               arrow_head(ex - 0.5 * math.sin(end), ey - 0.5 * math.cos(end),
                          head, 2.4))


@icon
def c3d_tangent():
    # a round resting on a flat, touching along one line
    return svg(rect(2.5, 16.4, 21.5, 21.5, SOLID),
               '<circle cx="12" cy="10" r="6.4" fill="%s" />' % ACCENT,
               '<circle cx="12" cy="16.4" r="1.5" fill="%s" />' % LINE)


@icon
def c3d_insert():
    # a bolt going into a hole, the two cut through on one axis
    # the axis shows only below, out of the hole: through the bolt it
    # made a cross
    return svg(rect(2.5, 12.5, 9.6, 20.5, SOLID, r=0.6),
               rect(14.4, 12.5, 21.5, 20.5, SOLID, r=0.6),
               rect(10.4, 6.5, 13.6, 16.5, ACCENT, r=0.4),
               rect(6.8, 2.8, 17.2, 6.8, ACCENT, r=0.8),
               path("M12 18V23.4", LINE, 1.4, dash="1.6 1.2"))


@icon
def c3d_parallel():
    # one above the other, the same gap all along
    # two plates, the second shifted along and lifted clear: faces turned
    # the same way, any distance apart
    return svg(rect(2.5, 15.5, 18, 20.5, SOLID),
               rect(6, 4.5, 21.5, 9.5, ACCENT),
               path("M11 10.8V14.2", LINE, 1.5, dash="1.2 1.0"),
               path("M16.5 10.8V14.2", LINE, 1.5, dash="1.2 1.0"))


@icon
def c3d_symmetry():
    # one either side of the plane, as far from it each
    return svg(path("M12 1V23", LINE, 1.6, dash="2.2 1.4"),
               rect(2.5, 7, 9, 17, SOLID),
               rect(15, 7, 21.5, 17, ACCENT))


# ----------------------------------------------------------------- CAM

@icon
def cam_sheet():
    # Sheet and Tool: the stock plate, the cutter over it and the path it
    # cuts, part of the outline cut already
    t = lambda a, b, c: iso(a, b, c, oy=15.5)  # noqa: E731
    plate = box(-8, -7, 0, 16, 14, 1.6, SOLID, oy=15.5)
    cut = [t(-4.5, -3.5, 1.6), t(3.5, -3.5, 1.6), t(3.5, 4, 1.6),
           t(-4.5, 4, 1.6)]
    done = "M%.2f %.2fL%.2f %.2fL%.2f %.2f" % (cut[3] + cut[0] + cut[1])
    todo = "M%.2f %.2fL%.2f %.2fL%.2f %.2f" % (cut[1] + cut[2] + cut[3])
    tip = cut[1]
    head = [(tip[0] - 2.2, tip[1] - 9.4), (tip[0] + 2.2, tip[1] - 9.4),
            (tip[0] + 2.2, tip[1] - 5.2), (tip[0] + 0.9, tip[1] - 2.2),
            (tip[0] - 0.9, tip[1] - 2.2), (tip[0] - 2.2, tip[1] - 5.2)]
    return svg(plate,
               path(done, ACCENT, 1.8),
               path(todo, ACCENT, 1.4, dash="1.5 1.4"),
               poly(head, LINE),
               path("M%.2f %.2fL%.2f %.2f" % (tip[0], tip[1] - 2.0,
                                               tip[0], tip[1] - 0.3),
                    ACCENT, 1.4))


# -------------------------------------------------------------- piping

@icon
def pipe_insert():
    # a copper run bent round a corner, its skeleton line under it
    return svg(path("M4 21V11a6 6 0 0 1 6 -6H21", LINE, 1.0, dash="1.6 1.4"),
               path("M4 21V11a6 6 0 0 1 6 -6H21", ACCENT, 4.2, cap="butt"),
               path("M4 21V11a6 6 0 0 1 6 -6H21", "#ffffff", 1.0,
                    opacity=0.35, cap="butt"))


@icon
def pipe_corners():
    # an elbow fitting with its two sockets, and the choice beside it
    return svg(path("M5 21V12a4 4 0 0 1 4 -4H17", ACCENT, 3.6, cap="butt"),
               path("M5 17.4V20.4M13.4 8H16.4", LINE, 5.4, cap="butt",
                    opacity=0.85),
               poly([(16.4, 15.6), (21.6, 15.6), (19, 18.8)], LINE))


@icon
def pipe_cutlist():
    # a length of tube with its cut length over it, the list under
    return svg(path("M6.2 4.6V9.4M17.8 4.6V9.4", LINE, 1.2),
               path("M8.6 7H15.4", ACCENT, 1.1),
               arrow_head(6.8, 7, 180, 2.0, ACCENT),
               arrow_head(17.2, 7, 0, 2.0, ACCENT),
               path("M5 12.4H19", ACCENT, 3.6, cap="butt"),
               path("M5 16.6H19M5 20H15", SOLID, 1.6))


def main(names):
    for name in names or sorted(ICONS):
        with open(os.path.join(OUT, name + ".svg"), "w",
                  encoding="utf-8", newline="\n") as fp:
            fp.write(ICONS[name]())
        print("wrote", name)


if __name__ == "__main__":
    main(sys.argv[1:])
