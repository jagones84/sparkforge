#!/usr/bin/env python3
import re
import sys

p = sys.argv[1] if len(sys.argv) > 1 else "/home/jagones/ui2.xml"
data = open(p, encoding="utf-8", errors="replace").read()
for node in re.findall(r"<node[^>]*?/?>", data):
    def g(k):
        m = re.search(k + r'="([^"]*)"', node)
        return m.group(1) if m else ""
    t, d, b, c, cl = g("text"), g("content-desc"), g("bounds"), g("clickable"), g("class")
    if t or d or c == "true":
        print("%-28s click=%-5s %-16s text=%r desc=%r" % (b, c, cl.split(".")[-1], t, d))
