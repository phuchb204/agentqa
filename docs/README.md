# Tài liệu AgentQA

Index tài liệu và chuẩn viết. Tài liệu mô tả **dự án** (thiết kế, quyết định, quy trình, tiến độ), không phải nhật ký cá nhân.

## Cấu trúc

| Thư mục / file | Nội dung | Khi nào dùng |
|---|---|---|
| `architecture.md` | Kiến trúc hệ thống, module, luật import, luồng dữ liệu | Đọc trước khi sửa code |
| `adr/` | Quyết định kiến trúc (đánh số, một chiều) | Đọc trước khi đổi kiến trúc/dependency; tạo ADR mới khi có quyết định lớn |
| `specs/` | Đặc tả thiết kế feature — `YYYY-MM-DD-<slug>-design.md` | Đọc trước khi triển khai feature; viết spec mới khi thiết kế thay đổi lớn |
| `plans/` | Kế hoạch triển khai feature — `YYYY-MM-DD-<slug>.md` | Viết trước khi code; xoá khi merge xong |
| `runbooks/` | Hướng dẫn vận hành (setup, tái lập thí nghiệm) | Onboard; cập nhật khi quy trình đổi |
| `roadmap.md` | Mốc phiên bản và trạng thái dự án | Cập nhật khi mốc đổi trạng thái |

`docs/reports/` là gói báo cáo đồ án, không thuộc repo (bị gitignore) — không index tại đây.

## Chuẩn viết

1. **Ngôn ngữ:** nội dung tiếng Việt; tên file và định danh tiếng Anh.
2. **Đặt tên:** `adr/NNNN-<slug>.md`, `specs|plans/YYYY-MM-DD-<slug>.md`; tên file không dấu.
3. **Đầu file** ghi **Ngày** + **Trạng thái**; ADR/spec ghi thêm **Phạm vi ảnh hưởng**.
4. **Cùng PR:** PR đổi hành vi, kiến trúc hoặc quy trình phải cập nhật tài liệu tương ứng trong cùng PR.
5. **Bản ghi lịch sử:** ADR/spec đã duyệt không sửa nội dung cũ; thay đổi quyết định thì tạo bản mới ghi rõ "Thay thế bởi …".
6. **Plan tạm thời:** plan chỉ tồn tại trong lúc triển khai; xoá khi merge xong — kết luận đã nằm ở ADR/spec/CHANGELOG.
7. Không ghi phân công hay tên thành viên trong repo; phân công theo dõi ở GitHub Issues.
