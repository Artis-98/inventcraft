"""The Templates folder, Inventor's: set in Preferences, it offers the
part, assembly and drawing templates kept there, a shared drive's for a
whole company."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("DATUM_SETTINGS_ORG", "IITEG-tests")
import tempfile                                                    # noqa: E402
os.environ["DATUM_TEMPLATES_DIR"] = tempfile.mkdtemp(prefix="datum_tpl_")

from datum.core import drawing as dwg, fileformat, prefs, templates  # noqa
from datum.core.document import Document                        # noqa: E402

FAILS = []


def check(name, cond, extra=""):
    print(("  PASS  " if cond else "  FAIL  ") + name
          + (("  " + str(extra)) if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


folder = tempfile.mkdtemp(prefix="templates_")
part = Document()
part.save(os.path.join(folder, "Standard (mm).icpart"))
drawing = dwg.DrawingDocument()
drawing.add_sheet("A3")
drawing.save(os.path.join(folder, "IITEG.icdraw"))
held = prefs.prefs().templates_folder
prefs.prefs().templates_folder = folder
try:
    check("the folder's part template is offered",
          [t.name for t in templates.of_type(fileformat.PART)]
          == ["Standard (mm)"])
    check("its drawing template comes first among drawing templates",
          templates.available()[0].name == "IITEG")
finally:
    prefs.prefs().templates_folder = held
check("without a folder, the standard ones in mm and inches",
      sorted(t.name for t in templates.of_type(fileformat.PART))
      == ["Standard (in)", "Standard (mm)"],
      [t.name for t in templates.of_type(fileformat.PART)])
check("and the ISO and ANSI drawings first among drawing templates",
      [t.name for t in templates.available()][:2] == ["ANSI (in)",
                                                       "ISO (mm)"],
      [t.name for t in templates.available()][:3])
check("a New Drawing in inches starts from ANSI",
      templates.default_for(fileformat.DRAWING, "in").name == "ANSI (in)")

print()
if FAILS:
    print("%d FAILED: %s" % (len(FAILS), ", ".join(FAILS)))
    sys.exit(1)
print("all passed")
