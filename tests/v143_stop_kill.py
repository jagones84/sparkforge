#!/usr/bin/env python3
"""v0.9.38 acceptance — Stop uccide la generazione in corso (JAG-129D)."""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


import server  # noqa: E402

srv = open(os.path.join(REPO, "server.py"), encoding="utf-8", errors="replace").read()
check("V1 _router_stream accepts cancel", "cancel=None" in srv, "")
check("V3 chat wires cancel callback", "cancel=_abort_now" in srv and "_abort_now" in srv, "")
check("V4 abort short-circuit + user_abort",
      "chat.interrupted" in srv and "user_abort" in srv, "")


class _FakeResp:
    def __init__(self, lines):
        self._lines = iter(lines)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def __iter__(self):
        return self

    def __next__(self):
        return next(self._lines)


def _fake_open(req, timeout):
    chunks = []
    for i in range(5):
        chunks.append(('data: {"choices":[{"delta":{"content":"tok%d"}}]}\n' % i).encode("utf-8"))
    chunks.append(b'data: [DONE]\n')
    return _FakeResp(chunks)


_orig_open = server._open_with_retry
_orig_idle = server._set_read_idle
server._open_with_retry = _fake_open
server._set_read_idle = lambda resp, t: None
try:
    n = {"c": 0}

    def cancel():
        n["c"] += 1
        return n["c"] >= 2

    ans, _think = server._router_stream([{"role": "user", "content": "x"}], "m",
                                        lambda ch, t: None, cancel=cancel)
    check("V2 cancel stops the stream early", "tok0" in ans and "tok4" not in ans, repr(ans))
finally:
    server._open_with_retry = _orig_open
    server._set_read_idle = _orig_idle

total = len(results)
print("\n==== %d/%d checks passed ====" % (sum(results), total))
sys.exit(0 if all(results) else 1)