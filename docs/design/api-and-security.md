# API, quyền truy cập và bảo mật

- Ngày: 2026-10-06
- Trạng thái: Thiết kế đề xuất; chưa có endpoints triển khai
- Phạm vi: Platform API/CLI/CI, auth, credentials và network boundaries
- Liên quan: [Contracts](contracts-and-dsl.md), [Platform](platform-and-storage.md), [web](web-experience.md)

## 1. API conventions

REST JSON tại `/api/v1`; FastAPI sinh OpenAPI 3.1 từ Contracts/request models. Schema DSL/events xuất riêng tại `/api/v1/schemas/{schema_name}/{version}`; release exports pin digest. Web types sinh từ OpenAPI, không viết client payload không version.

Workspace resources có prefix `/workspaces/{workspace_id}`. Paths dưới đây tương đối với `/api/v1`. UUID object IDs không là quyền. List endpoints dùng opaque cursor từ sort tuple và scope/filter digest, không offset cho events/run timeline; invalid cursor trả validation error.

Response error có code, message tiếng Việt, field_errors[{path,code,message}], request_id và retryable; không có raw stack trace/HTML/provider body. HTTP 401 unauthenticated; 403 thiếu quyền trong workspace đã có quyền nhìn; 404 resource ngoài scope; 409 state/idempotency conflict; 412 stale If-Match; 422 semantic validation; 429 admission/rate; 503 unavailable capability/storage.

GET drafts trả ETag/edit version. PATCH draft dùng If-Match, nếu thiếu trả 428; update field qua whitelist, không mass-assign owner/lifecycle. Ready content không có PATCH; promote tạo immutable revision trong transaction, có confirmation payload và source validation receipt.

## 2. Endpoint families

| Family | Endpoints chính | Semantics |
|---|---|---|
| Auth | POST `/auth/login`, `/auth/logout`, `/auth/local-bootstrap`; GET `/auth/session`; POST `/auth/tokens` | HttpOnly session hoặc scoped token; bootstrap one-time local-only |
| Workspaces | GET/POST `/workspaces`; GET/PATCH `/workspaces/{w}`; `/memberships` | Membership/owner invariant, audit; không tự gửi invitation email |
| Applications | `/workspaces/{w}/applications`; `/applications/{id}/environments/revisions` | Environment URL/network/auth/fixture profiles versioned |
| Sources | `/workspaces/{w}/sources`; `/sources/{id}/revisions`; POST `/sources/{id}/extract` | Upload vào quarantine, job extraction, safe source segments |
| Requirements | `/workspaces/{w}/requirements`; `/requirements/{id}/revisions`; `/requirements/{id}/impact` | Requirement version/source và affected cases |
| Authoring | POST `/workspaces/{w}/authoring-jobs`; `/exploration-jobs`; GET `/jobs/{id}` | Background jobs pin input/cost; proposals không tự promote |
| Cases | `/workspaces/{w}/cases`; `/cases/{id}/draft`; `/draft/validate`; `/draft/promote`; `/revisions`; `/revisions/{rid}/archive` | Revision lifecycle, conflict và validation fields |
| Import/export | POST `/workspaces/{w}/imports`; POST `/workspaces/{w}/exports` | Format versioned, safe parse; asynchronous nếu cần, không import credentials |
| Suites/data | `/workspaces/{w}/suites`; `/datasets`; `/fixtures`; revision subresources | Suite pin refs/data, fixture registry references |
| Runs | POST `/workspaces/{w}/runs`; GET `/runs/{id}`; `/executions`; `/attempts`; `/events`; POST `/runs/{id}/controls` | Idempotent submit, immutable snapshot, durable controls/events |
| Evidence | GET `/workspaces/{w}/artifacts/{id}`; POST `/artifacts/{id}/download-grants`; `/runs/{id}/comparison` | ACL/redaction/integrity; grant không là permanent URL |
| Reports | POST `/workspaces/{w}/runs/{id}/reports`; `/issue-packages`; GET `/reports/{id}` | JSON/HTML/CSV/JSONL/JUnit, proposal diagnosis riêng |
| Experiments | `/workspaces/{w}/experiments`; `/revisions`; `/validate`; `/execute`; `/results`; `/calibrations` | Manifest/schema, split, matrix, safe scoring output |
| Schedules | `/workspaces/{w}/schedules`; `/revisions`; `/occurrences`; `/enable`, `/disable` | Timezone/overlap, future revision, unique occurrence |
| Settings | `/workspaces/{w}/credential-references`; `/provider-profiles`; `/retention`; `/workers`; `/usage` | Hai routes cố định, secret set/rotate không read plaintext |
| Health | `/health/live`, `/health/ready` | Public response tối thiểu; diagnostics chi tiết yêu cầu operator role |

