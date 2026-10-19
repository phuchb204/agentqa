# ADR 0003 — Registry cặp provider và Command Code

- Ngày: 2026-10-19
- Trạng thái: Đã triển khai trên nhánh `feat/commandcode-routes`; cặp OpenCode giữ mặc định
- Phạm vi: Models, Platform (supervisor entrypoint, CLI research), manifests calibration/experiments, web Settings
- Liên quan: [Engine](../design/execution-and-models.md) §8, [runbook conformance](../runbooks/model-conformance.md), spec D-11/§7.1

## Bối cảnh

Spec gốc pin đúng hai route OpenCode (D-05) và nhiều điểm code hardcode `opencode_go`/`opencode_zen` (ledger routes, supervisor live models, Settings, conformance). Gói GOAT của Command Code cung cấp cùng hai họ giao thức qua một base URL và một key: OpenAI Chat Completions (`deepseek/deepseek-v4.1-flash`) và System One decisions (`typesafe/jev`), đã xác minh live ngày 2026-10-19 (catalog 93 models, cả hai endpoint 200, receipts verified). Nhu cầu: cho người dùng đổi qua lại hai cặp mà không fork engine, và thêm cặp thứ ba sau này không phải sửa rải rác.

## Quyết định

1. Thêm `ProviderRoute.COMMANDCODE_CHAT` / `COMMANDCODE_SYSTEMONE`; giữ nguyên hai route OpenCode và mọi receipts/manifests cũ.
2. Registry trung tâm `src/agentqa/models/routes.py` (`ROUTE_CATALOG` + `MODEL_PAIRS` + `resolve_pair`): mỗi route khai origin, path, default model, env key/base/model, có cần session header không. Thêm pair mới chỉ cần thêm entry catalog.
3. Adapter Command Code kế thừa wire OpenAI-chat/System One, khác ở route/version và không gửi `x-opencode-session`. Mọi ledger (composition, authoring, diagnostics) suy route từ adapter đang dùng thay vì hardcode.
4. Chọn pair lúc chạy qua `AGENTQA_MODEL_PAIR` (`opencode` mặc định); manifests research pin `model_pair`, CLI `calibration/experiment execute --live` từ chối khi env không khớp manifest (fail-closed).
5. Cloudflare của Command Code chặn request thiếu `User-Agent` (403 code 1010); adapter luôn gửi `AgentQA/<version>` nên không ảnh hưởng. Usage `prompt_tokens/completion_tokens` dùng chung parser hiện có.

## Các phương án

Hardcode thêm hai route tại từng điểm dùng: nhanh nhưng mỗi pair mới lặp lại toàn bộ chỗ sửa và dễ sót ledger/UI. Tách engine riêng cho Command Code: vi phạm D-09 (một engine chung) và nhân đôi quy tắc verdict. Dùng một key cho cả hai họ Command Code và suy route từ adapter: giữ đúng semantics kế toán mà không thêm plumbing.

## Hệ quả

Mở rộng pair không cần migration DB (cột route là Text) nhưng đổi enum nên phải regen schemas + typed client. Calibration/healing profile và RQ manifests phải chạy riêng theo pair (receipts/provenance không dùng chung). Cặp Command Code là metered (GOAT credits), không còn free như tier OpenCode free — mọi ước tính chi phí ghi nguồn giá riêng, thiếu dữ liệu giữ unknown thay vì zero.
