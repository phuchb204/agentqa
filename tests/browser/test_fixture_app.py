from __future__ import annotations

import time

import httpx
from playwright.async_api import Page, expect

from agentqa.platform.fixtures import FixtureRegistry, synthetic_password
from tests.support.browser import chromium_page, run_async
from tests.support.taskboard import TaskboardServer, alice_session, load_scenario


async def login(page: Page, server: TaskboardServer, namespace: str, username: str = "alice") -> None:
    await page.goto(f"{server.base_url}/{namespace}/login")
    await page.get_by_label("Tài khoản").fill(username)
    await page.get_by_label("Mật khẩu").fill(synthetic_password(namespace, username))
    await page.get_by_role("button", name="Đăng nhập").click()
    await page.wait_for_url(f"**/{namespace}/tasks")


def poll_probe(registry: FixtureRegistry, fixture_ref: str, namespace: str, predicate, timeout: float = 8.0):
    deadline = time.monotonic() + timeout
    probe = registry.probe(fixture_ref, namespace)
    while time.monotonic() < deadline and not predicate(probe):
        time.sleep(0.1)
        probe = registry.probe(fixture_ref, namespace)
    assert predicate(probe), probe
    return probe


def test_login_failure_is_recorded(taskboard_server: TaskboardServer, fixture_registry: FixtureRegistry) -> None:
    namespace = "login-failure"
    assert fixture_registry.prepare("taskboard@1", namespace).ok

    async def scenario() -> None:
        async with chromium_page() as page:
            await page.goto(f"{taskboard_server.base_url}/{namespace}/login")
            await page.get_by_label("Tài khoản").fill("alice")
            await page.get_by_label("Mật khẩu").fill("sai-mật-khẩu")
            await page.get_by_role("button", name="Đăng nhập").click()
            await expect(page.get_by_text("Sai tài khoản hoặc mật khẩu")).to_be_visible()

    run_async(scenario())
    probe = fixture_registry.probe("taskboard@1", namespace)
    assert probe["counters"].get("login_failed") == 1
    assert probe["counters"].get("login", 0) == 0


def test_login_and_create_item_success(taskboard_server: TaskboardServer, fixture_registry: FixtureRegistry) -> None:
    scenario_data = load_scenario("scenario_success")
    namespace = "create-success"
    assert fixture_registry.prepare("taskboard@1", namespace, seed=scenario_data["seed"]).ok

    async def scenario() -> None:
        async with chromium_page() as page:
            await login(page, taskboard_server, namespace)
            await page.get_by_label("Việc mới").fill(scenario_data["item_name"])
            await page.get_by_role("button", name="Thêm việc", exact=True).click()
            rows = page.locator("#task-list li")
            await expect(rows).to_have_count(scenario_data["expected"]["label_count"])
            await expect(rows.first.locator(".item-label")).to_have_text(scenario_data["item_name"])

    run_async(scenario())
    probe = fixture_registry.probe("taskboard@1", namespace)
    assert probe["label_counts"][scenario_data["item_name"]] == scenario_data["expected"]["label_count"]
    assert probe["counters"].get("item_created") == scenario_data["expected"]["item_created_events"]
    assert probe["counters"].get("duplicate_rejected", 0) == scenario_data["expected"]["duplicate_rejected_events"]
    assert probe["counters"].get("login") == 1


def test_duplicate_labels_target_sensor_distinguishes_entity(
    taskboard_server: TaskboardServer, fixture_registry: FixtureRegistry
) -> None:
    scenario_data = load_scenario("scenario_wrong_entity")
    namespace = "duplicate-rows"
    assert fixture_registry.prepare("taskboard@1", namespace, seed=scenario_data["seed"]).ok
    observed: dict[str, str | None] = {}

    async def scenario() -> None:
        async with chromium_page() as page:
            await login(page, taskboard_server, namespace)
            rows = page.locator("#task-list li")
            await expect(rows).to_have_count(scenario_data["expected"]["rows_same_label"])
            await expect(rows.nth(0).locator(".item-label")).to_have_text(scenario_data["same_label"])
            await expect(rows.nth(1).locator(".item-label")).to_have_text(scenario_data["same_label"])
            observed["first"] = await rows.nth(0).get_attribute("data-item-id")
            observed["second"] = await rows.nth(1).get_attribute("data-item-id")
            assert observed["first"] != observed["second"]
            await rows.nth(0).get_by_role("button", name="Xoá").click()
            await expect(rows).to_have_count(1)

    run_async(scenario())
    probe = fixture_registry.probe("taskboard@1", namespace)
    assert probe["item_count"] == 1
    assert probe["label_counts"][scenario_data["same_label"]] == 1
    assert probe["last_write_target"]["kind"] == "item_deleted"
    assert probe["last_write_target"]["entity_id"] == observed["first"]


