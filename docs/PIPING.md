# Piping

Requirements from Panagiotis Psomas, Ref-Technogenetiki (refrigeration
equipment maker, Northern Greece), mail of 2026-11-18. They move from
SketchUp and paper. Piping builds on the Frame Generator: route drawn as a
sketch, tube placed along the picked lines.

## Promised for this week's update (mail of 2026-11-18)

* Copper tube sizes
* Proper bends at sketch corners
* Continuous runs merged into one pipe
* Insulation

## What they asked for

1. **Tube standards:** both metric copper to EN 12735 and ACR (inch) sizes.
2. **Fittings:** 90 and 45 degree elbows, tees and branches, reducers,
   couplings and unions, return bends. Bends with a configurable bend
   radius, not sharp corners. Automatic fitting placement at route
   intersections and connection points.
3. **Insulation:** a parametric property of the pipe, thickness and
   material (elastomeric such as ArmaFlex), following the pipe through
   bends and fittings.
4. **Outputs:** total length per diameter, individual cut lengths, a BOM
   including fittings that tells sizes and materials apart, drawings.

Their view: a flexible piping engine would serve plumbing, process piping
and pumping stations too, not only refrigeration. A screenshot of a
typical system is coming from them.

## Split

**This week:** EN 12735 and ACR size tables, bend radius per run, merged
runs, insulation as a pipe property (thickness, material) that follows the
bends, cut lengths and total length per diameter in the BOM.

**Later:** fitting library (elbows, tees, reducers, couplings, unions,
return bends), automatic fittings at intersections and ends, fittings in
the BOM, piping drawings.

## Built (2026-11-18, card #339)

* **Sizes:** `datum/stdlib/profiles/en-12735-1-copper.csv` (metric
  stock sizes), `astm-b280-coil.csv` and `astm-b280-drawn.csv` (ACR
  inch). Kind `pipe`, columns d, t, r; r is a starting bend radius of
  3.5 x d, overridden per run.
* **Insert Pipe** (Design tab, Pipe panel): Insert Frame set to copper.
  Picked lines meeting end to end become one run; a point where three
  meet ends the runs there (a tee goes there later). Bend radius per
  run, 0 meaning the size's own.
* **The part:** one Pipe Run feature (`PipeRunFeature`), the route and
  section kept in it, a ring swept along straights and tangent arcs.
  Properties: Description, Stock Number, Length (developed), Bends, Bend
  Radius. Copper unless a material is picked.
* **Insulation:** thickness and material on the run (Elastomeric Foam by
  default). A part of its own beside the tube, swept along the same path,
  so it follows the bends and shows in the BOM as its own line.
* **Cut List** (Pipe panel): every pipe's cut length, bends, straights
  and insulation, totals per size and per insulation thickness, export
  to CSV.
* A leg too short for the bends at its ends is refused with the length
  it needs. End treatments skip pipes.
* Code: `datum/core/piping.py` (runs, bends, solids, cut list),
  `datum/core/piping_parts.py` (writing the parts); tests
  `tests/test_piping.py`, `tests/test_piping_ui.py`.

* Runs go through any of the skeleton's sketches: lines joined end to
  end in different sketches and planes are one route, kept on the member
  as [sketch, line] pairs (`Member.segments`).
* **Merge into one pipe** (ticked by default, offered only once the
  picked lines join up): ticked, a connected run is one bent part;
  unticked, one straight pipe per line.

Known limit: a pipe is picked in the view by its longest leg.

## Fittings and corners (2026-11-18, card #340)

* **Automatic fittings** where separate pipes meet
  (`datum/core/piping_fittings.py`): two at 90 or 45 degrees an elbow,
  two in line a coupling or a reducer, three (two in line, one square) a
  tee or reducing tee. Anything else is reported, not guessed.
* Each pipe is cut back to its socket bottom, so Length and the cut list
  are what to cut. The cut list counts the fittings.
* One part per fitting kind and size (`PipeFittingFeature`), placed as
  often as needed so the BOM counts them; kept on the frame as
  `FrameDefinition.fittings` ({key, part, occurrence}).
* Sizes: `datum/stdlib/fittings/en-1254-1-solder.csv`. Socket depth L is
  EN 1254-1's capillary length; wall, elbow radius, tee and coupling lay
  lengths are typical, to check against the maker. Sizes between table
  rows (ACR inch tube) are read off between them.
* **Pipe Corners** (Pipe panel) turns piping mode on and off (Esc ends
  it): a small chip beside every switchable corner in the view, a bend or
  elbow icon and an arrow, its menu Bend or Elbow fitting
  (`datum/ui/pipe_corners_ui.py`, `datum/core/pipe_corners.py`). The
  chips are frameless tool windows kept over their corners, since Qt
  cannot paint on the OCCT view. Elbow splits the pipe there, Bend joins
  the two pipes again.
* **Miter every corner** (Miter window, on by default): of the picked
  members, each two that meet end to end are mitered, so a hexagon's six
  sides give all six corners at once (`frames.meeting_pairs`).

Not yet: unions, return bends and caps; insulation round the fittings;
reducing elbows.
