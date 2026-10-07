# SparkForge `src/` package refactor — Implementation Plan

> **For agentic workers:** execute task-by-task, commit after each phase, stop if a
> verification gate fails. Steps use checkbox (`- [ ]`).

**Goal:** move the 35 top-level Python modules into a real package `src/sparkforge/`
so the repo root contains only entrypoints + dirs, without changing behavior.

**Architecture:** the modules currently use *flat absolute imports* (`import api_v02`)
and 11 of them derive filesystem paths from `__file__`. The refactor (a) adds a
package with one central `paths.py`, (b) rewrites every sibling import to a relative
one (`from . import api_v02`), (c) keeps root entrypoint shims so the systemd unit and
`./run.sh` keep working unchanged.

**Tech Stack:** Python 3 stdlib only, bash, git, pytest-style hand-rolled suites in `tests/`.

**Baseline / rollback:** baseline commit `97ca091` (green). Any phase can be rolled back
with `git reset --hard 97ca091` (or `git revert <phase-commit>`). Work only on `master`,
one commit per phase.

---

## Facts (measured, not assumed)

- 35 root `.py` modules; entrypoints among them: `server.py`, `forge.py`.
- 11 files do `REPO = os.path.dirname(os.path.abspath(__file__))`:
  `edits.py hooks.py improve.py providers.py registry.py rules.py runmetrics.py selfevolve.py server.py skills.py taskgraph.py`.
- 171 sibling `import/from` statements in the root modules.
- 91 test files; 71 do `sys.path.insert`, with `REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`; 135 sibling imports.
- Dirs that must stay at the repo ROOT: `data/ config/ deploy/ docs/ eval/ scripts/ skills/ tests/ webui/ skills-autodist-skill` (via symlink), `run.sh run.ps1 .env.template .gitignore README.md LICENSE`.
- The systemd unit (outside the repo) runs `%h/Repositories/sparkforge/server.py` → a root `server.py` shim keeps it working with **no live-system change**.

---

## Target structure

```
sparkforge/
  server.py                # NEW shim: add src/ to sys.path, run sparkforge.server:main
  forge.py                 # NEW shim: same for the CLI
  run.sh run.ps1           # updated: PYTHONPATH=src exec python3 -m sparkforge.server "$@"
  src/sparkforge/
    __init__.py            # NEW (empty, marks the package)
    paths.py               # NEW: REPO_ROOT + the shared dir constants
    <35 modules moved here>
  tests/ ...               # bootstraps updated to import from sparkforge
```

`paths.py`:
```python
"""Central filesystem anchors for the SparkForge package (JAG-181).

Every module must import paths from here instead of deriving them from its own
__file__, so moving a module never changes which repo it reads.
"""
import os

# src/sparkforge/paths.py -> src/sparkforge -> src -> <repo root>
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(REPO_ROOT, "data")
```

---

## Phase 0 — baseline

- [ ] `ssh dgx "bash .../trash/run_jag177_regress.sh"` → expect exit 0 (15 suites green).
- [ ] `git -C <repo> rev-parse HEAD` → record `97ca091`.

## Phase 1 — package skeleton + central paths

- [ ] `mkdir -p src/sparkforge` and `touch src/sparkforge/__init__.py`.
- [ ] Create `src/sparkforge/paths.py` with the content above.
- [ ] Commit: `chore(pkg): create src/sparkforge package + paths.py`.

## Phase 2 — move modules + rewrite imports

- [ ] `git mv` every root `.py` EXCEPT `server.py`/`forge.py` (which become shims) into `src/sparkforge/`.
- [ ] In `src/sparkforge/*.py`: replace `REPO = os.path.dirname(os.path.abspath(__file__))`
      with `from .paths import REPO_ROOT as REPO`.
- [ ] Rewrite sibling imports with `trash/rewrite_imports.sh` (relative, idempotent):
      `import S` → `from . import S`; `import S as Z` → `from . import S as Z`;
      `from S import x` → `from .S import x`. Only for the known sibling names.
- [ ] Fix the non-literal import sites found by grep (exact, no placeholders):
      - `api_v02.py` `_lazy()`: `importlib.import_module(name)` →
        `importlib.import_module("%s.%s" % (__package__ or "sparkforge", name))`
        (the 11 `_LAZY_MODS` names are siblings).
      - `mcp_server.py` config example path: `.../sparkforge/mcp_server.py` →
        `.../sparkforge/src/sparkforge/mcp_server.py`.
      - `server.py` self-probe `os.path.join(REPO, "server.py")` stays valid:
        `REPO` becomes the repo root and the **root shim** `server.py` lives there.
- [ ] Move `server.py`/`forge.py` bodies into the package, and put root shims:
      ```python
      # server.py (root shim)
      import os, sys
      sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))
      from sparkforge.server import main
      if __name__ == "__main__":
          main()
      ```
- [ ] Gate: `python3 -c "import sys; sys.path.insert(0,'src'); import sparkforge.server"` OK; `python3 -m py_compile src/sparkforge/*.py` OK; `./run.sh --help` starts.
- [ ] Commit: `refactor(pkg): move modules into src/sparkforge + relative imports`.

## Phase 3 — tests bootstrap

- [ ] Scripted, per test file: `REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
      stays (repo root); change every `sys.path.insert(0, REPO)` → `sys.path.insert(0, os.path.join(REPO, "src"))`.
- [ ] Rewrite `import S` / `from S import x` in tests to `from sparkforge import S` / `from sparkforge.S import x`
      (135 statements) with `trash/rewrite_tests.sh`.
- [ ] Gate: `bash trash/run_jag177_regress.sh` → exit 0; then run the *whole* `tests/` dir and diff the pass/fail set vs baseline.
- [ ] Commit: `test(pkg): import from sparkforge + src/ on path`.

## Phase 4 — entrypoints, docs, packaging

- [ ] `run.sh`/`run.ps1`: `PYTHONPATH="$PWD/src" exec python3 -m sparkforge.server "$@"` (and the `.ps1` equivalent).
- [ ] `deploy/sparkforge.service`: leave `ExecStart=.../server.py` (shim) — note it in README.
- [ ] Add `pyproject.toml` (setuptools, `package-dir = {"" = "src"}`, `sparkforge` package, console entry `sparkforge = sparkforge.server:main`).
- [ ] README: update the "structure" section + `run.sh` notes; fix any path examples.
- [ ] Commit: `docs(pkg): document src layout + run/install`.

## Phase 5 — full verification

- [ ] `python3 -m py_compile src/sparkforge/*.py` → no error.
- [ ] Full suite: run every `tests/*.py` that is runnable offline, compare to baseline.
- [ ] Restart service: `systemctl --user restart sparkforge.service`; `is-active` = active; `curl :8790/api/status` 200.
- [ ] Browser smoke: WebUI loads, one chat turn, Plan panel renders.
- [ ] HANDOFF + commit/push.

---

## Risks & mitigations

- **Double-module import** (`server` + `sparkforge.server` both loaded): avoided — the move is
  all-at-once, root files are shims only, nothing imports the flat names after Phase 3.
- **Dynamic imports / subprocess** (`importlib`, `__import__`, `sys.executable server.py`): must be
  grepped and fixed in Phase 2 (add a sub-step: `grep -rn "importlib\|__import__\|sys.executable" src/sparkforge`).
- **Path drift**: every `REPO = ...__file__` replaced by `paths.REPO_ROOT` (grep-verified 0 left).
- **Live systemd**: untouched — the root `server.py` shim keeps `ExecStart` valid.

## Out of scope

Deleting the `skills-autodist-skill` symlink, splitting `server.py` (200 KB), any behavior change.
