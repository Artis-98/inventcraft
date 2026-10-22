"""The urgent ones for 0.3.0, found while building DIAL in 0.2.8.

The window drags by its title bar again.  dLogic is cLogic.  Delete takes
every selected relationship.  A pick on an imported part lands where it
was picked, every pick counts, and a big assembly solves only what a
change touches.  Dialogs stay in front and Esc reaches them.  Section View
never carries off a part, and keeps its place in and out of a component
and from tab to tab.  A pattern is one boolean, not one per copy.  End of
Part stays where it is dropped.
"""

import ctypes
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import harness  # noqa: E402,F401

os.environ["DATUM_SETTINGS_ORG"] = "IITEG-tests"

from PySide6 import QtCore, QtGui, QtWidgets                       # noqa: E402
from PySide6.QtTest import QTest                                   # noqa: E402

from OCP.gp import gp_Trsf, gp_Vec                                 # noqa: E402
from OCP.TopLoc import TopLoc_Location                             # noqa: E402

from datum.core import constraints3d, kernel                       # noqa: E402
from datum.core.assembly import (AssemblyConstraint, AssemblyDocument,  # noqa: E402
                                 Occurrence)
from datum.core.constraints3d import MATE, Placement               # noqa: E402
from datum.core.document import Document                           # noqa: E402
from datum.core.features import (CUT, ExtrudeFeature,              # noqa: E402
                                 PatternFeature, SketchFeature)
from datum.core.sketch import STANDARD_PLANES, Sketch              # noqa: E402
from datum.ui import frame                                         # noqa: E402
from datum.ui.main_window import MainWindow                        # noqa: E402
from datum.ui.theme import stylesheet                              # noqa: E402

FAILS = []
WORK = tempfile.mkdtemp(prefix="datum_batch19_")
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOTE = os.path.join(REPO, "examples", "plywood-tote")


