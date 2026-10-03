#!/usr/bin/env python3
"""SparkForge ACP (Agent Client Protocol) — Sperimentale

Bidirectional interoperability: SparkForge can be PILOTED by other harnesses
(ACP server mode) and can PILOT other harnesses (ACP client mode).

Based on the emerging Agent Client Protocol spec (2026):
  - Server: expose SparkForge agent operations (chat, plan, tasks, tool call,
    run) as an ACP endpoint over HTTP.
  - Client: connect to external ACP servers and delegate actions to them.

ACP is transport-agnostic; this implementation uses JSON-RPC 2.0 over HTTP
(POST /acp), similar to the MCP pattern but oriented toward agent-level
operations instead of tool-level:

  agent/run         - run an agent toward a goal
  agent/run_stream  - SSE agent run
  agent/status      - check on a running agent
  agent/control     - pause/resume/abort
  agent/result      - get the result of a completed run
  plan/set          - set the plan
  plan/get          - read the plan
  tasks/list        - list tasks
  tools/list        - list available tools
  tools/call        - call a tool through the approval gate
  memory/search     - search persistent memory
"""

import json
import queue
import threading
import time
import uuid

from . import api_v02
from . import approvals
from . import registry
from . import mcp  # reuse MCP transport helpers

REPO = registry.REPO

PROTOCOL_VERSION = "2026-09-01"
SUPPORTED_VERSIONS = ("2026-09-01",)

SERVER_INFO = {"name": "sparkforge", "title": "SparkForge ACP Server",
               "version": "0.1.0-acp", "protocol": "acp",
               "protocolVersion": PROTOCOL_VERSION}


# -------------------------------------------------------------- ACP server ---

ACP_TOOLS = {
    "agent/run": {
        "description": "Run the SparkForge agent loop toward a goal. Returns run_id; poll agent/status for completion.",
        "properties": {"goal": {"type": "string"}, "max_steps": {"type": "integer", "default": 6},
                       "model": {"type": "string"}, "wait": {"type": "boolean", "default": True}},
        "required": ["goal"],
    },
    "agent/run_stream": {
        "description": "SSE-streamed agent run. Returns events as they happen.",
        "properties": {"goal": {"type": "string"}, "max_steps": {"type": "integer", "default": 6}},
        "required": ["goal"],
    },
    "agent/status": {
        "description": "Check the status of a running or completed agent run.",
        "properties": {"run_id": {"type": "string"}},
        "required": ["run_id"],
    },
    "agent/control": {
        "description": "Pause, resume, or abort a running agent run.",
        "properties": {"run_id": {"type": "string"}, "action": {"type": "string", "enum": ["pause", "resume", "abort"]}},
        "required": ["run_id", "action"],
    },
    "agent/list": {
        "description": "List recent agent runs.",
        "properties": {"limit": {"type": "integer", "default": 20}},
    },
    "plan/get": {
        "description": "Read the current plan.",
        "properties": {},
    },
    "plan/set": {
        "description": "Set a new goal and plan steps.",
        "properties": {"goal": {"type": "string"}, "steps": {"type": "array"}},
        "required": ["goal"],
    },
    "tasks/list": {
        "description": "List the task board.",
        "properties": {},
    },
    "tools/list": {
        "description": "List available tools from the harness registry.",
        "properties": {},
    },
    "tools/call": {
        "description": "Call a tool through the approval gate.",
        "properties": {"tool": {"type": "string"}, "args": {"type": "object"},
                       "wait": {"type": "boolean", "default": True}},
        "required": ["tool"],
    },
    "memory/search": {
        "description": "Search persistent memory.",
        "properties": {"query": {"type": "string"}, "kind": {"type": "string"},
                       "limit": {"type": "integer", "default": 10},
                       "semantic": {"type": "boolean", "default": False}},
        "required": ["query"],
    },
}


def _srv():
    from . import server
    return server


