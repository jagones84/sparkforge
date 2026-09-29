#!/usr/bin/env python3
"""SparkForge MCP client — v0.3 / Sperimentale

Connects to external MCP servers (Filesystem, Playwright, GitHub, etc.) and
exposes their tools as native SparkForge tools through the registry.

Two transports:
- **stdio**: spawn a subprocess, speak JSON-RPC over its stdin/stdout
- **HTTP** / **SSE**: POST /mcp (streamable-HTTP) or connect to an SSE endpoint

Configuration: `config/mcp_clients.yaml` (or JSON). Examples:

    clients:
      filesystem:
        command: "npx"
        args: ["-y", "@modelcontextprotocol/server-filesystem", "/home/jagones"]
        enabled: true
      playwright:
        command: "npx"
        args: ["-y", "@playwright/mcp"]
        enabled: true
      github:
        url: "http://127.0.0.1:8791/mcp"
        enabled: true
      brave-search:
        command: "npx"
        args: ["-y", "@anthropic/mcp-brave-search"]
        enabled: false

Usage:
    from mcp_client import MCPClientManager
    manager = MCPClientManager()
    manager.start_all()         # spawn configured clients
    tools = manager.list_tools()  # merge all client tools
    manager.call_tool("filesystem__read", {"path": "/etc/hostname"})
"""

import json
import os
import queue
import re
import subprocess
import sys
import threading
import time

import registry

REPO = registry.REPO
CONFIG_PATH = os.path.join(REPO, "config", "mcp_clients.yaml")
CONFIG_JSON_PATH = os.path.join(REPO, "config", "mcp_clients.json")

PROTOCOL_VERSION = "2025-06-18"
SUPPORTED_PROTOCOLS = ("2025-06-18", "2025-03-26", "2024-11-05")

_log_lock = threading.Lock()


def log(*a, **kw):
    with _log_lock:
        print("[mcp-client]", *a, file=sys.stderr, flush=True, **kw)


# --------------------------------------------------------------- session ---

