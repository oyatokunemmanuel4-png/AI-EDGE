# `app/` — Deployable application

The running system: the `aiedge` Python package plus the contracts, config, and
tests it needs. This is what gets deployed (as a Lambda package and as the
dashboard container). It contains **no training code and no data generation** —
those live in [`../ml/`](../ml/).

## Contents

```
app/
  aiedge/            the installable Python package (import name: aiedge)
    ports.py         Protocol interfaces + signal/decision value types
    pipeline.py      orchestration: normalise -> validate -> route -> decide -> emit
    ingest.py        raw records -> canonical events (drops eval-only labels)
    schemas.py       validate events/decisions against app/schemas/*.json
    factory.py       wires real components (env-gated) or deterministic stubs
    storage.py       Storage port + local-filesystem and S3 adapters
    aws.py           one boto3 session (profile/region resolution)
    handlers/        AWS Lambda entry point (s3_ingest) for the event-driven hot path
    nlp/             TransformerContentClassifier (loads the fine-tuned model)
    anomaly/         features + IsolationForest + LSTM + fusion + ModelAnomalyScorer
    rules/           config-driven governance rule engine (GDPR / ISO 27001)
    ledger/          FabricDecisionSink (writes decisions to Hyperledger Fabric)
    dashboard/       FastAPI service + enterprise UI + upload flow
  schemas/           canonical_event / governance_decision JSON Schemas (the contracts)
  config/rules/      governance_rules.yaml (the shipped rule set)
  tests/             pytest suite for the whole package
```

## How it fits the project

- **Ports & adapters.** `pipeline.py` depends only on the Protocols in `ports.py`.
  `factory.build_pipeline()` injects the real classifier / anomaly scorer / rule
  engine / ledger sink when configured, else stubs — so the app runs with no GPU,
  no AWS, and no Fabric.
- Trained models produced by [`../ml/`](../ml/) are loaded at runtime via
  `AIEDGE_CLASSIFIER_MODEL_DIR` and `AIEDGE_ANOMALY_MODEL_DIR`.
- Deployment images and the Lambda package are built from here by
  [`../infra/`](../infra/).

## Developer notes

- Install + test (from the repo root):
  `pip install -e ".[dev,dashboard]"` then `pytest` (tests here) and
  `ruff check app ml`.
- **Path resolution:** `schemas.py` and `rules/engine.py` resolve `app/schemas`
  and `app/config` relative to this package; both honour env overrides
  (`AIEDGE_SCHEMA_DIR`, `AIEDGE_RULES_PATH`) used when packaged for Lambda/Docker.
- **Optional heavy deps are lazy-imported** (`torch`/`transformers` in
  `nlp`/`anomaly`, `boto3` in `aws`/`storage`, `keras` in `anomaly.model`) so the
  package imports cheaply; install the `ml` extra only when serving real models.
- Runtime env vars: `AIEDGE_FABRIC_SINK=1` (write to the ledger),
  `AIEDGE_DASHBOARD_DECISIONS` / `AIEDGE_DASHBOARD_LEDGER` (dashboard source).
