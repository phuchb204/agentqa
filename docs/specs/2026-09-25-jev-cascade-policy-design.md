# Jev Cascade Policy — Thiết kế

- **Ngày:** 2026-09-25
- **Trạng thái:** Đã triển khai
- **Phạm vi ảnh hưởng:** `src/agentqa/agent/policy.py` (mới), `agent/loop.py`, `cli.py`, `.env.example`, `docs/runbooks/dev-setup.md`, `tests/agent/test_policy.py` + `tests/agent/test_loop.py` + `tests/test_cli.py`. Không đụng `contracts/`, `verify/`, `platform/`.
- **Liên quan:** `docs/adr/0001-jev-openrouter-decision-layer.md` · `docs/architecture.md`

## 1. Bối cảnh & mục tiêu

Nghiên cứu tài liệu TypeSafe/OpenRouter và các browser agent dùng Jev cho thấy pattern chuẩn: state = DOM/a11y text (không screenshot) → một request Jev mỗi bước chọn op + target trong tập candidate → code thực thi; LLM nhỏ chỉ chạy khi cần sinh text; outcome kiểm chứng bằng code. Các số liệu cộng đồng (latency trung vị ~150–180 ms/quyết định, fan-out rẻ hơn gọi rời) là tự báo cáo, cần kiểm chứng lại.

Ràng buộc kỹ thuật của Jev: Choice tối đa 255 option; Noul không có trường `confidence` riêng (dùng trực tiếp xác suất); state + questions giới hạn khoảng 32k token; model alias `~typesafe/jev-latest` trôi phiên bản nên phải pin. PAGE TEXT là bề mặt prompt-injection.

**Mục tiêu:** (1) có arm so sánh Jev cascade vs LLM free-form trên cùng suite/trace; (2) không đổi contracts/`verify`/`platform`; (3) fail-closed và đo được token/latency từng bước.

## 2. Policy abstraction

`src/agentqa/agent/policy.py`:

```python
class PolicyResult(BaseModel):
    action: Action
    input_tokens: int = 0
    output_tokens: int = 0
    calls: int = 1
    model: str = ""
    escalated: bool = False
    confidence: float | None = None

class Policy(Protocol):
    model: str
    prompt_version: str
    async def decide(self, goal, snapshot, history) -> PolicyResult: ...
```

- `LLMPolicy(llm)` — bọc adapter hiện có, dùng nguyên `SYSTEM_PROMPT`/`build_user_prompt`; baseline, mặc định.
- `JevCascadePolicy(jev, llm, *, goal_done_min, stuck_min, conf_min, max_options)` — cascade; `model = f"jev:{jev.model}+llm:{llm.model}"`.
- `run_case(case, policy, *, base_url, headless, checker)` — loop dùng `PolicyResult` cho action/tokens/calls; `StepResult` không đổi field.
- `cli.py`: `build_policy()` đọc `AGENTQA_POLICY` (`llm` mặc định | `jev`); chỉ tạo `JevClient` khi chạy chế độ `jev`.
- Trace không đổi schema: `versions.model = policy.model`, `versions.prompt = policy.prompt_version`; backend thực tế và snapshot từng bước ghi trong `Action.rationale`.

## 3. Luồng quyết định mỗi bước

**Enumerator** (parse khối `ELEMENTS` trong `ObservationSnapshot.text` — format nội bộ do `observation.py` sinh):

- `click` candidates: `a`, `button` → key `e0..eN`, selector `#id` (ưu tiên) hoặc `text=<nhãn>`.
- `fill` candidates: `input`, `textarea` → cùng cách map.
- `select` chưa hỗ trợ (executor chưa có `select_option`) — ngoài phạm vi v1.
- Vượt `AGENTQA_JEV_MAX_OPTIONS` (mặc định 255) → cắt bớt; chọn `other` sẽ escalate.

**Một request Jev/bước** (fan-out, các câu hỏi song song):

| Question | Loại | Ghi chú |
|---|---|---|
| `op` | Choice {`click`, `fill`, `finish`, `other`} | Bỏ khi không có candidate |
| `click_target` | Choice trên click candidates | Bỏ nếu không có candidate |
| `fill_target` | Choice trên fill candidates | Bỏ nếu không có candidate |
| `goal_done` | Noul | "Mục tiêu đã đạt với bằng chứng hiển thị trên trang" |
| `stuck` | Noul | "Không hành động khả dụng nào tạo tiến triển" |

State gửi: goal + observation text (đã cap 8 KB) + history. `navigate` không nằm trong tập op của Jev ở v1 (đi qua escalate).

**Logic ghép trong code (thứ tự ưu tiên, fail-safe):**

1. `goal_done ≥ AGENTQA_JEV_GOAL_DONE_MIN` (0.8) → `Action(finish)` kể cả khi op nói khác.
2. `stuck ≥ AGENTQA_JEV_STUCK_MIN` (0.8) → escalate `LLMPolicy`.
3. `op=click` + target conf ≥ `AGENTQA_JEV_CONF_MIN` (0.6) → `click`.
4. `op=fill` + target conf ≥ conf_min → gọi LLM **value-only** (`VALUE_SYSTEM_PROMPT`, JSON `{"value": ...}`) → `fill`.
5. `op=finish` nhưng `goal_done` thấp · `op=other` · thiếu target · conf thấp · lỗi → escalate `LLMPolicy`.
6. Không có candidate nào → chỉ hỏi `goal_done` + `stuck`; vẫn không quyết được → escalate.

