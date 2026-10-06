# ADR 0001 — Năm lớp và control plane dùng dữ liệu bền vững

- Ngày: 2026-10-06
- Trạng thái: Đề xuất được sử dụng trong thiết kế 1.0; chưa triển khai
- Phạm vi: Toàn backend, UI/CLI, persistence và deployment
- Liên quan: [Kiến trúc](../architecture.md), [Platform/storage](../design/platform-and-storage.md)

## Bối cảnh

Sản phẩm có immutable revisions, authoring/run/experiment jobs, quyền workspace, browser sessions và verdict dùng chung Web/API/CLI/CI. Promote, snapshot, queue và events cần cùng nguồn dữ liệu nhất quán. Browser/model I/O dài không được gắn với lifetime request HTTP.

## Quyết định

1. Giữ Contracts, Models, Agent, Verify, Platform; Verify chỉ phụ thuộc Contracts và không được điều khiển browser.
2. Backend modular monolith, process API/worker/browser supervisor/scheduler riêng; composition trong Platform.
3. PostgreSQL 18 làm source of truth và queue; SQLAlchemy async/psycopg/Alembic, artifacts ngoài DB.
4. Events/state/audit/outbox commit cùng transaction, SSE dùng durable run sequence; NOTIFY chỉ wake-up hint.
5. React/TypeScript web và CLI là clients của cùng API, không có checker hoặc persistence bypass riêng.

## Các phương án

Microservices cho từng lớp làm promote/snapshot/control transactions phân tán; chưa có yêu cầu deploy độc lập các bounded domains này. Workflow runtime ngoài cung cấp orchestration nhưng không giải quyết exactly-once của thao tác website; không chọn thêm runtime trong topology này. Queue trong memory hoặc background HTTP task không có lịch sử/recovery đầy đủ nên không đáp ứng spec.

## Hệ quả

Phải thực thi rõ RLS/ownership/resource reservations, lock order, migrations và fault tests. Module boundaries giữ khả năng tách deployment sau này bằng ports; không thêm provider model ngoài hai route đã chọn. Các lựa chọn dependency trong thiết kế chưa đồng nghĩa đã được cài hoặc kiểm tra tương thích.
