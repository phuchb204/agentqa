# ADR 0001 — Dùng Jev qua OpenRouter làm decision layer (cascade)

- **Ngày:** 2026-09-25
- **Trạng thái:** Chấp nhận
- **Phạm vi ảnh hưởng:** `src/agentqa/llm/`, `src/agentqa/agent/policy.py`, kế hoạch thí nghiệm RQ1

## Bối cảnh

- Agent cần chọn action mỗi bước; chi phí và độ trễ của policy là biến số cần đo trong thí nghiệm.
- Jev (TypeSafe) là decision model trả typed answers (Choice/Noul/Score) kèm xác suất/confidence, không sinh text và không lý luận mở. Model có sẵn qua OpenRouter Decisions API (`typesafe/jev-1.13`) nên không cần tài khoản TypeSafe riêng; giá khảo sát 2026-09-25: khoảng 0.042 USD/1M input token, output miễn phí.
- Ràng buộc: contracts v1 đóng băng; import-linter chỉ cho `llm/` phụ thuộc `contracts/`; test/CI cấm gọi API thật.

## Quyết định

1. Tích hợp Jev như **decision layer bổ sung (cascade)**, không thay thế LLM: Jev quyết định đóng (chọn action trong tập candidate, xác nhận hoàn thành, phân loại), LLM giữ phần sinh text (giá trị `fill`, lý luận mở) và nhận escalation khi Jev không đủ tự tin.
2. Gọi qua **OpenRouter Decisions API** (không dùng SDK TypeSafe), đóng gói tại `agentqa.llm.jev.JevClient`; cấu hình `AGENTQA_JEV_API_KEY` (fallback `OPENROUTER_API_KEY`), `AGENTQA_JEV_BASE_URL`, `AGENTQA_JEV_MODEL`; pin `typesafe/jev-1.13`.
3. Bật bằng `AGENTQA_POLICY=jev`; mặc định `llm` giữ baseline free-form. **Không đổi contracts.**
4. Chi tiết luồng quyết định, ngưỡng và test plan nằm ở `docs/specs/2026-09-25-jev-cascade-policy-design.md`.

## Đã cân nhắc

| Phương án | Lý do loại |
|---|---|
| Không tích hợp Jev | Không rủi ro nhưng thí nghiệm mất chiều so sánh "decision model vs chat model" |
| Dùng TypeSafe SDK trực tiếp | Thêm dependency và tài khoản thứ hai trong khi OpenRouter phục vụ cùng model |
| Tự train/self-host decision model | Không đủ hạ tầng cho thí nghiệm chính, không có nhãn, không kịp tiến độ |
| Dùng Jev thay hoàn toàn LLM | Bất khả thi: Jev không sinh text nên không tạo được giá trị `fill` |

## Hệ quả

- **Tích cực:** chi phí thí nghiệm thấp; không đụng contracts nên các phần việc song song không bị chặn; so sánh định lượng hai policy trên cùng suite/trace.
- **Rủi ro:** vendor mới, chưa có benchmark chính thức (số liệu công khai là tự báo cáo); verdict có thể không tất định giữa các lần chạy → phải pin model version và dự kiến cache verdict; confidence thấp phải cascade sang LLM.
- **Cần theo dõi:** `RunMetrics` chưa có trường cost USD — muốn lưu cost vào trace sẽ cần sửa contracts (ADR mới + bump version); pricing/limits có thể thay đổi.
