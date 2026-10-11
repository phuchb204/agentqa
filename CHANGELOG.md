# Changelog

Mọi thay đổi đáng chú ý của dự án được ghi tại đây, viết từ hành vi đã triển khai và kiểm chứng.

## [0.1.0] — Gói 09: nghiệm thu và bàn giao (2026-10-11)

Trạng thái: **release candidate, không phải full release**. Production healing profile còn provisional
(`bound_upper=0.776` trên ceiling `0.01`); vision-first giữ blocked do image capability; xem `artifacts/release/validation.json`.

### P31 — Acceptance, fault, OS, privacy và hiệu năng

- Acceptance catalog 24 AC + 12 NFR: `tools/run_acceptance.py --models fake` — 36/36 scenario pass với evidence thật, fail-closed khi thiếu/chưa chạy.
- Fault matrix: `tools/run_fault_matrix.py --models fake` — 24 cases/12 nhóm (submit, lease, admission, dispatch, verify, DB, blob, finalization, stale worker, cancel race, duplicate message/schedule); thêm `tests/faults/test_partial_artifact.py` và `test_cleanup_failure.py`.
- Security: secret canary (0 matches trên 490+ sinks), upload bypass (traversal/absolute/symlink), pixel masking, operator mounts/DB roles.
- OS smoke Windows (core/CLI/browser/egress) và Linux container; CI có jobs `python` (ubuntu + PostgreSQL service) và `python-windows`.
- UI E2E 6/6 scenario, 49 checks; `tests/ui` + vitest xanh; sửa race readiness/revoke/create trong admin settings.
- Workloads W1–W6 đạt objectives đã pin: p95 event delivery 0.28s (≤ 1s), p95 paged read 0.21s (≤ 500ms), zero duplicate/unsafe admission, zero cross-workspace, backup restore links ok.

### Sửa component có evidence từ workload/fault

- `JobQueue.claim`: run/execution locks dùng `skip_locked` — hết deadlock khi nhiều worker claim cùng run.
- `EventService.append`: bỏ SELECT FOR UPDATE thừa (6→4 round-trips/event), giữ nguyên semantics khoá qua UPDATE...RETURNING.
- `BackupService` link verification phân biệt `available`/`deleted`/`unavailable` — artifact `unavailable` hợp lệ không còn bị coi là broken link.
- `.gitignore`: `artifacts/` → `/artifacts/` — ruff/pytest gates không còn bỏ qua `src/agentqa/platform/artifacts/` (change C1, đã duyệt).

### P32 — Release, demo và tài liệu tái lập

- Release validation: `tools/check_release.py --check` — structural pass (FR 51/51, AC 24, NFR 12, G0–G8), SBOM 62 pypi + 393 npm, manifest/version metadata trong `artifacts/release/`.
- Demo harness: `tools/run_demo.py --models fake` — chuỗi source → authoring → promote → agent run → replay → heal → bug detection → report → compare; ghi rõ `mode=fake`, `live_calls=0`.
- Runbooks: `quickstart`, `demo`, `research-reproduction`, `release-validation` — commands đã chạy với receipts.
- RQ manifests validate + offline recompute khớp cả 3 bundle; kết quả âm tính/thiếu dữ liệu được giữ nguyên.

### Chưa đạt / provisional

- Calibration healing profile provisional (bound vượt ceiling, n=2 nhóm); không dùng làm verified auto-healing profile.
- RQ1 vision-first blocked (image capability); không đổi sang text-only.
- Demo run và restore exercise phụ thuộc PostgreSQL test profile (port 55432) — xem mục Blocked trong báo cáo thực thi.
