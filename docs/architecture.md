# Kiến trúc AgentQA

- **Ngày:** 2026-09-25
- **Trạng thái:** Baseline `v0.1.0`

## 1. Tổng quan

AgentQA chạy một kịch bản kiểm thử mô tả bằng ngôn ngữ tự nhiên trên trình duyệt thật: agent quan sát trang, chọn hành động, thực thi và cuối cùng tầng kiểm chứng chạy assertion độc lập để kết luận đạt/không đạt. Mọi bước được ghi vào trace đo lường được.

## 2. Các lớp

```
cli  ──►  platform (trace store)
 │
 └──►  agent (observation → policy → executor → loop)
        │            │
        │            └──►  llm (adapter OpenAI-compatible, Jev client, FakeLLM)
        └──►  contracts  ◄── verify (checker, truyền vào loop qua DI)
```

| Module | Trách nhiệm |
|---|---|
| `contracts/` | Pydantic models đóng băng dùng chung: observation, action, step, assertion, mutation, trace, case |
| `llm/` | `OpenAICompatAdapter` (chat/responses), `JevClient` (OpenRouter Decisions API), `FakeLLM` cho test |
| `agent/` | `observation` (dump 8 KB), `policy` (`LLMPolicy`, `JevCascadePolicy`), `executor` (Playwright), `loop` (`run_case`) |
| `verify/` | `checker` thực thi `AssertionSpec` trên trang |
| `platform/` | `trace_store` ghi `trace.json` |
| `cli.py` | Entrypoint `agentqa run`; chọn policy qua `AGENTQA_POLICY` |

## 3. Contracts v1

| Model | Trường |
|---|---|
| `ObservationSnapshot` | `mode`, `url`, `title`, `text`, `element_count`, `size_bytes`, `truncated` |
| `Action` | `type` (navigate/click/fill/finish), `target`, `value`, `rationale` |
| `StepResult` | `index`, `action`, `ok`, `error`, `duration_ms`, `input_tokens`, `output_tokens`, `observation_bytes` |
| `AssertionSpec` / `AssertionResult` | `id`, `kind` (text_visible/url_contains), `value`, `description` / `assertion_id`, `status`, `detail` |
| `MutationSpec` / `MutationChange` | `id`, `variant`, `description`, `changes`, `ground_truth` |
| `RunMetrics` / `RunVersions` | `llm_calls`, `input_tokens`, `output_tokens`, `cost_usd`, `duration_s` / `app`, `model`, `prompt` |
| `RunTrace` | `run_id`, `case_name`, `status`, `started_at`, `finished_at`, `steps`, `assertions`, `metrics`, `versions`, `error` |
| `TestCase` | `name`, `start_path`, `goal`, `max_steps`, `assertions` (đọc từ YAML bằng `load_case`) |

`PolicyResult` (trong `agent/policy.py`, không thuộc contracts) mang thêm `calls`, `escalated`, `confidence` để kế toán token/call.

## 4. Luồng một lần chạy

1. CLI đọc case YAML, build policy theo env, gọi `run_case(case, policy, base_url, headless, checker)`.
2. Loop mở Chromium, điều hướng tới `start_path`.
3. Mỗi bước: `observe` (dump ngữ nghĩa, cap 8 KB) → `policy.decide(goal, snapshot, history)` → nếu `finish` thì dừng; nếu không thì `execute` và ghi `StepResult`.
4. Hết vòng lặp: `checker` chạy toàn bộ assertion trên trang.
5. `passed = finished && mọi assertion passed && mọi step ok`; lỗi ngoài dự kiến → `status = error`.
6. `trace_store` ghi `experiments/runs/<run_id>/trace.json`.

## 5. Policy

- `LLMPolicy` (mặc định): bọc adapter LLM, dùng `SYSTEM_PROMPT`/`build_user_prompt`, trả JSON action.
- `JevCascadePolicy` (`AGENTQA_POLICY=jev`): một request Jev fan-out mỗi bước (`op`, `click_target`, `fill_target`, `goal_done`, `stuck`); Jev quyết định đóng, LLM chỉ sinh text khi `fill`, escalate khi thiếu tự tin/lỗi/`other`/bế tắc (fail-closed). Ngưỡng qua `AGENTQA_JEV_*`; chi tiết thiết kế ở `docs/specs/2026-09-25-jev-cascade-policy-design.md`.

## 6. Luật import (import-linter)

- `contracts/` — lá, không import module nào khác trong `agentqa`.
- `llm/` — chỉ `contracts`.
- `agent/`, `verify/` — chỉ `contracts` + `llm`; **agent và verify không import nhau** (checker truyền vào `run_case` qua DI).
- `platform/`, `cli.py` — import tự do.

## 7. Quyết định liên quan

- `docs/adr/0001-jev-openrouter-decision-layer.md` — Jev qua OpenRouter làm decision layer.
- `docs/specs/2026-09-25-jev-cascade-policy-design.md` — thiết kế cascade.
- `docs/roadmap.md` — mốc tiếp theo (hybrid observation, self-healing, mutation, orchestrator).
