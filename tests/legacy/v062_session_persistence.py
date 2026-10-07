#!/usr/bin/env python3
"""SparkForge v0.6.2 acceptance — JAG-51: nessuna richiesta senza risposta.

Bug: `data/sessions/dc65e66e9b3d.json` held one single `user` message and no
assistant turn (orphan request). Evidence, not claims — every check prints the
per-session message count read back from `GET /api/history?session=`:

  A. deterministic (own instance on SPARKFORGE_TEST_PORT + tests/mock_router.py):
     A1 POST /api/chat x3 on the SAME session -> 6 messages (3 user + 3 assistant)
        and roles strictly alternate user,assistant,user,assistant,user,assistant
     A2 GET /api/chat/stream x3 on the SAME session -> 6 messages (3+3)
     A3 POST /api/chat/stream (alias) x3 on the SAME session -> 6 messages (3+3)
     A4 three DIFFERENT sessions are independent (2 messages each) — no bleed
  B. failure path (instance pointed at a dead router port):
     B1 POST /api/chat x3 -> 502 + 6 messages (3 user + 3 assistant error turns),
        every assistant turn has error=true / error_detail set
     B2 GET /api/chat/stream x3 -> `error` SSE event + 6 messages (3+3),
        no orphan user message in the transcript
  C. live service (--live): A1 against the real model on 127.0.0.1:8790.

Usage: python3 tests/v062_session_persistence.py [--base URL] [--live]
Exit code 0 iff every executed check passed. Report: data/v062-acceptance.json
"""
import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BASE = os.environ.get("SPARKFORGE_URL", "http://127.0.0.1:8790")
MOCK_PORT = int(os.environ.get("SPARKFORGE_MOCK_PORT", 8097))
TEST_PORT = int(os.environ.get("SPARKFORGE_TEST_PORT", 8797))
DEAD_PORT = int(os.environ.get("SPARKFORGE_DEAD_PORT", 8798))
DEAD_MOCK_PORT = int(os.environ.get("SPARKFORGE_DEAD_MOCK_PORT", 8098))

results = []


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


def check(name, ok, evidence, **extra):
    rec = {"check": name, "ok": bool(ok), "evidence": evidence, **extra}
    results.append(rec)
    print("\n%s %s\n   %s" % ("PASS" if ok else "FAIL", name, evidence))
    return ok


# -------------------------------------------------------------- HTTP client --
def api(base, token, path, payload=None, method=None, timeout=120):
    """JSON GET/POST helper -> (status, body)."""
    data = None
    headers = {"Authorization": "Bearer " + token} if token else {}
    if payload is not None:
        data = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(base + path, data=data, headers=headers,
                                 method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw or "{}")
        except Exception:  # noqa: BLE001
            return e.code, {"error": raw}
    except Exception as e:  # noqa: BLE001
        return 0, {"error": str(e)}


def sse(base, token, message, session, model=None, timeout=120.0, method="GET"):
    """GET/POST one chat SSE stream over a raw socket, read until EOF."""
    p = urllib.parse.urlparse(base)
    host, port = p.hostname, p.port or 80
    body = None
    if method == "POST":
        body = json.dumps({"message": message, "session": session}).encode()
        path = "/api/chat/stream"
        headers = {"Accept": "text/event-stream", "Content-Type": "application/json",
                   "Content-Length": str(len(body))}
    else:
        qs = urllib.parse.urlencode({"message": message, "session": session,
                                     **({"model": model} if model else {})})
        path = "/api/chat/stream?" + qs
        headers = {"Accept": "text/event-stream"}
    headers["Host"] = "%s:%d" % (host, port)
    if token:
        headers["Authorization"] = "Bearer " + token
    req = "%s %s HTTP/1.1\r\n" % (method, path)
    req += "".join("%s: %s\r\n" % (k, v) for k, v in headers.items()) + "\r\n"
    sock = socket.create_connection((host, port), timeout=10)
    sock.settimeout(timeout)
    buf = b""
    try:
        sock.sendall(req.encode())
        if body:
            sock.sendall(body)
        while True:
            data = sock.recv(65536)
            if not data:
                break
            buf += data
    except socket.timeout:
        pass
    finally:
        sock.close()
    text = buf.decode("utf-8", "replace")
    kinds = [l.split(":", 1)[1].strip() for l in text.splitlines() if l.startswith("event:")]
    return {"status": text.split("\r\n", 1)[0] if text else "NO RESPONSE",
            "deltas": kinds.count("chat.delta"), "done": kinds.count("done"),
            "error": kinds.count("error"), "events": len(kinds)}


