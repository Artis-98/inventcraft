"""Find every place two parts of the excavator occupy the same space.

    .venv/Scripts/python.exe -m examples.walking_excavator.interference [pose ...]

Each pose is flattened to its parts in world space; parts whose boxes
overlap are intersected, and any common volume over 1 mm3 is reported.
Parts that touch (welds, a pin in its bore, a nut on its stud) share no
volume and pass.  With --sweep, every control is also run to both ends of
its range from the Level pose.
"""
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from datum.core.assembly import AssemblyDocument
from datum.core.document import Document
from datum.core.constraints3d import Placement
from datum.core import kernel
from OCP.BRepAlgoAPI import BRepAlgoAPI_Common
from OCP.Bnd import Bnd_Box
from OCP.BRepBndLib import BRepBndLib
from OCP.TopLoc import TopLoc_Location
from OCP.GProp import GProp_GProps
from OCP.BRepGProp import BRepGProp
from . import motion as M
from .common import OUT

_shapes = {}
_flat = {}


def part_shape(path):
    if path not in _shapes:
        doc = Document.load(path)
        _shapes[path] = doc.shape
    return _shapes[path]


def flatten(path, placement=None, prefix=''):
    """(name, part path, world placement) for every part under an assembly."""
    key = str(path)
    if key not in _flat:
        ass = AssemblyDocument.load(key)
        rows = []
        for occ in ass.occurrences:
            sub = ass.component_path(occ)
            if sub is None:
                continue
            if sub.endswith('.icasm'):
                for name, p, pl in flatten(sub):
                    rows.append((occ.ref.label + '/' + name, p, _mul(occ.placement, pl)))
            else:
                rows.append((occ.ref.label, sub, occ.placement))
        _flat[key] = rows
    return _flat[key]


def _mul(a, b):
    import numpy as np
    from datum.core.constraints3d import rotation_vector
    xyz = a.matrix() @ np.asarray(b.position) + np.asarray(a.position)
    return Placement(list(xyz), list(rotation_vector(a.matrix() @ b.matrix())))


def world(recipes, p):
    """Every part of the machine in pose p: (name, group, path, placement)."""
    f = M.skeleton(p)
    out = []
    for r in recipes:
        frame = M.recipe_frame(r, f)
        top = Placement(list(frame[0]), list(M.rotation_vector(frame[1])))
        part = str(OUT / r['part'])
        if part.endswith('.icasm'):
            for name, sub, pl in flatten(part):
                out.append((r['label'] + '/' + name, r['label'], sub, _mul(top, pl)))
        else:
            out.append((r['label'], r['label'], part, top))
    return out


def located(path, placement):
    shape = part_shape(path)
    if shape is None:
        return None
    return shape.Moved(TopLoc_Location(placement.trsf()))


def box(shape):
    b = Bnd_Box()
    BRepBndLib.Add_s(shape, b, True)
    return b.Get()


def common_volume(a, b):
    op = BRepAlgoAPI_Common(a, b)
    if not op.IsDone():
        return -1.0
    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(op.Shape(), props)
    return props.Mass()


def check(recipes, p, only_between_groups=False, tol=1.0):
    items = []
    for name, group, path, pl in world(recipes, p):
        s = located(path, pl)
        if s is None:
            continue
        items.append((name, group, s, box(s)))
    hits = []
    n = len(items)
    for i in range(n):
        ni, gi, si, bi = items[i]
        for j in range(i + 1, n):
            nj, gj, sj, bj = items[j]
            if only_between_groups and gi == gj:
                continue
            if (bi[3] < bj[0] + 0.2 or bj[3] < bi[0] + 0.2 or bi[4] < bj[1] + 0.2 or
                    bj[4] < bi[1] + 0.2 or bi[5] < bj[2] + 0.2 or bj[5] < bi[2] + 0.2):
                continue
            v = common_volume(si, sj)
            if v > tol:
                hits.append((round(v, 1), ni, nj))
    hits.sort(reverse=True)
    return hits


def recipes():
    return json.loads((OUT / 'assembly-recipes.json').read_text(encoding='utf-8'))


def main():
    from examples.build_walking_excavator import poses, base_parameters
    from examples.walking_excavator import controls
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    sweep = '--sweep' in sys.argv
    rs = recipes()
    all_poses = poses()
    report = {}
    names = args or (list(all_poses) if not sweep else [])
    for name in names:
        hits = check(rs, all_poses[name], only_between_groups=name != names[0])
        report[name] = hits
        print('%s: %d interferences' % (name, len(hits)), flush=True)
        for h in hits[:60]:
            print('   %10.1f mm3  %s  x  %s' % h)
    if sweep:
        level = all_poses['Level']
        for title, sets in controls.control_sets().items():
            for _, key, lo, hi, _, _ in sets:
                if title.startswith('Leg') and not key.endswith('FL'):
                    continue
                for value in (lo, hi):
                    p = dict(level, **{key: value})
                    if key in ('ride_height',):
                        continue
                    hits = check(rs, p, only_between_groups=True)
                    label = '%s=%g' % (key, value)
                    report[label] = hits
                    print('%s: %d' % (label, len(hits)), flush=True)
                    for h in hits[:20]:
                        print('   %10.1f mm3  %s  x  %s' % h)
    (OUT / 'interference.json').write_text(json.dumps(report, indent=1), encoding='utf-8')


if __name__ == '__main__':
    main()
