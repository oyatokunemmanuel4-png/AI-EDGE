"""Schema loading and validation against the committed JSON Schemas.

The schemas in ``/schemas`` are the source of truth for the canonical event and
governance-decision contracts. Every event entering the pipeline and every
decision leaving it is validated here so contract drift fails fast.

The schema directory resolves to the repo's ``schemas/`` by default but can be
overridden with ``AIEDGE_SCHEMA_DIR`` (used when packaging for Lambda, where the
schemas are bundled alongside the code).
"""

from __future__ import annotations

import json
import os
from functools import cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

CANONICAL_EVENT = "canonical_event.schema.json"
GOVERNANCE_DECISION = "governance_decision.schema.json"


def schema_dir() -> Path:
    override = os.environ.get("AIEDGE_SCHEMA_DIR")
    if override:
        return Path(override)
    # app/aiedge/schemas.py -> parents[1] == app/ (schemas live at app/schemas)
    return Path(__file__).resolve().parents[1] / "schemas"


@cache
def _validator(name: str) -> Draft202012Validator:
    schema = json.loads((schema_dir() / name).read_text(encoding="utf-8"))
    return Draft202012Validator(schema, format_checker=FormatChecker())


def validate_event(event: dict[str, Any]) -> dict[str, Any]:
    """Validate a canonical event; raise jsonschema.ValidationError if invalid."""
    _validator(CANONICAL_EVENT).validate(event)
    return event


def validate_decision(decision: dict[str, Any]) -> dict[str, Any]:
    """Validate a governance decision; raise jsonschema.ValidationError if invalid."""
    _validator(GOVERNANCE_DECISION).validate(decision)
    return decision
