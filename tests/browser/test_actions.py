from __future__ import annotations

from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

from agentqa.contracts.actions import ActionOutcome, Operation
from agentqa.contracts.case import ComparisonCondition
from agentqa.contracts.identity import EntityScope, LocatorAlternative, LocatorKind, TargetDescriptor
from agentqa.contracts.values import LiteralValue, SecretValue
from agentqa.platform.fixtures import FixtureRegistry, synthetic_password
from agentqa.platform.security.egress import AllowedEndpoint
from tests.support.browser import FakeSecretBroker, run_async, start_stack
from tests.support.browser import action_command as command
from tests.support.taskboard import TaskboardServer


def taskboard_endpoint(server: TaskboardServer) -> AllowedEndpoint:
    parts = urlsplit(server.base_url)
    return AllowedEndpoint(host="127.0.0.1", port=parts.port or 80, addresses=("127.0.0.1",))


def by_text(name: str) -> TargetDescriptor:
    return TargetDescriptor(intent=name, role="button", name=name)


def test_navigate_fill_click_wait_and_probe_flow(
    taskboard_server: TaskboardServer, fixture_registry: FixtureRegistry, tmp_path: Path
) -> None:
    namespace = "actions-flow"
    assert fixture_registry.prepare("taskboard@1", namespace).ok
    run_id = uuid4()

    async def scenario() -> None:
        stack = await start_stack(temp_root=tmp_path, endpoints=[taskboard_endpoint(taskboard_server)])
        try:
            await stack.session.contexts.open(str(run_id), allowed_origins=("http://127.0.0.1",))
            login_url = f"{taskboard_server.base_url}/{namespace}/login"
            receipt = await stack.action_port.dispatch(
                command(run_id, Operation.NAVIGATE, value=LiteralValue(kind="literal", value=login_url))
            )
            assert receipt.outcome == ActionOutcome.SUCCEEDED
            assert receipt.side_effect.value == "read"

            receipt = await stack.action_port.dispatch(
                command(
                    run_id,
                    Operation.FILL,
                    target=TargetDescriptor(intent="username", role="textbox", name="Tài khoản"),
                    value=LiteralValue(kind="literal", value="alice"),
                )
            )
            assert receipt.outcome == ActionOutcome.SUCCEEDED

            receipt = await stack.action_port.dispatch(
                command(
                    run_id,
                    Operation.FILL,
                    target=TargetDescriptor(
                        intent="password",
                        locators=[LocatorAlternative(kind=LocatorKind.LABEL, value="Mật khẩu")],
                    ),
                    value=LiteralValue(kind="literal", value=synthetic_password(namespace, "alice")),
                )
            )
            assert receipt.outcome == ActionOutcome.SUCCEEDED

            receipt = await stack.action_port.dispatch(command(run_id, Operation.CLICK, target=by_text("Đăng nhập")))
            assert receipt.outcome == ActionOutcome.SUCCEEDED
            assert receipt.side_effect.value == "external_write"

            receipt = await stack.action_port.dispatch(
                command(
                    run_id,
                    Operation.WAIT,
                    target=TargetDescriptor(intent="heading", role="heading", name="Danh sách việc"),
                )
            )
            assert receipt.outcome == ActionOutcome.SUCCEEDED
            probe = await stack.read_port.probe(
                ComparisonCondition(
                    kind="comparison",
                    comparator="count_equals",
                    target=TargetDescriptor(intent="rows", role="listitem"),
                    expected=LiteralValue(kind="literal", value=0),
                ),
                str(run_id),
            )
            assert probe.satisfied is True

            await stack.action_port.dispatch(
                command(
                    run_id,
                    Operation.FILL,
                    target=TargetDescriptor(intent="new_item", role="textbox", name="Việc mới"),
                    value=LiteralValue(kind="literal", value="Việc kiểm thử"),
                )
            )
            await stack.action_port.dispatch(command(run_id, Operation.CLICK, target=by_text("Thêm việc")))
            probe = await stack.read_port.probe(
                ComparisonCondition(
                    kind="comparison",
                    comparator="count_equals",
                    target=TargetDescriptor(
                        intent="row",
                        role="listitem",
                        entity_scope=EntityScope(
                            field="text", value=LiteralValue(kind="literal", value="Việc kiểm thử")
                        ),
                    ),
                    expected=LiteralValue(kind="literal", value=1),
                ),
                str(run_id),
            )
            assert probe.satisfied is True
        finally:
            await stack.aclose()

    run_async(scenario())


