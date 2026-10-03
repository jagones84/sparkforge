# In-chat Task/TODO tree UX in modern coding agents (research)

Date: 2026-10-03 · Scope: how coding agents render TODO/plan state and harness→LLM
injections inside the chat UI. Method: primary sources only (official docs/repo/site).
Facts not found are marked "not confirmed" (no fabrication). Source list at bottom.

## 1) Claude Code (terminal / Agent SDK)
- Task tracking is a written todo list updated in place; "You see each change in the
  message stream as a structured tool call" [S1].
- Lifecycle per item: pending → in_progress → completed → removed (`status: "deleted"`
  in a `TaskUpdate` call) [S1].
- Current tools are the four Task tools (`TaskCreate`, `TaskGet`, `TaskList`,
  `TaskUpdate`); `TodoWrite` is the legacy single-tool form used when
  `CLAUDE_CODE_ENABLE_TASKS=0` (default on Claude 3.x / Opus 4–4.7 / Sonnet 4–4.6 /
  Haiku 4.5) [S1].
- Visibility is opt-in per session: on models without the tools "you see no `tool_use`
  blocks for them in the message stream" — i.e. harness tool calls can render as nothing [S1].
- Per-tool collapsibility in the TUI (e.g. a "ctrl+r to expand" hint under a tool
  result) is observed in real sessions but is NOT stated in the primary docs read →
  not confirmed from S1.

## 2) Cline (VS Code) / Roo
- Two-phase model: Plan mode (research, no edits) then Act mode (executes; each file
  edit and terminal command requires approval) [S2].
- In-chat change rendering (Background Edit): "Changes appear as collapsible diff blocks
  in the chat panel"; per-file expand/collapse by clicking the file header; "Real-time
  streaming as changes appear line-by-line"; additions green / deletions red; file-action
  icons plus (+/-) stats [S2].
- So Cline's expand/collapse unit is the per-file diff block, not a nested per-step tree [S2].
- Roo Code is a Cline fork; its specific chat-tree UI is not covered by the primary
  sources used here → not confirmed.

## 3) openclaw / hermes
- Hermes (Nous Research, repo README): "Full TUI with multiline editing, slash-command
  autocomplete, conversation history, interrupt-and-redirect, and streaming tool
  output" [S3].
- README also documents subagents, RPC tool calls, cron, persistent memory/skills, and
  `hermes claw migrate` from OpenClaw [S3]. It does NOT document an in-chat persistent
  plan/todo tree → not confirmed from a primary source in budget.
- OpenClaw's plan/todo chat rendering: no primary source read here → not confirmed.

## 4) Cursor / Devin / Aider
- Cursor (official site): the agent UI shows an in-chat task list ("3 Tasks: Add
  multiplayer mode to useAppStore.ts, Create a new MissionControlView.tsx component,
  Update AppManager.tsx") plus progress steps ("Explored 12 files, 4 searches",
  "Worked for 14m 22s") and a "Plan, search, build anything" input; Plan mode gates
  edits behind approval [S4].
- Aider: no todo/plan-tree UI found in a primary source within budget (CLI diff-centric)
  → not confirmed.
- Devin: no primary source read here → not confirmed.

## 5) Common pattern
- Planning is a first-class, approvable phase before any edits (Cline plan/act, Cursor
  plan, Claude Code plan) [S2][S4].
- A live task list updated in place with per-item status (Claude todo lifecycle; Cursor
  "3 Tasks") [S1][S4].
- Progressive disclosure of tool/step output: collapsible per-step/per-file blocks, with
  diffs and stats expanding on demand (Cline collapsible diffs; Claude expandable tool
  results) [S2][S1].
- Internal harness activity surfaces as structured events, but visibility is a policy:
  when task tools aren't enabled there are no `tool_use` blocks at all [S1]. Explicit
  statements about hiding vs showing prompt-injected/system messages were not found in
  the sources read → gap.

## Sources
- [S1] Claude Code — Track todos: https://code.claude.com/docs/en/agent-sdk/todo-tracking
- [S2] Cline — Background Edit (collapsible diffs) + Tasks/Plan-Act:
  https://docs.cline.bot/features/background-edit
- [S3] Hermes Agent — README (NousResearch/hermes-agent):
  https://github.com/NousResearch/hermes-agent
- [S4] Cursor — official product site (agent task list UI): https://cursor.com/
