# AgentQA — kế hoạch triển khai

- Ngày: 2026-10-06
- Phiên bản: 1.0
- Trạng thái: Plan đã viết để thực thi; các task chưa triển khai
- Cơ sở: [Spec](../specs/product-spec.md), [thiết kế hệ thống](../architecture.md), [truy vết thiết kế](../design/acceptance-mapping.md)
- Phạm vi: Toàn bộ 51 FR, 12 NFR, 24 AC; cả ba RQ và hai route model đã chọn
- Phương thức đề xuất: AI coding agent thực hiện trên workspace hiện tại theo dependencies và các gate của plan

## 1. Quy tắc thực thi

Plan này không thu hẹp sản phẩm; các mốc là thứ tự xây và xác minh những luồng hoàn chỉnh. Không có task đã được đánh dấu done vì mới viết tài liệu. Những đường dẫn code/tests/commands phía dưới là đầu ra cần tạo, không phải file hoặc lệnh đã tồn tại trong repo.

Giữ Contracts, Models, Agent, Verify, Platform và luật import của thiết kế. Chỉ có Go `deepseek-v4.1-flash` và Zen `jev-1.13-free`; không đổi provider/model hoặc route trả phí để vượt một gate lỗi. UI/CLI/API dùng cùng services/reducers, không xây ba engine khác nhau.

Thực hiện từng task: đọc nguồn và dependency receipts → viết fixtures/kiểm tra cho behavior cần chứng minh → triển khai component → chạy kiểm tra liên quan → cập nhật docs và evidence → chuyển task tiếp. Không cần hỏi lại các lựa chọn thông thường. Không tạo mock feature để UI báo đã hoạt động, không nới assertion/test/CI để làm gate xanh.

Test unit/integration/API/UI/fault luôn fake model transport, kể cả browser thật. Test configuration không đọc provider keys thật từ `.env`, không gửi request tới Go/Zen. Live conformance, calibration và research thật là những commands riêng, có opt-in, budgets, receipts và cost/missingness; không chạy từ pytest hoặc CI thường.

Code dùng tên tiếng Anh, UI/prompt/docs tiếng Việt; không comment/docstring giải thích trong code. Generated types/schema tooling cũng phải tuân thủ bằng generator/AST printer phù hợp; tài liệu kỹ thuật nằm ở docs. Không đưa API key, token, auth state hoặc oracle vào code/test/trace.

Bộ tài liệu nền được commit trước khi thực thi code. Khi cần commit, tạo nhánh `feat|fix|chore|docs/<slug>`, dùng Conventional Commits và chạy gates đã cấu hình. Không tự gắn remote, force-push lịch sử mới lên repo cũ, push main hoặc merge. PR chỉ tạo khi có remote được cấu hình/ủy quyền.

## 2. Các gói công việc

| Gói | Tasks | Đầu ra chính | Tài liệu |
|---|---|---|---|
| Nền dự án | P01–P03 | Runtime/lockfiles/CI, Contracts/DSL, schema và typed client | [01-foundation](01-foundation.md) |
| Dữ liệu và quyền | P04–P06 | PostgreSQL/RLS, auth/secrets, revisions/events/ledger/artifacts | [02-data-and-trust](02-data-and-trust.md) |
| Lượt chạy browser đầu tiên | P07–P11 | Fixture app, sandbox, supervisor, Verify và strict replay qua API | [03-first-browser-run](03-first-browser-run.md) |
| Model và quan sát | P12–P15 | Hai adapters/fakes, semantic/hybrid/vision, agent/cascade, conformance | [04-models-and-observation](04-models-and-observation.md) |
| Authoring và web | P16–P19 | Sources/requirements, proposals/exploration, editor, live/detail/compare | [05-authoring-and-web](05-authoring-and-web.md) |
| Phục hồi và engine đầy đủ | P20–P22 | Healing, actions/evaluators nâng cao, cache/cost/diagnostics/reports | [06-healing-and-complete-engine](06-healing-and-complete-engine.md) |
| Platform và vận hành | P23–P26 | Suite/scheduler, shared controls, CLI/CI, deploy/backup/retention | [07-platform-and-operations](07-platform-and-operations.md) |
| Ba RQ | P27–P30 | Corpus/oracle, variants/scoring, calibration/statistics, experiment UI/export | [08-research](08-research.md) |
| Nghiệm thu sản phẩm | P31–P32 | Fault/security/OS/workload checks và demo/release tái lập | [09-release](09-release.md) |

