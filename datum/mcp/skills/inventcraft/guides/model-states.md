# Model states: a part family in one file

A part has the **Primary** state, which is the part itself, and any number
of others. Each remembers only how it differs from Primary: parameter
values (user parameters, and the dimensions inside sketches and features),
which features are suppressed, the properties (so each has its own Part
Number) and the material. A bolt at five lengths, a bracket with and
without its holes, a casting and the part machined from it: the states
are the family. One file holds them all.

## Making a family

1. Build the part so that each size comes from a parameter (`len`, `dia`),
   with requirements that hold for every variant.
2. One call per variant, each leaving the part where it was:

   ```json
   {"action":"create","name":"M6x40","parameters":{"len":"40"},
    "props":{"Part Number":"B-640"}}
   ```

   (that is the arguments of model_states()). `suppress` / `unsuppress`
   take feature names; `material` a name from ic://materials;
   `copy_from` starts a state from another instead of Primary.
3. `model_states(action="list", measure=true)`: every state, what it
   changes, and its volume, mass and size. This is the table to check and
   to report.
4. `model_states(action="activate", name=...)` makes the part that state:
   inspect(), measure(), render_view() and save_document() then see it.
   Activate Primary again before you finish, unless asked otherwise.

## Rules

- While a non-Primary state is active, properties() and edit_feature()
  of a value change **that state**; adding a feature belongs to every
  state. To change a state without activating it use
  `model_states(action="set", name=..., parameters={...})`; `reset`
  names a parameter or feature to put back to Primary's.
- A state that does not build is refused (`FEATURE_FAILED`) and the part
  is unchanged. `dry_run` tries it without keeping it.
- Every call is one undo step, in both hosts.
- In an assembly: `place_component(file=..., model_state="M6x40")` places
  that variant, edit_feature(feature="Bolt:1", params={"model_state":
  "M6x60"}) swaps it, and bom() counts each state's own Part Number and
  mass. The assembly reads the file as last saved.
- A drawing shows the state a part was saved in.
- ic://doc/{id}/states is the same list as a resource.
