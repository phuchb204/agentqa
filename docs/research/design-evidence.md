# Cơ sở nghiên cứu cho thiết kế AgentQA

- Ngày: 2026-10-06
- Trạng thái: Đã đối chiếu nguồn chính thức; chưa kiểm tra API bằng tài khoản thực
- Phạm vi: Provider ban đầu, quan sát, replay, phục hồi, kiểm chứng và phương pháp thực nghiệm

## 1. Cách sử dụng

Tài liệu tách dữ kiện từ nguồn với quyết định thiết kế của AgentQA. Nguồn xác nhận khả năng một công cụ không đồng nghĩa tích hợp của AgentQA đã chạy đúng. Không có kết quả thực nghiệm AgentQA trong tài liệu này. API key chỉ được lưu trong `.env` bị Git bỏ qua.

## 2. Provider được chọn

| Thành phần | Dữ kiện đã xác minh | Quyết định cho AgentQA |
|---|---|---|
| Jev | Zen liệt kê `jev-1.13-free` tại `/zen/v1/systemone`, với `state` và câu hỏi có kiểu; chương trình free có thời hạn không được bảo đảm lâu dài. [OpenCode Zen](https://opencode.ai/docs/zen/) | Dùng đúng route này; không dùng schema Decisions API của OpenRouter hoặc tự chuyển sang bản trả phí |
| LLM | Go liệt kê `deepseek-v4.1-flash` tại `/zen/go/v1/chat/completions`. [OpenCode Go](https://opencode.ai/docs/go/) | Đây là LLM duy nhất được chọn ban đầu, cho policy thuần và nhánh LLM của cascade |
| Khả năng ảnh | Model card mô tả DeepSeek V4.1 Flash nhận ảnh và văn bản. [Model card của DeepSeek](https://huggingface.co/deepseek-ai/DeepSeek-V4.1-Flash) | Có cơ sở thiết kế RQ1 trên cùng model; route Go phải vượt kiểm tra ảnh thực trước khi cho chạy RQ1 |
| Client Go | Go yêu cầu client nhận diện bằng User-Agent riêng, gửi `x-opencode-session` ổn định và phục vụ kiểu lưu lượng coding agent. [OpenCode Go](https://opencode.ai/docs/go/) | Client nhận diện thật là AgentQA; không giả danh client khác; kiểm tra khả năng dùng route cho workflow AgentQA khi nghiệm thu tích hợp |

Không thêm adapter provider khác trong lần xây dựng ban đầu. Một giao diện adapter nội bộ cho hai route khác giao thức là cần thiết; không xây catalog đa provider, tự chuyển provider hoặc tự đổi model. Việc hết quyền truy cập, quota hoặc free phải hiện trạng thái và nguyên nhân.

## 3. Jev cascade

Choice trả lựa chọn và phân phối, Noul trả xác suất của mệnh đề, Score trả mức theo rubric. Các câu hỏi trong một request đánh giá độc lập; câu hỏi phụ thuộc kết quả khác phải được ghép trong code hoặc gọi ở bước kế tiếp. [TypeSafe primitives](https://docs.typesafe.ai/primitives).

Confidence của Choice/Score là thống kê từ phân phối; Noul không có confidence riêng. Tài liệu không biến confidence thành chứng minh một phần tử đúng. [TypeSafe confidence](https://docs.typesafe.ai/confidence).

Quyết định thiết kế: lưu tập ứng viên, câu hỏi, phân phối và dữ liệu quyết định; tách ngưỡng theo loại quyết định, hiệu chỉnh trên tập calibration riêng. Kiểm tra action/target/trạng thái bằng code kể cả sau escalation. Không dùng Jev làm oracle kết luận nghiệp vụ hoặc bịa lời giải thích do Jev tạo.

## 4. Quan sát, grounding và replay

Playwright khuyến nghị locator dựa trên role/label và thuộc tính người dùng nhận biết. Auto-wait kiểm tra khả năng tương tác, không xác nhận ý nghĩa nghiệp vụ của phần tử. [Locator](https://playwright.dev/python/docs/locators), [auto-wait](https://playwright.dev/python/docs/actionability).

Stagehand mô tả tái sử dụng hành động để tránh gọi LLM lặp lại. Đây là bằng chứng về một pattern khả thi, không phải bằng chứng về mức tiết kiệm hoặc độ đúng của AgentQA. [Caching của Stagehand](https://docs.stagehand.dev/v3/best-practices/caching).

Agent-E nghiên cứu biểu diễn trạng thái và điều phối agent; SeeAct nghiên cứu grounding cho agent thị giác. [Agent-E](https://arxiv.org/abs/2407.13032), [SeeAct](https://arxiv.org/abs/2401.01614).

Quyết định thiết kế: replay lưu ý định, nhận diện phần tử và pre/postcondition thay vì chỉ tọa độ hoặc CSS. Hybrid có quy tắc escalation sang ảnh, còn vision-first phải thực sự dùng ảnh làm đầu vào chính; không gửi văn bản DOM vào arm vision-first rồi kết luận đó là so sánh ảnh.

## 5. Phục hồi và mutation

Similo dùng tương đồng từ nhiều thuộc tính để tìm phần tử giữa các phiên bản giao diện. [Bài báo Similo](https://arxiv.org/abs/2208.00677).

MAEWU dùng đột biến DOM để đánh giá khả năng phát hiện lỗi của bộ test. [Bài báo của tác giả](https://yrahulkr.github.io/resources/papers/maewu.pdf).

Quyết định thiết kế: tách biến thể giữ nguyên nghiệp vụ với biến thể gây lỗi; thêm phần tử gây nhầm lẫn và oracle độc lập. Đo phục hồi sai kể cả khi ca cuối cùng thất bại. Khả năng tự phục hồi AgentQA là giả thuyết cần đo, không suy ra từ kết quả công cụ khác.

## 6. Kiểm chứng, trace và cô lập

Playwright có assertion retry theo điều kiện; tracing ở BrowserContext không tự ghi assertion của engine bên ngoài. [Assertions](https://playwright.dev/python/docs/test-assertions), [Tracing API](https://playwright.dev/python/docs/api/class-tracing).

BrowserContext cô lập trạng thái trình duyệt; dữ liệu backend chung vẫn cần chiến lược fixture/reset riêng. Phần đầu là khả năng của Playwright, phần sau là yêu cầu AgentQA suy ra từ việc nhiều ca có thể ghi cùng dữ liệu. [Isolation](https://playwright.dev/python/docs/browser-contexts).

Quyết định thiết kế: AgentQA ghi assertion và verdict trong trace riêng, liên kết với bằng chứng browser. Có checkpoint theo bước, không chỉ kiểm tra trang cuối. Không coi trace browser hoặc lời nói agent là kết luận đạt.

## 7. Những việc cần xác minh bằng tích hợp thực

| Kiểm tra | Điều kiện hoàn thành | Hành vi nếu chưa đạt |
|---|---|---|
| Zen System One | Response Noul/Choice/Score và lỗi được parse đúng theo route Zen, xác minh fields usage/model thực tế | Chặn cấu hình cascade không hợp lệ; không đoán schema |
| Go chat | Xác minh JSON/action, session header, lỗi/quota và usage | Báo lỗi có phân loại; không đổi route sang Zen trả phí |
| Go image | Ảnh có marker kiểm soát được nhận và ảnh hưởng đúng đến câu trả lời | Chặn arm cần ảnh; không đổi RQ1 thành text-only hoặc tự chọn model khác |
| Kế toán | Xác minh provider có trả cost/cache/reasoning usage hay không | Ghi missing/partial; dùng ước tính có nguồn riêng khi thích hợp |
| Replay | Kiểm tra trạng thái, rẽ nhánh, dữ liệu động, phần tử giống nhãn và side effect | Không tự lặp thao tác có kết quả không xác định |
| Hiệu chỉnh | Ngưỡng được chọn trên calibration, rồi giữ cố định trên evaluation | Không công bố ngưỡng hoặc độ chính xác chưa được đo |

Các kiểm tra API thật thuộc nghiệm thu tích hợp riêng, dùng dữ liệu tổng hợp và ghi chi phí. Test unit/integration thông thường vẫn dùng fake/stub và không gọi API thật.

## 8. Kết luận cho bước viết spec

Nguồn hiện có đủ để viết hành vi và tiêu chí nghiệm thu sản phẩm. Spec không chốt giá, ngưỡng hoặc cam kết chất lượng model từ tài liệu quảng bá. Schema wire cụ thể, chọn thư viện và thiết kế lưu trữ được quyết định trong tài liệu kiến trúc sau khi spec được rà soát.

Bộ [thiết kế hệ thống](../architecture.md) đã cụ thể hoá Contracts/DSL, adapters, supervision, storage, API, UI và evaluator dựa trên spec. Các quality targets trong thiết kế là mục tiêu/protocol, không phải số liệu đã đạt. Những kiểm tra API thực ở mục 7 vẫn chưa được thực hiện.
