"""The guidance an agent gets: guides, prompts, the skill, the error table.

In process, no MCP client: what is checked is that the text cannot drift
from the code it describes.

* every guide and prompt renders, and names only tools that exist
  (tools are written ``name()`` in all of them, and in the instructions);
* every op list shown in a guide as JSON builds;
* every error kind the bridge can raise is in ``errors.KINDS``, which
  ic://guide/errors is written from;
* the shipped Claude Code skill is exactly what the generator writes now.
"""
import asyncio
import glob
import json
import os
import re
import sys
import tempfile

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(errors="replace")
    except Exception:
        pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import harness  # noqa: E402,F401

from datum.bridge import errors  # noqa: E402
from datum.bridge.host import InProcessHost  # noqa: E402
from datum.mcp import guides, prompts, server, skills  # noqa: E402

FAILS = []


def check(name, cond, extra=""):
    print(("  PASS  " if cond else "  FAIL  ") + name
          + (("  " + str(extra)) if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


TOOL_RE = re.compile(r"\b([a-z][a-z_]+)\(\)")
# a profile family of the user's own must not reach the guides, or the
# shipped skill would differ from machine to machine
_own = tempfile.mkdtemp(prefix="ic-profiles-")
with open(os.path.join(_own, "tubes.json"), "w", encoding="utf-8") as _f:
    json.dump({"id": "my-tubes", "name": "My tubes", "standard": "",
               "category": "Tubes", "kind": "pipe", "columns": ["d", "t"],
               "rows": [["T1", 20, 2]]}, _f)
os.environ["DATUM_PROFILE_LIBRARY"] = _own
host = InProcessHost()
facts = host.call("guide_facts")
check("a profile family of the user's own is not in the guides",
      "my-tubes" not in [f["family"] for f in facts["profile_families"]]
      and facts["profile_families"], facts["profile_families"][:2])
tools = {t.name for t in asyncio.run(server.server.list_tools())}

print("guides")
check("the index lists every topic", all(
    "ic://guide/%s" % t in guides.index() for t in guides.TOPICS))
texts = {}
for topic in guides.TOPICS:
    try:
        texts["guide " + topic] = guides.render(topic, facts)
        ok = len(texts["guide " + topic]) > 200
    except Exception as exc:  # noqa: BLE001
        ok, texts["guide " + topic] = False, str(exc)
    check("guide %s renders" % topic, ok, texts["guide " + topic][:200])
# the errors guide is a generated table, one row per error kind: it
# grows with the kinds, so it has its own, larger bound
check("each guide stays short", all(
    len(t.splitlines()) < (130 if k == "guide errors" else 90)
    for k, t in texts.items()),
    {k: len(t.splitlines()) for k, t in texts.items()})

print("prompts")
for p in prompts.PROMPTS.values():
    args = {a.name: "X" for a in p.args if a.required}
    text = prompts.render(p.name, args)
    texts["prompt " + p.name] = text
    check("prompt %s renders and teaches the loop" % p.name,
          "build()" in text and "render_view()" in text
          and "inspect(" in text, text[:200])
    check("prompt %s points to guides that exist" % p.name,
          all(g in guides.TOPICS for g in p.guides))
check("left-out prompts are not offered",
      not set(prompts.LEFT_OUT) & set(prompts.PROMPTS))
texts["instructions"] = server.INSTRUCTIONS
texts["skill"] = skills.skill_md()

print("tool names")
for label, text in texts.items():
    named = set(TOOL_RE.findall(text))
    # Python and helper calls written in examples are not tools
    named -= {"print", "result", "range", "int", "union", "cylinder",
              "beam", "rod", "box", "move", "rotate", "tube"}
    named -= set(facts["code_helpers"])
    unknown = sorted(n for n in named if n not in tools)
    check("%s names only real tools" % label, not unknown, unknown)
check("the instructions point at the guides",
      "ic://guide/workflow" in server.INSTRUCTIONS
      and len(server.INSTRUCTIONS.splitlines()) < 25)

print("examples build")
blocks = []
for label, text in texts.items():
    for block in re.findall(r"```json\n(.*?)```", text, re.S):
        try:
            data = json.loads(block)
        except ValueError:
            continue
        if isinstance(data, dict) and "op" in data:
            data = [data]
        if isinstance(data, list) and data and all(
                isinstance(o, dict) and "op" in o for o in data):
            blocks.append((label, data))
check("the guides show op examples", len(blocks) >= 2, len(blocks))
for label, ops in blocks:
    host.call("new_document")
    names = {o.get("name") for o in ops if o.get("op") == "parameter"}
    pre = [{"op": "parameter", "name": n, "value": v}
           for n, v in (("L", 600), ("W", 400), ("b", 40), ("t", 3))
           if n not in names]
    r = host.call("build", {"ops": pre + ops})
    check("%s: its example builds" % label, r["ok"], r.get("error"))
    host.call("close_document")

print("frame members")
host.call("new_document")
r = host.call("build", {"ops": [
    {"op": "frame_member", "family": "din-en-10219-2-square",
     "size": "40 x 40 x 3", "length": 500}]})
check("a member sized from a family builds", r["ok"], r.get("error"))
check("to the family's size", sorted(round(x) for x in
                                     host.call("inspect")["bbox"])
      == [40, 40, 500])
r = host.call("build", {"ops": [
    {"op": "frame_member", "kind": "square_tube", "length": 500}]})
kind, msg = (r.get("error") or {}).get("kind"),     (r.get("error") or {}).get("message", "")
check("a member with no dims says which it needs",
      kind == "BAD_VALUE" and "b, t, ro" in msg, (kind, msg))
host.call("close_document")

print("sheet metal")
host.call("new_document")
r = host.call("build", {"ops": [
    {"op": "sketch", "id": "s", "plane": "XY",
     "entities": [{"rect": {"center": [0, 0], "size": [100, 50]}}]},
    {"op": "sheet_face", "sketch": "$s"}]})
check("a sheet feature without Thickness says to add it",
      not r["ok"] and "Thickness" in " ".join(r["error"]["hints"])
      and "BendRadius" in " ".join(r["error"]["hints"]), r.get("error"))
host.call("close_document")

print("errors")
raised = set()
for path in glob.glob(os.path.join(ROOT, "datum", "bridge", "*.py")) + \
        glob.glob(os.path.join(ROOT, "datum", "mcp", "*.py")):
    src = open(path, encoding="utf-8").read()
    raised |= set(re.findall(r"BridgeError\(\s*\"([A-Z_]+)\"", src))
    raised |= set(re.findall(r"\"kind\": \"([A-Z_]+)\"", src))
raised |= {kind for _p, kind, _h in errors._RULES}
missing = sorted(raised - set(errors.KINDS))
check("every error kind raised is in errors.KINDS", not missing, missing)
check("and the errors guide lists each",
      all("`%s`" % k in texts["guide errors"] for k in errors.KINDS))

print("skill")
generated = skills.generate(facts)
shipped = skills.shipped()
stale = sorted(k for k in set(generated) | set(shipped)
               if generated.get(k) != shipped.get(k))
check("the shipped skill is what the generator writes "
      "(python -m datum.mcp write-skill)", not stale, stale)
check("the skill has frontmatter with a name and description",
      generated["SKILL.md"].startswith("---\nname: inventcraft\n"
                                       "description: "))
links = re.findall(r"\]\((guides/[^)]+)\)", generated["SKILL.md"])
check("every file the skill links to is in it",
      links and all(l in generated for l in links), links)
dest = tempfile.mkdtemp(prefix="datum_skill_")
where = skills.install(dest=dest)
check("install-skill copies it", os.path.isfile(
    os.path.join(where, "SKILL.md")) and os.path.isfile(
    os.path.join(where, "guides", "workflow.md")))

print()
if FAILS:
    print("%d FAILURES: %s" % (len(FAILS), ", ".join(FAILS)))
    sys.exit(1)
print("all mcp guide tests passed")
sys.exit(0)
