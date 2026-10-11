# Thực nghiệm, benchmark và đánh giá

- Ngày: 2026-10-06
- Trạng thái: Pipeline/protocol đã triển khai (P27–P30); đã chạy live calibration + RQ1–RQ3 với provider thật (receipts/bundles trong `artifacts/`), calibration còn provisional theo bound đo được
- Phạm vi: RQ1–RQ3, calibration, mutation, oracle và export
- Liên quan: [Mục tiêu RQ](../research-questions.md), [spec](../specs/product-spec.md), [Platform](platform-and-storage.md)

## 1. Tách runtime và evaluator

Runtime nhận public execution snapshot: case/data, environment/build digests, blind variant token, mode/policy/calibration và budgets. Không nhận tên operator gợi đáp án, expected target maps, labels, scoring output hoặc raw oracle URLs. Model input audit ghi exact safe bytes/schema version để kiểm tra leakage.

Evaluator process có role và oracle database riêng, đọc safe action receipts/evidence, application fixture receipts và ground truth. Nó chấm independent `oracle_task_success`, detection/healing labels, false pass và scorable status; không sửa product verdict. Model/worker không có filesystem mount hoặc DB quyền đọc oracle.

Oracle là code/rule/ground-truth versioned có thể kiểm tra, không là cùng LLM "nhận xét mình làm đúng". Cases ngoài benchmark không có oracle không được mặc định task success dựa trên product passed.

## 2. Bộ benchmark

| Ứng dụng kiểm soát | Nhóm tình huống |
|---|---|
| `taskboard` | CRUD, đăng nhập, duplicate labels/rows, dữ liệu động, validation âm và multi-entity scope |
| `shopflow` | Search/filter/cart/checkout synthetic, select/checkbox, asynchronous state, tabs/frames, upload/download và relation assertions |
| `canvasdesk` | Widget/canvas/hotspots thị giác, viewport/scroll, visual state, image-only controls và delayed rendering |

Mỗi case gồm requirement/expected outcome, fixture/reset và applicable operator matrix. Static baseline, AgentQA case authoring và evaluator đều truy từ requirement nhưng baseline plans được soạn/kiểm tra độc lập, không copy plan AI rồi gọi đó là độc lập.

Benchmark registry versioned chứa public assets và private oracle package riêng. Build material cho worker không include private package; environment data reset dùng blinded resource IDs. UI demo dùng synthetic accounts/files, không cần tài khoản/dữ liệu thật của người dùng.

Coverage inventory phủ từng operation/evaluator và failure scenario của spec, không đếm số cases thay cho độ đa dạng. Thí nghiệm chính chỉ chạy corpus có requirement, fixture và oracle hợp lệ; inventory release check sẽ từ chối corpus thiếu nhóm giao dịch, bất đồng bộ hoặc thị giác.

## 3. Mutation model

| Nhóm | Operators | Kỳ vọng đánh giá |
|---|---|---|
| Giữ nghiệp vụ | ID/class/test attribute đổi; vùng/DOM structure; vị trí/viewport; label tương đương | Agent/test có thể tìm đúng target và hoàn thành |
| Gây nhầm | ID cũ được gán cho distractor; same-name duplicates; entity row reorder | Đo identity guard và false healing, không chỉ locator missing |
| Lỗi nghiệp vụ | Bỏ side effect; tác động entity sai; sai value/state/validation; output/count bị sai | Test phải phát hiện lỗi, không healing expectation để đạt |
| Temporal/state | Delay/render race, stale element, partial response | Phân biệt chờ hợp lệ, timeout/unknown và business failure |

`VariantManifest` private gồm operator/version/seed, applied patch, app build before/after, target identity map và oracle assertions. Public snapshot chỉ có build digest/blind token. Generator chạy trên fixture app có registry hooks, xác minh patch thực sự áp và semantics classification đúng trước evaluation; equivalent/non-applied mutants ghi invalid reason.

