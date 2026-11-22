"""Each file keeps how it is looked at.

A part set to Shaded and perspective keeps that when another part is
opened beside it, comes back to it when its tab is picked again, and
opens that way from the file. A part saved before this opens shaded
with edges and orthographic, as always.
"""
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import harness  # noqa: E402,F401

os.environ.setdefault("DATUM_SETTINGS_ORG", "IITEG-tests")

from PySide6 import QtCore, QtWidgets                              # noqa: E402

from datum.core.features import PrimitiveFeature                   # noqa: E402
from datum.core.viewsetup import ViewSetup                         # noqa: E402
from datum.ui.main_window import MainWindow                        # noqa: E402

FAILS = []
WORK = tempfile.mkdtemp(prefix="datum_viewfile_")
app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
win = MainWindow()
win.resize(1100, 750)
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


def looks():
    return (win.viewport.display_mode, win.viewport.is_orthographic())


settle(600)
win.new_document(prompt=False)
settle(300)
win.document.add_feature(PrimitiveFeature(kind="box", a="40", b="30",
                                          c="20"))
win.rebuild()
first = win.session.active
win.set_visual_style("shaded")
win.ortho_btn.setChecked(False)
settle(100)
check("the first part shaded, in perspective",
      looks() == ("shaded", False), looks())
win.document.path = os.path.join(WORK, "First.icpart")
win.save_document()
settle(200)

print("a second part beside it")
win.new_document(prompt=False)
settle(300)
check("starts shaded with edges, orthographic",
      looks() == ("shaded_edges", True), looks())

print("back to the first")
win.activate(first)
settle(300)
check("it is shaded and in perspective again",
      looks() == ("shaded", False), looks())

print("from the file")
path = first.path
for entry in list(win.session.documents):
    entry.document.modified = False
    win.close_key(entry.key)
settle(300)
win.open_path(path)
settle(400)
check("opens shaded, in perspective", looks() == ("shaded", False),
      looks())

print("an older file")
old = ViewSetup.from_dict({"front": [0, -1, 0], "top": [0, 0, 1]})
check("has no style of its own", old.style == ""
      and old.orthographic is None)

win.document.modified = False
win.close()
print()
print("FAILED: %s" % FAILS if FAILS else "ALL PASSED")
sys.exit(1 if FAILS else 0)
