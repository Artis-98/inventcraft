"""Render the exported excavator in Blender, Cycles, on a transparent
background with its shadow, for the splash screen.

    "C:/Program Files/Blender Foundation/Blender 5.2/blender.exe" --background --factory-startup
        --python examples/walking_excavator/blender_render.py -- [width] [samples]
"""
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector

HERE = Path(__file__).resolve().parent
DEST = HERE.parents[0] / 'walking-excavator/renders/blender'
args = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
WIDTH = int(args[0]) if args else 3000
SAMPLES = int(args[1]) if len(args) > 1 else 256
scene_info = json.loads((DEST / 'scene.json').read_text(encoding='utf-8'))

for o in list(bpy.data.objects):
    bpy.data.objects.remove(o, do_unlink=True)
scene = bpy.context.scene
root = scene.collection

bpy.ops.wm.obj_import(filepath=scene_info['obj'], forward_axis='Y', up_axis='Z')
for o in bpy.context.selected_objects:
    for poly in o.data.polygons:
        poly.use_smooth = True


def paint(mat, colour, rough, metal=0.0, coat=0.0):
    mat.use_nodes = True
    b = mat.node_tree.nodes.get('Principled BSDF')
    r, g, bl = (int(colour[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    # sRGB to linear, as the shader wants it
    lin = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in (r, g, bl)]
    b.inputs['Base Color'].default_value = (*lin, 1.0)
    b.inputs['Roughness'].default_value = rough
    b.inputs['Metallic'].default_value = metal
    if 'Coat Weight' in b.inputs:
        b.inputs['Coat Weight'].default_value = coat
        b.inputs['Coat Roughness'].default_value = 0.08


looks = {
    'cf5b301': ('f5b301', 0.32, 0.0, 0.6),     # machine yellow
    'ce8471b': ('e8471b', 0.35, 0.0, 0.5),     # signal orange
    'c2b3036': ('2b3036', 0.45, 0.0, 0.3),     # graphite
    'c1d1f22': ('1d1f22', 0.82, 0.0, 0.0),     # rubber
    'cb8bec4': ('b8bec4', 0.30, 1.0, 0.0),     # machined steel
    'cdde2e6': ('e4e8ec', 0.06, 1.0, 0.0),     # chrome rods
    'ca07c45': ('a07c45', 0.35, 1.0, 0.0),     # bronze
}
for mat in bpy.data.materials:
    key = mat.name.split('.')[0]
    if key in looks:
        paint(mat, *looks[key])
    elif key == 'glass':
        mat.use_nodes = True
        b = mat.node_tree.nodes.get('Principled BSDF')
        b.inputs['Base Color'].default_value = (0.75, 0.86, 0.9, 1)
        b.inputs['Roughness'].default_value = 0.0
        b.inputs['Transmission Weight'].default_value = 1.0
        b.inputs['IOR'].default_value = 1.5

# ground: catches the shadow only
bpy.ops.mesh.primitive_plane_add(size=60, location=(0, 0, scene_info['ground_z']))
ground = bpy.context.active_object
ground.is_shadow_catcher = True

# camera from the front-left, the whole machine in frame with room for the panel
target = Vector(scene_info['target'])
direction = Vector(scene_info['direction'])
cam_data = bpy.data.cameras.new('Camera')
cam_data.lens = 60
cam = bpy.data.objects.new('Camera', cam_data)
root.objects.link(cam)
distance = scene_info['radius'] / math.sin(math.atan(18 / cam_data.lens)) * 1.3
target = target + Vector((0, 0, -0.55))
cam.location = target + direction * distance
cam.rotation_euler = (target - cam.location).to_track_quat('-Z', 'Y').to_euler()
scene.camera = cam


def area(name, loc, power, size, colour=(1, 1, 1)):
    d = bpy.data.lights.new(name, 'AREA')
    d.energy = power
    d.size = size
    d.color = colour
    o = bpy.data.objects.new(name, d)
    root.objects.link(o)
    o.location = target + Vector(loc)
    o.rotation_euler = (target - o.location).to_track_quat('-Z', 'Y').to_euler()
    return o


area('Key', (6, 5, 7), 3200, 5)
area('Fill', (4, -7, 3), 900, 7, (0.9, 0.95, 1.0))
area('Rim', (-7, 2, 6), 2600, 4)
world = bpy.data.worlds.new('World')
scene.world = world
world.use_nodes = True
bg = world.node_tree.nodes['Background']
bg.inputs['Color'].default_value = (0.8, 0.84, 0.9, 1)
bg.inputs['Strength'].default_value = 0.25

scene.render.engine = 'CYCLES'
scene.cycles.samples = SAMPLES
scene.cycles.use_denoising = True
prefs = bpy.context.preferences.addons['cycles'].preferences
for kind in ('OPTIX', 'CUDA'):
    try:
        prefs.compute_device_type = kind
        prefs.get_devices()
        if any(d.type == kind for d in prefs.devices):
            for d in prefs.devices:
                d.use = d.type == kind
            scene.cycles.device = 'GPU'
            print('rendering on', kind)
            break
    except Exception:
        continue
scene.render.film_transparent = True
scene.view_settings.view_transform = 'Standard'
scene.view_settings.exposure = -0.2
scene.render.resolution_x = WIDTH
scene.render.resolution_y = int(WIDTH * 0.6)
scene.render.image_settings.file_format = 'PNG'
scene.render.image_settings.color_mode = 'RGBA'
scene.render.filepath = str(DEST / 'excavator-splash.png')
bpy.ops.wm.save_as_mainfile(filepath=str(DEST / 'excavator-splash.blend'))
bpy.ops.render.render(write_still=True)
print('rendered', scene.render.filepath)
