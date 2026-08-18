"""Configurable governance rule engine (Phase 4) — the RuleEngine port impl.

Self-enforcing, not document-based: rules are declarative config
(config/rules/governance_rules.yaml). Each rule's ``when`` conditions are ANDed;
every matching rule contributes its id, and the decision's action is the
highest-severity action among matches (block > alert > flag > allow) — governance
escalates to the most restrictive matched control. No match -> allow.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from aiedge.ports import AnomalySignal, ContentSignal, DecisionDraft

# Higher = more restrictive. Used to pick the winning action across matched rules.
SEVERITY = {"allow": 0, "flag": 1, "alert": 2, "block": 3}


def default_rules_path() -> Path:
    override = os.environ.get("AIEDGE_RULES_PATH")
    if override:
        return Path(override)
    # app/aiedge/rules/engine.py -> parents[2] == app/ (config lives at app/config)
    return Path(__file__).resolve().parents[2] / "config" / "rules" / "governance_rules.yaml"


@dataclass(frozen=True)
class Rule:
    id: str
    when: dict[str, Any]
    action: str
    explanation: str | None = None
    references: list[str] = field(default_factory=list)


def load_rules(path: str | Path | None = None) -> list[Rule]:
    import yaml

    path = Path(path) if path else default_rules_path()
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    rules: list[Rule] = []
    for raw in data.get("rules", []):
        if raw.get("action") not in SEVERITY:
            raise ValueError(f"rule {raw.get('id')!r} has invalid action {raw.get('action')!r}")
        rules.append(
            Rule(
                id=raw["id"],
                when=dict(raw.get("when", {})),
                action=raw["action"],
                explanation=raw.get("explanation"),
                references=list(raw.get("references", [])),
            )
        )
    return rules


def _build_context(
    event: dict[str, Any],
    content: ContentSignal | None,
    anomaly: AnomalySignal | None,
) -> dict[str, Any]:
    ctx: dict[str, Any] = {"data_plane": event.get("data_plane")}
    if content is not None:
        ctx["content_class"] = content.content_class
        ctx["content_confidence"] = content.content_confidence
    if anomaly is not None:
        ctx["fused_anomaly_score"] = anomaly.fused_anomaly_score
        ctx["isolation_forest_score"] = anomaly.isolation_forest_score
        ctx["lstm_score"] = anomaly.lstm_score
    if event.get("data_plane") == "access":
        access = event.get("access", {})
        ctx["access_action"] = access.get("action")
        ctx["resource_class"] = access.get("resource_class")
        ctx["role"] = access.get("role")
        ctx["department"] = access.get("department")
    return ctx


def _matches(rule: Rule, ctx: dict[str, Any]) -> bool:
    for key, expected in rule.when.items():
        if key.endswith("_gte"):
            actual = ctx.get(key[:-4])
            if actual is None or float(actual) < float(expected):
                return False
        else:
            actual = ctx.get(key)
            if isinstance(expected, list):
                if actual not in expected:
                    return False
            elif actual != expected:
                return False
    return True


class ConfigurableRuleEngine:
    def __init__(self, rules: list[Rule]) -> None:
        self.rules = rules

    @classmethod
    def load(cls, path: str | Path | None = None) -> ConfigurableRuleEngine:
        return cls(load_rules(path))

    def decide(
        self,
        event: dict[str, Any],
        *,
        content: ContentSignal | None,
        anomaly: AnomalySignal | None,
    ) -> DecisionDraft:
        ctx = _build_context(event, content, anomaly)
        matched = [r for r in self.rules if _matches(r, ctx)]
        if not matched:
            return DecisionDraft("allow", ["default-allow"], "No governance rule triggered.")

        # Winning action = most restrictive; order rule_ids/explanations by severity desc.
        matched.sort(key=lambda r: SEVERITY[r.action], reverse=True)
        action = matched[0].action
        rule_ids = [r.id for r in matched]
        explanation = " ".join(r.explanation for r in matched if r.explanation) or None
        return DecisionDraft(action, rule_ids, explanation)
