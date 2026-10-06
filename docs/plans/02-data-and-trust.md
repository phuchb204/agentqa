# Gói 02 — Dữ liệu, quyền và nhật ký

- Ngày: 2026-10-06
- Trạng thái: Chưa triển khai
- Plan: [rebuild-plan](rebuild-plan.md)
- Nguồn: [Platform/storage](../design/platform-and-storage.md), [API/security](../design/api-and-security.md)
- Gate: G1

## P04 — Schema, migrations và workspace isolation

**Depends on:** P01, P02.

**Files:** `src/agentqa/platform/storage/{database.py,tables.py,repositories.py,scope.py}`, `infra/migrations/`, `infra/compose.test.yml`, `tests/database/test_{migrations,rls,composite_references,role_grants,payload_partitioning}.py`.

1. Tạo PostgreSQL 18 test profile private/isolated; SQLAlchemy async + psycopg, migrations lock/version và async transaction-per-task. Không dùng SQLite thay RLS/lock semantics.
2. Migrate các nhóm metadata nền, revisions/runs/jobs/ledger/artifacts/roles theo design; heavy payload partitions có FK header+month, headers có global uniqueness. Tables của subsystem về sau bổ sung migration trước task dùng, không có app tự migrate khi request.
3. API/worker/supervisor/evaluator/migration roles riêng, composite workspace FKs và deny khi thiếu SET LOCAL principal/workspace. Chuẩn bị oracle DB `agentqa_oracle` không cấp worker/API quyền; không seed truth vào business DB.
4. Test empty→latest, supported upgrade/rollback restore, pooled-connection scope reset, cross-workspace refs, payload duplicate và worker không dùng bypass role.

**Verify:** Start `infra/compose.test.yml` theo master; `uv run --locked pytest -q tests/database`. Harness tạo/migrate test DB bằng role riêng; không sửa DB người dùng hoặc cấu hình production.

**Done:** DB constraints/roles được kiểm trên PostgreSQL thật, lease/journal future tables có keys hợp lệ. Không tuyên bố RLS đủ thay application authorization.

## P05 — Identity, sessions và secret grants

**Depends on:** P02, P04.

**Files:** `src/agentqa/platform/identity/`, `src/agentqa/platform/security/{credentials.py,grants.py,redaction.py,taint.py,origin.py}`, auth/membership API routers, `tests/security/test_{sessions,roles,csrf,bootstrap,credential_envelope,grant_scope,revocation,canaries}.py`.

1. Opaque sessions, Argon2id/pwdlib, PAT hashes/scopes/revoke và roles Owner/Editor/Runner/Viewer. Local bootstrap one-time/loopback/Origin, shared luôn auth/TLS profile; membership change invalidates grants/caches.
2. Local credentials bằng env references; shared AES-GCM envelope/data key/nonce uniqueness và AAD, master key ngoài DB. Pin credential version, never GET plaintext; rotation/revoke tạo audit không có value.
3. Scoped secret broker cho provider auth header hoặc verified fill target; serialize/log/exception paths fail safe. Test Canary sử dụng synthetic values, không đọc keys thật; redaction/taint là service dùng lại trước mọi sink.
4. API authorization và RLS integration; CSRF/Origin/WebSocket bootstrap controls, safe errors, owner-last membership invariant.

**Verify:** `uv run --locked pytest -q tests/security tests/database/test_role_grants.py`; schema generation/check và import gates.

**Done:** Sai workspace/role/grant/destination bị chặn; key chỉ resolve trong trusted transport/executor, không xuất trong model/persist/export. Crypto fixtures gồm nonce collision, wrong AAD, rotation và deleted-record registry.

## P06 — Revisions, snapshots, events, ledger và artifacts

**Depends on:** P02, P04, P05.

**Files:** `src/agentqa/platform/{revisions,runs,events,usage,artifacts}/`, case/environment/suite draft/promotion/query routers, migrations tương ứng, `tests/platform/test_{revisions,snapshots,event_order,ledger,artifact_lifecycle,idempotency}.py`.

1. Draft edit_version/If-Match và promote receipt; ready content insert-only, lifecycle metadata riêng. Requirement/environment/suite/data revisions portable, import không nhận confirmation/credentials của workspace khác làm quyền thật.
2. Submit services snapshot transaction, executions dự kiến, request-digest/idempotency keys và immutable run configuration. Resource/capability validation giữ blocked/error facts, không trả pass ở submit.
3. Run_seq và execution_seq cùng state/event transaction, root→child lock order; durable event query và outbox rows, NOTIFY chỉ wake-up. Tests delayed commits/multi-execution ordering và rollbacks.
4. Call/usage/cost ledgers typed/null/basis, started/settled/unknown records; artifact staged→available/unavailable/tombstone, safe store/digests/reconciliation. Blob/DB failure không mất proof hoặc biến unknown thành zero.

**Verify:** `uv run --locked pytest -q tests/platform tests/database`; targeted race tests với independent concurrent sessions và fault store.

**Done:** Revision/digest/snapshot bất biến, request retries không tạo thêm execution, sequence không bỏ late commit và artifact/usage gaps đọc được. Evidence còn trong safe form ngay từ sink, không dựa vào export scrub.
