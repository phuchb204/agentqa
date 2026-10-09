from __future__ import annotations

import json
from hashlib import sha256
from typing import Any

from pydantic import BaseModel

from agentqa.contracts.case import CaseContent
from agentqa.contracts.events import RunEvent
from agentqa.contracts.values import Money
from agentqa.platform.api.error_models import ErrorResponse

OPENAPI_NAME = "openapi"
OPENAPI_VERSION = "3.1"
OPENAPI_PATH = "schemas/openapi.json"

PUBLIC_SCHEMAS: dict[tuple[str, str], tuple[str, type[BaseModel]]] = {
    ("case", "1"): ("schemas/dsl/case/1.schema.json", CaseContent),
    ("run-event", "1"): ("schemas/events/run-event/1.schema.json", RunEvent),
    ("money", "1"): ("schemas/contracts/money/1.schema.json", Money),
    ("error", "1"): ("schemas/api/error/1.schema.json", ErrorResponse),
}


JSON_SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"


def canonical_json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"


def schema_document(name: str, version: str) -> dict[str, Any]:
    _, model = PUBLIC_SCHEMAS[(name, version)]
    document = model.model_json_schema()
    document["$schema"] = JSON_SCHEMA_DIALECT
    return document


def schema_json_text(name: str, version: str) -> str:
    return canonical_json_text(schema_document(name, version))


def catalog_relative_paths() -> list[str]:
    return [path for path, _ in PUBLIC_SCHEMAS.values()]


def build_catalog(artifacts: dict[str, str]) -> dict[str, Any]:
    entries: list[dict[str, str]] = []
    for name, version in sorted(PUBLIC_SCHEMAS):
        path, _ = PUBLIC_SCHEMAS[(name, version)]
        text = artifacts[path]
        entries.append(
            {
                "name": name,
                "version": version,
                "path": path,
                "digest": sha256(text.encode("utf-8")).hexdigest(),
            }
        )
    openapi_text = artifacts[OPENAPI_PATH]
    entries.append(
        {
            "name": OPENAPI_NAME,
            "version": OPENAPI_VERSION,
            "path": OPENAPI_PATH,
            "digest": sha256(openapi_text.encode("utf-8")).hexdigest(),
        }
    )
    release_material = "\n".join(f"{entry['name']}/{entry['version']}:{entry['digest']}" for entry in entries)
    return {
        "release_digest": sha256(release_material.encode("utf-8")).hexdigest(),
        "schemas": entries,
    }
