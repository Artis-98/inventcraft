"""Beam analysis of a frame: how far it sags, how hard it works, how it rings.

The first step of static simulation (board #275), and the one a welded
frame needs most: every member is a beam along its skeleton line, joined
where the lines meet, standing on the supports it is given.  It is the
classic 3D frame method, the one every structural package is built on:
each member a 12 degree of freedom Euler-Bernoulli element (stretch, twist
and bend both ways), assembled and solved with numpy, nothing else
installed.

Units throughout are the ones an engineer reads a drawing in: millimetres,
newtons, megapascals (N/mm2), and tonnes for mass, which keeps every
equation consistent without a conversion in sight.

Loads:

* self weight, from each member's area and material density;
* point loads, a force at a joint;
* wind, from a speed: q = 1/2 rho v2 on the member's face, times a drag
  coefficient, square to the member.

What comes back: every joint's displacement, the biggest deflection,
each member's highest stress (axial plus bending at the outermost fibre,
a conservative sum), its use of the material's yield strength, the
reactions at the supports, and the frame's first natural frequencies.

A member is split into a few elements along its length, so the bending
moment between joints, where a self-weighted beam works hardest, is seen
and not only its ends.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

G = 9.81e3              # gravity, mm/s2
AIR = 1.25              # air density, kg/m3
FIXED = "fixed"         # every movement and turn held
PINNED = "pinned"       # moves held, turns free
SPLIT = 8               # elements per member, for the moments between joints


@dataclass
class Section:
    """What a profile gives a beam: area, how stiff it is each way, and how
    far its outermost fibres are from the middle.  In mm, mm2 and mm4,
    about the principal axes, ``angle`` (degrees) round from the
    profile's own X."""

    area: float
    iy: float               # about the member's local y
    iz: float               # about the member's local z
    j: float                # torsion constant
    cy: float = 0.0         # furthest fibre along y, for bending about z
    cz: float = 0.0         # furthest fibre along z, for bending about y
    angle: float = 0.0
    width: float = 0.0      # how wide the wind sees it, mm


@dataclass
class Material:
    e: float                # Young's modulus, MPa
    nu: float = 0.3
    density: float = 7.85   # g/cm3
    yield_strength: float = 235.0   # MPa

    @property
    def g(self) -> float:
        return self.e / (2.0 * (1.0 + self.nu))

    @property
    def rho(self) -> float:
        """Density in tonnes per mm3, the mass unit that goes with N, mm."""
        return self.density * 1e-9


@dataclass
class Member:
    """A beam from one joint to another."""

    a: int
    b: int
    section: Section
    material: Material
    # which way the section's y axis points, square to the member
    y_axis: Tuple[float, float, float] = (0.0, 0.0, 1.0)
    name: str = ""


@dataclass
class Load:
    node: int
    force: Tuple[float, float, float]                   # N
    moment: Tuple[float, float, float] = (0.0, 0.0, 0.0)  # N mm


@dataclass
class Model:
    nodes: List[Tuple[float, float, float]] = field(default_factory=list)
    members: List[Member] = field(default_factory=list)
    supports: Dict[int, str] = field(default_factory=dict)
    loads: List[Load] = field(default_factory=list)
    gravity: Tuple[float, float, float] = (0.0, 0.0, -1.0)
    self_weight: bool = True
    wind_speed: float = 0.0             # m/s
    wind_direction: Tuple[float, float, float] = (1.0, 0.0, 0.0)
    drag: float = 2.0                   # flat sided sections


@dataclass
class MemberResult:
    name: str
    stress: float = 0.0                 # MPa, the highest along it
    utilisation: float = 0.0            # stress / yield
    axial: float = 0.0                  # N, the largest, + is tension
    moment: float = 0.0                 # N mm, the largest bending


@dataclass
class Result:
    displacements: np.ndarray           # (nodes, 6)
    members: List[MemberResult]
    reactions: Dict[int, np.ndarray]
    frequencies: List[float]            # Hz
    max_deflection: float = 0.0         # mm
    max_node: int = -1
    max_stress: float = 0.0
    max_member: str = ""
    safety: float = math.inf
    error: str = ""


# ------------------------------------------------------------- sections

