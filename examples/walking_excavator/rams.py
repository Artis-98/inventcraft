"""Hydraulic cylinders sized from the spans their eyes travel.

A cylinder's frame has Z along its axis and X along its pins.  The barrel
starts at the base eye (Z 0); the rod starts at the rod eye and points back
into the barrel.  Each eye is a flat tongue as wide as the eye, so it sits
in its clevis; the round barrel and rod begin past the clevis plates.
Closed length and stroke come from the skeleton's spans over the
controls' ranges, so a cylinder never runs out of travel and never
bottoms.
"""
import math

from .common import Library, xy, yz, DARK, STEEL, CHROME, circle


def _tongue(r, reach):
    """The eye's outline in the YZ plane: round about the pin, straight
    sides running on to ``reach``."""
    pts = [(r * math.cos(math.radians(a)), r * math.sin(math.radians(a))) for a in range(180, 361, 10)]
    return [(-r, reach)] + pts[:-1] + [(r, 0), (r, reach)]


def ram(lib, name, closed, stroke, bore, rod, eye_r, pin, eye_w, barrel=DARK, base_reach=None):
    pin_bore = pin + 0.25
    wall = max(8.0, bore * 0.16)
    reach = eye_r + 30.0                # past the clevis plates
    base = base_reach or reach          # a longer tongue where the clevis is tall
    overlap = max(40.0, bore)           # rod left in the barrel at full stroke
    floor = base + 15.0                 # barrel floor above the base eye
    rod_offset = reach + 28.0           # rod eye to the gland, closed
    length = closed - rod_offset        # base eye to the barrel mouth
    if length < stroke + overlap + floor:
        raise ValueError('%s: %.0f closed cannot hold a %.0f stroke'
                         % (name, closed, stroke))
    doc = lib.doc(barrel)
    lib.extrude(doc, name + ' base eye', _tongue(eye_r, base + 6), eye_w, yz(-eye_w / 2),
                holes=[((0, 0), pin_bore)])
    lib.lathe(doc, name + ' barrel', [
        (0, base), (bore + wall - 6, base), (bore + wall, base + 6), (bore + wall, length - 3),
        (bore + wall - 3, length), (bore, length), (bore, floor), (0, floor)])
    for z in (floor + 35, length - 75):
        lib.extrude(doc, name + ' port boss %g' % z, circle(0, z, 15, 24), 22,
                    _side_plane(bore + wall - 4), holes=[((0, z), 7)])
    b = lib.save(doc, name + ' barrel')
    doc = lib.doc(STEEL)
    lib.lathe(doc, name + ' gland', [
        (rod + 0.4, length - 50), (bore, length - 50), (bore, length),
        (bore + wall - 2, length), (bore + wall - 2, length + 22),
        (bore + wall - 6, length + 26), (rod + 0.4, length + 26)])
    g = lib.save(doc, name + ' gland')
    doc = lib.doc(CHROME, 'Steel, Mild')
    lib.extrude(doc, name + ' rod eye', _tongue(eye_r, reach + 6), eye_w, yz(-eye_w / 2),
                holes=[((0, 0), pin_bore)])
    rod_len = rod_offset + stroke + overlap
    lib.lathe(doc, name + ' rod', [(0, reach), (rod, reach), (rod, rod_len - 2), (rod - 2, rod_len),
                                   (0, rod_len)])
    r = lib.save(doc, name + ' rod')
    return dict(barrel=b, gland=g, rod=r, closed=closed, stroke=stroke,
                min_span=closed, max_span=closed + stroke, eye_w=eye_w,
                pin=pin, eye_r=eye_r, outer=bore + wall)


def _side_plane(depth):
    """A plane facing -Y inside the barrel wall, for a port boss."""
    from datum.core.sketch import SketchPlane
    return SketchPlane((0, -depth, 0), (0, -1, 0), (1, 0, 0), 'port side')
