"""Views of a big model go on the sheet as a quick draft first, and the
real lines replace them from the workers without holding the window up,
the way Inventor places a view.  The Base View preview is a draft too.
A small part is drawn exactly straight away, as it always was."""
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import harness  # noqa: E402,F401

os.environ.setdefault("DATUM_SETTINGS_ORG", "IITEG-tests")

from PySide6 import QtCore, QtWidgets                              # noqa: E402

from datum.core import hlr, kernel                                 # noqa: E402
from datum.core import views                                       # noqa: E402
# the pins are a few hundred faces: drafted as a big model would be
views.DRAFT_FACES = 150
from datum.core.document import Document                           # noqa: E402
from datum.core.features import PrimitiveFeature                   # noqa: E402
from datum.ui.main_window import MainWindow                        # noqa: E402

FAILS = []
WORK = tempfile.mkdtemp(prefix="datum_draft_")
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
    loop = QtCore.QEventLoop()
    QtCore.QTimer.singleShot(ms, loop.quit)
    loop.exec()


print("hlr draft mode")
from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder        # noqa: E402
from OCP.BRepAlgoAPI import BRepAlgoAPI_Fuse                # noqa: E402
from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt                   # noqa: E402

# a big enough model: a row of 60 pins, each a few faces
shape = None
for i in range(60):
    pin = BRepPrimAPI_MakeCylinder(
        gp_Ax2(gp_Pnt(i * 12.0, (i % 6) * 12.0, 0), gp_Dir(0, 0, 1)),
        4.0, 30.0).Shape()
    shape = pin if shape is None else BRepAlgoAPI_Fuse(shape, pin).Shape()
exact = hlr.project(shape, *hlr.ORIENTATIONS["iso"])
draft = hlr.project(shape, *hlr.ORIENTATIONS["iso"], fast=True)
check("a draft projection comes back", draft.ok, draft.error)
check("the same size as the real one",
      all(abs(a - b) < 0.5 for a, b in zip(exact.box, draft.box)),
      (exact.box, draft.box))
check("joined into polylines, not loose segments",
      len(draft.lines) < 10 * max(1, len(exact.lines)),
      (len(draft.lines), len(exact.lines)))

doc = Document()
doc.add_feature(PrimitiveFeature(kind="box", a="40", b="30", c="10"))
doc.rebuild()
SMALL = doc.save(os.path.join(WORK, "small"))
# the pins saved as a part, through STEP, so a drawing can place them
from datum.core import standard_parts                        # noqa: E402
step = os.path.join(WORK, "pins.step")
from datum.core import fileio                                 # noqa: E402
fileio.write_step(shape, step)
BIG = None
if os.path.exists(step):
    BIG = standard_parts.part_for_file(step, WORK)

win.new_drawing(prompt=False)
settle(300)
win.drawing.path = os.path.join(WORK, "Sheet.icdraw")
win.save_document()
settle(200)
ui = win.drawing_ui
d, u = hlr.ORIENTATIONS["front"]

print("a small part")
base = ui.create_views({"path": SMALL, "scale": 1.0, "name": "Small"},
                       d, u, 100.0, 150.0, [(200.0, 150.0)])
settle(100)
check("is drawn exactly at once",
      all(not getattr(v, "draft", False) for v in win.drawing.active().views)
      and base.projection is not None)

if BIG:
    print("a big model")
    t = time.perf_counter()
    big = ui.create_views({"path": BIG, "scale": 1.0, "name": "Big"},
                          d, u, 100.0, 60.0, [(300.0, 60.0)])
    took = time.perf_counter() - t
    drafts = [v for v in win.drawing.active().views
              if getattr(v, "draft", False)]
    check("goes on as drafts", len(drafts) == 2, len(drafts))
    check("with lines to show", all(v.projection is not None
                                    and v.projection.lines for v in drafts))
    check("as outlines, at once", took < 3.0 and all(
        all(l.kind == hlr.SMOOTH for l in v.projection.lines)
        for v in drafts), took)
    ui.refine_now()
    settle(100)
    still = [v for v in win.drawing.active().views
             if getattr(v, "draft", False)]
    check("then the real lines replace them", not still, len(still))
    check("which are there", big.projection is not None
          and big.projection.ok)

    print("each view goes in as its own lines come back")
    from concurrent.futures import Future
    sheet = win.drawing.active()
    pair = [v for v in sheet.views if v.name == "Big"
            or (v.parent == big.id)]
    for v in pair:
        v.draft = True
    first, second = pair[0], pair[1]
    exact = first.projection
    ready, later = Future(), Future()
    ready.set_result(exact.to_dict())
    ui._refining = (win.drawing, {(id(sheet), first.id): ready,
                                  (id(sheet), second.id): later})
    ui._refine_timer.stop()
    ui._refine_poll()
    check("the finished one is real at once",
          not getattr(first, "draft", False))
    check("the other still waits as a draft",
          getattr(second, "draft", False))
    check("and is still being waited for",
          ui._refining is not None
          and list(ui._refining[1]) == [(id(sheet), second.id)])
    later.set_result(second.projection.to_dict())
    ui._refine_poll()
    check("then it goes in too", not getattr(second, "draft", False)
          and ui._refining is None)
else:
    print("  (no STEP export here: the big-model half is skipped)")

print()
print("FAILED: %s" % FAILS if FAILS else "ALL PASSED")
sys.exit(1 if FAILS else 0)
