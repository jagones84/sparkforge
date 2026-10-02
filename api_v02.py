#!/usr/bin/env python3
"""SparkForge v0.2 — safe execution surface: tool registry, approval gates,
HITL run control and the MCP endpoint.

This module owns the v0.2 HTTP surface (and the tool-enabled agent loop) so
that server.py only needs a tiny delegation hook:

    if api_v02.handle(self, method, path, qs, body):
        return

`server` is imported lazily inside functions (server.py imports this module at
startup, so a top-level import would be circular).

Routes owned here:
  GET  /api/tools                 registry + allowlist + sandbox backend
  POST /api/tools                 enable/disable a tool or change its policy
  POST /api/tools/call            run a tool through the approval gate
  GET  /api/approvals             approval queue (+stats)
  GET  /api/approvals/<id>        one approval
  POST /api/approvals/<id>        decide: {decision: approve|deny, by}
  GET  /api/sandbox               sandbox backend probe (evidence)
  GET  /api/feed/recent           feed backlog as JSON (MCP-friendly)
  GET  /api/agent/run             SSE agent run (tools enabled)  [GET]
  POST /api/agent/run             JSON agent run (goal, max_steps, script?)
  GET  /api/agent/runs            list agent runs + HITL status
  GET  /api/agent/runs/<id>       one run (trace)
  POST /api/agent/control         {runId, action: pause|resume|abort}
  POST /mcp                       MCP JSON-RPC 2.0 (tools/list, tools/call, …)
"""

import json
import queue
import sys
import threading
import time
import uuid

import approvals
import mcp
import registry
import sandbox
import tools as toolmod


def _srv():
    import server
    return server


def _publish(kind, **data):
    try:
        return _srv().publish(kind, **data)
    except Exception:  # feed must never break the run
        return None


# ------------------------------------------------------------- run state ----

class AbortRun(Exception):
    """Raised inside a run when the operator aborts it (HITL)."""


class RunState:
    def __init__(self, rid, goal, model, max_steps, script=None):
        self.id = rid
        self.goal = goal
        self.model = model
        self.max_steps = max_steps
        self.script = script
        self.status = "running"           # running|paused|aborting|aborted|done
        self.trace = []
        self.summary = None
        self.created = round(time.time(), 3)
        self.paused = False
        self.abort = False
        self.pause_notified = False
        self.resume_ev = threading.Event()
        self.resume_ev.set()

    def public(self):
        return {"id": self.id, "goal": self.goal, "model": self.model,
                "max_steps": self.max_steps, "status": self.status,
                "created": self.created, "summary": self.summary,
                "steps": len(self.trace), "trace": self.trace,
                "scripted": self.script is not None}


RUNS = {}
RUNS_LOCK = threading.RLock()


def new_run(goal, model=None, max_steps=6, script=None):
    st = RunState("run_" + uuid.uuid4().hex[:8], goal, model, max_steps, script)
    with RUNS_LOCK:
        RUNS[st.id] = st
        if len(RUNS) > 200:  # keep memory bounded
            for rid in sorted(RUNS, key=lambda r: RUNS[r].created)[:len(RUNS) - 200]:
                RUNS.pop(rid, None)
    return st


def run_get(rid):
    with RUNS_LOCK:
        return RUNS.get(rid)


def run_control(rid, action):
    st = run_get(rid)
    if not st or action not in ("pause", "resume", "abort"):
        return None
    terminal = st.status in ("done", "aborted", "error")
    if action == "pause" and not terminal:
        st.paused = True
        st.resume_ev.clear()
        if st.status == "running":
            st.status = "paused"
    elif action == "resume" and not terminal:
        st.paused = False
        if st.status == "paused":
            st.status = "running"
        st.resume_ev.set()
    elif action == "abort" and not terminal:
        st.abort = True
        st.status = "aborting"
        st.resume_ev.set()
    _publish("agent.control", run=rid, action=action, status=st.status, terminal=terminal)
    return st


def checkpoint(st):
    """Honour pause/abort. Called at every step and while waiting for approvals."""
    if st is None:
        return
    if st.abort:
        if st.status != "aborted":
            st.status = "aborting"
        raise AbortRun()
    if st.paused:
        if not st.pause_notified:
            st.pause_notified = True
            _publish("agent.paused", run=st.id)
        st.resume_ev.wait()
        st.pause_notified = False
        if st.abort:
            raise AbortRun()


# -------------------------------------------------------------- tool gate ---

