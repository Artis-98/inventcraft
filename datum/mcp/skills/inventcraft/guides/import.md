# Import: a STEP back into a tree

A STEP file brings a body with no history. build() one op
`{"op":"import","path":"C:/parts/bracket.step"}` and the part is a **dumb
solid**: one feature, nothing to edit. Two tools turn it back into
features. Neither needs a window.

## recognize: read it, change nothing

    recognize()                      # the open part, its one body
    recognize(body="Imported Body")  # name a solid when there are several
    recognize(detail=true)           # also the ops it would build

It answers with a summary line, then:

- `features`: the base (the profile of an end face extruded along x, y or
  z, with its length), through and blind holes (simple, counterbore,
  countersink: diameter, depth, axis, count), identical holes or bosses as
  a `grid` (count and pitch) or a `circle` (count and radius), pockets,
  steps, bosses, and constant-radius fillets and chamfers.
- `parameters`: the names a rebuild would give them (`thickness` or
  `length`, `hole_d`, `pitch`, `hole_count`, `fillet_r`, `chamfer_d`, the
  profile's `x_size`, `y_step1`, ...), with their values.
- `coverage`: faces explained of all faces, and the same by area. It is
  counted on the **rebuilt** body: a face is explained when the tree
  recognise built has the same face, so it cannot flatter itself.
- `check`: volume of both, the **residual volume** (boolean difference
  both ways) and the box gap. A few thousandths of a mm3 is the STEP's own
  tolerance.
- `unexplained`: every face nothing reproduces, with why, its centre and an
  `@F:` handle for find_geometry() and measure().

## parametrize: write the tree, or refuse

    parametrize()                    # replaces the import with the tree
    parametrize(dry_run=true)        # the same checks, nothing changed
    parametrize(plan={"names": {"hole_d": "bolt_d"}})

It builds the recognised tree in a scratch document first and compares it
with the original (volume, box and the boolean difference both ways must
agree within `tolerance`, default 0.001 of the volume). Only then is the
import replaced, as **one undo step**, one revision.

**Partial coverage is refused.** If features are found but the tree is not
the body, the error is `PARTIAL_COVERAGE`, the part is untouched, and the
error carries the full report (what was explained, the residual, the faces
left over). It never keeps the import as a base with half a tree on top:
a tree that looks parametric and is not the part is worse than none.
Then rebuild by hand (find_geometry, measure, build), or give
`plan={"ops": [...]}` of your own, which is checked the same way.

## What it reads, and what it does not

- Reads: a prism (the end face's outline, lines, arcs and circles),
  axis-aligned holes, cylinders and flats between the ends, round and
  45 degree flat blends, patterns on a line, a grid or a circle.
- Does not: oblique holes, tapers and drafts, freeform surfaces, threads,
  variable fillets, a body with several solids (name one with body=).
  Drill points on blind holes are reported, not rebuilt.
- A fillet or chamfer is picked by a stored rule when one rule finds exactly
  its edges (`{"along":"z"}`), else by position; edit_feature can change it.

## After it works

The tree is ordinary: properties(parameters={"hole_d": 12}) or
edit_feature() change it and it rebuilds. Add requirements() that hold the
original's volume and box so later edits are measured against them.
