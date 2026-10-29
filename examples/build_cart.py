"""Build a welding cart: frame, sheet metal, plasma-cut plates and parts,
put together with constraints.

This is the sample that shows the whole of InventCraft in one machine, the
kind of thing the workshop it was written in actually builds:

    the frame        Frame Generator on a skeleton of sketch lines:
                     30 x 30 x 2 square tube, the corners mitred
    the trays        sheet metal: Face and Flange, the corners relieved,
                     each one with its flat pattern
    the plates       caster plates and gussets cut on the plasma table,
                     nested on one sheet in a CAM document
    the parts        a MIG welder and a gas bottle modelled from sketches,
                     and a real caster as its maker supplies it
    the assembly     everything placed by Mate, Flush, Insert and Parallel
                     constraints, nothing grounded but the skeleton

The caster is modelled here at the size and mounting of McMaster-Carr's
2370T42 (4" swivel with brake).  The maker's own STEP file may be used but
not passed on, so it is not in the repository; with it in weld-cart/vendor/,
``--vendor`` builds the cart with the real caster instead, which is how the
website's pictures are made.  DATUM_CART_OUT builds somewhere else than
weld-cart/, so that build need not overwrite the sample.

Everything goes through the same core API the buttons call, so every file
opens, edits and rebuilds normally.

How it is laid out
------------------
Z up, X from the back of the cart (the handle, the bottle) to the front, Y
across it, the floor at Z 0.  The skeleton's lines run down the middle of
the tubes; every other number comes from the few below.
"""

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from datum.core import frames, kernel, sheetmetal
from datum.core.assembly import AssemblyConstraint, AssemblyDocument
from datum.core.cam import CamDocument
from datum.core.constraints3d import (
    FLUSH, INSERT, MATE, PARALLEL, Placement, frame_from_shape,
    rotation_vector)
from datum.core.document import Document
from datum.core.features import (
    CUT, JOIN, NEW_BODY, BuildContext, ExtrudeFeature, FlangeFeature,
    HemFeature, ImportFeature, PrimitiveFeature, RevolveFeature,
    SheetFaceFeature, SketchFeature, collect_regions)
from datum.core.sketch import STANDARD_PLANES, Sketch, SketchPlane

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.environ.get("DATUM_CART_OUT") or os.path.join(HERE, "weld-cart")
VENDOR_CASTER = os.path.join(HERE, "weld-cart", "vendor",
                             "2370T42 Cart-King Caster.step")
USE_VENDOR = "--vendor" in sys.argv
os.makedirs(OUT, exist_ok=True)

# --------------------------------------------------------------------------
# the numbers the cart comes from
# --------------------------------------------------------------------------

L = 700.0             # frame length, line to line, back to front
W = 420.0             # frame width, line to line
TUBE = "30 x 30 x 2"  # DIN EN 10219-2
B = 30.0              # its side
TOP = 800.0           # top of the top frame
CASTER_H = 127.0      # the caster's mount height, floor to plate
PLATE_T = 6.0         # the plasma-cut plates
HANDLE = 1050.0       # the handle bar's line
STRAP = 700.0         # the bottle strap's rail

Z_BOTTOM = CASTER_H + PLATE_T + B / 2     # bottom frame's lines
Z_TOP = TOP - B / 2                       # top frame's lines

BOTTLE_R = 70.0       # an 8 l cylinder
BOTTLE_H = 760.0
BOTTLE_X = -115.0     # its axis, behind the cart

RED = "Powder Coat, RAL 3020"
ZINC = "Galvanised"
STEEL = "Steel, Mild"


# --------------------------------------------------------------------------
# helpers - thin wrappers over the same API the dialogs drive
# --------------------------------------------------------------------------


def new_part(material=STEEL, appearance=""):
    doc = Document()
    doc.material = material
    doc.appearance = appearance
    return doc


def save(doc, name):
    # where it will be, first: an imported file is found from there
    doc.path = os.path.join(OUT, name + ".icpart")
    doc.rebuild()
    if not doc.last_report.ok:
        raise SystemExit("%s: %s" % (name, doc.last_report.message))
    path = doc.save(os.path.join(OUT, name))
    print("  %-26s %s" % (name, "ok"))
    return path


def xy_at(z):
    return SketchPlane((0.0, 0.0, z), (0, 0, 1), (1, 0, 0), "XY %+.0f" % z)


def xz_at(y):
    return SketchPlane((0.0, y, 0.0), (0, -1, 0), (1, 0, 0), "XZ %+.0f" % y)


def yz_at(x):
    return SketchPlane((x, 0.0, 0.0), (1, 0, 0), (0, 1, 0), "YZ %+.0f" % x)


def sketch_on(doc, name, plane="XY"):
    feature = SketchFeature()
    feature.name = name
    feature.sketch = Sketch(
        STANDARD_PLANES[plane] if isinstance(plane, str) else plane, name)
    doc.add_feature(feature)
    return feature


def loop(feature, points):
    pts = list(points)
    for i in range(len(pts)):
        feature.sketch.add_line(pts[i], pts[(i + 1) % len(pts)])
    return feature


