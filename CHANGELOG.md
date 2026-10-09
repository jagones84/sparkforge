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
- **The panel handles drifted off their border (JAG-357).** The app scales the page with CSS
  `zoom` on `<html>` (JAG-283); a fixed element's `left` is multiplied by that zoom while a
  panel's rect is already scaled, so the handle landed ~15% past the edge — and it only
  re-positioned on a *window* resize, so dragging the panel border left it behind. The
  position is now divided by the live zoom, recomputed during the resize drag, on a
  `ResizeObserver` of both panels, and whenever the zoom changes. Verified live: handle
  centre == panel border at rest, mid-drag and after the drag.
- **Collapsing the left panel now shows the active session name in the topbar (JAG-357)** —
  you hide the *panel*, never which session you are in. A collapsed panel also drops its
  resize grip so it cannot sit under the re-open handle.
- **The left arrow was dead at narrow widths (JAG-358).** Two bugs stacked: the drawer CSS
  lived in `@media (max-width: 820px)` while the arrow tested `<= 900`, so between 821–900
  it toggled a class with **no CSS at all**; and the drawer selector used a bare attribute
  (`body.show-left [data-col="sessions"]`), which *loses to the ID rule* `#aside { transform:
  translateX(105%) }`, so even ≤820 the panel never slid in. The CSS now covers `<= 900` and
  targets `#aside`, and the arrow's thresholds match the CSS exactly (sessions 900,
  inspector 1100). Verified live: the drawer opens/closes and the handle lands on its border.
- **Handles could still detach (JAG-358).** Placement trusted `getComputedStyle().zoom`,
  which engines disagree on, and a panel parked off-screen by a `transform` was counted as
  *shown* — flinging its handle past the edge. Placement now calibrates the real scale with a
  one-off probe, treats an element outside the viewport as hidden, and re-glues within a few
  animation frames after any toggle/resize/transition (`_settleHandles`).
- **"Bolder text" off still looked bold (JAG-358).** Many chrome labels ship at `600` in the
  base sheet, so the OFF state was indistinguishable from ON. The OFF state now resets those
  labels to a normal weight, so the switch changes the whole app (chat + labels) both ways.
- **The theme stopped at the app shell (JAG-359).** The Settings window and every popup
  (`#modelMenu`, the folder picker, the skill/diff/mcp windows) were pinned to the indigo dark
  surface (`#0f1320`) and the Harness/Tool-policy cards to raw slate hexes (`#1e293b`), so
  switching to Sand or Sepia left them navy. They now paint with the theme tokens
  (`var(--menubg)` / `--panel` / `--line-2` / `--chipbg`), so the settings panel follows the theme.
- **The topbar read like debug output (JAG-359).** `ctx 41k/127k · 32%` and
  `sandbox: none (by config)` are gone: the context load is now a tiny ring + `%` and the
  sandbox a coloured status dot + one short word, with the full detail moved into the tooltip.
  The context indicator turns **red from 70%** up.
- **Zooming left a gap at the bottom of the screen (JAG-359).** `100dvh` is an absolute unit,
  so the CSS `zoom` on `<html>` scaled it and the shell only covered `zoom × viewport` (~15%
  gap at 0.85, worse zoomed out, and overflow when zoomed in). The body height is now
  `calc(100dvh / var(--zoom))` and `applyZoom` publishes `--zoom`, so the shell fills the real
  viewport at every level (verified: body == viewport at 0.7 / 0.85 / 1.3 / 1.0).

- **The theme STILL stopped at a few surfaces (JAG-360).** After the settings window itself was
  themed, the MCP JSON textarea stayed near-black (`#0b0f18`), the toasts + the session menu
  stayed dark gray (`rgba(24,28,40,.97)`), and ~25 hover/active/chip fills kept the indigo blue
  (`rgba(108,140,255,…)` / `rgba(120,140,255,…)` / `rgba(139,123,240,…)`) — including the
  scrollbar thumb. They all resolve through theme tokens now (`--panel2` / `--menubg` /
  `--hover` / `--sel` / `--hl` / `--chipbg` / `--scroll`), so switching to Sand or Sepia
  re-paints the WHOLE UI.
- **The panel arrow was unreliable (JAG-360).** The toggle fired on the native `click`, which a
  press-and-hold, a 1-2 px wobble, or the resize grip sharing the same border could all
  swallow. It now toggles on POINTER UP with an ≤8px movement guard and a pointer capture, so a
  hold is exactly one click and small movements never cancel it.
