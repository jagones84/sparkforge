# AGENTS.md — start here (SparkForge)

Orientation for an AI agent (or human) landing in this repo. Read in this order;
you should be productive within minutes and operate at the level of the agents
that built this.

## Read order (do not skip)

1. **`.agent/HANDOFF.md`** — what was just done, current state, dead paths to avoid.
2. **`.agent/README-debugging.md`** — the debugging manual: folder map, the debug
   ladder, golden rules, known bug classes, exact commands, rollback.
3. **`docs/TESTING-PLAYBOOK.md`** — the mindset for testing the harness live.
4. **`docs/ARCHITECTURE.md`** and **`docs/CLI.md`** — how the system is wired.
5. **`tests/README.md`** — how to run the gate and write a test.
6. **`docs/research/2026-10-06-debugging-large-codebases.md`** — the science of
   debugging large, interrelated codebases (delta debugging, SBFL, slicing, …).

## The 60-second mental model

- A stdlib-only Python **agent harness** (`src/sparkforge/`), HTTP on `:8790`,
  SPA at `webui/index.html`, optional Orbit beta at `src2/orbit_beta/`.
- **Five object levels**: `Team (TN) → Job (JN) → Subjob (JN.j) → Agent (AX) → Todo
  (AX.nY)`. A **team** owns its roster; an **agent IS a session**
  (`agent["session"] == sid`). A **job** runs a coordinator + its team in dependency
  waves — the coordinator's PLAN turn is plan-only and read-only, the workers execute.
- **Everything is gated** behind `Authorization: Bearer <token>` (or `?token=`);
  the token lives in the service `EnvironmentFile`, never in the repo.
- State is files under `data/` (sessions, graphs, runs, edits, events.db, jobs).
- The **harness is the model's secretary**: it injects synthetic turns tagged
  `nudge` / `observation` / `continue`, persisted so the chat rebuilds them on reload.

## The one command that matters

```bash
bash tests/battery.sh     # 104/104 GREEN required before any commit
```

## Non-negotiables

- **No secrets in the repo.** `.env.template` is the only tracked env file.
- **Evidence over belief.** A claim needs a number (test count, HTTP status, file field).
- **`ast.parse` after any scripted patch**; `git checkout -- <file>` if you break it.
- **Checkpoint before refactor**, then `git reset --hard <checkpoint>` to roll back.
- **Trash goes to `trash/`**, temp scripts never pollute `scripts/` or the repo root.
- **Update `.agent/HANDOFF.md` + the matching `README-*.md` in the same session.**
