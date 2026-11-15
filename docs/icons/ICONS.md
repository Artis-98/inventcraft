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

## Icons that borrow another one

These buttons and menu items have a name of their own already, but show
another tool's picture until a file of that name is put in
`datum/ui/assets/icons/`. Same rules as above. "Draw" is the brief for the
image model; "Now shows" is what it borrows until then.

### Drawings

| File name | Where it is | Draw | Now shows |
|---|---|---|---|
| `dv_break` | Drawing, Place Views, Break | A long bar with a gap in its middle, two zigzag break lines either side of the gap; the zigzags in accent | `dv_detail` |
| `dv_breakout` | Drawing, Break Out | A view frame with an irregular closed blob cut into it, the inside of the blob hatched | `dv_section` |
| `dv_crop` | Drawing, Crop | A view frame with a dashed accent rectangle inside it and corner crop marks, the part outside faded | `dv_detail` |
| `dv_unbreak` | Drawing, Remove Breaks | A bar with its zigzag break and a curved accent arrow closing the gap | `delete` |
| `dim_baseline` | Drawing, Baseline set | Three dimension lines stacked, all starting from one vertical datum line on the left | `dimension` |
| `dim_chain` | Drawing, Chain set | Three short dimension lines end to end in one row | `dimension` |
| `dim_ordinate` | Drawing, Ordinate set | An origin mark with three leader lines up to numbers 0, 20, 45 shown as short ticks (no real text) | `dimension` |
| `retrieve` | Drawing, Retrieve | A small 3D part with a dimension line lifting off it, an accent arrow pointing down onto a sheet | `rollback` |
| `revision_table` | Drawing, Revision | A small table of three rows with a triangle revision marker beside it | `params` |
| `balloon` | Drawing, Balloon | A circle on a leader line ending in a dot, the circle outlined in accent | `c_coincident` |
| `auto_balloon` | Drawing, Auto Balloon | Three balloons on leaders fanned round a small part, a sparkle in accent | `pattern` |
| `parts_list` | Drawing, Parts List | A table with a header row and numbered item rows, header filled grey | `material` |
| `print` | Drawing, Print | A printer with a sheet coming out | `export` |
| `export_pdf` | Drawing, Export PDF | A page with a folded corner and an accent arrow out of it, a red band on the page | `export` |
| `sheet_setup` | Drawing, Sheet Setup | A sheet with its border and title block in the corner, a small gear | `export` |
| `duplicate` | Drawing, Duplicate sheet | Two sheets overlapping, the front one with a plus | `pattern` |
| `delete_sheet` | Drawing, Delete Sheet | A sheet with its title block and a red cross | `delete` |
| `update_views` | Drawing, Update and Update All | A drawing view frame with circular refresh arrows round it | `rollback` |
| `template` | File menu, Save as Template | A page with a ruler and a dashed outline, a star in accent | `dimension` |

### Part modelling

| File name | Where it is | Draw | Now shows |
|---|---|---|---|
| `cut` | Sheet metal, Cut | A plate with a rectangular hole going through, an accent arrow pushing down into it | `extrude` |
| `features` | Pattern and Mirror window, "Pattern features" | Three small feature blocks in a row, joined, on one body | `extrude` |
| `bodies` | Pattern and Mirror window, "Pattern solids" | Two whole separate solid boxes side by side | `box` |
| `project_geometry` | Sketch, Project Geometry | A 3D edge with a dashed accent line dropping onto a flat sketch plane below | `offset` |
| `construction` | Sketch, Construction | A dashed line between two points, in accent, nothing solid | `offset` |
| `redefine` | Browser, Redefine sketch or plane | A sketch plane with a curved accent arrow moving it onto another plane | `plane` |
| `delete_below` | Browser, Delete All Features Below | A short feature list with a red line and everything under it faded | `delete` |
| `sm_corner_round` | Sheet metal, Corner Round | A plate corner rounded off, the round edge in accent | `fillet` |
| `sm_folded` | Sheet metal flat pattern, Go to Folded Part | A flat plate with an accent arrow folding one flange up | `sm_face` |
| `sm_to_standard` | Convert to Standard Part | A bent sheet metal part with an arrow to a plain solid block | `sm_convert` |
| `origin` | View, Origin toggle | Three short axis arrows from one point (X red, Y green, Z blue are fine here) | `plane` |
| `normal_to` | View, Normal To | An eye looking straight at a face, the face square on, an accent arrow into it | `front` |
| `set_front` | View cube menu, Set Current View as Front | The front cube face filled accent with a small pin | `front` |
| `set_top` | View cube menu, Set Current View as Top | The top cube face filled accent with a small pin | `top` |
| `xray` | View, X-Ray | A solid shown see-through with its hidden edges dashed | `section` |

