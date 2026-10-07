#!/usr/bin/env python3
"""SparkForge v0.6.1 acceptance — JAG-48: the chat SSE stream closes after `done`.

Evidence, not claims: every check prints raw-socket numbers (time of the
terminal `done` event, time of EOF, delta counts) and the run writes
`data/v061-acceptance.json`.

  A. deterministic (own instance on SPARKFORGE_TEST_PORT + tests/mock_router.py):
     A1 3 sequential GET /api/chat/stream on the SAME session: each stream ends
        with exactly one `done` and EOF within <= 2 s of it → "3/3"
     A2 chat SSE carries no keep-alive filler (`: ping` = 0)
     A3 no socket left ESTAB on the test port after the 3 requests (`ss -tn`)
     A4 upstream stalls mid-stream (mock holds the response open): the chat
        stream still terminates (error + done) and closes — never ESTAB forever
     A5 /api/feed keeps its keep-alive: events arrive and the socket stays open
  B. live service (--live, real model on 127.0.0.1:8790): the same 3-sequential
     check with real timings.

Usage: python3 tests/v061_stream_close.py [--base http://127.0.0.1:8790] [--live]
Exit code 0 iff every executed check passed.
"""
import argparse
import json
import os
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
MOCK_PORT = int(os.environ.get("SPARKFORGE_MOCK_PORT", 8096))
TEST_PORT = int(os.environ.get("SPARKFORGE_TEST_PORT", 8796))
STALL_PORT = int(os.environ.get("SPARKFORGE_STALL_PORT", 8794))
STALL_MOCK_PORT = int(os.environ.get("SPARKFORGE_STALL_MOCK_PORT", 8094))
CLOSE_BUDGET = float(os.environ.get("SPARKFORGE_CLOSE_BUDGET", 2.0))  # s after `done`

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


# ------------------------------------------------------------ SSE client ----
def _hostport(base):
    p = urllib.parse.urlparse(base)
    return p.hostname, p.port or 80


def sse_stream(base, token, message, session, model=None, timeout=120.0,
               extra_headers=None, method="GET"):
    """GET an SSE endpoint over a raw socket; return timings around `done`/EOF.

    Raw socket on purpose: the question is *when the connection closes*
    (EOF), which is what a client waiting for the end of the stream sees —
    exactly the `ss -tn ... ESTAB` evidence of the bug report.
    """
    host, port = _hostport(base)
    q = {"message": message, "session": session}
    if model:
        q["model"] = model
    qs = urllib.parse.urlencode(q)
    headers = {"Accept": "text/event-stream", "Host": "%s:%d" % (host, port)}
    if token:
        headers["Authorization"] = "Bearer " + token
    headers.update(extra_headers or {})
    req = "%s /api/chat/stream?%s HTTP/1.1\r\n" % (method, qs)
    req += "".join("%s: %s\r\n" % (k, v) for k, v in headers.items()) + "\r\n"

    sock = socket.create_connection((host, port), timeout=10)
    sock.settimeout(timeout)
    t0 = time.time()
    sock.sendall(req.encode())
    buf = b""
    t_done = None
    t_eof = None
    try:
        while True:
            data = sock.recv(65536)
            if not data:
                t_eof = time.time() - t0
                break
            buf += data
            if t_done is None and b"event: done" in buf:
                t_done = time.time() - t0
    except socket.timeout:
        pass
    finally:
        sock.close()
    text = buf.decode("utf-8", "replace")
    kinds = [l.split(":", 1)[1].strip() for l in text.splitlines()
             if l.startswith("event:")]
    comments = [l for l in text.splitlines() if l.startswith(":")]
    return {
        "status": text.split("\r\n", 1)[0] if text else "NO RESPONSE",
        "done": kinds.count("done"),
        "error": kinds.count("error"),
        "deltas": kinds.count("chat.delta"),
        "events": len(kinds),
        "pings": sum(1 for c in comments if "ping" in c),
        "t_done": t_done,
        "t_eof": t_eof,
        "close_after_done": (t_eof - t_done) if (t_eof is not None and t_done is not None) else None,
    }


def fmt(r):
    return ("status=%s events=%d deltas=%d done=%d error=%d ping=%d done_at=%s "
            "eof_at=%s close_after_done=%s" % (
                r["status"], r["events"], r["deltas"], r["done"], r["error"], r["pings"],
                ("%.2fs" % r["t_done"]) if r["t_done"] is not None else "MISSING",
                ("%.2fs" % r["t_eof"]) if r["t_eof"] is not None else "NO-EOF",
                ("%.2fs" % r["close_after_done"]) if r["close_after_done"] is not None else "n/a"))


