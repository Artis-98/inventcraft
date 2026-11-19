# The rest of InventCraft's 3D icons, run inside render3d.py (exec'd into
# its globals, so the helpers there are to hand: box_object, prism, arrow,
# boolean, cutter, bevel_mod, mesh_object, bm_box, MATS).
#
# The house style: a grey part, the accent on what the command makes or
# touches, dark for arrows and axes, a see-through plane where a plane
# is the point.  Bold: a fillet is a big round, a hole a big hole.
#
# MORE maps each icon's name to the function that builds it.

MORE = {}


def model(name):
    def wrap(fn):
        MORE[name] = fn
        return fn
    return wrap


# ------------------------------------------------------------- helpers

def cyl(name, r, h, at=(0, 0, 0), mat="grey", segments=48, axis="Z",
        caps=True, smooth=True):
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=caps, segments=segments, radius1=r,
                          radius2=r, depth=h)
    bmesh.ops.translate(bm, vec=(0, 0, h / 2.0), verts=bm.verts)
    if axis == "X":
        bmesh.ops.rotate(bm, verts=bm.verts, cent=(0, 0, 0),
                         matrix=Matrix.Rotation(math.radians(90), 3, "Y"))
    elif axis == "Y":
        bmesh.ops.rotate(bm, verts=bm.verts, cent=(0, 0, 0),
                         matrix=Matrix.Rotation(math.radians(-90), 3, "X"))
    bmesh.ops.translate(bm, vec=at, verts=bm.verts)
    ob = mesh_object(name, bm, [mat])
    if smooth:
        for p in ob.data.polygons:
            p.use_smooth = abs(p.normal.dot(Vector(
                {"Z": (0, 0, 1), "X": (1, 0, 0), "Y": (0, 1, 0)}[axis]))) < 0.9
    return ob


def ball(name, r, at=(0, 0, 0), mat="grey"):
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=48, v_segments=24, radius=r)
    bmesh.ops.translate(bm, vec=at, verts=bm.verts)
    ob = mesh_object(name, bm, [mat])
    for p in ob.data.polygons:
        p.use_smooth = True
    return ob


def faces_by_normal(bm, pick, index):
    """Faces whose normal ``pick`` likes take material ``index``."""
    for f in bm.faces:
        if pick(f.normal):
            f.material_index = index


def coloured_box(name, sx, sy, sz, at=(0, 0, 0), pick=None, bevel=0.03):
    bm = bm_box(sx, sy, sz, at)
    if pick is not None:
        faces_by_normal(bm, pick, 1)
    ob = mesh_object(name, bm, ["grey", "accent"])
    if bevel:
        bevel_mod(ob, bevel)
    return ob


def place(ob, at=(0, 0, 0), rot=(0, 0, 0)):
    ob.location = at
    ob.rotation_euler = tuple(math.radians(a) for a in rot)
    return ob


def curved_arrow(centre, radius, start_deg, end_deg, z=0.0, thick=0.06,
                 head=0.18, mat="dark", plane="XY", point=None):
    """An arc of arrow round ``centre``, its head at the end."""
    n = 32

    def p3(deg):
        a = math.radians(deg)
        x, y = math.cos(a) * radius, math.sin(a) * radius
        if plane == "XY":
            return Vector((centre[0] + x, centre[1] + y, centre[2] + z))
        return Vector((centre[0] + x, centre[1] + z, centre[2] + y))
    # the shaft stops short of the end, where the head takes over
    gap = 12.0
    if point is not None:
        # a longer head takes more of the arc: as much as it is long
        tip = max(head * 1.5, 0.24) * point
        gap = math.degrees(tip / radius) * 0.85
    stop = end_deg - math.copysign(gap, end_deg - start_deg)
    cu = bpy.data.curves.new("Arc", "CURVE")
    cu.dimensions = "3D"
    cu.bevel_depth = thick
    cu.bevel_resolution = 3
    sp = cu.splines.new("POLY")
    sp.points.add(n)
    for i, spt in enumerate(sp.points):
        spt.co = tuple(p3(start_deg + (stop - start_deg) * i / n)) + (1.0,)
    ob = bpy.data.objects.new("Arc", cu)
    bpy.context.scene.collection.objects.link(ob)
    ob.data.materials.append(MATS[mat])
    arrow(p3(stop - math.copysign(2.0, end_deg - start_deg)), p3(end_deg),
          radius=thick, head=head, mat=mat,
          **({} if point is None else {"point": point}))
    return ob


def square_tube(name, length, s=0.6, t=0.1, mat="grey", end_mat="accent",
                axis="X"):
    """A square hollow section ``length`` long from the origin, its cut
    ends in ``end_mat``."""
    bm = bm_box(length, s, s, (length / 2.0, 0, -s / 2.0))
    faces_by_normal(bm, lambda n: abs(n.x) > 0.99, 1)
    ob = mesh_object(name, bm, [mat, end_mat])
    tool = cutter(name + " bore", bm_box(length + 0.4, s - 2 * t, s - 2 * t,
                                         (length / 2.0, 0, -(s - 2 * t) / 2)),
                  mat)
    boolean(ob, tool)
    bevel_mod(ob, 0.02)
    if axis == "Y":
        ob.rotation_euler = (0, 0, math.radians(90))
    elif axis == "Z":
        ob.rotation_euler = (0, math.radians(-90), 0)
    tool.parent = ob
    return ob