Actor chỉ thao tác child objects sau scope authorization, dù child path không lặp parent ID. Bộ router dùng chung services, không đặt verdict/engine logic ở endpoint handlers.

## 3. Submit và controls

SubmitRun body: case/suite revision refs, dataset refs, environment revision, execution_mode, policy, observation, calibration, budget/cache/gate profiles và intent authoring/regression/experiment. Các config đã có trong profile được resolve và snapshot; conflict giữa override và protected manifest bị từ chối.

`Idempotency-Key` bắt buộc trên submit và controls có side effects. Key reuse với same body trả original record; khác body trả 409. API trả 202 với run_id, snapshot_digest, event URL và queued state. Không trả passed khi chưa chạy. Inputs có secrets values hoặc oracle metadata bị validation từ chối.

Controls body gồm pause/resume/cancel, reason và expected_control_revision. Requested và effective là events riêng. 202 nhận request không hứa action đã dừng. Effective acknowledgement xuất từ supervisor; UI/CLI chờ khi cần semantics cancel. Resume kiểm tra quyền, browser state và data changes, không sửa snapshot.

## 4. SSE và live browser

`GET /workspaces/{w}/runs/{r}/events?after={run_seq}` dùng SSE id theo run_seq, Last-Event-ID hỗ trợ reconnect. Run/suite stream có envelope run_seq và execution_id/execution_seq khi applicable; run_seq cấp dưới root run lock cùng transaction append nên không bỏ late commit của execution khác. Execution filter vẫn dùng run_seq làm cursor, không gộp các execution_seq riêng thành một sequence. Dedupe theo event_id; duplicate transport không tạo event duplicate.

Server cấp initial snapshot với stream cursor trong cùng consistent read, rồi stream records sau cursor. UI merge snapshot và delta, không thay counters bằng optimistic event count. Cursor quá retention trả typed `cursor_expired`, snapshot/cursor mới và missing range; không giả lập đủ events. NOTIFY chỉ wake-up, periodic durable query bù notification bị mất.

Live browser route `/runs/{r}/browser-stream` là WebSocket, auth cookie hoặc one-time stream grant scoped run và role. Frames có session/page/frame/observation IDs, seq, viewport/DPR và masked PNG/WebP bytes; bounded latest-frame delivery bỏ frame cũ có metadata, không ghi mọi frame làm evidence. Các evidence frames tại step/checkpoint được lưu riêng.

Không expose CDP/VNC/Playwright websocket hoặc embed trang mục tiêu như iframe trong app origin. Manual input chỉ khi waiting_for_input, Runner trở lên và grant hiện hành; qua supervisor typed input commands, không shell/DOM scripts. Secret-tainted keystrokes không vào logs; manual intervention đánh dấu attempt contaminated cho research.

## 5. Auth và membership

Chọn opaque server-side sessions thay JWT cho UI để revoke tức thì. Cookie HttpOnly, SameSite=Strict, Secure khi TLS; local loopback HTTP có policy riêng và không cho bind shared với cookie không secure. Sessions/token hashes ở DB, rotate khi login/quyền đổi, logout revoke. Password Argon2id qua thư viện maintained, không tự viết crypto.

Personal mode có owner local, first-party UI exchange one-time bootstrap nonce từ private launcher channel để lấy session cookie. Nonce không đặt trong query, persistent logs hoặc provider prompt; nếu dùng URL fragment để launcher handoff, UI xoá fragment ngay và POST exchange cùng-origin. Chỉ loopback, TTL ngắn, consume once; shared mode cấm bootstrap flow này. Không cho website bên ngoài tự lấy owner session bằng request localhost.

Shared owner bootstrap qua admin CLI input có kiểm soát; tạo thành viên/password reset bởi owner, không tự gửi email. Roles đúng spec Owner/Editor/Runner/Viewer, thêm permission flag artifact_export/research_truth_access khi workspace yêu cầu. Runtime service identities có scopes riêng, không dùng user owner token.

CLI/CI dùng PAT có principal, workspace scopes, permission set, expiry và revocation, secret value chỉ phát một lần. Tokens không lưu trong project files; có environment hoặc OS credential store. Native browser EventSource dùng cookie, CLI SSE dùng Authorization header; không đặt PAT trong event URL.

API authorizes mỗi operation với membership và resource; database RLS/composite FKs bổ sung. Membership change invalidates cached permissions/grants. Lệnh browser đã accepted trước revoke có thể in-flight; không hứa hoàn tác external effect, nhưng revoke chặn admission mới và stream access.

## 6. Secret broker

