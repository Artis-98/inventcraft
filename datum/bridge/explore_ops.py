"""``evaluate`` and ``optimise``: trying designs without touching the design.

``evaluate`` takes variations of one part (parameter overrides, a grid of
them, or model states), builds every one on the worker pool and answers a
table: volume, mass, size, faces, whether the body is valid, every
requirement the part stores (value and pass or fail, and how far short) and
clearances between references. Each variant travels to a worker as
in-memory document data (``core/worker._evaluate``), so there are no
temporary files and the open document is never touched: its revision, its
undo stack and its file stay as they were. A variant that does not build is
a row with its error, not a failed call.

``optimise`` searches the parameters you let it vary for the best design
that clears every requirement: a coarse grid over the whole space, then a
compass search from the best point (steps of the grid's spacing, halved
whenever nothing improves), every step a batch of evaluate. The document
changes only when ``apply`` is true, then as one undo step, and, with a
branch name, on a branch the user can diff and merge.

Workers. Inside the app the window's own pool is used. A headless host is
told not to make workers (it is a process of its own), but ``evaluate``
brings a small pool of its own up for the call and lets it go a little
after: bounded by ``workers.capacity()`` (one core is left over and a
worker is about 230 MB, so memory counts), never more than the variants.
With no workers at all (``DATUM_WORKERS=0``) the variants are built one
after another in this process.
"""

from __future__ import annotations

import contextlib
import itertools
import json
import math
import os
import threading
import time
from typing import Any, Dict, Iterator, List, Optional, Sequence, Tuple

from ..core import requirements as reqs
from ..core import rules as core_rules
from . import measure as measure_mod
from . import ops
from .build import Build
from .errors import BridgeError
from .workspace import Entry, Workspace

op = ops.op

DEFAULT_METRICS = ("volume", "mass", "bbox", "faces", "valid", "requirements")
ALL_METRICS = ("volume", "mass", "area", "bbox", "faces", "solids", "valid",
               "requirements", "params")
MAX_VARIANTS = 200
DEFAULT_VARIANTS = 64
VARIANT_SECONDS = 120.0
HEARTBEAT = 4.0
# a private pool is kept this long after its last user, for the next call
KEEP_POOL = 45.0


# ---------------------------------------------------------------- workers

_PRIVATE: Dict[str, Any] = {"pool": None, "users": 0, "timer": None}
_LOCK = threading.Lock()


def _release_private() -> None:
    with _LOCK:
        if _PRIVATE["users"] == 0 and _PRIVATE["pool"] is not None:
            pool, _PRIVATE["pool"] = _PRIVATE["pool"], None
        else:
            return
    pool.shutdown()


@contextlib.contextmanager
def lease(hint: int = 1) -> Iterator[Any]:
    """A worker pool for a while: the window's, else a private one, else
    None (the variants then run in this process)."""
    from ..core import workers
    shared = workers.pool()
    if shared is not None:
        yield shared
        return
    explicit_off = os.environ.get("DATUM_NO_WORKERS") and \
        not os.environ.get("DATUM_HEADLESS_HOST")
    cap = workers.capacity()
    if explicit_off or cap < 1:
        yield None
        return
    want = max(1, min(cap, hint))
    stale = None
    with _LOCK:
        timer, _PRIVATE["timer"] = _PRIVATE["timer"], None
        if timer is not None:
            timer.cancel()
        pool = _PRIVATE["pool"]
        if pool is not None and pool.size < want and _PRIVATE["users"] == 0:
            stale, pool = pool, None
        if pool is None:
            pool = _PRIVATE["pool"] = workers.Pool(size=want)
        _PRIVATE["users"] += 1
    if stale is not None:
        stale.shutdown()
    try:
        yield pool
    finally:
        with _LOCK:
            _PRIVATE["users"] -= 1
            if _PRIVATE["users"] == 0:
                timer = threading.Timer(KEEP_POOL, _release_private)
                timer.daemon = True
                _PRIVATE["timer"] = timer
                timer.start()


def shutdown_private() -> None:
    """Let go of the private pool now (tests, and a host closing)."""
    with _LOCK:
        timer, _PRIVATE["timer"] = _PRIVATE["timer"], None
        pool, _PRIVATE["pool"] = _PRIVATE["pool"], None
    if timer is not None:
        timer.cancel()
    if pool is not None:
        pool.shutdown()


# ---------------------------------------------------------------- variants


def _is_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _span(spec: Any, what: str) -> List[Any]:
    """The values one axis of a grid takes: a number or expression, a list
    of them, or {"from", "to", "steps"} / {"min", "max", "step"}."""
    if isinstance(spec, dict):
        lo = spec.get("from", spec.get("min"))
        hi = spec.get("to", spec.get("max"))
        if not (_is_number(lo) and _is_number(hi)):
            raise BridgeError("BAD_VALUE", "%s: a range needs numeric from "
                              "and to" % what)
        if spec.get("step"):
            step = float(spec["step"])
            n = int(math.floor((hi - lo) / step + 1e-9)) + 1
            return [lo + i * step for i in range(max(n, 1))]
        n = int(spec.get("steps", 5))
        if n < 2:
            return [lo]
        return [lo + (hi - lo) * i / (n - 1) for i in range(n)]
    if isinstance(spec, (list, tuple)):
        return list(spec)
    return [spec]