def rounded_path(points, radius, steps=10):
    """A polyline's corners rounded to ``radius``, as many points."""
    out = [points[0]]
    for i in range(1, len(points) - 1):
        p0, p1, p2 = (Vector(points[i - 1]), Vector(points[i]),
                      Vector(points[i + 1]))
        u, v = (p1 - p0).normalized(), (p2 - p1).normalized()
        turn = math.acos(max(-1.0, min(1.0, u.dot(v))))
        if turn < 1e-3:
            out.append(tuple(p1))
            continue
        back = radius * math.tan(turn / 2.0)
        a, b = p1 - u * back, p1 + v * back
        normal = Vector((-u.y, u.x)) if u.x * v.y - u.y * v.x > 0 \
            else Vector((u.y, -u.x))
        c = a + normal * radius
        a0 = math.atan2(a.y - c.y, a.x - c.x)
        a1 = math.atan2(b.y - c.y, b.x - c.x)
        da = (a1 - a0 + math.pi) % (2 * math.pi) - math.pi
        for k in range(steps + 1):
            ang = a0 + da * k / steps
            out.append((c.x + radius * math.cos(ang),
                        c.y + radius * math.sin(ang)))
    out.append(points[-1])
    return out


def sheet(name, path2d, width=1.6, thick=0.12, mat="grey", at=(0, 0, 0),
          rot=(90, 0, 0)):
    """A sheet metal strip: ``path2d`` (x across, y up, in the bend's
    plane) given a thickness and pulled ``width`` deep."""
    cu = bpy.data.curves.new(name, "CURVE")
    cu.dimensions = "2D"
    cu.fill_mode = "BOTH"
    cu.extrude = width / 2.0
    cu.bevel_depth = thick / 2.0
    cu.bevel_resolution = 1
    sp = cu.splines.new("POLY")
    sp.points.add(len(path2d) - 1)
    for spt, (x, y) in zip(sp.points, path2d):
        spt.co = (x, y, 0.0, 1.0)
    ob = bpy.data.objects.new(name, cu)
    bpy.context.scene.collection.objects.link(ob)
    ob.data.materials.append(MATS[mat])
    return place(ob, at, rot)


def plane_sheet(name, sx, sy, at=(0, 0, 0), rot=(0, 0, 0), mat="plane"):
    bm = bmesh.new()
    bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=0.5)
    bmesh.ops.scale(bm, vec=(sx, sy, 1), verts=bm.verts)
    ob = mesh_object(name, bm, [mat])
    return place(ob, at, rot)


def edges_of_box(sx, sy, sz, at=(0, 0, 0), r=0.035, mat="dark"):
    """Thin rods down a box's twelve edges: shaded with edges."""
    x0, y0, z0 = at[0] - sx / 2, at[1] - sy / 2, at[2]
    corners = [(x0 + i * sx, y0 + j * sy, z0 + k * sz)
               for i in (0, 1) for j in (0, 1) for k in (0, 1)]
    for a in corners:
        for b in corners:
            d = [abs(a[i] - b[i]) for i in range(3)]
            if a < b and sum(1 for v in d if v > 1e-6) == 1:
                axis = "XYZ"[[i for i in range(3) if d[i] > 1e-6][0]]
                cyl("Edge", r, max(d), at=a, mat=mat, segments=12, axis=axis)


# ---------------------------------------------------------- primitives

@model("cylinder")
def _cylinder():
    ob = cyl("Cylinder", 0.85, 1.6)
    ob.data.materials.append(MATS["accent"])
    for p in ob.data.polygons:
        if p.normal.z > 0.9:
            p.material_index = 1
    bevel_mod(ob, 0.03)


@model("sphere")
def _sphere():
    ball("Sphere", 1.0, (0, 0, 1.0))
    cyl("Band", 1.004, 0.16, at=(0, 0, 0.92), mat="accent", segments=64,
        caps=False)


@model("feature")
def _feature():
    coloured_box("Part", 1.7, 1.7, 1.3, pick=lambda n: n.z > 0.99)


@model("hole")
def _hole():
    ob = box_object("Block", 1.9, 1.9, 1.0, bevel=0)
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, segments=64, radius1=0.55,
                          radius2=0.55, depth=2.4)
    tool = cutter("Drill", bm, "accent")
    boolean(ob, tool)
    bevel_mod(ob, 0.03)
    for p in ob.data.polygons:
        p.use_smooth = False


# ------------------------------------------------------------ features

@model("revolve")
def _revolve():
    # a stepped profile spun three quarters round its axis
    prof = [(0.35, 0.0), (1.05, 0.0), (1.05, 0.45), (0.7, 0.45),
            (0.7, 1.25), (0.35, 1.25)]
    bm = bmesh.new()
    vs = [bm.verts.new((x, 0.0, z)) for x, z in prof]
    face = bm.faces.new(vs)
    face.material_index = 1
    res = bmesh.ops.spin(bm, geom=[face] + vs + list(face.edges),
                         cent=(0, 0, 0), axis=(0, 0, 1),
                         angle=math.radians(270), steps=48,
                         use_duplicate=False)
    for f in res["geom_last"]:
        if isinstance(f, bmesh.types.BMFace):
            f.material_index = 1
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    ob = mesh_object("Revolved", bm, ["grey", "accent"])
    for p in ob.data.polygons:
        p.use_smooth = p.material_index == 0 and abs(p.normal.z) < 0.9
    ob.rotation_euler = (0, 0, math.radians(-45))
    cyl("Axis", 0.05, 2.4, at=(0, 0, -0.5), mat="dark", segments=16)


@model("sweep")
def _sweep():
    cu = bpy.data.curves.new("Path", "CURVE")
    cu.dimensions = "3D"
    # a fat tube along an S through space, the profile it carries at the
    # start in the accent
    cu.bevel_depth = 0.3
    cu.bevel_resolution = 8
    cu.use_fill_caps = True
    sp = cu.splines.new("POLY")
    pts = []
    for k in range(41):
        t = k / 40.0
        pts.append((-1.2 + 2.4 * t, 0.7 * math.sin(math.pi * 2 * t) * 0.8,
                    0.3 + 1.2 * t))
    sp.points.add(len(pts) - 1)
    for spt, co in zip(sp.points, pts):
        spt.co = co + (1.0,)
    ob = bpy.data.objects.new("Swept", cu)
    bpy.context.scene.collection.objects.link(ob)
    ob.data.materials.append(MATS["grey"])
    for poly in ob.data.splines:
        poly.use_smooth = True
    d = Vector(pts[1]) - Vector(pts[0])
    ring = cyl("Profile", 0.42, 0.1, mat="accent", axis="Z")
    ring.matrix_world = Matrix.Translation(Vector(pts[0]) - d.normalized()
                                           * 0.05) @ \
        d.to_track_quat("Z", "Y").to_matrix().to_4x4()


