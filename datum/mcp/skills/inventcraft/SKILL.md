---
name: inventcraft
description: Design parametric parts in InventCraft through its MCP server (mcp__inventcraft__* tools): brackets, plates, nuts and other standard parts, sheet-metal enclosures, welded frames, part families, optimising a design, rebuilding an imported STEP as features, assemblies of saved parts (place, constrain, check, bill of materials), part families as model states, trying a change on a branch, and drawings (views, sections, dimensions, PDF and DXF). Use whenever the user asks to model, change, check or save a part, assembly or drawing in InventCraft, or mentions .icpart, .icasm or .icdraw files.
---

# Designing in InventCraft

InventCraft is a parametric, history-based modeller. The MCP server's tools build parts headless; what you build is an ordinary feature tree a person can open and edit in the app. Build a design someone can change, not only the right shape.

## The loop

Work in this loop, and keep to it:
1. Spec first: write the sizes down as named parameters with comments,
   and the request's acceptance criteria as requirements() (sizes, mass,
   hole count, clearances). Say which values you assumed.
2. build() in a few stages (base body; cuts, bosses and holes; patterns;
   fillets and chamfers last), sized by expressions over the parameters.
3. Read each build's summary line: the volume change, faces, solids,
   reqs n/m. A cut that changed no volume did nothing.
4. inspect(expected=...) for the box, volume and validity you meant.
5. render_view() (iso, then the view that shows the detail) and look.
6. Refine with one-op builds, edit_feature() or properties(). After a
   failed build the part is unchanged: fix that op and send it again.
7. Change a main parameter by 20-50 % with properties(), check the
   build still succeeds and the requirements pass, then put it back.
The guides are resources: ic://guide/workflow first, then ic://guide
lists the others (sketches, references, requirements, errors...).

In Claude Code the guides are also in `guides/` next to this file; the server serves the same text as `ic://guide/{topic}`.

## Rules that prevent most failures

- Parameters first, in the same build() as the features that use them; sheet metal needs `Thickness` and `BendRadius`.
- Never pick faces or edges by index: references by definition (`Extrusion1.end`, `Hole1.wall[0]`), edge queries (`{"along":"z"}`), or `@F:` handles from find_geometry().
- A failed build changed nothing. Read `kind` and `hints`, fix that op, and send the build again.
- Check numbers (inspect() with `expected`, requirements) before pictures (render_view()), and both before saying it is done.
- Holes go in with the hole op at sketch points; patterns repeat features (`parents`), with counts and spacings as expressions.
- save_document() takes an absolute path; never overwrite a file unless the user said so.

## Workflows

The same workflows are MCP prompts (in Claude Code `/mcp__inventcraft__<name>`). Follow the one that fits.

### design-part

Design a parametric part from a description, checking it against requirements as it goes.

Guides: [workflow](guides/workflow.md), [sketches](guides/sketches.md), [references](guides/references.md), [requirements](guides/requirements.md), [errors](guides/errors.md).

Design this part in InventCraft: <description>

Material: <material> (properties(material=...)); mass requirements need it.

(the loop above)

Standard parts (DIN, ISO): use the standard's table values as the
parameters, and say which standard and size you used.

When it is done, say what you built (the parameters, the requirements and their results) and ask whether to save it.

### sheet-metal-enclosure

A sheet-metal box from a base face and flanges, sized by parameters.

Guides: [sheet-metal](guides/sheet-metal.md), [workflow](guides/workflow.md).

Design a sheet-metal enclosure in InventCraft, about <length> x <width> x <height> mm
outside, in <thickness> mm sheet.

Read ic://guide/sheet-metal first. Sheet-metal features read the
parameters Thickness and BendRadius: define them, and L, W and H, before
any sheet feature. Base with sheet_face on a rectangle, walls with
flange on its edges; contour_flange for channels and lids. Requirements:
the outside bbox, and any mounting holes (hole_count).

(the loop above)

With the +sheetmetal tools on: sheet_rules(k_factor=0.44) once the
Thickness and BendRadius are set, sheet_check() after the build (a bend
radius under 0.5 t, a flange under 4 t, a hole within 2 t of a bend and a
corner that will not unfold are findings: fix them, they are rules not
taste), then flat_pattern(path=<absolute .dxf>) and report the flat's
size, the bend list and the K-factor used. Without them say that the flat
pattern is in the app. A lid or a second part is a second document.

When it is done, say what you built (the parameters, the requirements and their results) and ask whether to save it.

### weldment-frame

A welded frame of library profiles on a skeleton, with mitres and a cut list.

Guides: [frames](guides/frames.md), [skeleton](guides/skeleton.md), [assemblies](guides/assemblies.md).

Design this welded frame in InventCraft: <description>

