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
import select
import socket
import threading
import time
import urllib.error
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import api_v02  # v0.2 surface: tool registry, approvals, HITL control, MCP
from . import approvals
from . import osutil
from . import otel_tracing  # v0.4: OpenTelemetry spans + fallback local spans
from . import registry
from . import routing  # v0.3: role-based model selection + fallback chain
from . import sandbox
from . import taskgraph  # v0.6: per-run LLM task graph (write_todos, live, interactive)

# JAG-370: mechanical split of this module. The optional beta hooks, the SSE
# plumbing / think coalescer, and the prose-tolerant text helpers now live in
# bridge / sse / textkit and are re-exported here, so every existing reference
# (`server.sse_pump`, `server.extract_json`, `server.ThinkCoalescer`, ...) keeps
# working unchanged.
from .bridge import _orbit_handle, _orbit_page
from .events import (DB_PATH, EVENTS_KEEP, MAX_FEED_EVENTS, PRUNE_BATCH,
                     PRUNE_INTERVAL_S, _ACTIVE_CHAT, _ACTIVE_CHAT_LOCK, _TURN_LOCKS,
                     _TURN_LOCKS_GUARD, _db_lock, _feed, _sse_queues, db, events_since,
                     feed_seq, prune_events, publish, query_events,
                     _start_event_pruning, _turn_lock, turn_begin, turn_end)
from .keys import ENV_FILE, KNOWN_ENV_KEYS, keys_status, reveal_key, set_key
from .sse import (CHAT_THINK_FLUSH_S, CHAT_THINK_LIVE_CAP, ThinkCoalescer,
                  sse_response, sse_pump)
from .textkit import extract_json, strip_think
from .tracing import (MODEL_PRICES, RunTrace, _REAL_CACHED_TOKENS, _REAL_PROMPT_TOKENS,
                      count_tokens, get_run_trace, runs_summary)
from .voice import (SHERPA_TTS_MODEL, WHISPER_BIN, WHISPER_MODEL, voice_status,
                    voice_stt, voice_tts)

from .paths import REPO_ROOT as REPO
DATA_DIR = os.path.join(REPO, "data")
# Session store. Overridable so tests/CI can run against a scratch directory
# (`SPARKFORGE_SESSIONS_DIR`) without touching the live transcripts.
SESSIONS_DIR = os.environ.get("SPARKFORGE_SESSIONS_DIR") or os.path.join(DATA_DIR, "sessions")
# JAG-316: persisted high-water mark for session job labels (monotonic counter).
_JOBSEQ_FILE = os.path.join(SESSIONS_DIR, ".jobseq")
WEBUI_DIR = os.path.join(REPO, "webui")

# The optional "Bridge" (former "Orbit") beta hooks moved to `bridge.py` (JAG-370).

# Static assets for the WebUI (vendored editor libs, css, images). Served
# read-only from webui/assets with an extension whitelist so a crafted path can
# never reach outside the assets root.
ASSET_EXTS = {".js", ".mjs", ".css", ".map", ".json", ".svg", ".png", ".jpg",
              ".jpeg", ".webp", ".gif", ".ico", ".woff2"}
ASSET_CTYPES = {
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".map": "application/json",
    ".json": "application/json",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".ico": "image/x-icon",
    ".woff2": "font/woff2",
}

ROUTER_BASE = os.environ.get("SPARKFORGE_ROUTER", "http://127.0.0.1:8080")
# JAG-372: MAX_FEED_EVENTS moved to events.py (imported above).
# JAG-208 (v208): cap the request body we buffer (memory-DoS guard). Larger
# bodies are drained, not allocated; the endpoint then sees an empty body.
MAX_BODY_BYTES = int(os.environ.get("SPARKFORGE_MAX_BODY", str(8 * 1024 * 1024)))
# JAG-295-fix: /api/feed must never replay the whole durable log (it can hold
# millions of rows). A live tail only needs the newest window.
FEED_REPLAY_MAX = int(os.environ.get("SPARKFORGE_FEED_REPLAY", "300"))
STORE_LOCK = threading.RLock()

VERSION = "1.0.0"
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
# JAG-370: the think-coalescing constants + ThinkCoalescer moved to `sse.py`
# (imported above, so `server.CHAT_THINK_FLUSH_S` and friends still resolve).

# JAG-372: the durable event log (sqlite) moved to `events.py` (imported above).


# JAG-372: the live SSE feed, publish(), turn locks and event queries moved to
# `events.py` (imported above).


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
    # JAG-201: a UNIQUE temp name per write. A fixed "<path>.tmp" collides when
    # two threads write the same file at once: the first os.replace() renames the
    # tmp away, so the second fails with FileNotFoundError — which used to escape
    # do_POST and drop the whole request (connection closed, turn lost).
    tmp = "%s.%s.tmp" % (path, uuid.uuid4().hex)
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(obj, f, indent=2, ensure_ascii=False)
        os.replace(tmp, path)
    except Exception:
        try:
            if os.path.exists(tmp):
                os.unlink(tmp)
        except OSError:
            pass
        raise


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


_SID_RE = re.compile(r"^[A-Za-z0-9_.-]{1,120}$")


def _valid_sid(sid):
    """A session id becomes a FILE name, so it must be a plain token (JAG-230).

    Ids arrive straight from the client (query string / JSON body). Anything
    with a path separator, a `..` segment or a non-string type is a traversal /
    type-confusion attempt and must never reach the filesystem.
    """
    return (isinstance(sid, str) and ".." not in sid
            and _SID_RE.match(sid) is not None)


def load_session(sid):
    if not _valid_sid(sid):
        return None
    return _read_json(os.path.join(SESSIONS_DIR, sid + ".json"), None)


# JAG-222: a session deleted WHILE its turn is running used to be RESURRECTED —
# the (not-aborted) worker persisted the final reply and recreated the file. A
# tombstone makes the write a no-op until the id is deliberately re-created.
# JAG-315: the tombstone is now PERSISTED (`.deleted`, deliberately not `*.json`
# so `list_sessions` never reads it as a session) and survives a restart; and
# `get_or_create_session` no longer silently resurrects a deleted id — a chat or
# attach that still references it gets a FRESH session instead.
_DELETED_SESSIONS = set()
_deleted_lock = threading.Lock()
_TOMBSTONE_FILE = os.path.join(SESSIONS_DIR, ".deleted")


def _load_tombstones():
    """Reload the durable deleted-session ids (a missing file is fine)."""
    try:
        with open(_TOMBSTONE_FILE, encoding="utf-8") as f:
            for line in f:
                sid = line.strip()
                if sid and _valid_sid(sid):
                    _DELETED_SESSIONS.add(sid)
    except (FileNotFoundError, OSError):
        pass


