r"""Tier 2 of the MCP plan's evaluation: a real agent, a natural-language
request, and a verdict that does not ask the agent whether it succeeded.

ON DEMAND ONLY. Every run spends model tokens, which cost money; this is
never part of tests\run.py and must not be added to it.

    .venv\Scripts\python.exe tests\tier2\run_tier2.py --list
    .venv\Scripts\python.exe tests\tier2\run_tier2.py --check-references
    .venv\Scripts\python.exe tests\tier2\run_tier2.py bracket din934_nut
    .venv\Scripts\python.exe tests\tier2\run_tier2.py --all --model haiku
    .venv\Scripts\python.exe tests\tier2\run_tier2.py bracket --record

How a run goes:

1. A scenario (``scenarios/*.json``) is a request in plain words and a
   verdict. The agent is ``claude -p`` (Claude Code, headless) with only
   this server (``--strict-mcp-config``, ``python -m datum.mcp``) and the
   MCP resource readers as tools, started in an empty folder, so nothing
   of this repository or of the user's settings steers it. It is told to
   save the part to a path in that folder; nothing else is added to the
   request.
2. The harness opens the saved file in a server of its own and checks it:
   ``inspect(expected)`` (or any one of several), requirements the
   harness sets on its copy (hole counts, mass, one size), feature types
   the tree must hold, a least number of parameters, the agent's own
   requirements passing, and that the model is parametric: every numeric
   parameter nudged +10 % still builds one valid solid (build123d-mcp's
   design audit, borrowed).
3. The score: the verdict, tool calls (by tool), failed calls, turns,
   tokens, dollars and seconds, from Claude Code's stream-json. Each run
   writes its transcript; the whole run writes ``report.json`` and
   ``report.md`` under ``tests/tier2/runs/<time>/`` (git-ignored).
4. ``--record`` turns a passing run into a Tier 1 replay,
   ``tests/mcp_replays/tier2_<scenario>.json``: the agent's own tool
   calls, each expected to fail or succeed as it did, and the verdict's
   inspect at the end. Wins become regression tests that cost nothing.

``--check-references`` builds each scenario's reference ops (no agent)
and checks them against the verdict, so a verdict is known to be
reachable before money is spent on it.

Scenario keys beyond prompt, verdict and reference (all optional):
``tools`` (the server's --tools, for the agent and for the judge:
"default,+drawing"), ``save_as`` (the extension of the file to judge:
.icpart, .icasm or .icdraw; anything but .icpart is made in a folder of its
own, ``<run>/<scenario>/``, written ``{dir}`` in the prompt, which also
holds the parts and exports the agent makes), ``fixtures`` (files the
agent starts from, built by the harness, free: ``{dir}`` again), and in the
verdict ``assembly``, ``drawing``, ``flat`` (a sheet metal part's flat
pattern), ``cut_list`` and ``files`` (exports that must exist in ``{dir}``).
A reference may be ``{"calls": [{tool, args}, ...]}``: a short run of tool
calls in a scratch folder (``{WORK}`` in paths), after which the open
document is judged.

``--judge-dir DIR`` is the session-driven route: some other agent (a
desktop Claude Code session, say) was given the prompt and saved
``DIR/<scenario>.icpart``; the harness judges those, scores the
``DIR/<scenario>.jsonl`` session transcripts beside them, and reports
(and with ``--record`` records) as above, spending nothing.
``--prepare DIR`` makes the folders and fixtures for those sessions and
writes each scenario's full prompt to ``DIR/prompts/<scenario>.txt``.
"""

from __future__ import annotations

import argparse
import asyncio
import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Any, Dict, List, Optional, Tuple

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(errors="replace")
    except Exception:
        pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
SCENARIOS = os.path.join(HERE, "scenarios")
RUNS = os.path.join(HERE, "runs")
REPLAYS = os.path.join(ROOT, "tests", "mcp_replays")
sys.path.insert(0, ROOT)

from mcp import ClientSession  # noqa: E402
from mcp.client.stdio import StdioServerParameters, stdio_client  # noqa: E402

SERVER = "inventcraft"
TOOL_PREFIX = "mcp__%s__" % SERVER
# the agent may read the server's resources (the guides), and nothing else
# of Claude Code's own tools
RESOURCE_TOOLS = ["ListMcpResourcesTool", "ReadMcpResourceTool"]
SAVE_LINE = ("\n\nWhen the part is finished, save it with save_document to "
             "this absolute path: {save}")


# ---------------------------------------------------------------- helpers


def load(name: str) -> Dict[str, Any]:
    with open(os.path.join(SCENARIOS, name + ".json"), encoding="utf-8") as f:
        return json.load(f)


def names() -> List[str]:
    return sorted(os.path.splitext(os.path.basename(p))[0]
                  for p in glob.glob(os.path.join(SCENARIOS, "*.json")))


def texts(result) -> List[str]:
    return [c.text for c in result.content if getattr(c, "type", "") == "text"]


