"""Ctrl+Z goes back one change, Ctrl+Y forward one.

It used to go back by a whole lot: a finished sketch was one step, so one
Ctrl+Z took every line of it; a sketch opened again to edit took no step
at all, so Ctrl+Z skipped past it to whatever came before; and a change
with no step of its own (a parameter typed into the table) went back with
the one before it.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import harness  # noqa: E402,F401

os.environ.setdefault("DATUM_SETTINGS_ORG", "IITEG-tests")

from PySide6 import QtCore, QtWidgets                              # noqa: E402

from datum.core.features import SketchFeature                      # noqa: E402
from datum.ui.main_window import MainWindow                        # noqa: E402

FAILS = []
app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
win = MainWindow()
win.resize(1300, 850)
win.show()
app.processEvents()
ed = win.editor


def check(name, cond, extra=""):
    print(("  PASS  " if cond else "  FAIL  ") + name
          + ("  " + str(extra) if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


def pump(n=3):
    for _ in range(n):
        app.processEvents()


def click(u, v):
    ed._on_move(u, v, QtCore.Qt.NoModifier)
    ed._on_click(u, v, QtCore.Qt.NoModifier)
    pump(1)


def lines():
    sk = next(f for f in win.document.features
              if isinstance(f, SketchFeature)).sketch
    return sum(1 for e in sk.entities.values() if e.kind == "line")


print("a new sketch, finished")
win.new_document(prompt=False)
win.start_sketch_on_plane("XY")
pump()
ed.snap_grid = False
ed.set_tool("line")
click(0, 0)
click(60, 0)
click(60, 40)
click(0, 40)
ed.set_tool("select")
pump()
win.finish_sketch()
pump()
check("three lines drawn", lines() == 3, lines())
win.undo()
pump()
check("one Ctrl+Z after Finish Sketch takes back one line, not the sketch",
      lines() == 2, lines())
win.undo()
pump()
check("and the next one more", lines() == 1, lines())
win.redo()
win.redo()
pump()
check("Ctrl+Y brings them back one at a time", lines() == 3, lines())

print("a sketch opened again to edit")
sid = next(f.id for f in win.document.features if isinstance(f, SketchFeature))
win.edit_sketch(sid)
pump()
ed.snap_grid = False
ed.set_tool("line")
click(0, 40)
click(-30, 20)
ed.set_tool("select")
pump()
win.finish_sketch()
pump()
check("a line added to it", lines() == 4, lines())
win.undo()
pump()
check("Ctrl+Z takes back that line, not what came before it",
      lines() == 3, lines())
win.redo()
pump()
check("and Ctrl+Y puts it back", lines() == 4, lines())

print("a change with no step of its own")
win.document.params.add("width", "50")
win.rebuild()
win.document.params.set_expression("width", "80")
win.rebuild()
check("the table says 80", win.document.params.get("width").expression == "80")
win.undo()
pump()
held = win.document.params.get("width")
check("one Ctrl+Z takes it back to 50, the step before alone",
      held is not None and held.expression == "50",
      held and held.expression)
check("and the sketch is still all there", lines() == 4, lines())

print()
if FAILS:
    print("%d FAILURES: %s" % (len(FAILS), ", ".join(FAILS)))
    sys.exit(1)
print("all passed")
