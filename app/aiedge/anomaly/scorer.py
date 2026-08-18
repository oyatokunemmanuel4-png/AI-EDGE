"""ModelAnomalyScorer: the real AnomalyScorer (Phase 3) behind the port.

Loads the trained Isolation Forest + LSTM + fusion config and scores canonical
access events. For the LSTM's temporal window it keeps a small per-user rolling
buffer of recent feature vectors (streaming state). In a long-running process
this accumulates real context; in a stateless Lambda it resets per invocation,
so cross-invocation history would come from an external store (integration
concern for Phase 4).
"""

from __future__ import annotations

from collections import defaultdict, deque
from pathlib import Path
from typing import Any

import numpy as np

from aiedge.anomaly.features import N_FEATURES, WINDOW, event_features
from aiedge.anomaly.model import FusionConfig, IsolationForestModel, LSTMModel
from aiedge.ports import AnomalySignal

ISO_FILE = "isolation_forest.joblib"
LSTM_FILE = "lstm.keras"
FUSION_FILE = "fusion.json"


class ModelAnomalyScorer:
    def __init__(
        self,
        iso: IsolationForestModel,
        lstm: LSTMModel,
        fusion: FusionConfig,
        *,
        window: int = WINDOW,
    ) -> None:
        self.iso = iso
        self.lstm = lstm
        self.fusion = fusion
        self.window = window
        self._history: dict[str, deque[np.ndarray]] = defaultdict(
            lambda: deque(maxlen=window)
        )

    @classmethod
    def load(cls, model_dir: str | Path, *, window: int = WINDOW) -> ModelAnomalyScorer:
        model_dir = Path(model_dir)
        return cls(
            iso=IsolationForestModel.load(model_dir / ISO_FILE),
            lstm=LSTMModel.load(model_dir / LSTM_FILE, window=window, n_features=N_FEATURES),
            fusion=FusionConfig.load(model_dir / FUSION_FILE),
            window=window,
        )

    def _windowed(self, user_id: str, feat: np.ndarray) -> np.ndarray:
        buf = self._history[user_id]
        buf.append(feat)
        padded = np.zeros((self.window, N_FEATURES), dtype=np.float32)
        seq = list(buf)
        padded[self.window - len(seq):] = np.vstack(seq)
        return padded

    def score(self, event: dict[str, Any]) -> AnomalySignal:
        feat = event_features(event)
        iso_score = float(self.iso.scores(feat.reshape(1, -1))[0])

        user_id = event["access"]["user_id"]
        window = self._windowed(user_id, feat)
        lstm_score = float(self.lstm.scores(window[None, ...])[0])

        fused = float(self.fusion.fuse(np.array([iso_score]), np.array([lstm_score]))[0])
        return AnomalySignal(
            isolation_forest_score=round(iso_score, 4),
            lstm_score=round(lstm_score, 4),
            fused_anomaly_score=round(fused, 4),
        )
