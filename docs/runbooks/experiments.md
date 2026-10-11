# Runbook — Thực nghiệm RQ1–RQ3

- Ngày: 2026-10-11
- Trạng thái: Pipeline offline đã triển khai; live execution chờ cấu hình runner/provider thật
- Liên quan: [Experiments & evaluation](../design/experiments-and-evaluation.md), [plan gói 08](../plans/08-research.md)

## 1. Phạm vi

Pipeline nghiên cứu RQ1 (hybrid vs vision-first), RQ2 (healing trên giao diện đột biến) và RQ3 (ổn định/chi phí so với baseline). Manifest bất biến, slots materialize trước khi chạy, scoring độc lập bằng oracle, export + recompute offline.

## 2. Lệnh offline (không gọi model)

```text
uv run --locked agentqa experiment validate --manifest benchmarks/experiments/rq1.yaml
uv run --locked agentqa experiment validate --manifest benchmarks/experiments/rq2.yaml
uv run --locked agentqa experiment validate --manifest benchmarks/experiments/rq3.yaml
uv run --locked agentqa experiment recompute --bundle artifacts/research/export
```

- `validate` in digest + incompatibilities. RQ1 không có capability receipt ảnh sẽ có warning `image_capability_unverified` (không blocking): slot vision-first phải được ghi `blocked` thay vì chạy model ảnh.
- `recompute` đọc bundle (manifest/slots/metrics/settings/integrity), tái tạo metrics/charts và so khớp; lệch integrity hoặc metrics trả exit code khác 0.

## 3. Live execution (khi được cấp phép)

```text
uv run --env-file .env agentqa experiment execute --manifest benchmarks/experiments/rq1.yaml --live
uv run --env-file .env agentqa experiment execute --manifest benchmarks/experiments/rq2.yaml --live
uv run --env-file .env agentqa experiment execute --manifest benchmarks/experiments/rq3.yaml --live
```

- Chỉ chạy khi chủ dự án opt-in; manifest pin budgets (`max_calls`, `max_cost_usd`) và routes Go/Zen.
- Slots dùng cache bypass local; provider cache nếu có phải được ghi nhận (`provider_cache_observed`) và phân tích tách cold/warm.
- Ghi chú: trong phiên bản hiện tại `--live` trả trạng thái `blocked` vì runner live (supervisor + model thật) chưa được cấu hình; kết quả âm/thiếu dữ liệu phải được ghi trung thực, không thay bằng fixture giả hoặc model khác.

## 4. Đọc kết quả

- API results tách `product`, `oracle`, `gate` và `analysis` (bounds, denominator, missingness, confounds, charts).
- Confounds bắt buộc đọc trước kết luận: model alias/resolved chưa xác minh, provider cache, cost basis trộn.
- Blocked/quota/timeout của slot hợp lệ vẫn thuộc task-success denominator; unscorable không bị quy thành false hoặc correct.
- RQ1 non-inferiority chỉ kết luận khi CI paired đủ hỗ trợ; nếu không, báo `insufficient_support`.