def test_unsupported_operation_is_rejected_not_noop(taskboard_server: TaskboardServer, tmp_path: Path) -> None:
    run_id = uuid4()

    async def scenario() -> None:
        stack = await start_stack(temp_root=tmp_path, endpoints=[taskboard_endpoint(taskboard_server)])
        try:
            await stack.session.contexts.open(str(run_id))
            assert stack.action_port.capability(Operation.UPLOAD).implemented is False
            assert Operation.UPLOAD not in stack.action_port.supported_operations
            receipt = await stack.action_port.dispatch(command(run_id, Operation.UPLOAD, target=by_text("Không dùng")))
            assert receipt.outcome == ActionOutcome.REJECTED
            assert receipt.evidence_refs == ["capability_unavailable"]
        finally:
            await stack.aclose()

    run_async(scenario())


def test_missing_and_ambiguous_targets_are_rejected(
    taskboard_server: TaskboardServer, fixture_registry: FixtureRegistry, tmp_path: Path
) -> None:
    namespace = "actions-ambiguous"
    assert fixture_registry.prepare("taskboard@1", namespace, seed="wrong_entity").ok
    run_id = uuid4()

    async def scenario() -> None:
        stack = await start_stack(temp_root=tmp_path, endpoints=[taskboard_endpoint(taskboard_server)])
        try:
            await stack.session.contexts.open(str(run_id))
            login_url = f"{taskboard_server.base_url}/{namespace}/login"
            await stack.action_port.dispatch(
                command(run_id, Operation.NAVIGATE, value=LiteralValue(kind="literal", value=login_url))
            )
            await stack.action_port.dispatch(
                command(
                    run_id,
                    Operation.FILL,
                    target=TargetDescriptor(intent="username", role="textbox", name="Tài khoản"),
                    value=LiteralValue(kind="literal", value="alice"),
                )
            )
            await stack.action_port.dispatch(
                command(
                    run_id,
                    Operation.FILL,
                    target=TargetDescriptor(
                        intent="password",
                        locators=[LocatorAlternative(kind=LocatorKind.LABEL, value="Mật khẩu")],
                    ),
                    value=LiteralValue(kind="literal", value=synthetic_password(namespace, "alice")),
                )
            )
            login = await stack.action_port.dispatch(command(run_id, Operation.CLICK, target=by_text("Đăng nhập")))
            assert login.outcome == ActionOutcome.SUCCEEDED
            wait = await stack.action_port.dispatch(
                command(
                    run_id,
                    Operation.WAIT,
                    target=TargetDescriptor(intent="heading", role="heading", name="Danh sách việc"),
                )
            )
            assert wait.outcome == ActionOutcome.SUCCEEDED

            missing = await stack.action_port.dispatch(
                command(run_id, Operation.CLICK, target=by_text("Không tồn tại"))
            )
            assert missing.outcome == ActionOutcome.REJECTED
            assert missing.evidence_refs == ["locator_missing"]

            scoped = TargetDescriptor(
                intent="delete_row",
                role="button",
                name="Xoá",
                entity_scope=EntityScope(field="text", value=LiteralValue(kind="literal", value="Việc giống nhau")),
            )
            ambiguous = await stack.action_port.dispatch(command(run_id, Operation.CLICK, target=scoped))
            assert ambiguous.outcome == ActionOutcome.REJECTED
            assert ambiguous.evidence_refs == ["locator_ambiguous"]
        finally:
            await stack.aclose()

    run_async(scenario())


def test_duplicate_command_id_returns_same_receipt(tmp_path: Path, taskboard_server: TaskboardServer) -> None:
    run_id = uuid4()

    async def scenario() -> None:
        stack = await start_stack(temp_root=tmp_path, endpoints=[taskboard_endpoint(taskboard_server)])
        try:
            await stack.session.contexts.open(str(run_id))
            first = command(
                run_id,
                Operation.NAVIGATE,
                value=LiteralValue(kind="literal", value=f"{taskboard_server.base_url}/demo/login"),
            )
            receipt_one = await stack.action_port.dispatch(first)
            receipt_two = await stack.action_port.dispatch(first)
            assert receipt_one == receipt_two
            assert receipt_two.outcome == ActionOutcome.SUCCEEDED
        finally:
            await stack.aclose()

    run_async(scenario())


def test_stale_scene_version_is_rejected_without_dispatch(taskboard_server: TaskboardServer, tmp_path: Path) -> None:
    run_id = uuid4()

    async def scenario() -> None:
        stack = await start_stack(temp_root=tmp_path, endpoints=[taskboard_endpoint(taskboard_server)])
        try:
            await stack.session.contexts.open(str(run_id))
            await stack.read_port.observe(str(run_id))
            lane = stack.session.contexts.lane(str(run_id))
            assert lane.observation_version == 2
            receipt = await stack.action_port.dispatch(
                command(
                    run_id,
                    Operation.NAVIGATE,
                    value=LiteralValue(kind="literal", value=f"{taskboard_server.base_url}/demo/login"),
                    observation_version=1,
                )
            )
            assert receipt.outcome == ActionOutcome.REJECTED
            assert receipt.evidence_refs == ["scene_stale"]
        finally:
            await stack.aclose()

    run_async(scenario())


