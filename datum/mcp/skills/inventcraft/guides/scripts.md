# run_script vs code features

Both are Python. They differ in when the code runs.

| | run_script() | `code` op in build() |
|---|---|---|
| runs | once, now, in a separate process on a copy | on every rebuild, in the part |
| leaves | ordinary features (sketches, holes...) | one Code feature |
| use for | one-off generation: holes from a table, a grid laid out once | structure that must follow a parameter: n posts for a length L |
| after a parameter change | the features stay as made | the count and layout follow |

Prefer plain build() ops when a pattern feature says it (`pattern`
with `count1` as an expression stays parametric too).

## run_script()

Helpers: `build(ops)`, `op(type, **fields)`, `param(name, value)`,
`sketch(**fields)`, `extrude(sketch, distance, **f)`,
`hole(sketch, diameter, **f)`, `fillet(radius, edges, **f)`,
`ref(text)`, `find(what, **where)`, `measure(a, b)`,
`inspect(expected)`, `params["w"]`. `sketch` takes every entity and
plane build does, so a loft of thirty spline sections is a loop and
`op("loft", sections=names)`. Colour, material and iProperties come
through too: `op("properties", appearance="#203060")`. For many parts use
build_project(), with `shared` for what they have in common. print()
output comes back; set
`result = ...` to return a value. What the script changed is applied to
the real part as one build: all or nothing, one undo step. `dry_run`
shows the ops it would apply. It is not a sandbox: it has the user's
privileges; `safe_mode` (on by default) refuses imports, files and
dunders. The server's `--code` decides the rest: `safe` (its default)
keeps safe mode on and checks code features the same way, `full` lets you
turn it off, `off` refuses agent code (a `CODE_OFF` error).

The user is asked before your code runs: the server shows them the source
in their client, and they allow it, allow all your code for the session,
or say no (`USER_DECLINED` for a script; a code feature then waits for
trust). Do not send declined code again: ask what they want. A client
that cannot ask refuses scripts (`CODE_NOT_ALLOWED`) and leaves code
features waiting for trust: use build ops, or the app, which asks itself.

## The code op

```json
{"op":"code","name":"Posts","operation":"join","source":
 "n = int(params.L // 300)\nbody = union(*[cylinder(10, 900).move(i*300, 0, 0) for i in range(n + 1)])"}
```

The source reads parameters as `params.L`, hands its solid back as
`body = ...` (or `result(solid)`), and `operation` joins, cuts or
intersects it with the part (`new` keeps it a separate solid). Solids
combine with `+` union, `-` difference, `&` intersection. Helpers:
- `box(x, y, z, centered=False)`
- `cylinder(radius, height, axis='z')`
- `cone(bottom, top, height, axis='z')`
- `sphere(radius)`
- `torus(ring, tube, axis='z')`
- `tube(outer, inner, height, axis='z')`
- `union(*solids)`
- `rod(start, end, radius)`
- `beam(start, end, width, height)`
- `circle(radius)`
- `rect(width, height, centered=True)`
- `polygon(points)`
- `regular(sides, radius)`
- `path(points, corner=0)`
- `arc(start, middle, end)`
- `helix(radius, pitch, height)`

Solid methods (each returns a new solid): `chamfer(distance)` `common(other)` `cut(*others)` `fillet(radius)` `fuse(*others)` `mirror(plane='yz', about=(0, 0, 0))` `move(x=0, y=0, z=0)` `move_to(x=0, y=0, z=0)` `repeat(count, x=0, y=0, z=0)` `repeat_around(count, axis='z', degrees=360, about=(0, 0, 0))` `rotate(axis='z', degrees=0, about=(0, 0, 0))` `scale(factor, about=(0, 0, 0))`.
Profile methods (circle, rect, polygon, regular make profiles): `extrude(height, taper=0)` `move(x=0, y=0)` `revolve(degrees=360, axis='y')` `sweep(along)`.

Your source is trusted for this session by its hash. Code that came in a
file, and yours once the saved file is reopened, waits for the user to
allow it (`waiting_for_trust` in the build result: tell the user).