def regions_of(doc, sketch_id):
    ctx = BuildContext(doc.params.scope())
    ctx.sketches = dict(doc.all_sketches())
    return [r for r in collect_regions(ctx) if r["sketch_id"] == sketch_id]


def extrude(doc, feature, distance, operation=NEW_BODY, extent="distance",
            keep=None, reverse=False, name=""):
    doc.rebuild()
    regions = regions_of(doc, feature.id)
    if keep is not None:
        regions = [r for r in regions if keep(r["centre"], r["area"])]
    if not regions:
        raise SystemExit("no region in %s" % feature.name)
    ex = ExtrudeFeature()
    ex.name = name or feature.name
    ex.distance = str(distance)
    ex.operation = operation
    ex.extent = extent
    ex.reversed = reverse
    for region in regions:
        ex.profiles.add(feature.id, region["centre"])
    doc.add_feature(ex)
    return ex


def revolve(doc, feature, axis="Z", operation=NEW_BODY, name=""):
    doc.rebuild()
    rev = RevolveFeature()
    rev.name = name or feature.name
    rev.angle = "360"
    rev.axis = axis
    rev.operation = operation
    for region in regions_of(doc, feature.id):
        rev.profiles.add(feature.id, region["centre"])
    doc.add_feature(rev)
    return rev


def cylinder(doc, radius, length, origin, operation=JOIN, label="Cylinder"):
    prim = PrimitiveFeature()
    prim.name = label
    prim.kind = "cylinder"
    prim.a, prim.b = str(radius), str(length)
    prim.origin = tuple(str(v) for v in origin)
    prim.operation = operation
    doc.add_feature(prim)
    return prim


def rounded_rect(feature, x0, y0, x1, y1, r):
    """A rectangle with its corners rounded, as lines and arcs."""
    s = feature.sketch
    s.add_line((x0 + r, y0), (x1 - r, y0))
    s.add_line((x1, y0 + r), (x1, y1 - r))
    s.add_line((x1 - r, y1), (x0 + r, y1))
    s.add_line((x0, y1 - r), (x0, y0 + r))
    for cx, cy, a in ((x1 - r, y0 + r, -90), (x1 - r, y1 - r, 0),
                      (x0 + r, y1 - r, 90), (x0 + r, y0 + r, 180)):
        s.add_arc((cx, cy), r, math.radians(a), math.radians(a + 90))


def edges_where(shape, test):
    """Straight edges whose two ends, taken together, pass ``test``."""
    from OCP.TopAbs import TopAbs_EDGE
    from OCP.TopoDS import TopoDS
    out = []
    for e in kernel.explore(shape, TopAbs_EDGE):
        e = TopoDS.Edge_s(e)
        if sheetmetal._is_line(e) and test(*sheetmetal._edge_ends(e)):
            out.append(e)
    return out


def near(a, b, tol=1e-6):
    return abs(a - b) < tol


# --------------------------------------------------------------------------
# sheet metal
# --------------------------------------------------------------------------


def sheet_part(name, thickness, outline, appearance=ZINC):
    """A sheet metal part: a Face from ``outline`` (a function drawing into
    a sketch on XY), ``thickness`` thick, standing on Z 0."""
    doc = new_part(STEEL, appearance)
    sheetmetal.convert(doc)
    doc.params.set_expression("Thickness", repr(thickness))
    sk = sketch_on(doc, "Outline")
    outline(sk)
    face = SheetFaceFeature()
    face.sketch_id = sk.id
    doc.add_feature(face)
    doc.rebuild()
    return doc


def flange(doc, edges, height, name="Flange", flipped=False):
    f = FlangeFeature()
    f.name = name
    f.edges.capture_from(doc.shape, "edge", edges)
    f.height = str(height)
    f.flipped = flipped
    doc.add_feature(f)
    doc.rebuild()
    if not doc.last_report.ok:
        raise SystemExit("%s: %s" % (name, doc.last_report.message))
    return f


def top_tray():
    """The welder's tray on the top frame, from the handle posts forward:
    a lip down over the frame at the front and sides, the front corners
    left open by the corner gap, and a fence up at the back, relieved
    where it meets the side lips' bends."""
    t = 2.0
    a, b = L + t, W + B + 2 * t
    doc = sheet_part("Top Tray", t,
                     lambda sk: sk.sketch.add_rectangle((0.0, 0.0), (a, b)))
    flange(doc, edges_where(doc.shape, lambda p, q: near(p[2], 0.0)
                            and near(q[2], 0.0)
                            and not (near(p[0], 0.0) and near(q[0], 0.0))),
           30, "Lips")
    flange(doc, edges_where(doc.shape, lambda p, q: near(p[2], t)
                            and near(q[2], t) and near(p[0], 0.0)
                            and near(q[0], 0.0)), 30, "Fence")
    return doc, a, b, t