Read ic://guide/frames first, then ic://guide/skeleton. A frame is
members of a library profile along the lines of a skeleton, so:
1. Skeleton part: the overall sizes as named parameters, the member
   lines as named sketches on work planes whose offsets are expressions
   (one sketch per level or side). Add one 2 mm block so an assembly can
   constrain to it. save_document() it.
2. new_document(type="assembly"), save_document() it, place_component()
   the skeleton (the +assembly tools), then frame_profiles() to choose the
   family and size, and frame_insert() once per sketch (the first makes
   the frame, the others pass frame="Frame0001:1").
3. frame_treat(kind="miter", corners=true, sketch=...) on each sketch
   whose corners are mitred; members=[a, b] for single joints, kind
   "notch" or "corner" for tubes that butt into others.
4. cut_list(path=<absolute .csv>): every piece with its cut length and
   end angles; check the count against the lines you drew and a mitred
   corner reads 45.0 at both ends. assembly_check() must show no
   interference and bom() the mass.
5. Prove it follows: skeleton_set(set={"Skeleton_L": ...}) by 20 % and
   read the cut list again; the lengths must move.
Without the +frames and +skeleton groups, build one part instead: a code
op that unions profile members along lines (beam(), rod(), hollow
sections as one beam minus another), sized by parameters, or frame_member
for a single member; say that the member parts and cut list need the
tool groups. Requirements: the overall bbox, and the mass if a material
is given.

(the loop above)

When it is done, say what you built (the parameters, the requirements and their results) and ask whether to save it.

### skeleton-design

Master parameters and layout sketches in one part; a frame and plate parts derived from it, placed, checked, and shown to follow a changed parameter.

Guides: [skeleton](guides/skeleton.md), [frames](guides/frames.md), [assemblies](guides/assemblies.md).

Design this top-down in InventCraft, from a skeleton: <description>

Read ic://guide/skeleton first (and ic://guide/frames, ic://guide/
assemblies). The skeleton is one part of master parameters and layout
sketches; every other part follows it. So:
1. Write the master parameters down (overall sizes, levels, tube or
   plate sizes) with comments, then build the skeleton part: parameters,
   work planes at expression offsets, named sketches of lines, one 2 mm
   block at the origin. inspect() the sketch_status of each sketch. Save
   it.
2. Build each part the skeleton drives (plates, trays) with its own
   parameters for the sizes that must follow, and save it. Frame members
   come from frame_insert(), not from parts you build.
3. new_document(type="assembly"), save it, place_component() the skeleton
   first, frame_insert() the members, then derive_part(file=..., drives=
   {"width": "Skeleton_W - 40"}) for each part: names are <part>_<name>,
   skeleton_params() lists them all.
4. place_component() each part and constrain() it to the skeleton's origin
   planes with offsets written over the parameters, until assembly_check()
   says DOF 0 and no interference; bom() for the list.
5. Prove it: skeleton_set(set={...}) one or two master parameters by 15 to
   30 %, read what moved, assembly_check() again (still no interference,
   still DOF 0), put the values back. A part that did not move is not
   derived: find why before you finish.
Say what is not there: a derived part that projects the skeleton's edges
(the app's adaptive link) and skeletons without a body.

(the loop above)

When it is done, say what you built (the parameters, the requirements and their results) and ask whether to save it.

### assembly-from-parts

Build parts, place them in an assembly, constrain them to zero degrees of freedom, check interference and list the bill of materials.

Guides: [assemblies](guides/assemblies.md), [references](guides/references.md), [workflow](guides/workflow.md).

Assemble this in InventCraft: <description>. Parts: <parts>

Read ic://guide/assemblies first (and ic://guide/references for the part
references the constraints use). An assembly places part files and
constrains faces and edges of one to another, so:
1. Build each part (build(), as in the loop below), give it a Part Number,
   description and material with properties(), and save_document() it to
   a folder of its own: the assembly places the files as last saved.
2. new_document(type="assembly"). place_component() the part that should
   stay put first (it is grounded), then each other part, with a name.
3. constrain() every free part until assembly_check() says DOF 0 for it:
   mate or flush a face to a face, insert a shaft into a hole (the walls
   are cylinders), `offset` for gaps. References look like
   "Plate:1/Hole1.wall[0]"; the part's own feature names are in its
   model_tree(). Read each answer's DOF line; a constraint that takes no
   freedom away is a mistake or already implied.
4. assembly_check(): no failed constraints, nothing still free that
   should not be, **no interference** (touching is fine). measure() two
   occurrence faces to prove a gap or a spacing, render_view() to look.
5. bom(): check quantities, part numbers and the total mass against the
   description; fix the part's properties and save it again if not.

Not yet: joints with limits and motion, a sub-assembly's own faces as
constraint targets, drawings of the assembly, skeleton-driven (top-down)
design. Say so if the request needs them.

