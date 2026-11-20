# InventCraft walking excavator — agent build prompt

Build InventCraft's flagship demonstration assembly, an original four-wheel walking spider excavator with manufacturing-level detail, editable native parts, functioning articulation, sketch-driven rigid hydraulic pipes, and polished native renders.

Work in C:/Users/aa/Downloads/CLAUDE/datum. Follow applicable repository instructions. Build the machine under examples/walking-excavator/, with a reproducible entry point examples/build_walking_excavator.py. Preserve the existing tracked excavator example and unrelated application work.

## Intent and design direction

The machine belongs to the same category as a Menzi Muck walking excavator. Develop an original design with four independently articulated wheel legs, a rotating upper carriage, glazed cab, fabricated boom and dipper, hydraulic bucket linkage, and compact tiltrotator. Aim for the visual credibility of a professional manufacturer's CAD assembly.

Use midnight navy sheet-metal body panels, restrained warm gold identification panels, graphite structure, black rubber, polished piston rods, and machined steel details. Apply the colors through InventCraft materials and appearances.

The companion concept image establishes the visual direction. CAD geometry, mechanisms, clearances, and the four-wheel count govern the build when the concept image is ambiguous. Resolve proportions into a coherent dimensioned design before producing detail.

This is a manufacturing-detailed CAD demonstration. Record unverified structural, fatigue, hydraulic, stability, and regulatory assumptions. Any fabrication-readiness claim must be supported by engineering review.

## Inspect the current implementation first

These existing sources are starting points. Verify their current interfaces before calling them.

- examples/build_excavator.py, examples/excavator/README.md, tests/test_excavator.py, and tests/shot_excavator.py demonstrate native documents, appearances, pins, barrel/rod placement, and pose-derived attachment coordinates. Reuse the approach and correct its simplifications.
- datum/core/document.py, features.py, sketch.py, and kernel.py provide the part and sketch feature model. Prefer named native sketches and features for manufactured components.
- datum/core/assembly.py and constraints3d.py provide placements, references, and assembly solving.
- datum/core/features.py contains SheetFaceFeature, FlangeFeature, FoldFeature, ContourFlangeFeature, CornerSeamFeature, PipeRunFeature, PipeFittingFeature, and ThreadFeature.
- datum/core/sheetmetal.py provides thickness, inside bend radius, K-factor, and flat-pattern support.
- datum/core/frames.py, piping.py, piping_parts.py, piping_fittings.py, and pipe_corners.py provide skeleton-driven piping, stock sizes, bend routing, fittings, and pipe cut lists. PipeRunFeature retains its route points, outside diameter, wall, and bend radius.
- datum/core/materials.py provides separate material and appearance libraries, including Glass, Clear and polished steel. Check actual entries before choosing them.
- datum/ui/render_ui.py and viewport.py::render_image provide native rendering, transparency, shadows, reflections, and output up to 3840×2160.
- The beaver identity reference is datum/ui/brand/inventcraft-512.png. Inspect it. The older datum-mark.svg is a different mark.

Use the application's real feature and document paths so files open, rebuild, edit, save, close, and reopen in InventCraft. Reuse existing helpers where they preserve the requested behavior. Limit application changes to specific gaps discovered during the build, and explain necessary changes.

## 1. Layout and dimensions

Set Z up, +X forward, +Y left. Use millimeters. Start with a compact approximately 8-tonne-class visual envelope, a cab roof roughly 2.8–3.1 m above the transport ground plane, approximately 2.4–2.7 m transport width, 1.0–1.2 m diameter tires, and 5.5–6.5 m maximum working reach. These are initial design targets. Derive final dimensions together and publish the actual envelope, calculated mass, travel ranges, and assumed operating pressure.

Create a master skeleton containing actual joint centers, wheel contact references, cylinder mounting points, boom/dipper pivots, bucket-link pivots, and hydraulic connection interfaces. Place components from those references and derived local coordinate systems. Shared hole centers, bearing axes, and mating surfaces must agree numerically.

Create named native subassemblies for chassis, four leg modules, upper carriage, cab, power pack, boom, dipper, tiltrotator/bucket, guards, and hydraulics. Give repeated parts shared files and meaningful occurrence names.

