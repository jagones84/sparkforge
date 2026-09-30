#!/usr/bin/env python3
# JAG-61: drain every pending approval (headless E2E auto-approver).
import json
import urllib.request

BASE = "http://127.0.0.1:8790"
TOKEN = "REDACTED-COMPROMISED-TOKEN"


def req(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(
        BASE + path, data=data, method=method,
        headers={"Authorization": "Bearer " + TOKEN,
                 "Content-Type": "application/json"})
    with urllib.request.urlopen(r, timeout=10) as resp:
        return json.loads(resp.read().decode())


def main():
    pend = req("GET", "/api/approvals?status=pending&limit=50").get("approvals", [])
    n = 0
    for ap in pend:
        rid = ap.get("id")
        cmd = (ap.get("args") or {}).get("command", "")
        try:
            req("POST", "/api/approvals/" + rid, {"decision": "approve", "by": "e2e-auto"})
            n += 1
            print("APPROVED %s :: %s" % (rid, cmd[:120]))
        except Exception as e:  # noqa: BLE001
            print("ERR %s %s" % (rid, e))
    print("approved %d of %d pending" % (n, len(pend)))


if __name__ == "__main__":
    main()
