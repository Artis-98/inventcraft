"""The upper carriage: deck, boom foot, counterweight, engine hood, and
the cab.

Upper frame: origin on the slew bearing's top, the deck's underside.  The
cab's structure is not drawn here: a skeleton part holds its lines, and
the build runs InventCraft's Frame Generator on them (frames.insert), so
the cab frame is a real frame assembly with RHS members that follow the
skeleton.  The glass, seals, roof and everything inside sit in the
openings those lines leave.
"""
import math

from . import motion as M
from .common import (Library, xy, xz, yz, ALONG_Y, ALONG_X, rotation, NAVY, GOLD, DARK,
                     STEEL, RUBBER, CHROME, GLASS, circle)
from .beam import pin
from .legs import ring, holes
from datum.core.features import CUT

DECK = 30.0
# cab: outer faces of its 80 x 80 tubes
CAB_X0, CAB_X1 = -550.0, 800.0
CAB_Y0, CAB_Y1 = 110.0, 1000.0
CAB_Z0, CAB_Z1 = 60.0, 1740.0
TUBE = 80.0
H = TUBE / 2
RAIL_Z = 520.0            # waist rail centre


def put(lib, name, part, pos=(0, 0, 0), rot=(0, 0, 0)):
    lib.put(name, part, pos, rot, 'upper')


def deck(lib):
    doc = lib.doc(DARK)
    outline = [(1100, -620), (1100, -60), (880, 100), (880, 1000), (-1150, 1000), (-1420, 730),
               (-1420, -730), (-1150, -1000), (820, -1000)]
    lib.plate(doc, 'Upper deck', outline, DECK, xy(0), radii=60, holes=[((0, 0), 120)])
    put(lib, 'Upper deck', lib.save(doc, 'Upper deck plate 30mm'))
    put(lib, 'Slew bearing inner race', ring(lib, 'Slew bearing inner race', 448, 380, -38, 0, STEEL))
    # boom foot towers either side of the boom
    fx, fy, fz = M.BOOM_FOOT
    doc = lib.doc(NAVY)
    lib.plate(doc, 'Boom foot tower', [(380, DECK), (950, DECK), (fx + 150, fz), (fx + 150, fz + 150),
                                       (fx - 150, fz + 150), (fx - 150, fz)], 30, xz(fy + 182),
              radii=[0, 0, 0, 150, 150, 0], holes=[((fx, fz), 60.3)])
    tower = lib.save(doc, 'Boom foot tower 30mm')
    put(lib, 'Boom foot tower L', tower)
    put(lib, 'Boom foot tower R', tower, (0, -334, 0))
    put(lib, 'Boom foot pin', pin(lib, 'Boom foot pin', 60, 364), (fx, fy, fz), ALONG_Y)
    bx, by, bz = M.BOOM_RAM_BASE
    doc = lib.doc(NAVY)
    lib.plate(doc, 'Boom ram base lug', [(bx - 90, DECK), (bx + 80, DECK), (bx + 60, bz), (bx + 60, bz + 60),
                                         (bx - 60, bz + 60), (bx - 60, bz)], 18, xz(by + 55),
              radii=[0, 0, 0, 60, 60, 0], holes=[((bx, bz), 30.3)])
    lug = lib.save(doc, 'Boom ram base lug 18mm')
    put(lib, 'Boom ram base lug L', lug)
    put(lib, 'Boom ram base lug R', lug, (0, -92, 0))
    put(lib, 'Boom ram base pin', pin(lib, 'Boom ram pin', 30, 110), (bx, by, bz), ALONG_Y)


