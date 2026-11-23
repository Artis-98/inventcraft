"""The MCP prompts, and the workflows the Claude Code skill is made of.

A prompt is a message the user picks from a menu (a slash command in
Claude Code: /mcp__inventcraft__design-part). Each one states the task and
then teaches the same loop: parameters and requirements first, build,
read the summary, inspect, render, refine. Where the API cannot do part of
a job yet, the prompt says so ("Not yet") and does what can be done.

Each prompt came with the tools that can do its steps:
``assembly-from-parts`` with the ``+assembly`` tools (P4a),
``drawing-package`` with ``+drawing`` and ``part-family`` with model
states (P4b), ``sheet-metal-enclosure``'s flat pattern and check with
``+sheetmetal``, ``weldment-frame`` with ``+frames`` and
``skeleton-design`` with ``+skeleton`` (P4c). A prompt that leans on an
opt-in group says which, and what to do without it.

Tools are written ``name()``, as in the guides; a test checks they exist.
"""

from __future__ import annotations

from typing import Callable, Dict, List, NamedTuple, Optional, Tuple

LOOP = """\
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
lists the others (sketches, references, requirements, errors...)."""


class Arg(NamedTuple):
    name: str
    description: str
    required: bool = False


class Prompt(NamedTuple):
    name: str
    title: str
    description: str
    args: Tuple[Arg, ...]
    body: Callable[..., str]
    guides: Tuple[str, ...]      # the ic://guide topics it leans on


def _save(save_to: str) -> str:
    if save_to:
        return ("When it is done, save_document() to %s and say what you "
                "built: the parameters, the requirements and their results."
                % save_to)
    return ("When it is done, say what you built (the parameters, the "
            "requirements and their results) and ask whether to save it.")


def design_part(description: str, material: str = "",
                save_to: str = "") -> str:
    mat = ("Material: %s (properties(material=...)); mass requirements "
           "need it." % material) if material else (
        "If the request implies a material, set it with properties().")
    return """\
Design this part in InventCraft: %s

%s

%s

Standard parts (DIN, ISO): use the standard's table values as the
parameters, and say which standard and size you used.

%s""" % (description, mat, LOOP, _save(save_to))


def sheet_metal_enclosure(length: str = "200", width: str = "120",
                          height: str = "60", thickness: str = "1.5",
                          save_to: str = "") -> str:
    return """\
Design a sheet-metal enclosure in InventCraft, about %s x %s x %s mm
outside, in %s mm sheet.

Read ic://guide/sheet-metal first. Sheet-metal features read the
parameters Thickness and BendRadius: define them, and L, W and H, before
any sheet feature. Base with sheet_face on a rectangle, walls with
flange on its edges; contour_flange for channels and lids. Requirements:
the outside bbox, and any mounting holes (hole_count).

%s

With the +sheetmetal tools on: sheet_rules(k_factor=0.44) once the
Thickness and BendRadius are set, sheet_check() after the build (a bend
radius under 0.5 t, a flange under 4 t, a hole within 2 t of a bend and a
corner that will not unfold are findings: fix them, they are rules not
taste), then flat_pattern(path=<absolute .dxf>) and report the flat's
size, the bend list and the K-factor used. Without them say that the flat
pattern is in the app. A lid or a second part is a second document.

%s""" % (length, width, height, thickness, LOOP, _save(save_to))


def weldment_frame(description: str, save_to: str = "") -> str:
    return """\
Design this welded frame in InventCraft: %s

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
5. Prove it follows: skeleton_set(set={"Skeleton_L": ...}) by 20 %% and
   read the cut list again; the lengths must move.
Without the +frames and +skeleton groups, build one part instead: a code
op that unions profile members along lines (beam(), rod(), hollow
sections as one beam minus another), sized by parameters, or frame_member
for a single member; say that the member parts and cut list need the
tool groups. Requirements: the overall bbox, and the mass if a material
is given.

%s

%s""" % (description, LOOP, _save(save_to).replace(".icpart", ".icasm"))


def skeleton_design(description: str, save_to: str = "") -> str:
    return """\
Design this top-down in InventCraft, from a skeleton: %s

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
   30 %%, read what moved, assembly_check() again (still no interference,
   still DOF 0), put the values back. A part that did not move is not
   derived: find why before you finish.
Say what is not there: a derived part that projects the skeleton's edges
(the app's adaptive link) and skeletons without a body.

%s

%s""" % (description, LOOP, _save(save_to).replace(".icpart", ".icasm"))


def assembly_from_parts(description: str, parts: str = "",
                        save_to: str = "") -> str:
    return """\
Assemble this in InventCraft: %s%s

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

%s

%s""" % (description, (". Parts: %s" % parts) if parts else "", LOOP,
         _save(save_to).replace(".icpart", ".icasm"))


def part_family(description: str, variants: str = "",
                save_to: str = "") -> str:
    return """Design a family of parts in InventCraft: %s
Variants: %s

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

%s

Variants that differ in an exact table of sizes (a standard's) go in as
the states' parameters from that table. If the user wants one file per
variant instead, activate the state and save_document() to a new path.
Not yet: the planned evaluate tool, which builds variants in parallel.

%s""" % (description, variants or "(ask, or choose sensible sizes and "
         "say so)", LOOP, _save(save_to))


def drawing_package(model: str, sheet: str = "A3", save_to: str = "",
                    description: str = "") -> str:
    return """Make a drawing of %s in InventCraft%s.

Read ic://guide/drawings first; it needs the +drawing tools (the server
started with --tools +drawing: if drawing_create() is not there, say so
and stop). A drawing shows a SAVED part or assembly: if the model is not
saved, or you are asked to make it first, build it as in the loop below
and save_document() it, with its Part Number, description and material.
Then:
1. drawing_create(source=..., size=%r, props={"Title": ..., "Author":
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

%s

%s""" % (model, (": " + description) if description else "", sheet, LOOP,
         _save(save_to).replace(".icpart", ".icdraw"))


