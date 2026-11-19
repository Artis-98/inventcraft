"""Toolbar icons rendered in 3D with Blender, for the icons that show a
solid: the shape built here, lit like a studio product shot, outlined so
it holds at 20 pixels, and rendered from the icon set's three quarter
view on a transparent background.

The grey is the set's solid tone and the copper its accent, so a render
sits among the drawn icons.  Each is rendered twice: for the light
schemes and, a touch brighter with a lighter outline, for the dark ones.

    blender --background --factory-startup --python tools/icons/render3d.py -- OUT [name ...]

writes OUT/<name>.png and OUT/<name>.dark.png, 256 pixels square.
"""
import math
import os
import sys

import bmesh
import bpy
from mathutils import Matrix, Vector

SIZE = 256
SAMPLES = 64


def lin(hex_colour):
    """An sRGB hex colour as Blender's linear RGBA."""
    out = []
    for i in (1, 3, 5):
        c = int(hex_colour[i:i + 2], 16) / 255.0
        out.append(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4)
    return out + [1.0]


GREY = "#8c96a2"
ACCENT = "#c48c14"
DARK_ARROW = "#2b3540"


# ------------------------------------------------------------- materials

def material(name, colour, metallic=0.0, roughness=0.45, coat=0.0):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    bsdf = m.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = lin(colour)
    bsdf.inputs["Metallic"].default_value = metallic
    bsdf.inputs["Roughness"].default_value = roughness
    if coat:
        bsdf.inputs["Coat Weight"].default_value = coat
    return m


def outline_material(colour):
    """Seen only from behind: the inverted hull's back faces, which show
    round a shape's edge as its outline."""
    m = bpy.data.materials.new("Outline")
    m.use_nodes = True
    nodes, links = m.node_tree.nodes, m.node_tree.links
    for n in list(nodes):
        nodes.remove(n)
    out = nodes.new("ShaderNodeOutputMaterial")
    mix = nodes.new("ShaderNodeMixShader")
    geo = nodes.new("ShaderNodeNewGeometry")
    emit = nodes.new("ShaderNodeEmission")
    emit.inputs["Color"].default_value = lin(colour)
    emit.inputs["Strength"].default_value = 1.0
    clear = nodes.new("ShaderNodeBsdfTransparent")
    links.new(geo.outputs["Backfacing"], mix.inputs["Fac"])
    # Solidify's flipped shell faces the viewer on its far side only, so
    # the side facing the viewer is the one let through
    links.new(clear.outputs["BSDF"], mix.inputs[1])
    links.new(emit.outputs["Emission"], mix.inputs[2])
    links.new(mix.outputs["Shader"], out.inputs["Surface"])
    return m


MATS = {}


def mats(outline_colour):
    MATS["grey"] = material("Grey", GREY, metallic=0.25, roughness=0.42,
                            coat=0.25)
    MATS["accent"] = material("Accent", ACCENT, metallic=0.75,
                              roughness=0.32)
    MATS["copper"] = material("Copper", "#d9925a", metallic=0.85,
                              roughness=0.3)
    MATS["dark"] = material("Dark", DARK_ARROW, metallic=0.1, roughness=0.5)
    glass = material("Plane", "#5a6c80", roughness=0.2)
    glass.node_tree.nodes.get("Principled BSDF").inputs["Alpha"] \
        .default_value = 0.32
    MATS["plane"] = glass
    ghost = material("Ghost", GREY, roughness=0.4)
    ghost.node_tree.nodes.get("Principled BSDF").inputs["Alpha"] \
        .default_value = 0.3
    MATS["ghost"] = ghost
    MATS["outline"] = outline_material(outline_colour)


# ---------------------------------------------------------------- shapes

def mesh_object(name, bm, materials):
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(ob)
    for m in materials:
        ob.data.materials.append(MATS[m])
    for p in ob.data.polygons:
        p.use_smooth = False
    return ob


