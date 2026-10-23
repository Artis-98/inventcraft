"""Which face is Front, and where Home is (#262, #263).

The document's own Front and Top turn every named view with them, in
the model and on a drawing; Home is kept in the file.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import harness  # noqa: E402,F401

from datum.core import hlr, viewsetup                             # noqa: E402
from datum.core import views as viewgen                           # noqa: E402
from datum.core.assembly import AssemblyDocument                  # noqa: E402
from datum.core.document import Document                          # noqa: E402
from datum.core.features import PrimitiveFeature                  # noqa: E402
from datum.core.viewsetup import ViewSetup                        # noqa: E402

FAILS = []


def check(name, cond, extra=""):
    print(("  PASS  " if cond else "  FAIL  ") + name
          + ("  " + str(extra) if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


def same(a, b):
    return all(abs(a[i] - b[i]) < 1e-9 for i in range(3))


print("the stock setup is the one there always was")
stock = ViewSetup()
check("it says so", stock.is_default())
check("every named view is hlr's own", all(
    same(stock.orientation(n)[0], hlr.ORIENTATIONS[n][0])
    and same(stock.orientation(n)[1], hlr.ORIENTATIONS[n][1])
    for n in hlr.ORIENTATIONS))
check("Front faces -Y, Right +X, Top +Z",
      stock.face_at((0, -1, 0)) == "front" and stock.face_at((1, 0, 0))
      == "right" and stock.face_at((0, 0, 1)) == "top")

print("Set Current View as Front")
setup = ViewSetup()
# looking at the stock Right face, from outside it, Z up
setup.set_front((-1.0, 0.0, 0.0), (0.0, 0.0, 1.0))
check("the face looked at is Front", same(setup.front, (1, 0, 0))
      and setup.face_at((1, 0, 0)) == "front", setup.front)
check("the top of the screen is Top", same(setup.top, (0, 0, 1)))
check("Right is the one to its right", setup.face_at((0, 1, 0)) == "right")
look, up = setup.orientation("front")
check("the Front view looks at it", same(look, (-1, 0, 0))
      and same(up, (0, 0, 1)), (look, up))
look, up = setup.orientation("top")
check("Top still looks down, with Front at the bottom of the screen",
      same(look, (0, 0, -1)) and same(up, (-1, 0, 0)), (look, up))
odd = ViewSetup()
odd.set_front((-0.9, 0.3, -0.2), (0.1, 0.2, 0.97))
size = sum(c * c for c in (-0.9, 0.3, -0.2)) ** 0.5
check("a view at any angle is taken exactly, not snapped",
      same(odd.front, (0.9 / size, -0.3 / size, 0.2 / size))
      and abs(sum(a * b for a, b in zip(odd.front, odd.top))) < 1e-12
      and odd.top[2] > 0.9, (odd.front, odd.top))
look, up = odd.orientation("front")
check("and its Front view looks exactly that way",
      same(look, (-0.9 / size, 0.3 / size, -0.2 / size)), look)
check("turning out and back again is no turn at all",
      same(odd.local(odd.turn((0.3, -0.4, 0.8))), (0.3, -0.4, 0.8)))

print("Set Current View as Top")
setup2 = ViewSetup()
# looking at the stock Front face, Z up the screen
setup2.set_top((0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
check("the face looked at is Top, the bottom of the screen Front",
      same(setup2.top, (0, -1, 0)) and same(setup2.front, (0, 0, -1)),
      (setup2.top, setup2.front))
setup2.reset_front()
check("and Reset puts the stock ones back", setup2.is_default())

print("a part modelled at an odd angle, drawn square once Front is set")
from OCP.gp import gp_Ax1, gp_Dir, gp_Pnt, gp_Trsf                # noqa: E402
from datum.core import kernel                                     # noqa: E402

slab = kernel.rotate(kernel.box(60, 20, 40), (0, 0, 0), (1, 2, 3), 37.0)
spin = gp_Trsf()
spin.SetRotation(gp_Ax1(gp_Pnt(0, 0, 0), gp_Dir(1, 2, 3)),
                 __import__("math").radians(37.0))


def spun(v):
    d = gp_Dir(*v).Transformed(spin)
    return (d.X(), d.Y(), d.Z())


stock_view = hlr.project(slab, *hlr.ORIENTATIONS["front"])
check("seen from the world's front it is a mess of slanted edges",
      abs(stock_view.width - 60) > 5 or abs(stock_view.height - 40) > 5,
      (stock_view.width, stock_view.height))
square = ViewSetup()
# Look At its 60 x 40 face, square on, its long edge level, then Set
# Current View as Front
square.set_front([-c for c in spun((0, -1, 0))], spun((0, 0, 1)))
front_view = hlr.project(slab, *square.orientation("front"))
check("from its own Front it is drawn 60 by 40, square",
      abs(front_view.width - 60) < 1e-3 and abs(front_view.height - 40) < 1e-3,
      (front_view.width, front_view.height))
top_view = hlr.project(slab, *square.orientation("top"))
check("and its Top 60 by 20", abs(top_view.width - 60) < 1e-3
      and abs(top_view.height - 20) < 1e-3, (top_view.width, top_view.height))

print("kept in the file")
doc = Document()
box = PrimitiveFeature()
box.kind, box.a, box.b, box.c = "box", "40", "20", "10"
doc.add_feature(box)
doc.rebuild()
doc.view.set_front((-1.0, 0.0, 0.0), (0.0, 0.0, 1.0))
doc.view.home = {"fit": False, "camera": [[100, -100, 100], [0, 0, 0],
                                          [0, 0, 1], 0.5, True]}
again = Document()
again.load_dict(doc.to_dict())
check("Front, Top and Home survive the file",
      same(again.view.front, (1, 0, 0)) and same(again.view.top, (0, 0, 1))
      and again.view.home == doc.view.home, again.view)
check("a file from before reads as the stock setup",
      ViewSetup.from_dict(None).is_default()
      and ViewSetup.from_dict({"front": "nonsense"}).is_default())
skew = ViewSetup.from_dict({"front": [0, -1, 0], "top": [0, -1, 0]})
check("Front and Top that are not square are made square",
      abs(sum(a * b for a, b in zip(skew.top, skew.front))) < 1e-9, skew)
assembly = AssemblyDocument()
assembly.view.set_front((0.0, -1.0, 0.0), (0.0, 0.0, 1.0))
twin = AssemblyDocument()
twin.load_dict(assembly.to_dict())
check("an assembly keeps its own too", same(twin.view.front, (0, 1, 0)))

folder = tempfile.mkdtemp(prefix="datum_viewsetup_")
path = os.path.join(folder, "Turned.pdat")
doc.save(path)
read = viewsetup.of_file(path)
check("read back from the saved part", same(read.front, (1, 0, 0)), read)
check("a file that is not there has the stock setup",
      viewsetup.of_file(os.path.join(folder, "missing.pdat")).is_default())

print("a drawing's views follow it")
front_look = read.orientation("front")[0]
check("the drawing calls the model's front Front",
      viewgen.named_orientation(front_look, read) == "front")
check("where the stock names would have called it Right",
      viewgen.named_orientation(front_look) == "right")

from PySide6 import QtWidgets                                     # noqa: E402
app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
from datum.ui.sheetcube import OrientationCube                    # noqa: E402

cube = OrientationCube()
cube.set_setup(read)
cube.set_view(*read.orientation("front"))
look, up, _right = cube._camera()
check("the sheet's little cube turns with the model: its front view "
      "shows the cube's FRONT", same(look, (0, 1, 0)) and same(up, (0, 0, 1)),
      (look, up))
look, up = cube.view_for("front")
check("and a click on FRONT is the model's front view",
      same(look, (-1, 0, 0)) and same(up, (0, 0, 1)), (look, up))
look, up = cube.view_for("home")
check("its house the model's isometric",
      same(look, [c / 3 ** 0.5 for c in read.orientation("iso")[0]]),
      look)

print()
if FAILS:
    print("%d FAILURES: %s" % (len(FAILS), ", ".join(FAILS)))
    sys.exit(1)
print("all passed")
sys.exit(0)
