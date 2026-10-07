# Prompt Architecture + Self-Improvement Routing — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rendere il system prompt di SparkForge un **registro di sezioni additivo** (default in codice + overlay da file, gerarchia `progetto > globale > default` solo sulle contraddizioni, tool/skill generati a runtime) e instradare il **self-improvement** (memoria libera; regole progetto/globali solo come proposta; codice fuori scope).

**Architecture:** Nuovo modulo `prompt.py` con un registro ordinato `SECTIONS`; ogni sezione è `static` (testo) o `dynamic` (provider in codice). Il renderer concatena, per sezione, `default + addendum globale + addendum progetto`. `server._system_prompt()` diventa un wrapper sottile. Parte B: nuovo `improve.py` (tabella di routing + soglie + store delle proposte) + tool `improve` + endpoint/WebUI.

**Tech Stack:** Python 3 stdlib (nessuna dipendenza nuova). Test = script standalone `tests/vNNN_*.py` con `check(name, ok, detail)` e `sys.exit(0/1)`. Unità systemd `sparkforge.service` (repo su DGX, `z:\Repositories\sparkforge`).

**Regola di chiarezza all'agente (requisito utente, non negoziabile):** ogni blocco deve essere auto-esplicativo — il prompt dichiara *dove* vivono le sezioni, *come* si compongono, *chi* vince in caso di conflitto, *quali* tool esistono e *dove* l'agente può scrivere. Il test `v136` include check espliciti su questo.

**Nota di scope:** Fase A e Fase B sono indipendenti → eseguibili una alla volta. Fase A è la prioritaria (risolve "generalizzare" + "chiarezza").

**Convenzioni esecuzione comandi (repo su DGX):** ogni comando che scrive su file esistenti gira **lato Linux** via script dedicato:
`ssh dgx "bash /home/jagones/Repositories/sparkforge/trash/<script>.sh"` (cwd locale `C:\Users\giova`). I file `.sh` vanno scritti senza CRLF.

---

## Fase A — Architettura del prompt

### Task A1: `prompt.py` — registro, default, render additivo

**Files:**
- Create: `prompt.py`
- Test: `tests/v136_prompt_sections.py`

- [ ] **Step 1: Write the failing test**

Create `tests/v136_prompt_sections.py`:

```python
#!/usr/bin/env python3
"""v0.9.37 acceptance — architettura prompt a registro (JAG-128A)."""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


def read(p):
    try:
        return open(p, encoding="utf-8", errors="replace").read()
    except OSError:
        return ""


import prompt  # noqa: E402

check("A1 module has render_sections + SECTIONS",
      hasattr(prompt, "render_sections") and hasattr(prompt, "SECTIONS"), "")
ids = [s["id"] for s in prompt.SECTIONS]
check("A2 core sections present",
      {"identity", "tools", "memory", "capability", "prompt-map"}.issubset(set(ids)),
      str(ids))
check("A3 every section kind is static|dynamic",
      all(s.get("kind") in ("static", "dynamic") for s in prompt.SECTIONS), "")

out = prompt.render_sections(None)
check("A4 render non-empty", bool(out.strip()), str(len(out)))
check("A5 identity text present", "SparkForge" in out, "")
check("A6 tool registry block present", "Tool registry" in out, "")

total = len(results)
print("\n==== %d/%d checks passed ====" % (sum(results), total))
sys.exit(0 if all(results) else 1)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python tests/v136_prompt_sections.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'prompt'` (exit 1).

- [ ] **Step 3: Write minimal implementation**

Create `prompt.py`:

