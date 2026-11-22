"""The Claude Code skill: the guides and prompts as files an agent loads.

The skill is ``datum/mcp/skills/inventcraft/``: a ``SKILL.md`` with the loop
and the workflows, and ``guides/<topic>.md``, one file per guide. Both
are *written* from the same code as the MCP guides and prompts
(:func:`generate`), and a test checks the shipped copy matches, so the
skill cannot drift from the server.

    python -m datum.mcp install-skill            into ./.claude/skills/
    python -m datum.mcp install-skill --user     into ~/.claude/skills/
    python -m datum.mcp install-skill --dest D   into D/inventcraft/
    python -m datum.mcp write-skill              rewrite the shipped copy
                                                 (after changing a guide)

Installing only copies files, so it needs no geometry kernel.
"""

from __future__ import annotations

import os
import shutil
from typing import Any, Dict, List, Optional

from . import guides, prompts

NAME = "inventcraft"
SHIPPED = os.path.join(os.path.dirname(os.path.abspath(__file__)), "skills",
                       NAME)

DESCRIPTION = (
    "Design parametric parts in InventCraft through its MCP server "
    "(mcp__inventcraft__* tools): brackets, plates, nuts and other "
    "standard parts, sheet-metal enclosures, welded frames, part families, "
    "optimising a design, rebuilding an imported STEP as features, "
    "assemblies of saved parts (place, constrain, check, bill of "
    "materials), part families as model states, trying a change on a "
    "branch, and drawings (views, sections, dimensions, PDF and DXF). Use "
    "whenever the user asks to model, change, check or save a part, "
    "assembly or drawing in "
    "InventCraft, or mentions .icpart, .icasm or .icdraw files.")


def _placeholders(p: prompts.Prompt) -> Dict[str, str]:
    return {a.name: "<%s>" % a.name for a in p.args
            if a.name not in ("save_to", "doc")}


def skill_md() -> str:
    lines: List[str] = [
        "---",
        "name: %s" % NAME,
        "description: %s" % DESCRIPTION,
        "---",
        "",
        "# Designing in InventCraft",
        "",
        "InventCraft is a parametric, history-based modeller. The MCP "
        "server's tools build parts headless; what you build is an "
        "ordinary feature tree a person can open and edit in the app. "
        "Build a design someone can change, not only the right shape.",
        "",
        "## The loop",
        "",
        prompts.LOOP,
        "",
        "In Claude Code the guides are also in `guides/` next to this "
        "file; the server serves the same text as `ic://guide/{topic}`.",
        "",
        "## Rules that prevent most failures",
        "",
        "- Parameters first, in the same build() as the features that use "
        "them; sheet metal needs `Thickness` and `BendRadius`.",
        "- Never pick faces or edges by index: references by definition "
        "(`Extrusion1.end`, `Hole1.wall[0]`), edge queries "
        "(`{\"along\":\"z\"}`), or `@F:` handles from find_geometry().",
        "- A failed build changed nothing. Read `kind` and `hints`, fix "
        "that op, and send the build again.",
        "- Check numbers (inspect() with `expected`, requirements) before "
        "pictures (render_view()), and both before saying it is done.",
        "- Holes go in with the hole op at sketch points; patterns repeat "
        "features (`parents`), with counts and spacings as expressions.",
        "- save_document() takes an absolute path; never overwrite a file "
        "unless the user said so.",
        "",
        "## Workflows",
        "",
        "The same workflows are MCP prompts (in Claude Code "
        "`/mcp__inventcraft__<name>`). Follow the one that fits.",
        "",
    ]
    for p in prompts.PROMPTS.values():
        text = p.body(**_placeholders(p))
        # the loop is said once above
        text = text.replace(prompts.LOOP, "(the loop above)")
        lines += ["### %s" % p.name, "", p.description, "",
                  "Guides: %s." % ", ".join(
                      "[%s](guides/%s.md)" % (g, g) for g in p.guides),
                  "", text, ""]
    if prompts.LEFT_OUT:
        lines += ["Not offered yet: %s." % "; ".join(
            "%s (%s)" % kv for kv in prompts.LEFT_OUT.items()), ""]
    lines += ["## Reference", ""]
    for topic, (title, summary) in guides.TOPICS.items():
        lines.append("- [%s](guides/%s.md): %s" % (title, topic,
                                                      summary))
    return "\n".join(lines) + "\n"


def generate(facts: Dict[str, Any]) -> Dict[str, str]:
    """Every file of the skill, by its path inside the skill folder."""
    out = {"SKILL.md": skill_md()}
    for topic in guides.TOPICS:
        out["guides/%s.md" % topic] = guides.render(topic, facts)
    return out


def write(files: Dict[str, str], folder: str) -> List[str]:
    written = []
    for rel, text in files.items():
        path = os.path.join(folder, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        written.append(path)
    return written


def shipped() -> Dict[str, str]:
    out = {}
    for root, _dirs, names in os.walk(SHIPPED):
        for name in names:
            path = os.path.join(root, name)
            rel = os.path.relpath(path, SHIPPED).replace(os.sep, "/")
            with open(path, encoding="utf-8") as fh:
                out[rel] = fh.read()
    return out


def install(dest: Optional[str] = None, user: bool = False,
            force: bool = False) -> str:
    """Copy the shipped skill into a skills folder; returns where."""
    if dest:
        base = dest
    elif user:
        base = os.path.join(os.path.expanduser("~"), ".claude", "skills")
    else:
        base = os.path.join(os.getcwd(), ".claude", "skills")
    target = os.path.join(base, NAME)
    if os.path.exists(target):
        if not force:
            raise FileExistsError("%s exists; pass --force to replace it"
                                  % target)
        shutil.rmtree(target)
    shutil.copytree(SHIPPED, target)
    return target


def facts_in_process() -> Dict[str, Any]:
    """guide_facts from a host in this process (imports the kernel)."""
    from ..bridge.host import InProcessHost
    return InProcessHost().call("guide_facts")


def main(argv: List[str]) -> int:
    import argparse
    if argv and argv[0] == "write-skill":
        for path in write(generate(facts_in_process()), SHIPPED):
            print(path)
        return 0
    parser = argparse.ArgumentParser(prog="python -m datum.mcp install-skill")
    parser.add_argument("--user", action="store_true",
                        help="install into ~/.claude/skills")
    parser.add_argument("--dest", help="install into this skills folder")
    parser.add_argument("--force", action="store_true",
                        help="replace an installed copy")
    args = parser.parse_args(argv[1:])
    try:
        print("installed the %s skill in %s" % (NAME, install(
            args.dest, args.user, args.force)))
    except FileExistsError as exc:
        print(exc)
        return 1
    return 0
