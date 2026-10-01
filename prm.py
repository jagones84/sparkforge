#!/usr/bin/env python3
"""SparkForge v0.95 — process reward / verification engine (prm).

A lightweight, inference-time course-corrector for the agent loop. It scores a
trajectory against an INEFFICIENCY TAXONOMY (spec / reasoning / coordination
errors) and renders a compact natural-language correction that the harness
injects back into the transcript — the same mechanism the frontier harnesses
ship as a Process Reward Model (PRM), but the deterministic core here needs no
model call, so it is cheap, safe and unit-testable.

Rationale (arXiv): 2504.00891 (GenPRM), 2502.10325 (AgentPRM),
2604.16529 (Scaling Test-Time Compute for Agentic Coding). The deterministic
rules cover the failure modes that recur in long-horizon coding runs
(repetition, premature "done", verification skipped).
"""

import json

# Inefficiency taxonomy: code -> human label. The deterministic scorer issues a
# subset of these; the full list is the taxonomy a model-guided PRM would use.
TAXONOMY = {
    "step_repetition": "repeated an identical action without progress",
    "verification_skipped": "declared done while task steps are still open",
    "termination_unaware": "kept working after the goal was already met",
    "tool_misuse": "used the wrong tool for the task",
    "information_ignored": "ignored a previous error or tool output",
    "goal_drift": "deviated from the main objective",
}

# Keys ignored when normalising tool args: volatile parameters a small model
# flips between otherwise-identical calls must not defeat repetition detection.
_IGNORED_ARGS = ("timeout_secs", "timeout", "args")

_PER_ISSUE_PENALTY = 0.15


def _norm_args(args):
    """Normalise tool args to a stable string for repetition comparison."""
    if args is None:
        return ""
    if isinstance(args, dict):
        return json.dumps(
            {k: args[k] for k in sorted(args) if k not in _IGNORED_ARGS},
            sort_keys=True, default=str)
    return str(args)


def _sig(step):
    """Canonical signature of a trajectory step (action, tool, normalised args)."""
    return (str(step.get("action")), str(step.get("tool") or ""),
            _norm_args(step.get("args")))


def evaluate(steps, open_nodes=0):
    """Score a trajectory and render correction feedback.

    Args:
        steps: list of dicts, each with action / tool / args (and optionally
            thought, observation).
        open_nodes: how many task-graph nodes are still open at the end.

    Returns dict(score, issues, feedback). score is in [0, 1]; issues is a list
    of {"code", "label"}; feedback is a compact correction string (empty when
    the trajectory is clean).
    """
    steps = steps or []
    issues = []

    # rule 1: step repetition — the same action+tool+args twice in a row.
    for i in range(1, len(steps)):
        if _sig(steps[i]) == _sig(steps[i - 1]):
            issues.append({"code": "step_repetition", "label": TAXONOMY["step_repetition"]})
            break

    # rule 2: verification skipped — finish while plan nodes are still open.
    if steps and open_nodes > 0 and str(steps[-1].get("action")).lower() == "finish":
        issues.append({"code": "verification_skipped",
                       "label": TAXONOMY["verification_skipped"]})

    score = max(0.0, 1.0 - _PER_ISSUE_PENALTY * len(issues))
    return {"score": round(score, 3), "issues": issues,
            "feedback": feedback_text(issues)}


def feedback_text(issues):
    """Render a compact natural-language correction from the detected issues."""
    if not issues:
        return ""
    return ("PROCESS FEEDBACK (inefficiencies): "
            + "; ".join("- %s" % i["label"] for i in issues))