def section_of_face(face, length_hint: float = 0.0,
                    kind: str = "", dims: Optional[Dict[str, float]] = None
                    ) -> Section:
    """A profile face on XY made into a beam section.

    The area and bending stiffness come straight from the face.  Torsion
    has no such simple formula, so it is worked out the way a handbook
    does for the shape: a closed tube by Bredt's formula, an open angle as
    its thin legs, anything else by Saint-Venant's estimate.
    """
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps

    from . import kernel

    props = GProp_GProps()
    BRepGProp.SurfaceProperties_s(face, props)
    area = props.Mass()
    c = props.CentreOfMass()
    m = props.MatrixOfInertia()
    ixx = m.Value(1, 1)                 # about X: integral of y2
    iyy = m.Value(2, 2)                 # about Y: integral of x2
    ixy = -m.Value(1, 2)                # integral of x y
    # principal axes: round from X by theta
    mean = (ixx + iyy) / 2.0
    half = math.hypot((ixx - iyy) / 2.0, ixy)
    # a square or a round has no principal direction: any will do, and
    # the arc tangent of two rounding errors would pick one at random
    theta = (0.0 if half <= 1e-9 * mean
             else 0.5 * math.atan2(-2.0 * ixy, ixx - iyy))
    i1, i2 = mean + half, mean - half
    # which of the two belongs to the turned X
    cos2, sin2 = math.cos(2 * theta), math.sin(2 * theta)
    i_x = mean + (ixx - iyy) / 2.0 * cos2 - ixy * sin2
    if abs(i_x - i1) > abs(i_x - i2):
        i1, i2 = i2, i1
    # the furthest fibres, in the principal frame
    points = []
    for vertex in kernel.vertices(face):
        p = kernel.shape_centre(vertex)
        points.append((p[0] - c.X(), p[1] - c.Y()))
    try:
        from .frames import _samples
        points += [(x - c.X(), y - c.Y()) for x, y in _samples(face)]
    except Exception:
        pass
    ct, st = math.cos(theta), math.sin(theta)
    u = [x * ct + y * st for x, y in points] or [0.0]
    v = [-x * st + y * ct for x, y in points] or [0.0]
    dims = dims or {}
    if kind == "square_tube" and "b" in dims and "t" in dims:
        b, t = dims["b"], dims["t"]
        j = 4.0 * (b - t) ** 4 * t / (4.0 * (b - t))
    elif kind == "angle" and "b" in dims and "t" in dims:
        b, t = dims["b"], dims["t"]
        j = (2.0 * b - t) * t ** 3 / 3.0
    else:
        ip = ixx + iyy
        j = area ** 4 / (40.0 * ip) if ip > 0 else 0.0
    box = kernel.bounding_box(face)
    width = max(box[3] - box[0], box[4] - box[1])
    # the section's own X turned by theta is the member's local y: bending
    # about it is i1, and its outermost fibre is out along v
    return Section(area=area, iy=i1, iz=i2, j=j,
                   cy=max(abs(x) for x in u), cz=max(abs(x) for x in v),
                   angle=math.degrees(theta), width=width)


# ------------------------------------------------------------ elements

def _axes(a, b, y_hint) -> np.ndarray:
    """The member's local axes as rows: x along it, y and z across."""
    x = np.asarray(b, float) - np.asarray(a, float)
    length = np.linalg.norm(x)
    x = x / length
    y = np.asarray(y_hint, float)
    y = y - x * (y @ x)
    if np.linalg.norm(y) < 1e-9:
        y = np.array([0.0, 0.0, 1.0]) if abs(x[2]) < 0.9 \
            else np.array([1.0, 0.0, 0.0])
        y = y - x * (y @ x)
    y = y / np.linalg.norm(y)
    z = np.cross(x, y)
    return np.array([x, y, z])


def local_stiffness(e, g, a, iy, iz, j, length) -> np.ndarray:
    """The 12 x 12 stiffness of a 3D Euler-Bernoulli beam, local axes:
    u v w rx ry rz at each end."""
    k = np.zeros((12, 12))
    L = length
    ea, gj = e * a / L, g * j / L
    k[0, 0] = k[6, 6] = ea
    k[0, 6] = k[6, 0] = -ea
    k[3, 3] = k[9, 9] = gj
    k[3, 9] = k[9, 3] = -gj
    # bending in the x-y plane: v and rz, stiffness iz
    a1, b1 = 12 * e * iz / L ** 3, 6 * e * iz / L ** 2
    c1, d1 = 4 * e * iz / L, 2 * e * iz / L
    for (i, j_), v in (((1, 1), a1), ((1, 5), b1), ((1, 7), -a1),
                       ((1, 11), b1), ((5, 5), c1), ((5, 7), -b1),
                       ((5, 11), d1), ((7, 7), a1), ((7, 11), -b1),
                       ((11, 11), c1)):
        k[i, j_] = k[j_, i] = v
    # bending in the x-z plane: w and ry, stiffness iy
    a2, b2 = 12 * e * iy / L ** 3, 6 * e * iy / L ** 2
    c2, d2 = 4 * e * iy / L, 2 * e * iy / L
    for (i, j_), v in (((2, 2), a2), ((2, 4), -b2), ((2, 8), -a2),
                       ((2, 10), -b2), ((4, 4), c2), ((4, 8), b2),
                       ((4, 10), d2), ((8, 8), a2), ((8, 10), b2),
                       ((10, 10), c2)):
        k[i, j_] = k[j_, i] = v
    return k


