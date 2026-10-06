# Contracts và Case DSL

- Ngày: 2026-10-06
- Trạng thái: Thiết kế đề xuất; chưa có schema/code triển khai
- Phạm vi: Contracts, authoring, engine, API và client types
- Liên quan: [Kiến trúc](../architecture.md), [spec](../specs/product-spec.md)

## 1. Quy tắc hợp đồng

Contracts là package lá chứa validation models, enums, immutable documents và ports. Python dùng Pydantic v2; wire JSON và JSON Schema 2020-12 được sinh từ cùng nguồn. TypeScript types sinh từ OpenAPI, DSL/event runtime validation dùng schema tương ứng. Không viết lại rules nghiệp vụ trong client.

Mỗi envelope có `schema_version`; API major `/api/v1` tách khỏi content schema version. Thêm optional field có default có thể tương thích; thay semantics/type hoặc bỏ field cần schema major, migration và fixture compatibility. Unknown node/action trong DSL bị từ chối; không silently drop. Adapter provider có schema wire riêng, không tái sử dụng case schema để parse response.

ID persisted dùng UUID4; workspace scope đi cùng ID. Event sequence và lease epoch là integer độc lập, timestamp không dùng làm sequence. Timestamps UTC aware ISO 8601; elapsed durations lấy monotonic clock. Monetary values là decimal string + currency, không dùng float làm ledger tiền.

Ready content dùng canonical JSON, UTF-8, SHA-256. Canonical representation loại lifecycle fields, DB IDs, timestamps và secret values; dùng source/content digests, logical parameter names và stable node IDs. Phân biệt `content_digest` với `run_snapshot_digest` và `artifact_digest`. Archive/promote metadata không thay content digest.

