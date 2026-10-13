# Runbook — Model conformance (P15)

- Ngày: 2026-10-12
- Trạng thái: Tool và tests offline đã có; live receipts đã chạy và refresh lần cuối 2026-10-12 — Zen verified, Go image giữ blocked (gate ảnh đóng)
- Phạm vi: `tools/model_conformance.py`, registry `src/agentqa/platform/models/capabilities.py`, receipts dưới `artifacts/model-capabilities/`
- Liên quan: [execution-and-models](../design/execution-and-models.md) §9, [design evidence](../research/design-evidence.md) §7, [plan gói 04](../plans/04-models-and-observation.md) P15

## 1. Nguyên tắc

- Chỉ hai route được pin: Zen `jev-1.13-free` (`https://opencode.ai/zen/v1`, `systemone`) và Go `deepseek-v4.1-flash` (`https://opencode.ai/zen/go/v1`, `chat/completions`). Tool từ chối provider/model khác; không có fallback route trả phí và không tự đổi model.
- Mặc định là **offline validate**; gọi provider thật chỉ khi có `--live` tường minh. Tests/CI thường không chạy `--live`.
- Live yêu cầu budgets: `--max-calls` (bắt buộc), `--max-output-tokens` (bắt buộc với Go), `--max-request-bytes` (mặc định 65536). Mọi input là synthetic; không dùng dữ liệu thật.
- Trước transport, request/result đi qua redaction sink: digest được tính trên payload đã sanitize, trường `api_key`/`authorization`/`token`/`secret` bị loại, giá trị key bị thay bằng `[REDACTED]`.
- Receipt không chứa key, account balance hoặc raw prompt có bí mật; `version_identity` giữ `unverified` vì gateway chỉ trả alias, không chứng minh weights/snapshot.

## 2. Phase offline validate

```text
uv run --locked python tools/model_conformance.py --provider opencode_zen --model jev-1.13-free --max-calls 4
uv run --locked python tools/model_conformance.py --provider opencode_go --model deepseek-v4.1-flash --max-calls 4 --max-output-tokens 2048
```

Kỳ vọng: JSON `status=validated_offline` kèm provider/model/budgets và `adapter_schema_version`; không có network call. Sai model, thiếu budget hoặc budget không dương → exit 64 với reason (`model_not_pinned`, `missing_call_budget`, `missing_output_budget`, `missing_request_budget`).

## 3. Phase live (chạy ở master khi được phép)

```text
uv run --env-file .env python tools/model_conformance.py --provider opencode_zen --model jev-1.13-free --live --max-calls 4
uv run --env-file .env python tools/model_conformance.py --provider opencode_go --model deepseek-v4.1-flash --live --max-calls 4 --max-output-tokens 4096
```

- Key đọc từ `AGENTQA_JEV_API_KEY` / `AGENTQA_LLM_API_KEY`; thiếu key → ghi receipt `blocked` với reason `missing_credential_env:...`, exit 2, không gọi transport.
- Probe Zen: System One với synthetic state và ba câu hỏi độc lập (Choice/Noul/Score); kiểm tra answers keyed đúng question ID, type khớp, usage/model nếu provider trả.
- Probe Go: text; JSON object; session/header (`x-opencode-session` ổn định, User-Agent `AgentQA/<version>`); image với **marker thị giác** (3 hình vuông đỏ vẽ bằng Pillow, không có chữ) — model phải trả `{"squares": 3}`; usage/cache fields chỉ ghi `verified` khi provider thật sự trả.
- Kết quả mỗi probe là `verified` / `blocked` / `unsupported`; `blocked` kèm reason (`provider_auth`, `provider_quota`, `image_marker_mismatch:<n>`, `call_budget_exceeded:...`, `request_budget_exceeded:...`, `provider_schema:<probe>:<detail>`). Lỗi schema chỉ chặn capability tương ứng và tiếp tục probe khác; lỗi auth/quota/rate/timeout/redirect chặn cả run. Auth/quota/ảnh không đạt thì lưu reason và **không** đổi model/route.

### Finding live 2026-10-10 (master)

