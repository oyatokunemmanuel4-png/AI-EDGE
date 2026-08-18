# `ml/` — Machine learning & data preparation

Everything that **produces** the models and datasets the application consumes.
Nothing here runs in production: it's the offline research/model-building
workflow. The scripts import the installed `aiedge` package (see
[`../app/`](../app/)).

## Contents

```
ml/
  data_generation/   CLIs that write synthetic datasets to ../data/raw/
    generate_access_logs.py    access-plane events (labelled anomalies)
    generate_content_docs.py   content documents from templates (offline fallback)
    generate_content_llm.py    content documents via the Anthropic API (primary)
  training/          model training + the classifier bake-off
    train_anomaly.py           IsolationForest + LSTM + fusion -> models/anomaly/
    train_classifier.py        fine-tune one encoder -> models/nlp/<name>/
    requirements-train.txt     extra deps for a GPU host
    README_runpod.md           step-by-step GPU (RunPod) bake-off
  samples/           demo documents to drag into the dashboard upload page
```

Outputs are written to the repo-root working dirs (git-ignored):
datasets to `../data/`, trained models to `../models/`.

## How it fits the project

- **Data generation → `../data/`**: the pipeline and training both read these
  synthetic datasets. Seeds are tracked in `../data/raw/*/seed_*.jsonl`; generated
  sets are regenerable and git-ignored.
- **Training → `../models/`**: `train_anomaly.py` and `train_classifier.py` save
  artifacts the application loads at runtime via `AIEDGE_ANOMALY_MODEL_DIR` /
  `AIEDGE_CLASSIFIER_MODEL_DIR`.
- Shared domain vocabulary (departments, resource classes, class labels) lives in
  the `aiedge` package (`synthetic_access.py`, `synthetic_content*.py`) because the
  app's feature extraction depends on it; the CLIs here are thin wrappers over it.

## Developer notes

- Data generation (from the repo root):
  ```bash
  python ml/data_generation/generate_access_logs.py --events 8000 --anomaly-rate 0.05 --seed 42 --output data/raw/access/generated_train.jsonl
  python ml/data_generation/generate_content_llm.py --model claude-haiku-4-5 --count 3000 --seed 42 --out data/raw/content/generated_train.jsonl   # needs ANTHROPIC_API_KEY + .[llm]
  ```
- Train (from the repo root):
  ```bash
  $env:KERAS_BACKEND="torch"; python ml/training/train_anomaly.py --epochs 8    # CPU
  # classifier bake-off is GPU work — see training/README_runpod.md
  ```
- Requires the `ml` (and `llm` for the API generator) extras:
  `pip install -e ".[ml,llm]"`. The RunPod flow is the recommended way to run the
  transformer bake-off.
- Bake-off result: **roberta-base** won (see `../docs/metrics_comparison.json`).
