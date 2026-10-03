#!/usr/bin/env python3
"""v208 — LIVE chaos / crash-resistance (requires a running server).

Adversarial HTTP abuse: malformed JSON, a 2 MB body, unknown paths/methods,
raw-socket garbage, a 100 KB header, an abrupt mid-request close, and a 40-thread
mixed burst. The system under test is the RUNNING harness. Success criterion:
NEVER a 5xx and the server is still healthy afterwards ("è rimasto in piedi").

Run (DGX, server up):  python3 tests/live/v208_chaos_http.py
"""
import json
import os
import socket
import threading
import urllib.error
import urllib.parse
import urllib.request

ENV = os.path.expanduser("~/.config/sparkforge/env")
TOK = ""
try:
    for line in open(ENV):
        line = line.strip()
        if line.startswith("SPARKFORGE_TOKEN="):
            TOK = line.split("=", 1)[1].strip().strip('"').strip("'")
except OSError:
    pass
BASE = os.environ.get("SPARKFORGE_BASE", "http://127.0.0.1:8790")
HOST, PORT = "127.0.0.1", int(os.environ.get("SPARKFORGE_PORT", "8790"))
RESULTS = []


def rep(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


def call(method, path, raw=None, token=True, timeout=10):
    url = BASE + path
    if token and TOK:
        url += ("&" if "?" in path else "?") + urllib.parse.urlencode({"token": TOK})
    headers = {"Authorization": "Bearer " + TOK} if (token and TOK) else {}
    if raw is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=raw, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read(200).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, (e.read(200).decode("utf-8", "replace") if e.fp else "")
    except OSError as e:
        # URLError, ConnectionResetError, BrokenPipeError, socket.timeout — the
        # server closing a garbage request is expected; never crash the worker.
        return 0, repr(e)[:120]


def health():
    s, _ = call("GET", "/api/status")
    return s


def raw_send(payload, read=True):
    try:
        s = socket.create_connection((HOST, PORT), timeout=5)
        s.sendall(payload)
        if read:
            try:
                s.recv(200)
            except OSError:
                pass
        s.close()
        return True
    except OSError:
        return False


# ---- C1: baseline ----
rep("C1 baseline health 200", health() == 200, "status=%s" % health())

# ---- C2: malformed JSON body ----
st, _ = call("POST", "/api/chat", raw=b"{ this is not json")
rep("C2 malformed JSON -> no 5xx", st not in (500, 502, 503, 504), "status=%s" % st)

# ---- C3: oversized body (2 MB) ----
st, _ = call("POST", "/api/chat", raw=json.dumps({"message": "x" * 2_000_000}).encode(),
             timeout=15)
rep("C3 2MB body -> no 5xx", st not in (500, 502, 503, 504), "status=%s" % st)

# ---- C4: unknown path ----
st, _ = call("GET", "/api/definitely-not-a-real-endpoint")
rep("C4 unknown path -> 404", st == 404, "status=%s" % st)

# ---- C5: bad method ----
st, _ = call("PUT", "/api/status", raw=b"{}")
rep("C5 bad method -> no 5xx", st not in (500, 502, 503, 504), "status=%s" % st)

# ---- C6: raw garbage ----
raw_send(b"NOT A VALID HTTP REQUEST\r\n\r\n")
rep("C6 raw garbage -> survives", health() == 200, "health=%s" % health())

# ---- C7: huge header (100 KB) ----
raw_send(b"GET /api/status HTTP/1.1\r\nHost: x\r\nX-Big: " + b"A" * 100000 + b"\r\n\r\n")
rep("C7 100KB header -> survives", health() == 200, "health=%s" % health())

# ---- C8: abrupt mid-request close ----
try:
    s = socket.create_connection((HOST, PORT), timeout=5)
    s.sendall(b"POST /api/chat HTTP/1.1\r\nHost: x\r\nContent-Length: 1000000\r\n\r\n{")
    s.close()
    ok8 = True
except OSError:
    ok8 = False
rep("C8 abrupt mid-request close -> survives", ok8 and health() == 200, "health=%s" % health())

# ---- C9: 40-thread mixed burst ----
codes = []
lock = threading.Lock()


def worker(i):
    if i % 2 == 0:
        c, _ = call("GET", "/api/status")
    else:
        c, _ = call("POST", "/api/chat", raw=b"@@garbage@@")
    with lock:
        codes.append(c)


ths = [threading.Thread(target=worker, args=(i,)) for i in range(40)]
[t.start() for t in ths]
[t.join() for t in ths]
bad = [c for c in codes if c in (500, 502, 503, 504)]
rep("C9 40-thread mixed burst -> no 5xx", not bad, "codes=%s" % sorted(set(codes)))

# ---- C10: still standing ----
rep("C10 server STILL healthy after the chaos", health() == 200, "health=%s" % health())

ok = sum(RESULTS)
print("\nv208: %d/%d PASS" % (ok, len(RESULTS)))
raise SystemExit(0 if ok == len(RESULTS) else 1)
