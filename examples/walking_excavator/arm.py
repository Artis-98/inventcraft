"""The digging arm: boom, dipper, bucket linkage, tiltrotator and bucket.

Boom frame: foot pin at the origin, dipper pin at X = BOOM_LENGTH.  Dipper
frame: its root pin at the origin, the attachment pin at DIPPER_LENGTH.
Attachment frame: the attachment pin; its X runs on to the tiltrotator.
Tilt frame: the tilt pin, Z its axis; bucket frame: the rotator's output,
X out of it, the bucket hanging along +X and opening towards -Z.
"""
import math
import numpy as np

from . import motion as M
from .common import (Library, xy, xz, yz, ALONG_Y, ALONG_X, rotation, NAVY, GOLD,
                     DARK, STEEL, CHROME, BRONZE, circle)
from .beam import Beam, boss, pin, turn
from .legs import ring, holes

BL, DL = M.BOOM_LENGTH, M.DIPPER_LENGTH


def z_on(line, x):
    for a, b in zip(line, line[1:]):
        if (a[0] - x) * (b[0] - x) <= 0 and a[0] != b[0]:
            return a[1] + (x - a[0]) / (b[0] - a[0]) * (b[1] - a[1])
    raise ValueError('off the line')


def lug(lib, name, line, x0, x1, at, r_out, bore, inner, t, group, below=False,
        color=NAVY, bend=0):
    """A pair of lug plates standing on a cap's outer face at x0..x1, their
    pin at ``at``.  Kinks of the cap between x0 and x1 are followed, rounded
    as the cap's face is."""
    base = [(x0, z_on(line, x0))] + [p for p in line if x0 < p[0] < x1] + [(x1, z_on(line, x1))]
    ax, az = at
    if below:
        tip = [(ax + r_out, az), (ax + r_out, az - r_out), (ax - r_out, az - r_out), (ax - r_out, az)]
        outline = list(reversed(base)) + list(reversed(tip))
        radii = [0] * len(base) + [0, r_out, r_out, 0]
        radii = [0] + [bend] * (len(base) - 2) + [0] + [0, r_out, r_out, 0]
        outline = base[::-1] + [(ax - r_out, az), (ax - r_out, az - r_out),
                                (ax + r_out, az - r_out), (ax + r_out, az)]
    else:
        outline = base + [(ax + r_out, az), (ax + r_out, az + r_out),
                          (ax - r_out, az + r_out), (ax - r_out, az)]
        radii = [0] + [bend] * (len(base) - 2) + [0] + [0, r_out, r_out, 0]
    doc = lib.doc(color)
    lib.plate(doc, name, outline, t, xz(inner + t), radii=radii, holes=[((ax, az), bore)])
    part = lib.save(doc, name + ' %gmm' % t)
    lib.put(name + ' L', part, group=group)
    lib.put(name + ' R', part, (0, -2 * inner - t, 0), group=group)
    return part


def standoff(lib, name, line, x, y, height, width, group, length=50):
    """A saddle the hardline sits on, standing on a cap's outer face."""
    pts = [(x - length / 2, z_on(line, x - length / 2)), (x + length / 2, z_on(line, x + length / 2))]
    top = [(p[0], p[1] + height) for p in reversed(pts)]
    doc = lib.doc(DARK)
    lib.extrude(doc, name, pts + top, width, xz(y + width / 2), radii=[0, 0, 4, 4])
    part = lib.save(doc, name)
    return part


