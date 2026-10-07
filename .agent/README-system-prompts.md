# System prompts — mappa completa (hardcoded vs file-based vs dinamico)

> Perché esiste: il system prompt dell'harness NON è un monolite né tutto hardcoded.
> È una **lista ordinata di sezioni**, alcune con testo di default in codice e altre
> generate a runtime; tutte estendibili con file. Questo file è la fonte unica per
> capire "cosa finisce nel prompt e da dove".

## 1. Chi monta il prompt

`server._system_prompt(sess, tool_ctx)` → `prompt.render_sections(sess, ws, tool_ctx)`
(`src/sparkforge/prompt.py`). È l'UNICA fonte: lo stesso testo è quello inviato al
modello e quello misurato dalla ctx-bar (`server.context_usage`). Non esistono due
versioni.

## 2. Le sezioni (in ordine) — `prompt.SECTIONS`

| # | id | tipo | da dove viene |
|---|----|------|----------------|
| 10 | `identity` | **statico** | `server.SYSTEM_PROMPT` |
| 15 | `prompt-map` | **statico** | `prompt._manifest_text()` (spiega al modello la mappa) |
| 20 | `self-summary` | dinamico | `server.self_summary()` (path, config, skill dir…) |
| 30 | `tools` | dinamico | `server._tool_context()` = `CHAT_TOOL_PROMPT` + registro tool LIVE |
| 40 | `rules-policy` | **statico** | `server.RULES_POLICY` |
| 41 | `rules` | dinamico | file regole global+progetto (path + contenuto) via `rules.rules_prompt_block` |
| 50 | `skills-policy` | **statico** | `server.SKILLS_POLICY` (come usare le skill) |
| 51 | `skills` | dinamico | `skills.skills_context(max_chars=2600)` → indice LIVE (nome+1 riga) |
| 60 | `memory-policy` | **statico** | `server.MEMORY_POLICY` |
| 61 | `memory` | dinamico | lezioni + core mem store (`memory.governed_query`/`core_read`) |
| 70 | `capability` | **statico** | `prompt.CAPABILITY_RULE` |
| 90 | `state` | dinamico | `"Harness state (your persistent task list):"` + `server.context_summary(session_id)` |

- **statico** = testo di default scritto in codice (`server.py` / `prompt.py`).
- **dinamico** = provider che genera il testo a runtime (tools/skills/rules/memory/state).

## 3. Overlay file-based (ADDITIVI, non sostitutivi)

- globale: `~/.config/sparkforge/prompt.d/<NN>-<id>.md`
- progetto: `<workspace>/.sparkforge/prompt.d/<NN>-<id>.md`

`<NN>` ordina l'addendum, `<id>` è l'id della sezione (es. `30-tools.md`,
`70-capability.md`). Su **contraddizione** vince il livello più specifico:
**PROGETTO > GLOBALE > DEFAULT**. Oggi si può **aggiungere** a una sezione; non
ancora **sostituire** il default (vedi §6).

## 4. I tre falsi "hardcoded" segnalati

1. **Lista skill** → NON hardcoded. Sezione `skills` = `skills.skills_context()`, che
   scansiona `skills/` (oggi 179). È un **indice** limitato (nome+descrizione); il
   corpo si carica on-demand con `skills{action:'read'}` e si cerca con
   `skills{action:'search'}` (JAG-198/202). L'agente **si auto-vede** le skill; il
   testo statico `skills-policy` spiega solo *come* usarle.
2. **Task list ("Esaminare suite…")** → NON hardcoded. Sezione `state` =
   `context_summary(session_id)` che legge il **taskgraph di QUELLA sessione** da
   disco. Quei nodi sono un piano persistito della sessione (grep nel repo = 0 match).
3. **Tool `pmcp__gateway.*`** → NON hardcoded nel registro: sezione `tools` =
   `api_v02.tool_context()`, che riflette i client MCP **realmente connessi** (26 tool
   adesso). Il testo `PMCP_PROMPT` è statico ma viene iniettato **solo se** un client
   `pmcp` è configurato (`server.system_prompt()`), altrimenti sparisce.

## 5. Conseguenza pratica

- La *policy* (come comportarsi) è testo statico in codice, per stabilità.
- Il *contenuto* (skill/tool/memoria/task-list/regole) è caricato a runtime o
  file-based → l'harness è data-driven, non "hardcoded".
- Per cambiare il comportamento senza toccare il codice: aggiungere file in
  `prompt.d/` (globale o progetto).

## 6. TODO possibile (se richiesto)

Far sì che un overlay possa **sostituire** (non solo aggiungere) il default di una
sezione, es. un header `--replace` nel file o una cartella `prompt.d.replace/`.
