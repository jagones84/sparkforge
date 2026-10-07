# WAYFORWARD (minor) — Stalled-turn watchdog

Status: **PLANNED — NOT IMPLEMENTED.** This file records the design only. Do not
build it until requested.

## 1. Problem

A chat turn can get stuck (the router call never returns, or the worker wedges).
Today nothing notices automatically: the session keeps a trailing `user` message
with no reply and the WebUI looks "stuck". The only existing recoveries are:

- `reconcile` (JAG-262/263): closes **orphan** turns — i.e. sessions with NO live
  turn — used at startup and on demand by the agent;
- the manual **⏹ stop** button (`POST /api/chat/abort`);
- the keepgoing wall-clock cap (`max_wall_secs`, default 3600s), which only fires
  if the agent loop is actually looping.

None of these catches "a single turn that is genuinely alive but making no
progress", without a human clicking stop.

## 2. Non-goals / hard safety rules

- **NEVER restart the service.** The watchdog runs in-process only. (The original
  incident was caused by a service restart killing a live turn — do not repeat it.)
- **NEVER touch a session that is not actively running.** Idle sessions are
  irrelevant to the watchdog.
- **NEVER touch a healthy, progressing turn.** Only a turn that is BOTH alive AND
  silent for the whole window is a candidate.
- Abort **one turn**, not the process, not other sessions.

## 3. Design

### 3.1 Progress signal

`_ACTIVE_CHAT[sid]` already exists and holds `{"ev0": <feed seq at turn start>, "ts": ...}`.
Extend it with a `last_progress` timestamp that is **touched on every feed event
for that session**:

- in `publish(kind, **data)` (server.py), after recording the event:
  if `data.get("session")` is an active chat, set
  `_ACTIVE_CHAT[sid]["last_progress"] = time.time()`.

The chat loop already emits `chat.delta`/`chat.run`/`harness.inject`/`graph.node.updated`
continuously, so a working turn refreshes `last_progress` every few hundred ms.

### 3.2 Watchdog loop

A daemon thread started once at boot (next to `providers.warm()`), polling every
`N` seconds:

```
for sid, info in list(_ACTIVE_CHAT.items()):
    idle = now - info.get("last_progress", info["ts"])
    if idle >= T:                     # alive but silent for the whole window
        abort_turn(sid, reason="watchdog: no progress for %ds" % T)
```

- `abort_turn(sid, reason)`: reuse the SAME path the ⏹ stop button uses
  (`POST /api/chat/abort` semantics) so the loop stops, `ensure_reply_persisted`
  writes an explicit assistant notice, and `_ACTIVE_CHAT.pop(sid)` runs in the
  worker's `finally`.
- After abort, the orphan (if any) is closed by the existing reconcile logic.

### 3.3 Config knobs (config/tools.yaml, `runtime:`)

- `watchdog_enabled: true|false` (default: false until validated)
- `watchdog_poll_secs: 30` — how often the loop scans.
- `watchdog_stall_secs: 300` — `T`, no-progress window before aborting.

All three overridable via `SPARKFORGE_*` env for tests.

## 4. Why this is safe (the user's exact concern)

A session that is working emits feed events → `last_progress` keeps advancing →
`idle < T` → never touched. A session that is idle is not in `_ACTIVE_CHAT` → never
touched. Only a turn that is in `_ACTIVE_CHAT` AND silent for the full window is
aborted, and only that one turn. No process restart, no cross-session effect.

## 5. Test plan (`tests/v264_watchdog.py`, deterministic, no network)

- With `watchdog_stall_secs` tiny, an `_ACTIVE_CHAT` entry whose `last_progress`
  is stale is aborted exactly once, and a persisted assistant notice appears.
- An `_ACTIVE_CHAT` entry that is being "touched" (progress advancing) is NOT
  aborted while the loop runs.
- A session not in `_ACTIVE_CHAT` is never aborted.
- The watchdog never spawns a restart (assert the function makes no service call).

## 6. Open questions

- Abort vs. keep-and-warn: for a very slow but legitimate model, `T` must be
  generous (>= the slowest expected first-token latency). Consider a first-token
  grace: reset the clock when the first delta arrives.
- Should the watchdog also cover agent runs (`api_v02.RUNS`) that are not chat
  turns? Out of scope for the minor version.
