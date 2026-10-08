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
- **Generalised: no tool may answer the model with nothing.** The same renderer also
  dropped the payload of `fs.write`/`fs.edit` (counters), `self` (its whole self-knowledge
  dict — a tool whose entire purpose is to guide the agent) and `improve`/`reconcile`.
  `observation()` now renders `stdout`/`stderr`/`content`/`path`, then an explicit
  `observation` string, and finally a JSON fallback of the remaining fields. The
  operator-facing `tool.result` events now also fall back to `content`, so file reads are
  no longer blank in the tool cards/feed. `self` reports the LIVE version (was stale
  `0.5.0`). Guarded by `tests/acceptance/v347_observation_payload.py`. Battery 106 → 107.
- **Job dependencies can no longer deadlock (open loop).** A job `blocked_by` a job that
  ended `partial` — a normal outcome when one worker failed — was neither released nor
  failed, so it stayed `blocked` forever. `_blockers_state` now treats any terminal
  blocker that is not `done` (`partial`/`error`) as a FAILED dependency, and `reconcile()`
  now sweeps (`wake()`) the dependents of a restart-killed job instead of leaving them
  blocked. Guarded by `tests/acceptance/v348_job_dep_no_deadlock.py`. Battery 107 → 108.
- **The agent loop (`/api/agent/run`) never saw its own steps (open loop).** It rebuilt
  its messages from scratch every iteration and injected only the task list, dropping every
  observation. The model could not use a subagent's result nor correct a rejected action
  (`unknown action` / `task not found`), so it re-derived the same mistake and could spin —
  the failure JAG-61 fixed in the chat loop but never here. The turn now carries the recent
  `(action -> observation)` history (`_agent_history`). Guarded by
  `tests/acceptance/v349_agent_loop_history.py`. Battery 108 → 109.
- **The coordinator could not look into a teammate's session (SEVERE).** Told
  "coder 1 is failing a lot — understand why and help him", the Master had NO way to
  see that teammate's chat: no DISCOVERY (which session is "coder 1"?) and no readable
  transcript (the raw `data/sessions/<id>.json` is unusable in context). Guiding the
  agent is the harness's whole point, so this was a first-class gap. New read-only
  `sessions` tool: `action=list` maps sessions to agent names, `action=read` renders
  the full transcript (messages + every tool call/result + harness injections,
  time-ordered). The delegation record now also carries each teammate's session id
  and points the master at the tool. Guarded by
  `tests/acceptance/v350_session_inspect.py`. Battery 109 → 110.
- **The Android build/deploy skill steered the agent into failure (SEVERE).** The
  Jago team could not finish, and it was the harness's *guidance*, not the agent or
  the infra: `android-app-build-deploy` step 3 prescribed `compileSdk = 36`, but its
  own reference (`build-on-arm64.md`) proves the ARM64 Debian aapt2 (`2.19`) cannot
  parse `android-35/36` → the build dies. And step 1 told the agent to *read* the ADB
  port from `adb devices -l` (empty on the DGX) or from the PC — never to run the
  trivial, working `adb connect oneplus-15r:5555`. Verified: `adb` over Tailscale
  works from the DGX (connected, phone authorized) yet **0 `adb connect` executions**
  exist across ALL sessions, so "install on device" could never succeed. Both steps
  now lead with the working DGX path (direct `adb connect` + the ARM64 `compileSdk 34`
  rule). Guarded by `tests/acceptance/v351_android_skill_adb.py`. Battery 110 → 111.
- **Chat file links often did nothing (JAG-354).** The reply linkifier only matched
  ABSOLUTE paths (`/…`, `~/…`), so the relative paths and bare filenames agents actually
  emit (`viz/trend.png`, `insights.md`, `README.md`) stayed plain text — and even when a
  link was made, `GET /api/fs/read` / `/api/fs/raw` resolved a relative `?path=` against
  the server CWD instead of the session workspace. Both ends fixed: the pattern now
  matches absolute, relative AND bare paths (code extensions included, so a generated
  script opens in the editor too), and the fs endpoints resolve a relative path against
  the session workspace first. The image preview now carries the session, so relative
  images open as well. Guarded by `tests/acceptance/v354_ui_links_pins.py`. Battery 112 → 113.
