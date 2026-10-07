#!/usr/bin/env python3
"""JAG-172 backfill — rebuild `messages` for sessions created BEFORE the agentic
history was persisted.

`chat_once` used to store only the final assistant reply, so a long session's
tool cards + harness injections never re-entered the prompt and the ctx meter
read a tiny fraction of the model window (session test: 15 msgs / 5 KB vs 161
tool cards -> a genuinely full context showed as 2-3%).

This migration rebuilds the transcript chronologically from the existing pieces
(all carry `ts`): the stored replies (`messages`, kept untouched) interleaved
with a synthesised assistant tool-call message per `tool_cards` entry and a user
message per non-system `injects` entry, each flagged `internal`. The UI keeps
rendering these from tool_cards/injects (no duplicate bubbles); the model now
sees its own past work and the meter shows true saturation.

Idempotent: a session that already has `internal` messages is skipped. Every
touched file is backed up next to it as `<sid>.json.bak-<ts>`.

Usage:
  python3 scripts/backfill_internal_history.py [--dry-run] [--session <sid>]
"""
import argparse
import json
import os
import shutil
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SESS_DIR = os.path.join(REPO, "data", "sessions")


def _action(card):
    try:
        args = json.loads(card.get("args") or "{}")
    except Exception:  # noqa: BLE001
        args = {}
    return json.dumps({"action": "tool", "tool": card.get("tool"), "args": args},
                      ensure_ascii=False)


def rebuild(sess):
    """Return (new_messages, reason) or (None, reason) when nothing to do."""
    msgs = list(sess.get("messages") or [])
    if any(m.get("internal") for m in msgs):
        return None, "already migrated"
    cards = sess.get("tool_cards") or []
    injs = [r for r in (sess.get("injects") or []) if r.get("kind") != "system"]
    if not cards and not injs:
        return None, "nothing to backfill"
    items = []
    for m in msgs:
        items.append((float(m.get("ts") or 0.0), 0, m, None))
    for c in cards:
        rec = {"role": "assistant", "content": _action(c), "internal": True,
               "node": c.get("node"), "ts": c.get("ts")}
        if c.get("think"):
            rec["reasoning"] = c["think"]
        items.append((float(c.get("ts") or 0.0), 1, rec, c))
    for r in injs:
        items.append((float(r.get("ts") or 0.0), 1, {
            "role": "user", "content": r.get("text") or "", "internal": True,
            "node": r.get("node"), "ts": r.get("ts")}, r))
    items.sort(key=lambda it: (it[0], it[1]))
    out = []
    for idx, (_ts, _tie, payload, owner) in enumerate(items):
        if owner is not None:
            # re-anchor the card/inject to the index of its synthesised message,
            # so the UI interleaves it where it really happened (the old `after`
            # pointed into the pre-migration short transcript and would bunch
            # every card near the top).
            owner["after"] = idx
        out.append(payload)
    return out, "rebuilt %d -> %d messages" % (len(msgs), len(items))


def reanchor(sess):
    """Already-migrated session: point each card/inject `after` at the index of
    its synthesised internal message so the UI interleaves it correctly.
    Returns (changed, reason)."""
    msgs = sess.get("messages") or []
    if not any(m.get("internal") for m in msgs):
        return False, "not migrated"
    idx = {}
    for i, m in enumerate(msgs):
        if m.get("internal"):
            idx[(m.get("role"), repr(m.get("ts")), m.get("content"))] = i
    changed = 0
    for c in sess.get("tool_cards") or []:
        i = idx.get(("assistant", repr(c.get("ts")), _action(c)))
        if i is not None and c.get("after") != i:
            c["after"] = i
            changed += 1
    for r in sess.get("injects") or []:
        if r.get("kind") == "system":
            continue
        i = idx.get(("user", repr(r.get("ts")), r.get("text") or ""))
        if i is not None and r.get("after") != i:
            r["after"] = i
            changed += 1
    return changed > 0, "re-anchored %d cards/injects" % changed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--session")
    a = ap.parse_args()
    if not os.path.isdir(SESS_DIR):
        print("no sessions dir: %s" % SESS_DIR)
        return 1
    files = sorted(f for f in os.listdir(SESS_DIR) if f.endswith(".json"))
    if a.session:
        files = [a.session + ".json"]
    stamp = time.strftime("%Y%m%d-%H%M%S")
    done = skipped = 0
    for fn in files:
        p = os.path.join(SESS_DIR, fn)
        try:
            with open(p, encoding="utf-8") as fh:
                sess = json.load(fh)
        except Exception as e:  # noqa: BLE001
            print("SKIP %s (unreadable: %s)" % (fn, e))
            continue
        new_msgs, why = rebuild(sess)
        sid = sess.get("id") or fn[:-5]
        if new_msgs is not None:
            sess["messages"] = new_msgs
        else:
            changed, why2 = reanchor(sess)
            if not changed:
                skipped += 1
                print("SKIP     %-14s %s" % (sid, why))
                continue
            why = why2
        if not isinstance(sess.get("messages"), list):
            print("SKIP     %-14s refusing to write non-list messages" % sid)
            continue
        print("%s %-14s %s" % ("BACKFILL" if not a.dry_run else "WOULD   ",
                               sid, why))
        done += 1
        if a.dry_run:
            continue
        shutil.copy2(p, p + ".bak-" + stamp)
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(sess, fh, ensure_ascii=False)
        os.replace(tmp, p)
    print("--- %s: %d backfilled, %d skipped ---" %
          ("DRY-RUN" if a.dry_run else "DONE", done, skipped))
    return 0


if __name__ == "__main__":
    sys.exit(main())
