"""What the user has picked in the app, said as references an agent can use.

A pick is a face or an edge of the part's solid. "Fillet this" must keep
working after the model changes, so each pick is named by what made it
(provenance roles, ``core/provenance.py``) before anything else: a face
that is the end cap of Extrusion1 is ``Extrusion1.end``, a face swept from
sketch line 3 is ``Extrusion1.side(#e3)``, the edge between two faces is
``Extrusion1.end.edge(side(#e3))``. Each candidate is resolved again with
the same ``refs.Resolver`` an agent's own references go through, and only
one that really names the pick (and, for an edge, only that edge) is
offered as its ``ref``. Anything else is given as the ``@F`` / ``@E``
handle ``find_geometry`` would hand out, which keeps the roles it was made
on and falls back on where it was.

This module needs OCP but not Qt: the app hands it the shapes it picked.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from ..core import kernel, provenance
from ..core.naming import ShapeRef
from . import refs
from .errors import BridgeError

MAX_PICKS = 200
CANDIDATES = 3


def _same(a, b) -> bool:
    try:
        return a.IsSame(b)
    except Exception:
        return False


def _find_in(pool, shape):
    """The body's own sub-shape for a picked one: the same one, or the one
    that fingerprints the same (a pick can come back located or copied)."""
    for s in pool:
        if _same(s, shape):
            return s
    return None


def role_texts(resolver: "refs.Resolver", role: str) -> List[str]:
    """The reference text a stored role would be written as, if any."""
    doc = resolver.doc
    try:
        fid, rest = provenance.split_role(role)
    except ValueError:
        return []
    f = doc.feature(fid)
    if f is None:
        return []
    name = f.name
    parts = rest.split(":")
    kind = parts[0]
    if len(parts) == 1 and kind in ("start", "end"):
        return ["%s.%s" % (name, kind)]
    if kind == "side" and len(parts) == 2 and parts[1].startswith("e"):
        return ["%s.side(#%s)" % (name, parts[1])]
    if kind in ("wall", "cbore", "floor", "shoulder", "csink") \
            and len(parts) == 2 and parts[1].startswith("p") \
            and f.type_name == "hole":
        try:
            pids = f.centres(resolver._sketch_of(f.sketch_id))
            at = pids.index(int(parts[1][1:]))
        except (ValueError, BridgeError):
            return []
        return ["%s.%s[%d]" % (name, kind, at)]
    if kind == "face" and len(parts) == 2 and parts[1].isdigit():
        return ["%s.face[%s]" % (name, parts[1])]
    return []


def _count_of(resolver, text: str, kind: str, sub) -> Optional[int]:
    """How many shapes ``text`` names, if it names ``sub`` among them."""
    try:
        got = resolver.resolve(text, "selection", (kind,))
    except BridgeError:
        return None
    except Exception:
        return None
    if not any(_same(s, sub) for s in got.shapes):
        return None
    return len(got.shapes)


def face_texts(resolver, shape, face) -> List[Tuple[str, int]]:
    """Verified texts for one face, most specific first: (text, how many
    faces it names)."""
    out: List[Tuple[str, int]] = []
    for role in sorted(provenance.roles_of(shape, face)):
        for text in role_texts(resolver, role):
            n = _count_of(resolver, text, "face", face)
            if n is not None and all(text != t for t, _n in out):
                out.append((text, n))
    out.sort(key=lambda tn: (tn[1], len(tn[0])))
    return out


def edge_texts(resolver, shape, edge) -> List[Tuple[str, int]]:
    """Verified ``A.edge(B)`` texts for an edge, fewest edges named first."""
    sides = provenance.adjacent_faces(shape, edge)
    if len(sides) != 2:
        return []
    cands = [face_texts(resolver, shape, f)[:CANDIDATES] for f in sides]
    out: List[Tuple[str, int]] = []
    for ta, _na in cands[0]:
        for tb, _nb in cands[1]:
            for a, b in ((ta, tb), (tb, ta)):
                head = a.split(".", 1)[0] + "."
                other = b[len(head):] if b.startswith(head) else b
                text = "%s.edge(%s)" % (a, other)
                n = _count_of(resolver, text, "edge", edge)
                if n is not None and all(text != t for t, _n in out):
                    out.append((text, n))
    out.sort(key=lambda tn: (tn[1], len(tn[0])))
    return out


def describe_picks(entry, picked: List[Any]) -> Dict[str, Any]:
    """The faces, edges and vertices of the part's solid among ``picked``
    (OCC shapes), each as ``{ref, via, handle, count, exact, what}``.

    ``ref`` is a role-based reference when one names exactly this pick,
    else the handle. ``refs`` lists every verified alternative."""
    doc = entry.document
    shape = getattr(doc, "shape", None)
    out: Dict[str, Any] = {"faces": [], "edges": [], "vertices": []}
    if shape is None or shape.IsNull() or not picked:
        return out
    resolver = refs.Resolver(entry)
    pools = {"face": kernel.faces(shape), "edge": kernel.edges(shape),
             "vertex": kernel.vertices(shape)}
    from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_VERTEX
    kinds = {TopAbs_FACE: "face", TopAbs_EDGE: "edge",
             TopAbs_VERTEX: "vertex"}
    seen: List[Any] = []
    if len(picked) > MAX_PICKS:
        out["truncated"] = "%d picked, the first %d are named" % (
            len(picked), MAX_PICKS)
    for raw in picked[:MAX_PICKS]:
        try:
            kind = kinds.get(raw.ShapeType())
        except Exception:
            kind = None
        if kind is None:
            continue
        sub = _find_in(pools[kind], raw)
        if sub is None:
            sub = _by_fingerprint(pools[kind], raw, kind)
        if sub is None or any(_same(sub, s) for s in seen):
            continue
        seen.append(sub)
        item: Dict[str, Any] = {}
        handle = refs.handle_for(entry, sub, kind, shape)
        texts: List[Tuple[str, int]] = []
        if kind == "face":
            texts = face_texts(resolver, shape, sub)
        elif kind == "edge":
            texts = edge_texts(resolver, shape, sub)
        exact = [t for t, n in texts if n == 1]
        if exact:
            item["ref"], item["via"], item["count"] = exact[0], "role", 1
            item["exact"] = True
        elif texts:
            # a role text that also names other faces or edges: the pick
            # is not all it says, so the handle is the exact name
            item["ref"], item["via"], item["count"] = handle, "handle", 1
            item["exact"] = True
            item["also"] = ["%s (names %d)" % (t, n) for t, n in texts[:2]]
        else:
            item["ref"], item["via"], item["count"] = handle, "handle", 1
            item["exact"] = True
        item["handle"] = handle
        if len(exact) > 1:
            item["refs"] = exact[:CANDIDATES]
        f = refs.facts(sub, kind)
        item["what"] = refs.describe(f)
        out[{"face": "faces", "edge": "edges",
             "vertex": "vertices"}[kind]].append(item)
    return out


def _by_fingerprint(pool, raw, kind: str):
    try:
        mine = ShapeRef.capture(raw, kind, 0)
    except Exception:
        return None
    for s in pool:
        try:
            if mine.same_as(ShapeRef.capture(s, kind, 0)):
                return s
        except Exception:
            continue
    return None


def summary_of(sel: Dict[str, Any]) -> str:
    """One line: what is selected, with the first references."""
    bits = []
    for key, label in (("faces", "face"), ("edges", "edge"),
                       ("vertices", "vertex"), ("features", "feature"),
                       ("occurrences", "occurrence")):
        items = sel.get(key) or []
        if items:
            names = [i.get("ref") or i.get("name") or "?" for i in items[:3]]
            more = ", ..." if len(items) > 3 else ""
            bits.append("%d %s%s (%s%s)" % (
                len(items), label, "" if len(items) == 1 else "s",
                ", ".join(str(n) for n in names), more))
    sk = sel.get("sketch")
    if sk:
        n = len(sk.get("entities", [])) + len(sk.get("points", [])) \
            + len(sk.get("dimensions", []))
        if n:
            bits.append("%d sketch item(s) in %s" % (n, sk.get("name")))
    return "selected: " + "; ".join(bits) if bits else "nothing selected"
