"""FastAPI governance dashboard service (Phase 5/6).

Serves a monochrome enterprise UI (Dashboard / Upload / Analysis Results /
Alerts) plus a JSON API computed from the decision stream. The Upload flow runs
documents through the EXISTING pipeline (aiedge.factory.build_pipeline) — it does
not reimplement any processing.

Decision source for the read views is env-selected:
- ``AIEDGE_DASHBOARD_LEDGER=1``       -> query the Hyperledger ledger (production)
- ``AIEDGE_DASHBOARD_DECISIONS=path`` -> a JSONL file of decisions (default)

Run:  uvicorn aiedge.dashboard.app:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, File, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from aiedge.dashboard.metrics import compute_metrics
from aiedge.dashboard.sources import (
    DecisionSource,
    JsonlDecisionSource,
    LedgerDecisionSource,
    load_rule_refs,
)
from aiedge.dashboard.uploads import list_runs, load_run, run_upload

STATIC = Path(__file__).resolve().parent / "static"

DECISIONS_PATH = os.environ.get("AIEDGE_DASHBOARD_DECISIONS", "data/processed/decisions.jsonl")
RUNS_DIR = os.environ.get("AIEDGE_DASHBOARD_RUNS", "data/processed/runs")


def _source() -> DecisionSource:
    if os.environ.get("AIEDGE_DASHBOARD_LEDGER"):
        return LedgerDecisionSource()
    return JsonlDecisionSource(DECISIONS_PATH)


app = FastAPI(title="AI-EDGE Governance Dashboard")


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/metrics")
def api_metrics() -> JSONResponse:
    decisions = _source().load()
    return JSONResponse(compute_metrics(decisions, rule_refs=load_rule_refs()))


@app.get("/api/decisions")
def api_decisions(limit: int = 50) -> JSONResponse:
    decisions = _source().load()
    decisions.sort(key=lambda d: d.get("decided_at") or "", reverse=True)
    return JSONResponse(decisions[: max(0, limit)])


@app.post("/api/upload")
async def api_upload(files: list[UploadFile] = File(...)) -> JSONResponse:  # noqa: B008 - FastAPI idiom
    """Run uploaded documents through the existing pipeline; persist results."""
    payloads: list[tuple[str, bytes]] = []
    for f in files:
        raw = await f.read()  # bytes: text is decoded per-type in records_from_file (PDFs stay binary)
        payloads.append((f.filename or "upload.txt", raw))
    run = run_upload(payloads, decisions_path=DECISIONS_PATH, runs_dir=RUNS_DIR)
    return JSONResponse({
        "run_id": run["run_id"],
        "processed": run["processed"],
        "errors": run["errors"],
    })


@app.get("/api/results")
def api_results(run_id: str = "latest") -> JSONResponse:
    run = load_run(RUNS_DIR, run_id)
    return JSONResponse(run or {"run_id": None, "results": []})


@app.get("/api/runs")
def api_runs(limit: int = 20) -> JSONResponse:
    return JSONResponse(list_runs(RUNS_DIR, limit=limit))


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")