def history(base, token, session):
    st, body = api(base, token, "/api/history?" + urllib.parse.urlencode({"session": session}))
    msgs = body.get("messages") or []
    roles = [m.get("role") for m in msgs]
    return st, msgs, roles


def count_summary(msgs, roles):
    return {"total": len(msgs), "user": roles.count("user"),
            "assistant": roles.count("assistant"),
            "errors": sum(1 for m in msgs if m.get("error"))}


def fmt(msgs, roles):
    c = count_summary(msgs, roles)
    return ("total=%d (user=%d assistant=%d errors=%d) roles=%s"
            % (c["total"], c["user"], c["assistant"], c["errors"], roles))


def alternating(roles, n_pairs):
    """True iff roles == [user, assistant] * n_pairs (no orphan user message)."""
    want = ["user", "assistant"] * n_pairs
    return roles[:len(want)] == want


# ------------------------------------------------------------ A: happy path --
def repeat_post_chat(base, token, session, label, n=3):
    sts = []
    for i in range(1, n + 1):
        st, body = api(base, token, "/api/chat",
                       {"message": "%s req %d" % (label, i), "session": session})
        sts.append({"req": i, "status": st, "reply": (body.get("reply") or "")[:24],
                    "messages": body.get("messages"),
                    "error": bool(body.get("error"))})
    return sts


def warm_up(base, token):
    """Warm the chat model first (the mock router is cold until /models/load).

    `POST /api/chat` is one-shot and does *not* wait for a cold model, so the
    happy-path checks warm the alias explicitly — the documented flow.
    """
    st, body = api(base, token, "/api/model/ensure", {})
    print("   warm-up: status=%s loaded=%s action=%s" % (st, body.get("loaded"), body.get("action")))
    return st == 200 and body.get("loaded") is True


def part_a(base, token):
    session = "v062-post-%s" % uuid.uuid4().hex[:6]
    sts = repeat_post_chat(base, token, session, "post")
    st, msgs, roles = history(base, token, session)
    c = count_summary(msgs, roles)
    print("   A1 session=%s statuses=%s replies=%s"
          % (session, [s["status"] for s in sts], [s["reply"] for s in sts]))
    check("A1 3x POST /api/chat on one session -> 6 messages (3 user + 3 assistant)",
          st == 200 and all(s["status"] == 200 for s in sts) and c["errors"] == 0
          and all(s["reply"] for s in sts)
          and c["total"] == 6 and c["user"] == 3 and c["assistant"] == 3
          and alternating(roles, 3),
          "statuses=%s replies=%s | history %s | roles alternate=%s"
          % ([s["status"] for s in sts], [s["reply"] for s in sts],
             fmt(msgs, roles), alternating(roles, 3)),
          session=session, counts=c)

    session = "v062-get-%s" % uuid.uuid4().hex[:6]
    for i in range(1, 4):
        r = sse(base, token, "get req %d" % i, session, method="GET")
        print("   GET req %d: done=%d error=%d deltas=%d" % (i, r["done"], r["error"], r["deltas"]))
    st, msgs, roles = history(base, token, session)
    check("A2 3x GET /api/chat/stream on one session -> 6 messages (3 user + 3 assistant)",
          st == 200 and len(msgs) == 6 and alternating(roles, 3),
          "history %s | roles alternate=%s" % (fmt(msgs, roles), alternating(roles, 3)),
          session=session, counts=count_summary(msgs, roles))

    session = "v062-postpatch-%s" % uuid.uuid4().hex[:6]
    for i in range(1, 4):
        r = sse(base, token, "post-stream req %d" % i, session, method="POST")
        print("   POST stream req %d: done=%d error=%d deltas=%d" % (i, r["done"], r["error"], r["deltas"]))
    st, msgs, roles = history(base, token, session)
    check("A3 3x POST /api/chat/stream (alias) -> 6 messages (3 user + 3 assistant)",
          st == 200 and len(msgs) == 6 and alternating(roles, 3),
          "history %s | roles alternate=%s" % (fmt(msgs, roles), alternating(roles, 3)),
          session=session, counts=count_summary(msgs, roles))

    sessions = ["v062-multi-%s" % uuid.uuid4().hex[:6] for _ in range(3)]
    for s in sessions:
        api(base, token, "/api/chat", {"message": "hello", "session": s})
    counts = []
    for s in sessions:
        _st, m, r = history(base, token, s)
        counts.append(fmt(m, r))
    ok = all("total=2 (user=1 assistant=1" in c for c in counts)
    check("A4 three distinct sessions stay independent (2 messages each)",
          ok, "sessions=%s -> %s" % ([s[-6:] for s in sessions], counts),
          counts=counts)
    return [session]


