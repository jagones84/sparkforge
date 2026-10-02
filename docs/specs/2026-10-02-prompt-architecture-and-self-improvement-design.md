# Spec — Architettura del prompt generalizzata + routing del self-improvement (2026-10-02)

Stato: **approvato** (brainstorming con l'utente). Ambito: SparkForge.

## Problema

1. **System prompt cablato nel codice.** Lo monta `_system_prompt()`
   (server.py:2815): concatena costanti hardcoded (`SYSTEM_PROMPT`,
   `RULES_POLICY`, `MEMORY_POLICY`, `SKILLS_POLICY`) con blocchi generati a
   runtime (tool list, skill list, rules, memoria, task list). Composizione e
   ordine sono fissi nel Python: cambiare il comportamento dell'agente significa
   toccare il codice.
2. **"Risposto male."** Alla domanda "come fai a sapere di avere il tool
   memory?" l'agente ha eseguito `git status` + `find` invece di rispondere dal
   proprio tool block. Nel prompt non esiste una direttiva per le domande sulle
   proprie capacità.
3. **Self-improvement non instradato.** `memory.maybe_reflect` scrive note
   `agent.note`, ma non è definito *dove* l'agente debba scrivere *cosa*
   (memoria? regole di progetto? regole globali? codice?).

## Ricerca (pattern di frontiera)

- **Prompt = assembly dinamico a blocchi**, non monolite. Claude Code: 29-110
  blocchi condizionali; anatomia a 4-5 layer (identità → regole → tool tipizzati
  → safety → sezioni condizionali). [zylos.ai, blckalpaca.at, ai-systems-2026.halla.ai]
- **Overlay a file per scope, tutti caricati e concatenati** (Claude Code:
  global + project + directory). In caso di **conflitto** vince il più specifico
  (proximity wins). [code.claude.com/docs/en/memory, docs.qcode.cc]
- **Tool/skill = tipizzati e generati a runtime**, mai spostati in prosa; ~4500
  token per 31 tool → si filtrano. [zylos.ai]
- **Self-improvement per scope** — separazione netta: *l'umano scrive le
  istruzioni, il modello accumula apprendimenti*. Claude Code: `CLAUDE.md`
  (umano) vs auto-memory `MEMORY.md` (modello, per-repo). "La memoria è
  contesto, non configurazione"; per imporre divieti servono gli hook. Hermes:
  *periodic nudge* + creazione autonoma di skill con soglie (≥5 tool call,
  recovery da errore, correzione utente), aggiornamento via *patch*. Letta/
  MemGPT: tier core/recall/archival, il modello promuove. DGM/Self-Harness: il
  modello riscrive il proprio **codice** ma con gate di test (frontier).
  [code.claude.com/docs/en/memory, mranand.substack.com, superkind.ai, tonybai.com]

Conclusione: **l'agente scrive libero solo la propria memoria**; le **regole**
(progetto/globale) le scrive l'umano — l'agente al massimo *propone*; il
**codice** solo con gate di test.

## Decisioni (dall'utente)

- **Additivo**: tutti i livelli sono letti e concatenati. Nessun livello
  esclude la lettura di un altro.
- **Gerarchia sulle sole contraddizioni**: `progetto > globale > default`.
- **Tool e skill restano generati a runtime**: non si spostano in prosa.
- **Niente replace-marker** (nessuna sostituzione piena).

## Parte A — Registro di sezioni del prompt

Modulo nuovo `prompt.py`. Una *sezione* è:

```
{id, order, kind, default, provider?}
```

- `kind=dynamic` → **provider in codice**, generato a runtime, **invariato**:
  `tools` (api_v02.tool_context), `skills` (skills.skills_context),
  `rules` (rules.rules_prompt_block), `memory` (lessons + core), `harness-state`
  (task list).
- `kind=static` → **testo** di comportamento:
  `identity` (ex SYSTEM_PROMPT), `rules-policy`, `skills-policy`,
  `memory-policy`, `capability-rule` (nuova), `manifest` (nuova).

**Overlay a file** (additivo, non sostitutivo):
- globale: `~/.config/sparkforge/prompt.d/<NN>-<id>.md`
- progetto: `<ws>/.sparkforge/prompt.d/<NN>-<id>.md`

**Merge**: contenuto finale della sezione = `default` **+** `addendum globale`
**+** `addendum progetto`, **concatenati**. Un file overlay **aggiunge**, non
sopprime il default.

**Ordine**: campo `order`; il prefisso `NN-` nei file ordina gli addendum tra
loro; gli addendum di progetto vanno in coda (più specifici).

**Contraddizioni**: l'header di ogni blocco dichiara esplicitamente la regola —
*"in caso di conflitto prevale il livello più specifico: progetto > globale >
default"* — così il modello sa quale prevale.

**Manifest**: sezione `static` che elenca i path reali delle sezioni e delle
regole → l'agente può auto-ispezionarsi senza improvvisare shell (**fix del
"risposto male"**).

