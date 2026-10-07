# README — Debugging SparkForge (domain manual)

> **Read this first** before debugging anything in this repo. It is the frozen,
> tested knowledge from the JAG-303..JAG-311 debugging campaign. If a future
> session follows only this file plus `docs/TESTING-PLAYBOOK.md`, it should be
> able to debug at the level of the agent that wrote them.

---

## 0. Where things live (the folder map)

| Path | What it is | Notes |
|------|-----------|-------|
| `src/sparkforge/` | the Python package (stdlib-only) | 44 modules; `server.py` is the HTTP core |
| `src2/orbit_beta/` | the Orbit beta (optional, never imported at top level) | `api.py` + `web/orbit.html`; the server swallows a missing beta |
| `webui/index.html` | the main SPA (single file: HTML+CSS+JS) | served behind the token |
| `tests/acceptance/` | **the live battery** (auto-discovered) | `v140..v311`; the gate |
| `tests/legacy/` | frozen history (`v02..v176`) | do NOT add here |
| `tests/live/` | scripts needing a running server | run by hand |
| `tests/nightly/` | the overnight mega loop + check helpers | `mega.sh`, `start.sh` |
| `tests/properties/` | Hypothesis property tests | pure logic |
| `docs/research/` | research notes (primary sources) | e.g. `2026-10-06-debugging-large-codebases.md` |
| `docs/` | `ARCHITECTURE.md`, `CLI.md`, `TESTING-PLAYBOOK.md`, plans/specs | |
| `.agent/HANDOFF.md` | short-term memory: what was just done + dead paths | **read it second** |
| `.agent/README-*.md` | per-domain manuals (this file) | |
| `outputs/` | dated run outputs (gitignored) | `YYYYMMDD_HHMM_RunType/` |
| `trash/` | superseded scripts/files (gitignored by design) | never mass-fixed |

Data dirs (all env-overridable): `data/sessions/<sid>.json`, `data/graphs/<sid>.json`,
`data/runs/<sid>.json`, `data/edits/<sid>.json`, `data/events.db`,
`data/jobs.json`, `data/agents.json`, `data/routines.json`.

---

## 1. The debug ladder (cheap → expensive)

Run in order; stop when the defect is isolated.

1. **Static (seconds)** — `ruff check src/sparkforge`, `mypy src/sparkforge --ignore-missing-imports`,
   `bandit -r src/sparkforge -ll`. Catches real bug classes across the repo.
2. **Battery (fast, deterministic)** — `bash tests/battery.sh`. 73 tests, one exit code.
   Every test is isolated (temp `SPARKFORGE_*` dirs) and needs no network/model.
3. **Property-based (seconds)** — `pytest tests/properties/`. Hypothesis over pure logic.
4. **Mutation (minutes)** — `mutmut` scoped to one module. Points at lines the battery
   does not really check. Config lives in `setup.cfg`.
5. **Runtime tracing (where the real bugs are)** — read `data/events.db` and the
   per-session JSON. `events.db` proved JAG-304/308/310.
6. **Live UI (slow)** — chrome-devtools MCP: DOM, console, network. `docs/TESTING-PLAYBOOK.md`.
7. **e2e (a few journeys only)** — `sparkforge/e2e` (gitignored), tester-army framework.

All of the above are wired into `tests/mega_test.sh` and `tests/nightly/mega.sh`.

---

## 2. Golden rules (learned the hard way)

1. **Evidence, never belief.** A claim needs a number: a test count, an HTTP status,
   a `data/*.json` field, a log line, a screenshot.
2. **`ast.parse` after ANY scripted patch.** Naive multiline string replaces in
   `prompt.py`/`server.py` silently produced a 3-space `except` → `IndentationError`
   that broke imports and turned the battery from 72 to 63. If a file is broken,
   `git checkout -- <file>` (a checkpoint commit always exists before a refactor).
3. **Never persist synthetic control rows into a transcript.** A "compaction notice"
   row appended to `messages` broke v214 (`messages_after` vs actual) and polluted
   history. Show control notices through the **SSE feed**, not the transcript.
