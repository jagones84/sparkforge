#!/usr/bin/env python3
"""SparkForge — frontier-style agent harness server for the DGX Spark.

Wraps the local llama.cpp router (127.0.0.1:8080) with:
  - streaming chat with Chain-of-Thought timeline
  - model-generated PLAN (strategy steps)
  - TASKS board with remaining bullets
  - a safe agent loop (thought -> action -> observation; no shell)
  - an SSE loopback feed (/api/feed) for WebUI + mobile live views
  - a mobile command API (bind 0.0.0.0 to reach the phone over Tailscale)

Stdlib only. Data lives in ./data (gitignored). Optional bearer token auth.
"""

import argparse
import json
import os
import queue
import re
import sqlite3
import threading
import time
import urllib.request
import uuid
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import api_v02  # v0.2 surface: tool registry, approvals, HITL control, MCP
import approvals
import otel_tracing  # v0.4: OpenTelemetry spans + fallback local spans
import registry
import routing  # v0.3: role-based model selection + fallback chain
import sandbox

REPO = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(REPO, "data")
SESSIONS_DIR = os.path.join(DATA_DIR, "sessions")
WEBUI_DIR = os.path.join(REPO, "webui")

ROUTER_BASE = os.environ.get("SPARKFORGE_ROUTER", "http://127.0.0.1:8080")
MAX_FEED_EVENTS = 800
STORE_LOCK = threading.RLock()

# --------------------------------------------------------------- sqlite ----

DB_PATH = os.environ.get("SPARKFORGE_DB", os.path.join(DATA_DIR, "events.db"))
_db_lock = threading.Lock()
_db = None


def db():
    global _db
    if _db is None:
        os.makedirs(DATA_DIR, exist_ok=True)
        _db = sqlite3.connect(DB_PATH, check_same_thread=False)
        _db.execute("""CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts REAL NOT NULL, kind TEXT NOT NULL, data TEXT NOT NULL)""")
        _db.execute("""CREATE TABLE IF NOT EXISTS runs (
            id TEXT PRIMARY KEY, kind TEXT NOT NULL, goal TEXT,
            model TEXT, ts REAL NOT NULL, tokens_in INTEGER DEFAULT 0,
            tokens_out INTEGER DEFAULT 0, cost_usd REAL DEFAULT 0.0,
            status TEXT DEFAULT 'running', spans TEXT DEFAULT '[]')""")
        _db.commit()
    return _db


# ---------------------------------------------------------------- events ----

_feed_lock = threading.Lock()
_feed = deque(maxlen=MAX_FEED_EVENTS)
_feed_seq = 0
_sse_queues = set()  # each: queue.Queue of str chunks


def publish(kind, **data):
    """Record an event in the SQLite store + memory cache, fan out to SSE.

    Payload keys never override the envelope: the event's own `id`/`ts` are
    the monotonic feed coordinates, so payloads that carry a domain `id`
    (checkpoints, approvals, ...) are stored under `<kind>_id` instead.
    """
    global _feed_seq
    with _feed_lock:
        with _db_lock:
            cur = db().execute("INSERT INTO events(ts, kind, data) VALUES(?,?,?)",
                               (round(time.time(), 3), kind, json.dumps(data, ensure_ascii=False)))
            db().commit()
        _feed_seq = cur.lastrowid
        for k in ("id", "ts"):
            if k in data:
                data[k + "_id"] = data.pop(k)
        event = {"id": _feed_seq, "ts": round(time.time(), 3), "kind": kind, **data}
        _feed.append(event)
        payload = "id: {id}\nevent: {kind}\ndata: {data}\n\n".format(
            id=event["id"], kind=kind, data=json.dumps(event, ensure_ascii=False)
        )
    for q in list(_sse_queues):
        try:
            q.put_nowait(payload)
        except Exception:
            pass
    return event


def events_since(last_id):
    """Replay events after last_id: memory cache first, SQLite as source of truth.
    An empty in-memory buffer must NOT short-circuit replay — the store is durable."""
    with _feed_lock:
        if _feed and _feed[0]["id"] <= last_id + 1:
            return [e for e in _feed if e["id"] > last_id]
    with _db_lock:
        rows = db().execute(
            "SELECT id, ts, kind, data FROM events WHERE id > ? ORDER BY id", (last_id,)
        ).fetchall()
    return [{"id": r[0], "ts": r[1], "kind": r[2], **json.loads(r[3])} for r in rows]


# ---------------------------------------------------------------- stores ----


def _ensure_dirs():
    os.makedirs(SESSIONS_DIR, exist_ok=True)


def _read_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _write_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def _store_path(name):
    return os.path.join(DATA_DIR, name)


def load_plan():
    return _read_json(_store_path("plan.json"), {"goal": "", "steps": [], "updated": None})


def save_plan(plan):
    plan["updated"] = round(time.time(), 3)
    _write_json(_store_path("plan.json"), plan)
    publish("plan.update", goal=plan.get("goal", ""), steps=plan.get("steps", []))


def load_tasks():
    return _read_json(_store_path("tasks.json"), {"tasks": [], "updated": None})


def save_tasks(store):
    store["updated"] = round(time.time(), 3)
    _write_json(_store_path("tasks.json"), store)
    publish("tasks.update", tasks=store.get("tasks", []))


def load_session(sid):
    return _read_json(os.path.join(SESSIONS_DIR, sid + ".json"), None)


def save_session(sess):
    _write_json(os.path.join(SESSIONS_DIR, sess["id"] + ".json"), sess)


def list_sessions():
    out = []
    try:
        for fn in sorted(os.listdir(SESSIONS_DIR)):
            if fn.endswith(".json"):
                s = _read_json(os.path.join(SESSIONS_DIR, fn), None)
                if s:
                    out.append({"id": s["id"], "title": s.get("title", ""),
                                "created": s.get("created"), "messages": len(s.get("messages", []))})
    except FileNotFoundError:
        pass
    return sorted(out, key=lambda s: s.get("created") or 0, reverse=True)


