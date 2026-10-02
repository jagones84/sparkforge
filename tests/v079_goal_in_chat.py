#!/usr/bin/env python3
"""JAG-78 acceptance — `/goal` inside the chat + live context.built + no JSON leak.

A. GET /api/chat/stream?...&mode=goal  → the SAME chat stream carries
     chat.run, context.built (live prompt size) and ends with `done`.
B. NEVER a raw tool-call JSON in the VISIBLE deltas (channel != "think").
   Regression for JAG-78b: the forced final call used to stream JSON straight
   into the user's bubble.

The reader has a WALL-CLOCK cap: if the model calls an approval-gated tool the
stream legitimately stays open (the harness waits for approval), so we stop
after `max_seconds` and still report what we saw. Exit 0 = all PASS.
"""
import json
import os
import socket
import sys
import time
import urllib.parse
import urllib.request
import uuid

BASE = os.environ.get("SPARKFORGE_URL", "http://127.0.0.1:8790")
# JAG-127: never hardcode the token — read it from the environment (a leaked
# token in a committed test is published forever).
TOK = os.environ.get("SPARKFORGE_TOKEN", "")
HDR = {"Authorization": "Bearer " + TOK} if TOK else {}

results = []


def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(("PASS " if ok else "FAIL ") + name + ((" — " + detail) if detail else ""))


def stream_events(session, message, mode=None, max_seconds=150, timeout=90):
    path = ("/api/chat/stream?session=" + session + "&message=" + urllib.parse.quote(message)
            + (("&mode=" + mode) if mode else ""))
    r = urllib.request.Request(BASE + path, headers=HDR)
    types, pairs = [], []
    pending = None
    deadline = time.time() + max_seconds
    done = False
    with urllib.request.urlopen(r, timeout=timeout) as resp:
        while time.time() < deadline:
            try:
                raw = resp.readline()
            except (socket.timeout, TimeoutError, OSError):
                break
            if not raw:
                break
            line = raw.decode("utf-8", "replace").rstrip("\n")
            if line.startswith("event: "):
                ev = line[7:]
                types.append(ev)
                pending = ev
                if ev in ("done", "chat.done"):
                    done = True
                    break
            elif line.startswith("data: "):
                try:
                    pairs.append((pending, json.loads(line[6:])))
                except Exception:
                    pairs.append((pending, {}))
    return types, pairs, done


sid = "v079-goal-" + uuid.uuid4().hex[:8]
types, pairs, done = stream_events(
    sid, "Spiega in due frasi, in prosa, cosa fa il comando 'adb devices'.", mode="goal")

check("stream includes chat.run", "chat.run" in types, "n=%d" % len(types))
check("stream includes context.built (live ctx)", "context.built" in types,
      "types=%s" % sorted(set(types)))
check("stream ends with done", done, "last=%s" % (types[-5:] if types else []))

visible = "".join((p.get("text") or "") for (e, p) in pairs
                  if e == "chat.delta" and p.get("channel") != "think")
check("no raw action JSON in the VISIBLE chat stream",
      '"action"' not in visible and '"update_todos"' not in visible,
      "visible=%d chars sample=%r" % (len(visible), visible[:120]))

fails = [r for r in results if not r[1]]
print("\n=== %d/%d checks passed ===" % (len(results) - len(fails), len(results)))
sys.exit(1 if fails else 0)
