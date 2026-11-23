"""Rebuild parts and compare what they became, between two checkouts.

For a change that touches how every part finds its faces and edges: the
example parts must come out the same with it as without it. Measure in
each checkout, then compare:

    python tools/compare_models.py measure before.json   (on main)
    python tools/compare_models.py measure after.json    (on the branch)
    python tools/compare_models.py diff before.json after.json

or in one checkout, with the face and edge tracking switched off and on:

    python tools/compare_models.py toggle

``measure`` takes part files or folders after the output file (default:
every .icpart under examples/). Each part is rebuilt from its tree, the
body cache off, and read with OpenCASCADE's plain integration, so the
numbers do not depend on the code being compared: rebuild errors, solids,
faces, edges, vertices, volume, area and bounding box.
"""

from __future__ import annotations

import concurrent.futures
import json
import os
import subprocess
import sys
from typing import Any, Dict, List

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REL = 1e-6          # how far volume and area may differ, as a fraction
ABS = 1e-6          # and the bounding box, in mm


def _parts(paths: List[str]) -> List[str]:
    out = []
    for path in paths or [os.path.join(ROOT, "examples")]:
        if os.path.isdir(path):
            for folder, _dirs, files in os.walk(path):
                out += [os.path.join(folder, f) for f in files
                        if f.lower().endswith(".icpart")]
        elif path.lower().endswith(".icpart"):
            out.append(path)
    return sorted(os.path.abspath(p) for p in out)


def _measure_one(path: str) -> Dict[str, Any]:
    os.environ["DATUM_NO_BODY_CACHE"] = "1"
    sys.path.insert(0, ROOT)
    from OCP.BRepBndLib import BRepBndLib
    from OCP.BRepGProp import BRepGProp
    from OCP.Bnd import Bnd_Box
    from OCP.GProp import GProp_GProps
    from OCP.TopAbs import (TopAbs_EDGE, TopAbs_FACE, TopAbs_SOLID,
                            TopAbs_VERTEX)
    from OCP.TopExp import TopExp
    from OCP.TopTools import TopTools_IndexedMapOfShape
    from datum.core.document import Document

    def count(shape, kind) -> int:
        found = TopTools_IndexedMapOfShape()
        TopExp.MapShapes_s(shape, kind, found)
        return found.Extent()

    try:
        doc = Document.load(path, build=False)
        report = doc.rebuild()
        shape = doc.shape
        out: Dict[str, Any] = {
            "errors": sorted(str(m) for _f, m in report.errors)}
        if shape is None or shape.IsNull():
            out["empty"] = True
            return out
        vol, area = GProp_GProps(), GProp_GProps()
        BRepGProp.VolumeProperties_s(shape, vol)
        BRepGProp.SurfaceProperties_s(shape, area)
        box = Bnd_Box()
        BRepBndLib.Add_s(shape, box)
        out.update(solids=count(shape, TopAbs_SOLID),
                   faces=count(shape, TopAbs_FACE),
                   edges=count(shape, TopAbs_EDGE),
                   vertices=count(shape, TopAbs_VERTEX),
                   volume=vol.Mass(), area=area.Mass(),
                   bbox=list(box.Get()) if not box.IsVoid() else [])
        return out
    except Exception as exc:                            # noqa: BLE001
        return {"crash": "%s: %s" % (type(exc).__name__, exc)}


def measure(out_file: str, paths: List[str], jobs: int = 0) -> int:
    parts = _parts(paths)
    jobs = jobs or max(1, (os.cpu_count() or 2) - 1)
    results: Dict[str, Any] = {}
    with concurrent.futures.ProcessPoolExecutor(jobs) as pool:
        for path, found in zip(parts, pool.map(_measure_one, parts)):
            results[os.path.relpath(path, ROOT).replace(os.sep, "/")] = found
    with open(out_file, "w", encoding="utf-8") as handle:
        json.dump(results, handle, indent=1, sort_keys=True)
    print("%d part(s) measured into %s" % (len(results), out_file))
    return 0


def _differs(a: Any, b: Any, key: str) -> bool:
    if key in ("volume", "area"):
        return abs(a - b) > REL * max(abs(a), abs(b), 1.0)
    if key == "bbox":
        return len(a) != len(b) or any(abs(x - y) > ABS
                                       for x, y in zip(a, b))
    return a != b


def diff(before_file: str, after_file: str) -> int:
    with open(before_file, encoding="utf-8") as handle:
        before = json.load(handle)
    with open(after_file, encoding="utf-8") as handle:
        after = json.load(handle)
    changed = []
    for part in sorted(set(before) | set(after)):
        a, b = before.get(part), after.get(part)
        if a is None or b is None:
            changed.append("%s: only in %s" % (
                part, "after" if a is None else "before"))
            continue
        for key in sorted(set(a) | set(b)):
            if key not in a or key not in b or _differs(a[key], b[key], key):
                changed.append("%s: %s %s -> %s" % (part, key, a.get(key),
                                                    b.get(key)))
    same = len(set(before) & set(after))
    print("%d part(s) compared" % same)
    for line in changed:
        print("  DIFFERS  " + line)
    print("all the same" if not changed else "%d difference(s)"
          % len(changed))
    return 1 if changed else 0


def toggle(paths: List[str]) -> int:
    """Measure with the face and edge tracking off, then on, and compare."""
    import tempfile
    folder = tempfile.mkdtemp(prefix="compare_models_")
    off, on = os.path.join(folder, "off.json"), os.path.join(folder,
                                                             "on.json")
    for target, flag in ((off, "1"), (on, "")):
        env = dict(os.environ)
        env.pop("DATUM_NO_PROVENANCE", None)
        if flag:
            env["DATUM_NO_PROVENANCE"] = flag
        subprocess.run([sys.executable, os.path.abspath(__file__), "measure",
                        target] + list(paths), env=env, check=True)
    return diff(off, on)


def main(argv: List[str]) -> int:
    if len(argv) >= 2 and argv[0] == "measure":
        return measure(argv[1], argv[2:])
    if len(argv) == 3 and argv[0] == "diff":
        return diff(argv[1], argv[2])
    if argv and argv[0] == "toggle":
        return toggle(argv[1:])
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