def local_mass(rho, a, ip, length) -> np.ndarray:
    """The 12 x 12 consistent mass of the same beam."""
    m = np.zeros((12, 12))
    L = length
    total = rho * a * L
    for (i, j_), v in (((0, 0), 2), ((0, 6), 1), ((6, 6), 2)):
        m[i, j_] = m[j_, i] = total * v / 6.0
    twist = rho * ip * L
    for (i, j_), v in (((3, 3), 2), ((3, 9), 1), ((9, 9), 2)):
        m[i, j_] = m[j_, i] = twist * v / 6.0
    f = total / 420.0
    bend_y = ((1, 1, 156), (1, 5, 22 * L), (1, 7, 54), (1, 11, -13 * L),
              (5, 5, 4 * L * L), (5, 7, 13 * L), (5, 11, -3 * L * L),
              (7, 7, 156), (7, 11, -22 * L), (11, 11, 4 * L * L))
    bend_z = ((2, 2, 156), (2, 4, -22 * L), (2, 8, 54), (2, 10, 13 * L),
              (4, 4, 4 * L * L), (4, 8, -13 * L), (4, 10, -3 * L * L),
              (8, 8, 156), (8, 10, 22 * L), (10, 10, 4 * L * L))
    for i, j_, v in bend_y + bend_z:
        m[i, j_] = m[j_, i] = f * v
    return m


def fixed_end(q, length) -> np.ndarray:
    """What a uniform load along a beam does to its ends, as forces and
    moments on them: the equivalent nodal loads, local axes."""
    qx, qy, qz = q
    L = length
    f = np.zeros(12)
    f[0] = f[6] = qx * L / 2.0
    f[1] = f[7] = qy * L / 2.0
    f[5], f[11] = qy * L * L / 12.0, -qy * L * L / 12.0
    f[2] = f[8] = qz * L / 2.0
    f[4], f[10] = -qz * L * L / 12.0, qz * L * L / 12.0
    return f


def _transform(axes) -> np.ndarray:
    t = np.zeros((12, 12))
    for i in range(4):
        t[3 * i:3 * i + 3, 3 * i:3 * i + 3] = axes
    return t


# ------------------------------------------------------------ solving

@dataclass
class _Element:
    a: int
    b: int
    member: int
    axes: np.ndarray
    length: float
    k: np.ndarray
    t: np.ndarray
    q: np.ndarray           # uniform load, local, N/mm


def _y_hint(member: Member, axis_x) -> np.ndarray:
    """The member's local y, turned to the section's principal axes."""
    y = np.asarray(member.y_axis, float)
    y = y - axis_x * (y @ axis_x)
    n = np.linalg.norm(y)
    if n < 1e-9:
        return y
    y = y / n
    angle = math.radians(member.section.angle)
    if abs(angle) < 1e-12:
        return y
    z = np.cross(axis_x, y)
    return math.cos(angle) * y + math.sin(angle) * z


def _elements(model: Model, nodes: List) -> List[_Element]:
    """Each member cut into SPLIT elements, the new joints added."""
    out: List[_Element] = []
    gravity = np.asarray(model.gravity, float)
    gn = np.linalg.norm(gravity)
    gravity = gravity / gn if gn > 0 else gravity
    wind = np.asarray(model.wind_direction, float)
    wn = np.linalg.norm(wind)
    wind = wind / wn if wn > 0 else wind
    pressure = 0.5 * AIR * model.wind_speed ** 2 * 1e-6     # N/mm2
    for index, member in enumerate(model.members):
        pa = np.asarray(nodes[member.a], float)
        pb = np.asarray(nodes[member.b], float)
        span = np.linalg.norm(pb - pa)
        if span < 1e-9:
            continue
        axis_x = (pb - pa) / span
        axes = _axes(pa, pb, _y_hint(member, axis_x))
        s, mat = member.section, member.material
        # loads along it, global, N/mm
        w = np.zeros(3)
        if model.self_weight:
            w += gravity * mat.rho * s.area * G
        if pressure > 0 and wn > 0:
            across = wind - axis_x * (wind @ axis_x)
            w += pressure * model.drag * s.width * np.linalg.norm(across) \
                * across
        q = axes @ w
        ids = [member.a]
        for i in range(1, SPLIT):
            nodes.append(tuple(pa + (pb - pa) * i / SPLIT))
            ids.append(len(nodes) - 1)
        ids.append(member.b)
        piece = span / SPLIT
        k_local = local_stiffness(mat.e, mat.g, s.area, s.iy, s.iz, s.j,
                                  piece)
        t = _transform(axes)
        for i in range(SPLIT):
            out.append(_Element(ids[i], ids[i + 1], index, axes, piece,
                                k_local, t, q))
    return out


