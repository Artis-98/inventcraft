# InventCraft Walking Excavator

A four-wheel walking excavator built entirely from native InventCraft parts and assemblies. It is a demonstration of what the program does: fabricated plate weldments, press-braked sheet metal that unfolds, a cab frame made by the Frame Generator, bent hydraulic tubes, turned pins and cylinders, an icLogic rule that drives every joint, and ray-traced renders.

About 10 t as modelled: 180 distinct parts, 495 placed.

## Open and move it

Open **Walking Excavator.icasm**. Allow the document when InventCraft asks, because its icLogic rule places every moving part.

In the **icLogic** panel, run **Leg controls FL**, **FR**, **RL** or **RR**, or **Boom and chassis controls**. Each opens a form of sliders. The model follows while you drag, OK keeps the pose and Cancel puts it back. Save the assembly to keep a pose.

| Control | Range | Moves |
|---|---|---|
| Leg spread | 30 to 62 deg | hip bracket about its vertical swivel pin (spread cylinder) |
| Leg lift | -8 to 58 deg | the leg's parallelogram, wheel kept parallel to the chassis (lift cylinder between the two bones) |
| Wheel steering | -14 to 14 deg | knuckle about its kingpin inside the rim (a small steering cylinder on the kingpin's arm) |
| Boom, dipper, bucket | 10 to 65, -120 to -35, -30 to 100 deg | arm, with the bucket's four-bar linkage closed by circles |
| Slew | full turn | upper carriage on the slew bearing |
| Attachment tilt and rotation | 35 deg either way, full turn | tiltrotator |
| Chassis height and pitch, wheel spin | | the rest of the pose |

**poses/** holds six saved poses: Level, Transport, Reach, Spider, Heels and Hero. The main assembly opens in Hero. Every pose stands on its lowest wheel.

## How it is built

The joints all come from one skeleton, **walking_excavator/motion.py**, which is plain math. The same source is embedded in the assembly as its icLogic rule, so the build scripts and the open document always agree on where everything goes.

- **Legs** are parallelograms, as on a Menzi Muck. A big lower bone and a slimmer upper bone are both pinned to a tall hip bracket and to the wheel carrier, so the wheel stays parallel to the chassis at every lift. The lift cylinder lies between the two bones and uses nearly its whole stroke over the lift range.
- **Box beams** (both leg bones, boom and dipper) use two laser-cut webs with rounded profiles. Their caps are Contour Flanges bent along the web's edge line, with the web's corners rounded to the radius the cap's outer face takes there, so each box closes flush. Turned bosses pass through the webs at the pins. The boom's and dipper's tips are forks, their caps stopping at a closure plate.
- **Sheet metal that unfolds**: the bent chassis walls (four bends each), engine hood, radiator cowl, bucket (two 20 mm side plates and one 12 mm wrap rolled round two 200 mm radii, with a lip bar, side cutters, wear strips and teeth) and flanged cab roof. Every bent part's flat pattern is a DXF in **flat-patterns/**.
- **Frame Generator**: the cab is a real frame assembly made from **Cab frame skeleton**. It has 80 x 80 x 4 RHS pillars and rails butt-jointed at the pillar faces, a roof rail in EN 10305-4 tube bent through two corners, and CHS posts. Edit the skeleton and the frame follows. The glazing sits in the openings in rubber seals, each pane 8 mm.
- **Hydraulics**: fifteen cylinders whose closed length and stroke are worked out from the spans the skeleton actually reaches over the control ranges. Rigid tubes on the boom and legs are Pipe Run parts on saddles and clamps. The cut list is in **rigid-tube-cut-list.csv**.
- **Wheels** are held from one side, as on a Menzi Muck. Each leg runs straight into the middle of its wheel, and the steering knuckle, hub motor and spindle sit inside the rim's deep dish. The tyres are 1400 x 650 balloon tyres with 16 big rounded lugs a side, and every wheel sits outboard of its leg.
- **Turned parts** are revolved half sections with their chamfers drawn in. These include the pins with retaining heads, bushes, glands, the hub, the rim and the tyre carcass. The tyre's 32 lugs are one circular pattern.

Hoses across moving joints are left out on purpose; the ports and bulkheads show where they connect.

## Checked

- **Clashes**: `interference.py` flattens the machine to its parts in world space and intersects every pair whose boxes overlap. It runs in all six poses and at both ends of every control. No two parts share more than 1 mm³; welds, pins in bores and nuts on studs touch but do not overlap. The results are in **interference.json**.
- **Controls**: `verify_controls.py` drives each icLogic form in the running program. It moves every slider, checks the model against the skeleton while the form is open, checks that Cancel restores the pose and that OK keeps it, and times each move. It also checks that every joint stays on its pin and every cylinder stays inside its stroke across every slider's range. The results are in **controls-validation.json**.
- **Parts**: `validate.py` reopens every part and checks that it rebuilds to a valid solid. It also writes **bom.csv**, the flat patterns and **validation.json**.

These checks cover geometry only. Structural, fatigue, hydraulic sizing, stability and regulatory work has not been done; the model is not a fabrication release.

## Regenerate

From the repository root:

    .venv/Scripts/python.exe examples/build_walking_excavator.py
    .venv/Scripts/python.exe -m examples.walking_excavator.interference Level Transport Reach Spider Heels Hero --sweep
    .venv/Scripts/python.exe -m examples.walking_excavator.verify_controls
    .venv/Scripts/python.exe -m examples.walking_excavator.validate
    .venv/Scripts/python.exe -m examples.walking_excavator.render --width 3840
    .venv/Scripts/python.exe -m examples.walking_excavator.render_poses

**renders/poses/** has every pose from five angles at 3840 x 2160. The renders in **renders/** come from InventCraft's own ray tracer (View > Render). **renders/render-report.json** records how each one was made.
