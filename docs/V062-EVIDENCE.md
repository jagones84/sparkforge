# SparkForge v0.6.2 — evidence (JAG-51)

`chat: nessuna richiesta senza risposta` — every request on a session persists
exactly one `user` + one `assistant` message (the reply, or an explicit error
turn). A session can never end on an orphan `user` message.

Date: 2026-09-29 · build: v0.6.2 · live: `127.0.0.1:8790` (restarted on the fix)

## The bug (evidence from the report)

```
$ python3 -c "import json;d=json.load(open('data/sessions/dc65e66e9b3d.json'));\
print(len(d['messages']), [m['role'] for m in d['messages']])"
1 ['user']                      # "di solo: due" → one user turn, NO assistant
$ python3 -c "import json;d=json.load(open('data/sessions/4aeb78d13ee1.json'));\
print(len(d['messages']), [m['role'] for m in d['messages']])"
4 ['user', 'assistant', 'user', 'assistant']   # multi-turn contrasting proof
```

## Regression baseline (pre-fix code, same scenario)

Same command, same 3 requests on one session, router unreachable — old tree
checked out in a worktree (`git worktree add /tmp/sf-prefix bc41baf`, v0.6.1):

```
$ for i in 1 2 3; do curl -s -X POST localhost:8799/api/chat -H 'Authorization: Bearer test-token' \
    -H 'Content-Type: application/json' -d "{\"message\":\"prefix req $i\",\"session\":\"prefix-orphan\"}"; done
{"error": "router call failed: <urlopen error [Errno 111] Connection refused>"}
{"error": "router call failed: <urlopen error [Errno 111] Connection refused>"}
{"error": "router call failed: <urlopen error [Errno 111] Connection refused>"}

$ python3 -c "..."   # data/sessions/prefix-orphan.json
messages=3
  user 'prefix req 1'
  user 'prefix req 2'
  user 'prefix req 3'
orphan_user_messages=1
```

3 requests → **3 messages, 0 assistant** — the reported bug reproduced.
(Also: the pre-fix 502 body carried neither `session` nor `run_id`, so the
client could not even tell which transcript was broken.)

## Command + output (fixed, identical scenario)

