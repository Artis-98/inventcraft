"""Build the native walking excavator: parts, subassemblies, the cab's
frame, cylinders sized from the skeleton, poses and the icLogic controls.

    .venv/Scripts/python.exe examples/build_walking_excavator.py
"""
from pathlib import Path
import argparse
import json
import math
import os
import shutil
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('DATUM_CONFIG_DIR', str(ROOT / 'build/walking-qa/config'))
os.environ.setdefault('DATUM_DOCUMENTS', str(ROOT / 'build/walking-qa/documents'))
os.environ.setdefault('DATUM_SETTINGS_ORG', 'WalkingExcavatorBuild')
from examples.walking_excavator.common import Library, OUT, PARTS, ALONG_Y
from examples.walking_excavator import motion as M, controls
from datum.core.assembly import AssemblyDocument
from datum.core.constraints3d import Placement

SUBS = OUT / 'subassemblies'
ANGLE_WORDS = ('angle', 'curl', 'steer', 'spread', 'lift', 'slew', 'spin', 'tilt',
               'rotation', 'ankle', 'pitch')


def base_parameters():
    p = dict(ride_height=1500.0, chassis_pitch=0.0, slew=0.0, boom_angle=40.0,
             dipper_angle=-80.0, bucket_curl=40.0, attachment_tilt=0.0,
             attachment_rotation=0.0, wheel_spin=0.0)
    for side in M.SIDES:
        p.update({'spread_' + side: 45.0, 'lift_' + side: 10.0,
                  'steer_' + side: 0.0, 'spin_' + side: 0.0})
    return p


def grounded(p):
    """Ride height that sets the lowest wheel on the ground plane."""
    f = M.skeleton(dict(p, ride_height=0.0))
    low = min(M.wheel_centre(f, s)[2] for s in M.SIDES)
    return dict(p, ride_height=round(M.TIRE_RADIUS - low, 3))


def poses():
    level = grounded(base_parameters())
    transport = dict(level, boom_angle=62.0, dipper_angle=-112.0, bucket_curl=40.0)
    for s in M.SIDES:
        transport.update({'spread_' + s: 32.0, 'lift_' + s: 4.0})
    transport = grounded(transport)
    reach = grounded(dict(level, slew=-15.0, boom_angle=22.0, dipper_angle=-45.0, bucket_curl=10.0))
    spider = dict(level, slew=25.0, boom_angle=45.0, dipper_angle=-85.0, bucket_curl=55.0,
                  lift_FL=4.0, lift_FR=16.0, lift_RL=22.0, lift_RR=8.0,
                  steer_FL=12.0, steer_FR=-10.0, steer_RL=-8.0, steer_RR=10.0,
                  spread_FL=40.0, spread_FR=55.0, spread_RL=50.0, spread_RR=38.0)
    spider = grounded(spider)
    heels = dict(level, slew=10.0, boom_angle=35.0, dipper_angle=-75.0, bucket_curl=45.0)
    for s in M.SIDES:
        heels['lift_' + s] = 52.0
    heels = grounded(heels)
    hero = dict(level, slew=-25.0, boom_angle=30.0, dipper_angle=-70.0, bucket_curl=35.0,
                attachment_tilt=12.0, lift_FL=18.0, lift_FR=18.0, lift_RL=10.0, lift_RR=10.0,
                spread_FL=40.0, spread_FR=40.0, spread_RL=50.0, spread_RR=50.0,
                steer_FL=12.0, steer_FR=12.0)
    hero = grounded(hero)
    return dict(Level=level, Transport=transport, Reach=reach, Spider=spider,
                Heels=heels, Hero=hero)


# ------------------------------------------------------------- cylinders
RAMS = {
    # key: (bore, rod, eye radius, pin, eye width, controls that move it)
    'leg': (55.0, 32.0, 45.0, 25.0, 60.0),
    'spread': (35.0, 20.0, 35.0, 20.0, 40.0),
    'steer': (25.0, 14.0, 20.0, 12.0, 30.0),
    'boom': (65.0, 38.0, 55.0, 30.0, 70.0),
    'dipper': (60.0, 35.0, 55.0, 30.0, 70.0, 110.0),
    'bucket': (50.0, 30.0, 45.0, 30.0, 60.0),
}


