"""Create New File, Document Settings and templates.

New lists the Templates folder by kind, with the standard mm and inch
parts and assemblies and the ISO and ANSI drawings. A part made from the
inch template is in inches; a drawing from the ANSI one is on its sheet,
nothing asked. Document Settings changes a part's look and keeps it in
the file, and Save As Template puts a copy in the Templates folder that
New then offers.
"""
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WORK = tempfile.mkdtemp(prefix="datum_newset_")
os.environ["DATUM_TEMPLATES_DIR"] = os.path.join(WORK, "Templates")

import harness  # noqa: E402,F401

os.environ.setdefault("DATUM_SETTINGS_ORG", "IITEG-tests")

from PySide6 import QtCore, QtWidgets                              # noqa: E402

from datum.core import fileformat, templates                       # noqa: E402
from datum.ui import dialogs, docsettings_ui                       # noqa: E402
from datum.ui.main_window import MainWindow                        # noqa: E402

FAILS = []
app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
win = MainWindow()
win.resize(1100, 750)
win.show()


def check(name, cond, extra=""):
    print(("  PASS  " if cond else "  FAIL  ") + name
          + ("  " + str(extra) if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


def settle(ms=250):
    end = time.monotonic() + ms / 1000.0
    while time.monotonic() < end:
        app.processEvents(QtCore.QEventLoop.AllEvents, 20)


settle(500)
print("Create New File")
dialog = dialogs.NewDocumentDialog(win)
names = {kind: [grid.item(i).text() for i in range(grid.count())]
         for kind, grid in zip((fileformat.PART, fileformat.ASSEMBLY,
                                fileformat.DRAWING, fileformat.CAM),
                               dialog.lists)}
check("parts in mm and inches", sorted(names[fileformat.PART])
      == ["Standard (in)", "Standard (mm)"], names[fileformat.PART])
check("assemblies too", sorted(names[fileformat.ASSEMBLY])
      == ["Standard (in)", "Standard (mm)"])
check("ISO and ANSI drawings first", names[fileformat.DRAWING][:2]
      == ["ANSI (in)", "ISO (mm)"], names[fileformat.DRAWING])
check("a CAM sheet to start", names[fileformat.CAM] == ["Standard"])
dialog.reject()

print("from the inch template")
inch = next(t for t in templates.of_type(fileformat.PART)
            if t.name == "Standard (in)")
win.new_document(template=inch)
settle(300)
check("the part is in inches", win.document.units == "in",
      win.document.units)
check("not tied to the template", not win.document.path)

print("a drawing from ANSI")
ansi = next(t for t in templates.available() if t.name == "ANSI (in)")
win.new_drawing(template=ansi)
settle(300)
sheet = win.drawing.active()
check("on the template's sheet, nothing asked",
      sheet.size == "Tabloid" and win.drawing.standard == "ANSI",
      (sheet.size, win.drawing.standard))

print("Document Settings")
win.new_document(prompt=False)
settle(300)
settings = docsettings_ui.DocumentSettingsDialog(win, win.document)
settings.style.setCurrentIndex(settings.style.findData("shaded"))
settings.ortho.setCurrentIndex(1)
settings.apply()
settle(100)
check("the look changes", (win.viewport.display_mode,
                           win.viewport.is_orthographic())
      == ("shaded", False))
check("and is kept with the part", win.document.view.style == "shaded"
      and win.document.view.orthographic is False)
written = templates.save_copy_as_template(win.document, "Shaded part")
check("Save As Template writes it to the Templates folder",
      os.path.dirname(written) == templates.shared_folder())
check("and New offers it", "Shaded part" in [
    t.name for t in templates.of_type(fileformat.PART)])
check("the part itself stays unsaved", not win.document.path)
settings.reject()

for entry in list(win.session.documents):
    entry.document.modified = False
win.close()
print()
print("FAILED: %s" % FAILS if FAILS else "ALL PASSED")
sys.exit(1 if FAILS else 0)