def shelf():
    """The lower shelf, between the legs on the bottom side rails: lips down
    over the rails along its sides, and up at its ends to keep spools on.
    The ends are flanged after the sides, so they are relieved where they
    meet the side lips' bends."""
    t = 1.5
    a, b = L - B, W + B + 2 * t
    doc = sheet_part("Lower Shelf", t,
                     lambda sk: sk.sketch.add_rectangle((0.0, 0.0), (a, b)))
    flange(doc, edges_where(doc.shape, lambda p, q: near(p[2], 0.0)
                            and near(q[2], 0.0) and near(p[1], q[1])
                            and (near(p[1], 0.0) or near(p[1], b))), 20,
           "Side Lips")
    flange(doc, edges_where(doc.shape, lambda p, q: near(p[2], t)
                            and near(q[2], t) and near(p[0], q[0])
                            and (near(p[0], 0.0) or near(p[0], a))), 45,
           "End Lips")
    return doc, a, b, t


def bottle_tray():
    """The gas bottle's tray behind the cart: a wall up all round, the
    front one bolted to the bottom rail."""
    t = 3.0
    a, b = 200.0, 220.0
    doc = sheet_part("Bottle Tray", t,
                     lambda sk: sk.sketch.add_rectangle((0.0, 0.0), (a, b)))
    flange(doc, edges_where(doc.shape, lambda p, q: near(p[2], t)
                            and near(q[2], t)), 40, "Walls")
    # a drain hole in the middle, which also centres the bottle
    cut = sketch_on(doc, "Drain", xy_at(t))
    cut.sketch.add_circle((a / 2, b / 2), 10.0)
    extrude(doc, cut, 20, CUT, extent="through_all", name="Drain")
    return doc, a, b, t


def bottle_strap():
    """The bottle's collar: a plate round the bottle's back with a lip up,
    bolted to the strap rail, and its free edge hemmed."""
    t = 3.0
    depth, width, r = -BOTTLE_X - B / 2, 200.0, BOTTLE_R + 3.0

    def outline(sk):
        s = sk.sketch
        s.add_line((0.0, 0.0), (0.0, width))
        s.add_line((0.0, width), (depth, width))
        s.add_line((depth, width), (depth, width / 2 + r))
        s.add_arc((depth, width / 2), r, math.radians(90),
                  math.radians(270))
        s.add_line((depth, width / 2 - r), (depth, 0.0))
        s.add_line((depth, 0.0), (0.0, 0.0))
    doc = sheet_part("Bottle Collar", t, outline)
    flange(doc, edges_where(doc.shape, lambda p, q: near(p[0], 0.0)
                            and near(q[0], 0.0) and near(p[2], t)
                            and near(q[2], t)), 50, "Bolting Lip")
    return doc, depth, width, t


# --------------------------------------------------------------------------
# plasma-cut plates
# --------------------------------------------------------------------------

# the caster's own plate: four slots on 74.6 x 44.4 (McMaster 2370T42)
CASTER_HOLES = [(sx * 37.3, sy * 22.22) for sx in (-1, 1) for sy in (-1, 1)]
CASTER_PLATE = (110.0, 80.0)


def caster_plate():
    doc = new_part(STEEL, RED)
    sk = sketch_on(doc, "Plate")
    a, b = CASTER_PLATE
    rounded_rect(sk, 0.0, 0.0, a, b, 8.0)
    for x, y in CASTER_HOLES:
        sk.sketch.add_circle((a / 2 + x, b / 2 + y), 4.25)
    sk.sketch.add_circle((a / 2, b / 2), 8.0)
    extrude(doc, sk, PLATE_T, keep=lambda c, area: area > 2000,
            name="Plate")
    return doc


def gusset():
    """A gusset for the handle's corners: a triangle with its corner cut
    off, so it clears the weld."""
    doc = new_part(STEEL, RED)
    sk = sketch_on(doc, "Gusset")
    loop(sk, [(0.0, 0.0), (90.0, 0.0), (90.0, 8.0), (8.0, 90.0),
              (0.0, 90.0)])
    sk.sketch.add_circle((30.0, 30.0), 9.0)
    extrude(doc, sk, PLATE_T, keep=lambda c, area: area > 1000,
            name="Gusset")
    return doc


# --------------------------------------------------------------------------
# bought and modelled parts
# --------------------------------------------------------------------------


