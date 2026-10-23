r"""Run the test suites, several at a time, the long ones first.

Every suite is its own process, and stays one: a crash or a leftover
setting in one cannot change what another sees, and a failure is reported
where it happened rather than as a cascade.  What is shared is the
machine, and the wall time is spent three ways:

* Starting up.  Qt and OpenCASCADE take a couple of seconds per process,
  more with a window to build.  That cannot be shared, only overlapped.
* The longest suite.  Nothing finishes before it does, so the suites go
  in longest first, by how long each took last time, and a suite that
  declares ``# shards: N`` near its top is run as N processes, each given
  ``DATUM_SHARD=i/N`` to take its own share of the work.
* Waiting for a slot.  Suites with no window are only arithmetic and run
  many at a time; window suites race each other for the screen and the
  clock, so fewer of those run together.

    python tests\run.py              every suite
    python tests\run.py --fast       only the ones with no window
    python tests\run.py cam sketch   only suites whose names have those words
    python tests\run.py --changed    only suites that run the code changed
                                     since the last commit (see below)
    python tests\run.py --map        every suite, recording which code each
                                     one runs, for --changed
    python tests\run.py --changed --list
                                     which ones, without running them
    python tests\run.py -j 4         at most four window suites at a time
    python tests\run.py --core-j 8   at most eight windowless ones

``--changed`` reads ``build/test-impact.json``, written by ``--map``: for
every function in ``datum/``, the suites that ran it.  A changed line picks:

* inside a function the map knows, the suites that ran that function;
* inside a new method, or in a class's own lines, the suites that ran
  anything of that class, since Qt or Python may call it unasked;
* inside a new function of its own, nothing: whatever calls it changed
  too, and picks for it;
* a changed import, the quickest suite that loads the file;
* anywhere else in the file, every suite that ran anything in it.

Blank lines and comments pick nothing.

A changed test file picks itself.  With no map it falls back to suites
that name the changed module.  It is for while working: the whole suite
still runs before a commit and before every release, and ``--map`` is
worth running again once a lot has moved.

Exits nonzero if any suite fails, and prints the output of the ones that
did, so nothing is hidden by the parallelism.
"""

import ast
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BUILD = os.path.join(ROOT, "build")
TIMINGS = os.path.join(BUILD, "test-timings.json")
IMPACT = os.path.join(BUILD, "test-impact.json")

# Measured on the 12 thread machine this is developed on, where OpenCASCADE
# already spreads one suite over several cores: four window suites and two
# without, longest first, ran everything in 178 s, and more at once only
# made them fight (11 together took 517 s, with timing failures).
GUI_WORKERS = 4
CORE_WORKERS = 2
# every process's own settings key, removed after the run
TEST_ORG = "IITEG-run-"


def suites():
    return sorted(os.path.join(HERE, name) for name in os.listdir(HERE)
                  if name.startswith("test_") and name.endswith(".py"))


def _source(path):
    try:
        with open(path, encoding="utf-8-sig") as handle:
            return handle.read()
    except OSError:
        return ""


def is_core(path):
    """A suite with no QApplication in it, so no window to build."""
    return "QApplication" not in _source(path)


def shards_of(path):
    """How many processes a suite asks to be split over: ``# shards: N``."""
    head = "\n".join(_source(path).splitlines()[:40])
    found = re.search(r"^#\s*shards:\s*(\d+)", head, re.M)
    return max(1, int(found.group(1))) if found else 1


def jobs_for(paths):
    """(label, path, shard) for every process to start."""
    out = []
    for path in paths:
        name = os.path.basename(path)
        count = shards_of(path)
        if count == 1:
            out.append((name, path, None))
        else:
            for i in range(count):
                out.append(("%s [%d/%d]" % (name, i + 1, count), path,
                            "%d/%d" % (i, count)))
    return out


# --------------------------------------------------------------- timings


