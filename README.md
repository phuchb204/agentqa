# AgentQA

[![ci](https://github.com/phuchb204/agentqa/actions/workflows/ci.yml/badge.svg)](https://github.com/phuchb204/agentqa/actions/workflows/ci.yml)

Nền tảng kiểm thử web bằng AI agent: chạy kịch bản mô tả bằng ngôn ngữ tự nhiên trên trình duyệt thật, ghi trace đo lường được (token, thời gian, phiên bản mô hình) và kiểm chứng kết quả độc lập với quyết định của agent.

## Tính năng

- Vòng lặp agent `observe → decide → execute → verify` trên Playwright Chromium (async).
- Quan sát trang dạng văn bản ngữ nghĩa, ngân sách cứng 8 KB mỗi bước.
- Policy cắm được: LLM free-form (mặc định) hoặc cascade Jev – LLM (`AGENTQA_POLICY=jev`), escalate fail-closed khi thiếu tự tin.
- Assertion chạy bằng code sau khi agent kết thúc, độc lập với agent.
- Trace JSON đầy đủ bước, assertion, token, thời gian và phiên bản để tái lập thí nghiệm.
- Demo-site tĩnh kèm generator biến thể UI (`id-change`) phục vụ đánh giá phục hồi locator.
- Contracts v1 đóng băng; ranh giới module được import-linter cưỡng chế trong CI.

## Trạng thái

`v0.1.0` — baseline kỹ thuật đã chạy end-to-end một case thật; xem mốc tiếp theo tại `docs/roadmap.md`.

## Quickstart

Yêu cầu: Python 3.12, [uv](https://docs.astral.sh/uv/); Chromium được Playwright cài tự động.

```bash
uv sync
uv run playwright install chromium
cp .env.example .env   # điền AGENTQA_LLM_API_KEY
```

Chạy test (không cần API key):

```bash
uv run pytest -q
```

Chạy một case thật trên demo-site:

```bash
# Terminal 1 — serve demo-site
uv run python -m http.server 8000 --directory apps/demo-site/base

# Terminal 2 — chạy case
uv run --env-file .env agentqa run --case experiments/cases/login_todo.yaml --base-url http://127.0.0.1:8000
```

Kết quả nằm ở `experiments/runs/<run_id>/trace.json`; thêm `--headed` để xem trình duyệt chạy.

## Cấu hình

| Biến | Mặc định | Ý nghĩa |
|---|---|---|
| `AGENTQA_LLM_API_KEY` | — | Key provider LLM (bỏ trống được với Ollama local) |
| `AGENTQA_LLM_BASE_URL` | `https://opencode.ai/zen/v1` | Endpoint OpenAI-compatible |
| `AGENTQA_LLM_MODEL` | `deepseek-v4-flash` | Model dùng cho policy LLM |
| `AGENTQA_LLM_API` | `chat` | `chat` hoặc `responses` |
| `AGENTQA_POLICY` | `llm` | `llm` (free-form) hoặc `jev` (cascade) |
| `AGENTQA_JEV_API_KEY` | — | Key OpenRouter (fallback `OPENROUTER_API_KEY`) |
| `AGENTQA_JEV_BASE_URL` | `https://openrouter.ai/api/alpha/decisions` | OpenRouter Decisions API |
| `AGENTQA_JEV_MODEL` | `typesafe/jev-1.13` | Model Jev (pin theo phiên bản) |
| `AGENTQA_JEV_GOAL_DONE_MIN` | `0.8` | Ngưỡng xác nhận hoàn thành mục tiêu |
| `AGENTQA_JEV_STUCK_MIN` | `0.8` | Ngưỡng bế tắc → escalate LLM |
| `AGENTQA_JEV_CONF_MIN` | `0.6` | Ngưỡng tự tin tối thiểu cho lựa chọn |
| `AGENTQA_JEV_MAX_OPTIONS` | `255` | Số lựa chọn tối đa mỗi câu Choice |

Chi tiết provider (Zen/Go, DeepSeek, OpenRouter, Gemini-compat, Ollama) và Jev: xem `docs/runbooks/dev-setup.md` và `.env.example`.

## Cấu trúc repo

```
src/agentqa/
├─ contracts/   # Pydantic models đóng băng dùng chung
├─ llm/         # adapter OpenAI-compatible, Jev client, FakeLLM
├─ agent/       # observation, policy, executor, loop
├─ verify/      # assertion checker
├─ platform/    # trace store
└─ cli.py       # entrypoint `agentqa run`
apps/demo-site/ # web app mẫu + generator biến thể UI
experiments/    # case YAML + trace các lần chạy (runs/ không commit)
docs/           # kiến trúc, ADR, spec, plan, runbook
tests/          # unit + integration (không gọi API thật)
```

## Tài liệu

- `docs/README.md` — index và chuẩn viết tài liệu
- `docs/architecture.md` — kiến trúc, luật import, luồng dữ liệu
- `docs/roadmap.md` — mốc phiên bản
- `docs/adr/`, `docs/specs/`, `docs/plans/`, `docs/runbooks/`
- `CONTRIBUTING.md` — quy trình đóng góp
- `CHANGELOG.md` — lịch sử phát hành

## Giấy phép

MIT — xem `LICENSE`.
