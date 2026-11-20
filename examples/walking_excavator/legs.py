"""A walking leg: hip swivel bracket, fabricated leg, wheel carrier with
its rotary actuators, steering fork, and the wheel.

Coordinates are the skeleton's: the hip bracket in its hip frame (swivel
axis at the origin), everything else in the leg frame (lift pin at the
origin, the distal pin at X = LEG_LENGTH).  The groups name the frame each
part rides on: hip, leg, carrier, steer, wheel.
"""
import math

from . import motion as M
from .common import (Library, xy, xz, yz, ALONG_Y, ALONG_X, rotation,
                     NAVY, GOLD, DARK, STEEL, RUBBER, BRONZE, circle)
from .beam import Beam, boss, pin
from datum.core.features import ExtrudeFeature, CUT

L = M.LEG_LENGTH
P = M.HIP_REACH
WY = M.WHEEL_Y          # the wheel's middle, out to the side of the leg
SCRUB = M.SCRUB         # kingpin to the wheel's middle
R = M.TIRE_RADIUS
PI = math.pi


def ring(lib, name, r_out, r_in, z0, z1, color=STEEL, chamfer=1.5):
    doc = lib.doc(color)
    c = min(chamfer, (z1 - z0) / 4, (r_out - r_in) / 4)
    lib.lathe(doc, name, [(r_in, z0), (r_out - c, z0), (r_out, z0 + c), (r_out, z1 - c),
                          (r_out - c, z1), (r_in, z1)])
    return lib.save(doc, name)


def holes(lib, doc, name, plane, centres, r, depth, start_inside=True):
    """Cut a set of round holes through a plate in one sketch."""
    sk = lib.sketch(doc, name + ' sketch', plane, holes=[(c, r) for c in centres])
    doc.rebuild()
    from datum.core.features import BuildContext, collect_regions
    ctx = BuildContext(doc.params.scope())
    ctx.sketches = dict(doc.all_sketches())
    f = ExtrudeFeature()
    f.name = name
    f.operation = CUT
    f.distance = str(depth)
    f.extent = 'symmetric'
    for region in collect_regions(ctx):
        if region['sketch_id'] == sk.id:
            f.profiles.add(sk.id, region['centre'])
    doc.add_feature(f)
    return f


def hip_bracket(lib):
    """The swivel bracket: tube, top and bottom plates, and a tall pair of
    cheeks carrying both bones' pins."""
    put = lambda n, part, pos=(0, 0, 0), rot=(0, 0, 0): lib.put(n, part, pos, rot, 'hip')
    put('Hip swivel tube', ring(lib, 'Hip swivel tube', 100, 60.3, -125, 125, DARK, 3))
    # the bottom plate stops short: the leg's underside swings back under
    # it as the leg drops
    # the top plate sits between the cheeks, the bottom plate under them
    for label, z, end, w in (('top', 125, 215, 122), ('bottom', -150, 180, 147)):
        plate = [(-w, -w), (end, -w), (end, w), (-w, w)]
        doc = lib.doc(DARK)
        lib.plate(doc, 'Hip %s plate' % label, plate, 25, xy(z), radii=[w, 12, 12, w],
                  holes=[((0, 0), 60.3)])
        put('Hip %s plate' % label, lib.save(doc, 'Hip bracket %s plate 25mm' % label))
    ux, uz = P + M.LINK_OFFSET[0], M.LINK_OFFSET[2]
    doc = lib.doc(NAVY)
    lib.plate(doc, 'Hip cheek', [(0, -125), (300, -125), (385, -30), (ux + 115, uz), (ux + 115, uz + 115),
                                 (ux - 115, uz + 115), (150, 150), (0, 125)],
              25, xz(147), radii=[0, 30, 60, 0, 115, 115, 40, 0],
              holes=[((P, 0), 50.3), ((ux, uz), 40.3)])
    cheek = lib.save(doc, 'Hip bracket cheek 25mm')
    put('Hip cheek L', cheek)
    put('Hip cheek R', cheek, (0, -269, 0))
    put('Hip link pin', pin(lib, 'Leg link pin', 40, 294), (ux, 0, uz), ALONG_Y)
    washer = ring(lib, 'Swivel thrust washer', 100, 60.3, 0, 9.5, BRONZE)
    put('Swivel thrust washer top', washer, (0, 0, 150))
    put('Swivel thrust washer bottom', washer, (0, 0, -159.5))
    return cheek


