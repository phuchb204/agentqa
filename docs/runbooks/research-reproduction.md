# Runbook — Tái lập nghiên cứu RQ1–RQ3 (P32.3)

- Ngày: 2026-10-11
- Trạng thái: Pipeline offline đã triển khai; recompute đã chạy trên export bundles
- Liên quan: [Research questions](../research-questions.md), [experiments & evaluation](../design/experiments-and-evaluation.md), [plan gói 08](../plans/08-research.md)

## 1. Nguyên tắc tái lập

- Manifest bất biến và đóng digest trước evaluation: `benchmarks/experiments/{rq1,rq2,rq3}.yaml`, `benchmarks/calibration/manifest.yaml`.
- Pilot/calibration tách khỏi evaluation. Không sửa threshold sau khi xem kết quả.
- Ground truth và oracle chỉ evaluator truy cập. Không đặt đáp án vào prompt/observation.
- Kết quả âm tính/thiếu dữ liệu thống kê được giữ nguyên, không bắt giả thuyết phải thắng để release.
- Calibration thiếu dữ liệu không được dùng làm verified auto-healing profile (production auto-healing giữ provisional).

## 2. Validate manifests (đã chạy, offline)

```text
uv run --locked agentqa experiment validate --manifest benchmarks/experiments/rq1.yaml
uv run --locked agentqa experiment validate --manifest benchmarks/experiments/rq2.yaml
uv run --locked agentqa experiment validate --manifest benchmarks/experiments/rq3.yaml
```

Kết quả đã chạy:

| Manifest | Kết quả |
|---|---|
| rq1-observation@1 | 0 blocking, 1 warning (image capability chưa verified) |
| rq2-healing@1 | 0 blocking, 0 warning |
| rq3-stability@1 | 0 blocking, 0 warning |

Xem receipt: `.opencode/execution/release-20261011/receipts/t10-rq-validate.log`.

## 3. Offline recompute (đã chạy, không key, không gọi model)

```text
uv run --locked agentqa experiment recompute --bundle artifacts/research/rq1-observation-1-1791711306
uv run --locked agentqa experiment recompute --bundle artifacts/research/rq2-healing-1-1791709015
uv run --locked agentqa experiment recompute --bundle artifacts/research/rq3-stability-1-1791711169
```

Kết quả đã chạy: cả ba bundle **recompute khớp** (`Recompute khớp bundle`, exit 0).
Xem receipt: `.opencode/execution/release-20261011/receipts/t10-rq-recompute.log`.

## 4. Live execution (tách riêng, không chạy trong runbook này)

Live runs dùng master commands trong [rebuild plan](../plans/rebuild-plan.md) §6, yêu cầu `.env` và budgets:

```text
uv run --env-file .env agentqa experiment execute --manifest benchmarks/experiments/rq1.yaml --live
uv run --env-file .env agentqa experiment execute --manifest benchmarks/experiments/rq2.yaml --live
uv run --env-file .env agentqa experiment execute --manifest benchmarks/experiments/rq3.yaml --live
```

Biến thể cặp Command Code (cần `AGENTQA_CMD_API_KEY` và `AGENTQA_MODEL_PAIR=commandcode` khớp `budgets.model_pair` trong manifest, CLI từ chối mismatch):

```text
uv run --env-file .env agentqa experiment execute --manifest benchmarks/experiments/rq1-commandcode.yaml --live
uv run --env-file .env agentqa experiment execute --manifest benchmarks/experiments/rq2-commandcode.yaml --live
uv run --env-file .env agentqa experiment execute --manifest benchmarks/experiments/rq3-commandcode.yaml --live
```

Kết quả RQ có thể bác bỏ giả thuyết; điều đó không cho phép sửa cách chấm.

### Finding live RQ1 v2 reps=5 cặp Command Code (2026-10-19, key GOAT)

- Bundle `rq1-observation-commandcode-2-1792403256`: 30/30 slots completed, 0 blocked/errors, 295 calls.
  Cả hai arm oracle success 6/15 (0.4): hybrid 146 calls, vision-first 149 calls. CIs trùng nhau hoàn toàn —
  không phát hiện khác biệt tỉ lệ thành công ở cỡ mẫu này; không kết luận tương đương (cần non-inferiority test
  với mẫu lớn hơn).
