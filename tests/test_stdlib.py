"""The standard parts library in datum/stdlib.

Every file says where its numbers came from and under which licence;
every profile size builds and the common European ones have the areas
their standards publish; a member's part made from an I beam, a channel
and a round tube is the extruded profile, mirrored and all; every size of
every fastener, ring and bearing builds into a solid part; the lengths a
size is offered keep inside its standard's range; and the Standards
filter hides what it is told to.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import harness  # noqa: E402,F401

from datum.core import frames, kernel, stdlib  # noqa: E402
from datum.core import standard_parts as sp  # noqa: E402
from datum.core.document import Document  # noqa: E402

FAILS = []
WORK = tempfile.mkdtemp(prefix="datum_stdlib_")
os.environ["DATUM_PROFILE_LIBRARY"] = os.path.join(WORK, "profiles")


def check(name, cond, extra=""):
    print(("  PASS  " if cond else "  FAIL  ") + name
          + ("  " + str(extra) if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


# -- the files
tables = stdlib.profiles() + stdlib.fasteners() + stdlib.bearings()
check("every file names its source and licence",
      all(t.source and t.licence for t in tables),
      [t.id for t in tables if not (t.source and t.licence)][:5])
check("and its licence is one the README covers",
      all(t.licence in ("LGPL-2.1-or-later", "Apache-2.0", "CC0-1.0")
          for t in tables))
readme = open(os.path.join(stdlib.folder(), "README.md"),
              encoding="utf-8").read()
check("the README says where each source is from",
      "FreeCAD" in readme and "cq_warehouse" in readme)
check("the licences are in the folder",
      all(os.path.exists(os.path.join(stdlib.folder(), "LICENSES", n))
          for n in ("LGPL-2.1.txt", "Apache-2.0.txt")))
check("no table came from a CAD program's own library",
      not any("Inventor" in t.source or "Content Center" in t.source
              for t in tables))
check("a size such as #10 is a size, not a note",
      "#10" in sp.family("asme-b18-3-cap").sizes())

# -- the profiles
fams = frames.families()
ids = [f.id for f in fams]
check("some twenty profile families", len(fams) >= 20, len(fams))
check("each with an id of its own", len(ids) == len(set(ids)))
check("the two that came first keep their ids",
      ids[:2] == ["din-en-10056-1-equal", "din-en-10219-2-square"])
check("every size has a name of its own within its family",
      all(len(set(f.sizes())) == len(f.sizes()) for f in fams))

# areas the standards publish, cm2 (EN 10365, DIN 1026-1, BS 4-1)
PUBLISHED = {
    ("en-10365-ipe", "IPE 200"): 28.5,
    ("en-10365-ipe", "IPE 400"): 84.5,
    ("en-10365-hea", "HEA 200"): 53.8,
    ("en-10365-heb", "HEB 200"): 78.1,
    ("en-10365-hem", "HEM 200"): 131.3,
    ("en-10365-upe", "UPE 200"): 29.0,
    ("din-1026-1-upn", "UPN 200"): 32.2,
    ("en-10365-ipn", "IPN 200"): 33.4,
    ("bs-4-1-uc", "UC 203x203x46"): 58.7,
    ("bs-4-1-ub", "UB 305x165x40"): 51.3,
}
for (fid, size), want in PUBLISHED.items():
    fam = frames.family(fid)
    got = kernel.face_area(frames.profile_face(fam.kind, fam.row(size))) / 100
    check("%s is %.1f cm2 as published" % (size, want),
          abs(got - want) / want < 0.01, "%.2f" % got)

bad = []
for fam in fams:
    for size in fam.sizes():
        try:
            if not kernel.face_area(frames.profile_face(fam.kind,
                                                        fam.row(size))) > 0:
                bad.append((fam.id, size))
        except Exception as e:  # noqa: BLE001
            bad.append((fam.id, size, str(e)))
check("every one of %d profile sizes builds"
      % sum(len(f.rows) for f in fams), not bad, bad[:5])

for fid, size, mirror in (("en-10365-heb", "HEB 200", False),
                          ("din-1026-1-upn", "UPN 100", True),
                          ("en-10219-chs", "CHS60.3x3.2", False)):
    fam = frames.family(fid)
    path = os.path.join(WORK, "%s.icpart" % fid)
    member = frames.Member(id=1, family=fid, size=size, mirror=mirror)
    frames.write_member_part(path, member, fam, 1000.0, {})
    part = Document.load(path)
    part.rebuild()
    want = kernel.face_area(frames.built_face(fam.kind, fam.row(size), "",
                                              mirror)) * 1000.0
    check("a %s member's part is its profile a metre long" % size,
          part.last_report.ok and part.shape is not None
          and abs(kernel.volume(part.shape) - want) < 1e-3 * want,
          part.shape and kernel.volume(part.shape))

# -- the fasteners
parts = sp.fastener_families()
check("over a hundred fastener and bearing families", len(parts) > 100,
      len(parts))
check("the four that came first keep their ids",
      all(sp.family(i) for i in ("iso-4017", "iso-4762", "iso-4032",
                                 "iso-7089")))
fids = [f.id for f in sp.families()]
check("no id is used twice in the whole library", len(fids) == len(set(fids)))

failed, built = [], 0
for fam in parts:
    for size in fam.sizes():
        chosen = sp.spec(fam.id, size, fam.default_length_for(size))
        try:
            doc = sp._fastener(fam, chosen)
            built += 1
            if not doc.last_report.ok or doc.shape is None \
                    or not kernel.volume(doc.shape) > 0:
                failed.append((fam.id, size))
        except Exception as e:  # noqa: BLE001
            failed.append((fam.id, size, str(e)))
check("every one of %d fastener sizes builds a solid part" % built,
      not failed, failed[:5])

bolt = sp.family("iso-4762")
check("an M8 cap screw is offered 10 to 80 long, as ISO 4762 has it",
      min(bolt.lengths_for("M8")) == 10 and max(bolt.lengths_for("M8")) == 80,
      bolt.lengths_for("M8"))
check("and starts about three diameters long",
      bolt.default_length_for("M8") in (25, 20, 30),
      bolt.default_length_for("M8"))

doc = sp._fastener(bolt, sp.spec("iso-4762", "M8", 30))
d, dk, k = 8.0, 13.0, 8.0
want = 3.14159 * (d / 2) ** 2 * 30
check("an M8 x 30 cap screw is about its shank and head",
      want < kernel.volume(doc.shape) < want + 3.14159 * (dk / 2) ** 2 * k,
      kernel.volume(doc.shape))
check("its length is the part's L", doc.params.get("L") is not None
      and float(doc.params.get("L").expression) == 30)

with tempfile.TemporaryDirectory() as there:
    path = sp.write_part(sp.spec("din-985", "M10"), there)
    check("a lock nut is written as a part that knows what it is",
          Document.load(path).standard_part == sp.spec("din-985", "M10"))

# -- the filter
check("standards are grouped by the body that issues them",
      [stdlib.body(s) for s in ("ISO 4762", "DIN EN 10056-1", "EN 1662",
                                "ASME B18.3", "DIN 933", "BS 4-1",
                                "IS 808", "Aluminium", "")]
      == ["ISO", "EN", "EN", "ASME", "DIN", "BS", "IS", "Other", "Other"])

from PySide6 import QtWidgets  # noqa: E402
app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
from datum.core import prefs  # noqa: E402
from datum.ui.library_dialog import LibraryDialog, library_tree  # noqa: E402

saved = list(prefs.prefs().hidden_standards)
try:
    prefs.prefs().hidden_standards = []
    every = library_tree([])
    asme = library_tree([], shows=lambda s: stdlib.body(s) != "ASME")
    count = lambda folder: len(folder.families) + sum(
        count(f) for f in folder.folders.values())
    check("hiding ASME leaves its families out of the library",
          count(asme) == count(every) - sum(
              1 for f in sp.families() if stdlib.body(f.standard) == "ASME"))
    dlg = LibraryDialog()
    dlg.standards._toggle("ASME", False)
    check("and the window's filter does it, and remembers",
          "ASME" in prefs.prefs().hidden_standards
          and count(dlg.root) == count(asme))
    dlg.standards._set_all(True)
    check("Show all brings them back", count(dlg.root) == count(every))
finally:
    prefs.prefs().hidden_standards = saved

print()
if FAILS:
    print("%d FAILURES: %s" % (len(FAILS), ", ".join(FAILS)))
    sys.exit(1)
print("all passed")
