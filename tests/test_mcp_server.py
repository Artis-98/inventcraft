"""The MCP server end to end: a real MCP client, the real server over
stdio, and the headless host process it starts.

Three things are tested:

* the tool surface: the tools are there, annotated, and failures come
  back as isError results with a kind and hints;
* the replays in tests/mcp_replays/: recorded sessions an agent could have
  had, run again call for call and checked (tier 1 of the plan's
  evaluation, deterministic, no model involved);
* the host dying: the server reports it, and the next call starts afresh.
"""
import asyncio
import glob
import json
import os
import sys
import tempfile

# results can contain symbols such as a check mark; a non-UTF-8 console
# (cp1254 here) must not crash the run
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(errors="replace")
    except Exception:
        pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from mcp import ClientSession  # noqa: E402
from mcp.client.stdio import StdioServerParameters, stdio_client  # noqa: E402

FAILS = []
EXAMPLES = os.path.join(ROOT, "examples").replace("\\", "/")


def check(name, cond, extra=""):
    print(("  PASS  " if cond else "  FAIL  ") + name
          + (("  " + str(extra)) if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


def texts(result):
    return [c.text for c in result.content if getattr(c, "type", "") == "text"]


def payload(result):
    """The JSON part of a result, whichever content block holds it."""
    for t in reversed(texts(result)):
        try:
            return json.loads(t)
        except ValueError:
            continue
    return {}


TMP = tempfile.mkdtemp(prefix="datum_replay_").replace("\\", "/")
# the replays save here, outside the project folder: allow it (see
# datum/mcp/safety.py; the servers the tests start inherit the variable)
os.environ["INVENTCRAFT_ALLOW_DIRS"] = TMP


def _fill(value):
    if isinstance(value, str):
        return value.replace("{EXAMPLES}", EXAMPLES).replace("{TMP}", TMP)
    if isinstance(value, list):
        return [_fill(v) for v in value]
    if isinstance(value, dict):
        return {k: _fill(v) for k, v in value.items()}
    return value


async def replay(session, path):
    scenario = json.load(open(path, encoding="utf-8"))
    print("replay: %s" % scenario["name"])
    for n, step in enumerate(scenario["calls"]):
        tool, expect = step["tool"], step.get("expect", {})
        result = await session.call_tool(tool, _fill(step.get("args", {})))
        label = "%s #%d %s" % (os.path.basename(path), n, tool)
        wants_error = expect.get("error", False)
        check("%s %s" % (label, "fails as expected" if wants_error
                         else "succeeds"),
              bool(result.is_error) == wants_error, texts(result)[:1])
        if "verdict" in expect:
            verdict = payload(result).get("verdict", {})
            check(label + " verdict", verdict.get("pass") == expect["verdict"],
                  verdict)
        if expect.get("image"):
            check(label + " returns an image", any(
                getattr(c, "type", "") == "image" for c in result.content))
        if "contains" in expect:
            check(label + " mentions " + expect["contains"],
                  any(expect["contains"] in t for t in texts(result)),
                  texts(result)[:1])
        for key, want in expect.get("fields", {}).items():
            got = payload(result).get(key)
            check("%s %s = %r" % (label, key, want), got == want, got)
    await session.call_tool("close_document", {})


async def main():
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "datum.mcp", "--code-ask", "no"], cwd=ROOT,
        env=dict(os.environ, PYTHONPATH=ROOT,
                 # never the real app's pairing: a test must not reach the
                 # InventCraft the user has open
                 DATUM_CONFIG_DIR=tempfile.mkdtemp(prefix="datum_cfg_")))
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            info = await session.initialize()
            check("the server introduces itself",
                  info.server_info.name == "InventCraft")
            check("with instructions for the agent",
                  "build" in (info.instructions or ""))

            print("tools")
            tools = {t.name: t for t in (await session.list_tools()).tools}
            for name in ("status", "new_document", "open_document",
                         "save_document", "export", "model_tree",
                         "properties", "inspect", "render_view", "build",
                         "edit_feature", "read_ir", "sketch_status", "diff",
                         "snapshot", "find_geometry", "measure",
                         "requirements", "run_script", "place_component",
                         "constrain", "assembly_check", "bom", "branch",
                         "model_states", "evaluate", "optimise",
                         "recognize", "parametrize", "build_project"):
                check("tool %s is there" % name, name in tools)
            check("every tool is annotated", all(
                t.annotations is not None for t in tools.values()))
            check("build names every feature type", all(
                kind in (tools["build"].description or "")
                for kind in ("revolve", "sheet_face", "pipe_fitting",
                             "thread", "ic://schema/op/")))

            print("resources")
            listed = await session.list_resources()
            uris = [str(r.uri) for r in listed.resources]
            check("the op list is a resource", "ic://schema/ops" in uris, uris)
            for uri in ("ic://status", "ic://documents", "ic://materials",
                        "ic://schema/ref"):
                check("%s is a resource" % uri, uri in uris, uris)
            shapes = [str(t.uri_template) for t in (
                await session.list_resource_templates()).resource_templates]
            for uri in ("ic://doc/{doc}/tree", "ic://doc/{doc}/parameters",
                        "ic://doc/{doc}/sketch/{sketch}",
                        "ic://doc/{doc}/requirements"):
                check("%s is a resource template" % uri, uri in shapes,
                      shapes)
            grammar = json.loads((await session.read_resource(
                "ic://schema/ref")).contents[0].text)
            check("the ref grammar says how refs resolve",
                  "fingerprint" in grammar.get("via", {}), grammar)
            mats = json.loads((await session.read_resource(
                "ic://materials")).contents[0].text)
            check("the materials resource lists the library",
                  len(mats.get("materials", [])) > 5)
            print("guides and prompts")
            check("ic://guide is a resource", "ic://guide" in uris, uris)
            check("ic://guide/{topic} is a resource template",
                  "ic://guide/{topic}" in shapes, shapes)
            gindex = (await session.read_resource(
                "ic://guide")).contents[0].text
            for topic in ("workflow", "sketches", "references", "units",
                          "requirements", "scripts", "sheet-metal",
                          "frames", "explore", "import", "errors"):
                check("the guide list names %s" % topic,
                      "ic://guide/%s" % topic in gindex)
                text = (await session.read_resource(
                    "ic://guide/%s" % topic)).contents[0].text
                check("guide %s reads through the server" % topic,
                      text.startswith("# ") and len(text) > 300, text[:120])
            listed_prompts = {p.name: p for p in
                              (await session.list_prompts()).prompts}
            for name in ("design-part", "sheet-metal-enclosure",
                         "weldment-frame", "part-family", "optimise-design",
                         "parametrize-import"):
                check("prompt %s is offered" % name, name in listed_prompts,
                      sorted(listed_prompts))
            design = listed_prompts.get("design-part")
            check("prompt arguments are described", design is not None and
                  all(a.description for a in design.arguments or []))
            got = await session.get_prompt("design-part", {
                "description": "a 100 x 60 x 8 plate with four M6 holes"})
            body = got.messages[0].content.text
            check("a prompt renders with its arguments and the loop",
                  "four M6 holes" in body and "requirements()" in body,
                  body[:200])
            await session.call_tool("new_document", {})
            await session.call_tool("build", {"ops": [
                {"op": "parameter", "name": "w", "value": 30},
                {"op": "sketch", "plane": "XY", "name": "S",
                 "entities": [{"circle": {"center": [0, 0], "d": "w"}}]},
                {"op": "extrude", "sketch": "S", "distance": 5}]})
            docs = json.loads((await session.read_resource(
                "ic://documents")).contents[0].text)["documents"]
            handle = docs[-1]["doc"]
            tree = json.loads((await session.read_resource(
                "ic://doc/%s/tree" % handle)).contents[0].text)
            check("the tree resource reads a document",
                  [f["name"] for f in tree.get("features", [])][:1] == ["S"],
                  tree)
            pars = json.loads((await session.read_resource(
                "ic://doc/%s/parameters" % handle)).contents[0].text)
            check("the parameters resource", pars["parameters"][0]["name"]
                  == "w", pars)
            sk = json.loads((await session.read_resource(
                "ic://doc/%s/sketch/S" % handle)).contents[0].text)
            check("the sketch resource", sk.get("sketch") == "S", sk)
            rq = json.loads((await session.read_resource(
                "ic://doc/%s/requirements" % handle)).contents[0].text)
            check("the requirements resource", rq.get("summary")
                  == "no requirements", rq)
            await session.call_tool("close_document", {})
            templates = await session.list_resource_templates()
            check("one schema per op type is a resource template",
                  any("ic://schema/op/{type}" in str(t.uri_template)
                      for t in templates.resource_templates))
            index = json.loads((await session.read_resource(
                "ic://schema/ops")).contents[0].text)
            check("the list has every core feature type",
                  len([o for o in index["ops"] if "uri" in o]) == 33,
                  len(index["ops"]))
            revolve = json.loads((await session.read_resource(
                "ic://schema/op/revolve")).contents[0].text)
            check("a schema is generated from the feature's fields",
                  revolve.get("title") == "revolve"
                  and "angle" in revolve.get("properties", {})
                  and revolve["properties"]["angle"].get("default") == "360",
                  revolve)
            check("reading tools say so", tools["inspect"].annotations
                  .read_only_hint is True)
            check("build documents its ops", "fillet" in
                  (tools["build"].description or ""))
            check("the default surface stays small", len(tools) <= 32,
                  len(tools))
            check("the drawing tools are off by default (+drawing)",
                  not [n for n in tools if n.startswith("drawing_")],
                  sorted(tools))

            print("explore")
            await session.call_tool("new_document", {})
            await session.call_tool("build", {"ops": [
                {"op": "parameter", "name": "w", "value": 100},
                {"op": "parameter", "name": "t", "value": 8},
                {"op": "sketch", "id": "s", "plane": "XY", "entities": [
                    {"rect": {"center": [0, 0], "size": ["w", 50]},
                     "id": "r"},
                    {"circle": {"center": [0, 0], "d": 10}, "id": "c"}]},
                {"op": "extrude", "sketch": "$s", "distance": "t",
                 "name": "Plate"}]})
            await session.call_tool("requirements", {"set": [
                {"name": "edge", "metric": "clearance",
                 "a": "Plate.side(c)", "b": "Plate.side(r.right)",
                 "min": 20},
                {"name": "stiff", "metric": "parameter", "param": "t",
                 "min": 4}]})
            before = payload(await session.call_tool("model_tree", {}))
            seen = []

            async def on_progress(done, total, message):
                seen.append((done, total))

            r = await session.call_tool("evaluate", {"variations": [
                {"t": 5}, {"t": 3}, {"w": 30}]},
                progress_callback=on_progress)
            body = payload(r)
            check("evaluate answers a table", not r.is_error
                  and "evaluate ok" in body.get("summary", "")
                  and body.get("table", "").count(chr(10)) == 4, texts(r)[:1])
            check("it tells which variants fail what",
                  "fails" in body.get("table", ""), body.get("table"))
            check("it reports progress", len(seen) >= 2
                  and seen[-1][0] == seen[-1][1], seen)
            after = payload(await session.call_tool("model_tree", {}))
            check("it never changes the open document",
                  after.get("revision") == before.get("revision")
                  and after.get("parameters") == before.get("parameters"),
                  (before.get("revision"), after.get("revision")))
            r = await session.call_tool("evaluate", {
                "variations": [{"nope": 1}], "baseline": False})
            check("a bad variant is a row, not a failed call",
                  not r.is_error and "ERROR" in payload(r).get("table", ""),
                  texts(r)[:1])
            start_mass = payload(await session.call_tool(
                "evaluate", {"detail": True}))["rows"][0]["mass_g"]
            r = await session.call_tool("optimise", {
                "vary": {"t": [2, 12], "w": [40, 120]}, "budget": 14})
            body = payload(r)
            check("optimise finds a feasible, lighter design",
                  not r.is_error and body.get("feasible") is True
                  and body.get("applied") is False
                  and body["best"]["vary"]["t"] >= 4
                  and body["best"]["value"] < start_mass,
                  texts(r)[:1])
            check("and names why others failed",
                  "edge" in body.get("failed_by", {})
                  or "stiff" in body.get("failed_by", {}), body)
            now = payload(await session.call_tool("model_tree", {}))
            check("without changing the part",
                  now.get("revision") == before.get("revision"))
            r = await session.call_tool("optimise", {
                "vary": {"t": [2, 12], "w": [40, 120]}, "budget": 14,
                "apply": True})
            check("apply writes it as one change",
                  not r.is_error and payload(r).get("applied") is True
                  and payload(r).get("revision") == before["revision"] + 1,
                  texts(r)[:1])
            r = await session.call_tool("requirements", {"check": True})
            check("and the part clears its requirements",
                  "reqs 2/2" in " ".join(texts(r)), texts(r)[:1])

            print("import")
            await session.call_tool("new_document", {})
            await session.call_tool("build", {"ops": [
                {"op": "sketch", "id": "s", "plane": "XY", "entities": [
                    {"rect": {"center": [0, 0], "size": [80, 50]}}]},
                {"op": "extrude", "sketch": "$s", "distance": 8},
                {"op": "sketch", "id": "h", "plane": "XY", "entities": [
                    {"point": [-20, 0], "id": "p"}]},
                {"op": "hole", "id": "h1", "sketch": "$h", "diameter": 7,
                 "points": ["p"], "through": True},
                {"op": "pattern", "parents": ["$h1"], "count1": 3,
                 "spacing1": 20, "dir1": "X"}]})
            stp = TMP + "/mcp_import.step"
            await session.call_tool("export", {"path": stp})
            await session.call_tool("close_document", {})
            await session.call_tool("new_document", {})
            await session.call_tool("build", {"ops": [
                {"op": "import", "path": stp}]})
            r = await session.call_tool("recognize", {})
            body = payload(r)
            check("recognize answers through MCP, read-only",
                  not r.is_error and body.get("prismatic") is True
                  and tools["recognize"].annotations.read_only_hint is True
                  and "faces explained" in body.get("summary", ""),
                  texts(r)[:1])
            check("with the holes counted and the faces all explained",
                  any(f["type"] == "hole" and f["count"] == 3
                      for f in body["features"])
                  and body["coverage"]["faces"]["share"] == 1.0, body)
            r = await session.call_tool("parametrize", {})
            check("parametrize replaces the import",
                  not r.is_error
                  and "parametrize ok" in payload(r).get("summary", ""),
                  texts(r)[:1])
            r = await session.call_tool("properties", {
                "parameters": {"hole_d": 9}})
            check("and the tree is editable", not r.is_error, texts(r)[:1])
            r = await session.call_tool("parametrize", {})
            check("a part that already has a tree is refused without "
                  "replace_tree", r.is_error and payload(r).get("kind")
                  == "REPLACE_TREE_REQUIRED", texts(r)[:1])
            r = await session.call_tool("parametrize", {"dry_run": True})
            check("but a dry run only says so", not r.is_error
                  and "replace_tree=true is needed" in payload(r).get(
                      "summary", ""), texts(r)[:1])
            r = await session.call_tool("parametrize",
                                        {"replace_tree": True})
            check("a part that already has a tree is read again from its "
                  "body, and the old tree replaced, with replace_tree",
                  not r.is_error and "parametrize ok" in payload(r).get(
                      "summary", ""), texts(r)[:1])

            print("errors")
            r = await session.call_tool("model_tree", {"doc": "d99"})
            check("a missing document is an error result", r.is_error)
            body = payload(r)
            check("with a kind and hints", body.get("kind") == "NO_DOCUMENT"
                  and isinstance(body.get("hints"), list), body)

            print("host loss")
            first = payload(await session.call_tool("status", {}))
            await session.call_tool("new_document", {})
            os.kill(first["pid"], 9)
            r = await session.call_tool("model_tree", {})
            check("a dead host is reported as such", r.is_error and
                  payload(r).get("kind") == "HOST_LOST", texts(r)[:1])
            again = payload(await session.call_tool("status", {}))
            check("and the next call starts a fresh one",
                  again.get("pid") not in (None, first["pid"]), again)
            check("and says how it was lost",
                  "exited" in again.get("last_host_loss", ""), again)
            check("which knows it lost what was open",
                  again.get("documents") == []
                  and again.get("host_restarts") == 1, again)
            r = await session.call_tool("new_document", {})
            check("and works", not r.is_error)


