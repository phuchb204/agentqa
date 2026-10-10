# Dependency inventory

- Ngày: 2026-10-10
- Trạng thái: Inventory của gói 01 (P01–P03), gói 02 (P04–P06), gói 03 (P07–P11), gói 04 (P12–P15) và gói 05 (P16–P19); version chính xác pin trong `uv.lock` và `pnpm-lock.yaml`
- Cập nhật gói 03: playwright/uvicorn/python-multipart (P07); pillow (P08)
- Cập nhật gói 04: không thêm dependency; hai adapters Go/Zen dùng httpx, marker ảnh conformance dùng pillow, fakes/tests không cần SDK provider
- Cập nhật gói 05: pypdf và python-docx cho extraction subprocess (P16); P17 không thêm dependency (authoring/exploration dùng model port + fakes hiện có); P18 thêm web packages TanStack Router/Query, Radix primitives, Monaco, yaml cùng dev packages jsdom/testing-library cho Vitest jsdom; P19 thêm websockets cho uvicorn WebSocket browser-stream
- Nguồn quyết định: [architecture.md](architecture.md) §3, [rebuild-plan.md](plans/rebuild-plan.md) §5/§8, [01-foundation.md](plans/01-foundation.md), [02-data-and-trust.md](plans/02-data-and-trust.md), [04-models-and-observation.md](plans/04-models-and-observation.md), [05-authoring-and-web.md](plans/05-authoring-and-web.md)

## 1. Toolchain

| Thành phần | Version khai báo | Version pin thực tế | Lý do |
|---|---|---|---|
| Python | 3.13 (`requires-python >=3.13,<3.14`, `.python-version`) | 3.13.12 do uv quản lý | Runtime async/data theo architecture §3 |
| uv | — | 0.10.7 | Quản lý venv và lockfile tái lập (`uv sync --locked`) |
| Node.js | `engines >=24 <25` trong `package.json`/`apps/web/package.json`; CI `node-version: 24` | CI Node 24; receipt local chạy Node 22.22.0 và được ghi rõ khác biệt | Frontend theo architecture §3; máy dev hiện tại chưa có Node 24 |
| pnpm | `packageManager: pnpm@10.34.6`, workspace tại root | 10.34.6 | Một shared lockfile tại root |

## 2. Python — runtime

| Package | Version | Lý do |
|---|---|---|
| fastapi | 0.143.0 | API typed + sinh OpenAPI 3.1 từ Contracts (architecture §3, P03) |
| httpx | 0.28.1 | HTTP client async; dùng cho provider transport (P12) và test app API (P03) |
| pydantic | 2.14.0 | Validation models và JSON Schema 2020-12 cho Contracts (architecture §3, P02) |
| pyyaml | 6.0.3 | Safe parser cho Case DSL (rebuild-plan §8, P02) |
| rfc8785 | 0.1.4 | Canonical JSON RFC 8785 đã chọn (rebuild-plan §8, P02) |
| sqlalchemy | 2.1.4 | ORM/Core async cho PostgreSQL, transaction và truy vấn typed (architecture §3, P04) |
| psycopg | 3.3.6 | Driver PostgreSQL 3 async (psycopg[binary]) cho SQLAlchemy (architecture §3, P04) |
| alembic | 1.20.0 | Migration runner lock/version; migration 0001 schema core, 0002 query indexes (P04, P06) |
| pwdlib | 0.3.1 | Argon2id password hashing qua thư viện maintained (api-and-security §5, P05) |
| cryptography | 46.0.7 | AES-256-GCM envelope credential: data key/nonce/AAD, master key ngoài DB (api-and-security §6, P05) |
| playwright | 1.63.0 | Browser thật cho Taskboard fixture và adapter async read/action (P07–P08) |
| uvicorn | 0.54.0 | HTTP server chạy Taskboard fixture và API runtime (P07, P11) |
| python-multipart | 0.0.32 | FastAPI form parsing cho Taskboard login/CRUD (P07) và upload source multipart (P16) |
| websockets | 15.0.1 | Protocol cho uvicorn phục vụ WebSocket browser-stream đã mask (P19) |
| pillow | 12.3.0 | Mask ảnh và image canary pixel-based cho SafeEvidenceService (P08) |
| pypdf | 6.20.0 | Đọc PDF page text và phát hiện file mã hoá trong extraction subprocess (P16) |
| python-docx | 1.2.0 | Đọc DOCX heading/paragraph/table-cell text trong extraction subprocess (P16) |
| lxml | 6.1.3 | Dependency của python-docx cho XML parsing an toàn trong subprocess (P16) |