def spans():
    """Each cylinder's shortest and longest span over its controls."""
    ranges = {k: (lo, hi) for sets in controls.control_sets().values()
              for (_, k, lo, hi, _, _) in sets}
    base = base_parameters()
    moving = {'leg': ['lift_FL'], 'spread': ['spread_FL'], 'steer': ['steer_FL'], 'boom': ['boom_angle'],
              'dipper': ['dipper_angle'], 'bucket': ['bucket_curl']}
    out = {}
    for key, params in moving.items():
        name = {'leg': 'leg_FL', 'spread': 'spread_FL', 'steer': 'steer_FL'}.get(key, key)
        values = []
        for side in (M.SIDES if key in ('leg', 'spread', 'steer') else ('',)):
            for k in range(41):
                p = dict(base)
                for q in params:
                    lo, hi = ranges[q]
                    qq = q.replace('FL', side) if side else q
                    p[qq] = lo + (hi - lo) * k / 40
                f = M.skeleton(p)
                n = name.replace('FL', side) if side else name
                values.append(M.norm(M.sub(f[n + '_a'], f[n + '_b'])))
        out[key] = (min(values), max(values))
    return out


def build_rams(lib):
    from examples.walking_excavator.rams import ram
    fam = {}
    for key, (lo, hi) in spans().items():
        bore, rod, eye_r, pin, eye_w = RAMS[key][:5]
        reach = RAMS[key][5] if len(RAMS[key]) > 5 else None
        closed = math.floor(lo - 8)
        stroke = math.ceil(hi - lo + 16)
        name = {'leg': 'Leg lift ram', 'spread': 'Leg spread ram', 'steer': 'Steering ram', 'boom': 'Boom ram',
                'dipper': 'Dipper ram', 'bucket': 'Bucket ram'}[key]
        fam[key] = ram(lib, name, closed, stroke, bore, rod, eye_r, pin, eye_w, base_reach=reach)
        fam[key]['span'] = [lo, hi]
    return fam


# ---------------------------------------------------------- assemblies
def subassembly(name, items):
    ass = AssemblyDocument()
    # one part grounded, as in Inventor: the first, which the others are
    # placed from; nothing constrains them, so nothing moves them
    for k, item in enumerate(items):
        occ = ass.place(item['part'], item['name'])
        occ.placement = Placement(item['pos'], item['rot'])
        occ.grounded = k == 0
    path = ass.save(str(SUBS / name))
    return path, ass


def cab_frame(upper_path, info):
    """Insert Frame on the cab skeleton: RHS pillars and rails, a bent
    roof rail and its posts."""
    from datum.core import frames
    ass = AssemblyDocument.load(upper_path)
    skel = next(o for o in ass.occurrences if o.ref.label == 'Cab frame skeleton')
    sketches = info['sketches']
    frame_occ = None
    made = []
    for name, (sid, ids) in sketches.items():
        if name.startswith('Roof rail'):
            continue
        doc, frame_occ, problems = frames.insert(ass, skel, sid, ids, 'din-en-10219-2-square',
                                                 '80 x 80 x 4', frame_occurrence=frame_occ,
                                                 material='Steel, Mild')
        made += problems
    sid, ids = sketches['Roof rail']
    doc, frame_occ, problems = frames.insert(ass, skel, sid, ids, 'en-10305-4-hydraulic', '30x3',
                                             merge=True, frame_occurrence=frame_occ, bend_radius=90,
                                             material='Steel, Stainless 304')
    made += problems
    for name, (sid, ids) in sketches.items():
        if name.startswith('Roof rail posts'):
            doc, frame_occ, problems = frames.insert(ass, skel, sid, ids, 'en-10219-chs', 'CHS33.7x3.2',
                                                     frame_occurrence=frame_occ, material='Steel, Stainless 304')
            made += problems
    ass.save(upper_path)
    if made:
        print('frame:', made)
    # members come out in their material's own finish; the cab's frame is
    # painted, the rail is bright steel
    from datum.core.document import Document
    from examples.walking_excavator.common import DARK, CHROME
    for part in Path(doc.path).parent.glob('*.icpart'):
        member = Document.load(str(part))
        member.appearance = CHROME if ('CHS' in part.stem or '30x3' in part.stem) else DARK
        member.save(str(part))
    return doc


