# Gói 03 — Luồng strict replay trên browser thật

- Ngày: 2026-10-06
- Trạng thái: Chưa triển khai
- Plan: [rebuild-plan](rebuild-plan.md)
- Nguồn: [Engine](../design/execution-and-models.md), [Verify](../design/verification-and-healing.md), [Platform](../design/platform-and-storage.md)
- Gate: G2; models chưa cần gọi thật

## P07 — Taskboard và fixture độc lập

**Depends on:** P01, P02.

**Files:** `benchmarks/apps/taskboard/`, `benchmarks/public/cases/taskboard/`, `benchmarks/public/fixtures/`, `tests/fixtures/browser/`, `tests/browser/test_fixture_app.py`, `src/agentqa/platform/fixtures/`.

1. Tạo ứng dụng kiểm soát có login, CRUD/list/duplicate labels và backend state riêng; accounts/data synthetic, không dùng provider keys hoặc dữ liệu cá nhân.
2. Fixture registry versioned prepare/reset/cleanup/probe, namespace theo execution/attempt; side-effect counter/actual-target sensor riêng để kiểm retry/wrong entity. Private observations không gắn ground truth vào DOM/marks.
3. Tạo ca requirement-backed và strict plans nhập bằng Contracts, gồm success, business failure và async outcome unknown; expected outcomes do app fixture xác nhận độc lập, không học từ trace agent.
4. Test app behavior/reset/namespace bằng browser/backend trực tiếp trước dùng nó để chứng minh engine.

**Verify:** `uv run --locked pytest -q tests/browser/test_fixture_app.py`; safe case compiler và fixture API tests.

**Done:** App/fixture đủ để chứng minh target, actual side effect và isolation; không chỉ một trang tĩnh lúc nào cũng báo thành công. Version/digests ổn định để pin vào run.

## P08 — Browser adapters, sandbox và safe capture

**Depends on:** P05, P07.

**Files:** `src/agentqa/agent/browser/{session.py,read_port.py,action_registry.py,capture.py,contexts.py}`, `src/agentqa/platform/security/{egress.py,proxy.py,sandbox_linux.py,sandbox_windows.py}`, `tests/browser/test_{contexts,actions,capture,network_boundary}.py`, `tests/security/test_browser_egress.py`.

1. Implement Playwright async session/context/page/frame và read/action ports theo typed registry; initial navigate/click/fill/wait/probe đủ luồng P07. Capability registry báo các operations còn chưa implement thay vì nhận rồi noop.
2. Browser supervision channel private; context không mount repo/.env/oracle/control credentials. Egress proxy validate hostname/port/resolved address/redirect và Linux/Windows outbound profile, không chỉ JavaScript route interception.
3. SafeEvidenceService sanitize semantic/DOM/network và mask ảnh trước blob/model/live sinks; native sensitive trace disabled. Broker resolve fill secret sau guard, taint giữ qua URL/capture/value history.
4. Test allowed local fixture, forbidden endpoints, DNS change/redirect/service worker/WebSocket bypass và context/backend isolation. Fail startup khi không enforce sandbox profile được yêu cầu.

**Verify:** `uv run --locked pytest -q tests/browser tests/security/test_browser_egress.py`; tests dùng Chromium và local trap servers thật, không Go/Zen.

**Done:** Browser read/write capabilities phân biệt, không public CDP, egress và redaction có proof. Image canary kiểm vùng mask/pixels hoặc đối chiếu output giữa hai giá trị synthetic, không chỉ search ASCII trong PNG bytes.

## P09 — Supervisor, command journal và fences

**Depends on:** P06, P08.

**Files:** `src/agentqa/platform/{supervisor,queue,controls,recovery}/`, command/lease procedures/migrations, `tests/faults/test_{command_journal,lease_loss,cancel_barrier,crash_after_effect,supervisor_recovery}.py`.

