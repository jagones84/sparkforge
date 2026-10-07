# 2026-10-02 — Compact contesto funzionante + meter prominente (JAG-110)

## Problema (evidenza dal codice)

- Il tasto WebUI chiama `POST /api/context/compact {session}` →
  `compact_session(session)` (percorso **manuale**).
- `context_engine.compact` usa **`keep_recent=8` fisso**: una sessione con
  ≤ 8 messaggi produce `old=[]`, quindi **il summarizer non viene mai chiamato**
  (nessuna GPU) e `compacted=0`. Il pulsante sembra un no-op.
- Il percorso manuale **non ha forza**: sotto certe dimensioni l'early-return
  "sotto budget" può evitare del tutto la compattazione.
- L'evento `context.compact` **non dichiara** se il riassunto è `llm` o
  `extractive`, né **quale modello** ha risposto → impossibile vedere se la GPU
  dovrebbe muoversi.
- La barra contesto (`.meter`, 8px) a 1.7% è un filo invisibile; il pannello non
  rende evidente la saturazione.

## Obiettivi

1. Il compact **manuale** riduce sempre una sessione con più di
   `COMPACT_MANUAL_KEEP_RECENT` messaggi.
2. Il compact manuale **tenta sempre** il summarizer LLM (ruolo `summarizer`) e
   registra **quale modello** ha risposto.
3. `context.compact` (evento SSE + risposta HTTP + FEED) espone:
   `summary` (`llm`/`extractive`) e `summarizer` (alias o `null`).
4. Il meter di contesto è **prominente**: barra alta con minimo visibile, `%`
   grande, colore di stato; la stessa informazione su WebUI e app (single source
   = server, come JAG-107).

## Design

### Engine (`context_engine.py`)
- `compact(messages, budget_tokens, keep_recent=DEFAULT_KEEP_RECENT,
  summarizer=None, force=False)`.
- Se `force=True` salta l'early-return "sotto budget" (`input_tokens <=
  budget_tokens`) e compatta comunque `len - keep_recent` messaggi.
- `stats` resta: `summary` ∈ {`llm`, `extractive`, `None`}.

### Server (`server.py`)
- Nuova costante `COMPACT_MANUAL_KEEP_RECENT` (env
  `SPARKFORGE_COMPACT_MANUAL_KEEP_RECENT`, **default 2**).
- `compact_session(session, budget_tokens=None, keep_recent=None)`:
  - **manuale** (`budget_tokens` assente): `force=True`,
    `keep_recent=COMPACT_MANUAL_KEEP_RECENT`.
  - **auto** (con `budget_tokens`): `force=False`, `keep_recent=None`
    (default engine 8) — invariato.
- `_summarize_with_llm(messages, model=None, meta=None) -> str|None`: quando il
  modello risponde scrive `meta["model"] = <alias risolto da
  stream_with_fallback>`.
- `stats["summarizer"] = meta.get("model")`; `publish("context.compact", **stats)`
  li include già.

### WebUI (`webui/index.html`)
- Card CONTEXT: barra ~14px con **minimo visibile** (anche a bassa %), riga grande
  `pct%` + `tok / budget`, etichetta stato (`normale`/`auto-compact al 75%` /
  `sopra soglia`).
- Pill top-bar: più prominente, tint `warn`/`err` per stato `near`/`over`.
- FEED e toast di compact: includono `· llm:<alias>` oppure `· estrattivo`.

### App (`ForgePanels.kt` / `ForgeScreen.kt`)
- Barra più alta + etichetta stato; nessuna logica nuova (usa `display.*`).

## Non-obiettivi
- Nessuna modifica ai ruoli di routing.
- Nessun nuovo endpoint (si estende `context.compact`).

## Test (TDD — `tests/v110_context_compact.py`)
- **E1** `force=True` compatta sotto budget; senza force no.
- **E2** `keep_recent` rispettato.
- **S1** manuale su sessione piccola → riduce e `summary=llm`,
  `summarizer=<alias>`.
- **S2** fallback → `summary=extractive`, `summarizer=None`.
- **S3** percorso auto invariato (`keep_recent=8`).
- **S4** evento `context.compact` contiene `summary`+`summarizer`.
- **D1** `context_display` espone `pct`/`bar_pct`/`state` (regressione).

## Rischi / mitigazioni
- `tests/v103_llm_compaction.py` monkeypatcha `_summarize_with_llm` con firma a 2
  argomenti → aggiornare a `(messages, model=None, meta=None)`.
- Il fallback estrattivo resta: la compattazione non può mai bloccare un turno.