@model("loft")
def _loft():
    n = 48
    bm = bmesh.new()

    def square(t, s, z):
        # a point on a square's outline at fraction t of the way round
        t = (t + 0.125) % 1.0
        side, f = int(t * 4), (t * 4) % 1.0
        x0, y0 = [(-s, -s), (s, -s), (s, s), (-s, s)][side]
        x1, y1 = [(s, -s), (s, s), (-s, s), (-s, -s)][side]
        return (x0 + (x1 - x0) * f, y0 + (y1 - y0) * f, z)
    low = [bm.verts.new(square(i / n, 0.9, 0.0)) for i in range(n)]
    high = [bm.verts.new((0.55 * math.cos(2 * math.pi * i / n + math.pi / 4
                                          - math.pi * 0.75 + math.pi / 4),
                          0.55 * math.sin(2 * math.pi * i / n + math.pi / 4
                                          - math.pi * 0.75 + math.pi / 4),
                          1.6)) for i in range(n)]
    for i in range(n):
        j = (i + 1) % n
        bm.faces.new((low[i], low[j], high[j], high[i]))
    bottom = bm.faces.new(list(reversed(low)))
    top = bm.faces.new(high)
    top.material_index = bottom.material_index = 1
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    ob = mesh_object("Loft", bm, ["grey", "accent"])
    for p in ob.data.polygons:
        p.use_smooth = p.material_index == 0


@model("combine")
def _combine():
    ob = box_object("Block", 1.7, 1.2, 0.9, (0, 0.2, 0), bevel=0)
    tool = cyl("Boss", 0.55, 1.7, at=(0.15, -0.35, 0.0), mat="accent")
    boolean(ob, tool, "UNION")
    tool.hide_render = True
    bevel_mod(ob, 0.03)
    for p in ob.data.polygons:
        p.use_smooth = False


def ring(name, r, z, at=(0, 0), thick=0.03, mat="dark"):
    """A thin round wire: a cylinder's edge drawn as a line."""
    cu = bpy.data.curves.new(name, "CURVE")
    cu.dimensions = "3D"
    cu.bevel_depth = thick
    cu.bevel_resolution = 3
    sp = cu.splines.new("POLY")
    n = 64
    sp.points.add(n)
    for i in range(n + 1):
        t = 2 * math.pi * i / n
        sp.points[i].co = (at[0] + r * math.cos(t), at[1] + r * math.sin(t),
                           z, 1.0)
    ob = bpy.data.objects.new(name, cu)
    bpy.context.scene.collection.objects.link(ob)
    cu.materials.append(MATS[mat])
    return ob


@model("intersect")
def _intersect():
    # the block and the boss of Combine drawn only as their edges, and
    # what they share solid in the accent: only the overlap is kept
    bx, by, bz, bat = 1.7, 1.2, 0.9, (0, 0.2, 0)
    r, h, cat = 0.55, 1.7, (0.15, -0.35, 0.0)
    ob = box_object("Kept", bx, by, bz, bat, mat="accent", bevel=0)
    tool = cyl("Tool", r, h, at=cat, mat="accent")
    boolean(ob, tool, "INTERSECT")
    tool.hide_render = True
    bevel_mod(ob, 0.03)
    for p in ob.data.polygons:
        p.use_smooth = False
    edges_of_box(bx, by, bz, bat, r=0.022, mat="grey")
    ring("Top", r, h, cat[:2], thick=0.022, mat="grey")
    ring("Bottom", r, 0.0, cat[:2], thick=0.022, mat="grey")
    # the two lines down its sides as seen from the icon view (45 degrees)
    k = r * math.sqrt(0.5)
    for sx, sy in ((-k, k), (k, -k)):
        cyl("Side", 0.022, h, at=(cat[0] + sx, cat[1] + sy, 0.0),
            mat="grey", segments=12)


@model("split")
def _split():
    coloured_box("Half A", 1.7, 0.8, 1.2, (0, 0.45, 0),
                 pick=lambda n: n.y < -0.99)
    coloured_box("Half B", 1.7, 0.8, 1.2, (0, -0.45, 0),
                 pick=lambda n: n.y > 0.99)
    plane_sheet("Split", 2.6, 1.9, at=(0, 0, 0.6), rot=(90, 0, 0))


@model("split_faces")
def _split_faces():
    box_object("Block", 1.7, 1.7, 1.4)
    box_object("Line", 1.74, 0.07, 1.44, (0, 0.1, -0.02), mat="accent",
               bevel=0)
    plane_sheet("Split", 2.5, 2.0, at=(0, 0.1, 0.7), rot=(90, 0, 0))


@model("split_solid")
def _split_solid():
    coloured_box("Half A", 1.7, 0.75, 1.2, (0.12, 0.6, 0.18),
                 pick=lambda n: n.y < -0.99)
    coloured_box("Half B", 1.7, 0.75, 1.2, (-0.12, -0.6, 0),
                 pick=lambda n: n.y > 0.99)


@model("cut")
def _cut():
    # a profile cut through the sheet: the opening's walls in the accent
    ob = box_object("Sheet", 2.2, 2.0, 0.22, bevel=0)
    tool = cutter("Window", bm_box(1.0, 0.8, 1.0, (0.1, 0.05, -0.3)), "accent")
    boolean(ob, tool)
    bevel_mod(ob, 0.02)


