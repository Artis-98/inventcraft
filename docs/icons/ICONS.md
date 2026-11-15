# InventCraft icons

Every icon in the app today, what it stands for, and how a replacement has to
be made so it drops straight in. The picture of how they look now is
`current-icons.png` next to this file.

## How a replacement is made

**File.** One SVG per icon, named exactly as the list below
(`extrude.svg`, `c3d_mate.svg`), put in `datum/ui/assets/icons/`. The app
picks a file up in place of the drawn icon by itself; delete the file and the
old one is back. No rebuild of anything else.

**Canvas.** `viewBox="0 0 24 24"`, no width or height attributes, transparent
background. Keep 2 units of empty margin all round (draw inside 2 to 22).

**Sizes it is shown at.** 16 px in the browser tree and menus, 18 to 22 px on
small ribbon buttons and dialogs, 32 px on big ribbon buttons, all at 1x and
2x. It has to read at 16 px: one idea per icon, no text smaller than the whole
icon, no detail under 1.5 units.

**Strokes.** 1.5 to 1.7 units, round caps, round joins. Fills flat. No
gradients, no shadows, no glow, no blur, no photo texture. Isometric 3D where
a solid is shown (30 degree sides), flat 2D for sketch and drawing tools.

**Colours.** Only these, because the app swaps them for the colour scheme
when it reads the file (dark, midnight, copper, charcoal, olive):

| Role | Hex in the file | What it is for |
|---|---|---|
| Line | `#2b3540` | outlines, the main shape |
| Accent | `#b9820f` | the thing the tool does: the arrow, the new edge, the highlight |
| Solid | `#7a8693` | faces of solids, filled areas (use `fill-opacity` 0.35 to 1) |
| Warning | `#e0a355` | only where an icon warns |
| Good | `#69c26b` | only for "done" or "fixed" |
| Delete | `#d9534f` | only for delete and cancel |

Any other colour stays the same in every scheme, so it will look wrong on the
dark ones. Write the hex in lower case.

**Style to ask the model for.** "Flat technical CAD toolbar icon, 24x24 grid,
1.6 px rounded strokes, dark slate outline #2b3540, one gold accent #b9820f
for the action, grey #7a8693 faces, isometric where 3D, transparent
background, no text, no gradient, no shadow, consistent with Autodesk
Inventor's ribbon icons in meaning but not copied." Image models give PNG:
trace it to SVG (Inkscape Trace Bitmap, or vectorizer.ai) and then set the
colours to the exact hex values above, or the scheme swap will miss them.

**Copyright.** Do not feed Inventor's own icons in as images to copy. Same
meaning, own drawing.

## Every icon now

### Files and the window

| Name | What it does |
|---|---|
| `new` | New part, assembly or drawing |
| `open` | Open a file |
| `save` | Save (also Save and Replace) |
| `file` | About, and a document in a tree |
| `export` | Export DXF, PDF, SVG, Print, Sheet Setup (shared, see the end) |
| `import` | Import a body, Import DXF, Place a component, Add Part |
| `exit` | Exit the program |
| `undo` / `redo` | Undo, Redo |
| `update` | Local Update (the lightning bolt), Refresh frames |
| `rollback` | Rollback marker in the tree, Regenerate, Update All, Retrieve, Versions (shared) |
| `params` | Parameters, Revision, Move To |
| `material` | Material, dProperties, Bill of Materials, Parts List |
| `measure` | Measure, Frame Analysis, Frame Time |
| `code` | Code feature (a body written as Python) |
| `auto` | cLogic rules |
| `spacemouse` | SpaceMouse settings |
| `library` | Place from Library (the shelf of standard parts) |
| `bulb` | Show the view label on a drawing |
| `select` | Pick a face or edge again in a dialog |
| `edit` | Edit a feature or constraint |
| `delete` | Delete anything (feature, sheet, breaks, end treatments) |
| `cancel` | Cancel a tool |
| `finish` | Finish Sketch, Return, OK |
| `suppress` | Suppress, Unsuppress |

### View

| Name | What it does |
|---|---|
| `iso` | Home view |
| `fit` | Fit all |
| `front` / `top` / `right` | Look along that axis; Front is also Normal To |
| `ortho` | Orthographic or perspective |
| `shaded` / `shaded_edges` / `wireframe` | Visual style |
| `section` | X-Ray, and Section View in the 3D window |
| `grid` | Show the sketch grid |
| `dof` | Show degrees of freedom in a sketch |

### Sketch

| Name | What it does |
|---|---|
| `sketch` | Start 2D Sketch, and a sketch in the tree |
| `sketch_shared` | A shared sketch in the tree |
| `line` | Line (also Edge pick) |
| `circle` | Circle, centre point |
| `arc` | Arc |
| `ellipse` | Ellipse |
| `spline` | Spline |
| `point` | Point (also Snap to Grid, Vertex pick) |
| `rect` | Rectangle, two point |
| `rect3` | Rectangle, three point |
| `rect_centre` | Rectangle, two point centre |
| `rect3_centre` | Rectangle, three point centre |
| `slot` | Slot, centre to centre |
| `slot_overall` | Slot, overall |
| `slot_centre` | Slot, centre point |
| `slot_arc3` | Arc slot, three point |
| `slot_arc_centre` | Arc slot, centre point |
| `polygon` | Polygon |
| `text` | Sketch text |
| `fillet2d` | Sketch fillet |
| `trim` | Trim |
| `offset` | Offset (also Project Geometry, Construction, Show Toolpath: shared) |
| `mirror` | Mirror |
| `dimension` | Sketch dimension (also drawing dimensions, Baseline, Chain, Ordinate: shared) |

### Sketch constraints

