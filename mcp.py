#!/usr/bin/env python3
"""SparkForge MCP server logic — expose the harness as a Model Context Protocol
server so Paperclip (OpenClaw / Hermes / Goose …) can pilot it.

Transport-agnostic: `handle(message, api)` takes a JSON-RPC 2.0 message and an
`api` object with the harness operations. Two transports use it:
  * mcp_server.py  — stdio (newline-delimited JSON-RPC), `HttpApi` -> running server
  * server.py      — POST /mcp (streamable-HTTP style), `LocalApi` -> in-process

MCP tools exposed: sparkforge_status, sparkforge_chat, sparkforge_plan,
sparkforge_tasks, sparkforge_agent_run, sparkforge_feed, sparkforge_tools,
sparkforge_approvals.
"""

import json
import os
import urllib.error
import urllib.request

PROTOCOL_VERSION = "2025-06-18"
SUPPORTED_PROTOCOLS = ("2025-06-18", "2025-03-26", "2024-11-05")
SERVER_INFO = {"name": "sparkforge", "title": "SparkForge agent harness",
               "version": "0.2.0"}


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
    return _error_text("unknown tool %r" % name)


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
                             "by /api/approvals."),
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