@model("cut_face")
def _cut_face():
    ob = box_object("Block", 1.8, 1.8, 1.3, bevel=0)
    tool = cutter("Corner", bm_box(1.2, 1.2, 1.0, (0.6, 0.6, 0.65)), "accent")
    boolean(ob, tool)
    bevel_mod(ob, 0.03)


@model("mirror")
def _mirror():
    L = [(0.15, -0.8), (0.95, -0.8), (0.95, -0.45), (0.5, -0.45),
         (0.5, 0.8), (0.15, 0.8)]
    a = prism("Original", [(x, y) for x, y in L], 0.9, mats_=("grey",))
    b = prism("Mirrored", [(-x, y) for x, y in reversed(L)], 0.9,
              mats_=("accent",))
    for ob in (a, b):
        bevel_mod(ob, 0.025)
    plane_sheet("Plane", 2.2, 1.6, at=(0, 0, 0.6), rot=(90, 0, 90))


@model("pattern")
def _pattern():
    # a square of the same block: the first one grey, the copies in the
    # accent, and over the first row and column an arrow each way it goes
    step = 0.8
    for i in range(3):
        for j in range(3):
            box_object("Block", 0.5, 0.5, 0.5, (i * step, j * step, 0.0),
                       mat="grey" if (i, j) == (0, 0) else "accent")
    z = 0.9
    arrow((0.0, 0.0, z), (2 * step + 0.2, 0.0, z), radius=0.08)
    arrow((0.0, 0.0, z), (0.0, 2 * step + 0.2, z), radius=0.08)


@model("pattern_circ")
def _pattern_circ():
    # the same block round an axis: the first one grey, the copies in the
    # accent, the axis up the middle and an arrow over them the way it goes
    n, r = 6, 1.0
    for k in range(n):
        a = 2 * math.pi * k / n + math.radians(165)
        box_object("Block", 0.45, 0.45, 0.45,
                   (r * math.cos(a), r * math.sin(a), 0.0),
                   mat="grey" if k == 0 else "accent")
    cyl("Axis", 0.07, 1.2, at=(0, 0, 0.0), mat="dark", segments=16)
    # above the back of the ring, from the first block on, sharp headed
    curved_arrow((0, 0, 0.0), r, 170, 290, z=0.95, thick=0.07,
                 head=0.16, point=2.8)


# --------------------------------------------------------------- views

@model("section")
def _section():
    ob = box_object("Block", 1.8, 1.8, 1.4, bevel=0)
    tool = cutter("Quarter", bm_box(1.0, 1.0, 1.6, (0.5, 0.5, -0.1)),
                  "accent")
    boolean(ob, tool)
    bevel_mod(ob, 0.03)


@model("xray")
def _xray():
    box_object("Shell", 1.8, 1.8, 1.4, mat="ghost", bevel=0)
    cyl("Inside", 0.45, 1.0, at=(0, 0, 0.2), mat="accent")


@model("shaded")
def _shaded():
    box_object("Block", 1.6, 1.6, 1.0)
    cyl("Boss", 0.5, 0.6, at=(0, 0, 1.0))


@model("shaded_edges")
def _shaded_edges():
    box_object("Block", 1.6, 1.6, 1.3, bevel=0)
    edges_of_box(1.6, 1.6, 1.3)


def _view_cube(pick):
    coloured_box("Cube", 1.6, 1.6, 1.6, pick=pick, bevel=0.06)


@model("front")
def _front():
    _view_cube(lambda n: n.y > 0.99)


@model("right")
def _right():
    _view_cube(lambda n: n.x > 0.99)


@model("top")
def _top():
    _view_cube(lambda n: n.z > 0.99)


@model("iso")
def _iso():
    box_object("Cube", 1.6, 1.6, 1.6, bevel=0.06)
    ball("Corner", 0.3, (0.8, 0.8, 1.6), mat="accent")


# ------------------------------------------------------------ assembly

@model("place")
def _place():
    box_object("Base", 2.2, 2.2, 0.25)
    box_object("Part", 0.9, 0.9, 0.7, (0, 0, 1.25), mat="accent")
    arrow((0.85, 0.85, 1.9), (0.85, 0.85, 0.35), radius=0.07, head=0.2)


@model("c3d_mate")
def _c3d_mate():
    coloured_box("Lower", 1.6, 1.6, 0.6, pick=lambda n: n.z > 0.99)
    coloured_box("Upper", 1.2, 1.2, 0.6, (0, 0, 1.05),
                 pick=lambda n: n.z < -0.99)
    arrow((0.95, 0.95, 1.9), (0.95, 0.95, 1.1), radius=0.06, head=0.17)


@model("c3d_flush")
def _c3d_flush():
    coloured_box("A", 1.0, 1.6, 0.9, (-0.6, 0, 0), pick=lambda n: n.z > 0.99)
    coloured_box("B", 1.0, 1.6, 0.9, (0.6, 0, 0), pick=lambda n: n.z > 0.99)


@model("c3d_angle")
def _c3d_angle():
    box_object("Base", 1.9, 1.6, 0.18)
    flap = box_object("Flap", 1.9, 1.5, 0.18, mat="accent")
    place(flap, (0, 0.8, 0.18), (35, 0, 0))
    flap.data.transform(Matrix.Translation((0, -0.75, 0)))


@model("c3d_insert")
def _c3d_insert():
    ob = box_object("Block", 1.8, 1.8, 0.8, bevel=0)
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, segments=48, radius1=0.42,
                          radius2=0.42, depth=2.0)
    tool = cutter("Bore", bm, "accent")
    boolean(ob, tool)
    bevel_mod(ob, 0.03)
    cyl("Pin", 0.36, 1.1, at=(0, 0, 1.15), mat="accent")
    cyl("Head", 0.58, 0.22, at=(0, 0, 2.2), mat="accent")


@model("c3d_parallel")
def _c3d_parallel():
    coloured_box("Lower", 1.8, 1.4, 0.3, pick=lambda n: n.z > 0.99)
    coloured_box("Upper", 1.4, 1.1, 0.3, (0.3, -0.2, 1.1),
                 pick=lambda n: n.z < -0.99)


