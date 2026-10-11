from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

CATALOG_VERSION = "acceptance-catalog/1"

EXPECTED_AC = tuple(f"AC-{index:02d}" for index in range(1, 25))
EXPECTED_NFR = tuple(f"NFR-{index:02d}" for index in range(1, 13))


@dataclass(frozen=True)
class PytestCheck:
    id: str
    targets: tuple[str, ...]
    isolated: bool = False


@dataclass(frozen=True)
class CommandCheck:
    id: str
    command: tuple[str, ...]


@dataclass(frozen=True)
class ArtifactCheck:
    id: str
    tool: str
    path: str


@dataclass(frozen=True)
class FunctionCheck:
    id: str
    function: Callable[[Path], tuple[bool, str]]


CheckDef = PytestCheck | CommandCheck | ArtifactCheck | FunctionCheck


@dataclass(frozen=True)
class Scenario:
    id: str
    title: str
    business_effect: str
    proof: str
    denominator: str
    check_ids: tuple[str, ...]
    requirement_refs: tuple[str, ...] = ()


@dataclass(frozen=True)
class Catalog:
    version: str
    checks: tuple[CheckDef, ...]
    scenarios: tuple[Scenario, ...]

    def check_map(self) -> dict[str, CheckDef]:
        return {check.id: check for check in self.checks}

    def scenario_map(self) -> dict[str, Scenario]:
        return {scenario.id: scenario for scenario in self.scenarios}

    def referenced_check_ids(self) -> tuple[str, ...]:
        seen: list[str] = []
        for scenario in self.scenarios:
            for check_id in scenario.check_ids:
                if check_id not in seen:
                    seen.append(check_id)
        return tuple(seen)

    def subset_for_scenarios(self, scenario_ids: tuple[str, ...]) -> Catalog:
        wanted = set(scenario_ids)
        scenarios = tuple(scenario for scenario in self.scenarios if scenario.id in wanted)
        referenced = {check_id for scenario in scenarios for check_id in scenario.check_ids}
        checks = tuple(check for check in self.checks if check.id in referenced)
        return Catalog(version=self.version, checks=checks, scenarios=scenarios)


def check_kind(check: CheckDef) -> str:
    match check:
        case PytestCheck():
            return "pytest"
        case CommandCheck():
            return "command"
        case ArtifactCheck():
            return "artifact"
        case FunctionCheck():
            return "function"
    raise TypeError(f"check không hỗ trợ: {check!r}")


def validate_catalog(catalog: Catalog) -> list[str]:
    gaps: list[str] = []

    def gap(message: str) -> None:
        gaps.append(message)

    if catalog.version != CATALOG_VERSION:
        gap(f"catalog version không khớp: {catalog.version} != {CATALOG_VERSION}")

    check_ids = [check.id for check in catalog.checks]
    duplicates = sorted({item for item in check_ids if check_ids.count(item) > 1})
    for item in duplicates:
        gap(f"check id trùng: {item}")

    for check in catalog.checks:
        match check:
            case PytestCheck():
                if not check.targets:
                    gap(f"check {check.id}: pytest check thiếu targets")
            case CommandCheck():
                if not check.command:
                    gap(f"check {check.id}: command check thiếu command")
            case ArtifactCheck():
                if not check.tool or not check.path:
                    gap(f"check {check.id}: artifact check thiếu tool/path")
            case FunctionCheck():
                if not callable(check.function):
                    gap(f"check {check.id}: function check không callable")

    scenario_ids = [scenario.id for scenario in catalog.scenarios]
    duplicates = sorted({item for item in scenario_ids if scenario_ids.count(item) > 1})
    for item in duplicates:
        gap(f"scenario id trùng: {item}")

    expected = set(EXPECTED_AC) | set(EXPECTED_NFR)
    actual = set(scenario_ids)
    for missing in sorted(expected - actual):
        gap(f"thiếu scenario bắt buộc: {missing}")
    for unknown in sorted(actual - expected):
        gap(f"scenario ngoài danh sách AC/NFR: {unknown}")

    for scenario in catalog.scenarios:
        for field_name in ("title", "business_effect", "proof", "denominator"):
            value = getattr(scenario, field_name)
            if not value or not value.strip():
                gap(f"scenario {scenario.id}: thiếu trường {field_name}")
        if not scenario.check_ids:
            gap(f"scenario {scenario.id}: không có check nào")

    known_checks = set(check_ids)
    for scenario in catalog.scenarios:
        for check_id in scenario.check_ids:
            if check_id not in known_checks:
                gap(f"scenario {scenario.id}: check không tồn tại {check_id}")
        if not scenario.requirement_refs:
            gap(f"scenario {scenario.id}: thiếu requirement_refs")

    referenced = set(catalog.referenced_check_ids())
    for check_id in check_ids:
        if check_id not in referenced:
            gap(f"check không được scenario nào dùng: {check_id}")

    return gaps