- **Sand and Sepia were effectively the SAME theme (JAG-355).** Both were near-white warm
  papers (`--bg #e7d9bd` vs `#e6dcc4`), so switching between them changed almost nothing —
  and Sand was still too bright to be an eye-saver. Sand is now a genuine low-luminance cream
  (`#d9c49c`) and Sepia is a **dark** warm amber (`#17120c`); they are now unmistakably
  different. `Sand` remains the only light theme.
- **The panel-collapse arrows pointed the wrong way and the resize grip could steal the
  press (JAG-356).** The arrows now follow the intended semantics — left panel `◀` open /
  `▶` closed, right panel `▶` open / `◀` closed — and the handle takes precedence over the
  column resize grip on the same border (z-index 30 + a `mousedown` guard), so pressing the
  arrow is always a click, never a drag.
- **"Bolder text" did almost nothing (JAG-356).** It only bumped a handful of nodes by 100.
  It is now a real, app-wide weight (body `600` cascades to panels, chat, inputs) with the
  chat bubble forced, so answers visibly change.
- **Removed the redundant Bridge refresh button (JAG-356).** The deck already polls every 5s
  (and a browser reload covers the rest), so the manual button added nothing.
- **Stripped the instructional prose from the GUI (JAG-356).** The multi-sentence "how to"
  paragraphs in the panels and sub-windows (Plan/Tasks, MCP, Models, Keys, Terminal, Memory,
  Browser, the new-session dialog, the tool-policy legend) are gone — the UI is now
  self-explanatory. The **Harness** settings tab keeps its full explanations, by request.
- **Models: an empty provider kind no longer persists as `""`** (falls back to `openai`).

### Added
- **`tests/acceptance/v352_appearance_theme.py` extended to 30 checks** — the six themes, the
  flipped edge-handle arrows, the resize-grip guard, the app-wide bolder text, and that the
  panels stay free of instructional prose while the Harness tab keeps it. Battery stays 114
  (an existing file grew, no new test file).
- **Live cost panel (JAG-355).** The harness already captures the provider's REAL `usage`
  per call; new `costs.py` prices each call (USD per 1M, `[input, output]`) and keeps a
  per-session ledger (`data/costs/<session>.json`), surfaced in a new right-panel **Cost**
  section: session total, tokens in/out, and **one row per API call** (model, time, tokens,
  $), pushed live on a `cost.usage` SSE event so it updates mid-run. Prices come from
  `SPARKFORGE_PRICES`, `config/prices.yaml` (or `config/prices.json`), or the `↻ prices`
  button, which pulls OpenRouter's PUBLIC model catalogue (no key needed) into
  `data/prices.json`. An unpriced model (e.g. a local GGUF) reports `usd: null` — never a
  fake zero. Verified live: a chat turn wrote 3 priced-shape call records (with cached
  tokens) for the local model, correctly `usd: null`. Routes: `GET /api/costs`,
  `POST /api/costs/refresh`, `POST /api/costs/reset`. Guarded by
  `tests/acceptance/v355_themes_donut_costs.py`. Battery 113 → 114.
- **Six eye-saver themes, all differentiated.** Indigo · Dark · Midnight · **Forest** (deep
  muted green) · Sand (low-luminance cream) · Sepia (dark warm amber) — WebUI **and** Bridge.
- **Context donut.** The token breakdown is now an SVG donut (part-to-whole, centre = total
  tokens) with a compact single-column legend, replacing the 8-px stacked micro-bar and its
  wrapping 12-row legend.
- **`tests/acceptance/v355_themes_donut_costs.py`** — the cost-ledger math + refresh parser +
  the donut/theme/cost static guards. Battery 113 → 114.
