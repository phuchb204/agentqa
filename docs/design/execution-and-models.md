# Engine, browser, quan sát và model

- Ngày: 2026-10-06
- Trạng thái: Thiết kế đề xuất, chưa kiểm tra live API
- Phạm vi: Models, Agent và composition runtime của Platform
- Liên quan: [Contracts/DSL](contracts-and-dsl.md), [guard/Verify](verification-and-healing.md), [queue](platform-and-storage.md)

## 1. Thành phần

| Thành phần | Lớp | Trách nhiệm |
|---|---|---|
| `RunCoordinator` | Platform | Snapshot, fixtures, controls, lease/budgets, gọi Agent và Verify theo checkpoint, finalization |
| `CaseCompiler` | Contracts/Platform | Validation thuần trong Contracts; resolve revision/environment và compile receipt trong Platform |
| `AgentRunner` | Agent | Mục tiêu/planning, state/history, action proposal và completion proposal |
| `ReplayRunner` | Agent | Diễn giải DSL, branch/loop/capture và step instance; không thay nội dung revision |
| `ObservationService` | Agent | Semantic/image observations và input provenance |
| `IdentityResolver`, `TargetGuard`, `Healer` | Agent | Candidate/identity checks và recovery proposal |
| `ActionExecutor` | Agent | Validated command, postcondition read, side-effect outcome; không tính final verdict |
| `BrowserSupervisor` | Platform process | Session ownership/fence, command journal/admission và kill/close lifecycle |
| `PlaywrightSession` | Agent browser implementation | BrowserReadPort/ActionPort, context/page/frame, safe capture và allowed actions |
| `ZenSystemOneAdapter`, `GoChatAdapter`, `CommandCodeSystemOneAdapter`, `CommandCodeChatAdapter` | Models | Native HTTP wire theo registry `models/routes.py` (hai cặp opencode/commandcode), validation/normalization, request accounting |

Coordinator không truyền assertion editor hoặc oracle cho policy. Agent biết goal/approved expectations cần thực hiện nhưng không có quyền sửa chúng. Verify đọc cảnh/bằng chứng qua port hạn chế, không lấy quyết định đạt từ Agent.

## 2. State của execution

Runtime context chứa snapshot_digest, current node/iteration/page/frame, typed captures, redacted action history, budgets, control revision, current observation version và evidence cursors. Capture/parameter taint được giữ qua history và model input. State đã chốt có checkpoint receipt; mutable variables của runner không ghi đè ready content.

Mỗi lượt: kiểm tra lease/control → chọn bước → observe → resolve/guard → proposal/repair → journal prepared command → supervisor admission → dispatch → record outcome → evaluate postconditions/checkpoint → advance. Replay bỏ bước gọi model nếu target/condition đủ; vẫn observe/probe/guard.

Agent planning tạo các subgoal có liên kết requirement; kế hoạch là proposal có version và bounds. Agent có thể đổi đường thực hiện trong mode agent khi vẫn giữ mục tiêu/expectations và policy; replay chỉ theo DSL branch đã pin. Kế hoạch mới của agent không tự ghi thành revision ready.

## 3. Browser supervision và command journal

Supervisor là process riêng; worker không có raw browser/CDP endpoint và không tự gọi browser APIs qua kênh khác. Session xác định bằng workspace/run/attempt, control revision và fence epoch; control plane đăng ký ownership với supervisor. Mỗi session có hàng đợi command tuần tự; concurrent contexts có queue riêng.

| Command state | Quy tắc |
|---|---|
| `prepared` | Payload digest, budgets/identity proof và intent đã vào DB trước dispatch |
| `accepted` | Supervisor kiểm tra epoch/lease/control/observation còn hợp lệ và ghi admission receipt |
| `dispatched` | Đã giao Playwright; từ đây timeout/disconnect không chứng minh chưa có side effect |
| `settled` | Outcome và evidence receipts chốt; command ID duplicate trả cùng receipt |
| `unknown` | Không đủ bằng chứng xác định external effect; không tự dispatch lại |
| `rejected` | Chưa dispatch, có reason rõ; có thể chuẩn bị command mới nếu control cho phép |

