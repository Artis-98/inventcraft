"""The chassis weldment, its slew pedestal and the hip swivel bearings.

Chassis frame: origin at the weldment's centre, the top plate's top at
Z 180, the slew bearing's top at UPPER_Z.  The side walls are two press
braked bands, each bent four times round half the octagon, that unfold
to flat strips; the top and bottom plates carry a lobe at each corner
for a hip's swivel pin.
"""
import math
import numpy as np

from . import motion as M
from .common import (Library, xy, xz, yz, ALONG_Y, rotation, NAVY, GOLD, DARK,
                     STEEL, BRONZE, circle)
from .beam import pin
from .legs import ring, holes
from datum.core.features import CUT

CX, CY, C = 760.0, 420.0, 260.0
WALL, BEND = 12.0, 30.0
LOBE = 130.0
OCTAGON = [(CX, -CY + C), (CX, CY - C), (CX - C, CY), (-CX + C, CY), (-CX, CY - C),
           (-CX, -CY + C), (-CX + C, -CY), (CX - C, -CY)]


def plate_outline():
    """The octagon with a lobe on each chamfer, round its hip's pin."""
    pts, radii = [], []
    n = len(OCTAGON)
    for i in range(n):
        a = np.array(OCTAGON[i])
        b = np.array(OCTAGON[(i + 1) % n])
        pts.append(tuple(a))
        radii.append(BEND + WALL)
        hip = next((h for h in M.HIP.values()
                    if abs(abs(h[0]) - CX) < 100 and np.sign(h[0]) == np.sign(a[0] + b[0])
                    and np.sign(h[1]) == np.sign(a[1] + b[1])), None)
        if hip is None or abs(a[0]) == abs(b[0]):
            continue
        if abs(a[1]) == abs(b[1]):
            continue
        v = (b - a) / np.linalg.norm(b - a)
        m = (a + b) / 2
        out = np.array(hip) - m
        nrm = out / np.linalg.norm(out)
        for q, r in ((m - LOBE * v, 20), (np.array(hip) - LOBE * v + LOBE * nrm, LOBE),
                     (np.array(hip) + LOBE * v + LOBE * nrm, LOBE), (m + LOBE * v, 20)):
            pts.append(tuple(q))
            radii.append(r)
    return pts, radii