- **Widening a side panel crushed the chat (JAG-360).** The panels were `flex: 0 0 <w>` (never
  shrink) with their width persisted to localStorage — a saved `618 + 773` in a ~1200px window
  squeezed the centre column to a sliver (hence the wrapped composer). The panels are now
  `flex: 0 1 <w>` with a 150px floor, the centre column has a hard `min-width: 420px`, and the
  drag + save maths run in CSS px, so a wide panel (or a narrow window) can no longer starve
  the chat.
- **Defaults (JAG-360):** the theme is indigo and bolder text is OFF out of the box.

- **The side rail could no longer edit the rules (JAG-361).** The editable Rules panel lived
  only in Settings, while the side rail had a Role-only pane with no file paths. There is now
  ONE complete **Rules** section: the per-session role, the GLOBAL
  `~/.config/sparkforge/RULES.md` and the PROJECT `<ws>/.sparkforge/RULES.md`, each with its
  real absolute path, the `AGENTS.md` addenda that are ALSO loaded, and an in-place editor +
  save. (`loadRole()` is kept as an alias so every call site still works.)
- **Cost was only ever an estimate (JAG-361).** When the provider reports the charge itself it
  is now used verbatim — OpenRouter returns the billed USD in `usage.cost` (with a
  `cost_details` breakdown), so no arithmetic is involved (`src: "provider"`). Otherwise the
  REAL token counts are priced with the full rate set: the cache-read rate for cached tokens
  (instead of the full input rate) plus the fixed per-request fee. Each row states which it is
  (the UI prefixes an estimate with `≈`, the panel header says "exact" / "estimated").
- **Touching a panel's inner border shrank it (JAG-361).** The panels had become `flex: 0 1`
  while the chat's `flex-basis: auto` still ate the free space, so the first pixel of a drag
  redistributed a few px. The panels are fixed-width again and an explicit budget clamp
  (`_panelRoom` / `_fitPanels`, chat floor 420px) protects the centre column instead: verified
  a +20px drag moves the panel exactly 20px and a huge drag stops at the 420px floor.
- **Duplicate `id="ctxPct"` (JAG-361).** The topbar element added in JAG-359 shadowed the
  inspector's meter (`getElementById` returns the first), so the inspector % never updated. The
  topbar one is now `#ctxPctTop`; the inspector reads its real percentage again.
- **Interface polish (JAG-361):** a hidden `#nowbar` no longer keeps rendering; the
  pick / paste-text / voice-help / skill / diff modals get the same border + radius + shadow as
  the rest of the app; `a.ghost` is actually styled; buttons gain a hover and a real disabled
  state; the dot-rail restores its focus ring; the undefined `--line2` token (which killed the
  session-menu border) is fixed; `#qmode` no longer forces a dark native popup on light themes;
  and the hardcoded light-blue id labels use `--acc2`.

- **Every agent looked identical to the model (JAG-362).** The `agent-role` prompt section only
  rendered the per-session `ROLE.md`, so the ~90% of agents with no ROLE.md yet contributed
  **nothing** and their own roster name/label never reached the prompt at all (33 agents, 3 role
  files — the other 30 were a void, which is why "role.md equal for all agents"). The section now
  always announces the agent identity (`You are A7 — coder (coding agent).`) and appends the
  ROLE.md when it is set. The three role-ish things are one story now: the roster `role` is a
  short **label** (UI only, never the prompt), the session `ROLE.md` **is** this prompt section,
  and the standing `RULES.md` (global + project) is the section right below it.
- **You can now see WHICH agent you are and WHERE its text comes from (JAG-362).** The Rules
  panel gained an identity line — `A7 · coder · coding agent — agent identity (roster); the role
  text below is this agent's ROLE.md`, or "ad-hoc session" when the session is not designated.
- **A long-lived tab could hide a GUI fix silently (JAG-362).** A cheap `GET /api/build`
  fingerprint is polled (at boot, every 60s, and on focus/visibility); when the served app
  changes, the tab reloads itself, so a fix is never buried behind a tab opened hours ago.
- **The topbar chips now read like the rest of the UI (JAG-362).** The sandbox pill says what it
  means — `sandboxed` / `no sandbox`, with the backend and the requested mode in the tooltip —
  and the ctx `%` is a ring + label matching the other header chips.

- **Clicking a panel's border shifted the panel (JAG-363).** The resize strip started resizing on
  the raw `mousedown`, so the 1–3px of pointer travel that any physical click carries became a
  1–3px panel move (and a press-and-hold did the same). The resize now engages only once the
  pointer really travels (**> 4px**), and it maps the full delta from there — so a click or a hold
  is a dead no-op, a drag tracks the cursor exactly (verified live: click 0px, 2px wobble 0px,
  drag +10/+30/−10 = exactly +10/+30/−10), and a plain click no longer persists a width.

