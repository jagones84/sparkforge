#!/usr/bin/env python3
"""v346 — fs.read observations must carry the file CONTENT (regression).

Root cause of a real, silent failure: tools.observation() rendered stdout / stderr
/ path but NEVER `content`. fs.read returns its payload in `content`, so every
fs.read reached the model as an EMPTY observation (exit=0, no error) — the agent
was blind to every file it read, and to the "read more with fs.read" offload files
the harness told it to open. A weak model then fumbles an otherwise easy task.

Deterministic, no model. Run: python3 tests/acceptance/v346_fs_read_observation.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))

from sparkforge import tools  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


# --- A: the observation of an fs.read result includes the CONTENT -------------
res = {"tool": "fs.read", "ok": True, "exit_code": 0, "backend": "host",
       "sandboxed": False, "path": "/tmp/x.kt",
       "content": "package com.x\nfun main() { println(42) }\n", "bytes": 38}
obs = tools.observation(res)
check("A1 fs.read observation includes the content", "fun main() { println(42) }" in obs,
      repr(obs)[:200])
check("A2 it still names the path", "/tmp/x.kt" in obs, "")

# --- B: end-to-end through the real fs.read implementation -------------------
live = tools._fs_read({"path": "setup.cfg"}, "v346")
check("B1 _fs_read returns ok with content",
      live.get("ok") is True and "mutmut" in (live.get("content") or ""),
      "bytes=%s" % live.get("bytes"))
check("B2 the observation of that read carries 'mutmut'", "mutmut" in tools.observation(live), "")

# --- C: no regression for stdout/stderr tools --------------------------------
obs_shell = tools.observation({"tool": "shell", "ok": True, "exit_code": 0,
                               "backend": "host", "sandboxed": False,
                               "stdout": "HELLO-STDOUT", "stderr": "warn-err"})
check("C1 shell stdout is still rendered", "HELLO-STDOUT" in obs_shell, "")
check("C2 shell stderr is still rendered", "warn-err" in obs_shell, "")

# --- D: truncation still bounded (content cannot flood the context) ----------
big = {"tool": "fs.read", "ok": True, "exit_code": 0, "backend": "host",
       "sandboxed": False, "path": "/tmp/big", "content": "x" * 100000}
check("D1 a huge read is truncated to the budget",
      len(tools.observation(big, max_chars=800)) < 1200, "")

print("---")
ok = sum(results)
print("%d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
