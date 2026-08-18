"""Deterministic Phase 1 placeholders for the model, rule, and sink ports.

These make the end-to-end pipeline runnable and testable NOW without the real
ML models or ledger. They are intentionally simple and rule-of-thumb; each is
replaced by a real implementation in a later phase (see aiedge.ports). None of
them learn anything — they are heuristics chosen only to exercise the wiring.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from aiedge.ports import AnomalySignal, ContentSignal, DecisionDraft

# --- Content classifier stub (real: modern encoder, Phase 2 bake-off) --------
# Phase 2 selects empirically between RoBERTa (baseline) and DeBERTa-v3.

_KEYWORDS = {
    "PII": ("ssn", "social security", "passport", "home address", "phone number", "date of birth"),
    "financial": ("revenue", "budget", "invoice", "bank", "salary", "margin", "settlement"),
    "policy": ("policy", "gdpr", "iso 27001", "compliance", "regulation", "procedure"),
}


class StubContentClassifier:
    """Keyword heuristic over the document text. Deterministic; no training."""

    def classify(self, event: dict[str, Any]) -> ContentSignal:
        text = event["content"]["text"].lower()
        for label, keywords in _KEYWORDS.items():
            if any(kw in text for kw in keywords):
                return ContentSignal(content_class=label, content_confidence=0.6)
        return ContentSignal(content_class="internal", content_confidence=0.5)


# --- Anomaly scorer stub (real: Isolation Forest + LSTM + fusion, Phase 3) ---

_ANOMALOUS_ACTIONS = {"bulk_download", "delete", "privilege_change"}


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


class StubAnomalyScorer:
    """Rule-of-thumb risk score from access attributes. Deterministic."""

    def score(self, event: dict[str, Any]) -> AnomalySignal:
        access = event["access"]
        risk = 0.1
        if access["action"] in _ANOMALOUS_ACTIONS:
            risk += 0.6
        device = access.get("device_id", "")
        if device.startswith("unmanaged") or not device:
            risk += 0.2
        try:
            hour = datetime.fromisoformat(event["occurred_at"]).hour
            if hour < 6 or hour >= 22:
                risk += 0.2
        except ValueError:
            pass

        fused = _clamp(risk)
        # Two "model" views around the fused score so downstream code that reads
        # both is exercised; real models produce these independently in Phase 3.
        return AnomalySignal(
            isolation_forest_score=round(_clamp(fused + 0.05), 4),
            lstm_score=round(_clamp(fused - 0.05), 4),
            fused_anomaly_score=round(fused, 4),
        )


# --- Rule engine stub (real: governance rule engine, Phase 4) ----------------


class StubRuleEngine:
    """Minimal starter rules so the vertical slice produces valid decisions.

    Real rule schema + full rule set arrive in Phase 4; these honour the
    decision contract (>=1 rule id, valid action enum).
    """

    def decide(
        self,
        event: dict[str, Any],
        *,
        content: ContentSignal | None,
        anomaly: AnomalySignal | None,
    ) -> DecisionDraft:
        if event["data_plane"] == "access" and anomaly is not None:
            action_name = event["access"]["action"]
            if action_name == "privilege_change":
                return DecisionDraft(
                    "alert", ["ACC-PRIV-CHANGE"], "Privilege change is always alerted."
                )
            if anomaly.fused_anomaly_score >= 0.8:
                return DecisionDraft(
                    "alert", ["ACC-HIGH-ANOMALY"], "Fused anomaly score >= 0.8."
                )
            if anomaly.fused_anomaly_score >= 0.5:
                return DecisionDraft(
                    "flag", ["ACC-MED-ANOMALY"], "Fused anomaly score >= 0.5."
                )
            return DecisionDraft("allow", ["default-allow"], "No access rule triggered.")

        if event["data_plane"] == "content" and content is not None:
            if content.content_class == "PII":
                return DecisionDraft("flag", ["CONT-PII"], "PII content flagged for review.")
            if content.content_class == "financial":
                return DecisionDraft("flag", ["CONT-FIN"], "Financial content flagged.")
            return DecisionDraft("allow", ["default-allow"], "No content rule triggered.")

        return DecisionDraft("allow", ["default-allow"], "No applicable signals.")


# --- Decision sinks (real: Hyperledger Fabric writer, Phase 4) ---------------


class InMemoryDecisionSink:
    """Collects decisions in a list; useful for tests and local runs."""

    def __init__(self) -> None:
        self.decisions: list[dict[str, Any]] = []

    def emit(self, decision: dict[str, Any]) -> None:
        self.decisions.append(decision)


class JsonlDecisionSink:
    """Appends decisions as JSON lines to a local file (dev stand-in for ledger)."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def emit(self, decision: dict[str, Any]) -> None:
        import json

        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(decision, separators=(",", ":"), sort_keys=True))
            handle.write("\n")