## 3. Dependencies có thể kiểm tra

Dependencies là các đầu ra component phải có interface/schema và receipts kiểm tra offline hợp lệ trước khi task downstream nối vào chúng. Trạng thái task: planned, in_progress, code_ready, blocked, done. Code_ready cho phép xây downstream với injected fakes; nó không thay evidence live hoặc chứng nhận production. P15/P29 chưa có receipts thật thì các live/calibration/evaluation steps phụ thuộc vẫn bị chặn, dù module/UI liên quan có thể được xây và kiểm tra offline. Không biến blocked/code_ready thành done để vượt gate.

| Task | Depends on | Mục đích |
|---|---|---|
| P01 | — | Runtime/scaffold và tooling mới |
| P02 | P01 | Contracts/Case DSL/validation thuần |
| P03 | P02 | OpenAPI/schema/client types và generation checks |
| P04 | P01, P02 | Database schema, migrations và RLS |
| P05 | P02, P04 | Identity/session/secret grants |
| P06 | P02, P04, P05 | Immutable revisions, snapshots, events, ledgers, artifact store |
| P07 | P01, P02 | Taskboard và fixture/reset/side-effect sensor |
| P08 | P05, P07 | Browser read/action adapters, sandbox/egress và safe capture |
| P09 | P06, P08 | Supervisor, journal/fences và control barriers |
| P10 | P02, P08 | Target guard, basic evaluators, verdict/gate reducers |
| P11 | P06, P09, P10 | Strict replay + Coordinator + submit/result/events API |
| P12 | P05, P06 | Models adapters, fakes, HTTP/error/accounting |
| P13 | P02, P08 | Observation/modalities/budget/redaction/input audit |
| P14 | P10, P11, P12, P13 | AgentRunner và Jev cascade |
| P15 | P12, P13 | Manual native API conformance và capability receipts |
| P16 | P03, P05, P06 | Source ingestion, extraction, requirements/impact |
| P17 | P11, P14, P16 | AI proposal, exploration, import/export, suites/data authoring |
| P18 | P03, P05, P06, P16, P17 | Web workspace/editor/revision flows |
| P19 | P11, P13, P18 | Live/detail/compare/filters/evidence UI |
| P20 | P10, P13, P14, P19 | Similarity/model healing, refusal, proposal revision/UI diff |
| P21 | P08, P10, P11 | Toàn bộ action/evaluator registry và DSL runtime |
| P22 | P06, P14, P19, P20, P21 | Cache, cost views, diagnostics, reports và issue package |
| P23 | P06, P07, P11, P18, P21 | Suite execution/UI, admission, fixture/cleanup và scheduler |
| P24 | P05, P08, P19 | Shared administration, permissions/network hardening |
| P25 | P03, P11, P22, P23, P24 | CLI/API parity, CI exports/templates và webhook outbox |
| P26 | P06, P09, P23, P24, P25 | Deployment, retention, backup/restore, health/telemetry |
| P27 | P07, P21 | Shopflow/Canvasdesk và independent baseline/oracle corpus |
| P28 | P06, P20, P23, P27 | Mutation validity, scoring và anti-leak isolation |
| P29 | P15, P20, P22, P28 | Calibration, sample design và statistical engine |
| P30 | P19, P22, P23, P25, P28, P29 | Immutable experiment manifests, RQ runner/UI và recompute |
| P31 | P19, P21, P22, P24, P25, P26, P30 | Cross-boundary fault/security/OS/performance nghiệm thu |
| P32 | P15, P26, P29, P30, P31 | Release evidence, live demo và tài liệu tái lập |

P29 dùng pilot/calibration jobs chạy trên Coordinator/suite/evaluator đã có ở P11/P23/P28; không cần UI/runner thí nghiệm đầy đủ của P30. Như vậy không tạo vòng dependency P29↔P30. Code healing P20 kiểm tra offline trước, production auto-healing profile chỉ ready sau calibration receipt thật của P29.

## 4. Mốc theo hành vi