@model("c3d_tangent")
def _c3d_tangent():
    box_object("Plate", 2.2, 1.8, 0.25)
    cyl("Roller", 0.5, 1.6, at=(-0.8, 0, 0.75), mat="accent", axis="X")


@model("c3d_symmetry")
def _c3d_symmetry():
    box_object("Left", 0.8, 1.1, 1.0, (0, 0.8, 0))
    box_object("Right", 0.8, 1.1, 1.0, (0, -0.8, 0), mat="accent")
    plane_sheet("Plane", 1.6, 1.7, at=(0, 0, 0.6), rot=(90, 0, 0))


@model("free_move")
def _free_move():
    box_object("Part", 1.0, 1.0, 1.0, mat="accent")
    for d in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        arrow((d[0] * 0.65, d[1] * 0.65, 0.5), (d[0] * 1.45, d[1] * 1.45, 0.5),
              radius=0.06, head=0.17)


@model("free_rotate")
def _free_rotate():
    box_object("Part", 1.1, 1.1, 1.1, mat="accent")
    curved_arrow((0, 0, 0.55), 1.15, -30, 210, thick=0.06)


@model("move")
def _move():
    box_object("Was", 1.0, 1.0, 1.0, (0.7, 0.7, 0), mat="ghost", bevel=0)
    box_object("Now", 1.0, 1.0, 1.0, (-0.7, -0.7, 0), mat="accent")
    arrow((0.55, 0.55, 0.5), (-0.35, -0.35, 0.5), radius=0.06, head=0.17)


@model("replace")
def _replace():
    box_object("Old", 0.9, 0.9, 0.9, (0.75, 0.75, 0))
    cyl("New", 0.48, 0.9, at=(-0.75, -0.75, 0), mat="accent")
    curved_arrow((0, 0, 1.0), 0.75, 20, 160, thick=0.05, plane="XY")


# --------------------------------------------------------------- frame

def _mitred(name, length, angle_end, s=0.6, mat="grey"):
    """A square tube from the origin along X, its far end cut on the
    half angle, the cut face in the accent."""
    ob = square_tube(name, length, s=s, mat=mat)
    big = bm_box(3.0, 3.0, 3.0, (1.5, 0, -1.5))
    tool = cutter(name + " miter", big, "accent")
    # in the tube's own frame, so it goes where the tube goes
    tool.parent = ob
    tool.location = (length, 0, 0)
    tool.rotation_euler = (0, 0, math.radians(angle_end))
    boolean(ob, tool)
    return ob


@model("frame_miter")
def _frame_miter():
    # an L: one member along X into the corner, the other along Y into it,
    # both cut on the half angle, the outside corner meeting
    _mitred("A", 1.8, -45)
    b = _mitred("B", 1.8, 45)
    b.matrix_world = Matrix.Translation((1.8, -1.8, 0)) @ \
        Matrix.Rotation(math.radians(90), 4, "Z")


@model("frame_corner")
def _frame_corner():
    square_tube("Runs on", 2.0, mat="grey")
    b = square_tube("Butts", 1.5, mat="grey")
    b.matrix_world = Matrix.Translation((1.7, -0.3, 0)) @ \
        Matrix.Rotation(math.radians(-90), 4, "Z")


@model("frame_notch")
def _frame_notch():
    cyl("Rail", 0.4, 2.4, at=(-1.2, 0, 0.5), mat="grey", axis="X")
    ob = square_tube("Post", 1.4, s=0.6, mat="accent", end_mat="accent")
    ob.matrix_world = Matrix.Translation((0, 0, -0.95)) @ \
        Matrix.Rotation(math.radians(-90), 4, "Y")
    tool = cyl("Cope", 0.4, 2.4, at=(-1.2, 0, 0.5), mat="accent", axis="X")
    tool.hide_render = True
    boolean(ob, tool)


@model("frame_trim")
def _frame_trim():
    box_object("Plate", 0.2, 2.0, 1.8, (1.0, 0, -0.6))
    ob = square_tube("Member", 2.6, mat="grey")
    ob.location = (-1.6, 0, 0.55)
    tool = cutter("Face", bm_box(2.0, 3.0, 3.0, (2.0 - 0.0, 0, -1.5)),
                  "accent")
    tool.location = (-0.1 + 0.0, 0, 1.0)
    boolean(ob, tool)


@model("frame_lengthen")
def _frame_lengthen():
    square_tube("Member", 1.4, mat="grey")
    ext = square_tube("Extension", 0.8, mat="accent", end_mat="accent")
    ext.location = (1.42, 0, 0)
    arrow((1.0, 0, 0.55), (2.45, 0, 0.55), radius=0.06, head=0.17)


@model("frame_insert")
def _frame_insert():
    leg = square_tube("Leg", 1.8, s=0.5, mat="grey")
    leg.matrix_world = Matrix.Rotation(math.radians(-90), 4, "Y")
    rail = square_tube("Rail", 1.8, s=0.5, mat="grey")
    rail.location = (0, 0, 1.8)
    new = square_tube("New", 1.8, s=0.5, mat="accent", end_mat="accent")
    new.matrix_world = Matrix.Translation((0, 0, 1.8)) @ \
        Matrix.Rotation(math.radians(90), 4, "Z")


@model("frame_assembly")
def _frame_assembly():
    s, w, d, h = 0.32, 2.2, 1.4, 1.4
    for x in (0, w):
        for y in (0, d):
            leg = square_tube("Leg", h, s=s, t=0.06)
            leg.matrix_world = Matrix.Translation((x, y, 0)) @ \
                Matrix.Rotation(math.radians(-90), 4, "Y")
    for y in (0, d):
        r = square_tube("Rail", w, s=s, t=0.06, mat="accent",
                        end_mat="accent")
        r.location = (0, y, h)
    for x in (0, w):
        r = square_tube("Rail", d, s=s, t=0.06, mat="accent",
                        end_mat="accent")
        r.matrix_world = Matrix.Translation((x, 0, h)) @ \
            Matrix.Rotation(math.radians(90), 4, "Z")