def spread_lugs(lib):
    """The spread ram lug, a plan plate symmetric about its pin's X."""
    sx, sy = M.SPREAD_ROD[0], M.SPREAD_ROD[1]
    doc = lib.doc(DARK)
    lib.plate(doc, 'Spread lug', [(sx - 50, 147), (sx + 50, 147), (sx + 50, sy + 50), (sx - 50, sy + 50)],
              18, xy(M.SPREAD_Z + 22), radii=[0, 0, 50, 50], holes=[((sx, sy), 20.3)])
    lug = lib.save(doc, 'Hip spread ram lug 18mm')
    spin = pin(lib, 'Spread ram pin', 20, 80)
    return lug, spin


def place_spread_lugs(lib, hand, lug, spin):
    """Lugs on the bracket's +Y (hand 1) or -Y side, for the recipes."""
    sx, z2 = M.SPREAD_ROD[0], 2 * M.SPREAD_Z
    out = []
    # the lower plate is the upper one turned over about the pins' height
    if hand > 0:
        out.append(('upper', lug, (0, 0, 0), (0, 0, 0)))
        out.append(('lower', lug, (2 * sx, 0, z2), (0, PI, 0)))
    else:
        out.append(('upper', lug, (2 * sx, 0, 0), (0, 0, PI)))
        out.append(('lower', lug, (0, 0, z2), (PI, 0, 0)))
    out.append(('pin', spin, (sx, hand * M.SPREAD_ROD[1], M.SPREAD_Z), (0, 0, 0)))
    # the lift pin's head goes on the side away from the lugs
    lift = pin(lib, 'Leg lift pin', 50, 294)
    out.append(('lift pin', lift, (P, 0, 0), ALONG_Y if hand < 0 else rotation((1, 0, 0), 90)))
    return out


def leg(lib):
    """The big bone below and the small bone above it, each a box beam,
    and the lift cylinder's lugs between them."""
    beam = Beam(lib, 'Leg', [dict(label='root', c=(0, 0), rb=100, bore=50.3),
                             dict(label='tip', c=(L, 0), rb=85, bore=45.3)],
                [(420, 150), (1150, 140)], [(420, -175), (1150, -145)],
                240, 14, 14, 40, 'leg')
    beam.web()
    beam.cap('top')
    beam.cap('bottom')
    beam.bosses()
    link = Beam(lib, 'Leg link', [dict(label='root', c=(0, 0), rb=55, bore=40.3),
                                  dict(label='tip', c=(L, 0), rb=55, bore=40.3)],
                [(300, 85), (1200, 85)], [(300, -85), (1200, -85)],
                240, 10, 10, 30, 'link')
    link.web()
    link.cap('top')
    link.cap('bottom')
    link.bosses()
    from .arm import lug
    bx, bz = M.LIFT_BASE[0], M.LIFT_BASE[2]
    lug(lib, 'Leg lift ram base lug', beam.top, bx - 100, bx + 25, (bx, bz), 55, 25.3, 32, 18, 'leg')
    lib.put('Leg lift ram base pin', pin(lib, 'Lift ram pin', 25, 100), (bx, 0, bz), ALONG_Y, 'leg')
    rx, rz = M.LIFT_ROD[0], M.LIFT_ROD[2]
    lug(lib, 'Leg lift ram rod lug', link.bottom, rx - 25, rx + 120, (rx, rz), 55, 25.3, 32, 18, 'link',
        below=True, bend=30)
    lib.put('Leg lift ram rod pin', pin(lib, 'Lift ram pin', 25, 100), (rx, 0, rz), ALONG_Y, 'link')
    return beam


