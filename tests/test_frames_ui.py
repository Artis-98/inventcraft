"""The Frame Generator in the window: the Design tab, Insert Frame with
lines clicked in the view, the frame following its skeleton, and the
Profile Library."""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import harness  # noqa: E402,F401

os.environ.setdefault("DATUM_SETTINGS_ORG", "IITEG-tests")
WORK = tempfile.mkdtemp(prefix="datum_frames_ui_")
os.environ["DATUM_PROFILE_LIBRARY"] = os.path.join(WORK, "profiles")

from PySide6 import QtCore, QtGui, QtWidgets                       # noqa: E402

from datum.core import frames, kernel                             # noqa: E402
from datum.core.assembly import AssemblyDocument                  # noqa: E402
from datum.core.document import Document                          # noqa: E402
from datum.core.features import (                                 # noqa: E402
    ExtrudeFeature, HoleFeature, SketchFeature)
from datum.core.sketch import (                                   # noqa: E402
    STANDARD_PLANES, Sketch, SketchPlane)
from datum.ui import frames_ui                                    # noqa: E402
from datum.ui.assembly_browser import ROLE_ID, ROLE_KIND          # noqa: E402
from datum.ui.main_window import TAB_DESIGN, MainWindow           # noqa: E402
from datum.ui.theme import stylesheet                              # noqa: E402

FAILS = []
SHOTS = os.environ.get("DATUM_SHOTS", "")