def bodywork(lib):
    # counterweight casting across the tail
    # counterweight casting across the tail: a rounded side section, its
    # rear corners cut back to the deck's
    doc = lib.doc(NAVY, 'Steel, Mild')
    lib.extrude(doc, 'Counterweight section', [(-1200, DECK), (-1420, DECK), (-1440, 120), (-1440, 500),
                                               (-1370, 650), (-1200, 690)], 2000, xz(0),
                radii=[0, 20, 60, 140, 90, 0], symmetric=True)
    for sy in (1, -1):
        lib.extrude(doc, 'Counterweight corner %d' % sy, [(-1150, sy * 1000), (-1460, sy * 690),
                                                          (-1460, sy * 1010), (-1150, sy * 1010)],
                    800, xy(0), op=CUT)
    put(lib, 'Counterweight', lib.save(doc, 'Counterweight casting'))
    # engine hood: one sheet braked twice into a tunnel over the power pack
    t = 3.0
    doc = lib.doc(NAVY)
    lib.contour(doc, 'Engine hood', yz(-1200), [(-990, DECK), (-990, 760), (-130, 760), (-130, DECK)],
                1530, t, 12, 'positive', flipped=True)
    slots = [((-1130 + 70 * k, 330), (-1130 + 70 * k + 34, 620)) for k in range(17)]
    for k, ((x0, z0), (x1, z1)) in enumerate(slots):
        lib.extrude(doc, 'Hood louvre %d' % (k + 1), [(x0, z0), (x1, z0), (x1, z1), (x0, z1)], 20,
                    xz(-980), op=CUT, radii=12)
    lib.extrude(doc, 'Exhaust opening', circle(-640, -760, 46, 40), 40, xy(740), op=CUT)
    put(lib, 'Engine hood', lib.save(doc, 'Engine hood 3mm bent'))
    doc = lib.doc(NAVY)
    lib.plate(doc, 'Hood front closure', [(-987, DECK), (-133, DECK), (-133, 757), (-987, 757)], 3, yz(327),
              radii=[0, 0, 12, 12])
    put(lib, 'Hood front closure', lib.save(doc, 'Hood front closure 3mm'))
    # radiator cowl behind the cab, a single bend, and its louvred side
    doc = lib.doc(NAVY)
    lib.contour(doc, 'Radiator cowl', xz(1000), [(-560, DECK), (-560, 760), (-1200, 760)],
                1130, t, 12, 'positive', flipped=True)
    put(lib, 'Radiator cowl', lib.save(doc, 'Radiator cowl 3mm bent'))
    doc = lib.doc(DARK)
    lib.plate(doc, 'Radiator grille', [(-1197, DECK), (-563, DECK), (-563, 757), (-1197, 757)], 3, xz(1003))
    for k in range(9):
        z = 110 + 64 * k
        lib.extrude(doc, 'Grille slot %d' % (k + 1), [(-1140, z), (-620, z), (-620, z + 30), (-1140, z + 30)],
                    20, xz(1010), op=CUT, radii=14)
    put(lib, 'Radiator grille', lib.save(doc, 'Radiator grille 3mm'))
    # what shows above the hood: exhaust and the tank's filler
    doc = lib.doc(DARK)
    lib.lathe(doc, 'Exhaust stack', [(36, 660), (42, 660), (42, 1010), (36, 1010)])
    put(lib, 'Exhaust stack', lib.save(doc, 'Exhaust stack'), (-640, -760, 0))
    doc = lib.doc(DARK, 'Aluminium 6061')
    lib.box(doc, 'Power pack', (600, 700, 360), (-940, -900, 300))
    put(lib, 'Power pack', lib.save(doc, 'Engine power pack envelope'))
    doc = lib.doc(STEEL)
    lib.lathe(doc, 'Filler', [(0, 763), (45, 763), (45, 790), (40, 795), (0, 795)])
    put(lib, 'Hydraulic tank filler', lib.save(doc, 'Hydraulic tank filler cap'), (-300, -500, 0))