def test_secret_fill_resolves_after_guard_and_stays_redacted(
    taskboard_server: TaskboardServer, fixture_registry: FixtureRegistry, tmp_path: Path
) -> None:
    namespace = "actions-secret"
    assert fixture_registry.prepare("taskboard@1", namespace).ok
    run_id = uuid4()
    secret_value = "tb-canary-secret-77"
    broker = FakeSecretBroker(secret=secret_value)

    async def scenario() -> None:
        stack = await start_stack(
            temp_root=tmp_path,
            endpoints=[taskboard_endpoint(taskboard_server)],
            secret_broker=broker,
        )
        try:
            await stack.session.contexts.open(str(run_id))
            login_url = f"{taskboard_server.base_url}/{namespace}/login"
            await stack.action_port.dispatch(
                command(run_id, Operation.NAVIGATE, value=LiteralValue(kind="literal", value=login_url))
            )
            missing_password = TargetDescriptor(intent="missing", role="textbox", name="Không tồn tại")
            rejected = await stack.action_port.dispatch(
                command(
                    run_id,
                    Operation.FILL,
                    target=missing_password,
                    value=SecretValue(kind="secret", credential_ref="taskboard.alice.password"),
                    grant_refs=["grant-denied"],
                )
            )
            assert rejected.outcome == ActionOutcome.REJECTED
            assert broker.calls == []

            receipt = await stack.action_port.dispatch(
                command(
                    run_id,
                    Operation.FILL,
                    target=TargetDescriptor(
                        intent="password",
                        locators=[LocatorAlternative(kind=LocatorKind.LABEL, value="Mật khẩu")],
                    ),
                    value=SecretValue(kind="secret", credential_ref="taskboard.alice.password"),
                    grant_refs=["grant-1"],
                )
            )
            assert receipt.outcome == ActionOutcome.SUCCEEDED
            assert broker.calls == ["grant-1"]
            assert receipt.evidence_refs == ["fill:secret_redacted"]
            assert secret_value not in receipt.model_dump_json()
            assert stack.evidence.history[-1]["value"] == "[REDACTED]"
            assert secret_value in stack.taint.values
            assert all(secret_value.encode() not in payload for payload in stack.sink.payloads())
            redacted_url = stack.evidence.sanitize_url(f"{taskboard_server.base_url}/x?token={secret_value}")
            assert secret_value not in redacted_url
            assert "REDACTED" in redacted_url
        finally:
            await stack.aclose()

    run_async(scenario())


def test_entity_attributes_disambiguate_duplicate_rows(
    taskboard_server: TaskboardServer, fixture_registry: FixtureRegistry, tmp_path: Path
) -> None:
    namespace = "actions-target"
    assert fixture_registry.prepare("taskboard@1", namespace, seed="wrong_entity").ok
    run_id = uuid4()

    async def scenario() -> None:
        stack = await start_stack(temp_root=tmp_path, endpoints=[taskboard_endpoint(taskboard_server)])
        try:
            await stack.session.contexts.open(str(run_id))
            login_url = f"{taskboard_server.base_url}/{namespace}/login"
            await stack.action_port.dispatch(
                command(run_id, Operation.NAVIGATE, value=LiteralValue(kind="literal", value=login_url))
            )
            await stack.action_port.dispatch(
                command(
                    run_id,
                    Operation.FILL,
                    target=TargetDescriptor(intent="username", role="textbox", name="Tài khoản"),
                    value=LiteralValue(kind="literal", value="alice"),
                )
            )
            await stack.action_port.dispatch(
                command(
                    run_id,
                    Operation.FILL,
                    target=TargetDescriptor(
                        intent="password",
                        locators=[LocatorAlternative(kind=LocatorKind.LABEL, value="Mật khẩu")],
                    ),
                    value=LiteralValue(kind="literal", value=synthetic_password(namespace, "alice")),
                )
            )
            await stack.action_port.dispatch(command(run_id, Operation.CLICK, target=by_text("Đăng nhập")))
            await stack.action_port.dispatch(
                command(
                    run_id,
                    Operation.WAIT,
                    target=TargetDescriptor(intent="heading", role="heading", name="Danh sách việc"),
                )
            )
            target = TargetDescriptor(
                intent="delete_second_row",
                role="button",
                name="Xoá",
                attributes={"data-item-id": "item-2"},
            )
            receipt = await stack.action_port.dispatch(command(run_id, Operation.CLICK, target=target))
            assert receipt.outcome == ActionOutcome.SUCCEEDED
            probe = fixture_registry.probe("taskboard@1", namespace)
            assert probe["item_count"] == 1
            assert probe["last_write_target"]["entity_id"] == "item-2"
        finally:
            await stack.aclose()

    run_async(scenario())