Fencing không dừng được request đã tác động ở server mục tiêu. Khi mất lease, supervisor từ chối command mới và đóng/quarantine session; recovery không cấp issuer mới cho cùng attempt trước khi lệnh in-flight được settle hoặc session cũ được xác nhận đã đóng. Outcome unknown chỉ được tiếp tục bằng probe chứng minh outcome, hoặc tạo attempt mới sau fixture reset có receipt; otherwise run error/inconclusive theo evidence hiện có.

Nếu supervisor không truy được nguồn quyền/lease, không dispatch mới. Lệnh đã accepted nhưng chưa biết dispatched được reconciliation từ journal; không xem "worker chưa nhận reply" là safe retry. Các side effects có thể tiếp tục ở website sau khi browser đóng; fixture/application-specific oracle của outcome được khai báo cho scenario cần chạy lại.

Cancel API response 202 chỉ nhận yêu cầu. `control.cancel_effective` phát khi supervisor đã chặn command admission mới; đây mới là acknowledgement về semantics FR-38. Đang in-flight được chờ có bound và ghi unknown nếu cần. Pause effective sau boundary tương tự; UI phân biệt requested/effective. Resume observe lại và ghi external intervention; không dùng attempt đó làm lượt nghiên cứu sạch.

## 4. Read/action capabilities

`BrowserReadPort` chỉ có probe/observation/safe capture. `BrowserActionPort` nhận command đã admission; không lộ evaluate script tuỳ ý cho LLM hoặc Verify. Nội bộ browser adapter có script tĩnh, versioned để thu DOM/geometry; input chỉ là selectors typed đã validation. Action registry không eval model code.

Page/context/frame keys là stable logical keys trong case, mapping runtime handles trong supervisor. Target refs ràng buộc session, observation version và frame; stale refs phải resolve lại. Tab mở mới chỉ được bind khi origin và opener expectation khớp. Frame/shadow locator có capability proof; missing support là lỗi capability, không chọn frame khác để tiếp tục.

Upload dùng file ID từ artifact catalog, MIME/size đã kiểm tra. Download vào private scratch, kiểm tra content/name/hash trước khi publish safe artifact. Dialog có rule accept/dismiss và expected prompt; dialog ngoài rule dừng với evidence. Không click browser permission hoặc OS UI bằng cách mở quyền host.

Auth profile: login fixture hoặc storage-state credential version. Context nhận bản sao state; auth state encrypted/private, không thành artifact thường. Session storage có setup hook được khai báo và versioned khi cần; không giả định storage-state chứa mọi loại auth state.

## 5. Semantic observation

Thu nội dung hiển thị, role/accessible name, state enabled/checked/selected, vùng/form/row/entity và các tương tác có thể dùng. Không export value password/secret-tainted inputs, tokens trong URLs hoặc hidden metadata. Visibility/actionability khác DOM existence; semantic snapshot giữ provenance và khả năng quan sát của mỗi vùng.

Candidate IDs `c0..cN` chỉ có nghĩa trong observation_id/frame. ElementRef không ghi vào portable CaseContent. Định vị ưu tiên role/label và entity scope; `id`/CSS/test ID là signal bổ sung. Geometry/page text sau redaction có thể phục vụ grounding/identity, nhưng không bỏ missingness.

Budget dùng token estimate + byte/image budgets trong profile versioned, không cố định 8 KB. Chọn vùng theo subgoal và scope, bảo toàn target-critical data; snapshot có retained/dropped manifest. Candidate list bị cắt luôn có "none/need_more_context" và flag; có thể mở rộng observation vùng tương ứng trước quyết định. Không đoán rằng candidate cuối được giữ là đúng.

## 6. Hybrid và vision-first

Hybrid gửi semantic trước. Ảnh được yêu cầu khi target có visual identity/canvas, candidates sau guard không phân biệt được, hoặc structured model result báo cần hình. Trigger được ghi và handler kiểm tra budget/capability; không dùng số vòng stuck cố định từ code cũ. Mỗi observation/LLM call ghi modality thực đã gửi.

