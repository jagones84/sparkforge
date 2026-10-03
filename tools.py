#!/usr/bin/env python3
"""SparkForge tool implementations (shell, fs.read, fs.write, git, http, web, browser).

Each `execute(tool, args, run_id)` returns a normalised dict:
    {tool, ok, backend, sandboxed, exit_code, stdout, stderr, duration_ms, ...}

Policy (allowlist / approval) is enforced by the caller (server.py) via
registry.classify(); this module only *runs* an already-permitted action.
"""

import ipaddress
import json
import os
import re
import shlex
import time
import urllib.parse
import urllib.request

import osutil
import registry
import sandbox

REPO = registry.REPO


def _truncate(s, n):
    if not isinstance(s, str):
        s = str(s)
    return s if len(s) <= n else s[:n] + "\n…[truncated %d chars]" % (len(s) - n)


def _host_allowed(url, allow_hosts):
    try:
        host = urllib.parse.urlparse(url).hostname or ""
    except Exception:
        return False, "unparseable url"
    if host in allow_hosts:
        return True, host
    for entry in allow_hosts:
        try:  # support CIDR entries like 10.0.0.0/8
            net = ipaddress.ip_network(entry, strict=False)
            if ipaddress.ip_address(host) in net:
                return True, host
        except ValueError:
            continue
    return False, host


# ------------------------------------------------------------------ shell ----

def _shell(args, run_id):
    command = str(args.get("command", ""))
    if not command.strip():
        return {"ok": False, "error": "empty command"}
    res = sandbox.run(command, run_id=run_id,
                      timeout=args.get("timeout_secs"),
                      workspace=args.get("workspace"))
    res["ok"] = res.get("exit_code") == 0
    return res


# ------------------------------------------------------------------- fs ------

def _fs_read(args, run_id):
    roots = registry.tool_spec("fs.read")["roots"]
    path, err = registry.resolve_path(str(args.get("path", "")), roots)
    if err:
        return {"ok": False, "error": err}
    if not os.path.isfile(path):
        return {"ok": False, "error": "no such file: %s" % path}
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        content = f.read(int(args.get("max_bytes", 65536)))
    return {"ok": True, "path": path, "content": content, "bytes": len(content),
            "backend": "host", "sandboxed": False, "exit_code": 0}


def _journal(run_id, path, before, after, action):
    """JAG-127: record the pre-image so the UI can diff and undo. Never raises."""
    try:
        import edits
        edits.record(run_id, path, before, after, action)
    except Exception:  # noqa: BLE001 — the journal must never break a write
        pass


def _verify_edit(tool, path, snap, res, args, run_id):
    """JAG-131: 'apply-only-if-green' su fs.write/fs.edit.

    Se il verifier e' attivo, esegue il comando di verifica nella sandbox: se
    fallisce, la modifica viene annullata (rollback al pre-image) e `res` diventa
    un fallimento con l'errore del check. Mai bloccante su eccezioni interne.
    """
    try:
        import verify as _v
    except Exception:  # noqa: BLE001
        return res
    try:
        if not _v.should_verify(tool, path):
            return res
    except Exception:  # noqa: BLE001
        return res
    workspace = args.get("workspace") if isinstance(args, dict) else None
    try:
        out, report = _v.verify(tool, path, snap, res, workspace=workspace,
                               run_id=run_id)
    except Exception as e:  # noqa: BLE001 — the verifier must never break a write
        return res
    try:
        import server
        server.publish("verify.run", run=run_id, tool=tool, path=path, **report)
    except Exception:  # noqa: BLE001
        pass
    return out


def _fs_write(args, run_id):
    spec = registry.tool_spec("fs.write")
    roots = spec["roots"]
    path, err = registry.resolve_path(str(args.get("path", "")), roots)
    if err:
        return {"ok": False, "error": err}
    os.makedirs(os.path.dirname(path), exist_ok=True)
    content = str(args.get("content", ""))
    append = bool(args.get("append"))
    existed = os.path.isfile(path)
    before = ""
    if existed:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            before = f.read()
    with open(path, "a" if append else "w", encoding="utf-8") as f:
        f.write(content)
    after = (before + content) if append else content
    _journal(run_id, path, before, after, "modified" if existed else "created")
    res = {"ok": True, "path": path, "bytes": len(content), "append": append,
           "backend": "host", "sandboxed": False, "exit_code": 0}
    return _verify_edit("fs.write", path, {"exists": existed, "content": before},
                        res, args, run_id)


