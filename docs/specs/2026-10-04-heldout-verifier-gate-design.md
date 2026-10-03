# Design — Gate di promozione held-out sigillato

Data: 2026-10-04 · Stato: approvato · Riferimento RDD: agenda §6 "punto 2"
(loop di auto-miglioramento sigillato). Fondamento di P1/P3/P6.

## 1. Problema

Il self-improvement esiste già: `selfevolve` fa `synth` (scrive `runner.py` +
`check.py`), `verify` (esegue `check.py` in sandbox) e `promote` (archivia se verde);
il tool `improve{promote}` lo invoca. **Il buco:** il verifier (`check.py`) è
*generato dalla proposta stessa*, quindi auto-referenziale. Un agente che ottimizza
contro il proprio verificatore fa **goodharting** e può amplificare i propri errori
(la tesi "errore ricorsivo"): senza un giudice esterno e immutabile, il tetto del
self-improvement non esiste.

## 2. Obiettivo

Rendere il verifier **il tetto sigillato**: una promozione avviene SOLO se una
suite di test *held-out* — fuori dallo spazio di lavoro dell'agente, integra e
deterministica — è verde. `check.py` locale resta utile ma non sufficiente.

## 3. Non-obiettivi (YAGNI / fuori scope)

- Nessuna firma crittografica asimmetrica, nessuna attestazione remota, nessun MCTS.
- L'integrità del *codice harness* stesso (`heldout.py`, `selfevolve.py`) NON è
  coperta: è la trusted base (come il kernel). Hardening futuro.
- Nessuna generazione di test da seed segreto (approccio C scartato).

## 4. Architettura

Nuovo modulo `src/sparkforge/heldout.py` (trusted), + integrazione in
`selfevolve.promote`. Held-out store **esterno** all'albero repo.

```
HELDOUT_DIR/                 (default $SPARKFORGE_HELDOUT_DIR, fallback ~/.sparkforge/heldout)
├── suite/                   test giudice deterministici (non leggibili dall'agente)
├── manifest.json            {"version":N,"command":[...],"files":{"<relpath>":"<sha256>"}}
└── (runner definito dal manifest: un comando eseguibile nella suite)
```

### `heldout.py` — interfacce

- `dir()` → path effettivo dello store (env → default).
- `load_manifest()` → dict o `None` se assente/illeggibile.
- `integrity()` → `{"ok": bool, "files": [{"path","expected","actual","status"}]}`;
  `ok=False` se un file manca o l'hash non combacia.
- `run(candidate=None, timeout=...)` → `(green, output, duration_ms)`; esegue il
  comando del manifest con `cwd=HELDOUT_DIR/suite` e `env HELDOUT_CANDIDATE=<path
  proposta>`; la suite può usarne il valore (o ignorarlo). Se lo ignora, funge da
  *baseline seal*: valida le invarianti dell'harness (es. battery held-out). Sempre
  read-only sul candidate.
- `gate(candidate=None)` → `{"green","integrity","run","reason"}`. `green` vero
  **solo** se integrity ok **e** run verde. **Fail-closed** su qualunque dubbio.
- `pin(paths=None)` → amministrazione (rigenera il manifest con gli hash attuali);
  **non** esposta come azione del tool `improve` — solo CLI/funzione fuori-agente.

## 5. Integrazione

- `selfevolve.promote(proposal_dir, ...)`: prima di archiviare, chiama
  `heldout.gate(proposal_dir)`. Se non verde → non archivia e ritorna
  `{"ok": False, "gate": <report>}` con motivo.
- `pipeline(...)`: `promote_if_green` diventa `promote_if_green AND gate.green`.
- Env `SPARKFORGE_REQUIRE_HELDOUT` (default `1`). Se `HELDOUT_DIR` manca / manifest
  assente / integrità rotta → **fail-closed** (promozione negata, motivo esplicito).
  Con `=0` si può disattivare solo per sviluppo locale (log di warning).

## 6. Data flow

```
proposta → synth (runner+check) → verify locale (check.py, sandbox)
        → heldout.gate(): [integrity manifest] ∧ [run suite esterna]
        → promote SOLO se locale verde ∧ gate verde
        → archiviazione con provenance (ts, path, hash suite)
```

## 7. Threat model

- **Test leakage:** la suite è fuori workspace → l'agente non la legge → niente
  ottimizzazione contro il giudice.
- **Manomissione:** se un file held-out è alterato, l'hash mismatch → fail-closed.
- **Auto-promozione:** `promote` è gated dal meccanismo trusted; l'agente non può
  forzare un verde.
- **Errore ricorsivo:** il giudice non è modificabile dalla traiettoria dell'agente
  → nessuna amplificazione auto-referenziale.

## 8. Error handling

| Condizione | Esito |
|---|---|
| `HELDOUT_DIR` assente/illeggibile | fail-closed, motivo `no_heldout_dir` |
| `manifest.json` assente/rotto | fail-closed, motivo `no_manifest` |
| hash mismatch su un file | fail-closed, motivo `integrity`, elenco file |
| runner timeout / exit ≠ 0 | gate rosso, motivo `run_failed` + output |
| locale rosso | promote negato (comportamento attuale) |

## 9. Testing — `tests/v205_heldout_gate.py` (nel gate battery)

- **A** integrità: manifest valido → `ok`; corrompo un file → `ok=False`.
- **B** gate: suite passing → verde; suite failing → rosso.
- **C** `promote` RIFIUTA proposta con gate rosso (nessuna archiviazione).
- **D** `promote` accetta solo con locale verde ∧ gate verde.
- **E** `HELDOUT_DIR` assente → fail-closed (`ok=False`, motivo).
- **F** il gate ignora un `check.py` manipolato dalla proposta (usa la suite esterna).
- Nessuna regressione: battery **6/6 → 7/7**.

Criterio di accettazione: una proposta di self-improve NON può superare la
promozione modificando il proprio verificatore; il gate fail-closed su ogni dubbio.

## 10. Rollout

1. `heldout.py` + test v205 (questo giro).
2. `selfevolve.promote` gated (stesso giro); `pin()` via CLI una tantum.
3. Applicazione del gate ad altri target (skill/prompt/tool) — RDD successivo.
