# Giao diện web và trải nghiệm sử dụng

- Ngày: 2026-10-06
- Trạng thái: Thiết kế luồng và UI states; chưa có giao diện triển khai
- Phạm vi: Web thuộc Platform, API client và các màn hình trong spec
- Liên quan: [API](api-and-security.md), [Contracts](contracts-and-dsl.md), [Verify](verification-and-healing.md)

## 1. Cấu trúc ứng dụng

React 19 + TypeScript + Vite, TanStack Router cho URL/search params, TanStack Query cho server state. Draft editor có reducer/history riêng; form state không nằm trong query cache của immutable revision. API types sinh từ OpenAPI, DSL/event validators Ajv dùng đúng schema release.

Shell gồm workspace/application/environment selector, navigation trái và vùng làm việc chính. Navigation: Tổng quan, Yêu cầu, Ca kiểm thử, Bộ ca, Lượt chạy, Thực nghiệm, Cài đặt. Local/shared khác auth/setup, không khác engine hoặc cách đọc kết quả.

Các tokens màu/chữ/khoảng cách là source chung, Radix primitives cho dialog/menu/tabs/focus. UI tiếng Việt, identifiers kỹ thuật chỉ xuất hiện khi cần phân tích hoặc cấu hình. Dark/light và contrast có cùng semantics; không dùng mỗi màu để phân biệt passed/failed/inconclusive.

## 2. Routes và state ownership

| Route | Màn hình | State URL |
|---|---|---|
| `/w/{w}` | Tổng quan | application/environment |
| `/w/{w}/requirements/{id}` | Nguồn, revision, coverage, impact | revision, section |
| `/w/{w}/cases/{id}` | Ca/editor | revision hoặc draft, tab, selected node |
| `/w/{w}/suites/{id}` | Suite/data/fixture/lịch | revision, filters |
| `/w/{w}/runs` | Tìm/lọc lượt chạy | cursor, verdict, status, healed, policy, environment, date range |
| `/w/{w}/runs/{r}` | Live/detail | execution, step, event, evidence tab |
| `/w/{w}/compare` | So sánh | run pair, aligned checkpoint, metric |
| `/w/{w}/experiments/{e}` | Manifest/results | revision, arm, case, variant, metric, scoring version |
| `/w/{w}/settings/{section}` | Quyền, credential refs, environment, workers, usage | section |

Deep link chỉ chứa object IDs và filters, không token/secret/provider input. Selected event/evidence được scope theo run; stale/deleted/expired có màn hình giải thích thay vì crash. Permission check phía server quyết định, UI chỉ giúp tránh thao tác không hợp lệ.

## 3. Case editor

```text
Nguồn yêu cầu và hội thoại | Steps / branches / checkpoints | Thuộc tính bước và evidence
                          | Structured view hoặc YAML       | Assertion và source links
                          |                                 | Validation tại field/node
```

Draft có hai views Structured và YAML (Monaco). YAML invalid giữ nguyên buffer và diagnostics; không ghi AST sai lên server hoặc mất nội dung khi đổi tab. Một draft server có edit_version; autosave chỉ gửi bản validated, If-Match conflict đưa người dùng vào merge/diff. Undo/redo cho local changes, remote revision changes không silently ghi đè history.

Hội thoại sinh proposals gắn diff node/parameter/assertion/source cụ thể. Nút áp dụng proposal tạo draft edit; promotion có tóm tắt kỳ vọng và nguồn cần xác nhận. AI chưa xác nhận nghiệp vụ hiển thị provenance "Suy luận từ quan sát", có thể sửa/xác nhận, không mặc định dấu "đã đúng".

Ready view read-only, có "Tạo bản chỉnh sửa". Run thử dùng draft snapshot và badge "Thử nghiệm"; nó không promote ca. Secret fields hiển thị credential references/permission status, không preview giá trị. Required assertions, applicability và completion được xem trước để tránh ca chỉ có hành động.

## 4. Live run

```text
Trạng thái thực thi | Kết luận hiện có | Phục hồi/retry/degraded | Pause / Tiếp tục / Huỷ
Timeline theo bước | Browser view và safe target overlay     | Assertion / Decisions / Usage
                  |                                         | Expected / Observed / Evidence
```

Snapshot + SSE cập nhật timeline, WebSocket cung cấp masked frames. UI selected step có thể ở quá khứ trong khi engine tiếp tục; có nút "Theo dõi trực tiếp" để quay lại latest, không tự kéo người đang đọc lỗi sang bước mới.

Decision panel thể hiện dữ kiện/candidates, backend, escalation, summary rule; không chạy animation giả chain-of-thought. Business verdict khi active là "Chưa có kết luận" hoặc assertion outcome đã biết được đánh dấu chưa final. Run effective pause/cancel là separate state từ request đang gửi.

Browser view là ảnh/stream, không iframe website target. Manual interaction chỉ mở khi waiting_for_input và quyền phù hợp; mọi can thiệp ghi annotation. Engine không phụ thuộc tab UI còn mở; reconnect dùng cursor, dedupe events, hiện stale/reconnecting và không tự đổi queued thành running.

