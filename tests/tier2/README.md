# Tier 2: agent benchmarks (on demand, costs money)

A real agent (Claude Code, `claude -p`) gets a request in plain words and
only the InventCraft MCP server. The harness then judges the part the
agent saved, without asking the agent how it went. See the docstring of
`run_tier2.py` for the details.

**Never part of `tests/run.py`.** Every run spends tokens.

```powershell
.venv\Scripts\python.exe tests\tier2\run_tier2.py --list
.venv\Scripts\python.exe tests\tier2\run_tier2.py --check-references   # free: verdicts vs. reference builds
.venv\Scripts\python.exe tests\tier2\run_tier2.py bracket din934_nut    # haiku by default
.venv\Scripts\python.exe tests\tier2\run_tier2.py --all --model sonnet --record
```

Needs `claude` on PATH and logged in (`claude auth login`), or
`ANTHROPIC_API_KEY`. Each run is capped by `--budget` (default $1).

## Session-driven runs (no CLI login needed)

Any agent can stand in for `claude -p`. For example, use one fresh
desktop Claude Code session per scenario, started in `C:\InventCraft`.
The repository's `.mcp.json` gives it the server.
1. Give each session the scenario's `prompt` and the save line,
   `save it with save_document to this absolute path:
   C:\InventCraft\tests\tier2\runs\sessions\<scenario>.icpart`. Allow
   only the inventcraft tools and resources: no file reads, no shell.
   Pick a cheap model.
2. Optional: copy each session's transcript
   (`~\.claude\projects\C--InventCraft\<session id>.jsonl`) next to its
   part as `<scenario>.jsonl`.
3. Judge them all. This spends nothing:

```powershell
.venv\Scripts\python.exe tests\tier2\run_tier2.py --judge-dir tests\tier2\runs\sessions --record
```

The report goes to `runs/judged-<time>/` and is the same as a CLI run's.
Cost and time are missing, because a session transcript doesn't record
them. Calls are counted once each (desktop transcripts repeat messages).
Any tool besides the server's, ToolSearch, the resource readers and the
app's task list is reported as "used tools outside the brief".

## Scenarios beyond one part (assembly, drawing, flat, weldment, optimise, STEP)

Eleven scenarios: the five parts above, then `assembly_pin_in_block`,
`drawing_of_bracket`, `sheet_metal_flat`, `weldment_cut_list`,
`optimise_lightest` and `step_parametrize`. The new ones can name:

- `tools`: the server's `--tools` for the agent and the judge
  (`default,+drawing`, `default,+sheetmetal`, `default,+frames`). For
  session-driven runs put the same in `.mcp.json` (`--tools all` does for
  every scenario).
- `save_as`: `.icpart` (default), `.icasm` or `.icdraw`, the file judged.
  Anything but a plain part gets a folder of its own, `<run>/<scenario>/`,
  written `{dir}` in the prompt, which also holds the parts and exports the
  agent makes.
- `fixtures`: files the agent starts from, built by the harness from ops
  (a saved part, a STEP file), free.
- verdict keys `assembly` (`occurrences`, `min_constraints`, `max_dof`,
  `max_interference`, `bom_lines`, `cut_list`), `drawing` (`min_views`,
  `min_annotations`, `size`, `section`), `flat` (a sheet metal part's
  `bends`, `length`), `cut_list` (`pieces`), `not_features`, and `files`
  (exports that must exist in `{dir}`).
- a `reference` that is `{"calls": [{tool, args}, ...]}` with `{WORK}` in
  paths: a short run of tool calls, after which the open document is judged.

```powershell
.venv\Scripts\python.exe tests\tier2\run_tier2.py --prepare tests\tier2\runs\sessions
```

makes each scenario's folder and fixtures and writes its full prompt to
`runs\sessions\prompts\<scenario>.txt` (free). `--judge-dir` then finds
`<scenario>.icpart` or `<scenario>\<scenario>.icasm` there.

OpenCode (the free `bench` agent in `opencode.json`) is a third route:
`opencode run --agent bench "<the prompt file's text>"` per scenario, then
`--judge-dir`. Its transcripts are not scored (Claude Code's format only),
so calls, tokens and cost are blank for those runs.

## Dashboard

```powershell
.venv\Scripts\python.exe tests\tier2\dashboard.py     # runs\dashboard.html
```

One static page (no scripts) from every `runs\*\report.json`: pass rate
per scenario over time, tool calls and failed calls per report, and a table
of every run with tokens and cost where known. Free.

## Files

- `scenarios/*.json`: `prompt`, `verdict`, and a `reference` (ops, or a
  call of a Tier 1 replay) that must pass the verdict.
- Verdict keys: `inspect` (or `any_of` several), `requirements` the
  harness sets on its copy (names start `t2 `), `features` /
  `features_any` (op types in `read_ir`), `min_parameters`, `parametric`
  (every numeric parameter +10 % still builds one valid solid). The
  agent's own requirements must pass too.
- Score: verdict, tool calls by tool, failed calls and their messages,
  guides read, turns, tokens, dollars, seconds.
- Output: `runs/<time>/report.md`, `report.json` and the transcripts
  (git-ignored). `--record` writes each passing run to
  `tests/mcp_replays/tier2_<scenario>.json`, a free Tier 1 regression:
  the calls that succeeded, then the verdict's inspect.