def cab_skeleton(lib):
    """The cab frame's layout: one sketch per side, lines on the tubes'
    centres, rails ending at the pillars' faces (butt joints)."""
    from datum.core.document import Document
    from datum.core.features import SketchFeature
    from datum.core.sketch import Sketch
    doc = lib.doc(STEEL)
    x0, x1, y0, y1 = CAB_X0 + H, CAB_X1 - H, CAB_Y0 + H, CAB_Y1 - H
    z0, z1 = CAB_Z0 + H, CAB_Z1 - H
    door = -20.0
    sketches = {}

    def sk(name, plane, lines):
        f = SketchFeature()
        f.name = name
        f.sketch = Sketch(plane, name)
        ids = [f.sketch.add_line(a, b) for a, b in lines]
        doc.add_feature(f)
        sketches[name] = (f, ids)

    for name, y, mid in (('Cab left side', y1, True), ('Cab right side', y0, False)):
        lines = [((x1, CAB_Z0), (x1, CAB_Z1)), ((x0, CAB_Z0), (x0, CAB_Z1)),
                 ((x0 + H, z1), (x1 - H, z1)), ((x0 + H, z0), (x1 - H, z0))]
        if mid:
            lines += [((door, z0 + H), (door, z1 - H)),
                      ((x0 + H, RAIL_Z), (door - H, RAIL_Z))]
        else:
            lines += [((x0 + H, RAIL_Z), (x1 - H, RAIL_Z))]
        sk(name, xz(y), lines)
    sk('Cab front', yz(x1), [((y0 + H, z1), (y1 - H, z1)), ((y0 + H, z0), (y1 - H, z0))])
    sk('Cab rear', yz(x0), [((y0 + H, z1), (y1 - H, z1)), ((y0 + H, z0), (y1 - H, z0)),
                            ((y0 + H, 900), (y1 - H, 900))])
    rz = CAB_Z1 + 4 + 56
    sk('Roof rail', xy(rz), [((-350, 200), (600, 200)), ((600, 200), (600, 910)), ((600, 910), (-350, 910))])
    for y in (200, 910):
        sk('Roof rail posts %d' % y, xz(y), [((-300, CAB_Z1 + 4), (-300, rz - 15)),
                                             ((470, CAB_Z1 + 4), (470, rz - 15))])
    part = lib.save(doc, 'Cab frame skeleton', empty=True)
    put(lib, 'Cab frame skeleton', part)
    doc.rebuild()
    return part, {k: (f.id, ids) for k, (f, ids) in sketches.items()}


def _pane(lib, name, plane, rect, inset=14, t=8.0):
    """A glazed opening: the pane and the rubber seal round it.  ``rect``
    is the opening between the tubes' faces, in the plane's coordinates."""
    from .common import _rounded
    from datum.core.features import ExtrudeFeature, collect_regions
    (u0, v0), (u1, v1) = rect
    inner = [(u0 + inset, v0 + inset), (u1 - inset, v0 + inset), (u1 - inset, v1 - inset),
             (u0 + inset, v1 - inset)]
    doc = lib.doc(GLASS, 'Glass')
    lib.extrude(doc, name, inner, t, plane, radii=10, symmetric=True)
    put(lib, name, lib.save(doc, name + ' 8mm'))
    doc = lib.doc(RUBBER, 'Rubber, EPDM')
    sk = lib.sketch(doc, name + ' seal', plane, [(u0, v0), (u1, v0), (u1, v1), (u0, v1)])
    _rounded(sk.sketch, inner, 10)
    doc.rebuild()
    regions = [r for r in collect_regions(_ctx(doc)) if r['sketch_id'] == sk.id]
    f = ExtrudeFeature()
    f.name = name + ' seal'
    f.distance = '24'
    f.extent = 'symmetric'
    f.profiles.add(sk.id, min(regions, key=lambda r: r['area'])['centre'])
    doc.add_feature(f)
    put(lib, name + ' seal', lib.save(doc, name + ' seal'))


def _ctx(doc):
    from datum.core.features import BuildContext
    ctx = BuildContext(doc.params.scope())
    ctx.sketches = dict(doc.all_sketches())
    return ctx


