"""Centralised AWS session construction for AI-EDGE.

Account/region selection lives in one place so switching AWS accounts later is a
single config change (an env var), mirroring the Terraform ``aws_profile``
variable. Resolution order for the profile:

1. ``AIEDGE_AWS_PROFILE`` (project-specific override)
2. ``AWS_PROFILE`` (standard AWS env var)
3. none -> boto3's default credential chain

Region resolves from ``AIEDGE_AWS_REGION`` then ``AWS_REGION`` /
``AWS_DEFAULT_REGION``, falling back to ``us-east-1`` to match the Terraform
default.
"""

from __future__ import annotations

import os
from functools import cache
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # avoid importing boto3 at module load / for type-checkers only
    import boto3

DEFAULT_REGION = "us-east-1"


def resolve_profile() -> str | None:
    """Return the AWS profile name to use, or None for the default chain."""
    profile = os.environ.get("AIEDGE_AWS_PROFILE") or os.environ.get("AWS_PROFILE")
    return profile or None


def resolve_region() -> str:
    """Return the AWS region, falling back to the Terraform default."""
    return (
        os.environ.get("AIEDGE_AWS_REGION")
        or os.environ.get("AWS_REGION")
        or os.environ.get("AWS_DEFAULT_REGION")
        or DEFAULT_REGION
    )


@cache
def get_session() -> boto3.Session:
    """Build a boto3 Session honoring the resolved profile and region.

    Cached so repeated calls reuse one session. boto3 is imported lazily so the
    package (and its tests) load without boto3 credentials configured.
    """
    import boto3

    return boto3.Session(profile_name=resolve_profile(), region_name=resolve_region())