**Regola capability** (sezione `static`): "domande sulle tue capacità →
rispondi dal tool registry block (o dal tool `self`); **mai** con shell/git".

**API**: `prompt.render_sections(sess, ws) -> str`. `_system_prompt()` diventa
un wrapper sottile che chiama `render_sections` (resta l'unica fonte per il
prompt inviato e per l'indicatore di contesto).

## Parte B — Routing del self-improvement

| Scope | File | Owner | Scrittura agente |
|---|---|---|---|
| memoria core | `data/memory/core.md` | agente | **libera** (silent) |
| memoria note/lessons | `data/memory/*.md` | agente | **libera** (silent) |
| skill procedurali | `skills/<cat>/<name>/` | agente | **proposta → conferma** (soglia) |
| regole progetto | `<ws>/.sparkforge/RULES.md` | umano | **solo proposta** (no silent) |
| regole globali | `~/.config/sparkforge/RULES.md` | umano | **solo proposta** (no silent) |
| codice harness | `sparkforge/*.py` | umano | **fuori scope** (gate test) |

- **Nudge periodico** (pattern Hermes): a fine turno, se scatta una soglia
  (≥5 tool call, *oppure* recovery da errore, *oppure* correzione dell'utente),
  l'agente valuta cosa persistere → scrive in memoria (auto) e/o emette
  **proposte**.
- **Mai scrittura silenziosa** su regole progetto/globali: si emette l'evento
  **`improve.proposal`** `{scope, target_path, diff, reason}`; l'utente
  approva/rifiuta dalla WebUI. Solo dopo approvazione il file viene scritto.
- **Skill**: proposta con soglia; creazione/aggiornamento via *patch* (non
  rewrite), coerente con Hermes.
- **Memoria**: resta `memory.py` (`store`, `core`, `maybe_reflect`). Invariata.
- **Codice harness**: esplicitamente fuori scope (richiederebbe
  mine → propose → validate-by-tests; pattern frontier da valutare a parte).

## Test (TDD)

- `tests/v136_prompt_sections.py`: merge **additivo** (default + globale +
  progetto concatenati, nessuno escluso); gerarchia dichiarata sulle
  contraddizioni; overlay file letto; manifest presente; provider `dynamic`
  (tools/skills/rules/memory) intatti; regola capability presente;
  `_system_prompt()` == `render_sections()`.
- `tests/v137_self_improve_routing.py`: memoria = scrittura libera; regole
  progetto/globali = **solo** `improve.proposal` (nessuna scrittura diretta);
  scatto soglie (≥5 tool call / error / correzione); evento proposta emesso.

## Fuori scope / default

- **Niente replace-marker**: tutto additivo.
- **Niente auto-write del codice** dell'harness.
- **Niente auto-write silenzioso delle regole**: solo proposte; l'auto-write
  potrà essere abilitato in futuro come opzione esplicita.
