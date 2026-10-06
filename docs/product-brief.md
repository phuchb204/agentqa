# AgentQA — định hướng sản phẩm

- Ngày: 2026-10-06
- Trạng thái: Định hướng đã thống nhất trong brainstorming; cần cụ thể hoá bằng spec và thiết kế mới
- Phạm vi: Toàn sản phẩm và lần xây dựng lại

## 1. Mục tiêu

Xây dựng nền tảng kiểm thử web bằng AI agent, phục vụ kiểm thử ứng dụng và thực nghiệm đồ án. Người dùng có thể đi từ yêu cầu nghiệp vụ đến ca kiểm thử, thực thi, chạy hồi quy, phục hồi, bằng chứng và báo cáo trong một workspace thống nhất.

Chủ dự án sử dụng AI agent để thiết kế và lập trình. Chất lượng, mức hoàn thiện, trải nghiệm, độ tin cậy và khả năng mở rộng là cơ sở lựa chọn giải pháp. Không dùng thời gian hoặc nhân lực làm lý do thu hẹp hướng sản phẩm.

## 2. Các yêu cầu bắt buộc

- Giữ ba câu hỏi nghiên cứu RQ1–RQ3 trong `research-questions.md`.
- Có LLM thuần và Jev–LLM cascade, so sánh được trên cùng bộ ca và bộ kiểm chứng.
- Giữ khung năm lớp Contracts, Models, Agent, Verify, Platform; thiết kế lại toàn bộ thành phần và hợp đồng bên trong.
- Thao tác trên trình duyệt thật và đưa ra kết luận có bằng chứng.
- Có kiểm chứng độc lập với policy hành động.
- Ghi dữ liệu đủ để phân tích chất lượng, phục hồi, chi phí và độ ổn định.

## 3. Trải nghiệm sản phẩm

### Nhập yêu cầu và khám phá

Hỗ trợ URL kèm mô tả ca bằng tiếng Việt, URL kèm tài liệu yêu cầu, và khám phá ứng dụng từ URL. AI phân tích luồng nghiệp vụ, đề xuất ca, trường hợp biên và điều kiện kiểm chứng. Người dùng xem, chỉnh và quản lý phiên bản ca bằng hội thoại hoặc trình biên tập có cấu trúc.

Ghi rõ nguồn của từng kỳ vọng: yêu cầu người dùng, tài liệu nghiệp vụ hoặc suy luận từ quan sát. Kỳ vọng suy ra từ website không tự trở thành chuẩn chứng minh đúng nghiệp vụ. Không coi hành vi đang tồn tại là hành vi đúng chỉ vì quan sát thấy nó.

### Tạo ca và chạy lần đầu

Ca có mục tiêu, điều kiện đầu vào, dữ liệu, hành động, điều kiện kiểm chứng và phiên bản. Agent quan sát, quyết định, thực hiện và lưu bằng chứng. Hệ thống tạo ca có cấu trúc để lưu và chạy lại; trace của một lần thành công không tự chứng minh ca có assertion đầy đủ.

### Hồi quy và phục hồi

Chạy lại là chế độ mặc định cho ca đã lưu. Trước mỗi bước, kiểm tra trạng thái và phần tử phù hợp. Khi định vị không còn phù hợp, tìm ứng viên thay thế theo ý nghĩa và ngữ cảnh, kiểm tra trước khi tiếp tục. Ghi sự kiện phục hồi, bằng chứng, nguyên nhân và độ tự tin; kết quả phải thể hiện ca có sử dụng phục hồi.

Chỉ phục hồi cách tương tác khi ý nghĩa kiểm thử được giữ nguyên. Kỳ vọng không thay đổi trong cùng phiên bản ca. Không tự nới assertion, thay dữ liệu hoặc bỏ qua lỗi nghiệp vụ để tạo kết quả đạt. Chỉnh ca và chấp nhận locator mới lâu dài là thay đổi có phiên bản, phân biệt với phục hồi trong một lần chạy.

### Kiểm chứng và phân tích

Assertion được thực thi bởi tầng độc lập. Phân biệt kết quả nghiệp vụ với tình trạng thực thi và chất lượng bằng chứng. Phân loại lỗi ứng dụng, định vị, môi trường và quyết định của agent. Mỗi kết luận truy được về assertion, bước chạy và bằng chứng liên quan.