- Số liệu đã qua recompute offline khớp bundle.

### Finding live RQ1 cặp Command Code (2026-10-19, key GOAT, reps=1 thăm dò)

- Lần 1 (`rq1-observation-commandcode-1-1792385016`): 3/6 completed, 3 blocked — arm `vision_first` bị chặn
  `image_capability_unverified` vì gate ảnh (`experiments/live.py`) chỉ đọc receipt `opencode_go-*`. Đã sửa
  thành `chat_image_verified(pair)` đọc đúng chat route của pair + kiểm tra expiry, kèm test.
- Lần 2 sau fix (`rq1-observation-commandcode-1-1792385315`): 6/6 completed, 0 blocked, 48 calls.
  Cả hai arm oracle success 1/3: hybrid 22 calls (27k in/7.4k out), vision-first 26 calls (43.5k in/8.6k out).
  Số liệu thô, mẫu nhỏ (3 slots/arm) — vision-first tốn token hơn với cùng tỉ lệ thành công trên mẫu này;
  kết luận RQ cần mẫu lớn và phân bố, không đọc từ một run thăm dò.

### Finding live RQ2 cặp Command Code (2026-10-19, key GOAT)

- Bundle `rq2-healing-commandcode-1-1792385358`: 8/8 slots completed, 0 blocked, 0 errors, tổng 1 model call.
  Oracle: ba arm healing (`healing_go_llm`, `heuristic_ranker`, `jev_cascade`) 2/2 đúng; `strict_replay` 1/2 đúng.
  Heuristic không gọi model; cascade/llm chỉ escalation khi cần nên tổng calls thấp — hành vi đúng thiết kế,
  không phải thiếu ghi nhận (mọi execution đều có record terminal).
- False pass 0 trên mẫu này; mẫu nhỏ (2 slots/arm), chưa đủ để kết luận RQ2.

### Finding live RQ2 v2 reps=5 cặp Command Code (2026-10-19, key GOAT)

- Bundle `rq2-healing-commandcode-2-1792403431`: 40/40 slots completed, 0 blocked/errors, tổng 5 model calls.
- Ba arm healing oracle task 10/10 đúng, phát hiện mismatch 5/5, correct heal 5/0, 0 false heal, 0 false pass.
  `strict_replay` bỏ sót cả 5 mismatch (0/5), oracle task 5/10. Tổng 5 calls đều ở arm `healing_go_llm`.
- Limitation ghi nhận: arm `jev_cascade` 0 calls — cascade chỉ escalation khi heuristic không quyết được,
  nên trên mẫu này so sánh thực tế là heuristic-vs-heuristic-vs-strict, không phải cascade thật.
- Số liệu đã qua recompute offline khớp bundle.

### Finding live RQ3 cặp Command Code (2026-10-19, key GOAT)

- Bundle `rq3-stability-commandcode-1-1792385599`: 20/20 slots completed, 0 blocked/errors, 56 calls.
  Oracle: `cascade_agent` 4/4 đúng, `healing_replay` 4/4, `llm_agent` 1/4, `static_baseline` 2/4, `strict_replay` 2/4.
- Điểm chênh đáng chú ý (ghi nhận, không sửa verdict): `cascade_agent` oracle 4/4 nhưng product pass 0.0 —
  engine không ra verdict passed dù oracle độc lập chấm đúng. Đây đúng là khoảng hở verdict-vs-oracle mà RQ3
  cần đo, không phải lỗi chấm; cần phân tích run detail trước khi diễn giải.
- Mẫu thăm dò (4 slots/arm sau repetitions=2), chưa đủ cho kết luận ổn định/chi phí của RQ3.

### Finding live RQ3 v2 reps=5 cặp Command Code (2026-10-19, key GOAT)

- Bundle `rq3-stability-commandcode-2-1792404305`: 50/50 slots completed, 0 blocked/errors, 181 calls.
  Oracle: cascade 10/10, healing_replay 10/10, llm 4/10, static 5/10, strict 5/10. Chi phí: cascade 85 calls,
  llm 96 calls, còn lại 0.
