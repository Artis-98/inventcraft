"""A static HTML dashboard of the Tier 2 benchmark history. Free to run.

Reads every ``runs/*/report.json`` (the harness writes one per run, and
``--judge-dir`` writes one per judged set of sessions) and writes one HTML
file with no external scripts or fonts:

* pass rate per scenario over time (a grid: one row per scenario, one cell
  per run, green passed, red failed, with the tool calls inside),
* the pass rate of each report,
* tool calls and failed calls per run (an inline SVG chart),
* a table of every run: model, calls, failed calls, tokens, cost, seconds,
  and the messages of the calls that failed.

    .venv\\Scripts\\python.exe tests\\tier2\\dashboard.py
    .venv\\Scripts\\python.exe tests\\tier2\\dashboard.py --out some.html

Cost and seconds are blank for runs judged from session transcripts, which
do not record them.
"""

from __future__ import annotations

import argparse
import glob
import html
import json
import os
import sys
from typing import Any, Dict, List, Optional

HERE = os.path.dirname(os.path.abspath(__file__))
RUNS = os.path.join(HERE, "runs")


def load_reports(runs: str = RUNS) -> List[Dict[str, Any]]:
    """Every report, oldest first, each with its folder name as ``label``."""
    out = []
    for path in sorted(glob.glob(os.path.join(runs, "*", "report.json"))):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict) or not isinstance(data.get("runs"),
                                                        list):
            continue
        data["label"] = os.path.basename(os.path.dirname(path))
        out.append(data)
    out.sort(key=lambda r: (str(r.get("started") or r["label"]), r["label"]))
    return out


def tokens_of(score: Dict[str, Any]) -> Optional[int]:
    """Tokens that were not read from cache: input plus output plus what
    was written to the cache. None when the run did not say."""
    t = score.get("tokens")
    if not isinstance(t, dict):
        return None
    got = [t.get(k) for k in ("input", "output", "cache_write")
           if isinstance(t.get(k), (int, float))]
    return int(sum(got)) if got else None


