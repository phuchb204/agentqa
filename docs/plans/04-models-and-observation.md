# Gói 04 — Hai model routes, quan sát và agent

- Ngày: 2026-10-06
- Trạng thái: Chưa triển khai; API thật chưa được kiểm tra
- Plan: [rebuild-plan](rebuild-plan.md)
- Nguồn: [Engine/models](../design/execution-and-models.md), [design evidence](../research/design-evidence.md)
- Gate: G3; offline tests và live capability là hai loại evidence

## P12 — Go/Zen adapters và fake transports

**Depends on:** P05, P06.

**Files:** `src/agentqa/models/{opencode_go.py,opencode_zen.py,wire.py,usage.py,retry.py,fakes.py}`, `tests/models/test_{go_chat,zen_systemone,usage,retry,redaction,model_scope}.py`, `tests/fixtures/models/`.

1. Native HTTPX adapters cho đúng Go Chat và Zen System One, typed parse theo contract version, answers keyed question IDs, criteria/finite/type checks. Request `model` không bị override qua extra body.
2. Headers/grants, User-Agent thật, stable Go session; no follow redirect/fallback paid, explicit bounded retry/repair, ledger từng attempt với missing cost/usage.
3. FakeGo/FakeJev và MockTransport fixtures: text/image/Choice/Noul/Score, malformed/unknown answers, auth/quota/rate/timeout, provider cache và partial usage; convenience SDK fields không bị nhầm thành native wire.
4. Tests canary/protocol/route allowlist và budget reservation; không cần hoặc đọc key thật, không dùng một SDK retries ngầm làm mất calls.

**Verify:** `uv run --locked pytest -q tests/models`; fake ledger totals và unauthorized destination tests.

**Done:** Hai adapters có native semantics/error taxonomy, parser fail closed. Các fixtures tham khảo wire docs chưa được ghi nhãn live-conformance nếu chưa có P15.

## P13 — Semantic/hybrid/vision-first và input audit

**Depends on:** P02, P08.

**Files:** `src/agentqa/agent/observation/{semantic.py,vision.py,hybrid.py,selection.py,provenance.py}`, `tests/agent/test_{semantic_observation,vision_grounding,hybrid_escalation,modality_leaks,budgets}.py`.

1. Semantic snapshots role/state/entity regions/candidates với opaque references, visibility và taint; budget controller giữ retained/dropped manifest, không hardcode 8 KB.
2. Safe image capture/marks chỉ số+geometry/DPR/scroll, executor mapping private; vision-first history/errors/checkpoint feedback không leak semantic DOM.
3. Hybrid image trigger theo ambiguity/visual targets/structured need-context, record modality/cost/trigger và blocked capability; conformance receipt chưa có thì không auto coi route nhận ảnh.
4. Audit exact safe bytes gửi policy và scene invalidation; tests dynamic layout/frame, same-name candidates, truncation, canaries và forbidden metadata.

**Verify:** `uv run --locked pytest -q tests/agent/test_semantic_observation.py tests/agent/test_vision_grounding.py tests/agent/test_hybrid_escalation.py tests/agent/test_modality_leaks.py tests/agent/test_budgets.py`.

**Done:** Có bằng chứng vision-first thực nhận ảnh, hybrid thực có ảnh khi cần, chi phí thiếu được giữ missing. Probe/marks/raw target handles không leak vào public inputs.

## P14 — LLM policy, cascade và AgentRunner

**Depends on:** P10, P11, P12, P13.

**Files:** `src/agentqa/agent/{planning,policies,history}/`, `src/agentqa/platform/runs/composition.py`, `tests/agent/test_{llm_policy,jev_cascade,agent_runner,finish_accounting}.py`, `tests/integration/test_agent_run.py`.

1. LLM structured proposals+strict parse/repair, planning/subgoals versioned, typed progress/stop; no arbitrary code/tool quyền host.
2. Cascade Choice trên valid operation/target pairs và optional independent Nouls; sentinel/missing/truncation/schema failure escalation theo pinned profile. Fill literal/parameter/capture trước value-generation; secret value luôn ngoài model.
3. Wire Coordinator completion/Verify và guard sau mọi nhánh, giữ two policies và valid mode/modality matrix; reject cascade+vision_first.
4. Offline flows success/business fail/stuck/low confidence/malformed/provider loss, finish call accounting và no expectation mutation; snapshot digest luôn cùng run.

**Verify:** `uv run --locked pytest -q tests/agent tests/integration/test_agent_run.py tests/models`; all real browser runs dùng injected FakeGo/FakeJev.

**Done:** G3 offline behavior hoạt động, stop/LLM confidence không tự tạo passed, every call/purpose/escalation có ledger. Model thật chỉ bật khi receipt của P15 phù hợp.

## P15 — Manual conformance và capability registry

**Depends on:** P12, P13.

**Files:** `tools/model_conformance.py`, `src/agentqa/platform/models/capabilities.py`, registry/migrations, `tests/models/test_capability_receipts.py`, `docs/runbooks/model-conformance.md`.

1. Tool có hai phases: offline validate và explicit `--live`; reject provider/model ngoài hai routes, require request/output/call budgets, synthetic state/image và redaction sink trước transport.
2. Probe Zen schema/questions/answers/model/usage; Go chat/JSON/image/session/header/cache/usage semantics. Image có known visual marker khác text để chứng minh route thực xử lý ảnh, không chỉ HTTP 200.
3. Ghi sanitized request/result digests, verified/blocked/unsupported, expiry/route epoch; actual model snapshot chưa biết ghi unverified. Không giả cost field có sẵn hoặc free luôn zero.
4. Chạy commands live ở master khi triển khai được phép; test receipt parser/invalid/expired bằng fixtures offline. Auth/quota/ảnh không đạt lưu reason, không tự đổi model hay route.

**Verify:** `uv run --locked pytest -q tests/models/test_capability_receipts.py`; manual commands Zen/Go của master, đọc receipts và ledger riêng.

**Done:** Zen/Go native API và khả năng ảnh bắt buộc có receipts thật hợp lệ, không chỉ docs. Tool/adapter đã code và tests offline xanh chỉ là code_ready nếu gate live còn blocked. Tính năng image/RQ1 và release conformance không được nghiệm thu khi thiếu bằng chứng; tasks độc lập vẫn tiến triển. Tests thường và CI không gọi tool live.
