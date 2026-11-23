# References and find_geometry

Faces, edges and vertices are named by readable references, never by an
index, because indices renumber after every feature.

## Forms

| reference | names |
|---|---|
| `Extrusion3.end / .start` | end and start caps of an extrusion, revolve, sweep or loft (via role, else definition) |
| `Extrusion3.side(a)` | the side face swept from sketch entity a (a build name, or #e4 by id; via role, or definition for an untapered extrusion) |
| `Extrusion3.end.edge(side(a))` | the edge between two faces: any face role, then .edge(another role of the same feature, or a whole reference such as Hole2.wall[0]) |
| `Hole2.wall[0] / Hole2.wall` | a hole's bore, by the order of its centres; every hole without an index |
| `Hole2.cbore[0]` | a counterbore's wall |
| `Hole2.shoulder[0] / .floor[0] / .csink[0]` | a counterbore's step, a blind hole's floor, a countersink's cone (via role) |
| `Fillet5.face[0] / Chamfer6.face[0]` | the round or bevel made from the feature's first edge, in the order the edges were given (via role). The faces are also kept by the edge they round, which an edge added earlier in the tree does not renumber |
| `Sketch1.region[0] / Sketch1.region` | a sketch's closed regions, largest first (a flat face of the sketch, not of the body) |
| `Sketch1.c1.center` | a named sketch point or entity, in 3D |
| `@F:xxxxxx @E:xxxxxx @V:xxxxxx` | handles from find_geometry, rebound by fingerprint |
| `body:Name / part` | a whole body, or the whole part (measure) |
| `Wheel:1/Hole1.wall[0]` | in an assembly: <occurrence>/<any reference above>, resolved in that component's part and taken on the placed body (an occurrence is its name, #id, or the part's name while only one is placed) |
| `Wheel:1/origin.XY` | in an assembly: the component's own origin plane (XY, XZ, YZ), axis (X, Y, Z) or origin.point; for constrain() only |
| `Wheel:1` | in an assembly: a whole component (measure, render_view highlight) |
| `[x, y, z]` | a point (measure only) |
| `$id.<any of these>` | an op of the same build |

Every answer that resolves references says how (`via`):
- `role`: provenance: the kernel's history says which feature made the face. Tried first; follows parameter changes, features added earlier and a sketch written out again
- `definition`: worked out from the feature's own inputs; the second route, where the part has no provenance for the face
- `fingerprint`: an @ handle rebound by where and what it was, after its roles (kept with the handle) found nothing; the answer's note says so

Prefer references to what a feature made (`Extrusion1.end`,
`Hole1.wall[0]`, `Fillet1.face[0]`, `Extrusion1.end.edge(side(r.top))`).
The part remembers which feature made which face (the kernel's own
history of each operation is kept as roles, per body), so these find
their face again after any parameter change, after a feature is added
earlier in the tree, and after a sketch is written out again with a new
entity first (an entity or point that keeps its name keeps its id).
Use `@` handles for anything else; a handle also keeps the roles of the
face it was made on, and is followed by them first.

When a stored pick could only be followed by where it was (its roles no
longer name anything), build() and edit_feature() return it under
`warnings`: look at that face before you trust the result. Roles are not
kept for a body of more than 2500 faces (an import); those parts use
definitions and handles as before. A role names the faces that exist now:
a face a later feature cut away, or a hole that now lies outside the
plate, answers `NO_MATCH`, never another face.

## find_geometry()

`what`: face, edge or vertex. `where` keys (all must hold): `type` `normal` `along` `at` `near` `count` `largest` `smallest` `area` `length` `radius` `created_by` `on` `hole` `limit`.
Face types: `plane` `cylinder` `cone` `sphere` `torus` `bspline` `other`. Edge types: `line` `circle` `ellipse` `bspline` `other`.

```json
find_geometry(what="face", where={"type":"cylinder","hole":true})
find_geometry(what="edge", where={"on":"Extrusion1.end","type":"line"})
find_geometry(what="face", where={"created_by":"Boss","largest":true})
```

Each row has a handle and one line saying what it is. Use the handle in
build picks, measure(), requirements() and render_view(highlight=[...]).

## Picks inside build()

- Edges for fillet and chamfer: a query, stored and re-run on every
  rebuild, so it survives size changes. Keys: `along` `at` `kind` `near` `count` `min_length` `max_length`.
  `{"along":"z"}` (vertical edges), `{"at":"+z"}` (on the top),
  a list is a union, `"all"`. Or references (`"Extrusion1.end"` stands
  for the edges round that face).
- Faces for shell, thread, split, sketch planes: a reference, or
  `{"faces":{...}}` with keys `at` `normal` `kind` `near` `count` `largest` `min_area`. Face picks are captured once as
  references, so check them again after big changes.

Check a pick before you use it: render_view(highlight=["Hole1.wall"]) or
render_view(highlight_edges={"along":"z"}) draws it in orange.
measure() gives sizes of one reference or how two relate (gap, angle,
axis distance).