def _hand(h):
    """What a hand needs: a plate plane for a plate whose +Y hand spans
    y_top - t to y_top, the turned part's axis out to the wheel, a suffix."""
    plane = (lambda y_top, t: xz(y_top)) if h > 0 else (lambda y_top, t: xz(-y_top + t))
    axis = ALONG_Y if h > 0 else rotation((1, 0, 0), 90)
    return plane, axis, ('' if h > 0 else ' RH')


def carrier(lib, h=1):
    """The carrier on the leg's tips: cheeks round both bones' pins, an
    upright outboard of them and two arms reaching into the wheel's dished
    rim to the kingpin.  h is the side the wheel is on: +1 the leg's +Y,
    -1 its mirror image (right-hand parts, as a real machine has)."""
    plane, axis, rh = _hand(h)
    group = 'carrier' if h > 0 else 'carrier_rh'
    put = lambda n, part, pos=(0, 0, 0), rot=(0, 0, 0): lib.put(
        n, part, (pos[0], h * pos[1], pos[2]), rot, group)
    ky = WY - SCRUB
    ux, uz = L + M.LINK_OFFSET[0], M.LINK_OFFSET[2]
    doc = lib.doc(DARK)
    lib.plate(doc, 'Carrier cheek', [(L - 115, -115), (L + 115, -115), (ux + 115, uz), (ux + 115, uz + 100),
                                     (ux - 100, uz + 100), (L - 115, 115)],
              25, xz(147), radii=[115, 115, 0, 100, 100, 0], holes=[((L, 0), 45.3), ((ux, uz), 40.3)])
    cheek = lib.save(doc, 'Carrier cheek 25mm')
    lib.put('Carrier cheek L', cheek, group=group)
    lib.put('Carrier cheek R', cheek, (0, -269, 0), group=group)
    put('Carrier link pin', pin(lib, 'Leg link pin', 40, 294), (ux, 0, uz), axis)
    doc = lib.doc(DARK)
    lib.plate(doc, 'Carrier upright', [(L - 115, -240), (L + 115, -240), (L + 200, 160), (L + 200, 300),
                                       (L - 115, 300)],
              30, plane(177, 30), radii=[60, 60, 40, 40, 60], holes=[((L, 0), 45.3)])
    put('Carrier upright', lib.save(doc, 'Carrier upright 30mm' + rh))
    doc = lib.doc(NAVY)
    lib.plate(doc, 'Kingpin arm', [(L - 50, h * 177), (L + 50, h * 177), (L + 50, h * (ky + 50)),
                                   (L - 50, h * (ky + 50))], 40, xy(160),
              radii=[0, 0, 50, 50], holes=[((L, h * ky), 25.3)])
    arm = lib.save(doc, 'Carrier kingpin arm 40mm' + rh)
    lib.put('Kingpin arm upper', arm, group=group)
    lib.put('Kingpin arm lower', arm, (0, 0, -360), group=group)
    # the steering cylinder's base lugs, on the upright
    sx, sy, sz = M.STEER_BASE
    doc = lib.doc(DARK)
    lib.plate(doc, 'Steering ram lug', [(sx - 35, h * 177), (sx + 35, h * 177), (sx + 35, h * (sy + 35)),
                                        (sx - 35, h * (sy + 35))], 12,
              xy(sz + 17), radii=[0, 0, 35, 35], holes=[((sx, h * sy), 12.3)])
    slug = lib.save(doc, 'Carrier steering ram lug 12mm' + rh)
    lib.put('Steering ram lug upper', slug, group=group)
    lib.put('Steering ram lug lower', slug, (0, 0, -46), group=group)
    put('Steering ram base pin', pin(lib, 'Steering ram pin', 12, 58), (sx, sy, sz))
    put('Carrier distal pin', pin(lib, 'Leg distal pin', 45, 324), (L, 15, 0), axis)


