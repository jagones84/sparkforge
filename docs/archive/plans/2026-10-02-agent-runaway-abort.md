# Piano — JAG-111 run agent che non si blocca + stop efficace (TDD)

Spec: `docs/specs/2026-10-02-agent-runaway-abort-design.md`
Esecuzione inline, un commit per task. Test: `tests/v111_agent_abort_runaway.py` +
regressione (v110, v107, v099, v102, v103, v104, v074).

## Task 1 — Spec + piano
- [x] spec + piano.

## Task 2 — Test TDD (devono fallire)
- [ ] `tests/v111_agent_abort_runaway.py`: R1, R2, A1, A1b, A2, A2b, A3, M1.
- Verifica: falliscono / crash (attributi mancanti).

## Task 3 — Engine stream: guardia + cap
- [ ] `_RepetitionGuard`, `_completion_body`, `MAX_TOKENS`, `REPEAT_GUARD`.
- [ ] `_router_stream(guard=)` + `stream_with_fallback(guard=)`.
- Verifica: R1, R2, M1 verdi.

## Task 4 — Abort reale nel loop agent
- [ ] `agent_run(run_state=)`: registra run, `agent.start` con `run`, checkpoint, abort.
- [ ] `agent_stream_gen`: run_state + abort su disconnessione.
- Verifica: A1, A2, A3 verdi; `py_compile` ok.

## Task 5 — WebUI FEED
- [ ] handler `agent.aborted` / `model.runaway`.

## Task 6 — Verifica e2e + HANDOFF
- [ ] v111 + regressione verde; live: abort di una run reale; HANDOFF.
