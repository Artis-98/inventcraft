"""Place from Library, beside Place, as Inventor's Content Center (#84).

The Assemble tab's Place is a split button: Place Component and Place from
Library.  The library window lays out its shelves and hands over to Place
Component for a file already on disk.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import harness  # noqa: E402,F401

os.environ.setdefault("DATUM_SETTINGS_ORG", "IITEG-tests")

from PySide6 import QtCore, QtWidgets  # noqa: E402

from datum.ui.library_dialog import LibraryDialog  # noqa: E402
from datum.ui.main_window import MainWindow  # noqa: E402
from datum.ui.theme import stylesheet  # noqa: E402

FAILS = []

app = QtWidgets.QApplication(sys.argv)
app.setStyle("Fusion")
app.setStyleSheet(stylesheet())
win = MainWindow()
win.resize(1200, 800)
win.show()
app.processEvents()


def check(name, cond, extra=""):
    print(("  PASS  " if cond else "  FAIL  ") + name
          + (("  " + str(extra)) if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


print("the Place button")
button = win.place_button
check("has both variants", button.keys == ["place", "library"], button.keys)
check("is a plain button, not a tool that stays down",
      not button.isCheckable())
check("reads Place Component", "Place" in button.text(), button.text())

print("choosing each")
calls = []
win.assembly_ui.place_component = lambda: calls.append("file")


seen = []
click = {"file": False}


def fake_exec(dialog, *args, **kwargs):
    """The harness rejects every modal; this one is looked at first."""
    seen.append(dialog)
    if click["file"]:
        dialog.from_file.click()
        return QtWidgets.QDialog.Accepted
    return QtWidgets.QDialog.Rejected


LibraryDialog.exec = fake_exec

win._place_chosen("place")
check("Place opens Place Component", calls == ["file"], calls)

calls.clear()
win._place_chosen("library")
check("the library window opened", len(seen) == 1)
check("closing it places nothing", calls == [], calls)

click["file"] = True
win._place_chosen("library")
check("Place Component from inside it hands over", calls == ["file"], calls)

print("the shelves")
from datum.core import frames, kernel                          # noqa: E402
from datum.core import standard_parts as sp                     # noqa: E402
from datum.ui.library_dialog import (ROLE_FAMILY,               # noqa: E402
                                     StandardPartDialog)
dialog = LibraryDialog()
tops = [dialog.tree.topLevelItem(i).text(0)
        for i in range(dialog.tree.topLevelItemCount())]
check("profiles, fasteners and the shelves to come",
      tops[:2] == ["Structural Shapes", "Fasteners"]
      and "Online libraries" in tops and "Bearings" in tops, tops)


def leaves(item):
    out = []
    for i in range(item.childCount()):
        child = item.child(i)
        if child.data(0, ROLE_FAMILY):
            out.append((item.text(0), child.data(0, ROLE_FAMILY)))
        out += leaves(child)
    return out


shapes = leaves(dialog.tree.topLevelItem(0))
check("Structural Shapes are the Frame Generator's own families, the same "
      "ones", sorted(f for _, f in shapes)
      == sorted(f.id for f in frames.families()), shapes)
check("by the Frame Generator's categories", all(
    shelf == frames.family(f).category for shelf, f in shapes), shapes)
bolts = leaves(dialog.tree.topLevelItem(1))
check("bolts, nuts and washers by ISO standard",
      {f for _, f in bolts} >= {"iso-4017", "iso-4762", "iso-4032",
                                "iso-7089"}, bolts)
coming = dialog.tree.findItems("GrabCAD and others",
                               QtCore.Qt.MatchExactly | QtCore.Qt.MatchRecursive)
dialog.tree.setCurrentItem(coming[0])
check("a shelf still empty says what is coming",
      "GrabCAD" in dialog.state.text() and not dialog.select.isVisible())

print("the size window")
angle = sp.family(frames.families()[0].id)
sizer = StandardPartDialog(None, angle, angle.sizes()[2], 750)
check("lists every size", sizer.table.rowCount() == len(angle.rows))
check("starts on the size given", sizer.size() == angle.sizes()[2])
check("and the length", sizer.length.currentText() == "750")
sizer.table.selectRow(4)
sizer.length.setEditText("1234")
sizer._ok()
check("hands back what was picked", sizer.chosen == {
    "family": angle.id, "size": angle.sizes()[4], "length": 1234.0},
    sizer.chosen)
washer = StandardPartDialog(None, sp.family("iso-7089"), "M8")
check("a washer has no length to ask", washer.length is None)

print("placed in an assembly")
import tempfile                                                 # noqa: E402
WORK = tempfile.mkdtemp(prefix="datum_library_")
del win.assembly_ui.place_component
win.new_assembly(prompt=False)
app.processEvents()
win.assembly.path = os.path.join(WORK, "Stand.icasm")
win.save_document()
app.processEvents()
doc = win.assembly
bolt = win.assembly_ui.place_standard(sp.spec("iso-4017", "M8", 30))
app.processEvents()
path = doc.component_path(bolt) if bolt else ""
check("a bolt is placed", bolt is not None and len(doc.occurrences) == 1)
check("its part is written in a Library folder beside the assembly",
      os.path.dirname(path) == os.path.join(WORK, "Library")
      and os.path.basename(path).startswith("ISO 4017 M8 x 30"), path)
box = kernel.bounding_box(bolt.shape)
check("30 long under a 5.3 head, 13 across flats",
      abs(box[2] + 30) < 0.01 and abs(box[5] - 5.3) < 0.01
      and abs((box[4] - box[1]) - 13) < 0.01, box)
beam = win.assembly_ui.place_standard(
    sp.spec(angle.id, angle.sizes()[0], 600))
app.processEvents()
check("a profile is placed the same way, 600 long", beam is not None and
      abs(kernel.bounding_box(beam.shape)[5]
          - kernel.bounding_box(beam.shape)[2] - 600) < 0.01)
again = win.assembly_ui.place_standard(sp.spec("iso-4017", "M8", 30))
app.processEvents()
check("the same size again uses the same file",
      doc.component_path(again) == path)

print("Change Size")
check("the component menu offers it",
      sp.spec_of(doc.component_path(bolt)) is not None)
win.assembly_ui.change_size(bolt.id, sp.spec("iso-4017", "M10", 40))
app.processEvents()
moved = doc.component_path(bolt)
check("the bolt is an M10 x 40 now", os.path.basename(moved)
      .startswith("ISO 4017 M10 x 40"), moved)
box = kernel.bounding_box(bolt.shape)
check("and is that size", abs(box[2] + 40) < 0.01
      and abs((box[4] - box[1]) - 16) < 0.01, box)
check("the other one is still M8", doc.component_path(again) == path)
win.undo()
app.processEvents()
back = win.assembly.occurrence(bolt.id)
check("undo gives the M8 back", back is not None and win.assembly
      .component_path(back) == path)

print()
if FAILS:
    print("%d FAILED" % len(FAILS))
    sys.exit(1)
print("all passed")
