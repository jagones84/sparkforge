# Harness di frontiera: meccanismi che rendono l'agente più affidabile del modello (2025-2026)

Ambito: solo meccanismi concreti, implementabili in un harness Python stdlib-only.
Per ogni asse: fatti citati dalla fonte + 1 riferimento primario. Nessuna opinione.

## 1. Verifier / test-time verification

- Il feedback basato su esecuzione (unit test) è la pratica dominante per gli agenti di
  coding, ma è "sparse" e non distingue traiettorie ugualmente riuscite/fallite: SWE-RM
  propone feedback execution-free da reward model (MoE, 30B totali / 3B attivi) che porta
  Qwen3-Coder-Flash da 51.6% a 62.0% su SWE-Bench Verified in test-time scaling.
- ExecCritic separa i ruoli: un Test agent genera test repository-native, un "fail-closed
  harness" li qualifica e li congela, poi un Repair agent modifica il codice senza toccare
  i test. Con test base il resolved rate scende da 61.2% a 57.3%; con test di qualità sale
  a 65.3% -> i test scritti dalla stessa traiettoria della patch possono creare falsa fiducia.
- Pattern implementabile stdlib: applica la patch in sandbox, esegui i test, accetta solo
  se verdi ("apply-only-if-green"), altrimenti rollback e ri-edit dal log di errore.
- SWE-RL formalizza la traiettoria (read issue -> search -> patch -> run test -> re-edit):
  il verifier è una test suite in ambiente isolato; patch che passa = reward, failure log
  = osservazione successiva.
- Fonti primarie: SWE-RM (ICLR 2026) https://openreview.net/forum?id=H9wMe1G76j ;
  ExecCritic https://arxiv.org/abs/2609.09133 ; SWE-RL https://arxiv.org/abs/2502.18449

## 2. Test-Time Compute & allocazione adattiva

- Snell et al. (2408.03314) misurano due meccanismi: ricerca contro verifier process-based
  densi e aggiornamento adattivo della distribuzione della risposta. L'efficacia di ciascuno
  dipende criticamente dalla difficoltà del prompt.
- Da ciò la strategia "compute-optimal": allocare test-time compute in modo adattivo per
  prompt, con efficienza >4x rispetto a un baseline best-of-N.
- In valutazione FLOPs-matched, il test-time compute può superare un modello 14x più grande
  sui problemi dove il modello piccolo ha success rate non banale; sui task facili il
  best-of-N/greedy è migliore, su quelli medi/difficili la ricerca (beam) lo è.
- Pattern implementabile: best-of-N con ranker + early-exit per task facili + budget
  crescente per difficoltà stimata.
- Fonte primaria: Snell et al., "Scaling LLM Test-Time Compute Optimally..." https://arxiv.org/abs/2408.03314

## 3. Self-evolving / meta-apprendimento

- Voyager (TMLR 2024) usa tre componenti: curriculum automatico, skill library di codice
  eseguibile "ever-growing", e prompting iterativo che incorpora feedback dell'ambiente,
  errori di esecuzione e self-verification. Risultati: 3.3x item unici, 2.3x distanza,
  milestone tech-tree fino a 15.3x più veloci; le skill sono interpretabili, componibili e
  mitigano il catastrophic forgetting.
- La self-verification in sandbox è il filtro che stabilizza la libreria: si accumulano solo
  skill il cui codice è stato eseguito e verificato con successo.
- La survey 2026 "Agent Self-Evolution" mappa i sistemi (Voyager, Reflexion, DGM, ADAS,
  AlphaEvolve, ACE) lungo gli assi "cosa/quando/come evolve" (modello, contesto, tool, architettura).
- Pattern implementabile: sintesi automatica di skill/tool verificate in sandbox + memory
  consolidation + curriculum a difficoltà crescente.
- Fonti primarie: Voyager https://arxiv.org/abs/2305.16291 ;
  survey https://agent-evolution.com/reports/self-evolve-survey-zh.pdf

## 4. Context/state di frontiera

- OpenHands Condenser comprime la history: LLMSummarizingCondenser scatta su soglia
  (max_size default 120 eventi), conserva verbatim i primi N (keep_first default 4) più il
  tail, riassume il middle con un LLM e registra un evento Condensation con forgotten_event_ids;
  la View filtra gli eventi "dimenticati" e reinserisce il summary. La history su disco resta
  completa: la compressione è una modifica di vista (replay-abile).
- Anthropic ("Effective context engineering") tratta il contesto come "finite attention
  budget" e indica tre tecniche long-horizon: tool-result clearing, compaction
  (summarize + reinit con summary) e sub-agent; il resume conserva gli ultimi 5 file letti.
- ACE (Agentic Context Engineering, arXiv:2510.04618, ICLR 2026) tratta il contesto come
  "playbook" evolutivo (non summary compresso) con ruoli Generator/Reflector/Curator e
  delta-update incrementali; riporta +10.6% sugli agenti e -86.9% di latenza di adattamento.
- Pattern implementabile: log event-sourced + "condense" come trasformazione di vista
  reversibile + compressione incrementale delle osservazioni.
- Fonti primarie: OpenHands Condenser https://docs.openhands.dev/sdk/arch/condenser ;
  Anthropic https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents ;
  ACE https://arxiv.org/abs/2510.04618

## Fonti

- SWE-RM — https://openreview.net/forum?id=H9wMe1G76j
- ExecCritic — https://arxiv.org/abs/2609.09133
- SWE-RL — https://arxiv.org/abs/2502.18449
- Snell et al. 2408.03314 — https://arxiv.org/abs/2408.03314
- Voyager — https://arxiv.org/abs/2305.16291
- Agent Self-Evolution survey — https://agent-evolution.com/reports/self-evolve-survey-zh.pdf
- OpenHands Condenser — https://docs.openhands.dev/sdk/arch/condenser
- Anthropic Context Engineering — https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents
- ACE — https://arxiv.org/abs/2510.04618