def tool_action(st, tool, args, on_event):
    """Gate then execute one tool action inside a run.

    Returns (observation_text, meta) where meta carries the evidence:
    approval id/status/decided_by, sandbox backend, exit code, stdout/stderr.
    """
    run_id = st.id if st else None
    args = args or {}
    spec = registry.tool_spec(tool)
    if spec is None:
        obs = "unknown tool %r — available: %s" % (tool, ", ".join(registry.tool_names()))
        _publish("tool.blocked", run=run_id, tool=tool, reason="unknown tool")
        return obs, {"tool": tool, "blocked": "unknown"}

    decision, reason = registry.classify(tool, args)
    if decision in ("disabled", "denied"):
        _publish("tool.blocked", run=run_id, tool=tool, args=args, reason=reason)
        on_event("tool.blocked", run=run_id, tool=tool, reason=reason)
        return "tool %r blocked by policy: %s" % (tool, reason), {"tool": tool, "blocked": reason}

    if decision == "auto":
        rec = approvals.create(tool, args, run_id=run_id,
                               decision="auto_approved", reason=reason)
        _publish("approval.auto", id=rec["id"], run=run_id, tool=tool,
                 summary=rec["summary"], reason=reason)
        on_event("approval.auto", run=run_id, id=rec["id"], tool=tool,
                 summary=rec["summary"], reason=reason)
    else:
        rec = approvals.create(tool, args, run_id=run_id, decision="pending", reason=reason)
        _publish("approval.request", id=rec["id"], run=run_id, tool=tool,
                 summary=rec["summary"], args=args)
        on_event("approval.request", run=run_id, id=rec["id"], tool=tool,
                 summary=rec["summary"], args=args)
        rec = approvals.wait(rec["id"], checkpoint=(lambda: checkpoint(st)) if st else None)
        if rec["status"] != "approved":
            _publish("approval.resolved", id=rec["id"], run=run_id, tool=tool,
                     status=rec["status"], by=rec.get("decided_by"))
            on_event("approval.resolved", run=run_id, id=rec["id"], status=rec["status"],
                     by=rec.get("decided_by"))
            return ("action not executed: approval %s %s (by %s)"
                    % (rec["id"], rec["status"], rec.get("decided_by")),
                    {"tool": tool, "approval_id": rec["id"], "approval_status": rec["status"]})
        _publish("approval.resolved", id=rec["id"], run=run_id, tool=tool,
                 status="approved", by=rec.get("decided_by"))
        on_event("approval.resolved", run=run_id, id=rec["id"], status="approved",
                 by=rec.get("decided_by"))

    _publish("tool.call", run=run_id, tool=tool, args=args, approval=rec["id"])
    on_event("tool.call", run=run_id, tool=tool, args=args, approval=rec["id"])
    res = toolmod.execute(tool, args, run_id=run_id)
    meta = {"tool": tool, "approval_id": rec["id"], "approval_status": rec["status"],
            "approval_by": rec.get("decided_by"), "sandbox_backend": res.get("backend"),
            "sandboxed": res.get("sandboxed"), "exit_code": res.get("exit_code"),
            "stdout": (res.get("stdout") or "")[:4000], "stderr": (res.get("stderr") or "")[:2000],
            "duration_ms": res.get("duration_ms"), "ok": res.get("ok")}
    _publish("tool.result", run=run_id, tool=tool, approval=rec["id"], ok=res.get("ok"),
             exit_code=res.get("exit_code"), backend=res.get("backend"),
             sandboxed=res.get("sandboxed"), duration_ms=res.get("duration_ms"),
             stdout=(res.get("stdout") or "")[:2000], stderr=(res.get("stderr") or "")[:1000])
    on_event("tool.result", run=run_id, tool=tool, ok=res.get("ok"),
             exit_code=res.get("exit_code"), backend=res.get("backend"),
             sandboxed=res.get("sandboxed"), duration_ms=res.get("duration_ms"),
             stdout=(res.get("stdout") or "")[:20000], stderr=(res.get("stderr") or "")[:8000])
    return toolmod.observation(res), meta


def gated_call(tool, args, run_id=None, wait=True, by="api", timeout=None):
    """One-shot gated tool call used by POST /api/tools/call and the chat loop.

    `timeout` (JAG-80) caps how long a `required` tool waits for a human decision.
    The chat loop passes a short cap so a turn can never freeze for the full
    approvals.timeout_secs (300s): the request is recorded, the app shows an
    inline Approve/Deny card, and if nobody decides in time the model continues.
    """
    spec = registry.tool_spec(tool)
    if spec is None:
        return {"status": "error", "error": "unknown tool %r" % tool}
    if not spec["enabled"]:
        _publish("tool.blocked", run=run_id, tool=tool, reason="not enabled")
        return {"status": "blocked", "reason": "tool %r is disabled (allowlist)" % tool}
    decision, reason = registry.classify(tool, args or {})
    if decision in ("disabled", "denied"):
        _publish("tool.blocked", run=run_id, tool=tool, args=args, reason=reason)
        return {"status": "blocked", "reason": reason}
    rec = approvals.create(tool, args or {}, run_id=run_id,
                           decision="auto_approved" if decision == "auto" else "pending",
                           reason=reason)
    if rec["status"] == "pending":
        _publish("approval.request", id=rec["id"], run=run_id, tool=tool,
                 summary=rec["summary"], args=args)
        if wait:
            rec = approvals.wait(rec["id"], timeout=timeout)
            if rec["status"] != "approved":
                _publish("approval.resolved", id=rec["id"], run=run_id, tool=tool,
                         status=rec["status"], by=rec.get("decided_by"))
                return {"status": rec["status"], "approval": rec, "reason": reason}
            _publish("approval.resolved", id=rec["id"], run=run_id, tool=tool,
                     status="approved", by=rec.get("decided_by"))
        else:
            return {"status": "pending", "approval": rec, "reason": reason}
    else:
        _publish("approval.auto", id=rec["id"], run=run_id, tool=tool,
                 summary=rec["summary"], reason=reason)
    res = toolmod.execute(tool, args or {}, run_id=run_id)
    _publish("tool.result", run=run_id, tool=tool, approval=rec["id"], ok=res.get("ok"),
             exit_code=res.get("exit_code"), backend=res.get("backend"),
             sandboxed=res.get("sandboxed"), stdout=(res.get("stdout") or "")[:2000])
    return {"status": "executed", "approval": rec, "result": res,
            "observation": toolmod.observation(res)}


# ------------------------------------------------------------- agent loop ---