GROUP_NAMES = {'chassis': 'Chassis', 'upper': 'Upper', 'boom': 'Boom', 'dipper': 'Dipper',
               'attachment': 'Tiltrotator Coupler', 'tilt': 'Tiltrotator', 'bucket': 'Bucket',
               'hip': 'Hip Bracket', 'leg': 'Leg Weldment', 'link': 'Leg Link', 'carrier': 'Wheel Carrier',
               'steer': 'Steering Knuckle', 'wheel': 'Wheel and Tyre',
               'carrier_rh': 'Wheel Carrier RH', 'steer_rh': 'Steering Knuckle RH',
               'wheel_rh': 'Wheel and Tyre RH'}


def build(reuse=False):
    from examples.walking_excavator import chassis, legs, arm, upper
    if not reuse:
        for folder in (PARTS, SUBS, OUT / 'poses'):
            if folder.exists():
                shutil.rmtree(folder)
        for old in OUT.glob('Walking Excavator*'):
            if old.is_dir():
                shutil.rmtree(old)
    lib = Library()
    meta = {}
    chassis.build(lib)
    meta['legs'] = legs.build(lib)
    arm.boom(lib)
    arm.dipper(lib)
    link_parts = arm.links(lib)
    arm.attachment(lib)
    arm.rotator(lib)
    arm.bucket(lib)
    meta['upper'] = upper.build(lib)
    rams = build_rams(lib)
    groups = {}
    for item in lib.placements:
        groups.setdefault(item['group'], []).append(item)
    SUBS.mkdir(parents=True, exist_ok=True)
    paths = {}
    for group, items in groups.items():
        path, _ = subassembly(GROUP_NAMES[group], items)
        paths[group] = path
    cab_frame(paths['upper'], meta['upper'])
    recipes = []
    rec = lambda label, parent, part, pos=(0, 0, 0), rot=(0, 0, 0): recipes.append(dict(
        kind='frame', label=label, parent=parent, part=str(part), pos=[float(v) for v in pos],
        rot=[float(v) for v in rot]))
    for group in ('chassis', 'upper', 'boom', 'dipper', 'attachment', 'tilt', 'bucket'):
        rec(GROUP_NAMES[group], group, paths[group])
    for side in M.SIDES:
        rec(side + ' hip bracket', 'hip_' + side, paths['hip'])
        rec(side + ' leg', 'leg_' + side, paths['leg'])
        rec(side + ' leg link', 'link_' + side, paths['link'])
        # left-hand wheel ends for a wheel on the leg's +Y side, right-hand
        # (mirror image) parts for -Y
        hand = '' if M.wheel_side(side) > 0 else '_rh'
        rec(side + ' wheel carrier', 'carrier_' + side, paths['carrier' + hand])
        rec(side + ' steering knuckle', 'steer_' + side, paths['steer' + hand])
        rec(side + ' wheel', 'wheel_' + side, paths['wheel' + hand])
        lug, spin = meta['legs']['spread_lug'], meta['legs']['spread_pin']
        for name, part, pos, rot in legs.place_spread_lugs(lib, M.handed(side), lug, spin):
            rec('%s spread lug %s' % (side, name), 'hip_' + side, part, pos, rot)
    # bucket linkage: two pairs of links and the pins and sleeves between
    for y, label in ((128.0, 'L'), (-112.0, 'R')):
        rec('Idler link ' + label, 'link_idler', link_parts['Idler link'], (0, y, 0))
    for y, label in ((146.0, 'L'), (-130.0, 'R')):
        rec('Bucket link ' + label, 'link_bucket', link_parts['Bucket link'], (0, y, 0))
    rec('Linkage joint pin', 'link_idler', link_parts['joint pin'], (M.IDLER_LINK, 0, 0), ALONG_Y)
    rec('Bucket link pin', 'link_bucket', link_parts['ear pin'], (M.BUCKET_LINK, 0, 0), ALONG_Y)
    rec('Joint spacer L', 'link_idler', link_parts['spacer'], (M.IDLER_LINK, 34, 0), ALONG_Y)
    rec('Joint spacer R', 'link_idler', link_parts['spacer'], (M.IDLER_LINK, -110, 0), ALONG_Y)
    for key in ['boom', 'dipper', 'bucket'] + ['%s_%s' % (k, s) for k in ('leg', 'spread', 'steer') for s in M.SIDES]:
        family = rams[key.split('_')[0]]
        axis = {'leg': 'leg_%s_axis' % key[-2:], 'spread': 'chassis_z',
                'steer': 'chassis_z'}.get(key.split('_')[0], 'upper_axis')
        for part, reverse in (('barrel', False), ('gland', False), ('rod', True)):
            recipes.append(dict(kind='ram', label='%s ram %s' % (key, part), part=family[part],
                                a=key + '_a', b=key + '_b', axis=axis, reverse=reverse,
                                pos=[0, 0, 0], rot=[0, 0, 0]))
    serial = [{**r, 'part': str(Path(r['part']).resolve().relative_to(OUT.resolve()))} for r in recipes]
    (OUT / 'assembly-recipes.json').write_text(json.dumps(serial, indent=1), encoding='utf-8')
    (OUT / 'ram-families.json').write_text(json.dumps(
        {k: {kk: vv for kk, vv in v.items()} for k, v in rams.items()}, indent=1), encoding='utf-8')
    (OUT / 'placements.json').write_text(json.dumps(lib.placements, indent=1), encoding='utf-8')
    return recipes