def payload(result) -> Dict[str, Any]:
    for t in reversed(texts(result)):
        try:
            value = json.loads(t)
        except ValueError:
            continue
        if isinstance(value, dict):
            return value
    return {}


def server_params(tools: str = "", allow: str = ""
                  ) -> StdioServerParameters:
    """The server a judge (or fixture builder) talks to: the scenario's
    tool groups, and the folder its files are in allowed (the server only
    touches the project folder and what it is told, datum/mcp/safety.py)."""
    args = ["-m", "datum.mcp"] + (["--tools", tools] if tools else [])
    env = dict(os.environ, PYTHONPATH=ROOT)
    if allow:
        env["INVENTCRAFT_ALLOW_DIRS"] = allow
    return StdioServerParameters(command=sys.executable, args=args,
                                 cwd=ROOT, env=env)


def layout(sc: Dict[str, Any], folder: str) -> Tuple[str, str, str]:
    """(the scenario's own folder, the file to judge, the prompt) for a
    run whose files are under ``folder``. A plain part is saved straight in
    ``folder``; anything else gets ``folder/<scenario>/``."""
    ext = sc.get("save_as", ".icpart")
    if ext == ".icpart" and not (sc.get("fixtures") or sc.get("tools")
                                 or sc.get("multi")):
        own = folder
    else:
        own = os.path.join(folder, sc["name"])
    save = os.path.join(own, sc["name"] + ext)
    what = {".icpart": "part", ".icasm": "assembly",
            ".icdraw": "drawing"}.get(ext, "file")
    prompt = sc["prompt"].replace("{dir}", own) + SAVE_LINE.replace(
        "the part", "the " + what).format(save=save)
    return own, save, prompt


async def make_fixtures(sc: Dict[str, Any], own: str) -> None:
    """The files a scenario starts the agent from, built by the harness."""
    if not sc.get("fixtures"):
        return
    os.makedirs(own, exist_ok=True)
    async with stdio_client(server_params(allow=own)) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            for fx in sc["fixtures"]:
                await session.call_tool("new_document", {})
                r, _b = await _call(session, "build", {"ops": fx["ops"]})
                if r.is_error:
                    raise RuntimeError("fixture %s: %s" % (
                        fx["file"], texts(r)[:1]))
                target = os.path.join(own, fx["file"])
                tool = "save_document" if target.endswith(".icpart") \
                    else "export"
                r, _b = await _call(session, tool, {"path": target,
                                                    "overwrite": True,
                                                    "confirm": True})
                if r.is_error:
                    raise RuntimeError("fixture %s: %s" % (
                        fx["file"], texts(r)[:1]))
                await _call(session, "close_document", {})


# ---------------------------------------------------------------- verdict


async def _call(session, tool, args):
    r = await session.call_tool(tool, args)
    return r, payload(r)


async def judge(session, verdict: Dict[str, Any],
                folder: str = "") -> Dict[str, Any]:
    """Check the open document against a verdict. Every check is listed
    with its outcome; the verdict passes when all of them pass. ``folder``
    is where ``files`` are looked for."""
    checks: List[Dict[str, Any]] = []

    def add(name, ok, detail=None):
        checks.append({"check": name, "pass": bool(ok),
                       "detail": detail})

    _r, tree = await _call(session, "model_tree", {})
    kind = tree.get("type", "part")
    if kind == "assembly":
        await judge_assembly(session, verdict, add)
    elif kind == "drawing":
        await judge_drawing(session, tree, verdict, add)
    else:
        await judge_part(session, verdict, add)
    for name in verdict.get("files", []):
        path = os.path.join(folder, name)
        size = os.path.getsize(path) if os.path.isfile(path) else 0
        add("the file %s was written" % name, size > 0, path)
    return {"pass": all(c["pass"] for c in checks), "checks": checks}


async def judge_assembly(session, verdict, add) -> None:
    want = verdict.get("assembly") or {}
    _r, tree = await _call(session, "model_tree", {})
    occ, cons = tree.get("occurrences") or [], tree.get("constraints") or []
    if "occurrences" in want:
        add("%d components placed" % want["occurrences"],
            len(occ) == want["occurrences"], [o.get("name") for o in occ])
    if "min_constraints" in want:
        add("at least %d constraints" % want["min_constraints"],
            len(cons) >= want["min_constraints"], len(cons))
    r, chk = await _call(session, "assembly_check", {})
    add("the assembly solves with nothing failed",
        not r.is_error and chk.get("ok") and not chk.get("failed"),
        chk.get("failed"))
    if "max_dof" in want:
        add("at most %s degrees of freedom left" % want["max_dof"],
            chk.get("dof", 99) <= want["max_dof"], chk.get("dof"))
    if "max_interference" in want:
        found = chk.get("interference") or {}
        add("interference between parts: at most %d" % want[
            "max_interference"], found.get("count", 0) <= want[
                "max_interference"], (found.get("pairs") or [])[:2])
    if "bom_lines" in want:
        r, bom = await _call(session, "bom", {})
        lines = (bom.get("totals") or {}).get("line_items")
        add("the bill of materials has %d lines" % want["bom_lines"],
            lines == want["bom_lines"], lines)
    if "cut_list" in want:
        cl = want["cut_list"]
        r, body = await _call(session, "cut_list", {})
        add("the cut list works", not r.is_error, texts(r)[:1])
        if "pieces" in cl:
            add("the cut list has %d pieces" % cl["pieces"],
                body.get("pieces") == cl["pieces"], body.get("pieces"))
        if "profiles" in cl:
            got = sorted((body.get("totals") or {}).keys())
            add("cut list profiles %s" % cl["profiles"],
                got == sorted(cl["profiles"]), got)
    if want.get("render", True):
        r, _b = await _call(session, "render_view", {"width": 300,
                                                     "height": 200})
        add("the assembly renders", not r.is_error, texts(r)[:1])