4. **Scope state to THIS turn.** JAG-310: `_run_agent` used the last assistant
   message of the WHOLE session, so a job with no new reply was "accepted" with a
   stale answer. Always bound reply-selection by the turn boundary.
5. **One writer per field.** JAG-309: `agent["model"]` and `session["model"]` were
   written by different code paths and drifted. A single writer (`_set_session_model`)
   + a startup reconciler fixed it.
6. **Ruff's `--fix` can change semantics.** It stripped `as exc` from a bare
   `except Exception:` while `str(exc)` was still referenced → `NameError` on every
   job error (found by the nightly loop). When you autofix, re-run the battery and
   eyeball the diff.
7. **Late binding in lambdas.** `lambda j: ... str(_e) ...` inside a loop/except
   captures the name at call time; pass defaults: `lambda j, _err=_err: ...`.
8. **Directories are the product.** Don't test inside the repo root; bind live test
   sessions to a disposable workspace. Temp scripts go to `trash/`, never `scripts/`.
9. **Distinguish repo state from live state.** systemd units live OUTSIDE the repo.
   After editing Python you must `systemctl --user restart sparkforge.service` for
   the API to change; static HTML is served from disk immediately.
10. **Two-strike rule.** If a fix fails twice, stop and re-read the source, don't
    stack a third guess.

---

## 3. Known bug classes in this codebase (checklist)

- **`str(exc)` without `as exc`** — appears after a ruff autofix. `grep -n 'str(exc)' src/sparkforge`.
- **Missing imports used only inside a branch** — `subprocess`, `queue`, `glob`.
  `ruff` F821 + `pyflakes` catch most; `mypy` catches the rest.
- **Bare `except Exception: pass`** — hides failures; `bandit` B110 flags it.
- **Weak hashes / permissive chmod** — `bandit` (`sha1` → `sha256`; `0o777` → `0o755`).
- **Deferred/`_lazy` module globals** — `api_v02.py` sets ~50 globals via `setattr`;
  static tools cannot see them (F821). Accept + keep the lazy setter documented.
- **Dual state (agent model vs session model)** — reconcile at startup.
- **Turn-scoped extraction (JAG-303/310)** — never let a fallback see a previous turn.
- **Stale-plan hijack (JAG-189)** — a job turn must not be auto-planned.
- **Sessions deleted while running resurrect** — tombstone the id (`_DELETED_SESSIONS`).
- **Test infra silently broken (JAG-313)** — `pytest tests/properties/` errored on
  collection (`ModuleNotFoundError: sparkforge`) because no `conftest.py` put `src`
  on `sys.path`; the nightly loop reported `props_exit=2` for hours and nobody
  looked. Fixed by `tests/conftest.py`. Lesson: a tool exit code in a loop log is
  evidence — a non-zero you never explained is a bug you never found.
- **Runtime maps leak across create/delete** — prune `_TURN_LOCKS`, ctx caches,
  steer inbox on delete (`_forget_session_runtime`).
- **Dangling references after a delete (JAG-314)** — deleting an object must scrub
  every reference to it: a job id left in another job's `blocked_by` deadlocks the
  dependent; a session id left as an agent designation lets a job/routine
  resurrect it. Deleting a job must `_scrub_blocker`; releasing an agent must
  `scrub_agent` + `delete_for_agent`; deleting a session must release the agent
  and purge its ROLE.md.
- **Daemon worker thread vs interpreter exit (JAG-314 segfault)** — `wake()` /
  `dispatch()` spawn a real daemon worker (`Thread(target=self._run, daemon=True)`).
  A test that exits while it runs can SIGSEGV (exit 139) AFTER printing PASS.
  Always stub first: `jobs.JOBS._run = lambda jid: None` (see v290, v314).