async def replays():
    """Every recorded session, on a server with every tool group on."""
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "datum.mcp", "--tools", "all", "--code-ask", "no"],
        cwd=ROOT, env=dict(os.environ, PYTHONPATH=ROOT,
                           DATUM_CONFIG_DIR=tempfile.mkdtemp(
                               prefix="datum_cfg_")))
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = {t.name for t in (await session.list_tools()).tools}
            check("--tools all adds the drawing group", {
                "drawing_create", "drawing_base_view",
                "drawing_projected_view", "drawing_section_view",
                "drawing_detail_view", "drawing_dimension", "drawing_note",
                "drawing_parts_list", "drawing_render",
                "drawing_export"} <= tools, sorted(tools))
            check("--tools all adds sheet metal, frames and skeleton", {
                "sheet_rules", "flat_pattern", "sheet_check",
                "frame_profiles", "frame_insert", "frame_treat", "cut_list",
                "skeleton_params", "derive_part", "skeleton_set"} <= tools,
                sorted(tools))
            for path in sorted(glob.glob(os.path.join(
                    ROOT, "tests", "mcp_replays", "*.json"))):
                await replay(session, path)
            # the weld cart replay left a flat pattern and a cut list
            dxf = os.path.join(TMP, "Top Tray.dxf")
            check("the cart replay wrote the tray's flat pattern",
                  os.path.exists(dxf) and "BEND_CENTERLINE" in open(
                      dxf, errors="replace").read(), dxf)
            csv_ = os.path.join(TMP, "Welding Cart cut list.csv")
            check("and the cut list",
                  os.path.exists(csv_) and len(open(
                      csv_, encoding="utf-8").read().splitlines()) == 7, csv_)
            # the drawing replay left real files
            for name in ("DBracket.pdf", "DBracket.dxf", "DBracket.icdraw"):
                full = os.path.join(TMP, name)
                check("the drawing replay wrote %s" % name,
                      os.path.exists(full) and os.path.getsize(full) > 2000,
                      full)
            pdf = open(os.path.join(TMP, "DBracket.pdf"), "rb").read(5)
            check("and the PDF is a PDF", pdf == b"%PDF-", pdf)


