"""Ctrl+Z and Ctrl+Y over frame and pipe edits, one change at a time.

The sequence from the user: pipes put in, a corner made an elbow, then
insulation added with Change Frame.  Ctrl+Z three times takes them back in
that order, last first, one each; Ctrl+Y three times puts them back the
same way.  At every step what the frame's files say and what the view
shows agree: a pipe in the tree is a pipe on the screen.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import harness  # noqa: E402,F401

os.environ.setdefault("DATUM_SETTINGS_ORG", "IITEG-tests")

from PySide6 import QtCore, QtWidgets                              # noqa: E402

from datum.core import frames, pipe_corners                        # noqa: E402
from datum.core.assembly import AssemblyDocument                   # noqa: E402
from datum.core.document import Document                           # noqa: E402
from datum.core.features import SketchFeature                      # noqa: E402
from datum.core.sketch import Sketch, SketchPlane                  # noqa: E402
from datum.ui.frames_ui import frame_ids, load_frame               # noqa: E402
from datum.ui.main_window import MainWindow                        # noqa: E402

FAILS = []
WORK = tempfile.mkdtemp(prefix="datum_frame_undo_")
os.environ["DATUM_PROFILE_LIBRARY"] = os.path.join(WORK, "profiles")
app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
win = MainWindow()
win.resize(1300, 850)
win.show()


def check(name, cond, extra=""):
    print(("  PASS  " if cond else "  FAIL  ") + name
          + ("  " + str(extra) if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


def settle(ms=300):
    loop = QtCore.QEventLoop()
    QtCore.QTimer.singleShot(ms, loop.quit)
    loop.exec()


skeleton = Document()
route = SketchFeature(name="Route")
route.sketch = Sketch(SketchPlane((0.0, 0.0, 300.0), (0.0, 0.0, 1.0)),
                      "Route")
route.sketch.add_line((0.0, 0.0), (900.0, 0.0))
route.sketch.add_line((900.0, 0.0), (900.0, 600.0))
route.sketch.add_line((900.0, 600.0), (1500.0, 600.0))
skeleton.add_feature(route)
skeleton.rebuild()
skp = skeleton.save(os.path.join(WORK, "Route"))
plant = AssemblyDocument()
plant.path = os.path.join(WORK, "Plant.icasm")
plant.place(skp)
plant.save(plant.path)
win.open_path(plant.path)
settle(900)


def state():
    """(pipes, elbows, insulated pipes, frame drawn with a shape)."""
    doc = win.assembly
    fids = frame_ids(doc)
    if not fids:
        return (0, 0, 0, False)
    fd = load_frame(doc, fids[0]).frame
    elbows = sum(1 for f in fd.fittings if "Elbow" in f["part"])
    lagged = sum(1 for m in fd.members if m.insulation > 0)
    occ = doc.occurrence(fids[0])
    # on the screen: the view holds a displayed object for the frame
    ais = getattr(win.viewport, "_component_ais", {}).get(fids[0])
    drawn = occ is not None and occ.shape is not None and ais is not None \
        and win.viewport.context.IsDisplayed(ais)
    return (len(fd.members), elbows, lagged, drawn)


print("the edits")
dialog = win.insert_pipe()
settle()
dialog.choose("en-12735-1-copper", "22x1")
dialog.add_lines(list(dialog.candidates()))
check("pipes put in", dialog.apply(), dialog.message.text())
dialog.close()
settle()
s_pipes = state()
check("one bent pipe, drawn", s_pipes == (1, 0, 0, True), s_pipes)

mode = win.pipe_corners()
settle()
mode.choose(0, "elbow")
mode.accept()
settle()
s_corner = state()
check("a corner made an elbow: two pipes and an elbow",
      s_corner == (2, 1, 0, True), s_corner)

fid = frame_ids(win.assembly)[0]
members = [m.id for m in load_frame(win.assembly, fid).frame.members]
change = win.change_frame(fid, members)
settle()
change.insulation.setValue(13.0)
check("insulation added with Change Frame", change.apply(),
      change.message.text())
change.close()
settle()
s_lag = state()
check("both pipes insulated", s_lag == (2, 1, 2, True), s_lag)

print("Ctrl+Z, one change at a time")
win.undo()
settle()
check("the first takes the insulation away, and nothing else",
      state() == s_corner, state())
win.undo()
settle()
check("the second puts the corner back to a bend", state() == s_pipes,
      state())
win.undo()
settle()
check("the third takes the pipes away", state()[0] == 0, state())

print("Ctrl+Y, one at a time")
win.redo()
settle()
check("the pipes come back, and are drawn", state() == s_pipes, state())
win.redo()
settle()
check("then the elbow", state() == s_corner, state())
win.redo()
settle()
check("then the insulation", state() == s_lag, state())

print("Pipe Corners' cross leaves no step behind")
mode = win.pipe_corners()
settle()
before_steps = len(win.assembly._undo)
mode.choose(0, "bend") if mode._corners else None
mode.cancel()
settle()
check("cancelled, the frame is as it was", state() == s_lag, state())
check("and Ctrl+Z still goes to the step before",
      len(win.assembly._undo) == before_steps, len(win.assembly._undo))

print()
if FAILS:
    print("%d FAILURES: %s" % (len(FAILS), ", ".join(FAILS)))
    sys.exit(1)
print("all passed")
