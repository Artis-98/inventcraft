# Branches: try a change in isolation, then merge or discard

An agent that is not sure of a change works on a **branch** of the saved
document, reviews it against main, and merges it or throws it away. A
branch is the document's own version history (the `.icversions` folder
beside the file, which the app's Versions panel shows too), so the file
must be saved, and the user can open any version in the app.

## The flow

1. `branch(action="create", name="try-wider")`: main is checked in (version
   1 if it never was), the branch starts at it and the document switches to
   it. Refused with `UNSAVED_CHANGES` if the open document has unsaved
   changes: save_document() or `check_in` first.
2. build(), edit_feature(), properties(): ordinary edits, now on the branch.
3. `branch(action="check_in", message="why")` saves the document and keeps
   it as the next version of the branch.
4. Review: `diff(before="branch:main", after="branch:try-wider")` lists
   features added, removed and changed and parameters changed, with no
   switching. `version:<id>` works too (branch(action="list") has them).
5. `branch(action="switch", name="main")`: main's latest replaces the
   document (one undo step in the app; refused while there are changes
   not checked in, since they would be lost).
6. `branch(action="merge", name="try-wider")`: that branch into the current
   one, as a new version. `dry_run=true` only checks for conflicts.
   `branch(action="discard", name="try-wider")` drops the branch instead
   (its versions stay in the store).

## What merge does

- Main has not moved since the branch parted: a plain fast-forward.
- Both moved: parts are merged **feature by feature against the version
  they parted at**. What only one side changed is taken; what both
  changed alike is taken once; features and parameters one side added
  come along.
- What both sides changed *differently* (the same parameter to two
  values, one side deleting a feature the other edited, both adding a
  feature with the same id) is a **MERGE_CONFLICT**: the error lists
  every conflict (`conflicts`: the feature or parameter, and the base,
  ours and theirs values), nothing is merged, and the file is untouched.
  Make the two agree (edit one branch) and merge again. Never work
  round a conflict by choosing for the user: tell them.
- A merge that would not build is refused the same way.
- Assemblies and drawings fast-forward only; if both moved it is a
  conflict (they are not merged feature by feature).

## Know

- Branch names are free text; `main` is the first. Versions are whole
  files, kept until the user deletes the folder.
- Every switch and merge moves the revision, so a diff against an earlier
  revision still shows what a switch changed.
- Without a saved file there is nothing to branch: use snapshot() for an
  in-memory copy.