def build_catalog() -> Catalog:
    checks: tuple[CheckDef, ...] = (
        PytestCheck("pytest.ac01.author_replay", ("tests/integration/test_author_to_replay.py",)),
        PytestCheck("pytest.ac01.revisions", ("tests/platform/test_revisions.py", "tests/platform/test_snapshots.py")),
        PytestCheck("pytest.ac01.replay", ("tests/integration/test_strict_replay.py",)),
        PytestCheck(
            "pytest.ac02.sources", ("tests/platform/test_source_anchors.py", "tests/platform/test_extraction.py")
        ),
        PytestCheck("pytest.ac02.impact", ("tests/platform/test_requirement_impact.py",)),
        PytestCheck("pytest.ac02.bundles", ("tests/platform/test_bundles.py",)),
        PytestCheck("pytest.ac03.exploration", ("tests/platform/test_exploration.py",)),
        PytestCheck("pytest.ac03.egress", ("tests/security/test_browser_egress.py",)),
        PytestCheck("pytest.ac04.truth", ("tests/verify/test_truth_table.py",)),
        PytestCheck("pytest.ac04.agent", ("tests/agent/test_agent_runner.py",)),
        PytestCheck("pytest.ac05.authoring", ("tests/platform/test_authoring.py",)),
        PytestCheck("pytest.ac06.evidence", ("tests/verify/test_evidence_errors.py",)),
        PytestCheck("pytest.ac06.exit_codes", ("tests/cli/test_exit_codes.py",)),
        PytestCheck("pytest.ac07.faults", ("tests/faults",)),
        ArtifactCheck("artifact.fault_matrix.cleanup", "run_fault_matrix", "artifacts/faults/latest.json"),
        PytestCheck("pytest.ac08.healing", ("tests/agent/test_healing.py", "tests/integration/test_healing_run.py")),
        PytestCheck("pytest.ac09.guard", ("tests/agent/test_target_guard.py",)),
        PytestCheck("pytest.ac09.fixture", ("tests/browser/test_fixture_app.py",)),
        PytestCheck("pytest.ac10.refusal", ("tests/agent/test_refusal.py",)),
        PytestCheck(
            "pytest.ac10.oracle", ("tests/evaluation/test_denominators.py", "tests/evaluation/test_scoring.py")
        ),
        PytestCheck("pytest.ac11.actions", ("tests/browser/test_operation_matrix.py",)),
        PytestCheck(
            "pytest.ac11.dsl", ("tests/integration/test_advanced_cases.py", "tests/contracts/test_case_compiler.py")
        ),
        PytestCheck("pytest.ac12.faults", ("tests/faults",)),
        ArtifactCheck("artifact.fault_matrix.side_effects", "run_fault_matrix", "artifacts/faults/latest.json"),
        PytestCheck(
            "pytest.ac13.models",
            ("tests/models/test_go_chat.py", "tests/models/test_zen_systemone.py", "tests/models/test_retry.py"),
        ),
        PytestCheck("pytest.ac13.scope", ("tests/models/test_model_scope.py",)),
        PytestCheck(
            "pytest.ac14.modality", ("tests/agent/test_modality_leaks.py", "tests/agent/test_hybrid_escalation.py")
        ),
        PytestCheck("pytest.ac14.capability", ("tests/models/test_capability_receipts.py",)),
        PytestCheck("pytest.ac15.visual", ("tests/verify/test_evaluator_matrix.py",)),
        PytestCheck("pytest.ac16.diagnostics", ("tests/platform/test_diagnostics.py",)),
        PytestCheck("pytest.ac16.compare", ("tests/ui/test_compare.py",)),
        PytestCheck("pytest.ac17.events", ("tests/api/test_events.py", "tests/api/test_controls.py")),
        PytestCheck("pytest.ac17.cancel", ("tests/faults/test_cancel_barrier.py",)),
        ArtifactCheck("artifact.ui_e2e.reconnect", "run_ui_e2e", "artifacts/ui-e2e/latest.json"),
        PytestCheck("pytest.ac18.suite", ("tests/platform/test_suite_execution.py", "tests/platform/test_dst.py")),
        PytestCheck(
            "pytest.ac18.scheduler", ("tests/platform/test_scheduler.py", "tests/platform/test_suite_revisions.py")
        ),
        PytestCheck(
            "pytest.ac18.fixture",
            ("tests/platform/test_fixture_lifecycle.py", "tests/platform/test_fixture_registry.py"),
        ),
        PytestCheck("pytest.ac19.accounting", ("tests/agent/test_finish_accounting.py",)),
        PytestCheck("pytest.ac19.usage", ("tests/platform/test_usage_aggregation.py", "tests/platform/test_cache.py")),
        PytestCheck("pytest.ac20.canary", ("tests/security/test_canaries.py",)),
        PytestCheck("pytest.ac20.capture", ("tests/browser/test_capture.py",)),
        PytestCheck(
            "pytest.ac20.acl", ("tests/security/test_cross_workspace.py", "tests/operations/test_retention.py")
        ),
        PytestCheck("pytest.ac20.artifacts", ("tests/platform/test_artifact_lifecycle.py",)),
        PytestCheck("pytest.ac21.research", ("tests/evaluation", "tests/experiments", "tests/statistics")),
        PytestCheck("pytest.ac22.parity", ("tests/integration/test_interface_parity.py", "tests/cli/test_parity.py")),
        PytestCheck("pytest.ac22.exports", ("tests/platform/test_exports.py", "tests/platform/test_reports.py")),
        PytestCheck("pytest.ac22.issue", ("tests/platform/test_issue_package.py",)),
        PytestCheck("pytest.ac23.ui", ("tests/ui/test_keyboard.py", "tests/ui/test_live_run.py")),
        PytestCheck("pytest.ac23.roles", ("tests/security/test_roles.py",)),
        PytestCheck("pytest.ac23.restore", ("tests/operations/test_backup_restore.py",), isolated=True),
        ArtifactCheck("artifact.os_smoke", "run_os_profile_smoke", "artifacts/os-smoke/latest.json"),
        PytestCheck("pytest.ac24.budgets", ("tests/agent/test_budgets.py",)),
        PytestCheck("pytest.ac24.admission", ("tests/platform/test_admission.py",)),
        PytestCheck("pytest.nfr01.truth", ("tests/verify/test_truth_table.py",)),
        PytestCheck("pytest.nfr01.scoring", ("tests/evaluation/test_scoring.py",)),
        PytestCheck(
            "pytest.nfr02.canary",
            ("tests/security/test_canaries.py", "tests/models/test_redaction.py", "tests/browser/test_capture.py"),
        ),
        PytestCheck("pytest.nfr03.rls", ("tests/database/test_rls.py", "tests/security/test_cross_workspace.py")),
        PytestCheck("pytest.nfr03.contexts", ("tests/browser/test_contexts.py",)),
        PytestCheck(
            "pytest.nfr04.boundary",
            ("tests/security/test_network_profiles.py", "tests/browser/test_network_boundary.py"),
        ),
        PytestCheck("pytest.nfr04.upload", ("tests/platform/test_upload_quarantine.py",)),
        PytestCheck("pytest.nfr05.recovery", ("tests/faults", "tests/operations/test_drain_quarantine.py")),
        PytestCheck("pytest.nfr06.limits", ("tests/agent/test_budgets.py", "tests/platform/test_admission.py")),
        ArtifactCheck("artifact.workloads", "run_workloads", "artifacts/workloads/latest.json"),
        PytestCheck("pytest.nfr07.health", ("tests/operations/test_health.py",)),
        PytestCheck("pytest.nfr07.query", ("tests/api/test_runs_query.py",)),
        PytestCheck("pytest.nfr08.keyboard", ("tests/ui/test_keyboard.py", "tests/ui/test_live_run.py")),
        ArtifactCheck("artifact.web_tests", "web_tests", "artifacts/web-tests/latest.json"),
        PytestCheck("pytest.nfr09.profile", ("tests/security/test_network_profiles.py",)),
        ArtifactCheck("artifact.os_smoke.nfr", "run_os_profile_smoke", "artifacts/os-smoke/latest.json"),
        PytestCheck("pytest.nfr10.contracts", ("tests/contracts", "tests/database/test_migrations.py")),
        CommandCheck("cmd.nfr10.imports", ("uv", "run", "--locked", "lint-imports")),
        CommandCheck("cmd.nfr10.schemas", ("uv", "run", "--locked", "python", "tools/export_schemas.py", "--check")),
        CommandCheck("cmd.nfr10.plan", ("uv", "run", "--locked", "python", "tools/check_plan_coverage.py")),
        PytestCheck("pytest.nfr11.repro", ("tests/platform/test_bundles.py",)),
        PytestCheck("pytest.nfr11.backup", ("tests/operations/test_backup_restore.py",), isolated=True),
        PytestCheck(
            "pytest.nfr12.offline", ("tests/foundation/test_runtime_guard.py", "tests/models/test_model_scope.py")
        ),
    )

    scenarios: tuple[Scenario, ...] = (
        Scenario(
            "AC-01",
            "Yêu cầu thêm entity, AI tạo ca/assertion và người dùng lưu ready",
            "Ca ready bất biến từ yêu cầu có nguồn; replay dùng dữ liệu runtime và tạo hiệu ứng entity đúng.",
            "Integration source tới proposal tới replay passed cùng revision/snapshot pinned và strict replay.",
            "Số ca fixture yêu cầu (1 requirement create_item) và số revision được tạo.",
            ("pytest.ac01.author_replay", "pytest.ac01.revisions", "pytest.ac01.replay"),
            ("FR-01", "FR-03", "FR-04", "FR-05", "FR-07", "FR-09"),
        ),
        Scenario(
            "AC-02",
            "Import tài liệu, export/import suite và requirement thay đổi",
            "Provenance được giữ; ca bị ảnh hưởng được đánh dấu; file không đọc được báo rõ; bundle round trip.",
            "Anchors/digests, impact links và portable bundle digest kiểm được từ output độc lập.",
            "Số tài liệu/segment đầu vào và số ca liên kết yêu cầu.",
            ("pytest.ac02.sources", "pytest.ac02.impact", "pytest.ac02.bundles"),
            ("FR-02", "FR-08"),
        ),
        Scenario(
            "AC-03",
            "Explore URL có link ra origin lạ và nút ghi dữ liệu chưa được phép",
            "Coverage quan sát được ghi nhận; thao tác ngoài phạm vi bị chặn kèm lý do; không invent expected outcome.",
            "Exploration coverage/gaps từ fixture và egress policy receipts trên trap origin.",
            "Số origin/hành động khai báo trong environment fixture.",
            ("pytest.ac03.exploration", "pytest.ac03.egress"),
            ("FR-06", "NFR-04"),
        ),
        Scenario(
            "AC-04",
            "Agent báo finish nhưng entity kỳ vọng chưa xuất hiện tại checkpoint hợp lệ",
            "Business failed với evidence truy được; không nhận lời nói agent làm kết luận.",
            "Truth table: finish không đủ điều kiện passed; verify độc lập quyết định.",
            "Số assertion bắt buộc của ca fixture.",
            ("pytest.ac04.truth", "pytest.ac04.agent"),
            ("FR-14", "FR-27", "FR-29"),
        ),
        Scenario(
            "AC-05",
            "Draft thiếu assertion hoặc kỳ vọng chỉ suy ra từ trang chưa xác nhận",
            "Không promote ready; run thử provisional; gate strict từ chối.",
            "Authoring promote fail-closed và draft run provisional không tạo ready.",
            "Số assertion bắt buộc thiếu nguồn trong fixture.",
            ("pytest.ac05.authoring", "pytest.nfr01.truth"),
            ("FR-04", "FR-09", "FR-29"),
        ),
        Scenario(
            "AC-06",
            "Assertion adapter lỗi hoặc evidence bắt buộc mất, chưa có business failure",
            "Inconclusive với lỗi/thiếu dữ liệu hiển thị; exit code 2.",
            "Evidence error không thành business failure; CLI precedence trả 2.",
            "Số assertion bắt buộc bị mất evidence trong fixture.",
            ("pytest.ac06.evidence", "pytest.ac06.exit_codes"),
            ("FR-16", "FR-28", "FR-29", "FR-42"),
        ),
        Scenario(
            "AC-07",
            "Đã chứng minh assertion false rồi worker/cleanup gặp lỗi",
            "Giữ failed và thêm execution/cleanup error; không đổi thành passed.",
            "Truth table giữ failed; fault matrix cleanup failure có counter thật.",
            "Số fault case cleanup trong matrix và số assertion failed đã chứng minh.",
            ("pytest.ac07.faults", "pytest.ac04.truth", "artifact.fault_matrix.cleanup"),
            ("FR-29", "FR-38", "FR-40"),
        ),
        Scenario(
            "AC-08",
            "Locator đổi, phục hồi đúng, mọi assertions qua",
            "Passed với healing event; strict gate từ chối; allow_healing chấp nhận.",
            "Healing integration run: gate truth table trên cùng fixture mutation.",
            "Số mutation target trong fixture (1 drift hợp lệ).",
            ("pytest.ac08.healing",),
            ("FR-23", "FR-25", "FR-29"),
        ),
        Scenario(
            "AC-09",
            "ID cũ được chuyển sang nút sai, cùng trang có nhiều nút cùng tên",
            "Guard phát hiện mismatch; không dùng selector/first-match làm bằng chứng identity.",
            "Target guard tests và fixture app sensor phân biệt entity theo ID/nhãn.",
            "Số nút trùng nhãn và ID tái dùng trong fixture.",
            ("pytest.ac09.guard", "pytest.ac09.fixture"),
            ("FR-11", "FR-22"),
        ),
        Scenario(
            "AC-10",
            "Hai candidate không phân biệt được hoặc tương tác sai entity",
            "Từ chối hoặc ghi sai theo oracle; không đổi assertions để đạt.",
            "Refusal tests và oracle denominators độc lập cho correct/false healing.",
            "Số cơ hội healing và candidate ambiguous trong fixture.",
            ("pytest.ac10.refusal", "pytest.ac10.oracle"),
            ("FR-23", "FR-24", "FR-26"),
        ),
        Scenario(
            "AC-11",
            "Có nhánh dữ liệu động, frame/tab, upload/download, checkbox/select, hover/scroll/press",
            "Tất cả nhóm hành động có fixture; capture và checkpoint đúng context.",
            "Operation matrix và DSL runtime tests trên fixture đa nhóm hành động.",
            "Số nhóm hành động theo inventory (8 nhóm).",
            ("pytest.ac11.actions", "pytest.ac11.dsl"),
            ("FR-12", "FR-13"),
        ),
        Scenario(
            "AC-12",
            "Timeout sau side effect và retry request/worker stale",
            "Không tác động trùng khi chưa biết outcome; mọi attempt được lưu.",
            "Fault tests journal/crash/epoch và fault matrix side-effect counters.",
            "Số backend side-effect counter trước/sau mỗi fault case.",
            ("pytest.ac12.faults", "artifact.fault_matrix.side_effects"),
            ("FR-15", "FR-41"),
        ),
        Scenario(
            "AC-13",
            "Jev thiếu answer/unknown target, free hết, Go quota lỗi",
            "Phân loại lỗi/degradation, không đổi model/provider/route trả phí; accounting đầy đủ.",
            "Fake transports cho missing answer/quota/error shapes; model scope giữ hai route.",
            "Số loại lỗi protocol trong fixture transport.",
            ("pytest.ac13.models", "pytest.ac13.scope"),
            ("FR-17", "FR-18", "FR-21"),
        ),
        Scenario(
            "AC-14",
            "Hybrid gặp phần tử thuần ảnh; chạy cùng ca vision-first",
            "Hybrid ghi image escalation; vision-first không nhận semantic DOM; route ảnh chưa conformance bị chặn.",
            "Modality leak audit và capability receipts image gate.",
            "Số bước quyết định và số ảnh gửi trong fixture.",
            ("pytest.ac14.modality", "pytest.ac14.capability"),
            ("FR-19", "FR-20"),
        ),
        Scenario(
            "AC-15",
            "Visual baseline khác, AI đề xuất thay baseline",
            "Diff có evidence; đề xuất riêng; baseline run giữ nguyên.",
            "Evaluator matrix: mask/tolerance/baseline immutable và proposal tách verdict.",
            "Số pixel/region diff và baseline digest trong fixture.",
            ("pytest.ac15.visual",),
            ("FR-30",),
        ),
        Scenario(
            "AC-16",
            "LLM đưa chẩn đoán sai, compare hai run khác model",
            "Chẩn đoán không sửa verdict; diff cấu hình hiện rõ.",
            "Diagnostics giữ verdict; compare config diff trên fixture khác model.",
            "Số khác biệt cấu hình giữa hai run fixture.",
            ("pytest.ac16.diagnostics", "pytest.ac16.compare"),
            ("FR-31", "FR-34"),
        ),
        Scenario(
            "AC-17",
            "UI mất kết nối, pause/resume/cancel, browser hoặc server chết",
            "Reconnect không lặp events; pause/cancel có semantics; partial trace đọc được.",
            "Event cursor tests và cancel barrier và UI E2E reconnect scenario.",
            "Số event durable và số lần reconnect trong fixture.",
            ("pytest.ac17.events", "pytest.ac17.cancel", "artifact.ui_e2e.reconnect"),
            ("FR-32", "FR-38", "FR-42"),
        ),
        Scenario(
            "AC-18",
            "Tải suite đồng thời với fixture backend và lịch trùng giờ",
            "Không lẫn dữ liệu/worker; đầy đủ execution; overlap/DST đúng cấu hình.",
            "Suite materialization/admission/fixture lifecycle tests trên PostgreSQL thật.",
            "Số execution dự kiến/danh sách occurrence trong fixture lịch.",
            ("pytest.ac18.suite", "pytest.ac18.scheduler", "pytest.ac18.fixture"),
            ("FR-10", "FR-37", "FR-39", "FR-40"),
        ),
        Scenario(
            "AC-19",
            "Retry/finish/parallel calls, một call thiếu cost, cache hit",
            "Tổng usage đúng theo semantics; partial/unknown cost rõ; cache guard và pha phí tách.",
            "Accounting tests: mọi call đếm một lần, missingness khác zero, cache receipts.",
            "Số call theo fixture (retry/finish/parallel) và số call thiếu usage.",
            ("pytest.ac19.accounting", "pytest.ac19.usage"),
            ("FR-43", "FR-45"),
        ),
        Scenario(
            "AC-20",
            "Secret canary xuất hiện trong trang và network; người khác truy artifact/run",
            "Không lộ secret qua mọi đường artifact; cross-workspace bị từ chối; expired artifact được giải thích.",
            "Canary sinks tests và pixel masking và ACL/retention/artifact lifecycle.",
            "Số sink được kiểm tra và số identity bị từ chối trong fixture.",
            ("pytest.ac20.canary", "pytest.ac20.capture", "pytest.ac20.acl", "pytest.ac20.artifacts"),
            ("FR-44", "NFR-02", "NFR-03"),
        ),
        Scenario(
            "AC-21",
            "Chạy manifest RQ1-RQ3 với bug/benign mutations và oracle độc lập",
            "Đủ records; không leak ground truth; metric định nghĩa và tách invalid/unscorable đúng.",
            "Evaluation/experiments/statistics suites trên private oracle fixtures.",
            "Số variant/slot/scorable trong fixture corpus.",
            ("pytest.ac21.research",),
            ("FR-46", "FR-47", "FR-48"),
        ),
        Scenario(
            "AC-22",
            "Submit cùng snapshot qua web/CLI/API và export báo cáo/issue package",
            "Verdict/gate tương đương; báo cáo/provenance khớp; không tự gửi ra ngoài.",
            "Parity integration và exports/issue package và UI E2E web read path.",
            "Số giao diện so sánh trên cùng snapshot (web/CLI/API).",
            ("pytest.ac22.parity", "pytest.ac22.exports", "pytest.ac22.issue", "artifact.ui_e2e.reconnect"),
            ("FR-33", "FR-35", "FR-36", "FR-49", "FR-50", "FR-51"),
        ),
        Scenario(
            "AC-23",
            "Keyboard navigation, role permissions, Windows/Linux và backup restore",
            "Các yêu cầu NFR liên quan đạt, không mất revision/evidence links.",
            "Keyboard/roles/restore tests và OS smoke receipts trên host và container.",
            "Số role/kiểm tra keyboard/restore link trong fixture.",
            ("pytest.ac23.ui", "pytest.ac23.roles", "pytest.ac23.restore", "artifact.os_smoke"),
            ("NFR-05", "NFR-07", "NFR-08", "NFR-09", "NFR-10", "NFR-11", "NFR-12"),
        ),
        Scenario(
            "AC-24",
            "Cạn step/call/wait budget hoặc bị cắt observation",
            "Có reason và accounting; không tạo pass giả hoặc gọi resource limit là lỗi nghiệp vụ.",
            "Budget tests (truncation/missingness) và admission limits.",
            "Số budget được khai báo trong fixture config.",
            ("pytest.ac24.budgets", "pytest.ac24.admission"),
            ("NFR-01", "NFR-06"),
        ),
        Scenario(
            "NFR-01",
            "Tính đúng đắn",
            "Fixture truth-table và false-pass đều cho kết quả quy định; assertion không bị đánh đổi.",
            "Truth table và scoring suites trên fixture độc lập.",
            "Số truth-table row và scorable record fixture.",
            ("pytest.nfr01.truth", "pytest.nfr01.scoring"),
            ("NFR-01",),
        ),
        Scenario(
            "NFR-02",
            "Bí mật và dữ liệu",
            "Canary không xuất hiện trong prompt/log/event/image/export; fill đi qua đường có kiểm soát.",
            "Canary sinks và model redaction và pixel mask tests.",
            "Số sink và số canary fixture.",
            ("pytest.nfr02.canary",),
            ("NFR-02",),
        ),
        Scenario(
            "NFR-03",
            "Cô lập và quyền",
            "Từ chối cross-workspace tại API/artifact/event; context và fixture isolation kiểm riêng.",
            "RLS/database và cross-workspace và browser context tests.",
            "Số workspace/context trong fixture cách ly.",
            ("pytest.nfr03.rls", "pytest.nfr03.contexts"),
            ("NFR-03",),
        ),
        Scenario(
            "NFR-04",
            "Browser/host boundary",
            "URL/redirect/websocket/file destinations bị kiểm theo environment; không nhận shell/Python tuỳ ý.",
            "Egress/network profile và network boundary và upload quarantine tests.",
            "Số destination bị chặn trong fixture policy.",
            ("pytest.nfr04.boundary", "pytest.nfr04.upload"),
            ("NFR-04",),
        ),
        Scenario(
            "NFR-05",
            "Khả năng phục hồi",
            "Restart worker/server không mất events đã chốt hoặc tạo side effect trùng; "
            "terminal outcome có nguyên nhân.",
            "Fault tests (crash/recovery/epoch) và drain/quarantine và fault matrix counters.",
            "Số fault case recovery và event đã chốt trong fixture.",
            ("pytest.nfr05.recovery", "artifact.fault_matrix.cleanup"),
            ("NFR-05",),
        ),
        Scenario(
            "NFR-06",
            "Tài nguyên",
            "Step/call/wait/concurrency budgets được pin; giới hạn không cắt input/evidence mà không ghi nhận.",
            "Budget/admission tests và workload receipts với thresholds pin trước.",
            "Số budget/limit khai báo và số workload profile W1-W6.",
            ("pytest.nfr06.limits", "artifact.workloads"),
            ("NFR-06",),
        ),
        Scenario(
            "NFR-07",
            "Khả năng quan sát",
            "Có worker/provider health, queue metrics và structured errors; correlation từ API xuống call/action.",
            "Health/readiness/queue suites và structured query errors.",
            "Số readiness layer và query shape trong fixture.",
            ("pytest.nfr07.health", "pytest.nfr07.query"),
            ("NFR-07",),
        ),
        Scenario(
            "NFR-08",
            "Trải nghiệm và accessibility",
            "UI thao tác bằng bàn phím, focus rõ, trạng thái không chỉ dựa màu; loading/error/empty có thông tin.",
            "Keyboard/focus tests và UI E2E checks và web unit artifacts.",
            "Số luồng UI và keyboard path trong fixture.",
            ("pytest.nfr08.keyboard", "artifact.ui_e2e.reconnect", "artifact.web_tests"),
            ("NFR-08",),
        ),
        Scenario(
            "NFR-09",
            "Tương thích",
            "Engine/CLI chạy trên Windows/Linux; web build trên trình duyệt chuẩn; enforcement thật, không stub.",
            "OS smoke receipts trên Windows host và Linux container và network profile tests.",
            "Số OS profile chạy thật (Windows, Linux).",
            ("pytest.nfr09.profile", "artifact.os_smoke.nfr"),
            ("NFR-09",),
        ),
        Scenario(
            "NFR-10",
            "Mở rộng/bảo trì",
            "Cưỡng chế ranh giới năm lớp, schema parity/migrations và generated artifacts không stale.",
            "Contract/migration suites và lint-imports và schema export và plan coverage commands.",
            "Số contract lớp và schema/migration fixture.",
            ("pytest.nfr10.contracts", "cmd.nfr10.imports", "cmd.nfr10.schemas", "cmd.nfr10.plan"),
            ("NFR-10",),
        ),
        Scenario(
            "NFR-11",
            "Tái lập và backup",
            "Export/import metadata không gồm secrets, giữ revision/manifest; restore không mất liên kết evidence.",
            "Backup/restore và bundle round-trip suites.",
            "Số link/checksum kiểm trong restore fixture.",
            ("pytest.nfr11.repro", "pytest.nfr11.backup"),
            ("NFR-11",),
        ),
        Scenario(
            "NFR-12",
            "Kiểm thử",
            "Test tự động offline fake/stub; network guard chặn egress provider; live tách riêng.",
            "Runtime guard và model scope tests trong môi trường không key thật.",
            "Số provider env var bị chặn trong fixture.",
            ("pytest.nfr12.offline",),
            ("NFR-12",),
        ),
    )

    return Catalog(version=CATALOG_VERSION, checks=checks, scenarios=scenarios)
