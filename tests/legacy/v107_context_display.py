#!/usr/bin/env python3
"""v0.9.15 acceptance — the context display is server-owned (JAG-107).

WebUI and app must NOT replicate formatting/derivation: the server ships a
`display` block (ready-made strings + state flags) and both clients bind it
verbatim. This locks the single source of truth.
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
tmp = tempfile.mkdtemp(prefix="sf-ctxdisp-")
os.environ["SPARKFORGE_SESSIONS_DIR"] = os.path.join(tmp, "sessions")
os.environ["SPARKFORGE_DB"] = os.path.join(tmp, "events.db")
os.environ["SPARKFORGE_GRAPH_DIR"] = os.path.join(tmp, "graphs")
os.makedirs(os.environ["SPARKFORGE_SESSIONS_DIR"], exist_ok=True)
os.makedirs(os.environ["SPARKFORGE_GRAPH_DIR"], exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from sparkforge import server  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


# ---- pure helper: formatting, percentage and state ------------------------
d = server.context_display(30000, 258048, 12)
check("normal state", d["state"] == "normal", d["state"])
check("short uses k suffix", d["short"] == "ctx 30k/258k · 12%", d["short"])
check("tokens label raw", d["tokens"] == "30000 tok", d["tokens"])
check("messages label", d["messages"] == "12 messages", d["messages"])
check("bar pct", d["bar_pct"] == 12 and not d["bar_hot"], str(d["bar_pct"]))
check("detail string", d["detail"] == "usati 30k / 258k token · 12%", d["detail"])

near = server.context_display(200000, 258048)
check("near state at 75%", near["state"] == "near", near["state"])
check("near detail mentions threshold",
      near["detail"].endswith("auto-compact al 75%"), near["detail"])

over = server.context_display(260000, 258048)
check("over state", over["state"] == "over", over["state"])
check("over budget label", over["budget"] == "258048 tok · OVER", over["budget"])
check("over detail", over["detail"].endswith("sopra soglia"), over["detail"])
check("over clamps bar", over["bar_pct"] == 100, str(over["bar_pct"]))
check("over hot flag", over["bar_hot"] is True, str(over["bar_hot"]))

na = server.context_display(available=False, reason="nessuna sessione")
check("unavailable state", na["state"] == "na" and na["meter"] == "ctx: n/d", na["meter"])

# ---- wired into /api/context ----------------------------------------------
sid = "disp-test"
sess = server.get_or_create_session(sid)
for i in range(3):
    server.append_message(sess, "user", "domanda %d %s" % (i, "lorem ipsum " * 20))
    server.append_message(sess, "assistant", "risposta %d %s" % (i, "dolor sit amet " * 20))

usage = server.context_usage(sid)
check("usage carries display", isinstance(usage.get("display"), dict), str(type(usage.get("display"))))
check("display pct matches pct",
      usage["display"]["pct"] == int(round(usage["pct"])),
      "%s vs %s" % (usage["display"]["pct"], usage["pct"]))
check("display available mirrors usage",
      usage["display"]["available"] == usage["available"], "")

missing = server.context_usage("does-not-exist")
check("missing session has na display",
      missing["display"]["available"] is False and missing["display"]["state"] == "na", "")

total = len(results)
passed = sum(results)
print("%d/%d" % (passed, total))
sys.exit(0 if passed == total else 1)
