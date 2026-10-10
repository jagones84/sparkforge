"""Attention feed — "what needs me" (Paperclip-style).

Paperclip funnels everything that needs a human decision into ONE inbox, typed by
source (`approval`, `failed_run`, `blocker_attention`, `budget_alert`, ...) and
ranked by severity (critical/high/medium/low). Orbit mirrors that with the
primitives Longrun already has:

  * approval        — a tool waiting on the HITL gate (`approvals.list_all`)
  * failed_run      — a dispatched job that ended in error
  * blocked_session — a session stopped with steps still open
  * budget_alert    — a session whose context window is nearly exhausted

Nothing here invents state: every item is derived from a live app module.
"""
import time

SEVERITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}
SOURCES = ("approval", "failed_run", "blocked_session", "budget_alert")
BUDGET_WARN_PCT = 90
BUDGET_CRIT_PCT = 98


def _mods():
    from longrun import approvals, server, taskgraph
    return approvals, server, taskgraph


class AttentionFeed:
    """Builds the single ranked inbox of things that need a human."""

    def __init__(self, registry, jobs_provider=None):
        self.registry = registry
        self.jobs_provider = jobs_provider or (lambda: [])

    def snapshot(self, sessions=None):
        approvals, server, taskgraph = _mods()
        items = []
        items += self._approvals(approvals)
        items += self._failed_runs()
        if sessions is None:
            sessions = self.registry.list().get("sessions", [])
        for s in sessions:
            items += self._open_steps(taskgraph, s)
            items += self._budget(server, s)
        items.sort(key=lambda i: (SEVERITY_RANK.get(i["severity"], 9), -(i.get("ts") or 0)))
        by = {}
        for it in items:
            by[it["severity"]] = by.get(it["severity"], 0) + 1
        return {"items": items, "count": len(items), "by_severity": by,
                "sources": list(SOURCES), "ts": round(time.time(), 3)}

    def _approvals(self, approvals):
        out = []
        try:
            for a in approvals.list_all("pending", 100):
                out.append({
                    "id": "approval:" + str(a.get("id")),
                    "kind": "approval",
                    "severity": "high",
                    "title": "Approval needed — " + str(a.get("tool") or "tool"),
                    "detail": a.get("summary") or "",
                    "session": a.get("run_id"),
                    "ts": a.get("ts"),
                    "actionable": True,
                    "ref": {"approval": a.get("id"), "tool": a.get("tool")},
                })
        except Exception:  # noqa: BLE001
            pass
        return out

    def _failed_runs(self):
        out = []
        try:
            jobs = self.jobs_provider() or []
        except Exception:  # noqa: BLE001
            jobs = []
        for j in jobs:
            if j.get("state") == "error":
                out.append({
                    "id": "failed:" + str(j.get("job")),
                    "kind": "failed_run",
                    "severity": "high",
                    "title": "Dispatch failed — " + str(j.get("session") or "")[:8],
                    "detail": j.get("error") or j.get("goal") or "",
                    "session": j.get("session"),
                    "ts": j.get("ended") or j.get("started"),
                    "actionable": False,
                    "ref": {"job": j.get("job")},
                })
        return out

    def _open_steps(self, taskgraph, s):
        if s.get("running"):
            return []
        try:
            g = taskgraph.load(s.get("id")) or {}
        except Exception:  # noqa: BLE001
            return []
        open_n = len([n for n in (g.get("nodes") or [])
                      if n.get("status") in ("todo", "doing")])
        if not open_n:
            return []
        return [{
            "id": "opentodos:" + str(s.get("id")),
            "kind": "blocked_session",
            "severity": "medium",
            "title": str(s.get("title")) + " — " + str(open_n) + " open step(s)",
            "detail": "stopped with work still open — resume or close it",
            "session": s.get("id"),
            "ts": s.get("updated"),
            "actionable": False,
            "ref": {"open": open_n},
        }]

    def _budget(self, server, s):
        try:
            # JAG-258/300: measure against the SESSION's own model window, not the
            # default budget — else a small-window session reads as nearly empty and
            # its budget alert never fires. Mirrors context_detail's own usage.
            model = server.resolve_ctx_model(s)
            cu = server.context_usage(s.get("id"), model=model) or {}
        except Exception:  # noqa: BLE001
            return []
        pct = cu.get("pct") or 0
        if pct < BUDGET_WARN_PCT:
            return []
        return [{
            "id": "budget:" + str(s.get("id")),
            "kind": "budget_alert",
            "severity": "critical" if pct >= BUDGET_CRIT_PCT else "high",
            "title": str(s.get("title")) + " — context " + str(pct) + "%",
            "detail": "context window nearly full — compact the session",
            "session": s.get("id"),
            "ts": s.get("updated"),
            "actionable": False,
            "ref": {"pct": pct},
        }]

    @staticmethod
    def board(sessions, items):
        """Group sessions into Working / Needs you / Idle from the attention items."""
        needs = {i.get("session") for i in items if i.get("session")}
        cols = {"working": [], "needs": [], "idle": []}
        for s in sessions:
            if s.get("running"):
                cols["working"].append(s)
            elif s.get("id") in needs:
                cols["needs"].append(s)
            else:
                cols["idle"].append(s)
        return cols