def get_or_create_session(sid, title=None):
    if sid:
        s = load_session(sid)
        if s:
            return s
    sid = sid or uuid.uuid4().hex[:12]
    s = {"id": sid, "title": title or "session " + sid[:6], "created": round(time.time(), 3), "messages": []}
    save_session(s)
    return s


def append_message(sess, role, content, reasoning=None, meta=None):
    msg = {"role": role, "content": content, "ts": round(time.time(), 3)}
    if reasoning:
        msg["reasoning"] = reasoning
    if meta:
        msg.update(meta)
    sess["messages"].append(msg)
    save_session(sess)
    return msg


# ---------------------------------------------------------------- router ----


def router_models():
    """[{alias, status, loaded}] from the llama.cpp router; [] on failure."""
    try:
        with urllib.request.urlopen(ROUTER_BASE + "/v1/models", timeout=6) as r:
            data = json.loads(r.read().decode("utf-8") or "{}")
        out = []
        for m in data.get("data", []):
            st = (m.get("status") or {}).get("value", "unknown")
            out.append({"alias": m.get("id"), "status": st, "loaded": st == "loaded"})
        return out
    except Exception:
        return []


def default_model():
    models = router_models()
    for m in models:
        if m["loaded"]:
            return m["alias"]
    return models[0]["alias"] if models else None


def strip_think(text):
    """Split optional <think>...</think> out of content."""
    m = re.search(r"<think>(.*?)</think>", text, re.S)
    if m:
        return text[: m.start()] + text[m.end():], m.group(1)
    return text, None