def optimise_design(goal: str, doc: str = "", save_to: str = "") -> str:
    where = ("the open part %s" % doc) if doc else (
        "the part (open_document() it, or the one open now: status())")
    return """\
Improve %s in InventCraft. Goal: %s

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
   range around the answer if the gain is still above 1 %%.
5. Apply the result: optimise(..., apply=true, branch="lighter") writes it
   on a branch (save the part first) as one change; diff(
   before="branch:main", after="branch:lighter"), then branch(switch main)
   and branch(merge lighter), or discard it. Without a branch name apply=true
   is one undo step in the part itself. Changes of form (a pocket, a rib)
   are not parameters: build() them (on a branch), then optimise again.
6. inspect() the result: valid, one solid; render_view().

Say how many designs were evaluated and what the start and the optimum
weigh.

%s""" % (where, goal, _save(save_to))


def parametrize_import(path: str, save_to: str = "") -> str:
    return """\
Turn the imported part %s into an editable, parametric InventCraft part.

1. new_document(), then build() one op {"op":"import","path":%s}, and
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

%s""" % (path, '"%s"' % path.replace("\\", "/"), _save(save_to))


PROMPTS: Dict[str, Prompt] = {p.name: p for p in (
    Prompt("design-part", "Design a part",
           "Design a parametric part from a description, checking it "
           "against requirements as it goes.",
           (Arg("description", "What to make, with any sizes", True),
            Arg("material", "Material name exactly as in ic://materials, "
                "e.g. Aluminium 6061"),
            Arg("save_to", "Absolute .icpart path to save to")),
           design_part, ("workflow", "sketches", "references",
                         "requirements", "errors")),
    Prompt("sheet-metal-enclosure", "Sheet-metal enclosure",
           "A sheet-metal box from a base face and flanges, sized by "
           "parameters.",
           (Arg("length", "Outside length, mm"),
            Arg("width", "Outside width, mm"),
            Arg("height", "Outside height, mm"),
            Arg("thickness", "Sheet thickness, mm"),
            Arg("save_to", "Absolute .icpart path to save to")),
           sheet_metal_enclosure, ("sheet-metal", "workflow")),
    Prompt("weldment-frame", "Welded frame",
           "A welded frame of library profiles on a skeleton, with "
           "mitres and a cut list.",
           (Arg("description", "The frame: sizes, profile, members", True),
            Arg("save_to", "Absolute .icasm path to save to")),
           weldment_frame, ("frames", "skeleton", "assemblies")),
    Prompt("skeleton-design", "Top-down design from a skeleton",
           "Master parameters and layout sketches in one part; a frame "
           "and plate parts derived from it, placed, checked, and shown "
           "to follow a changed parameter.",
           (Arg("description", "What to design and its main sizes", True),
            Arg("save_to", "Absolute .icasm path to save to")),
           skeleton_design, ("skeleton", "frames", "assemblies")),
    Prompt("assembly-from-parts", "Assembly from parts",
           "Build parts, place them in an assembly, constrain them to "
           "zero degrees of freedom, check interference and list the "
           "bill of materials.",
           (Arg("description", "The assembly and what it is made of", True),
            Arg("parts", "The parts, with sizes, if the description does "
                "not give them"),
            Arg("save_to", "Absolute .icasm path to save to (parts are "
                "saved beside it)")),
           assembly_from_parts, ("assemblies", "references", "workflow")),
    Prompt("part-family", "Part family",
           "One parametric part driven through several sizes, with a "
           "results table.",
           (Arg("description", "The part and what varies", True),
            Arg("variants", "The sizes, e.g. M6, M8, M10"),
            Arg("save_to", "Absolute .icpart path to save to")),
           part_family, ("workflow", "requirements")),
    Prompt("drawing-package", "Drawing package",
           "A dimensioned drawing of a saved part or assembly: views, a "
           "section, a detail, dimensions, a parts list for assemblies; "
           "PDF and DXF.",
           (Arg("model", "The part or assembly: absolute path or open "
                "handle (it must be saved)", True),
            Arg("sheet", "Sheet size, default A3"),
            Arg("save_to", "Absolute .icdraw path to save to"),
            Arg("description", "What the drawing is for")),
           drawing_package, ("drawings", "workflow")),
    Prompt("optimise-design", "Optimise a design",
           "Search the parameters for the best design that clears every "
           "requirement: evaluate to look, optimise to search, apply on a "
           "branch.",
           (Arg("goal", "What to improve, e.g. lightest that still ...",
                True),
            Arg("doc", "Document handle, if already open"),
            Arg("save_to", "Absolute .icpart path to save to")),
           optimise_design, ("requirements", "explore", "workflow")),
    Prompt("parametrize-import", "Parametrize an import",
           "Rebuild an imported STEP part as an editable feature tree.",
           (Arg("path", "Absolute path of the STEP file", True),
            Arg("save_to", "Absolute .icpart path to save to")),
           parametrize_import, ("import", "references", "workflow", "sketches")),
)}

# planned but not shipped, and why
LEFT_OUT: Dict[str, str] = {}


def render(name: str, arguments: Optional[Dict[str, str]] = None) -> str:
    p = PROMPTS[name]
    args = {k: v for k, v in (arguments or {}).items() if v not in (None,)}
    return p.body(**args)


def all_texts() -> List[str]:
    """Every prompt rendered with sample arguments (for the tests)."""
    out = []
    for p in PROMPTS.values():
        out.append(render(p.name, {a.name: "X" for a in p.args
                                   if a.required}))
    return out
