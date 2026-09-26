# Runbook — Bộ kịch bản kiểm thử (case YAML)

- **Ngày:** 2026-09-25
- **Trạng thái:** Đang dùng

## 1. Vị trí

- Case commit sẵn: `experiments/cases/*.yaml`
- Kết quả chạy: `experiments/runs/<run_id>/trace.json` (không commit — đã gitignore)

## 2. Schema `TestCase`

| Trường | Kiểu | Bắt buộc | Mô tả |
|---|---|---|---|
| `name` | string | có | Tên case, dùng trong `run_id` và trace |
| `start_path` | string | có | Đường dẫn tương đối so với `--base-url`; nếu bắt đầu bằng `http` thì dùng nguyên URL |
| `goal` | string | có | Mục tiêu tiếng Việt, mô tả bằng ngôn ngữ tự nhiên |
| `max_steps` | int | không (mặc định 20) | Ngân sách số bước cho agent |
| `assertions` | list | không | Danh sách `AssertionSpec` chạy sau khi agent kết thúc |

`AssertionSpec`:

| Trường | Kiểu | Mô tả |
|---|---|---|
| `id` | string | Mã assertion, xuất hiện trong `trace.assertions[]` |
| `kind` | `text_visible` \| `url_contains` | Loại kiểm chứng |
| `value` | string | Chuỗi cần hiển thị (visible text) hoặc chuỗi con của URL |
| `description` | string | Ghi chú, không bắt buộc |

Ví dụ:

```yaml
name: login_todo
start_path: login.html
goal: "Đăng nhập bằng tài khoản demo/demo, sau đó thêm việc 'Mua sữa' vào danh sách"
max_steps: 15
assertions:
  - id: todo-visible
    kind: text_visible
    value: "Mua sữa"
  - id: on-index
    kind: url_contains
    value: "index.html"
```

## 3. Case hiện có

| Case | Kịch bản | Assertion chính |
|---|---|---|
| `login_todo` | Đăng nhập `demo/demo`, thêm "Mua sữa" | Thấy "Mua sữa"; URL chứa `index.html` |
| `add_two_todos` | Đăng nhập, thêm "Việc A" và "Việc B" | Thấy cả hai việc |
| `fail_demo` | Đăng nhập rồi kết thúc | Cố ý fail ("Sản phẩm đã giao") để thử nhánh fail của CLI |

## 4. Chạy

```bash
uv run python -m http.server 8000 --directory apps/demo-site/base

uv run --env-file .env agentqa run --case experiments/cases/login_todo.yaml --base-url http://127.0.0.1:8000
```

## 5. Thêm case mới

1. Tạo file YAML trong `experiments/cases/`.
2. Viết `goal` bằng tiếng Việt, mô tả kết quả quan sát được; nêu dữ liệu cụ thể (tài khoản, nội dung cần nhập) khi kịch bản cần.
3. Chọn assertion bám bằng chứng hiển thị (`text_visible`) hoặc URL (`url_contains` — so khớp chuỗi con, không phải khớp tuyệt đối).
4. `tests/test_cli.py::test_all_committed_cases_load` tự kiểm tra mọi file YAML trong `experiments/cases/` parse được, nên case mới phải hợp lệ trước khi merge.
