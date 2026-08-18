# AI-EDGE : Automated Intelligent Enterprise Data Governance Ecosystem

AI-EDGE is a production-shaped prototype of an active, self-enforcing data
governance system. It ingests enterprise data events in real time, classifies
and risk-scores them, enforces governance rules, writes an immutable audit trail
to a blockchain ledger, and surfaces everything on an enterprise dashboard.

The system is built to run like production; the **only** difference from a real
deployment is that the datasets are **synthetic** (real enterprise data is
confidential). Every artifact is regenerable from committed code + seeds.

> MSc dissertation project. Aligns with UN SDGs 9, 13, 16, 17. Full background,
> research questions, and the phase-by-phase build history are in [`docs/`](docs/).

## Architecture

```
 Document / event  ─►  Ingest & normalise ─►  Route by data plane
 (upload or S3)          (canonical schema)      │
                                                 ├─ content ─► NLP classifier (RoBERTa)
                                                 └─ access  ─► Anomaly detector (IsolationForest + LSTM + fusion)
                                                 │
                                          Governance rule engine (config-driven, GDPR / ISO 27001)
                                                 │
                                          Decision ─► Hyperledger Fabric ledger (immutable audit)
                                                 └─► Dashboard (metrics, results, alerts)
```

Everything is wired through **ports** (interfaces): real models, the rule engine,
and the ledger sink are injected, with deterministic stubs as fallbacks : so any
part runs standalone and later components slot in without changing the core.

## Repository layout

Four top-level directories, one per responsibility:

| Directory | Responsibility | Read |
|---|---|---|
| [`app/`](app/) | The **deployable application** : the `aiedge` Python package (pipeline, classifier/anomaly inference, rule engine, ledger sink, Lambda handler, dashboard), its JSON-Schema contracts, runtime config, and tests. | [app/README.md](app/README.md) |
| [`ml/`](ml/) | The **machine-learning & data-preparation workflow** : model training, the classifier bake-off (RunPod), synthetic data generation, and demo samples. | [ml/README.md](ml/README.md) |
| [`infra/`](infra/) | **Infrastructure & deployment** : AWS (Terraform + Lambda packaging), Docker images / compose, and the Hyperledger Fabric network + chaincode. | [infra/README.md](infra/README.md) |

Working directories at the root (git-ignored contents; created/populated at runtime):
`data/` (datasets : seeds tracked, generated ignored) and `models/` (trained artifacts).

## Quick start (from a clean clone)

> **New here?** For a complete, beginner-friendly walkthrough (install everything,
> run locally with Docker, then deploy to your own AWS and test it), see
> **[SETUP.md](SETUP.md)**. The steps below are the short version.

```powershell
# 1. Application + tests (Python 3.12)
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev,dashboard]"
.\.venv\Scripts\python.exe -m pytest -q          # expect: all green

# 2. Run the dashboard (Upload -> Analysis Results -> Alerts flow)
.\.venv\Scripts\python.exe -m uvicorn aiedge.dashboard.app:app --port 8000
#    open http://localhost:8000 and upload files from ml/samples/
#    (containerised alternative: docker compose up -d --build dashboard)
```

Recommended full sequence for the complete system:

1. **App + tests** : step 1 above (verifies the build).
2. **Data** : `ml/data_generation/` generates synthetic access logs and content
   documents; see [ml/README.md](ml/README.md).
3. **Train models** : `ml/training/` trains the anomaly detector (CPU) and runs
   the classifier bake-off (GPU/RunPod); the winner is served via
   `AIEDGE_CLASSIFIER_MODEL_DIR` / `AIEDGE_ANOMALY_MODEL_DIR`.
4. **Ledger** : bring up Hyperledger Fabric and deploy the governance chaincode
   (CCaaS); see [infra/README.md](infra/README.md).
5. **Cloud pipeline** : provision AWS (S3 + Lambda) via Terraform for the
   event-driven hot path; see [infra/README.md](infra/README.md).
6. **Dashboard** : run it over the decision store or directly against the ledger.

