# InventCraft standard parts library

Bolts, screws, nuts, washers, pins, retaining rings, bearings and steel
profiles, one CSV file per family. InventCraft's Place from Library and
Frame Generator read them, and the folder stands on its own: any program
can use it.

## The files

```
fasteners/   bolts, screws, nuts, washers, pins, retaining rings, rods
bearings/    ball bearings
profiles/    steel shapes and copper tube for the Frame Generator
LICENSES/    the licences the sources are under
```

Each file starts with a few `# key: value` lines, then a header and one
row per size:

```
# id: iso-4762
# name: Socket Head Cap Screw
# standard: ISO 4762
# category: Fasteners/Bolts/Socket Head
# kind: socket_head
# drive: hex
# source: FreeCAD Fasteners Workbench, FsData table ISO4762def
# licence: LGPL-2.1-or-later
# lengths: 2.5 3 4 5 6 8 10 12 ...
size,d,dk,k,s,t,lmin,lmax
M8,8,13,8,6.06,4,10,80
```

All sizes are millimetres, inch parts included. `kind` says how the part
is drawn and which columns it has; `lmin` and `lmax`, where present, are
the shortest and longest standard length of that size.

| kind | columns |
| --- | --- |
| hex_bolt, square_bolt | d, s across flats, k head; dc, c for a flange |
| socket_head, cheese | d, dk head, k head, s and t the drive |
| dome, pan | d, dk, k, s, t; dc, c for a collar |
| countersunk | d, dk, k, s, t, angle |
| shoulder | d thread, d1 shoulder, dk, k, lt thread length, s, t |
| set_screw | d, s, t, point (0 flat, 1 cone, 2 dog, 3 cup) |
| nut | d, s, m; dc, c for a flange |
| lock_nut | d, s, m hex, h overall, dw collar |
| cap_nut | d, s, m, h, dk |
| square_nut | d, s, m |
| washer | d1 inside, d2 outside, h |
| pin, rod | d (c chamfer) |
| taper_pin | d small end, 1:50 |
| spring_pin | d, s wall |
| headed_pin | d, dk, k |
| ring_external, ring_internal | d groove, d3 free, a, b, s |
| bearing | d bore, D outside, B width |
| pipe | d outside, t wall, r a bend radius to start from |

The drive is `hex` (s across flats), `torx` (s across the points),
`slot` (s the width) or `cross` (s across the arms); t is its depth.

## Where the numbers come from

Every number is a dimension of a published standard. They were taken
from open sources, never from a commercial CAD program's library, and
each file says which:

* **FreeCAD Fasteners Workbench** by shaise and its contributors,
  <https://github.com/shaise/FreeCAD_FastenersWB>, commit `375a73d`,
  LGPL-2.1-or-later. The fastener tables, reshaped into the columns
  above.
* **cq_warehouse** by Gumyr, <https://github.com/gumyr/cq_warehouse>,
  commit `a57bb7a`, Apache-2.0. Ball bearing bore, outside diameter and
  width only.
* **FreeCAD BIM profiles** (`src/Mod/BIM/Presets/profiles.csv`),
  <https://github.com/FreeCAD/FreeCAD>, commit `e2558b1`,
  LGPL-2.1-or-later. The profiles' sizes and thicknesses; the root radii
  were added from EN 10365, DIN 1025-1 and BS 4-1.
* **Typed in from the standards** (UPN channels from DIN 1026-1, the
  flat and round bar size ranges of EN 10058 and EN 10060, copper
  tube to EN 12735-1 and ASTM B280): plain
  dimensions, given away as CC0-1.0.

The files under LGPL-2.1-or-later stay under it, changed or not: anyone
may use, copy and change them, and a changed copy handed on is under the
same licence. The full texts are in `LICENSES/`.

## Rebuilding it

```
python tools/stdlib/build.py <FreeCAD_FastenersWB> <cq_warehouse> <profiles.csv>
```

with the three sources checked out at the commits above. It writes this
folder again from them.