Provider ban đầu từ hai env vars đã được chọn; local owner bind thành credential references không chứa value. Shared credential records encrypted bằng AES-GCM envelope qua thư viện cryptography: mỗi record version có data key 256-bit mới và nonce 96-bit, AAD(workspace,credential_id,version); data key được wrap bởi master key ngoài DB qua OS/secret mount. Wrap nonce có uniqueness registry theo master key version, không reuse nonce sau khi xoá credential. Master-key rotation rewrap với nonce mới; credential-value rotation tạo record version/data key mới. Run snapshot ghi version, không ghi secret digest/value. [AEAD API](https://cryptography.io/en/latest/hazmat/primitives/aead/).

`SecretGrant` scope gồm principal/service, workspace, run/attempt, purpose, destination hoặc target identity, expiry và credential_version. Model grant chỉ cho đúng Go/Zen origin và header; browser fill grant chỉ cho đúng verified target/context. Secret values resolve ở transport/executor memory, SensitiveValue không serializable, repr redacted, không dùng làm metrics label hoặc exception detail.

Owner set/rotate/delete reference có audit, không có API đọc plaintext. Existing run dùng pinned version đến hết grant hoặc bị revoke, không đổi key silently. Revocation có reason; failed account access không tự dùng credential khác. `.env`/encrypted auth state không xuất trong workspace bundle.

## 7. Network và host isolation

Browser sandbox qua egress gate/proxy enforce destination theo pinned environment: scheme, domain/port, resolved IP, redirects, HTTP(S), WebSocket và download routes. API/model transports có allowlist riêng; model traffic không đi qua quyền browser target. Block file://, host mounts, metadata services và undeclared private destinations; localhost/private targets chỉ được owner khai báo rõ cho test environment.

DNS được resolve/kiểm tra và kết nối qua proxy theo vetted address; không chỉ kiểm tra URL string rồi để browser tự resolve lần khác. Service worker/network channels không được bypass proxy. Linux dùng container network namespace; Windows dùng browser process với explicit proxy/OS outbound enforcement, startup fail nếu không đảm bảo profile yêu cầu. JavaScript request interception của Playwright một mình không được coi là network sandbox.

Target browser không mount source repo, `.env`, DB keyring, oracle files hoặc control API credentials. Browser service chạy user riêng, scratch sandbox giới hạn, capability media/clipboard/host downloads không cấp tự do. Action/model output không có host command hoặc filesystem path quyền cao.

Thiết kế allowlist/DNS/redirect theo [OWASP SSRF](https://cheatsheetseries.owasp.org/cheatsheets/Server_Side_Request_Forgery_Prevention_Cheat_Sheet.html); lựa chọn proxy/process profiles là quyết định AgentQA cần leak/bypass tests riêng.

## 8. Input, redaction và browser app security

Uploads kiểm MIME/size/decompression ratio, scanner/quarantine, parser subprocess không network, reject macros/active content. pypdf không tự OCR; source scan chưa trích được báo unextractable. DOCX anchors là heading/paragraph/table cell, không bịa số trang khi chưa có layout; PDF dùng page anchors. Original sensitive files private/encrypted, model dùng safe segments.

UI render tài liệu/model errors dưới dạng text/sanitized Markdown, không raw HTML từ website; CSP self và no executable target content. Mutation/case import safe parse và no arbitrary code. Cookies/session, Authorization, sensitive form fields, URL query và captures được taint/redaction trước persistence/live/provider input. All export/report/callback dùng cùng safe view.

Origin/CSRF checks áp cả personal loopback. CORS allowlist cụ thể, không wildcard credentials; WebSocket handshake và local bootstrap cũng check Origin. Shared TLS proxies có trusted proxy list, không tin X-Forwarded-* do client tuỳ ý. Session design theo [OWASP session management](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html).

## 9. CLI và CI integration

CLI là client HTTP: case/suite import, run submit/wait/cancel, inspect/export, experiments và configuration validation. Managed local server startup là lệnh riêng, vẫn đi cùng API services; không chạy một checker/loop khác. Subprocess process names không là quyền.

JSON/JUnit theo Contract versions và gate rules trong [Verify](verification-and-healing.md). CLI exit precedence giữ spec. Ctrl+C của attached owned run gửi cancel và chờ effective/terminal theo policy; detached hoặc observing shared run chỉ ngắt client mặc định. Structured stdout cho automation, human messages/stderr không lộ secrets.

CI templates đọc token từ CI secrets, submit pinned revisions/gate/environment và upload safe reports bằng cấu hình người dùng. Webhook owner config destination allowlist/signing secret, outbox delivery ID, HMAC timestamp/body, bounded retries và at-least-once semantics. Issue package tải về; không tự gửi email, comment hoặc issue tới dịch vụ ngoài.

## 10. Kiểm tra bắt buộc

Contract compatibility, invalid If-Match/idempotency conflicts, cross-workspace object/event/artifact IDs, Origin/CSRF, token revoke, stale stream grants, safe error payload, DNS rebinding/redirect/private IP/file paths, upload bombs và secret canaries. Tests dùng fake model transport; never send canary secrets tới API model thật.