def knuckle(lib, h=1):
    """Steering knuckle on the kingpin, inside the rim, with the spindle and
    the hub motor's housing: the wheel hangs off one side.  The kingpin
    turns with it and carries the steering arm on its top end."""
    plane, axis, rh = _hand(h)
    group = 'steer' if h > 0 else 'steer_rh'
    put = lambda n, part, pos=(0, 0, 0), rot=(0, 0, 0): lib.put(
        n, part, (pos[0], h * pos[1], pos[2]), rot, group)
    ky = WY - SCRUB
    doc = lib.doc(DARK)
    lib.lathe(doc, 'Kingpin boss', [(25.3, -158), (45, -158), (45, 158), (25.3, 158)])
    lib.extrude(doc, 'Knuckle flange', circle(0, 0, 150, 64), 30, plane(WY - 40 - ky, 30),
                holes=[((0, 0), 60.3)])
    put('Steering knuckle', lib.save(doc, 'Steering knuckle' + rh), (L, ky, 0))
    doc = lib.doc(STEEL)
    lib.lathe(doc, 'Kingpin', [(0, -200), (25, -200), (25, 272), (23, 274), (0, 274)])
    put('Kingpin', lib.save(doc, 'Steering kingpin'), (L, ky, 0))
    ax, az = M.STEER_ARM, M.STEER_BASE[2]
    doc = lib.doc(GOLD)
    lib.plate(doc, 'Steering arm', [(-45, -45), (ax + 30, -30), (ax + 30, 30), (-45, 45)], 12, xy(az + 17),
              radii=[45, 30, 30, 45], holes=[((0, 0), 25), ((ax, 0), 12.3)])
    arm = lib.save(doc, 'Steering arm 12mm')
    put('Steering arm upper', arm, (L, ky, 0))
    put('Steering arm lower', arm, (L, ky, -46))
    put('Steering ram rod pin', pin(lib, 'Steering ram pin', 12, 58), (L + ax, ky, az))
    doc = lib.doc(DARK)
    lib.lathe(doc, 'Hub motor housing', [(60.3, -40), (130, -40), (140, -30), (140, 40), (130, 48),
                                         (60.3, 48)])
    put('Hydraulic hub motor', lib.save(doc, 'Hydraulic hub motor housing'), (L, WY, 0), axis)
    doc = lib.doc(STEEL)
    lib.lathe(doc, 'Spindle', [(0, -55), (60, -55), (60, 316), (58, 318), (0, 318)])
    put('Wheel spindle', lib.save(doc, 'Wheel spindle'), (L, WY, 0), axis)
    doc = lib.doc(STEEL)
    lib.lathe(doc, 'Spindle nut', [(60, 288), (85, 288), (88, 291), (88, 311), (85, 314), (60, 314)])
    put('Spindle nut', lib.save(doc, 'Wheel spindle nut'), (L, WY, 0), axis)


