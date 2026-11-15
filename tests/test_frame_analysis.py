"""Frame Analysis on a real Frame Generator frame (#275).

A table: a 1000 x 600 top of 40 x 40 tubes at 750, standing on three
angle legs along its front, one of them meeting the front rail halfway.
The frame is made into beams, the middle leg splitting the rail it meets,
stood on its feet, loaded on top, and solved.  The answers are checked
for what must hold whatever the numbers: the feet take the whole load,
twice the load is twice the sag, and wind pushes it downwind.
"""
import math
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import harness  # noqa: E402,F401

import numpy as np  # noqa: E402

from datum.core import beams, frame_analysis, frames  # noqa: E402
from datum.core.assembly import AssemblyDocument  # noqa: E402
from datum.core.document import Document  # noqa: E402
from datum.core.features import SketchFeature  # noqa: E402
from datum.core.sketch import STANDARD_PLANES, Sketch, SketchPlane  # noqa: E402

FAILS = []
WORK = tempfile.mkdtemp(prefix="datum_frame_analysis_")
os.environ["DATUM_PROFILE_LIBRARY"] = os.path.join(WORK, "profiles")


def check(name, cond, extra=""):
    print(("  PASS  " if cond else "  FAIL  ") + name
          + ("" if cond else "  " + str(extra)))
    if not cond:
        FAILS.append(name)


skeleton = Document()
top = SketchFeature(name="Top")
top.sketch = Sketch(SketchPlane((0.0, 0.0, 750.0), (0.0, 0.0, 1.0)), "Top")
top.sketch.add_rectangle((0.0, 0.0), (1000.0, 600.0))
skeleton.add_feature(top)
legs = SketchFeature(name="Legs")
legs.sketch = Sketch(STANDARD_PLANES["XZ"], "Legs")
for x in (0.0, 500.0, 1000.0):
    legs.sketch.add_line((x, 0.0), (x, 750.0))
skeleton.add_feature(legs)
skeleton.rebuild()
skeleton_path = skeleton.save(os.path.join(WORK, "Table skeleton"))

table = AssemblyDocument()
table.path = os.path.join(WORK, "Table.icasm")
table.save(table.path)
skeleton_occurrence = table.place(skeleton_path)
sketches = frames.skeleton_sketches(skeleton_path)
top_id = next(i for i, s in sketches.items() if s[1] == "Top")
legs_id = next(i for i, s in sketches.items() if s[1] == "Legs")
frame, frame_occurrence, problems = frames.insert(
    table, skeleton_occurrence, top_id, list(sketches[top_id][2]),
    "din-en-10219-2-square", "40 x 40 x 3")
frame, frame_occurrence, problems = frames.insert(
    table, skeleton_occurrence, legs_id, list(sketches[legs_id][2]),
    "din-en-10056-1-equal", "L40x40x4", anchor="bl",
    frame_occurrence=frame_occurrence)
check("a frame of seven members", len(frame.frame.members) == 7, problems)

print("made into beams")
setup = frame_analysis.Setup(top_load=1000.0)
fm = frame_analysis.build(frame, setup)
model = fm.model
check("eight joints: four corners, the rail's middle, three feet",
      len(model.nodes) == 8, model.nodes)
check("the front rail split where the middle leg meets it: eight beams",
      len(model.members) == 8, len(model.members))
check("standing on its three feet", len(model.supports) == 3
      and all(model.nodes[i][2] < 1 for i in model.supports),
      model.supports)
check("the load shared over the top", len(model.loads) == 5
      and math.isclose(sum(l.force[2] for l in model.loads), -1000.0),
      [l.force for l in model.loads])
tube = next(m.section for m in model.members if "10219" in m.name)
check("the tube's section from its profile", 400 < tube.area < 450,
      tube.area)

print("solved")
fm, result, summary = frame_analysis.analyse(frame, setup)
check("no trouble", not result.error, result.error)
weight = sum(m.material.rho * m.section.area * beams.G
             * math.dist(model.nodes[m.a], model.nodes[m.b])
             for m in model.members)
held = sum(r[2] for r in result.reactions.values())
check("the feet hold the load and the frame's weight, %.1f N"
      % (1000 + weight), math.isclose(held, 1000 + weight, rel_tol=1e-6),
      held)
# legs only along the front: the back rail hangs out on the side rails
check("it sags, a few millimetres at the unsupported back",
      0 < result.max_deflection < 20
      and model.nodes[result.max_node][1] > 500,
      (result.max_deflection, model.nodes[result.max_node]))
check("a member per line in the summary", len(summary) == 7, len(summary))
check("well inside the steel", 0 < summary[0].utilisation < 1
      and result.safety > 1, (summary[0].utilisation, result.safety))
check("three natural frequencies, lowest first",
      len(result.frequencies) == 3 and result.frequencies[0] > 0
      and result.frequencies == sorted(result.frequencies),
      result.frequencies)

print("twice the load, twice the sag")
one = beams.solve(frame_analysis.build(
    frame, frame_analysis.Setup(top_load=1000.0, self_weight=False)).model,
    modes=0)
two = beams.solve(frame_analysis.build(
    frame, frame_analysis.Setup(top_load=2000.0, self_weight=False)).model,
    modes=0)
check("exactly", np.allclose(two.displacements, 2 * one.displacements,
                             atol=1e-9))

print("wind from the front")
blown = beams.solve(frame_analysis.build(
    frame, frame_analysis.Setup(self_weight=False, wind_speed=30.0,
                                wind_direction=(0.0, 1.0, 0.0))).model,
    modes=0)
top_nodes = [i for i, p in enumerate(model.nodes) if p[2] > 700]
check("the top moves downwind",
      all(blown.displacements[i, 1] > 0 for i in top_nodes),
      [blown.displacements[i, 1] for i in top_nodes])

print("pinned feet are softer than fixed ones")
pinned = beams.solve(frame_analysis.build(
    frame, frame_analysis.Setup(support=beams.PINNED, self_weight=False,
                                wind_speed=30.0,
                                wind_direction=(0.0, 1.0, 0.0))).model,
    modes=0)
check("more sway", pinned.error or pinned.max_deflection
      > blown.max_deflection, (pinned.error, pinned.max_deflection,
                               blown.max_deflection))

print("in the window")
os.environ.setdefault("DATUM_SETTINGS_ORG", "IITEG-tests")
from PySide6 import QtWidgets  # noqa: E402
from datum.ui.main_window import MainWindow  # noqa: E402
from datum.ui.theme import stylesheet  # noqa: E402

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
app.setStyleSheet(stylesheet())
win = MainWindow()
win.resize(1300, 850)
win.show()
table.save(table.path)
win.open_path(table.path)
for _ in range(20):
    app.processEvents()
dialog = win.frame_analysis()
check("the dialog finds the frame", dialog is not None
      and dialog.frame.count() == 1)
dialog.load.setValue(1000.0)
dialog.run()
for _ in range(5):
    app.processEvents()
check("the results are shown", "Safety factor" in dialog.summary.text(),
      dialog.summary.text())
check("every member ranked", dialog.table.rowCount() == 7,
      dialog.table.rowCount())
dialog.grab().save(os.path.join(WORK, "frame_analysis.png"))
print("    picture:", os.path.join(WORK, "frame_analysis.png"))

print()
if FAILS:
    print("%d FAILED" % len(FAILS))
    sys.exit(1)
print("all passed")
