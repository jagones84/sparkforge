# System prompt re-send & prefix caching — how other harnesses do it

Date: 2026-10-04 · Scope: why the full system prompt is sent on every user
message, whether it can be avoided, and what the real optimization is.
Ticket: JAG-271.

## Question
"È giusto che tutto il system prompt venga ridato ad ogni messaggio dell'utente?
No, devi cambiare questa cosa. Vedi come fanno le altre harness."

## Finding 1 — it CANNOT be avoided (protocol), it CAN be made free (caching)
Every OpenAI-compatible and Anthropic chat API is **stateless**: the server keeps
no conversation for you, so each request MUST carry the system prompt + the whole
history + the new message. There is no "send it once" mode. So the observation is
correct but the conclusion changes: the fix is not to stop sending it, it is to
make re-processing it **free** via **prefix (KV) caching**.

- **What is cached:** the model's *working state* (KV tensors) after prefill, not
  the text. Reuse is **prefix-only**: the server matches from position 0 and the
  **first differing byte kills everything after that point**.
- **Anthropic:** explicit `cache_control` breakpoints (up to 4), 90% cheaper reads.
- **OpenAI:** automatic, prefix ≥1024 tokens, matched in 128-token blocks.
- **llama.cpp (our router):** LCP similarity + context checkpoints (default every
  ~8192 tokens); it restores the cached prefix and only evaluates the new tail.

## Finding 2 — the IRON RULE: stable first, dynamic last
Everything left of the first mismatch is reused; everything right is recomputed.
Therefore: tools/system instructions (stable) → session-stable context → history
(grows, prefix stable) → **new message (always last)**.

The #1 cache killer is **content that changes near the START** — a timestamp, a
random id, a version/attribution header. The Claude Code ↔ local-LLM incident:
Claude Code injects an attribution header (with a timestamp) at the front of the
system prompt; against a local llama.cpp backend this invalidated the prefix on
**every** request and made inference ~90% slower. Fix: omit it
(`CLAUDE_CODE_ATTRIBUTION_HEADER=0`).

## Finding 3 — what we applied in SparkForge
Our prompt is a list of ordered sections (`prompt.py:SECTIONS`). We:
1. **Reordered to cache-safe**: every `static` section first, then the dynamic
   ones, and pushed `state` (the live task list — the only section that changes
   often) to the very end. `task-policy` stays immediately above `state` (JAG-266:
   the rule travels with the list).
2. **Verified the front is byte-stable**: `self_summary()` is static text (paths +
   service hint) — no timestamp, no session id, no live list in the early sections.
3. **Reduced duplication**: the harness nudge now NAMES the exact open steps
   (`_open_todo_brief`) instead of a generic "mark the next step"; the model no
   longer re-derives the plan, and the list is not restated in prose elsewhere.

Result: the bytes before `state` are identical turn-to-turn, so llama.cpp reuses
the KV from the previous request and only evaluates the new tail (the live list +
the new message). The prompt is still *sent* (protocol), but not *recomputed*.

## Sources
- Prompt caching + KV cache for long-running agents — zylos.ai/research/2026-03-27-prompt-caching-kv-cache-optimization-long-running-ai-agents/
- Static-first / dynamic-last architecture patterns — zylos.ai/en/research/2026-02-24-prompt-caching-ai-agents-architecture/
- Claude Code + local LLM KV-cache reuse failure (LCP/checkpoint) — cnblogs.com/DarkAthena/articles/19976394
- Hidden prompt-cache killer: attribution header at the prompt front — mykolaaleksandrov.dev/posts/2026/06/claude-code-llamacpp-prompt-cache-fix/
- KV cache in local AI (prefix invalidation is fatal at long context) — thinksmart.life/research/posts/kv-cache-local-inference/
- Prompt caching doesn't cache prompts (prefix-match rule) — karanbansal.in/blog/prompt-caching/
- Structuring a prompt for cache hits — blog.jatinbansal.com/ai-engineering/prompt-caching/
