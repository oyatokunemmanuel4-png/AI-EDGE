"""Pipeline assembly. Keeps the core (aiedge.pipeline) free of stub imports.

Real components are used when available, otherwise the Phase 1 stubs. Swap-in
points:
- ``AIEDGE_ANOMALY_MODEL_DIR``    -> real ModelAnomalyScorer (Phase 3)
- ``AIEDGE_CLASSIFIER_MODEL_DIR`` -> real TransformerContentClassifier (Phase 2)
- governance rules config present -> real ConfigurableRuleEngine (Phase 4);
  override path with ``AIEDGE_RULES_PATH``
- ``AIEDGE_FABRIC_SINK`` truthy    -> FabricDecisionSink via WSL peer CLI (Phase 4)
"""

from __future__ import annotations

import os
from pathlib import Path

from aiedge.pipeline import Pipeline
from aiedge.ports import AnomalyScorer, ContentClassifier, DecisionSink, RuleEngine
from aiedge.stubs import (
    InMemoryDecisionSink,
    StubAnomalyScorer,
    StubContentClassifier,
    StubRuleEngine,
)


def _resolve_scorer() -> AnomalyScorer:
    model_dir = os.environ.get("AIEDGE_ANOMALY_MODEL_DIR")
    if model_dir and Path(model_dir).exists():
        from aiedge.anomaly.scorer import ModelAnomalyScorer

        return ModelAnomalyScorer.load(model_dir)
    return StubAnomalyScorer()


def _resolve_classifier() -> ContentClassifier:
    model_dir = os.environ.get("AIEDGE_CLASSIFIER_MODEL_DIR")
    if model_dir and Path(model_dir).exists():
        from aiedge.nlp.classifier import TransformerContentClassifier

        return TransformerContentClassifier.load(model_dir)
    return StubContentClassifier()


def _resolve_rule_engine() -> RuleEngine:
    # Prefer the real config-driven engine; the shipped rules mirror the stub's
    # behaviour, so this is a strict upgrade. Fall back to the stub only if the
    # rules file is missing.
    from aiedge.rules.engine import default_rules_path

    if default_rules_path().exists():
        from aiedge.rules.engine import ConfigurableRuleEngine

        return ConfigurableRuleEngine.load()
    return StubRuleEngine()


def _resolve_sink(explicit: DecisionSink | None) -> DecisionSink:
    if explicit is not None:
        return explicit
    if os.environ.get("AIEDGE_FABRIC_SINK"):
        from aiedge.ledger.fabric_sink import FabricDecisionSink, build_wsl_cli_transport

        return FabricDecisionSink(build_wsl_cli_transport())
    return InMemoryDecisionSink()


def build_pipeline(sink: DecisionSink | None = None) -> Pipeline:
    return Pipeline(
        classifier=_resolve_classifier(),
        scorer=_resolve_scorer(),
        rule_engine=_resolve_rule_engine(),
        sink=_resolve_sink(sink),
    )