async def tools_flag():
    """--tools turns a group off (and unknown groups are refused)."""
    print("--tools")
    cfg = tempfile.mkdtemp(prefix="datum_cfg_")
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "datum.mcp", "--tools", "default,-assembly"], cwd=ROOT,
        env=dict(os.environ, PYTHONPATH=ROOT, DATUM_CONFIG_DIR=cfg))
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            names = {t.name for t in (await session.list_tools()).tools}
            check("the default surface leaves the opt-in groups off",
                  not names & {"flat_pattern", "frame_insert",
                               "skeleton_set", "drawing_create"},
                  sorted(names))
            check("--tools default,-assembly drops the assembly tools",
                  not names & {"place_component", "constrain",
                               "assembly_check", "bom"}, sorted(names))
            check("and keeps the rest", {"build", "model_tree",
                                         "edit_feature"} <= names)
            r = await session.call_tool("new_document",
                                        {"type": "assembly"})
            check("an assembly can still be made and read",
                  not r.is_error, texts(r)[:1])
            r = await session.call_tool("model_tree", {})
            check("and read", "occurrences" in "".join(texts(r)))
            r = await session.call_tool("model_states", {})
            check("model_states and branch are on every surface",
                  r.is_error and payload(r).get("kind") == "WRONG_TYPE",
                  texts(r)[:1])
    import subprocess
    bad = subprocess.run([sys.executable, "-m", "datum.mcp", "--tools",
                          "nosuch"], cwd=ROOT, capture_output=True,
                         text=True, env=dict(os.environ, PYTHONPATH=ROOT,
                                             DATUM_CONFIG_DIR=cfg),
                         timeout=60)
    check("an unknown tool group is refused", bad.returncode != 0
          and "nosuch" in bad.stderr, bad.stderr[-200:])


