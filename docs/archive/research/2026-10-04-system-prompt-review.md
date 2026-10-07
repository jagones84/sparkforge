# Revisione del system prompt di SparkForge (JAG-202)

Data: 2026-10-04. Metodo: `trash/dump_prompt.py` compone il prompt REALE con
`server._system_prompt(None)` e ne stampa le dimensioni per sezione.

## 1. Composizione (prima → dopo JAG-202)

| sezione | prima (char) | dopo (char) | note |
|---|---|---|---|
| identity | 255 | 255 | statico |
| prompt-map | 661 | 661 | meta (spiega le sezioni al modello) |
| self-summary | 733 | 733 | path/versione/come estendere |
| **tools** | **6966** | **6461** | registri + muro DISABLED compattato |
| rules-policy | 427 | 427 | statico |
| rules | 2913 | 2864 | letto dal disco ogni turno |
| skills-policy | 586 | 586 | statico |
| **skills** | **8013** | **2674** | indicizzazione breve (era un dump troncato) |
| memory-policy | 1017 | 1017 | statico |
| capability | 385 | 385 | statico |
| state | 61 | 61 | task list |
| **TOTALE** | **22035** | **16142** | ~5508 → ~4035 token (−26%) |

## 2. Difetti trovati

- **F1 — Skills troncato.** Con **179 skill** il blocco a 8000 char veniva tagliato
  (`…[truncated]`): ~2/3 della libreria INVISIBILE e ~2000 token spesi per una lista
  inutilizzabile. → indice breve (2600) + hint a `skills{action:"search"}`.
- **F2 — Muro dei tool DISABLED.** ~900 char che elencavano 20 tool non chiamabili,
  affogando i tool reali (regressione JAG-80 reintrodotta). → una riga con conteggio
  + 3 esempi (~183 char).
- **F3 — Ridondanza regole.** "Rules (global+project)" (policy) e "Rules on disk"
  dicono quasi la stessa cosa. Minore, lasciato.
- **F4 — prompt-map** spiega al modello la MECCANICA del prompt (meta). Piccolo,
  utile per self-modifica; lasciato.
- **F5 — self-summary "SparkForge v0.6"** può divergere da VERSION reale.

## 3. Quando il modello LEGGE cosa (domanda utente)

- **SparkForge: il prompt è ricostruito ad OGNI turno.** `prompt.render_sections`
  chiama i provider dinamici (tool/skills/memory/rules/state) a ogni richiesta, e
  le **regole su disco vengono rilette ogni turno** (`rules.rules_prompt_block`).
  → Vantaggio: una regola modificata ha effetto IMMEDIATO, senza restart.
  Limite: costo/token a ogni turno.
- **TRAE (questo IDE):** `project_rules.md` + `user_rules` vengono iniettate
  dall'IDE nel contesto dell'assistente per sessione/richiesta (il blocco
  `<trae_rules_context>`). Sono regole del *developer harness*, non del runtime.
- **Claude Code:** `CLAUDE.md` letto all'inizio sessione (poi in cache); le skill
  sono progressive disclosure (metadata sempre, corpo on demand). Le regole NON
  sono rilette per turno.
- **openclaw:** stessa famiglia (harness con regole+skill iniettate a sessione);
  il pattern di caricamento è equivalente al nostro L1/L2.

Conclusione: la nostra gestione è più *live* (regole rilette per turno), in linea con
le harness di frontiera sul lato skill; l'unica lacuna era la discovery (risolta con
`search`, JAG-198) e il budget del prompt (risolto qui, JAG-202).

## 4. Raccomandazioni (backlog)

1. **Curare la libreria skill**: 179 con doppioni (mcp-builder / mcp-server-builder-guide,
   tdd / test-driven-development, brainstorming…). Ridurla o marcare i duplicati →
   meno rumore, meno ambiguità di selezione (la ricerca scientifica: >~40% di
   utilizzazione del contesto peggiora le prestazioni).
2. **Allineare `self_summary` alla VERSION** reale (import da server.VERSION).
3. **Unificare la doppia sezione regole** in una sola.
4. **Misurare l'impatto**: prompt 4k token su 258k = 1.6% — già ottimo; ogni
   aggiunta va giustificata da un test (v198 G1 già protegge il budget).
