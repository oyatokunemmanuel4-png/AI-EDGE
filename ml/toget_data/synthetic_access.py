"""Synthetic access-log stream generation for the Phase 0 access plane."""

from __future__ import annotations

import json
import random
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

NORMAL_ACTIONS = ("read", "search", "download", "update")
ANOMALOUS_ACTIONS = ("bulk_download", "delete", "privilege_change")
DEPARTMENTS = ("finance", "hr", "legal", "engineering", "sales", "security")
RESOURCE_CLASSES = ("PII", "financial", "policy", "internal", "public")


@dataclass(frozen=True)
class AccessEvent:
    event_id: str
    event_type: str
    occurred_at: str
    user_id: str
    role: str
    department: str
    resource_id: str
    resource_class: str
    action: str
    source_ip: str
    device_id: str
    session_id: str
    is_anomaly: bool
    anomaly_reason: str | None

    def to_json(self) -> str:
        return json.dumps(asdict(self), separators=(",", ":"), sort_keys=True)


def generate_access_events(
    count: int,
    *,
    anomaly_rate: float = 0.08,
    seed: int = 740,
    start: datetime | None = None,
) -> list[AccessEvent]:
    """Generate realistic-enough user/resource/action/timestamp sequences."""

    if count < 0:
        raise ValueError("count must be non-negative")
    if not 0 <= anomaly_rate <= 1:
        raise ValueError("anomaly_rate must be between 0 and 1")

    rng = random.Random(seed)
    start_time = start or datetime(2026, 1, 5, 8, 0, tzinfo=UTC)
    users = _build_users()
    resources = _build_resources()

    events: list[AccessEvent] = []
    for index in range(count):
        user = rng.choice(users)
        resource = _choose_resource_for_user(rng, resources, user["department"])
        occurred_at = start_time + timedelta(minutes=index * rng.randint(1, 4))
        is_anomaly = rng.random() < anomaly_rate

        if is_anomaly:
            event = _make_anomalous_event(rng, occurred_at, user, resources)
        else:
            event = AccessEvent(
                event_id=str(uuid4()),
                event_type="access",
                occurred_at=occurred_at.isoformat(),
                user_id=user["user_id"],
                role=user["role"],
                department=user["department"],
                resource_id=resource["resource_id"],
                resource_class=resource["resource_class"],
                action=rng.choice(NORMAL_ACTIONS),
                source_ip=_office_ip(rng),
                device_id=user["device_id"],
                session_id=f"session-{user['user_id']}-{occurred_at:%Y%m%d}",
                is_anomaly=False,
                anomaly_reason=None,
            )
        events.append(event)

    return events


def write_jsonl(events: Iterable[AccessEvent], output_path: str | Path) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for event in events:
            handle.write(event.to_json())
            handle.write("\n")
    return path


def _build_users() -> list[dict[str, str]]:
    users: list[dict[str, str]] = []
    for dept_index, department in enumerate(DEPARTMENTS):
        for user_index in range(1, 9):
            role = "manager" if user_index in (1, 2) else "analyst"
            users.append(
                {
                    "user_id": f"u-{dept_index + 1:02d}-{user_index:03d}",
                    "role": role,
                    "department": department,
                    "device_id": f"managed-{dept_index + 1:02d}-{user_index:03d}",
                }
            )
    return users


def _build_resources() -> list[dict[str, str]]:
    resources: list[dict[str, str]] = []
    for department in DEPARTMENTS:
        for resource_class in RESOURCE_CLASSES:
            for index in range(1, 6):
                resources.append(
                    {
                        "resource_id": f"{department}-{resource_class.lower()}-{index:03d}",
                        "department": department,
                        "resource_class": resource_class,
                    }
                )
    return resources


def _choose_resource_for_user(
    rng: random.Random, resources: list[dict[str, str]], department: str
) -> dict[str, str]:
    same_department = [item for item in resources if item["department"] == department]
    return rng.choice(same_department if rng.random() < 0.88 else resources)


def _make_anomalous_event(
    rng: random.Random,
    occurred_at: datetime,
    user: dict[str, str],
    resources: list[dict[str, str]],
) -> AccessEvent:
    # Mix of OVERT anomalies (use a distinct anomalous action) and STEALTH
    # anomalies (use a NORMAL action in an anomalous context). The stealth cases
    # ensure the `action` feature alone cannot separate classes, so the models
    # must learn contextual/temporal patterns — a non-trivial benchmark.
    scenario = rng.choice(
        (
            "priv_action",          # overt: privilege_change / delete
            "bulk_sensitive",       # overt-ish: bulk_download of sensitive data
            "off_hours_sensitive",  # stealth: normal action, off-hours, sensitive
            "cross_dept_normal",    # stealth: normal action, other department
            "unknown_device",       # stealth: normal action, unmanaged device + external IP
        )
    )
    resource = _choose_resource_for_user(rng, resources, user["department"])
    action = rng.choice(NORMAL_ACTIONS)
    source_ip = _office_ip(rng)
    device_id = user["device_id"]
    event_time = occurred_at

    if scenario == "priv_action":
        action = rng.choice(("privilege_change", "delete"))
        resource = rng.choice(resources)
    elif scenario == "bulk_sensitive":
        action = "bulk_download"
        resource = rng.choice(
            [item for item in resources if item["resource_class"] in ("PII", "financial")]
        )
    elif scenario == "off_hours_sensitive":
        event_time = occurred_at.replace(hour=rng.choice((1, 2, 3, 23)))
        resource = rng.choice(
            [item for item in resources if item["resource_class"] in ("PII", "financial")]
        )
        action = rng.choice(("read", "download", "search"))
    elif scenario == "cross_dept_normal":
        resource = rng.choice([item for item in resources if item["department"] != user["department"]])
        action = rng.choice(("read", "download"))
    elif scenario == "unknown_device":
        device_id = f"unmanaged-{rng.randint(1000, 9999)}"
        source_ip = f"198.51.100.{rng.randint(1, 254)}"
        action = rng.choice(NORMAL_ACTIONS)

    return AccessEvent(
        event_id=str(uuid4()),
        event_type="access",
        occurred_at=event_time.isoformat(),
        user_id=user["user_id"],
        role=user["role"],
        department=user["department"],
        resource_id=resource["resource_id"],
        resource_class=resource["resource_class"],
        action=action,
        source_ip=source_ip,
        device_id=device_id,
        session_id=f"session-{user['user_id']}-{event_time:%Y%m%d}",
        is_anomaly=True,
        anomaly_reason=scenario,
    )


def _office_ip(rng: random.Random) -> str:
    return f"10.{rng.randint(1, 12)}.{rng.randint(0, 255)}.{rng.randint(1, 254)}"