## 3. Python — dev

| Package | Version | Lý do |
|---|---|---|
| pytest | 8.4.2 | Chạy test offline; không gọi model thật (NFR-12) |
| pytest-asyncio | 1.4.0 | Async tests cho database/security/platform (P04–P06) |
| ruff | 0.16.10 | Lint + format gate (P01.3) |
| import-linter | 2.15 | Cưỡng chế luật import năm lớp (P01.3, NFR-10) |
| jsonschema | 4.26.0 | Xác thực generated JSON Schema trong parity tests (P03.3) |

## 4. Web — runtime/build

| Package | Version | Lý do |
|---|---|---|
| react, react-dom | 19.3.0 | SPA shell theo architecture §3 (P01.2) |
| vite | 7.3.7 | Build pipeline frontend (P01.2) |
| @vitejs/plugin-react | 5.2.0 | JSX transform cho Vite |
| typescript | 5.8.3 | Typecheck và generated client (P03.2) |
| openapi-typescript | 7.13.0 | Sinh TypeScript types từ OpenAPI (P03.2) |
| openapi-fetch | 0.14.1 | Typed fetch client dùng generated paths (P03.2) |
| ajv | 8.20.0 | Runtime validators cho DSL/event schema phía client (P03.2) |
| tsx | 4.23.15 | Chạy AST printer TypeScript trong `scripts/generate-client.ts` (P03.2) |
| @tanstack/react-router | 1.170.x | URL/search params và route tree cho workspace/editor (P18) |
| @tanstack/react-query | 5.104.x | Server state, cache và invalidation cho UI (P18) |
| @radix-ui/react-{dialog,tabs,dropdown-menu,tooltip} | 1.x–2.x | Primitives accessible cho dialog/tab/menu/focus (P18) |
| monaco-editor | 0.57.0 | YAML editor trong case editor; fallback textarea khi chạy Vitest (P18) |
| yaml | 2.9.1 | Parse/serialize YAML phía client trước khi gửi JSON validated (P18) |

## 5. Web — dev quality

| Package | Version | Lý do |
|---|---|---|
| vitest | 3.2.7 | Test frontend ở run mode, không watch (P01.2) |
| eslint, @eslint/js, typescript-eslint, globals | 9.39.5 / 9.39.5 / 8.71.1 / 16.5.0 | ESLint flat config |
| eslint-plugin-react-hooks, eslint-plugin-react-refresh | 5.2.0 / 0.4.26 | Rule React cho shell |
| prettier | 3.9.9 | Format check frontend |
| @types/react, @types/react-dom, @types/node | 19.3.0 / 19.3.0 / 24.19.1 | Type definitions |
| jsdom | 30.1.x | DOM environment cho Vitest component tests (P18) |
| @testing-library/react, @testing-library/user-event | 16.3.x / 14.6.x | Render và tương tác component trong Vitest (P18) |

## 6. Ghi chú

- Không thêm SDK/router provider; hai route OpenCode Go/Zen dùng HTTPX với adapter native (P12).
- Version trong bảng là bản resolve tại thời điểm gói 01; lockfile là nguồn pin chính xác.
- Không có dependency nào đọc `.env` hoặc tự gọi provider trong test/CI.