def _persist_tombstones():
    """Write the deleted-session ids atomically so a restart cannot forget them."""
    tmp = "%s.%s.tmp" % (_TOMBSTONE_FILE, os.getpid())
    try:
        os.makedirs(SESSIONS_DIR, exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            for sid in sorted(_DELETED_SESSIONS):
                f.write(sid + "\n")
        os.replace(tmp, _TOMBSTONE_FILE)
    except OSError:
        pass


_load_tombstones()


def save_session(sess):
    sid = sess.get("id")
    if not _valid_sid(sid):
        return  # JAG-230: never write a transcript to a path from an unsafe id
    with _deleted_lock:
        if sid in _DELETED_SESSIONS:
            return  # JAG-222: the session was deleted — never resurrect it
    _write_json(os.path.join(SESSIONS_DIR, sid + ".json"), sess)


def _purge_session_artifacts(sid):
    """JAG-179: delete EVERY per-session artifact, not just the transcript.

    A session owns four files, all keyed by the session id: the transcript
    (`data/sessions/<sid>.json`), its task graph (`data/graphs/<sid>.json`), its
    run metrics (`data/runs/<sid>.json`) and its edit journal
    (`data/edits/<sid>.json`). The delete button only removed the transcript, so
    graphs/runs/edits piled up as orphans (586 graph files for 76 sessions was
    exactly this leak). This also sweeps the `.bak-*` / `.reset-*` backups.
    """
    import glob
    if not _valid_sid(sid):
        return []  # JAG-230: a traversal-shaped id must never drive unlink()
    bases = [os.path.join(SESSIONS_DIR, sid + ".json")]
    try:
        bases.append(taskgraph._path(sid))
    except Exception:  # noqa: BLE001
        pass
    try:
        from . import runmetrics
        bases.append(runmetrics._path(sid))
    except Exception:  # noqa: BLE001
        pass
    try:
        from . import edits
        bases.append(edits._key_file(sid))
    except Exception:  # noqa: BLE001
        pass
    try:
        from . import roles as roles_mod
        bases.append(roles_mod.path_for(sid))   # JAG-314: the per-session ROLE.md
    except Exception:  # noqa: BLE001
        pass
    removed = []
    for base in bases:
        for f in glob.glob(glob.escape(base) + "*"):
            if f.endswith(".tmp"):
                continue
            try:
                os.unlink(f)
                removed.append(os.path.basename(f))
            except OSError:
                pass
    return removed


def _forget_session_runtime(sid):
    """JAG-302: drop the IN-MEMORY per-session entries on delete.

    JAG-179 purged the per-session FILES; the runtime maps keyed by session id
    (ctx-cache, turn lock, steer inbox) were never pruned, so they grew without
    bound across create/chat/delete cycles. The abort flag is only cleared when
    no turn is live — a running turn must still see it to stop.
    """
    _REAL_PROMPT_TOKENS.pop(sid, None)
    _REAL_CACHED_TOKENS.pop(sid, None)
    with _steer_lock:
        STEER_INBOX.pop(sid, None)
    with _TURN_LOCKS_GUARD:
        _TURN_LOCKS.pop(sid, None)
    with _ACTIVE_CHAT_LOCK:
        active = sid in _ACTIVE_CHAT
        _ACTIVE_CHAT.pop(sid, None)
    if not active:
        clear_abort(sid)


def clear_session(sid):
    """JAG-321: TRULY wipe a session's transcript — messages AND the side stores.

    The transcript the WebUI rebuilds on reload (`loadHistory`) is the merge of
    `messages` + `tool_cards` + `injects`. The `/clear` endpoint used to reset
    only `messages`, so the persisted tool cards and the harness entries
    (nudge / pivot / final / retry) came straight back — a "reset" left the chat
    visibly un-cleared. Wipe all three. Returns the session dict, or None when
    the id does not exist.
    """
    sess = load_session(sid)
    if not sess:
        return None
    push_abort(sid)
    sess["messages"] = []
    sess["tool_cards"] = []
    sess["injects"] = []
    save_session(sess)
    try:
        taskgraph.reset(sid)
    except Exception:  # noqa: BLE001 — a missing graph must not block the clear
        pass
    _forget_session_runtime(sid)
    publish("session.cleared", session=sid)
    return sess


def _rel_time(ts):
    """JAG-113: short relative label ('ora', '3 min', '15 h', '2 g') for a timestamp."""
    try:
        d = max(0.0, time.time() - float(ts))
    except (TypeError, ValueError):
        return ""
    if d < 60:
        return "ora"
    if d < 3600:
        return "%d min" % int(d // 60)
    if d < 86400:
        return "%d h" % int(d // 3600)
    return "%d g" % int(d // 86400)


def list_sessions():
    """JAG-113: sessions ordered by LAST USE (not creation), with an age label.

    JAG-323: each row carries a live ``running`` flag (from `_ACTIVE_CHAT`, the
    registry of turns in flight). Before, the main app's session list had NO such
    field, so a turn started HEADLESS — a job/routine turn on a session this
    browser did not open — was invisible: the session looked idle while a model
    burned GPU/tokens ("phantom run"). The flag is authoritative: every turn,
    whoever started it, registers in `_ACTIVE_CHAT` for its whole duration.
    """
    try:
        with _ACTIVE_CHAT_LOCK:
            _active = set(_ACTIVE_CHAT.keys())
    except Exception:  # noqa: BLE001
        _active = set()
    out = []
    try:
        for fn in sorted(os.listdir(SESSIONS_DIR)):
            if fn.endswith(".json"):
                s = _read_json(os.path.join(SESSIONS_DIR, fn), None)
                if not s:
                    continue
                msgs = s.get("messages", [])
                stamps = [s.get("created") or 0]
                if msgs:
                    stamps.append(msgs[-1].get("ts") or 0)
                cards = s.get("tool_cards") or []
                if cards:
                    stamps.append(cards[-1].get("ts") or 0)
                upd = max(stamps)
                out.append({"id": s["id"], "title": s.get("title", ""),
                            "created": s.get("created"), "updated": upd,
                            "age": _rel_time(upd), "messages": len(msgs),
                            "workspace": s.get("workspace"),
                            "job": s.get("job"),
                            "model": s.get("model"),
                            "running": s["id"] in _active})
    except FileNotFoundError:
        pass
    return sorted(out, key=lambda s: s.get("updated") or 0, reverse=True)


def _max_job():
    """JAG-169/JAG-316: highest session job number ever assigned.

    Must be MONOTONIC. The old version took the max only over LIVE session
    files, so deleting the session that held the top number let the next session
    reuse it — two different sessions could both be labelled ``J12`` over time,
    contradicting the "assigned once, never shifts" contract. We now also read a
    persisted high-water mark (``.jobseq``, deliberately not ``*.json`` so
    ``list_sessions`` never reads it as a session).
    """
    best = _read_seq()
    try:
        for fn in os.listdir(SESSIONS_DIR):
            if fn.endswith(".json"):
                s = _read_json(os.path.join(SESSIONS_DIR, fn), None) or {}
                try:
                    best = max(best, int(s.get("job") or 0))
                except (TypeError, ValueError):
                    pass
    except FileNotFoundError:
        pass
    return best


def _read_seq():
    try:
        with open(_JOBSEQ_FILE, encoding="utf-8") as f:
            return int(f.read().strip() or "0")
    except (FileNotFoundError, OSError, ValueError):
        return 0


def _write_seq(n):
    tmp = "%s.%s.tmp" % (_JOBSEQ_FILE, os.getpid())
    try:
        os.makedirs(SESSIONS_DIR, exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(str(int(n)))
        os.replace(tmp, _JOBSEQ_FILE)
    except OSError:
        pass


def ensure_job(sess):
    """JAG-169: a stable human id for a session — JX, X = job number.

    Assigned ONCE and persisted, so it never shifts when other sessions are
    deleted (unlike a position in the list). Returns True when it changed `sess`.
    """
    try:
        if int(sess.get("job") or 0) > 0:
            return False
    except (TypeError, ValueError):
        pass
    n = _max_job() + 1
    sess["job"] = n
    _write_seq(n)   # JAG-316: keep the counter monotonic across deletes
    return True


def ensure_session_workspace(sess, workspace=None):
    """JAG-117: every session is linked to a folder.

    Precedence: the explicit `workspace` argument, else the session's existing
    folder, else the global default. Returns True when it changed `sess`.
    """
    try:
        from . import rules as rules_mod
        want = rules_mod.check_dir(workspace) or sess.get("workspace") or rules_mod.get_workspace()
    except Exception:  # noqa: BLE001 — never break session loading
        want = workspace or sess.get("workspace") or REPO
    if want and sess.get("workspace") != want:
        sess["workspace"] = want
        return True
    return False


def backfill_session_workspaces():
    """JAG-117: pin a folder on any stored session that has none yet."""
    n = 0
    try:
        for fn in sorted(os.listdir(SESSIONS_DIR)):
            if not fn.endswith(".json"):
                continue
            s = _read_json(os.path.join(SESSIONS_DIR, fn), None)
            if s and ensure_session_workspace(s):
                save_session(s)
                n += 1
    except FileNotFoundError:
        pass
    return n


def backfill_jobs():
    """JAG-169: give every stored session a stable JX job id (assigned once)."""
    n = 0
    try:
        for fn in sorted(os.listdir(SESSIONS_DIR)):
            if not fn.endswith(".json"):
                continue
            s = _read_json(os.path.join(SESSIONS_DIR, fn), None)
            if s and ensure_job(s):
                save_session(s)
                n += 1
    except FileNotFoundError:
        pass
    return n


def _set_session_model(sid, model):
    """JAG-309: the single writer for a session's model AND its agent's model.

    An agent IS a session (agents.py: agent["session"] == sid), yet two
    independent writers let the two diverge: Orbit set only `agent["model"]`
    (which jobs read) while the composer set only `session["model"]` (which
    interactive chat reads). A3 showed a local model in Orbit but
    `deepseek-reasoner` in the composer. Unify them here: one model per entity,
    served by BOTH surfaces. `""` clears the choice; `None` leaves it untouched
    is NOT the contract here — this is an explicit write, so `""` clears.
    """
    sid = str(sid or "").strip()
    if not sid:
        return None
    ref = str(model or "")[:120]
    sess = load_session(sid)
    if sess is not None:
        sess["model"] = ref
        save_session(sess)
    try:
        from . import agents as agents_mod
        if agents_mod.REGISTRY.is_agent(sid):
            agents_mod.REGISTRY.designate(sid, model=ref)
    except Exception:  # noqa: BLE001 — the agent layer is optional for a session
        pass
    return ref


def reconcile_agent_models():
    """JAG-309: make every agent's model agree with its session's (agent wins).

    The agent model is the explicit per-agent choice made in Orbit and is what
    its jobs actually ran on, so it is authoritative; the session model is
    back-filled from it. When only the session has one, the agent inherits it.
    Idempotent; runs once at startup so pre-JAG-309 divergence heals.
    """
    try:
        from . import agents as agents_mod
        rows = agents_mod.REGISTRY.list().get("agents", [])
    except Exception:  # noqa: BLE001 — agents are optional
        return 0
    fixed = 0
    for a in rows:
        sid = a.get("session")
        if not sid:
            continue
        sess = load_session(sid)
        if sess is None:
            continue
        am = a.get("model") or ""
        sm = sess.get("model") or ""
        if am == sm:
            continue
        if am:
            sess["model"] = str(am)[:120]
            save_session(sess)
            fixed += 1
        else:
            try:
                agents_mod.REGISTRY.designate(sid, model=sm)
                fixed += 1
            except Exception:  # noqa: BLE001
                pass
    return fixed


def _remember_workspace(path):
    """JAG-126: remember the folder of the session being used, so the NEXT new
    session defaults to it. Never breaks the session if the write fails."""
    try:
        from . import rules as rules_mod
        rules_mod.remember_workspace(path)
    except Exception:  # noqa: BLE001
        pass


def _chat_workspace(sess):
    """JAG-127: the folder of the chatting session, for the tool approval gate
    (a file op outside it must be confirmed). Never raises."""
    try:
        from . import rules as rules_mod
        return rules_mod.resolve_workspace(sess)
    except Exception:  # noqa: BLE001
        return None


def get_or_create_session(sid, title=None, workspace=None):
    if sid and not _valid_sid(sid):
        sid = None  # JAG-230: refuse a traversal-shaped id, allocate a safe one
    if sid:
        with _deleted_lock:
            _gone = sid in _DELETED_SESSIONS
        if _gone:
            # JAG-315: a deleted session must never come back. A caller that still
            # holds the old id (a chat / attach from a stale tab) gets a FRESH one
            # rather than silently resurrecting the deleted transcript.
            sid = None
        else:
            s = load_session(sid)
            if s:
                changed = ensure_session_workspace(s, workspace)
                changed = ensure_job(s) or changed   # JAG-169: backfill a stable JX id
                if changed:
                    save_session(s)
                _remember_workspace(s.get("workspace"))
                return s
    sid = sid or uuid.uuid4().hex[:12]
    s = {"id": sid, "title": title or "session " + sid[:6],
         "created": round(time.time(), 3), "messages": []}
    ensure_session_workspace(s, workspace)
    ensure_job(s)                                # JAG-169: allocate JX on creation
    save_session(s)
    _remember_workspace(s.get("workspace"))
    return s


def append_message(sess, role, content, reasoning=None, meta=None):
    # JAG-238: the transcript must only ever hold STRING content. A client could
    # POST {"message": 123}; the int was persisted and later crashed /api/context
    # (`len(int)` -> dropped connection). Coerce at this single choke point so no
    # caller can poison the stored transcript.
    if not isinstance(content, str):
        content = "" if content is None else str(content)
    msg = {"role": role, "content": content, "ts": round(time.time(), 3)}
    if reasoning:
        msg["reasoning"] = reasoning
    if meta:
        msg.update(meta)
    sess["messages"].append(msg)
    save_session(sess)
    return msg


def persist_tool_card(sess, tool, ok, args=None, result="", error="",
                      exit_code=None, backend=None, node=None, think=None, after=None):
    """JAG-96: persist an inline tool card so cold-start UIs can rebuild it.

    Stored in `sess["tool_cards"]` — NOT in `messages` — so it never reaches the
    model prompt (`context_engine.build` only reads `messages`). `after` is the
    number of already-persisted messages the card follows, letting the WebUI and
    the mobile mirror interleave cards with the transcript on history reload.
    `node` (JAG-167) is the todo node id the card belongs to, so the in-chat tree
    can nest it under the right node on reload.

    JAG-192: `after` MUST be passed explicitly from the chat loop. During a turn
    the transcript lives in the local `msgs` list and is flushed into
    `sess["messages"]` only at the end, so `len(sess["messages"])` is frozen at
    the turn-start value — every card of a multi-step turn then collapsed onto
    the same boundary and a reload stacked the whole turn at the top instead of
    interleaving it (that is the "Ctrl+Shift+R reshuffles the chat" bug).
    `node` is coerced to its id so a caller that accidentally passes the node
    dict cannot poison the JSON with "[object Object]".
    """
    try:
        if isinstance(node, dict):
            node = node.get("id")
        args_str = args if isinstance(args, str) else json.dumps(args or {},
                                                                ensure_ascii=False)
        card = {
            "tool": str(tool),
            "ok": bool(ok),
            "args": args_str[:4000],
            "result": str(result or "")[:4000],
            "error": str(error or "")[:2000],
            "exit_code": exit_code,
            "backend": backend,
            "node": node,
            "think": (str(think)[:6000] if think else None),
            "after": (len(sess.get("messages", [])) if after is None else int(after)),
            "ts": round(time.time(), 3),
        }
        sess.setdefault("tool_cards", []).append(card)
        save_session(sess)
        return card
    except Exception:  # noqa: BLE001 — persisting a card must never break a turn
        return None


def persist_inject(sess, kind, text, node=None, after=None):
    """JAG-167: persist a harness→LLM injection so the chat can rebuild it on reload.

    Mirrors `persist_tool_card`: stored in `sess["injects"]` (never sent to the
    model), with `after` (message boundary) + `node` (the todo node it belongs to)
    + `ts`, so `loadHistory` re-nests it under the right node. JAG-192: `after`
    is passed explicitly by the chat loop (see persist_tool_card) and `node` is
    coerced to its id.
    """
    try:
        if isinstance(node, dict):
            node = node.get("id")
        rec = {"kind": str(kind or "inject"), "text": str(text or "")[:8000],
               "node": node,
               "after": (len(sess.get("messages", [])) if after is None else int(after)),
               "ts": round(time.time(), 3)}
        sess.setdefault("injects", []).append(rec)
        save_session(sess)
        return rec
    except Exception:  # noqa: BLE001 — persisting an inject must never break a turn
        return None


# JAG-113: the live tool card must show input + output (truncated), like the
# persisted one rebuilt on reload — the live SSE event used to carry neither.
TOOL_EVENT_MAX = int(os.environ.get("SPARKFORGE_TOOL_EVENT_MAX", "2000"))


def _trunc(text, n=None):
    """Truncate to <= n chars INCLUDING the '… troncati' suffix (JAG-113)."""
    s = text if isinstance(text, str) else json.dumps(text, ensure_ascii=False)
    n = n or TOOL_EVENT_MAX
    if len(s) <= n:
        return s
    keep = max(0, n - 48)
    return s[:keep] + "\n… [%d caratteri troncati]" % (len(s) - keep)


def _tool_event(tool, ok, args=None, output="", **extra):
    """Payload for a live tool card (args + truncated output + meta)."""
    args_s = args if isinstance(args, str) else json.dumps(args or {}, ensure_ascii=False)
    ev = {"tool": str(tool), "ok": bool(ok), "args": _trunc(args_s),
          "output": _trunc(output or "")}
    ev.update(extra)
    return ev


# JAG-371: the API-key management (ENV_FILE, KNOWN_ENV_KEYS, _env_file_upsert,
# set_key, reveal_key, keys_status) moved to `keys.py` (imported above).


# --- JAG-51 session contract: no request without a persisted answer ---------
ERROR_PREFIX = "⚠️ error: "


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


def reconcile_orphan_turns(session=None):
    """JAG-262: close turns left half-done by a hard restart.

    A systemd restart (SIGTERM) kills an in-flight chat turn; its `finally` never
    runs, so the session keeps a trailing `user` message with no reply and the
    WebUI shows it as if it were still working ("stuck"). At startup nothing can
    be in flight, so any session ending on a `user` turn is an orphan: close it
    with an explicit assistant notice (never silently dropped). Returns the count.

    `session` (JAG-263): restrict the sweep to one session id, so the agent can
    repair a single stuck session on demand via the `reconcile` tool.
    """
    fixed = 0
    if session:
        names = ([session + ".json"]
                 if os.path.exists(os.path.join(SESSIONS_DIR, session + ".json"))
                 else [])
    else:
        try:
            names = os.listdir(SESSIONS_DIR)
        except FileNotFoundError:
            return 0
    for fn in names:
        if not fn.endswith(".json"):
            continue
        sid = fn[:-5]
        # JAG-262b: a session with a LIVE turn has a trailing `user` message too
        # (the reply is persisted only at the end), so a blind sweep would corrupt
        # a working session. NEVER touch a session that currently owns a turn.
        if sid in _ACTIVE_CHAT:
            continue
        try:
            sess = load_session(sid)
        except Exception:  # noqa: BLE001
            continue
        msgs = (sess or {}).get("messages", [])
        if not msgs or msgs[-1].get("role") != "user":
            continue
        try:
            append_message(
                sess, "assistant",
                ERROR_PREFIX + "previous turn was interrupted by a service restart "
                "— send a new message to continue.",
                meta={"error": True, "error_detail": "interrupted-by-restart",
                      "interrupted": True})
            # also release progress left 'doing' by the killed turn, so the panel
            # does not show a phantom active step.
            try:
                from . import taskgraph
                g = taskgraph.load(sid)
                if g:
                    for n in list(g.get("nodes", [])):
                        if n.get("status") == "doing":
                            taskgraph.update_node(g, n["id"], status="todo")
            except Exception:  # noqa: BLE001
                pass
            publish("session.reconciled", session=sid, reason="orphan_user_turn")
            fixed += 1
        except Exception:  # noqa: BLE001 — recovery must never block startup
            continue
    return fixed


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
# JAG-99: after compaction the transcript is shrunk to this % of the budget, so
# the TOTAL prompt lands BELOW the trigger with headroom (no instant re-trigger).
AUTOCOMPACT_TARGET_PCT = float(os.environ.get(
    "SPARKFORGE_CONTEXT_TARGET_PCT", str(max(10.0, AUTOCOMPACT_PCT - 15.0))))
# JAG-102: the MANUAL "compact now" action must always reduce. It targets this
# fraction of the transcript's CURRENT size — using the full model budget made
# the button a no-op for any session under 100% (so it "did nothing").
COMPACT_FORCE_RATIO = float(os.environ.get("SPARKFORGE_COMPACT_FORCE_RATIO", "0.5"))
# JAG-110: how many newest turns the MANUAL "compact now" keeps verbatim. The
# automatic path keeps 8; the manual action is a deliberate shrink, so it keeps
# only this few — otherwise a short session (<=8 msgs) compacted nothing and the
# summarizer was never called (no GPU activity, "0 msgs compacted").
COMPACT_MANUAL_KEEP_RECENT = int(os.environ.get("SPARKFORGE_COMPACT_MANUAL_KEEP_RECENT", "2"))
# JAG-214: cap the transcript handed to the LLM summarizer. A session can be
# dominated by ONE huge paste; sending it whole to the summarizer would overflow
# the summarizer's own window and fail. Keep the head + tail (the summarizer only
# needs the gist), so the call always fits and the summary is still faithful.
SUMMARIZER_MAX_CHARS = int(os.environ.get("SPARKFORGE_SUMMARIZER_MAX_CHARS", "60000"))


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
    from . import context_engine
    # JAG-71: a provider model may declare its window (remote models have no
    # router meta); the live router roster is the fallback for local aliases.
    try:
        from . import providers
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
        from . import providers
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
        from . import providers
        resolved = providers.endpoint(model)
        if resolved:
            return resolved
    except Exception:  # noqa: BLE001 — the catalogue must never break chat
        pass
    return (ROUTER_BASE + "/v1/chat/completions",
            {"Content-Type": "application/json"}, model or "default")


# JAG-111: bound a single completion and cut a degenerate repetition loop, so a
# model stuck repeating itself cannot hang a run (ROUTER_IDLE_TIMEOUT only covers
# *silence*, not a continuous token stream).
# JAG-305: the llama.cpp router defaults to a 4096-token completion when the
# request omits `max_tokens`. A reasoning model spends most of that budget on its
# (hidden) thinking, so a long deliverable — a coordinator's synthesis, a big
# schema — was silently TRUNCATED mid-answer (observed on J2: completion_tokens
# pinned at 4096, think_chars 12k, answer cut mid-table). Send a generous, still
# bounded, cap by default so the model can finish; override with the env var
# (0 = omit and let the router decide, the old behaviour).
MAX_TOKENS = int(os.environ.get("SPARKFORGE_MAX_TOKENS", "16384"))
REPEAT_GUARD = os.environ.get("SPARKFORGE_REPEAT_GUARD", "1") not in ("0", "false", "False")
_REPEAT_MIN_PERIOD = int(os.environ.get("SPARKFORGE_REPEAT_MIN_PERIOD", "20"))
_REPEAT_MAX_PERIOD = int(os.environ.get("SPARKFORGE_REPEAT_MAX_PERIOD", "240"))
_REPEAT_LIMIT = int(os.environ.get("SPARKFORGE_REPEAT_LIMIT", "4"))


class _RepetitionGuard:
    """Detect a degenerate repetition loop in a streamed reply.

    Streaming chunks are tiny, so we watch the accumulated text: if the last
    `p*limit` characters are exactly `limit` copies of `text[-p:]` for some period
    `p` in [min_period, max_period], the model is looping and the stream must be
    cut. Blocks with too small an alphabet, or (under 48 chars) without a space,
    are ignored so code/tables/numbers never trip the guard.
    """

    def __init__(self, min_period=_REPEAT_MIN_PERIOD, max_period=_REPEAT_MAX_PERIOD,
                 limit=_REPEAT_LIMIT, max_scan=8000):
        self.min_period = max(4, int(min_period))
        self.max_period = max(self.min_period, int(max_period))
        self.limit = max(2, int(limit))
        self.max_scan = max_scan
        self.text = ""

    def feed(self, piece):
        """Append a streamed chunk; return True when a repetition loop is detected."""
        if not piece:
            return False
        self.text = (self.text + piece)[-self.max_scan:]
        t = self.text
        if len(t) < self.min_period * self.limit:
            return False
        maxp = min(self.max_period, len(t) // self.limit)
        for p in range(self.min_period, maxp + 1):
            blk = t[-p:]
            if len(set(blk.strip())) < 4:
                continue
            if " " not in blk and p < 48:
                continue
            if t[-(p * self.limit):] == blk * self.limit:
                return True
        return False


def _reasoning_effort():
    """JAG-281: the OpenAI-compatible `reasoning_effort` to attach, or None.

    OPT-IN via the Thinking-effort setting (data/tools.overlay.yaml): when it is
    disabled or unset this returns None, so the request body stays byte-identical
    to before and plain/local models that reject the field are never affected.
    """
    try:
        from . import registry as _reg
        r = _reg.load_config().get("reasoning") or {}
        if r.get("enabled"):
            eff = str(r.get("effort") or "").strip().lower()
            if eff in ("none", "minimal", "low", "medium", "high", "xhigh"):
                return eff
    except Exception:  # noqa: BLE001
        pass
    return None


def _completion_body(model_id, messages, stream, max_tokens=None):
    """Single place that builds the OpenAI-compatible request body (JAG-111)."""
    # JAG-167: strip harness-only metadata (e.g. the per-message `node` used to
    # rebuild the in-chat tree) so ONLY wire-valid fields reach the provider.
    clean = []
    for m in messages or []:
        if not isinstance(m, dict):
            continue
        cm = {"role": m.get("role", "user"), "content": m.get("content", "")}
        if m.get("name"):
            cm["name"] = m["name"]
        clean.append(cm)
    body = {"model": model_id, "messages": clean, "stream": bool(stream),
            "temperature": 0.7}
    if stream:
        body["stream_options"] = {"include_usage": True}
    if max_tokens:
        body["max_tokens"] = int(max_tokens)
    effort = _reasoning_effort()
    if effort:
        body["reasoning_effort"] = effort
    return body


# JAG-217: a provider whose host is UNREACHABLE must fail fast. A blackholed
# host (e.g. an offline Tailscale peer such as the `win:` provider) made
# urlopen block for the whole OS connect timeout before the fallback chain moved
# on — measured 140s for one chat turn, which looked exactly like a hang. A short
# TCP connect probe turns that into an immediate, clean failure so failover is
# near-instant (the chain's next model answers right away).
CONNECT_TIMEOUT = float(os.environ.get("SPARKFORGE_CONNECT_TIMEOUT", "3.0"))


def _reachable(url, timeout=None):
    """True if the endpoint's host:port accepts a TCP connection quickly."""
    try:
        from urllib.parse import urlsplit
        u = urlsplit(url)
        host = u.hostname
        if not host:
            return True
        port = u.port or (443 if u.scheme == "https" else 80)
        sock = socket.create_connection((host, port),
                                        timeout=timeout or CONNECT_TIMEOUT)
        sock.close()
        return True
    except OSError:
        return False


def _router_stream(messages, model, on_delta, timeout=300, usage=None, guard=None,
                   cancel=None):
    """POST /chat/completions with stream=true; feed deltas to on_delta.

    on_delta(channel, text) with channel in {think, answer}. Returns the
    full (answer, think) pair. Falls back to a non-streaming call.

    JAG-86: when `usage` (a dict) is passed we ask the OpenAI-compatible server
    for its real token accounting (`stream_options.include_usage`) and copy the
    final `usage` object into it — so the ctx meter can show the model's own
    prompt_tokens instead of the ~4-chars/token proxy.
    """
    url, headers, model_id = _chat_endpoint(model)
    # JAG-217: fail fast on an UNREACHABLE provider, BEFORE the blocking open, so
    # neither the streaming attempt nor the non-streaming fallback (inside the
    # `except` below) can hang on a blackholed host; the caller moves on at once.
    if not _reachable(url):
        raise urllib.error.URLError("provider unreachable: %s" % url)
    body = json.dumps(_completion_body(model_id, messages, True,
                                       MAX_TOKENS or None)).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=headers)
    answer, think = [], []
    rg = _RepetitionGuard() if (guard if guard is not None else REPEAT_GUARD) else None
    try:
        with _open_with_retry(req, timeout) as resp:
            if ROUTER_IDLE_TIMEOUT > 0:
                # v0.6.1 (JAG-48): mid-stream silence must not hang the run.
                _set_read_idle(resp, ROUTER_IDLE_TIMEOUT)
            # JAG-197: poll in short slices so `cancel` (the Stop button) is
            # honoured even while the router is SILENT. Before this, cancel was
            # only checked when a new line arrived, so during a long silent gap
            # (model "thinking", or a busy single-slot router) Stop did nothing
            # until ROUTER_IDLE_TIMEOUT elapsed — the turn hung and starved every
            # later request on a shared router.
            _poll = 0.5 if ROUTER_IDLE_TIMEOUT > 0 else None
            try:
                _sock = resp.fp.raw._sock
            except Exception:  # noqa: BLE001
                _sock = None
            _last = time.time()
            while True:
                if cancel is not None and cancel():
                    # JAG-129D: Stop kills the in-flight generation (closing the
                    # socket at the end of the `with` block interrupts the router-side inference).
                    break
                if _sock is not None:
                    try:
                        _r, _, _ = select.select([_sock], [], [], _poll)
                    except Exception:  # noqa: BLE001
                        _r = [True]
                    if not _r:
                        if ROUTER_IDLE_TIMEOUT > 0 and \
                                (time.time() - _last) >= ROUTER_IDLE_TIMEOUT:
                            raise socket.timeout("router idle")
                        continue
                raw = resp.readline()
                if not raw:
                    break
                _last = time.time()
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
                if usage is not None and isinstance(chunk.get("usage"), dict):
                    usage.update(chunk["usage"])
                delta = ((chunk.get("choices") or [{}])[0].get("delta")) or {}
                rc = delta.get("reasoning_content")
                c = delta.get("content")
                piece = (rc or "") + (c or "")
                if rg is not None and piece and rg.feed(piece):
                    publish("model.runaway", model=model_id, chars=len(rg.text))
                    break
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
        # JAG-197: an abort must never enter the blocking non-streaming fallback.
        # That fallback re-issues the WHOLE generation, ignores Stop, and can hold
        # the run — and a single-slot router — hostage for the full timeout.
        if cancel is not None and cancel():
            return "".join(answer), "".join(think)
        if answer or think:
            return "".join(answer), "".join(think)
        # non-streaming fallback
        body = json.dumps(_completion_body(model_id, messages, False,
                                           MAX_TOKENS or None)).encode("utf-8")
        req = urllib.request.Request(url, data=body, headers=headers)
        with _open_with_retry(req, timeout) as resp:
            data = json.loads(resp.read().decode("utf-8") or "{}")
        if usage is not None and isinstance(data.get("usage"), dict):
            usage.update(data["usage"])
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


def stream_with_fallback(messages, model, role, on_delta, timeout=300, usage=None,
                         guard=None, cancel=None):
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
            if usage is not None:
                usage.clear()  # a failed attempt must not leave stale numbers
            answer, think = _router_stream(messages, alias, on_delta, timeout, usage,
                                           guard, cancel)
            if i > 0:
                publish("model.fallback", role=role, from_model=chain[0],
                        to_model=alias)
            return answer, think, alias
        except Exception as e:  # noqa: BLE001
            last_err = e
            publish("model.failover", role=role, failed=alias,
                    next_model=chain[i + 1] if i + 1 < len(chain) else None)
    raise last_err if last_err else RuntimeError("no router model available")


# JAG-374: RunTrace + token/cost accounting moved to `tracing.py` (imported above).


# ------------------------------------------------------------- agent core ----

SYSTEM_PROMPT = (
    "You are SparkForge, the reasoning core of a frontier-style agent harness "
    "running locally on a DGX Spark (GB10, ARM64, unified memory) behind a "
    "llama.cpp router. Be direct, concrete and useful. When asked to plan or "
    "act, produce compact, actionable output."
)

# JAG-159: the PMCP gateway block is injected only when a `pmcp` MCP client is
# actually configured — a clone without it must not advertise tools it lacks.
PMCP_PROMPT = (
    "\n\n## MCP gateway (PMCP)\n"
    "Besides your native tools you can reach ~140 downstream MCP servers through "
    "the PMCP gateway (tools named `pmcp__gateway.*`). To use a capability you do "
    "not have natively:\n"
    "1. `pmcp__gateway.catalog_search` {query} - find the server/tool for a task.\n"
    "2. `pmcp__gateway.describe` {tool_id} - get the exact arguments.\n"
    "3. `pmcp__gateway.invoke` {tool_id:\"server::tool\", arguments:{...}} - run it.\n"
    "Downstream servers are lazy: `invoke` starts them on its own, so NEVER call "
    "`connect_server` first and never assume a server is offline. `invoke` is "
    "approval-gated, so prefer your native tools/skills for local work and use the "
    "gateway only when a capability is genuinely missing. A tool_id is prefixed by "
    "the server name, e.g. `core-time::get_current_time`."
)


def system_prompt():
    """Base system prompt, plus the PMCP block only if a `pmcp` client exists."""
    try:
        from . import mcp_client
        if "pmcp" in (mcp_client.get_manager().status().get("clients") or {}):
            return SYSTEM_PROMPT + PMCP_PROMPT
    except Exception:  # noqa: BLE001 — never break the prompt
        pass
    return SYSTEM_PROMPT

# JAG-114/125: standing rules — global (user) + project (workspace), AGENTS.md-style.
# The actual file paths are rendered by rules.rules_prompt_block (below), so the
# model always knows WHERE its instructions live and can read/edit them.
RULES_POLICY = (
    "## Rules (global + project)\n"
    "Your standing rules are FILES on disk (paths given below): a GLOBAL file for "
    "every project and a PROJECT file for the current workspace, each also "
    "loading its scope's AGENTS.md (additive, not a fallback). GLOBAL rules come "
    "from your user config; PROJECT rules override global ones on conflict. "
    "Follow them; if a rule conflicts with the "
    "user's explicit request in this turn, say so before proceeding."
)


def rules_context(sess=None, ws=None):
    """JAG-114/115/125: rules block for the prompt, ALWAYS carrying the paths.

    `ws` (or the session's own workspace) selects the project; without either the
    global default workspace is used. Uses `rules_prompt_block` (never empty) so
    the model always sees where the global/project rules and their AGENTS.md
    additions (also loaded, additive) live — not just their text.
    """
    try:
        from . import rules as rules_mod
        return rules_mod.rules_prompt_block(ws=ws or rules_mod.resolve_workspace(sess))
    except Exception:  # noqa: BLE001 — rules must never break a prompt
        return ""

PLANNER_PROMPT = (
    "You are the planner module of the SparkForge harness. Break the goal into "
    "3-7 concrete strategy steps. Respond with ONLY a JSON array, each item "
    '{"title": "<short step>", "detail": "<one sentence>"}'
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
    "- CORE (always visible): keep a compact, living CORE block of durable facts "
    "— user preferences, project conventions, key decisions. Read it with "
    "memory{action:'core'} and REWRITE it with memory{action:'set_core', "
    "content:'...'} whenever it changes; it is injected into every prompt, so "
    "keep it short and current.\n"
    "Never store ephemeral chatter, and never store secrets."
)

# JAG-79: the model knew the `skills` TOOL existed but the system prompt never
# told it WHICH skills are installed, so it never used them (e.g. superpowers,
# brainstorming, tdd). We now inject the live skills list + this directive.
# JAG-80: how long a chat turn waits for a human approval before moving on.
# The gate's own timeout is 300s (approvals.timeout_secs) — waiting that long in
# the chat stream was experienced as "si blocca" and let mobile NAT kill the SSE.
CHAT_APPROVAL_WAIT = 30

# JAG-127b: mid-run steering. A message the user types while a turn is still
# streaming (or a queued message the app flushes) is dropped here and injected
# as a user message at the next loop boundary — the modern-IDE "steer" behaviour,
# with no second turn and no second SSE stream.
STEER_INBOX = {}
_steer_lock = threading.Lock()


def push_steer(sess_id, text):
    """Queue a steering message for a running session. Returns the new depth."""
    text = str(text or "").strip()
    if not sess_id or not text:
        return 0
    with _steer_lock:
        q = STEER_INBOX.setdefault(sess_id, [])
        q.append(text)
        return len(q)


def drain_steer(sess_id):
    """Pop all steering messages for a session (called per loop iteration)."""
    with _steer_lock:
        # JAG-302: pop the key instead of re-inserting an empty list — the old
        # `STEER_INBOX[sess_id] = []` left a permanent empty entry for every
        # session that ever ran a turn (an unbounded dict).
        return STEER_INBOX.pop(sess_id, [])


def has_steer(sess_id):
    """JAG-129A: True when there is at least one steering message queued."""
    with _steer_lock:
        return bool(STEER_INBOX.get(sess_id))


# JAG-129A: abort of an in-flight chat turn (distinct from steer: steer
# redirects, abort stops). The loop checks the flag on every iteration.
ABORT_INBOX = set()
_abort_lock = threading.Lock()


def push_abort(sess_id):
    if not sess_id:
        return False
    with _abort_lock:
        ABORT_INBOX.add(sess_id)
    return True


def _is_aborted(sess_id):
    with _abort_lock:
        return sess_id in ABORT_INBOX


def clear_abort(sess_id):
    with _abort_lock:
        ABORT_INBOX.discard(sess_id)

SKILLS_POLICY = (
    "Skills: you have an installed skill library — the SKILLS list below is "
    "live and includes all symlinked distributions. Before solving a task, SCAN "
    "it: if a skill matches (e.g. using-superpowers, brainstorming, "
    "writing-plans, tdd, systematic-debugging, research, mcp-builder, "
    "code-review), LOAD it with the `skills` tool "
    '({\"action\":\"read\",\"name\":\"<name>\"}) and FOLLOW its instructions '
    "step by step instead of improvising. Use {\"action\":\"list\"} for the "
    "full list with descriptions; if the list is long or truncated, SEARCH it "
    'with {"action":"search","query":"..."} and read the best match.'
)


def self_summary():
    """Compact self-knowledge block injected into the system prompt (v0.5)."""
    return (
        "Self-knowledge: you are SparkForge v0.6, a local agent harness installed "
        "at the repo path %s on this DGX Spark. Data dir: %s. Tool policy: "
        "config/tools.yaml; model routing: config/routing.yaml; external MCP "
        "servers: config/mcp_clients.yaml (add a stdio command or HTTP url entry, "
        "tools appear as <client>__<tool>; then reload via POST /api/tools or "
        "restart with %s, unit file "
        "deploy/sparkforge.service, port 8790). Skills: the `skills` tool lists and "
        "reads agent skills from skills/<category>/<name>/SKILL.md. Harness-"
        "native tools: "
        "registry.TOOL_SCHEMAS + tools.py. Full self report: GET /api/self or "
        "the `self` tool."
    ) % (REPO, DATA_DIR, osutil.service_hint())


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
                    "restart_cmd": osutil.service_hint()},
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
            "Apply with POST /api/tools (reload) or restart: %s."
        ) % osutil.service_hint(),
    }
    try:
        from . import skills as skills_mod
        sk = skills_mod.list_skills()
        info["skills"] = {"dir": info["skills_dir"], "count": len(sk),
                          "categories": sorted({s["category"] for s in sk})}
    except Exception as e:  # noqa: BLE001
        info["skills"] = {"error": str(e)}
    try:
        if osutil.IS_POSIX:
            out = sp.run(["systemctl", "--user", "is-active", "sparkforge.service"],
                         capture_output=True, text=True, timeout=4).stdout.strip()
            info["service"]["active"] = out or "unknown"
        else:
            info["service"]["active"] = "n/a (no systemd on this host)"
    except Exception:
        info["service"]["active"] = "unknown"
    return info


def context_summary(session_id=None, graph_key=None):
    """Harness state injected into EVERY prompt.

    JAG-63: the persistent task list (the graph) is the single TODO the model
    owns. It is re-injected on every turn, so the model never forgets it across
    compaction or restarts. The old parallel `tasks.json` board is no longer
    injected here (it was the source of the "graph vs todo" confusion).

    JAG-276: `state_block` wraps this and injects it into the CURRENT user turn
    (not the system prompt) so the system prompt + transcript stay cache-stable.
    """
    lines = []
    key = graph_key or session_id
    g = None
    if key:
        try:
            g = taskgraph.load(key)
        except Exception:  # noqa: BLE001 — context must never break a turn
            g = None
    if g:
        todos = taskgraph.render_todos(g, compact=True)
        if todos:
            lines.append(todos)
    return "\n".join(lines) if lines else "(no task list yet)"


def state_block(session_id=None, graph_key=None):
    """The live task list, to inject INTO the current USER turn (JAG-276).

    JAG-276 (cache): this block used to be the LAST section of the SYSTEM prompt.
    Any task-list change therefore invalidated the KV prefix FROM THERE ON — i.e.
    the whole transcript had to be recomputed every turn. Putting it in the LAST
    user message (which changes every turn anyway) keeps the system prompt + the
    committed transcript byte-stable, so llama.cpp reuses the prefix cache. This is
    the Claude-Code pattern. Mirrored by `assemble_turn` and `context_usage`.
    """
    return ("Harness state (your persistent task list):\n"
            + context_summary(session_id=session_id, graph_key=graph_key))


def start_run_graph(run_id, goal, session_id=None, model=None, on_event=None,
                    cancel=None):
    """v0.6 — first action of a run: model-generated write_todos → live graph.

    The graph is bound to run_id + session_id and every node lands on the feed as
    a `graph.node.added` event the moment the model emits it. `cancel` (JAG-197)
    makes the planner call abortable.
    """
    try:
        return taskgraph.generate_from_model(run_id, goal, session_id=session_id,
                                             model=model, on_event=on_event,
                                             cancel=cancel)
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
        # JAG-215: an OPERATOR "add node" on a session that has no graph yet must
        # CREATE it. The WebUI Plan panel's "+" was silently writing to the dead
        # legacy /api/tasks board for a fresh session, so the node vanished.
        # Other actions still require an existing graph.
        if action in ("add", "node"):
            g = taskgraph.ensure(run_id)
        else:
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
            # JAG-274: announce on the feed so the WebUI can refresh the Plan panel
            # AND show the replan in the chat. We deliberately do NOT inject a chat
            # turn here (the operator chose "update + show only"): the model already
            # owns replan/continue as its OWN tools (replan_todos + the keepgoing
            # loop), and it picks up the new list on its next turn via `state`.
            try:
                publish("graph.replanned", run=run_id, session=g.get("session_id"),
                        added=[n["id"] for n in added],
                        labels=[n["label"] for n in added],
                        nodes=len(g.get("nodes", [])))
            except Exception:  # noqa: BLE001
                pass
            return {"added": [n["id"] for n in added], "added_labels": [n["label"] for n in added],
                    "nodes": len(g.get("nodes", []))}, None, 200
    except ValueError as e:
        return None, {"error": str(e)}, 400
    except KeyError as e:
        return None, {"error": str(e).strip("'\"")}, 404
    return None, {"error": "unknown action %r" % action}, 400


CHAT_TOOL_MAX_STEPS = int(os.environ.get("SPARKFORGE_CHAT_TOOL_STEPS", "8"))
# JAG-84: hard cap on TOTAL loop iterations (bookkeeping + retries included), so
# that making plan/todo actions "free" can never spin the loop forever.
# JAG-164: the iters cap must NOT preempt the continuation loop — with the tool
# budget now refilled per keepgoing round (<= keepgoing_max rounds, default 8)
# the real governors are keepgoing.decide + the wall-clock budget; this is only a
# runaway backstop.
CHAT_TOOL_MAX_ITERS = int(os.environ.get("SPARKFORGE_CHAT_TOOL_ITERS", "64"))
# JAG-344: a PLAN-ONLY turn (the job coordinator's decomposition turn). The master
# MAY inspect the workspace and record its own todo plan, but it MUST NOT execute
# the teammates' work: left with the full budget + the keepgoing continuation loop,
# a capable master completed the WHOLE job itself in its planning turn (it wrote the
# deliverable files and "verified" them), bypassing the team. A plan turn is capped
# to a few real tool steps and NEVER continues past them (see `plan_only` below).
PLAN_ONLY_MAX_STEPS = int(os.environ.get("SPARKFORGE_PLAN_TOOL_STEPS", "3"))
# JAG-344: the tools a PLAN-ONLY turn may still call — INSPECTION only. Everything
# else (shell, fs.write, fs.edit, subagent, improve, …) is refused, so the master can
# read the workspace and consult a skill to inform its plan but CANNOT execute the
# teammates' work instead of delegating it (the SEVERE "master did the whole job").
PLAN_ONLY_TOOLS = {"fs.read", "skills", "memory", "self"}
# JAG-256: the assembled system prompt is published as a collapsed "system" inject
# so the operator can read it. Publishing it EVERY turn spammed the transcript with
# N identical blocks (reported as "the harness re-sends the system prompt ad
# infinitum"). Keep the last hash per session; re-publish only when it changes.
_LAST_SYS_INJECT = {}
# JAG-88 (harness layer L2 — context budgeting): observations above this many
# chars are offloaded to a file instead of being flooded into the context (and
# instead of the old silent 4000-char truncation that LOST the rest).
CHAT_TOOL_OBS_LIMIT = int(os.environ.get("SPARKFORGE_TOOL_OBS_LIMIT", "6000"))
# JAG-189: how long the chat loop waits for a delegated subagent before giving up
# (the child runs its own bounded agent loop; a chat turn must not hang forever).
SUBAGENT_WAIT = int(os.environ.get("SPARKFORGE_SUBAGENT_WAIT", "180"))
# JAG-181: the chat loop feeds the FULL tool output to the harness budgeter
# (_offload_observation), which writes it to a file and shows the model a head+tail
# preview. If the tool layer truncated first (tools.observation default 1600) the
# tail was lost forever and the model saw a dead "...[truncated N chars]" marker.
# So the chat path renders observations up to this ceiling, then the harness offload
# bounds the model context while NOTHING is discarded (the file keeps it all).
CHAT_OBS_FULL = int(os.environ.get("SPARKFORGE_OFFLOAD_MAX", "200000"))
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
    "FOLLOW it: address each step by its STABLE id — the list shows it as `label (n3)`. "
    "Before starting a step emit ONLY "
    '{"action":"update_todos","steps":[{"id":"<node id, e.g. n3>","status":"doing"}]}; when '
    "a step is finished emit ONLY "
    '{"action":"update_todos","steps":[{"id":"<node id>","status":"done","evidence":"<what proves it>"}]} '
    "(done REQUIRES evidence). The 0-based `index` still works as a fallback, but the id "
    "is preferred: it never shifts when the list changes. If new work appears or a step "
    "became irrelevant, "
    "briefly re-plan with "
    '{"action":"replan_todos","note":"<why>"} and then IMMEDIATELY resume the plan. '
    "To delegate a self-contained subtask to ONE child agent — it gets an isolated "
    "transcript and its own task list, then reports back its summary — emit ONLY "
    '{"action":"subagent","goal":"<the subtask>","max_steps":4}. Use it for a '
    "distinct subtask that can run on its own (e.g. reading and summarising a big "
    "file); do not delegate the whole task. One delegate per subtask. "
    "Tool registry (allowlist):\n"
)


# JAG-266: the task-list contract as a STANDING rule, not only a reactive nudge. It is
# registered as the `task-policy` prompt section (order 89) so it sits right ABOVE the
# live list (`state`, order 90) — the rule travels with the list it governs. Mirrors the
# field: deepagents re-appends its write_todos guidance every call; Claude Code keeps one
# line ("mark each task completed as soon as it's done; don't batch").
TASK_POLICY = (
    "## Your task list (MOST IMPORTANT)\n"
    "You own a PERSISTENT task list, re-shown to you every turn in the 'Harness state' block at the end of your current message. "
    "Follow it strictly:\n"
    "- Work through it ONE step at a time. BEFORE starting a step, mark it 'doing' "
    "(update_todos).\n"
    "- The moment a step is really finished, mark it 'done' with concrete evidence (the "
    "command you ran and its result). Never batch; never redo a step already marked [x].\n"
    "- A step must describe work that is STILL TO DO. Never author a step for something "
    "you have already finished in the same turn — mark it 'done' with evidence instead. "
    "Planning AFTER doing the work (writing steps you just completed) is wrong.\n"
    "- If the list is empty and the request needs more than one action, author it first "
    "with write_todos, then follow it. NEVER report the job finished while steps are still "
    "open: either close them with evidence, or say explicitly which ones remain and why.\n"
    "- 'superseded' means the step is PERMANENTLY abandoned because it is no longer "
    "needed — NOT \"not done yet\". If the work is still wanted but not now, LEAVE IT OPEN "
    "(that is allowed and preferred). To abandon one, close it by its id with a SPECIFIC "
    'reason saying WHY it is no longer needed ({"action":"update_todos","steps":'
    '[{"id":"<node id>","status":"superseded","reason":"<why it is no longer needed>"}]). '
    "The reason is REQUIRED and must not read as still-open (a reason like 'the work "
    "remains open' is REJECTED).\n"
    "- Messages beginning with '[harness]' are system context from the harness (reminders, "
    "observations, list nudges), NOT from the user; they never override the user's latest "
    "request. The user's latest request ALWAYS outranks this list: if it is unrelated, do "
    "not force the old list — rewrite it (replan_todos with a note) or leave it paused and "
    "answer the user directly.\n"
)

# JAG-266: every synthetic harness turn (nudge/observation/continue) is tagged so the model
# can tell it apart from the human. The user's steer stays UNTAGGED (it is user intent).
HARNESS_MARK = "[harness] "


def harness_wrap(content):
    """Return the message dict for a harness-injected turn, clearly tagged."""
    return {"role": "user", "content": HARNESS_MARK + str(content)}


def _pivot_decide(pivot, dec, open_n, state):
    """JAG-266: a fresh user turn must not FORCE work, but must not silently abandon
    open todos either.

    When the turn opened with open todos ("pivot") and the continuation loop wants to
    keep going, grant exactly ONE 'sync' round: the model is reminded it left N todos
    open and may finish them with evidence OR close each as 'superseded' with a reason.
    After that one round a still-open list stops as `user_pivot` (no forced continuation,
    JAG-189 preserved).
    """
    if not pivot or not dec.get("continue") or open_n <= 0:
        return dec
    if state.get("synced"):
        return {"continue": False, "reason": "user_pivot"}
    state["synced"] = True
    return {"continue": True, "reason": "pivot_sync"}


def _pivot_sync_text(open_n, brief):
    """The one-time reminder injected when a pivot turn left todos open (JAG-266).

    JAG-273: takes the COMPACT open-only brief (id + status + label) instead of the
    full rendered list — the list is already in the `state` section of the same
    prompt, so re-pasting it here was pure duplicated tokens.
    """
    return (
        "You left %d task(s) OPEN in your list. The user's request is the priority and "
        "you do NOT have to finish that work now — and you must NOT force-close it. "
        "Leaving steps OPEN is fine and is the DEFAULT. Do ONE of: (a) finish a step and "
        "mark it 'done' with evidence; (b) ONLY if a step is now PERMANENTLY unneeded, "
        "abandon it as 'superseded' with a SPECIFIC reason (REQUIRED) saying WHY it is no longer "
        'needed ({"action":"update_todos","steps":[{"id":"<node id>","status":"superseded",'
        '"reason":"<why it is no longer needed>"}]) — a reason that reads as still-open is '
        "REJECTED; or (c) rewrite the list with replan_todos. Then answer the "
        "user. Open (full list in 'Harness state' at the end of your message):\n%s" % (open_n, brief)
    )


def _next_stale(prev_stale, prev_hash, cur_hash, worked):
    """JAG-268: advance the 'no progress' counter ONLY for a truly idle round.

    A round that executed at least one tool (`worked`) DID make progress even if the
    todo-list hash did not move — that false positive used to halt a turn while the
    model was verifying its output (shell `FILE_OK` / `STRUCTURE_OK`) without touching
    the list. `stale` counts only a round with NO tool call AND no list change, which
    is the real "model is spinning" case; it stops via keepgoing's no_progress.
    """
    if prev_hash is None or cur_hash != prev_hash or worked:
        return 0
    return prev_stale + 1


def _looks_like_json_action(text):
    """True when `text` is a (possibly malformed/truncated) tool-call JSON —
    i.e. something we must NEVER show to the user as a chat reply."""
    t = (text or "").strip()
    if not t.startswith(("{", "[")):
        return False
    return ('"action"' in t) or ('"tool"' in t) or ('"args"' in t)


# JAG-304: a parsed JSON OBJECT is only an ACTION ATTEMPT when it carries one of
# these top-level keys (an action name, a tool name/args, or a raw tool-arg key).
# A dict with NONE of them is the model's own JSON ARTIFACT — a JSON Schema, a
# response envelope, a data record — i.e. its ANSWER, not a stray action.
_JSON_ACTION_KEYS = ("action", "tool", "tool_name", "args", "todos", "steps")
_JSON_TOOL_ARG_KEYS = ("command", "path", "content", "url", "query", "pattern")


def _looks_like_action_dict(act):
    """True when a parsed JSON dict is a (possibly malformed) action/tool call.

    JAG-304: the chat loop used to reject ANY parsed dict as a stray action
    ("That was not a valid action"), so a worker/coordinator that delivered its
    own JSON artifact (a JSON-Schema, a response envelope) as the answer was
    nagged into needless retries — and could be halted at four in a row. Only a
    dict that actually carries an action- or tool-signalling key is an attempt.
    """
    if not isinstance(act, dict):
        return False
    keys = set(act)
    if keys & set(_JSON_ACTION_KEYS):
        return True
    return bool(keys & set(_JSON_TOOL_ARG_KEYS))


# JAG-74: "act, don't announce". A reply that OPENS with an action verb in the
# first person and is short is a promise of imminent work, not a result. If no
# tool ran this turn we nudge the model once to actually do it (or conclude).
_PROMISE_RE = re.compile(
    r"^\s*(?:\*\*)?(?:carico|procedo|eseguo|lancio|creo|installo|avvio|aggiorno|"
    r"verifico|controllo|continuo|cerco|consulto|analizzo|recupero|preparo|"
    r"inizio|comincio|elaboro|determino|sintetizzo|organizzo|accedo|scarico|"
    r"i'?ll|i will|i'?m going to|let me|loading|running)\b",
    re.IGNORECASE)


def _looks_like_promise(text):
    """True when the reply only announces an action (and is not a result)."""
    t = (text or "").strip()
    return bool(t) and len(t) <= 400 and bool(_PROMISE_RE.match(t))


def _skill_hints(text, limit=3):
    """JAG-178: names of installed skills that best match `text`. Cheap keyword
    scoring — a name/title hit weighs more than a description hit — so a stuck
    model is nudged to READ the skill that actually covers the problem instead of
    guessing the syntax again."""
    try:
        from . import skills
        words = set(re.findall(r"[a-z]{3,}", (text or "").lower()))
        words -= {"the", "and", "for", "with", "you", "are", "not", "this", "that",
                  "error", "failed", "unknown", "command", "tool", "run", "get", "set"}
        if not words:
            return []
        scored = []
        for s in skills.list_skills():
            name = str(s.get("name") or "")
            strong = (name + " " + str(s.get("title") or "")).lower()
            weak = str(s.get("description") or "").lower()
            score = sum(3 for w in words if w in strong) + sum(1 for w in words if w in weak)
            if score:
                scored.append((score, name))
        scored.sort(key=lambda x: (-x[0], x[1]))
        return [n for _, n in scored[:limit] if n]
    except Exception:  # noqa: BLE001
        return []


def _stuck_note(tool, obs, fail_streak, repeats, hints):
    """JAG-178: a socratic "you are stuck" nudge. The harness does NOT solve the
    problem — it makes the model ask the RIGHT questions (syntax? skill? another
    route? ask the user?) and reminds it that it has skills and tools."""
    why = []
    if fail_streak >= 2:
        why.append("'%s' has failed %d times in a row" % (tool, fail_streak))
    if repeats >= 1:
        why.append("you just repeated the SAME call")
    return "\n".join([
        "Observation for tool %s:" % tool,
        obs,
        "",
        "SYSTEM (harness) — YOU ARE STUCK: %s." % ("; ".join(why) or "no progress"),
        "STOP and THINK before the next tool call. Ask yourself:",
        "  1) Is the command SYNTAX exactly right for this exact subcommand? (re-read the error above)",
        "  2) Have I READ the skill that covers this? You have skills — e.g. %s — "
        "read one with the `skills` tool (action=read, name=<skill>)."
        % (", ".join(hints) if hints else "check them in your system prompt"),
        "  3) Is there a DIFFERENT route to the same result that avoids this broken call?",
        "  4) If you cannot progress, ASK THE USER one precise question instead of retrying.",
        "Do NOT repeat the same call. Change approach, read a skill, or ask the user.",
    ])


def _repeat_block_note(tool, err, repeats, hints):
    """JAG-183: hard anti-loop directive. When the model re-issues an IDENTICAL
    call that already FAILED, the harness refuses to run it again (see the call
    site) and hands back this directive instead of a socratic question. Without it
    a stuck model burned the step budget looping and then resigned with a bare
    "mi fermo e chiedo" (session v176: 3x `adb ... input tap` -> exit 1)."""
    return "\n".join([
        "SYSTEM (harness) — CALL BLOCKED (repeat #%d). It was NOT executed." % repeats,
        "You already ran exactly this `%s` and it FAILED:" % tool,
        "  %s" % ((err or "").strip()[:300] or "(no error text)"),
        "Re-running it verbatim will fail again. Do ONE of these NOW:",
        "  1) a DIFFERENT command / a different route to the same result;",
        "  2) READ the skill that covers this%s;"
        % ((" — e.g. " + ", ".join(hints)) if hints else " (check your system prompt)"),
        "  3) if it is truly blocked, answer the user with ONE precise question:"
        " what you tried, the EXACT error, and what you need from them.",
        "Do NOT repeat the same call.",
    ])


def _plan_only_refusal(tool):
    """JAG-344: directive when a PLAN-ONLY turn tries to run a MUTATING tool.

    The master's planning turn may inspect the workspace (`fs.read`) and consult a
    skill (`skills`) but must NOT execute the teammates' work. Without this the model
    wrote the deliverable files itself and "verified" them, bypassing the team
    (observed live: the coordinator produced the whole KICKOFF PACKAGE in its plan
    turn). The tool is refused and the model is sent back to PLANNING.
    """
    return "\n".join([
        "SYSTEM (harness) — PLAN-ONLY turn: `%s` is NOT available while planning. "
        "It was NOT executed." % tool,
        "You are DECOMPOSING the goal for your team, not doing it. Allowed now: "
        "`fs.read` (inspect a file), `skills` (consult a skill) and your task list.",
        "Do this NOW: record the sub-tasks in your task list and END your reply with "
        "ONE bullet per teammate (agent id first, e.g. \"- A25: ...\"), putting "
        "\"(after AX)\" on any bullet that must WAIT for another agent.",
        "Do NOT write files and do NOT run commands — the workers execute them.",
    ])


def _open_plan_steps(sess):
    """How many plan nodes are still OPEN (todo/doing/blocked) for this session.

    JAG-87 ("verify before you finish", harness layer L7): the persistent plan is
    the execution state; a turn that ends with open steps and no explanation is a
    silent abandonment. Returns 0 when there is no plan at all.
    """
    try:
        from . import taskgraph
        g = taskgraph.load(sess["id"])
        if not g or not g.get("nodes"):
            return 0
        c = taskgraph.counts(g)
        return sum(c.get(s, 0) for s in taskgraph.OPEN_STATUSES)
    except Exception:  # noqa: BLE001
        return 0


def _open_todo_brief(sess, limit=10):
    """JAG-271: the EXACT open steps (id + status + label) for a harness nudge.

    "mark the next step 'doing'" told the model nothing it could not guess, so it
    re-derived (and sometimes re-opened) the plan. The nudge must NAME what is left,
    by id (id-first) so the model can act on it directly. Returns (count, brief);
    brief is "(none …)" when the list is fully closed.
    """
    try:
        g = taskgraph.load(sess["id"])
        nodes = taskgraph.plan_nodes(g) or []
        opn = [n for n in nodes if n.get("status") in taskgraph.OPEN_STATUSES]
    except Exception:  # noqa: BLE001
        return 0, ""
    if not opn:
        return 0, "(none — every step is closed)"
    lines = ["  - %s [%s] %s" % (n.get("id"), n.get("status"), n.get("label", ""))
             for n in opn[:limit]]
    if len(opn) > limit:
        lines.append("  - … +%d more" % (len(opn) - limit))
    return len(opn), "\n".join(lines)


def _nudge_open_todos(sess):
    """JAG-271: the post-update nudge — NAMES the exact steps still open (by id).

    Replaces the old generic "mark the next step 'doing'" which named nothing.
    """
    on, brief = _open_todo_brief(sess)
    if on:
        return ("Noted — plan updated (by id). STILL OPEN (%d):\n%s\n"
                "Now do the FIRST one: mark it 'doing' before you start it, then 'done' "
                "with concrete evidence when it is really finished. Never redo a [x] "
                "step; close an unwanted one as 'superseded' WITH a reason."
                % (on, brief))
    return ("Noted — every step is now closed. If the user's request is fully answered, "
            "give the final plain-text answer now; otherwise say what still needs doing.")


# JAG-88: per-session counter for offloaded observation files (001_, 002_, ...).
_OFFLOAD_SEQ = {}
_OFFLOAD_HEAD = 1500
_OFFLOAD_TAIL = 600


def _offload_observation(sess, tool, text):
    """JAG-88 (harness layer L2 — context budgeting): keep big tool outputs OUT
    of the model's context but NEVER lose them.

    The chat loop used to hard-truncate every observation to 4000 chars: a big
    web page, a log dump or a `find` over a tree was silently cut and the tail
    was LOST to the model (and it could not recover it). Now an oversized
    observation is written verbatim to data/offload/<session>/ and the model
    receives a compact reference — size, line count, path, a head+tail preview,
    and the exact call to read the rest (fs.read / shell grep). The context
    stays bounded; nothing is discarded.
    """
    n = len(text)
    seq = _OFFLOAD_SEQ.get(sess["id"], 0) + 1
    _OFFLOAD_SEQ[sess["id"]] = seq
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", str(tool))[:40] or "tool"
    fallback = ("Observation for tool %s:\n%s\n\n"
                "Now answer the user in plain text, or call another tool."
                % (tool, text[:CHAT_TOOL_OBS_LIMIT]))
    try:
        outdir = os.path.join(DATA_DIR, "offload", sess["id"])
        os.makedirs(outdir, exist_ok=True)
        path = os.path.join(outdir, "%03d_%s.txt" % (seq, safe))
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
    except Exception:  # noqa: BLE001 — offload must never kill the turn
        return fallback
    lines = text.count("\n") + 1
    head = text[:_OFFLOAD_HEAD]
    ref = (
        "Observation for tool %s: output is LARGE (%d chars, %d lines) and was "
        "saved to a file so it does not flood your context.\n"
        "FULL OUTPUT FILE: %s\n"
        "Read more of it with {\"action\":\"tool\",\"tool\":\"fs.read\","
        "\"args\":{\"path\":\"%s\"}} (or grep it with the shell tool).\n"
        "Preview — first %d chars:\n%s\n"
        % (tool, n, lines, path, path, min(_OFFLOAD_HEAD, n), head))
    if n > _OFFLOAD_HEAD + _OFFLOAD_TAIL:
        ref += "...\nPreview — last %d chars:\n%s\n" % (_OFFLOAD_TAIL, text[-_OFFLOAD_TAIL:])
    ref += "\nNow answer the user in plain text, or call another tool."
    return ref


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


def _apply_chat_todos(sess, act, on_event, node=None, after=None):
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
        todo_args = {"todos": todos if isinstance(todos, list) else []}
        on_event("tool.call", session=sess["id"], tool="write_todos", args=todo_args,
                 inline=True)
        # JAG-177: a new plan REPLACES the previous OPEN plan — cancel the open
        # steps the model did NOT keep, so re-planning never accumulates a wall of
        # obsolete, overlapping steps (session `test`: 27 nodes from 3 re-plans).
        # `done`/`cancelled` history is preserved.
        _labels = []
        for _t in (todos or []):
            _l = _t if isinstance(_t, str) else (_t.get("label") or _t.get("title")
                                                 or _t.get("task"))
            if _l:
                _labels.append(_l)
        if _labels:
            for _cid in taskgraph.supersede_open(graph, _labels):
                _n = taskgraph.find(graph, node_id=_cid)
                if _n:
                    on_event("graph.node.updated", session=sess["id"], node=_n,
                             index=graph["nodes"].index(_n),
                             total=len(graph["nodes"]), changes=["status"])
        base = len(graph.get("nodes", []))
        added = taskgraph.apply_write_todos(
            graph, taskgraph._missing(graph, todos or []))
        total = len(graph.get("nodes", []))
        # surface each node on the chat stream too, so the app renders the list
        # live (apply_write_todos only fans out on the global feed).
        for i, _nd in enumerate(added):
            on_event("graph.node.added", session=sess["id"], node=_nd,
                     index=base + i, total=total)
        # JAG-116: the card must show in AND out, not an empty body.
        # JAG-269: show the CURRENT plan with each node's ID + any close reason
        # (id-first addressing: the model learns the ids here and reuses them).
        out = "\n".join(
            "- [%s] %s %s%s" % (
                n.get("status", "open"), n.get("id", ""), n.get("label", ""),
                ("  (%s: %s)" % (n.get("status"), n.get("reason"))
                 if n.get("reason") else ""))
            for n in (taskgraph.plan_nodes(graph) or graph.get("nodes", [])))
        on_event("tool.result", session=sess["id"], tool="write_todos", ok=True,
                 exit_code=0, backend="harness", args=todo_args,
                 output=out[:2000] or ("+%d node(s)" % len(added)),
                 summary="task list: %d node(s), +%d" % (total, len(added)))
        # JAG-190: persist the card so a reload rebuilds it (harness-action cards
        # were streamed live but never stored, so they vanished on refresh).
        persist_tool_card(sess, "write_todos", True, args=todo_args,
                          result=out[:2000] or ("+%d node(s)" % len(added)),
                          exit_code=0, backend="harness", node=node, after=after)
        return len(added)
    except Exception as e:  # noqa: BLE001 — the task list must never break chat
        try:
            on_event("tool.result", session=sess["id"], tool="write_todos",
                     ok=False, backend="harness", stderr=str(e)[:200])
            persist_tool_card(sess, "write_todos", False, error=str(e)[:200],
                              backend="harness", node=node, after=after)
        except Exception:  # noqa: BLE001
            pass
        return 0


def _resolve_graph_node(graph, step):
    """Locate a node by id, label or 0-based index (JAG-75).

    JAG-196: the model's `update_todos` uses 0-based indices / labels into ITS
    CURRENT list. Since JAG-194 keeps every plan's nodes in the graph, resolving
    against the whole node list made index 0 hit an OLD plan's node — the current
    plan never advanced ("All steps complete" vs "4 open" deadlock). Resolve
    labels/indices against the CURRENT plan only; ids stay globally unique.
    """
    nodes = taskgraph.plan_nodes(graph) or graph.get("nodes", [])
    node = None
    if step.get("id") is not None:
        node = taskgraph.find(graph, node_id=str(step["id"]))
    if node is None and step.get("label"):
        _lbl = str(step["label"]).strip().lower()
        for _n in nodes:
            if str(_n.get("label", "")).strip().lower() == _lbl:
                node = _n
                break
    if node is None and step.get("index") is not None:
        try:
            i = int(step["index"])
        except (TypeError, ValueError):
            return None
        if 0 <= i < len(nodes):
            node = nodes[i]
    return node


def _apply_chat_todo_updates(sess, act, on_event, node=None, after=None):
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
        on_event("tool.call", session=sess["id"], tool="update_todos",
                 args={"steps": steps}, inline=True)
        changed = []
        # JAG-269: reasons/misses are surfaced (not swallowed) so the model learns
        # WHY a close was rejected instead of silently seeing "0/N updated".
        errors = []
        for step in steps:
            if not isinstance(step, dict):
                continue
            _ref = step.get("id") or step.get("label") or step.get("index")
            _nd = _resolve_graph_node(graph, step)
            if _nd is None:
                errors.append("step %r not found" % (_ref,))
                continue
            status = str(step.get("status") or "").strip().lower()
            ev = step.get("evidence")
            try:
                if status == "done":
                    # JAG-320: refuse a `done` that contradicts a FAILED delegation on
                    # THIS step. Observed live: three subagents timed out for a step,
                    # then the model closed it as done with invented evidence. The
                    # marker is durable (stored on the node) so the guard still fires
                    # hours later / after a restart — a short timer missed it (the real
                    # claim came ~8.6h after the failure). The refusal is ONE-SHOT: the
                    # marker is consumed, so a genuine retry or a self-completed step
                    # is never blocked forever.
                    _fail = _nd.get("delegation")
                    if isinstance(_fail, dict) and _fail.get("ok") is False:
                        errors.append(
                            "step %s: refusing 'done' — its delegated subagent FAILED "
                            "(%s); retry the delegation or do the work yourself, then "
                            "close it again."
                            % (_nd["id"], str(_fail.get("error") or "error")[:120]))
                        try:
                            taskgraph.clear_delegation(graph, _nd["id"])
                        except Exception:  # noqa: BLE001
                            pass
                        continue
                    _nd = taskgraph.complete_node(
                        graph, node_id=_nd["id"], evidence=ev, source="model:update_todos")
                elif status in taskgraph.STATUSES:
                    _nd = taskgraph.update_node(
                        graph, _nd["id"], status=status, evidence=ev,
                        reason=step.get("reason"), source="model:update_todos")
                else:
                    errors.append("step %s: bad status %r" % (_nd["id"], status))
                    continue
            except (KeyError, ValueError) as _e:
                errors.append("step %s: %s" % (_nd["id"], _e))
                continue
            changed.append(_nd)
            on_event("graph.node.updated", session=sess["id"], node=_nd,
                     index=graph["nodes"].index(_nd), total=len(graph["nodes"]),
                     changes=["status"])
        # JAG-177: at most ONE step may be 'doing' — demote the extras to 'todo'.
        for _did in taskgraph.enforce_single_doing(graph):
            _dn = taskgraph.find(graph, node_id=_did)
            if _dn:
                on_event("graph.node.updated", session=sess["id"], node=_dn,
                         index=graph["nodes"].index(_dn),
                         total=len(graph["nodes"]), changes=["status"])
        # JAG-268: show the WHOLE current list (like write_todos), not just the
        # changed lines — a lone "- [doing] <label>" read like a stray claim and
        # hid the step in its list context.
        # JAG-269: each line carries the node's ID (id-first addressing) and, for a
        # closed-with-reason step, the reason — so the card shows the whole object.
        def _render_line(_n):
            _extra = ("  (%s: %s)" % (_n.get("status"), _n.get("reason"))
                      if _n.get("reason") else "")
            return "- [%s] %s %s%s" % (_n.get("status", "open"), _n.get("id", ""),
                                       _n.get("label", ""), _extra)
        _out = ("\n".join(_render_line(n)
                          for n in (taskgraph.plan_nodes(graph) or graph.get("nodes", [])))[:2000]
                or "no step changed")
        if errors:
            _out = (_out + "\n! " + "\n! ".join(str(e) for e in errors))[:2000]
        _err = "; ".join(str(e) for e in errors)[:400]
        _n_steps = len([s for s in steps if isinstance(s, dict)])
        on_event("tool.result", session=sess["id"], tool="update_todos", ok=(not errors),
                 exit_code=(0 if not errors else 1), backend="harness", args={"steps": steps},
                 output=_out, stderr=(_err or None),
                 summary="task list: %d/%d step(s) updated%s"
                         % (len(changed), _n_steps,
                            (", %d rejected" % len(errors)) if errors else ""))
        # JAG-190: persist so the card survives a reload.
        persist_tool_card(sess, "update_todos", (not errors), args={"steps": steps},
                          result=_out, error=_err, exit_code=(0 if not errors else 1),
                          backend="harness", node=node, after=after)
        return len(changed)
    except Exception as e:  # noqa: BLE001 — the task list must never break chat
        try:
            on_event("tool.result", session=sess["id"], tool="update_todos",
                     ok=False, backend="harness", stderr=str(e)[:200])
            persist_tool_card(sess, "update_todos", False, error=str(e)[:200],
                              backend="harness", node=node, after=after)
        except Exception:  # noqa: BLE001
            pass
        return 0


def _apply_chat_replan(sess, act, on_event, node=None, after=None):
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
        # JAG-190: persist so the card survives a reload.
        persist_tool_card(sess, "replan_todos", True,
                          result="re-plan: +%d step(s)" % len(added),
                          exit_code=0, backend="harness", node=node, after=after)
        return len(added)
    except Exception as e:  # noqa: BLE001 — never break chat
        try:
            on_event("tool.result", session=sess["id"], tool="replan_todos",
                     ok=False, backend="harness", stderr=str(e)[:200])
            persist_tool_card(sess, "replan_todos", False, error=str(e)[:200],
                              backend="harness", node=node, after=after)
        except Exception:  # noqa: BLE001
            pass
        return 0


def _apply_chat_subagent(sess, act, on_event, node=None, after=None):
    """Harness action `subagent` (JAG-189): delegate ONE subtask to a child run.

    The chat loop spawns a subagent (isolated transcript, its own task list, the
    same tools/approvals/sandbox), WAITS for it, and feeds its summary back as
    the next observation. Mirrors the HTTP `/api/subagent/spawn` endpoint and the
    MCP `sparkforge_subagent` tool, so the model can actually delegate: before
    JAG-189 the action existed but was nowhere in the model's menu, so a request
    to "delegate to a subagent" looped forever.
    """
    try:
        from . import subagent as _sub
        _act = act if isinstance(act, dict) else {}
        _args = _act.get("args") if isinstance(_act.get("args"), dict) else {}
        goal = str(_act.get("goal") or _args.get("goal")
                   or _act.get("detail") or "").strip()
        if not goal:
            on_event("tool.result", session=sess["id"], tool="subagent", ok=False,
                     backend="harness", exit_code=1, summary="subagent: goal required")
            persist_tool_card(sess, "subagent", False, error="goal required",
                              backend="harness", node=node, after=after)
            return "subagent error: goal required"
        try:
            max_steps = int(_act.get("max_steps", _args.get("max_steps", 4)))
        except (TypeError, ValueError):
            max_steps = 4
        model = _act.get("model") or _args.get("model") or None
        on_event("tool.call", session=sess["id"], tool="subagent",
                 args={"goal": goal, "max_steps": max_steps, "model": model},
                 inline=True)
        spawned = _sub.spawn(goal, parent_run_id=sess["id"], max_steps=max_steps,
                             model=model, depth=_sub.depth_of(sess["id"]) + 1) or {}
        sid = spawned.get("subagent_id")
        if not sid:
            err = spawned.get("error") or "spawn failed"
            on_event("tool.result", session=sess["id"], tool="subagent", ok=False,
                     backend="harness", exit_code=1, summary="subagent: " + str(err))
            persist_tool_card(sess, "subagent", False, error=str(err),
                              backend="harness", node=node, after=after)
            return "subagent error: %s" % err
        res = _sub.collect(sid, timeout=SUBAGENT_WAIT) or {}
        summary = str(res.get("summary") or "").strip()
        ok = bool(res.get("ok"))
        # JAG-320: remember the OUTCOME on the delegated step's node (durable, so a
        # later `update_todos ... done` cannot close a step whose subagent failed —
        # even hours later or after a restart). A successful delegation clears it.
        if node:
            try:
                _g = taskgraph.load(sess["id"])
                if _g:
                    taskgraph.record_delegation(_g, node, ok,
                                                error=res.get("error"), subagent_id=sid)
            except Exception:  # noqa: BLE001
                pass
        out = summary or json.dumps(res, ensure_ascii=False, default=str)[:1500]
        on_event("tool.result", session=sess["id"], tool="subagent", ok=ok,
                 exit_code=0 if ok else 1, backend="subagent",
                 args={"goal": goal, "max_steps": max_steps, "subagent_id": sid},
                 output=out[:4000],
                 summary="subagent %s: %s" % (sid, "done" if ok else "error"))
        # JAG-190: persist so the card survives a reload.
        persist_tool_card(sess, "subagent", ok,
                          args={"goal": goal, "max_steps": max_steps,
                                "subagent_id": sid},
                          result=out[:4000], exit_code=0 if ok else 1,
                          backend="subagent", node=node, after=after)
        if ok:
            return ("Subagent %s finished (goal: %s).\nResult:\n%s"
                    % (sid, goal[:120], out[:4000]))
        # JAG-320: say FAILED plainly (the old text said "finished" even on
        # failure) and forbid closing the delegated step on the back of it.
        return ("Subagent %s FAILED: %s. This delegated step is NOT done — retry "
                "the delegation, do the work yourself, or mark the step blocked."
                % (sid, str(res.get("error") or "unknown")[:200]))
    except Exception as e:  # noqa: BLE001 — delegation must never break chat
        try:
            on_event("tool.result", session=sess["id"], tool="subagent", ok=False,
                     backend="harness", exit_code=1, stderr=str(e)[:200],
                     summary="subagent: error")
            persist_tool_card(sess, "subagent", False, error=str(e)[:200],
                              backend="harness", node=node, after=after)
        except Exception:  # noqa: BLE001
            pass
        return "subagent error: %s" % e


# JAG-93: post-turn reflection -> one append-only lesson in the memory store
# (self-improvement). A reflection must never break a turn: everything here is
# guarded and bounded, and a per-session cooldown keeps short bursts from
# spamming the store.
_REFLECT_LATEST = {}
_REFLECT_COOLDOWN = 90.0


def maybe_reflect(sess, message, answer, used_tools, model=None):
    """Distill one short reusable lesson after a tool-using turn.

    Returns the stored lesson string, or None when skipped/failed.
    """
    if not used_tools:
        return None
    now = time.time()
    if now - _REFLECT_LATEST.get(sess["id"], 0) < _REFLECT_COOLDOWN:
        return None
    try:
        from . import memory
        msgs = [{"role": "system", "content":
                 "You are the self-improvement module. Read the exchange and write "
                 "ONE short reusable lesson (a durable rule, a fix, a gotcha) for "
                 "future sessions. Max 140 characters. No preamble, no quotes, no markdown."},
                {"role": "user", "content":
                 "Goal: %s\nOutcome: %s" % (str(message)[:500], str(answer)[:800])}]
        lesson, _think, _alias = _router_stream(
            msgs, model or default_model(), lambda ch, t: None, timeout=60)
        lesson = (lesson or "").strip().strip('"').strip()
        if len(lesson) < 6 or len(lesson) > 400:
            return None
        memory.store("agent.note", lesson, session=sess["id"], source="reflect")
        _REFLECT_LATEST[sess["id"]] = now
        return lesson
    except Exception:  # noqa: BLE001 — reflection must never break a turn
        return None


def _apply_skill_slash(message):
    """JAG-109: `/name rest` → injects the SKILL.md into the turn's prompt.

    It does not modify the saved history (stays `/name rest`); the injection is
    transient and applies only to this turn. `/goal` is untouched.
    """
    if not message or not message.startswith("/"):
        return message
    token, _, rest = message[1:].partition(" ")
    token = token.strip().lower()
    if not token or token == "goal":
        return message
    try:
        from . import skills as skills_mod
        sk = skills_mod.get_skill(token)
    except Exception:  # noqa: BLE001 — the injection must never break a turn
        return message
    if not sk:
        return message
    body = (sk.get("content") or "")[:20000]
    rel = sk.get("path") or ""
    skill_dir = (os.path.dirname(os.path.abspath(os.path.join(REPO, rel)))
                 if rel else "")
    hint = ""
    if skill_dir:
        hint = (
            "SKILL_DIR (absolute path of this skill \u2014 use it as the skill ROOT; "
            "replace ${CLAUDE_SKILL_DIR} / ${SKILL_DIR} / $SKILL_DIR with it, and "
            "resolve every relative path in the instructions below against it). "
            "DO NOT search the filesystem for the script: it is right here.\n"
            "SKILL_DIR: %s\n\n" % skill_dir)
    return ("SKILL ACTIVATION \u2014 '%s' (follow these instructions for this turn)\n\n"
            "%s%s\n\n---\nUSER: %s" % (token, hint, body, rest.strip()))


def assemble_turn(sess, message, tool_ctx=None, model=None, autonomous=False):
    """Assemble the exact message list SENT to the router for one chat turn.

    JAG-100: the caller has ALREADY appended the `user` turn to the session
    (JAG-51 contract), so we drop that stored copy and let `context_engine.build`
    append the (possibly autonomous-augmented) message exactly ONCE. Before this
    fix the same message was sent twice: harmless for a short prompt, but it
    DOUBLED a large pasted message (a 34.5k-token block reached the model as
    ~72k = 2x block + system). Returns (msgs, ctx_stats); ctx_stats is None when
    the context engine is unavailable (plain fallback).
    """
    if tool_ctx is None:
        tool_ctx = _tool_context()
    sys = _system_prompt(sess, tool_ctx)
    eff_message = _apply_skill_slash(message)
    if autonomous:
        eff_message = (
            "AUTONOMOUS GOAL MODE — accomplish the goal below end to end without "
            "asking for confirmation. FIRST emit write_todos with 2-8 steps, then "
            "execute them one by one with tools, marking each 'doing' and then "
            "'done' with evidence, then finish with a short plain-text summary."
            "\n\nGOAL: " + str(message))
    # JAG-100: drop the just-stored user turn so it is never sent twice.
    transcript = list(sess.get("messages", []))
    if transcript and transcript[-1].get("role") == "user":
        transcript = transcript[:-1]
    # JAG-276: the live task list rides in the CURRENT user turn (not the system
    # prompt) so the whole system prompt + committed transcript stay cache-safe.
    eff_message = eff_message + "\n\n" + state_block(session_id=(sess or {}).get("id"))
    try:
        from . import context_engine
        msgs, ctx_stats = context_engine.build(
            sys, transcript, eff_message, budget_tokens=context_budget(model))
        return msgs, ctx_stats
    except Exception:  # noqa: BLE001 — never block a turn on the context engine
        msgs = [{"role": "system", "content": sys}]
        msgs += [{"role": m["role"], "content": m["content"]}
                 for m in transcript[-20:]]
        msgs.append({"role": "user", "content": eff_message})
        return msgs, None


_HARNESS_ACTION_NAMES = ("write_todos", "update_todos", "replan_todos", "subagent",
                         "plan_step", "complete_plan_step", "add_task",
                         "complete_task", "note", "finish")

# JAG-278: a weak model often ends a turn with a made-up envelope whose action is a
# synonym of "I am done" ({"action":"answer","text":"..."} / {"action":"finish"}).
# Treat those as the plain-text answer instead of burning the retry budget on them.
_TERMINAL_ACTIONS = ("answer", "respond", "response", "final", "final_answer",
                     "finish", "complete", "done", "end", "stop", "message",
                     "reply", "result", "output", "report")


def _term_action(act):
    """True when the action is a made-up 'I am done' synonym (JAG-278)."""
    try:
        return str(act.get("action") or "").strip().lower() in _TERMINAL_ACTIONS
    except Exception:  # noqa: BLE001
        return False


def _normalize_action(act):
    """JAG-264: accept the obvious near-misses weak models keep emitting.

    Real tools use {"action":"tool","tool":"<name>","args":{...}}; harness/plan
    actions are TOP-LEVEL ({"action":"update_todos","steps":[...]}). A small model
    conflates the two — it wraps a harness action inside the tool envelope, or
    emits the bare payload with no "action" — then loops forever on the harness's
    "not a valid tool call" retry (observed flooding the WebUI). Normalise those
    back to the intended action; a well-formed tool call or harness action is
    returned unchanged.
    """
    if not isinstance(act, dict):
        return act
    a = act.get("action")
    # JAG-278: an OpenAI-style function call {"name":"x","arguments":{...}}.
    if not a and isinstance(act.get("name"), str) and "arguments" in act:
        _args = act.get("arguments")
        if isinstance(_args, str):
            try:
                _args = json.loads(_args)
            except Exception:  # noqa: BLE001
                _args = {}
        return {"action": "tool", "tool": act["name"], "args": _args or {}}
    if a == "tool":
        name = act.get("tool") or act.get("tool_name") or act.get("name")
        if name in _HARNESS_ACTION_NAMES:
            inner = dict(act.get("args") or {})
            inner["action"] = name
            for k in ("thought", "note", "todos", "steps", "goal", "detail",
                      "model", "max_steps"):
                if k in act and k not in inner:
                    inner[k] = act[k]
            return inner
        if name:
            return {"action": "tool", "tool": name, "args": act.get("args") or {}}
        return act
    if not a:
        if "todos" in act:
            return dict(act, action="write_todos")
        if "steps" in act:
            return dict(act, action="update_todos")
        if "note" in act:
            return dict(act, action="replan_todos")
    # JAG-278: an UNKNOWN action name but a recognizable PAYLOAD — coerce by SHAPE.
    # A weak model writes the right body under a wrong/labelled action ("update",
    # "set_todos", ...); the payload is the reliable signal, not the action name.
    if a not in ("tool", "write_todos", "update_todos", "replan_todos", "subagent"):
        if isinstance(act.get("todos"), list):
            return dict(act, action="write_todos")
        if isinstance(act.get("steps"), list):
            return dict(act, action="update_todos")
    return act


def _harness_start_note(sess):
    """JAG-332: ONE durable "session started" harness marker, written on the first turn.

    The full system prompt is emitted every turn but TRANSIENTLY (kind 'system', not
    persisted), so after a reload the operator sees NO harness message at the start of a
    session and cannot tell that the harness passed a real prompt. This writes a single
    durable marker per session stating what the harness LOADED (workspace, rules, skills
    index, tool registry, prompt size) — the wiring the model is actually given.
    """
    sid = (sess or {}).get("id")
    if not sid:
        return
    if any(r.get("kind") == "harness-start" for r in (sess.get("injects") or [])):
        return
    try:
        from . import prompt as prompt_mod, rules as rules_mod
        ws = rules_mod.resolve_workspace(sess)
        secs = prompt_mod.section_texts(sess, ws=ws, tool_ctx=None)
        text = ("session started \u2014 harness wiring\n"
                "- workspace: %s\n"
                "- rules loaded (RULES.md): %d chars\n"
                "- skills index: %d chars \u2014 search a skill with skills{action:'search'}\n"
                "- tool registry: %d chars\n"
                "- system prompt: %d chars (re-sent with each request; the provider reuses "
                "its KV-cache, so it is recomputed only after compaction/reset)"
                % (ws or "-", len(secs.get("rules") or ""), len(secs.get("skills") or ""),
                   len(secs.get("tools") or ""),
                   len(prompt_mod.render_sections(sess, ws=ws, tool_ctx=None))))
    except Exception:  # noqa: BLE001 — the marker must never break a turn
        text = "session started"
    try:
        persist_inject(sess, "harness-start", text)
        publish("harness.inject", session=sid, inject_kind="harness-start", text=text)
    except Exception:  # noqa: BLE001
        pass


def chat_once(sess, message, model=None, on_delta=None, trace=None, on_event=None,
              autonomous=False, plan_only=False):
    """Run one streamed router call and persist exactly one assistant message.

    Contract (JAG-51): the caller appends the `user` message; this function is
    the only place that persists the matching `assistant` turn. It returns
    `(message, model_used)`. On success the message carries the reply; when the
    model returns no answer at all the message is still persisted, flagged with
    `error=True` / `error_detail` (see `ensure_reply_persisted`) so no request
    can ever end as an orphan `user` turn. Raises only when the router call
    itself fails — callers then persist the error turn (`ensure_reply_persisted`).
    """
    # JAG-332: on the FIRST turn of a session, leave a durable harness marker so the
    # operator can SEE the wiring (the full prompt card is transient, per turn).
    if len(sess.get("messages") or []) <= 1:
        _harness_start_note(sess)
    if on_delta is None:
        on_delta = lambda channel, text: publish(
            "chat.delta", session=sess["id"], channel=channel, text=text)
    if on_event is None:
        on_event = publish
    # JAG-58b: the chat IS the agent — same tool registry as the agent loop, so
    # the model can call tools inline before it answers. Falls back to plain chat
    # if the tool registry is unavailable.
    # JAG-70/JAG-100: one shared assembler builds the EXACT prompt sent here and
    # measured by the context indicator, so the number cannot drift from reality.
    tool_ctx = _tool_context()
    msgs, ctx_stats = assemble_turn(sess, message, tool_ctx, model, autonomous)
    # JAG-172: everything appended to `msgs` from this index on is THIS turn's
    # agentic history (tool calls, observations, nudges). It is persisted at the
    # end of the turn so the model retains its own work across turns and the ctx
    # meter reflects the real prompt (see the block before `append_message`).
    _turn_base = len(msgs)
    if ctx_stats:
        # JAG-78: `on_event` (not `publish`), so the chat STREAM carries the live
        # prompt size and the app's ctx meter updates during the turn.
        on_event("context.built", session=sess["id"],
                 display=context_display(ctx_stats.get("final_tokens"),
                                         ctx_stats.get("budget_tokens")),
                 **{
                     k: v for k, v in ctx_stats.items() if k in (
                         "budget_tokens", "retrieved_memories", "final_messages",
                         "final_tokens")})
    model = model or default_model()
    # JAG-58b: tool-aware chat loop. The model may answer directly, or ask for a
    # tool; the tool runs through the same approval gate as the agent loop and
    # its observation is fed back, then the model continues. Streaming deltas are
    # buffered per iteration so raw tool-call JSON is never shown to the user.
    max_steps = CHAT_TOOL_MAX_STEPS if tool_ctx else 1
    # JAG-344: a plan-only turn keeps a TIGHT real-tool budget (the master inspects
    # a little to inform its plan) and never continues past it (see the loop below).
    if plan_only:
        max_steps = min(max_steps, PLAN_ONLY_MAX_STEPS)
    answer, think = "", ""
    final_answer = ""
    # JAG-304: set when the final answer is the model's own JSON artifact (not an
    # action) — the tail JSON guard must not gut a legitimate artifact that merely
    # contains an "action"/"tool"/"args" substring.
    _final_is_artifact = False
    announce_nudged = False
    _hitl = None   # JAG-171: set when the turn stops with OPEN todos → ask the human
    # JAG-84: only REAL tool calls consume the work budget. Plan/todo bookkeeping
    # (write_todos / update_todos / replan_todos) and invalid-JSON retries used to
    # eat the same 4-step budget, so a "plan then work" turn ran out of steps right
    # after the plan, was forced to "answer in plain text" and announced instead of
    # acting (session 558d0f0fce6e / run 056347769632: write_todos + skills x3 then
    # "I'm proceeding with the live search…" and stop). Now bookkeeping is free but bounded
    # by CHAT_TOOL_MAX_ITERS.
    # JAG-86: the model's REAL token accounting for this turn (from the router's
    # `usage`), so the ctx meter stops being a pure chars/4 proxy.
    chat_usage = {}

    def _record_usage():
        pt = chat_usage.get("prompt_tokens")
        if pt:
            try:
                _REAL_PROMPT_TOKENS[sess["id"]] = int(pt)
            except (TypeError, ValueError):
                pass
        # JAG-273: the provider's prefix (KV) cache hit for this call.
        _det = chat_usage.get("prompt_tokens_details") or {}
        _c = _det.get("cached_tokens")
        if _c is None:
            _c = (chat_usage.get("timings") or {}).get("cache_n")
        if _c is not None:
            try:
                _REAL_CACHED_TOKENS[sess["id"]] = int(_c)
            except (TypeError, ValueError):
                pass
        # JAG-355: price this call from its REAL usage, append it to the live cost
        # ledger, and push it so the Cost panel updates mid-run.
        try:
            from . import costs as _costs
            _call = _costs.record(sess["id"], model, chat_usage)
            if _call:
                on_event("cost.usage", session=sess["id"], call=_call)
        except Exception:  # noqa: BLE001 — accounting must never break a turn
            pass

    def _emit_context():
        """JAG-98: re-emit the live ctx size with the model's REAL prompt_tokens
        (falling back to the chars/4 estimate before the first call), so the
        meter is accurate and grows with the tool observations in this turn."""
        payload = {}
        if ctx_stats:
            payload = {k: ctx_stats.get(k) for k in (
                "budget_tokens", "retrieved_memories", "final_messages",
                "final_tokens") if ctx_stats.get(k) is not None}
        real = chat_usage.get("prompt_tokens")
        if real and int(real) > 0:
            payload["final_tokens"] = int(real)
        if payload:
            payload["display"] = context_display(
                payload.get("final_tokens"), payload.get("budget_tokens"))
            on_event("context.built", session=sess["id"], **payload)

    work_steps = 0
    iters = 0
    used_tools = []
    # JAG-129A: completion loop state (see keepgoing.decide).
    from . import keepgoing as _kg
    clear_abort(sess["id"])
    from . import runmetrics
    runmetrics.start(sess["id"], model=model)
    _abort_now = (lambda: _is_aborted(sess["id"]))  # JAG-129D: Stop kills the generation
    _kg_rounds = 0
    _kg_stop_reason = None
    _kg_prev = None
    _kg_stale = 0
    _fail_streak = 0        # JAG-178: consecutive failing tool calls
    _last_tool_hash = None  # JAG-178: detect a repeated identical call
    _tool_repeat = 0
    _last_failed_hash = None  # JAG-183: last FAILED (tool,args) -> verbatim re-run blocked
    _last_failed_err = ""
    _blocked_repeat = 0
    # JAG-272: a weak model can emit NONSENSE turns forever (malformed JSON /
    # unknown action / a bare promise). Without a cap it burned the whole iteration
    # budget. Stop after a few consecutive invalid turns with a clear reason.
    _invalid_streak = 0
    # JAG-189: a NEW user message must be able to supersede a stale plan. When
    # the turn OPENS with steps still open from an earlier request, do NOT force
    # the keepgoing loop back onto them — the model may simply answer the user.
    # The moment it re-engages the plan (write_todos/update_todos/replan_todos)
    # the flag clears and normal keepgoing resumes. Without this a fresh
    # instruction ("no todo list needed") was hijacked by the old list (session
    # a7d2794d8f88: "I'll continue on my own — 2/3 steps open" after a plain answer).
    try:
        _open0 = [n for n in (taskgraph.load(sess["id"]) or {}).get("nodes", [])
                  if n.get("status") in taskgraph.OPEN_STATUSES]
    except Exception:  # noqa: BLE001
        _open0 = []
    _user_pivot = bool(_open0)
    _pivot_state = {"synced": False}  # JAG-266: exactly one pivot sync round per turn
    _kg_started = time.time()
    _kg_last_tool = None
    _last_tool_ok = None
    # JAG-134/135: a SINGLE difficulty estimate (compute-optimal) feeds both the
    # best-of-N and the budget of the keepgoing rounds. The signals are the ones the harness
    # already has, recomputed on every round (a single estimator, no divergence).
    try:
        from . import difficulty as _diff
        _kg_base = int(_kg.cfg().get("keepgoing_max") or 0)
    except Exception:  # noqa: BLE001
        _diff, _kg_base = None, None

    def _diff_signals(_msg, _used, _stale=0):
        try:
            _nodes = (taskgraph.load(sess["id"]) or {}).get("nodes", [])
        except Exception:  # noqa: BLE001
            _nodes = []
        _open_n = len([n for n in _nodes if n.get("status") in taskgraph.OPEN_STATUSES])
        return {"open_nodes": _open_n,
                "msg_words": len(str(_msg).split()),
                "tool_count": len(_used or []),
                "prev_error": (_last_tool_ok is False),
                "prev_no_progress": bool(_stale)}

    _diff_level = None
    if _diff is not None:
        try:
            _diff_level = _diff.estimate(_diff_signals(message, [], 0))["level"]
        except Exception:  # noqa: BLE001
            _diff_level = None

    def _cur_node():
        """JAG-167: id of the todo node being worked on right now (first `doing`,
        else first open), so persisted cards/injects nest under the right in-chat
        node on reload. Returns None when the graph is empty or fully closed."""
        try:
            _g = taskgraph.load(sess["id"]) or {}
        except Exception:  # noqa: BLE001
            return None
        # JAG-194: only the CURRENT plan — an abandoned open node from an old plan
        # must not capture a card/reply that belongs to the new task.
        for _st in ("doing", "todo", "blocked"):
            for _n in taskgraph.plan_nodes(_g):
                if _n.get("status") == _st:
                    return _n.get("id")
        return None

    def _after():
        """JAG-192: the transcript boundary a persisted card/inject belongs to.

        The turn's agentic history lives in the local `msgs` list and is flushed
        into `sess["messages"]` only at the END of the turn. So the boundary is
        the transcript length BEFORE the turn plus the messages already emitted
        this turn: `len(sess["messages"]) + (len(msgs) - _turn_base)`. Using only
        `len(sess["messages"])` (the old behaviour) froze every card of the turn
        on the same index and a reload stacked the whole turn at the top.
        """
        return len(sess.get("messages", [])) + (len(msgs) - _turn_base)

    def _inject(content, kind):
        """JAG-166: add a synthetic message to the LLM context AND surface it.

        The harness is the model's secretary: every nudge, observation and
        'continue' it feeds back is ALSO emitted as `harness.inject`, so the chat
        can show exactly what was injected — nothing is hidden.
        """
        msgs.append(harness_wrap(content))  # JAG-266: tag harness turns
        # NOTE: the payload key must NOT be `kind` — the SSE emitters take the
        # event name as a positional `kind`, so a `kind` kwarg collides.
        on_event("harness.inject", session=sess["id"], inject_kind=kind, text=content)
        # JAG-167: persist the injection so a reload rebuilds the in-chat tree.
        # The 'system' prompt is re-published every turn and is transient by
        # design → it is NOT persisted (avoids N identical copies in history).
        if kind != "system":
            persist_inject(sess, kind, content, node=_cur_node(), after=_after())

    # JAG-166: publish the assembled system prompt once per turn (collapsed in the
    # UI), so the operator can read the real prompt the model received.
    try:
        if msgs and msgs[0].get("role") == "system":
            _sys_txt = msgs[0].get("content") or ""
            _h = hash(_sys_txt)
            if _LAST_SYS_INJECT.get(sess["id"]) != _h:
                _LAST_SYS_INJECT[sess["id"]] = _h
                on_event("harness.inject", session=sess["id"], inject_kind="system",
                         text=_sys_txt)
    except Exception:  # noqa: BLE001 — must never break the turn
        pass
    # JAG-170: buffer the live reasoning so each persisted tool card carries the
    # chain-of-thought that led to it — otherwise the COTs between tool calls
    # vanish on reload (they were only ever streamed, never stored).
    _think_buf = {"t": ""}
    while iters < CHAT_TOOL_MAX_ITERS:
        iters += 1
        # JAG-164: the tool budget is PER keepgoing round, not per turn. Before
        # this the turn hard-stopped the moment `work_steps` hit `max_steps`
        # (8 real tool calls) — the loop exited, the forced-final path produced a
        # prose answer and the persistent todos stayed stuck in 'doing' (session
        # 66c66e3c702d: 8 shells, answer "…scaffold incompleto", n2 never closed).
        # Now, when the budget is spent with OPEN steps, the continuation loop
        # decides: refill the budget and push the model to close every step with
        # evidence, or stop for a typed reason (budget/no_progress/blocked).
        if tool_ctx and work_steps >= max_steps:
            _g = taskgraph.load(sess["id"]) or {}
            _nodes = _g.get("nodes", [])
            _open = [n for n in _nodes if n.get("status") in taskgraph.OPEN_STATUSES]
            # JAG-344: a PLAN-ONLY turn never continues. The master's own todos are
            # its DELEGATION plan, not work for it to close itself; the continuation
            # loop would otherwise nag it ("close every step with evidence") into
            # doing the whole job, bypassing the team. Stop here with a typed reason.
            if plan_only:
                _kg_stop_reason = "plan_only"
                on_event("plan.stopped", session=sess["id"], reason="plan_only",
                         open=len(_open), total=len(_nodes), rounds=_kg_rounds,
                         difficulty=_diff_level, duration_s=round(time.time() - _kg_started, 1))
                break
            _cur = _kg.state_hash(_nodes)
            # JAG-268: only a truly idle round (no tool AND no list change) is stale.
            _kg_stale = _next_stale(_kg_stale, _kg_prev, _cur, work_steps > 0)
            _kg_override = None
            if _diff is not None and _kg_base:
                try:
                    _kg_override = {"keepgoing_max": _diff.rounds_for(
                        _kg_base, _diff_signals(message, used_tools, _kg_stale))}
                except Exception:  # noqa: BLE001
                    _kg_override = None
            _dec = _kg.decide(open_nodes=len(_open), rounds=_kg_rounds, stale=_kg_stale,
                              started=_kg_started, aborted=_is_aborted(sess["id"]),
                              blocked=any(n.get("status") == "blocked" for n in _nodes),
                              steer=has_steer(sess["id"]), override=_kg_override)
            _dec = _pivot_decide(_user_pivot, _dec, len(_open), _pivot_state)
            if not _dec["continue"]:
                _kg_stop_reason = _dec["reason"]
                on_event("plan.stopped", session=sess["id"], reason=_dec["reason"],
                         open=len(_open), total=len(_nodes), rounds=_kg_rounds,
                         difficulty=_diff_level, duration_s=round(time.time() - _kg_started, 1))
                break
            _kg_rounds += 1
            _kg_prev = _cur
            work_steps = 0  # grant another round of tool calls
            on_event("plan.continuing", session=sess["id"], round=_kg_rounds,
                     open=len(_open), total=len(_nodes), difficulty=_diff_level)
            if _dec.get("reason") == "pivot_sync":
                _inject(_pivot_sync_text(len(_open), _open_todo_brief(sess)[1]), "pivot")
            else:
                _inject(
                    "CONTINUE — %d task(s) are still OPEN (the full list is in "
                    "'Harness state' at the end of your message). Work ONE step at a time: mark the current "
                    "step 'doing', do the work with a tool call, then mark it 'done' with "
                    "the concrete evidence via update_todos. Never redo a step already "
                    "marked [x]. Open now:\n%s"
                    % (len(_open), _open_todo_brief(sess)[1]), "continue")
            continue
        # JAG-127b: inject any steering message typed while this turn was running.
        for _s in drain_steer(sess["id"]):
            msgs.append({"role": "user", "content":
                         "[user steering — take this into account now] " + _s})
            on_event("chat.steer", session=sess["id"], text=_s, applied=True)
        collected = []

        def _capture(ch, t, _c=collected):
            # JAG-65: stream the model's REASONING live, so a tool-calling turn
            # shows progress instead of dead air; buffer only answer text so raw
            # tool-call JSON is never streamed to the user.
            if ch == "think":
                _think_buf["t"] += t   # JAG-170: remembered for the next card
                on_delta("think", t)
            else:
                _c.append((ch, t))

        answer, think, model = stream_with_fallback(msgs, model, "chat", _capture,
                                                    usage=chat_usage, cancel=_abort_now)
        _record_usage()
        _emit_context()  # JAG-98: live meter now uses the model's real count
        if _is_aborted(sess["id"]):
            # JAG-129D: Stop interrupted the generation. No tool may run
            # after an abort: the turn is closed immediately with an explicit outcome.
            publish("chat.interrupted", session=sess["id"])
            # JAG-175: an abort can cut the model mid tool-call, so the buffered
            # answer may be RAW tool-call JSON. Never stream/persist that as the
            # user's reply — fall back to a neutral stop note.
            if answer and not _looks_like_json_action(answer):
                for ch, t in collected:
                    on_delta(ch, t)
                final_answer = answer
            else:
                final_answer = "⏹ Interrupted by the user."
                on_delta("answer", final_answer)
            _kg_stop_reason = "user_stop"
            break
        # JAG-132/134: adaptive best-of-N. Only when the first sample is NOT usable
        # (malformed tool-call JSON) are more samples spent and the
        # best picked with the deterministic ranker (prm.rank_text). N grows with the
        # estimated task difficulty (compute-optimal). n=1 -> zero overhead.
        try:
            from . import bestofn as _bn
            _bN = _bn.n_of(signals=_diff_signals(message, used_tools, _kg_stale))
        except Exception:  # noqa: BLE001
            _bN = 1
        if _bN > 1 and _looks_like_json_action(answer):
            _cands = [answer]
            for _ in range(_bN - 1):
                try:
                    _a2, _t2, _m2 = stream_with_fallback(
                        msgs, model, "chat", lambda ch, t: None,
                        usage=chat_usage, cancel=_abort_now)
                except Exception:  # noqa: BLE001
                    break
                _cands.append(_a2)
                if (_a2 or "").strip() and not _looks_like_json_action(_a2):
                    break  # a usable candidate already exists: stop spending compute
            _best, _scores = _bn.choose(_cands)
            if _best is not None and _best != answer:
                on_event("bestofn.chosen", session=sess["id"], n=len(_cands),
                         scores=[round(s, 3) for _, s in _scores])
                answer = _best
        act = _normalize_action(extract_json(answer))
        if isinstance(act, dict) and act.get("action") == "write_todos":
            _user_pivot = False   # JAG-189: the model re-engaged the plan
            n = _apply_chat_todos(sess, act, on_event, after=_after())
            _invalid_streak = 0
            msgs.append({"role": "assistant", "content": answer})
            _on, _brief = _open_todo_brief(sess)
            _inject(
                "Task list saved (%d new step(s)) — it is YOURS to keep current. "
                "OPEN (%d):\n%s\nA step must describe work STILL TO DO: if you already "
                "did that work in this turn, mark it 'done' NOW with the concrete evidence "
                "— never leave finished work as an open step. Otherwise start with the "
                "FIRST open step: mark it 'doing' before you start it, do the work, then "
                "'done' with concrete evidence."
                % (n, _on, _brief), "nudge")
            continue
        if isinstance(act, dict) and act.get("action") in ("update_todos", "replan_todos"):
            # JAG-75: the model advances its own plan mid-run (in_progress → done
            # with evidence), or briefly re-plans. Then it must resume the plan.
            _user_pivot = False   # JAG-189: the model re-engaged the plan
            _invalid_streak = 0
            _node_here = _cur_node()   # JAG-190: nest the card where it happened
            if act["action"] == "update_todos":
                _apply_chat_todo_updates(sess, act, on_event, node=_node_here,
                                         after=_after())
                nudge = _nudge_open_todos(sess)
            else:
                _apply_chat_replan(sess, act, on_event, node=_node_here,
                                   after=_after())
                nudge = ("Plan updated. Now resume following the plan from where you "
                         "left off; do not re-plan again unless something really changed.")
            msgs.append({"role": "assistant", "content": answer})
            _inject(nudge, "nudge")
            continue
        if isinstance(act, dict) and act.get("action") == "subagent":
            # JAG-189: synchronous delegation — spawn ONE child run, wait for it,
            # feed its summary back. Counts as a real work step (it is real work).
            if plan_only:
                # JAG-344: the master's plan turn must not spawn subagents either.
                msgs.append({"role": "assistant", "content": answer})
                _inject("SYSTEM (harness) — PLAN-ONLY turn: spawning subagents is not "
                        "allowed while planning. Record the plan and stop.", "nudge")
                work_steps += 1
                continue
            work_steps += 1
            used_tools.append("subagent")
            _th = str(act.get("thought") or "").strip()
            if _th:
                _think_buf["t"] += _th + "\n"
                on_delta("think", _th + "\n")
            obs = _apply_chat_subagent(sess, act, on_event, node=_cur_node(),
                                       after=_after())
            msgs.append({"role": "assistant", "content": answer})
            _inject(obs + "\n\nContinue: call the next tool, or report the result.",
                    "observation")
            continue
        tc = _chat_tool_call(act, api_v02) if tool_ctx else None
        if tc:
            # JAG-127b: surface the model's own `thought` for this step as a
            # "think" delta BEFORE the tool card — otherwise, with models that do
            # not emit reasoning_content, the chat showed tool cards back-to-back
            # with no visible reasoning in between ("I don't see thinking").
            _th = str((act or {}).get("thought") or "").strip()
            if _th:
                _think_buf["t"] += _th + "\n"   # JAG-170: kept with the card
                on_delta("think", _th + "\n")
            tool, args = tc
            # JAG-344: a PLAN-ONLY turn may INSPECT (fs.read / skills) but NEVER mutate.
            # Refuse shell / fs.write / fs.edit / … so the master cannot execute the
            # teammates' work; hand back a directive to plan and stop.
            if plan_only and tool not in PLAN_ONLY_TOOLS:
                msgs.append({"role": "assistant", "content": answer})
                _inject(_plan_only_refusal(tool), "nudge")
                work_steps += 1
                continue
            # JAG-183: HARD anti-loop guard. An IDENTICAL call that already FAILED
            # is NOT executed again: it burned the step budget and led to a resigned
            # stop (v176: 3x `adb ... input tap` -> exit 1 -> "mi fermo"). We refuse
            # it and hand back a directive so the model MUST change route, read a
            # skill, or ask ONE precise question.
            _call_h = _kg.tool_hash(tool, args)
            if _call_h == _last_failed_hash:
                _blocked_repeat += 1
                msgs.append({"role": "assistant", "content": answer})
                _inject(_repeat_block_note(tool, _last_failed_err, _blocked_repeat,
                                           _skill_hints(tool + " " + (_last_failed_err or ""))),
                        "nudge")
                continue
            work_steps += 1
            used_tools.append(tool)
            on_event("tool.call", session=sess["id"], tool=tool, args=args, inline=True)
            try:
                # JAG-80: a `required` tool must never freeze the turn. We wait a
                # SHORT, bounded time (CHAT_APPROVAL_WAIT) so a quick tap on the
                # inline Approve card still executes the tool; if nobody decides,
                # the model gets an observation and continues. The old code waited
                # the full 300s and the mobile SSE died = "si blocca".
                res = api_v02.gated_call(tool, args, run_id=sess["id"],
                                         timeout=CHAT_APPROVAL_WAIT,
                                         workspace=_chat_workspace(sess),
                                         obs_max=CHAT_OBS_FULL)
                status = res.get("status")
                obs = res.get("observation") or res.get("error") or res.get("status") or ""
                if status in ("pending", "expired"):
                    rec = res.get("approval") or {}
                    obs = ("Action '%s' NOT executed: approval %s (id %s). The card is "
                           "in the chat: the user can approve it and retry, or tell me "
                           "to proceed. Do NOT repeat the same call now; continue "
                           "with something else or explain to the user what is needed."
                           % (tool, status, rec.get("id", "?")))
                elif status == "denied":
                    obs = "Action '%s' DENIED by the user." % tool
                ok = status == "executed"
                sub = res.get("result") or {}
                # JAG-178: `ok` means "the tool executed"; a tool can execute and
                # still FAIL (nonzero exit / ok:false). Track failure separately.
                _tool_failed = ((not ok) or (sub.get("ok") is False)
                                or (sub.get("exit_code") not in (None, 0)))
                # JAG-96: persist the card so cold-start UIs rebuild the transcript.
                persist_tool_card(sess, tool, ok, args=args,
                                  result=sub.get("stdout") or obs or "",
                                  error=sub.get("stderr") or "",
                                  exit_code=sub.get("exit_code"),
                                  backend=sub.get("backend") or "harness",
                                  node=_cur_node(), think=_think_buf["t"].strip(),
                                  after=_after())
                _think_buf["t"] = ""   # JAG-170: fresh CoT for the next action
                on_event("tool.result", session=sess["id"], **_tool_event(
                    tool, ok, args=args, output=(sub.get("stdout") or obs or ""),
                    exit_code=sub.get("exit_code"),
                    backend=sub.get("backend") or "harness",
                    inline=True, summary=("error" if not ok else "")))
            except Exception as e:  # noqa: BLE001 — a tool failure must not kill chat
                obs, ok = "tool error: %s" % e, False
                _tool_failed = True   # JAG-178: a raised tool error is a failure too
                persist_tool_card(sess, tool, False, args=args, error=str(e)[:200],
                                  backend="harness", node=_cur_node(),
                                  think=_think_buf["t"].strip(), after=_after())
                _think_buf["t"] = ""
                on_event("tool.result", session=sess["id"], **_tool_event(
                    tool, False, args=args, output=str(e)[:200],
                    backend="harness", inline=True, summary="error"))
            # JAG-134: feeds the prev_error signal of the difficulty estimate.
            _last_tool_ok = bool(ok)
            _invalid_streak = 0
            # JAG-88: an oversized observation goes to a file (referenced) rather
            # than being truncated into the context — nothing is lost.
            obs = str(obs)
            # JAG-178: track consecutive failures + repeated identical calls, and
            # COACH a stuck model (socratic) instead of the generic continue.
            if _call_h == _last_tool_hash:
                _tool_repeat += 1
            else:
                _tool_repeat = 0
            _last_tool_hash = _call_h
            _fail_streak = (_fail_streak + 1) if _tool_failed else 0
            # JAG-183: remember the (tool,args) of a FAILED call so the next verbatim
            # re-issue is blocked (a SUCCESS clears it — only failed calls are frozen).
            if _tool_failed:
                _last_failed_hash = _call_h
                _last_failed_err = obs[:300]
            else:
                _last_failed_hash = None
            if len(obs) <= CHAT_TOOL_OBS_LIMIT and (_fail_streak >= 2 or _tool_repeat >= 1):
                note = _stuck_note(tool, obs, _fail_streak, _tool_repeat,
                                   _skill_hints(tool + " " + obs))
            elif len(obs) > CHAT_TOOL_OBS_LIMIT:
                note = _offload_observation(sess, tool, obs)
            else:
                note = ("Observation for tool %s:\n%s\n\n"
                        "Continue: call the next tool, or report the result. Keep your "
                        "task list current (mark a finished step done with evidence)."
                        % (tool, obs))
            msgs.append({"role": "assistant", "content": answer})
            _inject(note, "observation")
            continue
        if _term_action(act):
            # JAG-278: a made-up "I am done" envelope — take its text as the answer.
            _txt = ""
            for _k in ("text", "content", "answer", "message", "reply", "output", "result"):
                if isinstance(act.get(_k), str) and act[_k].strip():
                    _txt = act[_k].strip()
                    break
            if _txt:
                final_answer = _txt
                on_delta("answer", _txt)
                break
        if isinstance(act, dict) and act:
            if not _looks_like_action_dict(act):
                # JAG-304: a JSON OBJECT with no action/tool key is an ARTIFACT the
                # model means as its answer (a schema, a response envelope, a data
                # record) — surface it instead of rejecting it as a stray action.
                # That rejection forced needless "not a valid action" retries and
                # could halt the turn after four in a row (observed on J2: the
                # coordinator's own Book JSON-Schema deliverable was rejected).
                final_answer = answer
                _final_is_artifact = True
                on_delta("answer", answer)
                break
            # stray JSON the model emitted in a schema we do not recognise: never
            # show it to the user — nudge it back to a valid tool call or prose.
            msgs.append({"role": "assistant", "content": answer})
            _invalid_streak += 1
            if _invalid_streak >= 4:
                _kg_stop_reason = "no_valid_action"
                on_event("plan.no_valid_action", session=sess["id"], streak=_invalid_streak)
                break
            try:
                _snip = json.dumps(act, ensure_ascii=False)[:220]
            except Exception:  # noqa: BLE001
                _snip = str(act)[:220]
            _inject(
                "That was not a valid action. You emitted: " + _snip + "\n"
                'Emit either {"action":"tool","tool":"<name>","args":{...}} for a real '
                "tool, a top-level harness action (write_todos / update_todos / "
                "replan_todos), or answer the user in plain prose (no JSON).", "retry")
            continue
        if _looks_like_json_action(answer):
            # JAG-64: malformed/TRUNCATED tool-call JSON (extract_json failed, so
            # `act` is None). Never leak it into the chat — ask for a clean retry.
            msgs.append({"role": "assistant", "content": answer})
            _invalid_streak += 1
            if _invalid_streak >= 4:
                _kg_stop_reason = "no_valid_action"
                on_event("plan.no_valid_action", session=sess["id"], streak=_invalid_streak)
                break
            _inject(
                "That JSON was invalid or incomplete (it did not parse). "
                "Re-emit a VALID "
                '{"action":"tool","tool":"<name>","args":{...}} with all '
                "braces closed, or answer the user in plain prose. Never "
                "show JSON to the user.", "retry")
            continue
        if _looks_like_promise(answer) and not announce_nudged:
            # JAG-74: the model promised an action ("I'll load another skill…") but
            # called no tool this turn — nudge it ONCE to actually act or conclude.
            announce_nudged = True
            msgs.append({"role": "assistant", "content": answer})
            _inject(
                "You announced an action but did not call any tool. Either "
                'call it NOW with {"action":"tool","tool":"<name>","args":{...}}, '
                "or — if there is nothing left to do — reply with the final "
                "result in plain prose. Do not just repeat the announcement.", "nudge")
            continue
        if tool_ctx:
            # JAG-129A: the harness (the "secretary") decides whether the agent can really
            # close. With open steps it re-injects the list and CONTINUES.
            # JAG-173 (rev): the MODEL owns the todo list — the standard contract
            # (Claude Code TodoWrite): the agent marks a step 'doing' before it
            # starts and 'done' with evidence when it is really finished. The harness
            # only ENFORCES and REMINDS; it never auto-closes a step, because closing
            # a step that is not truly done is "lying about completion".
            _g = taskgraph.load(sess["id"]) or {}
            _nodes = _g.get("nodes", [])
            _open = [n for n in _nodes if n.get("status") in taskgraph.OPEN_STATUSES]
            _cur = _kg.state_hash(_nodes)
            # JAG-268: see the note at the budget branch — a round that ran tools is
            # NOT 'no progress' just because the list hash did not move.
            _kg_stale = _next_stale(_kg_stale, _kg_prev, _cur, work_steps > 0)
            # JAG-134: continuation budget recomputed from the current signals.
            _kg_override = None
            if _diff is not None and _kg_base:
                try:
                    _kg_override = {"keepgoing_max": _diff.rounds_for(
                        _kg_base, _diff_signals(message, used_tools, _kg_stale))}
                except Exception:  # noqa: BLE001
                    _kg_override = None
            _dec = _kg.decide(open_nodes=len(_open), rounds=_kg_rounds, stale=_kg_stale,
                              started=_kg_started, aborted=_is_aborted(sess["id"]),
                              blocked=any(n.get("status") == "blocked" for n in _nodes),
                              steer=has_steer(sess["id"]), override=_kg_override)
            # JAG-266: on a pivot, grant ONE sync round (remind the model it left
            # todos open) instead of stopping silently; after it, stop as user_pivot.
            _dec = _pivot_decide(_user_pivot, _dec, len(_open), _pivot_state)
            # JAG-171: with autocontinue OFF the harness does not insist — the
            # first stop with OPEN todos goes straight to the human gate.
            # JAG-266: but never suppress the single pivot sync round.
            if (_open and _dec.get("reason") != "pivot_sync"
                    and not bool((_kg.cfg(_kg_override) or {}).get("autocontinue", True))):
                _dec = {"continue": False, "reason": "need_input"}
            if _dec["continue"]:
                _kg_rounds += 1
                _kg_prev = _cur
                for _s in drain_steer(sess["id"]):
                    msgs.append({"role": "user", "content":
                                 "[user steering — take this into account now] " + _s})
                    on_event("chat.steer", session=sess["id"], text=_s, applied=True)
                on_event("plan.continuing", session=sess["id"], round=_kg_rounds,
                         open=len(_open), total=len(_nodes), difficulty=_diff_level)
                msgs.append({"role": "assistant", "content": answer})
                if _dec.get("reason") == "pivot_sync":
                    _inject(_pivot_sync_text(len(_open), _open_todo_brief(sess)[1]), "pivot")
                else:
                    _inject(
                        "CONTINUE — your TASK LIST still has %d open step(s), and it is "
                        "YOURS (the full list is in 'Harness state' at the end of your message): mark the step "
                        "you are working on 'doing', and when it is REALLY finished mark it "
                        "'done' with the concrete evidence (the command you ran and its "
                        "result) via update_todos. One step at a time. NEVER redo a step "
                        "already marked [x]. Open now:\n%s"
                        % (len(_open), _open_todo_brief(sess)[1]), "continue")
                continue
            _kg_stop_reason = _dec["reason"]
            on_event("plan.stopped", session=sess["id"], reason=_dec["reason"],
                     open=len(_open), total=len(_nodes), rounds=_kg_rounds,
                     difficulty=_diff_level,
                     duration_s=round(time.time() - _kg_started, 1))
            # JAG-171: HUMAN IN THE LOOP — never end on prose with open todos; ask
            # the operator how to proceed (continue / close / replan / stop).
            # JAG-189: but NOT on a user_pivot stop — the user is actively
            # chatting, so the reply is theirs; the paused plan needs no gate.
            # JAG-295: and NEVER on a headless turn (a JOB/routine, autonomous):
            # there is nobody to answer, so the turn just stops.
            if _kg.hitl_gate(_dec["reason"], _open, autonomous):
                _hitl = {"reason": _dec["reason"],
                         "open": [{"id": n.get("id"), "label": n.get("label", "")}
                                  for n in _open[:8]]}
                on_event("hitl.request", session=sess["id"], reason=_dec["reason"],
                         open=_hitl["open"], total=len(_nodes), rounds=_kg_rounds)
        for ch, t in collected:
            on_delta(ch, t)
        final_answer, think = answer, think
        break
    if not final_answer and not _is_aborted(sess["id"]):
        # JAG-78b: the loop ran out of tool steps without a prose answer — force
        # one, but BUFFER it. Streaming it live leaked raw tool-call JSON into
        # the user's chat bubble when the model kept acting instead of answering
        # (the JSON guard below only protected the PERSISTED text, not the stream).
        # JAG-84: a forced "final" that is only an ANNOUNCEMENT ("I'm proceeding with…") is
        # not an answer — retry (bounded) asking for the RESULT, not a promise.
        _inject(
            "Answer the user now in plain text. Do not emit JSON, and do NOT "
            "announce future work: report the RESULT you already have (what "
            "you did, what you found, what is still missing).", "final")
        for _try in range(3):
            forced = []

            def _cap_final(ch, t, _c=forced):
                if ch == "think":
                    on_delta("think", t)
                else:
                    _c.append((ch, t))

            final_answer, think, model = stream_with_fallback(msgs, model, "chat",
                                                              _cap_final, usage=chat_usage,
                                                              cancel=_abort_now)
            _record_usage()
            if ((final_answer or "").strip() and not _looks_like_json_action(final_answer)
                    and not _looks_like_promise(final_answer)):
                for ch, t in forced:  # only a REAL reply reaches the user live
                    on_delta(ch, t)
                break
            msgs.append({"role": "assistant", "content": final_answer or ""})
            _inject(
                "That was still an announcement/JSON, not a result. Give the "
                "final RESULT in plain prose now.", "final")
        else:
            # last resort: stream whatever prose we have (never leak JSON)
            if final_answer and not _looks_like_json_action(final_answer):
                for ch, t in forced:
                    on_delta(ch, t)
    answer = final_answer or answer
    if trace:
        trace.span("llm.chat", model=model, context=ctx_stats)
        trace.llm_call(msgs, answer + think)
    meta = {"model": model, "node": _cur_node()}
    content = answer.strip()
    if _hitl:
        # JAG-171: the turn stopped with open todos → the visible reply is the
        # human gate, not the model's prose report.
        content = ("⏸ In pausa: ci sono %d passi aperti e serve la tua scelta "
                   "(vedi la card HUMAN IN THE LOOP)." % len(_hitl["open"]))
        meta = {"model": model, "hitl": True, "node": _cur_node(),
                "open": len(_hitl["open"]), "reason": _hitl["reason"],
                "hitl_open": _hitl["open"]}   # JAG-295: replayable card payload
    if (_looks_like_json_action(content) and not _final_is_artifact) or not content:
        # JAG-64/78b: last-resort guard — never show/persist raw tool-call JSON
        # (or an empty turn). Summarise the plan state instead of leaking JSON.
        # JAG-304: a confirmed JSON artifact (checked via _looks_like_action_dict)
        # is the model's ANSWER and must pass this guard untouched.
        try:
            _g = taskgraph.load(sess["id"])
            _nodes = (_g or {}).get("nodes", [])
            _done = sum(1 for x in _nodes if x.get("status") == "done")
        except Exception:  # noqa: BLE001
            _nodes, _done = [], 0
        content = (("Plan updated: %d/%d steps completed. Tell me how to proceed "
                    "or let me continue." % (_done, len(_nodes))) if _nodes else "Done.")
        meta = {"model": model, "synthesised": True,
                "reason": "model emitted JSON instead of a prose reply"}
    # JAG-172: PERSIST the agentic history of this turn (tool calls, observations,
    # nudges) into the transcript. Before, only the final assistant reply was
    # stored, so every tool observation was discarded at the turn boundary: the
    # model lost its own work between turns and the ctx meter measured a prompt
    # that never grew (session test: 15 msgs / 5 KB vs 161 tool cards → a
    # genuinely full context read as 2%). Marked `internal` so the UI keeps
    # rendering these from tool_cards/injects (no duplicate bubbles) while
    # `context_engine` still counts them and `_completion_body` filters the
    # marker out before the provider call.
    try:
        _extra = [dict(_m, internal=True) for _m in msgs[_turn_base:]
                  if isinstance(_m, dict) and _m.get("role") in ("user", "assistant")]
        if _extra:
            sess.setdefault("messages", []).extend(_extra)
            save_session(sess)
    except Exception:  # noqa: BLE001 — persistence must never break a turn
        pass
    reply = append_message(sess, "assistant", content, reasoning=think.strip() or None,
                           meta=meta)
    try:
        runmetrics.finish(sess["id"], outcome=("user_abort" if _is_aborted(sess["id"]) else "done"),
                          stop_reason=_kg_stop_reason, iterations=_kg_rounds,
                          steps=work_steps,
                          prompt_tokens=int(chat_usage.get("prompt_tokens") or 0),
                          completion_tokens=int(chat_usage.get("completion_tokens") or 0),
                          tokens=int(chat_usage.get("prompt_tokens") or 0)
                                 + int(chat_usage.get("completion_tokens") or 0),
                          model=model, difficulty=_diff_level)
        publish("run.metrics", session=sess["id"], metrics=runmetrics.get(sess["id"]))
    except Exception:  # noqa: BLE001 — metrics must never break a turn
        pass
    publish("chat.done", session=sess["id"], message_id=len(sess["messages"]),
            model=model, think_chars=len(think), error=bool(meta.get("error")))
    try:  # JAG-133: records the turn's tool sequence for skill mining
        from . import selfevolve as _se
        if used_tools:
            # per-TURN key (not per-session): so mining sees sequences
            # repeated across different runs instead of always overwriting the same record.
            _se.record("%s#%.3f" % (sess["id"], time.time()), used_tools)
    except Exception:  # noqa: BLE001 — history must never break a turn
        pass
    # JAG-128B: end-of-turn nudge — when the turn used many tools (or
    # errored), it invites evaluating what to persist (free memory or
    # a rule proposal via the `improve` tool). Never blocking: any
    # exception is swallowed so it does not break the turn.
    try:
        from . import improve as improve_mod
        if improve_mod.should_nudge(used_tools=len(used_tools or []),
                                    errored=bool(meta.get("error"))):
            publish("improve.nudge", session=sess["id"],
                    hint="evaluate what to persist: memory (free) or rule proposal (improve tool)")
    except Exception:  # noqa: BLE001 — the nudge must never break a turn
        pass
    # JAG-129A: safety net — if the turn ends with open steps (e.g. after
    # an abort), it still publishes the end-of-turn metrics. `plan.incomplete`
    # coexists with `plan.stopped` emitted by the loop.
    try:
        _g = taskgraph.load(sess["id"])
        _nodes = (_g or {}).get("nodes", [])
        # JAG-308: count only TRULY-open steps. `status not in ("done","cancelled")`
        # also counted `superseded` (a CLOSED state), so a session whose every step
        # was closed still reported "N open" and re-nagged on the next turn.
        _open = [n for n in _nodes if n.get("status") in taskgraph.OPEN_STATUSES]
        if _open:
            publish("plan.incomplete", session=sess["id"], open=len(_open),
                    total=len(_nodes),
                    items=[str(n.get("label", "")) for n in _open][:12])
    except Exception:  # noqa: BLE001
        pass
    try:  # JAG-69: deterministic Stop hooks at the end of the turn
        from . import hooks
        hooks.run("Stop", run_id=sess["id"], observation=content)
    except Exception:  # noqa: BLE001 — a hook must never break a turn
        pass
    # JAG-93: post-turn reflection (self-improvement). Runs after the reply is
    # persisted so it can never delay or corrupt the user-visible turn.
    try:
        maybe_reflect(sess, message, answer, work_steps > 0, model)
    except Exception:  # noqa: BLE001
        pass
    return reply, model


def generate_plan(goal, model=None):
    sess = {"id": "planner", "title": "planner", "created": time.time(), "messages": []}  # ephemeral
    sys = system_prompt() + "\n\n" + PLANNER_PROMPT
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
                 "complete_task", "subagent", "note", "finish")