async def judge_drawing(session, tree, verdict, add) -> None:
    want = verdict.get("drawing") or {}
    sheets = tree.get("sheets") or []
    views = [v for sh in sheets for v in sh.get("views", [])]
    notes = [a for sh in sheets for a in sh.get("annotations", [])]
    if "min_views" in want:
        add("at least %d views" % want["min_views"],
            len(views) >= want["min_views"], len(views))
    if "min_annotations" in want:
        add("at least %d dimensions and notes" % want["min_annotations"],
            len(notes) >= want["min_annotations"], len(notes))
    if want.get("section"):
        add("a section view", any("section" in str(v.get("type", "")).lower()
                                  or "section" in str(v.get("kind", "")).lower()
                                  for v in views), [v.get("type") for v in
                                                    views][:6])
    if "size" in want:
        add("the sheet is %s" % want["size"],
            any(str(sh.get("size")) == want["size"] for sh in sheets),
            [sh.get("size") for sh in sheets])
    r, _b = await _call(session, "drawing_render", {"width": 400})
    add("the drawing renders", not r.is_error, texts(r)[:1])


async def judge_part(session, verdict, add) -> None:

    # the shape: one expected, or any one of several
    options = [verdict] if "inspect" in verdict else verdict.get("any_of",
                                                                [])
    if options:
        results = []
        for opt in options:
            _r, body = await _call(session, "inspect",
                                   {"expected": opt["inspect"]})
            results.append(body.get("verdict", {}))
        best = next((v for v in results if v.get("pass")), results[0])
        add("inspect(expected)", best.get("pass"),
            {k: v for k, v in best.items() if k != "pass"})

    # the agent's own requirements, read before the harness adds its own
    _r, own = await _call(session, "requirements", {})
    own_items = own.get("results") or []
    add("the agent's requirements pass", all(r.get("pass") for r in
                                            own_items),
        [r.get("text") for r in own_items if not r.get("pass")])

    if verdict.get("requirements"):
        r, body = await _call(session, "requirements",
                              {"set": verdict["requirements"]})
        if r.is_error:
            add("verdict requirements", False, texts(r)[:1])
        else:
            for item in body.get("results", []):
                if str(item.get("name", "")).startswith("t2 "):
                    add("requirement " + item["name"], item.get("pass"),
                        item.get("text"))
        await _call(session, "requirements", {"remove": [
            q["name"] for q in verdict["requirements"]]})

    _r, ir = await _call(session, "read_ir", {})
    ops = ir.get("ops") or []
    kinds = {o.get("op") for o in ops}
    for want in verdict.get("features", []):
        add("the tree has a %s feature" % want, want in kinds, sorted(kinds))
    if verdict.get("features_any"):
        add("the tree has one of %s" % ", ".join(verdict["features_any"]),
            kinds & set(verdict["features_any"]), sorted(kinds))
    params = [o for o in ops if o.get("op") == "parameter"]
    if "min_parameters" in verdict:
        add("at least %d parameters" % verdict["min_parameters"],
            len(params) >= verdict["min_parameters"],
            [p.get("name") for p in params])

    if verdict.get("parametric"):
        broken = []
        for p in params[:10]:
            try:
                value = float(p.get("value"))
            except (TypeError, ValueError):
                continue          # an expression follows the others
            if value == 0:
                continue
            nudged = round(value * 1.1, 6)
            r, body = await _call(session, "properties", {
                "parameters": {p["name"]: str(nudged)}})
            if r.is_error:
                broken.append("%s=%s: %s" % (p["name"], nudged,
                                             (texts(r) or ["?"])[0][:120]))
                continue
            _r2, ins = await _call(session, "inspect", {})
            if ins.get("solids") != 1 or not ins.get("valid"):
                broken.append("%s=%s: %s solids, valid %s" % (
                    p["name"], nudged, ins.get("solids"), ins.get("valid")))
            await _call(session, "properties", {
                "parameters": {p["name"]: str(p.get("value"))}})
        add("every parameter +10 %% still builds one valid solid",
            not broken, broken)

    if verdict.get("not_features"):
        add("the tree has no %s feature" % ", ".join(
            verdict["not_features"]), not kinds & set(
                verdict["not_features"]), sorted(kinds))
    if verdict.get("flat"):
        want = verdict["flat"]
        r, body = await _call(session, "flat_pattern", {})
        add("the part unfolds", not r.is_error, texts(r)[:1])
        bends = body.get("bends") or []
        if "bends" in want:
            add("%d bends" % want["bends"], len(bends) == want["bends"],
                len(bends))
        if "length" in want:
            got = body.get("length")
            add("flat length %s" % want["length"], isinstance(got, (int,
                float)) and abs(got - want["length"]) <= want.get(
                    "tolerance", 0.5), got)
        r, chk = await _call(session, "sheet_check", {})
        add("sheet_check has no error findings", not any(
            f.get("level") == "error" for f in chk.get("findings", [])),
            [f for f in chk.get("findings", []) if f.get("level") == "error"])
    if verdict.get("cut_list"):
        want = verdict["cut_list"]
        r, body = await _call(session, "cut_list", {})
        add("the cut list works", not r.is_error, texts(r)[:1])
        if "pieces" in want:
            add("the cut list has %d pieces" % want["pieces"],
                body.get("pieces") == want["pieces"], body.get("pieces"))


