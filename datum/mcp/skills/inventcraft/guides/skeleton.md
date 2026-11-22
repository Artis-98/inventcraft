# Skeleton design (top-down)

One part, the **skeleton**, holds the layout as sketches and the numbers
the design hangs on as parameters; everything else follows it.
`--tools +skeleton` (and +frames for members):

1. **Skeleton part**: `parameter` ops for the master numbers (`L`, `W`,
   `TOP`, a tube size `B`), derived ones as expressions (`Ztop = TOP - B/2`),
   `workplane` ops with expression offsets for the levels, and sketches of
   lines on them with expression coordinates:
   `{"line":[[0,"Zbot + B/2"],["L","Zbot + B/2"]]}`, a `rect` with
   `size:["L","W"]`. Give each sketch a name: it is how frames pick it.
   Add one small solid (a 2 mm block at the origin): an assembly places
   and constrains components that have a body, so this is what the others
   are constrained to by the skeleton's origin planes. Save it.
2. **Parts to derive**: build each normally with its own parameters (a
   plate's `TL`, `TW`) and save it.
3. **Assembly**: place the skeleton first (it is grounded), then
   `frame_insert()` the members on its sketches.
4. `derive_part(file=..., drives={"TL": "Skeleton_L - 2"})` makes a part
   follow: a parameter set by an expression over the skeleton's, written
   into the part's file. Names are `<part>_<name>`, the part's number or
   file name (spaces become underscores): `skeleton_params()` lists every
   one, the drivers, and the assembly's own parameters.
5. `place_component()` and `constrain()` the parts to the skeleton's origin
   planes with offsets written over the parameters: `constrain(kind=
   "flush", a="Skeleton:1/origin.XY", b="Tray:1/origin.XY",
   offset="Skeleton_TOP")` (the XZ plane's normal is -Y, so a y offset is
   negative). Constrain to 0 DOF, then `assembly_check()` and `bom()`.
6. `skeleton_set(set={"Skeleton_L": 800})` changes a master parameter:
   the skeleton and every derived part are rebuilt and saved, the frame
   follows the lines, constraints written over parameters move; the answer
   lists what moved and the box before and after. One undo step; refused,
   with the files as they were, if a part will not build.
   Then `assembly_check()` again: fit is yours to check.

The parts stay ordinary parts that build on their own: the relationship
is kept by the assembly (its Parameters table in the app). To stop it,
`derive_part(drives={}, release=["Top_Tray_TL"])` keeps the value.
Not there: a derived part that projects the skeleton's edges (the app's
adaptive projection), or a skeleton without any body.