def bm_box(sx, sy, sz, at=(0, 0, 0)):
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bmesh.ops.scale(bm, vec=(sx, sy, sz), verts=bm.verts)
    bmesh.ops.translate(bm, vec=Vector(at) + Vector((0, 0, sz / 2.0)),
                        verts=bm.verts)
    return bm


def bevel_mod(ob, width=0.035, segments=3):
    b = ob.modifiers.new("Bevel", "BEVEL")
    b.width = width
    b.segments = segments
    b.limit_method = "ANGLE"
    b.harden_normals = False
    return b


def outline(ob, thickness=0.028):
    """The inverted hull: a shell a little outside, its normals in, in
    the outline material."""
    ob.data.materials.append(MATS["outline"])
    s = ob.modifiers.new("Outline", "SOLIDIFY")
    s.thickness = thickness
    s.offset = 1.0
    s.use_flip_normals = True
    s.use_rim = False
    s.material_offset = len(ob.data.materials) - 1
    return s


def box_object(name, sx, sy, sz, at=(0, 0, 0), mat="grey", bevel=0.035):
    ob = mesh_object(name, bm_box(sx, sy, sz, at), [mat])
    if bevel:
        bevel_mod(ob, bevel)
    return ob


def cutter(name, bm, mat="accent"):
    ob = mesh_object(name, bm, [mat])
    ob.hide_render = True
    return ob


def boolean(ob, tool, op="DIFFERENCE"):
    b = ob.modifiers.new("Bool", "BOOLEAN")
    b.operation = op
    b.object = tool
    b.solver = "EXACT"
    try:
        b.use_self = False
    except AttributeError:
        pass
    try:
        # the cut faces take the cutter's material: a hole's bore, a
        # miter's face, in the accent
        b.material_mode = "TRANSFER"
    except (AttributeError, TypeError):
        pass
    # booleans before the bevel, so the cut edges are bevelled too
    bpy.context.view_layer.objects.active = ob
    while ob.modifiers[0].name != b.name:
        bpy.ops.object.modifier_move_up(modifier=b.name)
    return b


def arrow(start, end, radius=0.06, head=0.17, mat="dark", point=1.6):
    """A shaft and a cone head from ``start`` to ``end``."""
    # big wide heads on thin shafts: at toolbar size it is the head that
    # says which way, and a fat shaft only blurs it
    head = max(head * 1.5, 0.24)
    radius = radius * 0.75
    start, end = Vector(start), Vector(end)
    d = end - start
    length = d.length
    rot = d.to_track_quat("Z", "Y").to_matrix().to_4x4()
    # a short arrow is all head (a curved arrow's tip is one)
    # ``point``: how long the head is for how wide; more is sharper
    tip_len = min(head * point, length)
    made = []
    if length - tip_len > 1e-3:
        bm = bmesh.new()
        bmesh.ops.create_cone(bm, cap_ends=True, segments=24, radius1=radius,
                              radius2=radius, depth=length - tip_len)
        bmesh.ops.translate(bm, vec=(0, 0, (length - tip_len) / 2.0),
                            verts=bm.verts)
        made.append(mesh_object("Shaft", bm, [mat]))
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, segments=24, radius1=head,
                          radius2=0.0, depth=tip_len)
    bmesh.ops.translate(bm, vec=(0, 0, length - tip_len / 2.0),
                        verts=bm.verts)
    tip = mesh_object("Head", bm, [mat])
    made.append(tip)
    shaft = made[0]
    for ob in made:
        ob.matrix_world = Matrix.Translation(start) @ rot
        for p in ob.data.polygons:
            p.use_smooth = True
    return shaft, tip