def welder():
    """A MIG welder, about 460 x 230 x 380: a rounded case, its front
    panel set in, two knobs, the torch socket and a carrying handle."""
    doc = new_part("ABS", "Paint, Machine Charcoal")
    side = sketch_on(doc, "Case", xz_at(0.0))
    rounded_rect(side, 0.0, 12.0, 460.0, 380.0, 22.0)
    extrude(doc, side, 230, name="Case", reverse=True)
    feet = sketch_on(doc, "Feet", xz_at(10.0))
    for x0 in (30.0, 380.0):
        loop(feet, [(x0, 0.0), (x0 + 50, 0.0), (x0 + 50, 14.0),
                    (x0, 14.0)])
    extrude(doc, feet, 210, JOIN, name="Feet", reverse=True)
    # the front panel, set in 6 mm
    panel = sketch_on(doc, "Panel", yz_at(460.0))
    rounded_rect(panel, 20.0, 40.0, 210.0, 350.0, 10.0)
    extrude(doc, panel, 6, CUT, name="Panel", reverse=True)
    for y, z in ((70.0, 270.0), (160.0, 270.0)):
        cylinder_x(doc, 22.0, 30.0, (454.0, y, z), "Knob")
    cylinder_x(doc, 16.0, 36.0, (454.0, 115.0, 110.0), "Torch Socket")
    # the handle along the top
    handle = sketch_on(doc, "Handle", xz_at(115.0))
    loop(handle, [(110.0, 378.0), (130.0, 378.0), (130.0, 420.0),
                  (330.0, 420.0), (330.0, 378.0), (350.0, 378.0),
                  (350.0, 440.0), (110.0, 440.0)])
    extrude(doc, handle, 30, JOIN, extent="symmetric", name="Handle")
    # cooling slots in the side
    vents = sketch_on(doc, "Vents", xz_at(0.0))
    for i in range(6):
        x = 90.0 + 26.0 * i
        loop(vents, [(x, 120.0), (x + 12, 120.0), (x + 12, 300.0),
                     (x, 300.0)])
    extrude(doc, vents, 3, CUT, name="Vents", reverse=True)
    return doc


def cylinder_x(doc, radius, length, origin, label):
    """A cylinder along +X from ``origin``: sketched on YZ and extruded."""
    sk = sketch_on(doc, label, yz_at(origin[0]))
    sk.sketch.add_circle((origin[1], origin[2]), radius)
    extrude(doc, sk, length, JOIN, name=label)


def gas_bottle():
    """An 8 l shielding gas cylinder, turned: the body with its domed
    shoulder, the neck, the valve and its handwheel."""
    doc = new_part(STEEL, "Powder Coat, Grey")
    sk = sketch_on(doc, "Profile", "XZ")
    r, h = BOTTLE_R, BOTTLE_H - 130.0
    s = sk.sketch
    pts = [(0.0, 0.0), (r - 8, 0.0)]
    s.add_line(pts[0], pts[1])
    s.add_arc((r - 8, 8.0), 8.0, math.radians(270), math.radians(360))
    s.add_line((r, 8.0), (r, h))
    s.add_arc((0.0, h), r, math.radians(0), math.radians(60))
    shoulder = (r * math.cos(math.radians(60)), h + r * math.sin(
        math.radians(60)))
    s.add_line(shoulder, (18.0, shoulder[1]))
    s.add_line((18.0, shoulder[1]), (18.0, h + 95.0))
    s.add_line((18.0, h + 95.0), (0.0, h + 95.0))
    s.add_line((0.0, h + 95.0), (0.0, 0.0))
    revolve(doc, sk, "Y", name="Cylinder")     # the sketch's Y is Z
    valve = sketch_on(doc, "Valve", xy_at(h + 95.0))
    loop(valve, [(-16.0, -14.0), (16.0, -14.0), (16.0, 14.0),
                 (-16.0, 14.0)])
    extrude(doc, valve, 30, JOIN, name="Valve")
    cylinder(doc, 30.0, 8.0, (0.0, 0.0, h + 125.0), JOIN, "Handwheel")
    cylinder_x(doc, 9.0, 34.0, (16.0, 0.0, h + 110.0), "Outlet")
    return doc


def modelled_caster():
    """A 4" swivel caster of 2370T42's size and mounting, for when the
    maker's model is not to hand: the same plate, holes and height, its
    plate's top on Y 0 and the wheel below it, as the STEP file has it."""
    doc = new_part(STEEL, "Galvanised")
    top = sketch_on(doc, "Plate", SketchPlane((0, -4.0, 0), (0, 1, 0),
                                              (1, 0, 0), "Plate"))
    s = top.sketch
    s.add_rectangle((-46.0, -31.75), (46.0, 31.75))
    for x, y in CASTER_HOLES:
        s.add_circle((x, y), 3.97)
    s.add_circle((0.0, 0.0), 6.35)          # where the king pin's head is
    extrude(doc, top, 4, keep=lambda c, area: area > 1000, name="Plate")
    yoke = sketch_on(doc, "Yoke", SketchPlane((0, 0, -21.0), (0, 0, 1),
                                              (1, 0, 0), "Yoke"))
    loop(yoke, [(-25.0, -14.0), (25.0, -14.0), (25.0, -4.0),
                (-25.0, -4.0)])
    extrude(doc, yoke, 42, JOIN, name="Yoke")
    for z in (-21.0, 17.0):
        leg = sketch_on(doc, "Fork Leg", SketchPlane((0, 0, z), (0, 0, 1),
                                                     (1, 0, 0), "Fork"))
        loop(leg, [(-25.0, -14.0), (25.0, -14.0), (25.0, -30.0),
                   (-20.0, -88.0), (-46.0, -88.0), (-40.0, -30.0)])
        extrude(doc, leg, 4, JOIN, name="Fork Leg")
    cylinder(doc, 6.0, 42.0, (-33.0, -76.2, -21.0), JOIN, "Axle")
    wheel = sketch_on(doc, "Wheel", SketchPlane((0, 0, -16.0), (0, 0, 1),
                                                (1, 0, 0), "Wheel"))
    wheel.sketch.add_circle((-33.0, -76.2), 50.8)
    extrude(doc, wheel, 32, JOIN, name="Wheel")
    return doc