| Name | What it does |
|---|---|
| `c_coincident` | Coincident (also Balloon in drawings: shared) |
| `c_collinear` | Collinear |
| `c_concentric` | Concentric |
| `c_equal` | Equal |
| `c_fix` | Fix / Grounded, and Ground a component |
| `c_horizontal` | Horizontal |
| `c_vertical` | Vertical |
| `c_midpoint` | Midpoint |
| `c_parallel` | Parallel |
| `c_perpendicular` | Perpendicular |
| `c_pointon` | Point on curve |
| `c_symmetric` | Symmetric |
| `c_tangent` | Tangent |

### Part features

| Name | What it does |
|---|---|
| `extrude` | Extrude (also Cut) |
| `revolve` | Revolve (also Free Rotate, Rotate 90: shared) |
| `sweep` | Sweep |
| `loft` | Loft |
| `hole` | Hole |
| `fillet` | Fillet (also Corner Round) |
| `chamfer` | Chamfer |
| `shell` | Shell (also Face, Cut Face: shared) |
| `pattern` | Rectangular pattern (also Duplicate, Auto Balloon, Auto Arrange: shared) |
| `pattern_circ` | Circular pattern |
| `combine` | Combine bodies |
| `split` / `split_faces` / `split_solid` | Split, and its two modes |
| `move` | Move Body (also Free Move, Move Parts) |
| `emboss` / `engrave` | Emboss and Engrave |
| `plane` | Work plane (also Origin) |
| `axis` | Work axis |
| `box` / `cylinder` / `sphere` | Primitives; `box` is also a part in a tree |
| `feature` | A generic feature in the tree |
| `dir_default` / `dir_flipped` / `dir_symmetric` / `dir_asymmetric` | Which way an extrude goes |

### Sheet metal

| Name | What it does |
|---|---|
| `sm_defaults` | Sheet Metal Defaults (thickness, bend radius, K factor) |
| `sm_face` | Face |
| `sm_flange` | Flange |
| `sm_contour` | Contour Flange |
| `sm_corner` | Corner Seam |
| `sm_fold` | Fold |
| `sm_hem` / `sm_hem_double` / `sm_hem_rolled` / `sm_hem_teardrop` | Hem and its types |
| `sm_inside` / `sm_adjacent` | Where a flange's bend starts |
| `sm_flat` | Flat pattern |
| `sm_convert` | Convert to sheet metal, and back |
| `sm_perforation` / `sm_perforation_straight` / `sm_perforation_trapezoid` | Bend perforation and its slot shapes |

### Assembly

| Name | What it does |
|---|---|
| `c3d_mate` | Constrain, Mate |
| `c3d_flush` | Flush |
| `c3d_insert` | Insert, and Assemble |
| `c3d_angle` | Angle |
| `c3d_tangent` | Tangent |
| `c3d_parallel` | Parallel |
| `c3d_symmetry` | Symmetry (drawn, not on a button yet) |

### Frame generator

| Name | What it does |
|---|---|
| `frame_insert` | Insert Frame |
| `frame_change` | Change Frame |
| `frame_member` | A frame member in the tree |
| `frame_assembly` | A frame assembly in the tree |
| `frame_library` | Profile Library |
| `frame_miter` | Miter |
| `frame_corner` | Corner Joint |
| `frame_trim` | Trim and Extend to a face |
| `frame_notch` | Notch |
| `frame_lengthen` | Lengthen and Shorten |

### Drawings

| Name | What it does |
|---|---|
| `new_sheet` | New Sheet |
| `dv_base` | Base view |
| `dv_projected` | Projected view |
| `dv_auxiliary` | Auxiliary view |
| `dv_section` | Section view (also Break Out: shared) |
| `dv_detail` | Detail view (also Break: shared) |
| `view_visible` / `view_hidden` | Visible lines only, or hidden lines shown; also Show / Hide annotations |
| `an_text` | Text |
| `an_leader` | Leader text |
| `an_hole` | Hole and thread note |
| `an_centremark` | Centre mark |
| `an_centreline` | Centre line |
| `an_bisector` | Centre line bisector |
| `an_surface` | Surface texture symbol |
| `an_fcf` | Feature control frame (GD&T) |
| `an_datum` | Datum identifier |
| `an_weld` | Welding symbol |

## Icons that are missing

These buttons borrow another tool's icon today. Each one wants its own; same
rules as above, and the file name is what the app will look for once I wire
it up.

| New name | For | Borrows now |
|---|---|---|
| `dv_break` | Break view | `dv_detail` |
| `dv_breakout` | Break Out | `dv_section` |
| `dv_crop` | Crop a view (coming) | none |
| `dim_baseline` | Baseline dimension set | `dimension` |
| `dim_chain` | Chain dimension set | `dimension` |
| `dim_ordinate` | Ordinate dimension set | `dimension` |
| `retrieve` | Retrieve model dimensions | `rollback` |
| `revision_table` | Revision table | `params` |
| `balloon` | Balloon | `c_coincident` |
| `parts_list` | Parts list | `material` |
| `versions` | Versions and branches | `rollback` |
| `frame_analysis` | Frame Analysis | `measure` |
| `project_geometry` | Project Geometry | `offset` |
| `construction` | Construction line toggle | `offset` |
| `adaptive` | Adaptive part badge in the assembly tree (coming) | none |
| `redefine` | Redefine sketch | none |
| `print` | Print | `export` |
| `export_pdf` | Export PDF | `export` |
| `sheet_setup` | Sheet Setup | `export` |
| `cut` | Extrude as a cut | `extrude` |
| `free_rotate` | Free Rotate | `revolve` |
| `duplicate` | Duplicate a sheet | `pattern` |