@model("frame_library")
def _frame_library():
    angle = [(0, 0), (0.7, 0), (0.7, 0.14), (0.14, 0.14), (0.14, 0.7),
             (0, 0.7)]
    channel = [(0, 0), (0.7, 0), (0.7, 0.7), (0.56, 0.7), (0.56, 0.14),
               (0.14, 0.14), (0.14, 0.7), (0, 0.7)]
    for k, (shape, mat) in enumerate(((angle, "grey"), (channel, "accent"))):
        ob = prism("Profile", shape, 1.8, mats_=(mat,))
        ob.matrix_world = Matrix.Translation((0, k * 1.0, 0)) @ \
            Matrix.Rotation(math.radians(90), 4, "Y") @ \
            Matrix.Rotation(math.radians(90), 4, "Z")
        bevel_mod(ob, 0.015)
    tube = square_tube("Tube", 1.8, s=0.7, t=0.12)
    tube.location = (0, 2.2, 0.0)


# --------------------------------------------------------- sheet metal

T = 0.12


@model("sm_face")
def _sm_face():
    coloured_box("Face", 2.2, 1.8, T, pick=lambda n: n.z > 0.99, bevel=0.01)


# The walls and hems are at the back (toward -X), so the view looks at
# their faces and down their profiles, not at their backs.

@model("sm_flange")
def _sm_flange():
    sheet("Base", [(1.1, 0), (-0.6, 0)], width=1.8)
    sheet("Flange", rounded_path([(-0.6, 0), (-0.95, 0), (-0.95, 1.5)],
                                 0.3), width=1.8, mat="accent")


@model("sm_contour")
def _sm_contour():
    sheet("Contour", rounded_path([(1.0, 0.7), (1.0, 0), (-0.9, 0),
                                   (-0.9, 1.4)], 0.28), width=1.6,
          mat="accent")


@model("sm_fold")
def _sm_fold():
    sheet("Flat", [(1.2, 0), (-0.2, 0)], width=1.8)
    sheet("Folded", rounded_path([(-0.2, 0), (-0.35, 0), (-1.05, 1.2)], 0.2),
          width=1.8, mat="accent")
    box_object("Line", 0.06, 1.8, 0.01, (-0.2, 0, T / 2), mat="dark",
               bevel=0)


@model("sm_folded")
def _sm_folded():
    # the folded tray: its base and four walls
    box_object("Base", 2.0, 1.8, T, bevel=0.01)
    for x in (-1.0 + T / 2, 1.0 - T / 2):
        box_object("Wall", T, 1.8, 0.8, (x, 0, T), mat="accent", bevel=0.01)
    for y in (-0.9 + T / 2, 0.9 - T / 2):
        box_object("Wall", 2.0 - 2 * T - 0.04, T, 0.8, (0, y, T),
                   mat="accent", bevel=0.01)


@model("sm_flat")
def _sm_flat():
    cross = [(-0.5, -1.2), (0.5, -1.2), (0.5, -0.5), (1.2, -0.5), (1.2, 0.5),
             (0.5, 0.5), (0.5, 1.2), (-0.5, 1.2), (-0.5, 0.5), (-1.2, 0.5),
             (-1.2, -0.5), (-0.5, -0.5)]
    ob = prism("Flat", cross, T)
    bevel_mod(ob, 0.01)
    for (x, y, sx, sy) in ((0, -0.5, 1.0, 0.1), (0, 0.5, 1.0, 0.1),
                           (-0.5, 0, 0.1, 1.0), (0.5, 0, 0.1, 1.0)):
        box_object("Bend line", sx, sy, 0.02, (x, y, T), mat="accent",
                   bevel=0)


def _hem(path):
    # drawn running out to +X, turned round so the hem is at the back and
    # its profile faces the view
    mirror = [(-x, y) for x, y in path]
    sheet("Sheet", [(1.2, 0), (-0.6, 0)], width=1.2)
    sheet("Hem", mirror, width=1.2, mat="accent")


@model("sm_hem")
def _sm_hem():
    _hem(rounded_path([(0.6, 0), (1.0, 0), (1.0, 0.34), (0.0, 0.34)], 0.17))


@model("sm_hem_double")
def _sm_hem_double():
    _hem(rounded_path([(0.6, 0), (1.0, 0), (1.0, 0.34), (0.15, 0.34),
                       (0.15, 0.68), (0.9, 0.68)], 0.17))


@model("sm_hem_rolled")
def _sm_hem_rolled():
    pts = [(0.6, 0.0)]
    for k in range(0, 31):
        a = math.radians(-90 + 300 * k / 30)
        pts.append((0.8 + 0.35 * math.cos(a), 0.35 + 0.35 * math.sin(a)))
    _hem(pts)


@model("sm_hem_teardrop")
def _sm_hem_teardrop():
    pts = [(0.6, 0.0)]
    for k in range(0, 25):
        a = math.radians(-90 + 220 * k / 24)
        pts.append((0.85 + 0.28 * math.cos(a), 0.28 + 0.28 * math.sin(a)))
    pts.append((0.1, 0.16))
    _hem(pts)


@model("sm_corner")
def _sm_corner():
    # a base and two walls up from it, a seam's gap where they meet
    box_object("Base", 2.0, 2.0, T, bevel=0.01)
    box_object("Wall A", T, 1.86, 1.1, (-1.0 + T / 2, 0.07, T),
               mat="accent", bevel=0.01)
    box_object("Wall B", 1.86, T, 1.1, (0.07, -1.0 + T / 2, T),
               mat="accent", bevel=0.01)


