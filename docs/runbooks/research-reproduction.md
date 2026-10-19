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

### Finding live RQ1 cặp Command Code (2026-10-19, key GOAT)

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

### Finding live RQ3 cặp Command Code (2026-10-19, key GOAT)

- Bundle `rq3-stability-commandcode-1-1792385599`: 20/20 slots completed, 0 blocked/errors, 56 calls.
  Oracle: `cascade_agent` 4/4 đúng, `healing_replay` 4/4, `llm_agent` 1/4, `static_baseline` 2/4, `strict_replay` 2/4.
- Điểm chênh đáng chú ý (ghi nhận, không sửa verdict): `cascade_agent` oracle 4/4 nhưng product pass 0.0 —
  engine không ra verdict passed dù oracle độc lập chấm đúng. Đây đúng là khoảng hở verdict-vs-oracle mà RQ3
  cần đo, không phải lỗi chấm; cần phân tích run detail trước khi diễn giải.
- Mẫu thăm dò (4 slots/arm sau repetitions=2), chưa đủ cho kết luận ổn định/chi phí của RQ3.
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

### Giới hạn cấu trúc v1 (cả hai pair, 2026-10-19)

- Bound tính theo đơn vị family: `profiles.py:_selection_units` giữ một trial đầu tiên cho mỗi family, và
  `build_receipt` đòi ít nhất 2 groups độc lập. Live mapping hiện tại (`live.py:LIVE_CALIBRATION_CASES`) chỉ có
  3 families trên app taskboard, trong đó split `calibration` chỉ dùng 2 (`taskboard-delete`, `taskboard-ambiguous`)
  nên số units tối đa là 2, bound tốt nhất có thể là 0.776 trên ceiling 0.01.
- Chạy thêm repetitions trên cùng families không tăng units. Thoát provisional đòi hỏi hoặc thêm families
  live-mapped mới (operators + oracle cho shopflow/canvasdesk), hoặc định nghĩa lại đơn vị bound — cả hai đều
  là thay đổi protocol nghiên cứu, phải chốt mẫu số trước khi chạy theo `research-questions.md`, không tự đổi
  sau khi xem kết quả.
