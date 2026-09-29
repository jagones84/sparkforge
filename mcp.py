#!/usr/bin/env python3
"""SparkForge MCP server logic — expose the harness as a Model Context Protocol
server so Paperclip (OpenClaw / Hermes / Goose …) can pilot it.

Transport-agnostic: `handle(message, api)` takes a JSON-RPC 2.0 message and an
`api` object with the harness operations. Two transports use it:
  * mcp_server.py  — stdio (newline-delimited JSON-RPC), `HttpApi` -> running server
  * server.py      — POST /mcp (streamable-HTTP style), `LocalApi` -> in-process

MCP tools exposed: sparkforge_status, sparkforge_chat, sparkforge_plan,
sparkforge_tasks, sparkforge_agent_run, sparkforge_feed, sparkforge_tools,
sparkforge_approvals + Sperimentale tools (memory, subagent, meta, blackboard,
acp, swarm).
"""

import json
import os
import urllib.error
import urllib.request

PROTOCOL_VERSION = "2025-06-18"
SUPPORTED_PROTOCOLS = ("2025-06-18", "2025-03-26", "2024-11-05")
SERVER_INFO = {"name": "sparkforge", "title": "SparkForge agent harness",
               "version": "0.3.0-sperimentale"}


def _text(s):
    return {"content": [{"type": "text", "text": s if isinstance(s, str)
                         else json.dumps(s, indent=2, ensure_ascii=False)}],
            "isError": False}


def _error_text(s):
    return {"content": [{"type": "text", "text": s}], "isError": True}