@model("sm_corner_round")
def _sm_corner_round():
    # the plate, its corner rounded off big, the round in the accent
    ob = prism("Plate", [(-1.1, -1.0), (1.1, -1.0), (1.1, 0.2), (0.3, 0.2),
                         (0.3, 1.0), (-1.1, 1.0)], T)
    bevel_mod(ob, 0.01)
    sector = [(0.3, 0.2)] + [(0.3 + 0.8 * math.cos(math.radians(a)),
                              0.2 + 0.8 * math.sin(math.radians(a)))
                             for a in range(0, 91, 6)]
    c = prism("Round", sector, T, mats_=("accent",))
    bevel_mod(c, 0.01)


def _perforated(cut_shape):
    ob = box_object("Sheet", 2.4, 2.0, T, bevel=0)
    bm = bmesh.new()
    for k in range(4):
        y = -0.72 + k * 0.48
        verts = [bm.verts.new((x * 1.9, y + yy * 1.5, -0.5))
                 for x, yy in cut_shape]
        face = bm.faces.new(verts)
        if face.normal.z < 0:
            face.normal_flip()
        ext = bmesh.ops.extrude_face_region(bm, geom=[face])
        top = [v for v in ext["geom"] if isinstance(v, bmesh.types.BMVert)]
        bmesh.ops.translate(bm, vec=(0, 0, 1.0), verts=top)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    tool = cutter("Slots", bm, "accent")
    boolean(ob, tool)
    box_object("Bend", 0.05, 2.0, 0.01, (0, 0, T), mat="dark", bevel=0)


@model("sm_perforation")
def _sm_perforation():
    _perforated([(-0.28, -0.09), (0.0, 0.06), (0.28, -0.09), (0.28, 0.05),
                 (0.0, 0.2), (-0.28, 0.05)])


@model("sm_perforation_straight")
def _sm_perforation_straight():
    _perforated([(-0.08, -0.15), (0.08, -0.15), (0.08, 0.15),
                 (-0.08, 0.15)])


@model("sm_perforation_trapezoid")
def _sm_perforation_trapezoid():
    _perforated([(-0.16, -0.15), (0.16, -0.15), (0.07, 0.15),
                 (-0.07, 0.15)])


# The assembly constraints are drawn, not rendered: side views read at
# the 18 pixels the Place Constraint window shows them at, isometric
# blocks do not (redraw_2026_11.py has them).
for _name in [n for n in MORE if n.startswith("c3d_")]:
    del MORE[_name]


@model("sweep")
def _sweep_square():
    # a square profile, standing apart in the accent at the start; the
    # path it follows, a dark line; and the bar it sweeps out along a
    # quarter turn.  Square, so it reads as a section carried along a
    # path and not as a tube.
    R, half, n = 1.5, 0.3, 32
    centre = Vector((0.0, 0.0, 0.0))

    def at(t):
        a = math.radians(-90 + 90 * t)
        p = centre + Vector((R * math.cos(a), R * math.sin(a), 0.4))
        tangent = Vector((-math.sin(a), math.cos(a), 0.0))
        return p, tangent

    bm = bmesh.new()
    loops = []
    for k in range(n + 1):
        p, tg = at(0.08 + 0.92 * k / n)
        side = tg.cross(Vector((0, 0, 1))).normalized()
        up = Vector((0, 0, 1))
        loops.append([bm.verts.new(p + side * sx * half + up * sz * half)
                      for sx, sz in ((-1, -1), (1, -1), (1, 1), (-1, 1))])
    for a, b in zip(loops, loops[1:]):
        for i in range(4):
            j = (i + 1) % 4
            bm.faces.new((a[i], a[j], b[j], b[i]))
    bm.faces.new(list(reversed(loops[0])))
    bm.faces.new(loops[-1])
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bar = mesh_object("Swept", bm, ["grey"])
    bevel_mod(bar, 0.02)
    # the profile, out in front of where the bar starts
    p0, t0 = at(-0.12)
    plate = box_object("Profile", 2 * half + 0.08, 0.07, 2 * half + 0.08,
                       mat="accent", bevel=0.01)
    plate.matrix_world = Matrix.Translation(p0 - Vector((0, 0, half + 0.04))) \
        @ t0.to_track_quat("Y", "Z").to_matrix().to_4x4()
    # the path, from the profile into the bar and out past its end
    cu = bpy.data.curves.new("Path", "CURVE")
    cu.dimensions = "3D"
    cu.bevel_depth = 0.035
    sp = cu.splines.new("POLY")
    pts = [at(-0.12 + 1.27 * k / 40)[0] for k in range(41)]
    sp.points.add(len(pts) - 1)
    for spt, co in zip(sp.points, pts):
        spt.co = tuple(co) + (1.0,)
    path_ob = bpy.data.objects.new("Path", cu)
    bpy.context.scene.collection.objects.link(path_ob)
    path_ob.data.materials.append(MATS["dark"])