```python
#!/usr/bin/env python3
"""Registro di sezioni del system prompt (JAG-128A).

Il prompt NON e' un monolite: e' una lista ordinata di sezioni. Ogni sezione e':
  - kind="static"  -> testo di default (default + overlay file, additivo)
  - kind="dynamic" -> provider in codice, generato a runtime (tools/skills/...)

Overlay file (ADDITIVI, non sostitutivi):
  - globale:  ~/.config/sparkforge/prompt.d/<NN>-<id>.md
  - progetto: <workspace>/.sparkforge/prompt.d/<NN>-<id>.md
In caso di CONTRADDIZIONE vince il livello piu' specifico:
  PROGETTO > GLOBALE > DEFAULT.
"""
import glob
import os

GLOBAL_DDIR = os.path.expanduser(os.path.join("~", ".config", "sparkforge", "prompt.d"))

# Ordine e natura delle sezioni. `<NN>-` nei file ordina gli addendum via glob.
SECTIONS = [
    {"id": "identity",      "order": 10, "kind": "static"},
    {"id": "prompt-map",    "order": 15, "kind": "static"},
    {"id": "self-summary",  "order": 20, "kind": "dynamic"},
    {"id": "tools",         "order": 30, "kind": "dynamic"},
    {"id": "rules-policy",  "order": 40, "kind": "static"},
    {"id": "rules",         "order": 41, "kind": "dynamic"},
    {"id": "skills-policy", "order": 50, "kind": "static"},
    {"id": "skills",        "order": 51, "kind": "dynamic"},
    {"id": "memory-policy", "order": 60, "kind": "static"},
    {"id": "memory",        "order": 61, "kind": "dynamic"},
    {"id": "capability",    "order": 70, "kind": "static"},
    {"id": "state",         "order": 90, "kind": "dynamic"},
]

# sezioni statiche i cui default vivono in server.py (lazy import: niente cicli)
_STATIC_ATTRS = {
    "identity": "SYSTEM_PROMPT",
    "rules-policy": "RULES_POLICY",
    "skills-policy": "SKILLS_POLICY",
    "memory-policy": "MEMORY_POLICY",
}


def project_ddir(ws):
    return os.path.join(ws or "", ".sparkforge", "prompt.d")


def _read(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read().strip()
    except OSError:
        return ""


def _section_id(filename):
    stem = filename[:-3] if filename.endswith(".md") else filename
    head, sep, tail = stem.partition("-")
    if sep and head.isdigit():
        return tail
    return stem


def _addenda(base_dir):
    """{section_id: text} dagli overlay <NN>-<id>.md (ordine alfabetico)."""
    out = {}
    if not base_dir:
        return out
    for p in sorted(glob.glob(os.path.join(base_dir, "*.md"))):
        sid = _section_id(os.path.basename(p))
        if sid:
            out[sid] = _read(p)
    return out


def _static_text(sid):
    if sid == "capability":
        return CAPABILITY_RULE
    if sid == "prompt-map":
        return _manifest_text()
    import server
    return getattr(server, _STATIC_ATTRS.get(sid, ""), "") or ""


def render_sections(sess=None, ws=None, tool_ctx=None):
    """Monta il prompt finale: per ogni sezione, default + globale + progetto."""
    g = _addenda(GLOBAL_DDIR)
    p = _addenda(project_ddir(ws)) if ws else {}
    parts_out = []
    for sec in sorted(SECTIONS, key=lambda s: s["order"]):
        sid = sec["id"]
        if sec["kind"] == "static":
            base = _static_text(sid)
        else:
            base = _PROVIDERS.get(sid, lambda *a: "")(sess, ws, tool_ctx)
        parts = [x.strip() for x in (base or "", g.get(sid, ""), p.get(sid, ""))
                 if x and x.strip()]
        if parts:
            parts_out.append("\n".join(parts))
    return "\n\n".join(parts_out)
```

(le funzioni `CAPABILITY_RULE`, `_manifest_text` e il dict `_PROVIDERS` arrivano nei Task A2/A3)

- [ ] **Step 4: Run test to verify it passes**

Run: `python tests/v136_prompt_sections.py`
Expected: FAIL sui check A2/A5/A6 finché A2/A3 non sono implementati — è atteso; il modulo però deve importare e A1/A4 passare. Prosegui.

- [ ] **Step 5: Commit**

```bash
git add prompt.py tests/v136_prompt_sections.py
git commit -m "feat(prompt): registro di sezioni + render additivo (JAG-128A)"
```

---

### Task A2: provider dinamici (tools/skills/rules/memory/state/self-summary)

**Files:**
- Modify: `prompt.py`
- Test: `tests/v136_prompt_sections.py`

- [ ] **Step 1: Write the failing test (append)**

Append to `tests/v136_prompt_sections.py`, prima del `total = len(results)`:

