# Truy vết và kiểm tra thiết kế

- Ngày: 2026-10-06
- Trạng thái: Truy vết thiết kế, không phải báo cáo tests đã pass
- Phạm vi: 51 FR, 12 NFR, 24 AC của [product spec](../specs/product-spec.md)

## 1. Yêu cầu chức năng

| Mã | Thành phần và cơ chế | Tài liệu |
|---|---|---|
| FR-01 | Environment revisions, origin/auth/fixture validation, run snapshot | [API](api-and-security.md), [Contracts](contracts-and-dsl.md) |
| FR-02 | Source extraction job, sandbox parser, anchors và unextractable status | [API](api-and-security.md), [Platform](platform-and-storage.md) |
| FR-03 | Authoring proposals có linked requirements và expected outcomes | [Contracts](contracts-and-dsl.md), [Web](web-experience.md) |
| FR-04 | Source provenance/confirmation, scoped assertions và promotion validation | [Contracts](contracts-and-dsl.md), [Verify](verification-and-healing.md) |
| FR-05 | Draft reducer/history, If-Match, ready immutable/diff | [Web](web-experience.md), [API](api-and-security.md) |
| FR-06 | Exploration jobs, environment action policy, observed coverage | [Engine](execution-and-models.md), [API](api-and-security.md) |
| FR-07 | Suite/data revisions và execution matrix, fixture binding | [Platform](platform-and-storage.md), [Contracts](contracts-and-dsl.md) |
| FR-08 | Versioned safe bundles, portable digest, credential exclusion | [Contracts](contracts-and-dsl.md), [API](api-and-security.md) |
| FR-09 | Agent authoring run, DSL proposal, provisional và explicit promotion | [Engine](execution-and-models.md), [Web](web-experience.md) |
| FR-10 | Browser session/context riêng, fixture namespace/reset | [Engine](execution-and-models.md), [Platform](platform-and-storage.md) |
| FR-11 | TargetGuard, uniqueness/entity/context và admission proof | [Verify](verification-and-healing.md), [Engine](execution-and-models.md) |
| FR-12 | Action registry, tab/frame/file/dialog typed capabilities | [Engine](execution-and-models.md), [Contracts](contracts-and-dsl.md) |
| FR-13 | DSL branch/loop/capture interpreter, type/taint và node instances | [Contracts](contracts-and-dsl.md), [Engine](execution-and-models.md) |
| FR-14 | Completion plan/postconditions/checkpoint và reducer | [Verify](verification-and-healing.md) |
| FR-15 | Prepared/accepted/dispatched journal, unknown effect và safe retry | [Engine](execution-and-models.md), [Platform](platform-and-storage.md) |
| FR-16 | Typed errors và capability/blocking, khác business failure | [Contracts](contracts-and-dsl.md), [Verify](verification-and-healing.md) |
| FR-17 | Hai policy, immutable model/prompt/question settings | [Engine](execution-and-models.md) |
| FR-18 | Native System One adapter, independent questions, candidate/schema guard | [Engine](execution-and-models.md) |
| FR-19 | Semantic/hybrid/vision-first pipelines, modality/input audits | [Engine](execution-and-models.md), [Experiments](experiments-and-evaluation.md) |
| FR-20 | Route capability receipts và image conformance gate | [Engine](execution-and-models.md) |
| FR-21 | HTTP retries/accounting theo các routes trong registry, no model fallback | [Engine](execution-and-models.md) |
| FR-22 | Guard ngay cả locator resolve và reused ID/distractor | [Verify](verification-and-healing.md) |
| FR-23 | Heuristic/LLM/cascade ranking, calibrated acceptance/refusal | [Verify](verification-and-healing.md), [Experiments](experiments-and-evaluation.md) |
| FR-24 | Immutable expectation/branch/entity constraints và runtime binding | [Contracts](contracts-and-dsl.md), [Verify](verification-and-healing.md) |
| FR-25 | HealingRecord, actual target và proposal revision riêng | [Verify](verification-and-healing.md), [Web](web-experience.md) |
| FR-26 | Evidence identity port, comparator/expectation không vào resolver | [Verify](verification-and-healing.md) |
| FR-27 | Verify độc lập, checkpoint/final và no policy verdict authority | [Verify](verification-and-healing.md) |
| FR-28 | Typed evaluators, wait theo condition và evidence receipts | [Verify](verification-and-healing.md) |
| FR-29 | Pure verdict/gate reducers, non-empty completion, CLI precedence | [Verify](verification-and-healing.md) |
| FR-30 | Versioned visual baseline/mask/tolerance, diff và proposal | [Verify](verification-and-healing.md) |
| FR-31 | Diagnostic jobs/labels tách verdict và cause evidence | [Web](web-experience.md), [Engine](execution-and-models.md) |
| FR-32 | Durable SSE run_seq, reconnect/dedupe, live safe frame stream | [API](api-and-security.md), [Web](web-experience.md) |
| FR-33 | Revision/step/checkpoint/evidence source links | [Web](web-experience.md), [Contracts](contracts-and-dsl.md) |
| FR-34 | Run compare config diff và node/path alignment | [Web](web-experience.md) |
| FR-35 | Workspace filters, opaque pagination và scoped counts | [API](api-and-security.md), [Platform](platform-and-storage.md) |
| FR-36 | Issue package từ safe read model, download không auto-send | [API](api-and-security.md), [Web](web-experience.md) |
| FR-37 | Durable queue, admission slots, resource reservations và namespace | [Platform](platform-and-storage.md) |
| FR-38 | Requested/effective controls, fence, recovery/quarantine | [Engine](execution-and-models.md), [Platform](platform-and-storage.md) |
| FR-39 | Frozen suite matrix, occurrence keys, DST/overlap/rerun records | [Platform](platform-and-storage.md) |
| FR-40 | Versioned fixture registry, prepare/reset/cleanup receipts | [Platform](platform-and-storage.md) |
| FR-41 | Idempotency transaction, lease epochs, supervisor command admission | [Platform](platform-and-storage.md), [Engine](execution-and-models.md) |
| FR-42 | Append events/calls, immutable snapshot và partial artifact records | [Platform](platform-and-storage.md) |
| FR-43 | Call/usage/cost basis ledger, retries/finish/parallel accounting | [Engine](execution-and-models.md), [Platform](platform-and-storage.md) |
| FR-44 | Private artifact store, grants, redaction/retention/integrity | [Platform](platform-and-storage.md), [API](api-and-security.md) |
| FR-45 | Decision cache namespace/version/input digest, replay guard | [Engine](execution-and-models.md) |
| FR-46 | Immutable manifest/split, blinded slots, oracle process/database | [Experiments](experiments-and-evaluation.md) |
| FR-47 | Fixture mutation operators, private map, validity/classification | [Experiments](experiments-and-evaluation.md) |
| FR-48 | Scoring revisions, denominators, uncertainty và recompute bundle | [Experiments](experiments-and-evaluation.md), [Web](web-experience.md) |
| FR-49 | API application services dùng chung bởi Web/CLI/CI | [API](api-and-security.md), [Kiến trúc](../architecture.md) |
| FR-50 | Versioned exports/read models, JUnit gate và raw research ledgers | [API](api-and-security.md), [Experiments](experiments-and-evaluation.md) |
| FR-51 | CI templates, explicit webhook destinations, signed idempotent outbox | [API](api-and-security.md), [Platform](platform-and-storage.md) |

