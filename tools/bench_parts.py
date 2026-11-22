"""Time rebuilding parts from scratch, and where the time goes.

    .venv/Scripts/python.exe tools/bench_parts.py [folder or part ...]

Every part is loaded and rebuilt with nothing reused, the slowest are
listed, and a profile of the whole run says which calls took the time.
"""
import cProfile
import glob
import os
import pstats
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["DATUM_FULL_REBUILD"] = "1"
os.environ.setdefault("DATUM_NO_WORKERS", "1")

from datum.core.document import Document                      # noqa: E402

args = [a for a in sys.argv[1:] if not a.startswith("--")]
paths = []
for a in args or [os.path.join(ROOT, "examples", "walking-excavator",
                               "parts")]:
    if os.path.isdir(a):
        paths += sorted(glob.glob(os.path.join(a, "*.icpart")))
    else:
        paths.append(a)

times = []
profiler = cProfile.Profile()
for path in paths:
    try:
        doc = Document.load(path)
    except Exception as exc:
        print("cannot load", path, exc)
        continue
    profiler.enable()
    t = time.perf_counter()
    report = doc.rebuild()
    took = time.perf_counter() - t
    profiler.disable()
    times.append((took, os.path.basename(path), len(doc.features),
                  report.ok))
times.sort(reverse=True)
print("total %.2f s over %d parts" % (sum(t for t, *_ in times),
                                      len(times)))
for took, name, count, ok in times[:12]:
    print("  %6.2f s  %3d features  %s%s" % (took, count, name,
                                            "" if ok else "  (errors)"))
if "--profile" in sys.argv:
    pstats.Stats(profiler).sort_stats("tottime").print_stats(18)