AGENT_PROMPT = (
    "You are the agent loop of the SparkForge harness. Given the goal and the "
    "current harness state, decide ONE next action. Respond with ONLY a JSON "
    'object: {"thought": "<brief reasoning>", "action": "write_todos|'
    'plan_step|complete_plan_step|add_task|complete_task|subagent|note|finish", '
    '"todos": [{"label": "...", "deps": []}] (for write_todos), '
    '"title": "<for plan_step/add_task>", "id": "<for '
    'complete_plan_step/complete_task>", "detail": "<optional>", '
    '"goal": "<the subtask>" and "max_steps": 4 (for subagent — delegate ONE '
    'self-contained subtask to a child run and get its summary back), '
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
    if action == "subagent":
        goal = str(act.get("goal") or act.get("detail") or "").strip()
        if not goal:
            return "subagent error: goal required"
        try:
            max_steps = int(act.get("max_steps", 4))
        except (TypeError, ValueError):
            max_steps = 4
        from . import subagent as _sub
        result = _sub.spawn(goal, parent_run_id=run_id, max_steps=max_steps,
                            model=act.get("model"),
                            depth=_sub.depth_of(run_id) + 1)
        if result.get("error"):
            return "subagent error: %s" % result["error"]
        if run_id:
            try:
                graph = taskgraph.ensure(run_id, session_id=session)
                taskgraph.add_node(graph, goal, source="subagent",
                                   child_run_id=result["run_id"])
            except Exception as e:  # noqa: BLE001 — linking must never break a run
                publish("graph.error", run=run_id, error=str(e))
        return "subagent spawned: %s (goal: %s, max_steps=%d)" % (
            result["subagent_id"], goal[:80], max_steps)
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


def _agent_history(actions, limit=8):
    """JAG-348: the agent loop's OWN recent steps as text for the next iteration.

    The chat loop learned this the hard way (JAG-61): the observation produced at
    step N MUST be visible at step N+1, or the model re-derives everything, never
    learns a tool/subagent result, cannot correct a rejected action and loops
    forever. The agent loop rebuilt its messages from scratch every iteration and
    dropped every observation -> an open loop. This renders the recent history.
    """
    if not actions:
        return ""
    rows = []
    for a in actions[-limit:]:
        txt = (a.get("observation") or a.get("summary") or "").strip()
        rows.append("  %s. %s -> %s" % (a.get("i", "-"), a.get("action", "?"), txt[:300]))
    return ("\n\nYour previous steps (build on these; do NOT repeat a step that "
            "already failed):\n" + "\n".join(rows))


def agent_run(goal, max_steps=6, model=None, on_event=None, trace=None, run_state=None,
              workspace=None):
    """Sense-think-act loop. No shell, no filesystem writes except harness stores."""
    if on_event is None:
        on_event = lambda kind, **d: publish(kind, **d)
    model = model or default_model()
    # JAG-111: every run is abortable via /api/agent/control, and its id travels
    # in `agent.start` so the WebUI/app stop button can target it.
    st = run_state or api_v02.new_run(goal, model, max_steps)
    on_event("agent.start", goal=goal, max_steps=max_steps, run=st.id, model=model)
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
    aborted = False
    rb = rules_context(ws=workspace)  # JAG-114/115: the agent loop honours the same rules
    from . import prompt as prompt_mod  # JAG-128A: prompt-map + capability in the agent loop too
    try:
        for i in range(max_steps):
            api_v02.checkpoint(st)  # JAG-111: honour pause / abort between steps
            sys = (prompt_mod.prompt_map_text() + "\n\n" + prompt_mod.capability_text()
                   + "\n\n" + system_prompt() + "\n\n" + self_summary() + "\n\n" + AGENT_PROMPT
                   + "\n\n" + RULES_POLICY + ("\n" + rb if rb else ""))
            # JAG-276: the live task list rides in the user turn, not the system prompt.
            # JAG-348: ALSO carry the agent's own previous steps + observations, so the
            # model learns from a tool/subagent result and can correct a rejected action
            # instead of re-deriving the same mistake every iteration (open loop).
            msgs = [{"role": "system", "content": sys},
                    {"role": "user", "content": "Goal: %s (iteration %d/%d)\n\n%s%s"
                     % (goal, i + 1, max_steps, state_block(graph_key=trace.id),
                        _agent_history(actions))}]
            on_event("agent.iteration", i=i + 1, of=max_steps)
            answer, think = _router_stream(msgs, model, lambda ch, t: on_event("agent.think", channel=ch, text=t))
            _llm(msgs, answer + think)
            act = _normalize_action(extract_json(answer)) or {}
            if not isinstance(act, dict) or not act.get("action"):
                act = {"thought": answer[:200], "action": "note", "detail": answer[:400]}
            thought = str(act.get("thought", ""))[:400]
            action = act.get("action")
            on_event("agent.thought", i=i + 1, thought=thought, action=action)
            if action == "finish":
                summary = str(act.get("summary", ""))[:600]
                on_event("agent.finish", summary=summary)
                actions.append({"i": i + 1, "thought": thought, "action": "finish", "summary": summary})
                st.status = "done"
                st.summary = summary
                break
            obs = apply_agent_action(act, run_id=trace.id)
            trace.span("agent.action", i=i + 1, action=action, observation=obs)
            on_event("agent.observation", i=i + 1, observation=obs)
            actions.append({"i": i + 1, "thought": thought, "action": action, "observation": obs})
        else:
            summary = "stopped at max_steps=%d; see trace" % max_steps
            on_event("agent.finish", summary=summary)
            actions.append({"action": "finish", "summary": summary})
            st.status = "done"
            st.summary = summary
    except api_v02.AbortRun:
        aborted = True
        summary = "aborted by operator"
        on_event("agent.aborted", run=st.id)
        on_event("agent.finish", summary=summary)
        actions.append({"action": "finish", "summary": summary})
        st.status = "aborted"
        st.summary = summary
    st.trace = actions
    finish_run_graph(trace.id, None, goal, on_event=on_event)
    trace.finish("aborted" if aborted else "done")
    return {"goal": goal, "model": model, "trace": actions, "run_id": trace.id,
            "aborted": aborted}


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


# JAG-373: voice (whisper STT / sherpa-onnx TTS) moved to `voice.py` (imported above).


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


def _as_int(x, default):
    """Coerce any wire value to int, falling back on garbage (JAG-229/231)."""
    try:
        return int(x)
    except (TypeError, ValueError):
        return default


def _int_arg(qs, key, default):
    """Parse an integer query parameter with a safe fallback (JAG-229).

    Query strings are attacker-controlled: `?since=abc` used to raise an
    unhandled ValueError that reset the connection instead of returning a
    clean response. Any malformed value falls back to `default`.
    """
    return _as_int(qs.get(key, default), default)


def _should_autoplan(jid, graph, autonomous, message):
    """JAG-308: may the end-of-turn fallback planner run for this turn?

    The JAG-76 fallback exists so the interactive 🧩 GRAPH panel is never empty:
    when the model answers in prose (no `write_todos`) we still show a plan. But
    it creates todos NOBODY executes — and the harness, by design (JAG-173),
    never auto-closes a step, so on a headless job turn (no HITL gate, JAG-295)
    they dangled as OPEN on a job already `done`. A JOB turn (`jid` set) already
    owns its graph — the coordinator decomposes and the workers author/close
    their own steps — so it must NEVER be auto-planned.
    """
    if jid is not None:                      # a job turn: the graph is the job's
        return False
    if graph is not None and taskgraph.plan_nodes(graph):
        return False                         # the current plan already has steps
    return bool(autonomous or len(str(message).split()) >= 4)


def chat_stream_gen(sess, message, model, mark=None, autonomous=False, jid=None,
                    sender=None, subjob=None, plan_only=False):
    """SSE producer for one chat request on `sess`.

    Contract (JAG-51): the caller has already appended the `user` message and
    passes `mark = session_mark(sess)` (the index captured just before it). Every
    exit path of this generator — reply, router error, warm-up error — leaves the
    session with a matching `assistant` message: a failed stream persists an
    explicit assistant error turn *and* emits the `error` SSE event, so a
    streamed request can never leave an orphan `user` message behind.

    `jid` (JAG-301): the job (JN) this turn belongs to, or None for a manual
    turn. It is written onto the session's task graph for THIS turn only, so a
    previous job's tag can never linger on a later, unrelated todo.

    `sender` / `subjob` (JAG-322): a turn TRIGGERED BY ANOTHER AGENT, not the
    human. When a job's coordinator delegates a subjob, the worker's turn must be
    attributed ("Delegation from A8 (Master) · J6.1") instead of showing up as the
    operator's own message. Both fields ride on the persisted user message and are
    rendered by the WebUI; a manual turn leaves them None ("YOU").

    `plan_only` (JAG-344): a turn that DECOMPOSES rather than works — the job
    coordinator's planning turn. It keeps a tight real-tool budget and NEVER
    enters the keepgoing continuation loop, so the master cannot complete the
    whole job itself instead of delegating it to the team.
    """
    q = queue.Queue()
    done = {"flag": False}
    since = mark if mark is not None else max(0, session_mark(sess) - 1)
    # JAG-181: register this turn as ACTIVE for its session, capturing the feed id
    # at turn start, so a re-attaching client can replay the whole turn.
    # JAG-299: a unique token per turn — the worker must only clear the
    # registration IT created. Two overlapping requests on one session (the second
    # blocks on the turn lock) used to have the first worker's exit pop the
    # SECOND turn's registration, so /api/chat/live reported idle and /api/chat/
    # attach could not resume a turn that was in fact still running.
    _turn_tok = object()
    with _ACTIVE_CHAT_LOCK:
        _ACTIVE_CHAT[sess["id"]] = {"ev0": feed_seq(), "ts": time.time(), "tok": _turn_tok}

    def _delta(channel, text):
        q.put("event: chat.delta\ndata: %s\n\n" % json.dumps(
            {"session": sess["id"], "channel": channel, "text": text}, ensure_ascii=False))
        publish("chat.delta", session=sess["id"], channel=channel, text=text)

    _coalesce = ThinkCoalescer(_delta)

    def on_delta(channel, text):
        _coalesce.feed(channel, text)

    def worker():
        nonlocal sess, since
        # JAG-201: serialise turns on this session (see _turn_lock).
        _turn_lock(sess["id"]).acquire()
        target = model

        def _emit(kind, **d):
            # graph/model events go to BOTH this chat stream and the feed, so
            # the WebUI can render the task graph live either way.
            q.put("event: %s\ndata: %s\n\n" % (kind, json.dumps(d, ensure_ascii=False)))
            publish(kind, **d)

        try:
            # JAG-201: the transcript read-modify-write happens INSIDE the lock —
            # reload the session, then append this turn's user message. Doing it in
            # the request thread (as before) let two concurrent streaming turns
            # overwrite each other (lost update).
            _fresh = load_session(sess["id"])
            if _fresh:
                sess = _fresh
            sess = prepare_session_for_turn(sess, model or sess.get("model"))
            since = session_mark(sess)
            append_message(sess, "user", message,
                           meta=({"sender": sender, "subjob": subjob}
                                 if (sender or subjob) else None))
            publish("chat.user", session=sess["id"], text=message,
                    sender=sender, subjob=subjob)
            # v0.5.1 warm-up: resolve the target alias and, if it is cold, emit
            # `model.loading` and load it *before* the first token instead of
            # letting the client stall silently on the router's autoload.
            target = model or routing.pick("chat") or default_model()
            trace = RunTrace("chat", goal=message[:120], model=target)
            trace.span("chat.stream", session=sess["id"])
            q.put("event: chat.run\ndata: %s\n\n" % json.dumps(
                {"run_id": trace.id, "session": sess["id"]}))
            # JAG-323: mirror the turn START onto the GLOBAL feed (chat.done already
            # is). Without it, a turn this browser did not begin — a headless job or
            # routine turn — never flipped the session's "running" marker, so the
            # session looked idle while the model burned GPU ("phantom run").
            publish("chat.run", run_id=trace.id, session=sess["id"])
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
                    # JAG-194: a finished task starts a NEW plan. We bump `plan`
                    # instead of hard-resetting the graph: keeping the old nodes
                    # (with their unique ids) is what lets the transcript's old
                    # cards resolve to the right node on reload instead of a
                    # relabelled/reused id.
                    taskgraph.begin_plan(_existing)
                # JAG-301: the job tag belongs to THIS turn. A job turn passes its
                # `jid`; a manual turn passes None — so a finished job's tag never
                # lingers on the session and mislabels a later, unrelated todo.
                # JAG-324: the SUBJOB tag rides alongside, so each todo an agent
                # creates is embraced by the (jid, subjob) it was produced for.
                if _existing is not None:
                    _existing["jid"] = jid
                    _existing["subjob"] = subjob
                    taskgraph.save(_existing)
                chat_once(sess, message, target, on_delta, trace=trace, on_event=_emit,
                          autonomous=autonomous, plan_only=plan_only)
                # JAG-76: guarantee a plan. The model normally authors the list
                # itself via `write_todos`; when it answers with prose only (which
                # left the app's 🧩 GRAPH panel empty — "there is no plan"), we
                # generate the graph from the request so the panel is never empty.
                # Skipped for one-liners (greetings/chit-chat) where a task list
                # would be noise.
                _g = taskgraph.load(gkey)
                # JAG-197: never spawn a planner model call for an ABORTED turn —
                # it ignores Stop and pins the session in _ACTIVE_CHAT (the turn
                # looked hung). The planner call is also made abortable.
                # JAG-216: run the fallback planner in a BACKGROUND daemon thread
                # and emit its nodes on the FEED (`publish`), NOT the turn's SSE.
                # Before this the planner call sat between the reply and `done`, so
                # the session stayed "running" (and the plan/ctx panels only
                # refreshed at `done`) for the whole planner round-trip — measured
                # ~20s of tail after a 1.4s reply. The WebUI renders graph events
                # from the feed too (index.html /api/feed handler -> applyGraphEvent
                # with a session guard), so nothing is lost. The turn now closes as
                # soon as the reply is done; the graph fills in a moment later.
                # JAG-308: never auto-plan a JOB turn (see `_should_autoplan`) —
                # its graph belongs to the job, not to a fallback UI planner.
                if _should_autoplan(jid, _g, autonomous, message) and \
                        not _is_aborted(sess["id"]):
                    threading.Thread(
                        target=start_run_graph,
                        args=(gkey, message, gkey, routing.pick("planner")),
                        kwargs={"on_event": publish,
                                "cancel": (lambda: _is_aborted(sess["id"]))},
                        daemon=True).start()
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
            try:
                from . import runmetrics
                runmetrics.finish(sess["id"], outcome="error", stop_reason="error",
                                  model=target)
                publish("run.metrics", session=sess["id"],
                        metrics=runmetrics.get(sess["id"]))
            except Exception:  # noqa: BLE001
                pass
            q.put("event: error\ndata: %s\n\n" % json.dumps(
                {"error": str(e), "session": sess["id"], "stored": True},
                ensure_ascii=False))
        finally:
            _coalesce.flush()  # JAG-265: emit any coalesced CoT tail before closing
            done["flag"] = True
            q.put(None)
            # JAG-181: the turn is over — no longer "attachable".
            # JAG-299: only clear OUR registration; a newer turn may have replaced it.
            with _ACTIVE_CHAT_LOCK:
                if (_ACTIVE_CHAT.get(sess["id"]) or {}).get("tok") is _turn_tok:
                    _ACTIVE_CHAT.pop(sess["id"], None)
            _turn_lock(sess["id"]).release()  # JAG-201: allow the next turn

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


_ATTACH_KINDS = ("chat.run", "chat.delta", "chat.done")


def _attach_frame(ev, terminal=False):
    kind = "done" if (terminal or ev.get("kind") == "chat.done") else ev.get("kind")
    return "id: %d\nevent: %s\ndata: %s\n\n" % (
        ev["id"], kind, json.dumps(ev, ensure_ascii=False))


def chat_attach_gen(sid, since=0):
    """JAG-181: re-attach a refreshed / reopened WebUI to a chat turn that is still
    RUNNING for `sid`.

    A page refresh or a session switch loses the browser's SSE channel but never
    stops the server-side worker. This generator replays the turn's streaming
    events (chat.delta text) from the durable event log and then tails new ones
    until the turn ends, so the reload resumes exactly where it left off instead of
    looking "interrupted". Only the streaming/render events are replayed: tool
    cards, todo tree and injects are already rebuilt by loadHistory, so replaying
    them would duplicate.
    """
    with _ACTIVE_CHAT_LOCK:
        info = _ACTIVE_CHAT.get(sid)
    if not info:
        yield "event: done\ndata: {}\n\n"   # turn already finished: nothing to follow
        return
    last = since or info.get("ev0", 0)
    for ev in events_since(last):
        if ev.get("session") != sid or ev.get("kind") not in _ATTACH_KINDS:
            continue
        last = ev["id"]
        if ev.get("kind") == "chat.done":
            yield _attach_frame(ev, terminal=True)
            return
        yield _attach_frame(ev)
    idle = 0
    while True:
        with _ACTIVE_CHAT_LOCK:
            if sid not in _ACTIVE_CHAT:
                break
        time.sleep(0.4)
        emitted = False
        for ev in events_since(last):
            if ev.get("session") != sid or ev.get("kind") not in _ATTACH_KINDS:
                continue
            last = ev["id"]; emitted = True
            if ev.get("kind") == "chat.done":
                yield _attach_frame(ev, terminal=True)
                return
            yield _attach_frame(ev)
        if not emitted:
            idle += 1
            if idle % 15 == 0:
                yield ": ping\n\n"
    yield "event: done\ndata: {}\n\n"


def agent_stream_gen(goal, max_steps, model, workspace=None):
    q = queue.Queue()
    # JAG-111: create the run HERE so the generator can abort it when the client
    # disconnects; pass it to agent_run so /api/agent/control can stop it too.
    st = api_v02.new_run(goal, model, max_steps)

    def on_event(kind, **d):
        q.put("event: %s\ndata: %s\n\n" % (kind, json.dumps(d, ensure_ascii=False)))
        if not kind.startswith("agent.think"):
            publish(kind, **d)

    def worker():
        try:
            agent_run(goal, max_steps, model, on_event, run_state=st, workspace=workspace)
        except Exception as e:  # noqa: BLE001
            q.put("event: error\ndata: %s\n\n" % json.dumps({"error": str(e)}))
        finally:
            q.put(None)

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    try:
        yield from sse_pump(q, t, open_comment=": agent stream open\n\n",
                            idle_timeout=CHAT_STREAM_IDLE or None)
    finally:
        # client gone (socket closed): stop the loop instead of leaving an orphan
        # worker streaming forever.
        if t.is_alive():
            st.abort = True


def feed_gen(since=0):
    q = queue.Queue()
    _sse_queues.add(q)
    try:
        backlog = events_since(since, limit=FEED_REPLAY_MAX)
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
            import subprocess
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


def resolve_ctx_model(sess, model=None):
    """JAG-258: the model a turn's context is measured against.

    Explicit `model` wins; else the session's own model; else the default. NEVER
    the arbitrary model the router happens to have loaded: using that for the
    meter made a healthy 131k-window session read as 99% full while the
    auto-compaction trigger (which uses the session model) correctly saw 22% and
    never fired — the "no autocompaction" illusion.
    """
    if model:
        return model
    return (sess.get("model") if sess else None) or default_model()


def providers_catalog():
    """Every provider + model the harness can use, with live usability (JAG-71)."""
    try:
        from . import providers
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

    JAG-128A: now delegates to the section registry (prompt.render_sections). It remains
    the ONLY source for the sent prompt and for the context indicator.
    """
    try:
        from . import rules as rules_mod
        ws = rules_mod.resolve_workspace(sess)
    except Exception:  # noqa: BLE001
        ws = None
    try:
        from . import prompt as prompt_mod
        return prompt_mod.render_sections(sess, ws=ws, tool_ctx=tool_ctx)
    except Exception:  # noqa: BLE001 — the prompt must never break the chat
        return system_prompt()


def context_display(tokens_used=0, budget_tokens=0, messages=0,
                    available=True, reason="no session"):
    """JAG-107: single source of truth for the context indicator presentation.

    Both the WebUI (JS) and the Android app (Kotlin) render these ready-made
    strings and flags verbatim, so the token formatting, the percentage and the
    over/near state are computed ONLY here — never replicated client-side.

    JAG-242: these strings are USER-FACING and must be English (project rule).
    """
    def _short(n):
        n = int(n)
        return ("%.0fk" % (n / 1000.0)) if n >= 10000 else str(n)

    if not available or not budget_tokens:
        return {"available": False, "reason": reason or "no session",
                "state": "na", "short": "ctx n/d", "meter": "ctx: n/d",
                "tokens": "n/d", "budget": "n/d", "messages": "n/d",
                "detail": "context n/d", "pct": 0, "bar_pct": 0,
                "bar_hot": False}
    used = int(tokens_used or 0)
    budget = int(budget_tokens)
    pct_f = (used / budget * 100.0) if budget else 0.0
    pct_int = int(round(pct_f))
    over = used > budget
    near = pct_f >= AUTOCOMPACT_PCT
    state = "over" if over else ("near" if near else "normal")
    threshold = int(round(AUTOCOMPACT_PCT))
    detail = "used %s / %s tokens" % (_short(used), _short(budget))
    if pct_int > 0:
        detail += " · %d%%" % pct_int
    if over:
        detail += " · over threshold"
    elif near:
        detail += " · auto-compact at %d%%" % threshold
    short = "ctx %s/%s" % (_short(used), _short(budget))
    if pct_int > 0:
        short += " · %d%%" % pct_int
    return {"available": True, "reason": "", "state": state, "short": short,
            "meter": "ctx: %d/%d" % (used, budget),
            "tokens": "%d tok" % used,
            "budget": "%d tok%s" % (budget, " · OVER" if over else ""),
            "messages": "%d messages" % int(messages or 0),
            "detail": detail, "pct": pct_int,
            "bar_pct": max(0, min(100, pct_int)), "bar_hot": pct_int > 90}


_RX_URL = re.compile(r'https?://[^\s"\'<>)\]},]+')
_RX_TOOL = re.compile(r'"tool"\s*:\s*"([A-Za-z0-9_.]+)"')
_RX_PATH = re.compile(
    r'/(?:[^\s"\'<>|:*?]+/)*[^\s"\'<>|:*?]+\.'
    r'(?:py|md|json|ya?ml|sh|txt|html?|jsx?|tsx?|css|toml|cfg|ini|csv|log|lock|env)')


def context_items(session_id=None):
    """JAG-267/269: the Context-panel breakdown for ONE session (never mixes sessions).

    Derived from the session's RETAINED transcript (`sess['messages']`) — the exact
    text transported to the model — plus the workspace rule files (always in the
    system prompt). Because it is recomputed from what is STILL in context, a
    compaction drops aged-out items automatically: the panel resets by itself.
    Categories: skills / rules / web / files / other, matching the operator's UI.

    JAG-269: also returns a TOKEN attribution — how much of the window each category
    occupies (rules from the system prompt; files/web/skills/other from the tool
    observations in the transcript; harness/conversation for the rest) plus the real
    `budget_tokens` / `used_tokens` / `pct`, so the panel ties to the ctx meter.
    File, rule and skill items carry a real `path` the UI can open in the editor.
    """
    from . import context_engine
    sess = load_session(session_id) if session_id else None
    empty = {"skills": [], "rules": [], "web": [], "files": [], "other": []}
    zero = {"system": 0, "tools": 0, "rules": 0, "skills": 0, "memory": 0,
            "plan": 0, "web": 0, "files": 0, "other": 0, "harness": 0,
            "conversation": 0, "overhead": 0}
    if not sess:
        return {"session": session_id, "available": False, "categories": empty,
                "counts": {}, "total": 0, "tokens": zero, "tokens_total": 0,
                "breakdown": [], "budget_tokens": 0, "used_tokens": 0, "pct": 0.0}
    msgs = sess.get("messages", [])
    blob = "\n".join(str(m.get("content")) for m in msgs
                     if isinstance(m.get("content"), str))

    def _dedupe(items):
        out, seen = [], set()
        for it in items:
            k = it.get("url") or it.get("path") or it.get("label")
            if k and k not in seen:
                seen.add(k)
                out.append(it)
        return out

    # rules live in the SYSTEM prompt (not the transcript): real paths + their tokens
    rules_items = []
    rules_tokens = 0
    try:
        from . import rules as _rules
        col = _rules.collect(_rules.resolve_workspace(sess))
        for scope in ("global", "project"):
            for p in (col.get(scope) or {}).get("files") or []:
                if p:
                    rules_items.append({"label": os.path.basename(p), "path": p})
        rules_tokens = context_engine.count_tokens(_rules.rules_prompt_block())
    except Exception:  # noqa: BLE001 — the panel must never break
        pass

    # skills: resolve each used skill to its real SKILL.md path so it can be opened
    try:
        from . import skills as _skills
        _skill_path = {}
        for _s in _skills.list_skills():
            _r = _s.get("path") or ""
            _skill_path[_s.get("name")] = (_r if os.path.isabs(_r)
                                           else os.path.join(REPO, _r))
    except Exception:  # noqa: BLE001
        _skill_path = {}

    def _skill(nm):
        it = {"label": nm}
        if _skill_path.get(nm):
            it["path"] = _skill_path[nm]
        return it

    skills = [_skill(nm) for nm in
              re.findall(r'"tool"\s*:\s*"skills".{0,200}?"name"\s*:\s*"([A-Za-z0-9_.\-]{2,})"',
                         blob, re.S)]
    skills += [_skill(nm) for nm in
               re.findall(r'(?:^|\n)\s{2,}([A-Za-z0-9][A-Za-z0-9_.\-]{2,})\s+::\s+', blob)]

    web = []
    for mm in re.finditer(r'(?:^|\s)\d+\.\s+([^\n]+)\n\s*(https?://\S+)', blob):
        web.append({"label": mm.group(1).strip()[:90], "url": mm.group(2).strip().rstrip('.,)')})
    for u in _RX_URL.findall(blob):
        web.append({"label": u.rstrip('.,)')[:100], "url": u.rstrip('.,)')})

    # strip URLs first so their paths are not mistaken for local files.
    # JAG-272: keep ONLY a path that really exists (relatives resolved against the
    # session workspace / repo). A text mention like "/battery.sh" is not a file and
    # must not become a dead click in the editor (it also wasted panel space).
    try:
        from . import rules as _rules_ws
        _ws = _rules_ws.resolve_workspace(sess)
    except Exception:  # noqa: BLE001
        _ws = None
    files, _seen_files = [], set()
    for p in _RX_PATH.findall(_RX_URL.sub(" ", blob)):
        cands = [p] if os.path.isabs(p) else [os.path.join(_ws or "", p),
                                              os.path.join(REPO, p)]
        real = next((c for c in cands if c and os.path.isfile(c)), None)
        if real and real not in _seen_files:
            _seen_files.add(real)
            files.append({"label": os.path.basename(real), "path": real})

    tool_counts = {}
    for nm in _RX_TOOL.findall(blob):
        if nm in ("fs.read", "fs.write", "fs.edit", "web", "skills"):
            continue
        tool_counts[nm] = tool_counts.get(nm, 0) + 1
    other = [{"label": k, "count": v} for k, v in
             sorted(tool_counts.items(), key=lambda kv: (-kv[1], kv[0]))]

    # JAG-269/272: token attribution that ADDS UP to the measured total — the system
    # prompt (per section) + the transcript (per tool) + an explicit 'overhead'
    # bucket for the gap vs the router's real count. sum(tokens.values()) == used.
    tok = dict(zero)
    try:
        from . import prompt as _prompt
        _secs = _prompt.section_texts(sess, ws=_ws, tool_ctx=None)
    except Exception:  # noqa: BLE001
        _secs = {}

    def _stok(*ids):
        return sum(context_engine.count_tokens(_secs.get(i, "")) for i in ids)

    tok["system"] = _stok("identity", "prompt-map", "self-summary", "rules-policy",
                          "skills-policy", "memory-policy", "capability", "task-policy")
    tok["tools"] = _stok("tools")
    tok["rules"] = _stok("rules") or rules_tokens
    tok["skills"] = _stok("skills")
    tok["memory"] = _stok("memory")
    tok["plan"] = context_engine.count_tokens(state_block(session_id=session_id))

    _obs = re.compile(r"^(?:\[harness\]\s+)?Observation for tool\s+([A-Za-z0-9_.\-]+)\s*:")
    for m in msgs:
        c = m.get("content")
        c = c if isinstance(c, str) else ("" if c is None else str(c))
        n = context_engine.count_tokens(c)
        if not n:
            continue
        mo = _obs.match(c)
        if mo:
            tool = mo.group(1)
            if tool == "skills":
                tok["skills"] += n
            elif tool == "web":
                tok["web"] += n
            elif tool in ("fs.read", "fs.write", "fs.edit"):
                tok["files"] += n
            else:
                tok["other"] += n
        elif c.startswith(HARNESS_MARK):
            tok["harness"] += n
        else:
            tok["conversation"] += n

    budget = used = 0
    pct = 0.0
    cached = 0
    cache_hit_pct = 0.0
    try:
        _u = context_usage(session_id)
        budget = context_budget(resolve_ctx_model(sess))
        used = int(_u.get("tokens_used") or 0)
        cached = int(_u.get("cached_tokens") or 0)
        cache_hit_pct = float(_u.get("cache_hit_pct") or 0.0)
        pct = round(used / budget * 100, 1) if budget else 0.0
    except Exception:  # noqa: BLE001
        pass
    _sum = sum(tok.values())
    if used > _sum:
        tok["overhead"] = used - _sum        # our estimate vs the router's real count

    # JAG-272: the ordered breakdown the UI renders (sums to the context total).
    _order = [("system", "System instructions"), ("tools", "Tool schemas"),
              ("rules", "Rules"), ("skills", "Skills"), ("memory", "Memory"),
              ("plan", "Plan / task list"), ("web", "Web / search"),
              ("files", "Files (reads)"), ("other", "Other tool output"),
              ("harness", "Harness messages"), ("conversation", "Conversation"),
              ("overhead", "Measured overhead")]
    breakdown = [{"key": k, "label": lab, "tokens": tok.get(k, 0)}
                 for k, lab in _order if tok.get(k, 0)]

    cats = {"skills": _dedupe(skills)[:40], "rules": _dedupe(rules_items)[:40],
            "web": _dedupe(web)[:40], "files": _dedupe(files)[:60], "other": other[:40]}
    return {"session": session_id, "available": True, "categories": cats,
            "counts": {k: len(v) for k, v in cats.items()},
            "total": sum(len(v) for v in cats.values()),
            "tokens": tok, "tokens_total": sum(tok.values()),
            "breakdown": breakdown,
            "budget_tokens": budget, "used_tokens": used, "pct": pct,
            "cached_tokens": cached, "cache_hit_pct": cache_hit_pct}


def context_usage(session_id=None, message=None, model=None):
    """Effective prompt tokens vs budget for the next turn (JAG-70).

    Counts what is REALLY sent: the system prompt (tool registry + skills +
    persistent task list), the compacted transcript and the pending user
    message. Returns the raw parts too, so the UI can explain the number.
    """
    from . import context_engine
    budget = context_budget(model)
    base = {"budget_tokens": budget, "session": session_id, "model": model,
            "auto_compact_pct": AUTOCOMPACT_PCT,
            "auto_compact_target_pct": AUTOCOMPACT_TARGET_PCT}
    sess = load_session(session_id) if session_id else None
    if not sess:
        return {**base, "available": False, "messages": 0, "tokens_used": 0,
                "pct": 0.0, "over_threshold": False, "over_budget": False,
                "display": context_display(available=False,
                                           reason="session not found")}
    sysp = _system_prompt(sess)
    # JAG-276: the live task list is injected into the user turn (see assemble_turn).
    # Mirror that here so the meter counts what is REALLY sent.
    aug_message = (message or "") + "\n\n" + state_block(session_id=session_id)
    # JAG-72: mirror `chat_once` EXACTLY — same model-aware budget and the same
    # memory-retrieval block — so `compacted_tokens` is the size that WILL be sent.
    msgs, stats = context_engine.build(
        sysp, sess.get("messages", []), aug_message,
        budget_tokens=budget, retrieve_memory=True)
    compacted = int(stats.get("final_tokens") or 0)
    sysp_tokens = context_engine.count_tokens(sysp)
    transcript = sum(context_engine.count_tokens(m.get("content", ""))
                     for m in sess.get("messages", []))
    # JAG-214: the meter must show what you are CARRYING (system prompt + the full
    # stored transcript + the pending message), NOT the post-compaction build size.
    # That size can never exceed the threshold, so the auto-compact trigger could
    # never fire; and two different sessions both collapsed to the system prompt,
    # so the ctx bar looked identical when switching sessions. Prefer the router's
    # REAL prompt_tokens (JAG-86) when it is larger, so we never under-report.
    raw = sysp_tokens + transcript + context_engine.count_tokens(aug_message)
    real = _REAL_PROMPT_TOKENS.get(session_id) if session_id else None
    used = max(raw, int(real)) if real else raw
    pct = round(used / budget * 100, 1) if budget else 0.0
    # JAG-273: how much of the last prompt the provider served from its prefix
    # (KV) cache — the evidence that the static-first ordering actually pays off.
    cached = int(_REAL_CACHED_TOKENS.get(session_id) or 0) if session_id else 0
    cache_hit_pct = (round(cached / int(real) * 100, 1)
                     if (real and int(real) > 0) else 0.0)
    out = {**base, "available": True,
           "messages": len(sess.get("messages", [])),
           "tokens_used": used, "pct": pct,
           "estimate_tokens_used": raw,
           "compacted_tokens": compacted,
           "system_tokens": sysp_tokens,
           "transcript_tokens": transcript,
           "final_messages": stats.get("final_messages"),
           "over_threshold": pct >= AUTOCOMPACT_PCT,
           "over_budget": used > budget,
           "cached_tokens": cached,
           "cache_hit_pct": cache_hit_pct,
           "source": "model" if real else "estimate"}
    out["display"] = context_display(used, budget, len(sess.get("messages", [])))
    if real:
        out["real_tokens_used"] = int(real)
    return out


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
        # JAG-99: shrink to TARGET% (not the full budget) so the prompt lands back
        # under the trigger with headroom; the system prompt is accounted for.
        target = int(usage["budget_tokens"] * AUTOCOMPACT_TARGET_PCT / 100.0)
        stats = compact_session(sess["id"], target, origin="auto")
        publish("context.auto_compact", session=sess["id"],
                pct=usage.get("pct"), threshold=AUTOCOMPACT_PCT,
                target_pct=AUTOCOMPACT_TARGET_PCT,
                before=stats.get("input_tokens"), after=stats.get("output_tokens"),
                compacted=stats.get("compacted"), dropped=stats.get("dropped"))
        return load_session(sess["id"]) or sess
    except Exception:  # noqa: BLE001 — compaction must never break a turn
        return sess


def _summarize_with_llm(messages, model=None, meta=None):
    """JAG-103: let the MODEL do the compaction.

    Summarize the OLDER turns into one faithful, compact block (decisions, facts,
    file paths/commands, user preferences, open tasks) in the transcript's own
    language. Reuses `stream_with_fallback` (role "summarizer") — no bespoke router
    code. Returns the summary text, or None on ANY failure so the caller falls back
    to the local extractive merge (compaction must never stall a turn).

    JAG-110: when `meta` (a dict) is passed, records `meta["model"] = <alias that
    actually answered>`, so the UI can show WHICH model did the compaction.
    """
    lines = []
    for m in messages:
        content = m.get("content") or ""
        # JAG-238: a stored message may carry a non-string content.
        if not isinstance(content, str):
            content = str(content)
        content = content.strip()
        if content:
            lines.append("%s: %s" % (m.get("role", "?"), content))
    transcript = "\n".join(lines)
    if not transcript.strip():
        return None
    # JAG-214: never hand the summarizer more than it can hold. A session may be
    # dominated by one huge paste; keep the head + tail so the call always fits.
    if len(transcript) > SUMMARIZER_MAX_CHARS:
        head = int(SUMMARIZER_MAX_CHARS * 0.7)
        tail = SUMMARIZER_MAX_CHARS - head
        transcript = transcript[:head] + "\n…[middle omitted]…\n" + transcript[-tail:]
    prompt = (
        "You are compacting the OLDER turns of an ongoing chat so the assistant can "
        "keep working with less context. Write a faithful, compact summary IN THE "
        "SAME LANGUAGE as the transcript. Preserve: decisions made, concrete facts, "
        "file paths and commands, user preferences, and any OPEN tasks or questions. "
        "Drop chit-chat and repetition. Reply with the summary text ONLY (no preamble), "
        "at most ~200 words.\n\nTRANSCRIPT:\n" + transcript)
    # JAG-160: honour an explicitly pinned summarizer model (Settings -> Models)
    # before falling back to pattern-based routing for the "summarizer" role.
    if not model:
        try:
            from . import routing as _routing
            model = _routing.role_model("summarizer")
        except Exception:  # noqa: BLE001
            model = None
    try:
        answer, _think, used = stream_with_fallback(
            [{"role": "user", "content": prompt}], model, "summarizer",
            lambda ch, t: None, timeout=180)
        answer = (answer or "").strip()
        if answer and meta is not None:
            meta["model"] = used
        return answer or None
    except Exception:  # noqa: BLE001 — never let summarization break compaction
        return None


def compact_session(session, budget_tokens=None, keep_recent=None, origin=None):
    """Compact a session transcript in place under the token budget (v0.5).

    Uses the v0.3 extractive compaction; the newest messages stay verbatim,
    older ones are merged into a synthetic summary message. Returns stats.

    JAG-102: called WITHOUT `budget_tokens` this is the MANUAL "compact now"
    action. It must actually SHRINK the transcript, so it targets a fraction of
    what the transcript currently uses (`COMPACT_FORCE_RATIO`). Previously it used
    the full model budget, which made it a no-op for any session under 100% — the
    button appeared to do nothing. The single source of this policy lives here, so
    the WebUI and the app need no duplicated logic.

    JAG-110: the manual action also FORCES compaction and keeps only
    `COMPACT_MANUAL_KEEP_RECENT` recent turns, so a short session actually shrinks
    and the LLM summarizer runs (previously `keep_recent=8` left <=8-message
    sessions untouched: no model call, no GPU). The automatic path is unchanged
    (engine default 8, never forced).
    """
    from . import context_engine
    sess = load_session(session) if session else None
    if not sess:
        return {"error": "session not found: %s" % session}
    messages = sess.get("messages", [])
    current = sum(context_engine.count_tokens(m.get("content", "")) for m in messages)
    if budget_tokens:
        budget = int(budget_tokens)
        # JAG-99: the system prompt is sent uncompacted and consumes the budget,
        # so the transcript is compacted against what is really LEFT for it.
        room = max(1024, budget - context_engine.count_tokens(_system_prompt(sess)))
    else:
        # JAG-102: manual action — target a fraction of the CURRENT transcript.
        # JAG-104: the floor is small (256) so the ratio also applies to short
        # sessions; a 1024 floor made the button a near no-op under ~1k tokens.
        budget = current
        room = max(256, int(current * COMPACT_FORCE_RATIO))
    manual = not budget_tokens
    if manual and keep_recent is None:
        keep_recent = COMPACT_MANUAL_KEEP_RECENT
    meta = {}
    kwargs = {"summarizer": lambda old: _summarize_with_llm(old, meta=meta),
              "force": manual}
    if keep_recent is not None:
        kwargs["keep_recent"] = keep_recent
    msgs, stats = context_engine.compact(messages, room, **kwargs)
    sess["messages"] = msgs
    save_session(sess)
    # JAG-104: the cached "real" prompt size belongs to the turn BEFORE the
    # compaction; keeping it made /api/context report the OLD number, so the ctx
    # meter did not move and the button looked like a no-op even though the
    # transcript had shrunk. Drop it so the meter falls back to the fresh estimate.
    _REAL_PROMPT_TOKENS.pop(session, None)
    stats.update({"session": session, "budget_tokens": budget,
                  "transcript_room": room,
                  "summarizer": meta.get("model"),
                  "messages_after": len(msgs),
                  "tokens_after": sum(context_engine.count_tokens(m.get("content", ""))
                                      for m in msgs)})
    origin = origin or ("manual" if not budget_tokens else "auto")
    stats["origin"] = origin
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
        if isinstance(obj, bytes):
            body = obj
        elif isinstance(obj, str):
            body = obj.encode("utf-8")
        else:
            # JAG-233: every JSON-serializable payload (dict / list / None / int /
            # bool / float) must serialize. `None` used to fall through to the old
            # `else` branch and call `None.encode()`, an unhandled AttributeError
            # that closed the socket with NO response (live repro:
            # GET /api/subagent?id=<unknown> when the store returns None).
            body = json.dumps(obj, indent=2, ensure_ascii=False).encode("utf-8")
        # JAG-208 (v208): a client that disconnects mid-response must never raise
        # an unhandled BrokenPipeError/ConnectionResetError (it floods the log and
        # is indistinguishable from a real crash under abuse). Swallow it.
        try:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            # JAG-232: never let a browser re-sniff a declared type into HTML/JS.
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _send_asset(self, rel):
        """Serve a read-only static asset under webui/assets (vendored editor
        libs, css, images). The path is resolved inside the assets root and the
        extension is whitelisted, so it can never escape the folder."""
        import posixpath
        rel = posixpath.normpath("/" + (rel or "")).lstrip("/")
        if not rel or rel.startswith(".."):
            return self._send(404, {"error": "not found"})
        root = os.path.normpath(os.path.join(WEBUI_DIR, "assets"))
        full = os.path.normpath(os.path.join(root, rel))
        if full != root and not full.startswith(root + os.sep):
            return self._send(404, {"error": "not found"})
        ext = os.path.splitext(full)[1].lower()
        if ext not in ASSET_EXTS:
            return self._send(404, {"error": "not found"})
        try:
            with open(full, "rb") as f:
                data = f.read()
        except (FileNotFoundError, IsADirectoryError, PermissionError):
            return self._send(404, {"error": "not found"})
        return self._send(200, data, ctype=ASSET_CTYPES.get(ext, "application/octet-stream"))

    def _content_length(self):
        """Content-Length as int, 0 on a malformed/missing header (JAG-229)."""
        try:
            return int(self.headers.get("Content-Length") or 0)
        except (TypeError, ValueError):
            return 0

    def _body(self):
        n = self._content_length()
        if not n:
            return {}
        # JAG-208 (v208): an unbounded Content-Length is a memory-DoS. Buffer at
        # most MAX_BODY_BYTES and DRAIN the rest in chunks (so the socket stays
        # framed) instead of allocating the whole payload.
        keep = min(n, MAX_BODY_BYTES)
        raw = self.rfile.read(keep)
        remaining = n - keep
        while remaining > 0:
            got = self.rfile.read(min(65536, remaining))
            if not got:
                break
            remaining -= len(got)
        if n > MAX_BODY_BYTES:
            return {}
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {}
        # JAG-231: a JSON body is only useful as an OBJECT. A top-level array,
        # string, number, bool or null is valid JSON but not a dict, and every
        # caller does `body.get(...)` — that raised AttributeError, which dropped
        # the connection with no response (live repro: POST /api/chat "[1,2]").
        return parsed if isinstance(parsed, dict) else {}

    def _query(self):
        from urllib.parse import parse_qs, urlparse
        q = urlparse(self.path)
        return q.path, {k: v[0] for k, v in parse_qs(q.query).items()}

    # ---- GET ----
    def do_GET(self):
        path, qs = self._query()
        if path.startswith("/assets/"):
            return self._send_asset(path[len("/assets/"):])
        if _orbit_page(self, path):   # JAG-285: optional beta shell (public)
            return
        if path in ("/console", "/console.html", "/deck"):
            # JAG-209: the Command Deck SHELL is public (it holds no secrets); the
            # data it fetches underneath stays auth-gated. This avoids putting the
            # token in the URL just to load the page.
            try:
                with open(os.path.join(WEBUI_DIR, "console.html"), "r", encoding="utf-8") as f:
                    return self._send(200, f.read(), ctype="text/html; charset=utf-8")
            except FileNotFoundError:
                return self._send(404, {"error": "console missing"})
        if not check_auth(self.headers, qs):
            return self._send(401, {"error": "unauthorized"})
        if api_v02.handle(self, "GET", path, qs, None):
            return
        if _orbit_handle(self, "GET", path, qs, None):   # JAG-285: optional beta API
            return

        if path == "/api/build":
            # JAG-362: a cheap fingerprint of the served SPA so a long-lived tab
            # can notice that the app was updated and reload itself — the reason
            # a freshly-fixed UI could keep looking stale in an open tab.
            try:
                _b = "%d-%d" % tuple(int(x) for x in (
                    os.stat(os.path.join(WEBUI_DIR, "index.html")).st_mtime,
                    os.stat(os.path.join(WEBUI_DIR, "index.html")).st_size))
            except OSError:
                _b = ""
            return self._send(200, {"build": _b})
        if path in ("/", "/index.html"):
            try:
                with open(os.path.join(WEBUI_DIR, "index.html"), "r", encoding="utf-8") as f:
                    return self._send(200, f.read(), ctype="text/html; charset=utf-8")
            except FileNotFoundError:
                return self._send(404, {"error": "webui missing"})
        if path == "/api/self":
            return self._send(200, self_knowledge())
        if path == "/api/context":
            # JAG-258: measure against the SAME model the turn uses (explicit >
            # session model > default), never the arbitrarily-loaded router model.
            _sid = qs.get("session")
            _mdl = resolve_ctx_model(load_session(_sid) if _sid else None,
                                     qs.get("model"))
            return self._send(200, context_status(_sid, _mdl))
        if path == "/api/context/items":
            # JAG-267: Context-panel breakdown for ONE session (never mixes sessions).
            return self._send(200, context_items(qs.get("session")))
        if path == "/api/status":
            return self._send(200, status_payload())
        if path == "/api/models" or path == "/api/providers":
            return self._send(200, providers_catalog())
        if path == "/api/keys":
            return self._send(200, keys_status())
        if path == "/api/selfcheck":
            llm = qs.get("llm", "1").lower() not in ("0", "false", "no")
            return self._send(200, selfcheck_payload(
                host=getattr(self.server, "host", "127.0.0.1"),
                port=getattr(self.server, "port", 8790), llm_probe=llm))
        if path == "/api/feed":
            since = _int_arg(qs, "since", 0)
            # keep-alive is a /api/feed-only privilege (v0.6.1, JAG-48)
            return sse_response(self, feed_gen(since), keepalive=True)
        if path == "/api/plan":
            # JAG-129B/F3: read alias of the persistent task list, with
            # a backward-compatible shape {nodes,counts,goal,steps} (legacy consumers).
            sid = qs.get("session") or ""
            g = taskgraph.load(sid) if sid else None
            pub = taskgraph.public(g) or {"nodes": [], "counts": {}}
            pub["goal"] = (g or {}).get("goal") or ""
            pub["steps"] = [{"id": n.get("id"), "title": n.get("label"),
                             "done": n.get("status") in ("done", "cancelled")}
                            for n in (g or {}).get("nodes", [])]
            return self._send(200, pub)
        if path == "/api/tasks":
            tasks = load_tasks()
            remaining = ["%s: %s" % (t["status"], t["title"]) for t in tasks.get("tasks", [])
                         if t.get("status") != "done"]
            return self._send(200, {**tasks, "remaining": remaining})
        if path == "/api/improve":
            # JAG-128B: list of self-improvement proposals for the WebUI card.
            from . import improve as improve_mod
            return self._send(200, {"proposals": improve_mod.list_proposals()})
        if path == "/api/sessions":
            return self._send(200, {"sessions": list_sessions()})
        if path == "/api/sessions/new":
            # JAG-127: an explicitly requested folder must exist — never silently
            # fall back to the default (that made a Z:/wrong path look like the
            # session was created in a folder the user never picked).
            ws = qs.get("workspace")
            if ws:
                from . import rules as _rm
                if not _rm.check_dir(ws):
                    return self._send(400, {"error": "no such folder: %s" % ws})
            sess = get_or_create_session(None, qs.get("title"), ws)
            publish("session.created", session=sess["id"], title=sess["title"])
            return self._send(200, sess)
        if path == "/api/history":
            sid = qs.get("session")
            sess = load_session(sid) if sid else None
            if not sess:
                return self._send(404, {"error": "session not found"})
            if ensure_job(sess):   # JAG-169: backfill a stable JX on first read
                save_session(sess)
            return self._send(200, sess)
        if path == "/api/events":
            # JAG-262: filtered event-log history for post-mortem. Answers "what
            # happened to session X" (or a kind / time window) after the fact.
            return self._send(200, {"events": query_events(
                session=qs.get("session"), kind=qs.get("kind"),
                since=qs.get("since"), until=qs.get("until"),
                limit=_int_arg(qs, "limit", 200))})
        if path == "/api/chat/live":
            # JAG-181: which sessions currently have a chat turn running (for the
            # WebUI to re-attach after a refresh / session switch).
            with _ACTIVE_CHAT_LOCK:
                return self._send(200, {"active": list(_ACTIVE_CHAT.keys())})
        if path == "/api/chat/attach":
            # JAG-181: resume following a still-running turn for `session`.
            sid = qs.get("session")
            if not sid:
                return self._send(400, {"error": "session required"})
            since = _int_arg(qs, "since", 0)
            return sse_response(self, chat_attach_gen(sid, since))
        if path == "/api/chat/stream":
            # SSE chat. Session contract: see the Handler docstring (JAG-51).
            sid = qs.get("session")
            message = qs.get("message", "")
            if not message:
                return self._send(400, {"error": "message required"})
            sess = get_or_create_session(sid)
            # JAG-201: prepare + append the user turn INSIDE the worker's turn lock
            # (chat_stream_gen), not here — two concurrent turns must not overwrite.
            return sse_response(self, chat_stream_gen(sess, message, qs.get("model"), None,
                                                      autonomous=qs.get("mode") == "goal"))
        if path == "/api/agent/run":
            goal = qs.get("goal", "")
            if not goal:
                return self._send(400, {"error": "goal required"})
            _ws_sess = load_session(qs.get("session")) if qs.get("session") else None
            from . import rules as _rules_mod
            _ws = _rules_mod.resolve_workspace(_ws_sess)
            return sse_response(self, agent_stream_gen(goal, _int_arg(qs, "max_steps", 6),
                                                       qs.get("model"), workspace=_ws))
        if path.startswith("/api/runs/"):
            parts = path.strip("/").split("/")
            if len(parts) == 4 and parts[3] == "trace":
                t = get_run_trace(parts[2])
                return self._send(200, t) if t else self._send(404, {"error": "run not found"})
            if len(parts) == 4 and parts[3] == "graph":
                # v0.6: the run's task graph (linked to run_id + session_id).
                # JAG-189: a run with no graph YET is not an error — return an
                # empty graph (200) so the UI poll stops logging spurious 404s.
                g = taskgraph.load(parts[2])
                return self._send(200, taskgraph.public(g) or {
                    "run_id": parts[2], "session_id": None, "nodes": [],
                    "counts": {}, "status": "empty", "node_count": 0})
            return self._send(404, {"error": "not found"})
        if path == "/api/runs":
            return self._send(200, {"runs": runs_summary(_int_arg(qs, "limit", 50))})
        if path.startswith("/api/sessions/") and path.endswith("/graph"):
            # JAG-91: the chat graph is keyed by SESSION id (one task = one
            # session), so the WebUI plan panel reads the session graph directly
            # instead of the orphaned global plan.json.
            sess_id = path[len("/api/sessions/"):-len("/graph")].strip("/")
            g = taskgraph.load(sess_id)
            # JAG-189: no graph yet (fresh session, or a deleted one) is not an
            # error — return an empty graph (200) so the UI poll doesn't log 404s.
            return self._send(200, taskgraph.public(g) or {
                "session_id": sess_id, "run_id": sess_id, "nodes": [],
                "counts": {}, "status": "empty", "node_count": 0})
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
            n = self._content_length()
            if not n:
                return self._send(400, {"error": "audio body required"})
            import tempfile
            ext = ".wav"
            # JAG-295-fix: cap the read — an unbounded Content-Length is a memory-DoS.
            with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as f:
                f.write(self.rfile.read(min(n, MAX_BODY_BYTES)))
                tmp = f.name
            try:
                return self._send(200, voice_stt(tmp))
            finally:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
        # Raw skill zip upload (JAG-109) — before JSON parsing.
        if path == "/api/skills/install" and (
                ctype.startswith("application/zip") or ctype.startswith("application/x-zip")):
            n = self._content_length()
            if not n:
                return self._send(400, {"error": "zip body required"})
            data = self.rfile.read(min(n, MAX_BODY_BYTES))  # JAG-295-fix: bound the read
            res = api_v02.install_skill_raw(data, name=qs.get("name"),
                                            overwrite=qs.get("overwrite") == "1")
            return self._send(200 if res.get("ok") else 400, res)
        # JAG-279: raw attachment upload from the composer's native file picker.
        # A browser cannot expose a client path, so the picker sends the bytes and
        # we store them server-side; the model then gets a real absolute path.
        if path == "/api/attach" and ctype and not ctype.startswith("application/json"):
            n = self._content_length()
            if not n:
                return self._send(400, {"error": "empty body"})
            cap = int(os.environ.get("SPARKFORGE_ATTACH_MAX", str(32 * 1024 * 1024)))
            data = self.rfile.read(min(n, cap))
            res = api_v02.attach_save(data, name=qs.get("name"),
                                      session=qs.get("session"))
            return self._send(200 if res.get("ok") else 400, res)
        body = self._body()
        if api_v02.handle(self, "POST", path, qs, body):
            return
        if _orbit_handle(self, "POST", path, qs, body):   # JAG-285: optional beta API
            return

        if path == "/api/chat":
            # One-shot chat. Session contract: see the Handler docstring (JAG-51).
            message = body.get("message", "")
            # JAG-238: `message` becomes a persisted transcript turn. A non-string
            # (int/list/...) used to be stored verbatim and later crashed
            # /api/context (`len(int)`), so reject it at the boundary.
            if not isinstance(message, str):
                return self._send(400, {"error": "message must be a string"})
            if not message:
                return self._send(400, {"error": "message required"})
            sess = get_or_create_session(body.get("session"))
            # JAG-201: one turn at a time per session; RELOAD + prepare INSIDE the
            # lock so a concurrent turn's save is never overwritten (lost update).
            with _turn_lock(sess["id"]):
                _fresh = load_session(sess["id"])
                if _fresh:
                    sess = _fresh
                # JAG-157: explicit model wins, else the session's own model.
                sess = prepare_session_for_turn(sess, body.get("model") or sess.get("model"))  # JAG-70: auto-compact @75%
                mark = session_mark(sess)  # JAG-51: boundary of this request
                append_message(sess, "user", message)
                publish("chat.user", session=sess["id"], text=message)
                # JAG-325: bracket this turn in the active-turn registry too — the
                # sync path runs a REAL model turn but used to show NO running signal
                # (a phantom run). turn_end runs in the finally below, on any outcome.
                _turn_tok = turn_begin(sess["id"])
                trace = None
                try:
                    trace = RunTrace("chat", goal=message[:120], model=body.get("model"))
                    trace.span("chat.once", session=sess["id"])
                    # v0.6 first action: model-generated write_todos → per-run graph.
                    # JAG-76: key the graph by the SESSION (same key as
                    # `/api/chat/stream`), so every client that binds the panel to the
                    # session finds it. Keying it by the ephemeral trace id made the
                    # two chat paths disagree and the panel look empty.
                    # JAG-194: a finished task opens a NEW plan (keep the old nodes).
                    _ex = taskgraph.load(sess["id"])
                    if _ex and taskgraph.all_done(_ex):
                        taskgraph.begin_plan(_ex)
                    # JAG-301: this path is never a job turn — drop any job tag a
                    # previous job left on the graph so the fresh todos are not
                    # mislabelled as belonging to that job.
                    if _ex is not None:
                        _ex["jid"] = None
                        _ex["subjob"] = None
                        taskgraph.save(_ex)
                    start_run_graph(sess["id"], message, sess["id"], routing.pick("planner"))
                    reply, model = chat_once(sess, message, body.get("model"), trace=trace,
                                             autonomous=(body.get("mode") or qs.get("mode")) == "goal")
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
                finally:
                    turn_end(sess["id"], _turn_tok)   # JAG-325: clear the running signal
                finish_run_graph(sess["id"], sess["id"], message)
                trace.model = model
                trace.finish("done")
                return self._send(200, {"session": sess["id"], "model": model, "run_id": trace.id,
                                        "reply": reply["content"], "reasoning": reply.get("reasoning"),
                                        "messages": len(sess["messages"]),
                                        "error": bool(reply.get("error"))})
        if path == "/api/chat/steer":
            # JAG-127b: drop a steering message into a RUNNING turn's loop (see
            # push_steer/drain_steer). No new turn, no new SSE.
            sid = body.get("session") or qs.get("session")
            text = body.get("message") or qs.get("message", "")
            if not sid or not text:
                return self._send(400, {"error": "session and message required"})
            depth = push_steer(sid, text)
            publish("chat.steer", session=sid, text=text, queued=depth)
            return self._send(200, {"ok": True, "queued": depth})
        if path == "/api/chat/abort":
            # JAG-129A: stops the in-flight turn (the agent must not continue).
            sid = body.get("session") or qs.get("session")
            if not sid:
                return self._send(400, {"error": "session required"})
            push_abort(sid)
            publish("chat.abort", session=sid)
            return self._send(200, {"ok": True, "aborted": sid})
        if path == "/api/improve":
            # JAG-128B: approve/reject a self-improvement proposal.
            from . import improve as improve_mod
            pid = body.get("id") or qs.get("id", "")
            decision = body.get("decision") or qs.get("decision", "")
            res = improve_mod.decide(pid, decision)
            return self._send(200 if res.get("ok") else 400, res)
        if path == "/api/chat/stream":
            # a JSON body over query params). Same SSE contract.
            message = body.get("message") or qs.get("message", "")
            if not message:
                return self._send(400, {"error": "message required"})
            sess = get_or_create_session(body.get("session") or qs.get("session"))
            # JAG-201: prepare + append inside the worker's turn lock (see GET path).
            return sse_response(self, chat_stream_gen(
                sess, message, body.get("model") or qs.get("model"), None,
                autonomous=(body.get("mode") or qs.get("mode")) == "goal"))
        if path == "/api/model/ensure":
            alias = body.get("model") or qs.get("model") or \
                routing.pick("chat") or default_model()
            if not alias:
                return self._send(503, {"error": "no router model available"})
            res = ensure_model(alias, on_event=lambda k, **d: publish(k, **d))
            return self._send(200 if res.get("loaded") else 502, res)
        if path == "/api/plan":
            # JAG-129B/F3: the legacy "plan" IS the persistent task list, with
            # a backward-compatible shape {nodes,counts,goal,steps} (legacy consumers).
            sid = body.get("session") or qs.get("session") or ""
            g = taskgraph.load(sid) if sid else None
            pub = taskgraph.public(g) or {"nodes": [], "counts": {}}
            pub["goal"] = (g or {}).get("goal") or ""
            pub["steps"] = [{"id": n.get("id"), "title": n.get("label"),
                             "done": n.get("status") in ("done", "cancelled")}
                            for n in (g or {}).get("nodes", [])]
            return self._send(200, pub)
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
            # JAG-129B: the legacy toggle acts on the persistent task list
            # (a single source of truth), no longer on plan.json.
            node_id = str(body.get("id") or qs.get("id") or "")
            _g = taskgraph.load(body.get("session") or qs.get("session") or "")
            node = taskgraph.find(_g, node_id=node_id) if _g else None
            if not node:
                return self._send(404, {"error": "step not found"})
            if node.get("status") == "done":
                taskgraph.update_node(_g, node_id, status="todo")
            else:
                taskgraph.complete_node(_g, node_id,
                                        evidence="manual toggle (legacy /api/plan/toggle)")
            return self._send(200, taskgraph.public(_g))
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
            result = agent_run(goal, _as_int(body.get("max_steps", 6), 6), body.get("model"))
            return self._send(200, result)
        if path.startswith("/api/runs/") and path.endswith("/graph/nodes"):
            # v0.6: add/cancel node + incremental re-plan on a run's graph
            run_id = path[len("/api/runs/"):-len("/graph/nodes")].strip("/")
            payload, err, code = graph_post(run_id, body)
            return self._send(code, err if err else payload)
        if path.startswith("/api/sessions/") and path.endswith("/clear"):
            sid = path[len("/api/sessions/"):-len("/clear")].strip("/")
            if not _valid_sid(sid) or load_session(sid) is None:
                return self._send(404, {"error": "session not found"})
            clear_session(sid)
            return self._send(200, {"ok": True, "cleared": sid})
        if path.startswith("/api/sessions/") and path.endswith("/rename"):
            sid = path[len("/api/sessions/"):-len("/rename")].strip("/")
            sess = load_session(sid)
            if not sess:
                return self._send(404, {"error": "session not found"})
            title = str((body or {}).get("title") or "").strip()[:80]
            if not title:
                return self._send(400, {"error": "title required"})
            sess["title"] = title
            save_session(sess)
            # JAG-322: an agent IS a session — keep an org agent's NAME in lockstep
            # with its session TITLE so renaming here updates the Orbit table too.
            try:
                from . import agents as _agents_mod
                if _agents_mod.REGISTRY.is_agent(sid):
                    _agents_mod.REGISTRY.set_name(sid, title)
            except Exception:  # noqa: BLE001 — the rename must never fail on this
                pass
            publish("session.renamed", session=sid, title=title)
            return self._send(200, {"ok": True, "id": sid, "title": title})
        if path.startswith("/api/sessions/") and path.endswith("/graph/reset"):
            # JAG-63: only the user clears the persistent task list (new task).
            sess_id = path[len("/api/sessions/"):-len("/graph/reset")].strip("/")
            return self._send(200, taskgraph.reset(sess_id))
        if path.startswith("/api/runs/") and path.endswith("/graph/reset"):
            # JAG-125: clear the CURRENT run graph from the UI (Execution panel).
            run_id = path[len("/api/runs/"):-len("/graph/reset")].strip("/")
            return self._send(200, taskgraph.reset(run_id))
        if path == "/api/context/compact":
            res = compact_session(body.get("session"), body.get("budget_tokens"), origin="manual")
            return self._send(200 if "error" not in res else 404, res)
        if path == "/api/sessions":
            sess = get_or_create_session(None, body.get("title"))
            publish("session.created", session=sess["id"], title=sess["title"])
            return self._send(200, sess)
        if path.startswith("/api/sessions/") and path.endswith("/model"):
            # JAG-157: per-session model — the session remembers its own LLM.
            sid = path[len("/api/sessions/"):-len("/model")].strip("/")
            if not sid or "/" in sid or ".." in sid:
                return self._send(404, {"error": "session not found"})
            sess = load_session(sid)
            if not sess:
                return self._send(404, {"error": "session not found"})
            ref = _set_session_model(sid, body.get("model"))
            return self._send(200, {"ok": True, "session": sid, "model": ref})
        if path == "/api/eval/run":
            return self._send(200, eval_run(body.get("model"), _as_int(body.get("max_steps", 6), 6),
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
        if _orbit_handle(self, "PATCH", path, qs, body):   # JAG-285: optional beta API
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
        if _orbit_handle(self, "DELETE", path, qs, None):   # JAG-285: optional beta API
            return
        if path.startswith("/api/sessions/"):
            sid = path[len("/api/sessions/"):]
            if not _valid_sid(sid):
                return self._send(404, {"error": "session not found"})
            fpath = os.path.join(SESSIONS_DIR, sid + ".json")
            if not os.path.isfile(fpath):
                return self._send(404, {"error": "session not found"})
            # JAG-179: cascade — the red X must also remove the session's graph,
            # run metrics and edit journal (+ backups), else they leak as orphans.
            # JAG-222: stop a running turn AND tombstone the id first, so the
            # worker's final write cannot resurrect the just-deleted session.
            push_abort(sid)
            with _deleted_lock:
                _DELETED_SESSIONS.add(sid)
                _persist_tombstones()   # JAG-315: survive a restart
            removed = _purge_session_artifacts(sid)
            _forget_session_runtime(sid)
            # JAG-314: an agent IS a session — deleting the session must also
            # release the agent designation (and scrub its jobs/routines), else a
            # later job/routine resurrects it via get_or_create_session.
            try:
                from . import agents as agents_mod
                rel = agents_mod.REGISTRY.release(sid)
                if rel.get("released"):
                    removed.append("agent:" + str(rel["released"]))
            except Exception:  # noqa: BLE001
                pass
            publish("session.deleted", session=sid, removed=removed)
            return self._send(200, {"ok": True, "deleted": sid, "removed": removed})
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
        from . import providers
        providers.load_env()
    except Exception:  # noqa: BLE001 — provider metadata is optional
        pass
    # JAG-123: CLAIM THE PORT FIRST, before any side effect. A second instance
    # (systemd auto-restart after a manual/orphan server already owns :8790) used
    # to run _ensure_dirs + providers.warm + backfill_session_workspaces and
    # publish("service.start") — writing to events.db and rewriting every session
    # every RestartSec — and ONLY THEN failed to bind. That crash looped 15k+
    # times, flooding the event feed and contending on SQLite with the live
    # server (chat "si blocca"). Failing before any write makes a duplicate start
    # a silent, harmless no-op.
    try:
        server = ThreadingHTTPServer((args.host, args.port), Handler)
    except OSError as e:
        print("SparkForge: cannot bind %s:%d (%s) — another instance is already "
              "serving. Exiting without side effects." % (args.host, args.port, e))
        raise SystemExit(3)
    server.host, server.port = args.host, args.port
    try:
        from . import providers
        providers.warm()  # JAG-72: fetch remote model windows off the request path
    except Exception:  # noqa: BLE001 — provider metadata is optional
        pass
    backfill_session_workspaces()  # JAG-117: every session gets a folder
    backfill_jobs()                # JAG-169: every session gets a stable JX id
    reconcile_agent_models()       # JAG-309: agent model == its session's model
    reconcile_orphan_turns()       # JAG-262: close turns killed by a hard restart
    publish("service.start", host=args.host, port=args.port, router=ROUTER_BASE)
    try:
        from . import jobs as _jobs
        _jobs.JOBS.reconcile()  # JAG-288: close jobs killed by a hard restart
    except Exception:  # noqa: BLE001 — job reconcile is best-effort
        pass
    try:
        _start_event_pruning()  # JAG-300: keep the durable replay log bounded
    except Exception:  # noqa: BLE001 — pruning is best-effort
        pass
    try:
        from . import routines
        routines.start_scheduler()  # JAG-287 D: agents wake on a cadence
    except Exception:  # noqa: BLE001 — the heartbeat scheduler is optional
        pass
    print("SparkForge v%s on http://%s:%d  (router: %s)" % (
        VERSION, args.host, args.port, ROUTER_BASE))
    server.serve_forever()


if __name__ == "__main__":
    main()
