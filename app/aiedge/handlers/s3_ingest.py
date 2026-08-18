"""S3 ObjectCreated -> pipeline Lambda handler (Phase 1 hot path).

Trigger: object created under ``raw/`` in the raw bucket. For each object the
handler infers the data plane from the key prefix, reads the JSONL records,
runs them through the pipeline, and writes canonical events + governance
decisions to the processed bucket:

    raw/access/…\u200b.jsonl  ->  events/access/…\u200b.jsonl  +  decisions/access/…\u200b.jsonl

This adapter stays thin: all logic is in the pipeline core. The Phase 1
decision sink is S3 (the processed bucket); the Fabric ledger sink replaces it
in Phase 4.

Environment:
- ``AIEDGE_PROCESSED_BUCKET`` (required): destination bucket.
- ``AIEDGE_SCHEMA_DIR`` (set at deploy): bundled schemas path (/var/task/schemas).
No AWS_PROFILE is set in Lambda, so boto3 uses the execution role.
"""

from __future__ import annotations

import json
import os
import urllib.parse
from typing import Any

from aiedge.factory import build_pipeline
from aiedge.storage import S3Storage, data_plane_for_key, iter_jsonl


def _to_jsonl(items: list[dict[str, Any]]) -> str:
    return "\n".join(json.dumps(i, separators=(",", ":"), sort_keys=True) for i in items) + "\n"


def handler(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    processed_bucket = os.environ["AIEDGE_PROCESSED_BUCKET"]
    dst = S3Storage(processed_bucket)

    summary: list[dict[str, Any]] = []
    for record in event.get("Records", []):
        bucket = record["s3"]["bucket"]["name"]
        key = urllib.parse.unquote_plus(record["s3"]["object"]["key"])
        plane = data_plane_for_key(key)

        raws = list(iter_jsonl(S3Storage(bucket).read_text(key)))
        pipe = build_pipeline()  # Phase 1 stubs; decisions collected below
        results = pipe.process_records(raws, source=f"s3://{bucket}/{key}", data_plane=plane)

        out_key = key.split("/", 1)[1] if "/" in key else key  # drop leading raw/
        dst.write_text(f"events/{out_key}", _to_jsonl([r.event for r in results]))
        dst.write_text(f"decisions/{out_key}", _to_jsonl([r.decision for r in results]))

        summary.append({"bucket": bucket, "key": key, "plane": plane, "records": len(results)})

    return {"processed": summary}