def boom(lib):
    g = 'boom'
    beam = Beam(lib, 'Boom', [dict(label='foot', c=(0, 0), rb=110, bore=60.3, length=300),
                              dict(label='tip', c=(BL, 0), rb=95, bore=55.3, fork=True,
                                   hole=55.3, ring=25)],
                [(M.BOOM_KNEE[0], 520)], [(1350, 90)], 300, 14, 12, 40, g)
    beam.web()
    _, top = beam.cap('top', None, BL - 300)
    _, bottom = beam.cap('bottom', None, BL - 300)
    beam.closure(BL - 300, beam.top, beam.bottom)
    beam.bosses()
    lib.put('Boom dipper pin', pin(lib, 'Boom dipper pin', 55, 350), (BL, 0, 0), ALONG_Y, g)
    rx, rz = M.BOOM_RAM_ROD[0], M.BOOM_RAM_ROD[2]
    lug(lib, 'Boom lift ram lug', beam.bottom, rx - 140, rx + 140, (rx, rz), 60, 30.3, 37, 18, g,
        below=True, bend=40)
    lib.put('Boom lift ram rod pin', pin(lib, 'Boom ram pin', 30, 110), (rx, 0, rz), ALONG_Y, g)
    dx, dz = M.DIPPER_RAM_BASE[0], M.DIPPER_RAM_BASE[2]
    lug(lib, 'Boom dipper ram lug', beam.top, dx - 220, dx + 40, (dx, dz), 60, 30.3, 37, 18, g)
    lib.put('Boom dipper ram base pin', pin(lib, 'Boom ram pin', 30, 110), (dx, 0, dz), ALONG_Y, g)
    # twin hardlines over the top cap, on saddles, either side of the ram
    lift = 34.0
    a = (360.0, z_on(beam.top, 360.0))
    k = beam.top[1]
    b = (2240.0, z_on(beam.top, 2240.0))
    n1 = _up_normal(a, k)
    n2 = _up_normal(k, b)
    nk = (np.add(n1, n2)) / np.linalg.norm(np.add(n1, n2))
    knee = tuple(np.add(k, nk * lift / math.cos(math.acos(float(np.dot(n1, n2))) / 2)))
    for side in (1, -1):
        y = side * 100.0
        route = [(a[0] + n1[0] * lift, y, a[1] + n1[1] * lift), (knee[0], y, knee[1]),
                 (b[0] + n2[0] * lift, y, b[1] + n2[1] * lift)]
        part = lib.pipe('Boom hardline %s' % ('L' if side > 0 else 'R'), route, 22, 2.5, 110)
        lib.put('Boom hardline %s' % ('L' if side > 0 else 'R'), part, group=g)
        for x in (560, 1000, 1900):
            s = standoff(lib, 'Boom hardline saddle %d' % x, beam.top, x, 0, lift - 11, 24, g)
            lib.put('Boom hardline saddle %d %s' % (x, 'L' if side > 0 else 'R'), s, (0, y, 0), group=g)
    return beam


def _up_normal(a, b):
    d = np.subtract(b, a)
    d = d / np.linalg.norm(d)
    return np.array([-d[1], d[0]])


def dipper(lib):
    """The dipper is one box from its heel to its tip: the webs run back past
    the root pin to the heel, where the dipper ram's rod pins between them,
    and the caps close the box over the top and round the back."""
    g = 'dipper'
    hx, hz = M.DIPPER_RAM_ROD[0], M.DIPPER_RAM_ROD[2]
    beam = Beam(lib, 'Dipper', [dict(label='heel', c=(hx, hz), rb=68, bore=30.3, fork=True,
                                     hole=30.3, ring=0),
                                dict(label='tip', c=(DL, 0), rb=70, bore=42.3, fork=True,
                                     hole=42.3, ring=0)],
                [(450, 170), (1250, 135)], [(-60, -122), (450, -190), (1250, -120)], 220, 12, 10, 30, g,
                extra_bores=[((0, 0), 95), ((M.IDLER_PIVOT[0], M.IDLER_PIVOT[2]), 50)])
    beam.web()
    x0 = hx + 150
    beam.cap('top', x0, DL - 150)
    beam.cap('bottom', x0, DL - 150)
    beam.closure(x0, beam.top, beam.bottom, 'heel')
    beam.closure(DL - 150, beam.top, beam.bottom)
    lib.put('Dipper root boss', boss(lib, 'Dipper root boss', 95, 55.3, 268), (0, 0, 0), ALONG_Y, g)
    ix, iz = M.IDLER_PIVOT[0], M.IDLER_PIVOT[2]
    lib.put('Dipper idler boss', boss(lib, 'Dipper idler boss', 50, 30.3, 220), (ix, 0, iz), ALONG_Y, g)
    lib.put('Dipper idler pin', pin(lib, 'Idler pin', 30, 256), (ix, 0, iz), ALONG_Y, g)
    lib.put('Dipper attachment pin', pin(lib, 'Attachment pin', 42, 220, head=False), (DL, 0, 0), ALONG_Y, g)
    # the heel: the ram's eye between the webs, spacers either side of it
    lib.put('Dipper heel pin', pin(lib, 'Dipper heel pin', 30, 220), (hx, 0, hz), ALONG_Y, g)
    spacer = ring(lib, 'Dipper heel spacer', 45, 30.3, 0, 60, STEEL)
    lib.put('Dipper heel spacer L', spacer, (hx, 37, hz), ALONG_Y, g)
    lib.put('Dipper heel spacer R', spacer, (hx, -97, hz), ALONG_Y, g)
    top = beam.top
    bx, bz = M.BUCKET_RAM_BASE[0], M.BUCKET_RAM_BASE[2]
    lug(lib, 'Dipper bucket ram lug', top, bx - 180, bx + 40, (bx, bz), 55, 30.3, 32, 16, g)
    lib.put('Dipper bucket ram base pin', pin(lib, 'Bucket ram pin', 30, 100), (bx, 0, bz), ALONG_Y, g)
    return beam


