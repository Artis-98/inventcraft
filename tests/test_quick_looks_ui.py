"""A quick look drawn while the exact rebuild is still on its way, in the
window.

A part of several slow solids is edited: the spare cores build each
solid on its own and that goes on screen first, then the exact rebuild
takes its place, and what is left on screen is the exact one.
"""
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

WORK = tempfile.mkdtemp(prefix="datum_looks_ui_")
os.environ["DATUM_CONFIG_DIR"] = os.path.join(WORK, "cfg")
os.environ["DATUM_DOCUMENTS"] = os.path.join(WORK, "Documents")
os.environ["DATUM_NO_RESULT_CACHE"] = "1"
# workers on, which the harness otherwise switches off for window tests
os.environ["DATUM_NO_WORKERS"] = ""
os.environ["DATUM_WORKERS"] = "4"

import harness  # noqa: E402,F401

from PySide6 import QtWidgets  # noqa: E402

from datum.core import document as docmod  # noqa: E402
from datum.core import kernel, workers  # noqa: E402
from datum.ui.main_window import MainWindow  # noqa: E402
from datum.ui.theme import stylesheet  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from quick_looks_parts import plates  # noqa: E402

FAILS = []
app = QtWidgets.QApplication(sys.argv)
app.setStyleSheet(stylesheet())
win = MainWindow()
win.resize(1300, 850)
win.show()


def check(name, cond, extra=""):
    print(("  PASS  " if cond else "  FAIL  ") + name
          + (("  " + str(extra)) if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


def pump(n=6):
    for _ in range(n):
        app.processEvents()


path = os.path.join(WORK, "Plates.icpart")
plates(3, holes=4, fillets=True).save(path)
check("the part opens", win.open_path(path))
pump()
helpers = workers.pool()
helpers.start()
check("workers are ready", helpers.wait_ready(timeout=120) == 4)
time.sleep(2.0)       # the copy the window asked for when it opened
pump()
win.rebuild(keep_camera=True)
pump()

docmod.PREVIEW_FROM = 0.0
docmod.GROUP_MIN = 0.0
docmod.REMOTE_AFTER = 0.0
shown = []
real = win.viewport.set_shape


def spy(shape, *args, **kwargs):
    shown.append(shape)
    return real(shape, *args, **kwargs)


win.viewport.set_shape = spy
looks = []
real_looks = win._quick_looks


def spy_looks(document, helpers_, exact):
    made = real_looks(document, helpers_, exact)
    looks.append(made)
    return made


win._quick_looks = spy_looks
win.document.params.set_expression("d", "6")
win.rebuild(keep_camera=True)
pump()
check("quick looks were sent", looks and len(looks[0].futures) == 3,
      looks and len(looks[0].futures))
check("one was drawn before the exact rebuild", looks and looks[0].shown
      and len(shown) >= 2, (looks and looks[0].shown, len(shown)))
check("the exact rebuild is what stays on screen",
      shown and shown[-1] is win.document.visible_shape())
check("and it is clean", not win.document.last_report.errors,
      win.document.last_report.errors)
first = shown[0] if len(shown) >= 2 else None
check("the look had every solid of the exact one",
      first is not None and abs(kernel.volume(first)
                                - kernel.volume(win.document.shape)) < 1e-3)

win.viewport.set_shape = real
win._quick_looks = real_looks
docmod.PREVIEW_FROM = 0.8
docmod.GROUP_MIN = 0.1
docmod.REMOTE_AFTER = 0.3
win.document.modified = False
helpers.shutdown()
print()
print("all passed" if not FAILS else "FAILED: %s" % FAILS)
sys.exit(1 if FAILS else 0)