async def judge_file(path: str, verdict: Dict[str, Any],
                     tools: str = "") -> Dict[str, Any]:
    if not os.path.isfile(path):
        return {"pass": False, "checks": [{
            "check": "the file was saved", "pass": False, "detail": path}]}
    folder = os.path.dirname(os.path.abspath(path))
    async with stdio_client(server_params(tools, folder)) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            r, body = await _call(session, "open_document", {"path": path})
            if r.is_error:
                return {"pass": False, "checks": [{
                    "check": "the saved part opens", "pass": False,
                    "detail": texts(r)[:1]}]}
            out = await judge(session, verdict, folder)
            out["checks"].insert(0, {"check": "the file was saved",
                                     "pass": True, "detail": None})
            return out


async def check_references(which: List[str]) -> int:
    bad = 0
    for name in which:
        sc = load(name)
        ref = sc.get("reference")
        if not ref:
            print("%-22s no reference" % name)
            continue
        work = tempfile.mkdtemp(prefix="ic_ref_%s_" % name)
        own, _save, _prompt = layout(dict(sc, name=name), work)
        os.makedirs(own, exist_ok=True)
        folder = own.replace("\\", "/")
        try:
            await make_fixtures(dict(sc, name=name), own)
            async with stdio_client(server_params(
                    sc.get("tools", ""), work)) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    failed = []
                    if "calls" in ref:
                        for step in ref["calls"]:
                            args = json.loads(json.dumps(step.get(
                                "args", {})).replace("{WORK}", folder))
                            r, _b = await _call(session, step["tool"], args)
                            if r.is_error != bool(step.get("error")):
                                failed.append("%s: %s" % (
                                    step["tool"], texts(r)[:1]))
                    else:
                        if "replay" in ref:
                            with open(os.path.join(REPLAYS, ref["replay"]),
                                      encoding="utf-8") as f:
                                ops = json.load(f)["calls"][ref["call"]][
                                    "args"]["ops"]
                        else:
                            ops = ref["ops"]
                        await _call(session, "new_document", {})
                        r, _b = await _call(session, "build", {"ops": ops})
                        if r.is_error:
                            failed.append("build: %s" % texts(r)[:1])
                        if ref.get("material"):
                            await _call(session, "properties",
                                        {"material": ref["material"]})
                    result = await judge(session, sc["verdict"], own)
                    ok = result["pass"] and not failed
                    bad += not ok
                    print("%-22s reference %s" % (name, "passes" if ok
                                                   else "FAILS"))
                    for f in failed:
                        print("    x call %s" % f)
                    for c in result["checks"]:
                        if not c["pass"]:
                            print("    x %s: %s" % (c["check"], c["detail"]))
        finally:
            shutil.rmtree(work, ignore_errors=True)
    return 1 if bad else 0


# ---------------------------------------------------------------- agent


def claude_exe() -> Optional[str]:
    return shutil.which("claude")


def clean_env() -> Dict[str, str]:
    """The environment for the agent. Run from inside a Claude Code session
    (as this harness often is), the child would inherit that session's
    CLAUDECODE / CLAUDE_CODE_* / ANTHROPIC_BASE_URL and talk to the parent's
    plumbing instead of logging in on its own; drop them."""
    nested = "CLAUDECODE" in os.environ
    return {k: v for k, v in os.environ.items()
            if not (k == "CLAUDECODE" or k.startswith("CLAUDE_CODE_")
                    or k.startswith("CLAUDE_AGENT_SDK_")
                    or (nested and k == "ANTHROPIC_BASE_URL"))}


