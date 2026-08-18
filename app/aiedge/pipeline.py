"""The AI-EDGE governance pipeline core (backbone).

Flow per record:  normalise -> validate event -> route by data plane ->
gather signals (content classifier | anomaly scorer) -> rule engine decision ->
build & validate governance decision -> emit to sink.

The core depends only on the port Protocols in ``aiedge.ports``; concrete
models/rules/sink are injected, so AWS, ML, and Fabric slot in later without
changing this file.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from aiedge.ingest import normalize
from aiedge.ports import (
    AnomalyScorer,
    AnomalySignal,
    ContentClassifier,
    ContentSignal,
    DecisionDraft,
    DecisionSink,
    RuleEngine,
)
from aiedge.schemas import validate_decision, validate_event


@dataclass(frozen=True)
class PipelineResult:
    event: dict[str, Any]
    decision: dict[str, Any]


def _build_signals(
    content: ContentSignal | None, anomaly: AnomalySignal | None
) -> dict[str, Any]:
    """Assemble the decision ``signals`` object with only the keys we have."""
    signals: dict[str, Any] = {}
    if content is not None:
        signals["content_class"] = content.content_class
        signals["content_confidence"] = content.content_confidence
    if anomaly is not None:
        signals["isolation_forest_score"] = anomaly.isolation_forest_score
        signals["lstm_score"] = anomaly.lstm_score
        signals["fused_anomaly_score"] = anomaly.fused_anomaly_score
    return signals


def _build_decision(
    event: dict[str, Any],
    draft: DecisionDraft,
    content: ContentSignal | None,
    anomaly: AnomalySignal | None,
) -> dict[str, Any]:
    decision: dict[str, Any] = {
        "decision_id": str(uuid4()),
        "event_id": event["event_id"],
        "decided_at": datetime.now(UTC).isoformat(),
        "action": draft.action,
        "rule_ids": list(dict.fromkeys(draft.rule_ids)),  # dedupe, preserve order
        "signals": _build_signals(content, anomaly),
    }
    if draft.explanation:
        decision["explanation"] = draft.explanation
    return decision


class Pipeline:
    def __init__(
        self,
        classifier: ContentClassifier,
        scorer: AnomalyScorer,
        rule_engine: RuleEngine,
        sink: DecisionSink,
    ) -> None:
        self.classifier = classifier
        self.scorer = scorer
        self.rule_engine = rule_engine
        self.sink = sink

    def process_record(
        self, raw: dict[str, Any], *, source: str, data_plane: str
    ) -> PipelineResult:
        event = validate_event(normalize(raw, source=source, data_plane=data_plane))

        content_signal: ContentSignal | None = None
        anomaly_signal: AnomalySignal | None = None
        if event["data_plane"] == "content":
            content_signal = self.classifier.classify(event)
        else:
            anomaly_signal = self.scorer.score(event)

        draft = self.rule_engine.decide(event, content=content_signal, anomaly=anomaly_signal)
        decision = validate_decision(
            _build_decision(event, draft, content_signal, anomaly_signal)
        )
        self.sink.emit(decision)
        return PipelineResult(event=event, decision=decision)

    def process_records(
        self, raws: Iterable[dict[str, Any]], *, source: str, data_plane: str
    ) -> list[PipelineResult]:
        return [
            self.process_record(raw, source=source, data_plane=data_plane) for raw in raws
        ]
