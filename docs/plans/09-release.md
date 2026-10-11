# Gói 09 — Nghiệm thu và bàn giao sản phẩm

- Ngày: 2026-10-06
- Trạng thái: P31 đã triển khai và nghiệm thu offline (2026-10-11): acceptance 36/36 scenario (24 AC + 12 NFR), fault matrix 24/24, OS smoke windows+linux, UI E2E 6/6 scenario, workloads W1–W6 đạt objectives (p95 delivery 0.28s, p95 read 0.21s, zero duplicate), canary scan 0 matches. P32 chưa triển khai.
- Plan: [rebuild-plan](rebuild-plan.md)
- Nguồn: [Spec AC](../specs/product-spec.md), [design mapping](../design/acceptance-mapping.md), [acceptance plan](acceptance-plan.md)
- Gate: G8

## P31 — Acceptance, fault, OS, privacy và hiệu năng

**Depends on:** P19, P21, P22, P24, P25, P26, P30.

**Files:** `tools/run_{acceptance,fault_matrix,ui_e2e}.py`, `tests/acceptance/`, `tests/faults/`, `tests/security/`, `tests/performance/`, `infra/workloads/`, OS CI jobs, safe failure artifacts và benchmark manifests.

1. Tạo acceptance catalog từ 24 AC, mỗi scenario có expected business effect/proof/denominator độc lập và test refs; fail khi thiếu scenario hoặc chưa chạy, không output pass giả từ ID list.
2. Fault injection tại submit/lease/admission/dispatch/Verify/DB/blob/finalization: stale worker, DB outage, cancel race, crash sau side effect, partial artifact, duplicate message/schedule và cleanup failure. Test actual side-effect counts, not implementation booleans.
3. Cross-workspace/roles/PAT/stream/secret canary/upload/egress bypass; inspect all safe sinks, pixel masking và operator private mounts/DB roles. Tests chỉ dùng synthetic secrets và fake model transports.
4. Windows/Linux core/CLI/browser/egress smoke và lockfile/runtime matrix; shared/local profiles thực. Unsupported/blocked OS enforcement không tính là pass NFR-09.
5. UI keyboard/accessibility, conflict/reconnect/compare/report/experiment, no truth/value leakage; all regressions deterministic đủ để tìm nguyên nhân flaky.
6. Chạy workloads và thresholds đã pin dưới đây; giữ manifests host/browser/DB/configuration, raw metrics và tính toán. Không đổi thresholds sau xem kết quả mà giữ manifest cũ.

### Workload và quality objectives

| Profile | Workload khai báo | Điều kiện kiểm tra |
|---|---|---|
| W1 personal | 1 worker, 1 execution, fixture deterministic | Correct result/trace, baseline latency/memory/phase measurements |
| W2 shared | 4 workers, suite 32 required executions, fake model latency cố định | Không duplicate/unsafe admission/data mixing; concurrent wall time đúng |
| W3 event/live | 20 read clients, 2 executions, 2,000 durable events/execution, reconnect một phần clients | Zero lost/duplicate committed events sau dedupe; expected cursor retention behavior |
| W4 history | 10,000 synthetic run metadata records, filters/pagination/compare | Correct scoped counts và bounded query/memory, dùng indexes đã thiết kế |
| W5 recovery | Repeated worker/supervisor/DB/blob faults với side-effect counter | Zero unintended duplicate external effects, stale writes và false pass trên fault fixtures |
| W6 isolation/retention | Concurrent namespaces, artifact expiry/reconcile và backup/restore | Không cross-workspace access, links/digests khớp hoặc missing reason đúng |

Default product objectives cho server-local profiles W2–W4: p95 committed-event→authorized-client delivery ≤ 1 giây; p95 paged read API ≤ 500 ms khi datasets/filters/profile đã pin. Đây là mục tiêu UX do plan chọn để live monitor/read interaction phản hồi rõ, không là số liệu đã đạt hoặc latency model. Model/browser external latency đo riêng và không che trong UI/server SLA.

Memory/soak so với warmed baseline và resource reservation ceilings đã khai báo, không tăng tuyến tính theo số run đã finalized do leaked sessions/handles. Correctness/privacy/fencing objectives là zero violations trên bộ fixture cụ thể, không khẳng định tuyệt đối mọi ứng dụng. Nếu workload không đạt, sửa component/index/lifecycle hoặc lập design revision có evidence, không chỉnh test để né.

**Verify:** Toàn bộ ordinary gates trong master; `tools/run_fault_matrix.py --models fake`, `tools/run_acceptance.py --models fake`, UI E2E và workload runs trên isolated profiles.

**Done:** 24 AC/12 NFR có receipts đúng OS/boundaries, faults không tạo effects/pass sai và objectives trước-run được kiểm. Tests offline không thay live receipt của P15/P29.

## P32 — Release, live demo và tài liệu tái lập

**Depends on:** P15, P26, P29, P30, P31.

**Files:** release manifest/SBOM/version metadata, `docs/runbooks/{quickstart,demo,research-reproduction,release-validation}.md`, README/update index, package/container build configs và integrity/report bundles.

1. Kiểm tất cả FR/NFR/AC/task receipts, schema/locks/build digests và G0–G8; live Go/Zen/image receipts chưa đủ hoặc production healing profile provisional thì không declare full release.
2. Demo user flow từ URL/tài liệu→ca/source confirmation→agent run→replay→benign mutation/heal→bug detection→evidence/report/compare; dùng synthetic applications/accounts. Ghi mode fake/live và actual calls/cost, không tráo fake panels thành model thật.
3. Run RQ manifests đã pin và offline recompute exports; truthful negative/insufficient statistical outcomes được giữ, không bắt giả thuyết phải thắng để release. Không dùng insufficient calibration làm verified auto-healing profile.
4. Fresh install/local/shared/Windows/Linux quickstart, migrate/restore exercise, pinned artifacts/SBOM/licensing và redaction scan. Runbook commands đã chạy với receipts, không copy số test/results cũ.
5. Build release packages/images và changelog từ behavior thật. Local artifacts/branch/PR chuẩn bị review được; publish/deploy/merge/send và remote changes chỉ khi được yêu cầu riêng.

**Verify:** Clean-environment gates/build/setup/demo/recompute/restore từ runbooks; source/model/secrets/oracle integrity và manifest audit. Không chạy destructive reset để tạo clean test environment.

**Done:** Có sản phẩm và evidence có thể kiểm lại, không chỉ bộ tài liệu/scaffold; các quality targets và khả năng chưa đạt được ghi rõ. User có đường demo và tái lập nghiên cứu đầy đủ, không cần đọc nhật ký hội thoại.