class MCPSession:
    """A single MCP client session (stdio or HTTP)."""

    def __init__(self, name, config):
        self.name = name
        self.config = config
        self.proc = None          # subprocess for stdio
        self.tools = {}           # name -> {name, description, inputSchema}
        self._lock = threading.RLock()
        self._req_id = 0
        self._pending = {}        # id -> queue.Queue
        self._reader = None
        self._stop = False
        self._connected = False
        self._connect_time = None
        self._http_base = None    # HTTP transport base URL

    @property
    def connected(self):
        return self._connected

    # ---- stdio transport ----

    def _connect_stdio(self, command, args, env):
        full_env = dict(os.environ)
        full_env.update(env or {})
        self.proc = subprocess.Popen(
            [command] + args, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, env=full_env,
            cwd=self.config.get("cwd", REPO))
        log("%s: spawned pid=%d", self.name, self.proc.pid)

        def _reader():
            try:
                for line in self.proc.stdout:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        msg = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    mid = msg.get("id")
                    if mid is not None and mid in self._pending:
                        self._pending[mid].put(msg)
                    elif msg.get("method") and msg.get("params"):
                        pass  # server-initiated notification — ignore for now
            except Exception:
                pass
            self._connected = False

        self._reader = threading.Thread(target=_reader, daemon=True)
        self._reader.start()
        return True

    def _send_raw(self, obj, timeout=20):
        mid = self._next_id()
        q = queue.Queue()
        with self._lock:
            self._pending[mid] = q
            req = {**obj, "id": mid}
            if self.proc and self.proc.stdin:
                self.proc.stdin.write(json.dumps(req, ensure_ascii=False) + "\n")
                self.proc.stdin.flush()
            elif self._http_base:
                return self._http_call(obj, timeout)
            else:
                self._pending.pop(mid, None)
                return None
        try:
            return q.get(timeout=timeout)
        except queue.Empty:
            with self._lock:
                self._pending.pop(mid, None)
            return None

    def _next_id(self):
        with self._lock:
            self._req_id += 1
            return self._req_id

    # ---- HTTP transport ----

    def _connect_http(self, url):
        if not url.startswith("http"):
            url = "http://" + url
        self._http_base = url.rstrip("/")
        log("%s: HTTP base = %s", self.name, self._http_base)
        return True

    def _http_call(self, obj, timeout=20):
        import urllib.request as ureq
        import urllib.error as uerr
        data = json.dumps(obj).encode("utf-8")
        req = ureq.Request(self._http_base, data=data,
                           headers={"Content-Type": "application/json"})
        try:
            with ureq.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8") or "{}")
        except uerr.HTTPError as e:
            try:
                return json.loads(e.read().decode())
            except Exception:
                return {"error": {"code": e.code, "message": str(e)}}
        except Exception as e:
            return {"error": {"code": -1, "message": str(e)}}

    def _send_http(self, obj, timeout=20):
        return self._http_call(obj, timeout)

    # ---- public session lifecycle ----

    def initialize(self):
        params = {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "sparkforge", "version": "0.3.0"},
        }
        resp = self._send_raw({"method": "initialize", "params": params}, timeout=30)
        if resp is None:
            return False
        result = resp.get("result") or {}
        server_ver = result.get("protocolVersion", "unknown")
        if server_ver not in SUPPORTED_PROTOCOLS and server_ver != "unknown":
            log("%s: protocol version %s may be incompatible", self.name, server_ver)
        # Send initialized notification
        self._send_raw({"method": "notifications/initialized"})
        self._connected = True
        self._connect_time = time.time()
        log("%s: initialized (protocol %s)", self.name, server_ver)
        return True

    def fetch_tools(self):
        resp = self._send_raw({"method": "tools/list"}, timeout=30)
        if resp is None:
            return []
        tools = (resp.get("result") or {}).get("tools") or []
        with self._lock:
            for t in tools:
                tname = t.get("name", "unknown")
                # namespace by client name to avoid collisions
                self.tools[tname] = t
        log("%s: %d tools available", self.name, len(tools))
        return tools

    def call_tool(self, tool_name, args, timeout=120):
        """Call a tool on this client session."""
        # Normalise: if the caller uses the namespaced form "client__tool",
        # strip the prefix
        if "__" in tool_name:
            _, _, bare = tool_name.partition("__")
            tool_name = bare or tool_name
        resp = self._send_raw({
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": args or {}},
        }, timeout=timeout)
        if resp is None:
            return {"isError": True, "content": [{"type": "text", "text": "mcp call timed out"}]}
        result = resp.get("result") or {}
        if "error" in resp:
            return {"isError": True, "content": [{"type": "text", "text": str(resp["error"])}]}
        return result

    def ping(self):
        resp = self._send_raw({"method": "ping"}, timeout=10)
        return resp is not None

    def close(self):
        self._stop = True
        if self.proc:
            try:
                self.proc.terminate()
                self.proc.wait(timeout=5)
            except Exception:
                self.proc.kill()
        self._connected = False


# ------------------------------------------------------------- manager ----