| Gate | Tasks cần hoàn thành | Hành vi phải chứng minh |
|---|---|---|
| G0 | P01–P03 | Các schema/ports/types thống nhất, linter/format/import/network-test guard hoạt động |
| G1 | P04–P06 | Không reference chéo workspace, không sửa ready content, secrets không serialize, events/ledger durable |
| G2 | P07–P11 | Case ready → browser thật → assertion độc lập → trace/result qua API; unknown side effect không bị replay |
| G3 | P12–P15 | LLM/cascade với input audit và receipts của đúng Go/Zen routes; image arm chỉ khi capability verified |
| G4 | P16–P19 | URL/tài liệu → proposal → editor/promotion → live/replay/detail/compare trong web |
| G5 | P20–P22 | Healing có refusal/proofs, đầy đủ actions/assertions, báo cáo và kế toán không che missingness |
| G6 | P23–P26 | Chạy suites/lịch, shared permissions, CLI/CI parity, restore/quarantine và artifact lifecycle |
| G7 | P27–P30 | Ba apps/corpus, private oracle, validity/scoring/calibration/RQ manifests và offline recompute |
| G8 | P31–P32 | Tất cả AC qua, safety faults không tạo false pass/duplicate, demo và evidence release tái lập |

G3 có phần live capability khác test offline. Nếu auth/quota/free/ảnh bị chặn, ghi receipt blocked/error và giữ tính năng phụ thuộc chưa được nghiệm thu; các tasks độc lập vẫn có thể tiến triển. Không đổi RQ1 thành text-only và không thay model để làm đủ cột demo.

## 5. Bộ lệnh kiểm tra sẽ tạo

