# Held-out Verifier Gate — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: use superpowers:executing-plans (inline)
> or superpowers:subagent-driven-development. Steps use `- [ ]` checkboxes.

**Goal:** rendere `selfevolve.promote` **fail-closed** dietro un gate held-out esterno
e hash-pinnato, così una proposta di self-improvement non può essere promossa
manipolando il proprio verificatore.

**Architecture:** nuovo modulo puro `src/sparkforge/heldout.py` (dir/manifest/
integrity/run/gate/pin). `heldout.gate()` = integrità del manifest ∧ esecuzione della
suite giudice (runner iniettabile nei test, sandbox in produzione). `selfevolve.promote`
chiama il gate prima di archiviare. Store fuori dallo spazio agente:
`SPARKFORGE_HELDOUT_DIR` (default `~/.sparkforge/heldout`).

**Tech Stack:** Python 3 stdlib (`hashlib`, `json`, `os`, `shlex`, `time`), sandbox
esistente, pytest-style test runner custom (pattern `check(...)` del repo).

---

### Task 1: `heldout.py` — dir / manifest / integrità / pin

**Files:**
- Create: `src/sparkforge/heldout.py`

- [ ] **Step 1: scrivi il modulo**

```python
#!/usr/bin/env python3
"""Gate di promozione held-out sigillato (RDD punto 2).

Il verifier del self-improvement deve stare FUORI dallo spazio di lavoro dell'agente:
una suite giudice esterna, ancorata a un manifest di hash, che `selfevolve.promote`
deve superare (fail-closed) prima di archiviare una proposta. Cosi' l'agente non puo'
ne' leggere ne' manomettere il giudice. Modulo puro (nessuna dipendenza dal server).
"""
import hashlib
import json
import os
import shlex
import time

DEFAULT_DIR = "~/.sparkforge/heldout"


def dir():
    """Directory dello store held-out (env SPARKFORGE_HELDOUT_DIR -> default)."""
    return os.path.abspath(os.path.expanduser(
        os.environ.get("SPARKFORGE_HELDOUT_DIR") or DEFAULT_DIR))


def require_enabled():
    """Il gate e' obbligatorio di default; SPARKFORGE_REQUIRE_HELDOUT=0 lo spegne."""
    return os.environ.get("SPARKFORGE_REQUIRE_HELDOUT", "1").strip() not in ("0", "false", "no")


def manifest_path():
    return os.path.join(dir(), "manifest.json")


def load_manifest():
    """Legge il manifest o None se assente/illeggibile/malformato."""
    try:
        with open(manifest_path(), "r", encoding="utf-8") as f:
            m = json.load(f)
        if not isinstance(m, dict) or not isinstance(m.get("files"), dict):
            return None
        return m
    except (OSError, ValueError):
        return None


def _sha256(path):
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
    except OSError:
        return None
    return h.hexdigest()


def integrity(c=None):
    """Verifica che ogni file del manifest esista con l'hash atteso (fail-closed)."""
    m = load_manifest()
    if m is None:
        return {"ok": False, "reason": "no_manifest", "files": []}
    root = dir()
    files = []
    ok = True
    for rel, exp in sorted(m.get("files", {}).items()):
        actual = _sha256(os.path.join(root, rel))
        status = "ok" if (actual is not None and actual == exp) \
            else ("missing" if actual is None else "mismatch")
        if status != "ok":
            ok = False
        files.append({"path": rel, "expected": exp, "actual": actual, "status": status})
    return {"ok": ok, "reason": "ok" if ok else "integrity", "files": files}


def pin(paths=None):
    """Admin: (ri)scrive il manifest con gli hash attuali. NON e' un'azione agente."""
    root = dir()
    files = {}
    if paths:
        for rel in paths:
            files[rel] = _sha256(os.path.join(root, rel))
    else:
        suite = os.path.join(root, "suite")
        for base, _dirs, names in os.walk(suite):
            for n in names:
                p = os.path.join(base, n)
                files[os.path.relpath(p, root)] = _sha256(p)
    m = {"version": 1, "command": "python3 check_all.py", "files": files}
    os.makedirs(root, exist_ok=True)
    with open(manifest_path(), "w", encoding="utf-8") as f:
        json.dump(m, f, indent=2, sort_keys=True)
    return m
```

- [ ] **Step 2: commit**

```bash
git add src/sparkforge/heldout.py
git commit -m "feat(heldout): sealed gate module (dir/manifest/integrity/pin)"
```

---

### Task 2: `run` + `gate` (runner iniettabile)

**Files:**
- Modify: `src/sparkforge/heldout.py`

- [ ] **Step 1: aggiungi `run` e `gate`**

