"""Cosmetic threads in drawing views, the ISO 6410 way.

A threaded shaft seen from the side has two thin lines at the root of
its thread and a wide line where the thread stops; seen end on, a thin
three-quarter circle. A tapped hole seen from the side has its thread as
hidden lines, at the crest. A plain part has none of this.
"""
import math
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WORK = tempfile.mkdtemp(prefix="datum_dthread_")
os.environ["DATUM_CONFIG_DIR"] = os.path.join(WORK, "cfg")
os.environ["DATUM_NO_WORKERS"] = "1"

from datum.core import fileformat, hlr, kernel, threads, views, workers  # noqa
from datum.core.document import Document                           # noqa
from datum.core.drawing import (BASE, WITH_HIDDEN, DrawingDocument,  # noqa
                                View)
from datum.core.features import (CUT, PrimitiveFeature,           # noqa
                                 ThreadFeature)
from datum.core.naming import RefSet                               # noqa

workers.ENABLED = False
FAILS = []


def check(name, cond, extra=""):
    print(("  PASS  " if cond else "  FAIL  ") + name
          + (("  " + str(extra)) if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


def round_face(shape, radius):
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_SurfaceType
    for f in kernel.faces(shape):
        s = BRepAdaptor_Surface(f)
        if s.GetType() == GeomAbs_SurfaceType.GeomAbs_Cylinder \
                and abs(s.Cylinder().Radius() - radius) < 1e-6:
            return f
    return None


def drawn(path, orientation, display=WITH_HIDDEN, direction=None, up=None):
    doc = DrawingDocument()
    doc.path = os.path.join(WORK, "t.ddat")
    sheet = doc.add_sheet("A3")
    view = View(kind=BASE, orientation=orientation, scale=2.0, x=150,
                y=150, display=display)
    if direction is not None:
        view.direction, view.up = list(direction), list(up)
    view.ref = fileformat.ComponentRef(
        path=fileformat.relative_path(path, WORK),
        name=os.path.basename(path), label="part")
    doc.add_view(sheet, view)
    views.Generator().rebuild(doc, force=True)
    return view


shaft = Document()
shaft.add_feature(PrimitiveFeature(name="Shaft", kind="cylinder", a="8",
                                   b="30"))
shaft.rebuild()
thread = ThreadFeature(designation="M16", diameter=16.0, pitch=2.0)
thread.refs = RefSet()
thread.refs.capture_from(shaft.shape, "face", [round_face(shaft.shape, 8.0)])
thread.full_length, thread.length = False, "20"
shaft.add_feature(thread)
shaft.rebuild()
SHAFT = shaft.save(os.path.join(WORK, "Shaft"))

print("a threaded shaft from the side")
side = drawn(SHAFT, "front")
lines = side.projection.of_kind(hlr.THREAD)
check("two thin thread lines", len(lines) == 2, len(lines))
root = 8.0 - 0.6134 * 2.0
if len(lines) == 2:
    gap = abs(lines[0].points[0][0] - lines[1].points[0][0])
    check("at the root diameter, at the view's scale",
          abs(gap - 2 * root * 2.0) < 1e-6, (gap, 2 * root * 2.0))
    length = math.dist(*lines[0].points)
    check("20 long, as the thread is", abs(length - 40.0) < 1e-6, length)

print("end on")
end = drawn(SHAFT, "top")
arc = end.projection.of_kind(hlr.THREAD)
check("one three-quarter circle", len(arc) == 1, len(arc))
if arc:
    xs = [p[0] for p in arc[0].points]
    check("of the root radius",
          abs((max(xs) - min(xs)) / 2.0 - root * 2.0) < 0.1)
    first, last = arc[0].points[0], arc[0].points[-1]
    check("open by a quarter", math.dist(first, last) > root * 2.0)

print("a tapped hole")
block = Document()
block.add_feature(PrimitiveFeature(name="Block", kind="box", a="40",
                                   b="40", c="20"))
block.add_feature(PrimitiveFeature(name="Bore", kind="cylinder", a="6",
                                   b="20", operation=CUT,
                                   origin=("20", "20", "0")))
block.rebuild()
tap = ThreadFeature(designation="M14", diameter=14.0, pitch=2.0)
tap.refs = RefSet()
tap.refs.capture_from(block.shape, "face", [round_face(block.shape, 6.0)])
block.add_feature(tap)
block.rebuild()
BLOCK = block.save(os.path.join(WORK, "Block"))
hole = drawn(BLOCK, "front")
tapped = [l for l in hole.projection.lines if l.kind == hlr.HIDDEN
          and len(l.points) == 2
          and abs(l.points[0][1] - l.points[1][1]) > 30.0]
check("its crest lines are hidden lines", len(tapped) >= 2, len(tapped))
check("and none is a thin solid line",
      not hole.projection.of_kind(hlr.THREAD))
plainly = drawn(BLOCK, "front", display="visible")
check("with hidden lines off, it is not shown",
      not [l for l in plainly.projection.lines if l.kind == hlr.HIDDEN])

print("nothing on a plain part")
plain = Document()
plain.add_feature(PrimitiveFeature(kind="cylinder", a="8", b="30"))
plain.rebuild()
PLAIN = plain.save(os.path.join(WORK, "Plain"))
check("no thread lines", not drawn(PLAIN, "front").projection.of_kind(
    hlr.THREAD))

print()
print("all passed" if not FAILS else "FAILED: %s" % FAILS)
sys.exit(1 if FAILS else 0)