def caster():
    if USE_VENDOR:
        if not os.path.exists(VENDOR_CASTER):
            raise SystemExit("--vendor: %s is not there" % VENDOR_CASTER)
        doc = new_part(STEEL, "Galvanised")
        imported = ImportFeature()
        imported.name = "2370T42 Cart-King Caster"
        imported.path = os.path.relpath(VENDOR_CASTER, OUT).replace(
            os.sep, "/")
        doc.add_feature(imported)
        doc.properties["Part Number"] = "McMaster-Carr 2370T42"
        doc.properties["Description"] = ("Cart-King caster, swivel with "
                                         "brake, 4 in solid rubber wheel")
        return doc, "2370T42 Caster"
    return modelled_caster(), "Caster"


# --------------------------------------------------------------------------
# the skeleton and its frame
# --------------------------------------------------------------------------


def skeleton():
    """The cart as lines: the two frames, the legs, the handle and the
    rail the bottle's collar is bolted to."""
    doc = new_part()
    bottom = sketch_on(doc, "Bottom Frame", xy_at(Z_BOTTOM))
    bottom.sketch.add_rectangle((0.0, 0.0), (L, W))
    top = sketch_on(doc, "Top Frame", xy_at(Z_TOP))
    top.sketch.add_rectangle((0.0, 0.0), (L, W))
    for name, y in (("Left Legs", 0.0), ("Right Legs", W)):
        legs = sketch_on(doc, name, xz_at(y))
        for x in (0.0, L):
            legs.sketch.add_line((x, Z_BOTTOM + B / 2), (x, Z_TOP - B / 2))
    rear = sketch_on(doc, "Handle", yz_at(0.0))
    rear.sketch.add_line((0.0, Z_TOP + B / 2), (0.0, HANDLE))
    rear.sketch.add_line((0.0, HANDLE), (W, HANDLE))
    rear.sketch.add_line((W, HANDLE), (W, Z_TOP + B / 2))
    rear.sketch.add_line((B / 2, STRAP), (W - B / 2, STRAP))
    return doc


def build_frame(asm, skeleton_occurrence, skeleton_path):
    sketches = frames.skeleton_sketches(skeleton_path)
    by_name = {name: (sid, lines) for sid, (_p, name, lines)
               in sketches.items()}
    frame_occurrence = None
    for name in ("Bottom Frame", "Top Frame", "Left Legs", "Right Legs",
                 "Handle"):
        sid, lines = by_name[name]
        frame_doc, frame_occurrence, problems = frames.insert(
            asm, skeleton_occurrence, sid, list(lines),
            "din-en-10219-2-square", TUBE, material=STEEL,
            frame_occurrence=frame_occurrence)
        if problems:
            raise SystemExit("frame: %s" % problems)
    fd = frame_doc.frame

    def member_on(sketch_name, a, b):
        """The member on the line from a to b, in that sketch."""
        sid, lines = by_name[sketch_name]
        for m in fd.members:
            if m.sketch != sid:
                continue
            p, q = frames.run_of(lines, m.lines)
            if {tuple(np.round(p, 3)), tuple(np.round(q, 3))} == {
                    tuple(np.round(a, 3)), tuple(np.round(b, 3))}:
                return m.id
        raise SystemExit("no member from %s to %s" % (a, b))

    # mitre every corner of the two frames, and the handle's two
    for name, z in (("Bottom Frame", Z_BOTTOM), ("Top Frame", Z_TOP)):
        corners = [(0.0, 0.0), (L, 0.0), (L, W), (0.0, W)]
        sides = [member_on(name, (*corners[i], z),
                           (*corners[(i + 1) % 4], z)) for i in range(4)]
        for i in range(4):
            frames.add_treatment(frame_doc, "miter",
                                 [sides[i], sides[(i + 1) % 4]],
                                 gap=0.0, split=True)
    bar = member_on("Handle", (0.0, 0.0, HANDLE), (0.0, W, HANDLE))
    for y in (0.0, W):
        post = member_on("Handle", (0.0, y, Z_TOP + B / 2),
                         (0.0, y, HANDLE))
        frames.add_treatment(frame_doc, "miter", [post, bar], gap=0.0,
                             split=True)
    # the frame red, part by part, as it would be powder coated
    for m in fd.members:
        path = os.path.join(frame_doc.base_dir, m.part)
        part = Document.load(path)
        part.appearance = RED
        part.save(path)
    return frame_doc, frame_occurrence


# --------------------------------------------------------------------------
# constraints
# --------------------------------------------------------------------------


