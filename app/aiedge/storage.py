"""Storage port + local-filesystem and S3 adapters.

The pipeline never talks to S3 directly. Local development/tests use
``LocalFilesystemStorage``; the deployed Lambda uses ``S3Storage``. Both satisfy
the same ``Storage`` protocol.

Deployment convention: the S3 key prefix declares the data plane, e.g.
``raw/access/2026/…\u200b.jsonl`` -> access, ``raw/content/…\u200b.jsonl`` -> content.
``data_plane_for_key`` centralises that mapping.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class Storage(Protocol):
    def read_text(self, key: str) -> str: ...
    def write_text(self, key: str, data: str) -> None: ...
    def list_keys(self, prefix: str = "") -> list[str]: ...


class LocalFilesystemStorage:
    """Maps object keys to files under a root directory."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def _path(self, key: str) -> Path:
        return self.root / key

    def read_text(self, key: str) -> str:
        return self._path(key).read_text(encoding="utf-8")

    def write_text(self, key: str, data: str) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(data, encoding="utf-8")

    def list_keys(self, prefix: str = "") -> list[str]:
        base = self.root
        if not base.exists():
            return []
        keys = [
            str(p.relative_to(base)).replace("\\", "/")
            for p in base.rglob("*")
            if p.is_file()
        ]
        return sorted(k for k in keys if k.startswith(prefix))


class S3Storage:
    """boto3-backed S3 adapter. Session resolves via aiedge.aws (profile/region)."""

    def __init__(self, bucket: str, session: Any | None = None) -> None:
        from aiedge.aws import get_session

        self.bucket = bucket
        self._client = (session or get_session()).client("s3")

    def read_text(self, key: str) -> str:
        obj = self._client.get_object(Bucket=self.bucket, Key=key)
        return obj["Body"].read().decode("utf-8")

    def write_text(self, key: str, data: str) -> None:
        self._client.put_object(Bucket=self.bucket, Key=key, Body=data.encode("utf-8"))

    def list_keys(self, prefix: str = "") -> list[str]:
        keys: list[str] = []
        paginator = self._client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            keys.extend(item["Key"] for item in page.get("Contents", []))
        return keys


def iter_jsonl(text: str) -> Iterator[dict[str, Any]]:
    """Yield one dict per non-blank line of JSONL text."""
    for line in text.splitlines():
        line = line.strip()
        if line:
            yield json.loads(line)


def data_plane_for_key(key: str) -> str:
    """Infer the data plane from an S3 key by convention. Raises on ambiguity."""
    k = key.lower()
    has_access = "/access/" in k or k.startswith("access/")
    has_content = "/content/" in k or k.startswith("content/")
    if has_access and not has_content:
        return "access"
    if has_content and not has_access:
        return "content"
    raise ValueError(f"cannot determine data plane from key: {key!r}")