AGENT_PROMPT_V2 = (
    "You are the agent loop of the SparkForge harness. Given the goal and the "
    "current harness state, decide ONE next action. Respond with ONLY one JSON "
    'object, always with a "thought" field. Actions:\n'
    '  {"action":"write_todos","todos":[{"label":"...","deps":[]}]}\n'
    '  {"action":"tool","tool":"<name>","args":{...}}   run a registered tool\n'
    '  {"action":"plan_step","title":"...","detail":"..."}\n'
    '  {"action":"complete_plan_step","id":"..."}\n'
    '  {"action":"add_task","title":"..."}\n'
    '  {"action":"complete_task","id":"..."}\n'
    '  {"action":"note","detail":"..."}\n'
    '  {"action":"finish","summary":"..."}\n'
    "Every action that touches the world goes through an approval gate: if the "
    "gate requires a human, the run PAUSES until the decision arrives, then the "
    "observation carries the tool output. Prefer one tool call per iteration."
)


def tool_context():
    """The tool block for the chat/agent prompt.

    JAG-80: only ENABLED tools are listed as callable. Disabled ones (e.g. the
    opt-in pmcp gateway surface) are collapsed into one compact footer line — a
    huge [DISABLED] wall used to drown the real tools and push the model into
    calling an approval-gated gateway tool.
    """
    lines = ["Tool registry (allowlist — only enabled tools may be called):"]
    disabled = []
    for t in registry.catalog():
        if not t["enabled"]:
            disabled.append(t["name"])
            continue
        props = ", ".join((t["inputSchema"].get("properties") or {}).keys())
        lines.append("  - %-9s(%s) approval=%s :: %s"
                     % (t["name"], props, t["approval"], t["description"]))
    if disabled:
        lines.append("(present but DISABLED / not callable: %s — only the user can "
                     "enable one in config/tools.yaml)" % ", ".join(disabled))
    return "\n".join(lines)


def agent_run_v2(goal, max_steps=6, model=None, on_event=None, script=None, run_id=None):
    """Sense-think-act loop with real tools behind the approval gate + HITL."""
    srv = _srv()
    if on_event is None:
        on_event = lambda kind, **d: srv.publish(kind, **d)
    st = run_get(run_id) if run_id else new_run(goal, model, max_steps, script)
    if st is None:
        st = new_run(goal, model, max_steps, script)
    st.goal, st.max_steps, st.script = goal, max_steps, script
    model = model or srv.default_model()
    # v0.3 multi-model routing: role-based selection keeps the explicit model
    # request intact and otherwise picks the agent-role alias from the roster.
    if not model:
        try:
            import routing
            model = routing.pick("agent") or srv.default_model()
        except Exception:
            model = srv.default_model()
    st.model = model
    # v0.3 checkpoint at run start (idempotent per run) so plan/tasks/transcript
    # survive a restart and can be rolled back after a bad run.
    try:
        import checkpoints
        _CHECKPOINTS_START = checkpoints.create(
            label="agent run %s" % st.id, idempotency_key="agent-run:" + st.id,
            by="agent-loop")
        on_event("checkpoint.created", run=st.id, id=_CHECKPOINTS_START.get("id"))
    except Exception:
        _CHECKPOINTS_START = None
    probe = sandbox.probe()
    on_event("agent.start", run=st.id, goal=goal, max_steps=max_steps,
             scripted=script is not None, sandbox=probe["backend"], isolated=probe["isolated"])
    # v0.6: the FIRST action of every (non-scripted) run is a model-generated
    # write_todos call → the per-run task graph, streamed live as nodes land.
    if script is None:
        try:
            srv.start_run_graph(st.id, goal, None, model, on_event=on_event)
        except Exception as e:  # noqa: BLE001 — graph must never break the run
            _publish("graph.error", run=st.id, error=str(e))
    last_sig, repeated = None, 0
    # JAG-61: persistent turn history. The observation produced at step N MUST be
    # visible to the model at step N+1, otherwise the model re-derives everything
    # from scratch each iteration, never learns its own tool output, and loops
    # forever (the exact failure that looked like "the model cannot install the
    # app"). We carry assistant actions + observations across the whole run.
    hist = []
    try:
        for i in range(max_steps):
            checkpoint(st)
            if script is not None:
                act = script[i] if i < len(script) else {"action": "finish",
                                                         "summary": "script complete",
                                                         "thought": "script exhausted"}
                thought = str(act.get("thought", ""))[:400]
                action = act.get("action")
                on_event("agent.thought", run=st.id, i=i + 1, thought=thought,
                         action=action, scripted=True)
            else:
                sysp = (srv.SYSTEM_PROMPT + "\n\n" + AGENT_PROMPT_V2 + "\n\n"
                        + tool_context() + "\n\nHarness state (your persistent task list):\n"
                        + srv.context_summary(graph_key=st.id))
                if not hist:
                    hist.append({"role": "user", "content":
                                 "Goal: %s\n\nWork step by step: issue ONE action "
                                 "per message, read each Observation, then continue "
                                 "from what you already learned. Do not repeat an "
                                 "action that already succeeded. Keep going until "
                                 "the goal is fully accomplished (max %d steps)."
                                 % (goal, max_steps)})
                msgs = [{"role": "system", "content": sysp}] + hist
                on_event("agent.iteration", run=st.id, i=i + 1, of=max_steps)
                answer, think = srv._router_stream(
                    msgs, model, lambda ch, t: on_event("agent.think", channel=ch, text=t))
                act = srv.extract_json(answer) or {}
                if not isinstance(act, dict) or not act.get("action"):
                    act = {"thought": answer[:200], "action": "note", "detail": answer[:400]}
                thought = str(act.get("thought", ""))[:400]
                action = act.get("action")
                on_event("agent.thought", run=st.id, i=i + 1, thought=thought, action=action)

            if action == "finish":
                summary = str(act.get("summary", ""))[:600] or "done"
                st.summary, st.status = summary, "done"
                on_event("agent.finish", run=st.id, summary=summary)
                st.trace.append({"i": i + 1, "thought": thought, "action": "finish",
                                 "summary": summary})
                return _result(st, goal, model)

            # JAG-58: no-progress guard. A small model can re-emit the identical
            # action forever and never call `finish`, so the run dies at
            # max_steps having "worked" but never concluded. If the same action
            # (tool+args, or step+id+title) repeats, conclude the run instead of
            # re-executing it — deterministic termination for any model.
            try:
                raw_args = dict(act.get("args") or {})
                for k in ("command", "path", "url", "content"):
                    if k in act and k not in raw_args:
                        raw_args[k] = act[k]
                # volatile keys a small model flips between otherwise-identical
                # calls (e.g. timeout) must not defeat the guard.
                norm_args = {k: v for k, v in raw_args.items()
                             if k not in ("timeout_secs", "timeout", "args")}
                sig = (action, act.get("tool"),
                       json.dumps(norm_args, sort_keys=True, default=str),
                       act.get("id"), act.get("title"))
            except (TypeError, ValueError):
                sig = str(action)
            if sig == last_sig:
                repeated += 1
            else:
                repeated, last_sig = 1, sig
            if repeated >= 2:
                summary = "no progress: %r repeated; concluding run" % action
                st.summary, st.status = summary, "done"
                on_event("agent.finish", run=st.id, summary=summary, no_progress=True)
                _publish("agent.no_progress", run=st.id, action=action)
                st.trace.append({"i": i + 1, "thought": thought, "action": "finish",
                                 "summary": summary})
                return _result(st, goal, model)

            if action == "tool":
                tool = act.get("tool")
                args = dict(act.get("args") or {})
                for k in ("command", "path", "content", "url", "args"):
                    if k in act and k not in args:
                        args[k] = act[k]
                checkpoint(st)
                entry = {"i": i + 1, "thought": thought, "action": "tool",
                         "tool": tool, "args": args}
                obs, meta = tool_action(st, tool, args, on_event)
                entry["observation"] = obs
                entry["tool_result"] = meta
            else:
                obs = srv.apply_agent_action(act, run_id=st.id)
                entry = {"i": i + 1, "thought": thought, "action": action,
                         "observation": obs}

            st.trace.append(entry)
            on_event("agent.observation", run=st.id, i=i + 1, observation=obs)
            if script is None:
                # JAG-61: feed the action + its observation back so the next
                # iteration continues from evidence instead of restating the goal.
                hist.append({"role": "assistant",
                             "content": json.dumps(act, ensure_ascii=False, default=str)[:4000]})
                hist.append({"role": "user", "content":
                             "Observation (step %d/%d):\n%s"
                             % (i + 1, max_steps, (obs or "")[:4000])})
                if len(hist) > 30:
                    del hist[:-30]
        else:
            summary = "stopped at max_steps=%d; see trace" % max_steps
            st.summary, st.status = summary, "done"
            on_event("agent.finish", run=st.id, summary=summary)
            st.trace.append({"action": "finish", "summary": summary})
    except AbortRun:
        st.status = "aborted"
        summary = "aborted by operator at step %d" % len(st.trace)
        st.summary = summary
        _publish("agent.aborted", run=st.id, summary=summary)
        on_event("agent.aborted", run=st.id, summary=summary)
        st.trace.append({"action": "abort", "summary": summary})
    except Exception as e:  # noqa: BLE001
        st.status = "error"
        st.summary = "run error: %s" % e
        on_event("agent.error", run=st.id, error=str(e))
    return _result(st, goal, model)


