# Frontier Harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:test-driven-development to implement task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Port the research-grade capabilities identified in the SWE-harness spec + arXiv frontier (PRM verification, governed memory consolidation) into SparkForge, with TDD.

**Architecture:** Two new focused modules: `prm.py` (deterministic process-reward/verification engine with an inefficiency taxonomy) and memory-governance additions to `memory.py` (score / decay / dedupe). Both are pure, unit-testable; both are wired into the existing chat loop and reflection loop.

**Tech Stack:** Python stdlib + existing `memory.py`, `server.py`; standalone test scripts following `tests/vXXX_*.py` convention (exit 0 = pass).

**Frontier rationale (sources):**
- PRM / test-time compute: arxiv 2504.00891 (GenPRM), 2502.10325 (AgentPRM), 2604.16529 (Scaling TTC for Agentic Coding).
- Memory consolidation: arxiv 2605.20616 (Auto-Dreamer), 2607.13591 (Memory as a Controlled Process), 2608.00017 (Memory Reward Inflation), 2609.33013 (Epistemics of Agent Memory).
- Key emergent property: self-improving agents with scored memory suffer **reward inflation** — the stored score drifts upward. Mitigation: scores stay external (harness-set), decayed over time, and deduped.

---

### Task 1: Process Reward / Verification engine (`prm.py`)

**Files:**
- Create: `prm.py`
- Test: `tests/v095_prm.py`

- [ ] Step 1: write failing test `tests/v095_prm.py` asserting `evaluate()` flags repetition, verification-skipped, and reward-inflation-safe scoring.
- [ ] Step 2: run `python3 tests/v095_prm.py` → FAIL (module missing).
- [ ] Step 3: implement `prm.py` (taxonomy + deterministic `evaluate()` + `feedback()`).
- [ ] Step 4: run test → PASS.
- [ ] Step 5: commit `feat(prm): deterministic process-reward verification engine`.

### Task 2: Governed memory consolidation (`memory.py`)

**Files:**
- Modify: `memory.py` (add score to `_render_md`, add `effective_score`, `dedupe`, `governed_query`)
- Test: `tests/v095_memory_governance.py`

- [ ] Step 1: write failing test asserting score persistence, time-decay ordering, dedupe of near-identical lessons.
- [ ] Step 2: run test → FAIL.
- [ ] Step 3: implement governance functions.
- [ ] Step 4: run test → PASS.
- [ ] Step 5: commit `feat(memory): score+decay+dedupe governed recall`.

### Task 3: Wire PRM into the chat loop (`server.py`)

**Files:**
- Modify: `server.py` (JAG-87 verification gate → `prm.evaluate` with injected feedback)

- [ ] Step 1: in `chat_once`, after the loop, call `prm.evaluate`; if issues, append correction feedback to the transcript (bounded).
- [ ] Step 2: run `python3 tests/v080_webui_redesign.py` (regression) + py_compile.
- [ ] Step 3: commit.

### Task 4: Wire governed recall into prompt + reflection (`server.py`)

**Files:**
- Modify: `server.py` (`_system_prompt` uses `memory.governed_query`; `maybe_reflect` stores a harness-set score)

- [ ] Step 1: swap lessons injection to `memory.governed_query(kind="agent.note")`.
- [ ] Step 2: store lesson with an external fixed score (no self-rating).
- [ ] Step 3: run reflection verification script, commit.

### Task 5 (future, documented only): KV-cache prefix lock, AST compaction, transactional sandbox, skill synthesis.

---