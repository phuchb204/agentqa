# Gói 08 — Benchmark, calibration và ba RQ

- Ngày: 2026-10-06
- Trạng thái: Chưa triển khai/chạy nghiên cứu
- Plan: [rebuild-plan](rebuild-plan.md)
- Nguồn: [Research questions](../research-questions.md), [experiments/evaluation](../design/experiments-and-evaluation.md)
- Gate: G7

## P27 — Ba ứng dụng, corpus và baseline độc lập

**Depends on:** P07, P21.

**Files:** `benchmarks/apps/{taskboard,shopflow,canvasdesk}/`, `benchmarks/public/{requirements,cases,data,fixtures,baselines}/`, private oracle build package/registry, `tools/check_benchmark_inventory.py`, `tests/benchmarks/test_{apps,baseline_plans,coverage,reset,oracle_mounts}.py`.

1. Complete taskboard và tạo shopflow/canvasdesk đúng interaction/evaluator inventory; synthetic transactional/async/visual cases, data rows và fixture recipes có versions/digests.
2. Mỗi ca có requirement/expected effect độc lập và known reset; static baseline plans được author/validate riêng, không copy AI best run rồi ghi "independent".
3. Split public runtime package và private oracle package/DB/credentials, worker images/process mounts không có truth files/API quyền. Actual-target sensor trả opaque refs, mapping out-of-band chỉ evaluator đọc.
4. Corpus inventory theo actions/evaluators/errors/cohorts, không đếm ca thay diversity; safe source anchors/digest và baseline telemetry parity.

**Verify:** `uv run --locked pytest -q tests/benchmarks`; `uv run --locked python tools/check_benchmark_inventory.py`; ordinary tests browser/API thật nhưng fake models.

**Done:** Ba app reset/expected behaviors đúng, static/replay/agent comparable; evaluator có dữ kiện thật độc lập và runtime không được thấy ground truth.

## P28 — Mutation generator, validity và scoring

**Depends on:** P06, P20, P23, P27.

**Files:** `src/agentqa/platform/{experiments/variants,evaluation}/`, private registry/scoring procedures, `benchmarks/public/variant-tokens/`, `tests/evaluation/test_{operators,validity,scoring,denominators,leakage}.py`.

1. Operators versioned benign/distractor/business-bug/temporal, verify applied effect/classification; non-applied/equivalent invalid với reason. Public snapshot blind token/build digest, không descriptive operator label giúp model biết đáp án.
2. Stable mismatch opportunity và healing-attempt IDs, actual targets/effects/map; identical target retries không tăng opportunities, wrong heal final-failed vẫn wrong.
3. Scoring process/role độc lập: true/false/unscorable, correctness/false pass/refusal/detection, product verdict không bị thay. Empty denominator not_applicable, valid scheduled blocked/errors vẫn được báo.
4. Scoring revisions/evidence digests và safe results views; late evidence append revision, raw oracle không trong ordinary bundle.
5. Leak tests SQL/file/network/prompt/history/marks, one harmful mutation fixture gây product false pass để scorer phải bắt được; không mirror scorer output làm expected labels.

**Verify:** `uv run --locked pytest -q tests/evaluation`; scoped processes/DB integration với independent label fixtures.

**Done:** Oracle/scorer có căn cứ hành động/nghiệp vụ, variant validity/provenance đầy đủ, missingness không bị gán correct hoặc zero.

## P29 — Calibration, sample design và statistical engine

**Depends on:** P15, P20, P22, P28.

**Files:** `src/agentqa/platform/{calibration,statistics}/`, calibration CLI/jobs/API, `benchmarks/calibration/manifest.yaml`, `tests/statistics/test_{bounds,grouping,paired_analysis,samples,missingness,seeds}.py`, `docs/runbooks/calibration.md`.

1. Calibration/pilot/evaluation split theo independent case/target/variant families, profile/model/question/feature digests và scope. Quality targets 1% false-heal ceiling/95% confidence là goal, không vendor claim hoặc kết quả sẵn.
2. Search profiles chỉ calibration, acceptance/refusal/loss criterion versioned; ready profile cần real grouped/independence receipt và bound hợp lệ, no evidence từ evaluation tuning.
3. Exact one-sided bounds/zero-event positive bound, grouped analysis/insufficient_support, sample-size report từ pilot/conservative assumptions, paired/stratified bootstrap seeds và multiple-comparison rule.
4. Calibration jobs dùng Coordinator/suite/evaluator có từ P11/P23/P28; không đợi P30 dashboard/manifest runner đầy đủ, không dependency vòng. Offline statistical fixtures kiểm formulas/denominators độc lập bằng known vectors.
5. Run live calibration khi thực thi được phép, selected routes/capabilities/budgets, sanitized ledgers/price basis; nếu không đủ data, profile provisional và lý do rõ, không tự promote.

**Verify:** `uv run --locked pytest -q tests/statistics`; master live calibration command tạo receipts thật. Recompute bound/labels offline từ receipt trước auto-healing production gate.

**Done:** Statistical engine đúng fixtures và calibration release profile có evidence thật/quality bound hợp lệ. Profile còn blocked/provisional giữ task ở code_ready hoặc blocked tương ứng, không claim done toàn bộ hay bật production auto-healing. Không dùng số calls tương quan làm sample n hoặc bootstrap toàn zero làm upper bound zero.

## P30 — Manifest runner, ba RQ, dashboard và recompute

**Depends on:** P19, P22, P23, P25, P28, P29.

**Files:** `src/agentqa/platform/experiments/{manifests.py,compiler.py,runner.py,analysis.py,exports.py}`, `benchmarks/experiments/{rq1,rq2,rq3}.yaml`, experiments API/CLI commands, `apps/web/src/features/experiments/`, `tests/experiments/test_{manifests,slots,arms,analysis,exports,recompute}.py`, `tests/ui/test_experiment_flow.py`.

1. Manifest immutable/schema-validation/sample/profile/price/capability digests, materialize expected slots unique trước evaluation; rerun linked records không overwrite original.
2. RQ1 same Go LLM hybrid/vision-first, local cache bypass/provided-cache facts; RQ2 four arms/cohorts/mutations/refusal/false healing; RQ3 static/LLM/cascade/replay/healing với accounting phases và same load/reset.
3. No cascade+vision_first/unsupported image, no inferred ground truth; valid blocked slots vẫn vào reports. Analysis thấy model alias/version chưa xác minh và cache/cost basis confounds.
4. Dashboard/filter/drill-down UI tách product/oracle/gate, denominator/missingness/uncertainty; CSV/JSONL/manifest/receipt digest bundles và seed settings.
5. Offline recompute không có key/model call; recreate metrics/charts từ export khớp backend/UI. Live execution dùng master commands riêng, record truthful negative/insufficient results.

**Verify:** `uv run --locked pytest -q tests/experiments tests/statistics tests/evaluation`; web experiments E2E, offline recompute, manual live commands RQ1–RQ3 đã validate.

**Done:** Pipeline nghiên cứu tái lập và chấm đúng; có thể kết luận giả thuyết không được hỗ trợ. Thiếu capability/quota/data không được lấp bằng fixture giả hoặc model khác.