Ground truth element mapping nằm trong fixture/evaluator registry, không là `data-oracle-id` trong DOM hay overlay. Trusted sensor ghi actual action target bằng opaque runtime reference và evaluator ánh xạ out-of-band tới entity/handler identity. Không cho worker query map này; semantic collector không lấy private metadata. Action-level ground truth cho phép chấm wrong heal kể cả khi ca cuối failed.

Mutation đổi ID không làm hỏng mọi semantic locator. Eligibility/mismatch opportunities được tính theo locator recipe/guard đã pin; không tính một thay đổi vô hại đối với test thành false negative detection. RQ2 có robustness cohort với descriptor bình thường và fragility cohort với preferred locator cố định; cohort được báo riêng, không dùng cohort cố ý fragile để khẳng định vượt mọi test Playwright.

Trong run live, mutation được áp atomically cùng fixture prepare bên trong mỗi execution: harness đăng ký "mutation intent" (operator + params, control token) trước khi submit; app giữ intent riêng theo namespace và áp nó ngay sau khi dựng seed, nên reset của coordinator không xóa variant. Environment revision mang `fixture_seed` để coordinator prepare đúng seed của case (ví dụ `duplicate_rejected`); runtime chỉ thấy public snapshot và token mù, không nhận tên operator hay patch. `ExecutionSpec.fixture_seed` và `executions.parameters` (kế thừa environment parameters) giữ nguyên semantics: worker merge environment + execution parameters, evaluator đọc cùng nguồn.

## 4. Runtime records cho scoring

`EvaluationInput` gồm execution snapshot_digest, step/command actual targets, branch/completion proofs, healing attempts/refusals và evidence integrity. `OracleRecord` private chứa expected target/effect, mismatch opportunities và applicability. `EvaluationResult` có evaluator/schema/version, input/oracle digests, task outcome, per-opportunity labels, scorable flag/reason và product comparison.

Opportunity key: case+variant+step instance+original target identity. Repeated retry cùng mismatch không tạo opportunity mới; mỗi healing attempt có label riêng. Detection positive là guard/runtime đánh dấu cần resolve khác, không tự tạo từ mọi mutation known trong oracle. Candidates không dùng để "chấm đúng" nếu action actual target không có receipt.

Unscorable thiếu target/effect evidence không bị gán correct. Empty denominator → not_applicable. Variant invalid trước evaluation được tách khỏi valid corpus theo manifest gate; blocked/quota/timeout của một valid scheduled execution vẫn thuộc task-success denominator. Failed provider không được xóa khỏi corpus để tăng tỷ lệ.

Oracle task outcome có true/false/unscorable. Với unscorable, báo guaranteed success lower bound `known_true / valid_scheduled` và possible upper bound `(known_true + unscorable) / valid_scheduled`, kèm coverage; không đổi unscorable thành oracle false. False-pass denominator chỉ gồm known oracle false, đúng spec. Execution error có thể vẫn đạt goal theo independent oracle; giữ hai chiều kết quả để phân tích, không đồng nhất chúng.

## 5. Calibration protocol

Calibration split theo case/entity/variant families; không chia các gần-bản-sao của cùng target vào calibration và evaluation. Pilot dùng subset riêng để ước tính variance và xác minh protocol. Evaluation corpus labels không dùng để sửa weights/prompts/thresholds.

`CalibrationProfile` gồm ranker/features/question set/model route versions, candidate population groups, similarity weights, p_max/confidence/margin thresholds, guard policy và validation receipts. Search candidates trên calibration, chọn theo quality policy đã khai báo ưu tiên false healing thấp, rồi refusal/correct-heal efficiency; không chọn bằng pass rate cuối ca đơn lẻ.

Quality policy tự động hoá có `max_false_heal_rate`, confidence level và scope/action class. Chọn mặc định thiết kế 1% false-heal ceiling trên calibration phù hợp, confidence 95%; đây là mục tiêu chất lượng phải kiểm chứng, không là kết quả đã đạt hoặc vendor guarantee. Auto-healing profile chỉ ready khi bound theo protocol hỗ trợ mục tiêu; thiếu mẫu/bằng chứng giữ provisional. Không gọi inference confidence 0.99 là thay thế bound này.