MCP_TOOLS = [
    {
        "name": "sparkforge_status",
        "description": "Health + roster + plan/task counts + sandbox backend of the SparkForge harness.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "sparkforge_chat",
        "description": "Send a message to the SparkForge chat (visible CoT) and get the reply.",
        "inputSchema": {"type": "object", "properties": {
            "message": {"type": "string"}, "session": {"type": "string"},
            "model": {"type": "string"}}, "required": ["message"]},
    },
    {
        "name": "sparkforge_plan",
        "description": "Read the current PLAN, or generate a new one from a goal.",
        "inputSchema": {"type": "object", "properties": {"goal": {"type": "string"}}},
    },
    {
        "name": "sparkforge_tasks",
        "description": "Read or mutate the TASKS board (list / add / set status).",
        "inputSchema": {"type": "object", "properties": {
            "action": {"type": "string", "enum": ["list", "add", "set"]},
            "title": {"type": "string"}, "id": {"type": "string"},
            "status": {"type": "string", "enum": ["todo", "doing", "done"]}}},
    },
    {
        "name": "sparkforge_agent_run",
        "description": ("Run the sense-think-act agent loop toward a goal. Actions that "
                        "touch the world go through the approval gate; the result contains "
                        "the full thought/action/observation trace."),
        "inputSchema": {"type": "object", "properties": {
            "goal": {"type": "string"}, "max_steps": {"type": "integer"},
            "model": {"type": "string"}}, "required": ["goal"]},
    },
    {
        "name": "sparkforge_feed",
        "description": "Recent harness events (the loopback feed): chat, plan/task changes, tool calls, approvals.",
        "inputSchema": {"type": "object", "properties": {
            "since": {"type": "integer"}, "limit": {"type": "integer"}}},
    },
    {
        "name": "sparkforge_tools",
        "description": "The tool registry with allowlist + approval policy (shell, fs.read, fs.write, git, http, browser).",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "sparkforge_approvals",
        "description": "List the approval queue or decide a pending action (approve / deny).",
        "inputSchema": {"type": "object", "properties": {
            "action": {"type": "string", "enum": ["list", "decide"]},
            "id": {"type": "string"}, "decision": {"type": "string", "enum": ["approve", "deny"]},
            "by": {"type": "string"}}},
    },
    # ---- Sperimentale MCP tools ----
    {
        "name": "sparkforge_memory",
        "description": "Search or store persistent memory records. Supports keyword and semantic search.",
        "inputSchema": {"type": "object", "properties": {
            "action": {"type": "string", "enum": ["store", "search", "stats"]},
            "query": {"type": "string"}, "kind": {"type": "string"},
            "content": {"type": "string"}, "semantic": {"type": "boolean"},
            "limit": {"type": "integer"}},
            "required": ["action"]},
    },
    {
        "name": "sparkforge_subagent",
        "description": "Spawn a subagent run for delegated subtask, collect result, or check status.",
        "inputSchema": {"type": "object", "properties": {
            "action": {"type": "string", "enum": ["spawn", "collect", "status"]},
            "goal": {"type": "string"}, "max_steps": {"type": "integer"},
            "model": {"type": "string"}, "id": {"type": "string"}},
            "required": ["action"]},
    },
    {
        "name": "sparkforge_meta",
        "description": "Meta-harness self-improvement: run candidate evaluation on Pareto frontier, report status.",
        "inputSchema": {"type": "object", "properties": {
            "action": {"type": "string", "enum": ["run", "status", "best"]},
            "n_candidates": {"type": "integer"},
            "eval_task_id": {"type": "string"}},
            "required": ["action"]},
    },
    {
        "name": "sparkforge_blackboard",
        "description": "Swarm blackboard: post and read shared entries for multi-agent cooperation.",
        "inputSchema": {"type": "object", "properties": {
            "action": {"type": "string", "enum": ["post", "get", "search", "stats"]},
            "topic": {"type": "string"}, "content": {"type": "string"},
            "tags": {"type": "string"}, "id": {"type": "string"},
            "query": {"type": "string"}, "limit": {"type": "integer"}},
            "required": ["action"]},
    },
    {
        "name": "sparkforge_acp",
        "description": "ACP (Agent Client Protocol): communicate with external ACP servers or drive this harness as an ACP target.",
        "inputSchema": {"type": "object", "properties": {
            "action": {"type": "string", "enum": ["server_call", "client_connect", "client_list"]},
            "method": {"type": "string"}, "params": {"type": "object"},
            "name": {"type": "string"}, "url": {"type": "string"}},
            "required": ["action"]},
    },
    {
        "name": "sparkforge_swarm",
        "description": "Swarm coordinator: decompose a goal, spawn workers, collect results, synthesise.",
        "inputSchema": {"type": "object", "properties": {
            "goal": {"type": "string"}, "n_workers": {"type": "integer"},
            "max_steps": {"type": "integer"}},
            "required": ["goal"]},
    },
]


def _ok(msg_id, result):
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def _err(msg_id, code, message):
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}


def call_tool(name, args, api):
    a = args or {}
    if name == "sparkforge_status":
        return _text(api.status())
    if name == "sparkforge_chat":
        if not a.get("message"):
            return _error_text("message is required")
        return _text(api.chat(a["message"], a.get("session"), a.get("model")))
    if name == "sparkforge_plan":
        return _text(api.plan(a.get("goal")))
    if name == "sparkforge_tasks":
        return _text(api.tasks(a))
    if name == "sparkforge_agent_run":
        if not a.get("goal"):
            return _error_text("goal is required")
        return _text(api.agent_run(a["goal"], int(a.get("max_steps", 6)), a.get("model")))
    if name == "sparkforge_feed":
        return _text(api.feed(int(a.get("since", 0)), int(a.get("limit", 40))))
    if name == "sparkforge_tools":
        return _text(api.tools())
    if name == "sparkforge_approvals":
        return _text(api.approvals(a))
    # ---- Sperimentale MCP tool dispatch ----
    if name == "sparkforge_memory":
        return _memory_call(a)
    if name == "sparkforge_subagent":
        return _subagent_call(a)
    if name == "sparkforge_meta":
        return _meta_call(a)
    if name == "sparkforge_blackboard":
        return _blackboard_call(a)
    if name == "sparkforge_acp":
        return _acp_call(a)
    if name == "sparkforge_swarm":
        return _swarm_call(a)
    return _error_text("unknown tool %r" % name)