Vision-first gửi ảnh viewport đã masking và overlay marker chỉ gồm số/geometry. Marker map nằm trong executor, không gửi role/name/DOM text. Tọa độ tính từ ảnh viewport có scale/scroll/DPR metadata, được revalidate trước thao tác; biến đổi layout làm proof hết hạn. Visible text nằm trong ảnh là dữ liệu thị giác hợp lệ. Semantic labels không được rò qua history, rationale hoặc error messages của guard.

Vision-first input history gồm operation/marker, outcome code và images mới; error text không chép target DOM label. Checkpoint evidence không được dùng làm gợi ý target policy cho arm RQ1. Hybrid và vision-first dùng cùng supported action registry và LLM/model generation settings.

| Mode/policy | Modality được phép |
|---|---|
| Agent + `llm` | semantic, hybrid, vision_first |
| Agent + `jev_cascade` | semantic, hybrid; quyết định thị giác chuyển sang Go LLM |
| Replay strict | Read-only semantic/visual probes; không gọi policy action/healer |
| Replay healing + heuristic | Semantic identity; không gọi model |
| Replay healing + `llm`/cascade | Semantic/hybrid recovery theo profile |

`jev_cascade + vision_first` không được quảng bá là arm thuần thị giác: Jev chỉ nhận state văn bản. Cấu hình này bị validation từ chối. RQ1 mặc định LLM thuần, đúng spec.

## 7. Cascade cụ thể

Enumerator tạo tập hợp operation/target pairs hợp lệ theo candidates và action registry; một Choice chọn một pair, tránh ghép operation và target từ hai câu hỏi độc lập không nhất quán. Pair chứa ý định, scope, trạng thái và candidate ID; không chứa secret/value runtime cần gõ. Có sentinel `none/need_more_context`.

Có thể fan-out cùng request với các Noul độc lập: progress evidence đủ và trạng thái stuck. Question ID không thay cho instructions; instructions phải diễn đạt đủ câu hỏi. Câu hỏi phụ thuộc pair được chọn đặt ở bước sau hoặc xử lý trong code, không giả định câu trả lời Choice đi vào context của Noul khác.

Trình tự: dữ liệu/schema sai → escalation nếu được phép; progress có thể tạo stop proposal → Coordinator chạy completion/Verify; pair hợp lệ, confidence/p_max/margin qua calibrated profile → engine guard; cần fill value → lấy literal/parameter/capture trước, chỉ gọi value-generation khi ca cho phép và target data constraint rõ; thiếu bằng chứng/none/stuck → mở rộng quan sát hoặc gọi Go LLM. Value secret luôn resolve ngoài model.

Mọi nhánh LLM vẫn qua guard. Noul không có confidence riêng. Choice confidence không là P(correct target); ngưỡng theo question, candidate population và risk/action class, versioned/calibrated. Model không sinh tự do "lý do Jev"; rationale là summary từ state/question/answer và engine rule đã áp.

Với policy LLM live, parser chấp nhận JSON object nằm trong text (bỏ code fence, trích object hợp lệ đầu tiên) trước khi repair; runner khớp case node theo intent, sau đó theo tên/role của candidate, và theo locator value khớp tên candidate — nhờ đó fill secret vẫn resolve qua node value (`node_secret`) kể cả khi model đặt intent khác. Các fallback này không nới guard: secret không bao giờ đến từ proposal, và operation ngoài registry vẫn bị từ chối.

## 8. Hai HTTP adapters

