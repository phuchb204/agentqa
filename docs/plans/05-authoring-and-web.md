# Gói 05 — Authoring và trải nghiệm web

- Ngày: 2026-10-06
- Trạng thái: Chưa triển khai
- Plan: [rebuild-plan](rebuild-plan.md)
- Nguồn: [API/security](../design/api-and-security.md), [Web](../design/web-experience.md), [Contracts](../design/contracts-and-dsl.md)
- Gate: G4

## P16 — Documents, requirements và impact

**Depends on:** P03, P05, P06.

**Files:** `src/agentqa/platform/{sources,requirements,extraction}/`, source/requirement API routers, `tests/platform/test_{extraction,source_anchors,requirement_impact,upload_quarantine}.py`, safe PDF/DOCX fixtures.

1. Upload/quarantine/safe file validation và extraction jobs; pypdf/python-docx trong subprocess giới hạn, no network/macros/external entities. Scan không đọc được → unextractable, không OCR/điền nội dung giả.
2. Source revisions/segments/digests và anchors PDF page, DOCX heading/paragraph/table-cell; privacy/taint redaction trước model input, original sensitive source không publish như artifact thường.
3. Requirement revisions/acceptance/source links và impact graph; update requirement đánh dấu linked cases cần xem, không sửa ready case/expectation cũ.
4. Test text Unicode, tables, duplicate source identity, encrypted/invalid files, decompression bombs, missing quote/digest và credentials trong nguồn upload.

**Verify:** `uv run --locked pytest -q tests/platform/test_extraction.py tests/platform/test_source_anchors.py tests/platform/test_requirement_impact.py tests/platform/test_upload_quarantine.py`; model network guard và artifact canaries.

**Done:** Nguồn truy được/đọc an toàn, không bịa DOCX page numbers hoặc business rules. Các SourceRefs dùng được trong promotion/compiler đã có.

## P17 — Proposals, exploration và bộ ca portable

**Depends on:** P11, P14, P16.

**Files:** `src/agentqa/platform/{authoring,exploration,bundles,suites,datasets}/`, authoring/exploration/import/export API routers, `tests/platform/test_{authoring,exploration,bundles,suite_revisions,data_rows}.py`, `tests/integration/test_author_to_replay.py`.

1. Background authoring input URL+goal/expectations hoặc sources, pinned model/call ledger; typed proposals liên kết requirement, positive/negative/boundary cases và explicit inferred provenance.
2. Patch proposals vào draft qua edit_version/diff; promotion vẫn cần source confirmation thật và complete required assertions. Draft run có provisional, successful trace không tự trở thành ready.
3. Exploration qua sandbox/action policy, default read-only, write chỉ khi pinned environment cho phép; record pages/actions/coverage gaps và đề xuất ca, không gọi đó là full website coverage.
4. Portable YAML/JSON bundles safe parse/digest, remap DB IDs, secrets/approvals không import thành quyền; suite/data revision rows/fixtures. Unsupported runtime capability báo rõ khi bind/run.
5. End-to-end source/goal→FakeGo proposal→Editor confirmation API→ready→strict replay thật→Verify/result, thêm wrong inferred expectation và malicious page instructions.

**Verify:** `uv run --locked pytest -q tests/platform/test_authoring.py tests/platform/test_exploration.py tests/platform/test_bundles.py tests/platform/test_suite_revisions.py tests/platform/test_data_rows.py tests/integration/test_author_to_replay.py`.

**Done:** Ca có nghĩa/nguồn và có thể sửa/lưu/chạy lại; engine không nhận arbitrary code hoặc artifact host path từ proposals. Coverage có định nghĩa và gaps, không pass-rate marketing.

## P18 — Workspace web và case editor

**Depends on:** P03, P05, P06, P16, P17.

**Files:** `apps/web/src/{app,routes,api,components,tokens}/`, `apps/web/src/features/{workspace,requirements,cases,suites}/`, reducers/YAML editor/schema workers, corresponding Vitest tests, `tests/ui/test_authoring_flow.py`, `tools/run_ui_e2e.py` với scenario authoring ban đầu.

1. Shell/route selectors/navigation và role-aware login/local bootstrap dùng API typed client; tokens/Radix focus, light/dark/contrast, all states loading/empty/error được thiết kế thực.
2. Requirement sources/impact/coverage và suite/data/fixture editor lấy server records; no raw target HTML, credential/token trong URL/browser storage.
3. Case editor Structured/YAML (Monaco/Ajv), local history/undo/redo, source/proposal diffs; invalid YAML giữ buffer, autosave validated If-Match, conflict merge không overwrite.
4. Ready read-only/new draft, promote review/assertion/source confirmation, draft-run provisional và permission handling; secret references hiển thị trạng thái thay vì value.
5. UI E2E chạy với API/DB/browser thật và fake models, từ yêu cầu đến ready/replay; keyboard/focus và stale edit conflicts.

**Verify:** Web lint/format/typecheck/test/build; `uv run --locked python tools/run_ui_e2e.py --models fake --scenario authoring` từ harness tạo ở task này, mở rộng ở P19. Không chỉ test components mock happy path.

**Done:** Trải nghiệm authoring có server-backed revision/provenance; UI không tự tính business verdict hoặc optimistic promote trước receipt. Hành vi và strings tiếng Việt.

## P19 — Live/detail/compare và evidence navigation

**Depends on:** P11, P13, P18.

**Files:** `apps/web/src/features/{runs,live,compare,evidence}/`, durable stream client/reducers, backend browser-stream/query/compare routers, `tools/run_ui_e2e.py`, `tests/ui/test_{live_run,run_detail,compare,reconnect,keyboard}.py`, stream/API tests.

1. Snapshot+SSE run_seq client và authorized masked WS frames; cursor expired, reconnect/dedupe, selected historical step không bị auto-scroll về latest.
2. Trạng thái requested/effective controls, business verdict chưa final, annotations/healing/usage và safe decision summaries; no chain-of-thought animation/target iframe/CDP exposure.
3. Detail từ assertion/source/checkpoint tới đúng evidence, missing/redacted/expired states; query/filter/cursor/counts theo workspace quyền.
4. Compare case/config/policy/model/calibration/cache trước metrics, align node/iteration path không step index; actual expected/observed và unknown money khác zero.
5. Harness UI E2E quản local services/profile, no inherited provider creds, stop processes nó sở hữu và retain failed safe artifacts. Faults UI disconnect/tab close/stale token không dừng engine hay bypass ACL.

**Verify:** `uv run --locked python tools/run_ui_e2e.py --models fake`; API streams/security fixtures và web reducer/schema tests.

**Done:** Theo dõi/read/compare dựa cùng authoritative data, không synthetic success panels. UI mất kết nối không mất events hoặc canary secrets.