- Zen `jev-1.13-free`: receipt `verified` cho text/structured/usage; image/cache/session `unsupported` đúng thiết kế System One.
- Go `deepseek-v4.1-flash` là **reasoning model**: response có `reasoning_content` và `completion_tokens_details.reasoning_tokens`; khi budget output quá nhỏ, `content` rỗng với `finish_reason=length`.
- Với `--max-output-tokens 2048`, probe ảnh bị `blocked` (`provider_schema:go_image:Output không phải JSON hợp lệ`) vì reasoning ăn hết budget; text/JSON/usage/cache/session vẫn verified. Với `--max-output-tokens 4096`, cả 6 capability Go đều `verified` (marker ảnh trả `{"squares": 3}`).
- Khuyến nghị: live Go image verification và mọi arm vision (RQ1) dùng budget output **>= 4096**; budget được ghi trong request view của receipt để truy vết.
- Quan sát thêm: route Go chấp nhận `response_format={"type":"json_object"}` (HTTP 200, JSON đúng) — cơ sở để P14/P29 cân nhắc bật structured-output flag sau conformance bổ sung; mặc định adapter vẫn là structured prompt + strict parse.
- `prompt_tokens_details.cached_tokens` hiện diện (giá trị 0) → cache semantics verified; `reasoning_tokens` chưa vào contracts `Usage` (P22 sẽ quyết định field/ledger riêng).

### Finding live 2026-10-12 (refresh, master)

- Zen `jev-1.13-free`: `verified` cho text/structured/usage như các lần trước (cache/image/session `unsupported` đúng thiết kế); receipt hết hạn 2026-10-19.
- Go `deepseek-v4.1-flash`: 5/6 capability `verified` (text/structured/usage/cache/session); image tiếp tục `blocked` với reason `image_marker_mismatch:0` ở cả budget 4096 lẫn 8192 — request hợp lệ nhưng model trả `{"squares": 0}` thay vì 3, khác reason lần 10-11 (`provider_schema:go_image:Output không phải JSON hợp lệ`).
- Tool và adapter không đổi từ `b1c5d09`; vì 8192 cũng fail nên nguyên nhân không chỉ là margin budget — image Go hiện không ổn định.
- Quyết định: giữ gate ảnh đóng (fail closed) và RQ1 vision-first blocked, không đổi model/route. Cần điều tra phía provider hoặc bổ sung probe/retry ổn định rồi chạy lại conformance trước khi mở vision.

## 4. Receipts và registry

- Receipt JSON nằm trong `artifacts/model-capabilities/` (Git bỏ qua), tên `<route>-<receipt_id>.json`.
- Schema `capability-receipt/1`: route, model_requested/model_resolved, adapter_schema_version, request_digest/result_digest (sha256 của payload sanitize), capabilities theo kind (`text`, `image`, `structured_output`, `usage`, `cache`, `session`), `version_identity`, `route_epoch` (theo ngày), `verified_at`, `expires_at` (mặc định 7 ngày), `blocked_reason`.
- Parser fail closed: schema version lạ, digest sai định dạng, status blocked/unsupported thiếu reason, hoặc document chứa trường bí mật đều bị từ chối.
- Gate tính năng ảnh (hybrid/vision arm) chỉ mở khi receipt còn hạn và `image = verified`; hết hạn hoặc thiếu receipt → `blocked`, không tự dùng route khác.
- Registry hiện là file-backed trong `platform/models/capabilities.py` kèm hàm migrate receipt theo `schema_version`; khi API/UI cần truy vấn tập trung sẽ chuyển sang bảng DB ở gói vận hành (P24/P26) mà không đổi schema receipt.

## 5. Kiểm tra và giới hạn

- Offline: `uv run --locked pytest -q tests/models/test_capability_receipts.py` phủ parser/invalid/expired, budget, key thiếu, auth lỗi, marker mismatch, sanitization, và chạy `--live` pipeline bằng `httpx.MockTransport` (không egress).
- CI/pytest thường không chạy `--live` và không đọc `.env`.
- Receipts live 2026-10-10 (master, budgets trong receipt): Zen `verified`; Go `verified` đầy đủ 6 capability ở budget 4096; receipt Go ở budget 2048 giữ trạng thái `blocked` cho image như bằng chứng finding budget. Refresh 2026-10-12: Zen `verified`; Go `image=blocked` ở cả budget 4096 và 8192 (`image_marker_mismatch:0`); receipts mới hết hạn 2026-10-19. Receipt nằm trong `artifacts/model-capabilities/` (Git bỏ qua); không chứa key.