def links(lib):
    """The idler links (a pair outside the dipper) and the bucket links (a
    pair outside them), drawn along their own X from one pin to the next."""
    out = {}
    for name, length, r, bores in (('Idler link', M.IDLER_LINK, 55, (30.3, 30.3)),
                                   ('Bucket link', M.BUCKET_LINK, 55, (30.3, 30.3))):
        # a forged dogbone: round eyes, a waist between them
        doc = lib.doc(DARK)
        w = 36.0
        lib.plate(doc, name, [(0, -r), (length / 2, -w), (length, -r), (length, r), (length / 2, w), (0, r)],
                  16, xz(0), radii=[r, 420, r, r, 420, r],
                  holes=[((0, 0), bores[0]), ((length, 0), bores[1])])
        out[name] = lib.save(doc, name + ' 16mm')
    out['joint pin'] = pin(lib, 'Linkage joint pin', 30, 300)
    out['ear pin'] = pin(lib, 'Bucket link pin', 30, 300)
    out['spacer'] = ring(lib, 'Linkage spacer sleeve', 42, 30.3, 0, 76, STEEL)
    return out


def attachment(lib):
    """Coupler head on the attachment pin, between the dipper's tip webs,
    carrying the link ear and the tiltrotator's rotary tilt actuator."""
    g = 'attachment'
    ex, ez = M.BUCKET_EAR[0], M.BUCKET_EAR[2]
    td = M.ROTATOR_DROP
    doc = lib.doc(NAVY)
    lib.plate(doc, 'Coupler side plate', [(-70, -70), (td - 40, -110), (td + 40, -110), (td + 40, 110),
                                          (td - 135, 110), (ex + 70, ez + 60), (ex - 70, ez + 60), (-70, 70)],
              20, xz(96), radii=[70, 0, 30, 30, 30, 70, 70, 60], holes=[((0, 0), 42.3), ((ex, ez), 45.3)])
    side = lib.save(doc, 'Coupler side plate 20mm')
    lib.put('Coupler side plate L', side, group=g)
    lib.put('Coupler side plate R', side, (0, -172, 0), group=g)
    lib.put('Coupler pin bush', boss(lib, 'Coupler pin bush', 62, 42.3, 152, BRONZE), (0, 0, 0), ALONG_Y, g)
    lib.put('Coupler ear boss', boss(lib, 'Coupler ear boss', 45, 30.3, 256, DARK), (ex, 0, ez), ALONG_Y, g)
    doc = lib.doc(NAVY)
    lib.plate(doc, 'Coupler web', [(80, -76), (215, -76), (215, 76), (80, 76)], 16, xy(-110))
    lib.put('Coupler web', lib.save(doc, 'Coupler web 16mm'), group=g)
    doc = lib.doc(GOLD)
    lib.lathe(doc, 'Tilt actuator', [(0, -110), (70, -110), (76, -104), (76, 104), (70, 110), (0, 110)])
    lib.put('Helical rotary tilt actuator', lib.save(doc, 'Tiltrotator rotary tilt actuator'),
            (td, 0, 0), group=g)


def rotator(lib):
    """The tilt yoke round the actuator and the rotator it carries, in the
    tilt frame: the tilt axis is Z through the origin, the rotator on X."""
    g = 'tilt'
    doc = lib.doc(DARK)
    lib.plate(doc, 'Tilt yoke plate', [(-120, -120), (150, -120), (150, 120), (-120, 120)], 30, xy(112),
              radii=[120, 0, 0, 120])
    yoke = lib.save(doc, 'Tilt yoke plate 30mm')
    lib.put('Tilt yoke upper', yoke, group=g)
    lib.put('Tilt yoke lower', yoke, (0, 0, -254), group=g)
    doc = lib.doc(DARK)
    lib.plate(doc, 'Rotator mount plate', [(-120, -142), (120, -142), (120, 142), (-120, 142)], 30, yz(150),
              radii=20)
    lib.put('Rotator mount plate', lib.save(doc, 'Rotator mount plate 30mm'), group=g)
    doc = lib.doc(GOLD)
    lib.lathe(doc, 'Rotator housing', [(0, 180), (150, 180), (160, 190), (160, 288), (150, 298), (0, 298)])
    lib.put('Rotator housing', lib.save(doc, 'Tiltrotator rotator housing'), (0, 0, 0), ALONG_X, g)
    doc = lib.doc(DARK)
    lib.lathe(doc, 'Rotator motor', [(0, 0), (55, 0), (55, 110), (45, 120), (0, 120)])
    lib.put('Rotator drive motor', lib.save(doc, 'Rotator hydraulic motor'), (240, 0, 160), group=g)


