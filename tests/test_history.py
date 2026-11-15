"""Versions and branches of a file (#77, with #75 merged into it).

A plate is checked in, changed and checked in again; an old version is
restored, which comes back as the newest; a branch tries a thicker plate
and main goes on without it; switching puts each branch's plate back in
the file's place; merging the branch makes main take it.  Changes not
checked in are not thrown away by any of it.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import harness  # noqa: E402,F401

from datum.core import history  # noqa: E402
from datum.core.document import Document  # noqa: E402
from datum.core.features import PrimitiveFeature  # noqa: E402

FAILS = []
WORK = tempfile.mkdtemp(prefix="datum_history_")


def check(name, cond, extra=""):
    print(("  PASS  " if cond else "  FAIL  ") + name
          + ("" if cond else "  " + str(extra)))
    if not cond:
        FAILS.append(name)


def raises(call):
    try:
        call()
    except history.HistoryError as exc:
        return str(exc)
    return ""


PATH = os.path.join(WORK, "plate.icpart")


def save(thickness):
    doc = Document()
    box = PrimitiveFeature()
    box.kind = "box"
    box.a, box.b, box.c = "100", "60", str(thickness)
    doc.add_feature(box)
    doc.rebuild()
    doc.save(PATH)


def thickness():
    doc = Document.load(PATH)
    return float(doc.features[0].c)


print("checking in")
check("nothing to check in before the file exists",
      "save it first" in raises(lambda: history.check_in(PATH)))
save(10)
first = history.check_in(PATH, "First plate", "Artis")
check("version 1 on main", first.id == 1 and first.branch == "main")
check("who and why kept", first.author == "Artis"
      and first.message == "First plate")
check("kept beside the file", os.path.isdir(os.path.join(
    WORK, ".icversions", "plate.icpart")))
check("nothing changed, nothing to check in",
      "nothing has changed" in raises(lambda: history.check_in(PATH)))
save(12)
check("the file has changes", history.changed(PATH))
second = history.check_in(PATH, "Thicker")
check("version 2 follows 1", second.id == 2 and second.parent == 1)
check("and the file is clean again", not history.changed(PATH))

print("restoring")
save(15)
check("will not throw away changes not checked in",
      "not checked in" in raises(lambda: history.restore(PATH, 1)))
history.restore(PATH, 1, force=True)
check("version 1's plate is back", thickness() == 10.0, thickness())
h = history.load(PATH)
check("and is checked in again as version 3", h.head().id == 3
      and "Restored version 1" in h.head().message, h.head())
check("main runs 3, 2, 1", [v.id for v in h.line()] == [3, 2, 1])

print("a branch")
history.new_branch(PATH, "thick")
save(25)
history.check_in(PATH, "Try 25")
h = history.load(PATH)
check("on the branch", h.current == "thick" and h.head().branch == "thick")
check("it runs 4, 3, 2, 1", [v.id for v in h.line()] == [4, 3, 2, 1])
check("main is still at 3", h.branches["main"] == 3)
check("the same name twice is refused",
      "already" in raises(lambda: history.new_branch(PATH, "thick")))

print("switching")
history.switch(PATH, "main")
check("main's plate is back", thickness() == 10.0, thickness())
save(11)
check("a switch with changes not checked in is refused",
      "not checked in" in raises(lambda: history.switch(PATH, "thick")))
history.check_in(PATH, "Main moves on")
history.switch(PATH, "thick")
check("the branch's plate", thickness() == 25.0, thickness())

print("merging")
merged = history.merge(PATH, "thick", "main")
h = history.load(PATH)
check("main takes the branch's plate", thickness() == 25.0
      and h.current == "main")
check("as its next version", merged.branch == "main"
      and h.branches["main"] == merged.id and merged.parent == 5,
      merged)
check("what it replaced is still there", any(v.message == "Main moves on"
                                            for v in h.line()))

print("a branch from an old version")
history.new_branch(PATH, "from-one", from_version=1)
check("version 1's plate", thickness() == 10.0, thickness())
h = history.load(PATH)
check("the branch starts at 1", h.branches["from-one"] == 1
      and h.current == "from-one")

print("in the window")
os.environ.setdefault("DATUM_SETTINGS_ORG", "IITEG-tests")
from PySide6 import QtWidgets  # noqa: E402
from datum.ui.main_window import MainWindow  # noqa: E402
from datum.ui.theme import stylesheet  # noqa: E402

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
app.setStyleSheet(stylesheet())
win = MainWindow()
win.resize(1300, 850)
win.show()
PATH2 = os.path.join(WORK, "bracket.icpart")
PATH = PATH2
save(8)
win.open_path(PATH2)
for _ in range(10):
    app.processEvents()
dialog = win.show_versions()
check("the Versions window opens on the file", dialog is not None
      and dialog.path == win.document.path)
dialog.message.setText("Bracket as drawn")
dialog.check_in()
check("checked in from the window", history.load(PATH2).head().message
      == "Bracket as drawn")
win.document.features[0].c = "20"
win.rebuild()
win.document.modified = True
dialog.message.setText("Thicker bracket")
dialog.check_in()
check("unsaved work is saved before it is checked in",
      history.load(PATH2).head().id == 2 and thickness() == 20.0,
      thickness())
dialog.table.selectRow(dialog.table.rowCount() - 1)
check("the oldest picked", dialog.picked() == 1, dialog.picked())
dialog.restore()
for _ in range(10):
    app.processEvents()
check("restoring opens the file again with version 1's plate",
      float(win.document.features[0].c) == 8.0, win.document.features[0].c)
check("one tab for it, not two", sum(
    1 for e in win.session.documents
    if os.path.normcase(e.document.path or "") == os.path.normcase(PATH2))
    == 1)
check("the window says so", "restored" in win.status_message.text(),
      win.status_message.text())
dialog.grab().save(os.path.join(WORK, "versions.png"))
print("    picture:", os.path.join(WORK, "versions.png"))

print()
if FAILS:
    print("%d FAILED" % len(FAILS))
    sys.exit(1)
print("all passed")