Với các cơ hội độc lập, dùng one-sided exact binomial upper bound. Calibration quality gate dùng một acceptance trial đã preregistered từ mỗi independent target/case group, không dùng repetitions tương quan để tăng n. Trường hợp chưa đảm bảo grouping độc lập giữ profile provisional. Cluster bootstrap phục vụ mô tả/evaluation, không tự chứng minh rare-event ceiling: nếu không quan sát lỗi, resampling toàn zero không được báo upper bound bằng zero. Exact bound khi zero lỗi và n > 0 vẫn dương. Calibration receipt ghi sample units, grouping, bound method và refusal coverage. Các action class không được profile xác nhận từ chối hoặc dùng policy riêng, không extrapolate ngưỡng toàn cục.

Đóng digest profile trước evaluation. Model resolved version hoặc feature/question schema đổi làm profile cần revalidation; không silently giữ nhãn "đã hiệu chỉnh". Profile export không include private oracle examples trong prompt runtime.

## 6. RQ1

Primary arms: `agent + llm + hybrid` và `agent + llm + vision_first`, cùng Go `deepseek-v4.1-flash` và parameters. Semantic là ablation, cascade là experiment policy riêng. Same actions/marks/fixtures/checker và viewport; vision-first không nhận semantic DOM qua history/errors.

Local decision/action caches bypass trong cả hai arm. Provider cache nếu không tắt được phải ghi cached usage/state và tách cold/warm; không tuyên bố cache hoàn toàn off. Hybrid ghi trigger và image calls thật, không thay bằng text-only.

Metrics: oracle task success, input/output/cache/image usage theo availability, reported/estimated cost cùng basis, phase wall time, steps/calls và image escalation. Unknown image-token breakdown không được suy ra từ tổng byte ảnh; báo tổng input usage và missing breakdown.

Primary analysis ghép cặp cùng case/variant/data theo run block random hoá thứ tự để giảm ảnh hưởng cache/provider load. Báo success-rate difference và CI cùng cost/time distributions/paired ratios. Chọn non-inferiority margin 5 điểm phần trăm như quality decision trong preregistered protocol; không khẳng định giữ success nếu CI chưa hỗ trợ. Cả margin và primary metrics nằm trong manifest trước evaluation.

Nếu Go route không nhận ảnh qua conformance, RQ1 blocked có record, không đổi model hoặc RQ. Khi user yêu cầu route/model mới sau này phải có revision design và protocol mới; không dùng một model ảnh khác rồi quy kết chênh lệch là chỉ observation.

## 7. RQ2

Arms theo spec: strict replay, healing với Go LLM, heuristic ranker, Jev–LLM cascade. Cùng target descriptors, preferred locator recipes, guards, fixtures và calibration/evaluation split. Stored locator alternative vẫn hợp lệ là normal resolution với event riêng, không tự gọi healing; descriptor cohort được báo để giải thích biến thể không gây mismatch.

Đo detection precision/recall trên oracle opportunities, correct/false healing trên mọi attempts, refusal và oracle task success. False pass so product verdict với oracle. Benign và bug variants tách bảng; extra wrong actions vẫn chấm wrong heal dù final assertions không đạt.

Graph theo mutation family/severity và target ambiguity, kèm counts/missingness. `allow_healing` gate không thay product verdict hoặc scoring. Oracle correctness không được đưa trở lại healer trong cùng run để sửa cho đúng.

## 8. RQ3

Arms: static baseline plan, LLM agent, cascade agent, strict replay và healing replay. Static plan do baseline authoring riêng, dùng cùng action/verification telemetry adapter để đo, không một loop có accounting khác. Agent-generated replay plan được pin sau authoring từ calibration/data riêng, không lấy evaluation run tốt nhất làm plan.

Chạy repetitions trên trạng thái fixture reset, browser context riêng, same declared concurrency/admission conditions. Chi phí authoring, inference/replay/healing, retries, diagnostics và subscription allocation tách; báo tích luỹ theo N lượt hồi quy đã khai báo. Maintenance proposal counts là dữ liệu quan sát; không đổi chúng thành giờ code tay hoặc công bảo trì giả.

