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

from datum.ui.library_dialog import SHELVES, LibraryDialog  # noqa: E402
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
dialog = LibraryDialog()
tops = [dialog.tree.topLevelItem(i).text(0)
        for i in range(dialog.tree.topLevelItemCount())]
check("every category is there", tops == [c for c, _ in SHELVES], tops)
check("fasteners lead, with bolts first",
      dialog.tree.currentItem().text(0) == "Bolts")
check("online libraries have a shelf", "Online libraries" in tops)
check("it says what is coming", "GrabCAD" in dialog.state.text())

print()
if FAILS:
    print("%d FAILED" % len(FAILS))
    sys.exit(1)
print("all passed")