# ----------------------------------------------------------- B: error paths --
def part_b(base, token):
    session = "v062-err-post-%s" % uuid.uuid4().hex[:6]
    sts = []
    for i in range(1, 4):
        st, body = api(base, token, "/api/chat", {"message": "err req %d" % i, "session": session})
        sts.append({"req": i, "status": st, "stored_error": body.get("stored_error"),
                    "run_id": bool(body.get("run_id")), "error": (body.get("error") or "")[:40]})
    st, msgs, roles = history(base, token, session)
    c = count_summary(msgs, roles)
    detail = [{"role": m.get("role"), "error": bool(m.get("error")),
               "detail": (m.get("error_detail") or "")[:60]} for m in msgs]
    print("   B1 statuses=%s" % [s["status"] for s in sts])
    print("   B1 error turns=%s" % [d for d in detail if d["role"] == "assistant"])
    check("B1 router down: 3x POST /api/chat -> 502 + 6 messages (3 user + 3 error assistant)",
          all(s["status"] == 502 for s in sts) and c["total"] == 6 and c["user"] == 3
          and c["assistant"] == 3 and c["errors"] == 3 and alternating(roles, 3),
          "statuses=%s | history %s | error_detail=%r"
          % ([s["status"] for s in sts], fmt(msgs, roles),
             (msgs[1].get("error_detail") or "")[:70]),
          session=session, counts=c, statuses=sts)

    session = "v062-err-stream-%s" % uuid.uuid4().hex[:6]
    rows = []
    for i in range(1, 4):
        r = sse(base, token, "err stream %d" % i, session, method="GET")
        rows.append(r)
        print("   B2 stream req %d: status=%s events=%d error=%d done=%d"
              % (i, r["status"], r["events"], r["error"], r["done"]))
    st, msgs, roles = history(base, token, session)
    c = count_summary(msgs, roles)
    check("B2 router down: 3x GET /api/chat/stream -> `error` event + 6 messages (3+3)",
          all(r["error"] >= 1 for r in rows) and c["total"] == 6 and c["user"] == 3
          and c["assistant"] == 3 and c["errors"] == 3 and alternating(roles, 3),
          "streams error_events=%s | history %s" % ([r["error"] for r in rows], fmt(msgs, roles)),
          session=session, counts=c)
    return [session]


def _wait_port(base, token, tries=40):
    for _ in range(tries):
        st, _ = api(base, token, "/api/status", timeout=5)
        if st == 200:
            return True
        time.sleep(0.5)
    return False


