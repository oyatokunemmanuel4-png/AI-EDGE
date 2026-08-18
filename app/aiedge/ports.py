"""Ports (interfaces) and signal/decision value types for the pipeline.

The pipeline core depends only on these Protocols, never on concrete AWS,
model, or ledger implementations. Phase 1 ships deterministic stubs
(``aiedge.stubs``); later phases replace them:

- ``ContentClassifier`` -> transformer encoder chosen by a Phase 2 bake-off
  (RoBERTa baseline vs DeBERTa-v3), behind this port.
- ``AnomalyScorer``     -> Isolation Forest + LSTM + fusion (Phase 3)
- ``RuleEngine``        -> governance rule engine (Phase 4)
- ``DecisionSink``      -> Hyperledger Fabric ledger writer (Phase 4)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class ContentSignal:
    """Output of the content plane classifier."""

    content_class: str  # PII | financial | policy | internal | public
    content_confidence: float  # 0..1


@dataclass(frozen=True)
class AnomalySignal:
    """Output of the access plane anomaly detector (two models + fusion)."""

    isolation_forest_score: float
    lstm_score: float
    fused_anomaly_score: float  # 0..1


@dataclass(frozen=True)
class DecisionDraft:
    """Rule-engine output before it is serialised to the decision schema."""

    action: str  # allow | flag | block | alert
    rule_ids: list[str]
    explanation: str | None = None


@runtime_checkable
class ContentClassifier(Protocol):
    def classify(self, event: dict[str, Any]) -> ContentSignal: ...


@runtime_checkable
class AnomalyScorer(Protocol):
    def score(self, event: dict[str, Any]) -> AnomalySignal: ...


@runtime_checkable
class RuleEngine(Protocol):
    def decide(
        self,
        event: dict[str, Any],
        *,
        content: ContentSignal | None,
        anomaly: AnomalySignal | None,
    ) -> DecisionDraft: ...


@runtime_checkable
class DecisionSink(Protocol):
    def emit(self, decision: dict[str, Any]) -> None: ...
