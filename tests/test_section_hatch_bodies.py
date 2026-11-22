"""Parts side by side in a section are hatched differently (ISO 128-50).

Two blocks touching, cut through both: each block's cut face gets its
own group, the first hatched as the pattern says and the second square
to it, so where one stops and the next starts can be read. A single
body is hatched exactly as before. The groups survive the file and the
projection cache.
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DATUM_NO_WORKERS"] = "1"

from OCP.BRep import BRep_Builder                                # noqa: E402
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox                  # noqa: E402
from OCP.TopoDS import TopoDS_Compound                           # noqa: E402
from OCP.gp import gp_Pnt                                        # noqa: E402

from datum.core import drawing as dwg                            # noqa: E402
from datum.core import hlr, projcache, views                     # noqa: E402

FAILS = []


def check(name, cond, extra=""):
    print(("  PASS  " if cond else "  FAIL  ") + name
          + (("  " + str(extra)) if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


def angles(segments):
    out = set()
    for (x0, y0), (x1, y1) in segments:
        out.add(round(math.degrees(math.atan2(y1 - y0, x1 - x0)) % 180.0))
    return out


a = BRepPrimAPI_MakeBox(gp_Pnt(0, 0, 0), 40, 30, 20).Shape()
b = BRepPrimAPI_MakeBox(gp_Pnt(40, 0, 0), 40, 30, 20).Shape()
pair = TopoDS_Compound()
builder = BRep_Builder()
builder.MakeCompound(pair)
builder.Add(pair, a)
builder.Add(pair, b)

print("two bodies cut")
point, normal = (40.0, 15.0, 10.0), (0.0, 1.0, 0.0)
cut = views.half_space(pair, point, normal)
faces = views._cut_faces_by_body(cut, (40.0, 15.0, 10.0), normal)
check("a face of each, each with its body",
      sorted(g for _f, g in faces) == [0, 1], [g for _f, g in faces])
projection = hlr.project(cut, (0.0, -1.0, 0.0), (0.0, 0.0, 1.0),
                         hidden=False, hatch=faces)
loops = projection.of_kind(hlr.CUT)
check("both loops kept their body", sorted(l.group for l in loops)
      == [0, 1])
steel = dwg.hatch_patterns()["steel"]
by = {}
for line in loops:
    by.setdefault(line.group, []).append(line)
both = angles(dwg.hatch_segments(loops, steel))
plain = {round(a) % 180 for a in steel.angles}
square = {round(a + 90) % 180 for a in steel.angles}
check("one hatched as the pattern says, the other square to it",
      both == plain | square, both)
colours = dwg._neighbour_colours({g: [l.points for l in ls]
                                  for g, ls in by.items()})
check("touching, so never the same", colours[0] != colours[1], colours)
apart = dwg._neighbour_colours({0: [[(0, 0), (1, 0), (1, 1)]],
                                1: [[(5, 5), (6, 5), (6, 6)]]})
check("apart, they may share", apart[0] == apart[1], apart)

print("one body as before")
one = views._cut_faces_by_body(views.half_space(a, point, normal),
                               point, normal)
check("plain faces, no groups", all(not isinstance(f, tuple) for f in one))

print("kept")
back = hlr.Projection.from_dict(projection.to_dict())
check("through the file", sorted(l.group for l in back.of_kind(hlr.CUT))
      == [0, 1])
cache = projcache.ProjectionCache()
cache.put("k", projection)
check("through the cache", sorted(
    l.group for l in cache.get("k").of_kind(hlr.CUT)) == [0, 1])
check("a variant past the first two is closer",
      dwg.hatch_variant(steel, 2).spacing < steel.spacing)

print()
print("all passed" if not FAILS else "FAILED: %s" % FAILS)
sys.exit(1 if FAILS else 0)
