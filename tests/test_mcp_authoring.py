"""Freeform authoring through the MCP server alone, with a real client:
splines, ellipses and planes by numbers, colour, shaded and sectioned
pictures, many parts in one call, and a clash check that can be finished.
"""
import asyncio
import base64
import json
import math
import os
import struct
import sys
import tempfile
import zlib

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(errors="replace")
    except Exception:
        pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from mcp import ClientSession                               # noqa: E402
from mcp.client.stdio import StdioServerParameters, stdio_client  # noqa: E402

FAILS = []
TMP = tempfile.mkdtemp(prefix="datum_authoring_").replace(chr(92), "/")


def check(name, cond, extra=""):
    print(("  PASS  " if cond else "  FAIL  ") + name
          + (("  " + str(extra)) if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


def payload(result):
    for c in reversed(result.content):
        if getattr(c, "type", "") == "text":
            try:
                return json.loads(c.text)
            except ValueError:
                continue
    return {}


def text(result):
    return " ".join(getattr(c, "text", "") for c in result.content)


def pixels(result):
    """The rows of the picture in a result, as (r, g, b)."""
    data = next(base64.b64decode(c.data) for c in result.content
                if getattr(c, "type", "") == "image")
    at, body, width, height = 8, b"", 0, 0
    while at < len(data):
        size, tag = struct.unpack(">I4s", data[at:at + 8])
        chunk = data[at + 8:at + 8 + size]
        if tag == b"IHDR":
            width, height = struct.unpack(">II", chunk[:8])
        elif tag == b"IDAT":
            body += chunk
        at += 12 + size
    raw, rows = zlib.decompress(body), []
    for y in range(height):
        start = y * (width * 3 + 1)
        line = bytearray(raw[start + 1:start + 1 + width * 3])
        if raw[start] == 1:
            for i in range(3, len(line)):
                line[i] = (line[i] + line[i - 3]) & 255
        rows.append([tuple(line[i:i + 3]) for i in range(0, len(line), 3)])
    return rows


AIRFOIL = [[100, 0.6], [70, 4], [30, 7], [5, 4], [0, 0], [5, -3], [30, -4],
           [70, -1.5], [100, -0.6]]

PIN = '''
s = sketch(plane={"origin": [X, 0, 0], "normal": [0, 0, 1]},
           entities=[{"ellipse": {"rx": R, "ry": R / 2.0}}])
extrude(s, H)
op("properties", appearance=COLOUR)
'''


async def freeform(call):
    print("freeform sketches")
    r = await call("new_document")
    ops = [{"op": "parameter", "name": "L", "value": 120}]
    for i, (x, f) in enumerate((("0", "0.5"), ("L/2", "1"), ("L", "0.3"))):
        ops.append({"op": "sketch", "id": "s%d" % i, "plane": {
            "origin": [x, 0, 0], "normal": [1, 0, 0], "x": [0, 1, 0]},
            "entities": [{"ellipse": {"rx": "20*" + f, "ry": "14*" + f}}]})
    ops.append({"op": "loft", "sections": ["$s0", "$s1", "$s2"]})
    ops.append({"op": "properties", "appearance": "#C8102E"})
    r = await call("build", ops=ops)
    check("ellipses on planes by numbers loft into a body",
          not r.is_error and "1 solid" in text(r), text(r)[:300])
    before = payload(await call("inspect"))
    await call("properties", parameters={"L": 180})
    after = payload(await call("inspect"))
    check("the planes follow their parameter",
          abs(after["bbox"][0] - before["bbox"][0] - 60) < 0.2
          and abs(after["volume"] / before["volume"] - 1.5) < 0.01,
          (before["bbox"], after["bbox"]))
    check("the colour a build sets is kept",
          payload(await call("properties")).get("appearance") == "#c8102e")
    r = await call("properties", appearance="not a colour")
    check("an unknown colour is refused with the names there are",
          r.is_error and "#rrggbb" in text(r), text(r)[:200])
    r = await call("render_view", style="shaded", width=240, height=160)
    middle = pixels(r)[80][120]
    check("a shaded view is in that colour",
          middle[0] > 60 and middle[0] > 2 * middle[1], middle)
    r = await call("render_view", style="shaded", width=240, height=160,
                   view="front", section="XZ")
    middle = pixels(r)[80][120]
    check("a section shows the cut face",
          middle[0] > 160 and 60 < middle[1] < 110, middle)
    r = await call("render_view", section="XZ")
    check("a section of a line view is refused, not ignored", r.is_error)
    out = payload(await call("read_ir"))["ops"]
    await call("new_document")
    r = await call("build", ops=out)
    again = payload(await call("inspect"))
    check("the tree reads back and builds the same body, colour and all",
          not r.is_error and abs(again["volume"] - after["volume"]) < 1e-2
          and payload(await call("properties"))["appearance"] == "#c8102e")

    await call("new_document")
    ops = [{"op": "sketch", "id": "w%d" % i, "plane": {
        "origin": [0, y, 0], "normal": [0, -1, 0], "x": [1, 0, 0]},
        "entities": [{"spline": AIRFOIL, "closed": "line", "id": "af"}]}
        for i, y in enumerate((0, 250))]
    ops.append({"op": "loft", "sections": ["$w0", "$w1"], "ruled": True})
    r = await call("build", ops=ops)
    got = payload(await call("inspect"))
    area = got.get("volume", 0) / 250.0
    check("a spline airfoil lofts into one solid",
          not r.is_error and got.get("solids") == 1 and 600 < area < 900,
          text(r)[:300])
    await call("new_document")
    ring = [[30 * math.cos(math.pi * i / 4), 20 * math.sin(math.pi * i / 4)]
            for i in range(8)]
    r = await call("build", ops=[
        {"op": "sketch", "id": "s", "plane": "XY",
         "entities": [{"spline": ring, "closed": True}]},
        {"op": "extrude", "sketch": "$s", "distance": 10}])
    got = payload(await call("inspect"))
    check("a closed spline extrudes, and measures true",
          not r.is_error and abs(
              got.get("volume", 0) - math.pi * 6000) < 190, text(r)[:300])
    await call("new_document")
    r = await call("run_script",
                   code='X, R, H, COLOUR = 5, 8, 12, "#203060"' + PIN)
    check("run_script keeps the colour it set", not r.is_error and payload(
        await call("properties")).get("appearance") == "#203060",
        text(r)[:300])


async def project(call):
    print("many parts in one call")
    top = TMP + "/demo.icasm"
    good = [{"file": "%s/%s.icpart" % (TMP, name), "code":
             'X, R, H, COLOUR = %d, 10, 30, "%s"' % (x, colour)}
            for name, x, colour in (("A", 0, "#c8102e"), ("B", 12, "#1040a0"),
                                    ("C", 80, "#20a040"), ("D", 84, "#808080"))]
    for part in good:
        part["code"] += "\nmake()"
    shared = "def make():\n" + "\n".join(
        "    " + line for line in PIN.strip().split("\n"))
    broken = {"file": TMP + "/E.icpart", "ops": [
        {"op": "extrude", "sketch": "nothing", "distance": 5}]}
    r = await call("build_project", parts=good + [broken], assembly=top,
                   shared=shared)
    got = payload(r)
    check("one bad part is reported and the rest are made",
          r.is_error and got.get("built") == 4 and got.get("failed") == 1,
          text(r)[:500])
    check("the bad one is not written",
          not os.path.exists(TMP + "/E.icpart"))
    check("the others are in the assembly",
          (got.get("assembly") or {}).get("components") == 4,
          got.get("assembly"))
    r = await call("build_project", parts=good[:1], assembly=top,
                   shared=shared)
    check("a part that exists is not written over unasked",
          "WOULD_OVERWRITE" in text(r), text(r)[:300])
    r = await call("build_project", parts=good[:1], assembly=top,
                   shared=shared, overwrite=True)
    got = payload(r)
    check("asked, it is, and is not placed a second time",
          not r.is_error and got["assembly"]["components"] == 4
          and got["assembly"]["placed"] == 0, text(r)[:400])
    doc = got["assembly"]["doc"]

    r = await call("build_project", safe_mode=True, parts=[
        {"file": TMP + "/S.icpart", "code": "import subprocess"}])
    check("safe_mode holds in build_project too",
          r.is_error and "subprocess" in text(r)
          and not os.path.exists(TMP + "/S.icpart"), text(r)[:300])
    from datum.mcp import server
    hints = {t.name: t.annotations for t in await server.server.list_tools()}
    check("build_project says it runs code, as run_script does",
          hints["build_project"] == hints["run_script"])

    r = await call("render_view", doc=doc, style="shaded", view="front",
                   width=300, height=150)
    seen = [p for row in pixels(r) for p in row]
    check("an assembly is drawn in each part's own colour",
          any(p[0] > 70 and p[0] > 2 * p[1] for p in seen)
          and any(p[2] > 70 and p[2] > 2 * p[0] for p in seen))

    print("a clash check that can be finished")
    full = payload(await call("assembly_check", doc=doc))
    inter = full["interference"]
    check("both overlaps are found, every pair tested",
          inter["count"] == 2 and inter["complete"] and not full["ok"], inter)
    meant = [["A*", "B*"]]
    part = payload(await call("assembly_check", doc=doc, allow=meant))
    inter = part["interference"]
    check("a meant overlap is apart, the other is still a fault",
          inter["count"] == 1 and inter["allowed"]["count"] == 1
          and not part["ok"], inter)
    both = meant + [["D*", "C*"], ["Z*", "A*"]]
    done = payload(await call("assembly_check", doc=doc, allow=both))
    check("all of them meant is ok, and a pattern that matched none is said",
          done["ok"] and done["interference"]["allow_unused"] == [["Z*", "A*"]],
          done["interference"])


def resumed():
    from datum.bridge import ops, assembly_ops  # noqa: F401 (ops first)
    from datum.core.assembly import AssemblyDocument
    d = AssemblyDocument.load(TMP + "/demo.icasm")
    d.rebuild()
    first = assembly_ops.find_interference(d, budget=-1.0)
    check("out of time, it says it is not complete and where to go on",
          not first["complete"] and first["next_start"] == 1, first)
    rest = assembly_ops.find_interference(d, start=first["next_start"])
    check("resumed, every pair has been tested once",
          rest["complete"]
          and first["pairs_tested"] + rest["pairs_tested"]
          == first["pairs_total"]
          and first["count"] + rest["count"] == 2, (first, rest))


async def main():
    env = dict(os.environ, PYTHONPATH=ROOT, INVENTCRAFT_ALLOW_DIRS=TMP,
               # never the real app's pairing
               INVENTCRAFT_AGENT_DIR=tempfile.mkdtemp(prefix="datum_pair_"))
    params = StdioServerParameters(
        command=sys.executable, cwd=ROOT, env=env,
        args=["-m", "datum.mcp", "--host", "headless"])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            async def call(tool, **args):
                return await session.call_tool(tool, args)

            await freeform(call)
            await project(call)


if __name__ == "__main__":
    asyncio.run(main())
    resumed()
    print()
    if FAILS:
        print("%d FAILURES: %s" % (len(FAILS), ", ".join(FAILS)))
        sys.exit(1)
    print("all mcp authoring tests passed")