- **A queued message now shows its attachments (JAG-364).** A message typed while a turn is
  running is queued as `{raw, text, atts}`, and the queue chip shows the text you typed plus a
  marker for what it carries — `🖼 2 images · 📄 1 file · 📝 1 text` — instead of the raw blob
  (skipping the model-only attachment block). Steering and flushing send the raw payload but
  display the human text.
- **A theme sets the TEXT colours, not just the background (JAG-364).** Each theme card now
  previews its own text colour (`Aa`) and accent on the swatch, and the text/colour surfaces
  that were hardcoded are token-driven now: the code blocks and inline code in a reply, the todo
  statuses, the session running/done rings, the queue-dropdown options, and the ghost/copy hover
  borders — all follow the active theme (Sand included).
- **Chat links to a SIBLING project now open (JAG-364).** A relative link like
  `sparkpulse-server/status_server.py` failed with "not a file" because it was only resolved
  inside the session workspace (`Repositories/TESTS/Jago`). `_resolve_fs_arg` now resolves a
  relative path against the workspace **and each of its ancestors** that stays inside a browse
  root (bounded to 12 levels), so a link to a sibling project under `Repositories/` resolves to
  the real file. Verified live: the link opened `/home/jagones/Repositories/sparkpulse-server/status_server.py`.
- **The context breakdown is a list of horizontal bars (JAG-364).** Instead of a wrapping legend
  of words, each category is now a horizontal bar coloured exactly like its donut segment, sorted
  big → small, with a short label (`sys instr`, `tool out`, `harness`, …) so the bars get the
  width; the full label, token count and % stay in the tooltip. The donut is kept above it.

- **The Bridge agent prompts were VOID — now filled from `agency-agents` (JAG-365).** The roster
  was seeded from the local `agency-agents` clone, but the seed stored only the short LABEL
  (`agents.json.role`); the agent's role PROMPT (the clone's `.md` body) was never written, so the
  Bridge `✎ prompt` editor AND the main-app ROLE.md opened empty for all 30 seeded agents. The new
  `sparkforge.agency` module reads the clone and `scripts/seed_agent_roles.py` materialises each
  agent's body into `data/roles/<session>.md` — the SAME file both UIs read, so the Bridge prompt
  and the main-app ROLE.md are now identical. `scripts/seed_teams.py` calls it after seeding, so a
  seeded agent is never left without its role. Non-destructive: only an EMPTY role is filled
  (`--force` overwrites), so a role you wrote is never clobbered. Applied live: **30 roles filled**
  (the 3 custom agents — Master, coder 1/2 — kept their own).

- **The context PREVIEW understated the system prompt by thousands of tokens (JAG-366).** The
  dry-run `context_engine.preview()` sized its budget, compaction and "messages that fit" maths
  against the legacy monolithic `server.SYSTEM_PROMPT` (~64 tokens) instead of the REAL
  section-registry prompt that `assemble_turn()` sends. The preview therefore LIED about what
  would be sent. `preview()` now calls `server._system_prompt(sess)` (with a dry-run fallback
  that can never raise) and reports `system_prompt_tokens`.
- **The WebUI overflowed on a phone — the JS read a stale `window.innerWidth` (JAG-366).** The
  app's overlay thresholds (`_overlayLeft`/`_overlayRight` and the "is this panel shown" test) and
  the editor dock's overlay decision + both drag clamps read `window.innerWidth`, which can be
  stale under device emulation / the visual viewport / zoom, while the CSS media queries use the
  LAYOUT viewport (`document.documentElement.clientWidth`). Emulated at 390×844 the `#editorDock`
  stayed ~1039px wide and the page scrolled sideways (scrollWidth 1438 vs clientWidth 390). Both
  `webui/index.html` and `webui/assets/editor.js` now resolve the viewport through a shared
  `_vw() = document.documentElement.clientWidth || window.innerWidth`, so the JS thresholds and
  the CSS overlays can never disagree. The `width=device-width, initial-scale=1,
  viewport-fit=cover` meta is asserted as well.
- **The Bridge agent prompt was VOID while the primary UI showed the same ROLE.md (JAG-367).**
  In the Bridge (`/orbit`) the `✎ prompt` box opened EMPTY even though the SAME `ROLE.md` the
  primary Inspector § Role shows had content (the JAG-365 backfill). Root cause: the box loads the
  role ASYNC, but `render()`'s anti-poll dirty-guard — added to protect an in-progress edit from
  the 5 s table refresh — ALSO blocked the LOAD render: the textarea still held `""` while
  `openText` became the fetched text, so `roleDirty` was true and the box was never filled. JAG-365
  merely EXPOSED this latent race (before it, the fetched text was `""` too, so nothing diverged).
  The fetched role is now written straight into the textarea (with an `open !== sid` guard against
  a stale response). Verified live on the Bridge: the editor shows the EXACT ROLE.md (e.g. 15 455
  chars == the API response), i.e. the Bridge prompt and the primary UI are finally identical.
