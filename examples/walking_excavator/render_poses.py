"""Full-size renders of every saved pose from several angles.

    .venv/Scripts/python.exe -m examples.walking_excavator.render_poses

Writes renders/poses/<pose>-<angle>.png at 3840 x 2160, each through
InventCraft's own ray tracer, one InventCraft session per image.
"""
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'examples/walking-excavator'
ANGLES = {
    'front-left': (0.95, 0.75, 0.45),
    'front-right': (0.95, -0.8, 0.4),
    'rear-left': (-0.85, 0.95, 0.55),
    'side': (0.0, 1.0, 0.12),
    'low-front': (1.0, -0.35, 0.08),
}
POSES = ('Hero', 'Reach', 'Spider', 'Heels', 'Transport')


def main():
    dest = OUT / 'renders/poses'
    dest.mkdir(parents=True, exist_ok=True)
    tmp = ROOT / 'build/wx-pose-render'
    done = []
    poses = sys.argv[1:] or POSES
    for pose in poses:
        for name, cam in ANGLES.items():
            if tmp.exists():
                shutil.rmtree(tmp)
            cmd = [sys.executable, '-m', 'examples.walking_excavator.render', '--quick', '--width', '3840',
                   '--assembly', str(OUT / 'poses' / (pose + '.icasm')), '--output', str(tmp),
                   '--hero-camera', *map(str, cam), '--hero-scale', '1.0']
            result = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True, timeout=900)
            image = tmp / 'hero.png'
            if result.returncode == 0 and image.exists():
                target = dest / ('%s-%s.png' % (pose.lower(), name))
                shutil.copy(image, target)
                done.append(target.name)
                print('rendered', target.name, flush=True)
            else:
                print('FAILED', pose, name, result.stderr[-400:], flush=True)
    print('%d of %d renders' % (len(done), len(poses) * len(ANGLES)))
    return 0 if len(done) == len(poses) * len(ANGLES) else 1


if __name__ == '__main__':
    raise SystemExit(main())
