"""A rebuild never puts back a sketch solved for another state.

``Document`` keeps each feature's result under a fingerprint and uses it
again when the fingerprint comes round. A sketch is a live object that
every build solves in place, so what was kept for a feature could hold the
solution of a later build, and a feature after it that had to build read
the wrong diameter. Found through model states: Primary, then a state with
a new diameter and length, then Primary, then a state with the new length
and the old diameter, left Primary measuring the other state's diameter.
Undo and redo load the part again (new features, new sketches) and meet
the same cache.

Every number here is read from the solid, and every sequence is compared
with the same part built from nothing (``forget_results``).
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import harness  # noqa: E402,F401

from datum.core import kernel, modelparams  # noqa: E402
from datum.core.document import Document  # noqa: E402

FAILS = []


def check(name, cond, extra=""):
    print(("  PASS  " if cond else "  FAIL  ") + name
          + (("  " + str(extra)) if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


# a shank 6 across and 30 long (parameters dia and len, the sketch's
# circle dimensioned by dia) under a head 14 across and 4 high
SHANK = json.loads(r'''
{
 "appearance": "",
 "density": 1.0,
 "features": [
  {
   "id": 1,
   "name": "Sketch",
   "plane_ref": "XY",
   "shared": false,
   "sketch": {
    "constraints": [
     {
      "driving": true,
      "entities": [],
      "expression": "0",
      "id": 4,
      "kind": "distance_x",
      "label_offset": [
       0.0,
       0.0
      ],
      "name": "d1",
      "points": [
       1,
       2
      ],
      "value": 0.0
     },
     {
      "driving": true,
      "entities": [],
      "expression": "0",
      "id": 5,
      "kind": "distance_y",
      "label_offset": [
       0.0,
       0.0
      ],
      "name": "d2",
      "points": [
       1,
       2
      ],
      "value": 0.0
     },
     {
      "driving": true,
      "entities": [
       3
      ],
      "expression": "dia",
      "id": 6,
      "kind": "diameter",
      "label_offset": [
       0.0,
       0.0
      ],
      "name": "d3",
      "points": [],
      "value": 6.0
     }
    ],
    "entities": [
     {
      "ccw": true,
      "construction": false,
      "id": 3,
      "kind": "circle",
      "points": [
       2
      ],
      "radius": 3.0
     }
    ],
    "name": "Sketch",
    "next_id": 7,
    "plane": {
     "name": "XY Plane",
     "normal": [
      0.0,
      0.0,
      1.0
     ],
     "origin": [
      0.0,
      0.0,
      0.0
     ],
     "xdir": [
      1.0,
      0.0,
      0.0
     ]
    },
    "points": [
     {
      "fixed": true,
      "id": 1,
      "origin": true,
      "x": 0.0,
      "y": 0.0
     },
     {
      "fixed": false,
      "id": 2,
      "origin": false,
      "x": 0.0,
      "y": 0.0
     }
    ],
    "projections": [],
    "texts": []
   },
   "suppressed": false,
   "type": "sketch"
  },
  {
   "body_name": "",
   "distance": "len",
   "distance2": "5",
   "extend_face": false,
   "extent": "distance",
   "from_plane": "",
   "from_ref": [],
   "id": 2,
   "match_flip": false,
   "match_shape": false,
   "name": "Shank",
   "operation": "join",
   "param_names": {
    "distance": "d4",
    "taper": "d5"
   },
   "profiles": [],
   "reversed": false,
   "sketch_id": 1,
   "suppressed": false,
   "taper": "0",
   "taper2": "0",
   "to_plane": "",
   "to_ref": [],
   "type": "extrude"
  },
  {
   "id": 3,
   "name": "Sketch1",
   "plane_ref": "XY",
   "shared": false,
   "sketch": {
    "constraints": [
     {
      "driving": true,
      "entities": [],
      "expression": "0",
      "id": 4,
      "kind": "distance_x",
      "label_offset": [
       0.0,
       0.0
      ],
      "name": "d6",
      "points": [
       1,
       2
      ],
      "value": 0.0
     },
     {
      "driving": true,
      "entities": [],
      "expression": "0",
      "id": 5,
      "kind": "distance_y",
      "label_offset": [
       0.0,
       0.0
      ],
      "name": "d7",
      "points": [
       1,
       2
      ],
      "value": 0.0
     },
     {
      "driving": true,
      "entities": [
       3
      ],
      "expression": "14",
      "id": 6,
      "kind": "diameter",
      "label_offset": [
       0.0,
       0.0
      ],
      "name": "d8",
      "points": [],
      "value": 14.0
     }
    ],
    "entities": [
     {
      "ccw": true,
      "construction": false,
      "id": 3,
      "kind": "circle",
      "points": [
       2
      ],
      "radius": 7.0
     }
    ],
    "name": "Sketch1",
    "next_id": 7,
    "plane": {
     "name": "XY Plane",
     "normal": [
      0.0,
      0.0,
      1.0
     ],
     "origin": [
      0.0,
      0.0,
      0.0
     ],
     "xdir": [
      1.0,
      0.0,
      0.0
     ]
    },
    "points": [
     {
      "fixed": true,
      "id": 1,
      "origin": true,
      "x": 0.0,
      "y": 0.0
     },
     {
      "fixed": false,
      "id": 2,
      "origin": false,
      "x": 0.0,
      "y": 0.0
     }
    ],
    "projections": [],
    "texts": []
   },
   "suppressed": false,
   "type": "sketch"
  },
  {
   "body_name": "",
   "distance": "4",
   "distance2": "5",
   "extend_face": false,
   "extent": "distance",
   "from_plane": "",
   "from_ref": [],
   "id": 4,
   "match_flip": false,
   "match_shape": false,
   "name": "Head",
   "operation": "join",
   "param_names": {
    "distance": "d9",
    "taper": "d10"
   },
   "profiles": [],
   "reversed": false,
   "sketch_id": 3,
   "suppressed": false,
   "taper": "0",
   "taper2": "0",
   "to_plane": "",
   "to_ref": [],
   "type": "extrude"
  }
 ],
 "hidden_bodies": [],
 "hidden_planes": [],
 "hidden_sketches": [],
 "material": "Generic",
 "model_states": null,
 "named_entities": {},
 "next_id": 5,
 "origin_autohidden": false,
 "parameters": [
  {
   "comment": "",
   "expression": "30",
   "name": "len",
   "unit": "mm"
  },
  {
   "comment": "",
   "expression": "6",
   "name": "dia",
   "unit": "mm"
  }
 ],
 "properties": {},
 "rollback": null,
 "rules": [],
 "sheet_metal": null,
 "shown_sketches": [],
 "solid_labels": {},
 "units": "mm",
 "view": {
  "front": [
   0.0,
   -1.0,
   0.0
  ],
  "top": [
   0.0,
   0.0,
   1.0
  ]
 }
}
''')
doc = Document()
doc.load_dict(SHANK)
doc.rebuild()
states = doc.model_states


def read():
    """(shank diameter, height, volume), rebuilt with the cache in use."""
    doc.rebuild()
    box = kernel.bounding_box(doc.shape)
    return round(box[3] - box[0], 4), round(box[5] - box[2], 4), round(
        kernel.volume(doc.shape), 3)


def fresh():
    """The same part, every feature built from nothing."""
    doc.forget_results()
    doc._applied_chain = None
    return read()


def agrees(tag):
    got = read()
    want = fresh()
    check(tag, got == want, (got, want))
    return want


base = agrees("Primary, as built")
# the Head (14 wide) is the widest, so measure the shank by the solid's
# volume: any change of the shank's diameter or length moves it
vol_primary = base[2]

# two variants the way the bridge makes them: a copy of Primary, changed
states.create(doc, "Long")
modelparams.set_expression(doc, "len", "40")
states.sync(doc)
states.activate(doc, "Primary")
states.create(doc, "Stout")
modelparams.set_expression(doc, "dia", "8")
modelparams.set_expression(doc, "len", "40")
states.sync(doc)
states.activate(doc, "Primary")
agrees("Primary after the states are made")
check("Primary is the volume it was", read()[2] == vol_primary, read())

# the order that went wrong: Primary, new diameter and length, Primary,
# the new length and the old diameter, Primary
volumes = {}
for name in ("Stout", "Primary", "Long", "Primary", "Stout", "Long",
             "Primary", "Long", "Stout", "Primary"):
    states.activate(doc, name)
    got = agrees("state %s agrees with a build from nothing" % name)
    if name in volumes:
        check("state %s is the same size every time" % name,
              volumes[name] == got, (volumes[name], got))
    volumes[name] = got
check("the three states differ",
      len({volumes["Primary"], volumes["Long"], volumes["Stout"]}) == 3,
      volumes)
check("Primary is still Primary", volumes["Primary"][2] == vol_primary,
      volumes["Primary"])

# the part loaded again from its own snapshot, as measuring every state
# does and as undo does: new feature and sketch objects, the old results
# still held. Each state is built on the way (its sketch solved for it),
# then the part is put back and a feature after the sketch has to build
before = doc.snapshot()
for name in ("Primary", "Long", "Stout"):
    states.activate(doc, name)
    doc.rebuild()
doc.load_dict(json.loads(before))
doc.rebuild()
agrees("loaded again: matches a build from nothing")
states = doc.model_states
for name in ("Long", "Primary", "Stout", "Primary"):
    states.activate(doc, name)
    got = agrees("after loading again, state %s" % name)
    check("after loading again, state %s is the size it was" % name,
          volumes[name] == got, (volumes[name], got))
modelparams.set_expression(doc, "len", "30")
got = agrees("after loading again, the length is typed")
check("and Primary is Primary", got[2] == vol_primary, got)

# the same through undo and redo: loading the part again makes new feature
# and sketch objects, which the cache still holds the old ones of
doc.push_undo()
modelparams.set_expression(doc, "dia", "9")
doc.rebuild()
nine = read()
doc.push_undo()
modelparams.set_expression(doc, "dia", "6")
modelparams.set_expression(doc, "len", "40")
doc.rebuild()
long_six = read()
for step in range(2):
    check("undo %d" % step, doc.undo(), "")
    doc.rebuild()
    agrees("undo %d matches a build from nothing" % step)
    if step == 0:
        check("undo one step: the diameter 9 part, length 30",
              read() == nine, (read(), nine))
check("redo", doc.redo(), "")
doc.rebuild()
agrees("redo matches a build from nothing")
while doc.redo():
    pass
doc.rebuild()
check("redo to the end: the part as it was last edited",
      read() == long_six, (read(), long_six))

# undo straight after a diameter was typed: the sketch of the undone part
# is a new object, the held result of the same fingerprint is the old one,
# solved at the diameter that was undone. A feature after it then builds
states.activate(doc, "Primary")
modelparams.set_expression(doc, "len", "30")
modelparams.set_expression(doc, "dia", "6")
doc.rebuild()
want = fresh()
doc.push_undo()
modelparams.set_expression(doc, "dia", "8")
doc.rebuild()
check("the diameter is 8 before the undo", read()[2] != want[2], read())
check("undo", doc.undo(), "")
doc.rebuild()
check("undo gives the part back", read() == want, (read(), want))
modelparams.set_expression(doc, "len", "40")
agrees("a length typed right after the undo")
doc.undo()
doc.rebuild()
agrees("and undone again, whatever it goes back to")

# a sketch edited by hand and put back, with a feature after it that has
# to build each time
for dia in ("12", "6", "12", "7", "6"):
    modelparams.set_expression(doc, "dia", dia)
    for length in ("40", "55", "40"):
        modelparams.set_expression(doc, "len", length)
        agrees("dia %s, length %s" % (dia, length))

print()
if FAILS:
    print("%d FAILURES: %s" % (len(FAILS), "; ".join(FAILS[:10])))
    sys.exit(1)
print("ALL PASSED")