def flatten(reports: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """One row per scenario run."""
    rows = []
    for n, rep in enumerate(reports):
        for run in rep["runs"]:
            sc = run.get("score") or {}
            verdict = run.get("verdict") or {}
            rows.append({
                "report": rep["label"], "index": n,
                "started": str(rep.get("started") or ""),
                "model": str(rep.get("model") or ""),
                "scenario": run.get("scenario", "?"),
                "passed": bool(verdict.get("pass")),
                "calls": sc.get("server_calls", sc.get("tool_calls")),
                "all_calls": sc.get("tool_calls"),
                "failed": sc.get("failed_calls"),
                "turns": sc.get("turns"),
                "tokens": tokens_of(sc),
                "cost": sc.get("cost_usd"),
                "seconds": run.get("seconds"),
                "errors": [str(e) for e in (sc.get("errors") or [])][:4],
            })
    return rows


def _fmt(value: Any, spec: str = "{}") -> str:
    return "" if value is None else spec.format(value)


def _grid(rows: List[Dict[str, Any]], reports: List[Dict[str, Any]]) -> str:
    scenarios = sorted({r["scenario"] for r in rows})
    head = "".join("<th title=%s>%d</th>" % (
        html.escape(json.dumps(rep["label"])), i + 1)
        for i, rep in enumerate(reports))
    lines = []
    for name in scenarios:
        cells, passed, total = [], 0, 0
        for i in range(len(reports)):
            hit = [r for r in rows if r["scenario"] == name
                   and r["index"] == i]
            if not hit:
                cells.append('<td class="none"></td>')
                continue
            r = hit[0]
            total += 1
            passed += 1 if r["passed"] else 0
            cells.append('<td class="%s" title="%s">%s</td>' % (
                "ok" if r["passed"] else "bad",
                html.escape("%s: %s, %s calls, %s failed" % (
                    r["report"], "passed" if r["passed"] else "failed",
                    _fmt(r["calls"]), _fmt(r["failed"]))),
                _fmt(r["calls"])))
        rate = ("%d %%" % round(100 * passed / total)) if total else ""
        lines.append("<tr><th class='row'>%s</th>%s<td class='rate'>%s "
                     "<span class='dim'>(%d/%d)</span></td></tr>" % (
                         html.escape(name), "".join(cells), rate, passed,
                         total))
    return ("<table class='grid'><tr><th></th>%s<th>pass rate</th></tr>%s"
            "</table>" % (head, "".join(lines)))


def _chart(reports: List[Dict[str, Any]], rows: List[Dict[str, Any]]) -> str:
    """Per report: mean tool calls (bars) and failed calls (line), one
    inline SVG."""
    if not reports:
        return ""
    data = []
    for i, rep in enumerate(reports):
        mine = [r for r in rows if r["index"] == i]
        calls = [r["calls"] for r in mine if r["calls"] is not None]
        failed = [r["failed"] for r in mine if r["failed"] is not None]
        data.append((sum(calls) / len(calls) if calls else 0,
                     sum(failed) / len(failed) if failed else 0,
                     sum(1 for r in mine if r["passed"]), len(mine)))
    w, h, pad = max(360, 90 * len(data) + 60), 190, 34
    top = max([d[0] for d in data] + [1])
    step = (w - 2 * pad) / max(len(data), 1)
    out = ['<svg viewBox="0 0 %d %d" role="img" aria-label="Mean tool calls '
           'and failed calls per report" class="chart">' % (w, h)]
    out.append('<line x1="%d" y1="%d" x2="%d" y2="%d" class="axis"/>' % (
        pad, h - pad, w - pad, h - pad))
    pts = []
    for i, (c, f, ok, n) in enumerate(data):
        x = pad + i * step + step * 0.15
        bw = step * 0.7
        bh = (h - 2 * pad) * c / top
        out.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" '
                   'class="bar"><title>report %d: %.1f calls on average, '
                   '%d of %d passed</title></rect>' % (
                       x, h - pad - bh, bw, bh, i + 1, c, ok, n))
        out.append('<text x="%.1f" y="%d" class="lbl" text-anchor="middle">'
                   '%d</text>' % (x + bw / 2, h - pad + 14, i + 1))
        out.append('<text x="%.1f" y="%.1f" class="val" text-anchor="middle">'
                   '%.0f</text>' % (x + bw / 2, h - pad - bh - 4, c))
        pts.append("%.1f,%.1f" % (x + bw / 2,
                                  h - pad - (h - 2 * pad) * f / top))
    out.append('<polyline points="%s" class="fail"/>' % " ".join(pts))
    for p in pts:
        x, y = p.split(",")
        out.append('<circle cx="%s" cy="%s" r="3" class="failpt"/>' % (x, y))
    out.append('<text x="%d" y="14" class="lbl">bars: mean tool calls per '
               'scenario; line: mean failed calls</text>' % pad)
    out.append("</svg>")
    return "".join(out)


def _table(rows: List[Dict[str, Any]]) -> str:
    head = ("report", "scenario", "result", "model", "calls", "failed",
            "turns", "tokens", "cost $", "seconds", "what failed")
    body = []
    for r in reversed(rows):
        body.append(
            "<tr class='%s'><td>%s</td><td>%s</td><td>%s</td><td>%s</td>"
            "<td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td>"
            "<td>%s</td><td class='msg'>%s</td></tr>" % (
                "ok" if r["passed"] else "bad", html.escape(r["report"]),
                html.escape(r["scenario"]),
                "pass" if r["passed"] else "FAIL",
                html.escape(r["model"][:28]), _fmt(r["calls"]),
                _fmt(r["failed"]), _fmt(r["turns"]),
                _fmt(r["tokens"], "{:,}"), _fmt(r["cost"], "{:.3f}"),
                _fmt(r["seconds"], "{:.0f}"),
                html.escape(" | ".join(r["errors"])[:260])))
    return "<table class='runs'><tr>%s</tr>%s</table>" % (
        "".join("<th>%s</th>" % h for h in head), "".join(body))


