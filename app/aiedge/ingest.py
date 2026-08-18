"""Normalisation of raw source records into canonical events.

Raw records differ from the canonical schema in two ways this module resolves:

1. Access logs are *flat* (fields at top level); the canonical event nests them
   under ``access`` (and content under ``content``).
2. Raw access logs carry ground-truth labels (``is_anomaly``, ``anomaly_reason``)
   used only for offline model evaluation. These are **dropped** here so they
   never leak into a runtime event the models will score.

The plane is declared by the caller (in deployment, by the S3 key prefix
``raw/access/`` vs ``raw/content/``), not inferred from record contents.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

# Fields that make up a canonical access object (everything else in a raw
# access log is dropped, including the is_anomaly / anomaly_reason labels).
_ACCESS_REQUIRED = ("user_id", "role", "department", "resource_id", "resource_class", "action")
_ACCESS_OPTIONAL = ("source_ip", "device_id", "session_id")

_CONTENT_OPTIONAL = ("label", "metadata")


class NormalizationError(ValueError):
    """Raised when a raw record is missing fields required to normalise."""


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def normalize_access(raw: dict[str, Any], *, source: str) -> dict[str, Any]:
    missing = [k for k in _ACCESS_REQUIRED if k not in raw]
    if missing:
        raise NormalizationError(f"access record missing fields: {missing}")

    access: dict[str, Any] = {k: raw[k] for k in _ACCESS_REQUIRED}
    for opt in _ACCESS_OPTIONAL:
        if raw.get(opt) is not None:
            access[opt] = raw[opt]

    return {
        "event_id": raw.get("event_id") or str(uuid4()),
        "event_type": "access",
        "data_plane": "access",
        "occurred_at": raw.get("occurred_at") or _now_iso(),
        "source": source,
        "access": access,
    }


def normalize_content(raw: dict[str, Any], *, source: str) -> dict[str, Any]:
    if not raw.get("document_id"):
        raise NormalizationError("content record missing document_id")
    if not raw.get("text"):
        raise NormalizationError("content record missing text")

    content: dict[str, Any] = {"document_id": raw["document_id"], "text": raw["text"]}
    for opt in _CONTENT_OPTIONAL:
        if raw.get(opt) is not None:
            content[opt] = raw[opt]

    return {
        "event_id": raw.get("event_id") or str(uuid4()),
        "event_type": "content",
        "data_plane": "content",
        "occurred_at": raw.get("occurred_at") or _now_iso(),
        "source": source,
        "content": content,
    }


def normalize(raw: dict[str, Any], *, source: str, data_plane: str) -> dict[str, Any]:
    """Dispatch to the plane-specific normaliser."""
    if data_plane == "access":
        return normalize_access(raw, source=source)
    if data_plane == "content":
        return normalize_content(raw, source=source)
    raise NormalizationError(f"unknown data_plane: {data_plane!r}")
