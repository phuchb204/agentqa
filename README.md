# AgentQA

Nền tảng kiểm thử web bằng AI agent: biến yêu cầu nghiệp vụ thành ca kiểm thử, thực hiện trên trình duyệt thật, chạy hồi quy, phục hồi định vị và cung cấp kết luận truy được về bằng chứng.

Gói 01 (nền runtime, Contracts/DSL, schema và typed client) đã được triển khai trong repo này; các gói 02–09 của [implementation plan](docs/plans/rebuild-plan.md) chưa triển khai. Trạng thái và commands thực tế xem mục Phát triển bên dưới.

## Bắt đầu

1. Đọc [nội quy cho AI](AGENTS.md).
2. Đọc [index tài liệu](docs/README.md).
3. Đọc [định hướng sản phẩm](docs/product-brief.md) và [ba câu hỏi nghiên cứu](docs/research-questions.md).
4. Đọc [cơ sở nghiên cứu](docs/research/design-evidence.md) và [spec sản phẩm](docs/specs/product-spec.md).
5. Đọc [thiết kế hệ thống](docs/architecture.md), các thiết kế chi tiết và [truy vết nghiệm thu](docs/design/acceptance-mapping.md).
6. Đọc [implementation plan](docs/plans/rebuild-plan.md), các gói task và [truy vết nghiệm thu vào plan](docs/plans/acceptance-plan.md).
7. Triển khai theo dependency/gate của plan sau khi bản plan được chọn làm cơ sở thực thi; các lệnh trong plan chưa tồn tại ở repo hiện tại.

## Phát triển

Yêu cầu: Python 3.13 (uv quản lý), Node theo `engines >=24` (CI pin Node 24), pnpm 10. Các lệnh gate chính (đã cấu hình trong CI):

```text
uv lock && uv sync --locked
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked lint-imports
uv run --locked pytest -q
uv run --locked python tools/export_schemas.py --check
uv run --locked python tools/check_plan_coverage.py
pnpm --dir apps/web install --frozen-lockfile
pnpm --dir apps/web lint
pnpm --dir apps/web format:check
pnpm --dir apps/web typecheck
pnpm --dir apps/web test
pnpm --dir apps/web build
```

Dependency và lý do chọn nằm trong [docs/dependencies.md](docs/dependencies.md). Test tự động không gọi model thật; mọi egress tới provider bị network guard chặn trong test.

## Các quyết định nền tảng

- Giữ ba câu hỏi nghiên cứu RQ1–RQ3, LLM và Jev cascade.
- Giữ khung năm lớp: Contracts, Models, Agent, Verify, Platform; thiết kế lại các thành phần và hợp đồng bên trong.
- Hỗ trợ tạo ca bằng AI, khám phá ứng dụng, replay và phục hồi có kiểm soát.
- Kiểm chứng độc lập; kỳ vọng kiểm thử giữ nguyên trong từng phiên bản ca.
- Giao diện web, CLI, API và tích hợp CI dùng chung bộ thực thi.
- Ưu tiên chất lượng, mức hoàn thiện, trải nghiệm và độ tin cậy của sản phẩm.

Provider ban đầu: Jev `jev-1.13-free` qua OpenCode Zen System One và LLM `deepseek-v4.1-flash` qua OpenCode Go Chat Completions. Cấu hình mẫu nằm trong [.env.example](.env.example), không chứa API key. Provider khác thuộc phần mở rộng sau.

MIT — xem [LICENSE](LICENSE).
