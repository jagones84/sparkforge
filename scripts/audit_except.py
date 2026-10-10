#!/usr/bin/env python3
"""Audit silent exception handlers: list `except ...: pass/continue/return`.

A handler whose entire body is `pass`, `continue` or `return None` swallows the
error. Some are intentional (best-effort bookkeeping), but a swallow on a path
that should produce a value hides a real bug. This prints every site with the
guarded call so we can classify by hand.
"""
import ast
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(REPO, "src", "longrun")


def is_swallow(body):
    if len(body) != 1:
        return None
    st = body[0]
    if isinstance(st, ast.Pass):
        return "pass"
    if isinstance(st, ast.Continue):
        return "continue"
    if isinstance(st, ast.Break):
        return "break"
    if isinstance(st, ast.Return) and (st.value is None or
                                       (isinstance(st.value, ast.Constant) and st.value.value is None)):
        return "return None"
    return None


def guarded_name(node):
    """Best-effort name of the first call inside the try body."""
    for st in ast.walk(node):
        if isinstance(st, ast.Call):
            f = st.func
            if isinstance(f, ast.Attribute):
                return f.attr
            if isinstance(f, ast.Name):
                return f.id
    return "-"


total = 0
by_mod = {}
for fn in sorted(os.listdir(SRC)):
    if not fn.endswith(".py"):
        continue
    path = os.path.join(SRC, fn)
    try:
        tree = ast.parse(open(path, encoding="utf-8").read(), filename=path)
    except SyntaxError:
        continue
    sites = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        for h in node.handlers:
            kind = is_swallow(h.body)
            if kind:
                sites.append((h.lineno, kind, guarded_name(node)))
    if sites:
        by_mod[fn] = sites
        total += len(sites)

print("modules=%d silent_handlers=%d" % (len(by_mod), total))
for fn, sites in sorted(by_mod.items(), key=lambda kv: -len(kv[1])):
    print("%-24s %d" % (fn, len(sites)))
for fn in sys.argv[1:]:
    key = fn if fn.endswith(".py") else fn + ".py"
    for ln, kind, g in by_mod.get(key, []):
        print("  %s:%d %s (guarded: %s)" % (key, ln, kind, g))