- `cascade_agent` product pass 0.0 dù oracle 10/10 — đã điều tra root cause (2026-10-21, không tốn thêm calls):
  đây KHÔNG phải bug scoring. `product_passed = verdict == passed AND gate in (passed, None)`
  (`evaluation/scoring.py:148`, `experiments/analysis.py:40`). Mọi run live đều dùng `gate_profile="strict"`
  (`experiments/live.py:216`); gate strict từ chối khi verdict inconclusive, khi run degraded (fallback LLM,
  `agent/policies/cascade.py:212-220` + `verify/gate.py:56-57`), hoặc khi healed (`verify/gate.py:60-62`).
  Cascade: 5 slots verdict passed nhưng gate refused + 5 slots verdict inconclusive → product 0/10 đúng luật gate.
  Kết luận giữ nguyên: khoảng hở verdict-vs-oracle có hệ thống dưới gate strict — finding về độ khắt khe
  của gate, không phải lỗi chấm. Không sửa scoring/gate để số đẹp hơn.
- `static_baseline` product pass 1.0 nhưng false pass 5/5 — minh chứng không tin verdict/pass của baseline thiếu assertion.
- Số liệu đã qua recompute offline khớp bundle.

### Probe gate-99 — bằng chứng trực tiếp 3 cơ chế từ chối (2026-10-21, 10 slots, 36 calls)

- Manifest tạm ngoài repo (diagnostic, không phải số liệu luận văn): RQ3 reps=1, 5 arms strict.
  Bundle `rq3-gate-probe-commandcode-99-1792553590`, recompute khớp.
