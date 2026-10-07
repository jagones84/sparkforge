#!/usr/bin/env python3
"""A tiny llama.cpp-router stand-in for v0.5.1 warm-up evidence.

Implements just enough of the router surface for the SparkForge warm-up and
retry paths to be exercised deterministically (no giant GGUF, no GPU):

  GET  /health               -> {"status":"ok"}
  GET  /v1/models            -> roster with a single alias, `loaded` flips to
                                true `--warm-seconds` after POST /models/load
  POST /models/load          -> {"status":"loading"} and starts the warm-up clock
  POST /v1/chat/completions  -> 503 until warmed; then `--fail-503` extra 503s
                                (to prove retry/backoff) before streaming SSE.

Usage: python3 tests/mock_router.py [--port 8099] [--warm-seconds 2] [--fail-503 0]
"""
import argparse
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

STATE = {"loaded": False, "load_start": None, "fail_503": 0, "warm_seconds": 2,
         "stall_after": None, "stall_seconds": 0.0}
ALIAS = "mock-alpha"
LOCK = threading.Lock()

# JAG-65: the chat loop asks the model to author the task list INLINE as a
# harness action (`write_todos`); it is emitted ONCE, then the mock answers in
# plain prose — exactly how a real harness-driven model behaves.
TODOS_ACTION = ('{"action":"write_todos","todos":['
                '{"label":"Raccogliere il testo della richiesta","deps":[]},'
                '{"label":"Estrarre i requisiti e i vincoli","deps":[0]},'
                '{"label":"Produrre il piano finale verificato","deps":[1]}]}')
# a re-plan asks only for the steps still missing → return distinct new steps
REPLAN_TEXT = (
    '{"tool":"write_todos"}\n'
    '{"label":"Registrare l esito della verifica","status":"todo","deps":[]}\n'
    '{"label":"Notificare il risultato finale","status":"todo","deps":[0]}\n'
)
TODOS_TEXT = TODOS_ACTION


def _is_todo_call(body):
    for m in body.get("messages") or []:
        c = m.get("content") or ""
        if "write_todos" in c:
            return True
    return False


def _todo_answer(body):
    """Inline task-list action on the first call, prose afterwards.

    A re-plan request (system prompt says the list "already contains" labels)
    gets the distinct NDJSON 'missing' steps instead.
    """
    msgs = body.get("messages") or []
    if any(m.get("role") == "assistant" and '"write_todos"' in (m.get("content") or "")
           for m in msgs):
        return "pong"
    text = "\n".join((m.get("content") or "") for m in msgs)
    if "already contains" in text or "already has these nodes" in text:
        return REPLAN_TEXT
    return TODOS_TEXT


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _is_loaded(self):
        with LOCK:
            if STATE["load_start"] and time.time() - STATE["load_start"] >= STATE["warm_seconds"]:
                STATE["loaded"] = True
            return STATE["loaded"]

    def do_GET(self):
        if self.path.startswith("/health"):
            return self._json(200, {"status": "ok"})
        if self.path.startswith("/v1/models") or self.path.startswith("/models"):
            st = "loaded" if self._is_loaded() else "unloaded"
            return self._json(200, {"object": "list", "data": [
                {"id": ALIAS, "object": "model", "owned_by": "llamacpp",
                 "status": {"value": st}}]})
        return self._json(404, {"error": {"message": "not found"}})

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(n).decode() or "{}")
        except Exception:
            body = {}
        if self.path.startswith("/models/load"):
            if self._is_loaded():
                return self._json(400, {"error": {"message": "model is already running"}})
            with LOCK:
                STATE["load_start"] = time.time()
            return self._json(200, {"status": "loading"})
        if self.path.startswith("/v1/chat/completions"):
            if not self._is_loaded():
                return self._json(503, {"error": {"message": "model not loaded"}})
            with LOCK:
                if STATE["fail_503"] > 0:
                    STATE["fail_503"] -= 1
                    return self._json(503, {"error": {"message": "model not loaded"}})
            text = _todo_answer(body) if _is_todo_call(body) else "pong"
            stream = body.get("stream")
            if not stream:
                return self._json(200, {"choices": [{"message": {
                    "role": "assistant", "content": text}}]})
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            # stream in small chunks so downstream incremental parsing is exercised
            toks = [text[i:i + 7] for i in range(0, len(text), 7)] or [""]
            # --stall-after N: emit N deltas, then hold the response open (no
            # [DONE], no close) — the JAG-48 "upstream stalls mid-stream" case.
            stall = STATE["stall_after"]
            for i, tok in enumerate(toks):
                if stall is not None and i >= stall:
                    time.sleep(STATE["stall_seconds"] or 600)
                    return
                chunk = {"choices": [{"delta": {"content": tok}}]}
                self.wfile.write(("data: %s\n\n" % json.dumps(chunk)).encode())
                self.wfile.flush()
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
            return
        return self._json(404, {"error": {"message": "not found"}})


def main():
    global TODOS_TEXT
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8099)
    ap.add_argument("--warm-seconds", type=float, default=2.0)
    ap.add_argument("--fail-503", type=int, default=0)
    ap.add_argument("--todos", default=None,
                    help="NDJSON write_todos answer (default: 3-step MULTI_STEP)")
    ap.add_argument("--stall-after", type=int, default=None,
                    help="emit N deltas then hold the stream open, no [DONE] (JAG-48)")
    ap.add_argument("--stall-seconds", type=float, default=0.0,
                    help="how long the stalled stream is held (0 = forever)")
    a = ap.parse_args()
    STATE["warm_seconds"] = a.warm_seconds
    STATE["fail_503"] = a.fail_503
    STATE["stall_after"] = a.stall_after
    STATE["stall_seconds"] = a.stall_seconds
    if a.todos is not None:
        TODOS_TEXT = a.todos.replace("\\n", "\n")
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), H)
    print("mock router on %d (warm=%ss, fail503=%d)" % (a.port, a.warm_seconds, a.fail_503),
          flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
