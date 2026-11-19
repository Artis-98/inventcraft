"""Physical properties the Inventor way: an assembly says N/A until Update,
and Update weighs every part in its own material, parts open in a tab as
they are there.  Inspect has an Update Mass button; a drawing of the
assembly gets the same weight for {Model.Mass}."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import harness  # noqa: E402,F401

os.environ.setdefault("DATUM_SETTINGS_ORG", "IITEG-tests")

from PySide6 import QtCore, QtWidgets                              # noqa: E402

from datum.core import views                                       # noqa: E402
from datum.core.assembly import AssemblyDocument                   # noqa: E402
from datum.core.document import Document                           # noqa: E402
from datum.core.features import PrimitiveFeature                   # noqa: E402
from datum.core.parts import PartLibrary                           # noqa: E402
from datum.ui.main_window import MainWindow                        # noqa: E402

FAILS = []
WORK = tempfile.mkdtemp(prefix="datum_mass_")
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


def part(name, size, material):
    doc = Document()
    doc.add_feature(PrimitiveFeature(kind="box", a=str(size), b=str(size),
                                     c=str(size)))
    doc.set_material(material) if hasattr(doc, "set_material") else None
    if not hasattr(doc, "set_material"):
        doc.material = material
    doc.rebuild()
    return doc.save(os.path.join(WORK, name)), doc.density


STEEL, rho_steel = part("steel", 10, "Steel, Mild")
ALU, rho_alu = part("alu", 10, "Aluminium 6061")
check("the two parts have different densities", rho_steel != rho_alu,
      (rho_steel, rho_alu))

asm = AssemblyDocument()
asm.path = os.path.join(WORK, "Pair.icasm")
asm.save(asm.path)
win.open_path(asm.path)
settle(400)
ui = win.assembly_ui
ui.place_library_file(STEEL)
ui.place_library_file(ALU)
ui.place_library_file(ALU)
settle(200)
win.save_document()
settle(200)

win.show_properties()
settle(200)
panel = win.properties


def cell(label):
    for r in range(panel.table.rowCount()):
        if panel.table.item(r, 0).text() == label:
            return panel.table.item(r, 1).text()
    return None


check("before Update the assembly's mass is N/A", cell("Mass") == "N/A",
      cell("Mass"))
check("with Update to press", panel.update_btn.isVisibleTo(panel))
panel.update_btn.click()
settle(200)
expected = (1.0 * rho_steel + 2.0 * rho_alu)      # 1 cm3 each
text = cell("Mass") or ""
check("Update weighs each part in its own material",
      ("%.2f" % expected) in text.replace(",", "") or
      abs(float(text.split()[0]) - expected) < 0.01, (text, expected))
check("and says how many parts it weighed", cell("Parts weighed") == "3",
      cell("Parts weighed"))
check("the status bar says so", "Mass updated" in
      win.status_message.text(), win.status_message.text())
win.properties_window.close()

print("an edit makes it N/A again")
occurrence = win.assembly.occurrences[2]
win.assembly.remove_occurrence(occurrence.id)
ui.rebuild()
settle(200)
win.show_properties()
settle(200)
check("after the change it waits for Update again", cell("Mass") == "N/A",
      cell("Mass"))
win.properties_window.close()

print("Inspect has the button")
labels = []
for button in win.findChildren(QtWidgets.QToolButton):
    labels.append(button.text().replace("\n", " "))
check("Update Mass on the ribbon", "Update Mass" in labels)

print("a drawing's {Model.Mass} of the assembly")
win.save_document()
settle(200)
lib = PartLibrary()
shape = lib.shape(asm.path)
opened = AssemblyDocument.load(asm.path) if hasattr(AssemblyDocument,
                                                     "load") else None
props = views.model_properties(asm.path, shape, opened, lib)
want = rho_steel + rho_alu
check("is the parts' weight in their own materials",
      abs(float(props["Model.Mass"].split()[0]) - want) < 0.06,
      (props["Model.Mass"], want))

print()
print("FAILED: %s" % FAILS if FAILS else "ALL PASSED")
sys.exit(1 if FAILS else 0)
