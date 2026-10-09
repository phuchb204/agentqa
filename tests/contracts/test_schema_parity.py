from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import jsonschema
import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel, ValidationError

from agentqa.contracts.case import CaseContent
from agentqa.contracts.errors import AgentQAValidationError
from agentqa.contracts.events import RunEvent
from agentqa.contracts.values import Money
from agentqa.platform.api.application import api
from agentqa.platform.api.schemas import (
    JSON_SCHEMA_DIALECT,
    OPENAPI_PATH,
    PUBLIC_SCHEMAS,
    build_catalog,
    schema_document,
    schema_json_text,
)

REPO = Path(__file__).resolve().parents[2]
VECTORS_PATH = REPO / "schemas" / "vectors" / "parity.json"
MODELS: dict[str, type[BaseModel]] = {"case": CaseContent, "run-event": RunEvent, "money": Money}
FORBIDDEN_PUBLIC_NAMES = (
    "SensitiveValue",
    "SecretGrant",
    "BrowserReadPort",
    "BrowserActionPort",
    "VerificationPort",
    "IdentityPort",
    "SecretGrantPort",
    "oracle",
    "Oracle",
)


def load_vectors() -> list[dict[str, Any]]:
    return json.loads(VECTORS_PATH.read_text(encoding="utf-8"))["vectors"]


def json_schema_valid(schema: dict[str, Any], document: Any) -> bool:
    validator = jsonschema.Draft202012Validator(schema)
    return not list(validator.iter_errors(document))


def pydantic_valid(model: type[BaseModel], document: Any) -> bool:
    try:
        model.model_validate(document)
    except (ValidationError, AgentQAValidationError):
        return False
    return True


@pytest.mark.parametrize("vector", load_vectors(), ids=[vector["id"] for vector in load_vectors()])
def test_shared_vectors_on_python_side(vector: dict[str, Any]) -> None:
    schema = schema_document(vector["schema"]["name"], vector["schema"]["version"])
    assert json_schema_valid(schema, vector["document"]) is vector["valid"]
    assert pydantic_valid(MODELS[vector["schema"]["name"]], vector["document"]) is vector["valid"]


def test_generated_schemas_are_draft_2020_12() -> None:
    for name, version in PUBLIC_SCHEMAS:
        assert schema_document(name, version)["$schema"] == JSON_SCHEMA_DIALECT


def test_catalog_digests_match_generated_files() -> None:
    catalog = json.loads((REPO / "schemas" / "catalog.json").read_text(encoding="utf-8"))
    for entry in catalog["schemas"]:
        text = (REPO / entry["path"]).read_text(encoding="utf-8")
        assert hashlib.sha256(text.encode("utf-8")).hexdigest() == entry["digest"]
    artifacts: dict[str, str] = {}
    for (name, version), (path, _) in PUBLIC_SCHEMAS.items():
        artifacts[path] = schema_json_text(name, version)
    artifacts[OPENAPI_PATH] = (REPO / OPENAPI_PATH).read_text(encoding="utf-8")
    assert build_catalog(artifacts)["release_digest"] == catalog["release_digest"]


def test_public_surface_excludes_internal_types() -> None:
    catalog = json.loads((REPO / "schemas" / "catalog.json").read_text(encoding="utf-8"))
    names = {entry["name"] for entry in catalog["schemas"]}
    assert names == {"case", "run-event", "money", "error", "openapi"}
    for entry in catalog["schemas"]:
        text = (REPO / entry["path"]).read_text(encoding="utf-8")
        for forbidden in FORBIDDEN_PUBLIC_NAMES:
            assert forbidden not in text, f"{entry['path']} leaks {forbidden}"


def test_unknown_schema_version_has_no_document() -> None:
    with pytest.raises(KeyError):
        schema_document("case", "2")
    with pytest.raises(KeyError):
        schema_document("nope", "1")


def test_openapi_is_31_with_error_contract() -> None:
    openapi = api.openapi()
    assert openapi["openapi"].startswith("3.1")
    schemas = openapi["components"]["schemas"]
    assert "ErrorResponse" in schemas
    error_schema = schemas["ErrorResponse"]
    assert set(error_schema["required"]) >= {"code", "message"}


def test_schema_endpoint_serves_document_and_typed_404() -> None:
    client = TestClient(api)
    ok = client.get("/api/v1/schemas/case/1")
    assert ok.status_code == 200
    assert ok.json()["$schema"] == JSON_SCHEMA_DIALECT
    health = client.get("/health/live")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    missing = client.get("/api/v1/schemas/case/2")
    assert missing.status_code == 404
    body = missing.json()
    assert body["code"] == "not_found"
    assert body["retryable"] is False
    catalog_response = client.get("/api/v1/schemas")
    assert catalog_response.status_code == 200
    assert catalog_response.json()["schemas"]
