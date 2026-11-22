"""Place views of a big model in the real window and time the waits.

    .venv/Scripts/python.exe tools/bench_place_views.py [model]

How long the window is held placing a base view and three projected
ones, how long until every real line is in, and what an Update costs.
Saves pictures of the sheet with the placeholders and with real lines.
"""
import os
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
# the harness turns the workers off for tests; this is about them
os.environ["DATUM_NO_WORKERS"] = ""
import harness  # noqa: E402,F401

os.environ.setdefault("DATUM_SETTINGS_ORG", "IITEG-tests")
from PySide6 import QtCore, QtWidgets                            # noqa: E402

from datum.core import hlr                                       # noqa: E402
from datum.ui.main_window import MainWindow                      # noqa: E402

args = [a for a in sys.argv[1:] if not a.startswith("--")]
MODEL = os.path.abspath(args[0] if args else os.path.join(
    ROOT, "examples", "walking-excavator", "Walking Excavator.icasm"))
OUT = tempfile.mkdtemp(prefix="datum_place_")

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
win = MainWindow()
win.resize(1500, 950)
win.show()


def settle(ms=200):
    end = time.monotonic() + ms / 1000.0
    while time.monotonic() < end:
        app.processEvents(QtCore.QEventLoop.AllEvents, 20)


settle(800)
win.new_drawing(prompt=False)
settle(300)
win.drawing.path = os.path.join(OUT, "Bench.icdraw")
ui = win.drawing_ui
d, u = hlr.ORIENTATIONS["front"]

PROFILE = "--profile" in sys.argv
if PROFILE:
    import cProfile
    import pstats
    profiler = cProfile.Profile()
    profiler.enable()
t = time.perf_counter()
ui.create_views({"path": MODEL, "scale": 0.05, "name": "Front"}, d, u,
                150.0, 200.0, [(330.0, 200.0), (150.0, 80.0),
                               (330.0, 80.0)])
held = time.perf_counter() - t
if PROFILE:
    profiler.disable()
    pstats.Stats(profiler).sort_stats("cumulative").print_stats(35)
print("window held placing 4 views   %6.2f s" % held)
settle(200)
ui.canvas.grab().save(os.path.join(OUT, "1_placeholders.png"))
t = time.perf_counter()
ui.refine_now(600)
print("until every real line is in   %6.2f s" % (time.perf_counter() - t))
settle(400)
ui.canvas.grab().save(os.path.join(OUT, "2_real.png"))

t = time.perf_counter()
ui.update_views()
print("window held for Update        %6.2f s" % (time.perf_counter() - t))
t = time.perf_counter()
ui.refine_now(600)
print("Update, real lines in         %6.2f s" % (time.perf_counter() - t))

sheet = win.drawing.active()
base = sheet.views[0]
t = time.perf_counter()
base.scale = 0.04
for v in sheet.views:
    v.projection = None
ui.rebuild()
print("scale changed                 %6.2f s" % (time.perf_counter() - t))
print("pictures in", OUT)
win.drawing.modified = False
win.close()