def wheel(lib, h=1):
    """A wide balloon tyre on a deep dished rim, the knuckle inside the dish.
    Part coordinates: the axle on Z, the wheel's middle at Z 0.  Drawn at
    the 1080 size and scaled by K, bores and fasteners kept to size."""
    plane, axis, rh = _hand(h)
    group = 'wheel' if h > 0 else 'wheel_rh'
    put = lambda n, part: lib.put(n, part, (L, h * WY, 0), axis, group)
    K = R / 540.0
    sc = lambda pts: [(r * K, z * K) for r, z in pts]
    D = 130.0 * K                   # the centre disc, out towards the face
    doc = lib.doc(STEEL)
    lib.lathe(doc, 'Rim rolled section', sc([
        (318, -215), (318, -205), (300, -195), (300, -160), (272, -120), (272, 120), (300, 160),
        (300, 195), (318, 205), (318, 215), (308, 215), (290, 197), (290, 165), (262, 125),
        (262, -125), (290, -165), (290, -197), (308, -215)]))
    lib.lathe(doc, 'Rim centre disc', [(146, D - 12), (264 * K, D - 12), (264 * K, D + 12), (146, D + 12)])
    bc = 182.0
    holes(lib, doc, 'Rim vent holes', xy(D), [(268 * math.cos(k * PI / 4), 268 * math.sin(k * PI / 4))
                                              for k in range(8)], 44, 50)
    studs = [(bc * math.cos(k * PI / 6 + PI / 12), bc * math.sin(k * PI / 6 + PI / 12)) for k in range(12)]
    holes(lib, doc, 'Rim stud holes', xy(D), studs, 11, 50)
    put('Wheel rim', lib.save(doc, 'Wheel rim 30in dished'))
    doc = lib.doc(DARK)
    lib.lathe(doc, 'Hub', [(60.3, 50), (100, 50), (108, 58), (108, D - 42), (215, D - 42), (215, D - 12),
                           (108, D - 12), (108, 277), (100, 285), (60.3, 285)])
    holes(lib, doc, 'Hub stud holes', xy(D - 27), studs, 10, 30)
    put('Wheel hub', lib.save(doc, 'Wheel hub'))
    doc = lib.doc(STEEL)
    lib.lathe(doc, 'Wheel stud', [(0, D - 42), (10, D - 42), (10, D + 40), (0, D + 40)])
    stud = lib.save(doc, 'Wheel stud M20')
    doc = lib.doc(STEEL)
    hexagon = [(17 * math.cos(k * PI / 3), 17 * math.sin(k * PI / 3)) for k in range(6)]
    lib.extrude(doc, 'Wheel nut', hexagon, 18, xy(D + 12), holes=[((0, 0), 10)])
    nut = lib.save(doc, 'Wheel nut M20')
    from .common import compose
    from datum.core.constraints3d import Placement
    base = Placement([L, h * WY, 0], list(axis))
    for k, (x, y) in enumerate(studs):
        a = k * PI / 6 + PI / 12
        at = compose(base, Placement([x, y, 0], [0, 0, 0]))
        lib.put('Wheel stud %d' % (k + 1), stud, at.position, at.rotation, group)
        at = compose(base, Placement([x, y, 0], [0, 0, a]))
        lib.put('Wheel nut %d' % (k + 1), nut, at.position, at.rotation, group)
    # balloon carcass: low pressure, a tall round sidewall either side
    doc = lib.doc(RUBBER, 'Rubber, EPDM')
    outer = [(301, -150), (301, -193), (322, -199), (348, -216), (385, -236), (430, -244), (468, -236),
             (493, -214), (505, -175), (511, -110), (513, 0), (511, 110), (505, 175), (493, 214),
             (468, 236), (430, 244), (385, 236), (348, 216), (322, 199), (301, 193), (301, 150)]
    inner = [(335, 168), (378, 200), (428, 214), (462, 206), (480, 176), (488, 110), (490, 0),
             (488, -110), (480, -176), (462, -206), (428, -214), (378, -200), (335, -168)]
    lib.lathe(doc, 'Tyre carcass', sc(outer + inner))
    # few, big, round lugs: a fat chevron bar each side, staggered
    from datum.core.sketch import SketchPlane
    top = SketchPlane((R, 0, 0), (-1, 0, 0), (0, 1, 0), 'Tread tangent plane')
    n = 16
    pitch = 2 * PI * R / n
    lugs = []
    for k, (sign, off) in enumerate(((1, 0.0), (-1, pitch / 2))):
        pts = [((-95 + o) * K + off, z * K * sign) for o, z in ((0, 18), (90, 18), (170, 226), (80, 226))]
        lugs.append(lib.extrude(doc, 'Lug %d' % (k + 1), pts, 92 * K, top,
                                radii=[38 * K, 38 * K, 42 * K, 42 * K]))
    lib.pattern(doc, 'Lugs round the tyre', lugs, n, 'Z')
    put('Tyre', lib.save(doc, 'Tyre 1400x650 balloon'))


def build(lib):
    hip_bracket(lib)
    lug, spin = spread_lugs(lib)
    leg(lib)
    for h in (1, -1):
        carrier(lib, h)
        knuckle(lib, h)
        wheel(lib, h)
    return dict(spread_lug=lug, spread_pin=spin)