## 2. Four wheel legs and steering

Provide exactly four wheel-leg modules attached to the chassis. Each needs a credible arrangement for lateral spread, vertical terrain adjustment, wheel steering, and wheel rotation. Clearly distinguish joint axes. Use paired lugs, a tongue or bearing between them, real pins, bearing clearance, thrust washers, pin retainers, and accessible lubrication points.

Use fabricated hollow plate structures with local reinforcements around pin bores. Provide hydraulic barrels, rods, glands, end eyes, clevises, ports, and connection fittings. Derive barrel and rod placement from mount-to-mount distances, and calculate extension against the declared stroke.

Each of the four tires is a separate editable part with modeled deep chevron tread, staggered shoulder blocks, sidewall thickness, bead regions, and rounded rubber transitions. Include metal rim, hub, lug pattern, valve stem, and credible sidewall or hub protection. Guards must allow wheel steering, leg travel, and tire rotation.

Model foot/stabilizer geometry only where it has a defined mounting and deployable clearance. Maintain four primary wheels and avoid decorative supports that intersect them.

## 3. Upper carriage and cab

Include a slew ring with bolted interfaces, central hydraulic distribution, chassis covers, and access to the upper carriage. Show a believable power-pack envelope, radiator grille, hydraulic reservoir, manifolds, filler caps, and service doors behind the covers.

Make the cab a distinct framed assembly. Model individual transparent glazing panels with thickness, seals, frames, door hinges, latch, and handles. The seat, joysticks, pedals, dashboard, protective roof, floor, steps, handrails, side mirror, and working lights must be visible in useful views.

Include a windshield wiper with motor/pivot mount, arm, blade, and swept-area relationship to the front glass. Add door/window catches, gas struts where needed, and plausible weather seals. Handle small details by shared subassemblies and patterns so the assembly stays responsive.

Use clear glazing at sufficient opacity to reveal the interior without losing reflected edges. Validate it in the native renderer.

## 4. Fabricated boom, dipper, and bucket

Build the boom and dipper as hollow welded plate fabrications with separate side webs, cap plates, internal diaphragms where needed, end bosses, weld preparation, and local pin-bearing reinforcement. Use real sheet thickness and bends where the part would be press-braked. Keep welded plate assemblies as separate constituent parts with useful flat profiles.

Use machined solid modeling for pivot bosses, bushes, pin retainers, manifolds, glands, wheel hubs, and other genuinely machined components. Give those parts realistic bores, shoulders, small chamfers, and tool-accessible radii.

Show structural weld seams where they explain assembly. Include finite plate thickness, seam spacing, and clearance for welding and pin insertion. Use selective modeled weld geometry and lightweight representation for repeated small seams.

Drive the boom, dipper, bucket curl, and tiltrotator from coherent pivots and mechanical parameters. Include the actual bucket four-bar linkage with fixed link lengths, bucket inward-facing opening, side plates, curved back, cutting edge, wear strips, replaceable teeth, and quick-coupler interfaces.

A pose change must move associated pins, cylinder halves, linkage parts, connection fittings, rigid pipe runs, and guards together. Keep the same manufactured parts and fixed hole spacings across poses. Use actual shell sections rather than solid steel boom/leg volumes.

## 5. Native rigid hydraulic piping

Demonstrate InventCraft's pipe generator with fixed metal hydraulic tubes on the boom, dipper, cylinder barrels, leg members, and chassis.

Create named route sketches or skeleton sketches with explicit line IDs for the visible supply/return runs. Generate pipes from those sketch lines through the native piping workflow. Preserve source links, sizes, routes, bend radii, fittings, and generated pipe parts in the saved project.

Define each route in the local coordinate system of its supporting component. A boom pipe follows the boom as one rigid part; a cylinder-barrel pipe follows the barrel. Model repeatable P-clamps, stand-offs, unions, elbows, and bulkhead fittings. Check pipe-to-structure clearance and access to mounting fasteners.