```python
def run(candidate=None, c=None, timeout=None, runner=None):
    """Esegue la suite giudice. (green, output, duration_ms). `runner` iniettabile."""
    m = load_manifest()
    if m is None:
        return False, "no manifest", 0
    command = m.get("command") or "python3 check_all.py"
    if candidate and "{candidate}" in command:
        command = command.replace("{candidate}", shlex.quote(str(candidate)))
    suite = os.path.join(dir(), "suite")
    t0 = time.time()
    if runner is not None:
        try:
            green, out = runner(suite, command)
        except Exception as e:  # noqa: BLE001
            green, out = False, "runner error: %s" % e
    else:
        try:
            from . import sandbox
            res = sandbox.run(command, timeout=int(timeout or 120), workspace=suite)
            out = (res.get("stdout") or "") + (res.get("stderr") or "")
            green = res.get("exit_code") == 0
        except Exception as e:  # noqa: BLE001
            green, out = False, "sandbox error: %s" % e
    return bool(green), str(out)[-1200:], int((time.time() - t0) * 1000)


def gate(candidate=None, c=None, runner=None):
    """Verifica sigillata: integrity AND run. Fail-closed su ogni dubbio."""
    rep = integrity(c)
    if not rep.get("ok"):
        return {"green": False, "integrity": rep, "run": None,
                "reason": rep.get("reason", "integrity")}
    green, out, ms = run(candidate=candidate, c=c,
                         timeout=(c or {}).get("heldout_timeout"), runner=runner)
    return {"green": bool(green), "integrity": rep,
            "run": {"green": bool(green), "duration_ms": ms, "output": out},
            "reason": "ok" if green else "run_failed"}
```

- [ ] **Step 2: commit**

```bash
git add src/sparkforge/heldout.py
git commit -m "feat(heldout): run + sealed gate (integrity AND suite), fail-closed"
```

---

### Task 3: integra il gate in `selfevolve.promote`

**Files:**
- Modify: `src/sparkforge/selfevolve.py:362-390`

- [ ] **Step 1: gate fail-closed dopo il check di status**

In `promote`, dopo il blocco `if prop.get("status") != "verified": ...`, inserisci:

```python
    # RDD punto 2: gate held-out sigillato (fail-closed). Il verifier locale
    # (check.py) NON basta: la promozione richiede la suite giudice esterna.
    from . import heldout
    if heldout.require_enabled():
        g = heldout.gate(proposal_dir, c=c)
        if not g.get("green"):
            return {"ok": False, "gate": g,
                    "error": "held-out gate not green (%s)" % g.get("reason")}
```

- [ ] **Step 2: commit**

```bash
git add src/sparkforge/selfevolve.py
git commit -m "feat(selfevolve): promote is gated by the sealed held-out gate"
```

---

### Task 4: test deterministico `v205` + battery

**Files:**
- Create: `tests/v205_heldout_gate.py`
- Modify: `tests/battery.sh`

- [ ] **Step 1: scrivi `tests/v205_heldout_gate.py`** (isolato via `SPARKFORGE_HELDOUT_DIR`
  su temp dir; runner iniettato → niente sandbox). Verifica: A integrità ok/corrotta;
  B gate verde/rosso; C `promote` rifiuta a gate rosso; D `promote` ok a gate verde;
  E dir assente → fail-closed; F il gate ignora un `check.py` locale manipolato.

- [ ] **Step 2: aggiungi `v205_heldout_gate` a `TESTS` in `tests/battery.sh`** e aggiorna
  l'header/echo da SIX/6-6 a SEVEN/7-7.

- [ ] **Step 3: esegui**

```bash
python3 tests/v205_heldout_gate.py   # atteso: 6/6 PASS
bash tests/battery.sh                # atteso: battery: 7/7 GREEN
```

- [ ] **Step 4: commit**

```bash
git add tests/v205_heldout_gate.py tests/battery.sh
git commit -m "test(v205): sealed held-out gate covered in battery (7/7)"
```

---

### Task 5: documentazione

**Files:**
- Modify: `.agent/HANDOFF.md`
- Modify: `config/tools.yaml` (nota su `improve{promote}` gated) — opzionale

- [ ] **Step 1: aggiorna HANDOFF** con JAG-205 (gate held-out, P6/punto 2) + battery 7/7.
- [ ] **Step 2: commit + push.**

---

## Self-Review

- **Spec coverage:** §4 dir/manifest/integrity/run/gate/pin → Task 1-2; §5 integrazione
  → Task 3; §8 error handling → fail-closed nei Task 1-2-3; §9 testing → Task 4;
  §10 rollout → Task 5. Nessun gap.
- **Placeholder scan:** nessun TBD; ogni step ha codice/comandi.
- **Type consistency:** `integrity()->{ok,reason,files}`; `run()->(green,output,ms)`;
  `gate()->{green,integrity,run,reason}`; `require_enabled()->bool`; `pin()->manifest`.
  Usati coerentemente nei Task 2-3-4.
