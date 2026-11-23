"""The server's safety policy and the Tier 2 dashboard, in process, with no
host and no MCP client (the same policy end to end, through a real client,
is the ``safety`` section of test_mcp_server.py).

* file access: roots and folders, ``..`` escapes, other drives, URIs;
* the overwrite rule: what keeps an old version and what does not;
* paging and the byte budget of long answers;
* the image size cap;
* the Tier 2 dashboard turns reports into one static page with no
  scripts.
"""
import asyncio
import json
import os
import sys
import tempfile

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(errors="replace")
    except Exception:
        pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests", "tier2"))

from datum.mcp import safety  # noqa: E402

FAILS = []


def check(name, cond, extra=""):
    print(("  PASS  " if cond else "  FAIL  ") + name
          + (("  " + str(extra)) if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


work = tempfile.mkdtemp(prefix="datum_safety_")
inner = os.path.join(work, "proj")
os.makedirs(inner)

print("file access")
check("a path inside a folder is inside", safety.inside(
    os.path.join(inner, "a.icpart"), inner))
check("the folder itself is", safety.inside(inner, inner))
check("a sibling with the same prefix is not", not safety.inside(
    inner + "_other\\a.icpart", inner))
check("a .. escape is not", not safety.inside(
    os.path.join(inner, "..", "x.icpart"), inner))
check("another drive is not (and does not raise)", not safety.inside(
    "Z:\\x\\a.icpart" if os.name == "nt" else "/nonexistent/x", inner))
bad = safety.check_paths([os.path.join(work, "x.step")], [inner])
check("outside the roots is PATH_NOT_ALLOWED with the allowed list",
      bad and bad["kind"] == "PATH_NOT_ALLOWED" and bad["allowed"]
      and bad["source"] == "the client's roots" and bad["hints"], bad)
check("inside a root passes", safety.check_paths(
    [os.path.join(inner, "x.step")], [inner]) is None)
check("empty and non-string values are not paths", safety.check_paths(
    ["", None, 5], [inner]) is None)
check("with no roots the project folder is the rule",
      safety.check_paths([os.path.join(safety.PROJECT_DIR, "a.icpart")],
                         None) is None
      and safety.check_paths([os.path.join(work, "a.icpart")], None)
      is not None)
safety.add_allow_dirs([inner])
check("--allow-dir adds a folder", safety.check_paths(
    [os.path.join(inner, "a.icpart")], None) is None)
check("and still adds it when the client gives roots", safety.check_paths(
    [os.path.join(inner, "a.icpart")], [os.path.join(work, "elsewhere")])
    is None)
safety.ALLOW_DIRS.clear()
if os.name == "nt":
    got = safety.root_paths(["file:///C:/Users/me/My%20Parts"])
    check("a file:// root becomes a Windows folder",
          got == ["C:\\Users\\me\\My Parts"] or got == ["C:/Users/me/My "
                                                        "Parts"], got)
else:
    check("a file:// root becomes a folder", safety.root_paths(
        ["file:///home/me/My%20Parts"]) == ["/home/me/My Parts"])
check("a root that is not a file URI is ignored", safety.root_paths(
    ["https://example.com/x"]) == [])
check("build ops: only import ops name a file", safety.gate_ops([
    {"op": "extrude"}, {"op": "import", "path": "a.step"},
    {"op": "import"}]) == ["a.step"])


class NoClient:
    """A request context whose session cannot be asked anything."""
    session = None


check("a client that cannot be asked gives no roots",
      asyncio.run(safety.client_roots(NoClient())) is None)
check("and the gate then uses the project folder", asyncio.run(
    safety.gate(NoClient(), os.path.join(work, "z.icpart"))) is not None)

print("overwrite")
exists = os.path.join(work, "old.step")
open(exists, "w").write("x")
check("a missing target never asks", asyncio.run(safety.confirm_overwrite(
    NoClient(), os.path.join(work, "new.step"), True, False)) is None)
check("without overwrite there is nothing to confirm", asyncio.run(
    safety.confirm_overwrite(NoClient(), exists, False, False)) is None)
r = asyncio.run(safety.confirm_overwrite(NoClient(), exists, True, False))
check("overwriting a file with no old version needs the user: "
      "CONFIRM_REQUIRED", r and r["kind"] == "CONFIRM_REQUIRED"
      and "confirm=true" in " ".join(r["hints"]), r)
check("confirm=true is the user's yes", asyncio.run(
    safety.confirm_overwrite(NoClient(), exists, True, True)) is None)
check("a step file keeps no old version", not safety.keeps_old_version(
    exists))
check("a part does (OldVersions)", safety.keeps_old_version(
    os.path.join(work, "a.icpart")))

print("budgets")
big = {"summary": "s", "features": [{"id": i, "name": "F%d" % i,
                                      "summary": "x" * 60}
                                     for i in range(500)]}
page = safety.page(big, ("features",), 0, 0, 200)
check("a long list is paged to the default limit", len(page["features"])
      <= 200 and page["paging"]["features"]["next_offset"] is not None
      and "truncated" in page, page.get("paging"))
check("and held to the byte budget", safety.size_of(page) <= safety.MAX_BYTES
      + 400, safety.size_of(page))
nxt = page["paging"]["features"]["next_offset"]
page2 = safety.page(big, ("features",), nxt, 20, 200)
check("the next page starts at next_offset", page2["features"][0]["id"]
      == nxt and page2["paging"]["features"]["offset"] == nxt)
last = safety.page(big, ("features",), 490, 50, 200)
check("the last page says there is no more", len(last["features"]) == 10
      and "truncated" not in last and last["paging"]["features"][
          "next_offset"] is None)
small = {"summary": "s", "features": [{"id": 1}]}
check("a small answer is returned unchanged", safety.page(
    small, ("features",), 0, 0, 200) == small)
check("an error result is not touched", safety.page(
    "failure", ("features",)) == "failure")
many = {"summary": "s", "a": [{"v": "x" * 200}] * 300, "b": [1, 2, 3]}
cut = safety.page(many, (), 0, 0, 0, also=("a",))
check("lists named only for the budget are cut to fit", safety.size_of(cut)
      <= safety.MAX_BYTES + 400 and len(cut["a"]) < 300 and cut["b"]
      == [1, 2, 3], safety.size_of(cut))
check("text is cut at the last net", len(safety.cap_text("x" * 500000))
      < 400100)
check("a render size is capped", safety.clamp_side(9000, 800)
      == (safety.MAX_IMAGE_SIDE, True)
      and safety.clamp_side(640, 800) == (640, False)
      and safety.clamp_side("junk", 800) == (800, False))

print("dashboard")
import dashboard  # noqa: E402

runs = os.path.join(work, "runs")
for stamp, passed, calls in (("20260101-000000", False, 20),
                             ("20260102-000000", True, 9)):
    folder = os.path.join(runs, stamp)
    os.makedirs(folder)
    with open(os.path.join(folder, "report.json"), "w") as f:
        json.dump({"started": stamp, "model": "haiku", "runs": [
            {"scenario": "bracket", "verdict": {"pass": passed},
             "score": {"server_calls": calls, "failed_calls": 2 if
                       not passed else 0, "turns": 5,
                       "tokens": {"input": 10, "output": 100,
                                  "cache_write": 50, "cache_read": 9999},
                       "cost_usd": 0.12, "errors": ["<b>boom</b>"]},
             "seconds": 31.0}]}, f)
reports = dashboard.load_reports(runs)
check("the reports are read oldest first", [r["label"] for r in reports]
      == ["20260101-000000", "20260102-000000"])
rows = dashboard.flatten(reports)
check("each run is a row with its numbers", len(rows) == 2 and rows[1][
    "passed"] and rows[1]["calls"] == 9 and rows[0]["failed"] == 2
      and rows[0]["tokens"] == 160 and rows[0]["cost"] == 0.12, rows)
page = dashboard.render(reports)
check("one static page: no scripts, no external files", "<script" not in
      page and "http://" not in page and "https://" not in page
      and page.startswith("<!doctype html>"))
check("it shows the pass rate, the chart and the runs", "50 %" in page
      and "<svg" in page and "bracket" in page and "$0.24" in page)
check("text from reports is escaped", "<b>boom</b>" not in page
      and "&lt;b&gt;boom" in page)
out = os.path.join(work, "dash.html")
check("main writes the file and exits 0", dashboard.main(
    ["--runs", runs, "--out", out]) == 0 and os.path.getsize(out) > 1000)
check("no reports is a plain failure", dashboard.main(
    ["--runs", os.path.join(work, "none"), "--out", out]) == 1)

print()
if FAILS:
    print("%d FAILURES: %s" % (len(FAILS), ", ".join(FAILS)))
    sys.exit(1)
print("all mcp safety tests passed")