def expand(variations: Any, grid: Any = None) -> List[Dict[str, Any]]:
    """What the caller asked for, as a list of {"set", "state", "name"}.

    ``variations`` is a list (each item a dict of parameter values with the
    optional keys ``state`` and ``name``, or a model state's name), or a
    dict, which is a grid: every axis a list or a range, every combination
    tried. ``grid`` is the same dict given on its own."""
    out: List[Dict[str, Any]] = []

    def one(item: Any, at: int) -> Dict[str, Any]:
        if isinstance(item, str):
            return {"set": {}, "state": item, "name": item}
        if not isinstance(item, dict):
            raise BridgeError(
                "BAD_VALUE", "variation %d is not an object" % at,
                ['A variation is {"t": 6, "w": "w * 1.2"}, optionally with '
                 '"state": "M6x40" and "name": "label".'])
        item = dict(item)
        state = item.pop("state", None)
        name = item.pop("name", None)
        return {"set": item, "state": state, "name": name}

    if isinstance(variations, dict):
        grid, variations = dict(variations, **(grid or {})), None
    if variations:
        if not isinstance(variations, (list, tuple)):
            raise BridgeError("BAD_VALUE", "variations is a list or a grid")
        out.extend(one(v, i) for i, v in enumerate(variations))
    if grid:
        names = list(grid)
        axes = [_span(grid[n], n) for n in names]
        total = 1
        for axis in axes:
            total *= max(len(axis), 1)
        if total > MAX_VARIANTS:
            raise BridgeError(
                "TOO_MANY", "the grid is %d variants (the most is %d)"
                % (total, MAX_VARIANTS),
                ["Use fewer values per axis, or optimise(), which searches "
                 "with a budget."])
        for combo in itertools.product(*axes):
            out.append({"set": dict(zip(names, combo)), "state": None,
                        "name": None})
    return out


