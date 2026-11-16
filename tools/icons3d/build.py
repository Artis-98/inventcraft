"""Build all InventCraft 3D icons, or pass one or more icon names."""
import argparse
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess

from OCP.Bnd import Bnd_Box
from OCP.BRepBndLib import BRepBndLib
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.StlAPI import StlAPI_Writer

from models import MODELS

REPO = Path(__file__).resolve().parents[2]
WORK = REPO / 'build/icons3d'
ASSETS = REPO / 'datum/ui/assets/icons'
BLENDER = Path(r'C:\Program Files\Blender Foundation\Blender 5.2\blender.exe')


def mesh(name, destination):
    destination.mkdir(parents=True, exist_ok=True)
    groups = MODELS[name]()
    if not groups or groups.keys() - {'body', 'accent', 'line'}:
        raise ValueError(f'Invalid groups for {name}: {groups.keys()}')
    for previous in destination.glob('*.stl'):
        previous.unlink()
    for material, shape in groups.items():
        if shape.IsNull():
            raise ValueError(f'{name}/{material} is empty')
        bounds = Bnd_Box()
        BRepBndLib.AddOptimal_s(shape, bounds, False, False)
        if bounds.IsVoid() or max(map(abs, bounds.Get())) > 5.001:
            raise ValueError(f'{name}/{material} exceeds the 10 mm cube: {bounds.Get()}')
        BRepMesh_IncrementalMesh(shape, .01, False, .20, True)
        writer = StlAPI_Writer()
        writer.ASCIIMode = False
        if not writer.Write(shape, str(destination / f'{material}.stl')):
            raise RuntimeError(f'STL export failed for {name}/{material}')


def png_size(path):
    with path.open('rb') as file:
        header = file.read(26)
    if header[:8] != b'\x89PNG\r\n\x1a\n' or header[12:16] != b'IHDR':
        raise ValueError(f'Not a PNG: {path}')
    width, height, depth, color = struct.unpack('>IIBB', header[16:26])
    if (width, height, depth, color) != (256, 256, 8, 6):
        raise ValueError(f'Expected 256×256 RGBA8: {path}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('names', nargs='*', metavar='ICON')
    parser.add_argument('--blender', type=Path, default=Path(os.environ.get('INVENTCRAFT_BLENDER', BLENDER)))
    args = parser.parse_args()
    unknown = sorted(set(args.names) - MODELS.keys())
    if unknown:
        parser.error('unknown icons: ' + ', '.join(unknown))
    if not args.blender.is_file():
        parser.error(f'Blender not found: {args.blender}')
    names = list(dict.fromkeys(args.names)) or list(MODELS)
    WORK.mkdir(parents=True, exist_ok=True)
    staging = WORK / 'png'
    staging.mkdir(exist_ok=True)
    outputs = [staging / f'{name}{suffix}.png' for name in names for suffix in ('', '.dark')]
    for path in outputs:
        path.unlink(missing_ok=True)
    for name in names:
        mesh(name, WORK / name)
    (WORK / 'manifest.json').write_text(json.dumps(names), encoding='utf-8')
    subprocess.run([str(args.blender), '--background', '--factory-startup', '--threads', '4',
                    '--python-exit-code', '1', '--python', str(Path(__file__).with_name('render.py')),
                    '--', str(WORK), '--output', str(staging)], cwd=REPO, check=True)
    for path in outputs:
        png_size(path)
    for path in outputs:
        shutil.copyfile(path, ASSETS / path.name)
    print(f'Installed {len(outputs)} PNGs for {len(names)} icons.')
    if not args.names:
        from svg import update_svg
        print(f'Updated {update_svg(ASSETS)} SVGs.')


if __name__ == '__main__':
    main()
