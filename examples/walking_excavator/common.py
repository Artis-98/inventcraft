"""Native part helpers shared by the walking excavator's builders.

Every part is an ordinary InventCraft part document built from sketches and
features: laser cut plates are Face features on rounded sketches, turned
parts are revolved half sections with their chamfers drawn in, pressed
plates are Contour Flanges and Flanges that unfold.
"""
from pathlib import Path
import math
import sys
import numpy as np
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from datum.core.document import Document
from datum.core.features import (BuildContext, ExtrudeFeature, PrimitiveFeature,
                                 SketchFeature, PipeRunFeature, SheetFaceFeature,
                                 RevolveFeature, ContourFlangeFeature, FlangeFeature,
                                 PatternFeature, NEW_BODY, JOIN, CUT, collect_regions)
from datum.core.sketch import Sketch, SketchPlane, STANDARD_PLANES
from datum.core.constraints3d import Placement, rotation_vector
from datum.core.sheetmetal import SheetMetalDefaults
from datum.core import kernel

# appearances: plain colours, as a painted machine is
# machine yellow on the structure, signal orange on what moves it,
# graphite on the frames: names kept from the first palette
NAVY = '#f5b301'
GOLD = '#e8471b'
DARK = '#2b3036'
STEEL = '#b8bec4'
CHROME = '#dde2e6'
RUBBER = '#1d1f22'
BRONZE = '#a07c45'
GLASS = 'Glass, Clear'

OUT = ROOT / 'examples/walking-excavator'
PARTS = OUT / 'parts'


def xy(z=0.0): return SketchPlane((0, 0, z), (0, 0, 1), (1, 0, 0), 'XY')
def xz(y=0.0): return SketchPlane((0, y, 0), (0, -1, 0), (1, 0, 0), 'XZ')
def yz(x=0.0): return SketchPlane((x, 0, 0), (1, 0, 0), (0, 1, 0), 'YZ')


def rotation(axis, degrees):
    a = np.asarray(axis, float)
    a /= np.linalg.norm(a)
    return [float(v) for v in a * math.radians(degrees)]


# turned parts are drawn about Z; these lay that axis along X or Y
ALONG_Y = [float(v) for v in rotation((1, 0, 0), -90)]
ALONG_X = [float(v) for v in rotation((0, 1, 0), 90)]


def compose(a, b):
    xyz = a.matrix() @ np.asarray(b.position) + np.asarray(a.position)
    return Placement(list(xyz), list(rotation_vector(a.matrix() @ b.matrix())))


def circle(cx, cy, r, n=32):
    return [(cx + r * math.cos(i * math.tau / n), cy + r * math.sin(i * math.tau / n))
            for i in range(n)]


def _rounded(sketch, points, radii):
    """Lines and tangent arcs: a closed outline with its corners rounded."""
    n = len(points)
    if not isinstance(radii, (list, tuple)):
        radii = [radii] * n
    p = [np.asarray(q, float) for q in points]
    corners = []
    for i in range(n):
        a, b, c = p[i - 1], p[i], p[(i + 1) % n]
        r = float(radii[i] or 0)
        if r <= 0:
            corners.append((tuple(b), tuple(b), None))
            continue
        u = (a - b) / np.linalg.norm(a - b)
        v = (c - b) / np.linalg.norm(c - b)
        half = math.acos(max(-1.0, min(1.0, float(np.dot(u, v))))) / 2
        if half < 1e-6 or abs(half - math.pi / 2) < 1e-9:
            corners.append((tuple(b), tuple(b), None))
            continue
        t = r / math.tan(half)
        limit = 0.5 * min(np.linalg.norm(a - b), np.linalg.norm(c - b))
        if t > limit:
            t = limit
            r = t * math.tan(half)
        bis = (u + v) / np.linalg.norm(u + v)
        centre = b + bis * (r / math.sin(half))
        p_in, p_out = b + u * t, b + v * t
        a_in = math.atan2(p_in[1] - centre[1], p_in[0] - centre[0])
        a_out = math.atan2(p_out[1] - centre[1], p_out[0] - centre[0])
        turn = (b - a)[0] * (c - b)[1] - (b - a)[1] * (c - b)[0]
        start, end = (a_in, a_out) if turn > 0 else (a_out, a_in)
        # the arc's own end points, so the lines weld to them exactly
        q_in = (centre[0] + r * math.cos(a_in), centre[1] + r * math.sin(a_in))
        q_out = (centre[0] + r * math.cos(a_out), centre[1] + r * math.sin(a_out))
        corners.append((q_in, q_out, (tuple(centre), r, start, end)))
    for i in range(n):
        q_in, q_out, arc = corners[i]
        if arc:
            sketch.add_arc(arc[0], arc[1], arc[2], arc[3])
        nxt = corners[(i + 1) % n][0]
        if math.dist(q_out, nxt) > 1e-6:
            sketch.add_line(q_out, nxt)


