# AgentQA

Nền tảng kiểm thử web bằng AI agent: biến yêu cầu nghiệp vụ thành ca kiểm thử, thực hiện trên trình duyệt thật, chạy hồi quy, phục hồi định vị và cung cấp kết luận truy được về bằng chứng.

Repo được khởi tạo lại để thiết kế và triển khai từ đầu. Đã có tài liệu nền, cơ sở nghiên cứu, spec sản phẩm, bộ thiết kế hệ thống và implementation plan; chưa có mã nguồn hoặc môi trường thực thi.

## Bắt đầu

1. Đọc [nội quy cho AI](AGENTS.md).
2. Đọc [index tài liệu](docs/README.md).
3. Đọc [định hướng sản phẩm](docs/product-brief.md) và [ba câu hỏi nghiên cứu](docs/research-questions.md).
4. Đọc [cơ sở nghiên cứu](docs/research/design-evidence.md) và [spec sản phẩm](docs/specs/product-spec.md).
5. Đọc [thiết kế hệ thống](docs/architecture.md), các thiết kế chi tiết và [truy vết nghiệm thu](docs/design/acceptance-mapping.md).
6. Đọc [implementation plan](docs/plans/rebuild-plan.md), các gói task và [truy vết nghiệm thu vào plan](docs/plans/acceptance-plan.md).
7. Triển khai theo dependency/gate của plan sau khi bản plan được chọn làm cơ sở thực thi; các lệnh trong plan chưa tồn tại ở repo hiện tại.

## Các quyết định nền tảng

- Giữ ba câu hỏi nghiên cứu RQ1–RQ3, LLM và Jev cascade.
- Giữ khung năm lớp: Contracts, Models, Agent, Verify, Platform; thiết kế lại các thành phần và hợp đồng bên trong.
- Hỗ trợ tạo ca bằng AI, khám phá ứng dụng, replay và phục hồi có kiểm soát.
- Kiểm chứng độc lập; kỳ vọng kiểm thử giữ nguyên trong từng phiên bản ca.
- Giao diện web, CLI, API và tích hợp CI dùng chung bộ thực thi.
- Ưu tiên chất lượng, mức hoàn thiện, trải nghiệm và độ tin cậy của sản phẩm.

Provider ban đầu: Jev `jev-1.13-free` qua OpenCode Zen System One và LLM `deepseek-v4.1-flash` qua OpenCode Go Chat Completions. Cấu hình mẫu nằm trong [.env.example](.env.example), không chứa API key. Provider khác thuộc phần mở rộng sau.

MIT — xem [LICENSE](LICENSE).
