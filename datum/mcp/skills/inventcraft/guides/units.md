# Units

- **The API is always millimetres and degrees**, whatever units the part
  shows a person. inspect() and measure() answer in mm, mm², mm³ and g.
- A part's units (new_document(units=...)) are only how it shows numbers
  to a person: mm (Millimetres), cm (Centimetres), m (Metres), in (Inches), ft (Feet).
- Values are numbers or expressions over parameters: `"w/2 - 5"`,
  `"pitch * (n - 1)"`. Arithmetic with no names is worked out when it is
  stored.
- Expressions know the constants `e` `pi` and the functions `abs` `acos` `asin` `atan` `atan2` `ceil` `cos` `exp` `floor` `hypot` `ln` `log` `max` `min` `pow` `round` `sign` `sin` `sqrt` `tan`. Those names
  are reserved: a parameter cannot be called `e` or `pi` (use `edge`,
  `inset`...).
- Values with an explicit unit are kept as written: `"1 in"`, `"5 deg"`.
- In a part that is not in mm, every bare length inside an expression is
  stored with `mm` (`"w/2 - 5 mm"`), so nothing can later be read as
  inches; factors such as `w / 8` stay unitless.
- Counts (`count1`, `sides`) are plain numbers or expressions; angles
  (`angle`, `taper`) are degrees.
- Trigonometry is in degrees too: `cos(30)`, not `cos(pi/6)`.
- Mass needs a material, by its exact name (some hold commas):
  properties(material="Steel, Mild"). The names are `ABS` `Acrylic (PMMA)` `Aluminium 6061` `Brass` `Concrete` `Copper` `Elastomeric Foam` `Generic` `Glass` `MDF` `Nylon 6/6` `Oak` `PETG` `PLA` `POM (Acetal)` `Plywood, Birch` `Rubber, EPDM` `Steel, Mild` `Steel, Stainless 304`; ic://materials gives
  their densities.
