"""FabricDecisionSink: the real DecisionSink (Phase 4) — writes governance
decisions to the Hyperledger Fabric ``governance`` channel.

The sink is transport-agnostic: it takes a ``submit`` callable that persists one
decision and returns ``{"transaction_id": ...}``. This keeps the sink unit-
testable with a fake transport; the live transport (``build_wsl_cli_transport``)
shells out to the Fabric peer CLI inside WSL, where the network runs.

On success the ledger coordinates (channel, chaincode, transaction_id) are
attached to the decision under the schema's optional ``ledger`` object, so the
dashboard can link a decision to its immutable ledger record.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from typing import Any

SubmitFn = Callable[[dict[str, Any]], dict[str, Any]]


class FabricDecisionSink:
    def __init__(
        self,
        submit: SubmitFn,
        *,
        channel: str = "governance",
        chaincode: str = "governance",
    ) -> None:
        self._submit = submit
        self.channel = channel
        self.chaincode = chaincode
        self.submitted: list[str] = []

    def emit(self, decision: dict[str, Any]) -> None:
        result = self._submit(decision) or {}
        decision["ledger"] = {
            "channel": self.channel,
            "chaincode": self.chaincode,
            "transaction_id": str(result.get("transaction_id", "")),
        }
        self.submitted.append(decision["decision_id"])


def build_wsl_cli_transport(
    *,
    distro: str = "Ubuntu-24.04",
    script: str = "/root/aiedge/invoke_decision.sh",
    timeout: int = 60,
) -> SubmitFn:
    """Transport that submits a decision via the Fabric peer CLI inside WSL.

    Runs ``bash <script>`` in the distro, piping the decision JSON on stdin; the
    script invokes RecordDecision and prints the transaction id on stdout.
    """

    def submit(decision: dict[str, Any]) -> dict[str, Any]:
        payload = json.dumps(decision, separators=(",", ":"), sort_keys=True)
        proc = subprocess.run(
            ["wsl", "-d", distro, "-u", "root", "-e", "bash", script],
            input=payload,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"Fabric invoke failed: {proc.stderr.strip()}")
        return {"transaction_id": proc.stdout.strip()}

    return submit