def load_timings():
    try:
        with open(TIMINGS, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return {}


def save_timings(timings):
    try:
        os.makedirs(BUILD, exist_ok=True)
        with open(TIMINGS, "w", encoding="utf-8") as handle:
            json.dump(timings, handle, indent=1, sort_keys=True)
    except OSError:
        pass


# ------------------------------------------------------------- running


def run(label, path, shard, prefix=(), extra_env=None):
    """One process: ``python [prefix...] suite``, with its shard if any.

    Each gets settings, preferences and documents of its own.  Run side
    by side, suites sharing them read each other's: one test's active
    project turned up in another's, and a slider saved by one was already
    at its value in the next, so a change it was waiting for never came.
    """
    env = dict(os.environ)
    own = re.sub(r"\W+", "-", label).strip("-")
    scratch = tempfile.mkdtemp(prefix="datum_suite_")
    env["DATUM_SETTINGS_ORG"] = TEST_ORG + own
    env["DATUM_CONFIG_DIR"] = os.path.join(scratch, "config")
    env["DATUM_DOCUMENTS"] = os.path.join(scratch, "documents")
    os.makedirs(env["DATUM_CONFIG_DIR"])
    os.makedirs(env["DATUM_DOCUMENTS"])
    if shard:
        env["DATUM_SHARD"] = shard
    if extra_env:
        env.update(extra_env)
    started = time.time()
    try:
        done = subprocess.run([sys.executable] + list(prefix) + [path],
                              cwd=ROOT, capture_output=True, text=True,
                              env=env)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    return (label, path, done.returncode, time.time() - started,
            done.stdout + done.stderr)


def forget_settings():
    """Remove the registry keys the run's own settings went into."""
    if sys.platform != "win32":
        return
    import winreg

    def wipe(path):
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as key:
                names = []
                while True:
                    try:
                        names.append(winreg.EnumKey(key, len(names)))
                    except OSError:
                        break
            for name in names:
                wipe(path + "\\" + name)
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, path)
        except OSError:
            pass

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Software") as soft:
            mine, i = [], 0
            while True:
                try:
                    name = winreg.EnumKey(soft, i)
                except OSError:
                    break
                if name.startswith(TEST_ORG):
                    mine.append(name)
                i += 1
    except OSError:
        return
    for name in mine:
        wipe("Software\\" + name)


def run_all(jobs, gui_workers, core_workers, timings, coverage_dir=None):
    """Every job, longest first, windows and arithmetic in their own lanes.

    Unknown suites count as long, so a new one is not left to the end.
    """
    def expected(job):
        return timings.get(job[0], 60.0)

    ordered = sorted(jobs, key=expected, reverse=True)
    gui = [j for j in ordered if not is_core(j[1])]
    core = [j for j in ordered if is_core(j[1])]
    lock = threading.Lock()
    results = []
    total = len(jobs)

    def start(job):
        label, path, shard = job
        if coverage_dir is None:
            return run(label, path, shard)
        # in-process, so the geometry a worker would build is counted too
        data = os.path.join(coverage_dir, re.sub(r"\W+", "_", label))
        prefix = ("-m", "coverage", "run", "--data-file=" + data,
                  "--include=" + os.path.join(ROOT, "datum", "*"))
        return run(label, path, shard, prefix, {"DATUM_NO_WORKERS": "1"})

    with ThreadPoolExecutor(max_workers=max(1, gui_workers)) as gui_pool, \
            ThreadPoolExecutor(max_workers=max(1, core_workers)) as core_pool:
        futures = ([gui_pool.submit(start, j) for j in gui]
                   + [core_pool.submit(start, j) for j in core])
        for future in as_completed(futures):
            label, path, code, seconds, output = future.result()
            with lock:
                results.append((label, path, code, seconds, output))
                print("  %-4s %6.1fs  %-40s %3d/%d" % (
                    "FAIL" if code else "ok", seconds, label,
                    len(results), total), flush=True)
    return results


# --------------------------------------------------------- what changed


def changed_lines():
    """{repo-relative path: set of changed line numbers} since HEAD, with
    new files whole.  Deleted lines count as the line where they were."""
    out = {}
    try:
        diff = subprocess.run(["git", "diff", "-U0", "HEAD", "--", "."],
                              cwd=ROOT, capture_output=True, text=True,
                              encoding="utf-8", errors="replace").stdout
        fresh = subprocess.run(["git", "ls-files", "--others",
                                "--exclude-standard"], cwd=ROOT,
                               capture_output=True, text=True).stdout
    except OSError:
        return out
    current = None
    for line in diff.splitlines():
        if line.startswith("+++ "):
            name = line[4:].strip()
            current = name[2:] if name.startswith("b/") else None
            if current:
                out.setdefault(current, set())
        elif line.startswith("@@") and current:
            found = re.search(r"\+(\d+)(?:,(\d+))?", line)
            if found:
                first = int(found.group(1))
                count = int(found.group(2) or 1)
                out[current].update(range(first, first + max(count, 1)))
    for name in fresh.splitlines():
        out[name.strip().replace("\\", "/")] = {-1}       # all of it
    return out


