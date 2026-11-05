"""The title block edited in place: one definition, every sheet follows,
and text holds properties among its words as Inventor's Format Text does."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import harness  # noqa: E402,F401

from PySide6 import QtWidgets                                   # noqa: E402

from datum.core import drawing as dwg                           # noqa: E402

FAILS = []


def check(name, cond, extra=""):
    print(("  PASS  " if cond else "  FAIL  ") + name
          + (("  " + str(extra)) if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


values = {"Model.PartNumber": "26-011", "Model.Mass": "412.0 g"}
check("properties fill in among the words",
      dwg.fill_properties("Part <Model.PartNumber>, <Model.Mass>", values)
      == "Part 26-011, 412.0 g")
check("a name that is no property stays as typed",
      dwg.fill_properties("a <b> c", values) == "a <b> c")

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
from datum.ui.titleblock_ui import TitleBlockDialog, block_rect  # noqa: E402

doc = dwg.DrawingDocument()
one = doc.add_sheet("A3")
two = doc.add_sheet("A3")
dialog = TitleBlockDialog(None, doc, one.title_block)
dialog._add_text()
dialog.group.setCurrentIndex(0)
dialog.prop.setCurrentIndex(0)
dialog._insert_property()
dialog.width_box.setValue(200.0)
dialog.apply()
block = doc.title_blocks[one.title_block]
check("the new text is the part number property",
      block.fields[-1].kind == dwg.PROPERTY
      and block.fields[-1].text == "Model.PartNumber",
      (block.fields[-1].kind, block.fields[-1].text))
check("and both sheets show the changed block",
      two.title_block == one.title_block
      and abs(block_rect(doc, two)[2] - block_rect(doc, two)[0] - 200) < 1e-9)

print()
if FAILS:
    print("%d FAILED: %s" % (len(FAILS), ", ".join(FAILS)))
    sys.exit(1)
print("all passed")
