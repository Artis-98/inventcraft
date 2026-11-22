# Modelling workflow

InventCraft is a parametric, history-based modeller. What you build
becomes ordinary features in the part's tree, which a person can open
and edit. So build a design someone can change, not only the right shape.

## The loop

1. **Spec first.** Turn the request into named parameters, with units
   and a comment each (`{"op":"parameter","name":"w","value":120,
   "comment":"plate width"}`). Standard parts: write the table values
   down as parameters (a DIN 934 M10 nut: s = 17, m = 8).
2. **Say what done means.** requirements() with the sizes, mass, hole
   count or clearance the request implies. They stay in the part and
   every build reports them (`reqs 3/3 ✓`).
3. **build()** in a few calls, in the usual order: datum planes, the
   base body, the main cuts and bosses, holes, patterns, then fillets and
   chamfers last. Each call is one change, all or nothing.
4. **Read the summary line** before anything else: `+Sketch +Extrusion
   | V 48 200 mm³ (+12 000) | F 14 E 36 | 1 solid | reqs 3/3 ✓`.
   A cut whose volume change is 0 did nothing; 2 solids where you wanted
   one means something did not touch; a volume a thousand times off is a
   unit slip.
5. **inspect()** with `expected` (bbox, volume, solids, valid): numbers
   before pictures. A failed check is a finding, not noise: measure()
   the size that disagrees (two opposite faces) and fix the model or the
   expectation before you call it done.
6. **render_view()** to see the form: iso first, then the view that
   shows what you changed. `style="shaded"` is how it really looks (flat
   spots, colours, finish; `section`, `focus`); lines are for exact edges.
   `highlight` shows what a reference names,
   `highlight_edges` what an edge query picks, before you fillet them.
7. **Refine** with one-op builds, edit_feature(), or properties()
   (`parameters={"w": 160}`). Check a sketch with sketch_status().
8. **Prove it is parametric.** Change a main parameter by 20-50 % with
   properties(), check the build summary and requirements still pass,
   then put it back. A model that breaks here is a shape, not a design.
9. save_document() to an absolute `.icpart` path when the work should be
   kept; export() for STEP or STL.

## Habits that pay

- Size everything from parameters: `"w/2 - wall"`, never a hand-worked
  number. The build warns (`lint`) when one number keeps coming back.
- Name features (`"name":"Mounting holes"`) and use `id`s within a build:
  `"$s1"`, `"$e1.end"`.
- Pick geometry by rule or by definition, never by index
  (ic://guide/references).
- Try risky steps with `dry_run`, or snapshot() first and come back.
- After a failure the build was rolled back: fix that op and send the
  build again. Do not stack fixes on top (ic://guide/errors).
- read_ir() turns any part into build ops: a template for "one like
  that", and the way to see exactly what a part holds. diff() shows what
  changed since a revision or snapshot.

## When the user has InventCraft open

If they have allowed agents (Preferences > AI), status() shows
`gui_host.connected` and their documents have handles `g1`, `g2`...
(headless ones are `d1`...). They watch each change land and undo it with
Ctrl+Z (one build, one step). Say what you are about to do. `USER_BUSY`
means they are in a sketch or dialog on that document: wait for them.
`CANCELLED` means they pressed Stop: ask before trying again. A `code` op
shows them the source and waits for their answer (`waiting_for_trust` if
they say no). run_script still works on their documents; it runs in a
separate process and arrives as ordinary ops. You cannot close their
documents.

"Fillet this", "make that hole bigger": get_selection() gives what they
have picked as references (`Extrude.end`, `Extrude.end.edge(side(#e3))`,
else an `@F`/`@E` handle), features picked in the tree, sketch entities,
occurrences; `count` 1 means the reference names exactly the pick. Pass
them straight to build, e.g. `{"op":"fillet","radius":2,"edges":[...]}`.
ic://selection, ic://documents and ic://doc/{id}/tree can be subscribed
to: an update means "read it again". A file open in the app is edited
there whatever you name it by (its path or its `g` handle), and a headless
document is never saved over it (`FILE_OPEN_IN_APP`). If they edited since
you read, the change is refused as `STALE_REVISION` with `changes` saying
which features and parameters moved: read again, then redo it.

Files, limits and what in a file is data: ic://guide/safety.

Other guides: ic://guide/sketches, ic://guide/references, ic://guide/units, ic://guide/requirements, ic://guide/scripts, ic://guide/sheet-metal, ic://guide/frames, ic://guide/skeleton, ic://guide/assemblies, ic://guide/drawings, ic://guide/model-states, ic://guide/branches, ic://guide/explore, ic://guide/import, ic://guide/safety, ic://guide/errors.