def _result(st, goal, model):
    if st.status in ("running", "paused", "aborting"):
        st.status = "done"
    # v0.6: run end — close every still-open graph node with evidence.
    try:
        _srv().finish_run_graph(st.id, None, goal)
    except Exception:  # noqa: BLE001
        pass
    try:  # JAG-69: deterministic Stop hooks at the end of the run
        import hooks
        hooks.run("Stop", run_id=st.id, observation=st.summary)
    except Exception:  # noqa: BLE001
        pass
    # JAG-95: deterministic process-reward / verification report over the trace.
    # Pure function (no model) — never breaks a run on failure.
    prm_report = None
    try:
        import prm
        import taskgraph as _tg
        _g = _tg.load(st.id)
        open_n = sum(1 for n in (_g or {}).get("nodes", [])
                     if n.get("status") in ("todo", "doing", "blocked"))
        ev = prm.evaluate(st.trace, open_nodes=open_n)
        prm_report = {"score": ev["score"], "issues": [i["code"] for i in ev["issues"]],
                      "feedback": ev["feedback"]}
        if ev["feedback"]:
            _publish("prm.feedback", run=st.id, score=ev["score"],
                     issues=[i["code"] for i in ev["issues"]], feedback=ev["feedback"])
    except Exception:  # noqa: BLE001
        prm_report = None
    return {"run_id": st.id, "goal": goal, "model": model, "status": st.status,
            "summary": st.summary, "trace": st.trace, "prm": prm_report}


def agent_stream_gen_v2(goal, max_steps, model, run_id, script=None):
    srv = _srv()
    q = queue.Queue()

    def on_event(kind, **d):
        q.put("event: %s\ndata: %s\n\n" % (kind, json.dumps(d, ensure_ascii=False)))
        if not kind.startswith("agent.think"):
            srv.publish(kind, **d)

    def worker():
        try:
            agent_run_v2(goal, max_steps, model, on_event, script=script, run_id=run_id)
        except Exception as e:  # noqa: BLE001
            q.put("event: error\ndata: %s\n\n" % json.dumps({"error": str(e)}))
        finally:
            q.put(None)

    yield "event: run\ndata: %s\n\n" % json.dumps({"run_id": run_id})
    threading.Thread(target=worker, daemon=True).start()
    while True:
        try:
            item = q.get(timeout=15)
        except queue.Empty:
            # Keepalive: a run blocked on an approval gate can stay silent for
            # up to 300s; without this the SSE channel idles and mobile
            # networks/proxies abort it ("Software caused connection abort").
            # Clients ignore SSE comment lines.
            yield ": ping\n\n"
            continue
        if item is None:
            break
        yield item
    yield "event: done\ndata: {}\n\n"