def solve(model: Model, modes: int = 3) -> Result:
    """Deflections, stresses and natural frequencies of a frame."""
    nodes = list(model.nodes)
    elements = _elements(model, nodes)
    n = len(nodes)
    size = 6 * n
    K = np.zeros((size, size))
    M = np.zeros((size, size))
    F = np.zeros(size)
    for el in elements:
        mat = model.members[el.member].material
        s = model.members[el.member].section
        kg = el.t.T @ el.k @ el.t
        mg = el.t.T @ local_mass(mat.rho, s.area, s.iy + s.iz,
                                 el.length) @ el.t
        dofs = list(range(6 * el.a, 6 * el.a + 6)) + \
            list(range(6 * el.b, 6 * el.b + 6))
        K[np.ix_(dofs, dofs)] += kg
        M[np.ix_(dofs, dofs)] += mg
        F[dofs] += el.t.T @ fixed_end(el.q, el.length)
    for load in model.loads:
        F[6 * load.node:6 * load.node + 3] += load.force
        F[6 * load.node + 3:6 * load.node + 6] += load.moment

    held = set()
    for node, kind in model.supports.items():
        count = 6 if kind == FIXED else 3
        held.update(range(6 * node, 6 * node + count))
    free = [d for d in range(size) if d not in held]
    if not held:
        return Result(np.zeros((n, 6)), [], {}, [],
                      error="the frame stands on nothing: add a support")
    Kff = K[np.ix_(free, free)]
    try:
        uf = np.linalg.solve(Kff, F[free])
    except np.linalg.LinAlgError:
        return Result(np.zeros((n, 6)), [], {}, [],
                      error="the frame can move without bending: a joint "
                            "or member is not held, or a pin needs a "
                            "brace")
    u = np.zeros(size)
    u[free] = uf
    reactions_all = K @ u - F
    reactions = {node: reactions_all[6 * node:6 * node + 6]
                 for node in model.supports}

    # stresses, element by element, kept per member
    results = [MemberResult(name=m.name or "Member %d" % (i + 1))
               for i, m in enumerate(model.members)]
    for el in elements:
        member = model.members[el.member]
        s = member.section
        dofs = list(range(6 * el.a, 6 * el.a + 6)) + \
            list(range(6 * el.b, 6 * el.b + 6))
        local = el.k @ (el.t @ u[dofs]) - fixed_end(el.q, el.length)
        for end in (0, 6):
            axial = local[end]
            my, mz = local[end + 4], local[end + 5]
            stress = abs(axial) / s.area
            if s.iy > 0:
                stress += abs(my) * s.cz / s.iy
            if s.iz > 0:
                stress += abs(mz) * s.cy / s.iz
            result = results[el.member]
            if stress > result.stress:
                result.stress = stress
            # the end at 0 is pulled back by tension; report it as +
            tension = -axial if end == 0 else axial
            if abs(tension) > abs(result.axial):
                result.axial = tension
            result.moment = max(result.moment, math.hypot(my, mz))
    for member, result in zip(model.members, results):
        if member.material.yield_strength > 0:
            result.utilisation = result.stress / \
                member.material.yield_strength

    displacements = u.reshape(n, 6)
    moves = np.linalg.norm(displacements[:, :3], axis=1)
    worst = int(np.argmax(moves)) if n else -1
    top = max(results, key=lambda r: r.utilisation, default=None)
    out = Result(displacements, results, reactions, [],
                 max_deflection=float(moves[worst]) if n else 0.0,
                 max_node=worst,
                 max_stress=max((r.stress for r in results), default=0.0),
                 max_member=top.name if top else "",
                 safety=(1.0 / top.utilisation if top and top.utilisation
                         > 0 else math.inf))
    out.frequencies = _frequencies(K, M, free, modes)
    return out


def _frequencies(K, M, free, modes: int) -> List[float]:
    """The lowest natural frequencies, Hz: K x = w2 M x on the free
    movements, by a Cholesky split of the mass."""
    if modes <= 0 or not free:
        return []
    Kff = K[np.ix_(free, free)]
    Mff = M[np.ix_(free, free)]
    try:
        L = np.linalg.cholesky(Mff)
    except np.linalg.LinAlgError:
        return []
    Li = np.linalg.inv(L)
    A = Li @ Kff @ Li.T
    values = np.linalg.eigvalsh((A + A.T) / 2.0)
    values = values[values > 1e-9]
    return [float(math.sqrt(v) / (2.0 * math.pi)) for v in values[:modes]]
