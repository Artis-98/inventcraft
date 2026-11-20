"""The master skeleton: every joint centre and cylinder eye, in pure math.

The same source runs from the build scripts and, embedded, as the
assembly's own icLogic rule, so it imports nothing but math and keeps its
dimensions here.  Millimetres and degrees; Z up, +X forward, +Y left.

Frames, each a (position, rotation) pair:
  chassis   centre of the chassis weldment, pitched about Y
  upper     slew bearing top centre, turned by slew
  hip_XX    a leg's vertical swivel axis, turned by spread
  leg_XX    the leg's lift pin, turned by lift (positive drops the tip)
  link_XX   the small bone above the leg, turned by the same lift
  carrier_XX  the leg's tip; it moves with the parallelogram and never turns
  steer_XX  the wheel fork, turned about the vertical kingpin
  wheel_XX  the wheel, turned about its axle
  boom, dipper, attachment, bucket  the digging arm
"""
import math

# chassis and upper
HIP = {'FL': (820.0, 480.0), 'FR': (820.0, -480.0),
       'RL': (-820.0, 480.0), 'RR': (-820.0, -480.0)}
UPPER_Z = 600.0            # slew bearing top above the chassis centre
# leg
HIP_REACH = 260.0          # swivel axis to lift pin
LEG_LENGTH = 1500.0        # lift pin to distal pin
WHEEL_Y = 640.0            # the wheel's middle, beside the leg's tip
SCRUB = 130.0              # the kingpin, inside the rim, this far in from it
WHEEL_DROP = 0.0           # the axle is on the distal pin's line
TIRE_RADIUS = 700.0
STEER_ARM = 120.0          # kingpin to the steering arm's pin
STEER_BASE = (LEG_LENGTH + 120.0, 207.0, 245.0)   # carrier, steering ram base
LINK_OFFSET = (211.0, 0.0, 453.0)    # small bone's pins above the big bone's
LIFT_BASE = (100.0, 0.0, 232.0)      # big bone, lift ram base eye
LIFT_ROD = (1350.0, 0.0, -152.0)     # small bone, lift ram rod eye
SPREAD_BASE_X = 800.0                # chassis, spread ram base eye
SPREAD_BASE_Y = 60.0
SPREAD_ROD = (220.0, 200.0, 90.0)    # hip bracket; y is handed
SPREAD_Z = 90.0                      # both spread ram eyes, above the pins
# digging arm
BOOM_FOOT = (650.0, -300.0, 420.0)   # upper
BOOM_LENGTH = 2600.0                 # foot pin to dipper pin
BOOM_KNEE = (1450.0, 300.0)          # boom centreline knee, boom frame
BOOM_RAM_BASE = (1000.0, -300.0, 150.0)  # upper
BOOM_RAM_ROD = (1250.0, 0.0, -40.0)      # boom
DIPPER_RAM_BASE = (1350.0, 0.0, 720.0)   # boom
DIPPER_RAM_ROD = (-330.0, 0.0, 200.0)    # dipper heel
DIPPER_LENGTH = 1700.0               # dipper pin to bucket pin
BUCKET_RAM_BASE = (520.0, 0.0, 335.0)    # dipper
IDLER_PIVOT = (1430.0, 0.0, 40.0)       # dipper
BUCKET_EAR = (60.0, 0.0, 230.0)           # attachment
IDLER_LINK = 320.0
BUCKET_LINK = 300.0
ROTATOR_DROP = 300.0                 # attachment pin to tilt axis

SIDES = ('FL', 'FR', 'RL', 'RR')


def add(a, b): return [a[i] + b[i] for i in range(3)]
def sub(a, b): return [a[i] - b[i] for i in range(3)]
def scale(a, k): return [v * k for v in a]
def dot(a, b): return sum(a[i] * b[i] for i in range(3))
def cross(a, b): return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2],
                         a[0] * b[1] - a[1] * b[0]]
def norm(a): return math.sqrt(dot(a, a))


def unit(a):
    n = norm(a)
    if n < 1e-10:
        raise ValueError('Coincident mechanism anchors')
    return scale(a, 1 / n)


def identity(): return [[1., 0., 0.], [0., 1., 0.], [0., 0., 1.]]
def mv(m, p): return [dot(row, p) for row in m]


def mm(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)]
            for i in range(3)]


def axisrot(axis, angle):
    x, y, z = unit(axis)
    c = math.cos(angle)
    s = math.sin(angle)
    t = 1 - c
    return [[t * x * x + c, t * x * y - s * z, t * x * z + s * y],
            [t * x * y + s * z, t * y * y + c, t * y * z - s * x],
            [t * x * z - s * y, t * y * z + s * x, t * z * z + c]]