## 2. Yêu cầu phi chức năng

| Mã | Thiết kế đáp ứng |
|---|---|
| NFR-01 | [Verify](verification-and-healing.md): reducer/proofs/strict guard; false-pass oracle trong [Experiments](experiments-and-evaluation.md) |
| NFR-02 | [API/security](api-and-security.md): secret grants/taint, safe evidence trước capture/persist, sensitive handles không serialize |
| NFR-03 | [Platform](platform-and-storage.md): RLS/composite FKs, grants và fixture/context isolation |
| NFR-04 | [API/security](api-and-security.md): proxy/OS egress, URL/DNS/redirect/host boundaries, typed action registry |
| NFR-05 | [Platform](platform-and-storage.md): queue/journal/quarantine/reconcile, no duplicate unknown effects |
| NFR-06 | [Engine](execution-and-models.md): versioned budgets/reservations và truncation manifest |
| NFR-07 | [Platform](platform-and-storage.md): readiness/health/structured correlation và safe telemetry |
| NFR-08 | [Web](web-experience.md): focus/keyboard/aria-live, charts có bảng, error states |
| NFR-09 | [Kiến trúc](../architecture.md): Python/Node/container baseline, Windows/Linux browser profiles |
| NFR-10 | [Contracts](contracts-and-dsl.md): schema/ports, import boundaries, generated client và migrations |
| NFR-11 | [Platform](platform-and-storage.md): consistent DB/blob backup, restore digests và keyring riêng |
| NFR-12 | [Engine](execution-and-models.md): fake transports và manual live conformance, offline fault/evaluator tests |

