"""The window in another language: a table of what is shown, put on each
widget as it comes on screen, English wherever the table has nothing.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import harness  # noqa: E402,F401

os.environ.setdefault("DATUM_SETTINGS_ORG", "IITEG-tests")

from PySide6 import QtCore, QtWidgets                           # noqa: E402

from datum.core import prefs                                    # noqa: E402
from datum.ui import i18n                                       # noqa: E402

FAILS = []


def check(name, cond, extra=""):
    print(("  PASS  " if cond else "  FAIL  ") + name
          + (("  " + str(extra)) if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)


def pump(n=20):
    for _ in range(n):
        app.processEvents()


print("the tables")
langs = i18n.languages()
check("English first, German there", list(langs)[0] == "en"
      and langs.get("de") == "Deutsch", langs)
i18n.load("de")
table = dict(i18n._table)
check("the German table has the ribbon's words",
      table.get("Save") and table.get("Extrude") and table.get("Sketch"))
bad = [k for k, v in table.items()
       if k.count("%") != v.count("%") or k.count("{") != v.count("{")]
check("no translation loses a placeholder", not bad, bad[:5])

print("the lookup")
i18n._table = {"Save": "Speichern", "Open": "Öffnen", "Line one":
               "Zeile eins", "Depth": "Tiefe"}
i18n._reverse = {v: k for k, v in i18n._table.items()}
check("as it is", i18n.tr("Save") == "Speichern")
check("a menu entry's dots and shortcut kept",
      i18n.tr("&Open...\tCtrl+O") == "Öffnen...\tCtrl+O")
check("a label's colon kept", i18n.tr("Depth:") == "Tiefe:")
check("paragraph by paragraph",
      i18n.tr("Line one\nNot there") == "Zeile eins\nNot there")
check("not there: English", i18n.tr("Fillet") == "Fillet")
check("translated twice is still the same", i18n.tr("Speichern") ==
      "Speichern")
check("read back in English", i18n.english("Öffnen...\tCtrl+O")
      == "Öffnen...\tCtrl+O" and i18n.english("Speichern") == "Save")

print("on screen")
i18n.install(app, "en")
i18n._table = {"Save": "Speichern", "Depth": "Tiefe", "Options": "Optionen",
               "Hole": "Bohrung", "Name": "Name", "A tip": "Ein Tipp",
               "Later": "Später"}
i18n._reverse = {v: k for k, v in i18n._table.items()}
if i18n._filter is None:
    i18n._filter = i18n._Translator(app)
    app.installEventFilter(i18n._filter)
dialog = QtWidgets.QDialog()
dialog.setWindowTitle("Hole")
form = QtWidgets.QFormLayout(dialog)
box = QtWidgets.QGroupBox("Options")
form.addRow("Depth:", QtWidgets.QLineEdit())
button = QtWidgets.QPushButton("Save")
button.setToolTip("A tip")
form.addRow(box)
form.addRow(button)
tabs = QtWidgets.QTabWidget()
tabs.addTab(QtWidgets.QWidget(), "Later")
form.addRow(tabs)
dialog.show()
pump()
label = form.labelForField(form.itemAt(0, QtWidgets.QFormLayout.FieldRole)
                           .widget())
check("title, label, group and button", dialog.windowTitle() == "Bohrung"
      and label.text() == "Tiefe:" and box.title() == "Optionen"
      and button.text() == "Speichern",
      (dialog.windowTitle(), label.text(), box.title(), button.text()))
check("tabs", tabs.tabText(0) == "Später")
QtCore.QCoreApplication.sendEvent(
    button, QtCore.QEvent(QtCore.QEvent.ToolTip))
check("the tooltip, as it shows", button.toolTip() == "Ein Tipp")
button.setText("Name")
button.hide()
button.show()
pump()
check("a text set later, translated when shown again",
      button.text() == "Name")
status = QtWidgets.QLabel("x")
i18n.translated_label(status)
status.setText("Save")
check("a status label, each time it is set", status.text() == "Speichern")
dialog.close()

print("the preference")
p = prefs.Preferences.from_dict({"language": "de"})
check("kept", p.language == "de" and p.to_dict()["language"] == "de")
check("English when none", prefs.Preferences.from_dict({}).language == "en")
from datum.ui import prefs_ui                                    # noqa: E402
prefs.prefs().language = "de"
dialog = prefs_ui.PreferencesDialog()
check("Preferences offers it, on German",
      dialog.language_combo.currentData() == "de"
      and dialog.language_combo.findData("en") >= 0)
dialog.gather()
check("and keeps the choice", dialog.prefs.language == "de")
prefs.prefs().language = "en"

print("five languages, every table the same size")
langs = i18n.languages()
check("German, French, Spanish and Polish offered",
      all(c in langs for c in ("de", "fr", "es", "pl")), langs)
sizes = {}
for code in ("de", "fr", "es", "pl"):
    i18n.load(code)
    sizes[code] = len(i18n._table)
check("each has as many entries as German",
      len(set(sizes.values())) == 1, sizes)

print("messages with numbers and names in them")
i18n.load("de")
check("the numbers go into the translation",
      i18n.tr("Rebuilt 3 feature(s) in 12 ms")
      == "3 Element(e) in 12 ms neu erstellt", i18n.tr(
          "Rebuilt 3 feature(s) in 12 ms"))
check("a name before the colon is kept",
      i18n.tr("Extrusion1: distance must be positive")
      == "Extrusion1: der Abstand muss positiv sein")
check("an English plural s is dropped, empty or not",
      i18n.tr("Deleted 2 features.") == "2 Element(e) gelöscht."
      and i18n.tr("Deleted 1 feature.") == "2 Element(e) gelöscht."
      .replace("2", "1"))
check("a value that is in the table is translated too",
      i18n.tr("Home is this view, fitted to the part when you go there.")
      .startswith("Die Ausgangsansicht"))
check("a text no format string fits stays English",
      i18n.tr("Nothing like it 5") == "Nothing like it 5")
i18n.load("pl")
check("Polish puts the number where it reads",
      i18n.tr("Projected 4 edge(s). Keep clicking, or Esc to finish.")
      .startswith("Zrzutowano krawędzie: 4."))

print("a long caption on a big ribbon button")
from datum.ui import ribbon                                      # noqa: E402
button = ribbon.RibbonButton("extrude", "Extrude")
button.setText("Wyciągnięcie proste")
check("goes onto two lines", button.text() == "Wyciągnięcie\nproste",
      repr(button.text()))
check("and then fits", QtWidgets.QToolButton.sizeHint(button).width()
      <= button.maximumWidth())
button.setText("Extrude")
check("a short one stays on one", button.text() == "Extrude")

i18n.load("en")
i18n._table, i18n._reverse = {}, {}
print()
if FAILS:
    print("%d FAILED: %s" % (len(FAILS), ", ".join(FAILS)))
    sys.exit(1)
print("all passed")
sys.exit(0)
