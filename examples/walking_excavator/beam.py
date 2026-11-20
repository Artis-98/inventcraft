"""Fabricated box beams: two laser cut webs, press braked caps between
them, and turned bosses through the webs at the pins.

A beam is drawn in its own XZ plane, pins along Y.  The caps' outer faces
are the webs' edges, so the box closes flush: each cap is a Contour Flange
on the web's edge line, bent where the line bends, its thickness turned
inward; the web's corners are rounded to the radius the cap's outer face
takes there, the bend radius inside a bend and the bend radius plus the
gauge outside one.  A cap ends tangent to the boss it runs onto.
"""
import math
import numpy as np

from .common import (Library, xz, yz, ALONG_Y, NAVY, DARK, STEEL, BRONZE)
from datum.core.features import SheetFaceFeature, ExtrudeFeature
from datum.core.sheetmetal import SheetMetalDefaults


def tangent(c, r, q, up):
    """The point where a line from ``q`` touches the circle (c, r), on the
    side ``up`` points to."""
    c = np.asarray(c, float)
    q = np.asarray(q, float)
    d = q - c
    dist = np.linalg.norm(d)
    if dist <= r:
        raise ValueError('point inside the boss')
    phi = math.atan2(d[1], d[0])
    beta = math.acos(r / dist)
    options = [c + r * np.array([math.cos(phi + s * beta), math.sin(phi + s * beta)])
               for s in (1, -1)]
    return tuple(max(options, key=lambda t: float(np.dot(t - c, up))))


def turn(a, b, c):
    return (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0])


def polyline(sketch, pts, radii):
    """An open chain of lines from pts[0] to pts[-1], its inner corners
    rounded; returns nothing, the sketch holds it."""
    pts = [np.asarray(p, float) for p in pts]
    out = [tuple(pts[0])]
    arcs = []
    for i in range(1, len(pts) - 1):
        a, b, c = pts[i - 1], pts[i], pts[i + 1]
        r = radii[i]
        u = (a - b) / np.linalg.norm(a - b)
        v = (c - b) / np.linalg.norm(c - b)
        half = math.acos(max(-1.0, min(1.0, float(np.dot(u, v))))) / 2
        t = r / math.tan(half)
        centre = b + (u + v) / np.linalg.norm(u + v) * (r / math.sin(half))
        a_in = math.atan2(*(b + u * t - centre)[::-1])
        a_out = math.atan2(*(b + v * t - centre)[::-1])
        q_in = (centre[0] + r * math.cos(a_in), centre[1] + r * math.sin(a_in))
        q_out = (centre[0] + r * math.cos(a_out), centre[1] + r * math.sin(a_out))
        start, end = (a_in, a_out) if turn(a, b, c) > 0 else (a_out, a_in)
        out += [q_in, q_out]
        arcs.append((tuple(centre), r, start, end))
    out.append(tuple(pts[-1]))
    for arc in arcs:
        sketch.add_arc(*arc)
    for k in range(0, len(out), 2):
        sketch.add_line(out[k], out[k + 1])


def clip(line, x0=None, x1=None):
    """The part of a polyline between x0 and x1."""
    pts = [tuple(p) for p in line]

    def at(x):
        for a, b in zip(pts, pts[1:]):
            if (a[0] - x) * (b[0] - x) <= 0 and a[0] != b[0]:
                t = (x - a[0]) / (b[0] - a[0])
                return (x, a[1] + t * (b[1] - a[1]))
        raise ValueError('x outside the line')
    keep = [p for p in pts if (x0 is None or p[0] > x0 + 1e-6) and (x1 is None or p[0] < x1 - 1e-6)]
    return ([at(x0)] if x0 is not None else [pts[0]]) + \
        [p for p in keep if p != pts[0] and p != pts[-1]] + \
        ([at(x1)] if x1 is not None else [pts[-1]])


def boss(lib, name, r, bore, length, color=DARK, chamfer=3):
    doc = lib.doc(color)
    h = length / 2
    lib.lathe(doc, name, [(bore, -h), (r - chamfer, -h), (r, -h + chamfer), (r, h - chamfer),
                          (r - chamfer, h), (bore, h)])
    return lib.save(doc, name)


def pin(lib, name, r, length, head=True, color=STEEL):
    """A ground pin with a retaining collar at one end and chamfers."""
    doc = lib.doc(color)
    h = length / 2
    c = min(2.0, r / 8)
    section = [(0, -h), (r - c, -h), (r, -h + c)]
    if head:
        section += [(r, h), (r + 12, h), (r + 12, h + 8), (r + 10, h + 10), (0, h + 10)]
    else:
        section += [(r, h - c), (r - c, h), (0, h)]
    lib.lathe(doc, name, section)
    return lib.save(doc, name)