def _fs_edit(args, run_id):
    """Surgical edit: replace exact search text with replacement text."""
    spec = registry.tool_spec("fs.edit")
    path, err = registry.resolve_path(str(args.get("path", "")), spec["roots"])
    if err:
        return {"ok": False, "error": err}
    if not os.path.isfile(path):
        return {"ok": False, "error": "no such file: %s" % path}
    search = str(args.get("search", ""))
    replace = str(args.get("replace", ""))
    if not search:
        return {"ok": False, "error": "empty search string"}
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        content = f.read()
    count = content.count(search)
    if count == 0:
        return {"ok": False, "error": "search text not found in %s" % path}
    if count > 1 and not args.get("replace_all"):
        return {"ok": False, "error": ("search text matches %d times in %s; "
                                        "pass replace_all=true or use a more "
                                        "specific search") % (count, path)}
    n = count if args.get("replace_all") else 1
    new = content.replace(search, replace, n)
    with open(path, "w", encoding="utf-8") as f:
        f.write(new)
    _journal(run_id, path, content, new, "modified")
    res = {"ok": True, "path": path, "replacements": n, "bytes_before": len(content),
           "bytes_after": len(new), "backend": "host", "sandboxed": False,
           "exit_code": 0}
    return _verify_edit("fs.edit", path, {"exists": True, "content": content},
                        res, args, run_id)


# ------------------------------------------------------------------ git ------

def _git(args, run_id):
    raw = str(args.get("args", "")).strip()
    try:
        argv = shlex.split(raw)
    except ValueError as e:
        return {"ok": False, "error": "bad git args: %s" % e}
    if not argv:
        return {"ok": False, "error": "empty git args"}
    cwd = args.get("cwd") or REPO
    if not os.path.isdir(cwd):
        return {"ok": False, "error": "cwd not found: %s" % cwd}
    t0 = time.time()
    import subprocess
    try:
        p = subprocess.run(["git"] + argv, cwd=cwd, capture_output=True, text=True, timeout=25)
        return {"ok": p.returncode == 0, "exit_code": p.returncode,
                "stdout": p.stdout, "stderr": p.stderr, "cwd": cwd,
                "duration_ms": int((time.time() - t0) * 1000),
                "backend": "host(git)", "sandboxed": False}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": "git failed: %s" % e, "exit_code": 125}


# ----------------------------------------------------------------- http ------

