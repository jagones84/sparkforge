#!/usr/bin/env python3
"""SparkForge v0.96 acceptance — persisted inline tool cards (JAG-96).

Offline unit test of `server.persist_tool_card` (no HTTP, no model call).
Guarantees the card store lives OUTSIDE `messages` (so it can never reach the
model prompt) and survives a session reload. Exit 0 iff all pass.
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "src"))
from sparkforge import server  # noqa: E402


def check(name, ok, detail=""):
    print("%s %s %s" % ("PASS" if ok else "FAIL", name, detail))
    return bool(ok)


def main():
    ok = True
    server.SESSIONS_DIR = tempfile.mkdtemp(prefix="v096-")

    sess = {"id": "v096", "messages": [{"role": "user", "content": "run ls"}]}
    server.persist_tool_card(sess, "shell", True, args={"cmd": "ls"},
                             result="a b", exit_code=0, backend="harness")

    ok &= check("card appended", len(sess.get("tool_cards", [])) == 1)
    card = sess["tool_cards"][0]
    ok &= check("after index", card["after"] == 1, str(card.get("after")))
    ok &= check("args serialized", json.loads(card["args"])["cmd"] == "ls")
    ok &= check("result kept", card["result"] == "a b")
    ok &= check("exit_code kept", card["exit_code"] == 0)

    # Cards must NOT pollute the model prompt: `messages` stays role-clean.
    ok &= check("messages untouched", len(sess["messages"]) == 1
                and all(m.get("role") != "tool" for m in sess["messages"]))

    # Persisted on disk and reloadable (the mirror reads it from /api/history).
    server.save_session(sess)
    reloaded = server.load_session("v096")
    ok &= check("reload keeps cards",
                bool(reloaded) and len(reloaded.get("tool_cards", [])) == 1)

    # A failing card keeps its error and ok=False.
    server.persist_tool_card(sess, "git", False, error="boom", backend="harness")
    ok &= check("error kept", sess["tool_cards"][1]["error"] == "boom"
                and sess["tool_cards"][1]["ok"] is False)

    print("\n%s" % ("ALL PASS" if ok else "SOME FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
