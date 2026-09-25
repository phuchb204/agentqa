# AGENTS.md — nội quy cho AI coding assistant

Repo: AgentQA (nền tảng kiểm thử web bằng AI agent).
Trước khi code: đọc issue/PR đang làm, `docs/README.md` (index tài liệu), spec/plan liên quan trong `docs/specs/` + `docs/plans/`, `docs/architecture.md`, và file này.

## Lệnh chuẩn

- `uv sync` — cài/đồng bộ môi trường
- `uv run pytest -q` — chạy test (**cấm gọi LLM/Jev API thật trong test** — dùng `FakeLLM`/stub)
- `uv run ruff check .` — lint, bắt buộc xanh trước commit
- `uv run ruff format --check .` — format, bắt buộc xanh trước commit
- `uv run lint-imports` — kiểm tra luật import, bắt buộc xanh trước commit

## Luật import (import-linter enforce — đừng phá)

- `src/agentqa/contracts/` — module lá, không import gì khác trong `agentqa`
- `src/agentqa/llm/` — chỉ import `contracts`
- `src/agentqa/agent/`, `src/agentqa/verify/` — chỉ import `contracts` + `llm`; **agent và verify KHÔNG import nhau** (checker được truyền vào `run_case` qua tham số `checker` — DI, CLI/test wire)
- `src/agentqa/platform/`, `src/agentqa/cli.py` — được import tự do

## Contracts đóng băng (v1)

`src/agentqa/contracts/` đã freeze. Mọi thay đổi field/kiểu phải: có ADR, PR mô tả rõ module bị ảnh hưởng, bump version. Không tự ý đổi tên.

## Quy ước làm việc

Chi tiết tại `CONTRIBUTING.md`; tóm tắt:

- Branch `feat|fix|chore|docs/<slug>`; Conventional Commits với scope ∈ {contracts, llm, agent, verify, platform, cli, demo-site, ci, docs}
- Không push thẳng `main`, không tự merge — luôn nhánh + PR (CI xanh + 1 approval)
- Không sửa test/CI để né lỗi: test/CI đỏ thì sửa code gốc hoặc báo lại
- Không tự thêm dependency, không refactor ngoài phạm vi issue — cần thì bàn trong issue/PR trước
- Không commit `.env`/key, không ghi key vào code, test, trace hay tài liệu
- Không comment trong code; tên định danh tiếng Anh; chuỗi UI/prompt tiếng Việt theo thiết kế
- Docs là tài liệu dự án, không phải nhật ký cá nhân: đổi hành vi/kiến trúc/quy trình phải cập nhật docs tương ứng trong cùng PR
- Chạy CLI thật cần `.env` — xem `docs/runbooks/dev-setup.md`
