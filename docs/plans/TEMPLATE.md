# <Feature> — Implementation Plan

- **Spec:** `docs/specs/YYYY-MM-DD-<slug>-design.md`
- **Goal:** <kết quả cần đạt, 1–2 câu>
- **Không đổi:** <những gì bị đóng băng/ngoài phạm vi>

## Global Constraints

- Lệnh chuẩn: `uv run pytest -q`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run lint-imports`.
- Không đổi contracts nếu spec không yêu cầu; không thêm dependency.
- Cấm gọi API thật trong test (FakeLLM/stub).

---

### Task 1: <tên task>

**Files:** Create/Modify/Delete `<đường dẫn>`.

- [ ] **Step 1: <việc>**

```bash
<lệnh chạy>
```

Expected: <output mong đợi>.

- [ ] **Step 2: Verify**

```bash
<lệnh kiểm tra>
```

Expected: <kết quả>.

- [ ] **Step 3: Commit**

```bash
git add <files>
git commit -m "<type>(<scope>): <mô tả>"
```

---

## Verification tổng

1. <gate 1 + expected>
2. <gate 2 + expected>

## Rollback

<Cách quay lui nếu sai>
