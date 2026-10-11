# Runbook — Cài đặt nhanh (P32.4)

- Ngày: 2026-10-11
- Trạng thái: Commands đã chạy với receipts (fresh copy + redaction scan)
- Liên quan: [dev-setup](dev-setup.md), [plan gói 09](../plans/09-release.md)

## 1. Yêu cầu

| Công cụ | Phiên bản đã kiểm chứng |
|---|---|
| Python | 3.13 (pin `uv.lock`, `.python-version`) |
| uv | >= 0.10 (lockfile `uv.lock` là nguồn pin) |
| Node.js | 24 (`engines`, CI pin Node 24) |
| pnpm | 10 |
| Docker + Compose | PostgreSQL test profile, container smoke |
| Chromium | qua Playwright trong `uv.lock` |

Windows và Linux đều hỗ trợ. Personal/local bind loopback mặc định; shared cần TLS/session (xem [deployment](deployment.md)).

## 2. Fresh install từ bản sạch (đã chạy)

Tool `tools/run_quickstart_check.py` copy repo (trừ `.git/.venv/node_modules/artifacts`) sang thư mục tạm
và chạy toàn bộ gates offline:

```text
uv run --locked python tools/run_quickstart_check.py
```

Chuỗi lệnh trong bản sạch (đã chạy, exit 0):

1. `uv sync --locked`
2. `uv run --locked ruff check .`
3. `uv run --locked ruff format --check .`
4. `uv run --locked lint-imports`
5. `uv run --locked python tools/export_schemas.py --check`
6. `uv run --locked python tools/check_plan_coverage.py`
7. `uv run --locked pytest -q tests/contracts tests/foundation tests/acceptance`
8. `pnpm --dir apps/web install --frozen-lockfile`
9. `pnpm --dir apps/web typecheck`
10. `pnpm --dir apps/web test`
11. `pnpm --dir apps/web build`

Xem receipt: `.opencode/execution/release-20261011/receipts/t11-quickstart-fresh.log`.

## 3. Khởi động test profile

```text
docker compose -f infra/compose.test.yml up -d --wait
uv run --locked pytest -q
```

## 4. Redaction scan (đã chạy)

```text
uv run --locked python tools/redaction_scan.py
```

Quét `artifacts/`, `docs/`, `benchmarks/` tìm secret values: kết quả đã chạy `ok=true`, 698 files, 0 findings.
Xem receipt: `.opencode/execution/release-20261011/receipts/t11-redaction-scan.log`.

## 5. Migrate/restore exercise

- Unit: `uv run --locked pytest -q tests/operations/test_backup_restore.py`
- Full exercise với test dataset: xem [backup-restore](backup-restore.md) và mục 4 của runbook release-validation.
- Không chạy destructive reset để tạo môi trường sạch; restore luôn vào database **cách ly** (tên khác).
