# Runbook — Kiểm tra release (P32.1 + P32.4)

- Ngày: 2026-10-11
- Trạng thái: Tool và SBOM đã triển khai; receipts đính kèm
- Liên quan: [plan gói 09](../plans/09-release.md), [nghiên cứu tái lập](research-reproduction.md), [demo](demo.md)

## 1. Release validation (đã chạy)

```text
uv run --locked python tools/check_release.py --check
```

Tool kiểm:

1. FR/NFR/AC receipts: `artifacts/acceptance/latest.json` (24 AC + 12 NFR passed), fault matrix, UI E2E, OS smoke, workloads, web tests.
2. Schema export gate, lock digests (`uv.lock`, `pnpm-lock.yaml`), build digests (web dist).
3. Gates G0–G8 với evidence refs.
4. Live receipts Go/Zen (capabilities + `expires_at`) và image state.
5. Calibration receipt (`artifacts/calibration/*.json`) — provisional khi `bound_upper > 0.01`.
6. SBOM từ lockfiles (`artifacts/release/sbom.json`: 62 pypi + 393 npm).
7. Release manifest/version metadata (`artifacts/release/manifest.json`).

Kết quả: **structural pass, nhưng không phải full release**:

- `full_release=false` do (1) production healing profile provisional (`bound_upper=0.776 > ceiling 0.01`) và (2) P32 artifacts còn thiếu tại thời điểm kiểm.
- Live receipts Go/Zen còn hạn (đến 2026-10-16/18); image Go `blocked` theo receipt mới nhất — RQ1 vision-first giữ blocked, không tự đổi sang text-only.

Xem: `artifacts/release/{manifest,validation,sbom}.json` và receipt `.opencode/execution/release-20261011/receipts/t8-check-release.log`.

Quy tắc: **không declare full release khi còn provisional/thiếu**. Tool exit 0 cho structural; `full_release` là flag riêng trong JSON.

## 2. Migrate/restore exercise

```text
uv run --locked pytest -q tests/operations/test_backup_restore.py
uv run --locked python tools/run_workloads.py --models fake --profile W6
```

- W6 chạy backup create + verify + restore vào database cách ly và kiểm links/digests.
- Không chạy destructive reset; restore luôn vào database tên khác, drop sau khi kiểm.

## 3. Licensing và pinned artifacts

- License: MIT (`LICENSE`).
- SBOM: `artifacts/release/sbom.json` sinh từ `uv.lock` + `pnpm-lock.yaml` (digests ghi trong SBOM).
- Pinned versions: Python 3.13 (`.python-version`), Node 24 (`apps/web` engines + CI), Chromium theo `uv.lock`, images theo `infra/Dockerfile.*`.
