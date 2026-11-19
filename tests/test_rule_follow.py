"""A rule that only moves components is followed by shifting pictures.

An icLogic form runs its rule on every slider move.  When the rule only
places things, the viewport keeps the pictures it has and moves them; a
body that changed still gets everything drawn again.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import harness  # noqa: E402,F401

os.environ.setdefault("DATUM_SETTINGS_ORG", "IITEG-tests")

from PySide6 import QtCore, QtWidgets                              # noqa: E402

from datum.core import rules as core_rules                         # noqa: E402
from datum.core.assembly import AssemblyDocument                   # noqa: E402
from datum.core.document import Document                           # noqa: E402
from datum.core.features import PrimitiveFeature                   # noqa: E402
from datum.ui.main_window import MainWindow                        # noqa: E402

FAILS = []
WORK = tempfile.mkdtemp(prefix="datum_rule_follow_")
app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
win = MainWindow()
win.resize(1100, 750)
win.show()


def check(name, cond, extra=""):
    print(("  PASS  " if cond else "  FAIL  ") + name
          + ("  " + str(extra) if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


def settle(ms=300):
    loop = QtCore.QEventLoop()
    QtCore.QTimer.singleShot(ms, loop.quit)
    loop.exec()


block = Document()
block.add_feature(PrimitiveFeature(kind="box", a="100", b="60", c="40"))
block.rebuild()
BLOCK = block.save(os.path.join(WORK, "Block"))

asm = AssemblyDocument()
asm.path = os.path.join(WORK, "Rig.icasm")
fixed = asm.place(BLOCK, "Fixed")
moving = asm.place(BLOCK, "Moving")
fixed.grounded = moving.grounded = True
asm.params.add("travel", "0", "mm")
rule = asm.rules.add("Slide", "doc.occurrences[1].placement.position = "
                     "[200 + params['travel'], 0, 0]\n_changes.append('moved')\n")
rule.on_rebuild = True
rule.watch = ["travel"]
asm.save(asm.path)
win.open_path(asm.path)
settle(600)
core_rules.trust_document(win.assembly)
win._rules_changed()
settle(200)

vp = win.viewport
ui = win.assembly_ui
doc = win.assembly
mid = doc.occurrences[1].id
before = dict(vp._component_ais)

print("a rule that only moves")
doc.params.set_expression("travel", "150")
win._rules_changed()
settle(200)
check("the rule placed the block", abs(doc.occurrences[1].placement.position[0] - 350) < 1e-9,
      doc.occurrences[1].placement.position)
check("the pictures are the ones already drawn",
      all(vp._component_ais.get(k) is v for k, v in before.items()))
loc = vp.context.Location(vp._component_ais[mid]).Transformation().TranslationPart()
drawn = ui._drawn[mid].position[0]
check("the moved block's picture is shifted to it",
      abs(drawn + loc.X() - 350) < 1e-6, (drawn, loc.X()))

print("a body that changed")
part = Document.load(BLOCK)
part.features[0].a = "180"
part.rebuild()
part.save(BLOCK)
doc.rebuild()
win._rules_changed()
settle(200)
check("everything is drawn again",
      any(vp._component_ais.get(k) is not v for k, v in before.items()))

print()
print("FAILED: %s" % FAILS if FAILS else "ALL PASSED")
sys.exit(1 if FAILS else 0)
