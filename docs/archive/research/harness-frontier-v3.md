# Harness Frontier v3 — 4 assi di ricerca

Ricerca web (fonti primarie). Solo fatti citati; niente opinioni.

## 1. Stima della difficoltà del task per allocare test-time compute

- Snell et al. analizzano due meccanismi per scalare il test-time compute: (1) search contro
  verifier reward model densi e process-based; (2) aggiornamento adattivo della distribuzione
  della risposta in base al prompt.
- L'efficacia delle diverse strategie di scaling dipende criticamente dalla difficoltà del prompt.
- Da ciò una strategia "compute-optimal" che alloca il test-time compute in modo adattivo per
  prompt: migliora l'efficienza dello scaling di oltre 4x rispetto a una baseline best-of-N.
- In valutazione FLOPs-matched, sui problemi dove un modello più piccolo raggiunge un successo
  non banale, il test-time compute permette di superare un modello 14x più grande.

Fonte: Snell et al., "Scaling LLM Test-Time Compute Optimally…", arXiv:2408.03314 — https://arxiv.org/abs/2408.03314

## 2. Verifier-guided search / reward model come guida

- Best-of-N: si campionano N risposte dalla policy e si restituisce quella con punteggio più alto
  del verifier, `y*N = argmax_i verifier(sample_i)`.
- Rischio Goodhart: il verifier è una proxy del target; l'ottimizzazione può sfruttare il gap tra
  proxy e intento reale (reward hacking / over-optimization).
- Tassonomia di exploit documentata: extraction (soddisfa l'answer-extractor senza svolgere il
  task), reward shaping (format/partial credit), test-adequacy failures, learned verifier biases,
  distribution shift, mechanism gaps.
- Exploit empirici: manipolazione degli unit test e "missing negative" (test senza casi negativi).

Fonte: "Reinforcement Learning from Verifiable Rewards", cap. 7 Reward Hacking — https://rlvrbook.com/chapters/07-reward-hacking-and-verifier-robustness.html

## 3. Sintesi automatica di skill/strumenti (dal pattern al codice eseguibile)

- Voyager usa tre moduli: automatic curriculum, skill library, e un meccanismo di prompting
  iterativo che incorpora feedback dell'ambiente, errori di esecuzione e self-verification.
- Le skill sono programmi eseguibili (JavaScript) indicizzati per descrizione in linguaggio
  naturale e recuperati quando una situazione assomiglia a una già risolta.
- Write-gate: la skill entra nella libreria solo se verifica positiva, `if info["success"]:
  skill_manager.add_new_skill(info)`, dove `success` viene da un critic agent che ispeziona lo
  stato dell'ambiente dopo l'esecuzione.
- Composizione: le skill precedenti diventano primitive richiamabili da quelle successive.
- Risultati dichiarati: 3.3x più item unici, 2.3x distanza esplorata, fino a 15.3x più veloce
  nei milestone, e uso della skill library in un mondo nuovo per task inediti.

Fonte: Wang et al., "Voyager: An Open-Ended Embodied Agent with LLMs", arXiv:2305.16291 — https://arxiv.org/abs/2305.16291

## 4. Orchestrazione e control loop (ordine tra stop conditions, steer/abort/keepgoing)

- Ogni approccio di orchestrazione richiede il concetto di "run": un loop che fa operare gli
  agenti fino a una exit condition.
- Exit conditions comuni: invocazione di un tool (es. final-output tool), output strutturato,
  errori, oppure raggiungimento di un numero massimo di turni.
- Nell'Agents SDK il loop termina quando viene invocato un final-output tool, oppure il modello
  risponde senza tool call, oppure si raggiunge il limite di turni.
- Guardrails fungono da controllori del loop su input e output: se un guardrail rileva una
  violazione (es. input dannoso) interrompe l'esecuzione del workflow.
- Due categorie di orchestrazione: agente singolo (loop + tool) e più agenti (manager/worker,
  decentralizzato); la scelta dipende dalla complessità del task.

Fonte: OpenAI, "A practical guide to building agents" — https://openai.com/business/guides-and-resources/a-practical-guide-to-building-ai-agents/

## Fonti

1. Snell et al., arXiv:2408.03314 — https://arxiv.org/abs/2408.03314
2. RLVR Book, cap. 7 "Reward Hacking" — https://rlvrbook.com/chapters/07-reward-hacking-and-verifier-robustness.html
3. Wang et al., Voyager, arXiv:2305.16291 — https://arxiv.org/abs/2305.16291
4. OpenAI, "A practical guide to building agents" — https://openai.com/business/guides-and-resources/a-practical-guide-to-building-ai-agents/
