"""Construction, the Inventor way: with nothing picked it is a mode, and
what is drawn while it is on is construction and never makes a profile.

From an email: a line drawn after pressing Construction still split the
profile, because the button only ever changed what was already picked.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import harness  # noqa: E402,F401

os.environ.setdefault("DATUM_SETTINGS_ORG", "IITEG-tests")

from PySide6 import QtCore, QtWidgets                           # noqa: E402

from datum.core import kernel                                   # noqa: E402

FAILS = []


def check(name, cond, extra=""):
    print(("  PASS  " if cond else "  FAIL  ") + name
          + (("  " + str(extra)) if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)


def settle(ms=200):
    end = QtCore.QTime.currentTime().addMSecs(ms)
    while QtCore.QTime.currentTime() < end:
        app.processEvents()


from datum.ui.main_window import MainWindow                     # noqa: E402

win = MainWindow()
win.resize(1300, 850)
win.show()
win.new_document(prompt=False)
settle(600)
win.start_sketch_on_plane("XY")
settle(500)
ed = win.editor
ed.sketch.add_rectangle((0.0, 0.0), (50.0, 30.0))
ed.selected_entities.clear()
win.construction_btn.click()
settle(100)
check("with nothing picked, Construction turns on as a mode",
      ed.construction and win.construction_btn.isChecked())
ed.set_tool("line") if hasattr(ed, "set_tool") else setattr(ed, "tool", "line")
ed.begin_change()
diagonal = ed.sketch.add_line((0.0, 0.0), (50.0, 30.0), weld=False)
ed._touch()
check("a line drawn while it is on is construction",
      ed.sketch.entities[diagonal].construction)
check("and does not split the profile",
      len(kernel.sketch_regions(ed.sketch)) == 1,
      len(kernel.sketch_regions(ed.sketch)))
win.construction_btn.click()
settle(100)
ed.begin_change()
other = ed.sketch.add_line((0.0, 30.0), (50.0, 0.0), weld=False)
ed._touch()
check("clicked again it is off, and lines are lines",
      not ed.construction and not win.construction_btn.isChecked()
      and not ed.sketch.entities[other].construction)
ed.selected_entities.clear()
ed.selected_entities.add(other) if isinstance(ed.selected_entities, set) \
    else ed.selected_entities.append(other)
win.construction_btn.click()
settle(100)
check("with a line picked it turns that line to construction, no mode",
      ed.sketch.entities[other].construction and not ed.construction
      and not win.construction_btn.isChecked())

print()
if FAILS:
    print("%d FAILED: %s" % (len(FAILS), ", ".join(FAILS)))
    sys.exit(1)
print("all passed")
sys.exit(0)
