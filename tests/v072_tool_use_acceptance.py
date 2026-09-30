#!/usr/bin/env python3
"""SparkForge v0.7.2 — JAG-58: TOOL USE ACCEPTANCE (TDD, RED first).

Tesi dell'utente, da verificare con evidenze e non con affermazioni:
  "Non e' un harness vero: non esegue comandi, non usa davvero MCP ne' skills,
   non legge file; l'agente nella sessione chat non vede quei tool."

Cosa misura questo file (ogni check stampa l'evidenza grezza):
  T0 baseline operatore: POST /api/tools/call skills list  -> ok (non e' il claim)
  T1 CHAT:    POST /api/chat  con un ordine che richiede un tool -> il modello
              deve produrre una `tool.call` (o contenuto che cita dati reali).
  T2 AGENT skills: GET /api/agent/run goal="skills action=list poi finish" ->
              entro max_steps deve comparire `tool.call tool=skills` E un finish.
  T3 AGENT fs.read: goal="leggi /etc/hostname con fs.read poi finish" ->
              deve comparire `tool.call tool=fs.read`.
  T4 AGENT MCP: goal="chiama pmcp__gateway.health poi finish" ->
              deve comparire `tool.call tool=pmcp__gateway.health`.
  T5 AGENT shell: goal="esegui `echo JAG58` con shell poi finish" ->
              deve comparire `tool.call tool=shell` con output.

RED atteso: T1-T5 falliscono oggi (chat senza tool; agent loop che non progredisce).

Usage: python3 tests/v072_tool_use_acceptance.py [--base URL]
Exit 0 iff ogni check passa. Report: data/v072-tool-use.json
"""
import argparse
import json
import os
import urllib.request
import urllib.error
import urllib.parse

BASE = os.environ.get("SPARKFORGE_URL", "http://127.0.0.1:8790")
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
results = []


def _read_token():
    tok = os.environ.get("SPARKFORGE_TOKEN")
    if tok:
        return tok
    envf = os.path.expanduser("~/.config/sparkforge/env")
    if os.path.isfile(envf):
        for line in open(envf):
            if line.startswith("SPARKFORGE_TOKEN="):
                return line.split("=", 1)[1].strip()
    return None


TOKEN = _read_token()
HDR = {"Authorization": "Bearer " + TOKEN} if TOKEN else {}


def check(name, ok, evidence, **extra):
    rec = {"check": name, "ok": bool(ok), "evidence": evidence, **extra}
    results.append(rec)
    print("\n%s %s\n   %s" % ("PASS" if ok else "FAIL", name, evidence))
    return bool(ok)


def api(path, payload=None, method=None, timeout=180):
    data = None
    headers = dict(HDR)
    if payload is not None:
        data = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, json.loads(r.read().decode())


def sse(path, payload=None, method=None, timeout=600, max_events=100000):
    """POST/GET an SSE endpoint; return list of (event, data_dict)."""
    data = None
    headers = dict(HDR)
    if payload is not None:
        data = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    evs = []
    with urllib.request.urlopen(req, timeout=timeout) as r:
        cur = None
        for raw in r:
            line = raw.decode("utf-8", "replace").rstrip("\n")
            if line.startswith("event:"):
                cur = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                try:
                    d = json.loads(line.split(":", 1)[1].strip() or "{}")
                except json.JSONDecodeError:
                    d = {}
                evs.append((cur, d))
                if len(evs) >= max_events:
                    break
    return evs


def tool_calls(evs):
    return [d for (e, d) in evs if e in ("tool.call",) or (e == "tool.result")]


# Harness-internal tool calls (bookkeeping, not LLM-driven world actions).
INTERNAL_TOOLS = {"write_todos"}


def real_tool_names(evs):
    """Tool names the LLM actually asked for, excluding harness bookkeeping."""
    names = [d.get("tool") for (e, d) in evs if e == "tool.call"]
    return [n for n in names if n not in INTERNAL_TOOLS]


def observation_text(evs):
    """All agent.observation text (where the harness puts tool stdout)."""
    return "\n".join((d.get("observation") or "") for (e, d) in evs
                     if e == "agent.observation")


def shell_stdout(evs):
    """stdout of the shell tool, as surfaced in the agent observation."""
    return observation_text(evs)


def finished(evs):
    return any(e == "agent.finish" for (e, _) in evs)