def _memory_call(a):
    action = a.get("action", "stats")
    try:
        import memory as mem
        if action == "store":
            return _text(mem.store(a.get("kind", "memory.store"), a.get("content", "")))
        if action == "search":
            results = mem.search(a.get("query", ""), a.get("kind"),
                                 int(a.get("limit", 10)), a.get("semantic", False))
            return _text({"results": [{"score": s, **r} for s, r in results]})
        return _text(mem.stats())
    except Exception as e:
        return _error_text("memory error: %s" % e)


def _subagent_call(a):
    action = a.get("action")
    try:
        import subagent as sub
        if action == "spawn":
            goal = a.get("goal", "")
            if not goal:
                return _error_text("goal required")
            return _text(sub.spawn(goal, max_steps=int(a.get("max_steps", 4)),
                                   model=a.get("model")))
        if action == "collect":
            return _text(sub.collect(a.get("id", ""), timeout=int(a.get("timeout", 120))))
        if action == "status":
            return _text(sub.status(a.get("id")))
        return _error_text("unknown subagent action")
    except Exception as e:
        return _error_text("subagent error: %s" % e)


def _meta_call(a):
    action = a.get("action", "status")
    try:
        import meta as mt
        if action == "run":
            candidates = mt.sample_candidates(n=int(a.get("n_candidates", 8)))
            return _text(mt.meta_run(candidates, a.get("eval_task_id")))
        if action == "best":
            return _text(mt.propose_best())
        return _text(mt.status())
    except Exception as e:
        return _error_text("meta error: %s" % e)


def _blackboard_call(a):
    action = a.get("action")
    try:
        import swarm as sw
        if action == "post":
            return _text(sw.post(a.get("topic", "general"), a.get("content", ""),
                                  tags=a.get("tags"), author=a.get("author", "mcp")))
        if action == "get":
            return _text(sw.get(entry_id=a.get("id"), topic=a.get("topic"),
                                 limit=int(a.get("limit", 50))))
        if action == "search":
            return _text(sw.search(a.get("query", ""), topic=a.get("topic"),
                                    limit=int(a.get("limit", 20))))
        return _text(sw.stats())
    except Exception as e:
        return _error_text("blackboard error: %s" % e)


def _acp_call(a):
    action = a.get("action")
    try:
        import acp as acpmod
        if action == "server_call":
            method = a.get("method", "ping")
            params = a.get("params") or {}
            return _text(acpmod.handle_acp_message(
                {"jsonrpc": "2.0", "id": "mcp-acp", "method": method, "params": params}))
        if action == "client_connect":
            ok = acpmod.get_manager().connect(a.get("name"), a.get("url"), a.get("token"))
            return _text({"connected": ok})
        if action == "client_list":
            return _text(acpmod.get_manager().list_connections())
        return _error_text("unknown acp action")
    except Exception as e:
        return _error_text("acp error: %s" % e)


def _swarm_call(a):
    try:
        import swarm as sw
        goal = a.get("goal", "")
        if not goal:
            return _error_text("goal required")
        coord = sw.Coordinator()
        report = coord.run_swarm(goal, int(a.get("n_workers", 3)),
                                  int(a.get("max_steps", 4)), a.get("model"))
        return _text(report)
    except Exception as e:
        return _error_text("swarm error: %s" % e)