```python
check("B1 rules block injected", "Rules on disk" in out, "")
check("B2 memory policy injected",
      "memory" in out.lower() and "core" in out.lower(), "")
check("B3 dynamic tool_ctx is respected",
      prompt.render_sections(None, tool_ctx="TOOLCTX_SENTINEL").count("TOOLCTX_SENTINEL") == 1, "")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python tests/v136_prompt_sections.py`
Expected: FAIL — `_PROVIDERS` non esiste ancora (NameError) o i check B1-B3 falliscono.

- [ ] **Step 3: Write minimal implementation (append a `prompt.py`)**

```python
def _provider_self_summary(sess, ws, ctx):
    try:
        import server
        return server.self_summary()
    except Exception:  # noqa: BLE001
        return ""


def _provider_tools(sess, ws, ctx):
    if ctx:
        return ctx
    try:
        import server
        return server._tool_context()
    except Exception:  # noqa: BLE001
        return ""


def _provider_rules(sess, ws, ctx):
    try:
        import rules
        return rules.rules_prompt_block(ws=ws or rules.resolve_workspace(sess))
    except Exception:  # noqa: BLE001
        return ""


def _provider_skills(sess, ws, ctx):
    try:
        import skills
        return skills.skills_context(max_chars=3600)
    except Exception:  # noqa: BLE001
        return ""


def _provider_memory(sess, ws, ctx):
    block = ""
    try:
        import memory
        lessons = memory.governed_query(kind="agent.note", limit=6)
        instr = ["- " + str(r.get("content", "")).strip()
                 for r in lessons if str(r.get("content", "")).strip()]
        if instr:
            block = "\nLessons from past sessions (self-improvement):\n" + "\n".join(instr)
        core = memory.core_read().strip()
        if core:
            block += ("\n\n## Core memory (always visible \u2014 edit with "
                      "memory{action:'set_core'})\n" + core)
    except Exception:  # noqa: BLE001
        pass
    return block


def _provider_state(sess, ws, ctx):
    try:
        import server
        return ("Harness state (your persistent task list):\n"
                + server.context_summary(session_id=(sess or {}).get("id")))
    except Exception:  # noqa: BLE001
        return ""


_PROVIDERS = {
    "self-summary": _provider_self_summary,
    "tools": _provider_tools,
    "rules": _provider_rules,
    "skills": _provider_skills,
    "memory": _provider_memory,
    "state": _provider_state,
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python tests/v136_prompt_sections.py`
Expected: A1-A4, B1-B3 PASS. A2/A5/A6 possono ancora fallire (Task A3).

- [ ] **Step 5: Commit**

```bash
git add prompt.py tests/v136_prompt_sections.py
git commit -m "feat(prompt): provider dinamici delle sezioni (JAG-128A)"
```

---

### Task A3: sezioni nuove — `prompt-map` (manifest + gerarchia) e `capability`

**Files:**
- Modify: `prompt.py`
- Test: `tests/v136_prompt_sections.py`

- [ ] **Step 1: Write the failing test (append)**

```python
check("C1 manifest declares precedence",
      "PROJECT > GLOBAL > DEFAULT" in out, "")
check("C2 manifest lists section addenda dir",
      "prompt.d" in out, "")
check("C3 capability rule present (no shell for self-questions)",
      "Capability questions" in out and "NEVER run shell" in out, "")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python tests/v136_prompt_sections.py`
Expected: FAIL — `NameError: CAPABILITY_RULE` / check C1-C3 falliscono.

- [ ] **Step 3: Write minimal implementation (append a `prompt.py`, PRIMA di `render_sections`)**

