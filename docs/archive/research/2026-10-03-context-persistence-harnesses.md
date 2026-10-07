# Context persistence between agent turns: how harnesses store the transcript, count tokens, and compact (research)

Date: 2026-10-03 · Scope: Claude Code, OpenHands, Aider, Codex CLI (+ Cursor note).
Method: primary sources only (official docs / blog / repo). Unconfirmed claims labeled.
Max 4 sources; source list at bottom.

## 0) The shared model
- LLM APIs are stateless: the harness re-sends the accumulated conversation on every
  turn. "Every time you send a new message to an existing conversation, the conversation
  history is included as part of the prompt for the new turn" [S3].
- The transcript is a message list of typed content blocks: text, `tool_use` (name+input),
  `tool_result`, and reasoning/`thinking` blocks [S1]. Harnesses persist all of them,
  not just visible text.
- Two independent budgets must be respected: (a) the model context window, (b) cost —
  so harnesses avoid replaying everything verbatim and compact instead.

## 1) Claude Code / Anthropic API
- Persistence: the client keeps the *full, unmodified* history locally; server-side
  "context editing" rewrites what the model sees *after* upload, so the client never has
  to sync its local copy [S1]. Reasoning: `thinking` blocks are stored, and a
  `keep` policy decides whether all previous thinking or only the latest turn survives [S1].
- Token counting: official `count_tokens` endpoint for exact counts [S1]. The CLI adds a
  cheap estimate: `chars/4` (JSON ratio 2; images ~2000 tok) times a 4/3 safety margin,
  blended with exact `usage` from the last assistant message (hybrid) — per secondary
  reverse-engineering, not confirmed from a first-party page.
- Compaction cascade (cheap→expensive) with server or SDK variants [S1]:
  - `clear_tool_uses` / microcompact: replace old `tool_result` with a placeholder, keep
    recent ones.
  - `clear_thinking`: drop stale reasoning blocks.
  - full summarization: LLM summarizes history, replaced by one summary message;
    triggered at a token threshold or reactively on overflow [S1].
- Key point: compaction is applied *before* the prompt reaches the model; edits are
  lossy and must preserve user intent, decisions, and corrections.

## 2) OpenHands (Software Agent SDK)
- Event-sourced: state is an append-only list of typed events (actions, observations,
  condensation). The agent is stateless and derives its prompt from the event history [S2].
- `View` = the event slice formatted for the LLM; `ConversationMemory` formats messages;
  `Condenser` compresses [S2].
- `LLMSummarizingCondenser`: `should_condense()` checks a threshold; then it keeps head+
  tail events, forgets (summarizes) the middle, and emits a `Condensation` event carrying
  `forgotten_event_ids` + the summary. NoOp and Pipeline (chained) condensers also exist [S2].
- On overflow the agent emits a `CondensationRequest` event rather than crashing the loop [S2].

## 3) Codex CLI (OpenAI harness)
- Agent loop: user input → prompt → inference → optional `tool_call` → append output →
  re-query; a turn ends only on an assistant message. Earlier turns' messages and tool
  calls are replayed in each new prompt [S3].
- Compaction = summarize-and-replace ("a work handoff memo" replaces the raw history).
  Two paths: (a) local — client calls any provider's LLM to summarize; (b) remote —
  OpenAI's `/responses/compact` endpoint returns a list of items (incl. a special
  compaction item) that replace the prior input, freeing the window [S3].
- Practical caps: default input cap ~272K, ~258K usable (~5% headroom reserved); UI
  commands `/compact`, `/clear`, `/new`, plus auto-compaction [S3].

## 4) Aider
- No full-transcript replay: the prompt = files explicitly "added to the chat" + a
  repository map. Commits each edit to git (revert = context reset) [S4].
- Repo map: tree-sitter builds an AST-derived symbol map (classes/functions/signatures),
  graph-ranked to keep the most relevant parts, sized to a token budget
  (`--map-tokens`; default 1024 per secondary sources — not confirmed first-party) [S4].
- Token accounting: uses the selected model's tokenizer; `whole`/`diff`/`udiff` edit
  formats trade tokens for reliability. Chat history is kept but expected to be short.

## 5) Cursor
- No first-party primary source read within this budget → persistence/compaction
  mechanism NOT confirmed. (Not fabricated.)

## Sources
- [S1] Anthropic — Context editing: https://platform.claude.com/docs/en/build-with-claude/context-editing
      (+ count_tokens: https://platform.claude.com/docs/en/build-with-claude/token-counting)
- [S2] OpenHands SDK — Condenser: https://docs.openhands.dev/sdk/arch/condenser.md
      (Agent loop: https://docs.openhands.dev/sdk/arch/agent.md)
- [S3] OpenAI — Unrolling the Codex agent loop: https://openai.com/index/unrolling-the-codex-agent-loop/
      (Responses API compaction: https://openai.com/index/equip-responses-api-computer-environment/)
- [S4] Aider — Repository map: https://aider.chat/2023/10/22/repomap.html