def test_duplicate_policy_rejects_creation(
    taskboard_server: TaskboardServer, fixture_registry: FixtureRegistry
) -> None:
    scenario_data = load_scenario("scenario_duplicate")
    namespace = "duplicate-reject"
    assert fixture_registry.prepare("taskboard@1", namespace, seed=scenario_data["seed"]).ok

    async def scenario() -> None:
        async with chromium_page() as page:
            await login(page, taskboard_server, namespace)
            await page.get_by_label("Việc mới").fill(scenario_data["item_name"])
            await page.get_by_role("button", name="Thêm việc", exact=True).click()
            await expect(page.get_by_text("Nhãn không hợp lệ hoặc đã tồn tại")).to_be_visible()
            await expect(page.locator("#task-list li")).to_have_count(1)

    run_async(scenario())
    probe = fixture_registry.probe("taskboard@1", namespace)
    assert probe["label_counts"][scenario_data["item_name"]] == scenario_data["expected"]["label_count"]
    assert probe["counters"].get("duplicate_rejected") == scenario_data["expected"]["duplicate_rejected_events"]
    assert probe["counters"].get("item_created", 0) == scenario_data["expected"]["item_created_events"]


def test_async_outcome_unknown_then_settled(
    taskboard_server: TaskboardServer, fixture_registry: FixtureRegistry
) -> None:
    scenario_data = load_scenario("scenario_async")
    namespace = "async-unknown"
    assert fixture_registry.prepare("taskboard@1", namespace, seed=scenario_data["seed"]).ok

    async def scenario() -> None:
        async with chromium_page() as page:
            await login(page, taskboard_server, namespace)
            await page.get_by_label("Việc mới").fill(scenario_data["item_name"])
            await page.get_by_role("button", name="Thêm việc không chờ", exact=True).click()
            await expect(page.get_by_text("Đang xử lý")).to_be_visible()
            await page.wait_for_url(f"**/{namespace}/tasks", timeout=10000)
            await expect(page.locator("#task-list li")).to_have_count(1)

    run_async(scenario())
    probe = poll_probe(
        fixture_registry,
        "taskboard@1",
        namespace,
        lambda data: data["counters"].get("async_settled") == scenario_data["expected"]["async_settled_events"],
    )
    assert probe["label_counts"][scenario_data["item_name"]] == scenario_data["expected"]["label_count"]
    assert all(job["status"] == "succeeded" for job in probe["jobs"].values())


def test_reset_restores_seed_and_clears_side_effects(
    taskboard_server: TaskboardServer, fixture_registry: FixtureRegistry
) -> None:
    namespace = "reset-check"
    assert fixture_registry.prepare("taskboard@1", namespace).ok
    http = alice_session(taskboard_server.base_url, namespace)
    http.create_item(namespace, "Việc tạm")
    before = fixture_registry.probe("taskboard@1", namespace)
    assert before["counters"].get("item_created") == 1
    assert fixture_registry.reset("taskboard@1", namespace).ok
    after = fixture_registry.probe("taskboard@1", namespace)
    assert after["item_count"] == 0
    assert after["counters"].get("item_created", 0) == 0
    assert after["revision"] == 0


def test_namespace_isolation_and_cleanup(taskboard_server: TaskboardServer, fixture_registry: FixtureRegistry) -> None:
    scenario_data = load_scenario("scenario_isolation")
    namespace_a = "exec-a-attempt-1"
    namespace_b = "exec-a-attempt-2"
    assert fixture_registry.prepare("taskboard@1", namespace_a, seed=scenario_data["seed"]).ok
    assert fixture_registry.prepare("taskboard@1", namespace_b, seed=scenario_data["seed"]).ok
    http = alice_session(taskboard_server.base_url, namespace_a)
    http.create_item(namespace_a, "Việc mới của A")
    probe_a = fixture_registry.probe("taskboard@1", namespace_a)
    probe_b = fixture_registry.probe("taskboard@1", namespace_b)
    assert probe_a["label_counts"]["Việc mới của A"] == 1
    assert probe_a["item_count"] == scenario_data["expected"]["item_count"] + 1
    assert probe_b["item_count"] == scenario_data["expected"]["item_count"]
    assert "Việc mới của A" not in probe_b["label_counts"]
    assert probe_b["counters"].get("item_created", 0) == 0
    assert fixture_registry.cleanup("taskboard@1", namespace_a).ok
    with httpx.Client(timeout=5.0) as client:
        missing = client.get(
            f"{taskboard_server.base_url}/_control/namespaces/{namespace_a}/state",
            headers={"x-taskboard-control": taskboard_server.control_token},
        )
    assert missing.status_code == 404


def test_control_plane_requires_token_and_ground_truth_stays_private(
    taskboard_server: TaskboardServer, fixture_registry: FixtureRegistry
) -> None:
    namespace = "private-observations"
    assert fixture_registry.prepare("taskboard@1", namespace).ok
    with httpx.Client(timeout=5.0) as client:
        no_token = client.get(f"{taskboard_server.base_url}/_control/namespaces/{namespace}/probe")
        wrong_token = client.get(
            f"{taskboard_server.base_url}/_control/namespaces/{namespace}/probe",
            headers={"x-taskboard-control": "sai-token"},
        )
    assert no_token.status_code == 401
    assert wrong_token.status_code == 401

    async def scenario() -> None:
        async with chromium_page() as page:
            await page.goto(f"{taskboard_server.base_url}/{namespace}/login")
            login_html = await page.content()
            await login(page, taskboard_server, namespace)
            tasks_html = await page.content()
            for html in (login_html, tasks_html):
                assert "_control" not in html
                assert "probe" not in html
                assert "fixture_digest" not in html
                assert "duplicate_rejected" not in html
                assert "last_write_target" not in html

    run_async(scenario())