def _router_stream(messages, model, on_delta, timeout=300):
    """POST /v1/chat/completions with stream=true; feed deltas to on_delta.

    on_delta(channel, text) with channel in {think, answer}. Returns the
    full (answer, think) pair. Falls back to a non-streaming call.
    """
    body = json.dumps({
        "model": model or "default",
        "messages": messages,
        "stream": True,
        "temperature": 0.7,
    }).encode("utf-8")
    req = urllib.request.Request(
        ROUTER_BASE + "/v1/chat/completions", data=body,
        headers={"Content-Type": "application/json"},
    )
    answer, think = [], []
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            for raw in resp:
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if payload == "[DONE]":
                    break
                try:
                    chunk = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                delta = ((chunk.get("choices") or [{}])[0].get("delta")) or {}
                rc = delta.get("reasoning_content")
                c = delta.get("content")
                if rc:
                    think.append(rc)
                    on_delta("think", rc)
                if c:
                    txt = c
                    clean, embedded = strip_think(txt)
                    if embedded:
                        think.append(embedded)
                        on_delta("think", embedded)
                    if clean:
                        answer.append(clean)
                        on_delta("answer", clean)
    except Exception:
        if answer or think:
            return "".join(answer), "".join(think)
        # non-streaming fallback
        body = json.dumps({"model": model or "default", "messages": messages,
                           "temperature": 0.7}).encode("utf-8")
        req = urllib.request.Request(
            ROUTER_BASE + "/v1/chat/completions", data=body,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8") or "{}")
        msg = (data.get("choices") or [{}])[0].get("message") or {}
        rc = msg.get("reasoning_content") or ""
        c = msg.get("content") or ""
        if rc:
            on_delta("think", rc)
        clean, embedded = strip_think(c)
        if embedded:
            think.append(embedded)
            on_delta("think", embedded)
        if clean:
            answer.append(clean)
            on_delta("answer", clean)
    return "".join(answer), "".join(think)


# ----------------------------------------------------- tracing / cost ----


def stream_with_fallback(messages, model, role, on_delta, timeout=300):
    """v0.3 multi-model routing with fallback.

    Tries `model` (or the role-selected one) first; on a router failure walks
    the role's fallback chain (which always terminates on the DeepSeek alias
    when it exists in the roster) before giving up. Returns (answer, think,
    model_used).
    """
    primary = model or routing.pick(role)
    if not primary:
        primary = default_model()
    chain = [primary] + [a for a in routing.fallback_chain(role) if a != primary]
    last_err = None
    for i, alias in enumerate(chain):
        try:
            answer, think = _router_stream(messages, alias, on_delta, timeout)
            if i > 0:
                publish("model.fallback", role=role, from_model=chain[0],
                        to_model=alias)
            return answer, think, alias
        except Exception as e:  # noqa: BLE001
            last_err = e
            publish("model.failover", role=role, failed=alias,
                    next_model=chain[i + 1] if i + 1 < len(chain) else None)
    raise last_err if last_err else RuntimeError("no router model available")


# Token pricing per 1M tokens (input, output) for known local model families.
# Local models are free in $, but we still account tokens; cost is 0 unless a
# price is configured via SPARKFORGE_PRICES (json: {"alias": [in, out]}).
try:
    MODEL_PRICES = json.loads(os.environ.get("SPARKFORGE_PRICES", "{}"))
except Exception:
    MODEL_PRICES = {}


def count_tokens(text):
    """Cheap proxy: ~4 chars/token (good enough for local accounting)."""
    return max(1, len(text) // 4) if text else 0


class RunTrace:
    """Records spans + token/cost accounting for one run (chat, plan, agent).

    Spans go through OpenTelemetry when the SDK is installed (see
    otel_tracing.py); otherwise a lightweight local span list is kept.
    """

    def __init__(self, kind, goal=None, model=None):
        self.id = uuid.uuid4().hex[:12]
        self.kind = kind
        self.goal = (goal or "")[:300]
        self.model = model
        self.ts = round(time.time(), 3)
        self.tokens_in = 0
        self.tokens_out = 0
        self.spans = []
        self.status = "running"
        with _db_lock:
            db().execute(
                "INSERT INTO runs(id, kind, goal, model, ts) VALUES(?,?,?,?,?)",
                (self.id, kind, self.goal, model, self.ts))
            db().commit()
        self.otel = otel_tracing.init_provider()
        self._otel_root = None
        self._otel_ctx = None
        if self.otel:
            from opentelemetry.trace import set_span_in_context
            attrs = {"sparkforge.run_id": self.id, "sparkforge.kind": kind}
            if self.goal:
                attrs["sparkforge.goal"] = self.goal
            if self.model:
                attrs["sparkforge.model"] = self.model
            self._otel_root = otel_tracing.get_tracer().start_span("sparkforge.run", attributes=attrs)
            self._otel_ctx = set_span_in_context(self._otel_root)

    def span(self, name, **attrs):
        s = {"name": name, "ts": round(time.time(), 3), **attrs}
        self.spans.append(s)
        if self.otel and self._otel_root is not None:
            otel_attrs = {"sparkforge.run_id": self.id}
            otel_attrs.update({k: v for k, v in attrs.items() if v is not None})
            try:
                child = otel_tracing.get_tracer().start_span(
                    name, context=self._otel_ctx, attributes=otel_attrs)
                child.end()
            except Exception:
                pass
        return s

    def llm_call(self, messages, answer):
        tin = sum(count_tokens(m.get("content", "")) for m in messages)
        tout = count_tokens(answer)
        self.tokens_in += tin
        self.tokens_out += tout
        return tin, tout

    def finish(self, status="done"):
        self.status = status
        price = MODEL_PRICES.get(self.model or "", [0.0, 0.0])
        cost = (self.tokens_in / 1e6) * price[0] + (self.tokens_out / 1e6) * price[1]
        spans = self.spans
        if self.otel and self._otel_root is not None:
            try:
                self._otel_root.set_attribute("sparkforge.status", status)
                self._otel_root.end()
            except Exception:
                pass
            otel_spans = otel_tracing.take_spans(self.id)
            if otel_spans:
                spans = otel_spans
        with _db_lock:
            db().execute(
                "UPDATE runs SET tokens_in=?, tokens_out=?, cost_usd=?, status=?, model=?, spans=? WHERE id=?",
                (self.tokens_in, self.tokens_out, round(cost, 6), status,
                 self.model, json.dumps(spans, ensure_ascii=False), self.id))
            db().commit()

    def summary(self):
        return {"run_id": self.id, "kind": self.kind, "goal": self.goal,
                "model": self.model, "ts": self.ts, "status": self.status,
                "tokens_in": self.tokens_in, "tokens_out": self.tokens_out,
                "spans": self.spans}


def get_run_trace(run_id):
    with _db_lock:
        row = db().execute(
            "SELECT id, kind, goal, model, ts, tokens_in, tokens_out, cost_usd, status, spans"
            " FROM runs WHERE id=?", (run_id,)).fetchone()
    if not row:
        return None
    spans = json.loads(row[9])
    trace_id = next((s.get("trace_id") for s in spans if s.get("trace_id")), None)
    return {"run_id": row[0], "kind": row[1], "goal": row[2], "model": row[3],
            "ts": row[4], "tokens_in": row[5], "tokens_out": row[6],
            "cost_usd": row[7], "status": row[8], "spans": spans,
            "otel": bool(trace_id), "trace_id": trace_id}


def runs_summary(limit=50):
    with _db_lock:
        rows = db().execute(
            "SELECT id, kind, goal, model, ts, tokens_in, tokens_out, cost_usd, status"
            " FROM runs ORDER BY ts DESC LIMIT ?", (limit,)).fetchall()
    return [{"run_id": r[0], "kind": r[1], "goal": r[2], "model": r[3], "ts": r[4],
             "tokens_in": r[5], "tokens_out": r[6], "cost_usd": r[7], "status": r[8]}
            for r in rows]


# ------------------------------------------------------------- agent core ----

SYSTEM_PROMPT = (
    "You are SparkForge, the reasoning core of a frontier-style agent harness "
    "running locally on a DGX Spark (GB10, ARM64, unified memory) behind a "
    "llama.cpp router. Be direct, concrete and useful. When asked to plan or "
    "act, produce compact, actionable output."
)

PLANNER_PROMPT = (
    "You are the planner module of the SparkForge harness. Break the goal into "
    "3-7 concrete strategy steps. Respond with ONLY a JSON array, each item "
    '{"title": "<short step>", "detail": "<one sentence>"}'
)


def context_summary():
    plan, tasks = load_plan(), load_tasks()
    lines = []
    if plan.get("goal"):
        lines.append("PLAN goal: " + plan["goal"])
        for s in plan.get("steps", []):
            lines.append(" - [%s] %s" % ("x" if s.get("done") else " ", s.get("title", "")))
    todo = [t for t in tasks.get("tasks", []) if t.get("status") != "done"]
    if tasks.get("tasks"):
        lines.append("TASKS: %d open / %d total" % (len(todo), len(tasks["tasks"])))
        for t in todo[:8]:
            lines.append(" * (%s) %s" % (t.get("status", "todo"), t.get("title", "")))
    return "\n".join(lines) if lines else "(no plan or tasks yet)"


def extract_json(text):
    text = text.strip()
    try:
        return json.loads(text)
    except Exception:
        pass
    for opener, closer in (("{", "}"), ("[", "]")):
        i, j = text.find(opener), text.rfind(closer)
        if 0 <= i < j:
            try:
                return json.loads(text[i:j + 1])
            except Exception:
                continue
    return None


def chat_once(sess, message, model=None, on_delta=None, trace=None):
    """Append the user message, run one streamed router call, store the reply."""
    if on_delta is None:
        on_delta = lambda channel, text: publish(
            "chat.delta", session=sess["id"], channel=channel, text=text)
    sys = SYSTEM_PROMPT + "\n\nCurrent harness state:\n" + context_summary()
    # v0.3 context engineering: compaction + token budget + memory retrieval
    try:
        import context_engine
        msgs, ctx_stats = context_engine.build(
            sys, sess["messages"], message,
            budget_tokens=int(os.environ.get("SPARKFORGE_CONTEXT_BUDGET",
                                             context_engine.DEFAULT_BUDGET)))
        publish("context.built", session=sess["id"], **{
            k: v for k, v in ctx_stats.items() if k in (
                "budget_tokens", "retrieved_memories", "final_messages",
                "final_tokens")})
    except Exception:
        msgs = [{"role": "system", "content": sys}]
        msgs += [{"role": m["role"], "content": m["content"]} for m in sess["messages"][-20:]]
        msgs.append({"role": "user", "content": message})
        ctx_stats = None
    model = model or default_model()
    answer, think, model = stream_with_fallback(msgs, model, "chat", on_delta)
    if trace:
        trace.span("llm.chat", model=model, context=ctx_stats)
        trace.llm_call(msgs, answer + think)
    reply = append_message(sess, "assistant", answer.strip(), reasoning=think.strip() or None,
                           meta={"model": model})
    publish("chat.done", session=sess["id"], message_id=len(sess["messages"]),
            model=model, think_chars=len(think))
    return reply, model


def generate_plan(goal, model=None):
    sess = {"id": "planner", "title": "planner", "created": time.time(), "messages": []}  # ephemeral
    sys = SYSTEM_PROMPT + "\n\n" + PLANNER_PROMPT
    msgs = [{"role": "system", "content": sys}, {"role": "user", "content": goal}]
    model = model or routing.pick("planner") or default_model()
    trace = RunTrace("plan", goal=goal, model=model)
    answer, think = _router_stream(msgs, model, lambda ch, t: publish(
        "plan.think", channel=ch, text=t))
    trace.span("llm.plan", model=model)
    trace.llm_call(msgs, answer + think)
    data = extract_json(answer)
    steps = []
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict) and item.get("title"):
                steps.append({"id": uuid.uuid4().hex[:6], "title": str(item["title"])[:120],
                              "detail": str(item.get("detail", ""))[:300], "done": False})
    elif isinstance(data, dict) and data.get("title"):
        steps = [{"id": uuid.uuid4().hex[:6], "title": str(data["title"])[:120],
                  "detail": str(data.get("detail", ""))[:300], "done": False}]
    plan = {"goal": goal, "steps": steps, "updated": round(time.time(), 3)}
    _write_json(_store_path("plan.json"), plan)
    publish("plan.update", goal=goal, steps=steps, generated=True)
    trace.finish("done")
    return plan, answer, think, trace.id


AGENT_ACTIONS = ("plan_step", "complete_plan_step", "add_task", "complete_task", "note", "finish")

AGENT_PROMPT = (
    "You are the agent loop of the SparkForge harness. Given the goal and the "
    "current harness state, decide ONE next action. Respond with ONLY a JSON "
    'object: {"thought": "<brief reasoning>", "action": "plan_step|'
    'complete_plan_step|add_task|complete_task|note|finish", "title": "<for '
    'plan_step/add_task>", "id": "<for complete_plan_step/complete_task>", '
    '"detail": "<optional>", "summary": "<required for finish>"}.'
)


def apply_agent_action(act):
    """Apply a parsed agent action; returns observation text."""
    action = act.get("action")
    plan, tasks = load_plan(), load_tasks()
    if action == "plan_step":
        if not plan.get("goal"):
            plan["goal"] = act.get("detail") or act.get("title") or "goal"
        step = {"id": uuid.uuid4().hex[:6], "title": str(act.get("title", "step"))[:120],
                "detail": str(act.get("detail", ""))[:300], "done": False}
        plan.setdefault("steps", []).append(step)
        save_plan(plan)
        return "plan step added: %s (%s)" % (step["title"], step["id"])
    if action == "complete_plan_step":
        for s in plan.get("steps", []):
            if s.get("id") == act.get("id") or s.get("title") == act.get("title"):
                s["done"] = True
                save_plan(plan)
                return "plan step completed: %s" % s["title"]
        return "plan step not found"
    if action == "add_task":
        t = {"id": uuid.uuid4().hex[:6], "title": str(act.get("title", "task"))[:120],
             "status": "todo", "created": round(time.time(), 3)}
        tasks.setdefault("tasks", []).append(t)
        save_tasks(tasks)
        return "task added: %s (%s)" % (t["title"], t["id"])
    if action == "complete_task":
        for t in tasks.get("tasks", []):
            if t.get("id") == act.get("id") or t.get("title") == act.get("title"):
                t["status"] = "done"
                t["done_ts"] = round(time.time(), 3)
                save_tasks(tasks)
                return "task completed: %s" % t["title"]
        return "task not found"
    if action == "note":
        publish("agent.note", text=str(act.get("detail") or act.get("title") or "")[:400])
        return "noted"
    return "unknown action"


def agent_run(goal, max_steps=6, model=None, on_event=None, trace=None):
    """Sense-think-act loop. No shell, no filesystem writes except harness stores."""
    if on_event is None:
        on_event = lambda kind, **d: publish(kind, **d)
    on_event("agent.start", goal=goal, max_steps=max_steps)
    model = model or default_model()
    if trace is None:
        trace = RunTrace("agent", goal=goal, model=model)
        trace.span("agent.start", goal=goal, max_steps=max_steps)
    trace_model = model
    llm_log = []

    def _llm(msgs, answer):
        trace.span("llm.step", model=trace_model)
        tin, tout = trace.llm_call(msgs, answer)
        llm_log.append((tin, tout))

    actions = []
    for i in range(max_steps):
        sys = SYSTEM_PROMPT + "\n\n" + AGENT_PROMPT + "\n\nHarness state:\n" + context_summary()
        msgs = [{"role": "system", "content": sys},
                {"role": "user", "content": "Goal: %s (iteration %d/%d)" % (goal, i + 1, max_steps)}]
        on_event("agent.iteration", i=i + 1, of=max_steps)
        answer, think = _router_stream(msgs, model, lambda ch, t: on_event("agent.think", channel=ch, text=t))
        _llm(msgs, answer + think)
        act = extract_json(answer) or {}
        if not isinstance(act, dict) or not act.get("action"):
            act = {"thought": answer[:200], "action": "note", "detail": answer[:400]}
        thought = str(act.get("thought", ""))[:400]
        action = act.get("action")
        on_event("agent.thought", i=i + 1, thought=thought, action=action)
        if action == "finish":
            summary = str(act.get("summary", ""))[:600]
            on_event("agent.finish", summary=summary)
            actions.append({"i": i + 1, "thought": thought, "action": "finish", "summary": summary})
            break
        obs = apply_agent_action(act)
        trace.span("agent.action", i=i + 1, action=action, observation=obs)
        on_event("agent.observation", i=i + 1, observation=obs)
        actions.append({"i": i + 1, "thought": thought, "action": action, "observation": obs})
    else:
        summary = "stopped at max_steps=%d; see trace" % max_steps
        on_event("agent.finish", summary=summary)
        actions.append({"action": "finish", "summary": summary})
    trace.finish("done")
    return {"goal": goal, "model": model, "trace": actions, "run_id": trace.id}


# ---------------------------------------------------------- eval harness ----

EVAL_DIR = os.path.join(REPO, "eval")
GOLD_PATH = os.path.join(EVAL_DIR, "gold_tasks.json")
EVAL_RESULTS_DIR = os.path.join(EVAL_DIR, "results")


def eval_list_tasks():
    try:
        with open(GOLD_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data["tasks"] if isinstance(data, dict) else data
    except FileNotFoundError:
        return []


def _is_subsequence(needle, haystack):
    it = iter(haystack)
    return all(any(x == n for x in it) for n in needle)


def eval_score(result, task):
    """Score one agent run against the gold task.

    Returns dict with per-criterion pass/bool and total score in [0,1].
    Criteria (pattern Winder.AI): every expected action appears, the expected
    ones appear in order (as a subsequence — extra legitimate actions don't
    penalize), finish summary is non-empty, loop did not stall.
    """
    trace = result.get("trace") or []
    # finish is a real action and gold sets list it in expected_actions
    got_actions = [t.get("action") for t in trace if t.get("action")]
    expected = task.get("expected_actions", [])
    checks = {
        "actions_present": all(a in got_actions for a in expected),
        "actions_in_order": _is_subsequence(expected, got_actions),
        "finished": any(t.get("action") == "finish" for t in trace),
        "summary_nonempty": bool((trace[-1].get("summary", "") if trace else "").strip()),
        "no_stall": all((t.get("observation") or t.get("summary") or "")
                        != "unknown action" for t in trace),
    }
    score = sum(1 for v in checks.values() if v) / len(checks)
    return {"score": round(score, 3), "checks": checks,
            "actions_seen": got_actions}


def eval_run(model=None, max_steps=6, task_id=None, save=True):
    """Run every gold task (or one) through the agent loop and score it."""
    tasks = eval_list_tasks()
    if task_id:
        tasks = [t for t in tasks if t.get("id") == task_id]
    if not tasks:
        return {"error": "no eval tasks (missing %s)" % GOLD_PATH}
    results = []
    for t in tasks:
        result = agent_run(t["goal"], max_steps, model)
        sc = eval_score(result, t)
        results.append({"task": t["id"], "goal": t["goal"], "run_id": result.get("run_id"),
                        "score": sc["score"], "checks": sc["checks"],
                        "actions_seen": sc["actions_seen"]})
    summary = {"ts": round(time.time(), 3), "model": model or "default",
               "mean_score": round(sum(r["score"] for r in results) / len(results), 3),
               "per_task": results}
    if save:
        os.makedirs(EVAL_RESULTS_DIR, exist_ok=True)
        path = os.path.join(EVAL_RESULTS_DIR, "eval-%d.json" % int(time.time()))
        with open(path, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)
        summary["saved_to"] = path
    publish("eval.done", mean_score=summary["mean_score"], n=len(results))
    return summary


# ------------------------------------------------------------------ voice ----

WHISPER_BIN = os.environ.get("SPARKFORGE_WHISPER_BIN", "whisper-cli")
WHISPER_MODEL = os.environ.get("SPARKFORGE_WHISPER_MODEL", "")
SHERPA_TTS_MODEL = os.environ.get("SPARKFORGE_SHERPA_TTS_MODEL", "")


def _whisper_model_arg():
    """Model argument for the STT CLI: a real file path when configured as one,
    otherwise the bare name (openai-whisper resolves names from its cache)."""
    if WHISPER_MODEL and os.path.isfile(WHISPER_MODEL):
        return WHISPER_MODEL
    return WHISPER_MODEL


_whisper_style_cache = {}


def _whisper_style(bin_path):
    """'openai' if the CLI speaks openai-whisper flags (--output_format), else
    'cpp' for whisper.cpp-style CLIs (-m/-nt/-f). Detected once per process."""
    if bin_path in _whisper_style_cache:
        return _whisper_style_cache[bin_path]
    style = "cpp"
    import subprocess as sp
    try:
        out = sp.run([bin_path, "--help"], capture_output=True, text=True, timeout=15)
        blob = (out.stdout or "") + (out.stderr or "")
        style = "openai" if "output_format" in blob else "cpp"
    except Exception:
        pass
    _whisper_style_cache[bin_path] = style
    return style


def voice_status():
    """Detect whisper.cpp / openai-whisper and sherpa-onnx availability (evidence-based)."""
    import shutil
    bin_found = bool(shutil.which(WHISPER_BIN) or os.path.isfile(WHISPER_BIN))
    stt = {"backend": "whisper", "bin": WHISPER_BIN,
           "style": _whisper_style(WHISPER_BIN) if bin_found else None,
           "model": WHISPER_MODEL,
           "available": bin_found and bool(WHISPER_MODEL)}
    tts = {"backend": "sherpa-onnx", "model": SHERPA_TTS_MODEL, "available": False}
    if SHERPA_TTS_MODEL:
        try:
            import sherpa_onnx  # noqa: F401
            tts["available"] = True
        except ImportError:
            pass
    return {"stt": stt, "tts": tts}


def voice_stt(wav_path):
    """Transcribe a wav with the configured whisper CLI (openai-whisper or
    whisper.cpp style, auto-detected). Returns {text} or {error}."""
    if not wav_path or not os.path.isfile(wav_path):
        return {"error": "wav path required"}
    if not WHISPER_MODEL:
        return {"error": "whisper model not configured (SPARKFORGE_WHISPER_MODEL)"}
    import subprocess as sp
    import tempfile
    try:
        if _whisper_style(WHISPER_BIN) == "openai":
            with tempfile.TemporaryDirectory() as outdir:
                out = sp.run([WHISPER_BIN, "--model", _whisper_model_arg(),
                              "--output_format", "txt", "--output_dir", outdir,
                              wav_path],
                             capture_output=True, text=True, timeout=300)
                stem = os.path.splitext(os.path.basename(wav_path))[0] + ".txt"
                txt = os.path.join(outdir, stem)
                text = open(txt, encoding="utf-8").read().strip() \
                    if os.path.isfile(txt) else (out.stdout or "").strip()
        else:
            out = sp.run([WHISPER_BIN, "-m", WHISPER_MODEL, "-nt", "-f", wav_path],
                         capture_output=True, text=True, timeout=120)
            text = out.stdout.strip()
        publish("voice.stt", chars=len(text))
        return {"text": text}
    except Exception as e:
        return {"error": str(e)}


def voice_tts(text):
    """Synthesize speech with sherpa-onnx (VITS/piper) to a wav in data/.
    Returns {path, file, seconds} or {error}."""
    if not text.strip():
        return {"error": "text required"}
    if not SHERPA_TTS_MODEL or not os.path.isfile(SHERPA_TTS_MODEL):
        return {"error": "TTS model not configured (SPARKFORGE_SHERPA_TTS_MODEL)"}
    try:
        import sherpa_onnx
        import soundfile as sf
        mdir = os.path.dirname(SHERPA_TTS_MODEL)
        tokens = os.path.join(mdir, "tokens.txt")
        espeak = os.path.join(mdir, "espeak-ng-data")
        vits = sherpa_onnx.OfflineTtsVitsModelConfig(
            model=SHERPA_TTS_MODEL, tokens=tokens,
            data_dir=espeak if os.path.isdir(espeak) else "")
        cfg = sherpa_onnx.OfflineTtsConfig(
            model=sherpa_onnx.OfflineTtsModelConfig(vits=vits, num_threads=2),
            rule_fsts="", max_num_sentences=0)
        tts = sherpa_onnx.OfflineTts(cfg)
        audio = tts.generate(text)
        os.makedirs(DATA_DIR, exist_ok=True)
        fname = "tts-%s.wav" % uuid.uuid4().hex[:8]
        path = os.path.join(DATA_DIR, fname)
        sf.write(path, audio.samples, audio.sample_rate)
        publish("voice.tts", chars=len(text), path=fname)
        return {"path": path, "file": fname,
                "seconds": round(len(audio.samples) / max(audio.sample_rate, 1), 2)}
    except Exception as e:
        return {"error": str(e)}


# ------------------------------------------------------------------ HTTP ----

AUTH_TOKEN = None


def check_auth(headers, qs=None):
    if not AUTH_TOKEN:
        return True
    h = headers.get("Authorization") or ""
    if h == "Bearer " + AUTH_TOKEN:
        return True
    # EventSource cannot set headers: allow ?token= as fallback
    return bool(qs) and qs.get("token") == AUTH_TOKEN


def sse_response(handler, gen):
    handler.send_response(200)
    handler.send_header("Content-Type", "text/event-stream")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Connection", "close")
    handler.end_headers()
    try:
        for chunk in gen:
            handler.wfile.write(chunk.encode("utf-8"))
            handler.wfile.flush()
    except (BrokenPipeError, ConnectionResetError):
        pass


def chat_stream_gen(sess, message, model):
    q = queue.Queue()
    done = {"flag": False}

    def on_delta(channel, text):
        q.put("event: chat.delta\ndata: %s\n\n" % json.dumps(
            {"session": sess["id"], "channel": channel, "text": text}, ensure_ascii=False))
        publish("chat.delta", session=sess["id"], channel=channel, text=text)

    def worker():
        try:
            trace = RunTrace("chat", goal=message[:120], model=model)
            trace.span("chat.stream", session=sess["id"])
            q.put("event: chat.run\ndata: %s\n\n" % json.dumps({"run_id": trace.id}))
            try:
                chat_once(sess, message, model, on_delta, trace=trace)
                trace.finish("done")
            except Exception as e:
                trace.finish("error")
                raise
        except Exception as e:
            q.put("event: error\ndata: %s\n\n" % json.dumps({"error": str(e)}))
        finally:
            done["flag"] = True
            q.put(None)

    threading.Thread(target=worker, daemon=True).start()
    yield ": stream open\n\n"
    while True:
        item = q.get()
        if item is None:
            break
        yield item
    yield "event: done\ndata: {}\n\n"


def agent_stream_gen(goal, max_steps, model):
    q = queue.Queue()

    def on_event(kind, **d):
        q.put("event: %s\ndata: %s\n\n" % (kind, json.dumps(d, ensure_ascii=False)))
        if not kind.startswith("agent.think"):
            publish(kind, **d)

    def worker():
        try:
            agent_run(goal, max_steps, model, on_event)
        except Exception as e:
            q.put("event: error\ndata: %s\n\n" % json.dumps({"error": str(e)}))
        finally:
            q.put(None)

    threading.Thread(target=worker, daemon=True).start()
    yield ": agent stream open\n\n"
    while True:
        item = q.get()
        if item is None:
            break
        yield item
    yield "event: done\ndata: {}\n\n"


def feed_gen(since=0):
    q = queue.Queue()
    _sse_queues.add(q)
    try:
        backlog = events_since(since)
        if backlog:
            yield "event: backlog\ndata: %s\n\n" % json.dumps(backlog, ensure_ascii=False)
        yield ": feed open\n\n"
        idle = 0
        while idle < 600:  # ~10 min max per connection
            try:
                yield q.get(timeout=1)
                idle = 0
            except queue.Empty:
                idle += 1
                yield ": ping\n\n"
    finally:
        _sse_queues.discard(q)


def telemetry_summary():
    out = {"gpu": None, "memory": None}
    try:
        import psutil  # optional
        vm = psutil.virtual_memory()
        out["memory"] = {"used_gb": round(vm.used / 1024**3, 1),
                         "total_gb": round(vm.total / 1024**3, 1)}
        try:
            csv = subprocess.check_output(
                ["nvidia-smi", "--query-gpu=utilization.gpu,temperature.gpu,power.draw",
                 "--format=csv,noheader,nounits"], text=True, timeout=4).strip()
            util, temp, power = [p.strip() for p in csv.split(",")]
            out["gpu"] = {"util": util, "temp": temp, "power_w": power}
        except Exception:
            pass
    except ImportError:
        pass
    return out


def status_payload():
    plan, tasks = load_plan(), load_tasks()
    probe = sandbox.probe()
    return {
        "service": "sparkforge", "version": "0.4.0", "ts": round(time.time()),
        "router": ROUTER_BASE, "models": router_models(),
        "default_model": default_model(),
        "telemetry": telemetry_summary(),
        "plan": {"goal": plan.get("goal", ""), "steps": len(plan.get("steps", []))},
        "tasks": {"total": len(tasks.get("tasks", [])),
                  "open": len([t for t in tasks.get("tasks", []) if t["status"] != "done"])},
        "sandbox": {"backend": probe["backend"], "isolated": probe["isolated"],
                    "requested": probe["requested"]},
        "tools": {"registered": len(registry.catalog()),
                  "enabled": len([t for t in registry.catalog() if t["enabled"]])},
        "approvals": approvals.stats(),
        "runs": {"active": len([r for r in api_v02.RUNS.values()
                                if r.status in ("running", "paused", "aborting")]),
                 "total": len(api_v02.RUNS)},
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "SparkForge/0.1"

    def _send(self, code, obj, ctype="application/json"):
        if isinstance(obj, (dict, list)):
            body = json.dumps(obj, indent=2, ensure_ascii=False).encode("utf-8")
        elif isinstance(obj, bytes):
            body = obj
        else:
            body = obj.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n).decode("utf-8"))
        except json.JSONDecodeError:
            return {}

    def _query(self):
        from urllib.parse import parse_qs, urlparse
        q = urlparse(self.path)
        return q.path, {k: v[0] for k, v in parse_qs(q.query).items()}

    # ---- GET ----
    def do_GET(self):
        path, qs = self._query()
        if not check_auth(self.headers, qs):
            return self._send(401, {"error": "unauthorized"})
        if api_v02.handle(self, "GET", path, qs, None):
            return

        if path in ("/", "/index.html"):
            try:
                with open(os.path.join(WEBUI_DIR, "index.html"), "r", encoding="utf-8") as f:
                    return self._send(200, f.read(), ctype="text/html; charset=utf-8")
            except FileNotFoundError:
                return self._send(404, {"error": "webui missing"})
        if path == "/api/status":
            return self._send(200, status_payload())
        if path == "/api/models":
            return self._send(200, {"models": router_models()})
        if path == "/api/feed":
            since = int(qs.get("since", 0))
            return sse_response(self, feed_gen(since))
        if path == "/api/plan":
            return self._send(200, load_plan())
        if path == "/api/tasks":
            tasks = load_tasks()
            remaining = ["%s: %s" % (t["status"], t["title"]) for t in tasks.get("tasks", [])
                         if t.get("status") != "done"]
            return self._send(200, {**tasks, "remaining": remaining})
        if path == "/api/sessions":
            return self._send(200, {"sessions": list_sessions()})
        if path == "/api/history":
            sid = qs.get("session")
            sess = load_session(sid) if sid else None
            if not sess:
                return self._send(404, {"error": "session not found"})
            return self._send(200, sess)
        if path == "/api/chat/stream":
            sid = qs.get("session")
            message = qs.get("message", "")
            if not message:
                return self._send(400, {"error": "message required"})
            sess = get_or_create_session(sid)
            append_message(sess, "user", message)
            publish("chat.user", session=sess["id"], text=message)
            return sse_response(self, chat_stream_gen(sess, message, qs.get("model")))
        if path == "/api/agent/run":
            goal = qs.get("goal", "")
            if not goal:
                return self._send(400, {"error": "goal required"})
            return sse_response(self, agent_stream_gen(goal, int(qs.get("max_steps", 6)), qs.get("model")))
        if path.startswith("/api/runs/"):
            parts = path.strip("/").split("/")
            if len(parts) == 4 and parts[3] == "trace":
                t = get_run_trace(parts[2])
                return self._send(200, t) if t else self._send(404, {"error": "run not found"})
            return self._send(404, {"error": "not found"})
        if path == "/api/runs":
            return self._send(200, {"runs": runs_summary(int(qs.get("limit", 50)))})
        if path == "/api/eval/tasks":
            return self._send(200, eval_list_tasks())
        if path == "/api/voice/status":
            return self._send(200, voice_status())
        if path.startswith("/api/voice/audio/"):
            fname = path.split("/")[-1]
            if not fname.startswith("tts-") or not fname.endswith(".wav") \
                    or "/" in fname or ".." in fname:
                return self._send(404, {"error": "not found"})
            fpath = os.path.join(DATA_DIR, fname)
            if not os.path.isfile(fpath):
                return self._send(404, {"error": "not found"})
            with open(fpath, "rb") as f:
                return self._send(200, f.read(), ctype="audio/wav")
        return self._send(404, {"error": "not found"})

    # ---- POST ----
    def do_POST(self):
        path, qs = self._query()
        if not check_auth(self.headers, qs):
            return self._send(401, {"error": "unauthorized"})
        path = path
        # Raw audio upload (phone records a wav and POSTs it directly)
        ctype = (self.headers.get("Content-Type") or "")
        if path == "/api/voice/stt" and ctype.startswith("audio/"):
            n = int(self.headers.get("Content-Length") or 0)
            if not n:
                return self._send(400, {"error": "audio body required"})
            import tempfile
            ext = ".wav"
            with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as f:
                f.write(self.rfile.read(n))
                tmp = f.name
            try:
                return self._send(200, voice_stt(tmp))
            finally:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
        body = self._body()
        if api_v02.handle(self, "POST", path, qs, body):
            return

        if path == "/api/chat":
            message = body.get("message", "")
            if not message:
                return self._send(400, {"error": "message required"})
            sess = get_or_create_session(body.get("session"))
            append_message(sess, "user", message)
            publish("chat.user", session=sess["id"], text=message)
            trace = RunTrace("chat", goal=message[:120], model=body.get("model"))
            trace.span("chat.once", session=sess["id"])
            try:
                reply, model = chat_once(sess, message, body.get("model"), trace=trace)
            except Exception as e:
                trace.finish("error")
                return self._send(502, {"error": "router call failed: %s" % e})
            trace.model = model
            trace.finish("done")
            return self._send(200, {"session": sess["id"], "model": model, "run_id": trace.id,
                                    "reply": reply["content"], "reasoning": reply.get("reasoning")})
        if path == "/api/plan":
            goal = body.get("goal", "")
            plan = {"goal": goal, "steps": body.get("steps", load_plan().get("steps", []))}
            save_plan(plan)
            return self._send(200, plan)
        if path == "/api/plan/generate":
            goal = body.get("goal", "")
            if not goal:
                return self._send(400, {"error": "goal required"})
            try:
                plan, answer, think, run_id = generate_plan(goal, body.get("model"))
            except Exception as e:
                return self._send(502, {"error": "planner failed: %s" % e})
            return self._send(200, {"plan": plan, "raw": answer[:800], "run_id": run_id})
        if path == "/api/plan/toggle":
            sid = body.get("id")
            plan = load_plan()
            for s in plan.get("steps", []):
                if s["id"] == sid:
                    s["done"] = not s.get("done")
                    save_plan(plan)
                    return self._send(200, plan)
            return self._send(404, {"error": "step not found"})
        if path == "/api/tasks":
            title = body.get("title", "")
            if not title:
                return self._send(400, {"error": "title required"})
            tasks = load_tasks()
            t = {"id": uuid.uuid4().hex[:6], "title": str(title)[:140],
                 "status": body.get("status", "todo"), "created": round(time.time(), 3)}
            tasks.setdefault("tasks", []).append(t)
            save_tasks(tasks)
            return self._send(200, t)
        if path == "/api/agent/run":
            goal = body.get("goal", "")
            if not goal:
                return self._send(400, {"error": "goal required"})
            result = agent_run(goal, int(body.get("max_steps", 6)), body.get("model"))
            return self._send(200, result)
        if path == "/api/eval/run":
            return self._send(200, eval_run(body.get("model"), int(body.get("max_steps", 6)),
                                            body.get("task_id"), body.get("save", True)))
        if path == "/api/voice/stt":
            return self._send(200, voice_stt(body.get("text") or body.get("path")))
        if path == "/api/voice/tts":
            return self._send(200, voice_tts(body.get("text", "")))
        return self._send(404, {"error": "not found"})

    # ---- PATCH ----
    def do_PATCH(self):
        path, qs = self._query()
        if not check_auth(self.headers, qs):
            return self._send(401, {"error": "unauthorized"})
        body = self._body()
        if api_v02.handle(self, "PATCH", path, qs, body):
            return
        if path == "/api/tasks":
            tid, status = body.get("id"), body.get("status")
            tasks = load_tasks()
            for t in tasks.get("tasks", []):
                if t["id"] == tid:
                    if status in ("todo", "doing", "done"):
                        t["status"] = status
                        if status == "done":
                            t["done_ts"] = round(time.time(), 3)
                    if "title" in body:
                        t["title"] = str(body["title"])[:140]
                    save_tasks(tasks)
                    return self._send(200, t)
            return self._send(404, {"error": "task not found"})
        return self._send(404, {"error": "not found"})

    def log_message(self, fmt, *args):
        pass


def main():
    global AUTH_TOKEN
    ap = argparse.ArgumentParser(description="SparkForge harness server")
    ap.add_argument("--host", default="127.0.0.1",
                    help="bind host (0.0.0.0 to expose to Tailscale/mobile)")
    ap.add_argument("--port", type=int, default=8790)
    ap.add_argument("--token", default=None, help="require Authorization: Bearer <token>")
    args = ap.parse_args()
    AUTH_TOKEN = args.token
    _ensure_dirs()
    publish("service.start", host=args.host, port=args.port, router=ROUTER_BASE)
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print("SparkForge on http://%s:%d  (router: %s)" % (args.host, args.port, ROUTER_BASE))
    server.serve_forever()


if __name__ == "__main__":
    main()