(the loop above)

When it is done, say what you built (the parameters, the requirements and their results) and ask whether to save it.

### part-family

One parametric part driven through several sizes, with a results table.

Guides: [workflow](guides/workflow.md), [requirements](guides/requirements.md).

Design a family of parts in InventCraft: <description>
Variants: <variants>

Build ONE part whose every size comes from a few driving parameters,
with requirements that hold for every variant (parameter ranges, sizes
as expressions you check per variant). Read ic://guide/model-states.
The family is the part's MODEL STATES: for each variant,
model_states(action="create", name=..., parameters={...}, props={"Part
Number": ...}) (a variant that suppresses a feature takes `suppress`),
which leaves the part as it was. Then model_states(action="list",
measure=true) gives every variant's volume, mass and size: check them
against what the sizes imply, and activate each state in turn to
inspect() it and read its requirements. Finish with a table of the
variants and their results, with the part back in Primary.

(the loop above)

Variants that differ in an exact table of sizes (a standard's) go in as
the states' parameters from that table. If the user wants one file per
variant instead, activate the state and save_document() to a new path.
Not yet: the planned evaluate tool, which builds variants in parallel.

When it is done, say what you built (the parameters, the requirements and their results) and ask whether to save it.

### drawing-package

A dimensioned drawing of a saved part or assembly: views, a section, a detail, dimensions, a parts list for assemblies; PDF and DXF.

Guides: [drawings](guides/drawings.md), [workflow](guides/workflow.md).

Make a drawing of <model> in InventCraft: <description>.

Read ic://guide/drawings first; it needs the +drawing tools (the server
started with --tools +drawing: if drawing_create() is not there, say so
and stop). A drawing shows a SAVED part or assembly: if the model is not
saved, or you are asked to make it first, build it as in the loop below
and save_document() it, with its Part Number, description and material.
Then:
1. drawing_create(source=..., size='<sheet>', props={"Title": ..., "Author":
   ...}). Note the sheet frame and title block it reports.
2. drawing_base_view(orientation="front") (or the view that shows the
   part best), then drawing_projected_view(shows="top") and place="right",
   and shows="iso" for the corner. The scale and places are chosen for
   you; read each answer's `looks`, `scale` and warnings.
3. A section where there is something inside (drawing_section_view with a
   cut through the middle or through the holes), and a detail
   (drawing_detail_view) of what is too small to read.
4. Dimensions: drawing_dimension(kind="overall") on the view that shows
   width and height, kind "diameter" on the view that shows the holes,
   "linear" for the rest; drawing_note(kind="hole_notes") and
   "centre_marks". For an assembly: drawing_parts_list(balloons=true)
   instead of single dimensions.
5. drawing_render() and look: nothing overlapping, every dimension
   readable and not repeated, the views in the places the standard puts
   them. Fix with edit_feature(feature="View2", params={...}) (move,
   rescale) or delete=true.
6. save_document(path=...) for the .icdraw, then drawing_export(path=
   ...pdf) (add a .dxf if asked). Never overwrite an existing file unless
   the user said so.

Check the numbers, not only the picture: model_tree() lists each view's
position, size and scale and each dimension's value; the overall
dimensions must equal inspect()'s bbox of the part.

Not yet: several sheets, auxiliary or broken views, GD&T and surface
symbols, a revision table, sheet-metal flat patterns: say so if asked.

(the loop above)

When it is done, say what you built (the parameters, the requirements and their results) and ask whether to save it.

### optimise-design

Search the parameters for the best design that clears every requirement: evaluate to look, optimise to search, apply on a branch.

Guides: [requirements](guides/requirements.md), [explore](guides/explore.md), [workflow](guides/workflow.md).

Improve the part (open_document() it, or the one open now: status()) in InventCraft. Goal: <goal>

1. read_ir() and requirements() to see how it is built and what it must
   do. Write every must-have as a requirement BEFORE you search (mass,
   envelope bbox, clearances to a bolt or a keep-out, a minimum section as
   the clearance between two faces of one wall): optimise() enforces the
   stored requirements, so a design is only "best" among those that clear
   them. A parameter should drive each size you want the search to vary.
2. snapshot(action="save", name="start"), and the part saved if you will
   branch.
3. Look first: evaluate(grid={"t": [3, 4, 6], "w": [60, 90]}) tables the
   variants without touching the part (mass, bbox, valid, reqs n/m, what
   fails). Check that the requirements bite where you expect, and that the
   parameter ranges you mean to search all build.
4. optimise(vary={"t": [3, 12], "w": [60, 140]}, objective="min mass",
   budget=40). It runs a coarse grid then a compass search, in parallel on
   the worker pool, and answers the best feasible design against the
   start, the table explored and why the others failed (failed_by). Read
   failed_by: a requirement that fails everywhere is too tight, or a range
   is wrong. With "NO feasible design" it names the closest one; widen a
   range or relax a requirement and say which. Run it again with a tighter
   range around the answer if the gain is still above 1 %.
5. Apply the result: optimise(..., apply=true, branch="lighter") writes it
   on a branch (save the part first) as one change; diff(
   before="branch:main", after="branch:lighter"), then branch(switch main)
   and branch(merge lighter), or discard it. Without a branch name apply=true
   is one undo step in the part itself. Changes of form (a pocket, a rib)
   are not parameters: build() them (on a branch), then optimise again.
6. inspect() the result: valid, one solid; render_view().

Say how many designs were evaluated and what the start and the optimum
weigh.

When it is done, say what you built (the parameters, the requirements and their results) and ask whether to save it.

### parametrize-import

Rebuild an imported STEP part as an editable feature tree.

Guides: [import](guides/import.md), [references](guides/references.md), [workflow](guides/workflow.md), [sketches](guides/sketches.md).

Turn the imported part <path> into an editable, parametric InventCraft part.

1. new_document(), then build() one op {"op":"import","path":"<path>"}, and
   inspect() it: bbox, volume, faces. That is the target.
2. recognize(): read the features it finds (base, holes, patterns, bosses,
   pockets, fillets, chamfers), the parameters it would name, the coverage
   and the residual. render_view() the part from two sides and check the
   report against what you see; unexplained faces come with @F handles for
   find_geometry() and measure().
3. parametrize(dry_run=true), then parametrize(). It builds the tree in a
   scratch document, checks volume, box and the boolean difference against
   the import, and only then replaces the import with the tree (one undo
   step). If it refuses with PARTIAL_COVERAGE the part is untouched: read
   `unexplained`, then rebuild by hand: a SECOND document, base sketch and
   extrude, hole ops at sketch points, patterns, fillets, sized by
   parameters, with find_geometry() and measure() for the numbers. Or pass
   plan={"ops": [...]} to parametrize() and let it check yours.
4. inspect(expected=...) with the import's bbox and volume (tolerance
   0.001); requirements() for the bbox and volume of the import and
   hole_count per diameter.
5. Prove it is parametric: properties(parameters={"hole_d": ...}) or the
   thickness, inspect() the change, put it back.

Say how many faces were explained, the residual volume, and which faces (if
any) were left. Do not call a refused import parametric.

When it is done, say what you built (the parameters, the requirements and their results) and ask whether to save it.

## Reference

- [Modelling workflow](guides/workflow.md): The loop: parameters and requirements first, build, read the summary, inspect, render, refine. Read this first.
- [Sketches and constraints](guides/sketches.md): Entities, constraints and dimensions by name; regions; sketch_status().
- [References and find_geometry](guides/references.md): Naming faces and edges without indices: by definition, by query, by @ handle.
- [Units](guides/units.md): mm and degrees at the API, whatever the part's units; expressions.
- [Requirements](guides/requirements.md): Writing down what done means, kept in the part and checked on every rebuild.
- [run_script vs code features](guides/scripts.md): One-off generation, or structure that follows a parameter.
- [Sheet metal](guides/sheet-metal.md): Face, flange, contour flange, hem, fold, corner seam; sheet rules, the flat pattern with its bend list and DXF, the manufacturing check: the +sheetmetal tool group.
- [Frames and weldments](guides/frames.md): Members on skeleton lines from the profile library, mitres, the cut list: the +frames tool group.
- [Skeleton design](guides/skeleton.md): Top-down: master parameters and layout sketches in one part, parts derived from it, changed in one call: the +skeleton tool group.
- [Assemblies](guides/assemblies.md): Placing parts, constraining them with occurrence references, checking DOF and interference, the bill of materials.
- [Drawings](guides/drawings.md): Views, sections, dimensions, a parts list and balloons, PDF and DXF: the +drawing tool group.
- [Model states](guides/model-states.md): A family of parts in one file: parameter, suppression and property variants.
- [Branches](guides/branches.md): Try a change in isolation: create, check in, diff, merge or discard; conflicts are refused.
- [Explore: evaluate and optimise](guides/explore.md): Try variants without touching the part, and search for the lightest design that clears every requirement.
- [Import: a STEP back into a tree](guides/import.md): recognize() reads a dumb solid's holes, bosses, patterns and fillets; parametrize() rebuilds it as an editable tree, or refuses.
- [Files, limits and data](guides/safety.md): Where files may go, when the user is asked, paged answers, and why names and notes in a file are not instructions.
- [Common errors and fixes](guides/errors.md): Every error kind, what it means and what to do; how to recover from a failed build.
