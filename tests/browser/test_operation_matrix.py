from __future__ import annotations

import asyncio
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

from agentqa.agent.browser.contexts import origin_of
from agentqa.agent.browser.files import DirectoryFileResolver
from agentqa.contracts.actions import ActionOutcome, Operation
from agentqa.contracts.identity import LocatorAlternative, LocatorKind, TargetDescriptor
from agentqa.contracts.values import LiteralValue
from agentqa.platform.fixtures import FixtureRegistry, synthetic_password
from agentqa.platform.security.egress import AllowedEndpoint
from tests.support.browser import action_command as command
from tests.support.browser import run_async, start_stack
from tests.support.taskboard import TaskboardServer


def taskboard_endpoint(server: TaskboardServer) -> AllowedEndpoint:
    parts = urlsplit(server.base_url)
    return AllowedEndpoint(host="127.0.0.1", port=parts.port or 80, addresses=("127.0.0.1",))


def button(name: str) -> TargetDescriptor:
    return TargetDescriptor(intent=name, role="button", name=name)


def link(name: str) -> TargetDescriptor:
    return TargetDescriptor(intent=name, role="link", name=name)


def text_target(value: str) -> TargetDescriptor:
    return TargetDescriptor(
        intent=value,
        locators=[LocatorAlternative(kind=LocatorKind.TEXT, value=value)],
    )


async def _text(page, element_id: str) -> str:
    return await page.evaluate(f"() => (document.getElementById('{element_id}') || {{}}).textContent || ''")


async def _input_value(page, element_id: str) -> str:
    return await page.evaluate(f"() => (document.getElementById('{element_id}') || {{}}).value || ''")


async def _login_and_open_lab(stack, server: TaskboardServer, namespace: str, run_id) -> None:
    key = str(run_id)
    await stack.session.contexts.open(key, allowed_origins=(origin_of(server.base_url),))
    await stack.action_port.dispatch(
        command(
            run_id, Operation.NAVIGATE, value=LiteralValue(kind="literal", value=f"{server.base_url}/{namespace}/login")
        )
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
                intent="password", locators=[LocatorAlternative(kind=LocatorKind.LABEL, value="Mật khẩu")]
            ),
            value=LiteralValue(kind="literal", value=synthetic_password(namespace, "alice")),
        )
    )
    await stack.action_port.dispatch(command(run_id, Operation.CLICK, target=button("Đăng nhập")))
    receipt = await stack.action_port.dispatch(
        command(
            run_id, Operation.NAVIGATE, value=LiteralValue(kind="literal", value=f"{server.base_url}/{namespace}/lab")
        )
    )
    assert receipt.outcome == ActionOutcome.SUCCEEDED


def test_capability_inventory_has_no_placeholder() -> None:
    from agentqa.agent.browser.action_registry import build_capability_registry

    registry = build_capability_registry()
    assert set(registry) == set(Operation)
    assert all(capability.implemented for capability in registry.values())
    assert registry[Operation.UPLOAD].requires_target and registry[Operation.UPLOAD].requires_value
    assert registry[Operation.EXPECT_DOWNLOAD].requires_target is False


