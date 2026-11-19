"""Copy and paste of components between assemblies, and of a part from
its own tab.

Several components box-picked in one assembly, Ctrl+C, then Ctrl+V in
another assembly: the same files are placed there, keeping where they sat
to one another.  A part open in its own tab copies itself (Ctrl+C, or
Copy beside icProperties at the top of its tree) and pastes into an
assembly as a component.  Files copied in Explorer paste the same way.
"""
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
from datum.ui.browser import ModelBrowser                          # noqa: E402
from datum.ui.main_window import MainWindow                        # noqa: E402

FAILS = []
WORK = tempfile.mkdtemp(prefix="datum_copy_paste_")
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


def part(a, b, c, name, folder=WORK):
    doc = Document()
    doc.add_feature(PrimitiveFeature(kind="box", a=str(a), b=str(b), c=str(c)))
    doc.rebuild()
    return doc.save(os.path.join(folder, name))


PLATE = part(80, 60, 10, "plate")
BLOCK = part(30, 30, 20, "block")
PEG = part(8, 8, 40, "peg")


def assembly(name, folder):
    os.makedirs(folder, exist_ok=True)
    asm = AssemblyDocument()
    asm.path = os.path.join(folder, name)
    asm.save(asm.path)
    win.open_path(asm.path)
    settle(500)
    return win.session.active


first = assembly("First.icasm", WORK)
ui = win.assembly_ui
for path in (PLATE, BLOCK, PEG):
    ui.place_library_file(path)
settle(200)
doc = win.assembly
plate, block, peg = doc.occurrences
block.placement.position = [10.0, 5.0, 10.0]
peg.placement.position = [50.0, 20.0, 10.0]
doc.rebuild()
ui.rebuild()
settle(200)

print("box-picked block and peg, copied")
ui.browser.select_occurrences([block.id, peg.id])
win._copy_shortcut()
data = QtWidgets.QApplication.clipboard().mimeData()
check("the clipboard holds them in our format",
      data.hasFormat("application/x-inventcraft-components"))
check("and as files too", sorted(os.path.basename(u.toLocalFile())
                                 for u in data.urls())
      == ["block.icpart", "peg.icpart"],
      [u.toLocalFile() for u in data.urls()])

print("pasted into a second assembly in another folder")
second = assembly("Second.icasm", os.path.join(WORK, "elsewhere"))
win._paste_shortcut()
settle(300)
other = win.assembly
check("two components arrived", len(other.occurrences) == 2,
      len(other.occurrences))
paths = sorted(os.path.basename(other.component_path(o) or "")
               for o in other.occurrences)
check("the same two files, found from the other folder",
      paths == ["block.icpart", "peg.icpart"], paths)
a, b = other.occurrences
check("where they sat to one another is kept",
      [b.placement.position[i] - a.placement.position[i] for i in range(3)]
      == [40.0, 15.0, 0.0], (a.placement.position, b.placement.position))
check("an empty assembly keeps them right where they were",
      a.placement.position == [10.0, 5.0, 10.0], a.placement.position)
check("the first one into an empty assembly is grounded",
      a.grounded and not b.grounded)
check("they are drawn", all(o.shape is not None for o in other.occurrences))

print("pasted again in the same place: moved along, together")
win._paste_shortcut()
settle(300)
c, d = other.occurrences[2:]
check("two more", len(other.occurrences) == 4)
check("still apart from one another the same way",
      [d.placement.position[i] - c.placement.position[i] for i in range(3)]
      == [40.0, 15.0, 0.0], (c.placement.position, d.placement.position))
check("but not inside the first pair",
      c.placement.position[0] > b.placement.position[0],
      (c.placement.position, b.placement.position))

print("a part copied from its own tab")
win.open_path(PLATE)
settle(400)
check("the plate is open as a part", win.in_part)
menu = win.browser.menu_for(win.browser.topLevelItem(0))
labels = [act.text() for act in menu.actions() if act.text()]
check("Copy sits beside icProperties at the top of its tree",
      "Copy" in labels and "icProperties..." in labels
      and labels.index("Copy") == labels.index("icProperties...") + 1,
      labels)
win._copy_shortcut()
win.activate(second)
settle(300)
before = len(win.assembly.occurrences)
win._paste_shortcut()
settle(300)
check("Ctrl+V in the assembly places it",
      len(win.assembly.occurrences) == before + 1)
check("it is the plate", os.path.basename(win.assembly.component_path(
    win.assembly.occurrences[-1]) or "") == "plate.icpart")

print("files copied in Explorer")
mime = QtCore.QMimeData()
mime.setUrls([QtCore.QUrl.fromLocalFile(PEG)])
QtWidgets.QApplication.clipboard().setMimeData(mime)
before = len(win.assembly.occurrences)
win._paste_shortcut()
settle(300)
check("paste as components too", len(win.assembly.occurrences) == before + 1)

print("an assembly does not paste into itself")
win.copy_document()
before = len(win.assembly.occurrences)
win._paste_shortcut()
settle(200)
check("nothing placed", len(win.assembly.occurrences) == before)

print()
print("FAILED: %s" % FAILS if FAILS else "ALL PASSED")
sys.exit(1 if FAILS else 0)