def prism(name, outline_pts, height, at_z=0.0, mats_=("grey",),
          top_mat=0):
    """A profile in XY pulled up ``height``; its top face in material
    ``top_mat``."""
    bm = bmesh.new()
    verts = [bm.verts.new((x, y, at_z)) for x, y in outline_pts]
    face = bm.faces.new(verts)
    if face.normal.z < 0:
        face.normal_flip()
    ext = bmesh.ops.extrude_face_region(bm, geom=[face])
    top = [v for v in ext["geom"] if isinstance(v, bmesh.types.BMVert)]
    bmesh.ops.translate(bm, vec=(0, 0, height), verts=top)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    for f in bm.faces:
        if f.normal.z > 0.99 and abs(f.calc_center_median().z
                                     - (at_z + height)) < 1e-6:
            f.material_index = top_mat
    return mesh_object(name, bm, list(mats_))


# ----------------------------------------------------------------- icons

def m_box():
    box_object("Box", 1.6, 1.6, 1.6)


def m_bodies():
    box_object("A", 1.2, 1.2, 1.2, (0.55, -0.55, 0))
    box_object("B", 1.2, 1.2, 1.2, (-0.6, 0.6, 0), mat="accent")


def m_extrude():
    L = [(-0.9, -0.9), (0.9, -0.9), (0.9, -0.2), (-0.2, -0.2), (-0.2, 0.9),
         (-0.9, 0.9)]
    ob = prism("Prism", L, 1.1, mats_=("grey", "accent"), top_mat=1)
    bevel_mod(ob, 0.03)
    # up out of the profile it was pulled from
    arrow((0.0, -0.55, 1.1), (0.0, -0.55, 2.35), radius=0.08, head=0.21)


def _edge_block(segments, offset):
    bm = bm_box(1.8, 1.8, 1.6)
    # the top edge nearest the viewer, along Y at +X; cut deep, most of
    # the block's height, so the corner is what the icon is about
    edge = next(e for e in bm.edges
                if all(v.co.x > 0.8 and v.co.z > 1.5 for v in e.verts))
    res = bmesh.ops.bevel(bm, geom=[edge] + list(edge.verts), offset=offset,
                          segments=segments, profile=0.5, affect="EDGES")
    for f in res["faces"]:
        f.material_index = 1
    ob = mesh_object("Block", bm, ["grey", "accent"])
    if segments > 1:
        for p in ob.data.polygons:
            p.use_smooth = p.material_index == 1
    bevel_mod(ob, 0.03)
    return ob


def m_fillet():
    _edge_block(16, 1.15)


def m_chamfer():
    _edge_block(1, 1.15)


def m_shell():
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bmesh.ops.scale(bm, vec=(1.8, 1.8, 1.2), verts=bm.verts)
    bmesh.ops.translate(bm, vec=(0, 0, 0.6), verts=bm.verts)
    top = next(f for f in bm.faces if f.normal.z > 0.99)
    bmesh.ops.delete(bm, geom=[top], context="FACES")
    ob = mesh_object("Shell", bm, ["grey", "accent"])
    s = ob.modifiers.new("Walls", "SOLIDIFY")
    s.thickness = 0.16
    s.offset = -1.0
    s.material_offset = 1
    s.material_offset_rim = 0
    s.use_even_offset = True
    bevel_mod(ob, 0.025)


def m_hole():
    ob = box_object("Block", 1.8, 1.8, 1.0, bevel=0)
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, segments=48, radius1=0.42,
                          radius2=0.42, depth=2.0)
    tool = cutter("Drill", bm)
    boolean(ob, tool)
    ob.data.materials.append(MATS["accent"])
    bevel_mod(ob, 0.03)
    # the bore lit in the accent: a thin sleeve just inside it
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=False, segments=48, radius1=0.415,
                          radius2=0.415, depth=0.99)
    bmesh.ops.translate(bm, vec=(0, 0, 0.5), verts=bm.verts)
    bmesh.ops.reverse_faces(bm, faces=bm.faces)
    sleeve = mesh_object("Bore", bm, ["accent"])
    for p in sleeve.data.polygons:
        p.use_smooth = True


T_SHAPE = [(-0.78, 0.2), (-0.78, 0.66), (0.78, 0.66), (0.78, 0.2),
           (0.23, 0.2), (0.23, -0.8), (-0.23, -0.8), (-0.23, 0.2)]


