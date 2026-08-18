"""Deterministic featurisation of access events for the anomaly models.

Both models consume the same per-event numeric vector:
- one-hot: action, role, department, resource_class  (fixed vocabularies, so
  inference never hits an unseen category)
- engineered scalars: hour-of-day, off-hours flag, unmanaged-device flag,
  external-IP flag, cross-department flag (user dept != resource dept)

The Isolation Forest scores single vectors; the LSTM scores fixed-length
windows of a user's recent vectors (temporal patterns). ``build_sequences``
produces those windows.

Feature order is stable and captured in ``FEATURE_NAMES`` so trained artifacts
stay aligned with inference.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Any

import numpy as np


DEPARTMENTS = ("finance", "hr", "legal", "engineering", "sales", "security")
RESOURCE_CLASSES = ("PII", "financial", "policy", "internal", "public")

# Fixed vocabularies (order matters and must not change once models are trained).
ACTIONS = ("read", "search", "download", "update", "bulk_download", "delete", "privilege_change")
ROLES = ("manager", "analyst")

WINDOW = 8  # LSTM sequence length (events of context incl. current)


def _one_hot(value: str, vocab: tuple[str, ...]) -> list[float]:
    return [1.0 if value == v else 0.0 for v in vocab]


def _resource_department(resource_id: str) -> str:
    # resource_id convention: "<department>-<class>-nnn"
    return resource_id.split("-", 1)[0] if "-" in resource_id else ""


def _hour(occurred_at: str) -> int:
    try:
        return datetime.fromisoformat(occurred_at).hour
    except ValueError:
        return 12


def event_features(event: dict[str, Any]) -> np.ndarray:
    """Map one canonical access event to a fixed-length float32 vector."""
    access = event["access"]
    device = access.get("device_id", "") or ""
    ip = access.get("source_ip", "") or ""
    hour = _hour(event.get("occurred_at", ""))

    vec: list[float] = []
    vec += _one_hot(access["action"], ACTIONS)
    vec += _one_hot(access["role"], ROLES)
    vec += _one_hot(access["department"], DEPARTMENTS)
    vec += _one_hot(access["resource_class"], RESOURCE_CLASSES)
    vec.append(hour / 23.0)
    vec.append(1.0 if (hour < 6 or hour >= 22) else 0.0)
    vec.append(1.0 if (device.startswith("unmanaged") or device == "") else 0.0)
    vec.append(0.0 if ip.startswith("10.") else 1.0)
    vec.append(1.0 if _resource_department(access["resource_id"]) != access["department"] else 0.0)
    return np.asarray(vec, dtype=np.float32)


FEATURE_NAMES: tuple[str, ...] = (
    *(f"action={a}" for a in ACTIONS),
    *(f"role={r}" for r in ROLES),
    *(f"dept={d}" for d in DEPARTMENTS),
    *(f"resclass={c}" for c in RESOURCE_CLASSES),
    "hour_norm",
    "off_hours",
    "unmanaged_device",
    "external_ip",
    "cross_department",
)
N_FEATURES = len(FEATURE_NAMES)


def feature_matrix(events: Iterable[dict[str, Any]]) -> np.ndarray:
    rows = [event_features(e) for e in events]
    return np.vstack(rows) if rows else np.empty((0, N_FEATURES), dtype=np.float32)


def build_sequences(
    events: list[dict[str, Any]], *, window: int = WINDOW
) -> np.ndarray:
    """Per-user sliding windows of feature vectors, aligned to each event.

    Events are grouped by user and ordered by time; window i ends at event i and
    is left-padded with zeros when the user has fewer than ``window`` prior
    events. Returns shape (len(events), window, N_FEATURES) in the input order.
    """
    order = sorted(
        range(len(events)),
        key=lambda i: (events[i]["access"]["user_id"], events[i].get("occurred_at", "")),
    )
    feats = feature_matrix(events)
    out = np.zeros((len(events), window, N_FEATURES), dtype=np.float32)

    history: list[np.ndarray] = []
    current_user: str | None = None
    for idx in order:
        user = events[idx]["access"]["user_id"]
        if user != current_user:
            history = []
            current_user = user
        history.append(feats[idx])
        window_slice = history[-window:]
        padded = np.zeros((window, N_FEATURES), dtype=np.float32)
        padded[window - len(window_slice):] = np.vstack(window_slice)
        out[idx] = padded
    return out
