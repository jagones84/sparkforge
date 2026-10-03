# SparkForge v0.5.1 — raw evidence (JAG-43)

Scope: `docs/PLAN.md` §A (chat/LLM server wave). Repo
`/home/jagones/Repositories/sparkforge`, live service `sparkforge.service`
on `127.0.0.1:8790`, router `127.0.0.1:8080`. Everything below is command +
output + numbers, verbatim.

## 0. Diagnosis before the change

```
POST /api/chat        -> 200 (reply ok, 6.69 s)
GET  /api/chat/stream -> 200 SSE (first byte 0.02 s; events chat.run/delta/done)
POST /api/chat/stream -> 404
no auth               -> 401
```

## 1. `POST /api/chat/stream` is no longer 404

```
$ curl -sN -X POST -H "Authorization: Bearer <t>" -H 'Content-Type: application/json' \
    -d '{"message":"di solo: pong","session":"v051-test"}' \
    http://127.0.0.1:8790/api/chat/stream -D - | head -5
HTTP/1.0 200 OK
Server: SparkForge/0.5.1 Python/3.12.3
Content-Type: text/event-stream
Cache-Control: no-store

: stream open

event: chat.run
data: {"run_id": "a40af536ea2e"}

event: chat.delta
data: {"session": "v051-test", "channel": "think", "text": "We"}
...
event: chat.delta
data: {"session": "v051-test", "channel": "answer", "text": "pong"}

event: done
data: {}
```

## 2. `GET /api/selfcheck` → 200 with model + latency

```
$ curl -s -H "Authorization: Bearer <t>" http://127.0.0.1:8790/api/selfcheck
{
  "service": "sparkforge",
  "version": "0.5.1",
  "status": "ok",
  "model_requested": "nex-n25-mini-uncensored-q8",
  "model_loaded": true,
  "model_loaded_alias": "nex-n25-mini-uncensored-q8",
  "models": [ ... 7 aliases, 1 loaded ... ],
  "router": "http://127.0.0.1:8080",
  "router_reachable": true,
  "router_latency_ms": 0.6,
  "router_status": "ok",
  "llm_latency_ms": 165.5,
  "token_configured": true,
  "auth_required": true,
  "host": "127.0.0.1",
  "port": 8790,
  "check_seconds": 0.17
}
```

## 3. `POST /api/model/ensure` (idempotent warm-up)

```
$ curl -sX POST -H "Authorization: Bearer <t>" -H 'Content-Type: application/json' \
    -d '{}' http://127.0.0.1:8790/api/model/ensure
{"model": "nex-n25-mini-uncensored-q8", "loaded": true,
 "action": "already_loaded", "seconds": 0.0}          # HTTP 200
```

## 4. Real cold-model warm-up (live router, real alias)

`nex-n25-mini-uncensored-q8` was unloaded on the live router
(`POST :8080/models/unload {"model": "..."}` → `{"success":true}`), then a chat
stream was opened on the *real* SparkForge:

```
$ python3 - <<'PY'   # opens POST /api/chat/stream, timestamps each SSE event
model.loading @ 0.048s
model.ready   @ 42.132s
total events: 5 | kinds: ['chat.delta', 'chat.run', 'done', 'model.loading', 'model.ready']
first event chat.run @ 0.039s
done      @ 43.778s
errors: []
PY
```

- `model.loading` reached the client in **0.048 s (< 2 s)** ✔
- the 36 GB model really loaded in **42.1 s**, then the answer streamed to
  `done` at **43.778 s** with **0 errors** ✔

## 5. `tests/v051_acceptance.py` — 9/9

```
PASS A1 POST /api/chat/stream -> 200 SSE (not 404)
   HTTP 200 Content-Type=text/event-stream
PASS A2 stream completes: chat.run + chat.delta*34 + done, no error
PASS B1 GET /api/selfcheck -> 200 with full payload
   HTTP 200 version=0.5.1 missing=[]
PASS B2 selfcheck reports live model_loaded + LLM latency
   model_requested=nex-n25-mini-uncensored-q8 model_loaded=True llm_latency_ms=133.9
   router_reachable=True router_latency_ms=0.6 token_configured=True host=127.0.0.1:8790
PASS C1 POST /api/model/ensure (warm) -> loaded, action=already_loaded
   HTTP 200 {"model": "nex-n25-mini-uncensored-q8", "loaded": true, ...}
PASS D0 mock router + test instance up
PASS D1 cold model -> model.loading emitted, first-byte < 2.0 s
   first event=chat.run at 0.201s (< 2.0s)
PASS D2 cold model chat completes without error after warm-up
   HTTP 200 events=["chat.run","model.loading","model.ready","chat.delta","chat.delta","done"] total=4.29s
PASS E1 503 retry/backoff recovered the stream (feed model.retry events)
   feed model.retry x4 (attempts=[1, 1, 1, 1]) -> done=True
==== 9/9 checks passed ====
```

Checks D/E run against `tests/mock_router.py` (a deterministic router stand-in:
cold model + injected `503 model not loaded`) so the warm-up and retry paths are
reproducible without a 36 GB load or a GPU.

## 6. Regressions (unchanged build)

```
tests/v02_acceptance.py -> 8/8
tests/v03_acceptance.py -> 7/7
tests/v04_acceptance.py -> 17/17
```

## 7. Acceptance criteria

| Criterion | Result |
|---|---|
| cold model → SSE `model.loading` < 2 s, chat completes without error | ✅ 0.048 s loading, `done` @ 43.778 s, 0 errors |
| `POST /api/chat/stream` is no longer 404 | ✅ 200 `text/event-stream` |
| `GET /api/selfcheck` → 200 with `model_loaded` and latency | ✅ `model_loaded=true`, `llm_latency_ms=165.5` |
| retry/backoff on 503 model-not-loaded | ✅ `model.retry` events, stream recovers |
| e2e script with output | ✅ `tests/v051_acceptance.py` 9/9 |