- `gate.reasons` (mới ghi nhờ PR #15) cho thấy 3 cơ chế khác nhau sau cùng một `gate: refused`:
  cascade/create_item (oracle true, verdict passed) → `degraded_not_allowed` — cascade fallback sang LLM
  ngay cả ca benign; healing_replay/delete_healed (oracle true, verdict passed) → `healed_not_allowed_in_strict`
  — healing đúng nhưng strict chặn; cascade/delete_healed (oracle true) → `verdict_inconclusive`.

### Intervention gate-99 — dự đoán → can thiệp → khớp 3/3 (2026-10-21, 12 slots, 34 calls)

- Manifest tạm: thêm `cascade_agent_allow` + `healing_replay_allow` (nhờ PR #16), giữ 4 arm strict đối chứng.
  Bundle `rq3-gate-intervention-commandcode-99-1792553816`, recompute khớp. Dự đoán khóa trước khi chạy, khớp cả 3:
- `healing_replay_allow`/delete_healed → gate **passed** (lật so với strict) — healing đúng và guards đủ,
  strict là nguyên nhân duy nhất chặn product pass ở arm này.
- `cascade_agent_allow`/create_item → vẫn refused `degraded_not_allowed` — degraded không phụ thuộc profile
  (`verify/gate.py` từ chối degraded với mọi profile). Vấn đề của cascade là degradation (fallback), không phải healing.
- 4 arm strict lặp lại probe-99 — đối chứng ổn định.
- Giới hạn: manifest tạm version-99, N nhỏ — đây là bằng chứng cơ chế (mechanism), không phải ước lượng effect-size.
  Quyết định sản phẩm: giữ default strict (từ chối healed/degraded là invariant an toàn đúng đắn); `gate_profile`
  theo arm chỉ là công cụ nghiên cứu. Không bật production auto-healing theo receipt — đó là quyết định deployment.
## 5. Calibration hiện tại

Receipt mới nhất (cặp OpenCode): `artifacts/calibration/healing-default-1.json` — `bound_upper=0.776` trên ceiling `0.01`,
`evidence=measured` với `groups=2`. Profile giữ **provisional**; không dùng làm verified auto-healing profile.

### Finding live 2026-10-19 (cặp Command Code, key GOAT)

- Manifest `benchmarks/calibration/manifest-commandcode.yaml` (`profile_id: healing-commandcode`), chạy
  `agentqa calibration execute --live` với `AGENTQA_MODEL_PAIR=commandcode`: 37 trials, 18 model calls,
  receipt `artifacts/calibration/healing-commandcode-1.json`.
- Kết quả: `evidence=measured`, `sample_units=2`, `groups=2`, `bound_upper=0.776` (Clopper-Pearson một phía,
  confidence 0.95) trên ceiling `0.01` → status **provisional** (`bound_exceeds_ceiling`).
- Dữ liệu là measured và hợp lệ; không nới ngưỡng để đạt. Production auto-healing cho cặp Command Code
  vẫn chờ calibration đạt ceiling; chi tiết trials trong `artifacts/research/calibration-healing-commandcode-*/trials.json`.

### Protocol v2 — verification winner-only, đơn vị trial (pre-register 2026-10-19)

- Vấn đề: bound v1 tính theo đơn vị family, live mapping chỉ có 2 families cho split calibration nên
  units tối đa là 2 (bound tốt nhất 0.776) — chạy thêm repetitions không giúp. Đây không phải lỗi code.
- Quyết định (hướng B): protocol mới, đơn vị bound là trial. Winner v1 cả hai pair là `heuristic-0.5-0.1-24`.
  Manifest v2 (`manifest-v2.yaml` cho OpenCode, `manifest-commandcode-v2.yaml` cho Command Code) giữ nguyên
  splits/search space/budgets, thêm `verification`: winner + 3 families × 54 items × 2 seeds = 324 trials,
  thứ tự xáo trộn theo `shuffle_seed` khai báo trước, mỗi trial namespace/fixture/seed riêng, item/label
  khác nhau theo `{index}`/`{seed}`.
- Receipt v2 dùng `criteria_version=acceptance-refusal-loss-trial/1`, bound Clopper-Pearson một phía trên
  tổng trials scorable; `ready` khi và chỉ khi bound ≤ 0.01 và ≥ 2 families. Tiêu chí chốt trước khi chạy;
  receipts v1 giữ provisional theo luật cũ, không viết lại.
- Giới hạn khai báo: v2 đo repeatability trên families đã map, chưa đo khái quát hóa cross-family.
- Lệnh chạy: `agentqa calibration execute --manifest benchmarks/calibration/manifest-commandcode-v2.yaml --live --stage verify`
  (và `manifest-v2.yaml` cho cặp OpenCode, với `AGENTQA_MODEL_PAIR` khớp manifest).

### Finding live v2 lần 1 — void do fixture seed (2026-10-19)

- Chạy 324 trials nhưng tất cả `unscorable`, 0 model calls, receipt `missing_units`.
- Nguyên nhân (lỗi code, đã fix): verification truyền `fixture_seed` có hậu tố seed (`success-20261010`)
  trong khi `TaskboardFixture.prepare` chỉ nhận seed khai báo (`success`, `duplicate_rejected`, ...) nên
  fixture không dựng được trạng thái nào. Run void này giữ nguyên làm bằng chứng, không dùng.
- Fix: verification dùng đúng `fixture_seed` gốc của spec; khác biệt giữa các trial đến từ namespace UUID,
  item_name riêng (`{base}-{index:03d}-{seed}`), fixture reset và thứ tự xáo trộn — có test khóa
  (`test_verification_run_uses_exact_fixture_seeds_and_distinct_items`). Manifest v2 không đổi nên
  pre-register vẫn giữ nguyên hiệu lực.

### Finding live v2 lần 2 — winner v1 bị bác bỏ (2026-10-19)

- 324/324 trials scorable, bound 0.379 trên ceiling 0.01 → **provisional** (`bound_exceeds_ceiling`).
  Receipt `artifacts/calibration/healing-commandcode-v2.json` (criteria trial/1, measured).
- Phân bố lỗi nói lên đúng điều cần đo: `taskboard-delete` 108/108 correct, `taskboard-pilot` 108/108
  correct, `taskboard-ambiguous` 108/108 **false heal** (đáng lẽ phải refuse khi nhãn trùng).
  Winner v1 (`heuristic-0.5-0.1-24`) an toàn trên item cố định nhưng chữa bừa khi item varies — protocol v2
  đã làm đúng việc của nó: bác bỏ profile chưa đủ an toàn thay vì cho qua.
- Bước tiếp theo theo protocol: verify ứng viên ngưỡng chặt hơn (`heuristic-0.6-0.15-24`, manifest v3
  pre-register riêng `manifest-commandcode-v3.yaml`), kỳ vọng tăng refusal đúng trên ambiguous mà không
  mất correct heal.

### Pre-register v4 — verify lại sau healer fix (2026-10-19)

- Manifest `benchmarks/calibration/manifest-commandcode-v4.yaml` (`profile_id: healing-commandcode-v4`,
  version 4): cùng verification plan v2/v3 (324 trials), ứng viên quay lại winner gốc
  `heuristic-0.5-0.1-24` vì code healer đã đổi (quy tắc `duplicate_identity`, PR #6) làm mọi receipt v2/v3
  hết hiệu lực so sánh. Kỳ vọng: ambiguous chuyển từ false heal sang refusal → 0 errors → bound ≤ 0.01.
- Lệnh chạy sau khi merge PR chứa fix: `agentqa calibration execute --manifest
  benchmarks/calibration/manifest-commandcode-v4.yaml --live --stage verify` với
  `AGENTQA_MODEL_PAIR=commandcode`.

### Finding live v4 — fix chưa đổi hành vi (2026-10-19)

- 324/324 scorable, bound vẫn đúng 0.3789738832817356, phân bố y hệt v2/v3 (ambiguous 108/108 false heal).
  Receipt `artifacts/calibration/healing-commandcode-v4.json`.
- Nguyên nhân đã xác minh bằng trial instrument (dump scene thật): twins live cùng (role, tên) `button/Xoá`
  nhưng khác scope, quy tắc cũ loại scope nên không kích hoạt. Đã sửa thành scope-blind (PR #8).

### Finding live v5 — READY đầu tiên (2026-10-19)

- 324/324 scorable, 0 errors, 0 model calls → bound **0.0092** ≤ ceiling 0.01 → status **ready**.
  Receipt `artifacts/calibration/healing-commandcode-v5.json` (criteria trial/1, measured).
- Phân bố đúng thiết kế: `taskboard-delete` 108/108 correct heal, `taskboard-pilot` 108/108 correct heal,
  `taskboard-ambiguous` 108/108 **refusal** (0 false heal). Quy tắc duplicate-identity scope-blind hoạt động
  đúng: trang trùng lặp → từ chối, trang benign → phục hồi đúng.
- Đây là verified auto-healing profile đầu tiên của repo. Bật production auto-healing (gate strict hay
  allow_healing) là quyết định deployment riêng, không tự động theo receipt ready.

### Finding live v7 — cascade READY (2026-10-19)

- 324/324 scorable, 0 errors, 108 model calls (Jev consultations) → bound **0.0092** → **ready**.
  Receipt `artifacts/calibration/healing-commandcode-v7.json` (criteria trial/1, measured).
- Phân bố: delete/pilot 108/108 correct heal mỗi family, ambiguous 108/108 **refusal**, 0 false heal.
  Healer-level check chặn được cả đường model ranker (v6 false heal 72/72 không còn tái diễn).
- Lưu ý chi phí: check đặt sau ranker nên Jev vẫn được gọi trước khi refuse (108 calls/324 trials).
  Muốn tiết kiệm có thể kiểm tra duplicate trước khi gọi model — để dành tối ưu sau, không đổi semantics lúc này.
- Với v5 (heuristic ready) + v7 (cascade ready), cặp commandcode có đủ profile verified cho cả hai ranker
  chính. Bật production auto-healing (và chọn ranker/profile nào) là quyết định deployment.

### Pre-register v5 — verify lại sau fix scope-blind (2026-10-19)

- Manifest `benchmarks/calibration/manifest-commandcode-v5.yaml` (`profile_id: healing-commandcode-v5`,
  version 5): cùng verification plan 324 trials, winner `heuristic-0.5-0.1-24` + healer scope-blind.
- Kỳ vọng: ambiguous chuyển sang refuse → 0 errors → bound ≤ 0.01 → ready. Lệnh chạy sau khi merge PR #8:
  `agentqa calibration execute --manifest benchmarks/calibration/manifest-commandcode-v5.yaml --live --stage verify`
  với `AGENTQA_MODEL_PAIR=commandcode`.

### Finding live v3 — ngưỡng không phải nguyên nhân (2026-10-19)

- `heuristic-0.6-0.15-24`: 324/324 scorable, bound **đúng 0.3789738832817356 như v2** → provisional.
  Phân bố y hệt: ambiguous 108/108 false heal, delete/pilot 108/108 correct.
- Kết luận có cơ sở: ngưỡng (min_score/margin) không ảnh hưởng — v1 cho thấy cả LLM lẫn cascade cũng
  false-heal ambiguous trên item cố định, chỉ heuristic refuse được đúng 1 lần nhờ tie chính xác.
  Vấn đề nằm ở healer: thiếu quy tắc refuse tường minh khi tồn tại distractor trùng danh tính, chứ không
  phải ở ngưỡng hay số lượng trials. Chạy thêm vòng verify với ứng viên hiện có chỉ tốn tài nguyên.
- Quyết định: dừng vòng verify ở đây; production auto-healing giữ provisional. Công việc tiếp theo là
  product fix (quy tắc refuse khi duplicate-identity) rồi mới verify lại từ đầu — thuộc phạm vi thiết kế
  healer (P20), cần spec riêng, không nhồi thêm vào protocol calibration hiện tại.
- Không chạy opencode v2: heuristic không gọi model nên hành vi pair-independent; chạy lại chỉ lặp lại
  kết quả với chi phí browser vô ích. Kết luận áp dụng cho cả hai pair.

### Giới hạn cấu trúc v1 (cả hai pair, 2026-10-19)

- Bound tính theo đơn vị family: `profiles.py:_selection_units` giữ một trial đầu tiên cho mỗi family, và
  `build_receipt` đòi ít nhất 2 groups độc lập. Live mapping hiện tại (`live.py:LIVE_CALIBRATION_CASES`) chỉ có
  3 families trên app taskboard, trong đó split `calibration` chỉ dùng 2 (`taskboard-delete`, `taskboard-ambiguous`)
  nên số units tối đa là 2, bound tốt nhất có thể là 0.776 trên ceiling 0.01.
- Chạy thêm repetitions trên cùng families không tăng units. Thoát provisional đòi hỏi hoặc thêm families
  live-mapped mới (operators + oracle cho shopflow/canvasdesk), hoặc định nghĩa lại đơn vị bound — cả hai đều
  là thay đổi protocol nghiên cứu, phải chốt mẫu số trước khi chạy theo `research-questions.md`, không tự đổi
  sau khi xem kết quả.

### Finding live v8 — verify ready trên 5 families (2026-10-22, cặp commandcode)

- Select (`manifest-commandcode-v8.yaml`, 4 calibration + 1 pilot families): provisional
  (`bound_exceeds_ceiling`), units 4, bound 0.527, 42 calls — đúng kỳ vọng luật cũ theo đơn vị family.
- Verify ứng viên pre-register `heuristic-0.5-0.1-24` (5 families × 54 items × 2 seeds): **ready**,
  540/540 trials scorable, bound Clopper-Pearson một phía 0.0055 ≤ ceiling 0.01, 0 model calls
  (ranker heuristic). Hai families ambiguous mới (canvasdesk/shopflow) refuse đúng thay vì false heal.
- Bundle verify Elligible làm verified healing profile cho nghiên cứu; production auto-healing vẫn giữ
  provisional cho tới quyết định deployment riêng.

### Finding RQ2 v3 — cascade leo thang thật trên twins rồi refuse (2026-10-22, cặp commandcode)

- `rq2-commandcode.yaml`: 60/60 slots, 0 blocked/errors, 15 calls.
  Mỗi arm correct_heals 5, refusals 5, false_heals 0.
- Case twins (`taskboard_delete_twins_healed`): 20/20 refuse mọi arm (verdict inconclusive → gate refused).
  Arm cascade tốn đúng 1 call/slot trên twins rồi vẫn refuse — leo thang có thật, không pass hình thức.
- Kết luận: fixture-seeded twins ép heuristic refuse và cascade phản ứng đúng thiết kế.

### Finding RQ1 v3 — không khác biệt có ý nghĩa, CI rộng như dự kiến (2026-10-22, cặp commandcode)

- `rq1-commandcode.yaml`: 50/50 slots (25/arm), 468 calls, 0 blocked/errors.
  `agent_llm_hybrid` pass 0.28; `agent_llm_vision_first` pass 0.24.
- So sánh ghép cặp (5 pairs, bootstrap 10000, Holm): chênh lệch ước lượng 0.2, CI 95% [0.0, 0.6],
  p = 0.65 — không bác bỏ được giả thuyết ngang nhau; non-inferiority ở margin 0.05 giữ được nhưng CI
  rộng, đúng như nhận định cần ~750–1500 slots/arm mới thắt được equivalence ở margin này.
- Chi tiêu live đợt này: select 42 + verify 0 + RQ2 15 + RQ1 468 ≈ 525 calls.
