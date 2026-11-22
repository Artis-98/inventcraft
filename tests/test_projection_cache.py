"""Projections worked out once are used again.

A new scale, a rename, an undo, a second view the same way round and
hidden lines switched off all ask for lines already worked out. Each
must come from the cache, and be the lines a fresh projection would be.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WORK = tempfile.mkdtemp(prefix="datum_pcache_")
os.environ["DATUM_CONFIG_DIR"] = os.path.join(WORK, "cfg")
os.environ["DATUM_NO_WORKERS"] = "1"

from datum.core import fileformat, hlr, projcache, views, workers  # noqa
from datum.core.drawing import (BASE, PROJECTED, WITH_HIDDEN,     # noqa
                                DrawingDocument, View)

workers.ENABLED = False
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL = os.path.join(ROOT, "examples", "excavator", "Idler Wheel.pdat")
FAILS = []


def check(name, cond, extra=""):
    print(("  PASS  " if cond else "  FAIL  ") + name
          + (("  " + str(extra)) if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


def same(a, b, tol=1e-6):
    if a is None or b is None or len(a.lines) != len(b.lines):
        return False
    for p, q in zip(a.lines, b.lines):
        if p.kind != q.kind or len(p.points) != len(q.points):
            return False
        for (x1, y1), (x2, y2) in zip(p.points, q.points):
            if abs(x1 - x2) > tol or abs(y1 - y2) > tol:
                return False
    return all(abs(u - v) <= tol for u, v in zip(a.box, b.box))


calls = []
real_project = hlr.project


def counting(*args, **kw):
    calls.append(kw.get("hidden"))
    return real_project(*args, **kw)


views.hlr.project = counting

print("packing")
line = hlr.Polyline([(0.0, 0.0), (2.0, 1.0)], hlr.VISIBLE)
hid = hlr.Polyline([(1.0, 3.0), (1.0, -3.0)], hlr.HIDDEN)
p = hlr.Projection(lines=[line, hid], box=(-1, -3, 2, 3), centre=(5, 6))
cache = projcache.ProjectionCache(budget=10)
cache.put("k", p)
back = cache.get("k", 2.0)
check("scaled on the way out", back.lines[0].points[1] == (4.0, 2.0))
check("box scaled", back.box == (-2, -6, 4, 6))
check("a copy, not the original", back.lines[0] is not line)
check("original untouched", line.points[1] == (2.0, 1.0))
no_hidden = cache.get_without("k", (hlr.HIDDEN,))
check("hidden left out", [l.kind for l in no_hidden.lines] == [hlr.VISIBLE])
check("recentred on what is left",
      no_hidden.lines[0].points == [(-1.0, -0.5), (1.0, 0.5)]
      and no_hidden.centre == (6.0, 6.5), (no_hidden.lines[0].points,
                                           no_hidden.centre))
cache.put("j", p)
cache.put("i", p)
check("oldest let go past the budget", not cache.has("k")
      and cache.has("i"))


def reference(path):
    return fileformat.ComponentRef(
        path=fileformat.relative_path(path, WORK),
        name=os.path.basename(path),
        label=os.path.splitext(os.path.basename(path))[0])


doc = DrawingDocument()
doc.path = os.path.join(WORK, "cache.ddat")
sheet = doc.add_sheet("A3")
base = View(kind=BASE, orientation="front", scale=1.0, x=120, y=150,
            display=WITH_HIDDEN, name="Front")
base.ref = reference(MODEL)
doc.add_view(sheet, base)
top = doc.add_view(sheet, View(kind=PROJECTED, parent=base.id, name="Top",
                               x=120, y=60))
gen = views.Generator()

print("in a drawing")
gen.rebuild(doc, force=True)
first = len(calls)
check("two views, two projections", first == 2, calls)
fresh_front = base.projection

calls.clear()
base.scale = 2.0
for v in sheet.views:
    v.projection = None
gen.rebuild(doc)
check("a new scale projects nothing", calls == [], calls)
check("and draws the front twice the size",
      abs(base.projection.width - 2 * fresh_front.width) < 1e-6)

calls.clear()
base.scale = 1.0
for v in sheet.views:
    v.projection = None
gen.rebuild(doc)
check("back to the old scale, the very same lines",
      same(base.projection, fresh_front))

calls.clear()
base.display = "visible"
top.display = ""
for v in sheet.views:
    v.projection = None
gen.rebuild(doc)
check("hidden off comes from the lines with them", calls == [], calls)
derived = base.projection
projcache.shared().clear()
for v in sheet.views:
    v.projection = None
gen.rebuild(doc)
check("and is what projecting without them gives",
      same(derived, base.projection, 1e-6))

calls.clear()
twin = doc.add_view(sheet, View(kind=BASE, orientation="front", scale=1.0,
                                x=300, y=150, display="visible",
                                name="Front again"))
twin.ref = reference(MODEL)
gen.rebuild(doc)
check("a second view the same way round projects nothing", calls == [],
      calls)
check("and has the same lines", same(twin.projection, base.projection))

views.hlr.project = real_project
print()
print("all passed" if not FAILS else "FAILED: %s" % FAILS)
sys.exit(1 if FAILS else 0)
