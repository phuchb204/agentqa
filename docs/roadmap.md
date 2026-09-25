# Roadmap

- **Ngày:** 2026-09-25
- **Trạng thái:** Đang cập nhật theo mốc phiên bản

Cập nhật khi mốc đổi trạng thái. Mốc theo phiên bản (SemVer), không chia theo tuần hay nhóm công việc.

| Mốc | Nội dung | Trạng thái |
|---|---|---|
| `v0.1.0` | Baseline: contracts v1, LLM adapter (chat/responses), Jev client + cascade policy, agent loop, assertion checker, trace JSON, CLI, demo-site + variant generator, CI | Đã phát hành 2026-09-25 |
| `v0.2.0` | Core hoàn thiện: quan sát hybrid + budget controller (token/step), self-healing locator + đo false-heal, mutation generator có ground truth, orchestrator + worker pool | Kế hoạch |
| `v0.5.0` | Thí nghiệm chính: full run RQ1–RQ3 (hybrid vs vision-first, hiệu quả phục hồi, độ ổn định/chi phí), pipeline tái lập + bảng số tự động | Kế hoạch |
| `v1.0.0` | Đóng băng số liệu, báo cáo hoàn chỉnh, demo tái lập offline | Kế hoạch |

Ghi chú:

- Ba câu hỏi nghiên cứu của đồ án: RQ1 — quan sát hybrid vs vision-first (token/chi phí/thời gian); RQ2 — hiệu quả tự phục hồi khi UI đột biến; RQ3 — độ ổn định và chi phí so với baseline. Chi tiết phương pháp nằm trong báo cáo của nhóm.
- Thay đổi mốc: sửa bảng trên trong PR tương ứng, không mở nhật ký riêng.