async def safety():
    """Roots, allowed folders, confirmation, budgets (datum/mcp/safety.py,
    plan section 10), and the HTTP transport's address."""
    from mcp.types import (ElicitResult, ErrorData, ListRootsResult, Root)
    print("safety")
    cfg = tempfile.mkdtemp(prefix="datum_cfg_")
    ok_dir = tempfile.mkdtemp(prefix="ic_safe_ok_").replace("\\", "/")
    root_dir = tempfile.mkdtemp(prefix="ic_safe_root_").replace("\\", "/")
    env = dict(os.environ, PYTHONPATH=ROOT, DATUM_CONFIG_DIR=cfg)
    env.pop("INVENTCRAFT_ALLOW_DIRS", None)
    plate = [{"op": "sketch", "id": "s", "plane": "XY", "entities": [
        {"rect": {"center": [0, 0], "size": [40, 30]}, "id": "r"}]},
        {"op": "extrude", "id": "e", "sketch": "$s", "distance": 5}]

    def params(*extra):
        return StdioServerParameters(
            command=sys.executable, args=["-m", "datum.mcp"] + list(extra),
            cwd=ROOT, env=env)

    # 1. no roots from the client: the project folder, and --allow-dir
    async with stdio_client(params("--allow-dir", ok_dir)) as (rd, wr):
        async with ClientSession(rd, wr) as session:
            await session.initialize()
            await session.call_tool("new_document", {})
            await session.call_tool("build", {"ops": plate})
            r = await session.call_tool("save_document", {
                "path": os.path.join(tempfile.gettempdir(),
                                     "ic_not_allowed.icpart")})
            body = payload(r)
            check("a path outside the project folder is refused",
                  r.is_error and body.get("kind") == "PATH_NOT_ALLOWED"
                  and body.get("allowed") and body.get("hints"), body)
            check("and nothing was written", not os.path.exists(
                os.path.join(tempfile.gettempdir(), "ic_not_allowed.icpart")))
            good = ok_dir + "/a.icpart"
            r = await session.call_tool("save_document", {"path": good})
            check("--allow-dir lets a folder in", not r.is_error
                  and os.path.isfile(good), texts(r)[:1])
            inside = ROOT.replace("\\", "/") + "/ic_scratch_ok.icpart"
            r = await session.call_tool("save_document", {"path": inside})
            check("the project folder is allowed", not r.is_error,
                  texts(r)[:1])
            try:
                os.remove(inside)
            except OSError:
                pass
            r = await session.call_tool("open_document", {
                "path": ok_dir + "/../escape.icpart"})
            check("a .. escape out of an allowed folder is refused",
                  payload(r).get("kind") == "PATH_NOT_ALLOWED", texts(r)[:1])
            r = await session.call_tool("export", {
                "path": os.path.join(tempfile.gettempdir(), "ic_x.step")})
            check("export is held to the same folders",
                  payload(r).get("kind") == "PATH_NOT_ALLOWED")
            r = await session.call_tool("build", {"ops": [
                {"op": "import", "path": os.path.join(
                    tempfile.gettempdir(), "other.step")}]})
            check("an import op's file is checked too",
                  payload(r).get("kind") == "PATH_NOT_ALLOWED",
                  texts(r)[:1])

            # overwrite: an export keeps no old version
            stp = ok_dir + "/o.step"
            r = await session.call_tool("export", {"path": stp})
            check("an export to a new file works", not r.is_error,
                  texts(r)[:1])
            r = await session.call_tool("export", {"path": stp})
            check("a second one is refused: WOULD_OVERWRITE",
                  payload(r).get("kind") == "WOULD_OVERWRITE", texts(r)[:1])
            r = await session.call_tool("export", {"path": stp,
                                                   "overwrite": True})
            check("overwrite alone is not enough without a way to ask",
                  payload(r).get("kind") == "CONFIRM_REQUIRED",
                  texts(r)[:1])
            r = await session.call_tool("export", {
                "path": stp, "overwrite": True, "confirm": True})
            check("overwrite and confirm replace it", not r.is_error,
                  texts(r)[:1])
            r = await session.call_tool("save_document", {
                "path": good, "overwrite": True})
            check("a saved document keeps its old version, so overwrite "
                  "alone does (OldVersions)", not r.is_error,
                  texts(r)[:1])

            # budgets
            many = [{"op": "parameter", "name": "p%d" % i, "value": i}
                    for i in range(3)]
            for i in range(6):
                many.append({"op": "sketch", "id": "q%d" % i,
                             "plane": "XY", "entities": [
                                 {"circle": {"center": [i * 12, 0],
                                             "d": 5}, "id": "c"}]})
            await session.call_tool("build", {"ops": many})
            r = await session.call_tool("model_tree", {"limit": 2})
            body = payload(r)
            paging = (body.get("paging") or {}).get("features", {})
            check("model_tree pages", len(body.get("features", [])) == 2
                  and paging.get("next_offset") == 2
                  and paging.get("total", 0) >= 7 and "truncated" in body,
                  paging)
            r = await session.call_tool("model_tree", {"offset": 2,
                                                       "limit": 3})
            body = payload(r)
            check("and the next page starts where it said",
                  [f["id"] for f in body["features"]] and
                  body["paging"]["features"]["offset"] == 2)
            r = await session.call_tool("model_tree", {})
            check("a small tree comes back whole, no paging note",
                  "paging" not in payload(r))
            r = await session.call_tool("read_ir", {"limit": 3})
            check("read_ir pages", len(payload(r).get("ops", [])) == 3
                  and payload(r)["paging"]["ops"]["next_offset"] == 3,
                  texts(r)[:1])
            r = await session.call_tool("find_geometry", {
                "what": "edge", "where": {"limit": 3}})
            first = payload(r).get("items", [])
            r2 = await session.call_tool("find_geometry", {
                "what": "edge", "where": {"limit": 3}, "offset": 3})
            second = payload(r2).get("items", [])
            check("find_geometry pages by offset",
                  len(first) == 3 and second and
                  not {i.get("handle", i.get("ref", str(i)))
                       for i in first} & {i.get("handle", i.get("ref",
                                                                 str(i)))
                                          for i in second}, (first, second))
            r = await session.call_tool("render_view", {
                "width": 9000, "height": 9000})
            check("a render's size is capped", not r.is_error
                  and payload(r).get("size_capped_to") == 2000,
                  texts(r)[:1])

    # 2. the client's roots replace the project folder
    async def roots(_ctx):
        return ListRootsResult(roots=[Root(
            uri="file:///" + root_dir.lstrip("/"), name="work")])

    async with stdio_client(params()) as (rd, wr):
        async with ClientSession(rd, wr, list_roots_callback=roots) as s:
            await s.initialize()
            await s.call_tool("new_document", {})
            await s.call_tool("build", {"ops": plate})
            r = await s.call_tool("save_document", {
                "path": ROOT.replace("\\", "/") + "/ic_root_no.icpart"})
            body = payload(r)
            check("with roots, the project folder no longer counts",
                  body.get("kind") == "PATH_NOT_ALLOWED"
                  and body.get("source") == "the client's roots", body)
            r = await s.call_tool("save_document", {
                "path": root_dir + "/in_root.icpart"})
            check("a path inside a root is allowed", not r.is_error,
                  texts(r)[:1])

    # 3. elicitation: the user is asked; yes, and no
    answers = []

    async def say_yes(_ctx, params):
        answers.append(params.message)
        return ElicitResult(action="accept", content={"overwrite": True})

    async def say_no(_ctx, params):
        return ElicitResult(action="decline")

    target = ok_dir + "/e.step"
    for name, fn, expect_ok in (("yes", say_yes, True), ("no", say_no,
                                                         False)):
        async with stdio_client(params("--allow-dir", ok_dir)) as (rd, wr):
            async with ClientSession(rd, wr, elicitation_callback=fn) as s:
                await s.initialize()
                await s.call_tool("new_document", {})
                await s.call_tool("build", {"ops": plate})
                await s.call_tool("export", {"path": target})
                r = await s.call_tool("export", {"path": target,
                                                 "overwrite": True})
                if expect_ok:
                    check("elicitation: the user says yes, it is replaced",
                          not r.is_error and answers, texts(r)[:1])
                else:
                    check("elicitation: the user says no, it is not",
                          payload(r).get("kind") == "USER_DECLINED",
                          texts(r)[:1])

    # 4. HTTP: binds to this machine only, by default, and answers
    await http_smoke(env)

    # 5. --selftest: a host, a tiny build, inspect, render, save
    import subprocess
    done = subprocess.run([sys.executable, "-m", "datum.mcp", "--selftest"],
                          cwd=ROOT, env=env, capture_output=True,
                          text=True, encoding="utf-8", errors="replace",
                          timeout=240)
    check("--selftest passes and exits 0", done.returncode == 0
          and "PASS  inventcraft-mcp selftest" in done.stdout,
          (done.stdout + done.stderr)[-400:])


