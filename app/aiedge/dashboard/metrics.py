"""Governance metrics + SDG/sustainability scoring from the decision stream (pure).

Given a list of governance-decision dicts (the same objects written to the
ledger), compute the dashboard's panels: action breakdown, data-plane split,
rule frequency, security alerts, ledger/audit coverage, GDPR/ISO compliance
coverage, and transparent SDG/FEST-aligned indicators.

The SDG indicators are prototype **proxy** scores with explicit formulas (shown
in the UI). They are computed from the decision stream, not fabricated — but they
are indicators, not audited measurements. This is stated plainly for honesty.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

ACTIONS = ("allow", "flag", "alert", "block")
ENFORCING = ("flag", "alert", "block")  # non-allow = an active control fired


def _safe_div(n: float, d: float) -> float:
    return round(n / d, 4) if d else 0.0


def _plane(decision: dict[str, Any]) -> str:
    signals = decision.get("signals", {})
    if "content_class" in signals:
        return "content"
    if "fused_anomaly_score" in signals:
        return "access"
    return "unknown"


def _is_recorded(decision: dict[str, Any]) -> bool:
    return bool(decision.get("ledger", {}).get("transaction_id"))


def sdg_scores(total: int, enforcing: int, recorded: int) -> dict[str, dict[str, Any]]:
    """Transparent SDG-aligned proxy indicators in [0,1], each with its formula."""
    audit_coverage = _safe_div(recorded, total)
    enforcement_rate = _safe_div(enforcing, total)
    automation_coverage = 1.0 if total else 0.0  # every event gets an automated decision
    return {
        "SDG9_infrastructure": {
            "score": automation_coverage,
            "label": "Automated digital infrastructure",
            "formula": "events with an automated governance decision / total events",
        },
        "SDG13_digital_sustainability": {
            "score": enforcement_rate,
            "label": "Digital sustainability (self-enforcement)",
            "formula": "decisions where a control fired (non-allow) / total — proxy for "
                       "automated, resource-light governance vs. manual review",
        },
        "SDG16_accountability": {
            "score": _safe_div(recorded + enforcing, 2 * total) if total else 0.0,
            "label": "Institutional accountability",
            "formula": "mean(ledger audit coverage, enforcement rate)",
        },
        "SDG17_verifiable_sharing": {
            "score": audit_coverage,
            "label": "Verifiable cross-org data governance",
            "formula": "decisions immutably recorded on the shared ledger / total",
        },
    }


def compute_metrics(
    decisions: list[dict[str, Any]],
    *,
    rule_refs: dict[str, list[str]] | None = None,
    max_alerts: int = 20,
) -> dict[str, Any]:
    """Aggregate the decision stream into dashboard metrics.

    ``rule_refs`` maps rule_id -> list of compliance references (GDPR/ISO); when
    given, compliance-framework coverage is aggregated from the fired rules.
    """
    total = len(decisions)
    by_action = Counter(d.get("action") for d in decisions)
    enforcing = sum(by_action.get(a, 0) for a in ENFORCING)
    recorded = sum(1 for d in decisions if _is_recorded(d))
    by_plane = Counter(_plane(d) for d in decisions)
    rule_freq = Counter(r for d in decisions for r in d.get("rule_ids", []))

    # Security alerts: the most restrictive actions, most recent first.
    alerts = [
        {
            "decision_id": d.get("decision_id"),
            "action": d.get("action"),
            "rule_ids": d.get("rule_ids", []),
            "decided_at": d.get("decided_at"),
            "explanation": d.get("explanation"),
            "recorded": _is_recorded(d),
        }
        for d in decisions
        if d.get("action") in ("alert", "block")
    ]
    alerts.sort(key=lambda a: a.get("decided_at") or "", reverse=True)

    # Compliance-framework coverage (which controls fired, how often).
    compliance: Counter[str] = Counter()
    if rule_refs:
        for rid, count in rule_freq.items():
            for ref in rule_refs.get(rid, []):
                framework = ref.split("-", 1)[0]  # GDPR / ISO
                compliance[framework] += count

    return {
        "totals": {
            "decisions": total,
            "enforced": enforcing,
            "ledger_recorded": recorded,
        },
        "rates": {
            "enforcement_rate": _safe_div(enforcing, total),
            "ledger_coverage": _safe_div(recorded, total),
            "allow_rate": _safe_div(by_action.get("allow", 0), total),
        },
        "by_action": {a: by_action.get(a, 0) for a in ACTIONS},
        "by_plane": dict(by_plane),
        "top_rules": rule_freq.most_common(10),
        "compliance_hits": dict(compliance),
        "alerts": alerts[:max_alerts],
        "sdg": sdg_scores(total, enforcing, recorded),
    }