def _load_config():
    """Load client config from yaml or json."""
    if os.path.exists(CONFIG_PATH):
        try:
            import yaml  # noqa: F811
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            return data.get("clients") or {}
        except ImportError:
            log("PyYAML not installed but %s exists", CONFIG_PATH)
            return {}
        except Exception as e:
            log("error loading %s: %s", CONFIG_PATH, e)
            return {}
    if os.path.exists(CONFIG_JSON_PATH):
        with open(CONFIG_JSON_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("clients") or {}
    return {}


class MCPClientManager:
    """Manages all external MCP client sessions."""

    def __init__(self):
        self.sessions = {}        # name -> MCPSession
        self._lock = threading.RLock()
        self._tool_prefix = {}    # tool_name -> client_name
        self._started = False

    def _ensure_config(self):
        """Create default config if neither file exists."""
        if not os.path.exists(CONFIG_PATH) and not os.path.exists(CONFIG_JSON_PATH):
            default = {
                "clients": {
                    "example-filesystem": {
                        "command": "npx",
                        "args": ["-y", "@modelcontextprotocol/server-filesystem",
                                 os.path.expanduser("~")],
                        "enabled": False,
                    },
                }
            }
            try:
                import yaml
                os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
                with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                    yaml.safe_dump(default, f, sort_keys=False, allow_unicode=True,
                                   default_flow_style=False)
                log("created default config: %s", CONFIG_PATH)
            except ImportError:
                with open(CONFIG_JSON_PATH, "w", encoding="utf-8") as f:
                    json.dump(default, f, indent=2, ensure_ascii=False)
                log("created default config: %s", CONFIG_JSON_PATH)

    def start_all(self):
        """Start all enabled MCP client sessions."""
        with self._lock:
            if self._started:
                return
            self._ensure_config()
            configs = _load_config()
            for name, cfg in configs.items():
                if not cfg.get("enabled", True):
                    log("%s: disabled, skipping", name)
                    continue
                session = MCPSession(name, cfg)
                try:
                    ok = False
                    if cfg.get("command") and cfg.get("args") is not None:
                        ok = session._connect_stdio(
                            cfg["command"], list(cfg.get("args", [])),
                            cfg.get("env", {}))
                    elif cfg.get("url"):
                        ok = session._connect_http(cfg["url"])
                    if ok:
                        init_ok = session.initialize()
                        if init_ok:
                            session.fetch_tools()
                            self.sessions[name] = session
                            # Register tools
                            for tname in list(session.tools):
                                self._tool_prefix[tname] = name
                            log("%s: connected with %d tools", name, len(session.tools))
                        else:
                            log("%s: initialize failed, closing", name)
                            session.close()
                    else:
                        log("%s: transport connect failed", name)
                except Exception as e:
                    log("%s: connection error: %s", name, e)
                    try:
                        session.close()
                    except Exception:
                        pass
            self._started = True
            self._register_as_tools()

    def _register_as_tools(self):
        """Register each external MCP tool as a harness tool in the registry.

        Each external tool gets a synthetic entry named `client__toolname` so
        there are no name collisions. The approval policy is 'required' by
        default (configurable in tools.yaml).
        """
        for tname, cname in self._tool_prefix.items():
            session = self.sessions.get(cname)
            if not session:
                continue
            tspec = session.tools.get(tname)
            if not tspec:
                continue
            full_name = "%s__%s" % (cname, tname)
            schema = tspec.get("inputSchema") or {}
            # Register as an external tool — the harness registry needs to know
            # about these so the agent can call them via gated_call
            # We inject them directly into the catalog
            # Store in the module-level _EXTERNAL registry
            _EXTERNAL_TOOLS[full_name] = {
                "name": full_name,
                "enabled": True,
                "approval": "required",
                "allowed": True,
                "description": (tspec.get("description", "") +
                                " [external MCP: %s/%s]" % (cname, tname)),
                "inputSchema": schema,
                "client_name": cname,
                "original_name": tname,
            }

    def list_external_tools(self):
        """Return all external tools as registry-compatible entries."""
        return list(_EXTERNAL_TOOLS.values())

    def call_external(self, full_name, args, run_id=None):
        """Call an external MCP tool by its full namespaced name."""
        info = _EXTERNAL_TOOLS.get(full_name)
        if not info:
            return {"ok": False, "error": "unknown external tool: %s" % full_name}
        session = self.sessions.get(info["client_name"])
        if not session:
            return {"ok": False, "error": "MCP client %r not connected" % info["client_name"]}
        result = session.call_tool(info["original_name"], args)
        content = result.get("content") or []
        texts = [c.get("text", "") for c in content if c.get("type") == "text"]
        is_err = result.get("isError", False)
        return {
            "ok": not is_err,
            "tool": full_name,
            "stdout": "\n".join(texts),
            "stderr": "",
            "exit_code": 1 if is_err else 0,
            "backend": "mcp(%s)" % info["client_name"],
            "sandboxed": False,
            "external": True,
        }

    def disconnect_all(self):
        for session in self.sessions.values():
            session.close()
        self.sessions.clear()
        _EXTERNAL_TOOLS.clear()
        self._started = False

    def status(self):
        return {
            "clients": {n: {"connected": s.connected,
                            "tools": len(s.tools),
                            "uptime": round(time.time() - s._connect_time, 1)
                            if s._connect_time else 0}
                       for n, s in self.sessions.items()},
            "external_tools": len(_EXTERNAL_TOOLS),
        }


# Module-level registry of external tools (populated by the manager)
_EXTERNAL_TOOLS = {}

# Singleton
_manager = None


def get_manager():
    global _manager
    if _manager is None:
        _manager = MCPClientManager()
    return _manager


def list_tools():
    """Convenience: get all external tools from the singleton manager."""
    return get_manager().list_external_tools()


def call_tool(full_name, args, run_id=None):
    return get_manager().call_external(full_name, args, run_id)


def status():
    return get_manager().status()


def start():
    return get_manager().start_all()