def frame(pos=(0, 0, 0), axis=(0, 0, 1), degrees=0):
    return (list(pos), axisrot(axis, math.radians(degrees)))


def compose(a, b): return (add(a[0], mv(a[1], b[0])), mm(a[1], b[1]))
def point(f, p): return add(f[0], mv(f[1], p))


def around(p, axis, degrees):
    m = axisrot(axis, math.radians(degrees))
    return (sub(p, mv(m, p)), m)


def vector_rotation(v):
    angle = norm(v)
    return axisrot(scale(v, 1 / angle), angle) if angle > 1e-10 else identity()


def rotation_vector(m):
    angle = math.acos(max(-1, min(1, (m[0][0] + m[1][1] + m[2][2] - 1) / 2)))
    if angle < 1e-8:
        return [0., 0., 0.]
    if math.pi - angle < 1e-6:
        values = [math.sqrt(max(0, (m[i][i] + 1) / 2)) for i in range(3)]
        if m[0][1] < 0:
            values[1] = -values[1]
        if m[0][2] < 0:
            values[2] = -values[2]
        return scale(unit(values), angle)
    return scale([m[2][1] - m[1][2], m[0][2] - m[2][0], m[1][0] - m[0][1]],
                 angle / (2 * math.sin(angle)))


def aimed(a, b, normal=(0, 1, 0)):
    """A frame at ``a`` with Z towards ``b`` and X along the pin axis."""
    z = unit(sub(b, a))
    x = list(normal)
    if abs(dot(unit(x), z)) > .98:
        x = [1, 0, 0]
    y = unit(cross(z, x))
    x = unit(cross(y, z))
    return (list(a), [[x[i], y[i], z[i]] for i in range(3)])


def linkage(a, b, r, s, normal, above):
    """The joint of two links, lengths r from a and s from b, on the side
    of a-b that ``above`` points to: a four-bar closed by circles."""
    distance = norm(sub(b, a))
    if not abs(r - s) + 1e-6 < distance < r + s - 1e-6:
        raise ValueError('Bucket linkage cannot close: %.1f' % distance)
    e = unit(sub(b, a))
    side = unit(cross(normal, e))
    u = (r * r - s * s + distance * distance) / (2 * distance)
    h = math.sqrt(max(0, r * r - u * u))
    choices = [add(add(a, scale(e, u)), scale(side, h * sign))
               for sign in (-1, 1)]
    return max(choices, key=lambda q: dot(sub(q, a), above))


def hip_yaw(side, spread):
    front = side[0] == 'F'
    left = side[1] == 'L'
    yaw = spread if front else 180 - spread
    return yaw if left else -yaw


def handed(side):
    """+1 when the spread ram works on the bracket's +Y side."""
    return 1 if side in ('FR', 'RL') else -1


def wheel_side(side):
    """+1 when the wheel is on the leg's +Y side: always outboard."""
    return -handed(side)


def wheel_centre(f, side):
    return point(f['wheel_' + side], (LEG_LENGTH, wheel_side(side) * WHEEL_Y, 0))


