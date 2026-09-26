# ADR 0002 — Thêm cost_usd vào RunMetrics (contracts v1.1)

- **Ngày:** 2026-09-25
- **Trạng thái:** Chấp nhận
- **Phạm vi ảnh hưởng:** `src/agentqa/contracts/trace.py`, `src/agentqa/agent/policy.py`, `src/agentqa/agent/loop.py`, consumer của trace (CLI, thí nghiệm)

## Bối cảnh

- Jev trả `usage.cost` trong mọi response (`JevResult.cost`); arm cascade cần ghi chi phí thật vào trace để so sánh với baseline LLM ở RQ1.
- `RunMetrics` v1 chỉ có `llm_calls`, `input_tokens`, `output_tokens`, `duration_s` nên không tổng hợp được chi phí USD từ trace.
- Contracts v1 đóng băng: mọi thay đổi field phải có ADR, mô tả ảnh hưởng và bump version.

## Quyết định

1. Thêm field additive `RunMetrics.cost_usd: float = 0.0` — contracts v1.1, tương thích ngược (trace cũ đọc được với giá trị mặc định 0).
2. Thêm `PolicyResult.cost_usd`; `JevCascadePolicy` cộng `JevResult.cost` ở cả ba nhánh (finish/click, fill, escalate). `LLMPolicy` và phần sinh text bằng LLM trả 0 vì adapter chưa có dữ liệu cost.
3. `run_case` cộng dồn cost từng bước vào `metrics.cost_usd`; bump version app `0.1.1`.

## Đã cân nhắc

| Phương án | Lý do loại |
|---|---|
| Tính cost ngoài trace từ token × bảng giá | Giá đổi theo thời gian, không tất định; Jev đã trả cost trực tiếp |
| Nhét cost vào `Action.rationale` | Không parse ổn định, không tổng hợp được |
| Chờ tới khi có orchestrator mới thêm | Mất số liệu cost của các lần chạy trước |

## Hệ quả

- **Tích cực:** trace đủ dữ liệu cost cho so sánh RQ1; field additive không phá consumer cũ.
- **Rủi ro:** cost của arm LLM = 0 (chưa lấy được từ adapter OpenAI-compatible); khi cần đo chi phí LLM phải bổ sung field vào adapter bằng ADR tiếp theo.
- **Cần theo dõi:** đơn vị USD; ghi theo `cost` do API trả về, không hardcode bảng giá.