Consistency theo signature status+verdict, đọc cùng task success/error rate. Throughput/suite wall time theo tải/concurrency, không cộng duration song song thành elapsed. Price/cost basis phải tương thích; free Jev không làm tổng Go/subscription hoặc preparation cost bằng zero.

## 9. Sample design và statistical engine

ManifestBuilder có `SampleDesign`: independent unit(case/entity/variant group), endpoints, confidence level, precision/non-inferiority target, pilot_digest và algorithm_version. Nó tính số independent units/repetitions cần thiết từ pilot variance hoặc conservative binary bound, xuất SampleSizeReport trước evaluation; không nhập một n thuận tiện sau khi thấy kết quả.

Binary proportions dùng exact/binomial khi độc lập, cluster bootstrap khi grouped; paired costs/times dùng bootstrap over case blocks, stratify application. SciPy/NumPy là statistical backend được chọn; random generator seed và 10,000 bootstrap replicates pin trong analysis settings. Degenerate/không đủ nhóm để resampling trả insufficient_support với descriptive counts, không bịa CI. Nếu corpus không đủ independent units theo target, báo CI không đủ hỗ trợ thay vì bịa precision; có thể tạo manifest mới bổ sung corpus trước evaluation mới. [SciPy binomial](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.binomtest.html), [bootstrap](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.bootstrap.html).

Predeclared primary comparisons/endpoints có family adjustment Holm khi kiểm định nhiều hypothesis; exploratory breakdowns ghi rõ exploratory. Per-application distributions và uncertainty phải có, không dùng 3 synthetic app để suy ra mọi website. Không có số liệu nội bộ nào được hardcode thành chart seed.

## 10. API, UI và export

ExperimentRevision immutable gồm corpus/arms/randomisation/samples/budgets/cache/analysis. Validate trả incompatibilities, calibration/capability và fixture/oracle integrity. Execute tạo expected slots trước chạy, slot unique theo manifest+case+variant+data+arm+repetition; rerun bổ sung linked attempt/run, không overwrite original.

Evaluator chạy read-only đối với browser/app state đã được chốt; late evidence bổ sung tạo scoring revision, giữ bản cũ và digests. Schema/error nếu thiếu data tạo unscorable reason. API results view tách product, oracle, gate và statistics.

Export bundle gồm public manifest, deidentified slot/run/event/call/healing/assertion/scoring JSONL, metric definitions, analysis settings, price/capability receipts và integrity manifest. Private oracle package chỉ export bằng quyền/kênh riêng; ordinary product export không có nó. Recompute command offline từ bundle phải tái tạo metric values/denominators và charts, không gọi model.

## 11. Nghiệm thu pipeline

Synthetic scoring fixtures gồm correct heal+passed, wrong heal+failed, wrong heal+passed, valid refusal, missed mismatch, unchanged valid target, invalid/equivalent variant, missing actual target, provider error, cost unknown và blocked vision capability. Expected labels/counters được tính độc lập từ ground truth fixture, không mirror scorer implementation.

Leak tests kiểm filesystem/DB grants, snapshot/prompt/history/image marker payload và names. Statistical fixtures kiểm denominator zero, cluster grouping, seed reproducibility, price basis mismatch và duplicate repetitions. Pipeline tự tái lập không đồng nghĩa đầu ra model tất định.

## 12. Cơ sở phương pháp

Tương đồng đa thuộc tính lấy ý tưởng từ [Similo](https://arxiv.org/abs/2208.00677); mutation-based adequacy tham khảo [MAEWU](https://yrahulkr.github.io/resources/papers/maewu.pdf). Grounding/observation tham khảo [SeeAct](https://arxiv.org/abs/2401.01614), [WebVoyager](https://arxiv.org/abs/2401.13919) và [Agent-E](https://arxiv.org/abs/2407.13032). Những lựa chọn dataset, quality targets và statistical protocol trên là thiết kế AgentQA, không phải khẳng định công cụ đã đạt hiệu quả của bài báo.
