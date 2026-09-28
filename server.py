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
import threading
import time
import urllib.request
import uuid
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

REPO = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(REPO, "data")
SESSIONS_DIR = os.path.join(DATA_DIR, "sessions")
WEBUI_DIR = os.path.join(REPO, "webui")

ROUTER_BASE = os.environ.get("SPARKFORGE_ROUTER", "http://127.0.0.1:8080")
MAX_FEED_EVENTS = 800
STORE_LOCK = threading.RLock()

# ---------------------------------------------------------------- events ----

_feed_lock = threading.Lock()
_feed = deque(maxlen=MAX_FEED_EVENTS)
_feed_seq = 0
_sse_queues = set()  # each: queue.Queue of str chunks


def publish(kind, **data):
    """Record an event in the feed and fan it out to live SSE subscribers."""
    global _feed_seq
    with _feed_lock:
        _feed_seq += 1
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
    with _feed_lock:
        return [e for e in _feed if e["id"] > last_id]


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


def chat_once(sess, message, model=None, on_delta=None):
    """Append the user message, run one streamed router call, store the reply."""
    if on_delta is None:
        on_delta = lambda channel, text: publish(
            "chat.delta", session=sess["id"], channel=channel, text=text)
    sys = SYSTEM_PROMPT + "\n\nCurrent harness state:\n" + context_summary()
    msgs = [{"role": "system", "content": sys}]
    msgs += [{"role": m["role"], "content": m["content"]} for m in sess["messages"][-20:]]
    msgs.append({"role": "user", "content": message})
    model = model or default_model()
    answer, think = _router_stream(msgs, model, on_delta)
    reply = append_message(sess, "assistant", answer.strip(), reasoning=think.strip() or None,
                           meta={"model": model})
    publish("chat.done", session=sess["id"], message_id=len(sess["messages"]),
            model=model, think_chars=len(think))
    return reply, model


def generate_plan(goal, model=None):
    sess = {"id": "planner", "title": "planner", "created": time.time(), "messages": []}  # ephemeral
    sys = SYSTEM_PROMPT + "\n\n" + PLANNER_PROMPT
    msgs = [{"role": "system", "content": sys}, {"role": "user", "content": goal}]
    model = model or default_model()
    answer, think = _router_stream(msgs, model, lambda ch, t: publish(
        "plan.think", channel=ch, text=t))
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
    return plan, answer, think


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
            if s["id"] == act.get("id") or s["title"] == act.get("title"):
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
            if t["id"] == act.get("id") or t["title"] == act.get("title"):
                t["status"] = "done"
                t["done_ts"] = round(time.time(), 3)
                save_tasks(tasks)
                return "task completed: %s" % t["title"]
        return "task not found"
    if action == "note":
        publish("agent.note", text=str(act.get("detail") or act.get("title") or "")[:400])
        return "noted"
    return "unknown action"


def agent_run(goal, max_steps=6, model=None, on_event=None):
    """Sense-think-act loop. No shell, no filesystem writes except harness stores."""
    if on_event is None:
        on_event = lambda kind, **d: publish(kind, **d)
    on_event("agent.start", goal=goal, max_steps=max_steps)
    model = model or default_model()
    trace = []
    for i in range(max_steps):
        sys = SYSTEM_PROMPT + "\n\n" + AGENT_PROMPT + "\n\nHarness state:\n" + context_summary()
        msgs = [{"role": "system", "content": sys},
                {"role": "user", "content": "Goal: %s (iteration %d/%d)" % (goal, i + 1, max_steps)}]
        on_event("agent.iteration", i=i + 1, of=max_steps)
        answer, think = _router_stream(msgs, model, lambda ch, t: on_event("agent.think", channel=ch, text=t))
        act = extract_json(answer) or {}
        if not isinstance(act, dict) or not act.get("action"):
            act = {"thought": answer[:200], "action": "note", "detail": answer[:400]}
        thought = str(act.get("thought", ""))[:400]
        action = act.get("action")
        on_event("agent.thought", i=i + 1, thought=thought, action=action)
        if action == "finish":
            summary = str(act.get("summary", ""))[:600]
            on_event("agent.finish", summary=summary)
            trace.append({"i": i + 1, "thought": thought, "action": "finish", "summary": summary})
            break
        obs = apply_agent_action(act)
        on_event("agent.observation", i=i + 1, observation=obs)
        trace.append({"i": i + 1, "thought": thought, "action": action, "observation": obs})
    else:
        summary = "stopped at max_steps=%d; see trace" % max_steps
        on_event("agent.finish", summary=summary)
        trace.append({"action": "finish", "summary": summary})
    return {"goal": goal, "model": model, "trace": trace}


# ------------------------------------------------------------------ HTTP ----

AUTH_TOKEN = None


def check_auth(headers):
    if not AUTH_TOKEN:
        return True
    h = headers.get("Authorization") or ""
    return h == "Bearer " + AUTH_TOKEN


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
            chat_once(sess, message, model, on_delta)
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


import subprocess  # noqa: E402  (used by telemetry_summary)


class Handler(BaseHTTPRequestHandler):
    server_version = "SparkForge/0.1"

    def _send(self, code, obj, ctype="application/json"):
        body = (json.dumps(obj, indent=2, ensure_ascii=False).encode("utf-8")
                if isinstance(obj, (dict, list)) else obj.encode("utf-8"))
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
        if not check_auth(self.headers):
            return self._send(401, {"error": "unauthorized"})
        path, qs = self._query()

        if path in ("/", "/index.html"):
            try:
                with open(os.path.join(WEBUI_DIR, "index.html"), "r", encoding="utf-8") as f:
                    return self._send(200, f.read(), ctype="text/html; charset=utf-8")
            except FileNotFoundError:
                return self._send(404, {"error": "webui missing"})
        if path == "/api/status":
            models = router_models()
            return self._send(200, {
                "service": "sparkforge", "ts": round(time.time()),
                "router": ROUTER_BASE, "models": models,
                "default_model": default_model(),
                "telemetry": telemetry_summary(),
                "plan": {"goal": load_plan().get("goal", ""),
                         "steps": len(load_plan().get("steps", []))},
                "tasks": {"total": len(load_tasks().get("tasks", [])),
                          "open": len([t for t in load_tasks().get("tasks", []) if t["status"] != "done"])},
            })
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
        return self._send(404, {"error": "not found"})

    # ---- POST ----
    def do_POST(self):
        if not check_auth(self.headers):
            return self._send(401, {"error": "unauthorized"})
        path, _ = self._query()
        body = self._body()

        if path == "/api/chat":
            message = body.get("message", "")
            if not message:
                return self._send(400, {"error": "message required"})
            sess = get_or_create_session(body.get("session"))
            append_message(sess, "user", message)
            publish("chat.user", session=sess["id"], text=message)
            try:
                reply, model = chat_once(sess, message, body.get("model"))
            except Exception as e:
                return self._send(502, {"error": "router call failed: %s" % e})
            return self._send(200, {"session": sess["id"], "model": model,
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
                plan, answer, think = generate_plan(goal, body.get("model"))
            except Exception as e:
                return self._send(502, {"error": "planner failed: %s" % e})
            return self._send(200, {"plan": plan, "raw": answer[:800]})
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
        return self._send(404, {"error": "not found"})

    # ---- PATCH ----
    def do_PATCH(self):
        if not check_auth(self.headers):
            return self._send(401, {"error": "unauthorized"})
        path, _ = self._query()
        body = self._body()
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
