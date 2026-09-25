## What
<!-- Thay đổi gì, ở file/khu vực nào -->

## Why
<!-- Vì sao cần — gắn issue nếu có: Closes #... -->

## How verified
<!-- Lệnh đã chạy + kết quả thật, ví dụ: uv run pytest -q -> 80 passed -->

## Checklist
- [ ] `uv run pytest -q` + `uv run ruff check .` + `uv run ruff format --check .` + `uv run lint-imports` đều xanh
- [ ] Không đổi `contracts/` (hoặc: có — kèm ADR + ghi rõ ảnh hưởng + bump version)
- [ ] Không gọi LLM/Jev API thật trong test (FakeLLM/stub)
- [ ] Code AI sinh đã đọc hiểu + có test kèm
- [ ] Docs cập nhật nếu đổi hành vi/kiến trúc/quy trình (ADR/spec/runbook/roadmap — xem `docs/README.md`)