class Beam:
    def __init__(self, lib, name, ends, top, bottom, width, t_web, t_cap,
                 bend, group, color=NAVY, extra_bores=()):
        self.lib, self.name, self.group = lib, name, group
        self.width, self.t_web, self.t_cap, self.bend = width, t_web, t_cap, bend
        self.color = color
        e0, e1 = ends
        up, down = np.array([0, 1.0]), np.array([0, -1.0])
        r0, r1 = e0['rb'] + t_cap, e1['rb'] + t_cap
        self.top = [tangent(e0['c'], r0, top[0], up)] + list(top) + \
            [tangent(e1['c'], r1, top[-1], up)]
        self.bottom = [tangent(e0['c'], r0, bottom[0], down)] + list(bottom) + \
            [tangent(e1['c'], r1, bottom[-1], down)]
        self.ends = ends
        self.extra = list(extra_bores)

    def radius_at(self, line, i, interior_left):
        tr = turn(line[i - 1], line[i], line[i + 1])
        convex = (tr > 0) if interior_left else (tr < 0)
        return self.bend + self.t_cap if convex else self.bend

    def web(self):
        lib = self.lib
        doc = lib.doc(self.color)
        doc.sheet_metal = SheetMetalDefaults(str(self.t_web), str(1.5 * self.t_web), '0.44')
        from datum.core.features import SketchFeature
        from datum.core.sketch import Sketch
        sk = SketchFeature()
        sk.name = self.name + ' web outline'
        sk.sketch = Sketch(xz(self.width / 2), sk.name)
        s = sk.sketch
        bottom = self.bottom
        top = list(reversed(self.top))
        polyline(s, bottom, [0] + [self.radius_at(bottom, i, True)
                                   for i in range(1, len(bottom) - 1)] + [0])
        polyline(s, top, [0] + [self.radius_at(top, i, True)
                                for i in range(1, len(top) - 1)] + [0])
        (c0, c1) = (self.ends[0]['c'], self.ends[1]['c'])
        r0, r1 = self.ends[0]['rb'] + self.t_cap, self.ends[1]['rb'] + self.t_cap
        ang = lambda c, p: math.atan2(p[1] - c[1], p[0] - c[0])
        s.add_arc(c1, r1, ang(c1, bottom[-1]), ang(c1, top[0]))
        s.add_arc(c0, r0, ang(c0, top[-1]), ang(c0, bottom[0]))
        for e in self.ends:
            s.add_circle(e['c'], e.get('hole', e['rb']))
        for c, r in self.extra:
            s.add_circle(c, r)
        doc.add_feature(sk)
        region = lib._region(doc, sk, self.name)
        f = SheetFaceFeature()
        f.name = self.name + ' web'
        f.thickness = str(self.t_web)
        f.sketch_id = sk.id
        f.profiles.add(sk.id, region['centre'])
        doc.add_feature(f)
        part = lib.save(doc, self.name + ' %gmm web' % self.t_web)
        half = self.width / 2
        lib.put(self.name + ' web L', part, (0, 0, 0), group=self.group)
        lib.put(self.name + ' web R', part, (0, -self.width + self.t_web, 0), group=self.group)
        return part

    def cap(self, which, x0=None, x1=None):
        lib = self.lib
        line = self.top if which == 'top' else self.bottom
        line = clip(line, x0, x1)
        inner = self.width - 2 * self.t_web
        doc = lib.doc(self.color)
        name = '%s %s cap' % (self.name, which)
        if len(line) == 2:
            # a straight cap is a flat plate on its edge line
            (a, b) = line
            d = np.subtract(b, a)
            d /= np.linalg.norm(d)
            n = np.array([-d[1], d[0]]) * (-1 if which == 'top' else 1) * self.t_cap
            outline = [a, b, tuple(np.add(b, n)), tuple(np.add(a, n))]
            lib.extrude(doc, name, outline, inner, xz(inner / 2), sheet=True)
        else:
            tr = turn(line[0], line[1], line[2])
            convex = tr < 0 if which == 'top' else tr > 0
            lib.contour(doc, name, xz(0), line, inner, self.t_cap, self.bend,
                        'symmetric', flipped=convex)
        part = lib.save(doc, name + ' %gmm' % self.t_cap)
        lib.put(name, part, group=self.group)
        return part, line

    def bosses(self, color=DARK):
        made = []
        for k, e in enumerate(self.ends):
            length = e.get('length', self.width)
            if e.get('fork') and not e.get('ring', 25):
                continue
            if e.get('fork'):
                # a fork end: rings outside each web, the mating part between
                ring = boss(self.lib, '%s %s boss ring' % (self.name, e['label']),
                            e['rb'], e['bore'], e.get('ring', 25), color)
                h = self.width / 2 + e.get('ring', 25) / 2
                for side, y in (('L', h), ('R', -h)):
                    self.lib.put('%s %s ring %s' % (self.name, e['label'], side), ring,
                                 (e['c'][0], y, e['c'][1]), ALONG_Y, self.group)
                made.append(ring)
            else:
                part = boss(self.lib, '%s %s boss' % (self.name, e['label']),
                            e['rb'], e['bore'], length, color)
                self.lib.put('%s %s boss' % (self.name, e['label']), part,
                             (e['c'][0], 0, e['c'][1]), ALONG_Y, self.group)
                made.append(part)
        return made

    def closure(self, x, top_line, bottom_line, which='tip'):
        """A plate across the box where its caps stop short of a fork."""
        lib = self.lib
        inner = self.width - 2 * self.t_web

        def z_at(line, xx):
            for a, b in zip(line, line[1:]):
                if (a[0] - xx) * (b[0] - xx) <= 0 and a[0] != b[0]:
                    return a[1] + (xx - a[0]) / (b[0] - a[0]) * (b[1] - a[1])
            return line[-1][1]
        t = 12
        xa = x - t if which == 'tip' else x
        zt = min(z_at(top_line, xa), z_at(top_line, xa + t)) - self.t_cap - 0.5
        zb = max(z_at(bottom_line, xa), z_at(bottom_line, xa + t)) + self.t_cap + 0.5
        doc = lib.doc(self.color)
        lib.extrude(doc, self.name + ' closure plate',
                    [(-inner / 2, zb), (inner / 2, zb), (inner / 2, zt), (-inner / 2, zt)],
                    t, yz(xa), sheet=True)
        part = lib.save(doc, '%s %s closure plate' % (self.name, which))
        lib.put('%s %s closure' % (self.name, which), part, group=self.group)
        return part