def bucket(lib):
    """Quick coupler on the rotator's output and the bucket it holds."""
    g = 'bucket'
    doc = lib.doc(STEEL)
    lib.lathe(doc, 'Rotator output flange', [(0, 300), (160, 300), (165, 305), (165, 330), (0, 330)])
    lib.put('Rotator output flange', lib.save(doc, 'Rotator output flange'), (0, 0, 0), ALONG_X, g)
    doc = lib.doc(DARK)
    lib.plate(doc, 'Quick coupler plate', [(-200, -130), (200, -130), (200, 150), (-200, 150)], 25, yz(330),
              radii=30)
    lib.put('Quick coupler plate', lib.save(doc, 'Quick coupler plate 25mm'), group=g)
    pins = ((400.0, -60.0), (400.0, 80.0))
    doc = lib.doc(DARK)
    lib.plate(doc, 'Quick coupler hook', [(355, -105), (440, -105), (440, 125), (355, 125)], 20, xz(184),
              radii=[0, 40, 40, 0], holes=[(p, 30.3) for p in pins])
    hook = lib.save(doc, 'Quick coupler hook 20mm')
    lib.put('Quick coupler hook L', hook, group=g)
    lib.put('Quick coupler hook R', hook, (0, -348, 0), group=g)
    # a digging bucket: two D-shaped side plates and one wrap between them,
    # rolled round a big radius from the cutting edge, over the back, to
    # the flat hitch face; a single Contour Flange, one flat blank
    W, t_side, t_wrap, bend = 800.0, 20.0, 12.0, 300.0
    # a classic digging bucket's side: a short top plate under the hitch,
    # the back bulging out past it and sweeping round into a long floor,
    # the mouth a long diagonal down to the teeth.  The wrap is rolled
    # round three big radii that meet, so the back reads as one curve.
    P = [(1225, -490), (1235, 150), (1000, 420), (640, 330), (445, 143), (445, -105)]
    doc = lib.doc(NAVY)
    lib.contour(doc, 'Bucket wrap', xz(0), P, W - 2 * t_side, t_wrap, bend, 'symmetric', flipped=True)
    lib.put('Bucket wrap', lib.save(doc, 'Bucket wrap plate 12mm rolled'), group=g)
    lip = [(445, -165), (490, -165)]
    doc = lib.doc(NAVY)
    lib.plate(doc, 'Bucket side', P + lip, t_side, xz(W / 2),
              radii=[0] + [bend + t_wrap] * 4 + [0, 0, 0])
    side = lib.save(doc, 'Bucket side plate 20mm')
    lib.put('Bucket side L', side, group=g)
    lib.put('Bucket side R', side, (0, -W + t_side, 0), group=g)
    doc = lib.doc(DARK)
    lib.extrude(doc, 'Lip bar', [(445, -165), (490, -165), (490, -105), (445, -105)],
                W - 2 * t_side, xz(0), symmetric=True, radii=[10, 10, 0, 0])
    lib.put('Bucket lip bar', lib.save(doc, 'Bucket lip bar 45x60'), group=g)
    p0, p1 = np.array(P[0], float), np.array(P[1], float)
    d = (p0 - p1) / np.linalg.norm(p0 - p1)          # out of the bucket, along its floor
    n_in = np.array([-d[1], d[0]])
    if np.dot(n_in, np.array([700.0, -100.0]) - p0) < 0:
        n_in = -n_in                                 # into the bucket
    # a heavy rim along the mouth, outside each side plate, and a bolt-on
    # side cutter at the front of it
    m0, m1 = np.array((490.0, -165.0)), p0
    md = (m1 - m0) / np.linalg.norm(m1 - m0)
    mn = np.array([-md[1], md[0]])
    if np.dot(mn, np.array([800.0, 100.0]) - m0) < 0:
        mn = -mn                                     # into the side plate
    doc = lib.doc(NAVY)
    lib.plate(doc, 'Mouth rim', [tuple(m0), tuple(m1), tuple(m1 - 160 * md + 130 * mn),
                                 tuple(m0 + 40 * md + 130 * mn)], 25, xz(W / 2 + 25), radii=[0, 0, 40, 40])
    rim = lib.save(doc, 'Bucket mouth rim 25mm')
    lib.put('Bucket mouth rim L', rim, group=g)
    lib.put('Bucket mouth rim R', rim, (0, -W - 25, 0), group=g)
    c0 = m1 - 420 * md
    doc = lib.doc(DARK)
    lib.plate(doc, 'Side cutter', [tuple(c0 + 4 * mn), tuple(m1 + 40 * md), tuple(m1 - 60 * md + 60 * mn),
                                   tuple(c0 + 60 * mn)], 20, xz(W / 2 + 45), radii=[0, 10, 20, 20])
    cutter = lib.save(doc, 'Bucket side cutter 20mm')
    lib.put('Bucket side cutter L', cutter, group=g)
    lib.put('Bucket side cutter R', cutter, (0, -W - 70, 0), group=g)
    doc = lib.doc(STEEL)
    hexagon = [(17 * math.cos(k * math.pi / 3), 17 * math.sin(k * math.pi / 3)) for k in range(6)]
    lib.extrude(doc, 'Cutter bolt head', hexagon, 12, xy(0), radii=2)
    head = lib.save(doc, 'Side cutter bolt M20')
    for k, (u, h) in enumerate(((90, 30), (200, 30), (310, 30), (150, -0))):
        q = m1 - (u + 40) * md + (h + 15) * mn
        for label, y, rot in (('L', W / 2 + 45, (-math.pi / 2, 0, 0)), ('R', -W / 2 - 45, (math.pi / 2, 0, 0))):
            lib.put('Side cutter bolt %d %s' % (k + 1, label), head, (q[0], y, q[1]), rot, g)
    # cutting edge: a bevelled blade on the end of the wrap; teeth, each an
    # adapter nose and point in one casting, on its face
    at = lambda u, h: tuple(p0 + u * d + h * n_in)
    doc = lib.doc(STEEL)
    lib.extrude(doc, 'Cutting edge', [at(0, 0), at(70, 8), at(70, 22), at(0, 40)],
                W - 2 * t_side, xz(0), symmetric=True)
    lib.put('Bucket cutting edge', lib.save(doc, 'Bucket cutting edge 40mm bevelled'), group=g)
    doc = lib.doc(DARK)
    lib.extrude(doc, 'Tooth', [at(70, -14), at(140, -20), at(330, 4), at(346, 12), at(330, 20),
                               at(140, 60), at(70, 48)], 84, xz(0), symmetric=True,
                radii=[0, 20, 6, 4, 6, 20, 0])
    tooth = lib.save(doc, 'Bucket tooth')
    for k, y in enumerate((-300, -150, 0, 150, 300)):
        lib.put('Bucket tooth %d' % (k + 1), tooth, (0, y, 0), group=g)
    # wear strips on the floor's straight run, outside
    t1 = (bend + t_wrap) * math.tan(math.radians(21.0))
    q0 = p0 - d * 40
    q1 = p1 + d * (t1 + 20)
    doc = lib.doc(DARK)
    lib.extrude(doc, 'Wear strip', [tuple(q0), tuple(q1), tuple(q1 - 14 * n_in), tuple(q0 - 14 * n_in)],
                60, xz(0), symmetric=True, radii=[0, 0, 7, 7])
    wear = lib.save(doc, 'Bucket wear strip')
    for k, y in enumerate((-250, 0, 250)):
        lib.put('Bucket wear strip %d' % (k + 1), wear, (0, y, 0), group=g)
    doc = lib.doc(NAVY)
    # the ears stand on the short top plate and carry on out over the
    # back's curve, their edge kept just clear of it
    lib.plate(doc, 'Bucket hitch bracket', [(445, -100), (445, -40), (440, 125), (360, 125),
                                            (360, -100)], 22, xz(162),
              radii=[0, 0, 0, 45, 45], holes=[(p, 30.3) for p in pins])
    bracket = lib.save(doc, 'Bucket hitch bracket 22mm')
    lib.put('Bucket hitch bracket L', bracket, group=g)
    lib.put('Bucket hitch bracket R', bracket, (0, -302, 0), group=g)
    hp = pin(lib, 'Bucket hitch pin', 30, 368)
    for k, (x, z) in enumerate(pins):
        lib.put('Bucket hitch pin %d' % (k + 1), hp, (x, 0, z), ALONG_Y, g)
