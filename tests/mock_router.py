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

STATE = {"loaded": False, "load_start": None, "fail_503": 0, "warm_seconds": 2}
ALIAS = "mock-alpha"
LOCK = threading.Lock()


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
            stream = body.get("stream")
            if not stream:
                return self._json(200, {"choices": [{"message": {
                    "role": "assistant", "content": "pong"}}]})
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            for tok in ("po", "ng"):
                chunk = {"choices": [{"delta": {"content": tok}}]}
                self.wfile.write(("data: %s\n\n" % json.dumps(chunk)).encode())
                self.wfile.flush()
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
            return
        return self._json(404, {"error": {"message": "not found"}})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8099)
    ap.add_argument("--warm-seconds", type=float, default=2.0)
    ap.add_argument("--fail-503", type=int, default=0)
    a = ap.parse_args()
    STATE["warm_seconds"] = a.warm_seconds
    STATE["fail_503"] = a.fail_503
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), H)
    print("mock router on %d (warm=%ss, fail503=%d)" % (a.port, a.warm_seconds, a.fail_503),
          flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
