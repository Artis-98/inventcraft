"""Export one pose of the excavator for Blender: an OBJ in metres, one
object per paint, and the camera.

    .venv/Scripts/python.exe -m examples.walking_excavator.blender_export

Every part is meshed once from its own InventCraft document and placed
where the skeleton puts it; each face keeps its own vertices, so curved
faces shade smooth and edges stay sharp.  Then blender_render.py lights it.
"""
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import numpy as np
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.BRep import BRep_Tool
from OCP.TopLoc import TopLoc_Location
from OCP.TopAbs import TopAbs_REVERSED
from datum.core.document import Document
from datum.core import kernel
from . import interference as I
from .common import OUT

DEST = OUT / 'renders/blender'


def showcase_pose():
    """The transport stance, bucket tucked in by the front wheel."""
    from examples.build_walking_excavator import poses, grounded
    return grounded(dict(poses()['Transport'], dipper_angle=-118.0, bucket_curl=75.0))


def material(appearance):
    a = (appearance or '').lower()
    return 'glass' if 'glass' in a else 'c' + a.lstrip('#')


def mesh(shape):
    """(vertices, triangles) of a shape, in its own coordinates."""
    BRepMesh_IncrementalMesh(shape, 0.4, False, 0.25, True)
    verts, tris = [], []
    for face in kernel.faces(shape):
        loc = TopLoc_Location()
        tri = BRep_Tool.Triangulation_s(face, loc)
        if tri is None:
            continue
        trsf = loc.Transformation()
        base = len(verts)
        for i in range(1, tri.NbNodes() + 1):
            p = tri.Node(i).Transformed(trsf)
            verts.append((p.X(), p.Y(), p.Z()))
        flip = face.Orientation() == TopAbs_REVERSED
        for i in range(1, tri.NbTriangles() + 1):
            a, b, c = tri.Triangle(i).Get()
            tris.append((base + a - 1, base + c - 1, base + b - 1) if flip else
                        (base + a - 1, base + b - 1, base + c - 1))
    return np.asarray(verts, float), tris


def main():
    DEST.mkdir(parents=True, exist_ok=True)
    p = showcase_pose()
    cache = {}
    groups = defaultdict(list)
    lo, hi = np.full(3, 1e18), np.full(3, -1e18)
    for name, group, path, pl in I.world(I.recipes(), p):
        if path not in cache:
            doc = Document.load(path)
            cache[path] = (mesh(doc.shape), doc.appearance) if doc.shape is not None else None
        if cache[path] is None:
            continue
        (verts, tris), appearance = cache[path]
        if not len(verts):
            continue
        m = pl.matrix()
        world = verts @ m.T + np.asarray(pl.position)
        if np.linalg.det(m) < 0:
            tris = [(a, c, b) for a, b, c in tris]
        groups[material(appearance)].append((world, tris))
        lo = np.minimum(lo, world.min(0))
        hi = np.maximum(hi, world.max(0))
    obj = DEST / 'excavator.obj'
    with obj.open('w', encoding='utf-8') as out:
        n = 1
        for mat, parts in sorted(groups.items()):
            out.write('o %s\nusemtl %s\n' % (mat, mat))
            for world, tris in parts:
                for v in world * 0.001:
                    out.write('v %.5f %.5f %.5f\n' % tuple(v))
                for a, b, c in tris:
                    out.write('f %d %d %d\n' % (a + n, b + n, c + n))
                n += len(world)
    centre = (lo + hi) / 2 * 0.001
    d = np.asarray((0.95, 0.75, 0.45))
    d /= np.linalg.norm(d)
    radius = np.linalg.norm(hi - lo) / 2 * 0.001
    scene = dict(obj=str(obj), materials=sorted(groups), ground_z=float(lo[2]) * 0.001,
                 target=centre.tolist(), direction=d.tolist(), radius=float(radius),
                 pose=p)
    (DEST / 'scene.json').write_text(json.dumps(scene, indent=1), encoding='utf-8')
    print('exported', sum(len(v) for v in groups.values()), 'parts in', len(groups), 'paints to', obj)


if __name__ == '__main__':
    main()
