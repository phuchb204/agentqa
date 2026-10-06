# Gói 06 — Phục hồi và engine đầy đủ

- Ngày: 2026-10-06
- Trạng thái: Chưa triển khai
- Plan: [rebuild-plan](rebuild-plan.md)
- Nguồn: [Verify/healing](../design/verification-and-healing.md), [Engine](../design/execution-and-models.md), [Web](../design/web-experience.md)
- Gate: G5; production calibration receipt hoàn tất ở P29

## P20 — Identity ranking, healing và refusal

**Depends on:** P10, P13, P14, P19.

**Files:** `src/agentqa/agent/{identity,healing}/`, runtime calibration/profile contracts, proposal revision service/UI diff, `tests/agent/test_{similarity,healing,refusal,evidence_identity}.py`, `tests/integration/test_healing_run.py`.

1. Features/weights/missingness và heuristic/model/cascade rankers trên cùng scoped candidates; immutable hard constraints, calibrated thresholds/margins, none/need-context và candidate truncation.
2. Recovery protocol cho action target và evidence target, narrow IdentityPort không nhận comparator để chọn bằng chứng làm assertion đạt. Reused IDs/same-name ambiguity vẫn guard trước dispatch.
3. Healing opportunity/attempt IDs, actual targets/proofs/refusal/errors, annotations và postconditions; expectation/branch/data không đổi. Locator proposal thành draft revision riêng có diff/source.
4. Test synthetic calibrated profile chỉ trong test realm, never export như production/live measurement. Real profile readiness kiểm receipt/bound; pilot/provisional không claim verified auto-healing.
5. Integration valid heal, refused ambiguity, wrong-target-but-final-failed, evidence locator repair, strict-vs-allow_healing gate, native trace secret traps.

**Verify:** `uv run --locked pytest -q tests/agent/test_similarity.py tests/agent/test_healing.py tests/agent/test_refusal.py tests/agent/test_evidence_identity.py tests/integration/test_healing_run.py`; UI healing diff E2E.

**Done:** Logic/protocol có evidence offline, mọi refusals/wrong attempts được ghi. Gate production auto-healing còn cần P29, không bị bỏ qua vì tests fake có confidence cao.

## P21 — Toàn bộ actions, DSL runtime và evaluators

**Depends on:** P08, P10, P11.

**Files:** action/probe registry implementations, `src/agentqa/agent/replay/{branches.py,loops.py,captures.py,contexts.py}`, `src/agentqa/verify/evaluators/{elements.py,url.py,entities.py,network.py,download.py,visual.py}`, `tests/browser/test_operation_matrix.py`, `tests/verify/test_evaluator_matrix.py`, `tests/integration/test_advanced_cases.py`.

1. Complete declared operations: double-click/type/clear/press/check/uncheck/select/hover/scroll/upload/wait/tab/frame/dialog/download, multi-context roles và shadow/frame capabilities.
2. Complete branch/loop/capture, typed dynamic values/taint/context paths; continuation dựa proof không model tự skip required checkpoints. File IDs không arbitrary host paths.
3. Element/text/negative/count/value/state/attribute/entity relations, normalized URL, scoped network/API/download evidence, Pillow/NumPy visual baseline/masks/tolerances; versions không tự cập nhật để đạt.
4. Matrix fixture mỗi operation/evaluator, changed layout/context, absence vs unavailable, ambiguous row, masked evidence thiếu, negative branch và wrong baseline compatibility.

**Verify:** `uv run --locked pytest -q tests/browser/test_operation_matrix.py tests/verify/test_evaluator_matrix.py tests/integration/test_advanced_cases.py`; strict/healing truth tables vẫn xanh.

**Done:** Capability inventory khớp behavior thật của mọi group trong spec, không operation/evaluator placeholder. Visual comparison deterministic không dựa LLM nhận xét đúng/sai.

## P22 — Cache, kế toán, diagnostics và reports

**Depends on:** P06, P14, P19, P20, P21.

**Files:** `src/agentqa/platform/{cache,diagnostics,reports,comparison}/`, ledger aggregators/price snapshots, reports/issue-package endpoints/UI, `tests/platform/test_{cache,usage_aggregation,diagnostics,reports,issue_package}.py`, `tests/ui/test_reporting_flow.py`.

1. Decision cache đúng workspace/purpose/model epoch/prompt/question/input/profile/settings, hit/miss/bypass receipts và guard sau hit. Replay plan cache không reuse action outcome/captures/secret grant.
2. Usage/cost phases, provider-reported vs estimates/quota/subscription allocation, missingness/price time snapshots, finish/repair/retry/parallel ledger và wall-time semantics.
3. Diagnostic after terminal là linked job với own ledger; explanation có confidence/evidence label, không sửa final verdict. Compare filtering/provenance/denominators vẫn authoritative.
4. JSON/HTML/CSV/JSONL/JUnit/report packages và safe artifacts/checksums; issue package preview/download, no send. Versioned visual/report assets không chứa real secret/source raw body.
5. Integration stale cache/context, unknown cost, wrong diagnosis, healed strict gate rejection, partial/expired artifact và tampered integrity.

**Verify:** `uv run --locked pytest -q tests/platform/test_cache.py tests/platform/test_usage_aggregation.py tests/platform/test_diagnostics.py tests/platform/test_reports.py tests/platform/test_issue_package.py`; UI reporting E2E và schema parity.

**Done:** Cached decisions vẫn kiểm trên website thật; reports không biến unknown→zero hoặc gate rejection→business bug, exports đủ để đọc/recompute và scoped permissions đúng.
