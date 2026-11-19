"""After Finish Sketch, Ctrl+Z walks back through the sketch's own edits.

Dimensions placed and the lines they moved come off one at a time, newest
first, rather than the whole sketch going at once.  The same in a part and
in a sketch on a drawing sheet.
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


def draw_and_dimension():
    """Two lines, then a dimension on each typed to a new length."""
    ed.snap_grid = False
    ed.set_tool("line")
    click(0, 0)
    click(60, 0)
    click(60, 40)
    ed.set_tool("select")
    pump()
    ed.set_tool("dimension")
    for value in ("80", "50"):
        line = [e for e in ed.sketch.entities.values() if e.kind == "line"][
            0 if value == "80" else 1]
        a = ed.sketch.points[line.points[0]]
        b = ed.sketch.points[line.points[1]]
        mx, my = (a.x + b.x) / 2.0, (a.y + b.y) / 2.0
        click(mx, my)
        click(mx + 12.0, my - 12.0)
        pump()
        if ed.value_popup.isVisible():
            ed.value_popup.accepted.emit(value)
            ed.value_popup.hide()
        pump()
    ed.set_tool("select")
    pump()


def span(sketch):
    xs = [p.x for p in sketch.points.values()]
    return round(max(xs) - min(xs), 3) if xs else 0.0


def count(sketch):
    if sketch is None:
        return (0, 0, 0.0)
    return (sum(1 for e in sketch.entities.values() if e.kind == "line"),
            sum(1 for c in sketch.constraints.values()
                if c.kind in ("distance", "length", "horizontal_distance",
                              "vertical_distance", "dimension")
                or getattr(c, "driving", False)),
            span(sketch))


def walk(read, label):
    states = [read()]
    for _ in range(12):
        before = read()
        win.undo()
        pump()
        now = read()
        if now == before:
            break
        states.append(now)
    print("   ", label, "undo walk:", states)
    return states


print("a part sketch")
win.new_document(prompt=False)
win.start_sketch_on_plane("XY")
pump()
draw_and_dimension()
inside = count(ed.sketch)
win.finish_sketch()
pump()


def part_state():
    feature = next((f for f in win.document.features
                    if isinstance(f, SketchFeature)), None)
    return count(feature.sketch if feature else None)


check("two lines and their two dimensions", part_state()[0] == 2
      and part_state()[1] >= 2, part_state())
states = walk(part_state, "part")
check("Ctrl+Z took the dimensions off one at a time before any line",
      len(states) >= 5 and states[1][0] == 2 and states[2][0] == 2
      and states[1][1] == states[0][1] - 1, states)
# the walk's last press undid the empty part's own first step, which
# changes nothing to see: one more redo than steps seen
for _ in range(len(states)):
    win.redo()
    pump()
check("and Ctrl+Y put it all back", part_state() == states[0], part_state())

print("a sketch on a drawing sheet")
win.new_drawing(prompt=False)
pump()
sheet = win.drawing.active()
win.drawing_ui.begin_drawing_sketch(sheet, None)
pump()
draw_and_dimension()
win.finish_sketch()
pump()


def sheet_state():
    from datum.core.sketch import Sketch
    held = win.drawing.active().sketches
    return count(Sketch.from_dict(held[0].sketch) if held else None)


check("the drawing sketch has its lines and dimensions",
      sheet_state()[0] == 2 and sheet_state()[1] >= 2, sheet_state())
states = walk(sheet_state, "drawing")
check("Ctrl+Z on the drawing walks back inside the sketch, one at a time",
      len(states) >= 5 and states[1][0] == 2
      and states[1][1] == states[0][1] - 1 and states[-1] == (0, 0, 0.0),
      states)
for _ in range(len(states) - 1):
    win.redo()
    pump()
check("and Ctrl+Y brings each back", sheet_state() == states[0],
      sheet_state())

print()
if FAILS:
    print("%d FAILURES: %s" % (len(FAILS), ", ".join(FAILS)))
    sys.exit(1)
print("all passed")
