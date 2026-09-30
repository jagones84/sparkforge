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
import socket
import sqlite3
import threading
import time
import urllib.error
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
import taskgraph  # v0.6: per-run LLM task graph (write_todos, live, interactive)

REPO = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(REPO, "data")
# Session store. Overridable so tests/CI can run against a scratch directory
# (`SPARKFORGE_SESSIONS_DIR`) without touching the live transcripts.
SESSIONS_DIR = os.environ.get("SPARKFORGE_SESSIONS_DIR") or os.path.join(DATA_DIR, "sessions")
WEBUI_DIR = os.path.join(REPO, "webui")

ROUTER_BASE = os.environ.get("SPARKFORGE_ROUTER", "http://127.0.0.1:8080")
MAX_FEED_EVENTS = 800
STORE_LOCK = threading.RLock()

VERSION = "0.7.1"
# Router resilience (v0.5.1): retry/backoff on 503 "model not loaded" plus the
# warm-up path that loads a cold model before the first token.
ROUTER_RETRIES = int(os.environ.get("SPARKFORGE_ROUTER_RETRIES", 5))
ROUTER_BACKOFF = float(os.environ.get("SPARKFORGE_ROUTER_BACKOFF", 0.75))
ROUTER_BACKOFF_MAX = float(os.environ.get("SPARKFORGE_ROUTER_BACKOFF_MAX", 8.0))
MODEL_LOAD_TIMEOUT = int(os.environ.get("SPARKFORGE_MODEL_LOAD_TIMEOUT", 900))

# SSE termination (v0.6.1, JAG-48). A chat stream must end — and the socket must
# close — shortly after its terminal `done`; it must never outlive it.
#   ROUTER_IDLE_TIMEOUT: max silence tolerated from the router mid-stream. When
#                        it fires the partial answer is kept and the run ends
#                        normally (so `done` is still emitted).
#   CHAT_STREAM_IDLE:    max silence on a chat SSE stream before the server
#                        finishes the stream itself (error + done) and closes.
ROUTER_IDLE_TIMEOUT = float(os.environ.get("SPARKFORGE_ROUTER_IDLE_TIMEOUT", 120.0))
CHAT_STREAM_IDLE = float(os.environ.get("SPARKFORGE_CHAT_STREAM_IDLE", 900.0))

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


# --- JAG-51 session contract: no request without a persisted answer ---------
ERROR_PREFIX = "⚠️ errore: "


def session_mark(sess):
    """Index (len of `messages`) to pass to `ensure_reply_persisted` as `since`.

    Call it *before* appending the request's `user` message: it captures the
    boundary of the request so the helper can tell whether that request
    produced an assistant turn.
    """
    return len(sess.get("messages", []))


def has_reply_since(sess, since):
    """True iff an `assistant` message was persisted at index >= `since`."""
    return any(m.get("role") == "assistant" for m in sess.get("messages", [])[since:])


def ensure_reply_persisted(sess, since, error=None, model=None):
    """JAG-51 invariant: a request never leaves an orphan `user` message.

    Every request on a session must end with an `assistant` message — the model
    reply, an explicit error turn, or both (reply + graph error are separate).
    If nothing assistant-shaped was persisted since `since`, append the explicit
    error record and return it; otherwise return None. Idempotent: calling it
    twice (e.g. from `except` and `finally`) never doubles a message.
    """
    if has_reply_since(sess, since):
        return None
    detail = str(error) if error else "empty reply from the model"
    return append_message(sess, "assistant", ERROR_PREFIX + detail,
                          meta={"model": model, "error": True, "error_detail": detail})


# ---------------------------------------------------------------- router ----


def router_models():
    """[{alias, status, loaded, n_ctx}] from the llama.cpp router; [] on failure.

    JAG-66: `n_ctx` is the model's REAL context window (from `meta.n_ctx`, or the
    `--ctx-size` in its launch args) — the source of truth for the token budget.
    """
    try:
        with urllib.request.urlopen(ROUTER_BASE + "/v1/models", timeout=6) as r:
            data = json.loads(r.read().decode("utf-8") or "{}")
        out = []
        for m in data.get("data", []):
            st = (m.get("status") or {}).get("value", "unknown")
            meta = m.get("meta") or {}
            n_ctx = meta.get("n_ctx") or meta.get("n_ctx_train") or 0
            if not n_ctx:
                args = (m.get("status") or {}).get("args") or []
                for i, a in enumerate(args):
                    if a == "--ctx-size" and i + 1 < len(args):
                        n_ctx = int(args[i + 1])
                        break
            out.append({"alias": m.get("id"), "status": st, "loaded": st == "loaded",
                        "n_ctx": int(n_ctx or 0)})
        return out
    except Exception:
        return []


CONTEXT_RESERVE = int(os.environ.get("SPARKFORGE_CONTEXT_RESERVE", "4096"))
# JAG-70: auto-compaction triggers when the REAL prompt reaches this % of the
# budget (the frontier pattern: compact before you hit the wall, not after).
AUTOCOMPACT_PCT = float(os.environ.get("SPARKFORGE_CONTEXT_AUTOCOMPACT_PCT", "75"))


def model_context_window(alias=None):
    """Real context window (tokens) of `alias`, else the loaded model, else 0."""
    ms = router_models()
    if alias:
        for m in ms:
            if m.get("alias") == alias and m.get("n_ctx"):
                return m["n_ctx"]
    for m in ms:
        if m.get("loaded") and m.get("n_ctx"):
            return m["n_ctx"]
    return 0


def context_budget(alias=None):
    """Token budget for compaction.

    JAG-66: NOT a hardcoded 6000. An explicit `SPARKFORGE_CONTEXT_BUDGET` still
    wins (for tests), otherwise we use the model's real context window minus a
    reserve for the reply, so the harness actually exploits 131k/256k instead of
    compacting every trivial conversation.
    """
    env = os.environ.get("SPARKFORGE_CONTEXT_BUDGET")
    if env:
        try:
            return int(env)
        except ValueError:
            pass
    import context_engine
    # JAG-71: a provider model may declare its window (remote models have no
    # router meta); the live router roster is the fallback for local aliases.
    try:
        import providers
        declared = providers.context_length(alias) if alias else 0
        if declared:
            return max(2048, declared - CONTEXT_RESERVE)
    except Exception:  # noqa: BLE001
        pass
    n = model_context_window(alias)
    if n:
        return max(2048, n - CONTEXT_RESERVE)
    return context_engine.DEFAULT_BUDGET



def _local_ref(model):
    """True when `model` must be warmed on the local router (JAG-71).

    Remote providers (OpenRouter, DeepSeek API) have no `/models/load`, so the
    warm-up path is skipped for them; an unknown alias is assumed local, keeping
    the pre-JAG-71 behaviour.
    """
    try:
        import providers
        hit = providers.resolve(model)
        if hit is None:
            return True
        return bool(hit[0].get("local"))
    except Exception:  # noqa: BLE001
        return True


def default_model():
    models = router_models()
    for m in models:
        if m["loaded"]:
            return m["alias"]
    return models[0]["alias"] if models else None


def model_loaded(alias):
    """(loaded_bool, model_dict_or_None) for one alias from the live roster."""
    for m in router_models():
        if m.get("alias") == alias:
            return bool(m.get("loaded")), m
    return False, None


def router_ping(timeout=3):
    """GET the router /health; returns {reachable, latency_ms, status}."""
    t0 = time.time()
    try:
        with urllib.request.urlopen(ROUTER_BASE + "/health", timeout=timeout) as r:
            body = json.loads(r.read().decode("utf-8") or "{}")
        return {"reachable": True,
                "latency_ms": round((time.time() - t0) * 1000, 1),
                "status": body.get("status", "ok")}
    except Exception as e:  # noqa: BLE001
        return {"reachable": False,
                "latency_ms": round((time.time() - t0) * 1000, 1),
                "error": str(e)}


