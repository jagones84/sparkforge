#!/usr/bin/env python3
"""SparkForge CLI — command the harness from the terminal.

Usage:
  python3 forge.py chat "message" [--session ID] [--model ALIAS] [--stream]
  python3 forge.py agent "goal" [--max-steps N]
  python3 forge.py plan show | plan generate "goal" | plan toggle ID
  python3 forge.py tasks ls | tasks add "title" | tasks done ID | tasks set ID STATUS
  python3 forge.py tools ls | tools call <tool> '<json-args>'
  python3 forge.py approvals ls | approvals show ID | approvals approve ID | approvals deny ID
  python3 forge.py runs ls | runs show RUN_ID | control pause|resume|abort RUN_ID
  python3 forge.py status | models | feed | sandbox | mcp
Environment:
  SPARKFORGE_URL (default http://127.0.0.1:8790)
  SPARKFORGE_TOKEN (bearer token, optional)
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

BASE = os.environ.get("SPARKFORGE_URL", "http://127.0.0.1:8790").rstrip("/")
TOKEN = os.environ.get("SPARKFORGE_TOKEN")


def req(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(BASE + path, data=data, method=method,
                               headers={"Content-Type": "application/json",
                                        **({"Authorization": "Bearer " + TOKEN} if TOKEN else {})})
    try:
        with urllib.request.urlopen(r, timeout=300) as resp:
            return json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode())
        except Exception:
            return {"error": "HTTP %d" % e.code}
    except urllib.error.URLError as e:
        return {"error": "cannot reach SparkForge at %s (%s)" % (BASE, e.reason)}


def sse(path):
    """Consume an SSE endpoint, printing deltas live."""
    r = urllib.request.Request(BASE + path, headers={
        "Accept": "text/event-stream",
        **({"Authorization": "Bearer " + TOKEN} if TOKEN else {})})
    ev, data = None, []
    try:
        with urllib.request.urlopen(r, timeout=600) as resp:
            for raw in resp:
                line = raw.decode("utf-8", "replace").rstrip("\n")
                if line.startswith("event:"):
                    ev = line[6:].strip()
                elif line.startswith("data:"):
                    data.append(line[5:].strip())
                elif line == "" and ev:
                    payload = "\n".join(data)
                    data = []
                    yield ev, payload
                    ev = None
    except KeyboardInterrupt:
        return


def stream_chat(path):
    for ev, payload in sse(path):
        try:
            d = json.loads(payload) if payload and payload != "{}" else {}
        except json.JSONDecodeError:
            continue
        if ev == "chat.delta":
            sys.stdout.write("[90m…think[0m " if d.get("channel") == "think" else "")
            sys.stdout.write(d.get("text", ""))
            sys.stdout.flush()
        elif ev == "error":
            print("\n[error] %s" % d.get("error"), file=sys.stderr)
        elif ev == "done":
            print()


def cmd_chat(args):
    if args.stream:
        from urllib.parse import quote
        stream_chat("/api/chat/stream?message=%s%s%s" % (
            quote(args.message),
            "&session=" + args.session if args.session else "",
            "&model=" + args.model if args.model else ""))
        return
    out = req("POST", "/api/chat", {"message": args.message, "session": args.session,
                                    "model": args.model})
    if "error" in out:
        print("error:", out["error"], file=sys.stderr)
        sys.exit(1)
    if out.get("reasoning"):
        print("[thinking]", out["reasoning"][:600], "\n")
    print(out.get("reply", ""))


def cmd_agent(args):
    from urllib.parse import quote
    url = "/api/agent/run?goal=%s&max_steps=%d%s" % (
        quote(args.goal), args.max_steps, "&model=" + args.model if args.model else "")
    try:
        for ev, payload in sse(url):
            try:
                d = json.loads(payload) if payload else {}
            except json.JSONDecodeError:
                continue
            if ev == "agent.iteration":
                print("\n── iteration %s/%s ──" % (d.get("i"), d.get("of")))
            elif ev == "agent.think":
                pass  # already streamed via agent.thought below
            elif ev == "agent.thought":
                print("🧠 thought:", d.get("thought", ""))
                print("⚡ action:", d.get("action"))
            elif ev == "agent.observation":
                print("👁 observation:", d.get("observation"))
            elif ev == "agent.note":
                print("📝 note:", d.get("text"))
            elif ev == "agent.finish":
                print("\n🏁 finish:", d.get("summary", ""))
            elif ev == "error":
                print("[error]", d.get("error"), file=sys.stderr)
    except KeyboardInterrupt:
        pass


def cmd_plan(args):
    if args.action == "show":
        plan = req("GET", "/api/plan")
        print("GOAL:", plan.get("goal") or "(none)")
        for i, s in enumerate(plan.get("steps", []), 1):
            print(" %d. [%s] %s %s" % (i, "x" if s.get("done") else " ",
                                       s.get("title", ""), "(" + s.get("id", "") + ")"))
    elif args.action == "generate":
        out = req("POST", "/api/plan/generate", {"goal": args.goal})
        if "error" in out:
            print("error:", out["error"], file=sys.stderr)
            sys.exit(1)
        for s in out.get("plan", {}).get("steps", []):
            print(" •", s.get("title"))
    elif args.action == "toggle":
        print(json.dumps(req("POST", "/api/plan/toggle", {"id": args.id}), indent=2))


def cmd_tasks(args):
    if args.action == "ls":
        out = req("GET", "/api/tasks")
        for t in out.get("tasks", []):
            print(" [%s] %s (%s)" % (t.get("status", "?"), t.get("title"), t.get("id")))
        if out.get("remaining"):
            print("\nRemaining:")
            for r in out["remaining"]:
                print("  -", r)
    elif args.action == "add":
        print(json.dumps(req("POST", "/api/tasks", {"title": args.value}), indent=2))
    elif args.action == "done":
        print(json.dumps(req("PATCH", "/api/tasks", {"id": args.value, "status": "done"}), indent=2))
    elif args.action == "set":
        print(json.dumps(req("PATCH", "/api/tasks", {"id": args.value, "status": args.status}), indent=2))


def cmd_status(_):
    print(json.dumps(req("GET", "/api/status"), indent=2))


def cmd_sandbox(_):
    print(json.dumps(req("GET", "/api/sandbox?force=1"), indent=2))


def cmd_tools(args):
    if args.action == "ls":
        out = req("GET", "/api/tools")
        for t in out.get("tools", []):
            print(" %-9s enabled=%-5s approval=%-8s auto=%d :: %s"
                  % (t["name"], t["enabled"], t["approval"], len(t.get("auto_approve") or []),
                     (t.get("description") or "")[:70]))
        print("\nsandbox: %s (isolated=%s)" % (out.get("sandbox", {}).get("backend"),
                                               out.get("sandbox", {}).get("isolated")))
    elif args.action == "call":
        try:
            tool_args = json.loads(args.value2) if args.value2 else {}
        except json.JSONDecodeError as e:
            print("bad json args:", e, file=sys.stderr)
            sys.exit(2)
        out = req("POST", "/api/tools/call", {"tool": args.value, "args": tool_args})
        print(json.dumps(out, indent=2, ensure_ascii=False))


def cmd_approvals(args):
    if args.action == "ls":
        out = req("GET", "/api/approvals")
        print("stats:", json.dumps(out.get("stats", {})))
        for a in out.get("approvals", []):
            print(" [%-13s] %-9s %-10s %s" % (a["status"], a["tool"], a["id"], a["summary"][:70]))
    elif args.action == "show":
        print(json.dumps(req("GET", "/api/approvals/" + args.value), indent=2, ensure_ascii=False))
    elif args.action in ("approve", "deny"):
        out = req("POST", "/api/approvals/" + args.value,
                  {"decision": args.action, "by": "cli"})
        print(json.dumps(out, indent=2, ensure_ascii=False))


def cmd_runs(args):
    if args.action == "ls":
        for r in req("GET", "/api/agent/runs").get("runs", []):
            print(" [%-9s] %-16s steps=%-2s %s" % (r["status"], r["id"], r["steps"],
                                                   (r.get("goal") or "")[:60]))
    else:
        print(json.dumps(req("GET", "/api/agent/runs/" + args.value), indent=2, ensure_ascii=False))


def cmd_control(args):
    out = req("POST", "/api/agent/control", {"runId": args.value2, "action": args.value})
    print(json.dumps({k: out.get(k) for k in ("id", "status", "goal")}, indent=2))


def cmd_mcp(_):
    """Tiny MCP client: initialize a session over HTTP and list tools."""
    init = req("POST", "/mcp", {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                                "params": {"protocolVersion": "2025-06-18"}})
    print("server:", json.dumps(init.get("result", {}).get("serverInfo", {})))
    tl = req("POST", "/mcp", {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    for t in tl.get("result", {}).get("tools", []):
        print(" -", t["name"], "::", t["description"][:70])


def cmd_models(_):
    out = req("GET", "/api/models")
    for m in out.get("models", []):
        print(" %-60s %s" % (m.get("alias"), "LOADED" if m.get("loaded") else m.get("status")))


def cmd_feed(_):
    try:
        for ev, payload in sse("/api/feed"):
            try:
                d = json.loads(payload) if payload and not payload.startswith("[") else {}
            except json.JSONDecodeError:
                continue
            if ev == "backlog":
                for e in d if isinstance(d, list) else []:
                    print("%3s %-18s %s" % (e.get("id"), e.get("kind"), json.dumps(
                        {k: v for k, v in e.items() if k not in ("id", "ts", "kind")})[:140]))
            elif ev != "chat.delta":
                print("%-18s %s" % (ev, json.dumps(d, ensure_ascii=False)[:160]))
    except KeyboardInterrupt:
        pass


def main():
    ap = argparse.ArgumentParser(prog="forge")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("chat"); p.add_argument("message"); p.add_argument("--session"); \
        p.add_argument("--model"); p.add_argument("--stream", action="store_true"); p.set_defaults(fn=cmd_chat)
    p = sub.add_parser("agent"); p.add_argument("goal"); p.add_argument("--max-steps", type=int, default=6); \
        p.add_argument("--model"); p.set_defaults(fn=cmd_agent)
    p = sub.add_parser("plan"); p.add_argument("action", choices=["show", "generate", "toggle"]); \
        p.add_argument("value", nargs="?"); p.set_defaults(fn=cmd_plan)
    p = sub.add_parser("tasks"); p.add_argument("action", choices=["ls", "add", "done", "set"]); \
        p.add_argument("value", nargs="?"); p.add_argument("--status"); p.set_defaults(fn=cmd_tasks)
    p = sub.add_parser("tools"); p.add_argument("action", choices=["ls", "call"]); \
        p.add_argument("value", nargs="?"); p.add_argument("value2", nargs="?"); p.set_defaults(fn=cmd_tools)
    p = sub.add_parser("approvals"); \
        p.add_argument("action", choices=["ls", "show", "approve", "deny"]); \
        p.add_argument("value", nargs="?"); p.set_defaults(fn=cmd_approvals)
    p = sub.add_parser("runs"); p.add_argument("action", choices=["ls", "show"]); \
        p.add_argument("value", nargs="?"); p.set_defaults(fn=cmd_runs)
    p = sub.add_parser("control"); p.add_argument("action", choices=["pause", "resume", "abort"]); \
        p.add_argument("run"); p.set_defaults(fn=cmd_control)
    sub.add_parser("sandbox").set_defaults(fn=cmd_sandbox)
    sub.add_parser("mcp").set_defaults(fn=cmd_mcp)
    sub.add_parser("status").set_defaults(fn=cmd_status)
    sub.add_parser("models").set_defaults(fn=cmd_models)
    sub.add_parser("feed").set_defaults(fn=cmd_feed)
    args = ap.parse_args()
    if args.cmd == "plan":
        args.goal = args.value if getattr(args, "action", None) == "generate" else None
        args.id = args.value if getattr(args, "action", None) == "toggle" else None
    if args.cmd == "control":
        args.value, args.value2 = args.action, args.run
    if args.cmd == "tasks":
        args.value = args.value
    args.fn(args)


if __name__ == "__main__":
    main()