# --------------------------------------------------------------------------- #
def t0_baseline():
    st, d = api("/api/tools/call", {"tool": "skills", "args": {"action": "list"}})
    res = (d or {}).get("result") or d
    ok = st == 200 and res.get("ok") is True
    check("T0 baseline: POST /api/tools/call skills list (operator path)", ok,
          "status=%s ok=%s count=%s" % (st, res.get("ok"), res.get("count")))


def t1_chat_uses_tools():
    evs = sse("/api/chat/stream", {"message":
              "Usa il tool skills con action=list e dimmi quante skill ci sono. "
              "Poi rispondi in testo normale."}, method="POST", timeout=300)
    names = real_tool_names(evs)
    ans = "".join(d.get("text", "") for (e, d) in evs
                  if e == "chat.delta" and d.get("channel") == "answer")
    ok = ("skills" in names) and ("123" in ans or "skill" in ans.lower())
    check("T1 CHAT: il modello deve usare un tool reale e riportarne l'esito", ok,
          "real_tool_calls=%s answer_head=%r" % (names, ans[:160]))


def t2_agent_skills():
    evs = sse("/api/agent/run?goal=%s&max_steps=5" % urllib.parse.quote(
        "Usa il tool skills con action=list, poi chiama finish con summary=ok"),
        method="GET", timeout=600)
    names = real_tool_names(evs)
    fin = finished(evs)
    obs = observation_text(evs)
    ok = ("skills" in names) and fin and ("out" in obs.lower() or "skill" in obs.lower())
    check("T2 AGENT skills: deve chiamare skills, ottenere output, E poi finish", ok,
          "real_tool_calls=%s finished=%s obs_head=%r" % (names, fin, obs[:160]))


def t3_agent_fs_read():
    evs = sse("/api/agent/run?goal=%s&max_steps=5" % urllib.parse.quote(
        "Leggi il file README.md con il tool fs.read, poi chiama finish summary=ok"),
        method="GET", timeout=600)
    names = real_tool_names(evs)
    fin = finished(evs)
    obs = observation_text(evs)
    ok = ("fs.read" in names) and fin and ("stdout" in obs.lower() or "exit" in obs.lower())
    check("T3 AGENT fs.read: deve leggere il file, mostrare output, E poi finish", ok,
          "real_tool_calls=%s finished=%s obs_head=%r" % (names, fin, obs[:200]))


def t4_agent_mcp():
    evs = sse("/api/agent/run?goal=%s&max_steps=5" % urllib.parse.quote(
        "Chiama il tool MCP pmcp__gateway.health, poi chiama finish summary=ok"),
        method="GET", timeout=600)
    names = real_tool_names(evs)
    fin = finished(evs)
    ok = ("pmcp__gateway.health" in names) and fin
    check("T4 AGENT MCP: deve chiamare pmcp__gateway.health E poi finish", ok,
          "real_tool_calls=%s finished=%s" % (names, fin))


def t5_agent_shell():
    evs = sse("/api/agent/run?goal=%s&max_steps=5" % urllib.parse.quote(
        "Esegui il comando shell `echo JAG58`, verifica l'output, poi chiama finish summary=ok"),
        method="GET", timeout=600)
    names = real_tool_names(evs)
    out = shell_stdout(evs)
    fin = finished(evs)
    ok = ("shell" in names) and ("JAG58" in out) and fin
    check("T5 AGENT shell: deve eseguire shell, output JAG58, E poi finish", ok,
          "real_tool_calls=%s stdout_has_JAG58=%s finished=%s" % (names, "JAG58" in out, fin))


def main():
    global BASE
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=BASE)
    args = ap.parse_args()
    BASE = args.base
    print("SparkForge tool-use acceptance — base=%s token=%s" % (BASE, bool(TOKEN)))
    t0_baseline()
    t1_chat_uses_tools()
    t2_agent_skills()
    t3_agent_fs_read()
    t4_agent_mcp()
    t5_agent_shell()
    passed = sum(1 for r in results if r["ok"])
    summary = {"base": BASE, "passed": passed, "total": len(results), "results": results}
    os.makedirs(os.path.join(REPO, "data"), exist_ok=True)
    with open(os.path.join(REPO, "data", "v072-tool-use.json"), "w") as f:
        json.dump(summary, f, indent=2)
    print("\n==== %d/%d passed ====" % (passed, len(results)))
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
