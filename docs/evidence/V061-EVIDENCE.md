# SparkForge v0.6.1 — evidence (JAG-48)

Chat SSE stream terminates after `done`: the generator is exhausted and the
socket is closed; keep-alive stays a `/api/feed`-only privilege.

Date: 2026-09-29T21:34:21+02:00 · build: v0.6.1 · live: `127.0.0.1:8790`

## Regression baseline (pre-fix code, same harness)

With the v0.6 code, an upstream that stalls mid-stream (no `[DONE]`, socket
held open) left the chat stream open forever — `ss -tn` ESTAB, client waiting
for EOF. Only A4 fails; the healthy-mock case hid the bug.

```
FAIL A4 stalled upstream: chat stream still terminates and closes
   status=HTTP/1.0 200 OK events=3 deltas=0 done=0 error=0 ping=0 done_at=MISSING eof_at=NO-EOF close_after_done=n/a wall=90.15s (upstream held open, no [DONE])
==== 5/6 checks passed (0 skipped) ====
```

After the fix the same scenario ends normally: the partial answer is kept and
`done` closes the stream in ~6 s (`ROUTER_IDLE_TIMEOUT`), never ESTAB forever.

## Command + output (fixed)

```
$ python3 tests/v061_stream_close.py --live
SparkForge v0.6.1 stream-close acceptance (JAG-48) — test port=8796 live=http://127.0.0.1:8790 token=set

PASS A0 mock router + test instance up
   base=http://127.0.0.1:8796 mock=<Popen: returncode: None args: ['/usr/bin/python3', '/home/jagones/Repositor...>
   req 1: status=HTTP/1.0 200 OK events=9 deltas=1 done=1 error=0 ping=0 done_at=0.34s eof_at=0.34s close_after_done=0.00s  wall=0.34s
   req 2: status=HTTP/1.0 200 OK events=7 deltas=1 done=1 error=0 ping=0 done_at=0.11s eof_at=0.11s close_after_done=0.00s  wall=0.11s
   req 3: status=HTTP/1.0 200 OK events=7 deltas=1 done=1 error=0 ping=0 done_at=0.11s eof_at=0.11s close_after_done=0.00s  wall=0.11s

PASS A1 mock: 3/3 chat streams closed after `done` (<= 2.0s, same session)
   3/3 closed | req1 done=0.34s eof=0.34s Δ=0.00s | req2 done=0.11s eof=0.11s Δ=0.00s | req3 done=0.11s eof=0.11s Δ=0.00s | session=v061-close-d105fc

PASS A2 chat SSE has no keep-alive filler (ping=0)
   pings per request=[0, 0, 0] (keep-alive is /api/feed only)

PASS A3 no socket left ESTAB on the chat port after the 3 streams
   ss -tn | grep 8796 -> 0 ESTAB
(no rows)

PASS A5 /api/feed keeps its keep-alive (socket still open after 3.5s)
   bytes=83754 lines=['HTTP/1.0 200 OK', 'Server: SparkForge/0.6.1 Python/3.12.3', 'Date: Tue, 29 Sep 2026 19:34:24 GMT']

PASS A4 stalled upstream: chat stream still terminates and closes
   status=HTTP/1.0 200 OK events=5 deltas=1 done=1 error=0 ping=0 done_at=6.25s eof_at=6.25s close_after_done=0.00s wall=6.25s (upstream held open, no [DONE])
   selfcheck: version=0.6.1 model_loaded=True router=True
   req 1: status=HTTP/1.0 200 OK events=100 deltas=95 done=1 error=0 ping=0 done_at=14.66s eof_at=14.66s close_after_done=0.00s  wall=14.66s
   req 2: status=HTTP/1.0 200 OK events=65 deltas=60 done=1 error=0 ping=0 done_at=17.66s eof_at=17.66s close_after_done=0.00s  wall=17.66s
   req 3: status=HTTP/1.0 200 OK events=38 deltas=33 done=1 error=0 ping=0 done_at=10.54s eof_at=10.54s close_after_done=0.00s  wall=10.54s

PASS B1 live: 3/3 chat streams closed after `done` (<= 2.0s, same session)
   3/3 closed | req1 done=14.66s eof=14.66s Δ=0.00s | req2 done=17.66s eof=17.66s Δ=0.00s | req3 done=10.54s eof=10.54s Δ=0.00s | session=v061-close-live-089636

PASS B2 no socket left ESTAB on the live chat port
   ss -tn | grep 8790 -> 0 ESTAB
(no rows)

==== 8/8 checks passed (0 skipped) ====
```

## What changed

- **`server.py` — `sse_pump`**: drains the producer queue and always ends with
  exactly one terminal `done`; the producer thread dying without its sentinel
  ends the stream too, and an idle timeout ends a silent stream (`error` +
  `done`). Chat/agent streams use it → no `: ping` filler.
- **`server.py` — `sse_response(handler, gen, keepalive=False)` / `sse_close`**:
  after the generator ends the write side is flushed and shut down
  (`SHUT_WR` → FIN) and the connection is marked non-reusable, so clients
  waiting for EOF (`curl -N`, the mobile app) are released immediately.
  `SO_KEEPALIVE` is set only when `keepalive=True` — i.e. `/api/feed` and the
  blackboard watcher, which are loopback tails that stay open on purpose.
- **`server.py` — `_router_stream`**: `_set_read_idle` bounds the silence of an
  in-flight router stream (`SPARKFORGE_ROUTER_IDLE_TIMEOUT`, default 120 s); the
  partial answer is kept instead of hanging the run.
- **`tests/mock_router.py`**: `--stall-after N` / `--stall-seconds S` reproduce
  the stalled-upstream case deterministically.
- **`tests/v061_stream_close.py`**: acceptance — 3 sequential streams on the
  same session (mock + live), all closed within the budget, no ESTAB sockets,
  no keep-alive filler on chat, `/api/feed` still keep-alive.

Env knobs: `SPARKFORGE_ROUTER_IDLE_TIMEOUT` (120 s),
`SPARKFORGE_CHAT_STREAM_IDLE` (900 s), `SPARKFORGE_CLOSE_BUDGET` (2 s).
