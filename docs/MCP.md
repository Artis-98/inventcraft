# InventCraft MCP server: user guide

Lets an AI agent (Claude Code, Claude Desktop, Cursor, OpenCode, any MCP
client) design parts, assemblies and drawings in InventCraft. What the agent
builds lands in the part's feature tree as ordinary features that you can open
and edit. This page is for using it.

What it covers: the full feature tree, constrained sketches, review tools
(`diff`, `snapshot`, `branch`), geometry references that survive edits,
measuring, requirements stored in the part, scripts and code features,
assemblies (place, constrain, check, bill of materials), model states, drawings,
sheet metal flats, frames and top-down skeletons, `evaluate` and `optimise`
(variants on the worker pool, the lightest design that clears the
requirements), and `recognize` and `parametrize` (a STEP import read back
into an editable tree). Everything is made headless, or in the running app
(below), where the agent also sees what you have selected and hears about
your edits.

Contents: [Install](#install) · [Connect a client](#connect-a-client) ·
[Check it works](#check-it-works) · [Drive the running app](#drive-the-running-app) ·
[Tool groups](#tool-groups) · [Safety model](#safety-model) · [Tools](#tools) ·
[Guidance for the agent](#guidance-for-the-agent) ·
[Things to know](#things-to-know) · [Tests](#tests) ·
[Benchmarking agents (Tier 2)](#benchmarking-agents-tier-2) ·
[HTTP transport](#http-transport)

## What an agent built with it

An A320-class twin-jet airliner at 1:30: 54 components from 41 parts, made only
through this server's tools (`build_project`, `render_view`, `assembly_check`),
with every clash checked and the flaps and landing gear tested through their
motion. The files are in the project's `scratch/a320-mcp` folder with a design
note; the pictures below came from `render_view`.

![Three-quarter view](mcp/airliner-three-quarter.png)
![From above](mcp/airliner-above-side.png)
![Wing, gear and engine](mcp/airliner-high-angle.png)
![Wing structure, spars and ribs](mcp/airliner-structure.png)


## Install

From source: a Python 3.14 virtual environment with the project's
requirements (`cadquery-ocp`, `PySide6`, `numpy`) plus the `mcp` SDK.
Nothing else is needed: the server starts a windowless copy of InventCraft
(the *host*) on the first call. An installed build runs the same server as
`InventCraft.exe --mcp`.

Optionally install the Claude Code skill, the guides as files an agent
loads (see [Guidance for the agent](#guidance-for-the-agent)).

## Connect a client

**Claude Code.** Register the server once:

```bash
claude mcp add inventcraft -- <checkout>/.venv/bin/python -m datum.mcp
```

On Windows the interpreter is `<checkout>\.venv\Scripts\python.exe`. Or copy
[examples/mcp/mcp.json](../examples/mcp/mcp.json) to `.mcp.json` and set the
paths. Add `"--tools", "all"` to `args` for the opt-in groups, `"--allow-dir",
"D:\Parts"` for a folder outside the project.

**Other clients** (Claude Desktop, Cursor, any `mcpServers` config): the same
`command` and `args`. A client that is not started in the project folder must
say where files may go: the client's *roots*, or `--allow-dir` (see
[Safety model](#safety-model)).

**OpenCode.** Copy [examples/mcp/opencode.json](../examples/mcp/opencode.json).

**Installed build.** `InventCraft.exe --mcp [options]` takes the same
options.

If the geometry kernel crashes, only the host goes down. The server reports
`HOST_LOST`, and the next call starts a fresh host. Saved files are safe, but
unsaved documents in that host are lost.

## Check it works

```bash
python -m datum.mcp --selftest
InventCraft.exe --mcp --selftest
```

It starts the server the way a client would, in a temporary folder: lists
the tools, makes a part, builds a plate with a hole, inspects it, renders it,
saves it, opens it again, and checks that a path outside the allowed folders
is refused. It prints one line per step with its time, then `PASS` or
`FAIL`, and exits 0 or 1 (about four seconds when it passes):

```
  start server and handshake                             1.54 s
  list tools (31)                                        0.02 s
  ...
PASS  inventcraft-mcp selftest: 9 steps, 3.6 s
```

Then ask the agent to call `status`.

## Drive the running app

Off by default. To let an agent edit what is open in InventCraft:

1. In InventCraft: Preferences > AI > tick **Allow agents**. A status-bar
   label says "Agents: allowed". The app writes `bridge.json` (a secret
   and the pipe's name) to its config folder, `%APPDATA%\IITEG\DATUM`;
   only your user can read it, and it is deleted when you untick the box
   or close the app. Each time it is switched on the secret is new.
2. Run the server as usual. It finds the file and pairs by itself. The
   `status` tool then shows `gui_host.connected`, and the app's documents
   have handles `g1`, `g2`... (headless ones `d1`...).

`--host auto|headless|gui` (an argument of `python -m datum.mcp`) says
where NEW documents are made: `auto` in the app when it is connected,
else headless; `gui` only in the app (an error if it is not there);
`headless` never in the app. A document that is open in the app is
always edited through its `g` handle.

What you see and can do:
- Every `build`, `edit_feature`, `properties`, `requirements` or snapshot
  restore is **one undo step**: Ctrl+Z takes the whole agent change back.
- A copy of the document is saved first, in `agent-autosave\` beside
  `bridge.json` (the last five per document).
- While a request runs or waits the status bar shows **Agent working**
  with a **Stop** button: it drops what is queued and ends a running build
  at its next step, rolled back. The window ignores clicks meanwhile.
- The app never runs agent code. `run_script` runs in a separate process
  and arrives as build ops. A `code` op shows you its source and runs only
  if you click Allow (once per source, this session).
- An agent is refused (`USER_BUSY`) while you are in a sketch or a feature
  dialog on that document, and cannot close your documents. If you edit a
  document its revision moves, so an agent working from an older read is
  refused (`STALE_REVISION`), with `changes` saying which features were
  added, removed or edited and which parameters changed, and must read it
  again.
- **A document open in the app is edited in the app.** Naming it by its
  path (`doc`) or opening its path again gives the same `g` handle, never
  a second copy; a headless host refuses to save or export over a file the
  app has open (`FILE_OPEN_IN_APP`).
- **"Fillet this."** `get_selection` returns what you have picked as
  references the agent can pass straight to `build`. Faces and edges are
  named by what made them (`Extrude.end`,
  `Extrude.end.edge(side(#e3))`), so they keep working when the model
  changes; anything else is an `@F`/`@E` handle. Features picked in the
  tree, sketch entities and points while you sketch, and assembly
  occurrences come back too. Only the document the app shows has a
  selection, and `status` carries a count of it.
- **Subscriptions.** `ic://selection`, `ic://documents` and
  `ic://doc/{id}/tree` (and `.../parameters`) send
  `notifications/resources/updated` when you change the selection, open or
  close a document or edit a tree (an agent's own changes are not told
  back to it). Bursts are one notification. Both protocol eras are served:
  `resources/subscribe` and the newer `subscriptions/listen`.

## Tool groups

`--tools` chooses the optional groups: comma separated `default`, `all`,
`none`, `+group` and `-group`. The default surface is **31 tools**:

| Group | On by default | Tools |
|---|---|---|
| (core) | yes | `status`, `new_document`, `open_document`, `save_document`, `close_document`, `export`, `get_selection`, `model_tree`, `properties`, `inspect`, `render_view`, `build`, `edit_feature`, `read_ir`, `sketch_status`, `diff`, `snapshot`, `branch`, `model_states`, `find_geometry`, `measure`, `requirements`, `evaluate`, `optimise`, `recognize`, `parametrize`, `run_script` |
| `assembly` | yes | `place_component`, `constrain`, `assembly_check`, `bom` |
| `drawing` | no | `drawing_create`, `drawing_base_view`, `drawing_projected_view`, `drawing_section_view`, `drawing_detail_view`, `drawing_dimension`, `drawing_note`, `drawing_parts_list`, `drawing_render`, `drawing_export` |
| `sheetmetal` | no | `sheet_rules`, `flat_pattern`, `sheet_check` |
| `frames` | no | `frame_profiles`, `frame_insert`, `frame_treat`, `cut_list` |
| `skeleton` | no | `skeleton_params`, `derive_part`, `skeleton_set` |

`--tools default,-assembly` leaves the four assembly tools out (documents of
type assembly still open and read); `--tools +drawing` adds a group; `--tools
all` is every group (51 tools). `branch` and `model_states` are in no group.
Keeping the surface small is a benchmark result, not a taste.

## Safety model

Anything that can be undone runs freely; anything irreversible asks.

- **File access.** Every path a tool names (`open_document`, `save_document`,
  `export`, `place_component`, `derive_part`, a drawing's model and exports,
  flat patterns, cut lists, the file of an `import` op) must lie inside the
  **client's MCP roots** when the client provides roots. Otherwise it must lie
  inside the **project folder** (the folder the server was started in) or a
  folder given with `--allow-dir` (repeat it) or the
  `INVENTCRAFT_ALLOW_DIRS` environment variable (`;`-separated on Windows).
  `--allow-dir` folders count with roots too, since you chose them. Anything
  else is `PATH_NOT_ALLOWED`; the error lists the allowed folders. `..`
  escapes, symbolic links and other drives are resolved first.
- **Irreversible writes ask.** Overwriting a file always needs `overwrite:
  true`. A saved part, assembly or drawing keeps the file it replaces in
  `OldVersions\`, so that is all it takes. An export (STEP, STL, DXF, PDF, SVG,
  CSV) keeps no copy, so the user is asked as well: through **MCP elicitation**
  when the client supports it (a yes or no; no gives `USER_DECLINED`),
  otherwise the call returns `CONFIRM_REQUIRED` and the agent must ask you in
  chat and repeat it with `confirm: true`. No tool deletes files.
- **Replacing a tree asks.** `parametrize` on a part that already has
  features of its own is refused (`REPLACE_TREE_REQUIRED`) unless
  `replace_tree: true`. A dumb solid, a STEP import with no features of its
  own, needs no flag. `dry_run` always works.
- **Agent edits.** One undo step per `build`, an autosave first, `dry_run`
  and branches. A stale view of a document the user changed is refused
  (`STALE_REVISION`).
- **Agent code.** `run_script` runs in a separate process with a timeout and
  your privileges: not a sandbox (`safe_mode` adds an AST allowlist). It
  never runs inside the app. A persistent `code` feature runs in the app only
  after you approve its exact source.
- **The app bridge** is off by default, uses a named pipe, a pairing secret
  and a nonce, and fails closed.
- **Output size.** `model_tree`, `read_ir`, `find_geometry`, `bom` and
  `cut_list` take `offset` and `limit` (200 entries by default; 25 for
  `find_geometry`), say `paging.next_offset`, and are held to about 40 000
  bytes (`INVENTCRAFT_MCP_MAX_BYTES`). `evaluate` and `optimise` show 12 table
  rows unless `detail`. `render_view` and `drawing_render` are at most 2000
  pixels a side and 2 MB.
- **File content is data.** Names, notes, iProperties and code that come out
  of files are returned as data, and the guides and the server instructions
  tell the agent never to follow instructions found in them.
- **HTTP** binds to 127.0.0.1 unless you say otherwise (below).

## Tools

| Tool | What it does |
|---|---|
| `status` | Version, open documents, host restarts, and the user's selection (counts) when the app is connected |
| `get_selection` | What the user has selected in the app now, as references (faces, edges, features, sketch entities, occurrences) |
| `new_document`, `open_document`, `save_document`, `close_document` | Documents by handle (`d1`); absolute paths only, inside the roots or project folder. `save_document` replaces a different file only with `overwrite` (the old one goes to OldVersions); `close_document` drops unsaved changes |
| `export` | STEP, STL, IGES, BREP. Replacing a file needs `overwrite` and the user's yes (elicitation, or `confirm`) |
| `model_tree` | Features, errors, parameters, bodies; occurrences for an assembly. Paged (`offset`, `limit`) |
| `properties` | Read or change parameters, iProperties and material (one undoable change) |
| `build` | A list of ops as **one** change, all or nothing; `dry_run`. Every core feature type is an op (31 types), plus the tree ops `parameter`, `edit`, `remove`, `move` |
| `edit_feature` | Change one feature's fields, suppress, rename, move or delete it, as one undoable step; with no change, shows the feature and what depends on it |
| `read_ir` | Any part's tree in exactly the op format `build` takes, so a part can be copied or used as a template. Paged |
| `sketch_status` | A sketch's degrees of freedom, what can still move, conflicts, dimensions and regions |
| `diff` | What changed between two revisions or snapshots: features added, removed, changed or moved, and parameters |
| `snapshot` | Save, restore, list or drop named copies of a part (in memory) |
| `inspect` | Size, volume, mass, validity; `expected` gives a pass/fail verdict |
| `render_view` | A line drawing as an image; `highlight` shows what references name, `highlight_edges` what an edge query picks |
| `find_geometry` | Faces, edges or vertices by rule (type, normal, along, at, near, largest, area/length/radius ranges, hole, `created_by`, `on`), each with an `@F:`/`@E:`/`@V:` handle and a one-line description; `offset` pages |
| `measure` | One reference (area, normal, radius, length, position, a body's volume and box), or two (least distance, angle, plane gap, axis distance, centre distance) |
| `requirements` | Read, set or remove what the part must be (mass, bbox, volume, clearance, hole count, parameter range); stored in the part, checked on every rebuild, reported in every build |
| `run_script` | Python against the part in a separate host on a copy; what it changed is applied as one build. `timeout`, `safe_mode`, `dry_run`. Not a sandbox |
| `place_component` | `+assembly`. Place a saved part or sub-assembly file in an assembly, with a name and an optional `transform`; the first is grounded |
| `constrain` | `+assembly`. Mate, flush, insert, tangent, angle or parallel between a face or edge of one occurrence and one of another; atomic, refused when nothing can satisfy it |
| `assembly_check` | `+assembly`. Degrees of freedom per component, failed and redundant constraints, interference (pair, volume, place) |
| `bom` | `+assembly`. Flat and structured bill of materials: quantity, part number, description, material, mass. Paged |
| `model_states` | A part's variations (a bolt at five lengths, with and without its holes): `list` (`measure` builds each and gives volume, mass and size), `create`, `activate`, `set`, `delete`; one tool because every action takes the same arguments |
| `evaluate` | Try variants of a part without changing it: `variations` (a list of parameter overrides, with optional `state` and `name`) or a `grid` (every combination), on the worker pool, one table row per variant: mass, volume, bbox, faces, valid, every stored requirement's pass or fail and value, and `clearances` between references. A variant that fails to build is a row with its error. Reports progress; Stop or a cancel ends it between variants. Never touches the open document |
| `optimise` | Search `vary` (parameter ranges, lists or steps) for the best design that clears every stored requirement (and `subject_to` extras): `objective` `min mass`, `min volume`, `min bbox.x`, `max req:<name>`, `min param:<name>`; a coarse grid then a compass search, `budget` evaluations. Answers the best feasible design against the start, the table, and `failed_by`. Changes nothing unless `apply=true`: one undo step, or on a new `branch` to diff and merge |
| `recognize` | Read a dumb solid (a STEP import) and report what it is made of, changing nothing: the base prism, through and blind holes (counterbore, countersink), patterns on a line, grid or circle, pockets, bosses, constant-radius fillets and chamfers, each with measured values and the parameters a rebuild would name; coverage (share of faces and area, counted on the rebuilt body), the residual volume of a boolean difference, and `unexplained` faces with `@F` handles. `body` names a solid, `detail` adds the ops, `check=false` skips the scratch rebuild
| `parametrize` | Replace the import with an editable tree (named parameters, stored edge rules), checked first against the original (volume, box, boolean difference both ways within `tolerance`); one undo step. **Partial coverage is refused** (`PARTIAL_COVERAGE`, nothing changed, the report in the error). A part that already has features of its own needs `replace_tree=true` (`REPLACE_TREE_REQUIRED`). `dry_run`, `plan` (`names` to rename parameters, `ops` of your own, checked the same way), `verify`
| `branch` | Work on a copy of a saved design: `create`, `switch`, `check_in`, `merge` (a conflicting merge is refused and listed), `discard`, `list`; built on the file's version history; `diff` takes `branch:<name>` |
| `drawing_create` | `+drawing`. A new drawing (.icdraw) of a saved part or assembly: sheet size, standard, template, title block properties |
| `drawing_base_view`, `drawing_projected_view`, `drawing_section_view`, `drawing_detail_view` | `+drawing`. The views, laid out clear of each other and of the title block at a standard scale; a projection by `place` (right, below, iso...) or by the view you want (`shows`); a section by a vertical or horizontal cut; a detail by centre and radius |
| `drawing_dimension`, `drawing_note`, `drawing_parts_list` | `+drawing`. Overall, linear, diameter and radius dimensions tied to the model, notes and leaders, automatic hole notes and centre marks, a parts list with balloons for an assembly |
| `drawing_render`, `drawing_export` | `+drawing`. The sheet as a PNG; PDF (every sheet), DXF, SVG or PNG to a path (refuses to overwrite; `overwrite` plus the user's yes) |
| `sheet_rules` | `+sheetmetal`. A part's sheet metal rules, read or set: thickness, bend radius, K-factor (0 to 1, default 0.44), corner gap; setting converts the part |
| `flat_pattern` | `+sheetmetal`. A sheet metal part laid flat: size, area, blank mass and the bend list (angle, inside radius, line, allowance, which way it folds); `path` writes a DXF (outline and holes on `OUTER_PROFILE`, bend centre lines on `BEND_CENTERLINE`); `k_factor` tries another value |
| `sheet_check` | `+sheetmetal`. Manufacturing rules with numbers: bend radius under 0.5 t, K-factor outside 0.25 to 0.5, flange under 4 t, hole within 2 t of a bend, a part that will not unfold (relief wanted: t wide, t + r deep) |
| `frame_profiles` | `+frames`. The profile library: families, columns and sizes |
| `frame_insert` | `+frames`. Members of a library profile along a skeleton sketch's lines, one part each, in a frame beside the assembly that follows the skeleton; later inserts add to the same frame |
| `frame_treat` | `+frames`. End treatments, kept in the frame and made again when the skeleton changes: `miter` (named pairs, or `corners` for every corner of a sketch), `corner`, `trim_face`, `notch`, `lengthen`; `remove` |
| `cut_list` | `+frames`. Pieces grouped by profile, cut length (mitres included), end angles, quantity and mass, and totals; `path` writes a .csv; paged |
| `skeleton_params` | `+skeleton`. Retrieve every parameter of the assembly's parts by the name an expression reaches it with (`Skeleton_L`), the assembly's own, and which expression drives which part parameter |
| `derive_part` | `+skeleton`. A part follows the skeleton: parameters set by expressions over the skeleton's and others', kept by the assembly (the part stays an ordinary part), written into the part's file |
| `skeleton_set` | `+skeleton`. Change a master parameter: the skeleton and every derived part are rebuilt and saved, the frame follows its lines, constraints written over parameters move; refused whole if a part will not build |

`new_document(type="assembly")` makes an assembly; `edit_feature` edits
its occurrences (`"Wheel:1"`) and constraints (`"Mate:2"`), and
`properties` its parameters, so offsets can be expressions.

A drawing is a document like the others: `drawing_create` makes it (a new
tab in the app), `open_document` opens an `.icdraw`, `save_document` saves
it, `model_tree` lists its sheets, views (name, scale, position, size in
model mm) and annotations, `edit_feature` moves, rescales or deletes a view
(by name) or an annotation (by `#id`), and `properties(props=...)` fills the
title block. Each change is atomic, one undo step in either host, and a
view that cannot be drawn (a cut that misses the part) is refused with the
drawing as it was. A drawing shows the model as last saved; when the model
changes, `drawing_render` and `drawing_export` draw the views again first.

The op format is in the `build` tool's description, which the agent sees.
The schema of every op is **generated** from the core's feature types and
served as the resource `ic://schema/op/{type}`; `ic://schema/ops` lists
them. A feature type added to the core reaches the agent with no MCP code.

Resources: `ic://status`, `ic://selection`, `ic://documents`, `ic://doc/{doc}/tree`,
`ic://doc/{doc}/parameters`, `ic://doc/{doc}/sketch/{sketch}`,
`ic://doc/{doc}/requirements`, `ic://doc/{doc}/states`, `ic://materials`, `ic://schema/ref` (the
reference grammar), `ic://schema/ops`, `ic://schema/op/{type}`, and the
guides `ic://guide` (the list) and `ic://guide/{topic}`.

## Guidance for the agent

**Guides** are short markdown pages the agent reads as resources:
`workflow` (read first), `sketches`, `references`, `units`,
`requirements`, `scripts` (`run_script` vs `code`), `sheet-metal`,
`frames`, `skeleton`, `assemblies`, `drawings`, `model-states`,
`branches`, `explore`, `import`, `safety`, `errors`.
Their tables (constraints, dimensions, reference
forms, query keys, metrics, code helpers, profile families, every error
kind with its fix) are written from the code at read time, through the
host's `guide_facts`, so they cannot drift. The server's instructions are
short and point to them.

**Prompts** walk through whole jobs; in Claude Code they are slash
commands such as `/mcp__inventcraft__design-part`:

| Prompt | For | Not yet (said in the prompt) |
|---|---|---|
| `design-part` | any part from a description, standard parts included | |
| `sheet-metal-enclosure` | a box from a base face and flanges, then the rules, the check and the flat pattern with a DXF (needs `--tools +sheetmetal`) | hems and forming tools in the flat |
| `weldment-frame` | a frame of library profiles on a skeleton: members, mitres, cut list, shown to follow the skeleton (needs `+frames` and `+skeleton`; one-part fallback without) | pipes, notch and corner joints are less tested than mitres |
| `skeleton-design` | top-down: master parameters and layout sketches in one part, a frame and plates derived from it, placed, checked, and a parameter changed (needs `+skeleton`, `+frames`) | a derived part that projects the skeleton's edges (the app's adaptive link) |
| `part-family` | one part whose variants are its model states, with a measured table | a family sweep with `evaluate` (variants may name a `state`; the prompt does not yet) |
| `drawing-package` | a dimensioned drawing of a saved part or assembly: views, section, detail, dimensions, parts list and balloons, PDF and DXF (needs `--tools +drawing`) | several sheets, auxiliary and broken views, GD&T |
| `optimise-design` | requirements first, `evaluate` to look, `optimise` to search, applied on a branch and merged | changes of form (a rib, a pocket) are `build` jobs, not a search |
| `parametrize-import` | a STEP read with `recognize`, rebuilt with `parametrize`, checked, and edited through a parameter; by hand when it refuses | oblique holes, tapers, freeform faces, several bodies, threads |
| `assembly-from-parts` | parts built and saved, placed, constrained to zero DOF, checked for interference, BOM | joints with motion, a sub-assembly's own faces |

Every prompt teaches the same loop: parameters and requirements first,
`build`, read the summary, `inspect`, `render_view`, refine, then nudge a
parameter to prove the model is parametric.

**Claude Code skill.** The same guidance ships as a skill,
`datum/mcp/skills/inventcraft/` (`SKILL.md` and the guides in
`guides/`). Install it into a project or for your user:

```powershell
C:\InventCraft\.venv\Scripts\python.exe -m datum.mcp install-skill          # .\.claude\skills\inventcraft
C:\InventCraft\.venv\Scripts\python.exe -m datum.mcp install-skill --user   # ~\.claude\skills\inventcraft
```

`--dest DIR` installs elsewhere, `--force` replaces an installed copy.
The skill is generated from the guides and prompts
(`python -m datum.mcp write-skill`), and a test fails if the shipped copy
is out of date.

## Evaluate and optimise

`evaluate` and `optimise` build variants of the open part **in isolation**:
each goes to a geometry worker as in-memory document data, so there are no
temporary files, and the open document's revision, undo stack and file are
never touched. How many run at once is bounded by the machine
(`workers.capacity()`: one core is left for the app, one worker per 3 GB,
at most six; a worker is about 230 MB), and never more than the variants.
In the app the window's own pool is used and the badge shows
`optimise 12/40`; **Stop** ends it between variants. A headless host starts
a small pool of its own for the call (and lets it go 45 s later). A variant
that does not build, or names a parameter that is not there, is a row with
its error. `optimise` is a coarse grid then a compass search (a pattern move
along every axis that helped), so it finds a good design near the limits in
a few dozen evaluations, not a proof of the optimum; give it a narrower
range to refine. See `ic://guide/explore`.

## STEP back into a tree

A STEP file is a dumb solid: `build` `{"op":"import","path":...}` gives one
feature and nothing to edit. `recognize` reads it (read-only) and
`parametrize` writes the tree. How it recognises: fillets and chamfers are
found first (a cylinder, sphere or torus patch tangent to both neighbours,
a narrow 45 degree strip, a 45 degree cone round a round edge) and taken
off with OpenCASCADE's `BOPAlgo_RemoveFeatures`, so the rest is read
sharp; the sharp body is read as a prism along x, y or z (the profile of the
larger end face, lines, arcs and circles, extruded its length); concave
cylinders and the cones and flat rings coaxial with them are holes; flat
faces across the axis between the ends are pockets (a cut from the end) or
the shoulder round a boss (a join); identical holes or bosses are a grid or
a circle. Coverage is counted on the **rebuilt** body, so it cannot flatter
itself. `parametrize` builds the tree in a scratch document, compares it
with the original, and only then replaces the import in one undo step; if
the tree is not the body it **refuses** and changes nothing, and the error
carries the report. Reads prisms, not everything: oblique holes, tapers,
freeform surfaces, threads and several bodies are not recognised (the
report lists those faces). See `ic://guide/import`.

## Things to know

- **Always mm and degrees** at the API, whatever the part's units. An inch
  part still shows inches to a person.
- **Everything is parametric.** Sketch sizes and positions become driving
  dimensions, and values can be expressions over parameters (`"w/2 - 5"`).
- **Edges are picked by rule**, for example `{"along": "z"}` or `{"at": "+z"}`.
  The rule is stored on the fillet or chamfer and run again on every
  rebuild, so a fillet stays on its edges when the part changes size. If
  someone later re-picks the edges by hand in the app, the hand pick takes over.
- **Sketches are constrained by name.** Entities carry an `id` (`l1`,
  `c1.center`, `p.s2`), and constraints and dimensions refer to those
  names. A dimension that repeats what is already fixed is made driven,
  and an impossible one is refused with the conflict named.
- **References between ops:** `"$s1"`, `"$s1.region[0]"`, `"$s1.c1.center"`,
  `"$e1.end"`. Faces are picked by `{"faces": {"normal": "+z"}}` and kept as
  references (edges by a query, which is stored and re-run).
- **Geometry references are readable strings:** `Extrusion1.end`,
  `Extrusion1.side(r.top)`, `Hole1.wall[0]`, `Hole1.cbore[0]`,
  `Sketch1.region[0]`, `Sketch1.c1.center`, `@F:3a7c0e` (a handle from
  `find_geometry`), `body:Name`, `part`; also `Fillet1.face[0]`,
  `Hole1.shoulder[0]` and the edge between two faces,
  `Extrusion1.end.edge(side(r.top))`. Every answer says how each
  resolved: `via: role` (tried first: the part remembers which feature
  made which face, so it follows any parameter change, a feature inserted
  earlier and a sketch written out again), `definition` (worked out from
  the feature's own inputs, where there is no provenance for the face) or
  `fingerprint` (a handle, which keeps the roles of its face and falls
  back to where the face was, noting that it did; fails as `STALE_REF`
  after big changes). `build` and `edit_feature` return `warnings` when a
  stored pick had to be followed by position because its roles no longer
  named a face. Bodies of more than 2500 faces (imports) carry no
  provenance. A role nothing can resolve fails as `NO_PROVENANCE`.
  Provenance costs about 12 % on a cold rebuild; set the environment variable `DATUM_NO_PROVENANCE=1` to switch it off (refs then use definitions and fingerprints), or `DATUM_PROVENANCE_FACES=N` to change the 2500-face limit.
- **Assemblies hold files.** `place_component` places a part *as last
  saved*: save it first (an unsaved part is refused) and save it again
  after changing it; `assembly_check` rebuilds from the files. A face of a
  placed part is named `<occurrence>/<part reference>`:
  `Plate:1/Hole1.wall[0]`, `Axle:1/Extrude.end`, `Plate:1/origin.XY`
  (the part's own origin planes and axes), `#7/...` by occurrence id.
  The part reference resolves in the component's part (roles first), then
  is taken on the placed body, and the constraint keeps the face's roles
  as a constraint picked by hand does. Sketch-entity names such as
  `side(r.left)` and `@F` handles are known while the part is open in the
  same host; after a reopen use ids (`side(#e3)`), `Extrude.end` and the
  like. A change is atomic and one undo step. There are no joints: an
  `insert` or `mate` of two axes is the revolute/cylindrical freedom, and
  a part's faces inside a *sub-assembly* cannot be named yet.
- **Requirements** are part of the file and are checked whenever the part
  rebuilds, by the agent or in the app. A build's summary ends with
  `reqs 5/6 ✓` or with what fails, such as `reqs 5/6, light 1.32 kg > 1.2`.
- **Scripts and code:** `run_script` is for one-off generation (a hole
  table). It runs in its own process on a copy, with a timeout, and is
  **not a sandbox**: it has your privileges. `safe_mode` adds an AST
  allowlist. A `code` op is a feature that reruns on every rebuild, for
  structure that follows a parameter. The agent's own code is trusted for
  its session by the hash of its source. Code that came in a file, and the
  agent's code once the file is saved and reopened, waits until you allow
  it in the app's icLogic panel (`waiting_for_trust`).
- **Readable models:** every op takes a `name` and field `comments`, and a
  number that keeps coming back is flagged ("12.5 mm used 4 times; make it
  a parameter?").
- **Inch parts** store only unambiguous values: plain numbers are mm, as
  the core reads them, and a bare length inside an expression is written
  with its unit (`"w/2 - 5 mm"`).
- Saving over a different existing file, or exporting over one, needs
  `overwrite: true`, and an export (which keeps no old version) also your
  yes: see [Safety model](#safety-model). The agent is told to pass
  `overwrite` only when asked.

## Tests

```bash
.venv\Scripts\python.exe tests\test_mcp_bridge.py    # the ops, in process
.venv\Scripts\python.exe tests\test_mcp_server.py    # real client, server and host; safety; HTTP; selftest
.venv\Scripts\python.exe tests\test_mcp_gui_host.py  # the app's bridge, in a real window
.venv\Scripts\python.exe tests\test_mcp_gui_proxy.py # the server reaching that window
.venv\Scripts\python.exe tests\test_provenance.py    # geometry references through edits
.venv\Scripts\python.exe tests\test_mcp_guides.py    # guides, prompts, skill
.venv\Scripts\python.exe tests\test_mcp_safety.py    # the policy and the dashboard, in process
.venv\Scripts\python.exe tests\run.py --fast         # everything without a window
```

Run them one at a time. Do not set `QT_QPA_PLATFORM=offscreen` for the GUI
suites. `test_mcp_server.py` replays on a server with every tool group on
(`--tools all`), so the drawing replay and the weld cart replay
(`weld_cart_from_skeleton.json`: a skeleton with master parameters, a
16-member mitred frame, a sheet metal tray with its flat pattern and DXF, a
shelf and four caster plates derived from the skeleton, constrained to it,
checked, listed, then `Skeleton_L` and `Skeleton_TOP` changed and the
assembly checked again) run there too. Its `safety` section drives a real
client through roots, `--allow-dir`, `..` escapes, overwrite, elicitation
(yes and no), paging and image caps, starts the streamable HTTP server and
runs `--selftest`.

The lightest bracket (`lightest_bracket.json`): an L bracket with a bolt
hole and five requirements (the bolt's clearance to the edge and to the
flange, a minimum section as the clearance between two faces of one wall,
an envelope), a sweep with `evaluate`, `optimise` for minimum mass over four
parameters, applied on a branch, diffed and merged.

`test_mcp_server.py` also replays every session in `tests/mcp_replays/`.
To add a regression scenario, add a JSON file there (`{EXAMPLES}` is the
examples folder, `{TMP}` a fresh temporary folder, for files a replay
saves and places; the test allows `{TMP}` as a folder the server may use).
`test_mcp_guides.py` checks that every guide and prompt renders and names
only real tools, that the JSON examples in the guides build, that every
error kind is documented, and that the shipped skill is current (after
changing a guide run `python -m datum.mcp write-skill`).

## Benchmarking agents (Tier 2)

`tests/tier2/` gives a real agent natural-language scenarios and judges
the file it saved, without asking the agent how it went. It is on demand
and **costs money** (except the free routes below); it is never part of
`tests\run.py`. There are eleven scenarios: the first five make one part
each (a bracket, a DIN 934 nut, a plate with a hole pattern, a sheet-metal
tray, a part family); the others cover the later groups: an assembly of a
pin in a block, a drawing with a PDF, a sheet-metal flat with a DXF, a welded
frame with a cut list, the lightest bracket with `optimise`, and a STEP bracket
turned back into an editable part. A scenario can name the server's tool
groups (`tools`), the kind of file to judge (`save_as`), files the agent
starts from (`fixtures`, built by the harness) and files it must write.

```powershell
.venv\Scripts\python.exe tests\tier2\run_tier2.py --list
.venv\Scripts\python.exe tests\tier2\run_tier2.py --check-references   # free: each reference passes its verdict
.venv\Scripts\python.exe tests\tier2\dashboard.py                      # free: runs\dashboard.html
```

Three ways to run the agents:

1. **Claude Code sessions** (no CLI login needed). Make a folder ready:
   `run_tier2.py --prepare tests\tier2\runs\sessions` (free: a folder and
   fixtures per scenario, and the full prompt of each in `prompts\`). Give
   each prompt to a fresh session started in `C:\InventCraft`, with only the
   inventcraft tools allowed and a cheap model. A scenario that lists
   `--tools` needs the server started so: use `--tools all` in `.mcp.json`
   for those. Then judge what they saved, free:
   `run_tier2.py --judge-dir tests\tier2\runs\sessions --record`.
2. **`claude -p`**, driven by the harness (`claude` on PATH and logged in,
   or `ANTHROPIC_API_KEY`): `run_tier2.py bracket optimise_lightest
   --model haiku --budget 1`. It writes the server's tool groups into the
   agent's MCP config and the agent's folder into `INVENTCRAFT_ALLOW_DIRS`.
3. **OpenCode**, with the free `bench` agent in `opencode.json`: run
   `opencode run --agent bench "<contents of prompts\<scenario>.txt>"` once
   per scenario (for the scenarios that need groups, add them to the
   `inventcraft` server's command in `opencode.json`), then judge with
   `--judge-dir`. The harness judges the saved files; it scores transcripts
   in Claude Code's format only, so calls, tokens and cost are blank for
   OpenCode runs.

`--record` turns a passing run into a Tier 1 replay
(`tests/mcp_replays/tier2_<scenario>.json`). `dashboard.py` reads every
`runs\*\report.json` and writes one static page (no scripts): pass rate per
scenario over time, tool calls and failed calls per report, and a table of
every run with tokens and cost where known. See
[tests/tier2/README.md](../tests/tier2/README.md).

## HTTP transport

stdio is the transport for local clients. For a client that can only speak
HTTP:

```bash
python -m datum.mcp --transport streamable-http --port 8000
```

serves `http://127.0.0.1:8000/mcp`, on this machine only (`--bind` changes
the address; do not, unless you have put authentication in front: there is
none, and the server has your files). It is one user's tool: there are no
per-client sessions or accounts, and every connection shares the same
documents. A smoke test starts it, lists the tools, and checks that the
machine's network address is not reachable.
