# Runbook — Setup môi trường dev

## 1. Cài công cụ

- **uv** (quản lý Python + môi trường):
  - Windows: `winget install astral-sh.uv`
  - macOS/Linux: xem https://docs.astral.sh/uv/
- **Docker Desktop** (tuỳ chọn — chỉ cần khi dùng Postgres)
- Git + `gh` CLI (tuỳ chọn, để làm PR)

## 2. Cài repo

```bash
git clone https://github.com/phuchb204/agentqa.git
cd agentqa
uv sync
uv run playwright install chromium
```

## 3. Cấu hình `.env`

```bash
cp .env.example .env
```

Mở `.env`, điền `AGENTQA_LLM_API_KEY` (Zen/Go: lấy key tại https://opencode.ai/auth).

**OpenCode Go** (subscription): `AGENTQA_LLM_BASE_URL=https://opencode.ai/zen/go/v1` — model chat/completions (ví dụ `deepseek-v4.1-flash`) hoặc model responses-API (ví dụ `muse-spark-1.3-contributor` + `AGENTQA_LLM_API=responses`; lưu ý model Muse Spark Contributor dùng prompt/completion để train). Adapter tự gửi header `x-opencode-session` theo yêu cầu của Go.

Các provider khác (DeepSeek trực tiếp / OpenRouter / Gemini-compat / Ollama) — xem comment sẵn trong `.env.example`, đổi `AGENTQA_LLM_BASE_URL` + `AGENTQA_LLM_MODEL` là xong.

**Jev qua OpenRouter** (tuỳ chọn — chỉ cần khi chạy policy cascade):
- Model `typesafe/jev-1.13` gọi qua Decisions API `https://openrouter.ai/api/alpha/decisions`; billing theo input token, output free — giá tham khảo: https://openrouter.ai/typesafe/jev-1.13
- Điền `AGENTQA_JEV_API_KEY` (key OpenRouter) trong `.env`; client ở `agentqa.llm.jev.JevClient`
- Jev không phải chat-completions — không cấu hình qua `AGENTQA_LLM_*`

**Policy cascade Jev** (tuỳ chọn): đặt `AGENTQA_POLICY=jev` để agent dùng Jev chọn action (click/fill/finish) và chỉ gọi LLM khi cần sinh text hoặc khi Jev không đủ tự tin. Ngưỡng chỉnh qua `AGENTQA_JEV_*` (xem `.env.example`). Mặc định `llm` giữ baseline free-form. So sánh 2 chế độ bằng trace trong `experiments/runs/`.

## 4. Chạy test (không cần key)

```bash
uv run pytest -q
```

## 5. Chạy 1 case thật (cần key trong `.env`)

Terminal 1 — serve demo-site:

```bash
uv run python -m http.server 8000 --directory apps/demo-site/base
```

Terminal 2 — chạy case:

```bash
uv run --env-file .env agentqa run --case experiments/cases/login_todo.yaml --base-url http://127.0.0.1:8000
```

Thêm `--headed` nếu muốn nhìn trình duyệt chạy. Bộ case hiện có và schema YAML: xem `docs/runbooks/cases.md`.

## 6. Đọc kết quả

Mỗi lần chạy tạo `experiments/runs/<run_id>/trace.json`:

- `status`: passed / failed / error
- `steps[]`: từng hành động + lỗi + token + rationale
- `assertions[]`: kết quả từng assertion
- `metrics`: tổng `llm_calls` / `input_tokens` / `output_tokens` / `duration_s`
- `versions`: app / model / prompt (dùng để tái lập thí nghiệm)

## 7. Sinh UI variant (phục vụ mutation testing)

```bash
uv run python apps/demo-site/tools/gen_variants.py apps/demo-site/variant-specs/id-change.json
```

Kết quả ở `apps/demo-site/variants/<name>/` (không commit — đã gitignore).

## 8. Postgres (khi cần)

```bash
docker compose -f infra/docker-compose.yml up -d
```
