# Spec — Memoria self-managed + avviso di completamento del piano (2026-10-02)

Stato: **approvato** (brainstorming con l'utente). Ambito: SparkForge.

## Problema

1. **Memoria opaca.** `memory.py` dichiara i kind `tool.result`, `plan.update`,
   `task.done`, `chat.summary` in `MEMORY_FIELDS`, ma **nessun** call-site li
   scrive. La memoria si aggiorna solo per: tool `memory` (store), riflessione
   automatica (`agent.note`), `meta.*`. Manca un blocco **sempre visibile** che
   l'agente possa riscrivere: oggi i ricordi sono solo "recuperati per similarità".
2. **Il piano resta incompleto.** Il loop chat termina appena il modello risponde
   in prosa senza tool; **nessuno** controlla il task graph persistente. L'hook
   `Stop` esiste ma il suo esito è ignorato. Risultato: l'agente si ferma con
   passi aperti.

Ricerca (pattern dominanti): MemGPT/Letta (memory block editabili via tool),
Mem0 (estrazione/consolidazione esterna), Agentic Memory/AgeMem e Meta CLM
(le operazioni di memoria sono **azioni del modello**). Conclusione: **la memoria
la scrive il modello quando decide**, tramite tool, con un blocco sempre-visibile.

## Decisioni (dall'utente)

- **Completamento**: *solo avviso*, **niente** auto-continua.
- **Memoria**: *guida nel prompt + blocco `core` editabile* (mini-MemGPT). Niente
  auto-write dell'harness sui 4 kind.

## Design A — Avviso di pianificazione incompleta

- A fine turno (`chat_stream_gen`, dopo aver persistito la risposta) si legge
  `taskgraph.load(sess_id)`; se ci sono nodi con status in
  `OPEN_STATUSES = (todo, doing, blocked)` → si pubblica l'evento
  **`plan.incomplete`** con `{session, open, total, items:[label…]}`.
- **Nessuna chiamata LLM extra**, nessun blocco: il turno finisce normalmente.
- **WebUI**: banner in chat "⚠ restano N passi aperti: …" con pulsante
  **▶ continua** → invia un messaggio (`send("Continua: completa i passi aperti
  del piano.")`) che rientra nel loop. Il pulsante è l'unico modo per riprendere.

## Design B — Memoria self-managed (blocco `core`)

- **Store**: `data/memory/core.md`, un unico blocco di testo, cap
  `SPARKFORGE_CORE_MAX` (default 4000 char). API in `memory.py`:
  `core_read() -> str`, `core_write(content) -> {ok, chars}`.
- **Tool** `memory`, nuove azioni:
  `action:'core'` (legge il blocco), `action:'set_core'` (lo riscrive).
  Aggiornata la `enum` in `registry.TOOL_SCHEMAS["memory"]`.
- **Prompt**: il blocco `core` è **sempre iniettato** nel system prompt
  (`## Core memory (always visible …)`), subito dopo `MEMORY_POLICY`. La
  `MEMORY_POLICY` spiega *quando* aggiornarlo (preferenze utente, convenzioni di
  progetto, decisioni chiave) e di tenerlo compatto.
- Nessuna scrittura automatica dell'harness sui 4 kind dichiarati.

## Test (TDD)

- `tests/v134_plan_incomplete.py`: `chat_stream_gen` calcola i nodi aperti e
  pubblica `plan.incomplete`; la WebUI ha il listener + il pulsante "continua".
- `tests/v135_memory_core.py`: `core_read/core_write` round-trip + cap; il tool
  `memory` espone `core`/`set_core`; lo schema li dichiara; il prompt inietta il
  blocco core e la guida.

## Fuori ambito (YAGNI)

- `update`/`delete` delle memorie; archival/recall tier; auto-continua;
  scrittura automatica dei 4 kind.
