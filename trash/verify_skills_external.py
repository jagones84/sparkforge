#!/usr/bin/env python3
"""JAG-56 v0.7.1 — verify skills + agent loop end-to-end from outside."""
import json
import urllib.request
import sys

BASE = "http://127.0.0.1:8790"
TOKEN = "REDACTED-COMPROMISED-TOKEN"
HEADERS = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}


def call(body):
    req = urllib.request.Request(
        f"{BASE}/api/tools/call", data=json.dumps(body).encode(),
        headers=HEADERS, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, {"http_error": e.read().decode()[:300]}


def get(path):
    req = urllib.request.Request(f"{BASE}{path}", headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, {"http_error": e.read().decode()[:300]}


print("=== A. /api/self (skills metadata) ===")
s, d = get("/api/self")
print(f"status={s}")
sk = d.get("skills") or {}
print(f"skills.count={sk.get('count')} categories={sk.get('categories')}")
print(f"install_skill='{(d.get('install_skill') or '')[:200]}'")

print("\n=== B1. skills tool: list ===")
s, d = call({"tool": "skills", "args": {"action": "list"}})
res = (d or {}).get("result") or d
ok = res.get("ok")
count = res.get("count")
print(f"status={s} ok={ok} count={count}")
if ok:
    # count categories seen in stdout
    out = res.get("stdout", "")
    cats = [line.strip().lstrip("[").rstrip("]") for line in out.splitlines()
            if line.strip().startswith("[") and line.strip().endswith("]")]
    print(f"categories_in_stdout={cats}")

print("\n=== B2. skills tool: read paperclip ===")
s, d = call({"tool": "skills", "args": {"action": "read", "name": "paperclip"}})
res = (d or {}).get("result") or d
ok = res.get("ok")
body = res.get("stdout", "") or ""
print(f"status={s} ok={ok} bytes={len(body)}")
print(f"first_240={body[:240]!r}")
print(f"contains_Paperclip={'Paperclip' in body or 'paperclip' in body}")

print("\n=== B3. skills tool: read unknown (clean error) ===")
s, d = call({"tool": "skills", "args": {"action": "read", "name": "no-such-xyz"}})
res = (d or {}).get("result") or d
ok = res.get("ok")
err = res.get("error") or res.get("stderr") or ""
print(f"status={s} ok={ok} err={err[:160]}")

print("\n=== B4. skills tool: read brainstorming ===")
s, d = call({"tool": "skills", "args": {"action": "read", "name": "brainstorming"}})
res = (d or {}).get("result") or d
body = res.get("stdout", "") or ""
print(f"ok={res.get('ok')} bytes={len(body)} first120={body[:120]!r}")