```
$ python3 tests/v062_session_persistence.py --live
SparkForge v0.6.2 session-persistence acceptance (JAG-51) — test port=8797 live=yes

PASS A0 mock router + test instance up
   base=http://127.0.0.1:8797 mock=8097 sessions_dir=/tmp/sparkforge-v062-sessions

PASS A0b chat model warmed (POST /api/model/ensure) for the one-shot path
   ensure -> loaded=true
   A1 session=v062-post-b2887a statuses=[200, 200, 200] replies=['pong', 'pong', 'pong']

PASS A1 3x POST /api/chat on one session -> 6 messages (3 user + 3 assistant)
   statuses=[200, 200, 200] replies=['pong', 'pong', 'pong'] | history total=6 (user=3 assistant=3 errors=0)
   roles=['user', 'assistant', 'user', 'assistant', 'user', 'assistant'] | roles alternate=True
   GET req 1: done=1 error=0 deltas=1
   GET req 2: done=1 error=0 deltas=1
   GET req 3: done=1 error=0 deltas=1

PASS A2 3x GET /api/chat/stream on one session -> 6 messages (3 user + 3 assistant)
   history total=6 (user=3 assistant=3 errors=0) roles=['user', 'assistant', 'user', 'assistant', 'user', 'assistant']
   POST stream req 1: done=1 error=0 deltas=1
   POST stream req 2: done=1 error=0 deltas=1
   POST stream req 3: done=1 error=0 deltas=1

PASS A3 3x POST /api/chat/stream (alias) -> 6 messages (3 user + 3 assistant)
   history total=6 (user=3 assistant=3 errors=0) roles=['user', 'assistant', 'user', 'assistant', 'user', 'assistant']

PASS A4 three distinct sessions stay independent (2 messages each)
   sessions=['36d99a', 'f2a01d', 'c3a630'] -> total=2 (user=1 assistant=1) each

   -- messaggi per sessione (data/sessions/<id>.json) --
      v062-get-eb1e1b          messages=6 (user=3 assistant=3 error_turns=0) last=assistant
      v062-multi-36d99a        messages=2 (user=1 assistant=1 error_turns=0) last=assistant
      v062-multi-c3a630        messages=2 (user=1 assistant=1 error_turns=0) last=assistant
      v062-multi-f2a01d        messages=2 (user=1 assistant=1 error_turns=0) last=assistant
      v062-post-b2887a         messages=6 (user=3 assistant=3 error_turns=0) last=assistant
      v062-postpatch-06cc2c    messages=6 (user=3 assistant=3 error_turns=0) last=assistant

PASS A5 on-disk scan: no transcript ends on an orphan `user` message (0 orphans)
   6 transcripts, 3 with 6 messages (3 user + 3 assistant), orphans=none

PASS B0 failing-router instance up
   base=http://127.0.0.1:8798 router=http://127.0.0.1:8098 (nothing listens)
   B1 statuses=[502, 502, 502]
   B1 error turns=[{'role': 'assistant', 'error': True, 'detail': '<urlopen error [Errno 111] Connection refused>'} x3]

PASS B1 router down: 3x POST /api/chat -> 502 + 6 messages (3 user + 3 error assistant)
   statuses=[502, 502, 502] | history total=6 (user=3 assistant=3 errors=3)
   roles=['user', 'assistant', 'user', 'assistant', 'user', 'assistant']
   B2 stream req 1: status=HTTP/1.0 200 OK events=3 error=1 done=1
   B2 stream req 2: status=HTTP/1.0 200 OK events=3 error=1 done=1
   B2 stream req 3: status=HTTP/1.0 200 OK events=3 error=1 done=1

PASS B2 router down: 3x GET /api/chat/stream -> `error` event + 6 messages (3+3)
   streams error_events=[1, 1, 1] | history total=6 (user=3 assistant=3 errors=3)

   -- messaggi per sessione (data/sessions/<id>.json) --
      v062-err-post-e97686     messages=6 (user=3 assistant=3 error_turns=3) last=assistant
      v062-err-stream-0237bd   messages=6 (user=3 assistant=3 error_turns=3) last=assistant
      v062-get-eb1e1b          messages=6 (user=3 assistant=3 error_turns=0) last=assistant
      v062-multi-36d99a        messages=2 (user=1 assistant=1 error_turns=0) last=assistant
      v062-multi-c3a630        messages=2 (user=1 assistant=1 error_turns=0) last=assistant
      v062-multi-f2a01d        messages=2 (user=1 assistant=1 error_turns=0) last=assistant
      v062-post-b2887a         messages=6 (user=3 assistant=3 error_turns=0) last=assistant
      v062-postpatch-06cc2c    messages=6 (user=3 assistant=3 error_turns=0) last=assistant

PASS B3 on-disk scan after failures: 0 orphan transcripts, 2 error transcripts (3 error turns each)
   8 transcripts, 2 with 3 user + 3 error assistant, orphans=none

PASS C1 live: 3x POST /api/chat -> 6 messages (3 user + 3 assistant)
   statuses=[200, 200, 200] | history total=6 (user=3 assistant=3 errors=0)
   roles=['user', 'assistant', 'user', 'assistant', 'user', 'assistant']

==== 12/12 checks passed ====
```

Live transcript behind C1 (real model `nex-n25-mini-uncensored-q8`):

```
$ curl -s "localhost:8790/api/history?session=v062-live-c47f39" -H "Authorization: Bearer $TOKEN" | python3 -c "..."
1 user      'live req 1'
2 assistant 'Live req 1 received.'
3 user      'live req 2'
4 assistant 'Live req 2 received.'
5 user      'live req 3'
6 assistant 'Live req 3 received.'
total=6
```

