#!/usr/bin/env python3
"""v309 — an agent and its session must share ONE model (JAG-309).

Observed bug: Orbit's AGENTS table showed A3 with a LOCAL model while the main
page composer showed `deepseek-reasoner` for the same agent.

Root cause (two fields, two writers, zero sync):
  * an agent IS a session (agents.py: agent["session"] == sid);
  * Orbit wrote ONLY `agent["model"]` (POST /api/agents -> designate), and jobs
    read that field -> the local model really ran (GPU busy);
  * the composer wrote/read ONLY `session["model"]` (POST /api/sessions/<id>/model)
    -> it showed deepseek.
Chosen policy (user): ALWAYS UNIFY — one model per entity.

Locked here:
  * `server._set_session_model` is the single writer: it updates the session AND,
    when the session is an agent, the agent (so both surfaces agree);
  * clearing ("") clears BOTH; a non-agent session is written without creating an
    agent;
  * `designate(model=None)` leaves the field untouched, `""` clears it;
  * `reconcile_agent_models` heals legacy divergence (agent wins) and is idempotent;
  * the session-model endpoint and the Orbit designate path both go through it;
  * startup runs the reconcile.

Deterministic, no live model. Run: python3 tests/v309_model_sync.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))
TMP = tempfile.mkdtemp(prefix="sf-v309-")
SESS = os.path.join(TMP, "sessions")
os.makedirs(SESS, exist_ok=True)
os.environ["SPARKFORGE_AGENTS_FILE"] = os.path.join(TMP, "agents.json")
os.environ["SPARKFORGE_SESSIONS_DIR"] = SESS

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


def read(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as f:
        return f.read()


from sparkforge import server  # noqa: E402
from sparkforge import agents as agents_mod  # noqa: E402

REG = agents_mod.REGISTRY


def mk_session(sid, model=None):
    s = {"id": sid, "title": sid, "created": 0.0, "messages": []}
    if model is not None:
        s["model"] = model
    server.save_session(s)
    return s


def sess_model(sid):
    return (server.load_session(sid) or {}).get("model")


def agent_model(sid):
    return (REG.get(sid) or {}).get("model")


# --- the single writer keeps session and agent in lockstep ----------------------
mk_session("t1")
REG.designate("t1", name="T1", role="orchestrator")
check("a fresh agent carries no model", agent_model("t1") in (None, ""))
server._set_session_model("t1", "deepseek:deepseek-reasoner")
check("_set_session_model writes the session model",
      sess_model("t1") == "deepseek:deepseek-reasoner")
check("_set_session_model writes the agent model too",
      agent_model("t1") == "deepseek:deepseek-reasoner")

server._set_session_model("t1", "")
check("clearing clears the session model", sess_model("t1") == "")
check("clearing clears the agent model too", agent_model("t1") is None)

# --- a non-agent session is written, but no agent is invented -------------------
mk_session("t2")
server._set_session_model("t2", "win:nex-n2.5-mini-uncensored-iq4xs")
check("a non-agent session still gets its model",
      sess_model("t2") == "win:nex-n2.5-mini-uncensored-iq4xs")
check("it does not create an agent", REG.get("t2") is None)

# --- designate contract: None = untouched, "" = clear ---------------------------
REG.designate("t1", model="m1")
check("designate stores a model", agent_model("t1") == "m1")
REG.designate("t1", model=None)
check("designate(model=None) leaves the model untouched", agent_model("t1") == "m1")
REG.designate("t1", model="")
check("designate('') clears the model", agent_model("t1") is None)

# --- reconcile heals legacy divergence (agent wins), idempotently ---------------
mk_session("t3", model="deepseek:deepseek-reasoner")
REG.designate("t3", name="T3", model="dgx:nex-n25-mini-uncensored-q8")
mk_session("t4", model="deepseek:deepseek-reasoner")
REG.designate("t4", name="T4")
mk_session("t5", model="deepseek:deepseek-reasoner")
REG.designate("t5", name="T5", model="deepseek:deepseek-reasoner")
n = server.reconcile_agent_models()
check("reconcile reports the two fixed agents", n == 2, "n=%r" % n)
check("the agent's model wins over a divergent session model",
      sess_model("t3") == "dgx:nex-n25-mini-uncensored-q8")
check("an agent with no model inherits the session's",
      agent_model("t4") == "deepseek:deepseek-reasoner")
check("an already-equal pair is untouched",
      sess_model("t5") == "deepseek:deepseek-reasoner"
      and agent_model("t5") == "deepseek:deepseek-reasoner")
check("reconcile is idempotent (a second run fixes nothing)",
      server.reconcile_agent_models() == 0)

# ------------------------------------------------------------------ source locks
s = read("src", "sparkforge", "server.py")
check("the single writer exists", "def _set_session_model(sid, model):" in s)
check("the startup reconcile exists", "def reconcile_agent_models():" in s)
check("the session-model endpoint uses the single writer",
      'ref = _set_session_model(sid, body.get("model"))' in s)
check("startup runs the reconcile",
      "# JAG-309: agent model == its session's model" in s)

o = read("src", "sparkforge", "orchestration.py")
check("the Orbit designate path syncs the session model",
      'srv._set_session_model(sid, data.get("model") or "")' in o)

a = read("src", "sparkforge", "agents.py")
check("designate can store AND clear a model",
      "if model is not None:" in a and 'a["model"] = (str(model)[:120] or None)' in a)

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
