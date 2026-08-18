"""Decision sources for the dashboard.

The dashboard reads governance decisions from a pluggable source:
- ``JsonlDecisionSource`` — a JSONL file of decisions (e.g. the processed bucket
  output, or a local capture). Default; fully offline/reproducible.
- ``LedgerDecisionSource`` — queries the Hyperledger chaincode ``GetAllDecisions``
  (the immutable source of truth) via the WSL peer CLI. Production path.

Selected by env in the app: ``AIEDGE_DASHBOARD_DECISIONS`` (a JSONL path) or
``AIEDGE_DASHBOARD_LEDGER=1``.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Protocol


class DecisionSource(Protocol):
    def load(self) -> list[dict[str, Any]]: ...


class JsonlDecisionSource:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def load(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        out: list[dict[str, Any]] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                out.append(json.loads(line))
        return out


def normalize_ledger_decision(d: dict[str, Any]) -> dict[str, Any]:
    """Ledger-stored decisions carry a flat ``ledger_tx_id`` (added by the
    chaincode); the dashboard/metrics expect a nested ``ledger.transaction_id``.
    Map it so audit coverage and the ledger column render correctly."""
    if d.get("ledger_tx_id") and not d.get("ledger"):
        d = {**d, "ledger": {
            "channel": "governance", "chaincode": "governance",
            "transaction_id": d["ledger_tx_id"],
        }}
    return d


class LedgerDecisionSource:
    """Queries the chaincode GetAllDecisions via the WSL query script (no id arg)."""

    def __init__(
        self,
        *,
        distro: str = "Ubuntu-24.04",
        script: str = "/root/aiedge/query_decision.sh",
        timeout: int = 30,
    ) -> None:
        self.distro = distro
        self.script = script
        self.timeout = timeout

    def load(self) -> list[dict[str, Any]]:
        proc = subprocess.run(
            ["wsl", "-d", self.distro, "-u", "root", "-e", "bash", self.script],
            capture_output=True,
            text=True,
            timeout=self.timeout,
            check=False,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"ledger query failed: {proc.stderr.strip()}")
        data = json.loads(proc.stdout.strip() or "[]")
        items = data if isinstance(data, list) else []
        return [normalize_ledger_decision(d) for d in items]


def load_rule_refs() -> dict[str, list[str]]:
    """Map rule_id -> compliance references (GDPR/ISO) from the rule config."""
    try:
        from aiedge.rules.engine import load_rules

        return {r.id: r.references for r in load_rules()}
    except Exception:  # noqa: BLE001 - defensive: dashboard works even if rules fail to load
        return {}