Split the plumbing at each moving joint. Terminate rigid runs at realistic fittings on their respective components. Reserve space for the flexible connections that a real machine requires. These unmodeled flexible connections are an intentional visualization simplification and must be identified in the README.

Flexible hose deformation, adaptive hose sketches, automatic hose rerouting, and hose simulation are outside this build's scope. The concept image includes illustrative hose loops; the CAD implementation should prioritize dependable moving mechanisms and well-made rigid tubes.

Pipes must have outside diameter and wall thickness. Check bend setbacks and available straight lengths with piping.route. Include a cut list for the modeled rigid pipes and report any unresolved rigid route.

Keep the hydraulic cylinders fully articulated. Derive barrel orientation, rod orientation, and rod extension from the mounting points in every pose. Pipes attached to a barrel stay on that barrel, with clearance for the moving rod and gland. Verify that each cylinder remains within its declared stroke.

## 6. Sheet-metal panels and beaver stencil

Use sheet-metal features for cab skins, engine/service covers, wheel guards, belly pans, fenders, step panels, and inspection covers. Assign explicit thickness, inside radius, bend relief, corner gaps, and K-factor. Add realistic hemmed safe edges, flanged attachment margins, hinges, captive fasteners, vent louvers, and purposeful seams.

Create and verify flat patterns for representative bent panels. Flat laser-cut plates must retain editable outlines and hole patterns.

On one prominent removable side service cover, create a real through-cut beaver stencil derived from InventCraft's beaver identity. Simplify it into a legible ear/snout/incisor/head silhouette with bridges that retain internal islands and adequate material between cutouts. Store the stencil as an editable sketch followed by a through-cut. Scale to the panel and fabrication process. Show darker backing or mesh behind the opening. Preserve access, stiffness, and pinch clearance.

## 7. Articulation and validation

Expose named parameters for four leg lifts/spreads, four steering angles, wheel spin, slew angle, boom angle, dipper angle, bucket curl, attachment tilt, and attachment rotation. Use native constraints where supported and one deterministic pose controller for relationships the current solver cannot express. Report the implemented motion mechanism and any limitation.

Provide four reproducible saved poses: transport, level working stance, uneven-ground spider stance, and extended working reach. The spider hero pose should show four different leg positions, visible steering, and a convincing support stance.

For each pose, verify joint concentricity, bore/pin clearance, cylinder engagement and stroke, tire-to-leg clearance, panel clearance, rigid-pipe/fitting clearance, and obvious assembly interference. Exclude intentional bearing contact from collision failures. Demonstrate wheel rotation separately so tread interpenetration cannot be hidden by a still image.

Measure a representative hole and sheet thickness in the reopened model. Rebuild the complete model from a clean output directory, reopen it in InventCraft, and verify component references, material appearance, transparent glass, native pipe generation, and flat-pattern results. Use focused automated geometry checks where they catch mechanism or persistence regressions.

## 8. Deliverables and completion

Deliver a self-contained native project under examples/walking-excavator/, a reproducible build script, native parts and subassemblies with relative references, named route sketches and generated rigid piping, shared fasteners, saved poses, a BOM/material summary, pipe cut list, representative panel flats, and a concise README explaining regeneration and pose controls.

Render the actual finished CAD assembly through InventCraft's native renderer. Produce a full-machine 4K hero view in the uneven-ground stance, a neutral overview, a rigid hydraulic piping close-up, a cab/glass/wiper close-up, an open-service-panel detail showing the stencil, and a boom fabrication view. Save native viewport evidence with the assembly tree visible. Identify the concept image and finished CAD renders in the README.

Before calling the work complete, inspect the images. Verify four wheel-leg modules, cylinders connected to real mounts, readable tire tread, glazing that reveals the interior, rigid pipes connected to fittings and moving with their supporting components, hollow fabricated members, and an actual beaver panel cutout. Correct missing, intersecting, or visually implausible components.

If a requested behavior cannot be achieved with the existing implementation, finish unaffected deliverables and report the exact blocked operation, its source/API, and evidence. Describe what is implemented and demonstrated. Any engineering-certification or manufacturing-validation claim requires evidence beyond visual appearance.