Canonicalization dùng [RFC 8785](https://www.rfc-editor.org/rfc/rfc8785) qua thư viện đã được kiểm tra với vectors, chỉ chấp nhận JSON finite và integer an toàn cho client. Decimal nghiệp vụ dùng string có type/comparator rõ. Không coi `frozen=True` của Pydantic là deep immutability: node collections là tuple, content mapping được freeze/canonicalize; engine không có mutable reference tới revision ready.

## 2. Các models chính

| Model | Fields/ngữ nghĩa bắt buộc |
|---|---|
| `SourceRef` | source_content_digest, anchor type/page/section/paragraph, quote_digest, provenance (`user`, `document`, `inferred`), confirmation record reference |
| `RequirementContent` | logical_key, text, source_refs, acceptance statements, tags |
| `CaseContent` | schema_version, logical_key, title, goal, requirements, source_defs, postcondition_defs, parameter_defs, fixture_refs, preconditions, nodes, completion, required_capabilities |
| `RevisionRecord` | workspace_id, entity_id, revision_id, content_digest, lifecycle, author, promoted_by/at và supersedes; immutable content tách metadata |
| `TargetDescriptor` | intent, interaction role, semantic role/name, region/entity scope, stable attributes, locator alternatives, visual reference metadata; không chứa runtime DOM object |
| `ValueExpr` | discriminated union literal/parameter/capture/secret; type và data-sensitivity classification |
| `AssertionSpec` | id, checkpoint_id, target/scope, comparator, expected expression, required, source_refs, wait policy, evidence requirement |
| `RunSnapshot` | resolved content digests/versions, environment/fixture refs, parameters redacted, credential versions, policy/models, observation, budgets, cache, gate và calibration refs |
| `StepInstance` | node_id, branch/iteration path, dataset row, context/page/frame key, execution_id và attempt_id |
| `Observation` | observation_id/version, session/page/frame, observed_at, mode, semantic/image refs, candidate refs, size accounting, redaction và truncation manifest |
| `ActionProposal` | type, target candidate/descriptor, value expression, rationale summary/source, progress/stop signal; không chứa quyền thực thi |
| `ActionCommand` | command_id, run/attempt, fence_epoch, expected observation_version, action payload, secret grant refs và postcondition refs |
| `ActionReceipt` | command_id, state, observed target, outcome (`succeeded`, `rejected`, `failed`, `unknown`), side-effect classification, evidence refs, timestamps |
| `AssertionResult` | assertion_id/step instance, status (`passed`, `failed`, `error`, `not_evaluated`), expected/observed redacted, evidence status, applicable flag và reason |
| `HealingRecord` | mismatch opportunity ID, healing_attempt_id, actor (`action`, `evidence`), candidates/scores, chosen/refused, checks, actual target, outcome và proposal |
| `ModelCallRecord` | call/group/attempt IDs, purpose, model route/requested/resolved IDs, session, input/output refs, usage, price snapshot, error và times |
| `RunResult` | execution status, verdict nullable khi active, annotations, completion proof, required assertion summary, gate result và typed reasons |
| `RunEvent` | event_id, run_id, run_seq, execution_id/ execution_seq nullable cho root events, schema_version, type, phase, actor, payload type, recorded_at; no secret values |

Money/usage không nằm trong action rationale. Candidate distribution, error taxonomy và evidence status là typed fields, không parse lại từ text.

## 3. Value expressions và identity

`literal` chứa JSON typed value; `parameter` đọc input đã validation; `capture` đọc kết quả node/chứng cứ trước đó; `secret` chỉ chứa logical credential reference. Không eval Python/JS/Jinja, không shell expansion. String interpolation chỉ cho các segments literal/parameter/capture đã khai báo; secret không được nối vào URL, locator, assertion, source hay log.

Password/credential fill chỉ resolve secret ở executor sau khi target được xác minh và grant khớp action/context. Captures có type, scope và taint label; giá trị nhạy cảm không chuyển thành literal persisted. ID/entity dynamics được capture với evidence provenance, không lấy từ kịch bản authoring như hằng.

Target identity gồm scope entity và ý định nghiệp vụ, không chỉ `#id`. Ví dụ hai hàng cùng nút "Xoá": scope phải xác định row bằng entity key từ parameters/capture. Locator alternatives là cách resolve cùng identity, không cho phép đổi entity để đi tiếp.

## 4. DSL node types

| Node | Fields | Semantics |
|---|---|---|
| `action` | id, operation, context, target, value, wait, side_effect, postconditions | Thực hiện một thao tác đã validation, guard trước khi dispatch |
| `checkpoint` | id, assertions | Verify đánh giá expectation đã pin; không sửa nội dung |
| `capture` | id, probe, output name/type | Read-only probe, có evidence và sensitivity propagation |
| `branch` | id, condition, then_nodes, else_nodes | Điều kiện từ probe/capture, không là đoạn mã; path được ghi |
| `loop` | id, condition, max_iterations, body | Bound positive đã pin; mỗi iteration có instance key riêng |

Operations: navigate, click, double_click, fill, type, clear, press, check, uncheck, select, hover, scroll, upload, wait, switch_page, switch_frame, handle_dialog, expect_download. `finish` là policy stop signal, không bypass completion/Verify. Download assertion là checkpoint với artifact probe, không dùng đường dẫn host từ model.

Condition AST gồm and/or/not, typed comparison, exists/unique và boolean capture. Primitive `probe` gồm comparator, target/context khi cần và expected ValueExpr. `source_defs` ánh xạ logical source name tới SourceRef; `postcondition_defs` ánh xạ tên tới Condition AST với phân loại process hoặc business cùng source khi business. Source aliases trong nodes phải resolve từ source_defs. Condition phục vụ branch/loop không tự là business assertion; nếu cần kết luận nghiệp vụ phải có checkpoint. Không có arbitrary code node. Extensions là registry server-side có ID/version, capabilities và quyền, không nhận source code từ import.

## 5. Ví dụ content portable

```yaml
schema_version: case/1
logical_key: login_and_add_item
title: Đăng nhập và thêm việc
goal: Tạo một việc mới và xác nhận nó nằm trong danh sách
requirements:
  - create_item
source_defs:
  create_item:
    source_content_digest: 6cda406844663f46e5d1e5834c364a7f1881f2a235fcaab1445bb1bc697491bc
    anchor: {type: section, value: create-item}
    quote_digest: 392beb4b1202a969c5243e0966023c47dec42f736e95bc2d58950f93767fe2a2
    provenance: user
postcondition_defs:
  authenticated:
    classification: process
    condition:
      kind: probe
      comparator: url_path_equals
      expected: {kind: literal, value: /tasks}
  item_created:
    classification: process
    condition:
      kind: probe
      comparator: count_equals
      target:
        intent: created_item_row
        role: listitem
        entity_scope: {field: text, value: {kind: parameter, name: item_name}}
      expected: {kind: literal, value: 1}
parameter_defs:
  item_name: {type: string, required: true}
fixture_refs: [empty_test_account]
nodes:
  - id: open_login
    kind: action
    operation: navigate
    value: {kind: literal, value: /login}
    side_effect: read
  - id: username
    kind: action
    operation: fill
    target: {intent: login_username, role: textbox, name: Tài khoản}
    value: {kind: secret, credential_ref: demo_login.username}
    side_effect: reversible
  - id: password
    kind: action
    operation: fill
    target: {intent: login_password, locator: {kind: label, value: Mật khẩu}}
    value: {kind: secret, credential_ref: demo_login.password}
    side_effect: reversible
  - id: sign_in
    kind: action
    operation: click
    target: {intent: login_submit, role: button, name: Đăng nhập}
    side_effect: external_write
    postconditions: [authenticated]
  - id: item_name
    kind: action
    operation: fill
    target: {intent: new_item, role: textbox, name: Việc mới}
    value: {kind: parameter, name: item_name}
    side_effect: reversible
  - id: add_item
    kind: action
    operation: click
    target: {intent: create_item, role: button, name: Thêm việc}
    side_effect: external_write
    postconditions: [item_created]
  - id: result
    kind: checkpoint
    assertions:
      - id: item_exists_once
        required: true
        target:
          intent: created_item_row
          role: listitem
          entity_scope: {field: text, value: {kind: parameter, name: item_name}}
        comparator: count_equals
        expected: {kind: literal, value: 1}
        source_refs: [create_item]
completion:
  required_nodes: [add_item, result]
  required_assertions: [item_exists_once]
```

Source text của ví dụ: "Người dùng đã đăng nhập có thể tạo một việc mới; việc đó xuất hiện đúng một lần trong danh sách." Quote: "Việc mới xuất hiện đúng một lần trong danh sách." Hai SHA-256 phía trên tính từ đúng UTF-8 strings này. Đây là content minh hoạ, không phải ca test đã triển khai; environment/fixture `empty_test_account` và credential references phải được cấp trong bundle runtime. Confirmation record khi promote do Platform tạo, không tin record import. `label` cho ô password tránh giả định implicit ARIA role không có. Reference không resolve được là lỗi validation.

## 6. Validation pipeline

1. Safe parse và schema validation: giới hạn kích thước, reject duplicate keys, YAML custom tags/aliases quá mức, extra fields, NaN và unknown nodes.
2. Semantic compile: unique node/assertion IDs, reference/capture/data type, acyclic fixture references, bounded loops, capability requirements, scope và secrets restrictions.
3. Source validation: expectation bắt buộc có nguồn/confirmation, inference chưa xác nhận không promote; source digest/anchor khớp.
4. Environment binding: target origins, auth/fixture references, file references, viewport/route capability và policies đã resolve.
5. Promote transaction: draft edit version khớp If-Match, compile receipt có version, save immutable revision/digest và confirmation/audit.
6. Run snapshot: resolve ready revision/dependencies trong consistent transaction, schema/version compatible, lưu snapshot bytes và digest; chốt signature của verifier/identity/calibration.

Validation trả `field_path`, stable error code và message tiếng Việt; không echo secret values. UI Ajv giúp phản hồi sớm, backend vẫn validation lại tất cả. Import bundle remap DB IDs nhưng giữ portable content/source digests; không import credentials hoặc lifecycle "đã được xác nhận" từ workspace khác như approval thật.

## 7. Ports

| Port | Bên dùng | Methods theo ý nghĩa |
|---|---|---|
| `BrowserReadPort` | Agent, Verify | observe context, probe condition, read download/network metadata, capture safe evidence |
| `BrowserActionPort` | Agent executor | dispatch ActionCommand, query command outcome; không nằm trong Verify dependencies |
| `IdentityPort` | Agent guard, Verify evidence resolver | resolve/rank descriptor, return candidate proofs; không có action method |
| `VerificationPort` | Platform | evaluate checkpoint, finalize verdict, evaluate gate |
| `GenerativeModelPort` | Agent/authoring | generate structured result theo requested schema, multimodal content đã redaction |
| `DecisionModelPort` | Agent | decide typed questions trên redacted state |
| `EventSink` / `CallLedgerPort` | Runtime services | append scoped event hoặc call receipt với fence và idempotency |
| `ArtifactPort` | Capture/Verify/Platform | put safe bytes, get scoped ref, mark integrity/retention; không trả arbitrary path |
| `SecretGrantPort` | Trusted transport/executor | scoped grant cho auth/fill; sensitive value không serializable, repr redacted |
| `FixturePort` | Coordinator | prepare/reset/cleanup và outcome receipts |
| `ClockPort` / `BudgetPort` | Engine/scheduler | UTC/monotonic clocks, reserve/settle/check resources |

Ports không đưa workspace credentials/oracle vào policy interface. Platform cung cấp implementations và mocks qua composition. Serialization của sensitive handle phải fail, không sinh chuỗi có secret.

## 8. Event và error taxonomy

Event types gồm run.state_changed, control.requested/effective, observation.recorded, decision.proposed, model_call.started/completed/unknown, action.prepared/accepted/settled, checkpoint.evaluated, healing.proposed/accepted/refused, artifact.available/unavailable, run.finalized. Payload là discriminated union và có version.

Error classes: input_invalid, capability_unavailable, permission_denied, fixture_failed, locator_missing/ambiguous/identity_mismatch, action_timeout/outcome_unknown, provider_auth/quota/rate_limit/timeout/schema, verification_error, evidence_missing/redaction_failed, storage_unavailable, lease_lost, worker_lost, resource_exhausted. Error không tự là verdict failed; evaluator xác định đủ bằng chứng nghiệp vụ riêng.

Mỗi request/command/event receipt có idempotency identity; raw vendor error/body phải sanitize trước persistence. `message` dành cho người dùng, không chứa key hoặc raw HTML do trang kiểm soát.
