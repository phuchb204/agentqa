# Runbook — Tái lập nghiên cứu RQ1–RQ3 (P32.3)

- Ngày: 2026-10-11
- Trạng thái: Pipeline offline đã triển khai; recompute đã chạy trên export bundles
- Liên quan: [Research questions](../research-questions.md), [experiments & evaluation](../design/experiments-and-evaluation.md), [plan gói 08](../plans/08-research.md)

## 1. Nguyên tắc tái lập

- Manifest bất biến và đóng digest trước evaluation: `benchmarks/experiments/{rq1,rq2,rq3}.yaml`, `benchmarks/calibration/manifest.yaml`.
- Pilot/calibration tách khỏi evaluation. Không sửa threshold sau khi xem kết quả.
- Ground truth và oracle chỉ evaluator truy cập. Không đặt đáp án vào prompt/observation.
- Kết quả âm tính/thiếu dữ liệu thống kê được giữ nguyên, không bắt giả thuyết phải thắng để release.
- Calibration thiếu dữ liệu không được dùng làm verified auto-healing profile (production auto-healing giữ provisional).

## 2. Validate manifests (đã chạy, offline)

```text
uv run --locked agentqa experiment validate --manifest benchmarks/experiments/rq1.yaml
uv run --locked agentqa experiment validate --manifest benchmarks/experiments/rq2.yaml
uv run --locked agentqa experiment validate --manifest benchmarks/experiments/rq3.yaml
```

Kết quả đã chạy:

| Manifest | Kết quả |
|---|---|
| rq1-observation@1 | 0 blocking, 1 warning (image capability chưa verified) |
| rq2-healing@1 | 0 blocking, 0 warning |
| rq3-stability@1 | 0 blocking, 0 warning |

Xem receipt: `.opencode/execution/release-20261011/receipts/t10-rq-validate.log`.

## 3. Offline recompute (đã chạy, không key, không gọi model)

```text
uv run --locked agentqa experiment recompute --bundle artifacts/research/rq1-observation-1-1791711306
uv run --locked agentqa experiment recompute --bundle artifacts/research/rq2-healing-1-1791709015
uv run --locked agentqa experiment recompute --bundle artifacts/research/rq3-stability-1-1791711169
```

Kết quả đã chạy: cả ba bundle **recompute khớp** (`Recompute khớp bundle`, exit 0).
Xem receipt: `.opencode/execution/release-20261011/receipts/t10-rq-recompute.log`.

## 4. Live execution (tách riêng, không chạy trong runbook này)

Live runs dùng master commands trong [rebuild plan](../plans/rebuild-plan.md) §6, yêu cầu `.env` và budgets:

```text
uv run --env-file .env agentqa experiment execute --manifest benchmarks/experiments/rq1.yaml --live
uv run --env-file .env agentqa experiment execute --manifest benchmarks/experiments/rq2.yaml --live
uv run --env-file .env agentqa experiment execute --manifest benchmarks/experiments/rq3.yaml --live
```

Biến thể cặp Command Code (cần `AGENTQA_CMD_API_KEY` và `AGENTQA_MODEL_PAIR=commandcode` khớp `budgets.model_pair` trong manifest, CLI từ chối mismatch):

```text
uv run --env-file .env agentqa experiment execute --manifest benchmarks/experiments/rq1-commandcode.yaml --live
uv run --env-file .env agentqa experiment execute --manifest benchmarks/experiments/rq2-commandcode.yaml --live
uv run --env-file .env agentqa experiment execute --manifest benchmarks/experiments/rq3-commandcode.yaml --live
```

Kết quả RQ có thể bác bỏ giả thuyết; điều đó không cho phép sửa cách chấm.

## 5. Calibration hiện tại

Receipt mới nhất (cặp OpenCode): `artifacts/calibration/healing-default-1.json` — `bound_upper=0.776` trên ceiling `0.01`,
`evidence=measured` với `groups=2`. Profile giữ **provisional**; không dùng làm verified auto-healing profile.

### Finding live 2026-10-19 (cặp Command Code, key GOAT)

- Manifest `benchmarks/calibration/manifest-commandcode.yaml` (`profile_id: healing-commandcode`), chạy
  `agentqa calibration execute --live` với `AGENTQA_MODEL_PAIR=commandcode`: 37 trials, 18 model calls,
  receipt `artifacts/calibration/healing-commandcode-1.json`.
- Kết quả: `evidence=measured`, `sample_units=2`, `groups=2`, `bound_upper=0.776` (Clopper-Pearson một phía,
  confidence 0.95) trên ceiling `0.01` → status **provisional** (`bound_exceeds_ceiling`).
- Dữ liệu là measured và hợp lệ; không nới ngưỡng để đạt. Production auto-healing cho cặp Command Code
  vẫn chờ calibration đạt ceiling; chi tiết trials trong `artifacts/research/calibration-healing-commandcode-*/trials.json`.