```python
CAPABILITY_RULE = (
    "## Capability questions\n"
    "When the user asks about YOUR OWN capabilities \u2014 which tools you have, "
    "whether a tool exists, where your rules or memory live, what you can do \u2014 "
    "answer FROM YOUR PROMPT: the `Tool registry` block above, the tool `self`, or "
    "skills{action:'list'}. NEVER run shell/git (ls, find, git status) to answer a "
    "question about yourself: that inspects the machine, not you."
)


def _manifest_text():
    pretty = ", ".join("%s(%s)" % (s["id"], s["kind"]) for s in SECTIONS)
    return (
        "## How you are built (prompt map)\n"
        "Your system prompt is an ordered list of sections; some are generated at "
        "runtime, some are text you can EXTEND with files (adding, never replacing). "
        "In case of CONTRADICTION the more specific level wins: PROJECT > GLOBAL > DEFAULT.\n"
        "- global section addenda: %s/<NN>-<id>.md\n"
        "- project section addenda: <workspace>/.sparkforge/prompt.d/<NN>-<id>.md\n"
        "- sections: %s" % (GLOBAL_DDIR, pretty)
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python tests/v136_prompt_sections.py`
Expected: **tutti** i check PASS (`==== N/N checks passed ====`).

- [ ] **Step 5: Commit**

```bash
git add prompt.py tests/v136_prompt_sections.py
git commit -m "feat(prompt): manifest + gerarchia contraddizioni + regola capability (JAG-128A)"
```

---

### Task A4: overlay da file + cablaggio di `_system_prompt()`

**Files:**
- Modify: `server.py:2815-2858` (`_system_prompt`), `server.py:2807-2812` (`_tool_context`)
- Test: `tests/v136_prompt_sections.py`

- [ ] **Step 1: Write the failing test (append)**

```python
import tempfile
from unittest import mock

tmp = tempfile.mkdtemp()
os.makedirs(os.path.join(tmp, ".sparkforge", "prompt.d"), exist_ok=True)
with open(os.path.join(tmp, ".sparkforge", "prompt.d", "70-capability.md"),
          "w", encoding="utf-8") as f:
    f.write("PROJECT_OVERLAY_SENTINEL")
out2 = prompt.render_sections(None, ws=tmp)
check("D1 overlay file is appended", "PROJECT_OVERLAY_SENTINEL" in out2, "")
check("D2 default is NOT removed (additive)",
      "Capability questions" in out2, "")

import server  # noqa: E402
sp = server._system_prompt({"id": "sX"})
check("D3 _system_prompt delegates to render_sections",
      "prompt map" in sp and "Tool registry" in sp, "")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python tests/v136_prompt_sections.py`
Expected: FAIL — D1/D2 falliscono se `project_ddir` non è applicato al ws passato; D3 fallisce perché `_system_prompt` non delega ancora.

- [ ] **Step 3: Write minimal implementation**

3a. In `server.py`, sostituisci **integralmente** il corpo di `_system_prompt` (righe 2815-2858) con:

```python
def _system_prompt(sess, tool_ctx=None):
    """Single source of truth for the chat system prompt (JAG-70).

    JAG-128A: ora delega al registro di sezioni (prompt.render_sections). Resta
    l'UNICA fonte per il prompt inviato e per l'indicatore di contesto.
    """
    try:
        import rules as rules_mod
        ws = rules_mod.resolve_workspace(sess)
    except Exception:  # noqa: BLE001
        ws = None
    try:
        import prompt as prompt_mod
        return prompt_mod.render_sections(sess, ws=ws, tool_ctx=tool_ctx)
    except Exception:  # noqa: BLE001 — il prompt non deve mai rompere la chat
        return SYSTEM_PROMPT
```

3b. In `server.py`, `_tool_context()` (2807-2812) resta ma usa `CHAT_TOOL_PROMPT` come prima: nessuna modifica necessaria.

- [ ] **Step 4: Run test to verify it passes**

Run: `python tests/v136_prompt_sections.py`
Expected: **tutti** PASS.

- [ ] **Step 5: Verifica di non-regressione sui test prompt esistenti**

Run: `python tests/v135_memory_core.py`  → atteso `9/9` (il blocco core è ancora iniettato, ora via provider memory).
Run: `python tests/v134_plan_incomplete.py` → atteso `8/8`.

- [ ] **Step 6: Commit**

```bash
git add server.py prompt.py tests/v136_prompt_sections.py
git commit -m "feat(prompt): _system_prompt delega a render_sections; overlay da file (JAG-128A)"
```

---

### Task A5: rules additive (AGENTS.md non esclude RULES.md)

**Files:**
- Modify: `rules.py:200-293` (`collect` / `rules_prompt_block`)
- Test: `tests/v136_prompt_sections.py`

