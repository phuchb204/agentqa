# Dependency inventory

- Ngày: 2026-10-09
- Trạng thái: Inventory của gói 01 (P01–P03) và gói 02 (P04–P06); version chính xác pin trong `uv.lock` và `pnpm-lock.yaml`
- Nguồn quyết định: [architecture.md](architecture.md) §3, [rebuild-plan.md](plans/rebuild-plan.md) §5/§8, [01-foundation.md](plans/01-foundation.md), [02-data-and-trust.md](plans/02-data-and-trust.md)

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

## 5. Web — dev quality

| Package | Version | Lý do |
|---|---|---|
| vitest | 3.2.7 | Test frontend ở run mode, không watch (P01.2) |
| eslint, @eslint/js, typescript-eslint, globals | 9.39.5 / 9.39.5 / 8.71.1 / 16.5.0 | ESLint flat config |
| eslint-plugin-react-hooks, eslint-plugin-react-refresh | 5.2.0 / 0.4.26 | Rule React cho shell |
| prettier | 3.9.9 | Format check frontend |
| @types/react, @types/react-dom, @types/node | 19.3.0 / 19.3.0 / 24.19.1 | Type definitions |

## 6. Ghi chú

- Không thêm SDK/router provider; hai route OpenCode Go/Zen dùng HTTPX với adapter native (P12).
- Version trong bảng là bản resolve tại thời điểm gói 01; lockfile là nguồn pin chính xác.
- Không có dependency nào đọc `.env` hoặc tự gọi provider trong test/CI.