class Library:
    def __init__(self):
        PARTS.mkdir(parents=True, exist_ok=True)
        self.parts = {}
        self.placements = []

    def doc(self, color=NAVY, material='Steel, Mild'):
        doc = Document()
        doc.material = material
        doc.appearance = color
        return doc

    def save(self, doc, name, description='', empty=False):
        doc.properties = getattr(doc, 'properties', {}) or {}
        try:
            doc.properties['Description'] = description or name
        except TypeError:
            pass
        doc.rebuild()
        if not doc.last_report.ok:
            raise RuntimeError(name + ': ' + doc.last_report.message)
        if doc.shape is None and not empty:
            raise RuntimeError(name + ': empty')
        file = doc.save(str(PARTS / name))
        self.parts[name] = {'path': str(file), 'color': doc.appearance,
                            'material': doc.material,
                            'volume': kernel.volume(doc.shape) if doc.shape is not None else 0.0}
        return str(file)

    def put(self, name, part, pos=(0, 0, 0), rot=(0, 0, 0), group='static'):
        self.placements.append(dict(name=name, part=part, pos=[float(v) for v in pos],
                                    rot=[float(v) for v in rot], group=group))

    # ------------------------------------------------------------ sketches
    def sketch(self, doc, name, plane='XY', outline=None, radii=0, holes=(),
               lines=None):
        f = SketchFeature()
        f.name = name
        f.sketch = Sketch(STANDARD_PLANES[plane] if isinstance(plane, str) else plane, name)
        if outline:
            _rounded(f.sketch, list(outline), radii)
        for centre, r in holes:
            f.sketch.add_circle(centre, r)
        for a, b in lines or ():
            f.sketch.add_line(a, b)
        doc.add_feature(f)
        return f

    def _region(self, doc, sketch, name):
        doc.rebuild()
        ctx = BuildContext(doc.params.scope())
        ctx.sketches = dict(doc.all_sketches())
        regions = [r for r in collect_regions(ctx) if r['sketch_id'] == sketch.id]
        if not regions:
            raise RuntimeError(name + ': no closed profile')
        return max(regions, key=lambda r: r['area'])

    def extrude(self, doc, name, outline, depth, plane='XY', op=JOIN, radii=0,
                holes=(), symmetric=False, sheet=False, reverse=False):
        sk = self.sketch(doc, name + ' sketch', plane, outline, radii, holes)
        region = self._region(doc, sk, name)
        if sheet:
            f = SheetFaceFeature()
            f.thickness = str(depth)
            f.sketch_id = sk.id
        else:
            f = ExtrudeFeature()
            f.distance = str(depth)
            f.operation = op
            f.extent = 'symmetric' if symmetric else 'distance'
            if reverse:
                f.reversed = True
        f.name = name
        f.profiles.add(sk.id, region['centre'])
        doc.add_feature(f)
        return f

    def plate(self, doc, name, outline, thickness, plane, radii=0, holes=()):
        """A laser cut plate: a sheet metal Face of the given gauge."""
        doc.sheet_metal = SheetMetalDefaults(str(thickness), str(1.5 * thickness), '0.44')
        return self.extrude(doc, name, outline, thickness, plane, radii=radii,
                            holes=holes, sheet=True)

    def lathe(self, doc, name, section, op=JOIN):
        """A turned part: the (radius, z) half section revolved about Z."""
        sk = self.sketch(doc, name + ' half section', xz(0), section)
        region = self._region(doc, sk, name)
        f = RevolveFeature()
        f.name = name
        f.axis = 'Y'
        f.operation = op
        f.profiles.add(sk.id, region['centre'])
        doc.add_feature(f)
        return f

    def contour(self, doc, name, plane, path, width, thickness, radius,
                direction='symmetric', flipped=False):
        """A press braked plate: an open path bent at its corners."""
        doc.sheet_metal = SheetMetalDefaults(str(thickness), str(radius), '0.44')
        sk = self.sketch(doc, name + ' path', plane,
                         lines=list(zip(path, path[1:])))
        f = ContourFlangeFeature()
        f.name = name
        f.sketch_id = sk.id
        f.width = str(width)
        f.thickness = str(thickness)
        f.bend_radius = str(radius)
        f.direction = direction
        f.flipped = bool(flipped)
        doc.add_feature(f)
        return f

    def flange(self, doc, name, edges, height, thickness, radius, flipped=False,
               angle=90):
        doc.rebuild()
        f = FlangeFeature()
        f.name = name
        f.height = str(height)
        f.thickness = str(thickness)
        f.bend_radius = str(radius)
        f.angle = str(angle)
        f.flipped = bool(flipped)
        f.edges.capture_from(doc.shape, 'edge', edges)
        doc.add_feature(f)
        return f

    def pattern(self, doc, name, features, count, axis='Z', angle=360):
        f = PatternFeature()
        f.name = name
        f.mode = 'circular'
        f.parents = [x.id for x in features]
        f.count1 = str(count)
        f.axis = axis
        f.angle = str(angle)
        doc.add_feature(f)
        return f

    def box(self, doc, name, size, origin=(0, 0, 0), op=JOIN):
        f = PrimitiveFeature()
        f.name = name
        f.kind = 'box'
        f.a, f.b, f.c = map(str, size)
        f.origin = tuple(map(str, origin))
        f.operation = op
        doc.add_feature(f)
        return f

    def pipe(self, name, points, d=20, t=2.5, radius=60, color=STEEL):
        """A rigid hydraulic tube: a Pipe Run bent through its route."""
        doc = self.doc(color)
        f = PipeRunFeature()
        f.name = name
        f.d = d
        f.t = t
        f.radius = radius
        f.points = [list(map(float, p)) for p in points]
        doc.add_feature(f)
        return self.save(doc, name)


def top_edges(shape, z, axis=2, straight=True):
    """The straight edges lying in the plane coordinate[axis] == z."""
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.GeomAbs import GeomAbs_Line
    found = []
    for e in kernel.edges(shape):
        if straight and BRepAdaptor_Curve(e).GetType() != GeomAbs_Line:
            continue
        bb = kernel.bounding_box(e)
        if abs(bb[axis] - z) < .02 and abs(bb[axis + 3] - z) < .02:
            found.append(e)
    return found