def m_emboss():
    box_object("Slab", 2.0, 2.0, 0.3)
    ob = prism("Raised", T_SHAPE, 0.42, at_z=0.3, mats_=("accent",))
    bevel_mod(ob, 0.02)


def m_engrave():
    slab = box_object("Slab", 2.0, 2.0, 0.5, bevel=0)
    tool = prism("Cut", T_SHAPE, 0.5, at_z=0.2, mats_=("grey",))
    tool.hide_render = True
    boolean(slab, tool)
    bevel_mod(slab, 0.025)
    floor = prism("Floor", T_SHAPE, 0.01, at_z=0.2, mats_=("accent",))
    floor.scale = (0.999, 0.999, 1.0)


def m_frame_member():
    bm = bm_box(2.0, 0.82, 0.82, (0, 0, -0.41))
    for f in bm.faces:
        if abs(f.normal.x) > 0.99:
            f.material_index = 1
    ob = mesh_object("Tube", bm, ["grey", "accent"])
    tool = cutter("Bore", bm_box(2.2, 0.6, 0.6, (0, 0, -0.3)), "grey")
    boolean(ob, tool)
    bevel_mod(ob, 0.025)
    ob.rotation_euler = (0, 0, math.radians(-12))


def m_pipe_insert():
    cu = bpy.data.curves.new("Run", "CURVE")
    cu.dimensions = "3D"
    cu.bevel_depth = 0.3
    cu.bevel_resolution = 6
    cu.use_fill_caps = True
    sp = cu.splines.new("BEZIER")
    sp.bezier_points.add(2)
    pts = [(-1.0, 0, 0), (0.3, 0, 0), (0.3, 0, 1.3)]
    for bp, p in zip(sp.bezier_points, pts):
        bp.co = p
        bp.handle_left_type = bp.handle_right_type = "VECTOR"
    mid = sp.bezier_points[1]
    mid.handle_left_type = mid.handle_right_type = "FREE"
    mid.handle_left = (0.3 - 0.6, 0, 0)
    mid.handle_right = (0.3, 0, 0.6)
    ob = bpy.data.objects.new("Run", cu)
    bpy.context.scene.collection.objects.link(ob)
    ob.data.materials.append(MATS["copper"])
    ob.rotation_euler = (0, 0, math.radians(-45))


MODELS = {
    "box": m_box, "bodies": m_bodies, "extrude": m_extrude,
    "fillet": m_fillet, "chamfer": m_chamfer, "shell": m_shell,
    "hole": m_hole, "emboss": m_emboss, "engrave": m_engrave,
    "frame_member": m_frame_member, "pipe_insert": m_pipe_insert,
}

# the rest of the set's solids, in a file of their own, sharing the
# helpers above
exec(compile(open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "models3d.py"), encoding="utf-8").read(),
             "models3d.py", "exec"), globals())
MODELS.update(MORE)
# drawn icons that read better than their renders, picked 2026-11-18
FLAT = {"move", "replace", "sm_perforation",
        "sm_perforation_straight", "sm_perforation_trapezoid",
        "sm_corner_round", "pipe_insert"}
for _name in FLAT:
    MODELS.pop(_name, None)


# ------------------------------------------------------- scene and shot

def clear():
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob, do_unlink=True)
    for coll in (bpy.data.meshes, bpy.data.curves, bpy.data.materials,
                 bpy.data.lights, bpy.data.cameras, bpy.data.worlds):
        for item in list(coll):
            coll.remove(item)