def face(occurrence, normal, point, kind="plane", radius=None, tol=1e-3):
    """The face of a component, in its own coordinates, facing ``normal``
    through ``point`` (a plane), or round an axis through ``point`` along
    ``normal`` (a cylinder, of ``radius`` if given)."""
    best = None
    for f in kernel.faces(occurrence.shape):
        fr = frame_from_shape(f)
        if fr is None:
            continue
        d, o = np.array(fr.direction), np.array(fr.origin)
        if kind == "plane":
            if fr.kind != "plane" or np.dot(d, normal) < 1 - 1e-6 \
                    or abs(np.dot(np.array(point) - o, d)) > tol:
                continue
            score = np.linalg.norm(np.array(kernel.shape_centre(f))
                                   - np.array(point))
        else:
            if not fr.axial or abs(abs(np.dot(d, normal)) - 1) > 1e-6:
                continue
            off = np.array(point) - o
            if np.linalg.norm(off - np.dot(off, d) * d) > tol or (
                    radius is not None and abs(fr.radius - radius) > tol):
                continue
            score = abs(np.dot(off, d))
        if best is None or score < best[0]:
            best = (score, f)
    if best is None:
        raise SystemExit("%s: no face %s through %s" % (
            occurrence.label, normal, point))
    return best[1]


def world(occurrence, fr):
    m = occurrence.placement.matrix()
    return (np.array(occurrence.placement.apply_point(fr.origin)),
            m @ np.array(fr.direction))


def constrain(asm, kind, occ_a, face_a, occ_b, face_b, name=""):
    """A constraint between two faces, its offset and which way round
    taken from where the two components sit now: so it holds them exactly
    there, and the solver has nothing to do but keep them."""
    a = asm.attach(occ_a, "face", face_a)
    b = asm.attach(occ_b, "face", face_b)
    oa, da = world(occ_a, a.frame)
    ob, db = world(occ_b, b.frame)
    c = AssemblyConstraint(kind=kind, a=a, b=b)
    if kind in (MATE, FLUSH, INSERT):
        c.offset = "%.6g" % round(float(np.dot(ob - oa, da)), 6)
    if kind == INSERT:
        c.flip = float(np.dot(da, db)) > 0
    if kind == PARALLEL:
        c.flip = float(np.dot(da, db)) < 0
    if name:
        c.name = name
    asm.add_constraint(c)
    return c


def placed(asm, path, position, rotation=(0.0, 0.0, 0.0), label=""):
    occurrence = asm.place(path)
    occurrence.grounded = False
    occurrence.placement = Placement([float(v) for v in position],
                                     [float(v) for v in rotation])
    if label:
        occurrence.label = label
    # its body, to pick faces from before the assembly is next built
    occurrence.shape = asm.library.shape(asm.component_path(occurrence))
    return occurrence


def turn(axis, degrees):
    """A rotation vector: ``degrees`` about ``axis``."""
    v = np.array(axis, float)
    return list(v / np.linalg.norm(v) * math.radians(degrees))


# --------------------------------------------------------------------------
# build it
# --------------------------------------------------------------------------


def clean():
    """What an earlier run left, gone, but the maker's files and the
    README: a frame is numbered by the folders already there."""
    import shutil
    for name in os.listdir(OUT):
        if name in ("vendor", "README.md"):
            continue
        path = os.path.join(OUT, name)
        if os.path.isdir(path):
            shutil.rmtree(path)
        else:
            os.remove(path)