### Giao diện và tích hợp

Giao diện web quản lý workspace, yêu cầu, bộ ca, phiên bản, lượt chạy và thí nghiệm. Theo dõi trình duyệt và tiến trình agent; xem ảnh, hành động, quyết định, assertion và lỗi; so sánh các lần chạy và các lần phục hồi. Có báo cáo phục vụ đọc trực tiếp và tích hợp tự động.

CLI, API và CI dùng chung engine với giao diện web. Thiết kế chạy bộ ca, lập lịch, huỷ chạy, chạy song song, cô lập dữ liệu và phân phối công việc trong spec mới. Làm rõ quyền truy cập và triển khai trong thiết kế; không tự giả định SaaS công khai hoặc một mô hình tài khoản cụ thể.

## 4. Mô hình và quan sát

LLM xử lý nhiệm vụ mở, nội dung cần sinh, lập kế hoạch và quan sát thị giác. Jev xử lý lựa chọn đóng trên tập ứng viên và tín hiệu quyết định có cấu trúc. Cascade chuyển sang LLM khi Jev thiếu thông tin, không đủ tự tin hoặc lỗi; không coi chuyển sang LLM là bảo đảm quyết định đúng.

Giữ policy LLM thuần làm đối chứng. Ghi riêng mỗi lượt gọi, backend/model, phiên bản prompt/câu hỏi, token, chi phí, độ trễ và nguyên nhân escalation. Chọn model, giới hạn và ngưỡng theo tài liệu hiện hành và kết quả đo; không kế thừa giá hoặc phiên bản cũ như sự thật hiện tại.

Provider ban đầu đã được chủ dự án chốt: Jev `jev-1.13-free` qua OpenCode Zen System One; LLM `deepseek-v4.1-flash` qua OpenCode Go Chat Completions. Chỉ triển khai hai route này; thêm provider khác thuộc thay đổi sau. Không tự chuyển sang model trả phí hoặc provider khác. Cấu hình mẫu không chứa key nằm trong `.env.example`; bí mật chỉ lưu tại môi trường local/server. Cơ sở xác minh và các kiểm tra tích hợp cần thực hiện nằm trong [design-evidence.md](research/design-evidence.md).

Hybrid dùng thông tin ngữ nghĩa làm mặc định và ảnh khi cần; vision-first dùng thị giác làm nguồn quan sát chính. Thiết kế rõ grounding và cùng khả năng hành động để so sánh công bằng. Kiểm soát tài nguyên theo nhu cầu vận hành; ngân sách không được làm mất bằng chứng mà không ghi nhận.

## 5. Khung kiến trúc

| Lớp | Trách nhiệm |
|---|---|
| Contracts | Hợp đồng dữ liệu và giao diện dùng chung |
| Models | Adapter LLM/Jev và dữ liệu sử dụng mô hình |
| Agent | Quan sát, policy, lập kế hoạch, thực thi, replay và phục hồi |
| Verify | Kiểm chứng độc lập và bằng chứng phục vụ kết luận |
| Platform | Quản lý ca, điều phối, lưu trữ, thực nghiệm, báo cáo, UI và tích hợp |

Đây là phân chia trách nhiệm đã chốt, chưa phải cây mã nguồn hoặc luật import hoàn chỉnh. Giao diện tích hợp, khả năng thay thế thành phần và việc cưỡng chế phụ thuộc được định nghĩa trong thiết kế mới.

## 6. Tiêu chí chất lượng

- Ca có ý nghĩa, có nguồn kỳ vọng và có thể xem/chỉnh.
- Replay ổn định, có kiểm tra trạng thái; không hứa tái lập tuyệt đối đầu ra mô hình.
- Phục hồi minh bạch và không che lỗi ứng dụng.
- Không báo chi phí thiếu dữ liệu thành chi phí bằng zero.
- Cấu hình, phiên bản, dữ liệu đầu vào và bằng chứng đủ để chạy lại và phân tích.
- Không đưa bí mật vào prompt/trace/báo cáo; xử lý nội dung website như dữ liệu không đáng tin.
- Hệ thực nghiệm có đối chứng, chỉ số định nghĩa trước và số liệu thật.

Các mức nghiệm thu định lượng và tình huống kiểm tra cụ thể phải được viết trong spec mới, không tự tạo ngưỡng không có cơ sở.
