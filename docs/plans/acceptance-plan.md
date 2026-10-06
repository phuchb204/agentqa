# Truy vết yêu cầu vào implementation plan

- Ngày: 2026-10-06
- Trạng thái: Kế hoạch kiểm tra; không phải kết quả tests
- Nguồn: [Spec](../specs/product-spec.md), [design mapping](../design/acceptance-mapping.md), [task/dependency index](rebuild-plan.md)

## 1. Yêu cầu chức năng

| Mã | Tasks | Nghiệm thu chính |
|---|---|---|
| FR-01 | P05, P06, P11, P24 | Environment/snapshot validation, role/fixture/origin binding |
| FR-02 | P16 | Source parsing/anchor/quarantine và unextractable facts |
| FR-03 | P17 | Requirement-backed proposal có expected outcomes |
| FR-04 | P02, P17, P18 | Compiler/source confirmation và editor assertion scope |
| FR-05 | P06, P18 | Immutable revisions, If-Match/history/conflict |
| FR-06 | P08, P17 | Egress/action policy và exploration coverage/gaps |
| FR-07 | P17, P23 | Suite/data/fixture revisions và complete execution matrix |
| FR-08 | P02, P17 | Portable bundle/digests, no credential/approval bypass |
| FR-09 | P14, P17, P18 | Draft agent run/proposal, provisional và promotion |
| FR-10 | P07, P08, P11, P23 | Browser/backend data namespaces và fixture isolation |
| FR-11 | P08, P10, P20 | Guard context/identity/unique trước admission |
| FR-12 | P08, P21 | Browser operation/capability matrix |
| FR-13 | P02, P21 | DSL branch/loop/capture/types/taint runtime |
| FR-14 | P10, P11, P14 | Completion/Verify thắng stop proposal |
| FR-15 | P09, P11 | Actual side-effect counters qua unknown/retry faults |
| FR-16 | P02, P10, P12, P15 | Typed errors/capabilities khác business failure |
| FR-17 | P12, P14 | Hai policies/versions và same checker/fixtures |
| FR-18 | P12, P14 | Native System One/schema/candidates/independent questions |
| FR-19 | P13, P14 | Modality audit/budgets và vision no-semantic leakage |
| FR-20 | P13, P15 | Real image capability receipt và unsupported blocking |
| FR-21 | P12, P15 | No provider/paid fallback, bounded retry accounting |
| FR-22 | P10, P20 | Reused ID/same-name mismatch dù selector tồn tại |
| FR-23 | P20, P29 | Healing/refusal logic và quality calibration receipt |
| FR-24 | P02, P20 | Expectation/branch/entity immutable dưới recovery |
| FR-25 | P18, P19, P20 | Actual healing record/diff và draft proposal riêng |
| FR-26 | P10, P20 | Narrow evidence resolver và separate actor receipts |
| FR-27 | P10, P11, P14 | Independent Verify không chấm theo model rationale |
| FR-28 | P10, P21 | Evaluator matrix, wait và expected/observed proof |
| FR-29 | P10, P11, P25 | Truth table/gate/CLI exit parity |
| FR-30 | P21, P22 | Visual baseline/mask/tolerance versions và diff |
| FR-31 | P19, P22 | Diagnosis label/provenance không sửa verdict |
| FR-32 | P06, P11, P19 | Durable run_seq, cursor/WS và reconnect |
| FR-33 | P16, P18, P19 | Source→case→checkpoint→evidence links |
| FR-34 | P19, P22 | Config/path alignment và comparison missingness |
| FR-35 | P06, P19, P24 | Scoped filters/cursors/counts/permissions |
| FR-36 | P22, P25 | Safe issue package/download, no auto-send |
| FR-37 | P09, P23 | Queue/admission/resource leases và global races |
| FR-38 | P09, P11, P19, P26 | Requested/effective controls, recovery/drain faults |
| FR-39 | P17, P23 | Suite/data plans, schedules/DST/overlap/fail-fast/reruns |
| FR-40 | P07, P23, P26 | Fixture lifecycle/probe/reset/cleanup receipts |
| FR-41 | P06, P09, P23 | Idempotent transactions, fences và external effects |
| FR-42 | P06, P09, P11, P26 | Partial durable trace/artifact integrity/restore |
| FR-43 | P06, P12, P14, P22 | All calls/purposes/cost bases/missingness và wall time |
| FR-44 | P05, P06, P24, P26 | Safe artifact grants/retention/ACL/integrity |
| FR-45 | P22 | Scoped versioned cache và live guard after hit |
| FR-46 | P27, P28, P29, P30 | Frozen manifest/split/oracle-independent execution |
| FR-47 | P27, P28 | Applied/classified valid mutations, private truth maps |
| FR-48 | P28, P29, P30 | Independent scoring/denominators/uncertainty/recompute |
| FR-49 | P11, P18, P19, P25 | Same authoritative API/client/CLI engine |
| FR-50 | P22, P25, P30 | Reports/JUnit/research export có provenance và redaction |
| FR-51 | P25 | CI templates và explicit signed outbox callbacks |

