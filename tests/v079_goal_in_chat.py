#!/usr/bin/env python3
"""JAG-78 acceptance — `/goal` inside the chat + live context.built.

A. GET /api/chat/stream?...&mode=goal  → the SAME chat stream carries:
     chat.run, context.built (live prompt size), graph.node.added (the plan),
     and the turn ends cleanly.
B. the session graph exists afterwards (session-keyed) -> the app's panel shows it.

Exit code 0 = all PASS.
"""
import json
import sys
import urllib.request

BASE = "http://127.0.0.1:8790"
TOK = "REDACTED-COMPROMISED-TOKEN"
HDR = {"Authorization": "Bearer " + TOK}

results = []


def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(("PASS " if ok else "FAIL ") + name + ((" — " + detail) if detail else ""))


def stream_events(session, message, mode=None, limit_events=200000, timeout=600):
    path = ("/api/chat/stream?session=" + session + "&message=" + urllib.parse.quote(message)
            + (("&mode=" + mode) if mode else ""))
    r = urllib.request.Request(BASE + path, headers=HDR)
    types, payloads = [], []
    with urllib.request.urlopen(r, timeout=timeout) as resp:
        for raw in resp:
            line = raw.decode("utf-8", "replace").rstrip("\n")
            if line.startswith("event: "):
                types.append(line[7:])
            elif line.startswith("data: "):
                try:
                    payloads.append(json.loads(line[6:]))
                except Exception:
                    payloads.append({})
            if len(types) >= limit_events:
                break
    return types, payloads


def graph(session):
    r = urllib.request.Request(BASE + "/api/runs/" + session + "/graph", headers=HDR)
    try:
        with urllib.request.urlopen(r, timeout=20) as resp:
            return json.loads(resp.read().decode())
    except Exception:
        return {}


import uuid
import urllib.parse  # noqa: E402

sid = "v079-goal-" + uuid.uuid4().hex[:8]
types, payloads = stream_events(
    sid, "Verifica che ADB sia installato, elenca i dispositivi collegati e riporta l'esito.",
    mode="goal")

check("stream includes chat.run", "chat.run" in types, "n=%d" % len(types))
check("stream includes context.built (live ctx)", "context.built" in types,
      "types=%s" % sorted(set(types)))
check("stream includes graph.node.added (plan authored)",
      "graph.node.added" in types,
      "nodes=%d" % sum(1 for t in types if t == "graph.node.added"))
check("stream ends with done", "done" in types or "chat.done" in types,
      "last=%s" % (types[-5:] if types else []))

g = graph(sid)
nodes = g.get("nodes", [])
check("graph reachable by SESSION key", bool(g), "http body empty=%s" % (not g))
check("graph has the planned nodes", len(nodes) >= 1, "%d nodes" % len(nodes))
check("graph session_id == sid", g.get("session_id") == sid,
      "session_id=%s sid=%s" % (g.get("session_id"), sid))

fails = [r for r in results if not r[1]]
print("\n=== %d/%d checks passed ===" % (len(results) - len(fails), len(results)))
sys.exit(1 if fails else 0)
