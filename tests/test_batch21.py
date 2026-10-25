"""0.3.2: the four bugs reported on GitHub.

#13 the Dimension tool raised on every mouse move after the first pick,
and the error box came back as fast as it was closed.  #7 a Linux copy
trusted no certificates off Ubuntu.  #9 dProperties had no way to close
it.  #8 nowhere said which version this is.
"""

import os
import ssl
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import harness  # noqa: E402,F401

os.environ.setdefault("DATUM_SETTINGS_ORG", "IITEG-tests")

from PySide6 import QtCore, QtWidgets                              # noqa: E402

from datum import APP_NAME, __version__                            # noqa: E402
from datum import app as app_module                                # noqa: E402
from datum.core import update                                      # noqa: E402
from datum.ui.main_window import MainWindow                        # noqa: E402
from datum.ui.theme import stylesheet                              # noqa: E402

FAILS = []
WORK = tempfile.mkdtemp(prefix="datum_batch21_")


def check(name, cond, extra=""):
    print(("  PASS  " if cond else "  FAIL  ") + name
          + (("  " + str(extra)) if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


app = QtWidgets.QApplication(sys.argv)
app.setStyle("Fusion")
app.setStyleSheet(stylesheet())
win = MainWindow()
win.resize(1400, 900)
win.show()
app.processEvents()
ed = win.editor
NONE = QtCore.Qt.NoModifier


def pump(n=3):
    for _ in range(n):
        app.processEvents()


# ==========================================================================
print("#13: the Dimension tool, moving after the first pick")

win.new_document(prompt=False)
win.start_sketch_on_plane("XY")
pump()
ed.snap_grid = False
sketch = ed.sketch
line = sketch.add_line((0.0, 0.0), (40.0, 0.0))
ed.set_tool("dimension")
pump()

errors = []
for target in [("entity", line), ("point", sketch.entities[line].p1)
               if hasattr(sketch.entities[line], "p1") else ("entity", line)]:
    ed._pending = [target]
    for u, v in [(10.0, 5.0), (12.0, 0.1), (0.1, 20.0), (30.0, -8.0)]:
        try:
            ed._on_move(u, v, NONE)
        except Exception as exc:
            errors.append("%s %s: %s" % (target[0], type(exc).__name__, exc))
check("no error on any move, whatever was picked first", not errors, errors)

print("and a real pick, then moves")
ed._pending = []
ed._dim_target = None
errors = []
try:
    ed._on_move(20.0, 0.0, NONE)
    ed._on_click(20.0, 0.0, NONE)
    pump(1)
    for u, v in [(20.0, 6.0), (22.0, 9.0), (25.0, 12.0)]:
        ed._on_move(u, v, NONE)
except Exception as exc:
    errors.append("%s: %s" % (type(exc).__name__, exc))
check("picking the line and moving raises nothing", not errors, errors)
check("something was picked", bool(ed._pending) or ed._dim_target is not None,
      (ed._pending, ed._dim_target))
win.ok_sketch_tool()
pump()

print("line drawing still lines up with the last point")
ed.set_tool("line")
ed._pending = [(0.0, 0.0)]
ed._snap_info = ""
got = ed._snap(30.0, 0.05, NONE) if hasattr(ed, "_snap") else None
check("horizontal from the last point", ed._snap_info == "horizontal",
      (ed._snap_info, got))
ed._pending = []
ed.set_tool("select")

# ==========================================================================
print("#13: one error, one box")

shown = []
real_show = app_module._show_error
app_module._show_error = lambda kind, value, text: shown.append(str(value))
app_module._reported.clear()


def raise_here():
    raise TypeError("unsupported operand")


for _ in range(5):
    try:
        raise_here()
    except TypeError:
        app_module._excepthook(*sys.exc_info())
check("the same error five times shows one box", len(shown) == 1, shown)
try:
    raise ValueError("another")
except ValueError:
    app_module._excepthook(*sys.exc_info())
check("a different error still shows", len(shown) == 2, shown)


def nested(kind, value, text):
    shown.append("outer")
    try:
        raise KeyError("while the box is open")
    except KeyError:
        app_module._excepthook(*sys.exc_info())


app_module._show_error = nested
try:
    raise RuntimeError("third")
except RuntimeError:
    app_module._excepthook(*sys.exc_info())
check("an error while a box is open opens no second box",
      shown.count("outer") == 1 and len(shown) == 3, shown)
app_module._show_error = real_show
app_module._reported.clear()

# ==========================================================================
print("#7: certificates where the distribution keeps them")

check("Fedora's bundle is among the places looked",
      "/etc/pki/tls/certs/ca-bundle.crt" in update.CA_FILES)
check("Debian and Arch's too",
      "/etc/ssl/certs/ca-certificates.crt" in update.CA_FILES)

# one root from this machine's store, written where a distribution
# would keep it, stands in for a Linux system
bundle = os.path.join(WORK, "ca-bundle.crt")
roots = []
if hasattr(ssl, "enum_certificates"):
    roots = [der for der, enc, trust in ssl.enum_certificates("ROOT")
             if enc == "x509_asn"]
if roots:
    with open(bundle, "w", encoding="ascii") as handle:
        for der in roots[:5]:
            handle.write(ssl.DER_cert_to_PEM_cert(der))
    real_files, real_platform = update.CA_FILES, sys.platform
    update.CA_FILES = (os.path.join(WORK, "missing.crt"), bundle)
    sys.modules["certifi"] = None       # as if it were not shipped
    try:
        sys.platform = "linux"
        context = update._context()
        loaded = context.cert_store_stats()["x509_ca"]
    finally:
        sys.platform = real_platform
        update.CA_FILES = real_files
        del sys.modules["certifi"]
    check("the first bundle that exists is loaded", loaded >= 1, loaded)
    check("it still checks certificates",
          context.verify_mode == ssl.CERT_REQUIRED
          and context.check_hostname)
else:
    print("  skip  no certificate store to borrow from")
check("Windows keeps its own store", update._context().verify_mode
      == ssl.CERT_REQUIRED)

# ==========================================================================
print("#9: dProperties closes")

win.new_document(prompt=False)
pump()
win.show_properties()
pump()
window = win.properties_window
boxes = window.findChildren(QtWidgets.QDialogButtonBox)
close = boxes[0].button(QtWidgets.QDialogButtonBox.Close) if boxes else None
check("it has a Close button", close is not None, boxes)
check("it is open", window.isVisible())
if close is not None:
    close.click()
    pump()
check("Close closes it", not window.isVisible())
win.show_properties()
pump()
check("and it opens again", window.isVisible())
window.close()
pump()

# ==========================================================================
print("#8: About InventCraft")

texts = [a.text() for a in win.file_menu.actions()]
check("the File menu offers it",
      any(t.startswith("About %s" % APP_NAME) for t in texts), texts)
win.show_about()
pump()
dialog = win.about_dialog
words = " ".join(label.text() for label in
                 dialog.findChildren(QtWidgets.QLabel))
check("it says the version", __version__ in words, words)
check("and where to report things", "github.com/Artis-98/inventcraft" in words)
copy = [b for b in dialog.findChildren(QtWidgets.QPushButton)
        if b.text() == "Copy Version"]
check("a Copy Version button", len(copy) == 1)
if copy:
    copy[0].click()
    check("it copies the version",
          __version__ in QtWidgets.QApplication.clipboard().text(),
          QtWidgets.QApplication.clipboard().text())
dialog.close()

print()
if FAILS:
    print("%d FAILED: %s" % (len(FAILS), ", ".join(FAILS)))
    sys.exit(1)
print("all passed")
sys.exit(0)