# ------------------------------------------------------------- MCP backend --

class LocalApi:
    """Harness operations for the in-process MCP endpoint (POST /mcp)."""

    def status(self):
        return _srv().status_payload()

    def chat(self, message, session=None, model=None):
        srv = _srv()
        sess = srv.get_or_create_session(session)
        mark = srv.session_mark(sess)  # JAG-51: boundary of this request
        srv.append_message(sess, "user", message)
        srv.publish("chat.user", session=sess["id"], text=message)
        try:
            reply, mdl = srv.chat_once(sess, message, model)
        except Exception as e:  # noqa: BLE001
            # JAG-51: same contract as /api/chat — persist the error turn.
            srv.ensure_reply_persisted(sess, mark, error=e, model=model)
            return {"session": sess["id"], "model": model, "error": str(e),
                    "stored_error": True}
        return {"session": sess["id"], "model": mdl, "reply": reply.get("content"),
                "reasoning": reply.get("reasoning"), "error": bool(reply.get("error"))}

    def plan(self, goal=None):
        srv = _srv()
        if goal:
            plan, answer, think, run_id = srv.generate_plan(goal)
            return {"plan": plan, "raw": answer[:800], "run_id": run_id}
        return srv.load_plan()

    def tasks(self, a):
        srv = _srv()
        a = a or {}
        action = a.get("action", "list")
        if action == "add":
            title = str(a.get("title", ""))
            if not title:
                return {"error": "title required"}
            store = srv.load_tasks()
            t = {"id": uuid.uuid4().hex[:6], "title": title[:140],
                 "status": "todo", "created": round(time.time(), 3)}
            store.setdefault("tasks", []).append(t)
            srv.save_tasks(store)
            return t
        if action == "set":
            store = srv.load_tasks()
            for t in store.get("tasks", []):
                if t["id"] == a.get("id"):
                    if a.get("status") in ("todo", "doing", "done"):
                        t["status"] = a["status"]
                        if a["status"] == "done":
                            t["done_ts"] = round(time.time(), 3)
                    if a.get("title"):
                        t["title"] = str(a["title"])[:140]
                    srv.save_tasks(store)
                    return t
            return {"error": "task not found"}
        tasks = srv.load_tasks()
        remaining = ["%s: %s" % (t["status"], t["title"]) for t in tasks.get("tasks", [])
                     if t.get("status") != "done"]
        return {**tasks, "remaining": remaining}

    def agent_run(self, goal, max_steps=6, model=None):
        return agent_run_v2(goal, max_steps, model)

    def feed(self, since=0, limit=40):
        return {"events": _srv().events_since(since)[-limit:]}

    def tools(self):
        return {"tools": registry.catalog(), "sandbox": sandbox.probe(),
                "approvals": approvals.stats()}

    def approvals(self, a):
        a = a or {}
        if a.get("action") == "decide":
            rec = approvals.decide(a.get("id"), a.get("decision"), a.get("by", "mcp"))
            _publish("approval.decided", id=a.get("id"), decision=a.get("decision"),
                     by=a.get("by", "mcp"))
            return rec or {"error": "approval not found"}
        return {"approvals": approvals.list_all(a.get("status"), 100), "stats": approvals.stats()}


# ---------------------------------------------- lazy Sperimentale modules ----
# Sperimentale/v0.3 routes import optional feature modules on first use so a
# broken optional dep can never take down the core harness.

_LAZY_MODS = {"memory": "_MEMORY", "mcp_client": "_MCP_CLIENT", "subagent": "_SUBAGENT",
              "meta": "_META", "swarm": "_SWARM", "acp": "_ACP",
              "checkpoints": "_CHECKPOINTS", "context_engine": "_CONTEXT",
              "routing": "_ROUTING", "providers": "_PROVIDERS"}


def _lazy(name):
    import importlib
    attr = _LAZY_MODS.get(name)
    if attr is None:
        raise ValueError("unknown lazy module %r" % name)
    if getattr(sys.modules[__name__], attr, None) is None:
        setattr(sys.modules[__name__], attr, importlib.import_module(name))


import checkpoints  # noqa: E402  (v0.3)
import context_engine  # noqa: E402  (v0.3)


# --------------------------------------------------------------- HTTP glue --

def _r(handler, code, obj):
    handler._send(code, obj)
    return True