def _http_fetch(url, allow_hosts, max_bytes, method="GET"):
    ok, host = _host_allowed(url, allow_hosts)
    if not ok:
        return None, "host %r not in allow_hosts %s" % (host, allow_hosts)
    req = urllib.request.Request(url, method=method,
                                 headers={"User-Agent": "SparkForge/0.2 (+harness)"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read(max_bytes).decode("utf-8", "replace")
            return {"status": resp.status, "body": body, "host": host,
                    "duration_ms": int((time.time() - t0) * 1000)}, None
    except Exception as e:  # noqa: BLE001
        return None, "fetch failed: %s" % e


def _http(args, run_id):
    spec = registry.tool_spec("http")
    data, err = _http_fetch(str(args.get("url", "")), spec["allow_hosts"],
                            int(args.get("max_bytes", 32768)), args.get("method", "GET"))
    if err:
        return {"ok": False, "error": err, "backend": "host(http)", "sandboxed": False}
    body = _truncate(data["body"], 8192)
    return {"ok": True, "exit_code": 0, "stdout": "HTTP %s (%s)\n%s" % (
        data["status"], data["host"], body), "stderr": "",
        "status": data["status"], "bytes": len(data["body"]),
        "duration_ms": data["duration_ms"], "backend": "host(http)", "sandboxed": False}


def _browser(args, run_id):
    spec = registry.tool_spec("browser")
    if not spec["enabled"]:
        return {"ok": False, "error": "browser tool is disabled (set enabled: true in config/tools.yaml)"}
    data, err = _http_fetch(str(args.get("url", "")), spec["allow_hosts"],
                            int(args.get("max_bytes", 32768)))
    if err:
        return {"ok": False, "error": err, "backend": "host(browser)", "sandboxed": False}
    html = data["body"]
    html = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", html)
    text = re.sub(r"(?s)<[^>]+>", " ", html)
    text = re.sub(r"&nbsp;?", " ", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text).strip()
    return {"ok": True, "exit_code": 0, "stdout": _truncate(text, 8192), "stderr": "",
            "status": data["status"], "bytes": len(html), "backend": "host(browser)",
            "sandboxed": False, "note": "lightweight HTML->text extractor, not a headless browser"}


# ------------------------------------------------------------------ web ------

_WEB_UA = "Mozilla/5.0 (X11; Linux aarch64) SparkForge/0.7 (+harness)"
_HERMES_ENV = os.path.expanduser("~/.hermes/.env")


def _secret(name):
    """Env var, falling back to ~/.hermes/.env (the DGX's shared secret store)."""
    val = os.environ.get(name)
    if val and val.strip():
        return val.strip()
    try:
        with open(_HERMES_ENV, "r", encoding="utf-8", errors="replace") as f:
            for ln in f:
                m = re.match(r"\s*(?:export\s+)?%s\s*=\s*(.*)$" % re.escape(name), ln)
                if m:
                    v = m.group(1).strip().strip('"').strip("'")
                    if v:
                        return v
    except OSError:
        pass
    return None


def _strip_html(s):
    s = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", s or "")
    s = re.sub(r"(?s)<[^>]+>", " ", s)
    for a, b in (("&nbsp;", " "), ("&amp;", "&"), ("&quot;", '"'),
                 ("&#x27;", "'"), ("&#39;", "'"), ("&lt;", "<"), ("&gt;", ">")):
        s = s.replace(a, b)
    return re.sub(r"\s+", " ", s).strip()


def _public_host(url):
    """SSRF guard for `web`: only public http(s) hosts are reachable."""
    try:
        parsed = urllib.parse.urlparse(url)
    except Exception:  # noqa: BLE001
        return False, "unparseable url"
    if parsed.scheme not in ("http", "https"):
        return False, "only http/https is allowed"
    host = parsed.hostname or ""
    if not host:
        return False, "no host in url"
    if host.lower() in ("localhost", "localhost.localdomain"):
        return False, "localhost is not allowed"
    try:
        ip = ipaddress.ip_address(host)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            return False, "private/loopback address %s is not allowed" % host
    except ValueError:
        pass  # a DNS name -> allowed
    return True, host


def _web_search(query, n):
    """Tavily/Brave when a key is present, else the keyless DuckDuckGo HTML page."""
    n = max(1, min(int(n or 5), 10))
    if not query.strip():
        return None, "empty query"
    tav = _secret("TAVILY_API_KEY")
    if tav:
        try:
            payload = json.dumps({"api_key": tav, "query": query,
                                  "max_results": n}).encode("utf-8")
            req = urllib.request.Request("https://api.tavily.com/search", data=payload,
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=25) as r:
                data = json.loads(r.read().decode("utf-8", "replace"))
            res = [{"title": it.get("title", ""), "url": it.get("url", ""),
                    "snippet": _strip_html(it.get("content", ""))[:300]}
                   for it in (data.get("results") or [])]
            if res:
                return res, "tavily"
        except Exception:  # noqa: BLE001
            pass
    brave = _secret("BRAVE_API_KEY")
    if brave:
        try:
            u = ("https://api.search.brave.com/res/v1/web/search?q="
                 + urllib.parse.quote(query) + "&count=%d" % n)
            req = urllib.request.Request(u, headers={"Accept": "application/json",
                                                     "X-Subscription-Token": brave})
            with urllib.request.urlopen(req, timeout=25) as r:
                data = json.loads(r.read().decode("utf-8", "replace"))
            res = [{"title": it.get("title", ""), "url": it.get("url", ""),
                    "snippet": _strip_html(it.get("description", ""))[:300]}
                   for it in ((data.get("web") or {}).get("results") or [])]
            if res:
                return res, "brave"
        except Exception:  # noqa: BLE001
            pass
    u = "https://html.duckduckgo.com/html/?q=" + urllib.parse.quote(query)
    req = urllib.request.Request(u, headers={"User-Agent": _WEB_UA,
                                             "Accept-Language": "it,en;q=0.8"})
    with urllib.request.urlopen(req, timeout=25) as r:
        html = r.read(500000).decode("utf-8", "replace")
    links = re.findall(r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', html, re.S)
    snips = re.findall(r'class="result__snippet"[^>]*>(.*?)</a>', html, re.S)
    res = []
    for i, (href, title) in enumerate(links[:n]):
        if "uddg=" in href:
            found = re.search(r"uddg=([^&]+)", href)
            if found:
                href = urllib.parse.unquote(found.group(1))
        res.append({"title": _strip_html(title), "url": href,
                    "snippet": _strip_html(snips[i])[:300] if i < len(snips) else ""})
    return res, "duckduckgo"


def _web_fetch(url, max_bytes):
    """Readable page text: try the keyless r.jina.ai reader, else direct HTML->text."""
    if not re.match(r"^https?://", url):
        url = "https://" + url
    ok, host = _public_host(url)
    if not ok:
        return None, host
    try:
        req = urllib.request.Request("https://r.jina.ai/" + url,
                                     headers={"User-Agent": _WEB_UA})
        with urllib.request.urlopen(req, timeout=30) as r:
            text = r.read(max_bytes).decode("utf-8", "replace")
        if text.strip():
            return {"url": url, "text": text, "via": "jina", "host": host}, None
    except Exception:  # noqa: BLE001
        pass
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _WEB_UA})
        with urllib.request.urlopen(req, timeout=25) as r:
            raw = r.read(max_bytes).decode("utf-8", "replace")
        return {"url": url, "text": _strip_html(raw), "via": "direct", "host": host}, None
    except Exception as e:  # noqa: BLE001
        return None, "fetch failed: %s" % e


def _web(args, run_id):
    """Harness-native public-internet tool: search + fetch (read-only)."""
    action = (args.get("action") or "search").strip().lower()
    t0 = time.time()
    if action in ("fetch", "get", "read"):
        url = str(args.get("url") or args.get("query") or "").strip()
        if not url:
            return {"ok": False, "error": "url required for action=fetch",
                    "backend": "host(web)", "sandboxed": False}
        data, err = _web_fetch(url, int(args.get("max_bytes", 8192)))
        if err:
            return {"ok": False, "error": err, "backend": "host(web)", "sandboxed": False}
        return {"ok": True, "exit_code": 0, "stderr": "", "stdout": _truncate(data["text"], 8192),
                "url": data["url"], "via": data["via"],
                "duration_ms": int((time.time() - t0) * 1000),
                "backend": "host(web)", "sandboxed": False}
    query = str(args.get("query") or "").strip()
    try:
        results, engine = _web_search(query, args.get("max_results", 5))
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": "search failed: %s" % e,
                "backend": "host(web)", "sandboxed": False}
    if not results:
        return {"ok": False, "error": "no results for %r" % query, "engine": engine,
                "backend": "host(web)", "sandboxed": False}
    lines = ["%d. %s\n   %s\n   %s" % (i + 1, r["title"], r["url"], r["snippet"])
             for i, r in enumerate(results)]
    return {"ok": True, "exit_code": 0, "stderr": "", "engine": engine,
            "count": len(results), "stdout": _truncate("\n".join(lines), 8192),
            "results": results, "duration_ms": int((time.time() - t0) * 1000),
            "backend": "host(web)", "sandboxed": False}