def _swept_bar(points_of, half=0.3, n=36, profile_gap=0.28, path_r=0.05,
               attached=False):
    """A square bar swept along ``points_of(t) -> (point, tangent, up)``,
    t from 0 to 1; its profile in the accent at the start, apart from it
    or on its start face; the path as a dark line."""
    bm = bmesh.new()
    loops = []
    for k in range(n + 1):
        p, tg, up = points_of(k / n)
        side = tg.cross(up).normalized()
        up = side.cross(tg).normalized()
        loops.append([bm.verts.new(p + side * sx * half + up * sz * half)
                      for sx, sz in ((-1, -1), (1, -1), (1, 1), (-1, 1))])
    for a, b in zip(loops, loops[1:]):
        for i in range(4):
            j = (i + 1) % 4
            bm.faces.new((a[i], a[j], b[j], b[i]))
    start = bm.faces.new(list(reversed(loops[0])))
    bm.faces.new(loops[-1])
    if attached:
        start.material_index = 1
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bar = mesh_object("Swept", bm, ["grey", "accent"])
    bevel_mod(bar, 0.02)
    p0, t0, u0 = points_of(0.0)
    if not attached:
        side = t0.cross(u0).normalized()
        u0 = side.cross(t0).normalized()
        frame = Matrix((side, t0, u0)).transposed().to_4x4()
        plate = box_object("Profile", 2 * half + 0.1, 0.08, 2 * half + 0.1,
                           mat="accent", bevel=0.01)
        plate.data.transform(Matrix.Translation((0, 0, -(half + 0.05))))
        plate.matrix_world = Matrix.Translation(p0 - t0 * profile_gap) @ frame
    # the path: from the profile, through the bar, out past its end
    cu = bpy.data.curves.new("Path", "CURVE")
    cu.dimensions = "3D"
    cu.bevel_depth = path_r
    cu.bevel_resolution = 2
    sp = cu.splines.new("POLY")
    pts = []
    for k in range(-6, 47):
        t = k / 40.0
        if t <= 0:
            p, tg, _u = points_of(0.0)
            pts.append(p + tg * t * 1.2)
        elif t >= 1:
            p, tg, _u = points_of(1.0)
            pts.append(p + tg * (t - 1) * 1.2)
        else:
            pts.append(points_of(t)[0])
    sp.points.add(len(pts) - 1)
    for spt, co in zip(sp.points, pts):
        spt.co = tuple(co) + (1.0,)
    ob = bpy.data.objects.new("Path", cu)
    bpy.context.scene.collection.objects.link(ob)
    ob.data.materials.append(MATS["dark"])


@model("sweep")
def _sweep_across():
    # A: a quarter turn lying flat, bulging away from the viewer, so the
    # bar's whole length is seen sweeping across
    R = 1.5

    def at(t):
        a = math.radians(90 + 90 * t)
        return (Vector((R * math.cos(a) + 0.75, R * math.sin(a) - 0.75, 0.3)),
                Vector((-math.sin(a), math.cos(a), 0.0)), Vector((0, 0, 1)))
    _swept_bar(at, path_r=0.06)


@model("sweep_b")
def _sweep_rising():
    # B: rising in a quarter turn, seen from the side like an elbow, the
    # profile on its start face
    R = 1.4

    def at(t):
        a = math.radians(-90 + 90 * t)
        p = Vector((R * math.cos(a) - 0.7, 0.0, R * math.sin(a) + 1.4))
        tg = Vector((-math.sin(a), 0.0, math.cos(a)))
        return p, tg, Vector((0, 1, 0))
    _swept_bar(at, attached=True, path_r=0.06)


@model("sweep")
def _sweep_final():
    # The view looks in from +X+Y.  The bar starts heading -Y, so the
    # profile standing before it shows its face at 45 degrees with the
    # path in the gap between, then turns a quarter toward +X, across
    # the view, so the curve is seen whole.
    R, C = 1.4, Vector((0.4, 1.0, 0.3))

    def at(t):
        a = math.radians(180 + 90 * t)
        return (C + Vector((R * math.cos(a), R * math.sin(a), 0.0)),
                Vector((-math.sin(a), math.cos(a), 0.0)), Vector((0, 0, 1)))
    _swept_bar(at, profile_gap=0.5, path_r=0.06)


@model("sweep")
def _sweep_left_to_right():
    # the same, mirrored across the view, so it reads left to right: the
    # profile on the left, the bar sweeping off to the right
    R, C = 1.4, Vector((1.0, 0.4, 0.3))

    def at(t):
        a = math.radians(180 + 90 * t)
        x, y = R * math.cos(a), R * math.sin(a)
        tx, ty = -math.sin(a), math.cos(a)
        return (C + Vector((y, x, 0.0)), Vector((ty, tx, 0.0)),
                Vector((0, 0, 1)))
    _swept_bar(at, profile_gap=0.5, path_r=0.06)


@model("sweep")
def _sweep_s():
    # An S: two quarter turns, the second back the other way.  Drawn in a
    # frame where it starts heading -Y (so the profile before it shows its
    # face), then mirrored across the view (x and y swapped) so it reads
    # left to right: profile on the left, the S sweeping off to the right.
    R = 0.95

    def at(t):
        if t <= 0.5:
            a = math.radians(180 + 180 * t)
            x, y = R + R * math.cos(a), R * math.sin(a)
            tx, ty = -math.sin(a), math.cos(a)
        else:
            b = math.radians(90 - 180 * (t - 0.5))
            x, y = R + R * math.cos(b), -2 * R + R * math.sin(b)
            tx, ty = math.sin(b), -math.cos(b)
        return (Vector((y, x, 0.4)), Vector((ty, tx, 0.0)),
                Vector((0, 0, 1)))
    _swept_bar(at, half=0.36, n=48, profile_gap=0.5, path_r=0.065)


@model("thread")
def _thread():
    # a shaft with its thread: a copper helix wound round a grey bolt
    # shank, under a hex head, bold enough to read at 20 pixels
    cyl("Shank", 0.42, 1.9, at=(0, 0, 0))
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, segments=6, radius1=0.78,
                          radius2=0.78, depth=0.5)
    bmesh.ops.translate(bm, vec=(0, 0, 2.15), verts=bm.verts)
    head = mesh_object("Head", bm, ["grey"])
    bevel_mod(head, 0.03)
    cu = bpy.data.curves.new("Helix", "CURVE")
    cu.dimensions = "3D"
    cu.bevel_depth = 0.085
    cu.bevel_resolution = 3
    sp = cu.splines.new("POLY")
    turns, n = 5.5, 220
    sp.points.add(n)
    for k, spt in enumerate(sp.points):
        t = k / n
        a = 2 * math.pi * turns * t
        spt.co = (0.44 * math.cos(a), 0.44 * math.sin(a), 0.1 + 1.6 * t, 1.0)
    ob = bpy.data.objects.new("Helix", cu)
    bpy.context.scene.collection.objects.link(ob)
    ob.data.materials.append(MATS["accent"])
