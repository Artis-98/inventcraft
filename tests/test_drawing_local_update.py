"""A part edited in its own tab comes through to the drawing of it.

Reported from the Suggest button (#365): Local Update did not update the
views of a part changed in another tab; the views had to be placed
again. Going back to the drawing's tab takes the edit, as an assembly
does, and Local Update and Update both draw the views from the part as
it is now.
"""
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import harness  # noqa: E402,F401

os.environ.setdefault("DATUM_SETTINGS_ORG", "IITEG-tests")

from PySide6 import QtCore, QtWidgets                              # noqa: E402

from datum.core import hlr                                         # noqa: E402
from datum.core.document import Document                           # noqa: E402
from datum.core.features import PrimitiveFeature                   # noqa: E402
from datum.ui.main_window import MainWindow                        # noqa: E402

FAILS = []
WORK = tempfile.mkdtemp(prefix="datum_dlu_")
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
part.add_feature(PrimitiveFeature(kind="box", a="40", b="30", c="10"))
part.rebuild()
BLOCK = part.save(os.path.join(WORK, "Block"))

win.new_drawing(prompt=False)
settle(300)
win.drawing.path = os.path.join(WORK, "Block.icdraw")
win.save_document()
settle(200)
ui = win.drawing_ui
d, u = hlr.ORIENTATIONS["front"]
view = ui.create_views({"path": BLOCK, "scale": 1.0, "name": "Front"},
                       d, u, 120.0, 150.0, [])
settle(200)
drawing_entry = win.session.active
width = view.projection.width
check("the front view is the block's 40 mm", abs(width - 40.0) < 0.01,
      width)

print("the block made longer in its own tab")
win.open_path(BLOCK)
settle(300)
block_entry = win.session.by_path(BLOCK)
check("the part has a tab", block_entry is not None
      and win.session.active is block_entry)
win.document.features[0].a = "70"
win.document.modified = True
win.rebuild()
settle(200)

print("back in the drawing")
win.activate(drawing_entry)
settle(400)
ui.refine_now(120)
settle(200)
view = win.drawing.active().views[0]
check("the view is the new length at once",
      abs(view.projection.width - 70.0) < 0.01, view.projection.width)
check("and nothing is left to update", not win.qat_update.isEnabled())

print("Local Update, pressed in the drawing")
win.activate(block_entry)
settle(200)
win.document.features[0].a = "55"
win.document.modified = True
win.rebuild()
settle(200)
# the tab change takes it already; send the edit through Local Update
# alone by making the switch quietly
win.session.active = drawing_entry
win._set_workspace(drawing_entry.doc_type)
win.drawing = drawing_entry.document
settle(100)
check("the sheet knows it is behind", win.session.is_stale(drawing_entry))
win.local_update()
settle(300)
ui.refine_now(120)
view = win.drawing.active().views[0]
check("Local Update draws it from the edit",
      abs(view.projection.width - 55.0) < 0.01, view.projection.width)
check("and says so", "Updated" in win.status_message.text(),
      win.status_message.text())

print("Update with nothing changed keeps the lines")
lines = view.projection
ui.update_views()
settle(100)
view = win.drawing.active().views[0]
check("the same length", abs(view.projection.width - 55.0) < 0.01)

print("a part saved from elsewhere marks the view, and Update View fixes it")
block_entry.document.modified = False
win.close_key(block_entry.key)
settle(200)
other = Document()
other.add_feature(PrimitiveFeature(kind="box", a="90", b="30", c="10"))
other.rebuild()
time.sleep(0.05)
other.save(BLOCK)
win.activate(drawing_entry)
settle(200)
ui.rebuild()
view = win.drawing.active().views[0]
check("the view says it is out of date", view.stale)
ui.update_view(view.id)
settle(100)
view = win.drawing.active().views[0]
check("Update View draws it as saved", not view.stale
      and abs(view.projection.width - 90.0) < 0.01,
      (view.stale, view.projection.width))

for entry in list(win.session.documents):
    entry.document.modified = False
win.close()
print()
print("FAILED: %s" % FAILS if FAILS else "ALL PASSED")
sys.exit(1 if FAILS else 0)