def _spawn(base_port, router, sessions_dir, extra_env=None, token="test-token"):
    env = dict(os.environ, SPARKFORGE_ROUTER=router,
               SPARKFORGE_GRAPH_DIR="/tmp/sparkforge-v062-graphs",
               SPARKFORGE_DB="/tmp/sparkforge-v062-test.db",
               SPARKFORGE_SESSIONS_DIR=sessions_dir,
               SPARKFORGE_MODEL_LOAD_TIMEOUT="60",
               SPARKFORGE_ROUTER_RETRIES="0", SPARKFORGE_ROUTER_BACKOFF="0",
               **(extra_env or {}))
    return subprocess.Popen([sys.executable, os.path.join(REPO, "server.py"),
                             "--host", "127.0.0.1", "--port", str(base_port),
                             "--token", token],
                            cwd=REPO, env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _stop(*procs):
    for p in procs:
        p.terminate()
    for p in procs:
        try:
            p.wait(timeout=5)
        except Exception:  # noqa: BLE001
            p.kill()


def orphan_scan(sessions_dir):
    """Read every transcript on disk — the bug's own evidence format.

    Returns (rows, orphans) where `rows` is [{id, messages, user, assistant,
    errors, last_role}] and `orphans` the ids whose last message is a `user`
    turn (exactly the `dc65e66e9b3d.json` shape: "1 only message ('user', …)
    SENZA assistant").
    """
    rows, orphans = [], []
    for fn in sorted(os.listdir(sessions_dir)):
        if not fn.endswith(".json"):
            continue
        try:
            s = json.load(open(os.path.join(sessions_dir, fn)))
        except Exception:  # noqa: BLE001
            continue
        msgs = s.get("messages") or []
        roles = [m.get("role") for m in msgs]
        row = {"id": s.get("id") or fn[:-5], "messages": len(msgs),
               "user": roles.count("user"), "assistant": roles.count("assistant"),
               "errors": sum(1 for m in msgs if m.get("error")),
               "last_role": roles[-1] if roles else None}
        rows.append(row)
        if row["last_role"] == "user":
            orphans.append(row["id"])
    return rows, orphans


def log_session_table(sessions_dir):
    """Acceptance evidence: message count per session (the bug's evidence format)."""
    rows, orphans = orphan_scan(sessions_dir)
    print("\n   -- messaggi per sessione (data/sessions/<id>.json) --")
    for r in rows:
        print("      %-24s messages=%d (user=%d assistant=%d error_turns=%d) last=%s"
              % (r["id"], r["messages"], r["user"], r["assistant"], r["errors"], r["last_role"]))
    return rows, orphans


def main():
    global BASE, TOKEN
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=BASE)
    ap.add_argument("--token", default=TOKEN)
    ap.add_argument("--live", action="store_true", help="also run A1 against the live service")
    a = ap.parse_args()
    BASE, TOKEN = a.base, a.token
    print("SparkForge v0.6.2 session-persistence acceptance (JAG-51) — test port=%d live=%s"
          % (TEST_PORT, "yes" if a.live else "no"))

    sessions_dir = "/tmp/sparkforge-v062-sessions"
    shutil.rmtree(sessions_dir, ignore_errors=True)  # this run's transcripts only
    mock = subprocess.Popen([sys.executable, os.path.join(REPO, "tests", "mock_router.py"),
                             "--port", str(MOCK_PORT), "--warm-seconds", "0"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    inst = _spawn(TEST_PORT, "http://127.0.0.1:%d" % MOCK_PORT, sessions_dir)
    base = "http://127.0.0.1:%d" % TEST_PORT
    try:
        if not _wait_port(base, "test-token"):
            check("A0 mock router + test instance up", False, "no /api/status on %s" % base)
        else:
            check("A0 mock router + test instance up", True,
                  "base=%s mock=%s sessions_dir=%s" % (base, MOCK_PORT, sessions_dir))
            check("A0b chat model warmed (POST /api/model/ensure) for the one-shot path",
                  warm_up(base, "test-token"), "ensure -> loaded=true")
            part_a(base, "test-token")
            rows, orphans = log_session_table(sessions_dir)
            six = [r for r in rows if r["messages"] == 6]
            check("A5 on-disk scan: no transcript ends on an orphan `user` message (0 orphans)",
                  len(orphans) == 0 and len(six) == 3,
                  "%d transcripts, %d with 6 messages (3 user + 3 assistant), orphans=%s"
                  % (len(rows), len(six), orphans or "none"),
                  sessions=[r["id"] for r in rows])
    finally:
        _stop(inst, mock)

    # --- B: router unreachable (hard failure path) ---
    dead = _spawn(DEAD_PORT, "http://127.0.0.1:%d" % DEAD_MOCK_PORT, sessions_dir)
    base = "http://127.0.0.1:%d" % DEAD_PORT
    try:
        if not _wait_port(base, "test-token"):
            check("B0 failing-router instance up", False, "no /api/status on %s" % base)
        else:
            check("B0 failing-router instance up", True,
                  "base=%s router=http://127.0.0.1:%d (nothing listens)" % (base, DEAD_MOCK_PORT))
            part_b(base, "test-token")
            rows, orphans = log_session_table(sessions_dir)
            err_rows = [r for r in rows if r["errors"] == 3 and r["messages"] == 6]
            check("B3 on-disk scan after failures: 0 orphan transcripts, 2 error transcripts (3 error turns each)",
                  len(orphans) == 0 and len(err_rows) == 2,
                  "%d transcripts, %d with 3 user + 3 error assistant, orphans=%s"
                  % (len(rows), len(err_rows), orphans or "none"),
                  sessions=[r["id"] for r in rows])
    finally:
        _stop(dead)

    if a.live:
        if not _wait_port(BASE, TOKEN):
            check("C0 live service reachable", False, "%s unreachable" % BASE)
        else:
            session = "v062-live-%s" % uuid.uuid4().hex[:6]
            sts = repeat_post_chat(BASE, TOKEN, session, "live")
            _st, msgs, roles = history(BASE, TOKEN, session)
            check("C1 live: 3x POST /api/chat -> 6 messages (3 user + 3 assistant)",
                  len(msgs) == 6 and alternating(roles, 3),
                  "statuses=%s | history %s" % ([s["status"] for s in sts], fmt(msgs, roles)),
                  session=session)

    executed = [r for r in results if not r.get("skipped")]
    passed = sum(1 for r in executed if r["ok"])
    report = {"base": BASE, "ts": time.time(), "passed": passed,
              "total": len(executed), "results": results}
    os.makedirs(os.path.join(REPO, "data"), exist_ok=True)
    with open(os.path.join(REPO, "data", "v062-acceptance.json"), "w") as f:
        json.dump(report, f, indent=2)
    print("\n==== %d/%d checks passed ====" % (passed, len(executed)))
    return 0 if passed == len(executed) else 1


if __name__ == "__main__":
    sys.exit(main())