## 3. Nghiệm thu khi triển khai

| Mã | Test boundary cần dùng | Dữ kiện độc lập để kết luận |
|---|---|---|
| AC-01 | API + editor + engine, models fake | Requirement fixture và actual entity result |
| AC-02 | Extract/import/export + revisions | Input documents, portable digest và expected impact graph |
| AC-03 | Browser + egress/exploration | Trap origin và action permission fixture |
| AC-04 | Agent fake finish + Verify thật | Entity oracle và pinned assertion source |
| AC-05 | Compiler/promotion/gate | Draft thiếu/assertion inferred không confirmed |
| AC-06 | Evidence/verifier fault injection | Known unavailable proof, expected inconclusive/exit 2 |
| AC-07 | Engine cleanup/worker fault | Valid failed assertion trước crash, immutable receipt |
| AC-08 | Target mutation + healer + gate | Private target/effect map và strict/allow_healing truth table |
| AC-09 | Same-name/reused-ID browser fixture | Intended entity và actual clicked target |
| AC-10 | Ambiguous/wrong recovery fixture | Independent oracle labels, not final pass alone |
| AC-11 | Browser action registry + DSL | Expected effects per operation/frame/tab/file |
| AC-12 | Journal/idempotency/process faults | Backend side-effect counter và supervisor receipts |
| AC-13 | Fake HTTP transports + ledger | Missing answer/quota/error shapes và expected route usage |
| AC-14 | Input payload audit + image fixture | Exact bytes sent, model fake marker response; live route capability probe riêng |
| AC-15 | Visual evaluator/editor | Pin baseline/mask/tolerance digest before proposal |
| AC-16 | Diagnostic/compare | Incorrect diagnosis fixture, known config differences |
| AC-17 | SSE/WS + controls/process faults | Committed sequences, lost cursor/reconnect and effective control barriers |
| AC-18 | PostgreSQL races + fixtures/scheduler | Unique occurrence/ownership và data namespace receipts |
| AC-19 | Typed usage/cache/ledger | Provider fixture accounting semantics và missing fields |
| AC-20 | Secret canary + ACL/redaction + artifacts | Canary không có trong tất cả safe sinks; forbidden identities |
| AC-21 | Manifest/mutation/evaluator pipeline | Private corpus ground truth và independently expected counters |
| AC-22 | Web/API/CLI + exports | Same immutable snapshot, authoritative result và destination controls |
| AC-23 | UI keyboard + OS matrix + backup restore | Role expectations, digest/reference integrity, platform smoke |
| AC-24 | Budget/observation bounds | Planned max/reservations, known dropped regions, expected reason |

Các test trên chưa được tạo/chạy. Ưu tiên fixtures chứng minh external outcome hoặc boundary, không viết tests chỉ xác nhận implementation trả lại giá trị của chính nó. Ordinary tests luôn không gọi model API thật; conformance thật dùng synthetic data và có usage record riêng.

## 4. Bộ kiểm tra thiết kế trước plan

- Mọi FR/NFR có chủ sở hữu thành phần và tài liệu; mọi AC có boundary và nguồn expectation độc lập.
- Không có dependency Agent ↔ Verify, secret value trong schema persistable hoặc oracle trong runtime snapshot.
- Ready/import content digest không phụ thuộc DB IDs/lifecycle/secret; source aliases/DSL references resolve hoặc fail validation.
- Run-level SSE có durable ordering riêng, headers global unique, payload partition không phá idempotency.
- Cancel requested khác effective, unknown side effects không được replay dựa trên timeout, stale writes bị chặn.
- Cost basis/missingness và business verdict/evidence completeness tách; policy/provider versions không tự đổi.
- Tất cả quyết định về ngưỡng/calibration là mục tiêu/protocol, không kết quả đã đo.

Kế hoạch triển khai tiếp theo sẽ tham chiếu các mã này và thêm test files/commands khi có scaffold. Bước thiết kế không tạo test giả, môi trường runtime hoặc commit đầu tiên.
