"""A part opens without building when it was built just like this before.

A part slow enough to be worth it is built and saved; opened again in a
fresh process it builds nothing, and comes out the same solid with its
sketches. Changed by a parameter, it builds again. Edited after opening,
it builds as always.
"""
import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
WORK = tempfile.mkdtemp(prefix="datum_results_")
os.environ["DATUM_NO_WORKERS"] = "1"
os.environ["DATUM_CONFIG_DIR"] = os.path.join(WORK, "cfg")
os.environ["DATUM_CACHE_DIR"] = os.path.join(WORK, "cache")

FAILS = []


def check(name, cond, extra=""):
    print(("  PASS  " if cond else "  FAIL  ") + name
          + (("  " + str(extra)) if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


MAKE = r'''
import os, sys, json
sys.path.insert(0, %(root)r)
from datum.core import kernel
from datum.core.document import Document
from datum.core.features import (CUT, PatternFeature, PrimitiveFeature,
                                 SketchFeature)
doc = Document()
doc.params.add("w", "400")
doc.add_feature(PrimitiveFeature(kind="box", a="w", b="300", c="20"))
hole = PrimitiveFeature(kind="cylinder", a="6", b="20", operation=CUT,
                        origin=("15", "15", "0"))
doc.add_feature(hole)
doc.add_feature(PatternFeature(parents=[hole.id], count1="16",
                               spacing1="24", dir1="X", count2="12",
                               spacing2="24", dir2="Y"))
sketch = SketchFeature(name="Marks")
sketch.sketch.add_line((0, 0), (50, 0))
doc.add_feature(sketch)
doc.rebuild()
doc.save(%(path)r)
print(json.dumps({"volume": kernel.volume(doc.shape)}))
'''

OPEN = r'''
import os, sys, json, time
sys.path.insert(0, %(root)r)
from datum.core import kernel
from datum.core import document as docmod
from datum.core.document import Document
built = []
real = docmod.Document._rebuild_here
doc = Document.load(%(path)r, build=False)
for feature in doc.features:
    original = feature.build
    def spy(ctx, _o=original, _f=feature):
        built.append(_f.type_name)
        return _o(ctx)
    feature.build = spy
doc.rebuild()
out = {"built": built, "volume": kernel.volume(doc.shape),
       "sketches": len(doc._sketch_cache)}
if %(edit)r:
    doc.params.set_expression("w", "300")
    doc.rebuild()
    out["edited_volume"] = kernel.volume(doc.shape)
print(json.dumps(out))
'''

PATH = os.path.join(WORK, "Plate.icpart")


def run(script, **values):
    values.setdefault("root", ROOT)
    values.setdefault("path", PATH)
    values.setdefault("edit", False)
    done = subprocess.run([sys.executable, "-c", script % values],
                          capture_output=True, text=True,
                          env=dict(os.environ))
    lines = [l for l in done.stdout.splitlines() if l.startswith("{")]
    if not lines:
        print(done.stdout, done.stderr)
        return {}
    return json.loads(lines[-1])


made = run(MAKE)
print("opened again, in a fresh process")
first = run(OPEN)
check("nothing is built", first.get("built") == [], first.get("built"))
check("the same solid", abs(first.get("volume", 0) - made["volume"]) < 1e-6,
      (first.get("volume"), made["volume"]))
check("with its sketch", first.get("sketches") == 1, first.get("sketches"))

print("edited after opening")
edited = run(OPEN, edit=True)
check("builds again, to the new size",
      edited.get("edited_volume", 0) < made["volume"] * 0.8,
      (edited.get("edited_volume"), made["volume"]))

print("switched off")
os.environ["DATUM_NO_RESULT_CACHE"] = "1"
plain = run(OPEN)
del os.environ["DATUM_NO_RESULT_CACHE"]
check("builds everything", len(plain.get("built", [])) == 4,
      plain.get("built"))
check("to the same solid", abs(plain.get("volume", 0) - made["volume"])
      < 1e-6)

print()
print("all passed" if not FAILS else "FAILED: %s" % FAILS)
sys.exit(1 if FAILS else 0)
