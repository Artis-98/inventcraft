"""Centre marks and lines go on a part's views as they are placed.

A block with a hole through it: the view looking down the hole gets a
centre mark, the views from the side a centre line, without asking.
Turned off in the Base View dialog, none. An assembly's views get none
unasked. Automated Centerlines puts marks on as well as lines.
"""
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import harness  # noqa: E402,F401

os.environ.setdefault("DATUM_SETTINGS_ORG", "IITEG-tests")

from PySide6 import QtCore, QtWidgets                              # noqa: E402

from datum.core import drawing as dwg                              # noqa: E402
from datum.core import hlr                                         # noqa: E402
from datum.core.document import Document                           # noqa: E402
from datum.core.features import CUT, PrimitiveFeature              # noqa: E402
from datum.ui.main_window import MainWindow                        # noqa: E402

FAILS = []
WORK = tempfile.mkdtemp(prefix="datum_centres_")
app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
win = MainWindow()
win.resize(1300, 850)
win.show()


def check(name, cond, extra=""):
    print(("  PASS  " if cond else "  FAIL  ") + name
          + ("  " + str(extra) if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


def settle(ms=250):
    end = time.monotonic() + ms / 1000.0
    while time.monotonic() < end:
        app.processEvents(QtCore.QEventLoop.AllEvents, 20)


part = Document()
part.add_feature(PrimitiveFeature(name="Block", kind="box", a="60", b="40",
                                  c="20"))
part.add_feature(PrimitiveFeature(name="Hole", kind="cylinder", a="6",
                                  b="20", operation=CUT,
                                  origin=("30", "20", "0")))
part.rebuild()
BLOCK = part.save(os.path.join(WORK, "Block"))

win.new_drawing(prompt=False)
settle(300)
win.drawing.path = os.path.join(WORK, "Centres.icdraw")
win.save_document()
settle(200)
ui = win.drawing_ui
sheet = win.drawing.active()
d, u = hlr.ORIENTATIONS["front"]

print("placed with them")
base = ui.create_views({"path": BLOCK, "scale": 1.0, "name": "Front"},
                       d, u, 100.0, 180.0, [(100.0, 90.0)])
settle(200)
ui.refine_now(60)
settle(100)
top = [v for v in sheet.views if v.parent == base.id][0]


def of(view, kind):
    return [a for a in sheet.annotations
            if a.view == view.id and a.kind == kind]


check("the front view has a centre line down the hole",
      len(of(base, dwg.CENTRELINE)) == 1, len(of(base, dwg.CENTRELINE)))
check("the top view, looking down it, a centre mark",
      len(of(top, dwg.CENTRE_MARK)) == 1, len(of(top, dwg.CENTRE_MARK)))
mark = of(top, dwg.CENTRE_MARK)
check("reaching past the hole", mark and mark[0].value > 6.0,
      mark[0].value if mark else None)

print("asked not to")
before = len(sheet.annotations)
ui.create_views({"path": BLOCK, "scale": 1.0, "name": "Bare",
                 "centrelines": False}, d, u, 280.0, 180.0, [])
settle(200)
check("no new marks or lines", len(sheet.annotations) == before,
      len(sheet.annotations) - before)

print("Automated Centerlines marks holes too")
bare = [v for v in sheet.views if v.name == "Bare"][0]
ui.automated_centrelines(bare.id)
check("a line on the side view", len(of(bare, dwg.CENTRELINE)) == 1)
ui.automated_centrelines(top.id)
check("run again, still one mark, not two",
      len(of(top, dwg.CENTRE_MARK)) == 1, len(of(top, dwg.CENTRE_MARK)))

win.drawing.modified = False
win.close()
print()
print("FAILED: %s" % FAILS if FAILS else "ALL PASSED")
sys.exit(1 if FAILS else 0)