def _router_load(alias, timeout=MODEL_LOAD_TIMEOUT):
    """POST /models/load {"model": alias} on the llama.cpp router."""
    body = json.dumps({"model": alias}).encode("utf-8")
    req = urllib.request.Request(ROUTER_BASE + "/models/load", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8") or "{}")


def _fire(on_event, kind, **data):
    """Forward a model-lifecycle event to the caller hook, else to the feed."""
    if on_event:
        on_event(kind, **data)
    else:
        publish(kind, **data)


def ensure_model(alias, timeout=None, on_event=None):
    """Load `alias` on the router if it is cold; return an evidence dict.

    Emits a `model.loading` event (SSE + feed) the moment a cold model is
    detected, so a client can render progress before the first token. The
    router has `models_autoload` on, but we drive the explicit load so the
    wait is observable and bounded instead of a silent stall.
    """
    timeout = timeout or MODEL_LOAD_TIMEOUT
    t0 = time.time()
    loaded, m = model_loaded(alias)
    if loaded:
        return {"model": alias, "loaded": True, "action": "already_loaded",
                "seconds": 0.0}
    if m is None:
        return {"model": alias, "loaded": False, "action": "unknown_model",
                "seconds": round(time.time() - t0, 2),
                "error": "alias not present in router roster"}
    _fire(on_event, "model.loading", model=alias,
          detail="loading cold model before first token")
    err = None
    try:
        _router_load(alias, timeout=timeout)
    except Exception as e:  # noqa: BLE001
        err = str(e)
    # Poll until loaded (the load call may return before the weights are up).
    while time.time() - t0 < timeout:
        if model_loaded(alias)[0]:
            secs = round(time.time() - t0, 2)
            _fire(on_event, "model.ready", model=alias, seconds=secs)
            return {"model": alias, "loaded": True, "action": "loaded",
                    "seconds": secs}
        time.sleep(1.0)
    secs = round(time.time() - t0, 2)
    _fire(on_event, "model.load_failed", model=alias, seconds=secs, error=err)
    return {"model": alias, "loaded": False, "action": "timeout",
            "seconds": secs, "error": err or "timed out waiting for load"}


def measure_llm_latency(alias, timeout=60):
    """Round-trip latency (ms) of a 1-token completion on `alias`; None on error."""
    if not alias:
        return None
    body = json.dumps({"model": alias, "max_tokens": 1, "stream": False,
                       "messages": [{"role": "user", "content": "ping"}]}).encode("utf-8")
    req = urllib.request.Request(ROUTER_BASE + "/v1/chat/completions", data=body,
                                 headers={"Content-Type": "application/json"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            r.read()
        return round((time.time() - t0) * 1000, 1)
    except Exception:  # noqa: BLE001
        return None


def selfcheck_payload(host="127.0.0.1", port=8790, llm_probe=True):
    """GET /api/selfcheck — one JSON object proving the chat path is healthy."""
    t0 = time.time()
    roster = router_models()
    ping = router_ping()
    requested = routing.pick("chat") or default_model()
    loaded_alias = next((m["alias"] for m in roster if m.get("loaded")), None)
    req_loaded = bool(requested and any(
        m["alias"] == requested and m["loaded"] for m in roster))
    llm_ms = measure_llm_latency(loaded_alias or requested) if (llm_probe and ping["reachable"]) else None
    return {
        "service": "sparkforge", "version": VERSION,
        "ts": round(time.time(), 3),
        "status": "ok" if (ping["reachable"] and llm_ms is not None) else "degraded",
        "model_requested": requested,
        "model_loaded": req_loaded,
        "model_loaded_alias": loaded_alias,
        "models": [{"alias": m["alias"], "loaded": m["loaded"]} for m in roster],
        "router": ROUTER_BASE,
        "router_reachable": ping["reachable"],
        "router_latency_ms": ping["latency_ms"],
        "router_status": ping.get("status"),
        "llm_latency_ms": llm_ms,
        "token_configured": bool(AUTH_TOKEN),
        "auth_required": bool(AUTH_TOKEN),
        "host": host, "port": port,
        "check_seconds": round(time.time() - t0, 2),
    }


def strip_think(text):
    """Split optional <think>...</think> out of content."""
    m = re.search(r"<think>(.*?)</think>", text, re.S)
    if m:
        return text[: m.start()] + text[m.end():], m.group(1)
    return text, None


def _open_with_retry(req, timeout):
    """urlopen with exponential backoff on 503 (router: model not loaded).

    The llama.cpp router returns 503 while a cold model is still warming up;
    we retry a few times instead of surfacing a hard failure to the client.
    """
    delay = ROUTER_BACKOFF
    for attempt in range(ROUTER_RETRIES + 1):
        try:
            return urllib.request.urlopen(req, timeout=timeout)
        except urllib.error.HTTPError as e:
            if e.code == 503 and attempt < ROUTER_RETRIES:
                publish("model.retry", attempt=attempt + 1, delay=delay,
                        status=503, reason="model not loaded")
                time.sleep(delay)
                delay = min(delay * 2, ROUTER_BACKOFF_MAX)
                continue
            raise


def _set_read_idle(resp, seconds):
    """Bound the silence of an in-flight router stream (JAG-48).

    A stalled upstream stream used to hold the chat SSE open forever (events
    already emitted, no `done`, socket ESTAB) — the phone app waits for EOF and
    stayed on `busy`. With an idle read timeout the partial answer is kept and
    the normal `done` path is taken instead.
    """
    for getter in (lambda r: r.fp.raw._sock, lambda r: r.fp.raw, lambda r: r.fp):
        try:
            getter(resp).settimeout(seconds)
            return True
        except Exception:  # noqa: BLE001
            continue
    return False


def _chat_endpoint(model):
    """(url, headers, model_id) for a completion, provider-aware (JAG-71).

    A `<provider>:<model>` reference (or a known bare model id) routes to that
    provider's endpoint with its key; anything unknown falls back to the local
    DGX router, so existing configs keep working unchanged.
    """
    try:
        import providers
        resolved = providers.endpoint(model)
        if resolved:
            return resolved
    except Exception:  # noqa: BLE001 — the catalogue must never break chat
        pass
    return (ROUTER_BASE + "/v1/chat/completions",
            {"Content-Type": "application/json"}, model or "default")


def _router_stream(messages, model, on_delta, timeout=300):
    """POST /chat/completions with stream=true; feed deltas to on_delta.

    on_delta(channel, text) with channel in {think, answer}. Returns the
    full (answer, think) pair. Falls back to a non-streaming call.
    """
    url, headers, model_id = _chat_endpoint(model)
    body = json.dumps({
        "model": model_id,
        "messages": messages,
        "stream": True,
        "temperature": 0.7,
    }).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=headers)
    answer, think = [], []
    try:
        with _open_with_retry(req, timeout) as resp:
            if ROUTER_IDLE_TIMEOUT > 0:
                # v0.6.1 (JAG-48): mid-stream silence must not hang the run.
                _set_read_idle(resp, ROUTER_IDLE_TIMEOUT)
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
        body = json.dumps({"model": model_id, "messages": messages,
                           "temperature": 0.7}).encode("utf-8")
        req = urllib.request.Request(url, data=body, headers=headers)
        with _open_with_retry(req, timeout) as resp:
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

BREAKDOWN_PROMPT = (
    "Break the user request into 1-6 concrete todo tasks for the harness task "
    "board. Respond with ONLY a JSON array of short task strings. If the request "
    "is pure smalltalk with nothing actionable, respond with []."
)

# JAG-73: make the memory store explicit and actionable. Before this the agent
# had no tool to remember/recall (the store was passive), and the prompt never
# said memory existed or WHEN to use it.
MEMORY_POLICY = (
    "Memory: you have a persistent memory store seeded across sessions (the "
    "`memory` tool; also GET /api/memory). Relevant past memories are "
    "AUTO-INJECTED below as 'Relevant memories from previous sessions' when they "
    "match the current message. Use it deliberately:\n"
    "- to REMEMBER: call memory{action:'store', content:'...'} as soon as you "
    "learn a durable fact — a user preference, a decision and its reason, a "
    "project convention, the fix for a bug. Keep it short and self-contained.\n"
    "- to RECALL: call memory{action:'recall', query:'...'} whenever the user "
    "refers to earlier work or you are missing context; memory{action:'recent'} "
    "shows the newest notes.\n"
    "Never store ephemeral chatter, and never store secrets."
)


def self_summary():
    """Compact self-knowledge block injected into the system prompt (v0.5)."""
    return (
        "Self-knowledge: you are SparkForge v0.6, a local agent harness installed "
        "at the repo path %s on this DGX Spark. Data dir: %s. Tool policy: "
        "config/tools.yaml; model routing: config/routing.yaml; external MCP "
        "servers: config/mcp_clients.yaml (add a stdio command or HTTP url entry, "
        "tools appear as <client>__<tool>; then reload via POST /api/tools or "
        "restart with `systemctl --user restart sparkforge.service`, unit file "
        "deploy/sparkforge.service, port 8790). Skills: the `skills` tool lists and "
        "reads agent skills from skills/<category>/<name>/SKILL.md. Harness-"
        "native tools: "
        "registry.TOOL_SCHEMAS + tools.py. Full self report: GET /api/self or "
        "the `self` tool."
    ) % (REPO, DATA_DIR)


def self_knowledge():
    """Full self report: paths, config, docs, service state, extension recipe."""
    import subprocess as sp
    info = {
        "name": "SparkForge", "version": VERSION,
        "repo_path": REPO, "data_dir": DATA_DIR, "sessions_dir": SESSIONS_DIR,
        "webui": WEBUI_DIR,
        "entrypoint": os.path.join(REPO, "server.py"), "port": 8790,
        "router": ROUTER_BASE,
        "config": {"tools": os.path.join(REPO, "config", "tools.yaml"),
                   "routing": os.path.join(REPO, "config", "routing.yaml"),
                   "mcp_clients": os.path.join(REPO, "config", "mcp_clients.yaml")},
        "docs": {"plan": os.path.join(REPO, "docs", "PLAN.md"),
                 "readme": os.path.join(REPO, "README.md"),
                 "architecture": os.path.join(REPO, "docs", "ARCHITECTURE.md")},
        "service": {"unit": "sparkforge.service", "scope": "user",
                    "unit_file": os.path.join(REPO, "deploy", "sparkforge.service"),
                    "restart_cmd": "systemctl --user restart sparkforge.service"},
        "skills_dir": os.path.join(REPO, "skills"),
        "install_skill": (
            "A skill is a directory with a SKILL.md. Drop/clone it into a "
            "category under skills/ (e.g. skills/ops/<name>/SKILL.md), or symlink "
            "an existing distribution dir: `ln -sfn <source-dir> skills/<cat>`. "
            "Skills are picked up automatically by the `skills` tool (no reload "
            "needed). External MCP servers: add an entry to "
            "config/mcp_clients.yaml with either command+args (stdio) or url "
            "(HTTP); tools are discovered via tools/list and exposed as "
            "<client>__<tool> in the registry. Harness-native tools go in "
            "registry.TOOL_SCHEMAS + tools.py with policy in config/tools.yaml. "
            "Apply with POST /api/tools (reload) or `systemctl --user restart "
            "sparkforge.service`."),
    }
    try:
        import skills as skills_mod
        sk = skills_mod.list_skills()
        info["skills"] = {"dir": info["skills_dir"], "count": len(sk),
                          "categories": sorted({s["category"] for s in sk})}
    except Exception as e:  # noqa: BLE001
        info["skills"] = {"error": str(e)}
    try:
        out = sp.run(["systemctl", "--user", "is-active", "sparkforge.service"],
                     capture_output=True, text=True, timeout=4).stdout.strip()
        info["service"]["active"] = out or "unknown"
    except Exception:
        info["service"]["active"] = "unknown"
    return info


def breakdown_tasks(message, model=None, session=None):
    """Ask the planner-role model to split a request into TASKS board todos.

    Runs in a background thread so chat streaming is never delayed; the board
    is mutated live and the UI sees it through the tasks.update SSE event.
    """
    def work():
        try:
            msgs = [{"role": "system", "content": SYSTEM_PROMPT + "\n\n" + BREAKDOWN_PROMPT},
                    {"role": "user", "content": message}]
            m = routing.pick("planner") or model or default_model()
            answer, _think = _router_stream(msgs, m, lambda ch, t: None)
            items = extract_json(answer)
            if isinstance(items, dict):
                items = items.get("tasks") or items.get("items")
            if not isinstance(items, list):
                return
            tasks = load_tasks()
            added = []
            for it in items[:6]:
                title = str(it).strip()
                if not title:
                    continue
                t = {"id": uuid.uuid4().hex[:6], "title": title[:140],
                     "status": "todo", "created": round(time.time(), 3),
                     "session": session}
                tasks.setdefault("tasks", []).append(t)
                added.append(t)
            if added:
                save_tasks(tasks)
                publish("tasks.breakdown", session=session, source=(message or "")[:120],
                        tasks=[t["title"] for t in added])
        except Exception:
            pass
    threading.Thread(target=work, daemon=True).start()


def context_summary(session_id=None, graph_key=None):
    """Harness state injected into EVERY prompt.

    JAG-63: the persistent task list (the graph) is the single TODO the model
    owns. It is re-injected on every turn, so the model never forgets it across
    compaction or restarts. The old parallel `tasks.json` board is no longer
    injected here (it was the source of the "graph vs todo" confusion).
    """
    plan = load_plan()
    lines = []
    key = graph_key or session_id
    g = None
    if key:
        try:
            g = taskgraph.load(key)
        except Exception:  # noqa: BLE001 — context must never break a turn
            g = None
    if plan.get("goal"):
        lines.append("PLAN goal: " + plan["goal"])
        for s in plan.get("steps", []):
            lines.append(" - [%s] %s" % ("x" if s.get("done") else " ", s.get("title", "")))
    if g:
        todos = taskgraph.render_todos(g)
        if todos:
            lines.append(todos)
    return "\n".join(lines) if lines else "(no task list yet)"


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


def start_run_graph(run_id, goal, session_id=None, model=None, on_event=None):
    """v0.6 — first action of a run: model-generated write_todos → live graph.

    The graph is bound to run_id + session_id and every node lands on the feed as
    a `graph.node.added` event the moment the model emits it.
    """
    try:
        return taskgraph.generate_from_model(run_id, goal, session_id=session_id,
                                             model=model, on_event=on_event)
    except Exception as e:  # noqa: BLE001 — graph must never break the run
        publish("graph.error", run=run_id, error=str(e))
        return taskgraph.ensure(run_id, session_id, goal), []


def finish_run_graph(run_id, session_id, goal, on_event=None):
    """Run end — close every still-open node with evidence (acceptance: all done)."""
    try:
        g = taskgraph.load(run_id)
        if not g or not g.get("nodes"):
            return None
        closed = taskgraph.finalize(g, "run %s completed: %s" % (run_id, str(goal)[:200]))
        payload = {"run": run_id, "session": session_id,
                   "nodes": len(g.get("nodes", [])), "closed": len(closed)}
        (on_event or publish)("graph.finalized", **payload)
        return g
    except Exception as e:  # noqa: BLE001
        publish("graph.error", run=run_id, error=str(e))
        return None


def graph_post(run_id, body):
    """POST /api/runs/<id>/graph/nodes — add / cancel / update / complete / replan.

    Returns (payload, error, code). Evidence is mandatory to move a node to done.
    """
    action = str(body.get("action") or "add").lower()
    source = body.get("source", "operator")
    g = taskgraph.load(run_id)
    if g is None:
        return None, {"error": "graph not found for run %s" % run_id}, 404
    try:
        if action in ("add", "node"):
            node = taskgraph.add_node(g, body.get("label") or body.get("title"),
                                      deps=body.get("deps"), status=body.get("status", "todo"),
                                      evidence=body.get("evidence"), source=source)
            return node, None, 200
        if action in ("cancel", "remove", "delete"):
            return taskgraph.cancel_node(g, body.get("id")), None, 200
        if action == "complete" or action == "done":
            return taskgraph.complete_node(g, body.get("id"), body.get("label"),
                                           evidence=body.get("evidence"), source=source), None, 200
        if action == "update":
            return taskgraph.update_node(g, body.get("id"), status=body.get("status"),
                                         label=body.get("label"), deps=body.get("deps"),
                                         evidence=body.get("evidence"), source=source), None, 200
        if action == "replan":
            added = taskgraph.replan_from_model(g, body.get("note") or body.get("goal"),
                                                body.get("model"))
            return {"added": [n["id"] for n in added], "added_labels": [n["label"] for n in added],
                    "nodes": len(g.get("nodes", []))}, None, 200
    except ValueError as e:
        return None, {"error": str(e)}, 400
    except KeyError as e:
        return None, {"error": str(e).strip("'\"")}, 404
    return None, {"error": "unknown action %r" % action}, 400


CHAT_TOOL_MAX_STEPS = int(os.environ.get("SPARKFORGE_CHAT_TOOL_STEPS", "4"))
CHAT_TOOL_PROMPT = (
    "\n\n## Tools\nYou are a tool-using agent, not a plain chatbot: you chat with "
    "the user AND you can act. When a request needs a tool (run a command, read or "
    "write a file, call an MCP server, list or read a skill), reply with ONLY this "
    'JSON and nothing else: {"action":"tool","tool":"<name>","args":{...}}. '
    "After the tool runs you receive its observation and MUST continue: call another "
    "tool or answer the user in plain text. Never show JSON to the user; the final "
    "message must be plain prose. To plan a multi-step request, FIRST emit ONLY "
    '{"action":"write_todos","todos":[{"label":"<imperative step>","deps":[],"parent":null}]} '
    "(2-8 steps you author yourself; this list is PERSISTENT — it is saved and "
    "re-shown to you on every turn, and only you or the user may clear it), then "
    "FOLLOW it: before starting a step emit ONLY "
    '{"action":"update_todos","steps":[{"index":<0-based>,"status":"doing"}]}; when '
    "a step is finished emit ONLY "
    '{"action":"update_todos","steps":[{"index":<i>,"status":"done","evidence":"<what proves it>"}]} '
    "(done REQUIRES evidence). If new work appears or a step became irrelevant, "
    "briefly re-plan with "
    '{"action":"replan_todos","note":"<why>"} and then IMMEDIATELY resume the plan. '
    "Never drift: after any update, return to the list and continue with the next "
    "step. "
    "Tool registry (allowlist):\n"
)


def _looks_like_json_action(text):
    """True when `text` is a (possibly malformed/truncated) tool-call JSON —
    i.e. something we must NEVER show to the user as a chat reply."""
    t = (text or "").strip()
    if not t.startswith(("{", "[")):
        return False
    return ('"action"' in t) or ('"tool"' in t) or ('"args"' in t)


# JAG-74: "act, don't announce". A reply that OPENS with an action verb in the
# first person and is short is a promise of imminent work, not a result. If no
# tool ran this turn we nudge the model once to actually do it (or conclude).
_PROMISE_RE = re.compile(
    r"^\s*(?:\*\*)?(?:carico|procedo|eseguo|lancio|creo|installo|avvio|aggiorno|"
    r"verifico|controllo|continuo|i'?ll|i will|i'?m going to|let me|loading|running)\b",
    re.IGNORECASE)


def _looks_like_promise(text):
    """True when the reply only announces an action (and is not a result)."""
    t = (text or "").strip()
    return bool(t) and len(t) <= 400 and bool(_PROMISE_RE.match(t))


def _chat_tool_call(act, av02):
    """Accept the canonical {"action":"tool","tool":X,"args":{...}} and the
    model's frequent variant {"action":X,"args":{...}} when X is a real tool
    name. Returns (tool, args) or None."""
    if not isinstance(act, dict):
        return None
    try:
        names = set(av02.registry.tool_names())
    except Exception:  # noqa: BLE001
        return None
    tool = act.get("tool")
    if tool not in names and act.get("action") in names:
        tool = act.get("action")
    if tool not in names:
        return None
    args = dict(act.get("args") or {})
    for k in ("command", "path", "content", "url"):
        if k in act and k not in args:
            args[k] = act[k]
    return str(tool), args


def _apply_chat_todos(sess, act, on_event):
    """Harness action `write_todos`: persist the model-authored todo list.

    The chat loop is the ONLY writer of the task list (no separate planner
    call): when the model emits `{"action":"write_todos","todos":[...]}` we map
    it onto the session graph, publish a normal tool.call/tool.result pair so
    the app renders an inline card, and let the model continue.
    """
    try:
        graph = taskgraph.ensure(sess["id"], session_id=sess["id"])
        todos = act.get("todos")
        if isinstance(todos, str):
            todos, _ = taskgraph.parse_todos(todos)
        on_event("tool.call", session=sess["id"], tool="write_todos", args={},
                 inline=True)
        base = len(graph.get("nodes", []))
        added = taskgraph.apply_write_todos(
            graph, taskgraph._missing(graph, todos or []))
        total = len(graph.get("nodes", []))
        # surface each node on the chat stream too, so the app renders the list
        # live (apply_write_todos only fans out on the global feed).
        for i, node in enumerate(added):
            on_event("graph.node.added", session=sess["id"], node=node,
                     index=base + i, total=total)
        on_event("tool.result", session=sess["id"], tool="write_todos", ok=True,
                 exit_code=0, backend="harness",
                 summary="task list: %d node(s), +%d" % (total, len(added)))
        return len(added)
    except Exception as e:  # noqa: BLE001 — the task list must never break chat
        try:
            on_event("tool.result", session=sess["id"], tool="write_todos",
                     ok=False, backend="harness", stderr=str(e)[:200])
        except Exception:  # noqa: BLE001
            pass
        return 0


def _resolve_graph_node(graph, step):
    """Locate a node by id, label or 0-based index (JAG-75)."""
    node = None
    if step.get("id") is not None:
        node = taskgraph.find(graph, node_id=str(step["id"]))
    if node is None and step.get("label"):
        node = taskgraph.find(graph, label=step["label"])
    if node is None and step.get("index") is not None:
        nodes = graph.get("nodes", [])
        try:
            i = int(step["index"])
        except (TypeError, ValueError):
            return None
        if 0 <= i < len(nodes):
            node = nodes[i]
    return node


def _apply_chat_todo_updates(sess, act, on_event):
    """Harness action `update_todos`: the MODEL advances its own plan (JAG-75).

    `{"action":"update_todos","steps":[{"index":0,"status":"doing"}]}` marks a
    step in progress; `{"status":"done","evidence":"..."}` completes it (evidence
    is mandatory — same rule as the API). This is what let the graph advance on
    its own: before, only the UI/API could move a node.
    """
    try:
        graph = taskgraph.ensure(sess["id"], session_id=sess["id"])
        steps = act.get("steps") or act.get("todos") or []
        if isinstance(steps, dict):
            steps = [steps]
        if not isinstance(steps, list):
            steps = []
        on_event("tool.call", session=sess["id"], tool="update_todos", args={}, inline=True)
        changed = []
        for step in steps:
            if not isinstance(step, dict):
                continue
            node = _resolve_graph_node(graph, step)
            if node is None:
                continue
            status = str(step.get("status") or "").strip().lower()
            ev = step.get("evidence")
            try:
                if status == "done":
                    node = taskgraph.complete_node(
                        graph, node_id=node["id"], evidence=ev, source="model:update_todos")
                elif status in taskgraph.STATUSES:
                    node = taskgraph.update_node(
                        graph, node["id"], status=status, evidence=ev,
                        source="model:update_todos")
                else:
                    continue
            except (KeyError, ValueError):
                continue
            changed.append(node)
            on_event("graph.node.updated", session=sess["id"], node=node,
                     index=graph["nodes"].index(node), total=len(graph["nodes"]),
                     changes=["status"])
        on_event("tool.result", session=sess["id"], tool="update_todos", ok=True,
                 exit_code=0, backend="harness",
                 summary="task list: %d/%d step(s) updated"
                         % (len(changed), len([s for s in steps if isinstance(s, dict)])))
        return len(changed)
    except Exception as e:  # noqa: BLE001 — the task list must never break chat
        try:
            on_event("tool.result", session=sess["id"], tool="update_todos",
                     ok=False, backend="harness", stderr=str(e)[:200])
        except Exception:  # noqa: BLE001
            pass
        return 0


def _apply_chat_replan(sess, act, on_event):
    """Harness action `replan_todos`: a brief, controlled re-plan (JAG-75).

    The model asks for the graph to be extended/corrected; only NEW steps are
    generated, existing nodes are preserved, and the loop then resumes the plan.
    """
    try:
        graph = taskgraph.ensure(sess["id"], session_id=sess["id"])
        on_event("tool.call", session=sess["id"], tool="replan_todos", args={}, inline=True)
        added = taskgraph.replan_from_model(
            graph, act.get("note") or act.get("goal") or "", on_event=on_event) or []
        on_event("tool.result", session=sess["id"], tool="replan_todos", ok=True,
                 exit_code=0, backend="harness",
                 summary="re-plan: +%d step(s)" % len(added))
        return len(added)
    except Exception as e:  # noqa: BLE001 — never break chat
        try:
            on_event("tool.result", session=sess["id"], tool="replan_todos",
                     ok=False, backend="harness", stderr=str(e)[:200])
        except Exception:  # noqa: BLE001
            pass
        return 0


def chat_once(sess, message, model=None, on_delta=None, trace=None, on_event=None):
    """Run one streamed router call and persist exactly one assistant message.

    Contract (JAG-51): the caller appends the `user` message; this function is
    the only place that persists the matching `assistant` turn. It returns
    `(message, model_used)`. On success the message carries the reply; when the
    model returns no answer at all the message is still persisted, flagged with
    `error=True` / `error_detail` (see `ensure_reply_persisted`) so no request
    can ever end as an orphan `user` turn. Raises only when the router call
    itself fails — callers then persist the error turn (`ensure_reply_persisted`).
    """
    if on_delta is None:
        on_delta = lambda channel, text: publish(
            "chat.delta", session=sess["id"], channel=channel, text=text)
    if on_event is None:
        on_event = publish
    # JAG-58b: the chat IS the agent — same tool registry as the agent loop, so
    # the model can call tools inline before it answers. Falls back to plain chat
    # if the tool registry is unavailable.
    # JAG-70: one shared assembler (`_system_prompt`) is used here AND by the
    # context indicator, so the measured prompt size cannot drift from reality.
    tool_ctx = _tool_context()
    sys = _system_prompt(sess, tool_ctx)
    # v0.3 context engineering: compaction + token budget + memory retrieval
    try:
        import context_engine
        msgs, ctx_stats = context_engine.build(
            sys, sess["messages"], message, budget_tokens=context_budget(model))
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
    # JAG-58b: tool-aware chat loop. The model may answer directly, or ask for a
    # tool; the tool runs through the same approval gate as the agent loop and
    # its observation is fed back, then the model continues. Streaming deltas are
    # buffered per iteration so raw tool-call JSON is never shown to the user.
    max_steps = CHAT_TOOL_MAX_STEPS if tool_ctx else 1
    answer, think = "", ""
    final_answer = ""
    announce_nudged = False
    for _step in range(max_steps):
        collected = []

        def _capture(ch, t, _c=collected):
            # JAG-65: stream the model's REASONING live, so a tool-calling turn
            # shows progress instead of dead air; buffer only answer text so raw
            # tool-call JSON is never streamed to the user.
            if ch == "think":
                on_delta("think", t)
            else:
                _c.append((ch, t))

        answer, think, model = stream_with_fallback(msgs, model, "chat", _capture)
        act = extract_json(answer)
        if isinstance(act, dict) and act.get("action") == "write_todos":
            n = _apply_chat_todos(sess, act, on_event)
            msgs.append({"role": "assistant", "content": answer})
            msgs.append({"role": "user", "content":
                         "Task list saved (%d new step(s)); the full persistent list "
                         "is in your system state. Now work through it: answer the "
                         "user in plain prose, or call a tool — one step at a time."
                         % n})
            continue
        if isinstance(act, dict) and act.get("action") in ("update_todos", "replan_todos"):
            # JAG-75: the model advances its own plan mid-run (in_progress → done
            # with evidence), or briefly re-plans. Then it must resume the plan.
            if act["action"] == "update_todos":
                _apply_chat_todo_updates(sess, act, on_event)
                nudge = ("Task list updated. Continue STRICTLY following the plan: mark "
                         "the next step 'doing' before you start it, and 'done' with "
                         "evidence when it is finished — then move to the next step.")
            else:
                _apply_chat_replan(sess, act, on_event)
                nudge = ("Plan updated. Now resume following the plan from where you "
                         "left off; do not re-plan again unless something really changed.")
            msgs.append({"role": "assistant", "content": answer})
            msgs.append({"role": "user", "content": nudge})
            continue
        tc = _chat_tool_call(act, api_v02) if tool_ctx else None
        if tc:
            tool, args = tc
            on_event("tool.call", session=sess["id"], tool=tool, args=args, inline=True)
            try:
                res = api_v02.gated_call(tool, args, run_id=sess["id"])
                obs = res.get("observation") or res.get("error") or res.get("status") or ""
                ok = res.get("status") == "executed"
                on_event("tool.result", session=sess["id"], tool=tool, ok=ok, inline=True)
            except Exception as e:  # noqa: BLE001 — a tool failure must not kill chat
                obs, ok = "tool error: %s" % e, False
                on_event("tool.result", session=sess["id"], tool=tool, ok=False,
                         stderr=str(e)[:200], inline=True)
            msgs.append({"role": "assistant", "content": answer})
            msgs.append({"role": "user", "content":
                         "Observation for tool %s:\n%s\n\n"
                         "Now answer the user in plain text, or call another tool."
                         % (tool, str(obs)[:4000])})
            continue
        if isinstance(act, dict) and act:
            # stray JSON the model emitted in a schema we do not recognise: never
            # show it to the user — nudge it back to a valid tool call or prose.
            msgs.append({"role": "assistant", "content": answer})
            msgs.append({"role": "user", "content":
                         "That was not a valid tool call. Either emit "
                         '{"action":"tool","tool":"<name>","args":{...}} for a real '
                         "tool, or answer the user in plain text."})
            continue
        if _looks_like_json_action(answer):
            # JAG-64: malformed/TRUNCATED tool-call JSON (extract_json failed, so
            # `act` is None). Never leak it into the chat — ask for a clean retry.
            msgs.append({"role": "assistant", "content": answer})
            msgs.append({"role": "user", "content":
                         "That JSON was invalid or incomplete (it did not parse). "
                         "Re-emit a VALID "
                         '{"action":"tool","tool":"<name>","args":{...}} with all '
                         "braces closed, or answer the user in plain prose. Never "
                         "show JSON to the user."})
            continue
        if _looks_like_promise(answer) and not announce_nudged:
            # JAG-74: the model promised an action ("Carico un'altra skill…") but
            # called no tool this turn — nudge it ONCE to actually act or conclude.
            announce_nudged = True
            msgs.append({"role": "assistant", "content": answer})
            msgs.append({"role": "user", "content":
                         "You announced an action but did not call any tool. Either "
                         'call it NOW with {"action":"tool","tool":"<name>","args":{...}}, '
                         "or — if there is nothing left to do — reply with the final "
                         "result in plain prose. Do not just repeat the announcement."})
            continue
        for ch, t in collected:
            on_delta(ch, t)
        final_answer, think = answer, think
        break
    if not final_answer:
        # the loop ran out of tool steps without a prose answer — force one.
        msgs.append({"role": "user", "content":
                     "Answer the user now in plain text. Do not emit JSON."})
        final_answer, think, model = stream_with_fallback(msgs, model, "chat", on_delta)
    answer = final_answer or answer
    if trace:
        trace.span("llm.chat", model=model, context=ctx_stats)
        trace.llm_call(msgs, answer + think)
    meta = {"model": model}
    content = answer.strip()
    if _looks_like_json_action(content):
        # JAG-64: last-resort guard — never persist raw tool-call JSON.
        meta = {"model": model, "error": True,
                "error_detail": "tool-call JSON leaked instead of a reply"}
        content = ERROR_PREFIX + "the model returned tool-call JSON, not a reply — retry."
    if not content:
        # JAG-51: an empty answer is not a reply — record it explicitly instead
        # of persisting a silent blank assistant turn.
        meta = {"model": model, "error": True,
                "error_detail": "empty reply from the model"}
        content = ERROR_PREFIX + meta["error_detail"]
    reply = append_message(sess, "assistant", content, reasoning=think.strip() or None,
                           meta=meta)
    publish("chat.done", session=sess["id"], message_id=len(sess["messages"]),
            model=model, think_chars=len(think), error=bool(meta.get("error")))
    try:  # JAG-69: deterministic Stop hooks at the end of the turn
        import hooks
        hooks.run("Stop", run_id=sess["id"], observation=content)
    except Exception:  # noqa: BLE001 — a hook must never break a turn
        pass
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


AGENT_ACTIONS = ("write_todos", "plan_step", "complete_plan_step", "add_task",
                 "complete_task", "note", "finish")

AGENT_PROMPT = (
    "You are the agent loop of the SparkForge harness. Given the goal and the "
    "current harness state, decide ONE next action. Respond with ONLY a JSON "
    'object: {"thought": "<brief reasoning>", "action": "write_todos|'
    'plan_step|complete_plan_step|add_task|complete_task|note|finish", '
    '"todos": [{"label": "...", "deps": []}] (for write_todos), '
    '"title": "<for plan_step/add_task>", "id": "<for '
    'complete_plan_step/complete_task>", "detail": "<optional>", '
    '"summary": "<required for finish>"}.'
)


def apply_agent_action(act, run_id=None, session=None):
    """Apply a parsed agent action; returns observation text.

    v0.6: when a run_id is given, the action is mirrored onto the run's task
    graph (plan_step/complete_plan_step/add_task/complete_task → nodes).
    """
    action = act.get("action")
    plan, tasks = load_plan(), load_tasks()
    if action == "plan_step":
        if not plan.get("goal"):
            plan["goal"] = act.get("detail") or act.get("title") or "goal"
        step = {"id": uuid.uuid4().hex[:6], "title": str(act.get("title", "step"))[:120],
                "detail": str(act.get("detail", ""))[:300], "done": False}
        plan.setdefault("steps", []).append(step)
        save_plan(plan)
        return _mirror_graph(run_id, act, "plan step added: %s (%s)" % (step["title"], step["id"]),
                             session)
    if action == "complete_plan_step":
        for s in plan.get("steps", []):
            if s.get("id") == act.get("id") or s.get("title") == act.get("title"):
                s["done"] = True
                save_plan(plan)
                return _mirror_graph(run_id, act,
                                     "plan step completed: %s" % s["title"], session)
        return "plan step not found"
    if action == "add_task":
        t = {"id": uuid.uuid4().hex[:6], "title": str(act.get("title", "task"))[:120],
             "status": "todo", "created": round(time.time(), 3)}
        tasks.setdefault("tasks", []).append(t)
        save_tasks(tasks)
        return _mirror_graph(run_id, act, "task added: %s (%s)" % (t["title"], t["id"]), session)
    if action == "complete_task":
        for t in tasks.get("tasks", []):
            if t.get("id") == act.get("id") or t.get("title") == act.get("title"):
                t["status"] = "done"
                t["done_ts"] = round(time.time(), 3)
                save_tasks(tasks)
                return _mirror_graph(run_id, act, "task completed: %s" % t["title"], session)
        return "task not found"
    if action == "write_todos":
        return _mirror_graph(run_id, act, "write_todos: graph updated", session)
    if action == "note":
        publish("agent.note", text=str(act.get("detail") or act.get("title") or "")[:400])
        return "noted"
    return "unknown action"


def _mirror_graph(run_id, act, observation, session=None):
    """Mirror an applied action onto the run graph, with the observation as evidence."""
    if run_id:
        try:
            taskgraph.map_action(run_id, act, observation=observation, session_id=session)
        except Exception as e:  # noqa: BLE001 — mapping must never break a run
            publish("graph.error", run=run_id, error=str(e))
    return observation


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

    # v0.6: the run's FIRST action is a model-generated write_todos call, which
    # seeds the per-run task graph that the agent loop then advances.
    try:
        start_run_graph(trace.id, goal, None, model, on_event=on_event)
    except Exception as e:  # noqa: BLE001
        publish("graph.error", run=trace.id, error=str(e))

    actions = []
    for i in range(max_steps):
        sys = SYSTEM_PROMPT + "\n\n" + self_summary() + "\n\n" + AGENT_PROMPT + "\n\nHarness state (your persistent task list):\n" + context_summary(graph_key=trace.id)
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
        obs = apply_agent_action(act, run_id=trace.id)
        trace.span("agent.action", i=i + 1, action=action, observation=obs)
        on_event("agent.observation", i=i + 1, observation=obs)
        actions.append({"i": i + 1, "thought": thought, "action": action, "observation": obs})
    else:
        summary = "stopped at max_steps=%d; see trace" % max_steps
        on_event("agent.finish", summary=summary)
        actions.append({"action": "finish", "summary": summary})
    finish_run_graph(trace.id, None, goal, on_event=on_event)
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


def sse_close(handler):
    """v0.6.1 (JAG-48): end an SSE response for good.

    The HTTP/1.0 shutdown was not enough: the generator (and with it the
    socket) stayed open whenever the upstream model call stalled, so clients
    that wait for EOF (`curl -N`, the mobile app's HttpURLConnection with
    readTimeout=0) froze on `busy` and could not send the next message.
    Flush, mark the connection non-reusable and send the EOF explicitly.
    """
    try:
        handler.wfile.flush()
    except Exception:  # noqa: BLE001 — client already gone
        pass
    handler.close_connection = True
    try:
        handler.connection.shutdown(socket.SHUT_WR)  # FIN → client sees EOF now
    except Exception:  # noqa: BLE001
        pass


def sse_response(handler, gen, keepalive=False):
    """Write an SSE stream and close it when the generator ends.

    `keepalive=True` is reserved for `/api/feed` (and the blackboard watcher):
    those streams are loopback tails that stay open on purpose, so the socket
    gets SO_KEEPALIVE. Every other stream (`/api/chat/stream`,
    `/api/agent/run`) is terminal: after its `done` event the generator is
    exhausted and the connection is closed immediately.
    """
    handler.send_response(200)
    handler.send_header("Content-Type", "text/event-stream")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Connection", "close")
    handler.end_headers()
    if keepalive:
        try:
            handler.connection.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        except Exception:  # noqa: BLE001
            pass
    try:
        for chunk in gen:
            handler.wfile.write(chunk.encode("utf-8"))
            handler.wfile.flush()
    except (BrokenPipeError, ConnectionResetError):
        pass
    finally:
        sse_close(handler)


def sse_pump(q, worker, open_comment=": stream open\n\n", terminal="done",
             idle_timeout=None):
    """Drain a producer queue into SSE frames, then stop for good.

    v0.6.1 (JAG-48): the stream is *terminal* — it ends with exactly one
    terminal `done` and the caller closes the socket.
    Two guards make that unconditional, so the connection can never linger:
      * the producer thread dying without its sentinel ends the stream, and
      * `idle_timeout` seconds without a single event ends the stream with an
        `error` + `done` instead of waiting on a stalled upstream forever.
    v1.6.9 (JAG-60): while the producer is silent (blocked on the approval
    gate, or a slow first token) we emit an SSE comment `: ping` every ~10s so
    mobile networks/proxies don't idle-abort the channel ("connection abort").
    """
    yield open_comment  # first bytes out immediately → the client sees 200
    deadline = time.time() + idle_timeout if idle_timeout else None
    idle_s = 0.0
    while True:
        try:
            item = q.get(timeout=1.0)
        except queue.Empty:
            if deadline is not None and time.time() > deadline:
                yield "event: error\ndata: %s\n\n" % json.dumps(
                    {"error": "chat stream timed out after %.0fs of silence" % idle_timeout})
                break
            if not worker.is_alive():
                break  # producer gone without a sentinel: never hang the client
            idle_s += 1.0
            if idle_s >= 10.0:
                idle_s = 0.0
                yield ": ping\n\n"  # heartbeat: keeps the SSE channel alive
            continue
        if item is None:
            break
        idle_s = 0.0
        if deadline is not None:
            deadline = time.time() + idle_timeout
        yield item
    yield "event: %s\ndata: {}\n\n" % terminal


def chat_stream_gen(sess, message, model, mark=None):
    """SSE producer for one chat request on `sess`.

    Contract (JAG-51): the caller has already appended the `user` message and
    passes `mark = session_mark(sess)` (the index captured just before it). Every
    exit path of this generator — reply, router error, warm-up error — leaves the
    session with a matching `assistant` message: a failed stream persists an
    explicit assistant error turn *and* emits the `error` SSE event, so a
    streamed request can never leave an orphan `user` message behind.
    """
    q = queue.Queue()
    done = {"flag": False}
    since = mark if mark is not None else max(0, session_mark(sess) - 1)

    def on_delta(channel, text):
        q.put("event: chat.delta\ndata: %s\n\n" % json.dumps(
            {"session": sess["id"], "channel": channel, "text": text}, ensure_ascii=False))
        publish("chat.delta", session=sess["id"], channel=channel, text=text)

    def worker():
        target = model

        def _emit(kind, **d):
            # graph/model events go to BOTH this chat stream and the feed, so
            # the WebUI can render the task graph live either way.
            q.put("event: %s\ndata: %s\n\n" % (kind, json.dumps(d, ensure_ascii=False)))
            publish(kind, **d)

        try:
            # v0.5.1 warm-up: resolve the target alias and, if it is cold, emit
            # `model.loading` and load it *before* the first token instead of
            # letting the client stall silently on the router's autoload.
            target = model or routing.pick("chat") or default_model()
            trace = RunTrace("chat", goal=message[:120], model=target)
            trace.span("chat.stream", session=sess["id"])
            q.put("event: chat.run\ndata: %s\n\n" % json.dumps(
                {"run_id": trace.id, "session": sess["id"]}))
            try:
                # JAG-71: only a LOCAL model has a warm-up (/models/load); remote
                # providers are called directly with no loading step.
                if target and _local_ref(target):
                    loaded, _m = model_loaded(target)
                    if not loaded:
                        ensure_model(target, on_event=_emit)
                # JAG-63: the graph is keyed by SESSION = the persistent task
                # list for this task. It survives every message, compaction and
                # restart; a NEW task (previous list fully done) starts fresh.
                # JAG-65: the todo list is authored INLINE by the model on its own
                # first response (harness action `write_todos`) — exactly like
                # Claude Code / Deep Agents. There is NO separate planner call:
                # that extra round-trip was dead air before any reply and fed the
                # model only the raw user message, so it parroted it back as steps.
                gkey = sess["id"]
                _existing = taskgraph.load(gkey)
                if _existing and taskgraph.all_done(_existing):
                    taskgraph.reset(gkey)  # previous task finished → new task
                chat_once(sess, message, target, on_delta, trace=trace, on_event=_emit)
                # JAG-76: guarantee a plan. The model normally authors the list
                # itself via `write_todos`; when it answers with prose only (which
                # left the app's 🧩 GRAFO panel empty — "non c'è nessun plan"), we
                # generate the graph from the request so the panel is never empty.
                # Skipped for one-liners (greetings/chit-chat) where a task list
                # would be noise.
                _g = taskgraph.load(gkey)
                if (not _g or not _g.get("nodes")) and len(str(message).split()) >= 4:
                    start_run_graph(gkey, message, gkey, routing.pick("planner"),
                                    on_event=_emit)
                # JAG-63: do NOT finalize the task list at the end of every
                # message — that forced every open node to 'done' and is exactly
                # why the list could never persist. Nodes close only with real
                # evidence (or explicitly by the user).
                trace.finish("done")
            except Exception as e:
                trace.finish("error")
                raise
        except Exception as e:
            # JAG-51: a failed stream must still leave a trace in the session —
            # persist the explicit assistant error turn, then tell the client.
            ensure_reply_persisted(sess, since, error=e, model=target)
            publish("chat.error", session=sess["id"], error=str(e))
            q.put("event: error\ndata: %s\n\n" % json.dumps(
                {"error": str(e), "session": sess["id"], "stored": True},
                ensure_ascii=False))
        finally:
            done["flag"] = True
            q.put(None)

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    # v0.6.1 (JAG-48): no keep-alive here — one `done`, then the generator is
    # exhausted and sse_response closes the connection.
    try:
        yield from sse_pump(q, t, idle_timeout=CHAT_STREAM_IDLE or None)
    finally:
        # JAG-51 safety net: if the producer is already gone without a reply
        # (e.g. the pump gave up on silence), still leave an assistant trace.
        # While the worker is alive it owns the persistence — never double-write.
        if not t.is_alive():
            ensure_reply_persisted(sess, since, error="stream ended without a reply")


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

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    yield from sse_pump(q, t, open_comment=": agent stream open\n\n",
                        idle_timeout=CHAT_STREAM_IDLE or None)


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


def context_status(session=None, model=None):
    """Token usage vs budget for a session (UI indicator + compaction evidence).

    v1.6.3 (JAG-55): `available` tells the UI whether these numbers describe a
    real session. Without one the payload used to look like a valid measurement
    and the indicator was misleading — clients render "n/d" when it is false.

    JAG-70: `tokens_used` is now the EFFECTIVE prompt size (system prompt +
    compacted transcript + pending message) — what is really sent to the model —
    not just the stored transcript, which under-reported by ~18x because the
    system prompt (tool registry, skills, task list) dominates.
    """
    return context_usage(session, model=model)


def providers_catalog():
    """Every provider + model the harness can use, with live usability (JAG-71)."""
    try:
        import providers
    except Exception as e:  # noqa: BLE001
        return {"providers": [], "error": str(e)}
    loaded = {m["alias"] for m in router_models() if m.get("loaded")}
    cat = providers.catalog(loaded_aliases=loaded)
    cat["router_models"] = router_models()  # backward compat for the old client
    return cat


def _tool_context():
    """The tool-registry block for the chat system prompt ("" if unavailable)."""
    try:
        return CHAT_TOOL_PROMPT + "\n" + api_v02.tool_context()
    except Exception:  # noqa: BLE001 — the registry must never break chat
        return ""


def _system_prompt(sess, tool_ctx=None):
    """Single source of truth for the chat system prompt (JAG-70).

    Used by BOTH the model call and the context indicator, so the measured `x`
    can never drift from what is actually sent.
    """
    if tool_ctx is None:
        tool_ctx = _tool_context()
    return (SYSTEM_PROMPT + "\n\n" + self_summary() + tool_ctx
            + "\n\n" + MEMORY_POLICY
            + "\n\nHarness state (your persistent task list):\n"
            + context_summary(session_id=(sess or {}).get("id")))


def context_usage(session_id=None, message=None, model=None):
    """Effective prompt tokens vs budget for the next turn (JAG-70).

    Counts what is REALLY sent: the system prompt (tool registry + skills +
    persistent task list), the compacted transcript and the pending user
    message. Returns the raw parts too, so the UI can explain the number.
    """
    import context_engine
    budget = context_budget(model)
    base = {"budget_tokens": budget, "session": session_id,
            "auto_compact_pct": AUTOCOMPACT_PCT}
    sess = load_session(session_id) if session_id else None
    if not sess:
        return {**base, "available": False, "messages": 0, "tokens_used": 0,
                "pct": 0.0, "over_threshold": False, "over_budget": False}
    sysp = _system_prompt(sess)
    # JAG-72: mirror `chat_once` EXACTLY — same model-aware budget and the same
    # memory-retrieval block — so the indicator's `x` equals the real prompt.
    msgs, stats = context_engine.build(
        sysp, sess.get("messages", []), message,
        budget_tokens=budget, retrieve_memory=True)
    used = int(stats.get("final_tokens") or 0)
    pct = round(used / budget * 100, 1) if budget else 0.0
    return {**base, "available": True,
            "messages": len(sess.get("messages", [])),
            "tokens_used": used, "pct": pct,
            "system_tokens": context_engine.count_tokens(sysp),
            "transcript_tokens": stats.get("compaction", {}).get("input_tokens", 0),
            "final_messages": stats.get("final_messages"),
            "over_threshold": pct >= AUTOCOMPACT_PCT,
            "over_budget": used > budget}


def prepare_session_for_turn(sess, model=None):
    """Auto-compact the stored transcript BEFORE a turn when it is over threshold.

    JAG-70: runs at the start of the request (before the JAG-51 `since` boundary
    is captured), so message indices stay valid. Extractive + local: no model
    call, so it can never stall a turn. Returns the (possibly reloaded) session.

    JAG-72: the threshold is evaluated against the SAME model-aware budget the
    turn will use, so a small-window remote model is compacted correctly.
    """
    try:
        usage = context_usage(sess["id"], model=model)
        if not usage.get("available") or not usage.get("over_threshold"):
            return sess
        stats = compact_session(sess["id"], usage["budget_tokens"])
        publish("context.auto_compact", session=sess["id"],
                pct=usage.get("pct"), threshold=AUTOCOMPACT_PCT,
                before=stats.get("input_tokens"), after=stats.get("output_tokens"),
                compacted=stats.get("compacted"), dropped=stats.get("dropped"))
        return load_session(sess["id"]) or sess
    except Exception:  # noqa: BLE001 — compaction must never break a turn
        return sess


def compact_session(session, budget_tokens=None):
    """Compact a session transcript in place under the token budget (v0.5).

    Uses the v0.3 extractive compaction; the newest messages stay verbatim,
    older ones are merged into a synthetic summary message. Returns stats.
    """
    import context_engine
    sess = load_session(session) if session else None
    if not sess:
        return {"error": "session not found: %s" % session}
    budget = int(budget_tokens) if budget_tokens else context_budget()
    msgs, stats = context_engine.compact(sess.get("messages", []), budget)
    sess["messages"] = msgs
    save_session(sess)
    stats.update({"session": session, "budget_tokens": budget,
                  "tokens_after": sum(context_engine.count_tokens(m.get("content", ""))
                                      for m in msgs)})
    publish("context.compact", **stats)
    return stats


def status_payload():
    plan, tasks = load_plan(), load_tasks()
    probe = sandbox.probe()
    return {
        "service": "sparkforge", "version": VERSION, "ts": round(time.time()),
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
    """HTTP surface of the harness.

    Chat session contract (v0.6.2, JAG-51) — `POST /api/chat` and
    `GET|POST /api/chat/stream`:

      `session` (optional, str): id of the transcript to talk to.
        * omitted/empty  -> a NEW session is created (`uuid4().hex[:12]`) and its
                            id is returned in the JSON body (`{"session": id}`)
                            or in the SSE payloads (`chat.user`/`chat.delta`/`done`);
        * unknown id     -> a new session is created with THAT exact id (an id
                            supplied by the client is never silently replaced);
        * existing id    -> the request is appended to that session's `messages`.

      Every request persists exactly two messages on that session: one `user`
      turn and one `assistant` turn — the reply, or an explicit error turn
      (`error:true` + `error_detail`) when the router call failed or returned
      nothing. After N requests the session holds exactly 2N messages and never
      ends on an orphan `user` turn. See `ensure_reply_persisted` and README
      § "session parameter contract".
    """

    server_version = "SparkForge/" + VERSION

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
        if path == "/api/self":
            return self._send(200, self_knowledge())
        if path == "/api/context":
            return self._send(200, context_status(qs.get("session"), qs.get("model")))
        if path == "/api/status":
            return self._send(200, status_payload())
        if path == "/api/models" or path == "/api/providers":
            return self._send(200, providers_catalog())
        if path == "/api/selfcheck":
            llm = qs.get("llm", "1").lower() not in ("0", "false", "no")
            return self._send(200, selfcheck_payload(
                host=getattr(self.server, "host", "127.0.0.1"),
                port=getattr(self.server, "port", 8790), llm_probe=llm))
        if path == "/api/feed":
            since = int(qs.get("since", 0))
            # keep-alive is a /api/feed-only privilege (v0.6.1, JAG-48)
            return sse_response(self, feed_gen(since), keepalive=True)
        if path == "/api/plan":
            return self._send(200, load_plan())
        if path == "/api/tasks":
            tasks = load_tasks()
            remaining = ["%s: %s" % (t["status"], t["title"]) for t in tasks.get("tasks", [])
                         if t.get("status") != "done"]
            return self._send(200, {**tasks, "remaining": remaining})
        if path == "/api/sessions":
            return self._send(200, {"sessions": list_sessions()})
        if path == "/api/sessions/new":
            sess = get_or_create_session(None, qs.get("title"))
            publish("session.created", session=sess["id"], title=sess["title"])
            return self._send(200, sess)
        if path == "/api/history":
            sid = qs.get("session")
            sess = load_session(sid) if sid else None
            if not sess:
                return self._send(404, {"error": "session not found"})
            return self._send(200, sess)
        if path == "/api/chat/stream":
            # SSE chat. Session contract: see the Handler docstring (JAG-51).
            sid = qs.get("session")
            message = qs.get("message", "")
            if not message:
                return self._send(400, {"error": "message required"})
            sess = get_or_create_session(sid)
            sess = prepare_session_for_turn(sess, qs.get("model"))  # JAG-70: auto-compact @75%
            mark = session_mark(sess)  # JAG-51: boundary of this request
            append_message(sess, "user", message)
            publish("chat.user", session=sess["id"], text=message)
            return sse_response(self, chat_stream_gen(sess, message, qs.get("model"), mark))
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
            if len(parts) == 4 and parts[3] == "graph":
                # v0.6: the run's task graph (linked to run_id + session_id)
                g = taskgraph.load(parts[2])
                return self._send(200, taskgraph.public(g)) if g else \
                    self._send(404, {"error": "graph not found for run"})
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
            # One-shot chat. Session contract: see the Handler docstring (JAG-51).
            message = body.get("message", "")
            if not message:
                return self._send(400, {"error": "message required"})
            sess = get_or_create_session(body.get("session"))
            sess = prepare_session_for_turn(sess, body.get("model"))  # JAG-70: auto-compact @75%
            mark = session_mark(sess)  # JAG-51: boundary of this request
            append_message(sess, "user", message)
            publish("chat.user", session=sess["id"], text=message)
            trace = None
            try:
                trace = RunTrace("chat", goal=message[:120], model=body.get("model"))
                trace.span("chat.once", session=sess["id"])
                # v0.6 first action: model-generated write_todos → per-run graph.
                # JAG-76: key the graph by the SESSION (same key as
                # `/api/chat/stream`), so every client that binds the panel to the
                # session finds it. Keying it by the ephemeral trace id made the
                # two chat paths disagree and the panel look empty.
                start_run_graph(sess["id"], message, sess["id"], routing.pick("planner"))
                reply, model = chat_once(sess, message, body.get("model"), trace=trace)
            except Exception as e:  # noqa: BLE001
                # JAG-51: persist an explicit assistant error turn *before* the
                # 502 — the user message must never stay orphaned.
                ensure_reply_persisted(sess, mark, error=e, model=body.get("model"))
                publish("chat.error", session=sess["id"], error=str(e))
                if trace:
                    trace.finish("error")
                return self._send(502, {"error": "router call failed: %s" % e,
                                        "session": sess["id"],
                                        "run_id": getattr(trace, "id", None),
                                        "stored_error": True})
            finish_run_graph(sess["id"], sess["id"], message)
            trace.model = model
            trace.finish("done")
            return self._send(200, {"session": sess["id"], "model": model, "run_id": trace.id,
                                    "reply": reply["content"], "reasoning": reply.get("reasoning"),
                                    "messages": len(sess["messages"]),
                                    "error": bool(reply.get("error"))})
        if path == "/api/chat/stream":
            # v0.5.1: POST alias of GET /api/chat/stream (mobile clients prefer
            # a JSON body over query params). Same SSE contract.
            message = body.get("message") or qs.get("message", "")
            if not message:
                return self._send(400, {"error": "message required"})
            sess = get_or_create_session(body.get("session") or qs.get("session"))
            sess = prepare_session_for_turn(sess, body.get("model") or qs.get("model"))  # JAG-70: auto-compact @75%
            mark = session_mark(sess)  # JAG-51: boundary of this request
            append_message(sess, "user", message)
            publish("chat.user", session=sess["id"], text=message)
            return sse_response(self, chat_stream_gen(
                sess, message, body.get("model") or qs.get("model"), mark))
        if path == "/api/model/ensure":
            alias = body.get("model") or qs.get("model") or \
                routing.pick("chat") or default_model()
            if not alias:
                return self._send(503, {"error": "no router model available"})
            res = ensure_model(alias, on_event=lambda k, **d: publish(k, **d))
            return self._send(200 if res.get("loaded") else 502, res)
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
        if path.startswith("/api/runs/") and path.endswith("/graph/nodes"):
            # v0.6: add/cancel node + incremental re-plan on a run's graph
            run_id = path[len("/api/runs/"):-len("/graph/nodes")].strip("/")
            payload, err, code = graph_post(run_id, body)
            return self._send(code, err if err else payload)
        if path.startswith("/api/sessions/") and path.endswith("/graph/reset"):
            # JAG-63: only the user clears the persistent task list (new task).
            sess_id = path[len("/api/sessions/"):-len("/graph/reset")].strip("/")
            return self._send(200, taskgraph.reset(sess_id))
        if path == "/api/context/compact":
            res = compact_session(body.get("session"), body.get("budget_tokens"))
            return self._send(200 if "error" not in res else 404, res)
        if path == "/api/sessions":
            sess = get_or_create_session(None, body.get("title"))
            publish("session.created", session=sess["id"], title=sess["title"])
            return self._send(200, sess)
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

    # ---- DELETE ----
    def do_DELETE(self):
        path, qs = self._query()
        if not check_auth(self.headers, qs):
            return self._send(401, {"error": "unauthorized"})
        if api_v02.handle(self, "DELETE", path, qs, None):
            return
        if path.startswith("/api/sessions/"):
            sid = path[len("/api/sessions/"):]
            fpath = os.path.join(SESSIONS_DIR, sid + ".json")
            if "/" in sid or ".." in sid or not os.path.isfile(fpath):
                return self._send(404, {"error": "session not found"})
            os.unlink(fpath)
            publish("session.deleted", session=sid)
            return self._send(200, {"ok": True, "deleted": sid})
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
    try:
        import providers
        providers.load_env()
        providers.warm()  # JAG-72: fetch remote model windows off the request path
    except Exception:  # noqa: BLE001 — provider metadata is optional
        pass
    publish("service.start", host=args.host, port=args.port, router=ROUTER_BASE)
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.host, server.port = args.host, args.port
    print("SparkForge v%s on http://%s:%d  (router: %s)" % (
        VERSION, args.host, args.port, ROUTER_BASE))
    server.serve_forever()


if __name__ == "__main__":
    main()
