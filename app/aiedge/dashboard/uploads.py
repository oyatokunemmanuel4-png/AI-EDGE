"""Upload → existing pipeline → persisted results (dashboard glue).

This does NOT reimplement processing: it parses uploaded files into the records
the backend already understands, runs them through the **existing**
``aiedge.factory.build_pipeline`` (same classifier, anomaly scorer, rule engine),
appends the resulting decisions to the dashboard's decision store (so the
Dashboard and Alerts pages update), and saves the per-upload results for the
Analysis Results page.

Supported inputs (per the backend's real capabilities — no PDF/text extraction
exists, so none is faked):
- ``.txt`` / pasted text -> one content-plane document ``{document_id, text}``
- ``.jsonl`` -> one record per line; plane inferred (``text`` -> content,
  ``action``/``user_id`` -> access)
"""

from __future__ import annotations

import io
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from aiedge.factory import build_pipeline
from aiedge.stubs import JsonlDecisionSink


def _infer_plane(rec: dict[str, Any]) -> str:
    if "text" in rec or "document_id" in rec:
        return "content"
    if "action" in rec or "user_id" in rec:
        return "access"
    return "content"


def extract_pdf_text(data: bytes) -> str:
    """Extract text from a text-based PDF (pypdf, no OCR/ML). Empty for scanned PDFs."""
    from pypdf import PdfReader  # lazy: only imported when a PDF is uploaded

    reader = PdfReader(io.BytesIO(data))
    return "\n".join((page.extract_text() or "") for page in reader.pages).strip()


def records_from_file(filename: str, data: bytes | str) -> list[tuple[dict[str, Any], str]]:
    """Parse an uploaded file into (raw_record, data_plane) pairs.

    .pdf -> extracted text (one content doc); .jsonl -> one record per line;
    .txt / other -> one content doc. Raises on an unreadable/scanned PDF.
    """
    name = filename.lower()
    if name.endswith(".pdf"):
        blob = data if isinstance(data, bytes) else data.encode("utf-8")
        text = extract_pdf_text(blob)
        if not text:
            raise ValueError("no extractable text (scanned/image PDFs need OCR, not supported)")
        return [({"document_id": filename, "text": text}, "content")]

    content = data.decode("utf-8", "replace") if isinstance(data, bytes) else data
    items: list[tuple[dict[str, Any], str]] = []
    if name.endswith(".jsonl"):
        for line in content.splitlines():
            line = line.strip()
            if line:
                rec = json.loads(line)
                items.append((rec, _infer_plane(rec)))
    else:
        text = content.strip()
        if text:
            items.append(({"document_id": filename, "text": text}, "content"))
    return items


def run_upload(
    files: list[tuple[str, bytes | str]],
    *,
    decisions_path: str | Path,
    runs_dir: str | Path,
    source: str = "upload",
) -> dict[str, Any]:
    """Run uploaded files through the existing pipeline; persist decisions + run."""
    decisions_path = Path(decisions_path)
    runs_dir = Path(runs_dir)
    runs_dir.mkdir(parents=True, exist_ok=True)
    decisions_path.parent.mkdir(parents=True, exist_ok=True)

    pipe = build_pipeline(sink=JsonlDecisionSink(decisions_path))

    results: list[dict[str, Any]] = []
    for filename, data in files:
        try:
            records = records_from_file(filename, data)
        except Exception as exc:  # noqa: BLE001 - bad file (e.g. scanned PDF): one error row
            results.append({"filename": filename, "error": f"could not read file: {exc}"})
            continue
        if not records:
            results.append({"filename": filename, "error": "no content found in file"})
            continue
        for raw, plane in records:
            try:
                res = pipe.process_record(raw, source=f"{source}:{filename}", data_plane=plane)
                results.append({"filename": filename, "event": res.event, "decision": res.decision})
            except Exception as exc:  # noqa: BLE001 - surface bad records without aborting the batch
                results.append({"filename": filename, "error": str(exc)})

    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S-") + uuid.uuid4().hex[:6]
    run = {
        "run_id": run_id,
        "created_at": datetime.now(UTC).isoformat(),
        "processed": sum(1 for r in results if "decision" in r),
        "errors": sum(1 for r in results if "error" in r),
        "results": results,
    }
    (runs_dir / f"{run_id}.json").write_text(json.dumps(run), encoding="utf-8")
    (runs_dir / "latest.txt").write_text(run_id, encoding="utf-8")
    return run


def load_run(runs_dir: str | Path, run_id: str | None) -> dict[str, Any] | None:
    runs_dir = Path(runs_dir)
    if run_id in (None, "latest"):
        pointer = runs_dir / "latest.txt"
        if not pointer.exists():
            return None
        run_id = pointer.read_text(encoding="utf-8").strip()
    path = runs_dir / f"{run_id}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def list_runs(runs_dir: str | Path, limit: int = 20) -> list[dict[str, Any]]:
    runs_dir = Path(runs_dir)
    if not runs_dir.exists():
        return []
    out: list[dict[str, Any]] = []
    for path in sorted(runs_dir.glob("*.json"), reverse=True)[:limit]:
        r = json.loads(path.read_text(encoding="utf-8"))
        out.append({
            "run_id": r["run_id"],
            "created_at": r["created_at"],
            "processed": r.get("processed", 0),
            "errors": r.get("errors", 0),
        })
    return out
