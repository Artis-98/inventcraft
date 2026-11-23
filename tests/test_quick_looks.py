"""A slow rebuild is looked at quickly on spare cores while one builds it.

Solids in one part stay apart through a pattern and a move.
What each feature read and changed is kept, and says which solids build
apart.  A part of several such solids gets one quick look per set of them,
each on a worker of its own, naming its solids as the whole build does,
and together they come to what the exact build does.  A part whose time
goes into fillets gets one quick look without them.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WORK = tempfile.mkdtemp(prefix="datum_looks_")
os.environ["DATUM_CONFIG_DIR"] = os.path.join(WORK, "cfg")
os.environ["DATUM_NO_RESULT_CACHE"] = "1"
os.environ.pop("DATUM_NO_WORKERS", None)
os.environ["DATUM_WORKERS"] = "4"

from datum.core import document as docmod        # noqa: E402
from datum.core import kernel, workers           # noqa: E402
from datum.core.document import Document         # noqa: E402
from datum.core.features import MoveFeature, SketchFeature  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from quick_looks_parts import plates  # noqa: E402

FAILS = []


def check(name, cond, extra=""):
    print(("  PASS  " if cond else "  FAIL  ") + name
          + (("  " + str(extra)) if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


print("solids stay apart")
doc = plates(2)
check("a pattern of a hole in the second solid leaves two solids",
      len(doc.bodies) == 2, len(doc.bodies))
each = 150 * 100 * 10 - 9 * 3.14159265 * 5 ** 2 * 10
check("each drilled with its own holes",
      all(abs(kernel.volume(b.shape) - each) < 5 for b in doc.bodies),
      [kernel.volume(b.shape) for b in doc.bodies])
doc.add_feature(MoveFeature(dx="5"))
doc.rebuild()
check("a move moves both and keeps them two", len(doc.bodies) == 2
      and not doc.last_report.errors, (len(doc.bodies),
                                       doc.last_report.errors))

print("what each feature touched")
docmod.GROUP_MIN = 0.0
doc = plates(3)
marks = doc._footprints
check("the first plate made Solid1", marks[doc.features[0].id][2]
      == ["Solid1"], marks[doc.features[0].id])
check("the third plate's pattern changed Solid3 only",
      marks[doc.features[8].id][1] == ["Solid3"], marks[doc.features[8].id])
found = docmod.body_groups(doc, 8)
check("three sets of solids", found is not None and len(found[0]) == 3,
      found)
doc.add_feature(SketchFeature(name="Notes"))
doc.rebuild()
found = docmod.body_groups(doc, 8)
check("a sketch on no solid is shared by all", found is not None
      and len(found[1]) == 1, found)
check("two cores to spare make two groups",
      len(docmod.body_groups(doc, 2)[0]) == 2)

print("quick looks on the workers")
helpers = workers.pool()
helpers.start()
check("workers start", helpers.wait_ready() >= 3, helpers.ready)
doc = plates(3, holes=4, fillets=True)
docmod.PREVIEW_FROM = 0.0
exact_request = doc.remote_request()
looks = doc.preview_requests(3)
check("one look per solid", len(looks) == 3, [r["key"] for r in looks])
check("each with the other solids' features left out",
      all(sum(1 for f in r["data"]["features"] if not f.get("suppressed"))
          == 4 for r in looks))
taken = [doc.remote_key]
futures = []
for request in looks:
    helpers.bind(request["key"], avoid=taken)
    taken.append(request["key"])
    futures.append(helpers.submit_to(request["key"], "rebuild", **request))
exact = helpers.submit_to(doc.remote_key, "rebuild", **exact_request)
results = [f.result(timeout=300) for f in futures]
names = sorted(b["name"] for r in results for b in r["bodies"])
check("the solids named as the whole build names them",
      names == ["Solid1", "Solid2", "Solid3"], names)
shape = doc.preview_shape(results, looks)
report = doc.apply_remote(exact.result(timeout=300), exact_request)
check("the exact build is clean", not report.errors, report.errors)
check("together they come to what the exact build does",
      shape is not None and abs(kernel.volume(shape)
                                - kernel.volume(doc.shape)) < 1e-3,
      (shape and kernel.volume(shape), kernel.volume(doc.shape)))
check("the exact build sent back what each feature touched",
      len(doc._footprints) >= len(doc.features))

print("fillets left out")
one = plates(1, holes=4, fillets=True)
one._costs[one.features[-1].id] = 5.0
looks = one.preview_requests(3)
check("one look, without the fillet", len(looks) == 1
      and looks[0]["key"].endswith("#rough")
      and looks[0]["data"]["features"][-1].get("suppressed"),
      [r["key"] for r in looks])
result = helpers.submit_to(looks[0]["key"], "rebuild",
                           **looks[0]).result(timeout=300)
rough = one.preview_shape([result], looks)
check("and it comes back sharp", rough is not None and
      kernel.volume(rough) - kernel.volume(one.shape) > 1.0,
      (rough is not None and kernel.volume(rough), kernel.volume(one.shape),
       result.get("errors"), one.last_report.errors))
docmod.PREVIEW_FROM = 0.8
docmod.GROUP_MIN = 0.1
check("nothing to look at on a quick part",
      plates(1).preview_requests(3) == [])

helpers.shutdown()
print()
print("all passed" if not FAILS else "FAILED: %s" % FAILS)
sys.exit(1 if FAILS else 0)
