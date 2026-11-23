# Sketches and constraints

A sketch is a `sketch` op in build(): a plane, entities, then constraints
and dimensions that refer to the entities by the names you give them.
Sizes and positions written as numbers or expressions become driving
dimensions, so a parameter change later moves the geometry.

```json
[{"op":"parameter","name":"w","value":120},
 {"op":"parameter","name":"h","value":80},
 {"op":"parameter","name":"bolt","value":6.6},
 {"op":"sketch","id":"s1","plane":"XY","name":"Profile","entities":[
   {"rect":{"center":[0,0],"size":["w","h"]},"id":"r"},
   {"circle":{"center":["w/2 - 10", 0],"d":"bolt"},"id":"c"}]},
 {"op":"extrude","sketch":"$s1","distance":8}]
```

Entities: `rect` `circle` `arc` `line` `polyline` `point` `polygon` `spline` `ellipse`. Their parts are named after them: `r.top` `r.left`
`r.bl` `r.tr`, `c.center`, `l.start` `l.end`, `p.s0` (a polyline side)
`p.p0` (its points); `origin` is the sketch origin. rect, circle,
polygon and point are fully dimensioned on their own. Lines and
polylines with plain-number coordinates get horizontal/vertical
(`auto_constrain`); give them dimensions by name.

Curves are a `spline` (exactly through its points; `closed` true: smooth
all round, `"line"`: shut by a straight line) or an `ellipse` (`center`,
`rx`, `ry`, `rotation`), never a many-sided polyline: it shows as flats.

Planes: `XY`, `XZ`, `YZ`, a work plane (`"$wp1"`), any plane by numbers or
expressions (`{"origin":["L",0,0],"normal":[1,0,0],"x":[0,1,0]}`; it gets
a work plane of its own), or a flat face
(`"$e1.end"`, `{"faces":{"normal":"+z","largest":true}}`). On a face the
sketch keeps the face's own origin and x axis, so prefer origin planes
and work planes when positions must not move.

## Constraints (`"constraints":[{"perpendicular":["l1","l2"]}]`)

| kind | takes |
|---|---|
| `coincident` | point, point |
| `collinear` | line, line |
| `concentric` | entity, entity |
| `equal` | entity, entity |
| `fix` |  |
| `ground` |  |
| `horizontal` | horizontal takes a line, or two points. |
| `midpoint` | point, line |
| `offset` |  |
| `parallel` | line, line |
| `perpendicular` | line, line |
| `point_on` | point, entity |
| `symmetric` | point, point, line |
| `tangent` | entity, entity |
| `vertical` | vertical takes a line, or two points. |

## Dimensions (`"dimensions":[{"distance":["origin","c.center"],"value":20}]`)

| kind | takes |
|---|---|
| `distance` | distance takes two points, or a line (its length). |
| `distance_x` | point, point |
| `distance_y` | point, point |
| `distance_pl` | distance_pl takes a point and a line. |
| `radius` | entity |
| `diameter` | entity |
| `angle` | angle takes one line (from horizontal) or two lines. |
| `radial_gap` | entity, entity |
| `length` | length takes a line. |

A dimension that repeats what is already fixed is made driven, and the
build says so. An impossible one fails as `OVER_CONSTRAINED`, naming the
constraints that disagree.

## Checking a sketch

sketch_status() gives the degrees of freedom (aim for 0), which entities
can still move, conflicts, the dimensions, and the closed regions with
index, area and centre (largest first). Extrude `profiles` takes
`"outer"` (default: circles inside an outline become holes), `"all"`,
`"largest"`, or region indices.

## Lofts (wings, fuselages)

A `loft` blends sketches in order. Curved sections are splines or
ellipses with the same point count, start and direction in each, or it
twists (an airfoil: trailing edge, over the top, back; `"closed":"line"`).
`ruled: true` joins sections straight (a wing panel), false blends (a
body through many sections). `closed: true` (default) makes a solid or
fails saying why; `false` is an open surface. `XZ` offset +d is at -Y.
