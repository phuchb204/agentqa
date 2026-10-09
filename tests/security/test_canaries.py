from __future__ import annotations

import pytest
import sqlalchemy as sa

from agentqa.platform.security.redaction import REDACTED, RedactionService
from agentqa.platform.security.taint import SecretLeakError, TaintRegistry
from agentqa.platform.storage import tables
from agentqa.platform.storage.roles import ROLE_API
from tests.support.postgres import fetch_all, scoped_transaction, seed_workspace
from tests.support.security import create_user

pytestmark = pytest.mark.asyncio

CANARY = "canary-synthetic-4b91d0"


async def test_redaction_service_replaces_registered_values() -> None:
    registry = TaintRegistry()
    service = RedactionService(registry)
    service.register(CANARY)
    assert CANARY not in service.redact_text(f"login failed for {CANARY}")
    structured = service.redact_structure({"password": CANARY, "nested": [f"prefix-{CANARY}"]})
    assert structured["password"] == REDACTED
    assert CANARY not in str(structured)
    error = RuntimeError(f"upstream rejected {CANARY}")
    assert CANARY not in service.safe_error_message(error)


async def test_taint_registry_blocks_secret_at_sink() -> None:
    registry = TaintRegistry()
    registry.register(CANARY)
    registry.assert_clean({"safe": "value"}, "test-sink")
    with pytest.raises(SecretLeakError) as error:
        registry.assert_clean({"leak": f"Bearer {CANARY}"}, "log-sink")
    assert CANARY not in str(error.value)
    assert registry.find([CANARY]) == [CANARY]


async def test_login_error_path_does_not_leak_canary(api_client, runtime) -> None:
    runtime.taint.register(CANARY)
    _user_id, username = await create_user(runtime, "canary", "pw-123456")
    response = await api_client.post("/api/v1/auth/login", json={"username": username, "password": CANARY})
    assert response.status_code == 401
    assert runtime.taint.find(response.text) == []
    assert CANARY not in response.text


async def test_credential_pipeline_keeps_canary_out_of_sinks(runtime, role_engines: dict) -> None:
    runtime.taint.register(CANARY)
    principal, workspace = await seed_workspace(role_engines)
    async with scoped_transaction(runtime.engines[ROLE_API], principal_id=principal, workspace_id=workspace) as session:
        record = await runtime.credentials.create_envelope(
            session, workspace_id=workspace, credential_ref="provider/canary", plaintext=CANARY, actor="owner"
        )
        value = await runtime.credentials.resolve(
            session, workspace_id=workspace, credential_id=record.credential_id, version=record.version
        )
        metadata = await runtime.credentials.public_metadata(
            session, workspace_id=workspace, credential_id=record.credential_id
        )
        audit_rows = (
            await session.execute(sa.select(tables.audit_events.c.event_metadata, tables.audit_events.c.subject_id))
        ).all()
        credential_rows = (
            await session.execute(
                sa.select(
                    tables.credential_records.c.aad,
                    tables.credential_records.c.ciphertext,
                    tables.credential_records.c.wrapped_data_key,
                )
            )
        ).all()

    assert value.reveal() == CANARY
    sinks = [str(metadata), str(audit_rows), str(record), repr(value)]
    for sink in sinks:
        assert runtime.taint.find(sink) == []
    assert all(CANARY not in str(row) for row in credential_rows)

    redacted = runtime.redaction.redact_structure({"metadata": metadata, "audit": [str(row) for row in audit_rows]})
    runtime.taint.assert_clean(redacted, "export-sink")


async def test_session_and_token_tables_never_hold_raw_values(runtime, test_db) -> None:
    user_id, username = await create_user(runtime, "canary-user", "pw-123456")
    result = await runtime.sessions.login(username=username, password="pw-123456")
    issued = await runtime.tokens.create(user_id=user_id, name="ci")
    session_rows = await fetch_all(
        test_db.dsn(ROLE_API),
        "SELECT s.token_hash, s.csrf_hash FROM sessions s JOIN users u ON u.id = s.user_id WHERE u.username = :name",
        {"name": username},
    )
    token_rows = await fetch_all(
        test_db.dsn(ROLE_API),
        "SELECT token_hash FROM api_tokens WHERE user_id = :user_id",
        {"user_id": user_id},
    )
    assert result.raw_token not in str(session_rows)
    assert result.csrf_token not in str(session_rows)
    assert issued.raw_token not in str(token_rows)
    assert session_rows[0][0] != result.raw_token
    assert token_rows[0][0] != issued.raw_token