def _scopes(path, classes=False):
    """[(first, last, qualified name, is_class)] for every function in a
    file, and every class too when asked."""
    found = []
    try:
        tree = ast.parse(_source(path))
    except SyntaxError:
        return found

    def walk(node, prefix):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef,
                                  ast.ClassDef)):
                name = prefix + child.name
                is_class = isinstance(child, ast.ClassDef)
                if classes or not is_class:
                    found.append((child.lineno, child.end_lineno, name,
                                  is_class))
                walk(child, name + ".")
    walk(tree, "")
    return found


def _functions(path):
    return [(a, b, n) for a, b, n, _c in _scopes(path)]


def _innermost(functions, line):
    best = None
    for first, last, name in functions:
        if first <= line <= last and (best is None or first > best[0]):
            best = (first, name)
    return best[1] if best else None


def _import_lines(path):
    """Every line that belongs to a top level import statement."""
    found = set()
    try:
        tree = ast.parse(_source(path))
    except SyntaxError:
        return found
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            found.update(range(node.lineno, node.end_lineno + 1))
    return found


def _owner(scopes, line):
    """The innermost function or class a line is in: (name, is_class)."""
    best = None
    for first, last, name, is_class in scopes:
        if first <= line <= last and (best is None or first > best[0]):
            best = (first, name, is_class)
    return (best[1], best[2]) if best else (None, False)


def _class_of(name, scopes):
    """The class a function belongs to, the nearest one out, if any."""
    classes = {n for _a, _b, n, c in scopes if c}
    parts = name.split(".")
    for cut in range(len(parts) - 1, 0, -1):
        candidate = ".".join(parts[:cut])
        if candidate in classes:
            return candidate
    return None


def select_changed(all_suites):
    """The suites that run what changed, and why, for --changed."""
    changes = changed_lines()
    by_name = {os.path.basename(p): p for p in all_suites}
    try:
        with open(IMPACT, encoding="utf-8") as handle:
            impact = json.load(handle)
    except (OSError, ValueError):
        impact = None
    chosen, reasons = set(), []
    for rel, lines in sorted(changes.items()):
        base = os.path.basename(rel)
        if rel.startswith("tests/") and base in by_name:
            chosen.add(base)
            reasons.append("%s changed" % base)
            continue
        if not (rel.startswith("datum/") and rel.endswith(".py")):
            continue
        if impact is None:
            module = os.path.splitext(base)[0]
            hits = {os.path.basename(p) for p in all_suites
                    if re.search(r"\b%s\b" % re.escape(module), _source(p))}
            chosen |= hits
            reasons.append("%s: %d suite(s) that name it (no map yet; run "
                           "--map)" % (rel, len(hits)))
            continue
        per_file = impact.get("files", {}).get(rel, {})
        whole = set().union(*per_file.values()) if per_file else set()
        full = os.path.join(ROOT, rel)
        scopes = _scopes(full, classes=True)
        text = _source(full).splitlines()
        imports = _import_lines(full)
        hits, names, everything = set(), set(), -1 in lines and per_file
        if -1 in lines and not per_file:
            reasons.append("%s: new, nothing runs it yet" % rel)
            continue
        timings = load_timings()
        for line in lines:
            if everything:
                break
            said = text[line - 1].strip() if 0 < line <= len(text) else ""
            if not said or said.startswith("#"):
                continue                        # blank, or a comment
            name, is_class = _owner(scopes, line)
            if name is None and line in imports:
                if whole:
                    hits.add(min(whole, key=lambda n: timings.get(n, 60.0)))
                names.add("an import")
            elif name is None:
                everything = True               # module level
            elif not is_class and name in per_file:
                hits.update(per_file[name])
                names.add(name)
            else:
                owner = name if is_class else _class_of(name, scopes)
                if owner is None:
                    continue                    # a new function: callers
                prefix = owner + "."
                for known, ran in per_file.items():
                    if known == owner or known.startswith(prefix):
                        hits.update(ran)
                names.add(owner + " (class)")
        if everything:
            hits = set(whole)
        chosen |= hits
        reasons.append("%s: %d suite(s)%s" % (
            rel, len(hits), " (whole file)" if everything else
            " (%s)" % ", ".join(sorted(names)[:4]) if names else ""))
    return sorted(by_name[n] for n in chosen if n in by_name), reasons