## Failure path, before/after (same router-down scenario)

```
$ python3 -c "..."  # fixed v0.6.2 — /tmp/prefix-fixed-sessions/prefix-orphan.json
messages=6
  user 'prefix req 1' error=False
  assistant '⚠️ errore: <urlopen error [Errno 111] Connect' error=True
  user 'prefix req 2' error=False
  assistant '⚠️ errore: <urlopen error [Errno 111] Connect' error=True
  user 'prefix req 3' error=False
  assistant '⚠️ errore: <urlopen error [Errno 111] Connect' error=True
orphan_user_messages=0
$ curl -s -X POST localhost:8799/api/chat -d '{"message":"prefix req 1","session":"prefix-orphan"}'
{"error":"router call failed: ...","session":"prefix-orphan","run_id":"2d776aec57f1","stored_error":true}
```

| scenario (3 requests, same session) | v0.6.1 (bc41baf) | v0.6.2 |
|---|---|---|
| happy path, `/api/chat` | 6 (3+3) | **6 (3+3)** |
| happy path, `/api/chat/stream` | 6 (3+3) | **6 (3+3)** |
| router down, `/api/chat` | 3 (3+**0**) orphan | **6 (3+3 error turns)** |
| router down, `/api/chat/stream` | 3 (3+**0**) orphan | **6 (3+3 error turns)** |
| `502` body | `{error}` | `{error, session, run_id, stored_error:true}` |
| SSE failure event | `{error}` | `{error, session, stored:true}` |

## Regression suites (same fix, live v0.6.2)

```
$ python3 tests/v051_acceptance.py   → ==== 9/9 checks passed ====
$ python3 tests/v061_stream_close.py → ==== 6/6 checks passed (0 skipped) ====
$ python3 tests/v06_taskgraph.py     → ==== 15/15 checks passed (0 skipped) ====
$ python3 tests/v062_session_persistence.py --live → ==== 12/12 checks passed ====
$ curl -s localhost:8790/api/selfcheck -H "Authorization: Bearer $TOKEN"
  {'version': '0.6.2', 'status': 'ok', 'model_loaded': True, 'router_reachable': True, 'host': '0.0.0.0', 'port': 8790}
```

## What changed

- **`server.py` — session invariant**: `session_mark(sess)` (index captured
  *before* the request's `user` message) + `ensure_reply_persisted(sess, since,
  error=…)` (appends the explicit error turn — `role:"assistant"`, `error:true`,
  `error_detail` — only if that request produced no assistant message;
  idempotent, so `except` + `finally` never double-write).
- **`server.py` — `POST /api/chat`**: on a router failure the error turn is
  persisted *before* the `502`, which now carries `{session, run_id,
  stored_error:true}`; the success body adds `messages` + `error`.
- **`server.py` — `GET|POST /api/chat/stream`**: `chat_stream_gen(sess, message,
  model, mark)` persists the error turn on any worker failure (and emits
  `error {error, session, stored:true}`); a `finally` safety net covers the pump
  giving up while the producer is already gone. The caller passes `mark`.
- **`server.py` — `chat_once`**: an empty model answer is stored as an explicit
  error turn instead of a silent blank assistant message.
- **`api_v02.py` — MCP `chat` tool**: same contract (error turn persisted,
  `{stored_error:true}` returned).
- **`server.py` — `SPARKFORGE_SESSIONS_DIR`**: session store is overridable so
  tests run on scratch transcripts (`/tmp`) instead of the live store.
- **Docs**: README §*v0.6.2* + §*session parameter contract* and docstrings on
  `Handler`, `chat_once`, `chat_stream_gen` (`session` omitted / unknown /
  existing → created / created-with-that-id / appended; 2N messages after N
  requests).
- **`tests/v062_session_persistence.py`**: 12 acceptance checks (mock + live),
  including an on-disk scan of every transcript for orphan `user` turns.
