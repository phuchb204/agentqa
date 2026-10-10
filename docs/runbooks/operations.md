# Runbook — vận hành thường nhật

## 1. Health/readiness

- `GET /health/live`: process sống, API version, danh sách schema public.
- `GET /health/ready`: tách lớp `database` / `schema` / `storage` / `queue` / `providers`.
  - `schema` so revision DB với alembic head; lệch ⇒ `unavailable` (API không phục vụ sai version).
  - `providers` ghi nhận "capability chưa kiểm; không gọi model" — readiness không gọi provider.
  - HTTP 503 khi có check lỗi (database/schema/storage/queue).
- `GET /metrics`: request counters + ước lượng kích thước bảng vận hành; không chứa DSN/secret.
  Correlation: mọi response có `x-request-id` (echo header nếu client gửi).

## 2. Log và correlation

- Structured JSON log (`agentqa.platform.telemetry.configure_logging`), trường an toàn: ts/level/logger/
  message/request_id/run_id/execution_id/worker_id; không log body, credential hay DSN.
- Truy vết: request_id → run_id → execution_id → model_call/action receipt trong DB.

## 3. Worker/scheduler

- Drain: SIGTERM → dừng claim job mới, hoàn tất job hiện tại, release lease.
- Restart/version mismatch: worker không claim job, quarantine stale lease (reason `restart_quarantine`/
  `version_mismatch`), run active → `error` + `quarantined:*`; không replay side effect unknown.
- Scheduler daemon: materialize theo IANA timezone; DST gap ⇒ skipped receipt; overlap skip/queue;
  downtime không catch-up.

## 4. Retention và artifact lifecycle

- `RetentionService.expire_due`: artifact `available` quá TTL theo class (run 7 ngày, workspace 30 ngày,
  research 365 ngày — cấu hình versioned) → tombstone (`deleted` + `tombstoned_at` + reason), giữ metadata
  provenance để giải thích artifact hết hạn.
- `sweep_tombstones`: xoá bytes của bản đã tombstone; không đụng artifact đang staged/finalize.
- `scan_orphans`: liệt kê blob không có DB reference trong workspace; không tự xoá — xử lý thủ công theo
  review.
- Blob write lỗi ⇒ artifact `unavailable` (reason `blob_write_failed`); verdict không được nâng thành
  passed thiếu bằng chứng.

## 5. Backup/restore

Xem [backup-restore.md](backup-restore.md). Định kỳ theo policy:

1. `python -m agentqa.platform.backup create` (DB + blob manifest + checksums).
2. `keyring-backup` ra kênh riêng.
3. Diễn tập `restore` vào database cô lập và chạy `verify` + `/health/ready` trên đích.

## 6. Version/schema gates

- Không auto-migrate từ request; migration chạy như bước deploy riêng (compose service `migrate`).
- Chỉ nâng version khi `ruff/lint-imports/pytest/export_schemas --check/check_plan_coverage` và web gates
  xanh; xem `docs/runbooks/deployment.md` cho trình tự.