## 5. Run detail và phục hồi

Phần đầu trình bày business verdict, execution status, gate result, annotations và evidence completeness. "Đạt, có phục hồi" có badge riêng và lý do strict CI từ chối; không viết "Ứng dụng lỗi" cho gate rejection này.

Lỗi đầu có căn cứ hiển thị expectation/source, observed value, checkpoint/path và evidence. AI diagnosis có confidence/source và label "Đề xuất phân tích", không thay kết luận. Attempt history giữ rejected/unknown commands, retry và cleanup errors; không chỉ hiện successful steps cuối.

Healing diff đặt target gốc và candidate thực tế cạnh nhau, scope/entity proof, checks, outcome và source run. Proposal locator mới có preview revision diff; apply là Editor action, không có nút "Chữa tất cả lỗi để đạt". Refusal và wrong-heal theo oracle có trạng thái rõ trong experiment view.

Artifact missing/redacted/expired cho biết lý do và phần kết luận còn đọc được. Không tạo thumbnail/link cho original sensitive artifact mà người xem không có quyền.

## 6. Compare và reports

So sánh pin hai run/snapshot, kiểm tra case/environment/policy/model/browser/calibration/cache differences trước khi đặt chart. Align theo node/checkpoint và iteration path; không align chỉ theo step index khi branch khác nhau. Có khoảng "không có bước tương ứng" thay ghép sai evidence.

Metrics có provenance và coverage: reported/estimated/unknown cost, provider cache và quota/subscription tách biệt. Chart có filter/missing counts và bảng dữ liệu tương đương; bar zero không đại diện giá trị unknown. Diff images dùng baseline/masks/profile của từng run, không trình bày diff đã đổi tolerance như regression cố định.

HTML/JUnit/CSV/JSONL được tạo từ server read model có version, UI không tự tính verdict. Issue package preview redaction và nguồn evidence, người dùng download; không tự gửi tới bên ngoài.

## 7. Thực nghiệm

Manifest editor hiển thị RQ, valid configuration matrix, calibration/evaluation split, dataset/variant/repetition, budgets/cache và scoring. Validation chỉ rõ tổ hợp không hợp lệ như cascade+vision_first; capability chưa verified không được hiện ready cho arm ảnh.

Run progress có scheduled/running/completed/blocked/invalid/unscorable, không chỉ pass count. Results drill từ distribution/case pair xuống oracle scoring và safe evidence. UI tiêu đề phân biệt product passed với oracle success; wrong heal vẫn có thể hiện khi product cuối failed.

Manifest/scoring/calibration versions read-only sau pin; sửa tạo revision mới. Không có thao tác chỉnh denominator để ẩn lượt lỗi; exclusions có provenance trước evaluation. Protocol/sample report có rationale và label kết quả thực, không seed số minh hoạ vào dashboard production.

## 8. Async/error states

| State | Hành vi UI |
|---|---|
| Loading | Skeleton và nội dung vừa có, không reset editor/timeline selection |
| Empty | Giải thích chưa có dữ liệu và entry action tương ứng |
| Validation error | Field/node diagnostics có source; focus vào lỗi đầu, giữ buffer |
| Permission error | Không lộ existence ngoài workspace; có hướng đổi workspace/login hợp lệ |
| Network reconnect | Giữ snapshot cũ và đánh dấu stale; retry reads, không retry submit bằng key mới |
| Revision conflict | Diff base/local/remote; lưu proposal, không silently overwrite |
| Provider/capability unavailable | Hiện route/action bị thiếu và trạng thái; không gợi ý tự đổi provider trả phí |
| Evidence incomplete | Label + artifact reason + ảnh hưởng tới verdict/RQ, không thumbnail trắng giả đủ proof |

Server changes ghi query invalidation có cursor/version. Retry mutations chỉ dùng original idempotency key; logout/revoke đóng streams và xóa caches scoped user. Không optimistic mark promotion/run passed trước server receipt.

## 9. Accessibility và interaction

Keyboard điều khiển shell, editor, dialogs, timeline và data table; Radix focus quản lý modal và return focus. Live updates có aria-live summary throttled, không đọc mọi frame hoặc cướp focus. Reduced-motion không mất thông tin trạng thái.

Tooltip chứa detail bổ sung, thông tin quan trọng có text trực tiếp. Evidence images có caption/alt theo event metadata, table version của charts hỗ trợ đọc screen reader. Layout compact trên laptop, responsive collapse panels; thao tác bắt buộc không phụ thuộc hover.

## 10. Verification

Vitest kiểm reducer/history/query effects, schemas và formatting money/missingness. UI E2E dùng backend+PostgreSQL thật và fake model adapters: author→promote→replay→heal→report, reconnect, conflicts, role permissions và keyboard flows. Screenshots UI kiểm visual regression của chính AgentQA, độc lập với visual assertions cho website mục tiêu.

Không cần gọi API model thật để kiểm editor/live/report. Server supplies authoritative truth/gate và client contract fixtures; kiểm rằng UI không đổi hình thức unknown thành pass/zero, hoặc hiển thị hidden raw artifact vì client state bị sửa.