# ---------------------------------------------------------------- the map


def build_map(results, coverage_dir):
    """build/test-impact.json from each suite's coverage data."""
    import coverage

    files = {}
    tops = {}
    for label, _path, _code, _seconds, _output in results:
        suite = label.split(" [")[0]
        data_file = os.path.join(coverage_dir, re.sub(r"\W+", "_", label))
        if not os.path.exists(data_file):
            continue
        data = coverage.CoverageData(basename=data_file)
        data.read()
        for measured in data.measured_files():
            rel = os.path.relpath(measured, ROOT).replace("\\", "/")
            if not rel.startswith("datum/"):
                continue
            if rel not in tops:
                tops[rel] = _functions(measured)
            per_file = files.setdefault(rel, {})
            for line in data.lines(measured) or ():
                name = _innermost(tops[rel], line) or "<module>"
                per_file.setdefault(name, set()).add(suite)
    out = {"made": time.strftime("%Y-%m-%d %H:%M"),
           "files": {rel: {name: sorted(s) for name, s in names.items()}
                     for rel, names in files.items()}}
    os.makedirs(BUILD, exist_ok=True)
    with open(IMPACT, "w", encoding="utf-8") as handle:
        json.dump(out, handle, separators=(",", ":"))
    return len(files)


# ------------------------------------------------------------------ main


def main(argv):
    args = list(argv)
    gui_workers, core_workers = GUI_WORKERS, CORE_WORKERS
    for flag in ("-j", "--core-j"):
        if flag in args:
            i = args.index(flag)
            value = int(args[i + 1])
            del args[i:i + 2]
            if flag == "-j":
                gui_workers = value
            else:
                core_workers = value
    flags = {f for f in ("--fast", "--changed", "--map", "--list")
             if f in args}
    args = [a for a in args if a not in flags]

    chosen = suites()
    reasons = []
    if "--fast" in flags:
        chosen = [p for p in chosen if is_core(p)]
    if "--changed" in flags:
        chosen, reasons = select_changed(chosen)
        for reason in reasons:
            print("  " + reason)
    if args:
        chosen = [p for p in chosen
                  if any(word in os.path.basename(p) for word in args)]
    if not chosen:
        print("nothing to run" if "--changed" in flags
              else "nothing matched %s" % " ".join(args))
        return 0 if "--changed" in flags else 1

    if "--list" in flags:
        for path in chosen:
            print("  " + os.path.basename(path))
        print("%d suite(s)" % len(chosen))
        return 0

    cores = os.cpu_count() or 4
    gui_workers = max(1, min(gui_workers, cores))
    core_workers = max(1, min(core_workers, cores))
    jobs = jobs_for(chosen)
    print("%d suite(s) as %d process(es): %d window at a time, %d without"
          % (len(chosen), len(jobs), gui_workers, core_workers))

    timings = load_timings()
    coverage_dir = (tempfile.mkdtemp(prefix="datum_map_")
                    if "--map" in flags else None)
    started = time.time()
    results = run_all(jobs, gui_workers, core_workers, timings, coverage_dir)
    wall = time.time() - started
    forget_settings()

    if coverage_dir is None:
        for label, _path, _code, seconds, _output in results:
            timings[label] = round(seconds, 1)
        save_timings(timings)
    else:
        mapped = build_map(results, coverage_dir)
        print("mapped %d file(s) into %s" % (mapped, IMPACT))

    print("-" * 60)
    print("%d suite(s) in %.1fs wall" % (len(chosen), wall))

    failed = [(label, output) for label, _p, code, _s, output in results
              if code]
    for label, output in sorted(failed):
        print()
        print("=" * 60)
        print(label)
        print("=" * 60)
        print(output.strip()[-4000:])

    if failed and coverage_dir is None:
        print()
        print("%d FAILED: %s" % (len(failed),
                                 ", ".join(sorted(n for n, _ in failed))))
        return 1
    if failed:
        print("\n(%d suite(s) failed while mapping, without workers; the "
              "map still has what they ran)" % len(failed))
        return 0
    print("all passed")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