def handle(handler, method, path, qs, body):
    """Return True if this module produced the response.

    Routes: v0.2 core + Sperimentale (memory, subagent, meta, acp, blackboard, swarm).
    """

    if method == "GET":
        # v0.2 core GET routes
        if path == "/api/tools":
            return _r(handler, 200, {"tools": registry.catalog(),
                                     "sandbox": sandbox.probe(force=qs.get("probe") == "1"),
                                     "approvals": approvals.stats()})
        if path == "/api/tools/running":
            return _r(handler, 200, {"running": sandbox.running()})
        if path == "/api/hooks":
            import hooks
            return _r(handler, 200, {"hooks": hooks.load(reload=qs.get("reload") == "1"),
                                     "events": list(hooks.EVENTS),
                                     "config": hooks.CONFIG})
        if path == "/api/sandbox":
            return _r(handler, 200, sandbox.probe(force=qs.get("force") == "1"))
        if path == "/api/approvals":
            return _r(handler, 200, {
                "approvals": approvals.list_all(qs.get("status"), int(qs.get("limit", 100))),
                "stats": approvals.stats()})
        if path.startswith("/api/approvals/"):
            rec = approvals.get(path.rsplit("/", 1)[-1])
            return _r(handler, 200, rec) if rec else _r(handler, 404, {"error": "approval not found"})
        if path == "/api/feed/recent":
            since, limit = int(qs.get("since", 0)), int(qs.get("limit", 40))
            return _r(handler, 200, {"events": _srv().events_since(since)[-limit:]})
        if path == "/api/agent/runs":
            return _r(handler, 200, {"runs": [r.public() for r in
                                              sorted(RUNS.values(), key=lambda r: r.created,
                                                     reverse=True)]})
        if path.startswith("/api/agent/runs/"):
            st = run_get(path.rsplit("/", 1)[-1])
            return _r(handler, 200, st.public()) if st else _r(handler, 404, {"error": "run not found"})
        if path == "/api/agent/run":  # SSE, tool-enabled loop
            goal = qs.get("goal", "")
            if not goal:
                return _r(handler, 400, {"error": "goal required"})
            max_steps = int(qs.get("max_steps", 6))
            st = new_run(goal, qs.get("model"), max_steps)
            return _sse(handler, agent_stream_gen_v2(goal, max_steps, qs.get("model"), st.id))

        # --- Sperimentale GET routes ---
        if path == "/api/memory":
            _lazy('memory')
            query_text = qs.get("query", "")
            kind = qs.get("kind")
            limit = int(qs.get("limit", 20))
            semantic = qs.get("semantic", "").lower() in ("1", "true", "yes")
            if query_text:
                results = _MEMORY.search(query_text, kind, limit, semantic)
                return _r(handler, 200, {"results": [{"score": s, **r} for s, r in results]})
            return _r(handler, 200, _MEMORY.stats())

        if path == "/api/mcp/clients":
            _lazy('mcp_client')
            return _r(handler, 200, _MCP_CLIENT.status())

        # --- JAG-109: skills (engine in skills.py) ---
        if path == "/api/skills":
            import skills as skills_mod
            items = skills_mod.list_skills()
            return _r(handler, 200, {"skills": items, "count": len(items),
                                     "local_dir": skills_mod._local_dir()})
        if path.startswith("/api/skills/"):
            import skills as skills_mod
            nm = path[len("/api/skills/"):]
            sk = skills_mod.get_skill(nm)
            return _r(handler, 200, sk) if sk else \
                _r(handler, 404, {"error": "skill not found: %s" % nm})

        if path == "/api/subagent":
            _lazy('subagent')
            sid = qs.get("id")
            return _r(handler, 200, _SUBAGENT.status(sid))

        if path == "/api/meta":
            _lazy('meta')
            action = qs.get("action", "status")
            if action == "best":
                return _r(handler, 200, _META.propose_best())
            return _r(handler, 200, _META.status())

        if path == "/api/blackboard":
            _lazy('swarm')
            eid = qs.get("id")
            topic = qs.get("topic")
            tags = qs.get("tags")
            limit = int(qs.get("limit", 50))
            tag_list = tags.split(",") if tags else None
            if eid:
                thread = qs.get("thread", "").lower() in ("1", "true", "yes")
                if thread:
                    return _r(handler, 200, {"thread": _SWARM.thread(eid)})
                entry = _SWARM.get(entry_id=eid)
                return _r(handler, 200, entry[0] if entry else {"error": "not found"})
            entries = _SWARM.get(topic=topic, tags=tag_list, limit=limit)
            return _r(handler, 200, {"entries": entries, "stats": _SWARM.stats()})

        if path == "/api/blackboard/watch":
            _lazy('swarm')
            since = int(qs.get("since", 0))
            # blackboard watcher = loopback tail, kept open on purpose (JAG-48)
            return _sse(handler, _SWARM.watch_gen(since), keepalive=True)

        if path == "/api/checkpoints":
            _lazy('checkpoints')
            return _r(handler, 200, {"checkpoints": _CHECKPOINTS.list_checkpoints(
                int(qs.get("limit", 50)))})
        if path.startswith("/api/checkpoints/"):
            _lazy('checkpoints')
            cp_id = path.rsplit("/", 1)[-1]
            manifest = _CHECKPOINTS.get(cp_id)
            return _r(handler, 200, manifest) if manifest else \
                _r(handler, 404, {"error": "checkpoint not found"})

        if path == "/api/routing":
            _lazy('routing')
            return _r(handler, 200, _ROUTING.status())

        return False

    if method == "POST":
        # v0.2 core POST routes
        if path == "/api/tools":
            return _r(handler, 200, update_policy(body))
        if path == "/api/tools/call":
            tool = body.get("tool")
            if not tool:
                return _r(handler, 400, {"error": "tool required"})
            return _r(handler, 200, gated_call(tool, body.get("args") or {},
                                               body.get("run_id"), body.get("wait", True),
                                               body.get("by", "api")))
        if path == "/api/tools/cancel":
            job = body.get("job") or body.get("run_id")
            if not job:
                return _r(handler, 400, {"error": "job or run_id required"})
            res = sandbox.cancel(job)
            _publish("tool.cancel", job=job, cancelled=res.get("cancelled"))
            return _r(handler, 200, res)
        if path.startswith("/api/approvals/"):
            rec = approvals.decide(path.rsplit("/", 1)[-1], body.get("decision"),
                                   body.get("by", "webui"))
            if not rec:
                return _r(handler, 404, {"error": "approval not found"})
            _publish("approval.decided", id=rec["id"], decision=body.get("decision"),
                     by=rec.get("decided_by"), status=rec["status"])
            return _r(handler, 200, rec)
        if path == "/api/agent/control":
            rid, action = body.get("runId") or body.get("run_id"), body.get("action")
            st = run_control(rid, action)
            if not st:
                return _r(handler, 404, {"error": "run not found or bad action"})
            return _r(handler, 200, st.public())
        if path in ("/mcp", "/api/mcp"):
            return _r(handler, 200, _mcp_message(body))

        # --- JAG-108: user-managed external MCP clients (engine lives in mcp_client) ---
        if path == "/api/mcp/clients":
            _lazy('mcp_client')
            res = _MCP_CLIENT.upsert_client(body.get("name"), body)
            _publish("mcp.clients", action="upsert", name=body.get("name"),
                     ok=bool(res.get("ok")))
            return _r(handler, 200 if res.get("ok") else 400, res)
        if path == "/api/mcp/clients/remove":
            _lazy('mcp_client')
            res = _MCP_CLIENT.remove_client(body.get("name"))
            _publish("mcp.clients", action="remove", name=body.get("name"),
                     ok=bool(res.get("ok")))
            return _r(handler, 200 if res.get("ok") else 400, res)
        if path == "/api/mcp/clients/test":
            _lazy('mcp_client')
            return _r(handler, 200, _MCP_CLIENT.test_client(body))
        if path == "/api/mcp/reload":
            _lazy('mcp_client')
            return _r(handler, 200, _MCP_CLIENT.reload())
        if path == "/api/agent/run":
            goal = body.get("goal", "")
            if not goal:
                return _r(handler, 400, {"error": "goal required"})
            script = body.get("script")
            if script is not None and not isinstance(script, list):
                return _r(handler, 400, {"error": "script must be a list of actions"})
            result = agent_run_v2(goal, int(body.get("max_steps", 6)), body.get("model"),
                                  script=script)
            return _r(handler, 200, result)

        # --- Sperimentale POST routes ---
        if path == "/api/memory":
            _lazy('memory')
            kind = body.get("kind", "memory.store")
            content = body.get("content", "")
            meta = {k: v for k, v in body.items() if k not in ("kind", "content")}
            rec = _MEMORY.store(kind, content, **meta)
            return _r(handler, 200, rec)

        if path == "/api/subagent/spawn":
            _lazy('subagent')
            goal = body.get("goal", "")
            if not goal:
                return _r(handler, 400, {"error": "goal required"})
            max_steps = int(body.get("max_steps", 4))
            result = _SUBAGENT.spawn(goal, parent_run_id=body.get("run_id"),
                                     max_steps=max_steps, model=body.get("model"))
            return _r(handler, 200, result)

        if path == "/api/subagent/collect":
            _lazy('subagent')
            sid = body.get("id") or body.get("subagent_id")
            if not sid:
                return _r(handler, 400, {"error": "subagent_id required"})
            timeout = body.get("timeout", 120)
            result = _SUBAGENT.collect(sid, timeout=timeout)
            return _r(handler, 200, result)

        if path == "/api/meta":
            _lazy('meta')
            action = body.get("action", "run")
            if action == "run":
                n_candidates = int(body.get("n_candidates", 8))
                candidates = _META.sample_candidates(n=n_candidates)
                report = _META.meta_run(candidates, eval_task_id=body.get("eval_task_id"))
                return _r(handler, 200, report)
            return _r(handler, 200, _META.status())

        if path == "/api/acp":
            _lazy('acp')
            resp = _ACP.handle_http(body)
            return _r(handler, 200, resp if resp else {})

        if path == "/api/acp/connect":
            _lazy('acp')
            name = body.get("name", "")
            url = body.get("url", "")
            if not name or not url:
                return _r(handler, 400, {"error": "name and url required"})
            ok = _ACP.get_manager().connect(name, url, body.get("token"))
            return _r(handler, 200, {"connected": ok, "name": name, "url": url})

        if path == "/api/blackboard":
            _lazy('swarm')
            topic = body.get("topic", "general")
            content = body.get("content", "")
            if not content:
                return _r(handler, 400, {"error": "content required"})
            entry = _SWARM.post(topic, content,
                               tags=body.get("tags"),
                               parent=body.get("parent"),
                               author=body.get("author", "api"),
                               run_id=body.get("run_id"))
            return _r(handler, 200, entry)

        if path == "/api/swarm/run":
            _lazy('swarm')
            goal = body.get("goal", "")
            if not goal:
                return _r(handler, 400, {"error": "goal required"})
            n_workers = int(body.get("n_workers", 3))
            max_steps = int(body.get("max_steps", 4))
            coord = _SWARM.Coordinator()
            report = coord.run_swarm(goal, n_workers, max_steps, body.get("model"))
            return _r(handler, 200, report)

        # --- v0.3 POST routes: checkpoints / context / routing ---
        if path == "/api/checkpoints":
            _lazy('checkpoints')
            manifest = _CHECKPOINTS.create(
                label=body.get("label"), session_id=body.get("session"),
                idempotency_key=body.get("idempotency_key"),
                by=body.get("by", "api"))
            return _r(handler, 200 if "error" not in manifest else 400, manifest)
        if path.startswith("/api/checkpoints/") and path.endswith("/rollback"):
            _lazy('checkpoints')
            cp_id = path[len("/api/checkpoints/"):-len("/rollback")]
            res = _CHECKPOINTS.rollback(cp_id, by=body.get("by", "api"))
            return _r(handler, 200 if res.get("ok") else 404, res)
        if path == "/api/context/preview":
            _lazy('context_engine')
            res = _CONTEXT.preview(body.get("session"), body.get("message"),
                                   int(body.get("budget_tokens",
                                                _CONTEXT.DEFAULT_BUDGET)))
            return _r(handler, 200 if "error" not in res else 404, res)
        # --- JAG-112: user-editable providers / models -------------------------
        if path == "/api/providers":
            res = provider_upsert(body)
            return _r(handler, 200 if res.get("ok") else 400, res)
        if path == "/api/providers/models":
            res = provider_add_model(body)
            return _r(handler, 200 if res.get("ok") else 400, res)
        if path == "/api/providers/default":
            res = provider_set_default(body)
            return _r(handler, 200 if res.get("ok") else 400, res)
        if path == "/api/providers/reload":
            return _r(handler, 200, provider_reload())
        if path == "/api/routing":
            _lazy('routing')
            return _r(handler, 200, _ROUTING.update(body))

        return False

    if method == "DELETE":
        # JAG-108: delete a user-managed external MCP client by name.
        if path == "/api/mcp/clients":
            _lazy('mcp_client')
            res = _MCP_CLIENT.remove_client(qs.get("name"))
            _publish("mcp.clients", action="remove", name=qs.get("name"),
                     ok=bool(res.get("ok")))
            return _r(handler, 200 if res.get("ok") else 400, res)

        # JAG-109: remove a user-installed (local) skill.
        if path.startswith("/api/skills/"):
            import skills as skills_mod
            nm = path[len("/api/skills/"):]
            res = skills_mod.remove(nm)
            _publish("skills.remove", name=nm, ok=bool(res.get("ok")))
            return _r(handler, 200 if res.get("ok") else 400, res)

        # JAG-112: remove a provider / a model.
        if path == "/api/providers":
            res = provider_remove(qs.get("id"))
            return _r(handler, 200 if res.get("ok") else 400, res)
        if path == "/api/providers/models":
            res = provider_remove_model(qs.get("provider"), qs.get("model"))
            return _r(handler, 200 if res.get("ok") else 400, res)
        return False
    return False


