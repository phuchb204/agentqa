# Runbook — dựng môi trường phát triển

Áp dụng cho Windows/Linux. Các lệnh chạy từ repo root.

## 1. Công cụ

| Công cụ | Phiên bản dùng để kiểm chứng |
|---|---|
| Python | 3.13 (pin `uv.lock`) |
| uv | >= 0.10 (lockfile `uv.lock` là nguồn pin) |
| Node.js | 24 (`.npmrc`/pnpm workspace) |
| pnpm | 10 |
| Docker Desktop / Docker Engine | Docker 29.6 + Compose v5 (server PostgreSQL, container smoke) |

## 2. Cài dependency

```text
uv sync --locked
pnpm --dir apps/web install --frozen-lockfile
```

## 3. PostgreSQL test profile

```text
docker compose -f infra/compose.test.yml up -d --wait
```

Profile mở `127.0.0.1:55432`, user bootstrap `agentqa_bootstrap`, mật khẩu `agentqa_test_local_only`
(chỉ dùng cho test local; không có secret thật).

Bootstrap role + database lần đầu:

```text
uv run --locked python -m agentqa.platform.storage.migrate bootstrap
uv run --locked python -m agentqa.platform.storage.migrate upgrade --create-database --admin-dsn "postgresql+psycopg://agentqa_bootstrap:agentqa_test_local_only@127.0.0.1:55432/postgres" --dsn "postgresql+psycopg://agentqa_migrate:agentqa_test_local_only@127.0.0.1:55432/agentqa"
```

Lớp test sử dụng PostgreSQL thật: mỗi phiên pytest tạo database riêng và tự chạy migration; không cần
dựng DB thủ công cho `pytest`.

## 4. Chạy API local

```text
AGENTQA_DSN=postgresql+psycopg://agentqa_api:agentqa_test_local_only@127.0.0.1:55432/agentqa \
AGENTQA_WORKER_DSN=postgresql+psycopg://agentqa_worker:agentqa_test_local_only@127.0.0.1:55432/agentqa \
uv run --locked python -m agentqa.platform.api.server
```

Hoặc dùng CLI managed local start (cùng API services):

```text
uv run --locked agentqa serve --dsn postgresql+psycopg://agentqa_api:agentqa_test_local_only@127.0.0.1:55432/agentqa --port 8000
```

Kiểm tra:

```text
curl http://127.0.0.1:8000/health/live
curl http://127.0.0.1:8000/health/ready
```

UI: build web rồi API phục vụ same-origin, hoặc chạy Vite dev proxy trong `apps/web`.

## 5. Bộ kiểm tra chuẩn

```text
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked lint-imports
uv run --locked pytest -q
uv run --locked python tools/export_schemas.py --check
uv run --locked python tools/check_plan_coverage.py
pnpm --dir apps/web lint
pnpm --dir apps/web format:check
pnpm --dir apps/web typecheck
pnpm --dir apps/web test
pnpm --dir apps/web build
```

UI E2E dùng API/DB/browser thật với model fake:

```text
uv run --locked python tools/run_ui_e2e.py --models fake
```

## 6. Ghi chú

- Không đặt `--env-file .env` vào pytest/lint/UI E2E; test tự tạo credential synthetic và chặn egress provider.
- Live conformance/calibration/RQ là lệnh riêng có opt-in và budget (xem runbook tương ứng khi có).