def check(name, cond, extra=""):
    print(("  PASS  " if cond else "  FAIL  ") + name
          + (("  " + str(extra)) if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


def near(a, b, tol=1e-3):
    return abs(a - b) < tol


app = QtWidgets.QApplication(sys.argv)
app.setStyle("Fusion")
app.setStyleSheet(stylesheet())
win = MainWindow()
win.resize(1400, 900)
win.show()
app.processEvents()


def pump(n=4):
    for _ in range(n):
        app.processEvents()


def settle(ms=400):
    loop = QtCore.QEventLoop()
    QtCore.QTimer.singleShot(ms, loop.quit)
    loop.exec()


# a table's skeleton: its top, a rectangle at 750
skeleton = Document()
top = SketchFeature(name="Top")
top.sketch = Sketch(SketchPlane((0.0, 0.0, 750.0), (0.0, 0.0, 1.0)), "Top")
top.sketch.add_rectangle((0.0, 0.0), (1000.0, 600.0))
skeleton.add_feature(top)
skeleton.rebuild()
skeleton_path = skeleton.save(os.path.join(WORK, "Table skeleton"))
table = AssemblyDocument()
table.path = os.path.join(WORK, "Table.icasm")
table.place(skeleton_path)
table.save(table.path)

# ==========================================================================
print("the Design tab")
win.open_path(table.path)
settle(800)
check("an assembly has the Design tab", win.ribbon._buttons[TAB_DESIGN]
      .isVisible())

print("the part's sketch shows in the assembly")
lines = win.assembly_ui.component_sketch_lines()
check("its four lines are there to pick, where the part sits",
      len(lines) == 4 and all(near(a[2], 750) for a, _b in lines.values()),
      lines)

print("Insert Frame")
dialog = win.insert_frame()
pump()
check("no skeleton or sketch to choose first: the lines are the input",
      not hasattr(dialog, "skeleton") and len(dialog.candidates()) == 4)
check("the families are offered by category",
      [dialog.category.itemText(i) for i in range(dialog.category.count())]
      [:2] == ["Angles", "Square Tubes"])
check("it starts with none selected",
      dialog.count.text() == "No lines selected", dialog.count.text())
win.viewport.set_view("top")
win.viewport.fit_all()
settle(400)
pump()


def mouse(kind, x, y, buttons=None):
    pos = QtCore.QPointF(x, y)
    held = (QtCore.Qt.LeftButton if kind != QtCore.QEvent.MouseButtonRelease
            else QtCore.Qt.NoButton) if buttons is None else buttons
    event = QtGui.QMouseEvent(kind, pos, win.viewport.mapToGlobal(pos),
                              QtCore.Qt.LeftButton if kind !=
                              QtCore.QEvent.MouseMove else QtCore.Qt.NoButton,
                              held, QtCore.Qt.NoModifier)
    return dialog.eventFilter(win.viewport, event)


# a click on a line in the view picks it
first = next(iter(lines))
a, b = lines[first]
x, y = win.viewport.project(tuple((a[i] + b[i]) / 2 for i in range(3)))
eaten = mouse(QtCore.QEvent.MouseButtonPress, x, y)
mouse(QtCore.QEvent.MouseButtonRelease, x, y)
check("a click on a line in the view picks it", dialog.picked() == [first],
      dialog.picked())
check("the view does not get the click as well", eaten)
check("and it says so", dialog.count.text() == "1 line selected",
      dialog.count.text())
mouse(QtCore.QEvent.MouseButtonPress, x, y)
mouse(QtCore.QEvent.MouseButtonRelease, x, y)
check("clicked again, it is dropped", dialog.picked() == [])
if SHOTS:
    win.viewport.grab_image(os.path.join(SHOTS, "frame_pick.png"))
# a box dragged over the whole lot, left to right: all four in it
w, h = win.viewport.width(), win.viewport.height()
mouse(QtCore.QEvent.MouseButtonPress, 2, 2)
mouse(QtCore.QEvent.MouseMove, w / 2, h / 2)
mouse(QtCore.QEvent.MouseMove, w - 2, h - 2)
mouse(QtCore.QEvent.MouseButtonRelease, w - 2, h - 2)
check("a box dragged over them takes all four",
      len(dialog.picked()) == 4 and dialog.count.text() == "4 lines selected",
      dialog.count.text())
dialog.clear()
check("Clear drops them", dialog.picked() == [])
# a box over half of it, left to right: only the line wholly inside
pa = win.viewport.project((0.0, 0.0, 750.0))
pb = win.viewport.project((1000.0, 600.0, 750.0))
xs, ys = sorted((pa[0], pb[0])), sorted((pa[1], pb[1]))
left = (xs[0] - 20, ys[0] - 20)
mid_x = (xs[0] + xs[1]) / 2
window = dialog.lines_in_box(QtCore.QPoint(*map(int, left)),
                             QtCore.QPoint(int(mid_x), int(ys[1] + 20)))
crossing = dialog.lines_in_box(QtCore.QPoint(int(mid_x), int(ys[1] + 20)),
                               QtCore.QPoint(*map(int, left)))
check("left to right takes what is wholly inside: the left end",
      len(window) == 1, window)
check("right to left takes what it touches: three", len(crossing) == 3,
      crossing)
dialog.add_lines(list(dialog.candidates()))
check("the members it will make, in see-through green",
      dialog.draw_preview() == 4 and len(dialog._ghosts) == 4)
check("a family and size are chosen",
      dialog.choose("din-en-10219-2-square", "40 x 40 x 3"))
check("it applies", dialog.apply(), dialog.message.text())
pump()
asm = win.assembly
frame_occurrences = [o for o in asm.occurrences if o.follows]
check("the frame is placed, following the skeleton",
      len(frame_occurrences) == 1)
box = kernel.bounding_box(asm.shape)
check("four tubes round the top", near(box[0], -20, 0.05)
      and near(box[3], 1020, 0.05) and near(box[5], 770, 0.05),
      [round(c, 2) for c in box])
check("the selection is cleared for the next lot", dialog.picked() == [])
dialog.close()
pump()
if SHOTS:
    win.viewport.set_view("iso")
    win.viewport.fit_all()
    settle(500)
    win.viewport.grab_image(os.path.join(SHOTS, "frame_table.png"))

print("the skeleton edited in place, not saved: the frame follows")
skeleton_occurrence = next(o for o in win.assembly.occurrences
                           if not o.follows)
live = win._in_place_document(win.assembly.component_path(skeleton_occurrence))
sid = next(iter(live.all_sketches()))
feature = live.feature(sid)
for point in feature.sketch.points.values():
    if near(point.y, 600.0):
        point.y = 800.0
live.rebuild()
win.assembly_ui.rebuild()
pump()
box = kernel.bounding_box(win.assembly.shape)
check("the frame is 800 deep now", near(box[4], 820, 0.05), box)
check("and its sketch is drawn where it now is", any(
    near(a[1], 800) or near(b[1], 800)
    for a, b in win.assembly_ui.component_sketch_lines().values()))
live.modified = False
win._in_place_docs.clear()

print("a sketch hidden in the part is hidden in the assembly too")
part = Document.load(skeleton_path)
part.set_sketch_visible(sid, False)
part.save(skeleton_path)
win._browse_docs.clear()
reread = Document.load(skeleton_path)
check("hiding a sketch is kept in the part", sid in reread.hidden_sketches)
check("its lines are not offered in the assembly",
      win.assembly_ui.component_sketch_lines() == {})
part.set_sketch_visible(sid, True)
part.save(skeleton_path)
win._browse_docs.clear()

# ==========================================================================
print("the frame in the tree")
win.assembly_ui.rebuild()
pump()
asm = win.assembly
frame_occurrence = next(o for o in asm.occurrences if o.follows)
frame_oid = frame_occurrence.id
frame_path = asm.component_path(frame_occurrence)
tree = win.assembly_ui.browser
check("the frame has an icon of its own",
      tree._icon_of(frame_occurrence) == "frame_assembly"
      and tree._icon_of(next(o for o in asm.occurrences
                             if not o.follows)) == "box")
fd = frames.read_frame(frame_path)
member_path = os.path.join(os.path.dirname(frame_path), fd.members[0].part)
check("and its members' parts are known for what they are",
      frames.is_member_part(member_path)
      and not frames.is_member_part(skeleton_path))
root = tree.topLevelItem(0)
frame_item = next(root.child(i) for i in range(root.childCount())
                  if root.child(i).data(0, ROLE_KIND) == "occurrence"
                  and root.child(i).data(0, ROLE_ID) == frame_oid)
member_items = [frame_item.child(i) for i in range(frame_item.childCount())
                if frame_item.child(i).data(0, ROLE_KIND) == "frame_member"]
check("its four members are listed under it", len(member_items) == 4,
      len(member_items))
tree.clearSelection()
for item in member_items[:2]:
    item.setSelected(True)
owner, picked_ids = tree.selected_frame_members()
check("two members picked in the tree", owner == frame_oid
      and len(picked_ids) == 2, (owner, picked_ids))
menu = QtWidgets.QMenu()
tree._frame_menu(menu, owner, picked_ids)
labels = [a.text() for a in menu.actions() if a.text()]
check("the right click menu has Change Frame and the end treatments",
      labels[:2] == ["2 frame members", "Change Frame..."]
      and "Miter..." in labels and "Corner Joint..." in labels
      and "Notch..." in labels and "Remove End Treatments" in labels, labels)

print("Change Frame")
dialog = win.frame_action("change", owner, picked_ids)
pump()
check("it opens on the members picked in the tree",
      dialog.count.text() == "2 members selected", dialog.count.text())
check("with their size as it is", dialog.size.currentText() == "40 x 40 x 3",
      dialog.size.currentText())
check("nothing changed yet", dialog.changes() == {}, dialog.changes())
win.viewport.set_view("top")
win.viewport.fit_all()
settle(300)
check("a green picture of the picked members", dialog.draw_preview() == 2
      and len(dialog._ghosts) == 2)
if SHOTS:
    dialog.size.setCurrentText("80 x 80 x 5")
    dialog.draw_preview()
    win.viewport.set_view("iso")
    win.viewport.fit_all()
    settle(400)
    win.viewport.grab_image(os.path.join(SHOTS, "frame_change_preview.png"))
    dialog.size.setCurrentText("40 x 40 x 3")
    win.viewport.set_view("top")
    win.viewport.fit_all()
    settle(300)
# a third member clicked in the view
third = ("m", frame_oid, fd.members[2].id) \
    if fd.members[2].id not in picked_ids else ("m", frame_oid,
                                                fd.members[3].id)
a, b = dialog.candidates()[third]
x, y = win.viewport.project(tuple((a[i] + b[i]) / 2 for i in range(3)))
mouse(QtCore.QEvent.MouseButtonPress, x, y)
mouse(QtCore.QEvent.MouseButtonRelease, x, y)
check("a member clicked in the view joins them",
      dialog.count.text() == "3 members selected", dialog.count.text())
dialog.size.setCurrentText("60 x 60 x 4")
check("only what was changed is changed",
      dialog.changes() == {"size": "60 x 60 x 4"}, dialog.changes())
check("it applies", dialog.apply(), dialog.message.text())
fd = frames.read_frame(frame_path)
sizes = sorted(m.size for m in fd.members)
check("three members are 60 x 60 x 4 now, one is as it was",
      sizes == ["40 x 40 x 3"] + ["60 x 60 x 4"] * 3, sizes)
dialog.close()
pump()

print("Miter, from the ribbon, members picked after")
dialog = win.end_treatment("miter")
pump()
ids = [m.id for m in fd.members]
corner_pair = None
for i in ids:
    for j in ids:
        if i < j:
            ma, mb = fd.member(i), fd.member(j)
            la = frames.run_of(frames.skeleton_sketches(
                skeleton_path)[ma.sketch][2], ma.lines)
            lb = frames.run_of(frames.skeleton_sketches(
                skeleton_path)[mb.sketch][2], mb.lines)
            if any(near(p[0], q[0]) and near(p[1], q[1])
                   for p in la for q in lb) and corner_pair is None:
                corner_pair = [i, j]
dialog.pick(corner_pair)
check("two members that meet are picked",
      dialog.slots[0] == corner_pair, dialog.slots)
check("the green picture shows them mitered", dialog.draw_preview() == 2)
check("it applies", dialog.apply(), dialog.message.text())
fd = frames.read_frame(frame_path)
check("the frame keeps the miter", [t.kind for t in fd.treatments]
      == ["miter"])
if SHOTS:
    win.viewport.set_view("iso")
    win.viewport.fit_all()
    settle(500)
    win.viewport.grab_image(os.path.join(SHOTS, "frame_mitered.png"))
dialog.close()

print("Trim - Extend To Face")
dialog = win.end_treatment("trim_face", frame_oid, [corner_pair[0]])
pump()
dialog.set_face((500.0, 0.0, 0.0), (1.0, 0.0, 0.0))
check("a face and a member", dialog.face is not None
      and dialog.slots[0] == [corner_pair[0]])
check("it applies", dialog.apply(), dialog.message.text())
dialog.close()

print("Remove End Treatments")
gone = win.frame_action("remove", frame_oid, corner_pair)
check("both treatments on those members gone", gone == 2
      and not frames.read_frame(frame_path).treatments, gone)

print("Inventor's folders")
check("the frame is in Table/Frame0001, beside the assembly",
      os.path.normcase(os.path.dirname(frame_path)) == os.path.normcase(
          os.path.join(WORK, "Table", "Frame0001")), frame_path)

print("the pointer over a row in the tree lights it up in the view")
win.assembly_ui.rebuild()
pump()
fd = frames.read_frame(frame_path)
ids = [m.id for m in fd.members]
root = tree.topLevelItem(0)
frame_item = next(root.child(i) for i in range(root.childCount())
                  if root.child(i).data(0, ROLE_KIND) == "occurrence"
                  and root.child(i).data(0, ROLE_ID) == frame_oid)
member_item = next(frame_item.child(i) for i in range(frame_item.childCount())
                   if frame_item.child(i).data(0, ROLE_KIND) == "frame_member")
tree._entered(member_item, 0)
lit = win.assembly_ui._hover_drawn
check("a member's row lights up that member", len(lit) == 1)
if lit:
    x0, y0, _z0, x1, y1, _z1 = kernel.bounding_box(lit[0].Shape())
    check("and only it, not the whole frame", min(x1 - x0, y1 - y0) < 100,
          (x1 - x0, y1 - y0))
tree._entered(frame_item, 0)
check("a component's row lights up the component",
      len(win.assembly_ui._hover_drawn) == 1)
tree._set_hovered(("", 0, 0))
check("off the tree, nothing is lit", not win.assembly_ui._hover_drawn)

print("right click on a member in the view")
win.viewport.set_view("top")
win.viewport.fit_all()
settle(300)
axes = frames.member_axes(frames.open_frame(frame_path))
a, b, _reach = axes[ids[1]]
x, y = win.viewport.project(frame_occurrence.placement.apply_point(
    tuple((a[i] + b[i]) / 2 for i in range(3))))
win.viewport._menu_pos = QtCore.QPoint(int(x), int(y))
check("the member under the pointer is found",
      win.assembly_ui.frame_members_at_menu([frame_oid])
      == (frame_oid, [ids[1]]))
menu = QtWidgets.QMenu()
win.assembly_ui.context_menu(menu)
labels = [act.text() for act in menu.actions() if act.text()]
check("its menu has Change Frame", labels[:2] == ["1 frame member",
                                                  "Change Frame..."], labels)

print("in the frame itself")
win.edit_in_place(frame_oid)
settle(300)
check("stepped into the frame", getattr(win.assembly, "frame", None)
      is not None)
member_occurrence = win.assembly.frame.member(ids[0]).occurrence
tree.select_occurrences([member_occurrence])
owner, picked_ids = tree.selected_frame_members()
check("its parts are its members", owner == frames_ui.SELF
      and picked_ids == [ids[0]], (owner, picked_ids))
check("right clicked in the view, the same",
      win.assembly_ui.frame_members_at_menu([member_occurrence])
      == (frames_ui.SELF, [ids[0]]))
dialog = win.frame_action("change", owner, picked_ids)
pump()
check("Change Frame opens on it there",
      dialog.count.text() == "1 member selected", dialog.count.text())
check("with its green picture", dialog.draw_preview() == 1)
dialog.close()
win.finish_in_place()
settle(300)

print("Change Frame after the frame was edited in place")
before = kernel.bounding_box(win.assembly.shape)
dialog = win.frame_action("change", frame_oid, ids)
dialog.anchor_buttons["tl"].setChecked(True)
check("a new placement applies", dialog.apply(), dialog.message.text())
dialog.close()
after = kernel.bounding_box(win.assembly.shape)
check("and the members move to it",
      max(abs(p - q) for p, q in zip(before, after)) > 5, (before, after))

print("a member is a part to work on")
member_path = win.frame_action("open", frame_oid, [ids[0]])
settle(300)
part = win.session.by_path(member_path).document
plain = kernel.volume(part.shape)
centres = SketchFeature()
centres.sketch = Sketch(STANDARD_PLANES["XZ"], "Hole")
centres.sketch.add_circle((0, 100), 5)
part.add_feature(centres)
hole = HoleFeature()
hole.sketch_id = centres.id
hole.diameter = "10"
hole.depth = "100"
hole.through = True
part.add_feature(hole)
part.rebuild()
part.save(member_path)
check("it opens as a part, and takes a hole",
      kernel.volume(part.shape) < plain - 100)
check("made as Inventor makes one: a profile sketch, extruded",
      [f.type_name for f in part.features][:3]
      == ["sketch", "extrude", "frame_ends"])
win.new_feature(ExtrudeFeature)
pump()
extrude_dialog = win._active_dialog
check("Extrude on it offers Join, Cut and New Solid: the member is a solid",
      extrude_dialog is not None and not extrude_dialog.makes_first_solid()
      and extrude_dialog.operation is not None)
extrude_dialog.cancel() if hasattr(extrude_dialog, "cancel") \
    else extrude_dialog.reject()
pump()
win.activate(win.session.by_path(table.path))
settle(300)
size = "50 x 50 x 4"
dialog = win.frame_action("change", frame_oid, [ids[0]])
dialog.size.setCurrentText(size)
check("a new size applies", dialog.apply(), dialog.message.text())
dialog.close()
member = frames.read_frame(frame_path).member(ids[0])
renamed = os.path.join(os.path.dirname(frame_path), member.part)
again = Document.load(renamed)
check("the part is named for its new size, the hole still in it",
      size in member.part and any(isinstance(f, HoleFeature)
                                  for f in again.features), member.part)
check("the old name is gone", not os.path.exists(member_path))
check("and the tab open on it follows it", os.path.normcase(part.path)
      == os.path.normcase(renamed), part.path)

print("the Profile Library")
library = win.profile_library()
pump()
names = []
for i in range(library.tree.topLevelItemCount()):
    group = library.tree.topLevelItem(i)
    names += [group.child(j).text(0) for j in range(group.childCount())]
check("it shows the families", any("10056-1" in n for n in names)
      and any("10219-2" in n for n in names), names)
check("a built in family's table is read only",
      library.current.builtin and not library.save_button.isEnabled())
check("its sizes are in the table", library.table.rowCount()
      == len(library.current.rows))
library.fill("din-en-10219-2-square")
mine = library.copy("Workshop tubes")
check("Copy makes it your own", mine is not None and not mine.builtin
      and library.save_button.isEnabled())
library.table.setRowCount(1)
for c, value in enumerate(["30x30x2", "30", "2", "3"]):
    library.table.setItem(0, c, QtWidgets.QTableWidgetItem(value))
check("your own sizes save", library.save())
check("and are in the library", frames.family("workshop-tubes").row(
    "30x30x2") == {"b": 30.0, "t": 2.0, "ro": 3.0})
library.table.setItem(0, 1, QtWidgets.QTableWidgetItem("thirty"))
check("a size that is not a number is refused, saying which",
      not library.save() and "30x30x2" in library.message.text())
library.close()

print()
if FAILS:
    print("%d FAILED: %s" % (len(FAILS), ", ".join(FAILS)))
    sys.exit(1)
print("all passed")
sys.exit(0)
