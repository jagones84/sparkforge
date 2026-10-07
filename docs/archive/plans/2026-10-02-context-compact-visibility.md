# Piano — JAG-110 compact contesto + meter prominente (TDD)

Spec: `docs/specs/2026-10-02-context-compact-visibility-design.md`

Esecuzione inline con checkpoint. Un commit per task. Test: `v110_context_compact.py`
(più regressione `v103`, `v107`).

## Task 1 [in corso] — Spec + piano
- [x] `docs/specs/2026-10-02-context-compact-visibility-design.md`
- [x] `docs/plans/2026-10-02-context-compact-visibility.md`

## Task 2 — Test TDD (devono fallire prima dell'implementazione)
- [ ] `tests/v110_context_compact.py` con E1, E1b, E2, S1/b/c, S2/b, S3, S4/b, D1.
- Verifica: il file esiste e i check `force`/`summarizer` **falliscono** (atteso).

## Task 3 — Engine: `force` + `keep_recent`
- [ ] `context_engine.compact(..., force=False)` salta l'early-return se force.
- Verifica: E1, E1b, E2 verdi.

## Task 4 — Server: summarizer meta + compact manuale
- [ ] `COMPACT_MANUAL_KEEP_RECENT` (env, default 2).
- [ ] `_summarize_with_llm(messages, model=None, meta=None)` scrive `meta["model"]`.
- [ ] `compact_session(session, budget_tokens=None, keep_recent=None)`:
  manuale → `force=True`, `keep_recent=COMPACT_MANUAL_KEEP_RECENT`.
- [ ] `stats["summarizer"]`.
- [ ] Aggiornare `tests/v103_llm_compaction.py` (firma lambda 3 arg).
- Verifica: S1, S2, S3, S4 verdi; v103 ancora verde.

## Task 5 — WebUI: meter prominente + feed/toast
- [ ] CSS `.meter` più alto + minimo visibile; card CONTEXT con `%` grande e stato.
- [ ] Pill top-bar più prominente (warn/err).
- [ ] `compactNow()` e handler `context.compact` mostrano `llm:<alias>`/`estrattivo`.
- Verifica: browser (chrome-devtools), barra visibile anche a bassa %.

## Task 6 — App Kotlin: barra prominente
- [ ] `ForgePanels.kt`: barra più alta + etichetta stato (usa `display.*`).
- Verifica: build/manuale.

## Task 7 — Verifica e2e + HANDOFF
- [ ] `v110` + `v103` + `v107` + suite dei test verdi; live HTTP; CRLF check.
- [ ] Aggiornare `.agent/HANDOFF.md`.