## 2. Yêu cầu phi chức năng

| Mã | Tasks | Evidence boundary |
|---|---|---|
| NFR-01 | P02, P10, P20, P28, P31 | Non-empty proofs/truth tables/false pass độc lập |
| NFR-02 | P01, P05, P08, P12, P16, P24, P31 | Synthetic canary không vào bất kỳ safe sink/prompt/frame/export |
| NFR-03 | P04, P05, P07, P23, P24, P31 | RLS/FKs/API/stream/artifact và backend/browser isolation |
| NFR-04 | P02, P08, P17, P24, P31 | Typed registry, sandbox/egress/upload/capability grants |
| NFR-05 | P06, P09, P23, P26, P31 | Crash/recovery/journal và no duplicate external effect |
| NFR-06 | P06, P13, P23, P31 | Reservation accounting và explicit truncation/missingness |
| NFR-07 | P06, P19, P26, P31 | Safe correlation/readiness/queue/model health, no secret labels |
| NFR-08 | P18, P19, P30, P31 | Keyboard/focus/live/empty/error/table-chart UI states |
| NFR-09 | P01, P08, P24, P26, P31 | Windows/Linux runtime/browser/sandbox và locked builds |
| NFR-10 | P01, P02, P03, P04, P26 | Import rules/schema parity/version migrations |
| NFR-11 | P06, P17, P26, P30, P31 | Portable metadata/manifest/digests và actual restore/recompute |
| NFR-12 | P01, P12, P15, P29, P31 | Offline no-network tests, separate real conformance/research |

## 3. Acceptance scenarios

| Mã | Tasks kiểm chính | Dữ kiện để chấm |
|---|---|---|
| AC-01 | P02, P06, P17, P18, P11 | Requirement+entity fixture, revision và replay effects |
| AC-02 | P16, P17 | Input sources/digests và known impact links |
| AC-03 | P08, P17 | Trap network origin/action scope receipts |
| AC-04 | P10, P11, P14 | Fake finish nhưng independent entity oracle false |
| AC-05 | P02, P17, P18 | Draft assertion/provenance constraints, no ready/gate bypass |
| AC-06 | P06, P10, P11, P25 | Missing proof/error không false failure hoặc pass |
| AC-07 | P09, P10, P23, P26 | Failed assertion trước worker/cleanup fault |
| AC-08 | P20, P29, P25 | Known correct heal, strict/allow_healing truth table |
| AC-09 | P07, P10, P20 | Reused ID/same-name intended vs actual target |
| AC-10 | P20, P28 | Refusal/wrong healing và actual oracle labels |
| AC-11 | P02, P08, P21 | Operation/evaluator/branch/capture matrix |
| AC-12 | P06, P09, P23 | Side-effect counter, command duplicates và epoch races |
| AC-13 | P12, P14, P15 | Fake protocol failures; real route receipts riêng |
| AC-14 | P13, P14, P15 | Exact modality bytes/marker image capability |
| AC-15 | P21, P22 | Immutable visual baseline và separate proposal |
| AC-16 | P19, P22 | Wrong diagnosis/config diff, no verdict rewrite |
| AC-17 | P09, P11, P19, P26 | Durable stream/control barriers và process loss |
| AC-18 | P07, P23 | Concurrent namespaces/ownership/schedule occurrence |
| AC-19 | P06, P12, P14, P22 | Known usage semantics, final/repair/retry/parallel calls |
| AC-20 | P05, P08, P16, P24, P26 | All sinks/redacted pixels/ACL/tombstone/retention |
| AC-21 | P27, P28, P29, P30 | Private ground truth, independent metric vectors |
| AC-22 | P18, P19, P22, P25 | Same snapshot across clients và safe exports/destinations |
| AC-23 | P01, P18, P24, P26, P31 | OS profiles, keyboard/roles và restore integrity |
| AC-24 | P06, P13, P23, P31 | Bound reservations/truncation/resource reason |

P31/P32 chạy và tổng hợp tất cả scenarios; bảng không có ý nghĩa tests đã pass. Source expectation phải ngoài component đang được kiểm, không sinh expected labels từ output chính implementation.

## 4. Quy tắc audit plan

1. P01–P32 có đúng một task definition và dependency DAG không cycle/missing ID.
2. FR-01–FR-51, NFR-01–NFR-12, AC-01–AC-24 đều có mapping và mọi task được dùng.
3. Mỗi task có files, bước triển khai, verify commands và done conditions; command provider đã được task upstream tạo.
4. Tasks code-ready không thay production/live gate receipts; fake fixtures không được gắn nhãn actual data/conformance.
5. Các paths code/tests/manifest là outputs tương lai; chỉ local Markdown links phải tồn tại ở bước viết plan.
6. Toàn bộ plan/source docs không chứa real keys, deadline/nhân lực để giới hạn phạm vi hoặc số liệu nghiên cứu bịa.