**Env & defaults:**

| Env | Default | Ý nghĩa |
|---|---|---|
| `AGENTQA_POLICY` | `llm` | `llm` \| `jev` |
| `AGENTQA_JEV_MODEL` | `typesafe/jev-1.13` | Pin, không dùng alias trôi |
| `AGENTQA_JEV_GOAL_DONE_MIN` | `0.8` | Ngưỡng finish |
| `AGENTQA_JEV_STUCK_MIN` | `0.8` | Ngưỡng stuck → escalate |
| `AGENTQA_JEV_CONF_MIN` | `0.6` | Ngưỡng confidence cho op/target |
| `AGENTQA_JEV_MAX_OPTIONS` | `255` | Cap option mỗi Choice |

**Ghi vết:** rationale dạng `jev op=click target=#add-btn conf=0.82 goal_done=0.31 model=typesafe/jev-1.13-20260917` hoặc `escalated:llm reason=low_conf conf=0.41`; tokens của Jev và LLM (nếu có) cộng dồn vào `PolicyResult`; `calls` cộng vào `RunMetrics.llm_calls` (mỗi bước LLM thuần = 1; cascade = 1 hoặc 2 — đủ để kế toán; số call từng backend tách được từ rationale).

## 4. Fail-closed & tái lập

- HTTP 4xx/5xx, timeout, JSON hỏng, thiếu answer, xác suất ngoài `[0,1]` → escalate `LLMPolicy`; LLM cũng lỗi → `StepResult.ok=False` theo cơ chế loop hiện tại (run fail, không crash).
- Thiếu `goal_done` → escalate, **không finish**. Không default giá trị thiếu.
- Question set là "code": hằng `JEV_QUESTION_SET_VERSION` trong `policy.py`; khi cascade bật, `versions.prompt = "v1+jevq1"`. Đổi câu hỏi phải bump.
- Pin version: `typesafe/jev-1.13`; snapshot thực tế (`typesafe/jev-1.13-20260917`) ghi trong rationale.
- **Cache verdict để PR riêng sau** (key = SHA256(model, questions, state), lưu raw answers + usage, bật bằng env, dùng cho full run). Lý do defer: độc lập và cần review riêng vì cache che lỗi nếu làm ẩu.

## 5. Test plan & verification

**Unit — `tests/agent/test_policy.py` (stub toàn bộ, không mạng):**

- Enumerator: click/fill candidates đúng; selector `#id` ưu tiên, fallback `text=`; bỏ `select`; cap 255; ELEMENTS rỗng không lỗi.
- Decision logic (stub `JevClient` + `FakeLLM`): goal_done cao → finish; finish thiếu goal_done → escalate; stuck → escalate; click conf đủ → 0 call LLM; fill → đúng 1 call LLM value-only, tokens cộng đúng; other/conf thấp/HTTP 500/answers hỏng → escalate; không candidate → request chỉ có `goal_done`+`stuck`; rationale chứa marker `op=`/`conf=`/`escalated`.
- `LLMPolicy` giữ nguyên hành vi adapter cũ; `PolicyResult.calls` đúng.
- Config: defaults + override env; `build_policy()` mặc định `LLMPolicy`, `AGENTQA_POLICY=jev` → `JevCascadePolicy`, giá trị lạ → `ValueError` rõ.

**Integration — `tests/agent/test_loop.py`, `tests/test_cli.py`:**

- Test cũ chạy qua `LLMPolicy(FakeLLM(...))`, expectation không đổi (baseline giữ nguyên hành vi).
- Cascade stub trên demo-server → `passed`; nhánh escalate → `versions.model` chứa `jev:` và metrics cộng dồn tokens/calls.
- CLI: monkeypatch `build_policy`; test khẳng định `AGENTQA_POLICY=jev` build đúng loại policy (không gọi mạng).

**Verification khi triển khai (đã chạy):**

- `uv run pytest -q` · `uv run ruff check .` · `uv run ruff format --check .` · `uv run lint-imports`.
- Smoke thật trên demo-site 2 chế độ (`AGENTQA_POLICY=llm` vs `jev`) → so trace: status, số bước, tokens, latency (chi phí nhỏ, key trong `.env`).

## 6. Ngoài phạm vi (v1)

`select_option`; phân tầng option >255; disk cache verdict (PR sau); thay đổi contracts/`verify`/`platform`; vision/hybrid; hardening prompt-injection cho PAGE TEXT; UI/orchestrator.

## 7. Rủi ro & hạn chế

- Enumerator phụ thuộc format observation nội bộ; đổi format phải cập nhật cả hai phía.
- 255 option cap có thể bỏ sót phần tử ở trang lớn → chất lượng giảm, đo được qua tỉ lệ escalate.
- Nondeterminism chưa có cache → so sánh sơ bộ phải chấp nhận noise; số liệu chính thức chờ PR cache.
- Số liệu cost/latency của cộng đồng là tự báo cáo; phải kiểm chứng bằng smoke + suite của nhóm.
