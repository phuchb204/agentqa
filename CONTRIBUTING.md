# Đóng góp cho AgentQA

Quy trình chuẩn cho mọi thay đổi trong repo. Quy ước chi tiết về tài liệu nằm ở `docs/README.md`; kiến trúc và luật import nằm ở `docs/architecture.md`.

## 1. Cài đặt môi trường

Xem `docs/runbooks/dev-setup.md`. Tóm tắt:

```bash
uv sync
uv run playwright install chromium
cp .env.example .env
```

## 2. Gate bắt buộc trước khi mở PR

```bash
uv run ruff check .
uv run ruff format --check .
uv run lint-imports
uv run pytest -q
```

CI chạy đúng các lệnh trên; PR đỏ gate không được merge. Tuyệt đối không gọi LLM/Jev API thật trong test — dùng `FakeLLM`/stub.

## 3. Nhánh

- `feat/<slug>` — tính năng mới
- `fix/<slug>` — sửa lỗi
- `chore/<slug>` — hạ tầng, cấu hình, CI
- `docs/<slug>` — tài liệu

Nhánh sống ngắn; rebase `main` thường xuyên. Không push thẳng `main`.

## 4. Commit

Conventional Commits: `<type>(<scope>): <mô tả>`.

- `type` ∈ `feat`, `fix`, `chore`, `docs`, `test`, `refactor`.
- `scope` ∈ `contracts`, `llm`, `agent`, `verify`, `platform`, `cli`, `demo-site`, `ci`, `docs`.
- Ví dụ: `feat(agent): add budget controller`, `docs: update dev setup runbook`.

## 5. Pull request

- Một mục đích/PR, cố gắng dưới ~400 dòng diff.
- Mô tả theo template: What / Why / How verified.
- Cần ít nhất 1 approval và CI xanh; merge bằng squash.
- Không merge code mình không hiểu; code do AI sinh phải kèm test.
- Giữ đúng ranh giới import (xem `docs/architecture.md`); checker cho agent truyền qua tham số (DI), không import chéo `agent` ↔ `verify`.
- Sửa `src/agentqa/contracts/` phải kèm ADR, ghi rõ module bị ảnh hưởng và bump version.
- Không commit `.env`/key vào code, test, trace hay tài liệu.

## 6. Tài liệu

- PR đổi hành vi, kiến trúc hoặc quy trình phải cập nhật tài liệu tương ứng trong cùng PR.
- ADR/spec là bản ghi lịch sử: không sửa nội dung cũ; thay đổi quyết định thì tạo bản mới ghi rõ "Thay thế …".
- Plan chỉ tồn tại trong thời gian làm; xoá khi merge xong (chi tiết ở `docs/README.md`).

## 7. Release

- Phiên bản theo SemVer, tag annotated `vX.Y.Z`.
- Cập nhật `CHANGELOG.md`: chuyển mục `Unreleased` thành phiên bản + ngày phát hành.