def skeleton(p):
    f = {'world': frame(),
         'chassis': frame((0, 0, p['ride_height']), (0, 1, 0),
                          -p.get('chassis_pitch', 0))}
    f['chassis_z'] = mv(f['chassis'][1], [0, 0, 1])
    f['upper'] = compose(f['chassis'], frame((0, 0, UPPER_Z), (0, 0, 1),
                                             p['slew']))
    f['upper_axis'] = mv(f['upper'][1], [0, 1, 0])
    for side in SIDES:
        x, y = HIP[side]
        hip = compose(f['chassis'], frame((x, y, 0), (0, 0, 1),
                                          hip_yaw(side, p['spread_' + side])))
        # a parallelogram: the big bone and the small bone above it turn
        # together, so the carrier at their tips only ever moves, never
        # turns, and stays parallel to the chassis
        lift = math.radians(p['lift_' + side])
        leg = compose(hip, frame((HIP_REACH, 0, 0), (0, 1, 0), p['lift_' + side]))
        link = compose(hip, frame(add((HIP_REACH, 0, 0), LINK_OFFSET), (0, 1, 0),
                                  p['lift_' + side]))
        tip = [HIP_REACH + LEG_LENGTH * math.cos(lift) - LEG_LENGTH, 0.0,
               -LEG_LENGTH * math.sin(lift)]
        carrier = compose(hip, (tip, identity()))
        f['link_' + side] = link
        ws = wheel_side(side)
        steer = compose(carrier, around((LEG_LENGTH, ws * (WHEEL_Y - SCRUB), 0), (0, 0, 1),
                                        p['steer_' + side]))
        wheel = compose(steer, around((LEG_LENGTH, ws * WHEEL_Y, 0), (0, 1, 0),
                                      p['wheel_spin'] + p.get('spin_' + side, 0)))
        f['hip_' + side], f['leg_' + side] = hip, leg
        f['carrier_' + side], f['steer_' + side] = carrier, steer
        f['wheel_' + side] = wheel
        ky = WHEEL_Y - SCRUB
        bx, by, bz = STEER_BASE
        f['steer_%s_a' % side] = point(carrier, (bx, ws * by, bz))
        f['steer_%s_b' % side] = point(steer, (LEG_LENGTH + STEER_ARM, ws * ky, bz))
        f['leg_%s_axis' % side] = mv(hip[1], [0, 1, 0])
        f['leg_%s_a' % side] = point(leg, LIFT_BASE)
        f['leg_%s_b' % side] = point(link, LIFT_ROD)
        sx = 1 if side[0] == 'F' else -1
        sy = 1 if side[1] == 'L' else -1
        f['spread_%s_a' % side] = point(
            f['chassis'], (sx * SPREAD_BASE_X, sy * SPREAD_BASE_Y, SPREAD_Z))
        f['spread_%s_b' % side] = point(
            hip, (SPREAD_ROD[0], handed(side) * SPREAD_ROD[1], SPREAD_Z))
    f['boom'] = compose(f['upper'], frame(BOOM_FOOT, (0, 1, 0),
                                          -p['boom_angle']))
    f['dipper'] = compose(f['boom'], frame((BOOM_LENGTH, 0, 0), (0, 1, 0),
                                           -p['dipper_angle']))
    # curl turns the bucket in under the dipper, towards the machine
    f['attachment'] = compose(f['dipper'], frame((DIPPER_LENGTH, 0, 0),
                                                 (0, 1, 0), p['bucket_curl']))
    # the tiltrotator carries on along the attachment's X: it tilts sideways
    # about Z and turns the bucket about X
    tilt = compose(f['attachment'], frame((ROTATOR_DROP, 0, 0), (0, 0, 1),
                                          p['attachment_tilt']))
    f['tilt'] = tilt
    f['bucket'] = compose(tilt, frame((0, 0, 0), (1, 0, 0),
                                      p['attachment_rotation']))
    f['boom_a'] = point(f['upper'], BOOM_RAM_BASE)
    f['boom_b'] = point(f['boom'], BOOM_RAM_ROD)
    f['dipper_a'] = point(f['boom'], DIPPER_RAM_BASE)
    f['dipper_b'] = point(f['dipper'], DIPPER_RAM_ROD)
    f['bucket_a'] = point(f['dipper'], BUCKET_RAM_BASE)
    idler = point(f['dipper'], IDLER_PIVOT)
    ear = point(f['attachment'], BUCKET_EAR)
    f['idler'], f['ear'] = idler, ear
    # the joint sits on the dipper's top side, away from the bucket
    f['joint'] = linkage(idler, ear, IDLER_LINK, BUCKET_LINK,
                         f['upper_axis'], mv(f['dipper'][1], [0, 0, 1]))
    f['bucket_b'] = f['joint']
    f['link_idler'] = aimed_x(idler, f['joint'], f['upper_axis'])
    f['link_bucket'] = aimed_x(f['joint'], ear, f['upper_axis'])
    return f


def aimed_x(a, b, normal):
    """A frame at ``a`` with X towards ``b`` and Y along ``normal``."""
    x = unit(sub(b, a))
    y = list(normal)
    z = unit(cross(x, y))
    y = unit(cross(z, x))
    return (list(a), [[x[i], y[i], z[i]] for i in range(3)])


def recipe_frame(recipe, f):
    if recipe['kind'] == 'frame':
        parent = f[recipe['parent']]
    elif recipe['kind'] == 'ram':
        a, b = f[recipe['a']], f[recipe['b']]
        axis = f[recipe['axis']]
        parent = aimed(b, a, axis) if recipe.get('reverse') else aimed(a, b, axis)
    else:
        raise ValueError(recipe['kind'])
    local = (recipe.get('pos', [0, 0, 0]),
             vector_rotation(recipe.get('rot', [0, 0, 0])))
    return compose(parent, local)


def apply_motion(doc, p, recipes):
    f = skeleton(p)
    mapping = {o.ref.label: o for o in doc.occurrences}
    for recipe in recipes:
        pose = recipe_frame(recipe, f)
        occurrence = mapping[recipe['label']]
        occurrence.placement.position = list(pose[0])
        occurrence.placement.rotation = rotation_vector(pose[1])
    return f
