"""Render OpenCascade STL groups with one shared isometric studio setup."""
import argparse
import json
import math
from pathlib import Path
import sys

import bpy
from mathutils import Vector

# These accent groups consist of arrows, dashed marks, or thin guides.
# Their silhouettes would consume the colored marks at ribbon scale.
GUIDE_ACCENTS = {
    'extrude', 'revolve', 'sweep', 'loft', 'cut', 'sphere', 'split_faces', 'iso',
    'view_hidden', 'place', 'replace', 'adaptive', 'free_move', 'free_rotate',
    'move', 'create_part', 'dof', 'c3d_parallel', 'c3d_tangent', 'sm_flat',
    'sm_adjacent', 'sm_inside', 'sm_perforation', 'sm_perforation_straight',
    'sm_perforation_trapezoid', 'frame_insert', 'frame_change',
    'frame_lengthen', 'frame_refresh', 'frame_analysis', 'frame_untreat',
}


def linear_rgb(value):
    channels = [int(value[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    return tuple(c / 12.92 if c <= .04045 else ((c + .055) / 1.055) ** 2.4 for c in channels)


def studio():
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    scene = bpy.context.scene
    scene.render.engine = 'BLENDER_EEVEE'
    scene.eevee.taa_render_samples = 64
    scene.render.resolution_x = scene.render.resolution_y = 256
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = 'PNG'
    scene.render.image_settings.color_mode = 'RGBA'
    scene.render.image_settings.color_depth = '8'
    scene.render.film_transparent = True
    scene.render.use_freestyle = True
    scene.view_settings.view_transform = 'Standard'
    scene.view_settings.look = 'None'
    scene.view_settings.exposure = 0.0
    scene.world.use_nodes = True
    scene.world.node_tree.nodes.get('Background').inputs['Strength'].default_value = .6

    camera = bpy.data.objects.new('Isometric camera', bpy.data.cameras.new('Isometric'))
    scene.collection.objects.link(camera)
    camera.rotation_euler = (math.radians(54.7356103), 0, math.radians(45))
    camera.location = camera.rotation_euler.to_matrix() @ Vector((0, 0, 30))
    camera.data.type = 'ORTHO'
    # Isometric vertical projection of a centred 10 mm cube is 10 sqrt(8/3).
    camera.data.ortho_scale = 10 * math.sqrt(8 / 3) / .84
    scene.camera = camera

    sun = bpy.data.objects.new('Upper-left sun', bpy.data.lights.new('Sun', 'SUN'))
    scene.collection.objects.link(sun)
    sun.rotation_euler = Vector((-1.7, 6.5, -10)).to_track_quat('-Z', 'Y').to_euler()
    sun.data.energy = 3
    sun.data.use_shadow = False

    outlined = bpy.data.collections.new('Outlined solid groups')
    scene.collection.children.link(outlined)
    freestyle = scene.view_layers[0].freestyle_settings
    freestyle.crease_angle = math.radians(120)
    lines = freestyle.linesets[0]
    lines.select_by_collection = True
    lines.collection = outlined
    lines.collection_negation = 'INCLUSIVE'
    lines.select_silhouette = True
    lines.select_border = True
    lines.select_crease = True
    lines.linestyle.thickness = 6
    scene.render.line_thickness_mode = 'ABSOLUTE'
    return scene, outlined, lines.linestyle


def material(name, color, alpha=1.0, emission=False):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    rgb = linear_rgb(color)
    if emission:
        emit = nodes.new('ShaderNodeEmission')
        emit.inputs['Color'].default_value = (*rgb, 1)
        mat.node_tree.links.new(emit.outputs['Emission'], nodes.get('Material Output').inputs['Surface'])
    else:
        shade = nodes.get('Principled BSDF')
        shade.inputs['Base Color'].default_value = (*rgb, 1)
        shade.inputs['Roughness'].default_value = .55
        shade.inputs['Metallic'].default_value = 0
        shade.inputs['Alpha'].default_value = alpha
        if alpha < 1:
            mat.surface_render_method = 'DITHERED'
    return mat


def import_group(path, name, outlined, materials):
    bpy.ops.wm.stl_import(filepath=str(path))
    obj = bpy.context.object
    group = path.stem
    obj.name = group
    obj.data.materials.append(materials[group])
    if group != 'line' and (group != 'accent' or name not in GUIDE_ACCENTS):
        for collection in list(obj.users_collection):
            collection.objects.unlink(obj)
        outlined.objects.link(obj)
    if group == 'body' and name == 'xray':
        obj.data.materials[0] = materials['xray']
    if group == 'body' and name == 'cut_face':
        obj.data.materials.append(materials['ghost'])
        for face in obj.data.polygons:
            if face.center.z > .24186 * face.center.x + .071:
                face.material_index = 1
    if name in {'cylinder', 'sphere', 'hole', 'fillet', 'shell', 'sweep', 'loft', 'c3d_tangent'}:
        for poly in obj.data.polygons:
            poly.use_smooth = True
        obj.data.set_sharp_from_angle(angle=math.radians(33))
    return obj


def render_hidden_edges(scene, objects, path):
    # The real hidden-edge geometry has to stay visible through the opaque
    # model. Render it separately, retaining its isometric projection.
    import numpy as np

    accent = next(obj for obj in objects if obj.name == 'accent')
    accent.hide_render = True
    scene.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)
    accent.hide_render = False
    for obj in objects:
        obj.hide_render = obj != accent
    scene.render.use_freestyle = False
    overlay_path = path.with_name(path.stem + '.overlay.png')
    scene.render.filepath = str(overlay_path)
    bpy.ops.render.render(write_still=True)

    base = bpy.data.images.load(str(path), check_existing=False)
    overlay = bpy.data.images.load(str(overlay_path), check_existing=False)
    lower = np.empty(256 * 256 * 4, dtype=np.float32)
    upper = np.empty_like(lower)
    base.pixels.foreach_get(lower)
    overlay.pixels.foreach_get(upper)
    lower = lower.reshape(-1, 4)
    upper = upper.reshape(-1, 4)
    top_alpha = upper[:, 3:4]
    bottom_alpha = lower[:, 3:4] * (1 - top_alpha)
    alpha = top_alpha + bottom_alpha
    rgb = np.divide(upper[:, :3] * top_alpha + lower[:, :3] * bottom_alpha,
                    alpha, out=np.zeros_like(lower[:, :3]), where=alpha > 0)
    lower[:, :3], lower[:, 3:4] = rgb, alpha
    base.pixels.foreach_set(lower.ravel())
    base.save()
    bpy.data.images.remove(base)
    bpy.data.images.remove(overlay)
    overlay_path.unlink()
    for obj in objects:
        obj.hide_render = False
    scene.render.use_freestyle = True


def render(mesh_dir, output):
    scene, outlined, outline = studio()
    mats = {name: material(name, color, alpha) for name, color, alpha in (
        ('body', '9aa4ae', 1), ('accent', 'c8901a', 1),
        ('xray', '9aa4ae', .30), ('ghost', '9aa4ae', .25))}
    mats['line'] = material('Line', '2b3540', emission=True)
    light = mats['line'].node_tree.nodes.get('Emission')
    names = json.loads((mesh_dir / 'manifest.json').read_text(encoding='utf-8'))
    output.mkdir(parents=True, exist_ok=True)
    for name in names:
        objects = [import_group(path, name, outlined, mats)
                   for path in sorted((mesh_dir / name).glob('*.stl'))]
        if not objects:
            raise ValueError(f'{name} has no STL geometry')
        scene.render.use_freestyle = name != 'shaded' and bool(outlined.objects)
        for suffix, color in (('', '2b3540'), ('.dark', 'd5dee8')):
            rgb = linear_rgb(color)
            outline.color = rgb
            light.inputs['Color'].default_value = (*rgb, 1)
            path = output / f'{name}{suffix}.png'
            if name == 'view_hidden':
                render_hidden_edges(scene, objects, path)
            else:
                scene.render.filepath = str(path)
                bpy.ops.render.render(write_still=True)
        for obj in objects:
            mesh = obj.data
            bpy.data.objects.remove(obj, do_unlink=True)
            bpy.data.meshes.remove(mesh)


if __name__ == '__main__':
    argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mesh_dir', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args(argv)
    repo = Path(__file__).resolve().parents[2]
    render(args.mesh_dir.resolve(), (args.output or repo / 'datum/ui/assets/icons').resolve())