def stage(dark: bool):
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = SAMPLES
    scene.cycles.use_denoising = True
    scene.render.film_transparent = True
    scene.render.resolution_x = scene.render.resolution_y = SIZE
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.view_settings.view_transform = "Standard"
    scene.view_settings.look = "None"
    scene.view_settings.exposure = 0.25 if dark else 0.0
    world = bpy.data.worlds.new("Studio")
    world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")
    bg.inputs["Color"].default_value = lin("#c8ced6")
    bg.inputs["Strength"].default_value = 0.55
    scene.world = world
    for name, rot, energy, size in (
            ("Key", (math.radians(50), 0, math.radians(-25)), 3.2, 8.0),
            ("Fill", (math.radians(65), 0, math.radians(110)), 1.0, 20.0),
            ("Rim", (math.radians(-60), 0, math.radians(200)), 2.0, 5.0)):
        light = bpy.data.lights.new(name, "SUN")
        light.energy = energy
        light.angle = math.radians(size)
        ob = bpy.data.objects.new(name, light)
        ob.rotation_euler = rot
        scene.collection.objects.link(ob)


def shoot(path):
    scene = bpy.context.scene
    cam_data = bpy.data.cameras.new("Cam")
    cam_data.type = "ORTHO"
    cam = bpy.data.objects.new("Cam", cam_data)
    scene.collection.objects.link(cam)
    scene.camera = cam
    # the set's three quarter view: from front right, above
    az, el = math.radians(45.0), math.radians(32.0)
    look = -Vector((math.cos(el) * math.cos(az), math.cos(el) * math.sin(az),
                    math.sin(el)))
    rot = look.to_track_quat("-Z", "Y").to_matrix()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    corners = []
    for ob in scene.objects:
        if ob.type not in ("MESH", "CURVE") or ob.hide_render:
            continue
        # the geometry as it is drawn, every point of it: a curve's bound
        # box is far bigger than its tube, and would shrink the icon
        ev = ob.evaluated_get(depsgraph)
        me = ev.to_mesh()
        corners += [ev.matrix_world @ v.co for v in me.vertices]
        ev.to_mesh_clear()
    inv = rot.transposed()
    local = [inv @ c for c in corners]
    xs, ys = [p.x for p in local], [p.y for p in local]
    zs = [p.z for p in local]
    centre = rot @ Vector(((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2,
                           max(zs) + 10.0))
    cam.matrix_world = Matrix.Translation(centre) @ rot.to_4x4()
    cam_data.ortho_scale = max(max(xs) - min(xs), max(ys) - min(ys)) * 1.1
    cam_data.clip_end = 100.0
    scene.render.filepath = path
    bpy.ops.render.render(write_still=True)


def outline_png(path, colour, radius=6):
    """A dark rim round the render's silhouette, drawn from its own
    alpha: the mask grown ``radius`` pixels, filled under the shape.  At
    20 pixels it is the line that keeps the shape apart from the panel."""
    import numpy as np
    img = bpy.data.images.load(path)
    w, h = img.size
    px = np.array(img.pixels[:], dtype=np.float32).reshape(h, w, 4)
    a = px[..., 3]
    grown = a.copy()
    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            if dx * dx + dy * dy > radius * radius:
                continue
            shifted = np.roll(np.roll(a, dy, axis=0), dx, axis=1)
            np.maximum(grown, shifted, out=grown)
    c = np.array(lin(colour)[:3], dtype=np.float32)
    under = grown * (1.0 - a)
    alpha = a + under
    safe = np.where(alpha > 1e-6, alpha, 1.0)
    rgb = (px[..., :3] * a[..., None] + c * under[..., None]) / safe[..., None]
    out = np.dstack([rgb, alpha]).astype(np.float32)
    img.pixels[:] = out.ravel()
    img.filepath_raw = path
    img.file_format = "PNG"
    img.save()
    bpy.data.images.remove(img)


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    out, names = argv[0], argv[1:] or sorted(MODELS)
    os.makedirs(out, exist_ok=True)
    for name in names:
        for dark in (False, True):
            clear()
            mats("#000000")
            MODELS[name]()
            stage(dark)
            path = os.path.join(out, name + (".dark" if dark else "")
                                + ".png")
            shoot(path)
            outline_png(path, "#5d6977" if dark else "#1b2128")
            print("rendered", name, "dark" if dark else "light")


main()
