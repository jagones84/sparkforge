#!/usr/bin/env python3
"""JAG-88 — oversized tool observations are offloaded to a file, not truncated.

Mirrors the v087 stubbing style: the model is faked, the loop is real.
The claim under test: a big tool result is (a) written verbatim to a file and
(b) referenced compactly in the context — nothing is lost, the context stays
bounded.
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "src"))
os.environ.setdefault("SPARKFORGE_DB", os.path.join(REPO, "data", "events.db"))

from sparkforge import server      # noqa: E402
from sparkforge import taskgraph   # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(("PASS " if ok else "FAIL ") + name + ((" — " + detail) if detail else ""))


def _txt(r):
    if isinstance(r, dict):
        return r.get("content") or ""
    return r or ""


MID = "<<<MIDDLE-MARKER-MUST-SURVIVE-ONLY-ON-DISK>>>"
BIG = "HEAD-" + ("x" * 7000) + MID + ("y" * 4990) + "-TAILEND"

seen = {"msgs": [], "calls": 0}


def fake_stream(msgs, model, kind, on_delta, timeout=300, usage=None):
    seen["calls"] += 1
    seen["msgs"].append([dict(m) for m in msgs])
    return seq.pop(0) if seq else ("Fine.", "", model)


server.stream_with_fallback = fake_stream

state = {"obs": BIG}


def fake_gated(tool, args, run_id=None, timeout=None):
    return {"status": "executed", "observation": state["obs"]}


server.api_v02.gated_call = fake_gated

# ---------- A: a BIG observation must be offloaded, not truncated ----------
sid = "jag88-offload-big"
taskgraph.reset(sid)
seq = [
    ('{"action":"tool","tool":"shell","args":{"command":"ls"}}', "", "m"),
    ("Fatto: elaborazione completata.", "", "m"),
]
sess = server.get_or_create_session(sid)
reply, _ = server.chat_once(sess, "elenca i file", None)

notes = [m["content"] for call in seen["msgs"] for m in call
         if m.get("role") == "user" and "Observation for tool" in m.get("content", "")]
note = notes[0] if notes else ""
check("A1 an offload reference was sent to the model", "FULL OUTPUT FILE" in note,
      repr(note[:60]))
path = ""
if "FULL OUTPUT FILE: " in note:
    path = note.split("FULL OUTPUT FILE: ", 1)[1].split("\n", 1)[0].strip()
on_disk = ""
if path and os.path.isfile(path):
    with open(path, encoding="utf-8") as fh:
        on_disk = fh.read()
check("A2 the FULL output survived verbatim on disk", on_disk == BIG,
      "file=%s bytes=%d/%d" % (path, len(on_disk), len(BIG)))
check("A3 the injected context is bounded (no flooding)", len(note) < server.CHAT_TOOL_OBS_LIMIT,
      "note=%d limit=%d" % (len(note), server.CHAT_TOOL_OBS_LIMIT))
check("A4 the middle of the output is NOT in the context", MID not in note,
      "the model must read the file to see it")
check("A5 head and tail are previewed", "HEAD-" in note and "-TAILEND" in note)
check("A6 the model was told how to read the rest", "fs.read" in note and path in note)

# ---------- B: a small observation passes through verbatim ----------
sid2 = "jag88-offload-small"
taskgraph.reset(sid2)
state["obs"] = "ok: 3 file trovati"
seq = [
    ('{"action":"tool","tool":"shell","args":{"command":"ls"}}', "", "m"),
    ("Ecco il risultato finale.", "", "m"),
]
seen["msgs"] = []
sess2 = server.get_or_create_session(sid2)
reply2, _ = server.chat_once(sess2, "elenca i file", None)
notes2 = [m["content"] for call in seen["msgs"] for m in call
          if m.get("role") == "user" and "Observation for tool" in m.get("content", "")]

small = [n for n in notes2 if "ok: 3 file trovati" in n]
check("B1 a small observation is passed through verbatim", bool(small),
      repr(small[0][:60]) if small else "none")
check("B2 a small observation is NOT offloaded",
      not any("FULL OUTPUT FILE" in n for n in notes2))
check("B3 the final answer shipped", "risultato finale" in _txt(reply2), repr(_txt(reply2)[:60]))

fails = [r for r in results if not r]
print("\n=== %d/%d checks passed ===" % (len(results) - len(fails), len(results)))
sys.exit(1 if fails else 0)