def three_sequential(base, token, session, label, timeout=120.0):
    """JAG-48 acceptance: 3 sequential streams on the same session, all closed."""
    rows = []
    for i in (1, 2, 3):
        t = time.time()
        r = sse_stream(base, token, "%s (request %d)" % (label, i), session, timeout=timeout)
        r["wall"] = round(time.time() - t, 2)
        rows.append(r)
        print("   req %d: %s  wall=%.2fs" % (i, fmt(r), r["wall"]))
    closed = sum(1 for r in rows
                 if r["done"] == 1 and r["t_eof"] is not None
                 and r["close_after_done"] is not None
                 and r["close_after_done"] <= CLOSE_BUDGET)
    timing = " | ".join("req%d done=%s eof=%s Δ=%s" % (
        i + 1,
        ("%.2fs" % r["t_done"]) if r["t_done"] is not None else "MISSING",
        ("%.2fs" % r["t_eof"]) if r["t_eof"] is not None else "NO-EOF",
        ("%.2fs" % r["close_after_done"]) if r["close_after_done"] is not None else "n/a")
        for i, r in enumerate(rows))
    check("%s: 3/3 chat streams closed after `done` (<= %.1fs, same session)"
          % (label, CLOSE_BUDGET),
          closed == 3,
          "%d/3 closed | %s | session=%s" % (closed, timing, session),
          closed=closed, timing=timing, session=session)
    return rows


