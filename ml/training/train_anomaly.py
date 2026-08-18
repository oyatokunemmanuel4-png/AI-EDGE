"""Train + evaluate the Phase 3 access-anomaly models and save artifacts.

Runs on CPU (small models). Uses the labelled synthetic access data:
  data/raw/access/generated_train.jsonl  (fit + validation split)
  data/raw/access/generated_test.jsonl   (held-out evaluation)

Steps: featurise -> fit Isolation Forest -> train LSTM -> pick fusion weight +
threshold by validation F1 -> evaluate IF / LSTM / fused on test -> save
isolation_forest.joblib, lstm.keras, fusion.json, metrics.json.

Usage:
  python training/train_anomaly.py [--epochs 6] [--out models/anomaly]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from sklearn.metrics import f1_score, precision_recall_fscore_support, roc_auc_score

from aiedge.anomaly.features import WINDOW, build_sequences, feature_matrix
from aiedge.anomaly.model import FusionConfig, IsolationForestModel, LSTMModel
from aiedge.anomaly.scorer import FUSION_FILE, ISO_FILE, LSTM_FILE
from aiedge.ingest import normalize_access
from aiedge.storage import iter_jsonl

REPO = Path(__file__).resolve().parents[2]  # ml/training/x.py -> repo root (data/, models/)


def _load(path: Path):
    raws = list(iter_jsonl(path.read_text(encoding="utf-8")))
    events = [normalize_access(r, source=str(path.name)) for r in raws]
    labels = np.array([1 if r.get("is_anomaly") else 0 for r in raws], dtype=int)
    return events, labels


def _rates(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, float]:
    tp = int(((y_pred == 1) & (y_true == 1)).sum())
    fp = int(((y_pred == 1) & (y_true == 0)).sum())
    tn = int(((y_pred == 0) & (y_true == 0)).sum())
    fn = int(((y_pred == 0) & (y_true == 1)).sum())
    p, r, f1, _ = precision_recall_fscore_support(
        y_true, y_pred, average="binary", zero_division=0
    )
    return {
        "precision": round(float(p), 4),
        "recall_detection_rate": round(float(r), 4),
        "f1": round(float(f1), 4),
        "false_positive_rate": round(fp / (fp + tn) if (fp + tn) else 0.0, 4),
        "tp": tp, "fp": fp, "tn": tn, "fn": fn,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--epochs", type=int, default=6)
    ap.add_argument("--out", default=str(REPO / "models" / "anomaly"))
    ap.add_argument("--val-frac", type=float, default=0.2)
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    train_events, y_train = _load(REPO / "data/raw/access/generated_train.jsonl")
    test_events, y_test = _load(REPO / "data/raw/access/generated_test.jsonl")
    print(f"train={len(train_events)} (anom={int(y_train.sum())}) "
          f"test={len(test_events)} (anom={int(y_test.sum())})")

    # Validation split (last val-frac of train, preserving order for sequences).
    n_val = int(len(train_events) * args.val_frac)
    fit_events, val_events = train_events[:-n_val], train_events[-n_val:]
    y_fit, y_val = y_train[:-n_val], y_train[-n_val:]

    # --- Isolation Forest (unsupervised: fit on fit split features) ---
    X_fit = feature_matrix(fit_events)
    iso = IsolationForestModel(contamination=0.05).fit(X_fit)

    # --- LSTM (supervised on sequences) ---
    seq_fit = build_sequences(fit_events, window=WINDOW)
    n_pos = max(int(y_fit.sum()), 1)
    n_neg = int((y_fit == 0).sum())
    lstm = LSTMModel(window=WINDOW, n_features=X_fit.shape[1]).fit(
        seq_fit, y_fit, epochs=args.epochs, class_weight={0: 1.0, 1: n_neg / n_pos}
    )

    # --- Threshold + fusion selection on validation ---
    iso_val = iso.scores(feature_matrix(val_events))
    lstm_val = lstm.scores(build_sequences(val_events, window=WINDOW))

    def best_threshold(y: np.ndarray, scores: np.ndarray) -> tuple[float, float]:
        best_t, best_f1 = 0.5, -1.0
        for t in np.round(np.arange(0.05, 0.96, 0.01), 2):
            f1 = f1_score(y, (scores >= t).astype(int), zero_division=0)
            if f1 > best_f1:
                best_t, best_f1 = float(t), float(f1)
        return best_t, best_f1

    # Fusion weight + its own threshold, chosen jointly for best fused F1.
    best = {"weight": 0.5, "threshold": 0.5, "f1": -1.0}
    for w in np.round(np.arange(0.0, 1.01, 0.1), 2):
        fused = np.clip(w * lstm_val + (1 - w) * iso_val, 0, 1)
        t, f1 = best_threshold(y_val, fused)
        if f1 > best["f1"]:
            best = {"weight": float(w), "threshold": t, "f1": f1}
    fusion = FusionConfig(weight=best["weight"], threshold=best["threshold"])

    # Each model reported at its OWN validation-tuned threshold (fair comparison).
    iso_thr, _ = best_threshold(y_val, iso_val)
    lstm_thr, _ = best_threshold(y_val, lstm_val)
    print(f"selected fusion: weight={fusion.weight} threshold={fusion.threshold} "
          f"(val F1={best['f1']:.4f}); iso_thr={iso_thr} lstm_thr={lstm_thr}")

    # --- Evaluate on held-out test (each at its own threshold) ---
    iso_test = iso.scores(feature_matrix(test_events))
    lstm_test = lstm.scores(build_sequences(test_events, window=WINDOW))
    fused_test = fusion.fuse(iso_test, lstm_test)

    metrics = {
        "counts": {"train": len(train_events), "test": len(test_events),
                   "test_anomalies": int(y_test.sum())},
        "fusion": {"weight": fusion.weight, "threshold": fusion.threshold},
        "thresholds": {"isolation_forest": iso_thr, "lstm": lstm_thr,
                       "fused": fusion.threshold},
        "isolation_forest": {
            **_rates(y_test, (iso_test >= iso_thr).astype(int)),
            "roc_auc": round(float(roc_auc_score(y_test, iso_test)), 4),
        },
        "lstm": {
            **_rates(y_test, (lstm_test >= lstm_thr).astype(int)),
            "roc_auc": round(float(roc_auc_score(y_test, lstm_test)), 4),
        },
        "fused": {
            **_rates(y_test, (fused_test >= fusion.threshold).astype(int)),
            "roc_auc": round(float(roc_auc_score(y_test, fused_test)), 4),
        },
    }

    iso.save(out / ISO_FILE)
    lstm.save(out / LSTM_FILE)
    fusion.save(out / FUSION_FILE)
    (out / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")

    print(json.dumps(metrics, indent=2))
    print(f"\nartifacts + metrics saved to {out}")


if __name__ == "__main__":
    main()