def logged_in() -> Tuple[bool, str]:
    """Whether claude can call the API: logged in, or an API key set."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        return True, "ANTHROPIC_API_KEY"
    try:
        out = subprocess.run([claude_exe(), "auth", "status"],
                             capture_output=True, text=True, timeout=60,
                             env=clean_env()).stdout
        status = json.loads(out)
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        return False, "claude auth status failed: %s" % exc
    return bool(status.get("loggedIn")), status.get("authMethod", "")


def mcp_config(folder: str, tools: str = "") -> str:
    path = os.path.join(folder, "mcp.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"mcpServers": {SERVER: {
            "command": sys.executable,
            "args": ["-m", "datum.mcp"] + (["--tools", tools] if tools
                                           else []),
            "cwd": ROOT, "env": {"PYTHONPATH": ROOT,
                                 # the agent saves in its scratch folder
                                 "INVENTCRAFT_ALLOW_DIRS": folder}}}},
            f, indent=1)
    return path


def run_agent(sc: Dict[str, Any], work: str, model: str, budget: float,
              timeout: float, skill: bool) -> Dict[str, Any]:
    """One headless Claude Code run; the parsed stream and the save path."""
    own, save, prompt = layout(sc, work)
    os.makedirs(own, exist_ok=True)
    asyncio.run(make_fixtures(sc, own))
    config = mcp_config(work, sc.get("tools", ""))
    if skill:
        from datum.mcp import skills
        skills.install(dest=os.path.join(work, ".claude", "skills"),
                       force=True)
    cmd = [claude_exe(), "-p", prompt,
           "--mcp-config", config, "--strict-mcp-config",
           "--output-format", "stream-json", "--verbose",
           "--model", model,
           "--tools", ",".join(RESOURCE_TOOLS + (["Skill"] if skill else [])),
           "--allowedTools", "mcp__%s" % SERVER, *RESOURCE_TOOLS,
           "--max-budget-usd", "%.2f" % budget,
           "--no-session-persistence",
           "--setting-sources", "project" if skill else "local"]
    started = time.time()
    stream_path = os.path.join(work, "transcript.jsonl")
    with open(stream_path, "w", encoding="utf-8") as out:
        try:
            proc = subprocess.run(cmd, cwd=work, stdout=out, env=clean_env(),
                                  stderr=subprocess.PIPE, text=True,
                                  encoding="utf-8", errors="replace",
                                  timeout=timeout)
            rc, err = proc.returncode, proc.stderr
        except subprocess.TimeoutExpired:
            rc, err = -1, "timed out after %d s" % timeout
    events = []
    with open(stream_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    events.append(json.loads(line))
                except ValueError:
                    pass
    return {"save": save, "events": events, "returncode": rc,
            "stderr": (err or "")[-2000:], "seconds":
            round(time.time() - started, 1), "transcript": stream_path}


def score(events: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Tool calls, failures, turns, tokens and cost from a stream-json."""
    uses: Dict[str, Dict[str, Any]] = {}
    calls: List[Dict[str, Any]] = []
    by_tool: Dict[str, int] = {}
    errors: List[Dict[str, Any]] = []
    final: Dict[str, Any] = {}
    reads: List[str] = []
    for ev in events:
        if ev.get("type") == "assistant":
            for block in (ev.get("message") or {}).get("content") or []:
                if block.get("type") == "tool_use":
                    name = block.get("name", "")
                    short = name.replace(TOOL_PREFIX, "")
                    by_tool[short] = by_tool.get(short, 0) + 1
                    item = {"id": block.get("id"), "tool": short,
                            "args": block.get("input") or {},
                            "mcp": name.startswith(TOOL_PREFIX)}
                    uses[item["id"]] = item
                    calls.append(item)
                    if short == "ReadMcpResourceTool":
                        reads.append(str(item["args"].get("uri")))
        elif ev.get("type") == "user":
            for block in (ev.get("message") or {}).get("content") or []:
                if isinstance(block, dict) and \
                        block.get("type") == "tool_result":
                    item = uses.get(block.get("tool_use_id"))
                    if item is None:
                        continue
                    item["error"] = bool(block.get("is_error"))
                    if item["error"]:
                        content = block.get("content")
                        if isinstance(content, list):
                            content = " ".join(
                                c.get("text", "") for c in content
                                if isinstance(c, dict))
                        errors.append({"tool": item["tool"],
                                       "message": str(content)[:300]})
        elif ev.get("type") == "result":
            final = ev
    usage = final.get("usage") or {}
    return {
        "tool_calls": len(calls), "by_tool": by_tool,
        "server_calls": sum(1 for c in calls if c["mcp"]),
        "failed_calls": len(errors), "errors": errors,
        "guides_read": reads,
        "turns": final.get("num_turns"),
        "tokens": {"input": usage.get("input_tokens", 0),
                   "output": usage.get("output_tokens", 0),
                   "cache_read": usage.get("cache_read_input_tokens", 0),
                   "cache_write": usage.get("cache_creation_input_tokens",
                                            0)},
        "cost_usd": final.get("total_cost_usd"),
        "stopped": final.get("subtype"),
        "answer": (final.get("result") or "")[:1500],
        "calls": calls,
    }


