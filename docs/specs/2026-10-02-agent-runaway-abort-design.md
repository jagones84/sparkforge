# 2026-10-02 — Run agent che non si blocca + stop che funziona (JAG-111)

## Problema (evidenza dal codice)

- Il tasto **stop** della WebUI posta `POST /api/agent/control {runId: activeRunId,
  action:abort}`. Ma `activeRunId` è preso da `agent.start`, che **non contiene
  `run`** ([server.py](file:///z:/Repositories/sparkforge/server.py) `agent_run` →
  `on_event("agent.start", goal=…, max_steps=…)`) → `activeRunId` = `undefined`.
- Lo stream `GET /api/agent/run` usa `agent_stream_gen` → `agent_run`, che **non
  registra** un `RunState` in `api_v02.RUNS` (quello lo fa la API JSON v0.2).
  Quindi `run_control` non trova il run → **abort impossibile**.
- `_router_stream` non manda **`max_tokens`** e non ha **guardia anti-ripetizione**.
  `ROUTER_IDLE_TIMEOUT` copre solo il *silenzio*: un modello in loop ripetitivo
  (visto negli screenshot: muro di "contesto ripetuto per il transcript") continua
  a emettere token → nessun idle → la run resta appesa (fino al timeout 300s) a
  "Iteration 5/6".
- `sse_response` ignora la disconnessione del client: il worker continua a girare
  (loop orfano) dopo che la scheda è chiusa.

## Obiettivi

1. `agent_run` registra un run **abortibile** (`api_v02.new_run`) e `agent.start`
   porta `run=<id>` → lo stop del client funziona.
2. L'ABORT è onorato **a ogni iterazione** (`api_v02.checkpoint`) → `agent.aborted`.
3. Una risposta in **loop ripetitivo** viene tagliata subito
   (`_RepetitionGuard`), con evento `model.runaway`.
4. Cap opzionale di una completion (`SPARKFORGE_MAX_TOKENS`, default 0 = off).
5. Disconnessione del client → set `abort` sul run (nessun worker orfano).

## Design

### `_RepetitionGuard` (pura, testabile)
Rileva un periodo `p` (16..max_period) tale che gli ultimi `p*limit` caratteri siano
`limit` copie esatte di `text[-p:]`. Salta i blocchi banali (poco alfabeto) e i
blocchi **senza spazi** sotto 48 char (protegge codice/tabelle). Default:
`min_period=20, max_period=240, limit=4`.

### `server.py`
- `MAX_TOKENS` (`SPARKFORGE_MAX_TOKENS`, 0=off), `REPEAT_GUARD`
  (`SPARKFORGE_REPEAT_GUARD`, default on).
- `_completion_body(model_id, messages, stream, max_tokens=None)`: corpo unico
  (stream_options solo se stream; max_tokens solo se > 0).
- `_router_stream(..., guard=None)`: usa `_completion_body`; se guard, alimenta
  `_RepetitionGuard` con i delta e su trigger pubblica `model.runaway` e interrompe.
- `stream_with_fallback(..., guard=None)`: propaga `guard`.
- `agent_run(..., run_state=None)`: `st = run_state or api_v02.new_run(...)`;
  `agent.start` include `run=st.id`; `api_v02.checkpoint(st)` a inizio iterazione;
  `except api_v02.AbortRun` → `agent.aborted` + finish "aborted by operator";
  `st.status` done/aborted.
- `agent_stream_gen`: crea il run, lo passa come `run_state`, e in `finally` (chiusura
  del generatore = client disconnesso) set `st.abort = True` se il worker è vivo.

### WebUI
- `agent.start` → `activeRunId = d.run` (già codificato, ora il campo esiste).
- FEED: handler per `agent.aborted` e `model.runaway`.

## Test (TDD — `tests/v111_agent_abort_runaway.py`)
- **R1** guardia: 3 copie di un blocco → trigger; testo distinto → mai.
- **R2** `_router_stream` con stream ripetitivo finto → `model.runaway` + taglio.
- **A1** `agent.start` porta `run`; il run è in `api_v02.RUNS`.
- **A2** abort a metà → il loop si ferma prima di `max_steps` + `agent.aborted`.
- **A3** chiusura del generatore → `run_state.abort` = True.
- **M1** `_completion_body` include `max_tokens` solo se > 0.

## Non-obiettivi
- Nessuna modifica al routing dei ruoli.
- Nessuna UI nuova oltre agli handler FEED.
