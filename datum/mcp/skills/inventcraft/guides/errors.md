# Common errors and fixes

A failed call comes back as an error result with a `kind` (stable, to
branch on), a `message` and `hints`. A failed build also says where
(`at`: the op's index, type and id) and is rolled back, unless you
passed `keep_partial`.

## Recovering

1. Read `kind` and `hints` first; they usually say the fix.
2. The part is as it was before the call. Fix the failing op and send
   the whole build again; do not send only the rest.
3. A big build that fails late: send it in two or three builds (base
   body, then features, then finishing), so each failure is small.
4. Unsure a pick or size works? `dry_run` builds it, reports and puts
   the model back. snapshot(action="save") before an experiment,
   snapshot(action="restore") to come back.
5. Geometry that builds but looks wrong: render_view() with
   `highlight`, measure(), and sketch_status() for the sketch behind it.
6. The same error twice: change the approach (another face, a work
   plane, a smaller size) rather than the same op again.

## Kinds

| kind | means | what to do |
|---|---|---|
| `AMBIGUOUS` | The part has several bodies and the tool needs one. | Name it with body=. |
| `AMBIGUOUS_REF` | A reference inside a component names more than one face or edge; a constraint takes exactly one. | Add an index (Hole1.wall[0]) or use a handle. |
| `ASSEMBLY_FAILED` | build_project saved the parts and could not make the assembly of them. | Read the message, then call again or place_component() them. |
| `BAD_CODE` | A code op's source does not compile. | The message gives the line. |
| `BAD_EXPECTATION` | inspect() was given a key it cannot check. | Checkable: bbox, volume, mass_g, solids, faces, valid, tolerance. |
| `BAD_EXPRESSION` | An expression names a parameter that does not exist or does not parse. | Add a parameter op earlier in the same build, or read the parameters with properties(). |
| `BAD_FILE` | The file could not be read. | Is it an InventCraft part or assembly? |
| `BAD_FORMAT` | An export format that is not supported. | Use .step, .stl, .iges or .brep. |
| `BAD_KIND` | An unknown constraint kind. | mate, flush, angle, tangent, insert or parallel; the message says what each does. |
| `BAD_NAME` | A parameter name is not an identifier, or is one the expression language keeps (e, pi, sin, sqrt...). | Choose another name; ic://guide/units lists the reserved ones. |
| `BAD_OP` | An op is malformed: an unknown field, a missing one, or a value of the wrong shape. | The error lists the fields the op takes; the op's schema is ic://schema/op/{type}. |
| `BAD_ORDER` | A move would put a feature before something it uses. | Move it later, or move what it uses first. |
| `BAD_PAIRING` | That constraint kind does not apply to those two kinds of geometry (say, insert on two flat faces). | The message says what a and b are and which kinds take them. |
| `BAD_PATH` | A path is relative or has the wrong extension. | Use an absolute path. |
| `BAD_QUERY` | A face or edge query has an unknown key or value. | The message lists the keys it takes. |
| `BAD_REF` | A reference does not parse or names nothing. | ic://schema/ref has the grammar; find_geometry() hands out @F/@E/@V handles; in one build use "$id" of an op. |
| `BAD_REQUIREMENT` | A requirement is malformed. | See the requirements() tool description, or ic://guide/requirements. |
| `BAD_TRANSFORM` | A placement is malformed. | {"position":[x,y,z], "rotate":{"axis":[0,0,1], "angle":90}} in mm and degrees, or "euler":[rx,ry,rz]. |
| `BAD_VALUE` | A value is out of range: zero, negative, or not one of the choices. | The message names the choices. |
| `BAD_VIEW` | render_view() was given a view it does not know. | iso, front, back, left, right, top, bottom, or [x,y,z]. |
| `BUILD_FAILED` | A part of a build_project failed, so it was not written; the others were. | Fix that part and send only it, with overwrite. |
| `CANCELLED` | The user pressed Stop in the app, so the request was dropped before it ran or rolled back while it ran. | Nothing was kept. Ask the user what they want before trying again. |
| `CONFIRM_REQUIRED` | Writing over an existing file that keeps no old version of itself: the user must agree first. | Ask the user; then repeat the call with overwrite=true and confirm=true. |
| `CONSTRAINT_FAILED` | The change leaves a constraint nothing can satisfy, or a component that will not load; the assembly is unchanged. | The message names the constraint. Check the offset and flip, or remove a conflicting older constraint; assembly_check() lists conflicts. |
| `EDGE_OP_FAILED` | A fillet or chamfer could not be made. | Use a smaller size or fewer edges; check the pick with render_view(highlight_edges=...). |
| `FEATURE_FAILED` | A feature failed when the part rebuilt; the message is the core's. | Read the hints; the build was rolled back, so fix that op and send the build again. |
| `FILE_IN_USE` | A file to be written is open with unsaved changes. | save_document() or close_document() it first. |
| `FILE_OPEN_IN_APP` | A save or export from a headless host would write over a file the app has open. | Edit the app's copy (its g handle) and save from there, or use another path. |
| `FLAT_FAILED` | The sheet cannot be laid flat: a bend that is not round, a corner between bends with no relief, or not one thickness throughout. | sheet_check() says what is wrong; let flanges that meet relieve themselves or add a corner_seam. |
| `GUI_HOST_UNAVAILABLE` | The app's bridge is not reachable: the app is not running, or Preferences > AI > Allow agents is off. | Ask the user to start InventCraft and turn Allow agents on; or work headless (--host headless). |
| `GUI_PAIRING_FAILED` | The app's bridge refused this server's secret. | Turn Allow agents off and on in the app to make a new pairing, then try again. |
| `HAS_DEPENDENTS` | Removing a feature others use. | The error names them; pass delete_dependents, or "dependents":"remove" in a remove op. |
| `HOST_LOST` | The geometry host crashed or was killed. | Open or create the document again; saved files are safe. |
| `INTERNAL` | An unexpected error. | Report it, with the message. |
| `KERNEL_FAILED` | The geometry kernel refused the operation. | Often a tangent or zero-thickness case; nudge a size. |
| `MERGE_CONFLICT` | Both branches changed the same thing in different ways; nothing was merged. | The error lists each conflict. Change one branch so they agree, or merge the other way round. |
| `NEWER_FILE` | The file comes from a newer InventCraft. | Open it in that version. |
| `NOT_ALLOWED` | The operating system refused a file. | Choose another path. |
| `NOT_FLAT` | A sketch was put on a face that is not flat. | Pick a plane face, or a work plane. |
| `NOT_FOUND` | A file, feature or parameter of that name is not there. | Check the name with model_tree(). |
| `NOT_IN_GUI_HOST` | That tool is not run in the app: the user's session never runs an agent's code, and their open documents are theirs to close. | run_script goes to a separate host by itself; for a structure that follows a parameter use a code op in build (the user is asked to allow it). |
| `NOT_MATEABLE` | The face or edge is free-form (a spline), so the solver has no plane, axis or circle to hold. | Pick a flat face, a hole or shaft wall, or a circular edge. |
| `NOT_PARAMETRIC` | recognize() found no base to build on (the body is not a prism along x, y or z). | Rebuild it by hand from find_geometry() and measure(); ic://guide/import. |
| `NOT_SHEET_METAL` | The part has no sheet metal rules and no Thickness parameter, so there is nothing to lay flat or check. | sheet_rules(thickness=..., bend_radius=..., k_factor=...) converts it; build the sheet features first. |
| `NOT_VERIFIED` | parametrize() could not check its tree against the original, so it did not apply it. | recognize(detail=true) shows the ops; use verify=false only to see what it would do. |
| `NOT_YET` | That part of the API is planned, not built. | The message says what to use meanwhile. |
| `NO_BODY` | The feature needs a solid and there is none before it. | Extrude something first, or move the feature later. |
| `NO_BRANCH` | No branch of that name. | branch(action="list"). |
| `NO_COMPONENT` | A placed component's file is missing, did not build, or was never saved. | Save the part first (save_document), then place its file; assembly_check() lists components that failed to load. |
| `NO_DOCUMENT` | No such document handle, or no document open. | status() lists them; new_document() or open_document() makes one. |
| `NO_FRAME` | The assembly has no frame yet. | frame_insert() makes one on a skeleton. |
| `NO_MATCH` | A face or edge query matched nothing. | Loosen it, or look with find_geometry() and render_view(highlight=[...]). |
| `NO_MODEL` | A drawing needs a saved part or assembly to draw. | save_document() the model first, then give its path or handle as source. |
| `NO_OCCURRENCE` | No component of that name is placed in the assembly. | The message lists the occurrences (Wheel:1, ...); place_component() adds one. |
| `NO_PARAMETER` | No part or assembly has a parameter of that name. | skeleton_params() lists every name, parts' as <part>_<name>. |
| `NO_PROFILE` | There is no such profile family or size. | frame_profiles() lists families; frame_profiles(family=...) lists a family's sizes. |
| `NO_PROVENANCE` | The part does not know which feature made that face (a body too big to tag, a feature that changed it without saying how, or a role that feature does not have). | Use find_geometry() with created_by, or a face query; the message says what does work. |
| `NO_SKETCH` | The skeleton has no sketch of that name with lines. | The message lists the sketches; build and save the skeleton part first. |
| `NO_STATE` | No model state of that name. | model_states(action="list") lists them. |
| `NO_VIEW` | A drawing has no view or item of that name. | model_tree() lists the views (name, id) and annotations. |
| `OVER_CONSTRAINED` | Two constraints or dimensions disagree. | The message names them; drop one. |
| `PARTIAL_COVERAGE` | parametrize() found features, but the tree they make is not the body: the share of faces it reproduces is below the whole, or the boolean difference is over the tolerance. Nothing was changed. | The error carries the report: unexplained faces with handles. Rebuild those by hand, or pass plan={"ops": [...]}. |
| `PATH_NOT_ALLOWED` | A file path outside the folders the server may touch: the client's MCP roots when it gives them, else the project folder and the --allow-dir folders. | Use a path inside one of the allowed folders (the error lists them), or ask the user to start the server with --allow-dir <folder>. |
| `PROFILE_NOT_CLOSED` | The sketch has no closed region. | Use rect, circle or polygon entities, or a closed polyline; sketch_status() lists regions. |
| `RENDER_FAILED` | The drawing could not be made. | Is there a solid? inspect() says. |
| `REPLACE_TREE_REQUIRED` | parametrize() on a part that already has a feature tree of its own, which it would delete. Nothing was changed. | Pass replace_tree=true only if the user wants that tree replaced. |
| `SAFE_MODE` | safe_mode refused an import, a file access or a dunder. | Do without it, or run without safe_mode. |
| `SAME_OCCURRENCE` | Both sides of a constraint are on one component. | Constrain to a different component, or to its origin planes. |
| `SCRIPT_CRASHED` | The script's process died. | Nothing was applied; simplify the script. |
| `SCRIPT_FAILED` | run_script()'s code raised; nothing was applied. | The traceback and printed output come back. |
| `SCRIPT_UNSUPPORTED` | The script changed something that cannot be applied as ops. | The message says what. |
| `SELF_INTERSECTION` | The result would cross itself. | Reduce the size or split the step. |
| `SHEET_METAL_PARAMETERS` | A sheet-metal feature has no Thickness or BendRadius parameter to read. | Add both as parameter ops first. |
| `STALE_COMPONENT` | The body the assembly placed is no longer the part as the reference found it (the file changed or the part has unsaved edits). | save_document the part, then assembly_check() rebuilds the assembly from the files. |
| `STALE_REF` | An @ handle's face or edge is gone or changed past recognition after a big change. | Ask find_geometry() again, or use a reference by definition (Extrusion1.end, Hole1.wall[0]). |
| `STALE_REVISION` | Something else changed the document since you last read it (the user, in the app). | The error's `changes` lists the features added, removed or edited and the parameters changed. Read it again (model_tree()) and redo the change. |
| `TIMEOUT` | A script ran past its timeout. | Raise timeout (max 240 s) or do less per call. |
| `TOO_COMPLEX` | The body has too many faces to read (5000). | Split the import into parts, or hand-model it. |
| `TOO_MANY` | An evaluate would build more variants than the most allowed (200). | Use fewer values, or optimise(), which searches with a budget. |
| `UNKNOWN_MATERIAL` | No material of that name. | ic://materials lists them. |
| `UNKNOWN_METHOD` | Internal: the server asked the host for a method it does not have. | Report it. |
| `UNKNOWN_OP` | There is no op of that type. | ic://schema/ops lists them. |
| `UNSAVED_CHANGES` | A branch switch or merge would replace changes that are not checked in. | branch(action="check_in") first, or discard them (snapshot restore / undo). |
| `USER_BUSY` | The user is in the middle of a sketch or a feature dialog in that document, so the app will not change it under them. | Ask them to finish or cancel it, then try again. |
| `USER_DECLINED` | The user said no when the client asked them. | Do not repeat it. Choose another path or ask what they want. |
| `VIEW_FAILED` | A drawing view or annotation could not be made; the drawing was left as it was. | The message is the drawing engine's (a cut line that misses the part, a detail with nothing in it...). |
| `WOULD_OVERWRITE` | Saving or exporting over a different file. | Pass overwrite only if the user asked for it. |
| `WRONG_TYPE` | The tool works on parts and this is an assembly (or the other way round). | Open the right document. |