def cab(lib):
    x0, x1, y0, y1 = CAB_X0 + TUBE, CAB_X1 - TUBE, CAB_Y0 + TUBE, CAB_Y1 - TUBE
    z0, z1 = CAB_Z0 + TUBE, CAB_Z1 - TUBE
    door = -20.0
    yl, yr = CAB_Y1 - H, CAB_Y0 + H
    # rubber cab mounts under the four corners
    doc = lib.doc(RUBBER, 'Rubber, EPDM')
    lib.lathe(doc, 'Cab mount', [(0, DECK), (45, DECK), (45, DECK + 8), (36, DECK + 14), (36, CAB_Z0), (0, CAB_Z0)])
    mount = lib.save(doc, 'Cab rubber mount')
    for x in (CAB_X0 + H, CAB_X1 - H):
        for y in (CAB_Y0 + H, CAB_Y1 - H):
            put(lib, 'Cab mount %d %d' % (x, y), mount, (x, y, 0))
    # glazing: left rear, left door upper, right upper, windscreen, rear upper
    _pane(lib, 'Cab left rear glass', xz(yl), ((x0, RAIL_Z + H), (door - H, z1)))
    _pane(lib, 'Cab door glass', xz(yl), ((door + H, z0), (x1, z1)))
    _pane(lib, 'Cab right glass', xz(yr), ((x0, RAIL_Z + H), (x1, z1)))
    _pane(lib, 'Cab windscreen', yz(CAB_X1 - H), ((y0, z0), (y1, z1)))
    _pane(lib, 'Cab rear glass', yz(CAB_X0 + H), ((y0, 900 + H), (y1, z1)))
    # steel panels below the waist rail
    for name, plane, rect in (('Cab left rear panel', xz(yl + 2), ((x0, z0), (door - H, RAIL_Z - H))),
                              ('Cab right lower panel', xz(yr + 2), ((x0, z0), (x1, RAIL_Z - H))),
                              ('Cab rear lower panel', yz(CAB_X0 + H - 2), ((y0, z0), (y1, 900 - H)))):
        (u0, v0), (u1, v1) = rect
        doc = lib.doc(NAVY)
        lib.plate(doc, name, [(u0, v0), (u1, v0), (u1, v1), (u0, v1)], 4, plane)
        put(lib, name, lib.save(doc, name + ' 4mm'))
    # floor between the floor rails, flush with their tops
    doc = lib.doc(DARK)
    lib.plate(doc, 'Cab floor', [(x0, y0), (x1, y0), (x1, y1), (x0, y1)], 8, xy(z0 - 8))
    put(lib, 'Cab floor', lib.save(doc, 'Cab floor plate 8mm'))
    # roof: a sheet with its four edges flanged down over the roof rails
    doc = lib.doc(NAVY)
    rx0, rx1, ry0, ry1 = CAB_X0 - 12, CAB_X1 + 30, CAB_Y0 - 12, CAB_Y1 + 12
    lib.plate(doc, 'Cab roof', [(rx0, ry0), (rx1, ry0), (rx1, ry1), (rx0, ry1)], 4, xy(CAB_Z1))
    doc.rebuild()
    from .common import top_edges
    edges = top_edges(doc.shape, CAB_Z1 + 4)
    lib.flange(doc, 'Roof drip flanges', edges, 45, 4, 6, flipped=True)
    put(lib, 'Cab roof', lib.save(doc, 'Cab roof 4mm flanged'))
    # inside: seat, consoles with joysticks, pedals, dash
    sx, sy = -180.0, (y0 + y1) / 2
    doc = lib.doc(DARK, 'ABS')
    lib.extrude(doc, 'Seat base', [(sx - 220, sy - 230), (sx + 200, sy - 230), (sx + 200, sy + 230),
                                   (sx - 220, sy + 230)], 300, xy(z0), radii=20)
    put(lib, 'Seat base', lib.save(doc, 'Operator seat base'))
    doc = lib.doc(RUBBER, 'Elastomeric Foam')
    lib.extrude(doc, 'Seat cushion', [(sx - 230, sy - 250), (sx + 230, sy - 250), (sx + 230, sy + 250),
                                      (sx - 230, sy + 250)], 110, xy(z0 + 300), radii=50)
    lib.extrude(doc, 'Seat back', [(sx - 250, z0 + 410), (sx - 150, z0 + 410), (sx - 190, z0 + 1050),
                                   (sx - 290, z0 + 1050)], 470, xz(sy), radii=[0, 0, 40, 40], symmetric=True)
    put(lib, 'Seat', lib.save(doc, 'Operator seat'))
    for side in (1, -1):
        cy = sy + side * 300
        doc = lib.doc(DARK, 'ABS')
        lib.extrude(doc, 'Console', [(sx - 150, cy - 50), (sx + 280, cy - 50), (sx + 280, cy + 50),
                                     (sx - 150, cy + 50)], 560, xy(z0), radii=16)
        put(lib, 'Console %s' % ('L' if side > 0 else 'R'), lib.save(doc, 'Seat console %s' % ('L' if side > 0 else 'R')))
        doc = lib.doc(RUBBER, 'Rubber, EPDM')
        lib.lathe(doc, 'Joystick', [(0, 0), (12, 0), (12, 90), (22, 110), (24, 170), (16, 190), (0, 192)])
        put(lib, 'Joystick %s' % ('L' if side > 0 else 'R'), lib.save(doc, 'Joystick grip'), (sx + 200, cy, z0 + 560))
    doc = lib.doc(DARK, 'ABS')
    lib.extrude(doc, 'Dash', [(x1 - 160, sy - 140), (x1 - 20, sy - 140), (x1 - 20, sy + 140),
                              (x1 - 160, sy + 140)], 620, xy(z0), radii=20)
    put(lib, 'Dash column', lib.save(doc, 'Cab dash column'))
    doc = lib.doc(DARK)
    lib.extrude(doc, 'Display', [(x1 - 190, sy - 120), (x1 - 160, sy - 120), (x1 - 160, sy + 120),
                                 (x1 - 190, sy + 120)], 160, xy(z0 + 460), radii=6)
    put(lib, 'Dash display', lib.save(doc, 'Cab display'))
    for side in (1, -1):
        doc = lib.doc(DARK)
        lib.extrude(doc, 'Pedal', [(x1 - 330, -50), (x1 - 200, -50), (x1 - 200, 50), (x1 - 330, 50)],
                    14, xy(z0), radii=8)
        put(lib, 'Pedal %s' % side, lib.save(doc, 'Travel pedal'), (0, sy + side * 170, 0))
    # wiper: a through-glass spindle at the top of the windscreen, its arm
    # and blade on the outside of the glass
    gx = CAB_X1 - H + 4
    doc = lib.doc(DARK)
    lib.lathe(doc, 'Wiper spindle', [(0, 0), (14, 0), (14, 20), (8, 26), (0, 26)])
    put(lib, 'Wiper spindle', lib.save(doc, 'Wiper spindle housing'), (gx, sy, z1 - 50), ALONG_X)
    tilt = rotation((1, 0, 0), 24)
    doc = lib.doc(DARK)
    lib.extrude(doc, 'Wiper arm', [(-9, 10), (9, 10), (6, -800), (-6, -800)], 8, yz(0), radii=[4, 4, 3, 3])
    put(lib, 'Wiper arm', lib.save(doc, 'Wiper arm'), (gx + 26, sy, z1 - 50), tilt)
    doc = lib.doc(RUBBER, 'Rubber, EPDM')
    lib.extrude(doc, 'Wiper blade', [(-5, -160), (5, -160), (5, -790), (-5, -790)], 18, yz(0))
    put(lib, 'Wiper blade', lib.save(doc, 'Wiper blade'), (gx + 8, sy, z1 - 50), tilt)
    # mirror and work lamps
    doc = lib.doc(DARK)
    lib.extrude(doc, 'Mirror head', [(0, 0), (40, 0), (40, 240), (0, 240)], 180, xz(0), radii=12)
    put(lib, 'Mirror', lib.save(doc, 'Mirror head'), (CAB_X1 + 120, CAB_Y1 + 270, 1380))
    arm = lib.pipe('Mirror arm', [(CAB_X1 - H, CAB_Y1, 1500), (CAB_X1 - H, CAB_Y1 + 180, 1500),
                                  (CAB_X1 + 120, CAB_Y1 + 180, 1500)], 24, 3, 60, DARK)
    put(lib, 'Mirror arm', arm)
    for y in (CAB_Y0 + 120, CAB_Y1 - 120):
        doc = lib.doc(DARK)
        lib.extrude(doc, 'Lamp', [(0, -70), (90, -70), (90, 70), (0, 70)], 90, xy(CAB_Z1 + 4), radii=10)
        put(lib, 'Work lamp %d' % y, lib.save(doc, 'LED work lamp'), (CAB_X1 - 160, y, 0))
    # door hardware: hinges on the door pillar and a pull handle
    doc = lib.doc(STEEL)
    lib.lathe(doc, 'Hinge', [(6.3, 0), (18, 0), (18, 90), (6.3, 90)])
    hinge = lib.save(doc, 'Door hinge knuckle')
    for z in (z0 + 120, z1 - 210):
        put(lib, 'Door hinge %d' % z, hinge, (door + H + 18, CAB_Y1 + 18, z))
    return dict(seat=(sx, sy))


def frame_lines():
    """Which skeleton lines get which member: name -> (family, size)."""
    return {'square': ('en-10219-rhs', 'RHS80x80x4')}


def build(lib):
    deck(lib)
    bodywork(lib)
    skeleton, sketches = cab_skeleton(lib)
    info = cab(lib)
    return dict(skeleton=skeleton, sketches=sketches, **info)