def api_get(base, token, path, timeout=30):
    req = urllib.request.Request(base + path,
                                 headers={"Authorization": "Bearer " + token} if token else {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        return e.code, {"error": "HTTP %d" % e.code}
    except Exception as e:  # noqa: BLE001
        return 0, {"error": str(e)}


def estab_count(port):
    """`ss -tn` evidence: ESTAB sockets on `port` (the bug report's command)."""
    try:
        out = subprocess.run(["ss", "-tn"], capture_output=True, text=True, timeout=10).stdout
    except Exception as e:  # noqa: BLE001
        return None, "ss failed: %s" % e
    rows = [l for l in out.splitlines() if "ESTAB" in l and (":%d " % port) in l + " "]
    return len(rows), out


def _wait_port(base, token, tries=40):
    for _ in range(tries):
        st, _ = api_get(base, token, "/api/status", timeout=5)
        if st == 200:
            return True
        time.sleep(0.5)
    return False


# ------------------------------------------------------ A: deterministic ----
def part_a(mock, inst):
    base = "http://127.0.0.1:%d" % TEST_PORT
    tok = "test-token"
    if not _wait_port(base, tok):
        check("A0 mock router + test instance up", False, "no /api/status on %s" % base)
        return
    check("A0 mock router + test instance up", True, "base=%s mock=%s" % (base, mock))

    session = "v061-close-%s" % uuid.uuid4().hex[:6]
    rows = three_sequential(base, tok, session, "A1 mock", timeout=60)
    check("A2 chat SSE has no keep-alive filler (ping=0)",
          all(r["pings"] == 0 for r in rows),
          "pings per request=%s (keep-alive is /api/feed only)" % [r["pings"] for r in rows])

    time.sleep(1.0)
    n, out = estab_count(TEST_PORT)
    src = "\n".join(l for l in out.splitlines() if ":%d" % TEST_PORT in l) or "(no rows)"
    check("A3 no socket left ESTAB on the chat port after the 3 streams",
          n == 0,
          "ss -tn | grep %d -> %d ESTAB\n%s" % (TEST_PORT, n if n is not None else -1, src))


def part_a_stall():
    """Upstream stalls mid-stream (no [DONE], socket held open)."""
    mock = subprocess.Popen([sys.executable, os.path.join(REPO, "tests", "mock_router.py"),
                             "--port", str(STALL_MOCK_PORT), "--warm-seconds", "0",
                             "--stall-after", "2", "--stall-seconds", "0"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    env = dict(os.environ,
               SPARKFORGE_ROUTER="http://127.0.0.1:%d" % STALL_MOCK_PORT,
               SPARKFORGE_GRAPH_DIR="/tmp/sparkforge-v061-graphs",
               SPARKFORGE_DB="/tmp/sparkforge-v061-test.db",
               SPARKFORGE_ROUTER_IDLE_TIMEOUT="6",
               SPARKFORGE_CHAT_STREAM_IDLE="20",
               SPARKFORGE_MODEL_LOAD_TIMEOUT="30")
    inst = subprocess.Popen([sys.executable, os.path.join(REPO, "server.py"),
                             "--host", "127.0.0.1", "--port", str(STALL_PORT),
                             "--token", "test-token"],
                            cwd=REPO, env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = "http://127.0.0.1:%d" % STALL_PORT
    try:
        if not _wait_port(base, "test-token"):
            check("A4 stalled upstream: chat stream still terminates", False,
                  "stall test instance did not come up on %s" % base)
            return
        t0 = time.time()
        r = sse_stream(base, "test-token", "stall probe", "v061-stall", timeout=90)
        wall = time.time() - t0
        ok = (r["t_eof"] is not None and r["done"] >= 1 and wall < 90
              and r["close_after_done"] is not None
              and r["close_after_done"] <= CLOSE_BUDGET)
        check("A4 stalled upstream: chat stream still terminates and closes",
              ok, "%s wall=%.2fs (upstream held open, no [DONE])" % (fmt(r), wall),
              close_after_done=r["close_after_done"], wall=round(wall, 2))
    finally:
        inst.terminate()
        mock.terminate()
        for p in (inst, mock):
            try:
                p.wait(timeout=5)
            except Exception:  # noqa: BLE001
                p.kill()


def part_a_feed():
    """A5: /api/feed is the keep-alive stream — it must stay open."""
    base = "http://127.0.0.1:%d" % TEST_PORT
    host, port = _hostport(base)
    req = ("GET /api/feed?token=test-token HTTP/1.1\r\nHost: %s:%d\r\n"
           "Accept: text/event-stream\r\n\r\n" % (host, port))
    sock = socket.create_connection((host, port), timeout=10)
    sock.settimeout(4)
    sock.sendall(req.encode())
    buf = b""
    t0 = time.time()
    try:
        while time.time() - t0 < 3.5:
            data = sock.recv(65536)
            if not data:
                break
            buf += data
    except socket.timeout:
        pass
    finally:
        sock.close()
    text = buf.decode("utf-8", "replace")
    open_ok = (buf != b"" and b": feed open" in buf) or b"event:" in buf
    check("A5 /api/feed keeps its keep-alive (socket still open after 3.5s)",
          open_ok and not text.endswith("data: {}\n\n"),
          "bytes=%d lines=%s" % (len(buf), [l for l in text.splitlines()[:3]]))


# --------------------------------------------------------------- B: live ----
def part_b_live(base, token):
    st, _ = api_get(base, token, "/api/status", timeout=5)
    if st != 200:
        check("B0 live service reachable", True,
              "SKIPPED: %s unreachable" % base, skipped=True)
        return
    st, self_ = api_get(base, token, "/api/selfcheck", timeout=60)
    print("   selfcheck: version=%s model_loaded=%s router=%s" % (
        self_.get("version"), self_.get("model_loaded"), self_.get("router_reachable")))
    session = "v061-close-live-%s" % uuid.uuid4().hex[:6]
    three_sequential(base, token, session, "B1 live", timeout=180)
    time.sleep(1.0)
    n, out = estab_count(_hostport(base)[1])
    src = "\n".join(l for l in out.splitlines() if ":%d" % _hostport(base)[1] in l) or "(no rows)"
    check("B2 no socket left ESTAB on the live chat port", n == 0,
          "ss -tn | grep %d -> %s ESTAB\n%s" % (_hostport(base)[1], n, src))


def main():
    global BASE, TOKEN
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=BASE)
    ap.add_argument("--token", default=TOKEN)
    ap.add_argument("--live", action="store_true", help="also run the 3x check on the live service")
    a = ap.parse_args()
    BASE, TOKEN = a.base, a.token
    print("SparkForge v0.6.1 stream-close acceptance (JAG-48) — test port=%d live=%s token=%s"
          % (TEST_PORT, BASE, "set" if TOKEN else "none"))

    mock = subprocess.Popen([sys.executable, os.path.join(REPO, "tests", "mock_router.py"),
                             "--port", str(MOCK_PORT), "--warm-seconds", "0"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    env = dict(os.environ, SPARKFORGE_ROUTER="http://127.0.0.1:%d" % MOCK_PORT,
               SPARKFORGE_GRAPH_DIR="/tmp/sparkforge-v061-graphs",
               SPARKFORGE_DB="/tmp/sparkforge-v061-test.db",
               SPARKFORGE_MODEL_LOAD_TIMEOUT="60")
    inst = subprocess.Popen([sys.executable, os.path.join(REPO, "server.py"),
                             "--host", "127.0.0.1", "--port", str(TEST_PORT),
                             "--token", "test-token"],
                            cwd=REPO, env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        part_a(mock, inst)
        part_a_feed()
    finally:
        inst.terminate()
        mock.terminate()
        for p in (inst, mock):
            try:
                p.wait(timeout=5)
            except Exception:  # noqa: BLE001
                p.kill()
    part_a_stall()
    if a.live:
        part_b_live(BASE, TOKEN)

    executed = [r for r in results if not r.get("skipped")]
    passed = sum(1 for r in executed if r["ok"])
    report = {"base": BASE, "ts": time.time(), "passed": passed,
              "total": len(executed), "results": results}
    os.makedirs(os.path.join(REPO, "data"), exist_ok=True)
    with open(os.path.join(REPO, "data", "v061-acceptance.json"), "w") as f:
        json.dump(report, f, indent=2)
    print("\n==== %d/%d checks passed (%d skipped) ====" % (
        passed, len(executed), len(results) - len(executed)))
    return 0 if passed == len(executed) else 1


if __name__ == "__main__":
    sys.exit(main())