def _skills(args, run_id):
    """Skills registry: list available skills or read one SKILL.md."""
    import skills as skills_mod
    action = str(args.get("action", "list"))
    if action == "read":
        name = str(args.get("name", ""))
        got = skills_mod.get_skill(name)
        if got is None:
            avail = ", ".join(s["name"] for s in skills_mod.list_skills())
            return {"ok": False, "error": "skill %r not found; available: %s"
                    % (name, avail), "stdout": "", "stderr": ""}
        content = got.pop("content")
        return {"ok": True, "exit_code": 0, "stdout": content, "stderr": "",
                "skill": got, "backend": "host", "sandboxed": False}
    skills = skills_mod.list_skills()
    lines = []
    cats = {}
    for s in skills:
        cats.setdefault(s["category"], []).append(s)
    for cat in sorted(cats):
        lines.append("[%s]" % cat)
        for s in cats[cat]:
            lines.append("  %s :: %s" % (s["name"], (s["description"] or s["title"])[:120]))
    stdout = ("%d skills from %s (read one with the skills tool, "
              "action=read):\n%s" % (len(skills), skills_mod.SKILLS_DIR,
                                       "\n".join(lines)))
    return {"ok": True, "exit_code": 0, "stdout": stdout, "stderr": "",
            "count": len(skills), "backend": "host", "sandboxed": False}


