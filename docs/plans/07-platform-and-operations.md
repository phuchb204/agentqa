# Gói 07 — Điều phối, shared mode và vận hành

- Ngày: 2026-10-06
- Trạng thái: Chưa triển khai
- Plan: [rebuild-plan](rebuild-plan.md)
- Nguồn: [Platform/storage](../design/platform-and-storage.md), [API/security](../design/api-and-security.md), [Web](../design/web-experience.md)
- Gate: G6

## P23 — Suites, admission, fixtures và scheduler

**Depends on:** P06, P07, P11, P18, P21.

**Files:** `src/agentqa/platform/{suites,queue,scheduler,fixtures,budgets}/`, migrations/routers cho schedules/resources, `tests/platform/test_{suite_execution,admission,scheduler,dst,fixture_lifecycle,fail_fast}.py`, `tests/faults/test_scheduler_races.py`.

1. Materialize pinned suite/data matrix thành mọi execution dự kiến trước dispatch; fail-fast/skipped/rerun có records, không mất denominator hoặc ghi đè run cũ.
2. Resource reservations theo workspace/environment/browser/provider reference, transaction root→execution→job→session→resource keys; stale workers/duplicate claims không vượt giới hạn global.
3. Versioned fixtures prepare/reset/probe/cleanup và named backend namespaces; setup fail không gọi ca, cleanup queue có retries/bounds không mất business failure.
4. IANA schedule occurrence keys, DST gap/fold, overlap skip/queue và downtime no-catch-up; multiple schedulers dùng DB uniqueness/claim, not process-only lock.
5. Tests PostgreSQL concurrency thật, virtual clocks và side-effect receipts; UI suite/schedule/data views có provenance và readiness.

**Verify:** `uv run --locked pytest -q tests/platform/test_suite_execution.py tests/platform/test_admission.py tests/platform/test_scheduler.py tests/platform/test_dst.py tests/platform/test_fixture_lifecycle.py tests/platform/test_fail_fast.py tests/faults/test_scheduler_races.py`.

**Done:** Suite gate thấy toàn bộ planned executions, fixtures không ảnh hưởng ca khác, occurrence/admission races có expected outcomes từ DB/backend. Timers là vận hành được pin, không đổi để tăng research success.

## P24 — Shared administration và boundary hardening

**Depends on:** P05, P08, P19.

**Files:** shared settings/membership/credentials/environment UI, `src/agentqa/platform/security/`, authz API dependencies, `tests/security/test_{shared_mode,artifact_permissions,origin_streams,network_profiles,credential_rotation,cross_workspace}.py`, `tests/ui/test_admin_roles.py`.

1. Shared mode TLS/session/role flows, owner/member lifecycle, permission flags export/research, local bootstrap forbidden shared; server fail nếu profile cấu hình không enforce security.
2. Secret set/rotate/revoke/version và active grant/admission invalidation, WS/SSE/artifact/query authorization; test same IDs/different workspace và revoked token trên streams.
3. Linux/Windows egress enforcement deployment profiles, resolver/proxy/WebSocket/service-worker bypass tests, file/scratch/mount isolation và control-plane destinations cấm.
4. UI settings quản references/providers/retention/worker health đúng capability/readiness, no plaintext credential read endpoint. Source/Markdown/error content render safe và CSP/Origin/CSRF đúng.

**Verify:** `uv run --locked pytest -q tests/security`; UI permissions E2E và OS profile smoke riêng. Không gọi provider thật để kiểm ACL/CSRF/canaries.

**Done:** Personal không trở thành shared insecure qua bind flag; quyền bị kiểm tại tất cả backend sinks, không chỉ ẩn nút UI. OS profile chưa enforce được phải báo blocked, không claim tương thích bằng stub.

## P25 — CLI/API parity, CI exports và explicit outbox

**Depends on:** P03, P11, P22, P23, P24.

**Files:** `src/agentqa/platform/cli/`, API integration routes/client, `src/agentqa/platform/outbox/`, `infra/ci-templates/`, `tests/cli/test_{parity,exit_codes,controls,credentials}.py`, `tests/platform/test_{outbox,webhook}.py`, `tests/integration/test_interface_parity.py`.

1. Argparse CLI HTTP client commands cho import/export, run/suite submit/wait/query/cancel, calibration/experiment query và config validation; managed local start vẫn same API services, không engine/checker riêng.
2. Detached vs attached semantics, Ctrl+C ownership, JSON/stdout-safe errors, PAT/env scopes và exit precedence 64/130/2/1/0 theo spec; no token trong URL/shell history.
3. JSON/HTML/CSV/JSONL/JUnit server exports, strict healed gate rejection và evidence links/provenance; templates GitHub/GitLab chỉ dùng CI secrets/fake tests, không tự upload issue/email.
4. Owner-configured webhook allowlisted destination, outbox transactional, signing/grants/delivery ID/retries và at-least-once idempotency. Tests dùng local receiver, không gửi tới dịch vụ ngoài.
5. Same snapshot/case/fixtures qua API, CLI, web cho same authoritative verdict/gate, kể cả inconclusive/error/control races.

**Verify:** `uv run --locked pytest -q tests/cli tests/platform/test_outbox.py tests/platform/test_webhook.py tests/integration/test_interface_parity.py`; JUnit golden semantics và UI issue-package exports.

**Done:** CLI không phải đường bypass safety, CI không coi provisional/unknown là pass. PR/issue/site publishing không là side effect của commands chạy ca hoặc hoàn tất plan.

## P26 — Deployment, telemetry, retention và restore

**Depends on:** P06, P09, P23, P24, P25.

**Files:** `infra/compose.local.yml`, `infra/compose.shared.yml`, service Dockerfiles/configurations, migration/deployment tooling, `src/agentqa/platform/{health,telemetry,retention,backup}/`, `docs/runbooks/{dev-setup,deployment,backup-restore,operations}.md`, `tests/operations/`.

1. Personal/shared topology API/worker/supervisor/scheduler/DB/artifact/egress, non-root roles/networks/volumes, pinned images/lockfiles và same browser/schema versions. No auto migration from requests, readiness checks version/roles/storage.
2. Health/metrics/correlation, queues/providers capability không gọi model liên tục; safe labels/logging, worker drain/control barrier/quarantine khi restart/version mismatch.
3. Artifact gateway/local private store, lifecycle/retention/tombstones/reconciliation và conditional S3-compatible storage nếu triển khai multi-host; storage adapter không phải model provider mở rộng. Scoped identity contract không thay.
4. Consistent DB snapshot+blob manifest/checksums, encrypted keyring backup riêng; restore vào isolated target, verify links/counters/digests, revoke sessions theo policy và quarantine active runs.
5. Test failed write/orphan/expired artifacts, version upgrade/backfill, restore blocked missing key, drain/restart và secret leak scan toàn service artifacts. Update actual setup/commands trong docs.

**Verify:** `uv run --locked pytest -q tests/operations`; local/shared compose smoke và restore exercise dùng test datasets, không recursive delete/move ngoài verified target.

**Done:** Có môi trường tái lập và runbooks thật, restore kiểm được dữ liệu không chỉ "backup file tồn tại". No cloud deployment/publishing tự động, no production state bị sửa bởi test harness.