- [ ] **Step 1: Write the failing test (append)**

```python
import rules  # noqa: E402
wsdir = tempfile.mkdtemp()
os.makedirs(os.path.join(wsdir, ".sparkforge"), exist_ok=True)
with open(os.path.join(wsdir, ".sparkforge", "RULES.md"), "w", encoding="utf-8") as f:
    f.write("RULES_SENTINEL")
with open(os.path.join(wsdir, "AGENTS.md"), "w", encoding="utf-8") as f:
    f.write("AGENTS_SENTINEL")
blk = rules.rules_prompt_block(ws=wsdir)
check("E1 RULES.md read", "RULES_SENTINEL" in blk, "")
check("E2 AGENTS.md is ALSO read (additive, not excluded)", "AGENTS_SENTINEL" in blk, "")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python tests/v136_prompt_sections.py`
Expected: FAIL su E2 — oggi `RULES.md` vince e `AGENTS.md` è solo fallback (escluso).

- [ ] **Step 3: Write minimal implementation**

In `rules.py`, dentro `collect(ws)`, per ciascuno scope (`global`, `project`) **aggiungi** il contenuto di `AGENTS.md` al testo dello scope invece di usarlo solo come fallback. Concretamente: dopo aver composto `text` dello scope da `RULES.md` (+ `rules/*.md`), se esiste l'`AGENTS.md` dello scope e non è già incluso, appendi:

```python
agents_text = _read_file(agents_path)  # fallback path dello scope
if agents_text.strip():
    text = (text + "\n\n" + agents_text).strip()
```

