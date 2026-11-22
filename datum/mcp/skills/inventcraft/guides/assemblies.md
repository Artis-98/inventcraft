# Assemblies

An assembly holds **files**, not geometry: placed instances
(*occurrences*, named `Wheel:1`, `Wheel:2`) of parts or sub-assemblies,
and *constraints* between a face or edge of one and a face or edge of
another. A solver turns the constraints into placements. It is made with
`new_document(type="assembly")` and saved as `.icasm`. Needs the
`+assembly` tool group (on by default; `--tools default,-assembly` turns
it off). More than a few parts, modelled where they sit? build_project()
builds, colours, saves and places them all in one call.

## The loop

1. Build each part with build(), give it a Part Number, a description and
   a material with properties(), and **save_document() it**: an assembly
   places the file as last saved (an unsaved part is refused, and a part
   edited after saving must be saved again).
2. `new_document(type="assembly")`, then place_component(file=...) for
   each part. The first is **grounded** (fixed); later ones start at the
   origin or at `transform` and are free (6 degrees of freedom).
3. constrain() each free part to the grounded one (or to a part already
   placed): the answer says the DOF left on both. Repeat until 0.
4. **assembly_check()**: DOF per component, failing or redundant
   constraints, interference (volume and the pair). Then bom(). List the
   overlaps that are meant in `allow`, never a moving part against what it
   clears. Not `complete`? Go on from `next_start` before saying no clash.
5. render_view(style="shaded") shows it in colour; render_view(highlight=[...]) and
   measure() take occurrence references too (measure the gap you meant).

## Occurrence references

`<occurrence>/<reference in that part>`, in the grammar of
ic://guide/references, resolved *in the component's part* (by the roles
of its features, so they survive changes to the part), then taken on the
placed body:

- `Plate:1/Hole1.wall[0]`, `Axle:1/Extrude.end`, `Axle:1/Extrude.side(#e1)`
  (the feature names are the part's own: model_tree on the part lists
  them), `Plate:1/@F:3a7c0e` (a handle from find_geometry on that part
  while it is open).
- `Plate:1/origin.XY` (also XZ, YZ planes; X, Y, Z axes; `origin.point`):
  the part's own origin. A plane's normal is +Z (XY), -Y (XZ), +X (YZ), so
  `mate` flips a part onto it: use `flush` to keep it upright.
- The occurrence is its name, `#7` (its id), or the part's name while one
  occurrence has it. A whole component (`Plate:1`) is for measure() and
  render_view(), not constraints.
- A hole in a part is a cylinder wall: `insert` or `mate` it to a shaft
  wall to make them concentric.

## Constraint kinds

| kind | does |
|---|---|
| `mate` | Faces turned towards each other, axes made collinear. |
| `flush` | Faces turned the same way, lying in one plane. |
| `angle` | A fixed angle between two faces or axes. |
| `tangent` | A round face touching a flat or round one. |
| `insert` | Axes collinear and the two circles a set distance apart. |
| `parallel` | Two faces or axes kept parallel, free to slide apart. |

`offset` is mm (or an expression over the assembly's parameters,
set with properties(parameters={...}); `angle` for kind angle).
`flip` reverses the facing (insert, parallel, tangent). Geometry that is
not a plane, cylinder, cone, line or circle (a spline) cannot be used.
There are no joints (revolute, slider): an `insert` or `mate` on two
axes leaves the part free to turn and slide, which is the same freedom.

## Editing

There is no feature tree: **edit_feature(feature="Mate:2", params={"offset":5})**
changes a constraint (offset, angle, flip, kind, a, b), `"Wheel:1"` an
occurrence (transform, grounded, visible, model_state); suppress,
rename and delete work on both (deleting an occurrence needs
delete_dependents while constraints use it). properties() sets the
assembly's parameters. Every change is atomic and one undo step; a
constraint nothing can satisfy is refused (`CONSTRAINT_FAILED`) and the
assembly stays as it was.

## Reading the checks

- DOF 0 and `fully_constrained` = every free part is held. A part that
  only slides along an axle is 1 or 2: constrain it, or accept it.
- `redundant` constraints repeat others (consistent, but pointless).
- Touching faces are not interference; overlapping volume is.
- bom(): `flat` counts every part through sub-assemblies, `structured`
  keeps them under their sub-assembly; mass is grams from volume and the
  material's density, so set materials first.