# Tools a session-driven run may use besides the server's: reading its
# resources, loading deferred tool schemas, and the desktop app's own
# task list and wrap-up, which steer nothing in the model.
SESSION_HARMLESS = set(RESOURCE_TOOLS) | {"ToolSearch"}
SESSION_HARMLESS_PREFIX = ("mcp__ccd_turn__",)


def read_jsonl(path: str) -> List[Dict[str, Any]]:
    events = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                events.append(json.loads(line))
            except ValueError:
                pass
    return events


def score_session(events: List[Dict[str, Any]]) -> Dict[str, Any]:
    """The same score from a Claude Code session transcript (the JSONL a
    desktop or CLI session keeps under ~/.claude/projects/).

    Such a transcript repeats a message once per content block as it
    streams, so tool uses are counted once by id and usage once by
    message id; it has no closing ``result`` event, so turns are the
    assistant messages and cost is unknown. Tools outside the server, the
    resource readers, ToolSearch and the app's task list are listed as
    ``outside_tools``: a session run that used them broke its brief.
    """
    seen_ids = set()
    unique: List[Dict[str, Any]] = []
    usage: Dict[str, Dict[str, int]] = {}
    for ev in events:
        if ev.get("type") not in ("assistant", "user"):
            continue
        msg = ev.get("message") or {}
        if ev["type"] == "assistant" and msg.get("id"):
            usage[msg["id"]] = msg.get("usage") or {}
        blocks = []
        for block in msg.get("content") or []:
            if not isinstance(block, dict):
                continue
            key = block.get("id") or block.get("tool_use_id")
            if block.get("type") in ("tool_use", "tool_result"):
                if (block["type"], key) in seen_ids:
                    continue
                seen_ids.add((block["type"], key))
            blocks.append(block)
        if blocks:
            unique.append({"type": ev["type"],
                           "message": dict(msg, content=blocks)})
    total = {"input_tokens": 0, "output_tokens": 0,
             "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
    for u in usage.values():
        for k in total:
            total[k] += u.get(k, 0) or 0
    answer = ""
    for ev in unique:
        if ev["type"] == "assistant":
            for b in ev["message"]["content"]:
                if b.get("type") == "text":
                    answer = b.get("text", "")
    unique.append({"type": "result", "usage": total, "num_turns":
                   len(usage), "result": answer, "subtype": "session"})
    s = score(unique)
    s["outside_tools"] = sorted({
        c["tool"] for c in s["calls"] if not c["mcp"]
        and c["tool"] not in SESSION_HARMLESS
        and not c["tool"].startswith(SESSION_HARMLESS_PREFIX)})
    return s


# ---------------------------------------------------------------- replays


def to_replay(sc: Dict[str, Any], calls: List[Dict[str, Any]]
              ) -> Optional[Dict[str, Any]]:
    """A Tier 1 replay from a run's tool calls, or None if it cannot be
    replayed as one (more than one document, a file of its own...)."""
    out = []
    docs = 0
    for c in calls:
        if not c.get("mcp"):
            continue
        tool, args = c["tool"], dict(c["args"])
        if tool in ("save_document", "close_document", "export",
                    "status"):
            continue
        if c.get("error"):
            # A failed call changed nothing (a build rolls back), and once
            # the stumble behind it is fixed it would succeed and change
            # what follows: the replay is the path that worked.
            continue
        if tool in ("open_document",):
            return None
        if tool == "new_document":
            docs += 1
            if docs > 1:
                return None
        args.pop("doc", None)
        step: Dict[str, Any] = {"tool": tool, "args": args}
        expect: Dict[str, Any] = {}
        if tool == "render_view":
            expect["image"] = True
        if expect:
            step["expect"] = expect
        out.append(step)
    if not out or out[0]["tool"] != "new_document":
        out.insert(0, {"tool": "new_document", "args": {}})
    v = sc["verdict"]
    expected = v.get("inspect") or (v.get("any_of") or [{}])[0].get(
        "inspect")
    if expected:
        out.append({"tool": "inspect", "args": {"expected": expected},
                    "expect": {"verdict": True}})
    return {"name": "tier 2 win, %s: %s" % (sc["name"], sc["title"]),
            "recorded": time.strftime("%Y-%m-%d"), "calls": out}


# ---------------------------------------------------------------- report


def markdown(report: Dict[str, Any]) -> str:
    lines = ["# Tier 2 report, %s" % report["started"], "",
             "Model `%s`, %d run(s), %d passed. Total $%.3f." % (
                 report["model"], len(report["runs"]),
                 sum(r["verdict"]["pass"] for r in report["runs"]),
                 sum(r["score"].get("cost_usd") or 0
                     for r in report["runs"])), "",
             "| scenario | verdict | tool calls (server) | failed | turns "
             "| tokens in/out (cache read) | $ | s |",
             "|---|---|---|---|---|---|---|---|"]
    for r in report["runs"]:
        s = r["score"]
        t = s["tokens"]
        lines.append("| %s | %s | %d (%d) | %d | %s | %d/%d (%d) | %s | %s |" % (
            r["scenario"], "PASS" if r["verdict"]["pass"] else "FAIL",
            s["tool_calls"], s.get("server_calls", 0), s["failed_calls"],
            s.get("turns"),
            t["input"] + t["cache_write"], t["output"], t["cache_read"],
            "%.3f" % s["cost_usd"] if s.get("cost_usd") is not None
            else "?", r["seconds"] if r.get("seconds") is not None
            else "?"))
    for r in report["runs"]:
        s = r["score"]
        lines += ["", "## %s" % r["scenario"], "",
                  "Tools: %s." % ", ".join("%s %d" % kv for kv in
                                           sorted(s["by_tool"].items())),
                  "Guides read: %s." % (", ".join(s["guides_read"]) or
                                        "none")]
        failed = [c for c in r["verdict"]["checks"] if not c["pass"]]
        lines.append("Checks: %d/%d pass." % (
            len(r["verdict"]["checks"]) - len(failed),
            len(r["verdict"]["checks"])))
        for c in failed:
            lines.append("- FAILED %s: `%s`" % (
                c["check"], json.dumps(c["detail"], ensure_ascii=False)[:300]))
        for e in s["errors"]:
            lines.append("- tool error, %s: %s" % (
                e["tool"], e["message"].replace("\n", " ")[:240]))
        if r.get("replay"):
            lines.append("- recorded as `%s`" % r["replay"])
        if r.get("note"):
            lines.append("- %s" % r["note"])
    return "\n".join(lines) + "\n"


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("scenarios", nargs="*")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--check-references", action="store_true")
    ap.add_argument("--model", default="haiku",
                    help="claude model alias or id (default: haiku, the "
                    "cheapest)")
    ap.add_argument("--budget", type=float, default=1.0,
                    help="dollar cap per run, passed to claude")
    ap.add_argument("--timeout", type=float, default=900)
    ap.add_argument("--skill", action="store_true",
                    help="also give the agent the Claude Code skill")
    ap.add_argument("--record", action="store_true",
                    help="write passing runs as Tier 1 replays")
    ap.add_argument("--prepare", metavar="DIR",
                    help="no agent: make DIR ready for session-driven runs "
                    "(a folder and the fixtures per scenario) and write "
                    "each scenario's full prompt to DIR/prompts/")
    ap.add_argument("--judge-dir", metavar="DIR",
                    help="no agent: judge parts already saved there as "
                    "<scenario>.icpart (session-driven runs), scoring "
                    "<scenario>.jsonl transcripts beside them if present")
    args = ap.parse_args(argv)

    which = names() if (args.all or args.list or (args.check_references
                                                  and not args.scenarios)) \
        else args.scenarios
    unknown = [n for n in which if n not in names()]
    if unknown:
        print("no scenario %s; there are: %s" % (", ".join(unknown),
                                                ", ".join(names())))
        return 2
    if args.list:
        for n in which:
            print("%-22s %s" % (n, load(n)["title"]))
        return 0
    if args.check_references:
        return asyncio.run(check_references(which))
    if args.prepare:
        return prepare(args.prepare, which or names())
    if args.judge_dir:
        return judge_dir(args.judge_dir, which or names(), args.record)
    if not which:
        ap.print_help()
        return 2
    if not claude_exe():
        print("claude (Claude Code) is not on PATH; Tier 2 needs it.")
        return 2
    ok, how = logged_in()
    if not ok:
        print("claude is not logged in (%s). Run `claude auth login` once in "
              "a terminal, or set ANTHROPIC_API_KEY, then run this again. "
              "Nothing was spent." % (how or "no auth"))
        return 2

    stamp = time.strftime("%Y%m%d-%H%M%S")
    out_dir = os.path.join(RUNS, stamp)
    os.makedirs(out_dir, exist_ok=True)
    report = {"started": stamp, "model": args.model, "skill": args.skill,
              "runs": []}
    for name in which:
        sc = load(name)
        work = tempfile.mkdtemp(prefix="ic_tier2_%s_" % name)
        print("%s: running (%s) in %s" % (name, args.model, work),
              flush=True)
        run = run_agent(sc, work, args.model, args.budget, args.timeout,
                        args.skill)
        s = score(run["events"])
        verdict = asyncio.run(judge_file(run["save"], sc["verdict"],
                                         sc.get("tools", "")))
        entry = {"scenario": name, "verdict": verdict, "score": s,
                 "seconds": run["seconds"], "returncode": run["returncode"],
                 "stderr": run["stderr"]}
        keep = os.path.join(out_dir, name + ".jsonl")
        shutil.copy(run["transcript"], keep)
        entry["transcript"] = os.path.relpath(keep, ROOT)
        if args.record and verdict["pass"]:
            record(sc, entry, s["calls"])
        report["runs"].append(entry)
        say(entry)
        if run["returncode"] not in (0,) and run["stderr"]:
            print("    claude stderr: %s" % run["stderr"][-400:])
    return write_report(out_dir, report)


def record(sc: Dict[str, Any], entry: Dict[str, Any],
           calls: List[Dict[str, Any]]) -> None:
    replay = to_replay(sc, calls)
    if replay is None:
        entry["note"] = "passed, but not replayable as one session"
        return
    path = os.path.join(REPLAYS, "tier2_%s.json" % sc["name"])
    with open(path, "w", encoding="utf-8") as f:
        json.dump(replay, f, indent=1, ensure_ascii=False)
        f.write("\n")
    entry["replay"] = os.path.relpath(path, ROOT)


def say(entry: Dict[str, Any]) -> None:
    s, verdict = entry["score"], entry["verdict"]
    print("%s: %s, %d tool calls (%d to the server), %d failed%s" % (
        entry["scenario"], "PASS" if verdict["pass"] else "FAIL",
        s["tool_calls"], s.get("server_calls", 0), s["failed_calls"],
        "" if entry.get("seconds") is None else ", $%s, %ss" % (
            s.get("cost_usd"), entry["seconds"])), flush=True)
    for c in verdict["checks"]:
        if not c["pass"]:
            print("    x %s: %s" % (c["check"], json.dumps(
                c["detail"], ensure_ascii=False)[:200]))
    if s.get("outside_tools"):
        print("    ! used tools outside the brief: %s"
              % ", ".join(s["outside_tools"]))


def write_report(out_dir: str, report: Dict[str, Any]) -> int:
    with open(os.path.join(out_dir, "report.json"), "w",
              encoding="utf-8") as f:
        json.dump(report, f, indent=1, ensure_ascii=False)
    with open(os.path.join(out_dir, "report.md"), "w",
              encoding="utf-8") as f:
        f.write(markdown(report))
    print("report: %s" % os.path.join(out_dir, "report.md"))
    return 0 if all(r["verdict"]["pass"] for r in report["runs"]) else 1


def judge_dir(folder: str, which: List[str], do_record: bool) -> int:
    """Session-driven Tier 2: some other agent (a desktop Claude Code
    session, another client) was given the scenario prompt and saved
    ``<folder>/<scenario>.icpart``. Judge each part that is there, score
    ``<scenario>.jsonl`` beside it if there is one, and report as a run
    would. Spends nothing."""
    folder = os.path.abspath(folder)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    out_dir = os.path.join(RUNS, "judged-" + stamp)
    os.makedirs(out_dir, exist_ok=True)
    report = {"started": stamp, "model": "session (see transcripts)",
              "skill": None, "judged": folder, "runs": []}
    for name in which:
        sc = dict(load(name), name=name)
        _own, part, _prompt = layout(sc, folder)
        if not os.path.isfile(part):
            continue
        verdict = asyncio.run(judge_file(part, sc["verdict"],
                                         sc.get("tools", "")))
        tx = os.path.join(folder, name + ".jsonl")
        s = score_session(read_jsonl(tx)) if os.path.isfile(tx) else \
            score([])
        entry = {"scenario": name, "verdict": verdict, "score": s,
                 "seconds": None, "part": part}
        if os.path.isfile(tx):
            entry["transcript"] = tx
            if s.get("outside_tools"):
                entry["note"] = ("used tools outside the brief: %s"
                                 % ", ".join(s["outside_tools"]))
        if do_record and verdict["pass"] and s["calls"]:
            record(sc, entry, s["calls"])
        report["runs"].append(entry)
        say(entry)
    if not report["runs"]:
        print("no <scenario>.icpart (or <scenario>/<scenario>.icasm, ...) "
              "in %s" % folder)
        return 2
    return write_report(out_dir, report)


def prepare(folder: str, which: List[str]) -> int:
    """Everything a session-driven run needs, made without an agent."""
    folder = os.path.abspath(folder)
    os.makedirs(os.path.join(folder, "prompts"), exist_ok=True)
    for name in which:
        sc = dict(load(name), name=name)
        own, save, prompt = layout(sc, folder)
        if own != folder:
            os.makedirs(own, exist_ok=True)
        asyncio.run(make_fixtures(sc, own))
        with open(os.path.join(folder, "prompts", name + ".txt"), "w",
                  encoding="utf-8") as f:
            f.write(prompt + "\n")
        note = ("  needs the server started with --tools %s" % sc["tools"]
                if sc.get("tools") else "")
        print("%-24s -> %s%s" % (name, save, note))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
