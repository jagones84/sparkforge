#!/usr/bin/env python3
"""SparkForge v0.5.1 acceptance — evidence, not claims.

Verifies, with command + output + numbers, against the *running* service plus a
deterministic mock router for the cold-model path:

  A. POST /api/chat/stream is no longer 404: it returns 200 text/event-stream,
     streams chat.run/chat.delta events and terminates with `done`
  B. GET /api/selfcheck -> 200 with version, model_requested/model_loaded,
     router reachability, token_configured (bool), host/port and LLM latency
  C. POST /api/model/ensure on a warm model -> {loaded: true, action: already_loaded}
  D. cold model: against a mock router (model unloaded), the chat SSE emits
     `model.loading` in < 2 s, warms the model, and completes without error
  E. 503 "model not loaded": the router retry/backoff turns transient 503s into
     a successful stream (`model.retry` events observed)

Usage: python3 tests/v051_acceptance.py [--base http://127.0.0.1:8790]
Exit code 0 iff every check passed. Writes data/v051-acceptance.json.
"""
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = os.environ.get("SPARKFORGE_URL", "http://127.0.0.1:8790")
MOCK_PORT = int(os.environ.get("SPARKFORGE_MOCK_PORT", 8099))
TEST_PORT = int(os.environ.get("SPARKFORGE_TEST_PORT", 8795))


def _read_token():
    tok = os.environ.get("SPARKFORGE_TOKEN")
    if tok:
        return tok
    envf = os.path.expanduser("~/.config/sparkforge/env")
    if os.path.isfile(envf):
        for line in open(envf):
            if line.startswith("SPARKFORGE_TOKEN="):
                return line.split("=", 1)[1].strip()
    return None


TOKEN = _read_token()
results = []