class _Evaluator:
    """One part's variants: makes each as data, runs them, reads them back."""

    def __init__(self, ws: Workspace, entry: Entry, metrics: Sequence[str],
                 clearances: Optional[Dict[str, Any]], extra: Sequence[Any],
                 timeout: float, detail: bool) -> None:
        self.ws = ws
        self.entry = entry
        self.d = ops._need_part(entry)
        self.metrics = tuple(metrics)
        self.timeout = timeout
        self.detail = detail
        self.job = Build(entry)
        self.base = json.dumps(self.d.to_dict())
        self.trusted = core_rules.document_trusted(self.d)
        self.trusted_code = core_rules.trusted_code_in(self.d)
        self.path = self.d.path or ""
        self.extra: List[Dict[str, Any]] = []
        self.clearance_names: List[str] = []
        for name, pair in (clearances or {}).items():
            if not isinstance(pair, dict) or "a" not in pair \
                    or "b" not in pair:
                raise BridgeError(
                    "BAD_VALUE", "clearance %r needs a and b" % name,
                    ['clearances={"gap": {"a": "Hole1.wall[0]", '
                     '"b": "Plate.side(r.right)"}}'])
            self.extra.append({
                "name": "clearance:" + name, "metric": "clearance",
                "a": measure_mod.capture_end(entry, pair["a"]),
                "b": measure_mod.capture_end(entry, pair["b"]),
                "min": -1e9})
            self.clearance_names.append(name)
        self.extra.extend(self._extra_requirements(extra))
        self.done = 0
        self.total = 0
        self.cancelled = False
        self.used_pids: set = set()
        self.in_process = False
        self.workers_used = 0
        self.started = time.perf_counter()

    def _extra_requirements(self, extra: Sequence[Any]) -> List[Dict[str, Any]]:
        out = []
        for spec in extra or ():
            if not isinstance(spec, dict):
                continue
            spec = dict(spec)
            if spec.get("metric") == "clearance":
                for end in ("a", "b"):
                    if end in spec:
                        spec[end] = measure_mod.capture_end(self.entry,
                                                            spec[end])
            try:
                out.append(reqs.Requirement.from_dict(spec).to_dict())
            except reqs.RequirementError as exc:
                raise BridgeError(exc.kind, str(exc), exc.hints) from exc
        return out

    # -- making a variant -------------------------------------------------

    def data_for(self, variant: Dict[str, Any]) -> Dict[str, Any]:
        """The document with the variation applied, as data. The open
        document is not used beyond its text."""
        from ..core.document import Document
        copy = Document()
        copy.path = self.path
        copy.load_dict(json.loads(self.base))
        state = variant.get("state")
        if state:
            if state not in copy.model_states:
                raise BridgeError(
                    "NOT_FOUND", "no model state %r" % state,
                    ["States: %s" % (", ".join(copy.model_states.names())
                                     or "none")])
            copy.model_states.activate(copy, state)
        for name, value in (variant.get("set") or {}).items():
            if name not in copy.params:
                raise BridgeError(
                    "NOT_FOUND", "no parameter %r" % name,
                    ["Parameters: %s" % ", ".join(copy.params.names()),
                     "Only user parameters vary here; a dimension inside a "
                     "sketch is a model state's job."])
            unit = getattr(copy.params[name], "unit", "mm")
            kind = {"deg": "angle", "ul": "count"}.get(unit, "length")
            text = self.job.stored(value, kind, name)
            try:
                copy.params.set_expression(name, str(text))
            except Exception as exc:                    # noqa: BLE001
                raise BridgeError("BAD_EXPRESSION", "%s: %s" % (name, exc))
        return copy.to_dict()

    # -- running ----------------------------------------------------------

    def run(self, variants: List[Dict[str, Any]], offset: int = 0,
            total: Optional[int] = None, label: str = "evaluate"
            ) -> List[Dict[str, Any]]:
        """Build every variant and return a row each, in order. Stops
        taking new ones when the host says cancel; those rows say so."""
        n = len(variants)
        self.total = total or (offset + n)
        jobs: List[Optional[Dict[str, Any]]] = []
        rows: List[Optional[Dict[str, Any]]] = [None] * n
        for i, variant in enumerate(variants):
            try:
                jobs.append({"data": self.data_for(variant),
                             "path": self.path, "trusted": self.trusted,
                             "trusted_code": self.trusted_code,
                             "extra": self.extra})
            except BridgeError as exc:
                jobs.append(None)
                rows[i] = {"built": False, "error": exc.message}
        todo = [i for i, j in enumerate(jobs) if j is not None]
        self.ws.progress(self.done, self.total, "%s: starting" % label)
        with lease(len(todo)) as pool:
            if pool is None:
                self._run_here(jobs, todo, rows, label)
            else:
                self._run_pool(pool, jobs, todo, rows, label)
        out = []
        for i, (variant, raw) in enumerate(zip(variants, rows)):
            out.append(self._row(offset + i, variant, raw))
        return out

    def _finished(self, label: str) -> None:
        self.done += 1
        self.ws.progress(self.done, self.total, label)

    def _run_here(self, jobs, todo, rows, label) -> None:
        from ..core import worker
        self.in_process = True
        self.workers_used = 1
        for i in todo:
            if self.ws.should_cancel():
                self.cancelled = True
                break
            try:
                rows[i] = worker._evaluate(**jobs[i])
            except Exception as exc:                    # noqa: BLE001
                rows[i] = {"built": False, "error": "%s: %s" % (
                    type(exc).__name__, exc)}
            self._finished(label)

    def _run_pool(self, pool, jobs, todo, rows, label) -> None:
        limit = max(1, min(len(todo), pool.size))
        pending: Dict[int, Tuple[Any, float]] = {}
        queue = list(todo)
        beat = time.monotonic()
        while queue or pending:
            if self.ws.should_cancel():
                self.cancelled = True
                break
            while queue and len(pending) < limit:
                i = queue.pop(0)
                pending[i] = (pool.submit("evaluate", **jobs[i]),
                              time.monotonic())
            for i, (future, since) in list(pending.items()):
                if future.done():
                    del pending[i]
                    error = future.exception()
                    if error is not None:
                        rows[i] = {"built": False, "error": str(error)[:300]}
                    else:
                        rows[i] = future.result()
                    self._finished(label)
                    beat = time.monotonic()
                elif time.monotonic() - since > self.timeout:
                    del pending[i]
                    rows[i] = {"built": False, "error": (
                        "did not finish within %.0f s" % self.timeout)}
                    self._finished(label)
            if time.monotonic() - beat > HEARTBEAT:
                self.ws.progress(self.done, self.total, label)
                beat = time.monotonic()
            if pending:
                time.sleep(0.04)
        for future, _ in pending.values():
            future.cancel()
        self.workers_used = max(self.workers_used,
                                min(limit, pool.size))

    # -- reading one back -------------------------------------------------

    def _row(self, index: int, variant: Dict[str, Any],
             raw: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        label = variant.get("name") or ", ".join(
            "%s=%s" % (k, _short(v)) for k, v in
            (variant.get("set") or {}).items()) or (
            variant.get("state") or "as is")
        row: Dict[str, Any] = {"i": index, "label": label,
                               "vary": dict(variant.get("set") or {})}
        if variant.get("state"):
            row["state"] = variant["state"]
        if raw is None:
            row.update({"ok": False, "error": "cancelled before it ran",
                        "cancelled": True})
            return row
        if raw.get("pid"):
            self.used_pids.add(raw["pid"])
        errors = raw.get("errors") or []
        row["ok"] = bool(raw.get("built"))
        if raw.get("error"):
            row["error"] = raw["error"]
        elif errors:
            row["error"] = "; ".join("%s: %s" % (f, m) for f, m in errors)[:300]
        elif not raw.get("built"):
            row["error"] = "no body"
        m = self.metrics
        if "volume" in m:
            row["volume_mm3"] = round(raw.get("volume_mm3", 0.0), 3)
        if "mass" in m:
            row["mass_g"] = round(raw.get("mass_g", 0.0), 3)
        if "area" in m:
            row["area_mm2"] = round(raw.get("area_mm2", 0.0), 3)
        if "bbox" in m:
            row["bbox"] = [round(v, 3) for v in raw.get("bbox", [])]
        if "faces" in m:
            row["faces"] = raw.get("faces", 0)
        if "solids" in m:
            row["solids"] = raw.get("solids", 0)
        if "valid" in m:
            row["valid"] = bool(raw.get("valid"))
        results = raw.get("requirements") or []
        stored = [r for r in results if not r["name"].startswith(
            "clearance:")]
        measured = {r["name"][len("clearance:"):]: r.get("value")
                    for r in results if r["name"].startswith("clearance:")}
        if measured:
            row["clearance"] = {k: (round(v, 4) if _is_number(v) else v)
                                for k, v in measured.items()}
        row["_results"] = results
        if "requirements" in m and stored:
            row["pass"] = all(r.get("pass") for r in stored)
            row["reqs"] = "%d/%d" % (sum(1 for r in stored if r.get("pass")),
                                     len(stored))
            row["failing"] = [r["text"] for r in stored if not r.get("pass")]
            if self.detail:
                row["values"] = {r["name"]: r.get("value") for r in stored}
        if "params" in m:
            row["params"] = raw.get("params", {})
        row["seconds"] = raw.get("seconds")
        if raw.get("pid"):
            row["worker"] = raw["pid"]
        return row


def _short(v: Any) -> str:
    if _is_number(v):
        return ("%.4g" % v)
    return str(v)


def _num(v: Any, digits: int = 4) -> str:
    return "-" if v is None else ("%.*g" % (digits, v))


def table(rows: List[Dict[str, Any]], metrics: Sequence[str],
          clearance_names: Sequence[str]) -> str:
    """The rows as a compact text table (what the agent reads first)."""
    head = ["#", "variant"]
    if "mass" in metrics:
        head.append("mass g")
    if "volume" in metrics:
        head.append("vol mm3")
    if "bbox" in metrics:
        head.append("bbox")
    if "faces" in metrics:
        head.append("faces")
    head.extend(clearance_names)
    if "valid" in metrics:
        head.append("valid")
    if "requirements" in metrics:
        head.append("reqs")
    head.append("status")
    lines = [head]
    for r in rows:
        line = [str(r["i"]), r["label"]]
        if r.get("error") and not r.get("ok"):
            line += ["-"] * (len(head) - 3) + ["ERROR " + r["error"][:60]]
            lines.append(line)
            continue
        if "mass" in metrics:
            line.append(_num(r.get("mass_g")))
        if "volume" in metrics:
            line.append(_num(r.get("volume_mm3"), 6))
        if "bbox" in metrics:
            line.append("x".join(_num(v, 4) for v in r.get("bbox", [])))
        if "faces" in metrics:
            line.append(str(r.get("faces", "-")))
        for name in clearance_names:
            line.append(_num((r.get("clearance") or {}).get(name)))
        if "valid" in metrics:
            line.append("yes" if r.get("valid") else "NO")
        if "requirements" in metrics:
            line.append(r.get("reqs", "-"))
        if r.get("failing"):
            line.append("fails: " + "; ".join(r["failing"])[:80])
        else:
            line.append("ok" if r.get("ok") else "ERROR")
        lines.append(line)
    widths = [max(len(l[i]) for l in lines) for i in range(len(head))]
    return "\n".join("  ".join(c.ljust(w) for c, w in zip(l, widths)).rstrip()
                     for l in lines)


def _clean(row: Dict[str, Any], keep_results: bool = False) -> Dict[str, Any]:
    out = {k: v for k, v in row.items() if k not in ("_results", "_point")}
    if keep_results:
        out["results"] = [{k: r.get(k) for k in ("name", "pass", "value",
                                                 "text") if k in r}
                          for r in row.get("_results", [])
                          if not r["name"].startswith("clearance:")]
    return out


def _workers_info(ev: _Evaluator) -> Dict[str, Any]:
    from ..core import workers
    return {"capacity": workers.capacity(),
            "used": len(ev.used_pids) or (1 if ev.in_process else 0),
            "in_process": ev.in_process}


def _metrics(metrics: Optional[Sequence[str]]) -> Tuple[str, ...]:
    if not metrics:
        return DEFAULT_METRICS
    if isinstance(metrics, str):
        metrics = [metrics]
    bad = [m for m in metrics if m not in ALL_METRICS]
    if bad:
        raise BridgeError("BAD_VALUE", "unknown metric %s"
                          % ", ".join(map(repr, bad)),
                          ["Metrics: %s" % ", ".join(ALL_METRICS)])
    return tuple(metrics)


def _ensure_baseline(d) -> None:
    if not len(d.features):
        raise BridgeError("NO_BODY", "the part has no features to evaluate",
                          ["Build it first."])


# ---------------------------------------------------------------- evaluate


@op
def evaluate(ws: Workspace, doc: str = "", variations: Any = None,
             grid: Optional[Dict[str, Any]] = None,
             metrics: Optional[Sequence[str]] = None,
             clearances: Optional[Dict[str, Any]] = None,
             baseline: bool = True, detail: bool = False,
             timeout: float = VARIANT_SECONDS) -> Dict[str, Any]:
    """Build variants of a part on the worker pool and tabulate them."""
    started = time.perf_counter()
    entry = ws.get(doc)
    d = ops._need_part(entry)
    _ensure_baseline(d)
    wanted = _metrics(metrics)
    variants = expand(variations, grid)
    if not variants and not baseline:
        raise BridgeError("BAD_VALUE", "nothing to evaluate",
                          ["Give variations, a grid or baseline=true."])
    if baseline:
        variants.insert(0, {"set": {}, "state": None, "name": "as is"})
    if len(variants) > MAX_VARIANTS:
        raise BridgeError(
            "TOO_MANY", "%d variants (the most is %d)"
            % (len(variants), MAX_VARIANTS),
            ["Split the list, or use optimise() to search with a budget."])
    ev = _Evaluator(ws, entry, wanted, clearances, (), float(timeout),
                    detail)
    rows = ev.run(variants)
    seconds = round(time.perf_counter() - started, 2)
    failed = [r for r in rows if not r.get("ok")]
    passing = [r for r in rows if r.get("ok") and r.get("pass", True)]
    bits = ["evaluate ok" if not ev.cancelled else "evaluate cancelled",
            "%d variant%s in %.1f s" % (
                len(rows), "" if len(rows) == 1 else "s", seconds),
            "%d worker%s" % (max(1, len(ev.used_pids)),
                             "" if len(ev.used_pids) <= 1 else "s")]
    if "requirements" in wanted and d.requirements:
        bits.append("%d/%d clear the requirements" % (
            len(passing), len(rows) - len(failed)))
    if failed:
        bits.append("%d did not build" % len(failed))
    if "mass" in wanted:
        lightest = min((r for r in passing if "mass_g" in r),
                       key=lambda r: r["mass_g"], default=None)
        if lightest is not None:
            bits.append("lightest %s: %s g" % (
                "passing" if d.requirements else "built",
                _num(lightest["mass_g"])))
    out = {"doc": entry.handle, "revision": entry.revision,
           "summary": " | ".join(bits), "evaluated": len(rows),
           "cancelled": ev.cancelled, "seconds": seconds,
           "workers": _workers_info(ev),
           "table": table(rows, wanted, ev.clearance_names),
           "rows": [_clean(r, detail) for r in rows]}
    out["revision"] = entry.revision
    return out


# ---------------------------------------------------------------- optimise

_OBJECTIVE_KEYS = {
    "mass": ("mass_g", "g"), "volume": ("volume_mm3", "mm3"),
    "area": ("area_mm2", "mm2"), "faces": ("faces", ""),
}


def parse_objective(text: str) -> Tuple[str, str]:
    """"min mass" -> ("min", "mass"); "max req:clear" ... The key is a
    metric (mass, volume, area, faces, bbox.x, bbox.y, bbox.z, bbox_volume),
    ``req:<name>`` (a requirement's measured value) or ``param:<name>``."""
    words = str(text or "min mass").strip().split(None, 1)
    if len(words) == 1:
        words = ["min", words[0]]
    sense, key = words[0].lower(), words[1].strip()
    if sense in ("minimise", "minimize", "minimum", "lightest", "smallest"):
        sense = "min"
    if sense in ("maximise", "maximize", "maximum"):
        sense = "max"
    if sense not in ("min", "max"):
        raise BridgeError(
            "BAD_VALUE", "objective %r does not start with min or max"
            % text, ['"min mass", "min volume", "max req:clear", '
                     '"min bbox.x", "min param:t"'])
    base = key.split(":", 1)[0]
    if key not in _OBJECTIVE_KEYS and key not in (
            "bbox.x", "bbox.y", "bbox.z", "bbox_volume") \
            and base not in ("req", "param"):
        raise BridgeError(
            "BAD_VALUE", "unknown objective metric %r" % key,
            ["mass, volume, area, faces, bbox.x|y|z, bbox_volume, "
             "req:<requirement>, param:<name>"])
    return sense, key


def _objective_value(row: Dict[str, Any], key: str) -> Optional[float]:
    if key in _OBJECTIVE_KEYS:
        return row.get(_OBJECTIVE_KEYS[key][0])
    if key.startswith("bbox."):
        box = row.get("bbox") or []
        return box["xyz".index(key[-1])] if len(box) == 3 else None
    if key == "bbox_volume":
        box = row.get("bbox") or []
        return box[0] * box[1] * box[2] if len(box) == 3 else None
    if key.startswith("req:"):
        for r in row.get("_results", []):
            if r["name"] == key[4:] and _is_number(r.get("value")):
                return r["value"]
        return None
    if key.startswith("param:"):
        return (row.get("params") or {}).get(key[6:])
    return None


class _Axis:
    """One thing the search varies."""

    def __init__(self, name: str, spec: Any) -> None:
        self.name = name
        self.values: Optional[List[float]] = None
        self.step = 0.0
        if isinstance(spec, dict):
            if "values" in spec:
                self.values = sorted(float(v) for v in spec["values"])
            else:
                lo = spec.get("min", spec.get("from"))
                hi = spec.get("max", spec.get("to"))
                if not (_is_number(lo) and _is_number(hi)):
                    raise BridgeError("BAD_VALUE", "vary %s: give min and "
                                      "max (or values)" % name)
                self.lo, self.hi = float(lo), float(hi)
                self.step = float(spec.get("step") or 0.0)
        elif isinstance(spec, (list, tuple)):
            if not all(_is_number(v) for v in spec) or len(spec) < 2:
                raise BridgeError(
                    "BAD_VALUE", "vary %s: a list of numbers, [lo, hi] or "
                    "three or more values" % name)
            if len(spec) == 2:
                self.lo, self.hi = float(min(spec)), float(max(spec))
            else:
                self.values = sorted(float(v) for v in spec)
        else:
            raise BridgeError(
                "BAD_VALUE", "vary %s: [lo, hi], a list of values, or "
                '{"min": , "max": , "step": }' % name)
        if self.values is not None:
            self.lo, self.hi = self.values[0], self.values[-1]
        if self.lo > self.hi:
            raise BridgeError("BAD_VALUE", "vary %s: min is above max" % name)

    @property
    def discrete(self) -> bool:
        return self.values is not None

    def snap(self, v: float) -> float:
        v = min(max(v, self.lo), self.hi)
        if self.values is not None:
            return min(self.values, key=lambda c: abs(c - v))
        if self.step > 0:
            k = round((v - self.lo) / self.step)
            v = min(self.lo + k * self.step, self.hi)
        return round(v, 6)

    def grid(self, n: int) -> List[float]:
        if self.values is not None:
            if len(self.values) <= n:
                return list(self.values)
            at = [round(i * (len(self.values) - 1) / (n - 1))
                  for i in range(n)]
            return [self.values[i] for i in sorted(set(at))]
        if self.hi == self.lo:
            return [self.lo]
        pts = [self.snap(self.lo + (self.hi - self.lo) * i / (n - 1))
               for i in range(n)]
        return sorted(set(pts))

    def around(self, centre: float, h: float) -> List[float]:
        """The points of a compass stencil about ``centre``: one step each
        way (the neighbours in the list, for a discrete axis)."""
        if self.values is not None:
            i = self.values.index(centre)
            out = [self.values[j] for j in (i - 1, i + 1)
                   if 0 <= j < len(self.values)]
            return out
        pts = {self.snap(centre + s * h) for s in (-1, 1)}
        pts.discard(self.snap(centre))
        return sorted(pts)


def _key(point: Dict[str, float], axes: Sequence[_Axis]) -> Tuple:
    return tuple(round(point[a.name], 6) for a in axes)


def _violation(row: Dict[str, Any], enforced: Optional[set]) -> float:
    if not row.get("ok") or not row.get("valid", True):
        return 1e3
    total = 0.0
    if row.get("solids", 1) != 1:
        total += 1.0
    for r in row.get("_results", []):
        if r["name"].startswith("clearance:"):
            continue
        if enforced is not None and r["name"] not in enforced:
            continue
        total += float(r.get("gap", 0.0 if r.get("pass") else 1.0))
    return total


def _better_key(row: Dict[str, Any], sense: str, key: str,
                enforced: Optional[set]) -> Tuple[float, float]:
    """Smaller is better: feasible designs by the objective, then the ones
    that miss, by how far."""
    violation = _violation(row, enforced)
    value = _objective_value(row, key)
    if value is None:
        return (2.0, 0.0) if violation == 0 else (1.0, violation)
    if violation > 0:
        return (1.0, violation)
    return (0.0, value if sense == "min" else -value)


@op
def optimise(ws: Workspace, doc: str = "", vary: Optional[Dict[str, Any]] = None,
             objective: str = "min mass", subject_to: Any = None,
             budget: int = 40, apply: bool = False, branch: str = "",
             clearances: Optional[Dict[str, Any]] = None,
             detail: bool = False, timeout: float = VARIANT_SECONDS,
             expected_revision: Optional[int] = None) -> Dict[str, Any]:
    """Search the parameters in ``vary`` for the best design that clears
    every requirement."""
    started = time.perf_counter()
    entry = ws.get(doc)
    d = ops._need_part(entry)
    _ensure_baseline(d)
    if apply:
        ops._check_revision(entry, expected_revision)
    if not vary or not isinstance(vary, dict):
        raise BridgeError(
            "BAD_VALUE", "vary says which parameters the search may change",
            ['vary={"t": [3, 12], "w": [60, 140]}  (a range), or a list of '
             "three or more values, or {\"min\":, \"max\":, \"step\":}"])
    axes = []
    for name, spec in vary.items():
        if name not in d.params:
            raise BridgeError("NOT_FOUND", "no parameter %r" % name,
                              ["Parameters: %s" % ", ".join(
                                  d.params.names())])
        axes.append(_Axis(name, spec))
    sense, okey = parse_objective(objective)
    budget = int(budget)
    if not 4 <= budget <= MAX_VARIANTS:
        raise BridgeError("BAD_VALUE", "budget is between 4 and %d "
                          "evaluations" % MAX_VARIANTS)
    # which requirements must hold: the stored ones, or the ones named
    extras, named = [], []
    for item in (subject_to if isinstance(subject_to, list)
                 else [subject_to] if subject_to else []):
        (named if isinstance(item, str) else extras).append(item)
    stored = [r.name for r in d.requirements if r.enabled]
    for n in named:
        if n not in stored:
            raise BridgeError("NOT_FOUND", "no stored requirement %r" % n,
                              ["Requirements: %s" % (", ".join(stored)
                                                     or "none")])
    ev = _Evaluator(ws, entry, ("volume", "mass", "area", "bbox", "faces",
                                "solids", "valid", "requirements", "params"),
                    clearances, extras, float(timeout), detail)
    extra_names = [e["name"] for e in ev.extra
                   if not e["name"].startswith("clearance:")]
    enforced = (set(named) | set(extra_names)) if named else None
    if enforced is None and extras:
        enforced = set(stored) | set(extra_names)
    if okey.startswith("req:") and okey[4:] not in stored + extra_names:
        raise BridgeError("NOT_FOUND", "no requirement %r to optimise"
                          % okey[4:], ["Requirements: %s" % (
                              ", ".join(stored + extra_names) or "none")])

    explored: List[Dict[str, Any]] = []
    seen: Dict[Tuple, Dict[str, Any]] = {}
    # ---- the start: the design as it is, for the comparison
    lease_hint = min(max(budget // 3, 2), 8)
    with lease(lease_hint):
        start_row = ev.run([{"set": {}, "state": None, "name": "start"}],
                           total=budget, label="optimise")[0]
        start_point = {a.name: float(d.params[a.name].value) for a in axes}
        spent = 1

        def run_points(points: List[Dict[str, float]], label: str
                       ) -> List[Dict[str, Any]]:
            nonlocal spent
            fresh = [p for p in points if _key(p, axes) not in seen]
            fresh = fresh[:max(0, budget - spent)]
            if not fresh:
                return []
            rows = ev.run([{"set": dict(p), "state": None, "name": None}
                           for p in fresh], offset=spent, total=budget,
                          label="optimise %s" % label)
            spent += len(rows)
            for p, row in zip(fresh, rows):
                row["_point"] = p
                seen[_key(p, axes)] = row
                explored.append(row)
            return rows

        def score(row):
            return _better_key(row, sense, okey, enforced)

        # ---- round 1: a coarse grid over the whole space
        discrete = [a for a in axes if a.discrete]
        cont = [a for a in axes if not a.discrete]
        cap_d = 1
        for a in discrete:
            cap_d *= len(a.values)
        per = 7
        while per > 2 and (per ** max(len(cont), 0)) * cap_d > budget * 0.5:
            per -= 1
        axis_values = []
        for a in axes:
            axis_values.append(a.grid(per))
        while True:
            total = 1
            for vals in axis_values:
                total *= len(vals)
            if total <= max(budget - spent, 1) * 0.6 or per <= 2:
                break
            per -= 1
            axis_values = [a.grid(per) for a in axes]
        grid_points = [dict(zip([a.name for a in axes], combo))
                       for combo in itertools.product(*axis_values)]
        first = run_points(grid_points, "grid")
        rounds = 1
        # the start joins the pool of candidates if it lies inside the space
        inside = all(a.lo - 1e-9 <= start_point[a.name] <= a.hi + 1e-9
                     for a in axes)
        start_row["_point"] = dict(start_point)
        candidates = list(first) + ([start_row] if inside else [])
        # ---- refinement: compass search from the best point
        steps = {}
        for a in cont:
            n = len(a.grid(per))
            steps[a.name] = (a.hi - a.lo) / max(n - 1, 1)
        best = min(candidates, key=score) if candidates else None
        stalls = 0
        while best is not None and spent < budget and not ev.cancelled \
                and cont:
            if all(steps[a.name] < max(a.step, 1e-4 * max(abs(a.hi), 1.0))
                   for a in cont):
                break
            centre = best["_point"]
            stencil: List[Dict[str, float]] = []
            for a in axes:
                for v in a.around(centre[a.name], steps.get(a.name, 0.0)):
                    p = dict(centre)
                    p[a.name] = v
                    stencil.append(p)
            rows = run_points(stencil, "refine %d" % (rounds + 1))
            rounds += 1
            if not rows and not ev.cancelled:
                for a in cont:
                    steps[a.name] /= 2
                stalls += 1
                if stalls > 3:
                    break
                continue
            # the best step along each axis, taken together in one move
            # (a pattern move): often several axes improve at once
            moves: Dict[str, Dict[str, Any]] = {}
            for row in rows:
                changed = [a.name for a in axes
                           if row["_point"][a.name] != centre[a.name]]
                if len(changed) == 1 and score(row) < score(best) and (
                        changed[0] not in moves
                        or score(row) < score(moves[changed[0]])):
                    moves[changed[0]] = row
            if len(moves) > 1 and spent < budget and not ev.cancelled:
                combo = dict(centre)
                for name, row in moves.items():
                    combo[name] = row["_point"][name]
                rows = rows + run_points([combo], "pattern move")
            top = min(rows, key=score) if rows else None
            if top is not None and score(top) < score(best):
                best, stalls = top, 0
            else:
                for a in cont:
                    steps[a.name] /= 2
                stalls += 1
                if stalls > 4:
                    break
    if best is not None and "_point" not in best:
        best = None

    # ---- the answer
    feasible = best is not None and _violation(best, enforced) == 0
    failed_by: Dict[str, int] = {}
    for row in explored:
        if _violation(row, enforced) == 0:
            continue
        if not row.get("ok"):
            reason = "does not build"
        else:
            reason = None
            for r in row.get("_results", []):
                if not r.get("pass") and (enforced is None
                                          or r["name"] in enforced) \
                        and not r["name"].startswith("clearance:"):
                    failed_by[r["name"]] = failed_by.get(r["name"], 0) + 1
            if not row.get("valid", True):
                reason = "invalid solid"
        if reason:
            failed_by[reason] = failed_by.get(reason, 0) + 1
    order = sorted(explored, key=score)
    seconds = round(time.perf_counter() - started, 2)
    value = _objective_value(best, okey) if best is not None else None
    start_value = _objective_value(start_row, okey)
    start_ok = _violation(start_row, enforced) == 0
    label = okey.replace("_", " ")
    bits = ["optimise %s" % ("cancelled" if ev.cancelled else "ok"),
            "%s %s" % (sense, label)]
    if feasible:
        bits.append("best %s = %s%s" % (
            ", ".join("%s=%s" % (k, _short(v))
                      for k, v in best["_point"].items()),
            _num(value), " (start %s%s)" % (
                _num(start_value), "" if start_ok else ", fails")
            if start_value is not None else ""))
        if start_value and value is not None and start_ok \
                and start_value != 0:
            bits.append("%+.1f%%" % (100.0 * (value - start_value)
                                     / abs(start_value)))
    else:
        bits.append("NO feasible design in the space")
    bits.append("%d evaluations, %d rounds, %.1f s" % (
        spent, rounds, seconds))
    out: Dict[str, Any] = {
        "doc": entry.handle, "revision": entry.revision,
        "objective": {"sense": sense, "metric": okey},
        "feasible": feasible,
        "evaluations": spent, "rounds": rounds, "budget": budget,
        "seconds": seconds, "cancelled": ev.cancelled,
        "workers": _workers_info(ev),
        "start": _clean(start_row, True),
        "failed_by": failed_by,
        "table": table([start_row] + order, ev.metrics, ev.clearance_names)}
    if best is not None:
        key_ = "best" if feasible else "closest"
        out[key_] = {"vary": best["_point"], "value": value,
                     "row": _clean(best, True)}
        if not feasible:
            bits.append("closest misses: %s" % "; ".join(
                best.get("failing") or [best.get("error", "?")]))
    if detail:
        out["rows"] = [_clean(r, True) for r in order]
    out["not_enforced"] = [n for n in stored
                           if enforced is not None and n not in enforced]
    out["applied"] = False
    if apply and feasible and not ev.cancelled:
        out["applied"] = True
        out.update(_apply(ws, entry, best["_point"], branch, objective))
        bits.append("applied%s" % (" on branch %s" % branch if branch
                                   else ""))
    elif apply:
        out["not_applied"] = ("cancelled" if ev.cancelled else
                              "no feasible design: nothing was changed")
    out["summary"] = " | ".join(bits)
    return out


def _apply(ws: Workspace, entry: Entry, point: Dict[str, float],
           branch: str, objective: str) -> Dict[str, Any]:
    """Write the winning values to the document: one undo step, and with a
    branch name on that branch (made first), checked in after."""
    from . import branch_ops
    out: Dict[str, Any] = {}
    if branch:
        made = branch_ops.branch(ws, doc=entry.handle, action="create",
                                 name=branch)
        out["branch"] = {"name": branch, "created": made.get("summary", "")}
    got = ops.properties(ws, doc=entry.handle, parameters={
        k: v for k, v in point.items()})
    out["revision"] = got["revision"]
    out["rebuild"] = got.get("rebuild")
    if got.get("reqs"):
        out["reqs"] = got["reqs"]
    if branch:
        branch_ops.branch(ws, doc=entry.handle, action="check_in",
                          name="", message="optimise: %s" % objective)
        out["branch"]["checked_in"] = True
    return out