CSS = """
:root{--bg:#fafaf8;--fg:#1c1c1a;--dim:#6b6b66;--line:#d9d8d2;--ok:#cfe8d2;
--okfg:#1d5a2b;--bad:#f3cfcb;--badfg:#8a2018;--bar:#8fb4d9;--fail:#c4552b}
@media (prefers-color-scheme:dark){:root{--bg:#161615;--fg:#e8e7e2;
--dim:#9a9990;--line:#38372f;--ok:#21432a;--okfg:#a8dbb3;--bad:#4a2420;
--badfg:#f2b5ae;--bar:#4a7aa8;--fail:#ee8a5e}}
body{background:var(--bg);color:var(--fg);font:15px/1.45 system-ui,
sans-serif;margin:0 auto;max-width:1100px;padding:16px}
h1{font-size:1.5rem;margin:.2em 0}h2{font-size:1.1rem;margin:1.6em 0 .5em}
.dim{color:var(--dim)}table{border-collapse:collapse;width:100%}
th,td{border:1px solid var(--line);padding:4px 8px;text-align:left}
.grid td{text-align:center;min-width:34px}.grid th.row{white-space:nowrap}
td.ok{background:var(--ok);color:var(--okfg)}
td.bad{background:var(--bad);color:var(--badfg)}
td.none{background:transparent}.rate{white-space:nowrap}
tr.ok td:nth-child(3){color:var(--okfg)}tr.bad td:nth-child(3){
color:var(--badfg);font-weight:600}.msg{font-size:.85em;color:var(--dim)}
.wrap{overflow-x:auto}.chart{width:100%;max-width:640px;height:auto}
.chart .axis{stroke:var(--line)}.chart .bar{fill:var(--bar)}
.chart .fail{stroke:var(--fail);fill:none;stroke-width:2}
.chart .failpt{fill:var(--fail)}.chart text{fill:var(--dim);font-size:11px}
.chart .val{fill:var(--fg)}
"""


def render(reports: List[Dict[str, Any]]) -> str:
    rows = flatten(reports)
    n_pass = sum(1 for r in rows if r["passed"])
    cost = [r["cost"] for r in rows if isinstance(r["cost"], (int, float))]
    toks = [r["tokens"] for r in rows if r["tokens"] is not None]
    summary = "%d reports, %d scenario runs, %d passed (%s)" % (
        len(reports), len(rows), n_pass,
        ("%d %%" % round(100 * n_pass / len(rows))) if rows else "n/a")
    if cost:
        summary += "; total cost $%.2f over %d runs that recorded it" % (
            sum(cost), len(cost))
    if toks:
        summary += "; %s tokens (without cache reads) over %d runs" % (
            "{:,}".format(sum(toks)), len(toks))
    legend = "".join("<li>%d &nbsp;%s <span class='dim'>%s</span></li>" % (
        i + 1, html.escape(rep["label"]),
        html.escape(str(rep.get("model") or "")[:40]))
        for i, rep in enumerate(reports))
    return """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>InventCraft Tier 2</title><style>%s</style></head><body>
<h1>InventCraft Tier 2 benchmarks</h1>
<p class="dim">%s</p>
<h2>Pass rate per scenario over time</h2>
<p class="dim">One column per report (oldest left), the number is the tool
calls the agent made. Green passed the verdict, red failed it.</p>
<div class="wrap">%s</div>
<ol class="dim">%s</ol>
<h2>Tool calls and failed calls per report</h2>%s
<h2>Every run</h2><div class="wrap">%s</div>
</body></html>
""" % (CSS, html.escape(summary), _grid(rows, reports), legend,
       _chart(reports, rows), _table(rows))


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--runs", default=RUNS, help="the folder of run reports")
    ap.add_argument("--out", default=os.path.join(RUNS, "dashboard.html"))
    args = ap.parse_args(argv)
    reports = load_reports(args.runs)
    if not reports:
        print("no runs/*/report.json under %s" % args.runs)
        return 1
    page = render(reports)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8", newline="\n") as f:
        f.write(page)
    rows = flatten(reports)
    print("%s: %d reports, %d runs, %d passed" % (
        args.out, len(reports), len(rows), sum(r["passed"] for r in rows)))
    return 0


if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(errors="replace")
        except Exception:
            pass
    sys.exit(main())