def _sse(handler, gen, keepalive=False):
    return _srv().sse_response(handler, gen, keepalive=keepalive) or True


def _mcp_message(body):
    """Handle one (or a batch of) MCP JSON-RPC message(s)."""
    if isinstance(body, list):
        out = [mcp.handle(m, LocalApi()) for m in body]
        return [r for r in out if r is not None]
    resp = mcp.handle(body, LocalApi())
    return resp if resp is not None else {"jsonrpc": "2.0", "id": None, "result": {}}


def _reload_policy(cfg=None):
    import os
    if cfg is None:
        registry.load_config(reload=True)
    return registry.catalog()


def update_policy(body):
    """POST /api/tools — flip enabled / approval / auto_approve for a tool."""
    name = body.get("tool") or body.get("name")
    if not name:
        return {"error": "tool required", "tools": registry.catalog()}
    cfg = registry.load_config()
    entry = cfg.setdefault("tools", {}).setdefault(name, {})
    if "enabled" in body:
        entry["enabled"] = bool(body["enabled"])
    if "approval" in body:
        entry["approval"] = str(body["approval"])
    if "auto_approve" in body:
        entry["auto_approve"] = list(body["auto_approve"])
    registry.save_config(cfg)
    registry.load_config(reload=True)
    _publish("tools.update", tool=name, enabled=entry.get("enabled"),
             approval=entry.get("approval"))
    return {"ok": True, "tools": registry.catalog()}


