"""Mid-run steering + abort inboxes (JAG-127b / JAG-129A).

A message the user types while a turn is still streaming (or a queued message the
app flushes) is queued here and injected as a user message at the next loop
boundary — the modern-IDE "steer" behaviour, with no second turn and no second SSE
stream. Abort is separate: steer redirects, abort stops; the loop checks the flag
on every iteration.

Extracted from ``server.py`` (JAG-375). Stdlib only.
"""
import threading

# JAG-127b: mid-run steering. A message the user types while a turn is still
# streaming (or a queued message the app flushes) is dropped here and injected
# as a user message at the next loop boundary — the modern-IDE "steer" behaviour,
# with no second turn and no second SSE stream.
STEER_INBOX = {}
_steer_lock = threading.Lock()


def push_steer(sess_id, text):
    """Queue a steering message for a running session. Returns the new depth."""
    text = str(text or "").strip()
    if not sess_id or not text:
        return 0
    with _steer_lock:
        q = STEER_INBOX.setdefault(sess_id, [])
        q.append(text)
        return len(q)


def drain_steer(sess_id):
    """Pop all steering messages for a session (called per loop iteration)."""
    with _steer_lock:
        # JAG-302: pop the key instead of re-inserting an empty list — the old
        # `STEER_INBOX[sess_id] = []` left a permanent empty entry for every
        # session that ever ran a turn (an unbounded dict).
        return STEER_INBOX.pop(sess_id, [])


def has_steer(sess_id):
    """JAG-129A: True when there is at least one steering message queued."""
    with _steer_lock:
        return bool(STEER_INBOX.get(sess_id))


# JAG-129A: abort of an in-flight chat turn (distinct from steer: steer
# redirects, abort stops). The loop checks the flag on every iteration.
ABORT_INBOX = set()
_abort_lock = threading.Lock()


def push_abort(sess_id):
    if not sess_id:
        return False
    with _abort_lock:
        ABORT_INBOX.add(sess_id)
    return True


def _is_aborted(sess_id):
    with _abort_lock:
        return sess_id in ABORT_INBOX


def clear_abort(sess_id):
    with _abort_lock:
        ABORT_INBOX.discard(sess_id)

