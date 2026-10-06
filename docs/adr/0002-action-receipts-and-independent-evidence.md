# ADR 0002 — Action receipts và bằng chứng kiểm chứng độc lập

- Ngày: 2026-10-06
- Trạng thái: Đề xuất được sử dụng trong thiết kế 1.0; chưa triển khai
- Phạm vi: Agent, Verify, browser supervision, trace và research
- Liên quan: [Engine](../design/execution-and-models.md), [Verify](../design/verification-and-healing.md)

## Bối cảnh

Browser timeout hoặc worker mất reply không chứng minh side effect chưa xảy ra. Selector vẫn resolve có thể trỏ entity sai. Model nói đã hoàn thành không chứng minh expected outcome. Native browser traces có thể chứa sensitive data và không thay assertion trace của engine.

## Quyết định

1. Tách proposal, prepared command, admission, dispatch và settled/unknown outcome bằng journal/receipts có fence.
2. Browser supervisor kiểm ownership/control và scene proof; mất lease chặn lệnh mới, không tự chạy lại command outcome unknown.
3. Guard identity ngay cả khi locator resolve; recovery chỉ đổi target binding, không đổi expectation.
4. Verify tính business verdict và gate từ immutable plan/proofs, không từ policy rationale; healer không truy oracle.
5. Safe evidence phải được sanitize trước persist/model/live stream; SafeTraceBundle mặc định, native trace chỉ khi capture policy đủ bảo đảm.
6. Product verdict và independent oracle scoring được giữ riêng để đo false pass/false healing.

## Các phương án

Retry browser action trên timeout dễ tạo side effect trùng. Dùng agent/LLM làm judge của chính run không đáp ứng oracle độc lập. Chỉ redact JSON export để raw trace/screenshot vẫn chứa dữ liệu nhạy cảm không đáp ứng spec. Chỉ nhìn selector exception bỏ sót reused-ID/same-name identity mismatch.

## Hệ quả

Hệ thống có outcome inconclusive và refusal hợp lệ; không tối đa hoá pass rate bằng cách giấu uncertainty. DB fencing không hoàn tác request đã tới website; recovery cần outcome probes hoặc fixture reset receipts. Các guarantees phải được kiểm bằng side-effect counters, secret canaries và failure injection khi triển khai.
