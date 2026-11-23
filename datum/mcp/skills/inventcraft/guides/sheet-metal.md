# Sheet metal

Sheet-metal features read the sheet's thickness and bend radius from the
parameters **`Thickness`** and **`BendRadius`** (each feature's
`thickness` and `bend_radius` fields default to those names). Define
both first, in the same build, or the first sheet feature fails.

| op | what it makes |
|---|---|
| `sheet_face` | Sheet metal's Face: a closed profile given the sheet's thickness. |
| `flange` | Sheet metal's Flange, as Inventor makes one: a bend up from each picked edge and a wall to a height. |
| `hem` | Inventor's Hem: the edge of the sheet folded back over its face. |
| `fold` | Inventor's Fold: the sheet bent along a line sketched on its face, the line the bend's centre, so the flat pattern is the sheet as it was. |
| `contour_flange` | Inventor's Contour Flange: an open path of lines, the inside of the sheet, given the thickness, bent at its corners at the bend radius and run a width along its sketch's normal. |
| `corner_seam` | Inventor's Corner Seam: two flanges made apart, closed at the corner they share as one Flange on both edges would have it. |

A box open at the top, 200 x 120 x 60 in 1.5 mm sheet:

```json
[{"op":"parameter","name":"Thickness","value":1.5},
 {"op":"parameter","name":"BendRadius","value":1.5},
 {"op":"parameter","name":"L","value":200},
 {"op":"parameter","name":"W","value":120},
 {"op":"parameter","name":"H","value":60},
 {"op":"sketch","id":"s","plane":"XY","name":"Base","entities":[
   {"rect":{"center":[0,0],"size":["L","W"]}}]},
 {"op":"sheet_face","id":"base","sketch":"$s","name":"Base"},
 {"op":"flange","name":"Walls","height":"H",
  "edges":{"edges":{"at":"+z","kind":"line"}}}]
```

- `flange` `edges` takes an edge query inside `{"edges": ...}`, a face
  query inside `{"faces": ...}`, or references; the walls rise from the
  picked edges of the sheet's top face. `height` is the outside height.
- `contour_flange` bends an open path of lines (sketch it as a polyline,
  not closed) at its corners and runs it `width` along the sketch's
  normal: the quick route to a U or Z channel.
- `corner_seam` closes the corner between two flanges made apart.
- Check the result like any part: the bbox should be L x W x H, and the
  volume about the sheet area times Thickness.

## Rules, flat pattern, check (`--tools +sheetmetal`)

- `sheet_rules()` reads the part's sheet rules: thickness, bend radius,
  **K-factor** (0 to 1; 0.3 to 0.5 for steel and aluminium, default 0.44)
  and corner gap. With arguments (`sheet_rules(k_factor=0.4)`) it sets them
  and converts the part to sheet metal; the K-factor is kept in the file.
- `flat_pattern()` lays the part flat: the flat's size, area, blank mass
  and the **bend list** (angle, inside radius, bend line length, bend
  allowance, toward the front or away, and the line on the flat). A `path`
  ending in `.dxf` also writes it for cutting: outline and holes on layer
  OUTER_PROFILE, bend centre lines on BEND_CENTERLINE. `k_factor` tries
  another value without changing the part. A shape that cannot unfold
  (sharp corner, no relief) is `FLAT_FAILED` with the reason.
- `sheet_check()` judges it: a bend radius under 0.5 t is an error (under
  1 t a note), a K-factor outside 0.25 to 0.5 a warning, a flange under
  4 t outside (the leg after the bend under 2 t) an error, a hole closer
  than 2 t to a bend a warning, and a part that does not unfold is an error
  (corner relief at least t wide and t + r deep: flanges that meet relieve
  themselves, otherwise add a `corner_seam`). The answer quotes the rules.
- Order: set the rules, build, `sheet_check()`, fix what it finds,
  `flat_pattern(path=...)`, compare the flat's size with the blank you can
  cut. A flat size that moves when the K-factor does is expected: the bend
  allowance is the only part that depends on it.
