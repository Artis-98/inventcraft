"""What went wrong, said so that an agent can do something about it.

Every failure comes back as a kind, a message and a few hints. The kind is
stable and short, so an agent can branch on it; the hints say what usually
fixes it, which is most of what a person would have told it. Nothing here
imports OpenCASCADE: the classifier works on the exception's class name and
text, so the MCP server can use it too.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple


class BridgeError(Exception):
    """A failure the bridge means to report, with its kind and hints."""

    def __init__(self, kind: str, message: str,
                 hints: Optional[List[str]] = None, **extra: Any) -> None:
        super().__init__(message)
        self.kind = kind
        self.message = message
        self.hints = list(hints or [])
        self.extra = extra

    def to_dict(self) -> Dict[str, Any]:
        out = {"kind": self.kind, "message": self.message,
               "hints": self.hints}
        out.update(self.extra)
        return out


# (pattern applied to the message, kind, hints); the first match wins
_RULES: List[Tuple[str, str, List[str]]] = [
    (r"no (closed )?(region|profile)|not closed|open profile",
     "PROFILE_NOT_CLOSED",
     ["The sketch has no closed region to use. Lines must meet end to end.",
      "Use rect or circle entities, or a closed polyline."]),
    (r"there is no body|no solid|nothing to (fillet|chamfer|cut)|"
     r"require_shape|has no body",
     "NO_BODY",
     ["This feature works on a solid, and there is none yet before it.",
      "Extrude a sketch first, or check the feature order."]),
    (r"fillet|chamfer",
     "EDGE_OP_FAILED",
     ["The radius or distance may be too big for the edges it meets.",
      "Try a smaller value, or fewer edges, or fillet before the cuts."]),
    (r"self[- ]?intersect",
     "SELF_INTERSECTION",
     ["The result would cross itself. Reduce the size or split the step."]),
    (r"parameter '(Thickness|BendRadius)' is not defined",
     "SHEET_METAL_PARAMETERS",
     ["Sheet-metal features (sheet_face, flange, contour_flange, hem, "
      "fold, corner_seam) take the sheet's thickness and bend radius "
      "from the parameters Thickness and BendRadius. Add both first, in "
      "the same build: {\"op\":\"parameter\",\"name\":\"Thickness\","
      "\"value\":1.5} and {\"op\":\"parameter\",\"name\":\"BendRadius\","
      "\"value\":1.5}."]),
    (r"is a reserved name|is not a valid parameter name",
     "BAD_NAME",
     ["Parameter names are identifiers, and the expression language "
      "keeps some for itself: the constants e and pi, and its functions "
      "(sin, cos, sqrt, min, max, round...; ic://guide/units lists them). "
      "Choose a longer name, such as edge or inset for e."]),
    (r"unknown name|not defined|undefined|ExpressionError|could not "
     r"evaluate|invalid expression|syntax",
     "BAD_EXPRESSION",
     ["An expression names a parameter that does not exist, or is not "
      "valid. Read the parameters with properties(), or add the "
      "parameter in the same build with a parameter op."]),
    (r"zero|must be positive|is negative",
     "BAD_VALUE",
     ["A size came out as zero or negative. Check the expression."]),
]


# every kind a failure can have: what it means, then what usually fixes it.
# ic://guide/errors is written from this table and the rules above, and a
# test checks that every kind raised anywhere in the bridge is listed here.
KINDS: Dict[str, Tuple[str, str]] = {
    "BAD_OP": ("An op is malformed: an unknown field, a missing one, or a "
               "value of the wrong shape.",
               "The error lists the fields the op takes; the op's schema "
               "is ic://schema/op/{type}."),
    "UNKNOWN_OP": ("There is no op of that type.",
                   "ic://schema/ops lists them."),
    "BAD_REF": ("A reference does not parse or names nothing.",
                "ic://schema/ref has the grammar; find_geometry() hands "
                "out @F/@E/@V handles; in one build use \"$id\" of an op."),
    "STALE_REF": ("An @ handle's face or edge is gone or changed past "
                  "recognition after a big change.",
                  "Ask find_geometry() again, or use a reference by "
                  "definition (Extrusion1.end, Hole1.wall[0])."),
    "NO_PROVENANCE": ("The part does not know which feature made that "
                      "face (a body too big to tag, a feature that "
                      "changed it without saying how, or a role that "
                      "feature does not have).",
                      "Use find_geometry() with created_by, or a face "
                      "query; the message says what does work."),
    "NO_MATCH": ("A face or edge query matched nothing.",
                 "Loosen it, or look with find_geometry() and "
                 "render_view(highlight=[...])."),
    "BAD_QUERY": ("A face or edge query has an unknown key or value.",
                  "The message lists the keys it takes."),
    "BAD_VALUE": ("A value is out of range: zero, negative, or not one "
                  "of the choices.", "The message names the choices."),
    "BAD_EXPRESSION": ("An expression names a parameter that does not "
                       "exist or does not parse.",
                       "Add a parameter op earlier in the same build, or "
                       "read the parameters with properties()."),
    "BAD_NAME": ("A parameter name is not an identifier, or is one the "
                 "expression language keeps (e, pi, sin, sqrt...).",
                 "Choose another name; ic://guide/units lists the "
                 "reserved ones."),
    "SHEET_METAL_PARAMETERS": ("A sheet-metal feature has no Thickness or "
                               "BendRadius parameter to read.",
                               "Add both as parameter ops first."),
    "PROFILE_NOT_CLOSED": ("The sketch has no closed region.",
                           "Use rect, circle or polygon entities, or a "
                           "closed polyline; sketch_status() lists regions."),
    "OVER_CONSTRAINED": ("Two constraints or dimensions disagree.",
                         "The message names them; drop one."),
    "NO_BODY": ("The feature needs a solid and there is none before it.",
                "Extrude something first, or move the feature later."),
    "NOT_FLAT": ("A sketch was put on a face that is not flat.",
                 "Pick a plane face, or a work plane."),
    "EDGE_OP_FAILED": ("A fillet or chamfer could not be made.",
                       "Use a smaller size or fewer edges; check the pick "
                       "with render_view(highlight_edges=...)."),
    "SELF_INTERSECTION": ("The result would cross itself.",
                          "Reduce the size or split the step."),
    "FEATURE_FAILED": ("A feature failed when the part rebuilt; the "
                       "message is the core's.",
                       "Read the hints; the build was rolled back, so "
                       "fix that op and send the build again."),
    "KERNEL_FAILED": ("The geometry kernel refused the operation.",
                      "Often a tangent or zero-thickness case; nudge a "
                      "size."),
    "HAS_DEPENDENTS": ("Removing a feature others use.",
                       "The error names them; pass delete_dependents, or "
                       "\"dependents\":\"remove\" in a remove op."),
    "BAD_ORDER": ("A move would put a feature before something it uses.",
                  "Move it later, or move what it uses first."),
    "STALE_REVISION": ("Something else changed the document since you "
                       "last read it (the user, in the app).",
                       "The error's `changes` lists the features added, "
                       "removed or edited and the parameters changed. Read "
                       "it again (model_tree()) and redo the change."),
    "FILE_OPEN_IN_APP": ("A save or export from a headless host would write "
                         "over a file the app has open.",
                         "Edit the app's copy (its g handle) and save from "
                         "there, or use another path."),
    "NO_DOCUMENT": ("No such document handle, or no document open.",
                    "status() lists them; new_document() or "
                    "open_document() makes one."),
    "WRONG_TYPE": ("The tool works on parts and this is an assembly (or "
                   "the other way round).", "Open the right document."),
    "TOO_MANY": ("An evaluate would build more variants than the most "
                 "allowed (200).", "Use fewer values, or optimise(), "
                 "which searches with a budget."),
    "PARTIAL_COVERAGE": ("parametrize() found features, but the tree they "
                         "make is not the body: the share of faces it "
                         "reproduces is below the whole, or the boolean "
                         "difference is over the tolerance. Nothing was "
                         "changed.",
                         "The error carries the report: unexplained faces "
                         "with handles. Rebuild those by hand, or pass "
                         "plan={\"ops\": [...]}."),
    "NOT_PARAMETRIC": ("recognize() found no base to build on (the body is "
                       "not a prism along x, y or z).",
                       "Rebuild it by hand from find_geometry() and "
                       "measure(); ic://guide/import."),
    "NOT_VERIFIED": ("parametrize() could not check its tree against the "
                     "original, so it did not apply it.",
                     "recognize(detail=true) shows the ops; use "
                     "verify=false only to see what it would do."),
    "TOO_COMPLEX": ("The body has too many faces to read (5000).",
                    "Split the import into parts, or hand-model it."),
    "AMBIGUOUS": ("The part has several bodies and the tool needs one.",
                  "Name it with body=."),
    "REPLACE_TREE_REQUIRED": ("parametrize() on a part that already has a "
                              "feature tree of its own, which it would "
                              "delete. Nothing was changed.",
                              "Pass replace_tree=true only if the user "
                              "wants that tree replaced."),
    "PATH_NOT_ALLOWED": ("A file path outside the folders the server may "
                         "touch: the client's MCP roots when it gives them, "
                         "else the project folder and the --allow-dir "
                         "folders.",
                         "Use a path inside one of the allowed folders "
                         "(the error lists them), or ask the user to start "
                         "the server with --allow-dir <folder>."),
    "CONFIRM_REQUIRED": ("Writing over an existing file that keeps no old "
                         "version of itself: the user must agree first.",
                         "Ask the user; then repeat the call with "
                         "overwrite=true and confirm=true."),
    "USER_DECLINED": ("The user said no when the client asked them.",
                      "Do not repeat it. Choose another path or ask what "
                      "they want."),
    "NOT_FOUND": ("A file, feature or parameter of that name is not "
                  "there.", "Check the name with model_tree()."),
    "BAD_PATH": ("A path is relative or has the wrong extension.",
                 "Use an absolute path."),
    "FILE_IN_USE": ("A file to be written is open with unsaved changes.",
                    "save_document() or close_document() it first."),
    "BUILD_FAILED": ("A part of a build_project failed, so it was not "
                     "written; the others were.",
                     "Fix that part and send only it, with overwrite."),
    "ASSEMBLY_FAILED": ("build_project saved the parts and could not make "
                        "the assembly of them.",
                        "Read the message, then call again or "
                        "place_component() them."),
    "WOULD_OVERWRITE": ("Saving or exporting over a different file.",
                        "Pass overwrite only if the user asked for it."),
    "BAD_FORMAT": ("An export format that is not supported.",
                   "Use .step, .stl, .iges or .brep."),
    "BAD_FILE": ("The file could not be read.", "Is it an InventCraft "
                 "part or assembly?"),
    "NEWER_FILE": ("The file comes from a newer InventCraft.",
                   "Open it in that version."),
    "BAD_EXPECTATION": ("inspect() was given a key it cannot check.",
                        "Checkable: bbox, volume, mass_g, solids, faces, "
                        "valid, tolerance."),
    "BAD_REQUIREMENT": ("A requirement is malformed.",
                        "See the requirements() tool description, or "
                        "ic://guide/requirements."),
    "UNKNOWN_MATERIAL": ("No material of that name.",
                         "ic://materials lists them."),
    "BAD_VIEW": ("render_view() was given a view it does not know.",
                 "iso, front, back, left, right, top, bottom, or [x,y,z]."),
    "RENDER_FAILED": ("The drawing could not be made.",
                      "Is there a solid? inspect() says."),
    "BAD_CODE": ("A code op's source does not compile.",
                 "The message gives the line."),
    "SCRIPT_FAILED": ("run_script()'s code raised; nothing was applied.",
                      "The traceback and printed output come back."),
    "SCRIPT_CRASHED": ("The script's process died.", "Nothing was applied; "
                       "simplify the script."),
    "SCRIPT_UNSUPPORTED": ("The script changed something that cannot be "
                           "applied as ops.", "The message says what."),
    "SAFE_MODE": ("safe_mode refused an import, a file access or a "
                  "dunder.", "Do without it, or run without safe_mode."),
    "TIMEOUT": ("A script ran past its timeout.", "Raise timeout (max "
                "240 s) or do less per call."),
    "NOT_YET": ("That part of the API is planned, not built.",
                "The message says what to use meanwhile."),
    "VIEW_FAILED": ("A drawing view or annotation could not be made; the "
                    "drawing was left as it was.",
                    "The message is the drawing engine's (a cut line that "
                    "misses the part, a detail with nothing in it...)."),
    "NO_VIEW": ("A drawing has no view or item of that name.",
                "model_tree() lists the views (name, id) and annotations."),
    "NO_MODEL": ("A drawing needs a saved part or assembly to draw.",
                 "save_document() the model first, then give its path or "
                 "handle as source."),
    "UNSAVED_CHANGES": ("A branch switch or merge would replace changes "
                        "that are not checked in.",
                        "branch(action=\"check_in\") first, or discard "
                        "them (snapshot restore / undo)."),
    "MERGE_CONFLICT": ("Both branches changed the same thing in different "
                       "ways; nothing was merged.",
                       "The error lists each conflict. Change one branch "
                       "so they agree, or merge the other way round."),
    "NO_BRANCH": ("No branch of that name.", "branch(action=\"list\")."),
    "NO_STATE": ("No model state of that name.",
                 "model_states(action=\"list\") lists them."),
    "NOT_ALLOWED": ("The operating system refused a file.",
                    "Choose another path."),
    "UNKNOWN_METHOD": ("Internal: the server asked the host for a method "
                       "it does not have.", "Report it."),
    "HOST_LOST": ("The geometry host crashed or was killed.",
                  "Open or create the document again; saved files are "
                  "safe."),
    "CANCELLED": ("The user pressed Stop in the app, so the request was "
                  "dropped before it ran or rolled back while it ran.",
                  "Nothing was kept. Ask the user what they want before "
                  "trying again."),
    "USER_BUSY": ("The user is in the middle of a sketch or a feature "
                  "dialog in that document, so the app will not change it "
                  "under them.",
                  "Ask them to finish or cancel it, then try again."),
    "NOT_IN_GUI_HOST": ("That tool is not run in the app: the user's "
                        "session never runs an agent's code, and their "
                        "open documents are theirs to close.",
                        "run_script goes to a separate host by itself; for "
                        "a structure that follows a parameter use a code "
                        "op in build (the user is asked to allow it)."),
    "GUI_HOST_UNAVAILABLE": ("The app's bridge is not reachable: the app "
                             "is not running, or Preferences > AI > Allow "
                             "agents is off.",
                             "Ask the user to start InventCraft and turn "
                             "Allow agents on; or work headless "
                             "(--host headless)."),
    "GUI_PAIRING_FAILED": ("The app's bridge refused this server's "
                           "secret.",
                           "Turn Allow agents off and on in the app to "
                           "make a new pairing, then try again."),
    "NO_OCCURRENCE": ("No component of that name is placed in the "
                      "assembly.", "The message lists the occurrences "
                      "(Wheel:1, ...); place_component() adds one."),
    "AMBIGUOUS_REF": ("A reference inside a component names more than one "
                      "face or edge; a constraint takes exactly one.",
                      "Add an index (Hole1.wall[0]) or use a handle."),
    "NO_COMPONENT": ("A placed component's file is missing, did not "
                     "build, or was never saved.",
                     "Save the part first (save_document), then place its "
                     "file; assembly_check() lists components that failed "
                     "to load."),
    "STALE_COMPONENT": ("The body the assembly placed is no longer the "
                        "part as the reference found it (the file changed "
                        "or the part has unsaved edits).",
                        "save_document the part, then assembly_check() "
                        "rebuilds the assembly from the files."),
    "BAD_TRANSFORM": ("A placement is malformed.",
                      "{\"position\":[x,y,z], \"rotate\":{\"axis\":[0,0,1], "
                      "\"angle\":90}} in mm and degrees, or \"euler\":"
                      "[rx,ry,rz]."),
    "BAD_KIND": ("An unknown constraint kind.",
                 "mate, flush, angle, tangent, insert or parallel; the "
                 "message says what each does."),
    "BAD_PAIRING": ("That constraint kind does not apply to those two "
                    "kinds of geometry (say, insert on two flat faces).",
                    "The message says what a and b are and which kinds "
                    "take them."),
    "SAME_OCCURRENCE": ("Both sides of a constraint are on one "
                        "component.", "Constrain to a different "
                        "component, or to its origin planes."),
    "NOT_MATEABLE": ("The face or edge is free-form (a spline), so the "
                     "solver has no plane, axis or circle to hold.",
                     "Pick a flat face, a hole or shaft wall, or a "
                     "circular edge."),
    "CONSTRAINT_FAILED": ("The change leaves a constraint nothing can "
                          "satisfy, or a component that will not load; "
                          "the assembly is unchanged.",
                          "The message names the constraint. Check the "
                          "offset and flip, or remove a conflicting older "
                          "constraint; assembly_check() lists conflicts."),
    "NOT_SHEET_METAL": ("The part has no sheet metal rules and no "
                        "Thickness parameter, so there is nothing to "
                        "lay flat or check.",
                        "sheet_rules(thickness=..., bend_radius=..., "
                        "k_factor=...) converts it; build the sheet "
                        "features first."),
    "FLAT_FAILED": ("The sheet cannot be laid flat: a bend that is not "
                    "round, a corner between bends with no relief, or "
                    "not one thickness throughout.",
                    "sheet_check() says what is wrong; let flanges that "
                    "meet relieve themselves or add a corner_seam."),
    "NO_PROFILE": ("There is no such profile family or size.",
                   "frame_profiles() lists families; "
                   "frame_profiles(family=...) lists a family's sizes."),
    "NO_SKETCH": ("The skeleton has no sketch of that name with lines.",
                  "The message lists the sketches; build and save the "
                  "skeleton part first."),
    "NO_FRAME": ("The assembly has no frame yet.",
                 "frame_insert() makes one on a skeleton."),
    "NO_PARAMETER": ("No part or assembly has a parameter of that "
                     "name.", "skeleton_params() lists every name, parts' "
                     "as <part>_<name>."),
    "INTERNAL": ("An unexpected error.", "Report it, with the message."),
}


def classify(exc: BaseException) -> Dict[str, Any]:
    """Turn any exception into ``{kind, message, hints}``."""
    if isinstance(exc, BridgeError):
        return exc.to_dict()
    if isinstance(getattr(exc, "kind", None), str) and hasattr(exc, "hints"):
        # the core's own reportable errors (edgequery.QueryError)
        return {"kind": exc.kind, "message": str(exc),
                "hints": list(exc.hints)}
    message = str(exc) or exc.__class__.__name__
    haystack = "%s %s" % (exc.__class__.__name__, message)
    for pattern, kind, hints in _RULES:
        if re.search(pattern, haystack, re.IGNORECASE):
            return {"kind": kind, "message": message, "hints": list(hints)}
    name = exc.__class__.__name__
    kind = {"FeatureError": "FEATURE_FAILED",
            "KernelError": "KERNEL_FAILED",
            "FileFormatError": "BAD_FILE",
            "UnsupportedVersionError": "NEWER_FILE",
            "FileNotFoundError": "NOT_FOUND",
            "PermissionError": "NOT_ALLOWED",
            }.get(name, "INTERNAL")
    return {"kind": kind, "message": message, "hints": []}