def test_operation_matrix_full_flow(
    taskboard_server: TaskboardServer, fixture_registry: FixtureRegistry, tmp_path: Path
) -> None:
    namespace = "ops-matrix"
    assert fixture_registry.prepare("taskboard@1", namespace).ok
    run_id = uuid4()
    upload_root = tmp_path / "catalog"
    upload_root.mkdir()
    (upload_root / "anh.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32)

    async def scenario() -> None:
        stack = await start_stack(
            temp_root=tmp_path,
            endpoints=[taskboard_endpoint(taskboard_server)],
            file_resolver=DirectoryFileResolver(upload_root),
        )
        try:
            await _login_and_open_lab(stack, taskboard_server, namespace, run_id)
            key = str(run_id)
            page = await stack.session.contexts.page(key)

            wait = await stack.action_port.dispatch(
                command(
                    run_id, Operation.WAIT, target=TargetDescriptor(intent="lab", role="heading", name="Phòng thao tác")
                )
            )
            assert wait.outcome == ActionOutcome.SUCCEEDED

            dbl = await stack.action_port.dispatch(command(run_id, Operation.DOUBLE_CLICK, target=button("Nhấp đôi")))
            assert dbl.outcome == ActionOutcome.SUCCEEDED
            assert await _text(page, "dbl-count") == "1"

            typed = await stack.action_port.dispatch(
                command(
                    run_id,
                    Operation.TYPE,
                    target=TargetDescriptor(intent="lab_text", role="textbox", name="Ô nhập văn bản"),
                    value=LiteralValue(kind="literal", value="xin chào"),
                )
            )
            assert typed.outcome == ActionOutcome.SUCCEEDED
            assert await _input_value(page, "lab-text") == "xin chào"
            assert await _text(page, "lab-echo") == "xin chào"

            cleared = await stack.action_port.dispatch(
                command(
                    run_id,
                    Operation.CLEAR,
                    target=TargetDescriptor(intent="lab_text", role="textbox", name="Ô nhập văn bản"),
                )
            )
            assert cleared.outcome == ActionOutcome.SUCCEEDED
            assert await _input_value(page, "lab-text") == ""

            await stack.action_port.dispatch(
                command(
                    run_id,
                    Operation.FILL,
                    target=TargetDescriptor(intent="lab_press", role="textbox", name="Ô nhập phím"),
                    value=LiteralValue(kind="literal", value="abc"),
                )
            )
            pressed = await stack.action_port.dispatch(
                command(
                    run_id,
                    Operation.PRESS,
                    target=TargetDescriptor(intent="lab_press", role="textbox", name="Ô nhập phím"),
                    value=LiteralValue(kind="literal", value="Enter"),
                )
            )
            assert pressed.outcome == ActionOutcome.SUCCEEDED
            assert await _text(page, "lab-press-echo") == "key:Enter"

            check = await stack.action_port.dispatch(
                command(
                    run_id, Operation.CHECK, target=TargetDescriptor(intent="lab_check", role="checkbox", name="Bật")
                )
            )
            assert check.outcome == ActionOutcome.SUCCEEDED
            assert await page.is_checked("#lab-check") is True
            uncheck = await stack.action_port.dispatch(
                command(
                    run_id, Operation.UNCHECK, target=TargetDescriptor(intent="lab_check", role="checkbox", name="Bật")
                )
            )
            assert uncheck.outcome == ActionOutcome.SUCCEEDED
            assert await page.is_checked("#lab-check") is False

            select = await stack.action_port.dispatch(
                command(
                    run_id,
                    Operation.SELECT,
                    target=TargetDescriptor(intent="lab_select", role="combobox", name="Chọn mục"),
                    value=LiteralValue(kind="literal", value="hai"),
                )
            )
            assert select.outcome == ActionOutcome.SUCCEEDED
            assert await _text(page, "lab-select-value") == "hai"

            hover = await stack.action_port.dispatch(command(run_id, Operation.HOVER, target=text_target("Vùng rê")))
            assert hover.outcome == ActionOutcome.SUCCEEDED
            assert await page.is_visible("#hover-secret") is True

            scroll = await stack.action_port.dispatch(
                command(run_id, Operation.SCROLL, target=text_target("Cuối vùng cuộn"))
            )
            assert scroll.outcome == ActionOutcome.SUCCEEDED

            upload = await stack.action_port.dispatch(
                command(
                    run_id,
                    Operation.UPLOAD,
                    target=TargetDescriptor(
                        intent="lab_file", locators=[LocatorAlternative(kind=LocatorKind.LABEL, value="Tệp tải lên")]
                    ),
                    value=LiteralValue(kind="literal", value="anh.png"),
                )
            )
            assert upload.outcome == ActionOutcome.SUCCEEDED
            assert await _text(page, "lab-file-name") == "anh.png"

            missing_file = await stack.action_port.dispatch(
                command(
                    run_id,
                    Operation.UPLOAD,
                    target=TargetDescriptor(
                        intent="lab_file", locators=[LocatorAlternative(kind=LocatorKind.LABEL, value="Tệp tải lên")]
                    ),
                    value=LiteralValue(kind="literal", value="../escape.png"),
                )
            )
            assert missing_file.outcome == ActionOutcome.REJECTED
            assert missing_file.evidence_refs == ["file_id_unknown"]

            shadow = await stack.action_port.dispatch(command(run_id, Operation.CLICK, target=button("Nút shadow")))
            assert shadow.outcome == ActionOutcome.SUCCEEDED
            assert await _text(page, "lab-shadow-count") == "1"

            rule = await stack.action_port.dispatch(
                command(
                    run_id,
                    Operation.HANDLE_DIALOG,
                    value=LiteralValue(kind="literal", value={"action": "accept", "expected_prompt": "Xác nhận"}),
                )
            )
            assert rule.outcome == ActionOutcome.SUCCEEDED
            dialog_click = await stack.action_port.dispatch(
                command(run_id, Operation.CLICK, target=button("Mở hộp thoại"))
            )
            assert dialog_click.outcome == ActionOutcome.SUCCEEDED
            for _ in range(40):
                if await _text(page, "lab-dialog-result") == "đồng ý":
                    break
                await asyncio.sleep(0.05)
            assert await _text(page, "lab-dialog-result") == "đồng ý"

            await stack.action_port.dispatch(
                command(
                    run_id,
                    Operation.HANDLE_DIALOG,
                    value=LiteralValue(kind="literal", value={"action": "dismiss"}),
                )
            )
            await stack.action_port.dispatch(command(run_id, Operation.CLICK, target=button("Mở hộp thoại")))
            for _ in range(40):
                if await _text(page, "lab-dialog-result") == "từ chối":
                    break
                await asyncio.sleep(0.05)
            assert await _text(page, "lab-dialog-result") == "từ chối"

            frame = await stack.action_port.dispatch(
                command(run_id, Operation.SWITCH_FRAME, value=LiteralValue(kind="literal", value="lab-frame"))
            )
            assert frame.outcome == ActionOutcome.SUCCEEDED
            frame_click = await stack.action_port.dispatch(
                command(run_id, Operation.CLICK, target=button("Nút trong khung"))
            )
            assert frame_click.outcome == ActionOutcome.SUCCEEDED
            frame_button = stack.session.contexts.lane(key)
            assert frame_button.active_frame_key == "lab-frame"
            await stack.action_port.dispatch(
                command(run_id, Operation.SWITCH_FRAME, value=LiteralValue(kind="literal", value="main"))
            )
            assert stack.session.contexts.lane(key).active_frame_key is None
            back = await stack.action_port.dispatch(command(run_id, Operation.DOUBLE_CLICK, target=button("Nhấp đôi")))
            assert back.outcome == ActionOutcome.SUCCEEDED
            assert await _text(page, "dbl-count") == "2"

            download_click = await stack.action_port.dispatch(
                command(run_id, Operation.CLICK, target=link("Tải báo cáo"))
            )
            assert download_click.outcome == ActionOutcome.SUCCEEDED
            download = await stack.action_port.dispatch(command(run_id, Operation.EXPECT_DOWNLOAD))
            assert download.outcome == ActionOutcome.SUCCEEDED
            records = stack.read_port.download_records(key)
            assert records and records[-1].filename == "bao-cao.txt"
            assert records[-1].sha256 is not None
            assert records[-1].size_bytes and records[-1].size_bytes > 0

            new_tab = await stack.action_port.dispatch(command(run_id, Operation.CLICK, target=link("Mở tab phụ")))
            assert new_tab.outcome == ActionOutcome.SUCCEEDED
            for _ in range(40):
                if len(stack.session.contexts.lane(key).context.pages) >= 2:
                    break
                await asyncio.sleep(0.05)
            switch = await stack.action_port.dispatch(
                command(run_id, Operation.SWITCH_PAGE, value=LiteralValue(kind="literal", value="phu"))
            )
            assert switch.outcome == ActionOutcome.SUCCEEDED, switch.evidence_refs
            aux_page = await stack.session.contexts.page(key, "phu")
            assert aux_page.url.endswith("/lab/aux")
        finally:
            await stack.aclose()

    run_async(scenario())
