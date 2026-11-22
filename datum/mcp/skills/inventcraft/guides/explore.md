# Explore: evaluate and optimise

Two tools that try designs **without changing the one you hold**. Each
variant is built in isolation on the geometry worker pool, as in-memory
document data (no files, no change to the open part: its revision, undo
stack and file stay as they were).

## evaluate: a table of variants

    evaluate(variations=[{"t": 4}, {"t": 6, "w": "w*1.2"}, {"state": "M6x40"}])
    evaluate(grid={"t": [3, 4, 6], "w": {"from": 60, "to": 100, "steps": 3}})

- A variation is a dict of **user parameter** values (numbers in mm or
  degrees, or expressions over the other parameters), with optional
  `"state"` (a model state) and `"name"` (a label). A grid dict tries every
  combination. At most 200 variants; row 0 is the part as it is
  (`baseline=false` leaves it out).
- Each row: mass, volume, bbox, face count, whether the solid is valid, and
  every requirement the part stores (`reqs 4/5` and what fails). `metrics`
  chooses (volume, mass, area, bbox, faces, solids, valid, requirements,
  params). `clearances={"gap": {"a": ref, "b": ref}}` adds the least
  distance between two references as a column.
- A variant that does not build is a **row with its error**, not a failed
  call (a thickness larger than the part, a hole off the plate). A variant
  naming a parameter that does not exist is a row too.
- `detail=true` returns every row with each requirement's value, and the
  parameters of each variant.
- Variants run on at most as many workers as the machine can carry (a core is left for
  the app; a worker is about 230 MB, so memory counts): the answer says how
  many were used. The call reports progress, and can be cancelled between
  variants; what was built is returned.

## optimise: the best design that clears every requirement

    optimise(vary={"t": [3, 12], "w": [60, 140]}, objective="min mass",
             budget=40)

- `vary`: each parameter as `[lo, hi]` (continuous), a list of three or
  more values (discrete), or `{"min":, "max":, "step":}`. Numbers only.
- `objective`: `min mass` (default), `min volume`, `max volume`, `min area`,
  `min faces`, `min bbox.x|y|z`, `min bbox_volume`, `min|max req:<name>`
  (what a requirement measures, say a clearance) or `min|max param:<name>`.
- `subject_to`: by default every enabled stored requirement must pass. Names
  enforce only those; requirement objects (the format of `requirements`,
  refs as strings) add some for this search only.
- `budget` (4 to 200, default 40) counts every evaluation. The search is a
  coarse grid over the space, then a compass search from the best point:
  steps of the grid spacing, halved when nothing improves, with a combined
  move along every axis that helped. Each round is one parallel batch. It
  finds a good design near the limits, not a proof of the optimum: run it
  again over a narrower range for more.
- The answer: `best` (values and the objective against the start), the
  table explored (best first), `failed_by` (how many designs failed each
  requirement: if one fails everywhere, it is too tight or the range is
  wrong). With **no feasible design** it says so, and `closest` is the one
  that misses by least.
- It **never changes the part** unless `apply=true`: then the best values
  are written as ONE undo step. `branch="lighter"` does it on a new branch
  (the part must be saved) and checks it in, so you can
  `diff(before="branch:main", after="branch:lighter")`, switch to main and
  merge, or discard. If `apply` finds nothing feasible it changes nothing.

## Know

- What varies is a user parameter. A dimension inside a sketch or a
  feature is not (name it a parameter first: properties() or build()
  `parameter`), and a change of form is a build() job, not a search.
- Requirements are the contract: add them first (guide requirements). A
  design that clears nothing you wrote down is not "best".
- A clearance to a face keeps working as the part changes because the
  reference is a stored fingerprint (guide references); if a variant moves
  the face away the row says the requirement cannot be measured.
- In the app the badge shows "evaluate 12/40" and Stop ends the search at
  the next variant.
