# Runbook — triển khai local/shared

Topology compose: `postgres` + `migrate` (one-shot) + `api` + `worker` + `scheduler` + `egress`.
Images build từ `infra/Dockerfile.api`, `infra/Dockerfile.worker` (có Chromium theo version Playwright trong
`uv.lock`), `infra/egress-proxy/Dockerfile`; tất cả chạy non-root UID/GID 10001 (service egress UID 10003).
API/worker/scheduler dùng cùng lockfile; browser version do Playwright pin trong `uv.lock`.

## 1. Personal/local

```text
docker compose -f infra/compose.local.yml config --quiet
docker compose -f infra/compose.local.yml up -d --build --wait
docker compose -f infra/compose.local.yml ps
```

- `migrate` chạy một lần: `bootstrap` role + `upgrade --create-database`; API/worker chỉ start sau khi
  migrate hoàn tất (`service_completed_successfully`). **Không auto-migrate từ request** — migration là
  bước triển khai riêng.
- `api` phơi `127.0.0.1:8000`; readiness: `GET /health/ready` (kiểm database/schema/storage/queue; provider
  capability ghi nhận chưa kiểm, không gọi model). Metrics: `GET /metrics` (request counters + ước lượng
  bảng; không có DSN/secret).
- `worker` mặc định `AGENTQA_WORKER_MAINTENANCE_ONLY=1` cho smoke (quarantine stale lease, kiểm schema;
  không claim job). Để chạy execution đầy đủ: đặt `AGENTQA_WORKER_MAINTENANCE_ONLY=0`,
  `AGENTQA_WORKSPACE_ID`, `AGENTQA_PRINCIPAL_ID`, fixture `AGENTQA_FIXTURE_BASE_URL/CONTROL_TOKEN`.
- `scheduler` chạy daemon materialize/claim theo `AGENTQA_SCHEDULER_INTERVAL`.
- `egress` là HTTP proxy allowlist (`AGENTQA_EGRESS_ALLOW` JSON `[{host,port,addresses}]`); worker nối
  network `egress`. Supervisor vẫn enforce proxy/log/host isolation riêng trong process như thiết kế.

## 2. Shared

```text
AGENTQA_DB_PASSWORD=... \
AGENTQA_SHARED_ORIGINS=https://qa.example.com \
AGENTQA_WORKSPACE_ID=... AGENTQA_PRINCIPAL_ID=... \
docker compose -f infra/compose.shared.yml up -d --build --wait
```

- API bắt buộc `AGENTQA_SHARED_ORIGINS` (allowlist HTTPS, không loopback); thiếu cấu hình ⇒ process fail
  ngay (fail-closed). Đặt sau reverse proxy TLS; cookie session chỉ cấm gửi khi thiếu TLS, local bootstrap
  bị chặn ở shared.
- Postgres không publish port; chỉ network nội bộ `control`.
- Cấp password/secret qua secret store của orchestrator, không đặt trong file compose.

## 3. Nâng cấp version

1. Backup theo runbook `backup-restore.md` trước khi đổi schema.
2. Pull/build image mới; chạy `migrate` (upgrade) trước khi start API/worker.
3. API đọc schema version: nếu lệch head, `/health/ready` báo `unavailable` (schema check) — không phục vụ
   sai version.
4. Worker/scheduler khi khởi động kiểm schema; mismatch ⇒ quarantine stale lease + chờ, không claim job
   mới. Stale lease bị quarantine với reason `restart_quarantine`/`version_mismatch`, run active chuyển
   `error` + reason `quarantined:*` (không hồi sinh side effect).
5. Drain: gửi SIGTERM cho worker; loop dừng claim job mới, hoàn tất job hiện tại, release lease rồi thoát.

## 4. Kiểm chứng đã thực hiện

- `docker compose -f infra/compose.local.yml up -d --build --wait` → 5 service healthy (migrate Exited 0).
- `docs/runbooks/` này đi kèm receipt trong `.opencode/execution/pkg07-platform-ops-20261010/receipts/`.
