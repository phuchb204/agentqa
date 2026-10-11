from __future__ import annotations

from oracle.registry import (
    ORACLE_VERSION,
    record_for,
    registry_digest,
    registry_records,
    resolve_ref,
)
from oracle.variants import opportunities_for, publish_variant_manifests, variant_oracle_record

__all__ = [
    "ORACLE_VERSION",
    "opportunities_for",
    "publish_variant_manifests",
    "record_for",
    "registry_digest",
    "registry_records",
    "resolve_ref",
    "variant_oracle_record",
]