Tất cả lệnh ở mục này chỉ chạy sau task tạo tool/config tương ứng. Exact dependency versions được resolve và pin bằng uv.lock/pnpm-lock.yaml; không dựa vào số phiên bản cũ trong backup. [uv locked sync](https://docs.astral.sh/uv/concepts/projects/sync/), [pnpm frozen install](https://pnpm.io/cli/install).

| Lệnh | Task cung cấp | Kỳ vọng |
|---|---|---|
| `uv lock` rồi `uv sync --locked` | P01 | Lockfile reproducible, Python 3.13, không gọi model |
| `uv run --locked ruff check .` | P01 | Không lỗi lint |
| `uv run --locked ruff format --check .` | P01 | Không diff format |
| `uv run --locked lint-imports` | P01/P02 | Đúng năm lớp; Verify chỉ Contracts |
| `uv run --locked pytest -q` | P01, mở rộng từng task | Tests thật tương ứng pass, model egress bị deny; không dùng API key thật |
| `pnpm --dir apps/web install --frozen-lockfile` | P01 | Lockfile đúng; không tải thêm phiên bản ngoài lock |
| `pnpm --dir apps/web lint` | P01 | ESLint không lỗi |
| `pnpm --dir apps/web format:check` | P01 | Prettier check không diff |
| `pnpm --dir apps/web typecheck` | P01/P03 | TypeScript không lỗi |
| `pnpm --dir apps/web test` | P01, mở rộng P18/P19/P30 | Vitest run mode, không treo watch |
| `pnpm --dir apps/web build` | P01/P18 | Production bundle được tạo từ source/type contracts |
| `uv run --locked python tools/export_schemas.py --check` | P03 | Schema/OpenAPI/client output đã pin không stale |
| `uv run --locked python tools/check_plan_coverage.py` | P01/P03 | Spec/design/plan IDs và references đầy đủ |
| `docker compose -f infra/compose.test.yml up -d --wait` | P04 | PostgreSQL test profile isolated healthy, schema version đúng |
| `uv run --locked python tools/run_ui_e2e.py --models fake` | P18/P19 | API/worker/browser/UI fixtures thật, fake model I/O, artifact failures được lưu |
| `uv run --locked python tools/run_fault_matrix.py --models fake` | P31 | Fault cases có counters/proofs đúng, không model thật |
| `uv run --locked python tools/run_acceptance.py --models fake` | P31 | 24 AC có evidence mapped; không gọi đó là live provider certification |

Không đặt `--env-file .env` vào pytest/lint/UI E2E/fault commands. Harness test tự tạo DB credentials/synthetic fixture secrets và local process profiles. CI có job PostgreSQL/browser thật nhưng không cần Go/Zen keys; các live commands không có trong workflow thường.

## 6. Live commands được tách riêng

| Lệnh dự kiến | Task | Kết quả và giới hạn quyền |
|---|---|---|
| `uv run --env-file .env python tools/model_conformance.py --provider opencode_zen --model jev-1.13-free --live --max-calls 4` | P15 | Zen System One text/questions/response/error/usage receipt; không fallback paid |
| `uv run --env-file .env python tools/model_conformance.py --provider opencode_go --model deepseek-v4.1-flash --live --max-calls 4 --max-output-tokens 2048` | P15 | Go chat/JSON/image/session/usage capability receipt; synthetic inputs, key không output |
| `uv run --env-file .env agentqa calibration execute --manifest benchmarks/calibration/manifest.yaml --live` | P29 | Profile/raw trials/independence/quality bound và cost receipts; manifest pin budgets |
| `uv run --env-file .env agentqa experiment execute --manifest benchmarks/experiments/rq1.yaml --live` | P30 | RQ1 slots/raw runs/scoring/statistics, không provider/model khác |
| `uv run --env-file .env agentqa experiment execute --manifest benchmarks/experiments/rq2.yaml --live` | P30 | RQ2 valid variants, refusals/false heals/false pass và oracle isolation |
| `uv run --env-file .env agentqa experiment execute --manifest benchmarks/experiments/rq3.yaml --live` | P30 | RQ3 independent static baseline, variance và cost phases |
| `uv run --locked agentqa experiment recompute --bundle artifacts/research/export` | P30 | Recompute offline, không đọc API key và không gọi model |

Những manifest/file paths là outputs sẽ tạo ở P27–P30. Khi thực thi phải validate manifest, profile/capability receipts và budgets trước dispatch. `--live` không vô hiệu quyền, redaction hoặc gate; human-readable log chỉ có identifiers/summary và missingness, không raw credentials.

## 7. Evidence và định nghĩa done

Mỗi task cung cấp `TaskReceipt` có task_id, source/spec/design digests, files thay đổi, test command+outcome, artifact refs, schema/lock versions và open/blocking reasons. Receipts runtime lưu private artifact store hoặc `artifacts/implementation/` bị Git bỏ qua; docs chỉ giữ mô tả hệ thống/trạng thái tổng hợp, không nhật ký cá nhân.

Task done cần code chạy thực, tests kiểm behavior qua, documentation tương ứng cập nhật và import/security/format gates áp dụng xanh. Một UI mock, placeholder endpoint, model fake response hoặc receipt chưa chạy không chứng minh production feature đã done. Task live chỉ done khi receipt thật hợp lệ; kết quả nghiên cứu tiêu cực vẫn là dữ liệu hợp lệ.

Xem [acceptance-plan](acceptance-plan.md) để truy mỗi FR/NFR/AC tới tasks và boundary tests. Không đặt mục tiêu đếm test hoặc coverage phần trăm giả. Mỗi invariant phải có fixture/fault độc lập chứng minh outcome.

## 8. Dependency và thay đổi thiết kế

Thêm packages theo công nghệ đã chọn và task cần sử dụng, ghi trong dependency inventory/lockfiles. Bổ sung lựa chọn cụ thể: `rfc8785` để canonical JSON, PyYAML safe parser, argparse của standard library cho CLI; lý do và khóa phiên bản ở P01/P02. Không thêm SDK/router để tự mở provider ngoài phạm vi. [Thư viện canonicalization](https://github.com/trailofbits/rfc8785.py).

Nếu bắt gặp xung đột spec/design hoặc capability không đúng nguồn đã kiểm tra, giữ evidence, sửa thiết kế/ADR trong cùng thay đổi có reason và cập nhật mapping/plan. Không tự thay RQ, kỳ vọng, model hoặc tiêu chí đúng/sai. Hỏi chủ dự án khi quyết định đòi thông tin thực tế hoặc thay đổi yêu cầu bắt buộc, không hỏi lại routine implementation choice.

## 9. Rollback và kết thúc thực thi

Thay đổi source đảo bằng commit có phạm vi; không xoá workspace hoặc chạy reset để né test. Migrations dùng expand/contract đã kiểm tra với restore fixture; destructive migration chỉ sau backup/compatibility/drain được xác minh. Browser effects ngoài hệ thống không rollback bằng Git; dùng fixture reset/outcome probe có receipt.

Release yêu cầu G0–G8, toàn bộ FR/NFR/AC có evidence, hai route/capabilities có receipt thực, calibration và RQ exports integrity/recompute hợp lệ, restore và leak tests qua, UI demo có nguồn. Không tự publish site, merge PR, gửi issue/email hoặc thay remote chỉ vì plan hoàn tất.
