"""A part edited inside an assembly shows its Solid Bodies and Model
States in the assembly's tree, as its own tree does, and their right click
does the same things there."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import harness  # noqa: E402,F401

os.environ.setdefault("DATUM_SETTINGS_ORG", "IITEG-tests")

from PySide6 import QtCore, QtWidgets                              # noqa: E402

from datum.core.assembly import AssemblyDocument                   # noqa: E402
from datum.core.document import Document                           # noqa: E402
from datum.core.features import PrimitiveFeature                   # noqa: E402
from datum.ui.assembly_browser import ROLE_KIND, ROLE_OWNER        # noqa: E402
from datum.ui.main_window import MainWindow                        # noqa: E402

FAILS = []
WORK = tempfile.mkdtemp(prefix="datum_inplace_tree_")
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
    loop = QtCore.QEventLoop()
    QtCore.QTimer.singleShot(ms, loop.quit)
    loop.exec()


doc = Document()
doc.add_feature(PrimitiveFeature(kind="box", a="40", b="30", c="10"))
doc.rebuild()
PLATE = doc.save(os.path.join(WORK, "plate"))
asm = AssemblyDocument()
asm.path = os.path.join(WORK, "Bench.icasm")
asm.save(asm.path)
win.open_path(asm.path)
settle(600)
ui = win.assembly_ui
ui.place_library_file(PLATE)
settle(300)
oid = win.assembly.occurrences[0].id
win.edit_in_place(oid)
settle(500)
tree = ui.browser


def rows(kind):
    out = []
    for item in tree._iter_items():
        if item.data(0, ROLE_KIND) == kind \
                and item.data(0, ROLE_OWNER) == oid:
            out.append(item)
    return out


check("editing the part in place", win.in_part and bool(win.in_place))
check("its Solid Bodies folder is in the assembly tree",
      len(rows("bodies")) == 1)
check("with its one body", len(rows("body")) == 1)
check("its Model States folder too", len(rows("states")) == 1)
check("listing Primary", [r.data(0, QtCore.Qt.UserRole + 1)
                          for r in rows("state")] == ["Primary"])

tree.model_state_requested.emit("new", "", "")
settle(300)
names = win.document.model_states.names()
check("New Model State from there makes one in the part",
      len(names) == 2, names)
check("and the tree lists both", len(rows("state")) == 2)
check("still in the part, in the assembly", win.in_part and bool(win.in_place))

body = rows("body")[0].data(0, QtCore.Qt.UserRole + 1)
tree.body_visibility_requested.emit("hide", body)
settle(200)
check("Hide on a body hides it in the part",
      not win.document.body_visible(body))
check("and the row says so", "(hidden)" in rows("body")[0].text(0))
tree.body_visibility_requested.emit("all", body)
settle(200)
check("Show All brings it back", win.document.body_visible(body))

win.finish_in_place()
settle(300)
check("back in the assembly the folders are gone",
      not rows("bodies") and not rows("states"))

print()
print("FAILED: %s" % FAILS if FAILS else "ALL PASSED")
sys.exit(1 if FAILS else 0)