- **On a phone the WebUI clipped its right edge (JAG-367).** The desktop
  `[data-col="chat"] { min-width: 420px }` floor forced the page wider than the screen — measured
  on the REAL Pixel 8: visual viewport 363 px but the layout was forced to 420 px — and
  `body{overflow-x:hidden}` then CUT the right edge (the send button and the 5th tab were partly
  unreachable). A `@media (max-width: 900px) { [data-col="chat"] { min-width: 0; } }` override now
  drops that floor. It sits AFTER the base rule on purpose: same specificity, so source order is
  what lets it win (the first attempt put it in the earlier `max-width:900` block and lost).
  Verified on the device via CDP: `scrollWidth == clientWidth == 363`, the send button and all five
  tabs (`chat/sessions/tasks/context/feed`) now fully visible.

### Added
- **`src/sparkforge/agency.py` + `scripts/seed_agent_roles.py` (JAG-365)** — map an org agent
  NAME to its role prompt in the local `agency-agents` clone (`by_name`, `role_for`,
  `fill_roles`) and backfill `data/roles/<sid>.md`, non-destructively. `v341_team_seed` grew four
  checks (Q1–Q4) to lock the materialised role + the no-clobber guarantee. Battery stays 119.
- **`tests/acceptance/v364_queue_theme_links_ctx.py` (28 checks)** — a queued message carries its
  attachments and the chip shows the text + a marker (not the raw blob); every theme previews its
  text + accent colour and no hardcoded status text colour survives; `_resolve_fs_arg` walks the
  workspace ancestors so a SIBLING-project link resolves (with a real temp-dir check that a
  workspace-local path still wins and a missing path falls back); the context breakdown is sorted
  horizontal bars with short labels (the donut is kept); and (E1–E4) the app + editor dock resolve
  the viewport through `document.documentElement.clientWidth`, the viewport meta is mobile-ready,
  and on a phone the chat column drops its desktop 420 px floor (no right-edge clip).
  Battery 118 → 119. (`v354_ui_links_pins` gained B7: the preview reports the REAL system prompt;
  `v292_roles` gained two checks: the Orbit prompt editor writes the fetched ROLE.md into the
  textarea and no longer depends on a re-render the poll guard can block.)
- **`tests/acceptance/v362_agent_identity.py` (12 checks)** — every designated agent announces
  its roster identity in the `agent-role` prompt section even with no ROLE.md (and two agents
  get DIFFERENT sections), the ROLE.md is appended under the identity, a plain session still
  contributes nothing, the Rules panel states the agent identity (with the "ad-hoc session"
  fallback), the server exposes the `/api/build` fingerprint the SPA self-reloads on, and the
  sandbox pill says what it means. Battery 117 → 118.
- **`tests/acceptance/v361_rules_cost_polish.py` (16 checks)** — the single complete Rules
  panel (sources + paths + the right backend per scope), the exact-vs-estimated cost path
  (provider cost verbatim, cache-read rate + per-request fee, unknown stays null), the richer
  price cache, the `#ctxPct` duplicate-id fix and the polish guards. Battery 116 → 117.
- **`tests/acceptance/v360_shell_fixes.py` (14 checks)** — no indigo literal survives
  (`#0b0f18` / `rgba(24,28,40` / the blue tints), the settings + popups + MCP textarea +
  scrollbars resolve through theme tokens, the handle toggles on pointer-up with a movement
  guard (no native `onclick`), the chat keeps its `min-width: 420px` while the panels stay
  shrinkable, and the defaults are indigo + no bolder text. Battery 115 → 116.
- **`tests/acceptance/v352_appearance_theme.py` extended to 38 checks** — the six themes, the
  flipped edge-handle arrows, the resize-grip guard, the app-wide bolder text (and its OFF
  baseline), that the panels stay free of instructional prose while the Harness tab keeps it,
  and (K1–K7) that the handles re-glue on resize and on zoom, a collapsed panel drops its
  grip, an off-screen panel is not treated as shown, the toggle thresholds match the CSS
  overlays, and the topbar carries the active session name both when the panel is collapsed
  and when it is parked off screen. Battery stays 114 (an existing file grew, no new file).
- **`tests/acceptance/v359_theme_shell.py` (13 checks)** — every popup paints with a theme
  token (none left on `#0f1320`/`#1e293b`), the topbar ctx/sandbox indicators are the ring +
  status-dot graphics with the 70% red threshold, and the shell height is divided by the live
  zoom. Battery 114 → 115 (a new file).
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
