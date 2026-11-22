"""Freeform shapes measure true, splines go through their points, and a
loft is a solid or an error.

* volume, area and centre against answers known exactly;
* interpolated splines: through the points, flat, closed with no corner;
* a file from before keeps its fitted curve, unless that will not lie flat;
* the airfoils that used to loft into open skins.
"""
import math
import os
import sys

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(errors="replace")
    except Exception:
        pass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from OCP.BRepAdaptor import BRepAdaptor_Curve               # noqa: E402
from OCP.BRepBuilderAPI import BRepBuilderAPI_GTransform    # noqa: E402
from OCP.BRepCheck import BRepCheck_Analyzer                # noqa: E402
from OCP.gp import gp_GTrsf, gp_Mat, gp_Pnt, gp_XYZ         # noqa: E402

from datum.core import kernel                               # noqa: E402
from datum.core.sketch import Entity, Sketch, SketchPlane   # noqa: E402

FAILS = []


def check(name, cond, extra=""):
    print(("  PASS  " if cond else "  FAIL  ") + name
          + (("  " + str(extra)) if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


def close(a, b, rel):
    return abs(a - b) <= rel * abs(b)


def airfoil(n, chord, thick=0.12):
    xs = [(1 - math.cos(math.pi * i / (n - 1))) / 2 for i in range(n)]

    def half(x):
        return 5 * thick * (0.2969 * math.sqrt(x) - 0.126 * x - 0.3516 * x * x
                            + 0.2843 * x ** 3 - 0.1015 * x ** 4)
    upper = [(chord * x, chord * half(x)) for x in reversed(xs)]
    return upper + [(chord * x, -chord * half(x)) for x in xs[1:]]


def section(n, chord, z, thick=0.12):
    s = Sketch(SketchPlane(origin=(0.0, 0.0, z)), "section")
    pts = airfoil(n, chord, thick)
    sid = s.add_spline(pts)
    line = s.add_line(pts[-1], pts[0])
    ends = s.entities[sid].points
    s.entities[line].points = [ends[-1], ends[0]]
    return s, sid


def outline_area(sketch, eid):
    """By the shoelace rule along the real curve: the truth to test by."""
    c = BRepAdaptor_Curve(kernel._sketch_edge(sketch, eid))
    a, b = c.FirstParameter(), c.LastParameter()
    n = 20000
    pts = [c.Value(a + (b - a) * i / n) for i in range(n + 1)]
    return abs(sum(p.X() * q.Y() - q.X() * p.Y()
                   for p, q in zip(pts, pts[1:] + pts[:1]))) / 2


print("volume, area and centre of freeform solids")
for n in (9, 17, 21, 27, 41):
    s, sid = section(n, 80.0, 0.0)
    truth = outline_area(s, sid)
    profile = kernel.sketch_profile(s)
    check("a %d point airfoil's area is the area inside its curve" % n,
          close(kernel.surface_area(profile), truth, 2e-3),
          (kernel.surface_area(profile), truth))
    solid = kernel.extrude(profile, (0, 0, 1), 30.0)
    vol, centre = kernel.volume_and_centre(solid)
    check("extruded, its volume is that area by the length",
          close(vol, truth * 30.0, 5e-5), (vol, truth * 30.0))
    check("and volume() says the same", close(kernel.volume(solid), vol, 1e-6))
    check("its centre is half way along, inside it",
          abs(centre[2] - 15.0) < 0.05 and abs(centre[1]) < 0.1
          and 25 < centre[0] < 45, centre)

s, sid = section(27, 80.0, 0.0)
truth = outline_area(s, sid)
profile = kernel.sketch_profile(s)
out = kernel.volume_and_centre(kernel.extrude(profile, (0, 0, 1), 1.0))[1][0]
ring = kernel.revolve(profile, (-50, 0, 0), (0, 1, 0), 360.0)
check("revolved, Pappus gives its volume",
      close(kernel.volume(ring), 2 * math.pi * (50 + out) * truth, 1e-4),
      (kernel.volume(ring), 2 * math.pi * (50 + out) * truth))

a, b = section(21, 220.0, 0.0), section(21, 60.0, 400.0)
wing = kernel.loft([kernel.sketch_profile(a[0]), kernel.sketch_profile(b[0])],
                   True, True)
A, B = outline_area(*a), outline_area(*b)
truth = 400.0 / 3 * (A + B + math.sqrt(A * B))
check("a tapered wing is a frustum of its sections",
      close(kernel.volume(wing), truth, 1e-3), (kernel.volume(wing), truth))

matrix = gp_Mat(3, 0, 0, 0, 2, 0, 0, 0, 0.5)
stretched = BRepBuilderAPI_GTransform(
    kernel.sphere(10.0), gp_GTrsf(matrix, gp_XYZ(40, 0, 0)), True).Shape()
vol, centre = kernel.volume_and_centre(stretched)
truth = 4 / 3 * math.pi * 30 * 20 * 5
check("a spline ellipsoid is 4/3 pi a b c", close(vol, truth, 3e-3),
      (vol, truth))
check("centred where it was moved to",
      math.dist(centre, (40, 0, 0)) < 0.05, centre)
box = kernel.box(10, 20, 30, (0, 0, 0), False)
check("a box still measures exactly",
      abs(kernel.volume(box) - 6000) < 1e-9
      and abs(kernel.total_area(box) - 2200) < 1e-9)
both = kernel.compound([box, stretched])
check("a compound is the sum of its pieces",
      close(kernel.volume(both), 6000 + truth, 3e-3))

print("splines")
s = Sketch(SketchPlane(), "s")
pts = [(0, 0), (10, 8), (20, -3), (30, 6), (40, 0), (55, 2), (60, -9)]
sid = s.add_spline(pts)
edge = kernel._sketch_edge(s, sid)
off = max(kernel.distance_to_point(edge, (x, y, 0.0)) for x, y in pts)
check("a spline goes exactly through its points", off < 1e-6, off)
check("it is saved saying so",
      Entity.from_dict(s.entities[sid].to_dict()).fit == "through")
check("a line's saved form is unchanged",
      "fit" not in Entity(1, "line", [1, 2]).to_dict())
ring = Sketch(SketchPlane(), "ring")
rid = ring.add_spline([(30 * math.cos(math.pi * i / 4),
                        20 * math.sin(math.pi * i / 4)) for i in range(8)],
                      closed=True)
edge = BRepAdaptor_Curve(kernel._sketch_edge(ring, rid))
check("a closed spline comes back with no corner",
      edge.IsClosed() and edge.DN(edge.FirstParameter(), 1).Angle(
          edge.DN(edge.LastParameter(), 1)) < 1e-6)
faces = kernel.sketch_faces(ring)
check("it is a profile on its own", len(faces) == 1 and close(
    kernel.surface_area(faces[0]), math.pi * 30 * 20, 0.01))
check("and one clickable region", len(kernel.sketch_regions(ring)) == 1)
old, oid = section(21, 80.0, 0.0)
old.entities[oid].fit = ""
check("a spline from an older file still keeps a good fitted curve",
      BRepCheck_Analyzer(kernel.sketch_profile(old)).IsValid()
      and kernel.distance_to_point(
          kernel._sketch_edge(old, oid),
          old.plane.to_3d(*airfoil(21, 80.0)[10])) < 0.2)
off = 0.0
for n in (25, 27, 31, 33):
    tilted = Sketch(SketchPlane(origin=(0, 37.3, 0), normal=(0, -1, 0),
                                xdir=(1, 0, 0)), "tilted")
    tid = tilted.add_spline(airfoil(n, 220.0))
    tilted.entities[tid].fit = ""
    c = BRepAdaptor_Curve(kernel._sketch_edge(tilted, tid))
    a, b = c.FirstParameter(), c.LastParameter()
    off = max(off, max(abs(c.Value(a + (b - a) * i / 300).Y() - 37.3)
                       for i in range(301)))
check("an older one that left its plane is put back on it", off < 1e-3, off)

print("loose ends that meet")
for order in ("line first", "spline first"):
    s = Sketch(SketchPlane(), "mixed")
    draw = [lambda: s.add_line((40, 0), (0, 0), weld=False),
            lambda: s.add_spline([(0, 0), (10, 9), (30, 12), (40, 0)])]
    for one in (draw if order == "line first" else draw[::-1]):
        one()
    check("a spline and a line that meet are a profile, %s" % order,
          len(kernel.sketch_faces(s)) == 1)
s = Sketch(SketchPlane(), "touching")
s.add_rectangle((0, 0), (10, 10))
corner = [(10, 10), (20, 10), (20, 20), (10, 20)]
ids = [s.add_point(*p) for p in corner]
for a, b in zip(ids, ids[1:] + ids[:1]):
    s.add_line_ids(a, b)
check("two loops that touch at a corner stay two",
      sorted(len(loop) for loop in kernel._loops(s)) == [4, 4],
      kernel._loops(s))

print("where freeform solids overlap")
from types import SimpleNamespace
from datum.bridge import ops                                        # noqa
from datum.bridge import assembly_ops
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
from OCP.gp import gp_Pnt


def sections_at(z):
    s = Sketch(SketchPlane(origin=(0, 0, z)), "oval")
    s.add_spline([(20, 0), (0, 12), (-20, 0), (0, -12)], closed=True)
    return s


body = kernel.loft([kernel.sketch_faces(sections_at(z))[0]
                    for z in (0, 50, 100)])
slab = BRepPrimAPI_MakeBox(gp_Pnt(-40, -40, 45), gp_Pnt(40, 40, 55)).Shape()
meet = [SimpleNamespace(id=i, name=n, shape=s, visible=True,
                        placed=lambda s=s: s)
        for i, (n, s) in enumerate((("body", body), ("slab", slab)))]
found = assembly_ops.find_interference(
    SimpleNamespace(active=lambda: meet))["pairs"][0]
check("the overlap's box is the overlap's, not the whole surface's",
      abs(found["overlap_bbox"][2] - 45) < 0.1
      and abs(found["overlap_bbox"][5] - 55) < 0.1, found)

print("lofts")
bad = []
for n in (5, 9, 11, 14, 17, 21, 25, 27, 31, 33, 37, 41, 51, 61):
    try:
        made = kernel.loft([kernel.sketch_profile(section(n, c, z)[0])
                            for c, z in ((220.0, 0.0), (53.0, 500.0))],
                           True, True)
        if (len(kernel.solids(made)) != 1
                or not BRepCheck_Analyzer(made).IsValid()):
            bad.append(n)
    except kernel.KernelError as exc:
        bad.append((n, str(exc)))
check("airfoils of 5 to 61 points all loft into solids", not bad, bad)

bent = kernel.MakePolygon()
for p in ((0, 0, 0), (40, 0, 0), (40, 30, 6), (0, 30, 0)):
    bent.Add(gp_Pnt(*p))
bent.Close()
top = kernel.MakePolygon()
for p in ((0, 0, 50), (40, 0, 50), (40, 30, 56), (0, 30, 50)):
    top.Add(gp_Pnt(*p))
top.Close()
try:
    kernel.loft([bent.Wire(), top.Wire()], True, True)
    said = ""
except kernel.KernelError as exc:
    said = str(exc)
check("a loft that cannot be capped is an error, not an empty success",
      "open skin" in said, said)
check("an open loft is still allowed", kernel.is_valid(
    kernel.loft([bent.Wire(), top.Wire()], False, True)))

print()
if FAILS:
    print("%d FAILURES: %s" % (len(FAILS), ", ".join(FAILS)))
    sys.exit(1)
print("all freeform measurement tests passed")
