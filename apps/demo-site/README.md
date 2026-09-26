# Demo site

Web app tĩnh dùng làm đối tượng kiểm thử của AgentQA: HTML/JS thuần, dữ liệu giả lưu trong `localStorage`.

## Trang

- `login.html` — form đăng nhập; chỉ chấp nhận `demo` / `demo`; sai hiển thị lỗi ở `#login-error`.
- `index.html` — danh sách việc cần làm; nếu chưa có `agentqa_user` trong localStorage thì tự chuyển về `login.html`.

## Dữ liệu

| Key | Ý nghĩa |
|---|---|
| `agentqa_user` | Tên người dùng đã đăng nhập |
| `agentqa_todos` | Mảng JSON các việc cần làm |

## Chạy

```bash
uv run python -m http.server 8000 --directory apps/demo-site/base
```

Case mẫu dùng tài khoản `demo/demo`: `experiments/cases/login_todo.yaml`. Hướng dẫn đầy đủ ở `docs/runbooks/dev-setup.md` và `docs/runbooks/cases.md`.

## Biến thể UI

```bash
uv run python apps/demo-site/tools/gen_variants.py apps/demo-site/variant-specs/id-change.json
```

Kết quả ở `apps/demo-site/variants/<name>/` (gitignore, phục vụ mutation testing).

## Giới hạn

- Đánh dấu "done" chỉ toggle class trong DOM, không lưu trạng thái.
- Không có backend; mọi dữ liệu nằm trong localStorage của trình duyệt.