- **In-memory tombstone (`_DELETED_SESSIONS`) lost on restart + silent resurrection
  (JAG-315)** — JAG-222 blocked a late *write* to a deleted session, but
  `get_or_create_session(sid)` DISCARDED the tombstone, so `/api/chat` /
  `/api/chat/stream` (both call it with the client's session id) resurrected a
  deleted session as an empty transcript. Fixed: a load of a deleted id hands
  back a FRESH session and the tombstone is kept + persisted (`.deleted`), so it
  also survives a restart. Locked by `tests/acceptance/v315_session_delete_final.py`.
- **Identity counter derived from the LIVE set (JAG-316)** — `_max_job()` took the
  max session `job` over current files only, so deleting the top session let the
  next session REUSE its `JX` label (two sessions sharing `J12`; also colliding
  with the orchestrator's `J<n>`). Fixed with a persisted monotonic high-water
  mark (`.jobseq`). Rule: any "never reused" id must be backed by a durable
  counter, never recomputed from the objects that still exist. Locked by
  `tests/acceptance/v316_job_id_monotonic.py`.
- **An object with no true delete (JAG-317/318)** — memory had only a soft
  tombstone (and its `forget` action was an alias of it); checkpoints and
  approvals had no delete at all, so they grew forever (and `approvals._events`
  leaked one Event per id). Rule: EVERY stored object must offer a true,
  physical delete alongside any soft/invalidate path. Now: `memory.forget` /
  `purge_invalidated`, `checkpoints.delete` / `prune`, `approvals.delete` /
  `clear`. Locked by `v317_memory_true_delete.py`, `v318_ckpt_approvals_delete.py`.
  Audit tool: `python3 scripts/audit_except.py` (AST scan of silent handlers).
- **A `done` that contradicts the delegation that was supposed to produce it
  (JAG-320)** — the harness accepted any non-empty evidence string, so after a
  delegated subagent TIMED OUT (`{"ok": false, "error": "subagent timeout"}`) the
  model could still close that step `done` with invented evidence. Two defects:
  (1) the failure observation text said "Subagent X finished (...)" even on
  failure, so the model believed it had the result; (2) `update_todos ... done`
  never cross-checked the objective delegation outcome. Rule: when a step's work
  is delegated, its OUTCOME is a fact you own — record it durably and refuse a
  `done` that contradicts a failure. Fix: `taskgraph.record_delegation` stores the
  outcome ON the node (cleared by a successful retry); `_apply_chat_todo_updates`
  refuses the `done` once (one-shot, so a genuine retry / self-completion is never
  blocked forever). Durable + node-scoped on purpose: in the real incident the
  claim came ~8.6h after the timeout (a short timer would have missed it), and a
  failure on one step must not block another. Locked by
  `tests/acceptance/v320_failed_delegation_not_done.py`.
- **"Reset" that clears one store but not the others (JAG-321)** — a session
  transcript is the MERGE of three persisted stores: `messages` + `tool_cards` +
  `injects` (`loadHistory` rebuilds from all three). `POST /api/sessions/<id>/clear`
  reset only `messages`, so tool cards and the harness entries (nudge/pivot/final/
  retry) reappeared right after a reset — the chat was never truly empty. Rule:
  clearing a logical object means clearing EVERY store that composes it, not just
  the obvious one. Both the composer reset (`index.html`) and the per-agent reset
  (`orbit.html`) hit that one endpoint. Fixed via a single `clear_session(sid)`.
  Locked by `tests/acceptance/v321_reset_clears_all.py`.
- **A run that no-ops silently, or is stuck `running` (JAG-322)** — a job whose
  member agents were deleted gets `agents` scrubbed to `[]` (JAG-314); `_run` then
  walked an empty roster, did nothing and still marked the job `done`
  (`started == ended`, no work). A job left `running` by a killed worker answered
  "already running" to a re-run, so the ▶ run button did nothing. Rule: a worker
  must never report success for work it did not do — refuse/raise when there is no
  one to run (`dispatch` refuses an empty roster; `_run` raises for agents whose
  records are gone → visible `error`); `reconcile()` on startup closes jobs killed
  by a restart; and the UI must SURFACE a refused dispatch, never swallow it.
  Locked by `v322_job_delegation_subjobs.py` (§E), `v289_job_ops.py`.
- **A delegated turn with no attributable author, and no subjob ids (JAG-322)** —
  a worker's turn was appended as a plain `user` message, so the worker's chat
  showed the assignment as the OPERATOR's own ("YOU"), the coordinator's chat had
  NO record of delegating, and nothing identified which agent owned which piece.
  Rule: when an agent delegates, the hand-off is a FIRST-CLASS object — a numbered
  subjob (`J6.1`) bound to ONE agent, with its own status and timings, recorded in
  BOTH chats and attributed (`sender`/`subjob` on the message → the UI shows
  "A1 (Master) · J1.1", not "YOU"). See `jobs.plan_subjobs` / `_delegation_msg` /
  `_announce_delegation`.
- **One identity under two stale labels (JAG-322)** — an agent's NAME (Orbit
  table) and its session TITLE (main app list) are the same thing seen from two
  panels; editing one left the other stale. Rule: pick a single writer per field
  and mirror it (here `AgentRegistry.sync_title` / `set_name`, publishing
  `session.renamed` so the other panel refreshes live).
- **A "phantom run": a turn in flight with NO UI signal (JAG-323, SEVERE)** — an
  agent session was RUNNING (GPU busy, tokens burning) while the left panel showed
  it idle, so the operator could not see — let alone stop — it. Two holes: the
  session list (`/api/sessions`) exposed NO `running` flag, and `chat.run` was
  pushed only to the STARTING browser's stream, never published to the global feed
  (`chat.done` was). Any turn the browser did not itself begin — a headless
  job/routine turn on another session — was therefore invisible. Rule: the running
  state of a session is SERVER truth (`_ACTIVE_CHAT`), it must be published on the
  global feed on start AND end, AND exposed in the session list so a reload/missed
  event still shows it. Locked by `v323_running_signal.py`.
- **A hierarchy level that lives in the view but not in the data (JAG-324)** — the
  Job → Agent → Todo model had no place for a *subjob* (`J6.1`), so a delegated
  piece of work could not be named, attributed, ordered, or drawn. Rule: a level is
  real only when the DATA carries it, never when only a panel draws it. A job's
  subjob (`JN.j`) lives in `job["subjobs"]` with its own `deps` (a DAG mirroring the
  agent dependency waves); the todos it produces carry BOTH `jid` and `subjob` (the
  two invariants, stamped in `taskgraph.add_node`); `JobRegistry.subjob_todos`
  pivots the todo store into the subset a subjob *embraces*. The constellation then
  draws exactly Job → Subjob → Agent → Todo. Anchoring the level in the stores keeps
  every surface (main-app chip, Orbit subjob lane, `/api/jobs/<id>`) coherent
  instead of each inventing its own. Locked by `v324_subjob_hierarchy.py`.
- **A "running" signal that only ONE entry point emits (JAG-325, SEVERE)** — the
  JAG-323 fix taught the STREAMING path to register in `_ACTIVE_CHAT`, but the
  synchronous `POST /api/chat` handler and the in-process MCP `chat` bridge
  (`api_v02.LocalApi.chat`) also run REAL model turns and never registered, so those
  turns were STILL phantom runs (idle panel, GPU burning). Rule: the running signal
  is not a property of one handler — make it a SHARED bracket (`turn_begin` /
  `turn_end`) that EVERY entry point wraps its model call in, and carry a per-turn
  token so a late-finishing older turn never un-marks a newer one. Corollary: when
  you fix a cross-cutting concern by editing one call site, immediately enumerate
  the others (`grep chat_once\(` / `chat_stream_gen\(`). Locked by
  `v325_phantom_run_all_paths.py`.
- **Ids that look sortable but are not (JAG-326)** — subjob ids are `JN.1 … JN.10`,
  and a plain STRING sort puts `JN.10` before `JN.2`, so a job with 10+ subjobs
  listed them out of order (the coordinator's delegation record AND the Orbit
  JobsView). Rule: an id whose suffix is an ORDINAL (`A1`, `J6.3`) must be sorted by
  its NUMERIC index, never lexicographically — keep one shared key (`subjob_num` on
  the Python side, the `_jn` helper in Orbit). Locked by
  `v326_subjob_natural_order.py`.
- **A stable id that spans two runs (JAG-327)** — a re-run of a job REUSES the
  subjob ids (`J6.1` again), but `_scope_graph` keys the plan on the JOB id, which is
  unchanged on a re-run — so no new plan opened and `subjob_todos` merged the
  previous run's todos into this run's. Rule: a RUN must open a fresh plan
  (`jobs._run`), and a read-only view that pivots by a re-used id must scope to the
  LATEST plan that id appeared in (`jobs.latest_plan_nodes`) — NOT to the session's
  current plan, else a later unrelated plan would erase the mapping entirely. Locked
  by `v327_subjob_run_scope.py`.
- **A graph edge that shows a relationship that does not exist (JAG-328)** — the
  constellation drew a job's assign arrow to EVERY member (`J7 -> A8` AND `J7 -> A9`)
  although the job belongs to the coordinator only; the member's piece is a SUBJOB
  (`J7.1 -> A9`). Rule: an edge must encode a REAL relation from the object model — a
  job is assigned to its COORDINATOR, members are reached through their subjobs.
  Locked by `v328_job_edge_to_coordinator.py`.
- **A periodic re-render that eats live input (JAG-329)** — the Orbit agents table is
  rebuilt every 5s; the guard deferred it while a text field was focused but NOT while
  a native `<select>` (the MODEL dropdown) was OPEN, so the poll closed the dropdown
  mid-selection ("the model tab disappears after a timer"). Rule: a poll that rebuilds
  a DOM subtree must skip while ANY form control in it is live — `INPUT`, `TEXTAREA`,
  `SELECT`. Locked by `v329_select_survives_poll.py`.
- **A DAG that was never built, so ordered work ran in parallel (JAG-330, SEVERE)** —
  the coordinator job had NO subjob dependencies, so coder 2 started at the same time
  as coder 1 instead of waiting for it. The deps only came from the user's job config;
  the MASTER never declared the order. Rule (Paperclip): the coordinator must DECLARE
  what happens in order, and the runner must ENFORCE it. The decomposition asks for
  `(after AX)` on a bullet; `parse_plan_deps` reads it; `merge_deps` unions it with
  the user's deps; `waves()` then schedules in waves so a dependent subjob CANNOT
  start before the ones it waits on are done, and each subjob carries its `deps`.
  Locked by `v330_declared_subjob_deps.py`.
- **A "worker" told to narrate instead of work (JAG-331, SEVERE)** — the delegation
  message ended with a plain-text-only instruction, so a worker replied with a PLAN
  and "this turn exposes no callable tools" instead of deploying the app, even though
  the system prompt carries the tool registry and the skills index. Rule: a delegated
  subjob is WORK TO DO — tell the worker it HAS tools and skills, to carry out the
  assignment end to end and report the RESULT; never frame it as prose. Locked by
  `v331_worker_executes.py`.
- **A harness you cannot see (JAG-332)** — the per-turn system-prompt card is emitted
  TRANSIENTLY (kind `system`, not persisted), so after a reload there was NO harness
  message at the start of a session and the operator could not tell a real prompt was
  passed (mistaking ROLE.md for a replacement of everything). Rule: leave ONE durable
  `harness-start` marker per session on the first turn, stating what was loaded
  (workspace, rules, skills index, tool registry, prompt size). Locked by
  `v332_harness_start_marker.py`.
- **A master with no plan (JAG-333)** — a coordinator job showed an EMPTY task list:
  job turns are never auto-planned (JAG-308) and the coordinator is told not to call
  tools, so nothing created its plan. Rule: the harness SEEDS the master's plan from
  the decomposition — one todo per subjob, tagged with the subjob id. Locked by
  `v333_master_plan.py`.
- **Subjob ids that do not nest (JAG-334)** — a piece handed out FROM inside a subjob
  must be `JN.j.x`, not another flat `JN.k`, so the numbering mirrors the ORG depth.
  `subjob_id` / `plan_subjobs(parent_sub=…)`. Locked by `v334_nested_subjob_ids.py`.
- **A job panel that lists agents instead of structure (JAG-335)** — the Orbit job
  rows repeated a flat per-agent `runs` list ("A8 done, A9 done, A11 running"); only
  the `JN.j` indexes are the structure. Rule: show the subjobs INDENTED by depth and
  CLICKABLE to the receiving agent's chat; drop the per-agent rows. Locked by
  `v335_job_rows.py`.
- **A dependency feature proven only on a toy graph (JAG-336)** — the DAG was tested
  with 2-3 agents. A synthetic 12-agent "S.p.A." org with a multi-level dependency
  chain now locks the wave scheduler, the subjob deps and nesting in the battery.
  Locked by `v336_complex_organigram.py`.
- **A failed subjob returned to the master in total silence (JAG-337, SEVERE)** — a
  worker ("coder 2") FAILED, was NEVER retried, and its failure was not recorded in
  either chat: the ball passed back to the coordinator with no trace. Paperclip rule:
  never sit silently on blocked work. Fix: (a) workers end with an explicit
  `STATUS: DONE` / `STATUS: BLOCKED: <why>` / `STATUS: FAILED: <why>` (a missing
  status is DONE only when no plan step is still OPEN); (b) a non-DONE attempt is
  RETRIED up to `SPARKFORGE_JOB_RETRIES` (default 1) extra times; (c) a subjob that
  still fails is marked `failed` (NEVER `done`) and ESCALATED with a `handoff` inject
  into BOTH the worker's and the coordinator's chat; (d) the coordinator's synthesis
  message lists the UNFINISHED SUBJOBS; (e) the job record carries `failed_subjobs`
  and status `partial`. Locked by `v337_worker_outcome.py`.
- **A master that was forbidden to think (JAG-338)** — the coordinator's decomposition
  turn was told "do NOT call any tool", so it could not use its skills or write its
  own plan and the harness had to seed one. Fix: the coordinator MAY use tools/skills
  and SHOULD record its own todos; it is still forbidden to spawn subagents. The
  harness plan seed (`_seed_coordinator_plan`) is now a FALLBACK — it skips when the
  master already authored a plan. Locked by `v338_master_autonomy.py`.
- **A whole org level that did not exist (JAG-339)** — agents were the top grouping.
  Added the TEAM (`TN`): a real group of agents (`data/teams.json`, `TeamRegistry`),
  with an agent able to belong to SEVERAL teams. The team store OWNS membership;
  `agents.py` only reads it (`teams_for`), so they cannot drift. `/api/teams*`; Orbit
  gets a team selector that scopes agents/org/jobs/constellation; the main app tags
  each session with its team symbol(s). The seeding script
  (`scripts/seed_teams.py`) builds 3 diversified teams with real organigrams from the
  agency-agents clone. The chat todo id moved `AX.TY` → `AX.nY` (T is the team
  namespace; node ids were already `n`). Locked by `v339_teams.py`,
  `v340_team_scope.py`, `v341_team_seed.py`.
- **A two-column grid that clipped panels (JAG-342)** — the ORG CHART was cut off, the
  page grew a horizontal scrollbar while the chart ALSO had a transform pan ("se c'è il
  pan a che serve la scrollbar?"), and the layout was hard to read. Fix: every page row
  is a single column (mobile-style, full width); the org chart scrolls NATIVELY inside
  its panel (the transform pan is gone); switching team resets the constellation focus.
  Locked by `v342_orbit_layout.py` (and `v311` updated for the pan removal).
- **Every seeded agent defaulting to the SAME local model (JAG-343)** — a team's agents
  all had no model, so all resolved to one local model on one GPU. Fix: a team model
  policy — at most ONE local model per machine (dgx/win) per team; leads/coordinator get
  the strongest cheap cloud (`openrouter:z-ai/glm-5.3-flash`), everyone else the cheap
  cloud (`openrouter:deepseek/deepseek-v4-flash-0731`); a guard on every model set
  refuses a 2nd local on the same machine within a team. Applied via the Orbit "model
  policy" button (`POST /api/teams/<id>/models`) or `seed_teams.py --models`. Overridable
  with `SPARKFORGE_TEAM_LEAD_MODEL` / `_MEMBER_MODEL` / `_LOCAL_SLOTS`. Locked by
  `v343_team_models.py`.

---

## 4. Exact commands

```bash
# one gate (isolated, deterministic, no model):
bash tests/battery.sh

# full ladder (installs a venv on first run):
bash tests/mega_test.sh

# overnight loop (8h, safe autofix gated by the battery, self-reverting):
nohup bash tests/nightly/mega.sh > outputs/nohup_nightly.log 2>&1 &
# stop:  touch .nightly_stop

# static
.venv/bin/ruff check src/sparkforge
.venv/bin/mypy src/sparkforge --ignore-missing-imports
.venv/bin/bandit -r src/sparkforge -ll -q

# run one test
python3 tests/acceptance/v310_agent_turn_delivery.py

# live HTTP smoke (token from the service EnvironmentFile)
set -a; . /home/jagones/.config/sparkforge/env; set +a
curl -s -X POST http://127.0.0.1:8790/api/sessions \
  -H "Authorization: Bearer $SPARKFORGE_TOKEN" -H 'Content-Type: application/json' \
  -d '{"title":"smoke"}'
```

---

## 5. Rollback

- Every refactor is preceded by a **checkpoint commit** (see `git log`; e.g.
  `CHECKPOINT-BEFORE-REFACTOR-20261006`). `git reset --hard <checkpoint>` restores it.
- A single file: `git checkout -- src/sparkforge/<file>.py`.
- The battery is the safety net: **never** commit with it red.
- `trash/pre-refactor-20261006/` holds superseded helper scripts (kept on disk, untracked).

---

## 6. Writing a new acceptance test

Copy the header of `tests/acceptance/v310_agent_turn_delivery.py`:

- `REPO = dirname(dirname(dirname(abspath(__file__))))` (three levels: tests/acceptance/).
- `sys.path.insert(0, os.path.join(REPO, "src"))`.
- Point every `SPARKFORGE_*` env at a `tempfile.mkdtemp()` so the test is isolated.
- Use a local `check(name, ok, detail)` and `sys.exit(1)` if any fails.
- The battery auto-discovers `tests/acceptance/v*.py`; just drop the file in.

---

## 7. Documentation contract (do not skip)

After any resolved incident, in the **same session**:
1. append the incident to `.agent/HANDOFF.md` (goal, steps, **dead paths**, next);
2. merge the frozen fix + root cause into this file (or the matching `README-*.md`);
3. if tests changed, note the new count in `tests/README.md`.
"Mission accomplished" includes the documentation. Future agents inherit only what
you write down.

---

## 8. A job run: PLAN turn vs WORK turn

A `mode="coordinator"` job runs the master TWICE:

1. **PLAN turn** — decompose the goal into one bullet per teammate. This turn is
   **plan-only** (`_run_agent(..., plan_only=True)` → `chat_stream_gen(plan_only=...)`):
   a tight real-tool budget (`PLAN_ONLY_MAX_STEPS`, default 3), **no keepgoing
   continuation**, and **read-only** — only `PLAN_ONLY_TOOLS` (`fs.read`, `skills`,
   `memory`, `self`) may run; `shell` / `fs.write` / `fs.edit` / `subagent` are refused
   with a directive (`_plan_only_refusal`). Reason (JAG-344): with the full budget + the
   continuation loop, a capable master *completed the whole job itself* (wrote the
   deliverable files and "verified" them) instead of delegating — the team was bypassed.
   The master's own todos ARE the delegation, not work for it to close; the loop used to
   nag it to.
2. **SYNTHESIS turn** — after the worker waves, produce the final deliverable from the
   team report. `_close_open_todos` closes the master's decomposition steps first, so
   this turn has no open todos and is not nagged.

**Assignment text** (`_assignment_for`): the plan can carry an aggregate line listing
several ids ("critical path: A13 -> A14 -> A15"). Pick the **most specific** line —
first id = this agent, fewest OTHER agents named — or every worker gets the same text
(JAG-344).

**Symptom → cause:**
- "the master did the whole job / the team did nothing" → the PLAN turn was not
  plan-only (check `plan_only=True` reaches `chat_stream_gen`).
- "every subjob shows the same assignment" → `_assignment_for` returned the aggregate
  line.
