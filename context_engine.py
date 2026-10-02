#!/usr/bin/env python3
"""SparkForge context engineering — v0.3 compaction / token budget / retrieval.

Builds the LLM message list for chat from a session transcript under a token
budget:

  1. the system prompt always stays (uncompacted);
  2. the most recent `keep_recent` messages stay verbatim;
  3. older messages are *compacted* (extractive merge: role + truncated first
     line) into a single synthetic `system` summary block;
  4. relevant memories are *retrieved* (semantic or keyword via memory.search)
     and injected as a separate system block, so answers can use knowledge from
     previous sessions.

`preview()` runs the same pipeline without calling the model — it is what
`POST /api/context/preview` and the `sparkforge_context` MCP tool expose as
evidence (message counts, estimated tokens in/out, retrieved memory hits).
"""

import os

DEFAULT_BUDGET = int(os.environ.get("SPARKFORGE_CONTEXT_BUDGET", "32768"))
DEFAULT_KEEP_RECENT = int(os.environ.get("SPARKFORGE_CONTEXT_KEEP_RECENT", "8"))
RETRIEVAL_TOP_K = int(os.environ.get("SPARKFORGE_CONTEXT_RETRIEVAL_K", "3"))


def count_tokens(text):
    """Same ~4 chars/token proxy the harness uses for accounting."""
    return max(1, len(text) // 4) if text else 0


def _msgs_tokens(msgs):
    return sum(count_tokens(m.get("content", "")) for m in msgs)


def compact(messages, budget_tokens, keep_recent=DEFAULT_KEEP_RECENT, summarizer=None):
    """Compact a transcript under a token budget.

    Returns (msgs, stats). Keeps the newest `keep_recent` messages verbatim;
    older ones are merged into one summary message. If even that is over budget,
    the kept window is shrunk.

    JAG-103: when `summarizer(old_messages) -> str|None` is given, the older turns
    are summarized BY THE MODEL (a faithful prose summary) instead of the local
    extractive merge. A None/empty return (router down, timeout) falls back to the
    extractive path, so compaction can never stall a turn.
    """
    stats = {"input_messages": len(messages),
             "input_tokens": _msgs_tokens(messages),
             "compacted": 0, "kept": 0, "dropped": 0, "summary": None}
    if not messages:
        return [], stats
    if stats["input_tokens"] <= budget_tokens:
        stats["kept"] = len(messages)
        return list(messages), stats
    cut = max(0, len(messages) - keep_recent)
    old, recent = messages[:cut], messages[cut:]
    if old:
        summary = None
        if summarizer is not None:
            try:
                summary = summarizer(old)
            except Exception:  # noqa: BLE001 — fall back to the local merge
                summary = None
        if summary:
            stats["summary"] = "llm"
        else:
            summary_lines = []
            for m in old:
                role = m.get("role", "?")
                content = (m.get("content") or "").strip().replace("\n", " ")
                if content:
                    summary_lines.append("%s: %s" % (role, content[:160]))
            summary = "Earlier conversation (compacted):\n" + "\n".join(summary_lines[-40:])
            stats["summary"] = "extractive"
        stats["compacted"] = len(old)
        msgs = [{"role": "system", "content": summary}]
    else:
        msgs = []
    for m in recent:
        msgs.append(m)
        stats["kept"] += 1
    out_tokens = _msgs_tokens(msgs)
    # If the kept window alone is still over budget, shrink it further.
    if out_tokens > budget_tokens:
        while recent and out_tokens > budget_tokens:
            dropped = recent.pop(0)
            stats["dropped"] += 1
            stats["kept"] -= 1
            msgs = ([{"role": "system", "content": msgs[0]["content"]}] if old else []) + recent
            out_tokens = _msgs_tokens(msgs)
    stats["output_tokens"] = out_tokens
    return msgs, stats


def retrieve(query_text, top_k=RETRIEVAL_TOP_K, semantic=True):
    """Pull relevant memories for context injection (score >= 0.15)."""
    try:
        import memory
        if not query_text:
            return []
        hits = memory.search(query_text, None, top_k, semantic)
        out = [{"score": round(s, 3), "kind": r.get("kind"),
                "ts": r.get("ts"), "content": (r.get("content") or "")[:300]}
               for s, r in hits]
        # The vector index is rebuilt periodically; records written since the
        # last rebuild are invisible to it, so merge a keyword pass too.
        if semantic:
            seen = {(h["kind"], h["ts"]) for h in out}
            for s, r in memory.search(query_text, None, top_k, False):
                key = (r.get("kind"), r.get("ts"))
                if key not in seen:
                    out.append({"score": round(s, 3), "kind": r.get("kind"),
                                "ts": r.get("ts"), "content": (r.get("content") or "")[:300]})
        out.sort(key=lambda h: h["score"], reverse=True)
        return out[:top_k]
    except Exception:
        return []


def build(system_prompt, messages, message=None, budget_tokens=DEFAULT_BUDGET,
          keep_recent=DEFAULT_KEEP_RECENT, retrieve_memory=True):
    """Full pipeline: compaction + retrieval. Returns (msgs, stats).

    `msgs` is ready to send: [system(s)...] + compacted transcript + [user message].
    """
    query = message or (messages[-1].get("content") if messages else "")
    stats = {"budget_tokens": budget_tokens, "keep_recent": keep_recent,
             "retrieval_query": (query or "")[:120]}
    # JAG-99: the system prompt is sent uncompacted and dominates small budgets;
    # compact the transcript against what is LEFT for it, so the TOTAL prompt
    # (system + transcript) stays within `budget_tokens`.
    room = max(1024, budget_tokens - count_tokens(system_prompt))
    msgs, cstats = compact(messages, room, keep_recent)
    stats.update({"compaction": cstats})
    if retrieve_memory and query:
        hits = retrieve(query)
        stats["retrieved_memories"] = len(hits)
        if hits:
            mem_block = "Relevant memories from previous sessions:\n" + "\n".join(
                "- (%s, score %.2f) %s" % (h["kind"], h["score"], h["content"])
                for h in hits)
            msgs = [{"role": "system", "content": mem_block}] + msgs
    msgs = [{"role": "system", "content": system_prompt}] + msgs
    if message:
        msgs.append({"role": "user", "content": message})
    stats["final_messages"] = len(msgs)
    stats["final_tokens"] = _msgs_tokens(msgs)
    return msgs, stats


def preview(session, message=None, budget_tokens=DEFAULT_BUDGET, keep_recent=DEFAULT_KEEP_RECENT):
    """Dry-run against a harness session dict (no LLM call). Evidence-shaped."""
    import server  # lazy: server imports this module's consumers, not us
    sess = server.load_session(session) if session else None
    if not sess:
        return {"error": "session not found: %s" % session}
    sysp = server.SYSTEM_PROMPT
    msgs, stats = build(sysp, sess.get("messages", []), message,
                        budget_tokens, keep_recent, retrieve_memory=False)
    # retrieval is reported separately so the check can observe memory hits
    hits = retrieve(message or (sess["messages"][-1]["content"] if sess["messages"] else ""))
    stats["retrieval_hits"] = len(hits)
    stats["retrieval_samples"] = [h["content"][:120] for h in hits[:3]]
    stats["session_id"] = sess["id"]
    stats["transcript_messages"] = len(sess.get("messages", []))
    return stats