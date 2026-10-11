# Runbook — Calibration cho healing

- Ngày: 2026-10-10
- Trạng thái: Quy trình đã triển khai (offline validate/status); live execute chờ cấu hình runner thật
- Liên quan: [Experiments & evaluation](../design/experiments-and-evaluation.md), [plan gói 08](../plans/08-research.md)

## 1. Phạm vi

Calibration chọn ranker/threshold cho healing theo quality policy khai báo trước (mặc định: false-heal ceiling 1%, confidence 95%). Search chỉ chạy trên `calibration` split; `pilot` split chỉ dùng để ước tính variance/sample size; `evaluation` split không bao giờ được dùng để tune.

## 2. Lệnh offline (không gọi model)

```text
uv run --locked agentqa calibration validate --manifest benchmarks/calibration/manifest.yaml
uv run --locked agentqa calibration status --manifest benchmarks/calibration/manifest.yaml
```

- `validate` kiểm tra schema, split rời nhau, budgets dương, routes pin và in manifest digest.
- `status` đọc receipt gần nhất trong `artifacts/calibration/`; chưa có receipt ⇒ `provisional` với lý do `missing_receipt` và `production_ready=false`.

## 3. Điều kiện profile ready

Receipt chỉ được `ready` khi có đủ:

1. `evidence: measured` (receipt thật, không phải synthetic_test).
2. Ít nhất 2 family độc lập trong calibration split.
3. Exact one-sided upper bound (Clopper–Pearson) trên acceptance trial của từng family ≤ `max_false_heal_rate`.
4. Không có trial nào từ evaluation split.

Thiếu điều kiện nào, receipt ghi `provisional` kèm `reason` tương ứng (`synthetic_evidence`, `missing_units`, `insufficient_independent_groups`, `missing_bound`, `bound_exceeds_ceiling`). Không tự promote production auto-healing từ receipt provisional.

## 4. Lệnh live (khi được cấp phép, tốn chi phí)

```text
uv run --env-file .env agentqa calibration execute --manifest benchmarks/calibration/manifest.yaml --live
```

- Chỉ chạy khi chủ dự án opt-in; manifest pin budgets (`max_calls`, `max_cost_usd`) và routes (`opencode_go/deepseek-v4.1-flash`, `opencode_zen/jev-1.13-free`).
- Runner thật submit trial qua Coordinator/suite (P11/P23) và chấm bằng evaluator (P28); nhãn per-trial lấy từ `EvaluationResult` (correct/false heal, refusal, unscorable).
- Ghi chú: trong phiên bản hiện tại, `--live` trả trạng thái `blocked` với lý do runner live chưa được cấu hình; cần wire master command trước khi chạy.

## 5. Receipts và bất biến

- Receipt lưu tại `artifacts/calibration/<profile>-<version>.json` (không commit).
- Receipt gồm: sample units, groups, bound method/upper, refusal coverage, criteria version, profile/manifest digests, sample size report.
- Đổi model resolved version, feature schema hoặc question set ⇒ tăng version manifest; profile cũ cần revalidation, không giữ nhãn "đã hiệu chỉnh".