| Adapter | Route | Request | Parse/normalization |
|---|---|---|---|
| `ZenSystemOneAdapter` | `opencode_zen` | POST `https://opencode.ai/zen/v1/systemone`; model `jev-1.13-free`, state, questions keyed ID | Parse System One `answers` theo question type, model/usage nếu có; kiểm tra expected IDs, lựa chọn thuộc criteria và finite values |
| `GoChatAdapter` | `opencode_go` | POST `https://opencode.ai/zen/go/v1/chat/completions`; model `deepseek-v4.1-flash`, messages và parameters được conformance cho phép | Parse choices/message structured content hoặc JSON một object; usage/cache/reasoning fields chỉ khi được xác minh |
| `CommandCodeSystemOneAdapter` | `commandcode_systemone` | POST `https://api.commandcode.ai/provider/v1/systemone`; model `typesafe/jev`, state, questions keyed ID | Cùng shape System One; không có session header; [Provider API](https://commandcode.ai/docs/provider), xác minh live 2026-10-19 |
| `CommandCodeChatAdapter` | `commandcode_chat` | POST `https://api.commandcode.ai/provider/v1/chat/completions`; model `deepseek/deepseek-v4.1-flash` | Cùng parse OpenAI chat; không gửi `x-opencode-session`; usage `prompt_tokens/completion_tokens` đã có trong parser chung |

Wire System One tham khảo [schema SDK chính thức](https://github.com/typesafe-ai/typesafe-sdk-python/blob/main/src/typesafe_sdk/_schemas/models.py). Gateway có thể thêm/khác fields; fixture từ live conformance của Zen xác nhận wire thực. Không lấy các convenience properties của SDK như `response.choices` làm JSON wire.

Headers gồm Authorization từ scoped grant, Content-Type JSON và User-Agent `AgentQA/<app_version>`. Go thêm `x-opencode-session` là conversation ID persisted; retry cùng conversation giữ ID. Model transport chỉ cho hai routes đã chọn, không follow redirect sang host khác hoặc fallback sang Zen paid chat/OpenRouter. [Zen](https://opencode.ai/docs/zen/), [Go](https://opencode.ai/docs/go/).

Ảnh Go dùng inline safe image bytes trong multimodal content; không dùng URL do model/trang chỉ định. JSON schema response_format/tool calling chỉ bật khi conformance chứng minh route hỗ trợ; baseline là structured prompt + strict parse + validation. Invalid result được repair bounded qua cùng Go route, mỗi repair có call ledger; không silently strip một phần text rồi thực thi.

HTTPX không có retries ngầm. Retry policy do Models control: auth/schema/config errors không blind retry; 429 theo Retry-After và provider budget; timeout/5xx có bounded backoff cho model inference, ledger giữ từng attempt và unknown charge. Retry inference không kéo theo retry browser action.

## 9. Capability và fake models

CapabilityReceipt có route/model_requested/model_resolved, schema adapter version, probe payload/result digests, verified_at, text/image/structured-output/usage semantics và expiry/deployment version. Receipt không chứa key, account balance hoặc raw prompt có bí mật. Route image không qua probe → chặn hybrid step cần ảnh/RQ1 vision arm; không dùng model thay thế.

Gateway chỉ trả model alias không đủ chứng minh cùng weights/snapshot tuyệt đối. Ghi `version_identity=unverified` và route epoch khi thiếu actual model version; manifest chỉ khẳng định pin requested route/model, ghi provider drift là confound. Không tự bịa snapshot version để cache hoặc nói thí nghiệm hoàn toàn tất định.

FakeGo/FakeJev trả typed outcomes và usage theo fixture, có lỗi timeout/quota/missing answer/bad probability để kiểm tra branches. Browser fixtures vẫn là trình duyệt thật trong integration; toàn bộ model I/O stub. Live conformance là CLI tooling riêng dùng synthetic state/image, đúng hai model, ghi call ledger/chi phí; không chạy trong pytest/CI thường.

## 10. Budgets, ledger và cache

Reserve call/step/concurrency trước dispatch, settle từ outcome sau đó. Pending reservation được recovery reconcile; timeout call giữ unknown usage/cost nếu chưa có receipt, không zero. Completion call, inference repair, value generation, image escalation và diagnostic có purpose riêng.

Decision cache key gồm workspace, purpose, route/requested+resolved model version, prompts/questions digest, safe state/image digests, calibration và generation settings. Response từ cache vẫn qua guard và ghi cache hit; không ghi thêm provider call giả. Khi resolved version không xác định, cache chỉ dùng trong cùng verified route epoch; không chia xuyên version chưa kiểm tra. Research có explicit bypass.

Action plan cache không phải browser outcome cache: mỗi replay vẫn kiểm tra trang và assertion thật. Không tái sử dụng captured IDs, secret grants hoặc action receipt của run trước. Diagnostic sau terminal là job độc lập liên kết run và ledger riêng.