1. Process supervisor giữ session ownership và command queue; worker chỉ gửi ActionCommand có command ID/fence/control/scene proof. Implement prepared→accepted→dispatched→settled/rejected/unknown receipts.
2. DB claim/admission/reservations theo lock order; append writes check epoch, heartbeat riêng khỏi call/blocking work; DB unavailable dừng admission mới.
3. Pause/cancel requested/effective, duplicates trả cùng receipt, closing/quarantine khi lease mất; không tự requeue browser job đã dispatch. Recovery query receipt/outcome trước retry/reset attempt.
4. Fault test kill worker/supervisor ở mỗi boundary, response loss sau side effect, stale epoch và cancel race; dùng side-effect counter của fixture, không mock "succeeded" để chứng minh không duplicate.

**Verify:** `uv run --locked pytest -q tests/faults/test_command_journal.py tests/faults/test_lease_loss.py tests/faults/test_cancel_barrier.py tests/faults/test_crash_after_effect.py tests/faults/test_supervisor_recovery.py`.

**Done:** Stale issuer không dispatch mới hoặc write terminal hợp lệ, unknown không bị replay, records còn đủ để giải thích. Không claim database fencing hoàn tác external effect.

## P10 — Guard và Verify nền

**Depends on:** P02, P08.

**Files:** `src/agentqa/agent/identity/{resolver.py,guard.py}`, `src/agentqa/verify/{evaluators,completion.py,verdict.py,gate.py}`, `tests/verify/test_{truth_table,checkpoint,applicability,evidence_errors}.py`, `tests/agent/test_target_guard.py`.

1. Guard operation/context/entity/unique/state và scene version, kể cả selector còn resolve. Resolver alternatives đã lưu vẫn cùng identity; không click first/force để tránh ambiguity.
2. Implement visible/absent/text/count/URL/value/basic entity evaluators và read-only wait, checkpoint receipts/proof/evidence validity. Unsupported evaluator khai báo capability thiếu; không chấm default passed.
3. Completion/applicability thuần theo DSL branch plan và execution proof; reducer failed/inconclusive/passed/null/provisional, non-empty assertion và recovered attempts.
4. Strict/allow_healing gate và exit precedence cùng spec; fixtures: finish giả, all([]), required checkpoint bị bỏ, wrong entity, lost proof, failed trước cleanup fault.

**Verify:** `uv run --locked pytest -q tests/verify tests/agent/test_target_guard.py`; import-linter xác nhận Verify không có Models/Agent/Playwright implementation imports.

**Done:** Truth table độc lập pass, guard từ chối reused ID/same-name targets và evidence error không thành business failure. Tính final verdict không nằm ở policy hoặc API handler.

## P11 — Coordinator, strict replay và run API

**Depends on:** P06, P09, P10.

**Files:** `src/agentqa/agent/replay/`, `src/agentqa/platform/runs/{coordinator.py,service.py,read_models.py}`, `src/agentqa/platform/api/{runs.py,events.py,controls.py}`, `tests/integration/test_strict_replay.py`, `tests/api/test_{runs,events,controls}.py`.

1. Bind ready CaseContent+environment+parameters thành immutable snapshot; prepare fixtures/session, interpret basic DSL, guard→journal→action→checkpoint→finalization đúng boundaries.
2. Worker executes qua queue/ports, không mở browser trong HTTP request. Submit/query/state/result và durable SSE initial snapshot/cursor; multiple executions dùng run_seq, no gap/duplicate on reconnect.
3. Wire controls/recovery/evidence read models và cleanup; mọi outcomes có trace. Branch/advanced actions chưa có runtime ở gate này bị capability validator từ chối, không được quảng bá full DSL.
4. End-to-end qua API: ready case→Taskboard thật→known side effect→Verify→ledger/trace/result; thêm missing assertion, storage fault, unknown side effect, late event commit.

**Verify:** `uv run --locked pytest -q tests/integration/test_strict_replay.py tests/api tests/faults`; assert outcome từ fixture/backend state và product result independently.

**Done:** G2 có một đường sản phẩm hoàn chỉnh, không CLI loop riêng và không browser success mock. Submitted 202 chưa là test pass; engine có typed inconclusive/failed với evidence đúng.
