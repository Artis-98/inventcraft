# Frames and weldments

A frame is members of a library profile along the lines of a **skeleton**
(sketches in a part, see ic://guide/skeleton), with end treatments and a
cut list. `--tools +frames`:

1. Build and save the skeleton part, a new assembly, save it, and
   `place_component()` the skeleton.
2. `frame_profiles()` lists families; `frame_profiles(family=...)` its sizes.
3. `frame_insert(skeleton="Skeleton", sketch="Top Frame",
   profile="din-en-10219-2-square", size="30 x 30 x 2")` makes one member
   part per line in `<assembly>/Frame0001/` and places the frame in the
   assembly following the skeleton. Another sketch goes into the same
   frame with `frame="Frame0001:1"`. The answer lists each member (id,
   ends, length). `lines` picks lines by id, `anchor`, `offset_a/b` and
   `rotate` place the profile on the line, `merge` joins lines that run
   straight on.
4. `frame_treat(frame="Frame0001:1", kind="miter", corners=true,
   sketch="Top Frame")` mitres every corner of that sketch;
   `members=[a, b]` two named members. Also `corner` (butt joint),
   `trim_face`, `notch` and `lengthen`; `remove=true` undoes them. They
   are kept in the frame and made again when the skeleton changes.
5. `cut_list()`: pieces grouped by profile, cut length (mitres included),
   the angle each end is away from square, quantity, mass; `path` writes a
   .csv for the saw.

A member is a part like any other (its Length property is the cut
length), so `bom()` lists each one. Check with `assembly_check()`; mitred
frames should show no interference.

## Profile families

| family | kind | columns | sizes |
|---|---|---|---|
| `din-en-10056-1-equal` | angle | b, t, r1, r2 | L20x20x3, L25x25x3, L25x25x4, L30x30x3, ... |
| `din-en-10219-2-square` | square_tube | b, t, ro | 20 x 20 x 2, 25 x 25 x 2, 25 x 25 x 2.5, 25 x 25 x 3, ... |
| `alu-c-channel` | channel | h, b, tw, tf, r, slope, r2 | 2x1 Channel, 2x1.25 Channel, 3x1.5 Channel, 3x1.75 Channel, ... |
| `astm-a6-w` | i_beam | h, b, tw, tf, r, slope, r2 | W 4x13, W 5x16, W 5x19, W 6x9, ... |
| `astm-b280-coil` | pipe | d, t, r | 1/8 in, 3/16 in, 1/4 in, 5/16 in, ... |
| `astm-b280-drawn` | pipe | d, t, r | 3/8 in, 1/2 in, 5/8 in, 3/4 in, ... |
| `bs-4-1-ub` | i_beam | h, b, tw, tf, r, slope, r2 | UB 127x76x13, UB 152x89x16, UB 178x102x19, UB 203x102x23, ... |
| `bs-4-1-uc` | i_beam | h, b, tw, tf, r, slope, r2 | UC 152x152x23, UC 152x152x30, UC 152x152x37, UC 203x203x46, ... |
| `din-1026-1-upn` | channel | h, b, tw, tf, r, slope, r2 | UPN 50, UPN 65, UPN 80, UPN 100, ... |
| `en-10058-flat` | flat_bar | b, t, r | FL 10x3, FL 10x4, FL 10x5, FL 10x6, ... |
| `en-10060-round` | round_bar | d | RD 6, RD 8, RD 10, RD 12, ... |
| `en-10219-chs` | round_tube | d, t | CHS21.3x2.6, CHS21.3x2.9, CHS21.3x3.2, CHS26.9x2.6, ... |
| `en-10219-rhs` | rect_tube | h, b, t, ro | RHS50x30x2.9, RHS50x30x3, RHS50x30x3.2, RHS50x30x3.6, ... |
| `en-10305-4-hydraulic` | pipe | d, t, r | 6x1, 8x1, 8x1.5, 10x1, ... |
| `en-10365-hea` | i_beam | h, b, tw, tf, r, slope, r2 | HEA 100, HEA 120, HEA 140, HEA 160, ... |
| `en-10365-heb` | i_beam | h, b, tw, tf, r, slope, r2 | HEB 100, HEB 120, HEB 140, HEB 160, ... |
| `en-10365-hem` | i_beam | h, b, tw, tf, r, slope, r2 | HEM 160, HEM 180, HEM 200, HEM 220, ... |
| `en-10365-ipe` | i_beam | h, b, tw, tf, r, slope, r2 | IPE 100, IPE 120, IPE 140, IPE 160, ... |
| `en-10365-ipn` | i_beam | h, b, tw, tf, r, slope, r2 | IPN 80, IPN 100, IPN 120, IPN 140, ... |
| `en-10365-upe` | channel | h, b, tw, tf, r, slope, r2 | UPE 80, UPE 100, UPE 120, UPE 140, ... |
| `en-12735-1-copper` | pipe | d, t, r | 6x1, 8x1, 10x1, 12x1, ... |
| `is-4923-rhs` | rect_tube | h, b, t, ro | RHS50x25x2.9, RHS50x25x3.2, RHS60x40x2.9, RHS66x33x2.9, ... |
| `is-4923-shs` | rect_tube | h, b, t, ro | SHS25x25x2.6, SHS25x25x3.2, SHS30x30x2.6, SHS30x30x3.2, ... |
| `is-808-angle` | unequal_angle | a, b, t, r1, r2 | ISA20x20x3, ISA20x20x4, ISA25x25x3, ISA25x25x4, ... |
| `is-808-beam` | i_beam | h, b, tw, tf, r, slope, r2 | ISHB 150(1), ISHB 150(2), ISHB 150(3), ISHB 200(1), ... |
| `is-808-channel` | channel | h, b, tw, tf, r, slope, r2 | ISJC 100, ISJC 125, ISJC 150, ISJC 175, ... |
| `is-808-tee` | tee | h, b, tw, tf, r, r2 | ISNT 20, ISNT 30, ISNT 40, ISNT 50, ... |

Inside one part, without a skeleton, there are two older routes:
`{"op":"frame_member","family":"din-en-10219-2-square","size":"40 x 40 x 3",
"length":"L"}` is one member's solid, and a `code` feature can union
profile solids along lines and follow its parameters (ic://guide/scripts).
Not there: pipes (the app has the pipe cut list), notch and corner
joints are less checked than mitres.
