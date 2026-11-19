"""Ctrl+Z in an assembly goes back one action, Ctrl+Y forward one.

Placing a part, placing a bolt from the library, each constraint (three
placed in one Place Constraint window with Apply are three steps, not
one), grounding and deleting: each is undone on its own, newest first,
and done again in order.  A constraint window opened and cancelled leaves
no step that does nothing.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import harness  # noqa: E402,F401

os.environ.setdefault("DATUM_SETTINGS_ORG", "IITEG-tests")

from PySide6 import QtCore, QtWidgets                              # noqa: E402

from datum.core import kernel                                      # noqa: E402
from datum.core import standard_parts as sp                        # noqa: E402
from datum.core.assembly import AssemblyDocument                   # noqa: E402
from datum.core.constraints3d import MATE, FLUSH                   # noqa: E402
from datum.core.document import Document                           # noqa: E402
from datum.core.features import PrimitiveFeature                   # noqa: E402
from datum.ui.main_window import MainWindow                        # noqa: E402

FAILS = []
WORK = tempfile.mkdtemp(prefix="datum_asm_undo_")
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


def part(kind, a, b, c, name):
    doc = Document()
    f = PrimitiveFeature(kind=kind, a=str(a), b=str(b), c=str(c))
    doc.add_feature(f)
    doc.rebuild()
    return doc.save(os.path.join(WORK, name))


PLATE = part("box", 80, 60, 10, "plate")
BLOCK = part("box", 30, 30, 20, "block")
asm = AssemblyDocument()
asm.path = os.path.join(WORK, "Bench.icasm")
asm.save(asm.path)
win.open_path(asm.path)
settle(700)
ui = win.assembly_ui


def state():
    doc = win.assembly
    return (len(doc.occurrences), len(doc.constraints),
            sum(1 for o in doc.occurrences if o.grounded))


def stub_pick(occurrence_id, shape):
    o = win.assembly.occurrence(occurrence_id)
    win.viewport.selected_component_shapes = \
        lambda: [(occurrence_id, shape.Moved(o.placement.location()))]


def face(occurrence_id, pick):
    o = win.assembly.occurrence(occurrence_id)
    return pick(kernel.faces(o.shape),
                key=lambda f: kernel.shape_centre(f)[2])


history = [state()]
print("the actions")
ui.place_library_file(PLATE)
settle()
history.append(state())
ui.place_library_file(BLOCK)
settle()
history.append(state())
ui.place_standard(sp.spec("iso-4017", "M8", 30))
settle()
history.append(state())
check("a plate, a block and a library bolt placed, one step each",
      history[-1][0] == 3, history)

plate, block, bolt = [o.id for o in win.assembly.occurrences]
ui.constrain(MATE)
settle()
dialog = ui.dialog
# three constraints in one window: two with Apply, the last with OK
for first, second, kind in ((plate, block, MATE), (plate, block, FLUSH),
                            (plate, bolt, MATE)):
    if dialog.constraint.kind != kind:
        dialog.kind.set_value(kind)
    stub_pick(first, face(first, max))
    dialog.on_selection()
    stub_pick(second, face(second, min) if kind == MATE
              else face(second, max))
    dialog.on_selection()
    settle()
    if (first, second, kind) != (plate, bolt, MATE):
        dialog.apply_and_continue()
        settle()
        history.append(state())
dialog.commit()
settle()
history.append(state())
check("three constraints placed in one window",
      history[-1][1] == 3, history[-3:])

ui.toggle_ground(block)
settle()
history.append(state())
ui.delete_occurrences([bolt])
settle()
history.append(state())
check("then the block grounded and the bolt deleted",
      history[-1][0] == 2, history[-2:])

# a constraint window opened and cancelled: no step of its own
ui.constrain(MATE)
settle()
ui.dialog.cancel()
settle()

print("Ctrl+Z, one action at a time, newest first")
ok = True
for want in reversed(history[:-1]):
    win.undo()
    settle()
    if state() != want:
        ok = False
        check("undo goes back to %s" % (want,), False, state())
        break
check("each Ctrl+Z undid exactly one action, to an empty assembly",
      ok and state() == history[0], state())

print("Ctrl+Y, one at a time, in order")
ok = True
for want in history[1:]:
    win.redo()
    settle()
    if state() != want:
        ok = False
        check("redo goes forward to %s" % (want,), False, state())
        break
check("each Ctrl+Y redid exactly one", ok and state() == history[-1],
      state())
check("and what is placed is drawn",
      all(win.viewport.context.IsDisplayed(a)
          for a in win.viewport._component_ais.values())
      and len(win.viewport._component_ais) == len(win.assembly.occurrences))

print()
if FAILS:
    print("%d FAILURES: %s" % (len(FAILS), ", ".join(FAILS)))
    sys.exit(1)
print("all passed")