def build(lib):
    put = lambda n, part, pos=(0, 0, 0), rot=(0, 0, 0): lib.put(n, part, pos, rot, 'chassis')
    outline, radii = plate_outline()
    hip_holes = [(h, 60.3) for h in M.HIP.values()]
    for label, z in (('top', 160), ('bottom', -180)):
        doc = lib.doc(DARK)
        lib.plate(doc, 'Chassis %s plate' % label, outline, 20, xy(z), radii=radii,
                  holes=hip_holes + ([((0, 0), 120)] if label == 'top' else []))
        put('Chassis %s plate' % label, lib.save(doc, 'Chassis %s plate 20mm' % label))
    for label, path in (('front', [(0, -CY)] + OCTAGON[-1:] + OCTAGON[:3] + [(0, CY)]),
                        ('rear', [(0, CY)] + OCTAGON[3:7] + [(0, -CY)])):
        doc = lib.doc(NAVY)
        lib.contour(doc, 'Chassis %s wall' % label, xy(-160), path, 320, WALL, BEND,
                    'positive', flipped=True)
        put('Chassis %s wall' % label, lib.save(doc, 'Chassis %s wall 12mm bent' % label))
    # spread ram base lugs, a pair each on the front and rear walls
    sx, sy = M.SPREAD_BASE_X, M.SPREAD_BASE_Y
    doc = lib.doc(DARK)
    lib.plate(doc, 'Spread base lug', [(CX, sy - 45), (sx + 45, sy - 45), (sx + 45, sy + 45), (CX, sy + 45)],
              18, xy(M.SPREAD_Z + 22), radii=[0, 45, 45, 0], holes=[((sx, sy), 20.3)])
    lug = lib.save(doc, 'Chassis spread ram lug 18mm')
    spin = pin(lib, 'Spread ram pin', 20, 80)
    for side in M.SIDES:
        fx = 1 if side[0] == 'F' else -1
        fy = 1 if side[1] == 'L' else -1
        for level in ('upper', 'lower'):
            pos, rot = _lug_place(fx, fy, level, sy, 2 * M.SPREAD_Z)
            put('Spread base lug %s %s' % (side, level), lug, pos, rot)
        put('Spread base pin %s' % side, spin, (fx * sx, fy * sy, M.SPREAD_Z))
    # hip swivel pins
    swivel = pin(lib, 'Hip swivel pin', 60, 360)
    for side, (x, y) in M.HIP.items():
        put('Hip swivel pin %s' % side, swivel, (x, y, 0))
    # slew pedestal: rolled tube with two access windows, flange, bearing
    doc = lib.doc(DARK)
    lib.lathe(doc, 'Pedestal tube', [(415, 180), (440, 180), (440, 540), (415, 540)])
    lib.extrude(doc, 'Pedestal access windows', [(-170, 260), (170, 260), (170, 470), (-170, 470)],
                1000, xz(0), op=CUT, radii=50, symmetric=True)
    put('Slew pedestal', lib.save(doc, 'Slew pedestal tube 25mm'))
    doc = lib.doc(DARK)
    lib.lathe(doc, 'Pedestal flange', [(380, 540), (500, 540), (500, 560), (380, 560)])
    bolts = [(485 * math.cos(k * math.tau / 24), 485 * math.sin(k * math.tau / 24)) for k in range(24)]
    holes(lib, doc, 'Flange bolt holes', xy(550), bolts, 10.5, 30)
    put('Pedestal flange', lib.save(doc, 'Slew pedestal flange 20mm'))
    doc = lib.doc(STEEL)
    lib.lathe(doc, 'Slew ring outer race', [(450, 560), (520, 560), (520, 594), (516, 598), (450, 598)])
    holes(lib, doc, 'Race bolt holes', xy(580), bolts, 10.5, 50)
    put('Slew bearing outer race', lib.save(doc, 'Slew bearing outer race'))
    doc = lib.doc(STEEL)
    lib.lathe(doc, 'Slew bolt', [(0, 524), (16, 524), (18, 526), (18, 538), (10, 540), (10, 594), (9, 596), (0, 596)])
    bolt = lib.save(doc, 'Slew bolt M20')
    for k, (x, y) in enumerate(bolts):
        put('Slew bolt %d' % (k + 1), bolt, (x, y, 0))
    # the rotary union carries the circuits up through the slew
    doc = lib.doc(GOLD)
    lib.lathe(doc, 'Rotary union', [(0, 180), (110, 180), (110, 200), (85, 205), (85, 560), (70, 575),
                                    (70, 640), (0, 640)])
    put('Hydraulic rotary union', lib.save(doc, 'Hydraulic rotary union'))
    # distribution manifold and its hardlines to the four hips
    doc = lib.doc(GOLD)
    lib.extrude(doc, 'Manifold block', [(470, -120), (700, -120), (700, 120), (470, 120)], 110, xy(180), radii=12)
    put('Leg circuit manifold', lib.save(doc, 'Leg circuit manifold'))
    return dict(lug=lug)


def _lug_place(fx, fy, level, sy, z2=0.0):
    """Where the base lug plate, drawn upper at +X+Y and symmetric about
    its own pin's Y, goes for one corner and level."""
    pi = math.pi
    table = {(1, 1, 'upper'): ((0, 0, 0), (0, 0, 0)),
             (1, 1, 'lower'): ((0, 2 * sy, z2), (pi, 0, 0)),
             (1, -1, 'upper'): ((0, -2 * sy, 0), (0, 0, 0)),
             (1, -1, 'lower'): ((0, 0, z2), (pi, 0, 0)),
             (-1, -1, 'upper'): ((0, 0, 0), (0, 0, pi)),
             (-1, -1, 'lower'): ((0, -2 * sy, z2), (0, pi, 0)),
             (-1, 1, 'upper'): ((0, 2 * sy, 0), (0, 0, pi)),
             (-1, 1, 'lower'): ((0, 0, z2), (0, pi, 0))}
    return table[(fx, fy, level)]