def provider_upsert(body):
    """POST /api/providers — add/update a provider (engine: providers.upsert_provider)."""
    _lazy('providers')
    res = _PROVIDERS.upsert_provider(body or {})
    _publish("providers.update", action="upsert", id=(body or {}).get("id"),
             ok=bool(res.get("ok")))
    return res


def provider_remove(pid):
    """DELETE /api/providers?id= — remove or disable a provider."""
    _lazy('providers')
    res = _PROVIDERS.remove_provider(pid)
    _publish("providers.update", action="remove", id=pid, ok=bool(res.get("ok")))
    return res


def provider_add_model(body):
    """POST /api/providers/models — add a model to a provider."""
    _lazy('providers')
    body = body or {}
    res = _PROVIDERS.add_model(body.get("provider"), body.get("model"),
                               body.get("context_length"))
    _publish("providers.update", action="add_model", id=body.get("provider"),
             model=body.get("model"), ok=bool(res.get("ok")))
    return res


def provider_remove_model(pid, mid):
    """DELETE /api/providers/models?provider=&model= — remove a model."""
    _lazy('providers')
    res = _PROVIDERS.remove_model(pid, mid)
    _publish("providers.update", action="remove_model", id=pid, model=mid,
             ok=bool(res.get("ok")))
    return res


def provider_set_default(body):
    """POST /api/providers/default — set the default model reference."""
    _lazy('providers')
    body = body or {}
    res = _PROVIDERS.set_default(body.get("ref") or body.get("default"))
    _publish("providers.update", action="default", ok=bool(res.get("ok")))
    return res


def provider_reload():
    """POST /api/providers/reload — re-read providers + .env (hot reload)."""
    _lazy('providers')
    _PROVIDERS.reload()
    return {"ok": True}


def install_skill_raw(data, name=None, overwrite=False):
    """POST /api/skills/install — body zip grezzo. Engine: skills.install_zip."""
    import skills as skills_mod
    res = skills_mod.install_zip(data, name=name, overwrite=overwrite)
    _publish("skills.install", name=res.get("name"), ok=bool(res.get("ok")))
    return res
