#!/usr/bin/env python3
"""v259 — ctx window comes from the REAL local server, and the subagent role is
honoured (JAG-259).

1) `providers.context_length` used only the hand-edited `context_length` from
   providers.yaml for local models (declared 96000 while the server runs 200000;
   a missing value fell back to the 32768 default), so the auto-compaction
   trigger used the wrong window. It now prefers the local server's REAL
   `--ctx-size`/`n_ctx` (fetched in the background), declared value as fallback.
2) `subagent.spawn` ignored the "subagent" role model, so the WebUI setting had
   no effect.

Deterministic, no live server, no network. Run: python3 tests/v259_ctx_subagent.py
"""
import os
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun import providers as P  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


WIN = "nex-n2.5-mini-uncensored-iq4xs"
DGX = "deepseek-v4-flash-uncensored-q2-0731"

# 1) a live local window wins over the declared value (fresh cache -> no fetch)
P._LOCAL_CTX["win"] = {WIN: 4242}
P._LOCAL_CTX_TS["win"] = time.time()
check("live local window wins over declared",
      P.context_length("win:" + WIN) == 4242,
      str(P.context_length("win:" + WIN)))

# 2) declared fallback when the model has no live entry (cache fresh -> no fetch)
P._LOCAL_CTX["win"] = {"other-model": 7}
P._LOCAL_CTX_TS["win"] = time.time()
check("declared fallback when no live entry",
      P.context_length("win:" + WIN) == 131072,
      str(P.context_length("win:" + WIN)))

# 3) unknown ref -> 0
check("unknown ref -> 0", P.context_length("nope:nope") == 0)

# 4) a DGX alias uses the live window too
P._LOCAL_CTX["dgx"] = {DGX: 55555}
P._LOCAL_CTX_TS["dgx"] = time.time()
check("local dgx alias uses the live window",
      P.context_length("dgx:" + DGX) == 55555,
      str(P.context_length("dgx:" + DGX)))

# 5) static guards for the two wirings
with open(os.path.join(REPO, "src", "longrun", "subagent.py"), encoding="utf-8") as f:
    sa = f.read()
check("subagent.spawn honours the subagent role model",
      'routing.role_model("subagent") or routing.pick("subagent")' in sa)

with open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8") as f:
    ix = f.read()
check("chooseModel re-measures the ctx bar",
      "JAG-258: re-measure the context bar" in ix and "loadCtx();" in ix)

with open(os.path.join(REPO, "src", "longrun", "providers.py"), encoding="utf-8") as f:
    pv = f.read()
check("providers fetches the local live window (and warms it)",
      "_fetch_local_contexts" in pv
      and 'local_contexts(p.get("id"), block=True)' in pv)

print("---")
ok = sum(results)
print("%d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
