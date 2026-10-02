#!/usr/bin/env python3
"""v0.9.38 acceptance — loop di completamento (JAG-129A)."""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


import keepgoing  # noqa: E402

check("K1 defaults present",
      all(k in keepgoing.DEFAULTS for k in
          ("keepgoing_max", "no_progress_rounds", "max_wall_secs", "subagent_max_depth")),
      str(sorted(keepgoing.DEFAULTS)))
check("K2 default keepgoing_max is 8", keepgoing.DEFAULTS["keepgoing_max"] == 8, "")

d = keepgoing.decide(open_nodes=3, rounds=0, stale=0, started=1000.0, now=1001.0)
check("K3 continues with open nodes", d["continue"] is True and d["reason"] is None, str(d))

check("K4 goal_reached when no open",
      keepgoing.decide(open_nodes=0, rounds=0, stale=0, started=1000.0, now=1001.0)["reason"]
      == "goal_reached", "")
check("K5 budget at cap",
      keepgoing.decide(open_nodes=3, rounds=8, stale=0, started=1000.0, now=1001.0)["reason"]
      == "budget", "")
check("K6 no_progress",
      keepgoing.decide(open_nodes=3, rounds=1, stale=2, started=1000.0, now=1001.0)["reason"]
      == "no_progress", "")
check("K7 blocked",
      keepgoing.decide(open_nodes=3, rounds=0, stale=0, started=1000.0, now=1001.0,
                       blocked=True)["reason"] == "blocked", "")
check("K8 user_stop",
      keepgoing.decide(open_nodes=3, rounds=0, stale=0, started=1000.0, now=1001.0,
                       aborted=True)["reason"] == "user_stop", "")
check("K9 budget on wall-clock",
      keepgoing.decide(open_nodes=3, rounds=0, stale=0, started=1000.0, now=99999.0)["reason"]
      == "budget", "")
check("K10 steer forces continue",
      keepgoing.decide(open_nodes=0, rounds=0, stale=0, started=1000.0, now=1001.0,
                       steer=True)["continue"] is True, "")

h1 = keepgoing.state_hash([{"id": "n1", "status": "todo"}, {"id": "n2", "status": "done"}])
h2 = keepgoing.state_hash([{"id": "n1", "status": "todo"}, {"id": "n2", "status": "done"}])
h3 = keepgoing.state_hash([{"id": "n1", "status": "doing"}, {"id": "n2", "status": "done"}])
check("K11 state_hash stable", h1 == h2 and h1 != h3, "%s %s" % (h1[:8], h3[:8]))
check("K12 tool_hash deterministic",
      keepgoing.tool_hash("shell", {"cmd": "ls"}) == keepgoing.tool_hash("shell", {"cmd": "ls"}),
      "")
check("K13 cfg() exposes overrides",
      keepgoing.cfg({"keepgoing_max": 20})["keepgoing_max"] == 20, "")

srv = open(os.path.join(REPO, "server.py"), encoding="utf-8", errors="replace").read()
check("S1 chat loop imports keepgoing", "import keepgoing" in srv, "")
check("S2 emits plan.continuing", "plan.continuing" in srv, "")
check("S3 emits plan.stopped with reason", "plan.stopped" in srv and '"reason"' in srv, "")
check("S4 no one-shot verify gate left", "verify_nudged" not in srv, "")
check("S5 re-injects the todo list", "render_todos" in srv and "CONTINUA" in srv, "")
check("S6 has abort helpers", "def push_abort" in srv and "def _is_aborted" in srv, "")
check("S7 has /api/chat/abort route", '"/api/chat/abort"' in srv, "")
check("S8 abort flag cleared at turn start", "clear_abort" in srv, "")

total = len(results)
print("\n==== %d/%d checks passed ====" % (sum(results), total))
sys.exit(0 if all(results) else 1)