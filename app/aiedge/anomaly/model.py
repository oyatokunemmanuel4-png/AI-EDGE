"""Anomaly models: Isolation Forest (point) + LSTM (sequence) + fusion.

The two answer different questions and are combined, not compared:
- Isolation Forest: is this single access weird? (unsupervised, point)
- LSTM: is this *sequence* of a user's accesses weird? (supervised, temporal)

Both expose a normalised score in [0, 1] (higher = more anomalous); fusion is a
convex combination whose weight + decision threshold are chosen empirically on a
validation split (see training/train_anomaly.py).

Keras/torch are imported lazily so importing this module (e.g. during test
collection) stays cheap.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np


def _clip01(a: np.ndarray) -> np.ndarray:
    return np.clip(a, 0.0, 1.0)


# --- Isolation Forest --------------------------------------------------------


class IsolationForestModel:
    def __init__(self, contamination: float = 0.05, random_state: int = 740) -> None:
        self.contamination = contamination
        self.random_state = random_state
        self._model = None
        self._raw_min = 0.0
        self._raw_max = 1.0

    def fit(self, features: np.ndarray) -> IsolationForestModel:
        from sklearn.ensemble import IsolationForest

        self._model = IsolationForest(
            n_estimators=200,
            contamination=self.contamination,
            random_state=self.random_state,
        ).fit(features)
        raw = -self._model.score_samples(features)  # higher = more anomalous
        self._raw_min = float(raw.min())
        self._raw_max = float(raw.max())
        return self

    def scores(self, features: np.ndarray) -> np.ndarray:
        assert self._model is not None, "model not fitted/loaded"
        raw = -self._model.score_samples(features)
        span = self._raw_max - self._raw_min or 1.0
        return _clip01((raw - self._raw_min) / span)

    def save(self, path: str | Path) -> None:
        import joblib

        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(
            {"model": self._model, "raw_min": self._raw_min, "raw_max": self._raw_max},
            path,
        )

    @classmethod
    def load(cls, path: str | Path) -> IsolationForestModel:
        import joblib

        blob = joblib.load(path)
        obj = cls()
        obj._model = blob["model"]
        obj._raw_min = blob["raw_min"]
        obj._raw_max = blob["raw_max"]
        return obj


# --- LSTM sequence model -----------------------------------------------------


def _ensure_torch_backend() -> None:
    os.environ.setdefault("KERAS_BACKEND", "torch")


class LSTMModel:
    def __init__(self, window: int, n_features: int) -> None:
        self.window = window
        self.n_features = n_features
        self._model = None

    def _build(self):
        _ensure_torch_backend()
        import keras
        from keras import layers

        model = keras.Sequential(
            [
                keras.Input(shape=(self.window, self.n_features)),
                layers.Masking(mask_value=0.0),
                layers.LSTM(32),
                layers.Dense(16, activation="relu"),
                layers.Dense(1, activation="sigmoid"),
            ]
        )
        model.compile(optimizer="adam", loss="binary_crossentropy", metrics=["accuracy"])
        return model

    def fit(
        self,
        sequences: np.ndarray,
        labels: np.ndarray,
        *,
        epochs: int = 6,
        batch_size: int = 64,
        class_weight: dict[int, float] | None = None,
        verbose: int = 0,
    ) -> LSTMModel:
        self._model = self._build()
        self._model.fit(
            sequences,
            labels.astype("float32"),
            epochs=epochs,
            batch_size=batch_size,
            class_weight=class_weight,
            verbose=verbose,
        )
        return self

    def scores(self, sequences: np.ndarray) -> np.ndarray:
        assert self._model is not None, "model not fitted/loaded"
        preds = self._model.predict(sequences, verbose=0).reshape(-1)
        return _clip01(preds)

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._model.save(path)  # .keras file

    @classmethod
    def load(cls, path: str | Path, *, window: int, n_features: int) -> LSTMModel:
        _ensure_torch_backend()
        import keras

        obj = cls(window=window, n_features=n_features)
        obj._model = keras.models.load_model(path)
        return obj


# --- Fusion ------------------------------------------------------------------


@dataclass(frozen=True)
class FusionConfig:
    """fused = weight * lstm + (1 - weight) * isolation_forest; threshold for eval."""

    weight: float = 0.5
    threshold: float = 0.5

    def fuse(self, iso: np.ndarray, lstm: np.ndarray) -> np.ndarray:
        return _clip01(self.weight * lstm + (1.0 - self.weight) * iso)

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(asdict(self)), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> FusionConfig:
        return cls(**json.loads(Path(path).read_text(encoding="utf-8")))
