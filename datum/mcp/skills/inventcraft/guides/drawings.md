# Drawings

A drawing (`.icdraw`) holds no geometry: it references a **saved** part or
assembly and shows lines generated from it (hidden line removal), cached
in the file, so it opens and prints without the model. Change the model
and the drawing follows: views whose model changed are drawn again by
drawing_render() and drawing_export(). The tools are the `+drawing` group,
which is **off by default**: start the server with `--tools +drawing`.

## The loop

1. Build the part, set its Part Number, description and material with
   properties(), and save_document() it. A drawing cannot show an unsaved
   part, and a part edited after saving must be saved again.
2. `drawing_create(source=<path or handle>, size="A3")`. It answers with
   the sheet's frame and title block rectangle, in sheet mm from the
   bottom left. `props={"Title":..., "Author":...}` fills the title block.
3. `drawing_base_view(orientation="front")`: the largest standard scale at
   which it, a view beside it and one below it fit clear of the title
   block, placed top left. Its answer has `box_mm` and `extent_mm`.
4. `drawing_projected_view(parent="View1", shows="top")` (below the base),
   `place="right"` (beside it) and `shows="iso"` for the corner. `place` says
   where it stands; `shows` says which view you want and the standard decides
   where it goes (ISO, first angle: the view of the left side stands on the
   RIGHT of the base). Read the answer's `looks`.
5. `drawing_section_view(parent=..., cut={"direction":"vertical","at":0})`,
   `drawing_detail_view(parent=..., centre=[x, y], radius=r)`.
6. `drawing_dimension(view=..., kind="overall")` (width and height), kind
   `diameter` for every round hole (`4x` for equal ones), `linear` between
   two points. `drawing_note(kind="hole_notes")` and `"centre_marks"` are
   automatic. For an assembly: `drawing_parts_list(balloons=true)`.
7. **drawing_render()** and look at it; model_tree() has every view's
   position and size as numbers, and warns of overlaps and overflow.
8. save_document(path=...) writes the .icdraw;
   `drawing_export(path=...pdf)` or `.dxf`, `.svg`, `.png`.

## Coordinates (all mm)

- On the **sheet**: a view's `at` is its centre from the bottom left corner.
- In a **view**: model mm at 1:1 whatever the scale, x right, y up, the
  origin the middle of the view's box. A point near a model corner snaps
  to it, and the dimension then follows the model.
- Sheets: A4 (297 x 210), A3 (420 x 297), A2 (594 x 420), A1 (841 x 594), A0 (1189 x 841), Letter (279.4 x 215.9), Legal (355.6 x 215.9), Tabloid (431.8 x 279.4), ANSI C (558.8 x 431.8), ANSI D (863.6 x 558.8), ANSI E (1117.6 x 863.6). Scales: 10:1, 5:1, 2:1, 1:1, 1:2, 1:5, 1:10, 1:20, 1:50, 1:100.

## Editing

Every call is atomic (a view that cannot be drawn is `VIEW_FAILED` and the
drawing is as it was) and one undo step in either host. Views are
named (`View1`, `Section1`), annotations and parts lists by `#id`
(model_tree() lists them): `edit_feature(feature="View2",
params={"x": 150, "y": 90, "scale": "1:2"})` moves or rescales it (what
stands on it moves too), `delete=true` removes it (`delete_dependents`
when views come from it), and `properties(props={"Revision": "B"})`
changes the title block's fields. A `dry_run` shows what would happen.

## Know

- Dimensions are anchored to model vertices and circles. If what one
  measured goes, it is marked `sick` in model_tree() and drawn red; it is
  not deleted.
- A drawing shows the part as saved, in the state it was saved in
  (ic://guide/model-states): save the part in the state you want drawn.
- Not yet: a model state per view, several sheets from the tools, broken
  and auxiliary views, GD&T symbols, revision tables, a flat pattern view
  of sheet metal. The app has them; ask the user, or edit_feature().