### Selection filter

| File name | Where it is | Draw | Now shows |
|---|---|---|---|
| `select_body` | Selection filter, Body | A cursor arrow on a whole solid box, the whole box highlighted | `box` |
| `select_face` | Selection filter, Face | A cursor arrow on one face of a box, only that face filled accent | `shell` |
| `select_edge` | Selection filter, Edge | A cursor arrow on one edge of a box, only that edge in accent | `line` |
| `select_vertex` | Selection filter, Vertex | A cursor arrow on one corner of a box, an accent dot on the corner | `point` |

### Assembly and frames

| File name | Where it is | Draw | Now shows |
|---|---|---|---|
| `place` | Assemble, Place, and Place Component | A part dropping down onto a base with an accent arrow | `import` |
| `replace` | Component menu, Replace | Two parts with two arrows swapping them | `import` |
| `change_size` | Component menu, Change Size | A bolt with a double-ended accent arrow along its length | `library` |
| `create_part` | Assemble, Create Part | A new part outline with a plus, inside an assembly frame | `box` |
| `edit_in_place` | Component menu, Edit in Place | A pencil on one part among faded others | `edit` |
| `free_move` | Assemble, Free Move | A part with four way arrows | `move` |
| `free_rotate` | Assemble, Free Rotate | A part with a circular arrow round it | `revolve` |
| `return_up` | Assemble, Return (out of Edit in Place) | An arrow curving up and left out of a box | `finish` |
| `move_to` | Assemble and CAM, Move To | A part, a crosshair target and an accent arrow to it, a small number field | `params` |
| `hide` | Browser, Hide | A closed eye | `box` |
| `adaptive` | Assembly tree badge | Drawn already (two arrows chasing round), replace if wanted | drawn |
| `frame_refresh` | Frame Generator, Refresh | A frame of two members with circular refresh arrows | `update` |
| `frame_untreat` | Frame Generator, Remove End Treatments | A mitred corner of two members with a red cross | `delete` |
| `frame_analysis` | Design, Frame Analysis (experimental) | A frame with a downward load arrow and a curved deflection line in accent | `measure` |

### CAM

| File name | Where it is | Draw | Now shows |
|---|---|---|---|
| `cam_add_part` | CAM, Add Part | A flat part shape with a plus over a sheet | `import` |
| `cam_sheet` | CAM, Sheet and Tool | A rectangular sheet of plate with a small torch or cutter beside it | `rect` |
| `auto_arrange` | CAM, Auto Arrange | Several flat parts nested tightly on a sheet | `pattern` |
| `rotate_90` | CAM, Rotate 90 | A flat part with a quarter circle arrow and a right angle mark | `revolve` |
| `cut_face` | CAM, Cut Face | A part with one face filled accent and a cutter path round it | `shell` |
| `toolpath` | CAM, Show Toolpath | A dashed accent path running round a part outline with a direction arrow | `offset` |
| `frame_time` | View, Frame Time (developer timing) | A stopwatch | `measure` |

### Files and the window

| File name | Where it is | Draw | Now shows |
|---|---|---|---|
| `save_as` | File, Save As | A floppy disk with a small pencil | `save` |
| `save_replace` | Save and Replace | A floppy disk with two swap arrows | `save` |
| `export_dxf` | Every DXF export | A page with an accent arrow out of it and a small plotted line shape on the page | `export` |
| `export_svg` | Drawing, SVG | A page with an accent arrow out of it and a curve with two handles on the page | `export` |
| `import_dxf` | Import DXF | A page with an accent arrow into it and a plotted line shape | `import` |
| `folder_open` | Browser, Open File Location | An open folder with a small arrow out of it | `open` |
| `folder_add` | Library, Add Folder | A folder with an accent plus | `open` |
| `projects` | File, Projects | A folder with a small stack of parts on it | `open` |
| `preferences` | File, Preferences | A gear | `edit` |
| `properties` | dProperties everywhere | A part with a tag or label hanging on it | `material` |
| `bom` | Assemble, Bill of Materials | A list with a small part icon at each row | `material` |
| `check_updates` | Help, Check for Updates | A circular arrow round a down arrow | `rollback` |
| `regenerate` | Manage, Regenerate | A part with a lightning bolt and circular arrows | `rollback` |
| `versions` | File and Manage, Versions | A branching line with three dots, two branches | `rollback` |
