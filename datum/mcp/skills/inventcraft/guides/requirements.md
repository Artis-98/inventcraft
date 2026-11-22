# Requirements

Requirements say what the part must be. They are stored in the part,
checked on every rebuild (by you or in the app), and every build's
summary ends with `reqs 5/6 ✓` or with what fails. Set them early, from
the request, so each build tells you how far you are.

Metrics: `bbox` `mass` `volume` `clearance` `hole_count` `parameter` `solids` `faces`. Keys: `name` `metric` `target` `min` `max` `tolerance` `axis` `a` `b` `param` `diameter` `note` `enabled`.
`target` takes a relative `tolerance` (default 0.01); `min` and `max` are
limits.

```json
requirements(set=[
 {"name":"size","metric":"bbox","target":[120,80,10]},
 {"name":"fits","metric":"bbox","axis":"x","max":150},
 {"name":"light","metric":"mass","max":1200},
 {"name":"holes","metric":"hole_count","target":4,"diameter":6.6},
 {"name":"edge gap","metric":"clearance","a":"Hole1.wall[0]",
  "b":"Extrusion1.side(r.right)","min":5},
 {"name":"w range","metric":"parameter","param":"w","min":80,"max":200}])
```

- `bbox` with `target` compares the three sizes sorted, so orientation
  does not matter; with `axis` it is one size.
- `mass` is in grams and needs a material.
- `clearance` is the least distance between two references; give
  references by definition so it follows parameter changes.
- requirements() with no arguments reads them with their results;
  `check=true` measures again now; `remove` takes names.

inspect(expected=...) is the one-off check; requirements are the lasting
one. Use both: inspect for the shape you meant to build, requirements
for what the user asked.