def main():
    clean()
    print("parts")
    skeleton_path = save(skeleton(), "Cart Skeleton")
    tray_doc, tray_a, tray_b, tray_t = top_tray()
    tray_path = save(tray_doc, "Top Tray")
    shelf_doc, shelf_a, shelf_b, shelf_t = shelf()
    shelf_path = save(shelf_doc, "Lower Shelf")
    btray_doc, btray_a, btray_b, btray_t = bottle_tray()
    btray_path = save(btray_doc, "Bottle Tray")
    strap_doc, strap_depth, strap_w, strap_t = bottle_strap()
    strap_path = save(strap_doc, "Bottle Collar")
    plate_path = save(caster_plate(), "Caster Plate")
    gusset_path = save(gusset(), "Handle Gusset")
    welder_path = save(welder(), "MIG Welder")
    bottle_path = save(gas_bottle(), "Gas Bottle")
    caster_doc, caster_name = caster()
    caster_path = save(caster_doc, caster_name)
    for path in (tray_path, shelf_path, btray_path, strap_path):
        part = Document.load(path)
        sheetmetal.flat_pattern(part)        # each one lays flat

    print("assembly")
    asm = AssemblyDocument()
    asm.path = os.path.join(OUT, "Welding Cart.icasm")
    asm.save(asm.path)
    skel = asm.place(skeleton_path)
    skel.grounded = True
    frame_doc, frame = build_frame(asm, skel, skeleton_path)
    asm.rebuild()

    # the top tray on the top frame, its fence against the handle posts
    tray = placed(asm, tray_path, (B / 2, -B / 2 - tray_t, TOP))
    constrain(asm, MATE, frame, face(frame, (0, 0, 1), (L / 2, 0, TOP)),
              tray, face(tray, (0, 0, -1), (tray_a / 2, tray_b / 2, 0)))
    constrain(asm, MATE, frame, face(frame, (1, 0, 0),
                                     (B / 2, 0, TOP + 100)),
              tray, face(tray, (-1, 0, 0), (0, tray_b / 2, 15)))
    constrain(asm, MATE, frame, face(frame, (0, -1, 0),
                                     (L / 2, -B / 2, Z_TOP)),
              tray, face(tray, (0, 1, 0), (tray_a / 2, tray_t, -10)))

    # the shelf on the bottom side rails, between the legs
    z_rails = Z_BOTTOM + B / 2
    shelf_occ = placed(asm, shelf_path, (B / 2, -B / 2 - shelf_t, z_rails))
    constrain(asm, MATE, frame, face(frame, (0, 0, 1), (L / 2, 0, z_rails)),
              shelf_occ, face(shelf_occ, (0, 0, -1),
                              (shelf_a / 2, shelf_b / 2, 0)))
    constrain(asm, MATE, frame, face(frame, (0, -1, 0),
                                     (L / 2, -B / 2, Z_BOTTOM)),
              shelf_occ, face(shelf_occ, (0, 1, 0),
                              (shelf_a / 2, shelf_t, -10)))
    constrain(asm, MATE, frame, face(frame, (1, 0, 0),
                                     (B / 2, 0, z_rails + 100)),
              shelf_occ, face(shelf_occ, (-1, 0, 0),
                              (0, shelf_b / 2, 20)))

    # the bottle's tray behind, bolted to the bottom rail
    z_under = Z_BOTTOM - B / 2
    btray = placed(asm, btray_path, (-B / 2 - btray_a, W / 2 - btray_b / 2,
                                     z_under))
    constrain(asm, MATE, frame, face(frame, (-1, 0, 0),
                                     (-B / 2, W / 2, Z_BOTTOM)),
              btray, face(btray, (1, 0, 0), (btray_a, btray_b / 2, 20)))
    constrain(asm, FLUSH, frame, face(frame, (0, 0, -1),
                                      (L / 2, 0, z_under)),
              btray, face(btray, (0, 0, -1), (btray_a / 2, btray_b / 2, 0)))
    constrain(asm, FLUSH, frame, face(frame, (0, -1, 0),
                                      (L / 2, -B / 2, Z_BOTTOM)),
              btray, face(btray, (0, -1, 0), (btray_a / 2, 0, 20)))

    # the collar, bolted to the strap rail, turned to reach back
    z_strap = STRAP - B / 2
    collar = placed(asm, strap_path, (-B / 2, W / 2 + strap_w / 2,
                                      z_strap), turn((0, 0, 1), 180))
    constrain(asm, MATE, frame, face(frame, (-1, 0, 0),
                                     (-B / 2, W / 2, STRAP)),
              collar, face(collar, (-1, 0, 0), (0, strap_w / 2, 20)))
    constrain(asm, FLUSH, frame, face(frame, (0, 0, -1),
                                      (0, W / 2, z_strap)),
              collar, face(collar, (0, 0, -1),
                           (strap_depth / 2, strap_w / 4, 0)))
    constrain(asm, FLUSH, frame, face(frame, (0, -1, 0),
                                      (L / 2, -B / 2, Z_BOTTOM)),
              collar, face(collar, (0, 1, 0),
                           (strap_depth / 2, strap_w, 1)))

    # the bottle stands in its tray on the drain hole, through the collar:
    # Insert puts it on the hole's axis, standing on the tray, and leaves
    # it free to turn, as a bottle is
    bottle = placed(asm, bottle_path, (BOTTLE_X, W / 2, z_under + btray_t))
    asm.rebuild()
    constrain(asm, INSERT, btray, face(btray, (0, 0, 1),
                                       (btray_a / 2, btray_b / 2, 0),
                                       "axis", 10.0),
              bottle, face(bottle, (0, 0, 1), (0, 0, 200), "axis",
                           BOTTLE_R))

    # caster plates under the four corners, the casters under them
    corners = [(-B / 2, -B / 2, 1, 1), (L + B / 2, -B / 2, -1, 1),
               (L + B / 2, W + B / 2, -1, -1), (-B / 2, W + B / 2, 1, -1)]
    pa, pb = CASTER_PLATE
    up = turn((1, 0, 0), 90)            # the caster file's Y up into Z
    for x, y, sx, sy in corners:
        # each plate lies with a corner on the frame's outside corner
        px = x if sx > 0 else x - pa
        py = y if sy > 0 else y - pb
        plate = placed(asm, plate_path, (px, py, CASTER_H))
        asm.rebuild()
        constrain(asm, MATE, frame, face(frame, (0, 0, -1),
                                         (x + sx * 15, y + sy * 15, z_under)),
                  plate, face(plate, (0, 0, 1), (pa / 2, pb / 2, PLATE_T)))
        constrain(asm, FLUSH, frame, face(frame, (-sx, 0, 0),
                                          (x, y + sy * 15, Z_BOTTOM)),
                  plate, face(plate, (-sx, 0, 0),
                              (0 if sx > 0 else pa, pb / 2, 3)))
        constrain(asm, FLUSH, frame, face(frame, (0, -sy, 0),
                                          (x + sx * 15, y, Z_BOTTOM)),
                  plate, face(plate, (0, -sy, 0),
                              (pa / 2, 0 if sy > 0 else pb, 3)))
        # the caster's plate up against it, its king pin in the middle
        # hole, the brake to the outside
        rotation = up if sx > 0 else list(rotation_vector(
            Placement([0, 0, 0], turn((0, 0, 1), 180)).matrix()
            @ Placement([0, 0, 0], up).matrix()))
        caster_occ = placed(asm, caster_path,
                            (px + pa / 2, py + pb / 2, CASTER_H), rotation)
        asm.rebuild()
        constrain(asm, MATE, plate, face(plate, (0, 0, -1),
                                         (pa / 2, pb / 2, 0)),
                  caster_occ, face(caster_occ, (0, 1, 0), (0, 0, 0)))
        constrain(asm, INSERT, plate, face(plate, (0, 0, 1),
                                           (pa / 2, pb / 2, 0), "axis",
                                           8.0),
                  caster_occ, face(caster_occ, (0, 1, 0), (0, -2, 0),
                                   "axis", 6.35))
        constrain(asm, PARALLEL, plate, face(plate, (1, 0, 0),
                                             (pa, pb / 2, 3)),
                  caster_occ, face(caster_occ, (1, 0, 0), (46.0, -2, 0),
                                   tol=0.1))

    # gussets in the handle's two corners, under the bar against the post
    for y, sy in ((0.0, 1), (W, -1)):
        # the gusset's legs run along its X and Y, its thickness on Z: X
        # along the bar away from the post, Y down the post
        cols = [(0, sy, 0), (0, 0, -1), np.cross((0, sy, 0), (0, 0, -1))]
        rot = list(rotation_vector(np.column_stack(cols).astype(float)))
        corner = np.array([0.0, y + sy * B / 2, HANDLE - B / 2])
        g = placed(asm, gusset_path,
                   corner - np.array(cols[2], float) * PLATE_T / 2, rot)
        asm.rebuild()
        constrain(asm, MATE, frame, face(frame, (0, 0, -1),
                                         (0, W / 2, HANDLE - B / 2)),
                  g, face(g, (0, -1, 0), (45, 0, 3)))
        constrain(asm, MATE, frame, face(frame, (0, sy, 0),
                                         (0, y + sy * B / 2, HANDLE - 100)),
                  g, face(g, (-1, 0, 0), (0, 45, 3)))
        # its back face, whichever of its two that is, flush with the
        # tubes' backs, the 6 mm set in to the middle of the 30
        back = (0, 0, 1) if np.dot(cols[2], (-1, 0, 0)) > 0 else (0, 0, -1)
        constrain(asm, FLUSH, frame, face(frame, (-1, 0, 0),
                                          (-B / 2, W / 2, HANDLE)),
                  g, face(g, back, (30, 30, PLATE_T if back[2] > 0 else 0)))

    # the welder on the tray, in the middle, its panel to the front
    weld = placed(asm, welder_path, ((L - 460.0) / 2, W / 2 - 115.0,
                                     TOP + tray_t))
    asm.rebuild()
    constrain(asm, MATE, tray, face(tray, (0, 0, 1),
                                    (tray_a / 2, tray_b / 2, tray_t)),
              weld, face(weld, (0, 0, -1), (55, 115, 0)))
    constrain(asm, FLUSH, tray, face(tray, (0, -1, 0),
                                     (tray_a / 2, 0, -10)),
              weld, face(weld, (0, -1, 0), (230, 0, 200)))
    constrain(asm, FLUSH, tray, face(tray, (-1, 0, 0),
                                     (0, tray_b / 2, 15)),
              weld, face(weld, (-1, 0, 0), (0, 115, 200)))

    report = asm.rebuild()
    print("  %d components, %d constraints: %s" % (
        len(asm.occurrences), len(asm.constraints), report.message))
    asm.save(asm.path)
    return asm, frame_doc


def nest():
    """The plasma-cut plates on one sheet of 6 mm."""
    print("CAM")
    cam = CamDocument()
    cam.path = os.path.join(OUT, "Cart Plates.iccam")
    cam.sheet_width, cam.sheet_height = "500", "220"
    cam.sheet_thickness = str(PLATE_T)
    cam.tool_diameter = "1.5"
    cam.tool_name = "Plasma, 45 A, 1.5 mm kerf"
    cam.lead_length = "4"
    cam.margin = "10"
    cam.material = STEEL
    for name, count in (("Caster Plate", 4), ("Handle Gusset", 2)):
        for _ in range(count):
            cam.add_part(os.path.join(OUT, name + ".icpart"))
    cam.rebuild()
    cam.auto_arrange()
    report = cam.rebuild()
    cam.save(cam.path)
    print("  %d plates: %s" % (len(cam.parts), getattr(report, "message",
                                                        "")))
    return cam


def tidy():
    """The OldVersions the build's own saves over its own files left."""
    import shutil
    for here, folders, _files in os.walk(OUT):
        if "OldVersions" in folders:
            shutil.rmtree(os.path.join(here, "OldVersions"))


if __name__ == "__main__":
    main()
    nest()
    tidy()