def _self(args, run_id):
    """v0.5 self-knowledge: paths, config, docs, systemd state, extension recipe."""
    import subprocess as sp
    info = {
        "ok": True, "backend": "host", "sandboxed": False, "exit_code": 0,
        "name": "SparkForge", "version": "0.5.0",
        "repo_path": REPO,
        "data_dir": os.path.join(REPO, "data"),
        "sessions_dir": os.path.join(REPO, "data", "sessions"),
        "webui": os.path.join(REPO, "webui"),
        "entrypoint": os.path.join(REPO, "server.py"), "port": 8790,
        "router": os.environ.get("SPARKFORGE_ROUTER", "http://127.0.0.1:8080"),
        "config": {"tools": os.path.join(REPO, "config", "tools.yaml"),
                   "tools_overlay": os.path.join(REPO, "data", "tools.overlay.yaml"),
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
        import skills as skills_mod
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


def _memory(args, run_id):
    """Agent memory (JAG-73): store a durable note, or recall/search memories.

    action=store  {content, kind?}            → append-only record
    action=recall {query, kind?, limit?}      → semantic + keyword search
    action=recent {kind?, limit?}             → newest first
    action=core   {}                          → read the always-visible CORE block
    action=set_core {content}                 → rewrite the CORE block (JAG-127f)

    Closes a real gap: the store existed and was auto-injected, but the agent had
    NO tool to deliberately remember or recall anything.
    """
    import memory as mem
    action = (args.get("action") or "recall").strip().lower()
    limit = int(args.get("limit") or (10 if action == "recent" else 5))
    if action in ("core", "core_read", "read_core"):
        txt = mem.core_read().strip()
        return {"ok": True, "count": 1 if txt else 0,
                "stdout": txt or "(core memory is empty)", "backend": "host",
                "sandboxed": False}
    if action in ("set_core", "core_write", "write_core"):
        content = (args.get("content") or "").strip()
        if not content:
            return {"ok": False, "error": "content required for action=set_core",
                    "backend": "host", "sandboxed": False}
        res = mem.core_write(content)
        return {"ok": True, "count": 1,
                "stdout": "core memory updated (%d chars)" % res.get("chars", len(content)),
                "backend": "host", "sandboxed": False}
    if action == "store":
        content = (args.get("content") or "").strip()
        if not content:
            return {"ok": False, "error": "content required for action=store",
                    "backend": "host", "sandboxed": False}
        kind = (args.get("kind") or "memory.store").strip()
        mem.store(kind, content, session=run_id or "", source="agent")
        return {"ok": True, "count": 1,
                "stdout": "stored %d chars as %s" % (len(content), kind),
                "backend": "host", "sandboxed": False}
    try:
        if action == "recent":
            hits = [(1.0, r) for r in mem.query("", args.get("kind"), limit)]
        else:
            query = (args.get("query") or "").strip()
            if not query:
                return {"ok": False, "error": "query required for action=recall",
                        "backend": "host", "sandboxed": False}
            hits = mem.search(query, args.get("kind"), limit, True)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": "memory lookup failed: %s" % e,
                "backend": "host", "sandboxed": False}
    lines = ["- (%s, %.2f) %s" % (r.get("kind"), s, (r.get("content") or "")[:200])
             for s, r in hits]
    return {"ok": True, "count": len(hits), "stdout": "\n".join(lines) or "(no memories)",
            "backend": "host", "sandboxed": False}


def _diff(args, run_id):
    """Native diff tool: unified diff of two files (roots-checked) or two texts."""
    import difflib
    action = str(args.get("action") or "files").strip().lower()
    ctx = int(args.get("context", 3))
    if action == "text":
        a = str(args.get("text_a", ""))
        b = str(args.get("text_b", ""))
        label_a, label_b = "a", "b"
    else:
        roots = registry.tool_spec("fs.read")["roots"]
        pa, err = registry.resolve_path(str(args.get("a", "")), roots)
        if err:
            return {"ok": False, "error": err, "backend": "host", "sandboxed": False}
        pb, err = registry.resolve_path(str(args.get("b", "")), roots)
        if err:
            return {"ok": False, "error": err, "backend": "host", "sandboxed": False}
        if not os.path.isfile(pa):
            return {"ok": False, "error": "no such file: %s" % pa,
                    "backend": "host", "sandboxed": False}
        if not os.path.isfile(pb):
            return {"ok": False, "error": "no such file: %s" % pb,
                    "backend": "host", "sandboxed": False}
        with open(pa, "r", encoding="utf-8", errors="replace") as f:
            a = f.read()
        with open(pb, "r", encoding="utf-8", errors="replace") as f:
            b = f.read()
        label_a, label_b = pa, pb
    diff = list(difflib.unified_diff(a.splitlines(), b.splitlines(),
                                     fromfile=label_a, tofile=label_b, n=ctx, lineterm=""))
    added = sum(1 for ln in diff if ln.startswith("+") and not ln.startswith("+++"))
    removed = sum(1 for ln in diff if ln.startswith("-") and not ln.startswith("---"))
    return {"ok": True, "exit_code": 0, "stderr": "", "identical": not diff,
            "added": added, "removed": removed,
            "stdout": _truncate("\n".join(diff) if diff else "(identici)", 8192),
            "backend": "host", "sandboxed": False}


def _improve(args, run_id=None):
    """Registra una proposta di auto-miglioramento (skill/regole).

    scope=mine (JAG-133/135): il self-evolving lavora sulle sequenze di tool
    realmente osservate. action:
      - mine   (default) -> mina la history e deposita una BOZZA per pattern;
      - evolve           -> stadio 2: draft -> synth -> verify in sandbox ->
                            archive (solo se verde, write-gate);
      - verify           -> esegue il check di una proposta (`path`);
      - promote          -> archivia una proposta verificata (`path`).
    """
    import improve
    args = args or {}
    scope = str(args.get("scope", "")).strip()
    action = str(args.get("action", "propose") or "propose").strip()
    content = str(args.get("content", "")).strip()
    if scope == "mine":
        import selfevolve
        out = os.path.join(registry.REPO, "data", "proposals", "skills")
        path = str(args.get("path", "") or "").strip()

        def _pub(ev, **kw):
            try:
                import server as _srv
                _srv.publish(ev, **kw)
            except Exception:  # noqa: BLE001 — l'evento non deve rompere il tool
                pass

        if action == "verify":
            if not path:
                return {"error": "path richiesto per action=verify"}
            rep = selfevolve.verify(path)
            _pub("improve.verify", path=path, green=bool(rep.get("green")))
            return {"ok": True, "verify": rep}
        if action == "promote":
            if not path:
                return {"error": "path richiesto per action=promote"}
            res = selfevolve.promote(path)
            if res.get("ok"):
                _pub("improve.archived", name=res.get("name"), rel=res.get("rel"))
            return res
        if action == "evolve":
            c = selfevolve.cfg()
            reports = []
            for cand in selfevolve.mine(selfevolve.history(), c):
                rep = selfevolve.pipeline(cand["pattern"], out, cand["support"])
                green = bool((rep.get("verify") or {}).get("green"))
                reports.append({"pattern": cand["pattern"], "green": green,
                                "archived": rep.get("archived")})
                _pub("improve.evolve", pattern=cand["pattern"], green=green)
            return {"ok": True, "evolved": len(reports), "reports": reports}
        try:
            paths = selfevolve.mine_history(out, note=str(args.get("reason", "")))
        except Exception as e:  # noqa: BLE001
            return {"error": "mine failed: %s" % e}
        recs = []
        for p in paths:
            rec = {"scope": "skill", "path": p, "status": "proposed",
                   "reason": "pattern di tool ripetuto rilevato (selfevolve)"}
            recs.append(rec)
            _pub("improve.proposal", **rec)
        return {"ok": True, "mined": len(recs), "proposals": recs}
    if scope not in ("skill", "project", "global") or not content:
        return {"error": "scope in {skill,project,global,mine} and content required"}
    if improve.AGENT_WRITE.get(scope) == "forbidden":
        return {"error": "scope not writable"}
    rec = improve.propose(scope, content, reason=str(args.get("reason", "")))
    try:
        import server as _srv
        _srv.publish("improve.proposal", **rec)
    except Exception:  # noqa: BLE001 — l'evento non deve rompere il tool
        pass
    return {"ok": True, "proposal": rec}


_DISPATCH = {"shell": _shell, "fs.read": _fs_read, "fs.write": _fs_write,
             "fs.edit": _fs_edit, "diff": _diff,
             "git": _git, "http": _http, "browser": _browser, "self": _self,
             "skills": _skills, "memory": _memory, "web": _web, "improve": _improve}


def _dispatch_execute(tool, args, run_id=None):
    fn = _DISPATCH.get(tool)
    if fn is None:
        # external MCP tools (<client>__<tool>) route through the MCP client
        if "__" in tool:
            try:
                import mcp_client
                res = mcp_client.call_tool(tool, args, run_id=run_id)
                res["duration_ms"] = res.get("duration_ms", 0)
                res["tool"] = tool
                return res
            except Exception as e:  # noqa: BLE001
                return {"ok": False, "error": "external MCP call failed: %s" % e,
                        "tool": tool}
        return {"ok": False, "error": "no implementation for tool %r" % tool, "tool": tool}
    args = args or {}
    try:
        res = fn(args, run_id)
    except Exception as e:  # noqa: BLE001
        res = {"ok": False, "error": "tool error: %s" % e}
    res["tool"] = tool
    res["args"] = args
    res.setdefault("exit_code", 0 if res.get("ok") else 125)
    return res


def execute(tool, args, run_id=None):
    """Run a tool through the lifecycle hooks (JAG-69), then dispatch.

    `PreToolUse` may BLOCK the call (hook exit 2); `PostToolUse` receives the
    observation. Both are deterministic shell scripts — the model is not asked.
    """
    try:
        import hooks
        pre = hooks.run("PreToolUse", tool=tool, args=args or {}, run_id=run_id)
    except Exception:  # noqa: BLE001 — a hook must never break tool execution
        pre = {"blocked": False}
    if pre.get("blocked"):
        return {"ok": False, "tool": tool, "args": args or {}, "exit_code": 126,
                "hook_blocked": True,
                "error": "blocked by PreToolUse hook: %s" % pre.get("reason")}
    res = _dispatch_execute(tool, args, run_id=run_id)
    try:
        import hooks
        obs = (res.get("observation") or res.get("error") or res.get("content")
               or res.get("stdout"))
        hooks.run("PostToolUse", tool=tool, args=args or {}, observation=obs,
                  run_id=run_id)
    except Exception:  # noqa: BLE001
        pass
    return res


def observation(res, max_chars=1600):
    """Render a tool result as the agent's observation line."""
    if not res.get("ok") and res.get("error"):
        return "[%s] ERROR: %s" % (res.get("tool"), res["error"])
    bits = ["[%s] exit=%s backend=%s sandboxed=%s"
            % (res.get("tool"), res.get("exit_code"), res.get("backend"), res.get("sandboxed"))]
    if res.get("stdout"):
        bits.append("stdout: " + _truncate(res["stdout"].strip(), max_chars))
    if res.get("stderr"):
        bits.append("stderr: " + _truncate(res["stderr"].strip(), max_chars))
    if res.get("path"):
        bits.append("path: " + res["path"])
    return "\n".join(bits)