def handle(msg, api):
    """Handle one JSON-RPC message. Returns a response dict, or None for
    notifications (no id)."""
    if not isinstance(msg, dict):
        return _err(None, -32600, "invalid request")
    method = msg.get("method")
    msg_id = msg.get("id")
    if method == "notifications/initialized" or method == "initialized":
        return None
    if msg_id is None and method:  # other notifications
        return None
    if method == "initialize":
        params = msg.get("params") or {}
        want = params.get("protocolVersion") or PROTOCOL_VERSION
        return _ok(msg_id, {
            "protocolVersion": want if want in SUPPORTED_PROTOCOLS else PROTOCOL_VERSION,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": SERVER_INFO,
            "instructions": ("SparkForge harness: chat with visible chain-of-thought, "
                             "plan/tasks stores, an approval-gated agent loop, a live feed "
                             "and sandboxed tools. Actions that touch the world are gated "
                             "by /api/approvals.\n\n"
                             "Sperimentale features: persistent memory (sparkforge_memory), "
                             "subagent delegation (sparkforge_subagent), meta-harness "
                             "self-improvement (sparkforge_meta), swarm blackboard "
                             "(sparkforge_blackboard), ACP (sparkforge_acp), "
                             "and swarm coordination (sparkforge_swarm)."),
        })
    if method == "ping":
        return _ok(msg_id, {})
    if method == "tools/list":
        return _ok(msg_id, {"tools": MCP_TOOLS})
    if method == "tools/call":
        params = msg.get("params") or {}
        name = params.get("name")
        args = params.get("arguments") or {}
        try:
            return _ok(msg_id, call_tool(name, args, api))
        except Exception as e:  # noqa: BLE001
            return _ok(msg_id, _error_text("tool %r failed: %s" % (name, e)))
    if method in ("resources/list", "prompts/list"):
        return _ok(msg_id, {"resources": []} if method.startswith("resources") else {"prompts": []})
    return _err(msg_id, -32601, "method not found: %s" % method)


# ------------------------------------------------------------- HTTP backend ---

class HttpApi:
    """Harness operations over the SparkForge HTTP API (used by the stdio server)."""

    def __init__(self, base=None, token=None, timeout=600):
        self.base = (base or os.environ.get("SPARKFORGE_URL", "http://127.0.0.1:8790")).rstrip("/")
        self.token = token or os.environ.get("SPARKFORGE_TOKEN")
        self.timeout = timeout

    def _req(self, method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return json.loads(r.read().decode() or "{}")
        except urllib.error.HTTPError as e:
            try:
                return json.loads(e.read().decode())
            except Exception:
                return {"error": "HTTP %d" % e.code}
        except Exception as e:  # noqa: BLE001
            return {"error": "cannot reach SparkForge at %s (%s)" % (self.base, e)}

    # --- operations ---
    def status(self):
        return self._req("GET", "/api/status")

    def chat(self, message, session=None, model=None):
        out = self._req("POST", "/api/chat", {"message": message, "session": session, "model": model})
        if out.get("error"):
            return out
        return {"session": out.get("session"), "reply": out.get("reply"),
                "reasoning": out.get("reasoning")}

    def plan(self, goal=None):
        if goal:
            return self._req("POST", "/api/plan/generate", {"goal": goal})
        return self._req("GET", "/api/plan")

    def tasks(self, a):
        action = a.get("action", "list")
        if action == "add":
            return self._req("POST", "/api/tasks", {"title": a.get("title", "")})
        if action == "set":
            return self._req("PATCH", "/api/tasks", {"id": a.get("id"), "status": a.get("status")})
        return self._req("GET", "/api/tasks")

    def agent_run(self, goal, max_steps=6, model=None):
        return self._req("POST", "/api/agent/run",
                         {"goal": goal, "max_steps": max_steps, "model": model})

    def feed(self, since=0, limit=40):
        return self._req("GET", "/api/feed/recent?since=%d&limit=%d" % (since, limit))

    def tools(self):
        return self._req("GET", "/api/tools")

    def approvals(self, a):
        action = a.get("action", "list")
        if action == "decide":
            return self._req("POST", "/api/approvals/" + str(a.get("id")),
                             {"decision": a.get("decision"), "by": a.get("by", "mcp")})
        return self._req("GET", "/api/approvals")