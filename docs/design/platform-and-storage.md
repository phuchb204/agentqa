# Platform, lưu trữ và điều phối

- Ngày: 2026-10-06
- Trạng thái: Thiết kế đề xuất; chưa có database/migrations/process chạy
- Phạm vi: Platform persistence, jobs, browser ownership, artifacts, fixtures và vận hành
- Liên quan: [Kiến trúc](../architecture.md), [engine](execution-and-models.md), [API/security](api-and-security.md)

## 1. Database và transaction

Chọn PostgreSQL 18 cho personal/shared với cùng schema semantics. SQLAlchemy 2 async + psycopg 3, mỗi concurrent task có AsyncSession/transaction riêng; không chia sẻ session giữa heartbeat, call ledger và action execution. Alembic quản lý migration. PostgreSQL row locks và `SKIP LOCKED` phù hợp claim queue nhưng không là đảm bảo exactly-once của website. [SELECT locking](https://www.postgresql.org/docs/18/sql-select.html), [async session](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html).

Metadata quan hệ giữ các khóa/constraints và indexes; JSONB giữ immutable typed content/snapshot đã validation. Blob ảnh/document/download không đặt trong JSONB. Business aggregate services chốt state + event + audit/outbox trong một transaction ngắn; không giữ transaction khi chờ HTTP/model/browser.

## 2. Nhóm bảng

| Nhóm | Bảng chính và constraints |
|---|---|
| Identity | users, sessions, api_tokens; token hashes và revocation/version, không plaintext |
| Workspace | workspaces, memberships, applications, environment_revisions, policy_profiles; owner cuối không bị xoá khỏi workspace |
| Documents | sources, source_revisions, source_segments, extraction_jobs; anchor/digest và privacy classification |
| Authoring | requirements, requirement_revisions, case_drafts, case_revisions, case_source_links, authoring_jobs/proposals; ready content insert-only |
| Suites/data | suites, suite_revisions, dataset_revisions, fixture_revisions; case refs pin revision/digest, graph không cycle |
| Runs | runs, run_snapshots, executions, attempts, run_controls, run_events; unique run/run_seq và execution/execution_seq, immutable snapshots |
| Browser commands | browser_sessions, action_commands, command_receipts; unique session/command_id, fence/control/observation versions |
| Queue/admission | jobs, worker_leases, resource_slots, budget_reservations; unique active ownership và fencing epoch |
| Evidence/usage | assertion_results, healing_records, model_calls, usage_entries, cost_entries, price_snapshots, artifacts; receipt ID unique, amounts decimal |
| Scheduling | schedules, schedule_occurrences, fixture_runs, outbox_deliveries; occurrence key unique, no catch-up storm |
| Research | experiments, experiment_revisions, experiment_executions, evaluation_results, calibration_profiles; manifest digest và scoring version |
| Governance | credential_records, credential_grants, audit_events, retention_jobs, backups; no secret in audit/event payload |

Workspace-scoped tables có `(workspace_id, id)` unique key; references dùng composite FK để chặn reference chéo workspace. Row content của `case_revisions`, suite/requirement/environment revisions, snapshots và events không UPDATE/DELETE bởi runtime role. Drafts dùng edit_version; metadata lifecycle/retention có dịch vụ/quyền và audit riêng. Giữ logical content digest độc lập với DB ID để export/import portable.

Indexes tối thiểu: memberships(user,workspace), executions(workspace,created_at,id) và các filters verdict/status/mode/environment; jobs(state,available_at,priority,id); run_events(run_id,run_seq) và (execution_id,execution_seq); model_calls(execution,phase); artifacts(workspace,run,state); schedule_occurrences(schedule,local_occurrence_key).

Metadata headers `run_events`, `model_calls` và `artifacts` không partition, giữ global primary/idempotency keys; events có unique `(run_id, run_seq)` và `(execution_id, execution_seq)` cho execution events. Heavy payloads dùng `run_event_payloads` và `model_call_payloads` partition theo tháng; header có unique `(id, payload_month)` và child dùng composite FK/key tương ứng để một payload thuộc đúng header/month. Payload retention không xoá headers/provenance. Cách tách này tránh kỳ vọng unique index cross-partition không được PostgreSQL tự cung cấp. [Partition constraints](https://www.postgresql.org/docs/18/ddl-partitioning.html).

## 3. Schema và roles

RLS bảo vệ workspace scope trên business tables; app role không sở hữu tables hoặc có BYPASSRLS, bật FORCE RLS khi phù hợp. Transaction đặt principal/workspace từ authorization đã kiểm tra, dùng SET LOCAL; thiếu context phải deny. Composite FKs là lớp bảo vệ khác, RLS không thay permission check của từng operation. [PostgreSQL RLS](https://www.postgresql.org/docs/18/ddl-rowsecurity.html).

Runtime roles:

- API: business services theo membership, không đọc plaintext secrets hoặc oracle.
- Worker: claim jobs qua procedure hẹp, đọc snapshots của jobs đã cấp, append runtime records dưới fence; không đọc evaluation truth.
- Supervisor: session/command admission và receipts, không sửa case/expectations.
- Scheduler/recovery: jobs/lease/control/finalization qua procedures có audit; không chạy arbitrary user code.
- Evaluator: đọc safe run evidence và viết scoring results; truy cập oracle database riêng.
- Migration/backup: credentials riêng, không dùng cho API/worker.

Oracle được đặt trong logical database riêng `agentqa_oracle`, role/file mounts riêng, không có quyền từ worker. `evaluation_results` ở DB sản phẩm là bản xuất scoring đã cho phép cho người xem; worker không có SELECT trên bảng này. API cho người có quyền nghiên cứu đọc báo cáo, model-facing endpoints không đọc raw oracle.

## 4. Durable queue và ownership

SubmitRun transaction: kiểm tra quyền/revision → resolve/pin snapshot → tạo executions dự kiến và jobs → audit/event → commit. `Idempotency-Key` unique theo workspace+principal+operation; stored request digest khác báo conflict. Không mở browser trước commit này.

Worker claim bằng `FOR UPDATE SKIP LOCKED`, kiểm tra admission/resource slots trong cùng transaction, cấp attempt và fence epoch tăng dần. Candidate query chưa cấp ownership; claim procedure lock root run → execution → job → session → resource keys theo thứ tự cố định, rồi recheck queue/admission và commit ownership. Không giữ job lock trước root run trong một transaction khác làm ngược lock order. Deadlock/serialization retry chỉ retry transaction chưa có external dispatch. Lease heartbeat theo clock DB; default heartbeat 5 giây, lease 30 giây là thông số vận hành có version, không là ngưỡng chất lượng model. Heartbeat chạy độc lập khỏi model call. Không nhận thêm browser action nếu renew không thành công.

Mọi worker write chứa attempt/fence; procedure kiểm tra owner và expiry. Event/result từ stale epoch bị từ chối. Supervisor admission kiểm tra cùng fence và control revision, serialize command trên session. Resource slots (workspace/env/provider/browser) có reservations riêng; không chỉ giới hạn trong bộ nhớ từng worker. Provider scope được xác định theo credential reference/version, không bằng plaintext key.

Job states queued, claimed, running, waiting, settling, succeeded, failed, cancelled, quarantined. Browser run jobs hết lease vào quarantine/reconciliation, không quay lại queued tự động. Các jobs read-only như report hoặc extraction có retry idempotent; email/webhook delivery at-least-once theo key, không gọi đó là exactly-once.

## 5. Journal, event ordering và outbox

Action intent và budget reservation vào DB trước supervisor dispatch. Supervisor admission receipt có command ID, input digest và fence. Nếu dispatch có reply, receipt được persist idempotently; stale worker không append event, supervisor/recovery có quyền settle receipt cũ với reason riêng. Không mint command_id mới để lặp side effect unknown.

Root run có `next_run_seq` tăng dưới row lock, mỗi execution có `next_execution_seq` riêng. Một event execution nhận cả hai sequence trong cùng transaction; root control/state events chỉ có run_seq. Event và state update chốt trong transaction theo lock order root → execution. Suite SSE dùng run_seq nên late commits của hai execution không tạo cursor bỏ sót. Sequence gap do rolled-back transaction không bị gửi như event hợp lệ; SSE cursor dựa records đã commit. Timestamp riêng để đo duration, không dùng nó để sort/deduplicate.

Outbox row được chốt cùng state/event cho callbacks/reports. PostgreSQL NOTIFY chỉ gửi ID/cursor làm wake-up hint; client mất notification đọc lại durable rows. [NOTIFY](https://www.postgresql.org/docs/18/sql-notify.html). Không đưa payload bí mật vào NOTIFY, dùng query quyền scope để lấy events.

## 6. Recovery và controls

| Failure | Xử lý |
|---|---|
| API chết sau submit commit | Client retry cùng idempotency key nhận run cũ |
| Worker mất lease trước command admission | Supervisor từ chối; recovery close/quarantine session, không side effect mới |
| Worker/supervisor chết sau dispatch | Outcome unknown; reconcile receipt/evidence, không replay bước tự động |
| DB mất kết nối | Dừng command admission mới; giữ bounded safe buffers/unknown ledger; không fail-open |
| Blob write lỗi | Ghi artifact unavailable, verdict theo evidence; không biến run thành passed thiếu proof |
| Server restart với run active | Recovery vào finalization/quarantine, không hồi sinh browser từ DB metadata |
| Cancel trong action | Chặn admission mới, đợi/close có bound, ghi effect unknown nếu cần; ack effective riêng |
| Cleanup lỗi | Ghi lỗi và đóng run có bound; không xoá failed assertion đã có |

API pause/cancel tạo control request có revision; supervisor đọc và tạo effective event. Run đang chờ vẫn renew hoặc kết thúc theo wait policy. Manual intervention có grant/session scope và audit; observation/capture sau resume không được coi cùng clean attempt nghiên cứu.

Recovery tạo attempt mới chỉ khi plan cho phép, fixture mới/reset receipt phù hợp và effects của attempt cũ đã được reconcile hoặc đánh dấu không thể tiếp tục. Explicit rerun là run mới, không ghi đè attempt cũ. Operator không được xoá unknown để lấy kết quả đẹp.

## 7. Fixture và schedules

Fixture registry có ID/version và declared capabilities: prepare, reset, cleanup, outcome probe. Các handlers do platform cài đặt trước; ca/import không chứa shell/script để thực thi. Setup chứa dataset namespaced execution/attempt, auth grants và app state expectations. Browser context isolation không cô lập backend data; fixture chọn database namespace/account/entity keys để đảm bảo điều đó.

`FixtureReceipt` giữ inputs redacted, created resource IDs, setup validation và cleanup status. Cleanup queue độc lập có lease/retry policy; không làm finalization chờ vô hạn. Global fixtures có lock và lifetime rõ; suite case mặc định không phụ thuộc dữ liệu của ca khác.

Schedule dùng IANA timezone và occurrence key `(schedule_revision, local_wall_time, fold-policy)`. Gap DST → skipped receipt, fold → một occurrence, overlap default skip, optional queue đã pin. Leaderless nhiều scheduler dùng unique occurrence và claim locks; downtime không catch-up mặc định. Fail-fast tạo skipped executions có reason trước khi gate tổng hợp.

## 8. Artifact store

Interface `put_safe/get_authorized/mark_expired/check_integrity`. Default filesystem private: generated object key theo workspace/run/artifact ID, no user path, atomic write-rename và digest; reject symlink/path traversal. Multiple process cùng host dùng shared volume. Storage mount/credential chỉ Platform trusted services, browser sandbox không browse workspace files.

Artifacts có state staged, available, unavailable, expired, deleted; put staged metadata trước upload, publish available sau checksum. DB/blob không có distributed transaction, nên reconciliation quét staged/orphans. Không xóa bytes đang được finalize trước expiry; retention service tạo tombstone và giữ provenance/summary theo policy.

Ảnh/DOM/network safe buffers được sanitize trước put; raw secrets không vào staged blobs. Original uploaded document có privacy class và scanner/quarantine; credential-looking content không được đưa vào model/exports, chỉ source đã safe. Native trace không mặc định enabled ở environment có credentials; SafeTraceBundle đủ cho viewer.

Shared multi-host chọn cùng artifact gateway backed shared volume hoặc S3-compatible backend; ACL và IDs giữ nguyên. URL tải về chỉ API authorized hoặc signed grant ngắn hạn bị giới hạn scope; metadata public không chứa physical path. Content-addressed dedup chỉ trong workspace/privacy scope, không leak existence giữa workspaces.

## 9. Call/cost ledger

Model call tạo started record trước request, mọi attempt có settlement succeeded/error/unknown. Typed usage fields gồm observed/estimated/null và semantics version. Total/cached input không cộng lần hai. Monetary cost dùng Decimal string, basis provider_report/price_estimate/subscription_allocation, currency, snapshot ref và coverage.

Provider cost, quota value và allocated subscription cost là ba measures độc lập. Ledger tổng hợp từng measure/basis/currency, không gộp sum tạo số vô nghĩa. Missing một settled call cost → aggregate partial/unknown, không zero. Authoring/evaluation/diagnostic outside active execution giữ liên kết vào analysis, không thay engine total/duration sau terminal.

## 10. Migrations, backup và retention

Migration runner lock schema version, kiểm tra schema compatibility trước API/worker start; app không tự migrate lúc request. Expand/backfill/contract có checkpoints và compatibility matrix; không để hai schema incompatible append events cùng run. Events/JSON snapshots giữ original schema version; reader upcaster tạo view không ghi đè gốc.

Backup dùng database consistent snapshot và artifact manifest tại cutoff, sau đó kiểm tra digest/references; giữ blob có pending DB reference qua cửa sổ backup. Keyring/password/provider credentials không nằm trong workspace export; disaster backup encrypted key material qua kênh/quyền riêng. Restore vào môi trường tách biệt, verify objects/counters/digests, revoke old sessions/tokens theo policy và quarantine run active.

Retention khai báo theo artifact class và workspace; metadata verdict/provenance còn đủ để giải thích artifact expired. Dataset chứa PII có retention khác synthetic benchmark. Benchmark/manifests/evaluation receipts dùng immutable export pin, không phụ thuộc artifact đã hết hạn để giả định chấm được.

## 11. Vận hành

Health/readiness tách DB/schema, queue, workers/supervisor, storage và provider conformance. Readiness không gọi model thật liên tục. OpenTelemetry/structured metrics theo request/run/attempt/call; không đặt secret/model input làm metric labels.

Graceful shutdown: API ngừng submit mới theo readiness; workers drain và giữ lease đến close session; scheduler ngừng claim; supervisor settle/close có bound. Browser target, model gateway, database và credential broker là network scopes riêng, không cho browser truy control DB/API.

Kiểm thử fault dùng clocks/process fixtures: lease loss, queue races, cancelled admission, crash-after-side-effect, staged blobs và DB outage. Các khẳng định reliability phải được chứng minh bằng tests này; không suy ra từ việc đã dùng PostgreSQL.
