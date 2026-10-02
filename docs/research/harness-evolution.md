# Harness Evolution — meccanismi di affidabilità indipendenti dal modello

Meccanismi concreti, emersi negli harness agentici di frontiera, che migliorano l'affidabilità senza cambiare il modello sottostante. Solo fatti citati da fonti primarie.

## 1. Verifica prima di applicare l'azione (verifier loop / Process Reward Model)

Nel coding-agent, il saltro di affidabilità arriva da un *reward model* che giudica la traiettoria/patch **prima** di validarla, invece del solo feedback esecutivo (test) che è sparso e non distingue due traiettorie entrambe riuscite o entrambe fallite. SWE-RM, verifier execution-free a mistura-di-esperti (30B totali, 3B attivi), fornisce feedback fine-grained e viene usato sia per test-time scaling sia come reward per RL: con il test-time scaling porta Qwen3-Coder-Flash da 51.6% a 62.0% su SWE-bench Verified, e in RL guadagna 3 punti assoluti rispetto al feedback esecutivo.

Fonte: SWE-RM (ICLR 2026) — https://openreview.net/forum?id=H9wMe1G76j

## 2. Test-Time Compute e allocazione dinamica del ragionamento

Due meccanismi distinti, entrambi indipendenti dal modello:

- **Allocazione compute-optimal (DeepMind):** scalare il calcolo in inferenza tramite (1) ricerca su un PRM denso e (2) revisione iterativa adattiva della risposta, allocando il budget per-prompt in base alla difficoltà. Produce >4× di efficienza rispetto a best-of-N e, a parità di FLOPs, un modello piccolo supera uno 14× più grande sui problemi in cui il modello base ha successo non banale.
- **Esplorazione parallela + filtro per comportamento (AlphaCode):** generazione massiva di campioni (milioni), filtro sull'esito dell'esecuzione sui test d'esempio, poi clustering per ridurre a pochi candidati da sottoporre. Così AlphaCode raggiunge in media il top 54.3% nelle competizioni Codeforces (>5000 partecipanti).

Fonti: Snell et al., "Scaling LLM Test-Time Compute Optimally…" — https://arxiv.org/abs/2408.03314 ; AlphaCode — https://arxiv.org/abs/2203.07814

## 3. Self-evolving harness / sintesi autonoma di skill

Voyager accumula competenza persistente e verificata, senza fine-tuning: (1) curriculum automatico che propone il prossimo task in base a stato e abilità; (2) **skill library** in crescita di codice eseguibile, salvata con descrizione e recuperata per embedding (riuso composizionale, evita il catastrophic forgetting); (3) prompting iterativo che incorpora feedback dell'ambiente, errori di esecuzione e **self-verification** per correggere il programma finché non passa. Le skill, verificate in sandbox prima di essere archiviate, ottengono 3.3× più item unici, distanze 2.3× maggiori e milestone del tech tree fino a 15.3× più rapide rispetto al SOTA.

Fonte: Voyager (Wang et al., TMLR 2024) — https://arxiv.org/abs/2305.16291

## Fonti

1. SWE-RM: Execution-free Feedback for Software Engineering Agents (ICLR 2026) — https://openreview.net/forum?id=H9wMe1G76j
2. Scaling LLM Test-Time Compute Optimally can be More Effective than Scaling Model Parameters (Snell et al., ICLR 2025) — https://arxiv.org/abs/2408.03314
3. Competition-Level Code Generation with AlphaCode (Li et al., Science 2022) — https://arxiv.org/abs/2203.07814
4. Voyager: An Open-Ended Embodied Agent with Large Language Models (Wang et al., TMLR 2024) — https://arxiv.org/abs/2305.16291