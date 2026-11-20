"""Reopen every part, count the bill of materials, lay the bent plates flat.

    .venv/Scripts/python.exe -m examples.walking_excavator.validate

Writes validation.json, bom.csv, flat-patterns/*.dxf and a cut list of the
rigid hydraulic tubes.  Every part must rebuild and be a valid solid.
"""
import csv
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from datum.core.document import Document
from datum.core.features import ContourFlangeFeature, FlangeFeature, PipeRunFeature
from datum.core import kernel
from datum.core.sheetmetal import unfold
from datum.core.piping import route
from OCP.BRepCheck import BRepCheck_Analyzer
from .common import OUT, PARTS
from .interference import recipes, world
from . import motion as M


def main():
    from examples.build_walking_excavator import poses
    report = {'parts': {}, 'errors': [], 'flat_patterns': {}, 'tubes': []}
    flats = OUT / 'flat-patterns'
    flats.mkdir(exist_ok=True)
    for old in flats.glob('*'):
        old.unlink()
    files = sorted(set(PARTS.glob('*.icpart')) | set((OUT / 'subassemblies').rglob('*.icpart')))
    docs = {}
    for file in files:
        doc = Document.load(str(file))
        docs[str(file.resolve())] = doc
        if doc.shape is None:
            continue        # a skeleton holds only sketches
        ok = doc.last_report.ok and BRepCheck_Analyzer(doc.shape).IsValid()
        volume = kernel.volume(doc.shape)
        report['parts'][file.stem] = dict(ok=ok, mass_kg=round(volume * doc.density / 1e6, 3),
                                          material=doc.material)
        if not ok:
            report['errors'].append(file.name + ' does not rebuild to a valid solid')
        bent = [f for f in doc.features if isinstance(f, (ContourFlangeFeature, FlangeFeature))]
        if bent:
            try:
                t = doc.sheet_metal.thickness if doc.sheet_metal else None
                flat = unfold(doc.shape, 0.44, thickness=float(t) if t else None)
                from datum.core.dxf import face_to_dxf
                face_to_dxf(max(kernel.faces(flat.solid), key=kernel.face_area),
                            str(flats / (file.stem + ' flat.dxf')))
                w, h = flat.extents()
                report['flat_patterns'][file.stem] = dict(bends=len(flat.bends),
                                                          blank_mm=[round(w, 1), round(h, 1)])
            except Exception as exc:
                report['errors'].append('%s: no flat pattern (%s)' % (file.stem, exc))
        for f in doc.features:
            if isinstance(f, PipeRunFeature):
                r = route(f.points, f.radius)
                report['tubes'].append([file.stem, f.d, f.t, f.radius, round(r.length, 1), len(r.bends)])
    # bill of materials: every part in the machine, counted where it sits
    count = Counter()
    for name, group, path, pl in world(recipes(), poses()['Level']):
        count[str(Path(path).resolve())] += 1
    total = 0.0
    with (OUT / 'bom.csv').open('w', newline='', encoding='utf-8') as handle:
        out = csv.writer(handle)
        out.writerow(['Part', 'Quantity', 'Material', 'Unit mass kg', 'Total kg'])
        for path, n in sorted(count.items(), key=lambda kv: Path(kv[0]).stem):
            doc = docs.get(path) or Document.load(path)
            if doc.shape is None:
                continue
            mass = kernel.volume(doc.shape) * doc.density / 1e6
            total += mass * n
            out.writerow([Path(path).stem, n, doc.material, round(mass, 3), round(mass * n, 2)])
    with (OUT / 'rigid-tube-cut-list.csv').open('w', newline='', encoding='utf-8') as handle:
        out = csv.writer(handle)
        out.writerow(['Tube', 'OD mm', 'Wall mm', 'Bend radius mm', 'Developed length mm', 'Bends'])
        out.writerows(report['tubes'])
    report['machine'] = dict(parts_placed=sum(count.values()), distinct_parts=len(count),
                             mass_kg=round(total, 1))
    fam = json.loads((OUT / 'ram-families.json').read_text())
    report['cylinders'] = {k: dict(closed_mm=v['closed'], stroke_mm=v['stroke'],
                                   span_used_mm=[round(x, 1) for x in v['span']]) for k, v in fam.items()}
    (OUT / 'validation.json').write_text(json.dumps(report, indent=1), encoding='utf-8')
    print('%d parts, %d placed, %.0f kg; %d flat patterns; %d tubes; errors: %s'
          % (len(report['parts']), sum(count.values()), total, len(report['flat_patterns']),
             len(report['tubes']), report['errors'] or 'none'))
    return 1 if report['errors'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
