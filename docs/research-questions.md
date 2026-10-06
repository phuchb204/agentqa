# AgentQA — ba câu hỏi nghiên cứu

- Ngày: 2026-10-06
- Trạng thái: Mục tiêu nghiên cứu bắt buộc; cần viết giao thức thực nghiệm chi tiết

## RQ1 — Quan sát hybrid so với vision-first

Với cùng bộ kịch bản, hybrid tiết kiệm token, chi phí và thời gian đến mức nào so với vision-first, trong khi duy trì tỉ lệ hoàn thành và chất lượng kiểm chứng?

- Biến độc lập: chiến lược quan sát hybrid hoặc vision-first.
- Giữ chung mục tiêu, dữ liệu, ứng dụng, model/policy LLM đối chứng, khả năng hành động, điều kiện kết thúc và checker; ghi rõ mọi khác biệt không thể giữ chung.
- So sánh trong chế độ agent, tách tác động của replay và cache. Hybrid phải có quy tắc dùng ảnh rõ ràng, không đổi tên text-only thành hybrid.
- Đo token văn bản/ảnh khi provider cung cấp, chi phí, thời gian quan sát/quyết định/thực thi, số bước, tỉ lệ dùng ảnh và tỉ lệ hoàn thành theo kiểm chứng độc lập.
- Thí nghiệm Jev cascade so với LLM thuần là chiều so sánh policy riêng; không trộn thay đổi policy vào kết luận về quan sát.

## RQ2 — Hiệu quả phục hồi trên giao diện đột biến

Khi giao diện thay đổi có kiểm soát, hệ thống phát hiện và phục hồi định vị đúng đến mức nào, đồng thời hạn chế phục hồi sai và kết luận đạt sai?

- Lưu ca/locator và danh tính ngữ nghĩa của phần tử trên bản gốc, chạy lại trên biến thể; việc agent chọn phần tử từ đầu không tự được tính là phục hồi.
- Biến thể có ground truth về thay đổi và phần tử đích, được chấm bằng cơ chế độc lập; không cung cấp đáp án chuẩn cho agent/healer.
- Phân biệt thay đổi giao diện giữ nguyên nghiệp vụ với đột biến gây lỗi nghiệp vụ. Loại thứ nhất có thể phục hồi; loại thứ hai phải được phát hiện thay vì chữa thành đạt.
- Ghi sự kiện phát hiện, các ứng viên, phần tử được chọn, hành động thực tế, kết quả kiểm chứng và bằng chứng cần đối chiếu.
- Đo phát hiện đúng/sai, phục hồi đúng/sai, từ chối phục hồi, tỉ lệ hoàn thành và false pass. Phục hồi sai được đo cả khi ca cuối cùng không đạt; không chỉ đếm các lần sai dẫn đến đạt giả.
- Chốt mẫu số và đơn vị của mỗi chỉ số (cơ hội phục hồi, lần thử phục hồi, bước hoặc ca) trước khi chạy.
- So sánh cấu hình bật/tắt phục hồi và baseline định vị trên cùng biến thể.

## RQ3 — Độ ổn định và chi phí so với baseline

So với kịch bản tĩnh, nền tảng agent và replay có phục hồi đạt độ ổn định, thời gian, chi phí và khả năng tái lập như thế nào?

- Các arm: kịch bản tĩnh, agent LLM thuần, agent Jev cascade, replay không phục hồi và replay có phục hồi; định nghĩa tổ hợp hợp lệ trong giao thức thực nghiệm.
- Chạy cùng bộ ca, dữ liệu và checker trên ứng dụng gốc và các biến thể phù hợp; cô lập phiên và reset dữ liệu giữa các lượt.
- Lặp nhiều lần theo cấu hình khai báo; đo nhất quán kết quả, biến động thời gian/chi phí, tỉ lệ lỗi và tài nguyên khi chạy song song.
- Tách chi phí tạo ca, chạy lại và phục hồi; nêu số lượt hồi quy khi tính chi phí tích luỹ. Không so chi phí tạo ca của một arm với chỉ chi phí replay của arm khác.
- Chi phí chưa biết phải có trạng thái thiếu dữ liệu; mọi ước tính ghi nguồn giá, ngày và phương pháp. Không coi token hoặc API free/subscription là bằng chứng đủ để suy ra tổng chi phí bằng zero.
- Tái lập nghĩa là cấu hình, dữ liệu và cách thực nghiệm có thể chạy lại; không đòi trace hoặc đầu ra LLM phải giống tuyệt đối.

## Nguyên tắc chung

1. Dùng môi trường kiểm thử có thể kiểm soát, bộ ca đa dạng và biến thể có ground truth; không khoá thí nghiệm vào demo đăng nhập/todo cũ.
2. Khai báo cấu hình và chỉ số trước khi chạy; ghi toàn bộ lượt được lập lịch, cả lỗi, huỷ và timeout, không chỉ lưu ca đạt.
3. Ghi phiên bản ứng dụng, bộ ca, biến thể, code, model, prompt/câu hỏi và tham số sinh; seed chỉ khi backend hỗ trợ.
4. Ghi dữ liệu từng bước và từng lượt gọi mô hình; tổng hợp có thể đối chiếu với dữ liệu gốc.
5. Phân biệt cơ chế kiểm chứng trong sản phẩm với oracle đánh giá thí nghiệm, để đo được cả thiếu sót của assertion sản phẩm.
6. Lặp và so sánh cặp trên cùng ca; trình bày phân bố, độ bất định và hạn chế khái quát hoá, không chỉ số trung bình.
7. Test tự động không gọi API thật. Thực nghiệm thật có cấu hình riêng, đo chi phí và lưu bằng chứng.
8. Tài liệu này giữ mục tiêu và nguyên tắc; chưa chốt kích thước mẫu, ngưỡng hay kết quả thực nghiệm.