def check(name, cond, extra=""):
    print(("  PASS  " if cond else "  FAIL  ") + name
          + (("  " + str(extra)) if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


def near(a, b, tol=1e-6):
    return abs(a - b) <= tol


app = QtWidgets.QApplication(sys.argv)
app.setStyle("Fusion")
app.setStyleSheet(stylesheet())
win = MainWindow()
win.resize(1400, 900)
win.show()


def pump(ms=300):
    t = QtCore.QElapsedTimer()
    t.start()
    while t.elapsed() < ms:
        app.processEvents(QtCore.QEventLoop.AllEvents, 20)


pump(800)

# ------------------------------------------------------------------ #258
print("the title bar drags the window, whichever window is under it")
if sys.platform == "win32":
    from ctypes import wintypes

    top = int(win.winId())
    children = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def collect(hwnd, _param):
        children.append(int(hwnd))
        return True

    ctypes.windll.user32.EnumChildWindows(wintypes.HWND(top), collect, 0)
    check("the window has native children", bool(children), children)
    msg = wintypes.MSG()
    msg.hWnd = children[0] if children else 0
    msg.message = frame.WM_NCHITTEST
    real = win.title_hit
    win.title_hit = lambda point: frame.HT_CAPTION
    check("a child over the caption hands the question on",
          frame.child_hit(win, ctypes.addressof(msg)) == frame.HT_TRANSPARENT)
    win.title_hit = lambda point: frame.HT_TOP
    check("and over the top edge too",
          frame.child_hit(win, ctypes.addressof(msg)) == frame.HT_TRANSPARENT)
    win.title_hit = lambda point: frame.HT_CLIENT
    check("inside, the child answers for itself",
          frame.child_hit(win, ctypes.addressof(msg)) is None)
    msg.hWnd = top
    win.title_hit = lambda point: frame.HT_CAPTION
    check("the main window is answered as before, not here",
          frame.child_hit(win, ctypes.addressof(msg)) is None)
    win.title_hit = real
    check("the filter is installed", getattr(win, "_child_hits", None)
          is not None)
else:
    print("  (Windows only)")

# ------------------------------------------------------------------ #259
print("dLogic is cLogic")
shown = []
for root, _dirs, names in os.walk(os.path.join(REPO, "datum")):
    for name in names:
        if name.endswith(".py"):
            with open(os.path.join(root, name), encoding="utf-8-sig") as f:
                if "dLogic" in f.read():
                    shown.append(name)
check("the old name is gone from the program", not shown, shown)
docks = [d.windowTitle() for d in win.findChildren(QtWidgets.QDockWidget)]
check("the panel is called cLogic", "cLogic" in docks, docks)
check("and so is its guide",
      os.path.exists(os.path.join(REPO, "docs", "CLOGIC.md")))

# ------------------------------------------------------------------ #251
print("a pattern is one boolean per feature")


def sprocket(teeth):
    doc = Document()
    disc = SketchFeature()
    disc.sketch = Sketch(STANDARD_PLANES["XY"], "Disc")
    disc.sketch.add_circle((0, 0), 50)
    doc.add_feature(disc)
    body = ExtrudeFeature()
    body.sketch_id = disc.id
    body.distance = "6"
    doc.add_feature(body)
    tooth = SketchFeature()
    tooth.sketch = Sketch(STANDARD_PLANES["XY"], "Tooth")
    tooth.sketch.add_rectangle((49, -1), (54, 1))
    doc.add_feature(tooth)
    t = ExtrudeFeature()
    t.sketch_id = tooth.id
    t.distance = "6"
    doc.add_feature(t)
    p = PatternFeature()
    p.mode = "circular"
    p.parents = [t.id]
    p.count1 = str(teeth)
    doc.add_feature(p)
    return doc


start = time.perf_counter()
gear = sprocket(100)
gear.rebuild()
took = time.perf_counter() - start
check("a hundred teeth in moments", took < 8.0, "%.1f s" % took)
check("every tooth is there", len(kernel.faces(gear.shape)) == 798,
      len(kernel.faces(gear.shape)))
check("and the volume is the disc and its teeth",
      near(kernel.volume(gear.shape), 51927.9, 0.5),
      kernel.volume(gear.shape))

plate = Document()
sk = SketchFeature()
sk.sketch = Sketch(STANDARD_PLANES["XY"], "Plate")
sk.sketch.add_rectangle((0, 0), (60, 60))
plate.add_feature(sk)
ex = ExtrudeFeature()
ex.sketch_id = sk.id
ex.distance = "5"
plate.add_feature(ex)
hs = SketchFeature()
hs.sketch = Sketch(STANDARD_PLANES["XY"], "Hole")
hs.sketch.add_circle((10, 10), 3)
plate.add_feature(hs)
cut = ExtrudeFeature()
cut.sketch_id = hs.id
cut.distance = "5"
cut.operation = CUT
plate.add_feature(cut)
grid = PatternFeature()
grid.parents = [cut.id]
grid.count1 = grid.count2 = "5"
grid.spacing1 = grid.spacing2 = "10"
plate.add_feature(grid)
plate.rebuild()
check("a grid of holes cuts every one",
      near(kernel.volume(plate.shape), 60 * 60 * 5 - 25 * 3.14159265 * 9 * 5,
           1.0), kernel.volume(plate.shape))

# ------------------------------------------------------------------ #256
print("End of Part stays where it is dropped")
gear.rollback_index = 2          # the tooth's sketch, tucked under its extrude
win.document = gear
win.browser.set_document(gear)
win.browser.refresh()
pump(100)
root = win.browser.topLevelItem(0)
rows = [root.child(i).text(0) for i in range(root.childCount())]
marker = rows.index("End of Part") if "End of Part" in rows else -1
check("the marker sits right under the first extrude",
      marker >= 0 and rows[marker - 1].startswith("Extrude")
      and marker < len(rows) - 1, rows)
gear.rollback_index = None

# ------------------------------------------------------- assemblies, #244 on
print("relationships: delete, picks, solving")
win.open_path(os.path.join(TOTE, "Tote.adat"))
pump(1500)
asm = win.assembly
ui = win.assembly_ui
base = asm.occurrences[0]
side = asm.occurrences[1]
end = asm.occurrences[3]
for occurrence in (side, end):
    occurrence.grounded = False

top = max(kernel.faces(base.shape), key=lambda f: kernel.shape_centre(f)[2])
under_side = min(kernel.faces(side.shape),
                 key=lambda f: kernel.shape_centre(f)[2])
under_end = min(kernel.faces(end.shape),
                key=lambda f: kernel.shape_centre(f)[2])


def relation(a_occ, a_face, b_occ, b_face, offset="0"):
    c = AssemblyConstraint(kind=MATE)
    c.a = asm.attach(a_occ, "face", a_face)
    c.b = asm.attach(b_occ, "face", b_face)
    c.offset = offset
    asm.add_constraint(c)
    return c


for c in list(asm.constraints):
    asm.remove_constraint(c.id)
first = relation(base, top, side, under_side)
second = relation(base, top, end, under_end, "3")
ui.rebuild()
pump(300)
undo_depth = len(asm._undo)

from datum.ui.assembly_browser import ROLE_KIND                    # noqa: E402

browser = ui.browser
browser.clearSelection()
it = QtWidgets.QTreeWidgetItemIterator(browser)
while it.value():
    item = it.value()
    if item.data(0, ROLE_KIND) == "constraint":
        item.setSelected(True)
    it += 1
picked = browser.selected_constraint_ids()
check("both relationships are selected in the tree",
      sorted(picked) == sorted([first.id, second.id]), picked)
browser.setFocus()
QTest.keyClick(browser, QtCore.Qt.Key_Delete)
pump(300)
check("Delete took both", not asm.constraints,
      [c.name for c in asm.constraints])
check("as one step", len(asm._undo) == undo_depth + 1,
      (undo_depth, len(asm._undo)))
win.undo()
pump(300)
check("and one undo puts both back", len(win.assembly.constraints) == 2,
      len(win.assembly.constraints))

# a picked face of a part that carries a location of its own
print("a pick on an imported part lands where it was picked")
shift = gp_Trsf()
shift.SetTranslation(gp_Vec(100.0, 0.0, 0.0))
box = kernel.make_box(10, 10, 10) if hasattr(kernel, "make_box") else None
if box is None:
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    box = BRepPrimAPI_MakeBox(10, 10, 10).Shape()
imported = Occurrence()
imported.shape = box.Moved(TopLoc_Location(shift))     # as a STEP file has it
imported.placement = Placement([0.0, 50.0, 0.0], [0.0, 0.0, 0.3])
face = max(kernel.faces(imported.shape),
           key=lambda f: kernel.shape_centre(f)[2])
picked_face = face.Moved(imported.placement.location())   # as OCCT hands it
local = imported.unplaced(picked_face)
named = AssemblyDocument().attach(imported, "face", local)
check("the placement comes off and the part's own location stays",
      named is not None and kernel.faces(imported.shape)[named.ref.index]
      .IsSame(face), named.ref.index if named else None)
check("so the face is where the part has it",
      all(near(a, b) for a, b in zip(kernel.shape_centre(local),
                                      (105.0, 5.0, 10.0))),
      kernel.shape_centre(local))

print("a big assembly solves only what a change touches")
placements = {0: Placement()}
for k in range(1, 121):
    placements[k] = Placement([k * 20.0, 0.0, 15.0], [0.0, 0.0, 0.0])
frame_up = constraints3d.Frame("plane", (0.0, 0.0, 0.0), (0.0, 0.0, 1.0),
                               0.0, "top")
frame_down = constraints3d.Frame("plane", (0.0, 0.0, 0.0), (0.0, 0.0, -1.0),
                                 0.0, "under")
tie = constraints3d.ResolvedConstraint(
    id=1, kind=MATE, occ_a=0, occ_b=7, frame_a=frame_up, frame_b=frame_down,
    offset=4.0, flip=False)
before = {k: list(p.position) for k, p in placements.items()}
start = time.perf_counter()
solved = constraints3d.solve(placements, [tie], list(range(1, 121)))
took = time.perf_counter() - start
check("one relationship among 120 loose parts solves at once", took < 2.0,
      "%.2f s" % took)
check("and is satisfied", solved.ok, solved.message)
check("the tied part sits at the offset",
      near(placements[7].position[2], 4.0, 1e-4), placements[7].position)
check("the loose ones did not move", all(
    placements[k].position == before[k] for k in range(1, 121) if k != 7))
check("the freedom left is counted for all of them",
      solved.dof == 6 * 119 + 3, solved.dof)

print("a change to a relationship moves pictures, not the whole assembly")
redraws = []
real_show = ui.show_components
ui.show_components = lambda *a, **k: (redraws.append(1), real_show(*a, **k))
c = win.assembly.constraints[0]
c.offset = "7"
ui.resolve()
pump(200)
check("solved without drawing every component again", not redraws,
      len(redraws))
moved = win.assembly.occurrence(c.b.occurrence)
seat = moved.placement.apply_point(c.b.frame.origin)
check("the part followed the offset", near(seat[2], 15.0 + 7.0, 1e-3)
      or near(seat[2] - win.assembly.world_frame(c.a).origin[2], 7.0, 1e-3),
      seat)
ui.show_components = real_show

# ------------------------------------------------------------------ #246
print("dialogs stay in front and on screen, and Esc reaches them")
ui.constrain(MATE)
pump(300)
dialog = ui.dialog
check("Place Constraint is open", dialog is not None)
screen = win.screen().availableGeometry()
check("it opened on screen", screen.contains(dialog.frameGeometry().topLeft()),
      (dialog.frameGeometry(), screen))
raised = []
dialog.raise_ = lambda: raised.append(1)
win._raise_dialogs()
check("activating the window brings it back in front", raised)
del dialog.raise_
combo = win.findChildren(QtWidgets.QComboBox)[0]
combo.setFocus()
pump(100)
QTest.keyClick(combo, QtCore.Qt.Key_Escape)
pump(300)
check("Esc closes it even with the keyboard in a field of the window",
      ui.dialog is None)

# ------------------------------------------------------------- #248, #249
print("Section View in an assembly")
win.section_btn.setChecked(True)
pump(200)
check("while it waits for a face, no part can be dragged off",
      not ui._free_drag_allowed(side.id))
win._end_section(keep=False)
pump(100)
check("afterwards a loose part drags again",
      ui._free_drag_allowed(win.assembly.occurrences[1].id)
      == ui.freely_movable(win.assembly.occurrences[1].id))

plane = STANDARD_PLANES["XY"]
win._section = {"plane": plane, "keep": (0.0, 0.0, 1.0)}
win._section_carry = None
bar = win._section_toolbar()
bar.offset, bar.angle, bar.flipped = 12.0, 0.0, False
bar.set_offset(12.0)
win.section_btn.blockSignals(True)
win.section_btn.setChecked(True)
win.section_btn.blockSignals(False)
win._apply_section()


def clip():
    plane_now = win.viewport._clips["section"].ToPlane()
    p = plane_now.Location()
    n = plane_now.Axis().Direction()
    return (p.X(), p.Y(), p.Z()), (n.X(), n.Y(), n.Z())


in_assembly = clip()
check("the cut is 12 up in the assembly", near(in_assembly[0][2], 12.0))
target = win.assembly.occurrences[1]
where = target.placement
win.edit_in_place(target.id)
pump(800)
inside = clip()
expected = where.trsf().Inverted()
from OCP.gp import gp_Pnt                                          # noqa: E402
spot = gp_Pnt(*in_assembly[0]).Transformed(expected)
check("editing the part in place, the cut stays where it was",
      abs((inside[0][0] - spot.X()) * inside[1][0]
          + (inside[0][1] - spot.Y()) * inside[1][1]
          + (inside[0][2] - spot.Z()) * inside[1][2]) < 1e-6,
      (inside, (spot.X(), spot.Y(), spot.Z())))
win.finish_in_place()
pump(800)
back = clip()
check("and comes back unchanged", all(near(a, b) for a, b in zip(
    back[0] + back[1], in_assembly[0] + in_assembly[1])), (back, in_assembly))

assembly_tab = win.session.active
win.new_document(prompt=False)
pump(500)
check("a new part's tab has no cut",
      "section" not in getattr(win.viewport, "_clips", {})
      and not win.section_btn.isChecked())
win.activate(assembly_tab)
pump(800)
again = clip() if "section" in win.viewport._clips else None
check("back on the assembly's tab, its cut is back where it was",
      again is not None and all(near(a, b) for a, b in zip(
          again[0] + again[1], in_assembly[0] + in_assembly[1])), again)
win._end_section(keep=False)

print()
if FAILS:
    print("%d FAILURES: %s" % (len(FAILS), ", ".join(FAILS)))
    sys.exit(1)
print("all batch 19 tests passed")
sys.exit(0)
