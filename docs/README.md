# Tài liệu nền AgentQA

Đọc theo thứ tự:

| Tài liệu | Vai trò |
|---|---|
| [product-brief.md](product-brief.md) | Bài toán, hướng sản phẩm, trải nghiệm và các quyết định đã chốt |
| [research-questions.md](research-questions.md) | Ba RQ bắt buộc, nguyên tắc đối chứng và dữ liệu cần đo |
| [references.md](references.md) | Nguồn tham khảo để xây spec và phương pháp đánh giá |
| [research/design-evidence.md](research/design-evidence.md) | Dữ kiện đã xác minh, quyết định suy ra và những kiểm tra tích hợp cần thực hiện |
| [specs/product-spec.md](specs/product-spec.md) | Spec sản phẩm: 51 yêu cầu chức năng, 12 yêu cầu phi chức năng và 24 tình huống nghiệm thu |
| [architecture.md](architecture.md) | Topology, công nghệ, năm lớp, dependency rules, deployment và invariants |
| [design/contracts-and-dsl.md](design/contracts-and-dsl.md) | Data models, Case DSL, ports, validation và version/digest |
| [design/execution-and-models.md](design/execution-and-models.md) | Browser supervision, engine/replay, observation, policy và hai adapters |
| [design/verification-and-healing.md](design/verification-and-healing.md) | Target identity, recovery, evidence, evaluators, verdict và gate |
| [design/platform-and-storage.md](design/platform-and-storage.md) | Database/queue, locks/leases/events, fixtures, artifacts, scheduling và backup |
| [design/api-and-security.md](design/api-and-security.md) | HTTP/SSE/WS, auth/roles, secret grants, network và CLI/CI |
| [design/web-experience.md](design/web-experience.md) | Navigation, editor/live/compare/experiments và UI states |
| [design/experiments-and-evaluation.md](design/experiments-and-evaluation.md) | Benchmark/mutation/oracle, calibration và pipeline RQ1–RQ3 |
| [design/acceptance-mapping.md](design/acceptance-mapping.md) | Truy vết toàn bộ FR/NFR/AC vào thành phần và phương pháp nghiệm thu |
| [adr/0001-modules-and-durable-control-plane.md](adr/0001-modules-and-durable-control-plane.md) | Quyết định topology, năm lớp và nguồn dữ liệu nhất quán |
| [adr/0002-action-receipts-and-independent-evidence.md](adr/0002-action-receipts-and-independent-evidence.md) | Quyết định journal, unknown effects và kiểm chứng độc lập |
| [plans/rebuild-plan.md](plans/rebuild-plan.md) | Master implementation plan: 32 task, dependency DAG, G0–G8, commands và done/evidence rules |
| [plans/acceptance-plan.md](plans/acceptance-plan.md) | Truy vết 51 FR, 12 NFR, 24 AC vào task và test boundaries |
| [dependencies.md](dependencies.md) | Inventory dependency của gói 01, lý do chọn và phiên bản đã pin |

## Gói triển khai

| Gói plan | Phạm vi |
|---|---|
| [01-foundation](plans/01-foundation.md) | Runtime/lockfiles/CI, Contracts/DSL và schema/client generation |
| [02-data-and-trust](plans/02-data-and-trust.md) | PostgreSQL/RLS, identity/secrets, revisions/events/ledger/artifacts |
| [03-first-browser-run](plans/03-first-browser-run.md) | Fixture app, browser sandbox/supervisor, Verify và strict replay qua API |
| [04-models-and-observation](plans/04-models-and-observation.md) | Hai model adapters, observation, agent/cascade và native conformance |
| [05-authoring-and-web](plans/05-authoring-and-web.md) | Sources/proposals/exploration, editor và live/detail/compare |
| [06-healing-and-complete-engine](plans/06-healing-and-complete-engine.md) | Healing/refusal, action/evaluator matrix, cache/diagnostics/reports |
| [07-platform-and-operations](plans/07-platform-and-operations.md) | Suites/lịch, shared controls, CLI/CI và deployment/backup/retention |
| [08-research](plans/08-research.md) | Ba apps/oracle, mutations/scoring, calibration/statistics và RQ UI/export |
| [09-release](plans/09-release.md) | Fault/security/OS/workload nghiệm thu và demo/release tái lập |

## Các tài liệu cần viết tiếp

1. Thực thi P01–P32 theo master plan khi bắt đầu triển khai; tạo commands/configs ở task cung cấp chúng trước khi chạy.
2. Khi tạo dự án, sinh schema/OpenAPI/client types từ Contracts và pin dependency lockfiles.
3. Viết runbooks setup, deployment, conformance, backup/restore và thí nghiệm với receipts từ môi trường thực.
4. Thêm ADR khi có thay đổi các quyết định quan trọng.

Spec và bộ thiết kế hệ thống 1.0 được dùng làm cơ sở cho implementation plan. Gói 01 (P01–P03: runtime/lockfiles/CI, Contracts/DSL, schema và typed client), gói 02 (P04–P06: PostgreSQL 18/RLS/migrations, identity/sessions/secret grants, revisions/snapshots/events/ledger/artifacts) và gói 03 (P07–P11: Taskboard fixture, browser sandbox/egress/safe capture, supervisor/journal/fences, guard/Verify, strict replay qua API) đã được triển khai kèm test offline; P12–P32 chưa triển khai, chưa có live model receipts (hai route Go/Zen vẫn chưa gọi thật). Gói 02 chạy test trên PostgreSQL 18 thật qua `infra/compose.test.yml`; gói 03 chạy Chromium thật, local trap servers và PostgreSQL 18 thật, không gọi Go/Zen. Đọc spec cho yêu cầu, design cho kỹ thuật, plan cho công việc/phụ thuộc/commands, mapping cho nghiệm thu. Tài liệu hoặc code-ready không thay bằng chứng behavior/capability đã được kiểm thực.

## Quy ước tài liệu

- Nội dung tiếng Việt; tên file tiếng Anh, không dấu.
- Phân biệt trạng thái yêu cầu, đề xuất, đã chốt và đã triển khai.
- Spec/thiết kế mới ghi ngày, trạng thái và phạm vi ảnh hưởng.
- Ghi rõ nguồn của kết luận và số liệu; đánh dấu giả thuyết cần kiểm chứng.
- Tài liệu nền này là nguồn yêu cầu cho lần thiết kế mới. Tài liệu phiên bản trước nằm trong bản sao lưu ngoài workspace.