def handle_acp_message(msg):
    """Handle one ACP JSON-RPC message.

    Returns a response dict or None for notifications.
    """
    if not isinstance(msg, dict):
        return _acp_error(None, -32600, "invalid request")
    method = msg.get("method")
    msg_id = msg.get("id")
    params = msg.get("params") or {}

    if method == "initialize":
        version = params.get("protocolVersion", PROTOCOL_VERSION)
        return {"jsonrpc": "2.0", "id": msg_id, "result": {
            "protocolVersion": version if version in SUPPORTED_VERSIONS else PROTOCOL_VERSION,
            "capabilities": {"agent/run": True, "agent/control": True, "memory/search": True},
            "serverInfo": SERVER_INFO,
            "instructions": "SparkForge ACP server. Use agent/run to start an agent, "
                            "agent/status to check, tools/call for gated tool execution.",
        }}
    if method == "ping":
        return _acp_ok(msg_id, {})

    # --- agent operations ---
    if method == "agent/run":
        goal = params.get("goal", "")
        if not goal:
            return _acp_error(msg_id, -32602, "goal required")
        max_steps = int(params.get("max_steps", 6))
        model = params.get("model")
        wait = params.get("wait", True)
        result = api_v02.agent_run_v2(goal, max_steps, model)
        return _acp_ok(msg_id, result)

    if method == "agent/status":
        rid = params.get("run_id") or params.get("id")
        if not rid:
            return _acp_error(msg_id, -32602, "run_id required")
        st = api_v02.run_get(rid)
        if not st:
            return _acp_error(msg_id, -32602, "run not found")
        return _acp_ok(msg_id, st.public())

    if method == "agent/control":
        rid = params.get("run_id")
        action = params.get("action")
        if not rid or action not in ("pause", "resume", "abort"):
            return _acp_error(msg_id, -32602, "run_id + action (pause|resume|abort) required")
        st = api_v02.run_control(rid, action)
        if not st:
            return _acp_error(msg_id, -32602, "run not found")
        return _acp_ok(msg_id, st.public())

    if method == "agent/list":
        limit = int(params.get("limit", 20))
        from .server import runs_summary
        return _acp_ok(msg_id, {"runs": runs_summary(limit)})

    # --- plan operations ---
    if method == "plan/get":
        from .server import load_plan
        return _acp_ok(msg_id, load_plan())

    if method == "plan/set":
        from .server import save_plan
        goal = params.get("goal", "")
        steps = params.get("steps", [])
        plan = {"goal": goal, "steps": steps, "updated": time.time()}
        save_plan(plan)
        return _acp_ok(msg_id, plan)

    # --- tasks ---
    if method == "tasks/list":
        from .server import load_tasks
        tasks = load_tasks()
        todo = [t for t in tasks.get("tasks", []) if t.get("status") != "done"]
        return _acp_ok(msg_id, {**tasks, "remaining": len(todo)})

    # --- tools ---
    if method == "tools/list":
        return _acp_ok(msg_id, {"tools": registry.catalog()})

    if method == "tools/call":
        tool = params.get("tool")
        if not tool:
            return _acp_error(msg_id, -32602, "tool required")
        result = api_v02.gated_call(
            tool, params.get("args") or {},
            params.get("run_id"), params.get("wait", True),
            by=params.get("by", "acp"))
        return _acp_ok(msg_id, result)

    # --- memory ---
    if method == "memory/search":
        query_text = params.get("query", "")
        if not query_text:
            return _acp_error(msg_id, -32602, "query required")
        try:
            from . import memory
            results = memory.search(query_text, params.get("kind"),
                                    int(params.get("limit", 10)),
                                    params.get("semantic", False))
            return _acp_ok(msg_id, {"results": [{"score": s, **r} for s, r in results]})
        except Exception as e:
            return _acp_error(msg_id, -32603, "memory search failed: %s" % e)

    if method in ("notifications/initialized", "initialized"):
        return None

    return _acp_error(msg_id, -32601, "method not found: %s" % method)


def _acp_ok(msg_id, result):
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def _acp_error(msg_id, code, message):
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}


# ------------------------------------------------------------ ACP client ----

class ACPClient:
    """Connect to an external ACP server and drive it programmatically."""

    def __init__(self, name, url, token=None):
        self.name = name
        self.base = url.rstrip("/")
        self.token = token
        self._connected = False

    def _rpc(self, method, params=None, timeout=120):
        import urllib.request
        import urllib.error
        body = json.dumps({
            "jsonrpc": "2.0",
            "id": uuid.uuid4().hex[:8],
            "method": method,
            "params": params or {},
        }).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        req = urllib.request.Request(self.base + "/acp", data=body,
                                     headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as e:
            try:
                return json.loads(e.read().decode())
            except Exception:
                return {"error": {"code": e.code, "message": str(e)}}
        except Exception as e:
            return {"error": {"code": -1, "message": str(e)}}

    def initialize(self):
        resp = self._rpc("initialize", {"protocolVersion": PROTOCOL_VERSION})
        result = resp.get("result") or {}
        self._connected = "serverInfo" in result
        return self._connected

    def agent_run(self, goal, max_steps=6, model=None, wait=True):
        return self._rpc("agent/run", {"goal": goal, "max_steps": max_steps,
                                       "model": model, "wait": wait})

    def agent_status(self, run_id):
        return self._rpc("agent/status", {"run_id": run_id})

    def agent_control(self, run_id, action):
        return self._rpc("agent/control", {"run_id": run_id, "action": action})

    def tools_list(self):
        resp = self._rpc("tools/list")
        return (resp.get("result") or {}).get("tools", [])

    def tools_call(self, tool, args=None, wait=True):
        return self._rpc("tools/call", {"tool": tool, "args": args or {},
                                        "wait": wait})

    def plan_get(self):
        return self._rpc("plan/get")

    def plan_set(self, goal, steps=None):
        return self._rpc("plan/set", {"goal": goal, "steps": steps or []})

    def memory_search(self, query, kind=None, semantic=False):
        return self._rpc("memory/search", {"query": query, "kind": kind,
                                           "semantic": semantic})

    def ping(self):
        resp = self._rpc("ping", timeout=10)
        return "error" not in resp

    @property
    def connected(self):
        return self._connected


class ACPClientManager:
    """Manage connections to external ACP servers."""

    def __init__(self):
        self.clients = {}  # name -> ACPClient
        self._lock = threading.Lock()

    def connect(self, name, url, token=None):
        client = ACPClient(name, url, token)
        ok = client.initialize()
        if ok:
            with self._lock:
                self.clients[name] = client
        return ok

    def disconnect(self, name):
        with self._lock:
            self.clients.pop(name, None)

    def get(self, name):
        with self._lock:
            return self.clients.get(name)

    def list_connections(self):
        with self._lock:
            return {n: {"connected": c.connected} for n, c in self.clients.items()}

    def broadcast(self, method, params=None):
        """Call a method on all connected ACP servers and collect results."""
        results = {}
        with self._lock:
            for name, client in list(self.clients.items()):
                try:
                    results[name] = client._rpc(method, params)
                except Exception as e:
                    results[name] = {"error": str(e)}
        return results


# Singleton
_manager = None


def get_manager():
    global _manager
    if _manager is None:
        _manager = ACPClientManager()
    return _manager


def handle_http(body):
    """Handle an ACP request over HTTP (POST /acp)."""
    return handle_acp_message(body)