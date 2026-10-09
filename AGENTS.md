# AGENTS.md — nội quy cho AI coding assistant

## Ngữ cảnh

AgentQA đang được thiết kế và triển khai lại từ đầu. Trước khi làm việc, đọc `README.md`, `docs/README.md`, `docs/product-brief.md`, `docs/research-questions.md`, `docs/research/design-evidence.md`, `docs/specs/product-spec.md`, `docs/architecture.md`, `docs/design/acceptance-mapping.md`, `docs/plans/rebuild-plan.md`, `docs/plans/acceptance-plan.md` và gói task/thiết kế chi tiết/ADR liên quan được index trong `docs/README.md`.

Tài liệu nền ghi yêu cầu và hướng sản phẩm, không mô tả một hệ thống đã triển khai. Không suy diễn rằng schema, dependency, lệnh chạy, CI hoặc module của phiên bản cũ vẫn tồn tại.

## Quyết định của chủ dự án

- Bắt buộc giữ RQ1–RQ3, LLM và Jev cascade.
- Provider ban đầu chỉ gồm Jev `jev-1.13-free` qua OpenCode Zen System One và LLM `deepseek-v4.1-flash` qua OpenCode Go Chat Completions. Không tự thêm provider/model hoặc chuyển sang route trả phí; mở rộng thuộc yêu cầu sau.
- Giữ khung năm lớp Contracts, Models, Agent, Verify, Platform; được thiết kế mới toàn bộ hợp đồng và thành phần bên trong.
- Chủ động chọn giải pháp sản phẩm và kỹ thuật tốt nhất theo chất lượng, độ tin cậy, trải nghiệm và khả năng mở rộng.
- Không dùng giới hạn thời gian hoặc nhân lực để thu hẹp thiết kế. Chủ dự án phát triển bằng AI agent.
- Chỉ hỏi khi thiếu thông tin thực tế không thể suy ra hoặc có xung đột yêu cầu; các lựa chọn thiết kế thông thường do AI quyết định và giải thích trong tài liệu.

## Thiết kế và triển khai

- Viết spec sản phẩm, thiết kế hệ thống và implementation plan mới trước khi viết mã sản phẩm.
- Phân biệt yêu cầu bắt buộc, quyết định thiết kế và giả thuyết cần thực nghiệm.
- Mỗi yêu cầu phải có tiêu chí nghiệm thu quan sát hoặc đo được.
- Contracts quản lý dữ liệu dùng chung; Models quản lý adapter mô hình; Agent quản lý quan sát, policy, thực thi, replay và phục hồi; Verify kiểm chứng độc lập; Platform quản lý ca, điều phối, lưu trữ, thực nghiệm và giao diện.
- Giữ độc lập giữa ra quyết định và kết luận kiểm thử; định nghĩa giao diện tích hợp trong thiết kế mới.
- Không kế thừa contracts v1, giới hạn 8 KB, ngưỡng confidence, danh sách action hoặc dependency cũ như ràng buộc bắt buộc.
- Chọn dependency có lý do, ghi nhận quyết định và cấu hình kiểm tra chất lượng phù hợp khi tạo dự án.
- Không sửa test hoặc CI để né lỗi. Test tự động dùng fake/stub, không gọi LLM/Jev API thật. Thí nghiệm gọi API thật phải tách riêng và ghi nhận chi phí.
- Không tạo số liệu thực nghiệm giả hoặc trình bày thiết kế như tính năng đã triển khai.

## Quy ước

- Nội dung tài liệu, UI và prompt tiếng Việt; tên file và định danh tiếng Anh.
- Không comment trong code; dùng tên định danh và cấu trúc rõ nghĩa.
- Tài liệu mô tả dự án; không viết nhật ký cá nhân hoặc phân công thành viên.
- Cập nhật tài liệu liên quan cùng thay đổi hành vi, kiến trúc hoặc quy trình.
- Không commit `.env`, khóa truy cập hoặc dữ liệu nhạy cảm; không ghi bí mật vào prompt, trace, test hoặc tài liệu.
- Khi bắt đầu commit: dùng nhánh `feat|fix|chore|docs/<slug>` và Conventional Commits. Không push thẳng `main`, không tự merge; dùng PR và các kiểm tra đã cấu hình.
- Khi dọn hoặc khởi tạo lại repo, không tự xoá lịch sử Git, tạo commit đầu tiên hoặc gắn remote nếu chưa được yêu cầu.

## Lệnh kiểm tra (gói 01)

Chạy từ repo root; lockfile là nguồn pin phiên bản:

```text
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked lint-imports
uv run --locked pytest -q
uv run --locked python tools/export_schemas.py --check
uv run --locked python tools/check_plan_coverage.py
pnpm --dir apps/web generate:client:check
pnpm --dir apps/web lint
pnpm --dir apps/web format:check
pnpm --dir apps/web typecheck
pnpm --dir apps/web test
pnpm --dir apps/web build
```

`tools/export_schemas.py` (write mặc định, `--check` read-only) sinh `schemas/`; `apps/web/scripts/generate-client.ts` (`--check`) sinh typed client + Ajv validators. Test không đọc `.env`, không gọi Go/Zen; network guard chặn provider egress.
