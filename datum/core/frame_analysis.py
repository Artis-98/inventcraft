"""A Frame Generator frame made into a beam model, and analysed.

Each member is a beam along its skeleton line, as Inventor's Frame
Analysis treats it: the joints are where the lines meet, and a member
another one stops against partway along is split there, so the two are
joined.  The section is the member's profile, turned the way the member
is turned; the material is the member's own, or the frame's.

The supports and loads are what a first look at a frame needs and no
more: the lowest joints held (fixed, or pinned), the frame's own weight,
a load shared over the top joints, and wind.  See beams.py for the
solver and its units.
"""
from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from . import beams, frames, materials

JOIN = 0.5              # mm: line ends this close are one joint
STEEL = beams.Material(e=210000.0, nu=0.3, density=7.85,
                       yield_strength=235.0)


@dataclass
class Setup:
    """What the frame stands on and what it carries."""

    support: str = beams.FIXED          # at the lowest joints
    self_weight: bool = True
    top_load: float = 0.0               # N, shared over the top joints
    wind_speed: float = 0.0             # m/s
    wind_direction: Tuple[float, float, float] = (1.0, 0.0, 0.0)
    drag: float = 2.0
    gravity: Tuple[float, float, float] = (0.0, 0.0, -1.0)
    modes: int = 3


@dataclass
class FrameModel:
    model: beams.Model
    labels: List[str] = field(default_factory=list)     # per beam
    member_ids: List[int] = field(default_factory=list)  # per beam
    notes: List[str] = field(default_factory=list)


def _material(name: str, notes: List[str]) -> beams.Material:
    known = materials.library().materials.get(name or "")
    if known is None or known.youngs_modulus <= 0:
        if name and name not in ("Generic",):
            notes.append("%s has no stiffness on record; steel's used"
                         % name)
        return STEEL
    return beams.Material(e=known.youngs_modulus * 1000.0,
                          nu=known.poisson_ratio or 0.3,
                          density=known.density,
                          yield_strength=known.yield_strength or 235.0)


def build(frame_doc, setup: Setup) -> FrameModel:
    """The beam model of a frame assembly, as its skeleton is now."""
    fd = frame_doc.frame
    if fd is None:
        raise ValueError("that is not a frame")
    base = frame_doc.base_dir
    skeleton = os.path.normpath(os.path.join(base, fd.skeleton)) \
        if base and not os.path.isabs(fd.skeleton) else fd.skeleton
    sketches = frames.skeleton_sketches(skeleton)
    problems: List[str] = []
    geos = frames.member_geometries(fd, sketches, problems)
    notes = list(problems)

    nodes: List[Tuple[float, float, float]] = []

    def node(p) -> int:
        for i, q in enumerate(nodes):
            if math.dist(p, q) <= JOIN:
                return i
        nodes.append(tuple(float(c) for c in p))
        return len(nodes) - 1

    spans = []
    for member in fd.members:
        geo = geos.get(member.id)
        if geo is None:
            continue
        spans.append((member, geo, node(geo.start), node(geo.end)))

    sections: Dict[Tuple[str, str], beams.Section] = {}
    out = beams.Model(nodes=nodes, gravity=setup.gravity,
                      self_weight=setup.self_weight,
                      wind_speed=setup.wind_speed,
                      wind_direction=setup.wind_direction, drag=setup.drag)
    labels, ids = [], []
    frame_material = getattr(frame_doc, "material", "") or ""
    for member, geo, a, b in spans:
        key = (member.family, member.size)
        if key not in sections:
            face = frames.profile_face(geo.fam.kind, geo.dims,
                                       geo.fam.source)
            sections[key] = beams.section_of_face(face, kind=geo.fam.kind,
                                                  dims=geo.dims)
        section = sections[key]
        material = _material(member.material or frame_material, notes)
        y_axis = tuple(float(c) for c in np.asarray(geo.m)[:, 0])
        # joints that land partway along: the member is split at them
        pa, pb = np.asarray(nodes[a]), np.asarray(nodes[b])
        span = pb - pa
        length = float(np.linalg.norm(span))
        inner = []
        for i, q in enumerate(nodes):
            if i in (a, b):
                continue
            t = float((np.asarray(q) - pa) @ span) / (length * length)
            if 1e-6 < t < 1 - 1e-6 and np.linalg.norm(
                    pa + span * t - np.asarray(q)) <= JOIN:
                inner.append((t, i))
        chain = [a] + [i for _t, i in sorted(inner)] + [b]
        label = "%s %s" % (geo.fam.standard or geo.fam.name, member.size)
        for p, q in zip(chain, chain[1:]):
            out.members.append(beams.Member(p, q, section, material,
                                            y_axis=y_axis, name=label))
            labels.append(label)
            ids.append(member.id)

    if nodes:
        g = np.asarray(setup.gravity, float)
        g = g / (np.linalg.norm(g) or 1.0)
        heights = [-(np.asarray(p) @ g) for p in nodes]
        low, high = min(heights), max(heights)
        for i, h in enumerate(heights):
            if h - low <= JOIN:
                out.supports[i] = setup.support
        if setup.top_load and high - low > JOIN:
            tops = [i for i, h in enumerate(heights) if high - h <= JOIN]
            share = setup.top_load / len(tops)
            for i in tops:
                out.loads.append(beams.Load(i, tuple(g * share)))
    return FrameModel(out, labels, ids, notes)


@dataclass
class MemberSummary:
    member: int
    label: str
    stress: float
    utilisation: float


def summarise(fm: FrameModel, result: beams.Result) -> List[MemberSummary]:
    """One line per frame member, the worst of the beams it was split
    into."""
    worst: Dict[int, MemberSummary] = {}
    for mid, label, r in zip(fm.member_ids, fm.labels, result.members):
        held = worst.get(mid)
        if held is None or r.utilisation > held.utilisation:
            worst[mid] = MemberSummary(mid, label, r.stress, r.utilisation)
    return sorted(worst.values(), key=lambda s: -s.utilisation)


def analyse(frame_doc, setup: Setup):
    """Build and solve: (FrameModel, beams.Result, [MemberSummary])."""
    fm = build(frame_doc, setup)
    result = beams.solve(fm.model, modes=setup.modes)
    return fm, result, summarise(fm, result) if not result.error else []