- **`tests/acceptance/v354_ui_links_pins.py`** — chat file links (relative/external), the pin
  marker, and that compaction never drops the todo list. Battery 112 → 113.
- **Pinned sessions are marked in the rail (JAG-354).** A pinned session (already sorted
  to the top) now shows a 📌 marker and a heavier title in the left panel, so the pin is
  visible without opening the session menu.
- **Accurate positioning + dependency honesty (JAG-354).** The README no longer frames
  SparkForge as "not a meta-harness" (a meta-harness collects *other* harnesses; SparkForge
  is ONE harness whose own sessions are the agents you organise into teams and an org
  chart). The dependency claim is now truthful: the core is stdlib-only, with **PyYAML**
  (pure-Python) as the single third-party import — required only to read the shipped
  `config/*.yaml`, and the tool allowlist stays fail-closed if it is missing.
- **`sessions` tool** (read-only): let any agent — above all the coordinator — inspect
  another session's transcript to understand why a teammate is failing and help it.
  Wired in `registry.TOOL_SCHEMAS` + `tools.py`, enabled in `config/tools.yaml`.
- **`tests/acceptance/v351_android_skill_adb.py`** — a guard that the Android
  build/deploy skill keeps the working DGX→phone ADB guidance (a direct
  `adb connect oneplus-15r:5555`) and the ARM64 `compileSdk 34` rule.
- **Appearance settings (WebUI).** A new Settings → **Appearance** panel with three
  themes — **Indigo** (the house blue/purple), **Dark** (neutral graphite) and
  **Sabbia** (warm Egyptian sand & ochre) — applied pre-paint (no flash) and saved per
  device, plus a **Bolder text** preference. The whole surface is token-driven (panels,
  sidebars, popovers, tinted hovers, scrollbars, ambient gradients), so each theme is
  coherent rather than a background swap. Guarded by
  `tests/acceptance/v352_appearance_theme.py`.
- **Compaction model in the chat model menu.** The topbar `model ▾` picker now carries a
  `⛭ compaction` row: click it to switch the list into *compaction mode* and pin the model
  that summarizes/compacts the transcript (the `summarizer` role, via `POST /api/routing`).
  The same control remains under Settings → Models.
- **Five eye-saver themes, English-named, applied app-wide.** Indigo · Dark · Midnight ·
  Sand · Sepia. `Sand` is now a genuine warm cream (was near-white and too luminous); the
  two new ones are `Midnight` (deep blue-black) and `Sepia` (muted paper). The **Bridge**
  deck (formerly “Orbit”) reads the same per-device choice and is themed too — its hardcoded
  dark bits (background, header, constellation fills/links/labels) are now token-driven.
- **Minimal chrome, border handles.** The two topbar “hide panel” icons are gone; each
  panel now collapses from a **circular arrow handle on its own inner border** (left panel
  ▶ open / ◀ closed, right panel ◀ open / ▶ closed), positioned from the panel rect and
  preserved across resize + the mobile off-canvas behaviour. The composer bar is
  token-driven, so its toolbar text is legible on the light themes.
- **The beta deck is renamed “Bridge”.** “Orbit” made no sense for a mission-control deck;
  the label, the page title/`<h1>` and the API fallback page all read **Bridge** (the route
  `/orbit` is unchanged for link stability).
- **`tests/acceptance/v345_json_extract_props.py`** — a stdlib, seeded property gate
  for `server.extract_json` (400 randomized wrapped values + edge cases + malformed
  input). This closes a real coverage gap: `extract_json` previously had no runnable
  test — its only guard was `tests/properties/test_pure_logic.py`, which needs an
  uninstalled `hypothesis` and never ran. Battery: 104 → 105.

## [1.0.0] — 2026-10-07

The first tagged release. SparkForge is a local-first, stdlib-only agent harness that
**drives one LLM hard** and then runs **its own sessions as a team of agents**. It is a
single harness — not a meta-harness: every agent is one of its sessions, a full harness
instance with its own tools, skills, plan, memory and transcript.

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