def assembly(name, p, recipes):
    ass = AssemblyDocument()
    # only the chassis is grounded; the icLogic rule places everything else
    for recipe in recipes:
        occ = ass.place(recipe['part'], recipe['label'])
        occ.grounded = recipe['label'] == 'Chassis'
    for key, value in p.items():
        ass.params.add(key, str(value), 'deg' if any(k in key for k in ANGLE_WORDS) else 'mm')
    M.apply_motion(ass, p, recipes)
    source = Path(M.__file__).read_text(encoding='utf-8-sig').replace('import math\n', '', 1)
    rule = ass.rules.add('Articulate walking excavator', source +
                         '\np = {name: params[name] for name in ' + repr(list(p)) + '}\n' +
                         'recipes = ' + repr([{k: v for k, v in r.items() if k != 'part'} for r in recipes]) +
                         '\napply_motion(doc, p, recipes)\n_changes.append("Walking excavator articulated")\n')
    rule.button = True
    rule.on_rebuild = True
    rule.watch = list(p)
    controls.install(ass)
    ass.properties.update({'Title': 'InventCraft Walking Excavator',
                           'Description': 'Articulated four wheel walking excavator, a demonstration',
                           'Revision': 'B',
                           'EngineeringStatus': 'Demonstration; structure and hydraulics not verified'})
    return ass.save(str(OUT / name))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pose', choices=list(poses()), default='Hero')
    parser.add_argument('--reuse-parts', action='store_true')
    args = parser.parse_args()
    if args.reuse_parts:
        recipes = json.loads((OUT / 'assembly-recipes.json').read_text(encoding='utf-8'))
        for r in recipes:
            r['part'] = str(OUT / r['part'])
    else:
        recipes = build()
    (OUT / 'poses').mkdir(exist_ok=True)
    for name, p in poses().items():
        assembly('poses/' + name, p, recipes)
        print('Saved pose', name, flush=True)
    path = assembly('Walking Excavator', poses()[args.pose], recipes)
    for old in OUT.rglob('OldVersions'):
        shutil.rmtree(old, ignore_errors=True)
    (OUT / 'pose-parameters.json').write_text(json.dumps(poses(), indent=1), encoding='utf-8')
    print('Main assembly:', path, flush=True)


if __name__ == '__main__':
    main()
