# Changelog

All notable changes to SparkForge are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed
- **Determinism of the regression battery.** Four acceptance tests awaited async
  side-effects with fixed `time.sleep()` calls (v204 memory TTL, v222 concurrent
  late-write, v281 terminal output, v287 routine dispatch) — wall-clock races that
  can fail under load. They now poll the real condition with a bounded timeout, or
  order the threads with an `Event`, so the outcome is deterministic.
- **`fs.read` returned an EMPTY observation — silently, harness-wide.** `tools.observation()`
  rendered `stdout`/`stderr`/`path` but never `content`, and `fs.read` returns its payload
  in `content`. So every `fs.read` (and the "read more with fs.read" offload files the
  harness tells the agent to open) reached the model BLANK, with `exit=0` and no error.
  This is the root cause of the "coder 1" job that could not proceed: it was blind to the
  skill's device-fallback procedure and to the source it was editing. Content is now
  rendered (bounded by the budget); guarded by `tests/acceptance/v346_fs_read_observation.py`.
  Battery 105 → 106.

### Added
- **`tests/acceptance/v345_json_extract_props.py`** — a stdlib, seeded property gate
  for `server.extract_json` (400 randomized wrapped values + edge cases + malformed
  input). This closes a real coverage gap: `extract_json` previously had no runnable
  test — its only guard was `tests/properties/test_pure_logic.py`, which needs an
  uninstalled `hypothesis` and never ran. Battery: 104 → 105.

## [1.0.0] — 2026-10-07

The first tagged release. SparkForge is a local-first, stdlib-only agent harness that
**drives one LLM hard** and then composes that harness into **meta-agents organised in
teams**. It is *not* a meta-harness that merely spawns sub-agents: every agent is a full
harness instance with its own tools, skills, plan, memory and transcript.

### Added
- **TEAMS — the fifth object level.** A first-class object model:
  `Team (TN) → Job (JN) → Subjob (JN.j) → Agent (AX) → Todo (AX.nY)`. Teams own their
  roster; agents never own membership, so the two can't drift.
- **Meta-agent orchestration.** A coordinator decomposes a goal into per-teammate
  subjobs, enforces declared `(after AX)` dependencies as real dependency waves, and
  synthesises the team report into the final deliverable.
- **Plan-only coordinator turn (read-only).** The master's planning turn keeps a tight
  tool budget, never enters the completion loop, and may only *inspect* (`fs.read`,
  `skills`, `memory`, `self`) — it cannot execute the team's work, so it can't bypass it.
- **Orbit mission-control deck** (`/orbit`): org chart, live constellation, job
  create/dispatch, a whole-board team selector, and a per-team model policy button —
  single-column, mobile-style.
- **Per-team model policy.** At most **one local model per machine**; the remaining
  agents use cheap cloud models, and the strongest (still cheap) cloud model goes to the
  leads. Enforced on every model set.
- **Team seeding from an org chart** (`scripts/seed_teams.py`) with a model policy flag.
- **Bounded retry + escalation for workers.** A worker that reports `STATUS: BLOCKED`
  is retried a bounded number of times, then marked **failed**; the subjob is failed, the
  job becomes **partial**, and the coordinator is explicitly told which subjobs are
  unfinished so it cannot claim success.

### Changed
- Subjob **assignment text is now per-agent** (the most specific plan line), instead of
  an aggregate "critical path" line that was handed to every worker.
- Orbit board is a single column with a natively-scrolling org chart (no scroll/pan fight).

### Fixed
- Todo ids across the UI are `AX.nY` (the `T` namespace belongs to teams).
- Orbit constellation node labels no longer render the obsolete `AX.TY`.

### Quality
- Deterministic regression **battery: 104/104 GREEN**; CI runs it on every push/PR.

---

Earlier internal milestones (v0.1 → v0.7.7) live in the git history and in
`docs/PLAN.md`; they predate the first public tag and are not individually released.
