"""Export PDF runs on a thread of its own, the window drawing meanwhile.

The PDF comes out whole, with the title block's fields filled in from
the sheet being written, and the window's event loop keeps turning
while it is written.
"""
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import harness  # noqa: E402

os.environ.setdefault("DATUM_SETTINGS_ORG", "IITEG-tests")

from PySide6 import QtCore, QtWidgets                              # noqa: E402

from datum.core import hlr                                         # noqa: E402
from datum.core.document import Document                           # noqa: E402
from datum.core.features import PrimitiveFeature                   # noqa: E402
from datum.ui import drawingexport                                 # noqa: E402
from datum.ui.main_window import MainWindow                        # noqa: E402

FAILS = []
WORK = tempfile.mkdtemp(prefix="datum_bgexport_")
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
part.add_feature(PrimitiveFeature(kind="box", a="60", b="40", c="20"))
part.rebuild()
BLOCK = part.save(os.path.join(WORK, "Block"))
win.new_drawing(prompt=False)
settle(300)
win.drawing.path = os.path.join(WORK, "Export.icdraw")
win.save_document()
settle(200)
ui = win.drawing_ui
d, u = hlr.ORIENTATIONS["front"]
ui.create_views({"path": BLOCK, "scale": 1.0, "name": "Front"}, d, u,
                120.0, 150.0, [(260.0, 150.0)])
settle(200)

print("written in the background")
ticks = []
timer = QtCore.QTimer()
timer.setInterval(5)
timer.timeout.connect(lambda: ticks.append(time.monotonic()))
timer.start()
real = drawingexport.to_pdf


def slow(*args, **kw):
    time.sleep(0.6)          # as a big sheet would take
    return real(*args, **kw)


drawingexport.to_pdf = slow
pdf = os.path.join(WORK, "Export.pdf")
harness.saving(pdf)
ui.export_pdf()
drawingexport.to_pdf = real
timer.stop()
check("the PDF is written", os.path.exists(pdf)
      and os.path.getsize(pdf) > 1000)
check("the window kept turning while it was",
      len(ticks) > 20, len(ticks))
check("and says so", "Exported" in win.status_message.text(),
      win.status_message.text())

print("an error comes back to the window")
drawingexport.to_pdf = lambda *a, **k: (_ for _ in ()).throw(
    ValueError("disk full"))
harness.saving(os.path.join(WORK, "Bad.pdf"))
ui.export_pdf()
drawingexport.to_pdf = real
check("shown as an error box", "disk full" in harness.text("critical"),
      harness.text("critical"))

win.drawing.modified = False
win.close()
print()
print("FAILED: %s" % FAILS if FAILS else "ALL PASSED")
sys.exit(1 if FAILS else 0)