(Usa l'helper di lettura già presente in `rules.py`; mantieni il campo `files` aggiornato con il path di `AGENTS.md` quando incluso.)

- [ ] **Step 4: Run test to verify it passes**

Run: `python tests/v136_prompt_sections.py`
Expected: **tutti** PASS (incluso E2).

- [ ] **Step 5: Commit**

```bash
git add rules.py tests/v136_prompt_sections.py
git commit -m "feat(rules): AGENTS.md additivo a RULES.md (no esclusione) (JAG-128A)"
```

---

### Task A6: evidenza end-to-end + HANDOFF

**Files:**
- Modify: `.agent/HANDOFF.md` (repo padre `z:\Repositories`)

- [ ] **Step 1: Riavvio e prova reale**

```bash
ssh dgx "systemctl --user restart sparkforge.service"
```
Poi apri la WebUI e verifica che il prompt contenga "How you are built (prompt map)" e "Capability questions": usa un turno di chat "che tool hai?" e controlla che l'agente risponda dal tool registry (non con shell).

- [ ] **Step 2: Suite mirata**

Run: `python tests/v136_prompt_sections.py` → `N/N`
Run: `python tests/v135_memory_core.py` → `9/9`
Run: `python tests/v134_plan_incomplete.py` → `8/8`

- [ ] **Step 3: HANDOFF**

Aggiorna `.agent/HANDOFF.md` con: obiettivo, micro-step completati, comando test + **numero**, e la voce "rotazione SPARKFORGE_TOKEN ancora pendente".

- [ ] **Step 4: Commit**

```bash
git add docs/specs docs/plans
git commit -m "docs(prompt): spec+piano architettura prompt (JAG-128A)"
```

---

## Fase B — Routing del self-improvement

### Task B1: `improve.py` — routing, soglie, store proposte

**Files:**
- Create: `improve.py`
- Test: `tests/v137_self_improve_routing.py`

- [ ] **Step 1: Write the failing test**

Create `tests/v137_self_improve_routing.py`:

```python
#!/usr/bin/env python3
"""v0.9.37 acceptance — routing del self-improvement (JAG-128B)."""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


import improve  # noqa: E402

check("R1 routing table exposes scopes",
      set(improve.AGENT_WRITE) >= {"memory", "skill", "project", "global", "code"},
      str(sorted(improve.AGENT_WRITE)))
check("R2 memory is auto (free write)", improve.AGENT_WRITE["memory"] == "auto", "")
check("R3 project/global are propose-only",
      improve.AGENT_WRITE["project"] == "propose"
      and improve.AGENT_WRITE["global"] == "propose", "")
check("R4 code is forbidden", improve.AGENT_WRITE["code"] == "forbidden", "")

check("R5 threshold: 5 tool calls triggers",
      improve.should_nudge(used_tools=5) is True, "")
check("R6 threshold: 1 tool call does not trigger",
      improve.should_nudge(used_tools=1) is False, "")
check("R7 threshold: user correction triggers even with 0 tools",
      improve.should_nudge(used_tools=0, corrected=True) is True, "")

rec = improve.propose("project", "usa sempre pytest -q", reason="correzione utente")
check("R8 proposal has id + pending status",
      bool(rec.get("id")) and rec.get("status") == "pending", str(rec))
check("R9 proposal is persisted",
      any(p["id"] == rec["id"] for p in improve.list_proposals()), "")
improve.decide(rec["id"], "deny")
check("R10 deny does not write any rule file",
      improve.get_proposal(rec["id"])["status"] == "denied", "")

total = len(results)
print("\n==== %d/%d checks passed ====" % (sum(results), total))
sys.exit(0 if all(results) else 1)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python tests/v137_self_improve_routing.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'improve'`.

- [ ] **Step 3: Write minimal implementation**

Create `improve.py`:

```python
#!/usr/bin/env python3
"""Routing del self-improvement (JAG-128B).

Regola d'oro (pattern di frontiera): l'agente scrive LIBERO solo la memoria;
le REGOLE (progetto/globali) le scrive l'umano -> l'agente al massimo PROPONE;
il CODICE dell'harness e' fuori scope.
"""
import time
import os
import json

REPO = os.path.dirname(os.path.abspath(__file__))
PROPOSAL_DIR = os.path.join(REPO, "data", "proposals")

# scope -> modalita' di scrittura consentita all'agente
AGENT_WRITE = {
    "memory": "auto",       # data/memory/**  -> scrittura libera (silent)
    "skill": "propose",     # skills/**       -> proposta, soglia
    "project": "propose",   # <ws>/.sparkforge/RULES.md -> SOLO proposta
    "global": "propose",    # ~/.config/sparkforge/RULES.md -> SOLO proposta
    "code": "forbidden",    # sparkforge/*.py -> fuori scope
}

_TOOLCALL_THRESHOLD = 5


def should_nudge(used_tools=0, errored=False, corrected=False):
    """True quando scatta il nudge di self-improvement (pattern Hermes)."""
    if corrected or errored:
        return True
    try:
        return int(used_tools) >= _TOOLCALL_THRESHOLD
    except (TypeError, ValueError):
        return False


def _path(pid):
    return os.path.join(PROPOSAL_DIR, pid + ".json")


def propose(scope, content, reason="", target_path=""):
    """Registra una PROPOSTA (non scrive nulla di definitivo)."""
    os.makedirs(PROPOSAL_DIR, exist_ok=True)
    pid = "%d-%s" % (int(time.time() * 1000), scope)
    rec = {"id": pid, "ts": time.time(), "scope": scope,
           "content": str(content)[:8000], "reason": str(reason)[:500],
           "target_path": target_path, "status": "pending"}
    with open(_path(pid), "w", encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False, indent=2)
    return rec


def get_proposal(pid):
    try:
        with open(_path(pid), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def list_proposals():
    out = []
    try:
        for fn in sorted(os.listdir(PROPOSAL_DIR)):
            if fn.endswith(".json"):
                p = get_proposal(fn[:-5])
                if p:
                    out.append(p)
    except OSError:
        pass
    return out


def _save(rec):
    with open(_path(rec["id"]), "w", encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False, indent=2)
    return rec


def decide(pid, decision):
    """approve|deny. Solo 'approve' su project/global scrive (append) le regole."""
    rec = get_proposal(pid)
    if not rec or rec.get("status") != "pending":
        return {"ok": False, "error": "proposal not found or not pending"}
    if decision == "deny":
        rec["status"] = "denied"
        return {"ok": True, **_save(rec)}
    if decision != "approve":
        return {"ok": False, "error": "decision must be approve|deny"}
    if rec["scope"] in ("project", "global"):
        import rules
        rules.append(rec["scope"], rec["content"])
    rec["status"] = "approved"
    return {"ok": True, **_save(rec)}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python tests/v137_self_improve_routing.py`
Expected: `10/10` PASS.

- [ ] **Step 5: Commit**

```bash
git add improve.py tests/v137_self_improve_routing.py
git commit -m "feat(improve): routing self-improvement + store proposte (JAG-128B)"
```

---

### Task B2: `rules.append()` + tool `improve` + nudge di fine turno

**Files:**
- Modify: `rules.py` (nuova `append`), `tools.py` (`_improve`), `registry.py` (`TOOL_SCHEMAS["improve"]`), `config/tools.yaml`
- Modify: `server.py` (fine turno chat: nudge)

- [ ] **Step 1: Write the failing test (append a v137)**

```python
import rules  # noqa: E402
check("R11 rules.append exists", hasattr(rules, "append"), "")

import registry  # noqa: E402
sch = registry.TOOL_SCHEMAS.get("improve", {})
check("R12 improve tool declared with propose action",
      "propose" in (sch.get("properties", {}).get("action", {}).get("enum") or []), "")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python tests/v137_self_improve_routing.py`
Expected: FAIL su R11/R12.

- [ ] **Step 3: Write minimal implementation**

3a. In `rules.py`, aggiungi:

```python
def append(scope, content, ws=None):
    """Aggiunge testo alle regole (global|project) in modo additivo."""
    path = global_rules_path() if scope == "global" else project_rules_path(ws or get_workspace())
    cur = ""
    try:
        with open(path, encoding="utf-8") as f:
            cur = f.read()
    except OSError:
        cur = ""
    sep = "" if cur.endswith("\n") or not cur else "\n"
    return save(scope, cur + sep + (content or ""), ws=ws)
```

3b. In `registry.py`, aggiungi a `TOOL_SCHEMAS`:

```python
"improve": {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": ["propose"]},
        "scope": {"type": "string", "enum": ["skill", "project", "global"]},
        "content": {"type": "string"},
        "reason": {"type": "string"},
    },
    "required": ["action", "scope", "content"],
},
```

3c. In `config/tools.yaml`, sotto `memory:`:

```yaml
  improve:
    enabled: true
    approval: auto
```

3d. In `tools.py`, aggiungi `_improve` e registralo in `TOOL_DISPATCH`:

```python
def _improve(args):
    """Registra una proposta di auto-miglioramento (skill/regole)."""
    import improve
    scope = str((args or {}).get("scope", "")).strip()
    content = str((args or {}).get("content", "")).strip()
    if scope not in ("skill", "project", "global") or not content:
        return {"error": "scope in {skill,project,global} and content required"}
    if improve.AGENT_WRITE.get(scope) == "forbidden":
        return {"error": "scope not writable"}
    rec = improve.propose(scope, content, reason=str((args or {}).get("reason", "")))
    return {"ok": True, "proposal": rec}
```

3e. In `server.py`, dopo la `publish("chat.done", ...)` del loop chat, aggiungi:

```python
    try:
        import improve as improve_mod
        if improve_mod.should_nudge(used_tools=len(used_tools or []), errored=bool(errored)):
            publish("improve.nudge", session=sess["id"],
                    hint="valuta cosa persistere: memoria (libera) o proposta regole (improve tool)")
    except Exception:  # noqa: BLE001 — il nudge non deve mai rompere un turno
        pass
```

(usa i nomi reali delle variabili già presenti nel loop: la lista dei tool usati e l'eventuale flag di errore)

- [ ] **Step 4: Run test to verify it passes**

Run: `python tests/v137_self_improve_routing.py`
Expected: tutti PASS (R1-R12).

- [ ] **Step 5: Commit**

```bash
git add rules.py registry.py tools.py config/tools.yaml server.py tests/v137_self_improve_routing.py
git commit -m "feat(improve): tool + rules.append + nudge di fine turno (JAG-128B)"
```

---

### Task B3: endpoint + WebUI per approvare/rifiutare le proposte

**Files:**
- Modify: `server.py` (route `/api/improve`, `/api/improve/<id>`)
- Modify: `webui/index.html` (listener `improve.proposal` + card)

- [ ] **Step 1: Write the failing test (append a v137)**

```python
srv = read(os.path.join(REPO, "server.py"))
check("R13 route /api/improve present", '"/api/improve"' in srv, "")
web = read(os.path.join(REPO, "webui", "index.html"))
check("R14 webui listens to improve.proposal",
      'improve.proposal' in web and "function improveCard" in web, "")
```

Aggiungi in testa al file v137 (se manca) l'helper `read`:

```python
def read(p):
    try:
        return open(p, encoding="utf-8", errors="replace").read()
    except OSError:
        return ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python tests/v137_self_improve_routing.py`
Expected: FAIL su R13/R14.

- [ ] **Step 3: Write minimal implementation**

3a. In `server.py`, accanto alle altre route (es. dopo `/api/chat/steer`):

```python
        if path == "/api/improve":
            import improve as improve_mod
            if self.command == "POST":
                pid = body.get("id") or qs.get("id", "")
                decision = body.get("decision") or qs.get("decision", "")
                res = improve_mod.decide(pid, decision)
                return self._send(200 if res.get("ok") else 400, res)
            return self._send(200, {"proposals": improve_mod.list_proposals()})
```

3b. In `webui/index.html`, nel blocco SSE (vicino a `plan.incomplete`) aggiungi:

```javascript
  es.addEventListener("improve.proposal", e => { improveCard(JSON.parse(e.data)); loadApprovals(); });
```

e la funzione (modellata su `planIncomplete`):

```javascript
function improveCard(d) {
  const card = document.createElement("div");
  card.className = "msg ai";
  const bub = document.createElement("div"); bub.className = "bubble planwarn";
  const head = document.createElement("div");
  head.textContent = "💡 proposta di miglioramento (" + (d.scope || "") + ")";
  const body = document.createElement("div");
  body.style.cssText = "white-space:pre-wrap;font-size:12px;color:var(--dim);margin:4px 0";
  body.textContent = d.content || "";
  const row = document.createElement("div"); row.style.cssText = "display:flex;gap:6px;margin-top:4px";
  const ok = document.createElement("button"); ok.className = "ghost"; ok.style.color = "var(--ok)"; ok.textContent = "✅ accetta";
  const no = document.createElement("button"); no.className = "ghost"; no.style.color = "var(--err)"; no.textContent = "⛔ rifiuta";
  ok.onclick = () => api("POST", "/api/improve", { id: d.id_id || d.id, decision: "approve" })
    .then(() => { ok.textContent = "✅ accettata"; no.remove(); });
  no.onclick = () => api("POST", "/api/improve", { id: d.id_id || d.id, decision: "deny" })
    .then(() => { no.textContent = "⛔ rifiutata"; ok.remove(); });
  row.appendChild(ok); row.appendChild(no);
  bub.appendChild(head); bub.appendChild(body); bub.appendChild(row);
  card.appendChild(bub); $("log").appendChild(card); scroll();
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python tests/v137_self_improve_routing.py`
Expected: tutti PASS (R1-R14).

- [ ] **Step 5: Commit**

```bash
git add server.py webui/index.html tests/v137_self_improve_routing.py
git commit -m "feat(improve): endpoint /api/improve + card WebUI (JAG-128B)"
```

---

## Self-review (gaps/placeholder check)

- **Spec coverage:** Parte A → Task A1-A6 (registro, provider, manifest/capability, overlay+cablaggio, rules additivo, evidenza). Parte B → Task B1-B3 (routing, tool+nudge, endpoint+UI). Coperto.
- **Placeholder scan:** nessun TBD/TODO; ogni step ha codice o comando+output atteso. Task A4/B2 citano "i nomi reali delle variabili" per il loop chat — l'esecutore deve leggerli in `server.py` (chat_stream_gen) prima di applicare; è una scelta per non fissare nomi che possono differire.
- **Type consistency:** `render_sections(sess, ws, tool_ctx)`, `_addenda`, `_section_id`, `_static_text` usati in modo coerente tra i task. `improve.propose/get_proposal/list_proposals/decide/AGENT_WRITE/should_nudge` coerenti tra B1-B3. `rules.append` definito e usato in B1/B2.