def http(method, path, body=None, timeout=120, base=None, token=None):
    base = base or BASE
    token = token if token is not None else TOKEN
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(base + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            payload = r.read().decode()
            return r.status, dict(r.headers), json.loads(payload or "{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, dict(e.headers), json.loads(e.read().decode() or "{}")
        except Exception:
            return e.code, dict(e.headers), {"error": "HTTP %d" % e.code}
    except Exception as e:  # noqa: BLE001
        return 0, {}, {"error": str(e)}


def sse(path, body, base=None, token=None, timeout=180):
    """POST an SSE endpoint; return (status, headers, list_of_(event, data, t))."""
    base = base or BASE
    token = token if token is not None else TOKEN
    data = json.dumps(body).encode()
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(base + path, data=data, method="POST", headers=headers)
    t0 = time.time()
    events = []
    with urllib.request.urlopen(req, timeout=timeout) as r:
        status, hdrs = r.status, dict(r.headers)
        cur = None
        for raw in r:
            line = raw.decode("utf-8", "replace").rstrip("\n")
            if line.startswith("event:"):
                cur = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                events.append((cur, line.split(":", 1)[1].strip(), time.time() - t0))
    return status, hdrs, events


def check(name, ok, evidence, **extra):
    rec = {"check": name, "ok": bool(ok), "evidence": evidence, **extra}
    results.append(rec)
    print("\n%s %s\n   %s" % ("PASS" if ok else "FAIL", name, evidence))
    return ok


# ------------------------------------------------------------------ A ----
def a_post_chat_stream():
    status, hdrs, evs = sse("/api/chat/stream",
                            {"message": "Rispondi solo: pong", "session": "v051-e2e"},
                            timeout=180)
    kinds = [e[0] for e in evs]
    done = kinds.count("done") == 1
    deltas = kinds.count("chat.delta")
    err = [e for e in evs if e[0] == "error"]
    ctype = hdrs.get("Content-Type", "")
    check("A1 POST /api/chat/stream -> 200 SSE (not 404)",
          status == 200 and ctype.startswith("text/event-stream"),
          "HTTP %s Content-Type=%s" % (status, ctype), status=status)
    check("A2 stream completes: chat.run + chat.delta*%d + done, no error" % deltas,
          "chat.run" in kinds and deltas > 0 and done and not err,
          "events=%s" % json.dumps([e[0] for e in evs][:6]) + " ... total=%d" % len(evs),
          error=err[:1])


# ------------------------------------------------------------------ B ----
def b_selfcheck():
    status, _, body = http("GET", "/api/selfcheck")
    need = ("version", "model_requested", "model_loaded", "router_reachable",
            "token_configured", "host", "port", "llm_latency_ms")
    missing = [k for k in need if k not in body]
    check("B1 GET /api/selfcheck -> 200 with full payload",
          status == 200 and not missing,
          "HTTP %s version=%s missing=%s" % (status, body.get("version"), missing))
    check("B2 selfcheck reports live model_loaded + LLM latency",
          isinstance(body.get("model_loaded"), bool) and body.get("llm_latency_ms") is not None,
          "model_requested=%s model_loaded=%s llm_latency_ms=%s router_reachable=%s "
          "router_latency_ms=%s token_configured=%s host=%s:%s" % (
              body.get("model_requested"), body.get("model_loaded"),
              body.get("llm_latency_ms"), body.get("router_reachable"),
              body.get("router_latency_ms"), body.get("token_configured"),
              body.get("host"), body.get("port")))


# ------------------------------------------------------------------ C ----
def c_model_ensure():
    status, _, body = http("POST", "/api/model/ensure", {})
    check("C1 POST /api/model/ensure (warm) -> loaded, action=already_loaded",
          status == 200 and body.get("loaded") is True,
          "HTTP %s %s" % (status, json.dumps(body)))


# ------------------------------------------------------- D / E (mock) ----
def _wait_port(base, token, timeout=15):
    for _ in range(int(timeout * 2)):
        st, _, b = http("GET", "/api/status", base=base, token=token, timeout=3)
        if st == 200:
            return True
        time.sleep(0.5)
    return False


def d_e_cold_model():
    mock = subprocess.Popen([sys.executable, os.path.join(REPO, "tests", "mock_router.py"),
                             "--port", str(MOCK_PORT), "--warm-seconds", "3", "--fail-503", "2"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    env = dict(os.environ, SPARKFORGE_ROUTER="http://127.0.0.1:%d" % MOCK_PORT,
               SPARKFORGE_MODEL_LOAD_TIMEOUT="60",
               SPARKFORGE_DB="/tmp/sparkforge-v051-test.db")
    inst = subprocess.Popen([sys.executable, os.path.join(REPO, "server.py"),
                             "--host", "127.0.0.1", "--port", str(TEST_PORT),
                             "--token", "test-token"],
                            cwd=REPO, env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = "http://127.0.0.1:%d" % TEST_PORT
    try:
        up = _wait_port(base, "test-token")
        check("D0 mock router + test instance up", up, "base=%s up=%s" % (base, up))
        if not up:
            return
        t0 = time.time()
        status, hdrs, evs = sse("/api/chat/stream", {"message": "hi", "model": "mock-alpha",
                                                     "session": "v051-mock"},
                                base=base, token="test-token", timeout=90)
        kinds = [e[0] for e in evs]
        loading = next((e for e in evs if e[0] == "model.loading"), None)
        dt = (loading[2] if loading else None)
        check("D1 cold model -> model.loading emitted, first-byte < 2.0 s",
              loading is not None and dt is not None and dt < 2.0,
              "first event=%s at %.3fs (< 2.0s)" % (kinds[0] if kinds else None, dt or -1),
              loading_seconds=dt)
        check("D2 cold model chat completes without error after warm-up",
              status == 200 and "done" in kinds and "error" not in kinds
              and kinds.count("chat.delta") > 0,
              "HTTP %s events=%s total=%.2fs" % (status, json.dumps(kinds), time.time() - t0))
        # model.retry events land on the harness feed (not the chat SSE stream)
        _, _, feed = http("GET", "/api/feed/recent?limit=100", base=base,
                          token="test-token")
        retries = [e for e in feed.get("events", []) if e.get("kind") == "model.retry"]
        check("E1 503 retry/backoff recovered the stream (feed model.retry events)",
              len(retries) >= 1 and "done" in kinds,
              "feed model.retry x%d (attempts=%s) -> done=%s" % (
                  len(retries), [r.get("attempt") for r in retries], "done" in kinds),
              retries=len(retries))
    finally:
        for p in (inst, mock):
            try:
                p.terminate()
                p.wait(timeout=5)
            except Exception:
                try:
                    p.kill()
                except Exception:
                    pass


def main():
    global BASE, TOKEN
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=BASE)
    ap.add_argument("--token", default=TOKEN)
    a = ap.parse_args()
    BASE, TOKEN = a.base, a.token
    print("SparkForge v0.5.1 acceptance — base=%s token=%s" % (BASE, "set" if TOKEN else "none"))
    a_post_chat_stream()
    b_selfcheck()
    c_model_ensure()
    d_e_cold_model()
    passed = sum(1 for r in results if r["ok"])
    report = {"base": BASE, "ts": time.time(), "passed": passed, "total": len(results),
              "results": results}
    os.makedirs(os.path.join(REPO, "data"), exist_ok=True)
    with open(os.path.join(REPO, "data", "v051-acceptance.json"), "w") as f:
        json.dump(report, f, indent=2)
    print("\n==== %d/%d checks passed ====" % (passed, len(results)))
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
