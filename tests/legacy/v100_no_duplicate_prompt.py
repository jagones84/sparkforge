#!/usr/bin/env python3
"""v0.9.10 acceptance — the SENT prompt must not duplicate the user turn (JAG-100).

Reported as "carica 30k in una sessione, vedo se scrive davvero 30k". The 30k was
an ESTIMATE; the model really received ~72k because `chat_once` passed the user
message BOTH inside `sess["messages"]` (the caller had already appended it, JAG-51)
AND again as the pending `message` -> build() appended it a second time. Proven
live: a 34,502-token block (true tokenizer) arrived as 72,357 prompt_tokens.

These checks exercise the real assembler (`server.assemble_turn`), which is the
one place that builds the prompt sent to the router.
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
tmp = tempfile.mkdtemp(prefix="sf-dup-")
os.environ["SPARKFORGE_SESSIONS_DIR"] = os.path.join(tmp, "sessions")
os.environ["SPARKFORGE_DB"] = os.path.join(tmp, "events.db")
os.environ["SPARKFORGE_GRAPH_DIR"] = os.path.join(tmp, "graphs")
os.environ["SPARKFORGE_CONTEXT_BUDGET"] = "2000000"  # huge: never compact here
os.makedirs(os.environ["SPARKFORGE_SESSIONS_DIR"], exist_ok=True)
os.makedirs(os.environ["SPARKFORGE_GRAPH_DIR"], exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from sparkforge import context_engine  # noqa: E402
from sparkforge import server  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


BLOCK = "".join("RIGA %05d: contenuto di prova ripetuto per riempire il contesto. " % i
                for i in range(1, 1501))


def users(msgs):
    return [m for m in msgs if m.get("role") == "user"]


# --- Session A: a single (large) user turn ---------------------------------
sess = server.get_or_create_session("dup-a")
server.append_message(sess, "user", BLOCK)
sess = server.load_session("dup-a")
msgs, stats = server.assemble_turn(sess, BLOCK)

check("D1 the sent prompt has exactly ONE user message",
      len(users(msgs)) == 1, "user messages=%d" % len(users(msgs)))
check("D2 that message is the block itself (not doubled)",
      len(users(msgs)) == 1 and users(msgs)[0]["content"] == BLOCK,
      "len=%s" % (len(users(msgs)[0]["content"]) if users(msgs) else -1))

sys_tok = context_engine.count_tokens(server._system_prompt(sess, server._tool_context()))
blk_tok = context_engine.count_tokens(BLOCK)
check("D3 final_tokens == system + ONE block (not two)",
      stats["final_tokens"] < sys_tok + blk_tok * 1.5,
      "final=%d sys=%d block=%d (2x would be %d)"
      % (stats["final_tokens"], sys_tok, blk_tok, sys_tok + 2 * blk_tok))

# --- Session B: autonomous mode augments the goal, still once --------------
sessb = server.get_or_create_session("dup-b")
goal = "scrivi una nota di 3 righe sul prato verde"
server.append_message(sessb, "user", goal)
sessb = server.load_session("dup-b")
msgsb, _ = server.assemble_turn(sessb, goal, autonomous=True)
ub = users(msgsb)
check("D4 autonomous: exactly one user message AND it carries the directive",
      len(ub) == 1 and ub[0]["content"].startswith("AUTONOMOUS GOAL MODE")
      and goal in ub[0]["content"],
      "user messages=%d startswith=%r"
      % (len(ub), ub[0]["content"][:24] if ub else None))

# --- Session C: prior history kept once, big block once --------------------
sessc = server.get_or_create_session("dup-c")
server.append_message(sessc, "user", "ciao, domanda precedente")
server.append_message(sessc, "assistant", "risposta precedente")
server.append_message(sessc, "user", BLOCK)
sessc = server.load_session("dup-c")
msgsc, _ = server.assemble_turn(sessc, BLOCK)
uc = users(msgsc)
check("D5 history preserved: prior user kept + big block once",
      len(uc) == 2 and uc[0]["content"] == "ciao, domanda precedente"
      and uc[1]["content"] == BLOCK,
      "user messages=%d" % len(uc))

print("\n==== %d/%d checks passed ====" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
