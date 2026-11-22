"""An assembly view drawn again only where a part changed.

Thirty blocks in rows, some in front of others, seen from the front
with hidden lines. One is made longer. Redrawn only round it, the view
has the same lines as seeing the whole assembly again: every point of
one lies on the other, kind for kind, and the lengths of each kind
agree. A change too big to be worth it is left to the whole pass.
"""
import math
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DATUM_NO_WORKERS"] = "1"

from OCP.BRep import BRep_Builder                                # noqa: E402
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox                  # noqa: E402
from OCP.TopoDS import TopoDS_Compound                           # noqa: E402
from OCP.gp import gp_Pnt                                        # noqa: E402

from datum.core import hlr, partial                              # noqa: E402

FAILS = []


def check(name, cond, extra=""):
    print(("  PASS  " if cond else "  FAIL  ") + name
          + (("  " + str(extra)) if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


def assembly(blocks):
    builder = BRep_Builder()
    whole = TopoDS_Compound()
    builder.MakeCompound(whole)
    for shape in blocks:
        builder.Add(whole, shape)
    return whole


random.seed(3)
specs = []
for i in range(30):
    x, y, z = (i % 6) * 30.0, (i // 6) * 12.0, random.uniform(0, 20)
    specs.append((x, y, z, 22.0, 8.0, 15.0))
blocks = [BRepPrimAPI_MakeBox(gp_Pnt(*s[:3]), *s[3:]).Shape()
          for s in specs]
old_shape = assembly(blocks)
d, u = (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)
old = hlr.project(old_shape, d, u, hidden=True)

# one block in the middle made longer, the rest the very same solids
x, y, z, a, b, c = specs[14]
changed = list(blocks)
changed[14] = BRepPrimAPI_MakeBox(gp_Pnt(x, y, z), a + 12.0, b, c).Shape()
new_shape = assembly(changed)

print("what changed")
found = partial.changed(old_shape, new_shape)
check("one solid gone and one arrived",
      found and len(found[0]) == 1 and len(found[1]) == 1,
      found and (len(found[0]), len(found[1])))
plan = partial.plan(old_shape, new_shape, d, u)
check("a plan to redraw round it", plan is not None and plan[0] is not None)
region, involved = plan
check("seeing only some of the blocks again",
      0 < len(involved) < len(blocks), len(involved))

print("the same lines as the whole pass")
quick = partial.redraw(old, new_shape, region, involved, d, u, True, True)
full = hlr.project(new_shape, d, u, hidden=True)


def frame_points(projection, kind):
    cx, cy = projection.centre
    return [(x + cx, y + cy) for line in projection.of_kind(kind)
            for x, y in line.points]


def length(projection, kind):
    return sum(math.dist(p, q) for line in projection.of_kind(kind)
               for p, q in zip(line.points, line.points[1:]))


def near_any(point, lines, centre, reach=0.02):
    cx, cy = centre
    for line in lines:
        for p, q in zip(line.points, line.points[1:]):
            p = (p[0] + cx, p[1] + cy)
            q = (q[0] + cx, q[1] + cy)
            dx, dy = q[0] - p[0], q[1] - p[1]
            n = dx * dx + dy * dy
            t = 0.0 if n == 0 else max(0.0, min(1.0, (
                (point[0] - p[0]) * dx + (point[1] - p[1]) * dy) / n))
            if math.dist(point, (p[0] + dx * t, p[1] + dy * t)) < reach:
                return True
    return False


for kind in (hlr.VISIBLE, hlr.HIDDEN):
    a_len, b_len = length(quick, kind), length(full, kind)
    check("%s: the same length of line" % kind,
          abs(a_len - b_len) < 1e-3 * max(1.0, b_len), (a_len, b_len))
    pts = frame_points(quick, kind)[::7]
    stray = [p for p in pts
             if not near_any(p, full.of_kind(kind), full.centre)]
    check("%s: every point of it on the whole pass's lines" % kind,
          not stray, stray[:3])
check("centred the same", math.dist(quick.centre, full.centre) < 1e-6
      and all(abs(a - b) < 1e-6 for a, b in zip(quick.box, full.box)))

print("nothing changed")
same = partial.plan(old_shape, assembly(list(blocks)), d, u)
check("nothing to redraw", same == (None, []), same)

print("too much changed")
moved = [BRepPrimAPI_MakeBox(gp_Pnt(s[0] + 1, s[1], s[2]), *s[3:]).Shape()
         for s in specs]
check("left to the whole pass",
      partial.plan(old_shape, assembly(moved), d, u) is None)

print("splitting a line at a box")
inside = partial.split([(0, 0), (10, 0)], (2, -1, 5, 1), True)
outside = partial.split([(0, 0), (10, 0)], (2, -1, 5, 1), False)
check("the piece inside", inside == [[(2.0, 0.0), (5.0, 0.0)]], inside)
check("the pieces outside", outside == [[(0.0, 0.0), (2.0, 0.0)],
                                        [(5.0, 0.0), (10.0, 0.0)]], outside)

print("through the drawing")
import tempfile                                                  # noqa: E402
from datum.core import fileformat, projcache, views, workers      # noqa: E402
from datum.core.drawing import (BASE, WITH_HIDDEN,                # noqa: E402
                                DrawingDocument, View)
workers.ENABLED = False
WORK = tempfile.mkdtemp(prefix="datum_mend_")
MODEL = os.path.join(WORK, "Blocks.iam")
open(MODEL, "w").close()
gen = views.Generator()
bodies = {"now": old_shape}
gen.library.shape = lambda path, *a, **k: bodies["now"]
gen.library.peek = lambda path: bodies["now"]
doc = DrawingDocument()
doc.path = os.path.join(WORK, "d.ddat")
sheet = doc.add_sheet("A3")
view = View(kind=BASE, orientation="front", scale=1.0, x=200, y=150,
            display=WITH_HIDDEN)
view.ref = fileformat.ComponentRef(path="Blocks.iam", name="Blocks.iam",
                                   label="Blocks")
doc.add_view(sheet, view)
views.load_model = lambda path, library: (library.shape(path), None)
gen.rebuild(doc, force=True)
seen = []
real_project = hlr.project


def spy(shape, *a, **k):
    from OCP.TopAbs import TopAbs_SOLID
    from datum.core import kernel
    seen.append(len(list(kernel.explore(shape, TopAbs_SOLID))))
    return real_project(shape, *a, **k)


views.hlr.project = spy
partial.hlr.project = spy
bodies["now"] = new_shape
view.projection = None
gen.rebuild(doc, force=True)
views.hlr.project = partial.hlr.project = real_project
check("the changed view saw only the blocks round the change",
      seen and max(seen) < len(blocks), seen)
check("and came out as the whole pass would",
      abs(view.projection.width - full.width) < 1e-6
      and abs(length(view.projection, hlr.HIDDEN)
              - length(full, hlr.HIDDEN)) < 1e-3 * length(full, hlr.HIDDEN))

print()
print("all passed" if not FAILS else "FAILED: %s" % FAILS)
sys.exit(1 if FAILS else 0)