async def http_smoke(env):
    import socket
    import subprocess
    from mcp.client.streamable_http import streamable_http_client
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    proc = subprocess.Popen(
        [sys.executable, "-m", "datum.mcp", "--transport",
         "streamable-http", "--port", str(port)], cwd=ROOT, env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        up = False
        for _ in range(100):
            try:
                socket.create_connection(("127.0.0.1", port), 0.3).close()
                up = True
                break
            except OSError:
                await asyncio.sleep(0.2)
        check("streamable HTTP starts and listens on 127.0.0.1", up)
        if not up:
            return
        names = set()
        async with streamable_http_client(
                "http://127.0.0.1:%d/mcp" % port) as streams:
            async with ClientSession(streams[0], streams[1]) as s:
                await s.initialize()
                names = {t.name for t in (await s.list_tools()).tools}
                r = await s.call_tool("status", {})
                check("and serves the tools over HTTP",
                      {"build", "status"} <= names and not r.is_error)
        # the machine's other address: nothing answers there
        lan = ""
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            probe.connect(("192.0.2.1", 9))
            lan = probe.getsockname()[0]
        except OSError:
            pass
        finally:
            probe.close()
        if lan and not lan.startswith("127."):
            try:
                socket.create_connection((lan, port), 1.0).close()
                reachable = True
            except OSError:
                reachable = False
            check("and is not reachable on the machine's network address "
                  "(%s)" % lan, not reachable)
        else:
            print("  skip  no network address to test the binding against")
    finally:
        proc.kill()
        proc.wait(10)


asyncio.run(main())
asyncio.run(replays())
asyncio.run(tools_flag())
asyncio.run(safety())
print()
if FAILS:
    print("%d FAILURES: %s" % (len(FAILS), ", ".join(FAILS)))
    sys.exit(1)
print("all mcp server tests passed")
sys.exit(0)
