# Frontier harness 2026 vs SparkForge — skills, MCP, failure modes, nicchia

Data: 2026-10-04. Fonte: doc ufficiali Anthropic (Agent Skills), spec/roadmap MCP,
paper (HORIZON 2604.11978, LongHorizon-Harness 2608.01964, goal-drift 2505.02709 /
2603.03258), Anthropic "Effective harnesses for long-running agents", COMPEL
failure catalog, leaderboard 2026 (SWE-Bench Verified, OpenHands Index).

---

## 1. Come le harness di frontiera caricano le SKILL

**Claude Code / Anthropic — progressive disclosure a 3 livelli:**
- **L1 metadata** (`name` + `description` dal frontmatter YAML): SEMPRE nel system
  prompt, ~100 token per skill. È il trigger: il modello confronta la richiesta con
  la `description` ("Use when…"). Costo quasi nullo fino al trigger.
- **L2 istruzioni** (corpo `SKILL.md`): lette dal filesystem **solo quando attivate**.
- **L3 risorse/script** (`references/`, `scripts/`, `assets/`): solo se referenziate.
- Attivazione anche via `/skill-name`.

**SparkForge — già allineato (JAG-163), + novità JAG-198:**
- **L1**: `skills.skills_context()` inietta `name` + descrizione breve di TUTTE le
  skill installate (budget 8000 char). Policy `SKILLS_POLICY` dice di SCAN/LOAD.
- **L2**: `skills{action:"read",name}` carica il corpo su richiesta.
- **L3**: gli script si eseguono via `shell`.
- **NUOVO JAG-198**: `skills{action:"search",query}` = **ricerca keyword** con
  ranking (nome 3x, descrizione 1x) → *progressive discovery* (come la roadmap MCP
  e ScaleMCP). Serve perché con **179 skill** il blocco L1 viene troncato: la
  ricerca copre quelle fuori budget.

Conclusione: il meccanismo è identico al frontier; unica lacuna chiusa = ricerca.

## 2. Come sono caricati gli MCP tools

- **Frontier**: gli schemi dei tool si caricano **tutti up-front** (costo di
  contesto). La roadmap MCP 2026 dice esplicitamente che "tool scale is now a
  protocol concern: dumpare 100 schemi prima che l'utente chieda costa contesto e
  peggiora la selezione" → **progressive discovery**. ScaleMCP (arXiv 2505.06416):
  retriever di tool MCP che l'agente equipaggia on-demand via CRUD, auto-sync.
- **SparkForge**: `api_v02.tool_context()` elenca gli schemi dei tool ABILITATI;
  gli MCP appaiono come `<client>__<tool>` (oggi 26 `pmcp.*`). Stesso costo up-front,
  nessun retrieval dinamico.
- **Azione (RDD, futuro)**: se i tool abilitati superano ~50, introdurre schemi MCP
  *differiti* + un `tools{action:"search"}`. Oggi non è un problema.

## 3. Failure mode degli agenti long-horizon (ricerca) vs nostra architettura

| Failure (fonte) | Come SparkForge risponde |
|---|---|
| **Goal drift / goal persistence** (2505.02709, 2603.03258) | task list persistente (`write_todos`) per-sessione, re-iniettata ogni turno, sopravvive a compaction/restart; **stale-plan pivot** JAG-189; `begin_plan` conserva il piano vecchio JAG-194 |
| **Errore composto / history error accumulation** (HORIZON) | anti-loop: ri-esecuzione verbatim di una call FALLITA bloccata (JAG-183); `fail_streak` → stuck coach socratico; `done` richiede **evidenza** |
| **Loop infinito / no-progress** (COMPEL) | `max_steps`, runaway guard (ripetizione), no-progress detector, **abort reattivo** JAG-197 |
| **Context rot / finestra esaurita** (long-horizon) | budget = `n_ctx` reale del router, auto-compact al 75%, **tool-output offload**, meter onesto |
| **"Dichiarare fatto" troppo presto** (Anthropic) | loop **keepgoing** non finalizza; i nodi chiudono solo con evidenza → `plan.incomplete` |
| **Task-state loss** (LongHorizon-Harness: Manage-Execute-Audit) | la task list persistente È lo stato esplicito fuori contesto, aggiornata con evidenza e re-iniettata (sezione `state`) |
| **Planning error / false assumption** (HORIZON) | `replan_todos` (solo nuovi step); best-of-N quando il campione è inutilizzabile |
| **Fermarsi / stall** (COMPEL) | **JAG-197**: Stop reale anche su router silenzioso |
| **Memoria corrotta** (COMPEL) | memoria governata (core + note con governance), non auto-reinject cieco |

## 4. Dove SparkForge è AVANTI (parti uniche vs frontier harness)

1. **PRM / best-of-N deterministica** — un process-reward ranker deterministico +
   stimatore di difficoltà "compute-optimal" che dosa N e il budget del keepgoing.
   Le harness di frontiera si affidano al modello o a un singolo campione.
2. **Verifier gate (apply-only-if-green)** — test/lint/diff PRIMA di applicare.
3. **Contesto vincolato**: tool-output offload + budget reale + auto-compact.
4. **Task graph LLM inline con `done` gated dall'evidenza** (non un planner separato).
5. **Feed SSE loopback** per mobile + WebUI single-file.
6. **Stdlib-only, zero dipendenze**, stesso codice su DGX e Windows (osutil).
7. **`self` tool + prompt section registry** + regola "capability dalla prompt".
8. **Meta self-improvement + ACP + swarm/blackboard** (sperimentale).
9. **MCP bidirezionale** (client + server mode).

## 5. Backlog RDD (research-driven)

- [x] **JAG-198** ricerca skill (`skills{action:"search"}`).
- [ ] Schemi MCP differiti + `tools{action:"search"}` sopra ~50 tool abilitati.
- [ ] Rafforzare "non dichiarare fatto presto": step **auditor** read-only
      (pattern LongHorizon Manage-Execute-Audit) come subagent/verifier.
- [ ] Metrica di **goal drift** (GD_actions / GD_inaction) sui run (runmetrics).
