# Gói 01 — Nền dự án và Contracts

- Ngày: 2026-10-06
- Trạng thái: Chưa triển khai
- Plan: [rebuild-plan](rebuild-plan.md)
- Nguồn: [Architecture](../architecture.md), [Contracts/DSL](../design/contracts-and-dsl.md)
- Gate: G0; nguồn truy vết NFR-10, NFR-12

## P01 — Runtime, workspace và bộ kiểm tra

**Depends on:** Không có.

**Files cần tạo:** `pyproject.toml`, `uv.lock`, `.python-version`, `package.json`, `pnpm-workspace.yaml`, `pnpm-lock.yaml`, `apps/web/package.json`, `apps/web/tsconfig.json`, `apps/web/vite.config.ts`, cấu hình ESLint/Prettier/Vitest, `.github/workflows/ci.yml`, `tests/conftest.py`, `tests/foundation/test_runtime_guard.py`, `tools/check_plan_coverage.py`, các package `__init__.py` của năm lớp. **Cập nhật:** `.gitignore`, `README.md`, `AGENTS.md` theo commands thực đã tạo.

1. Khai báo Python 3.13/uv, Node 24/pnpm, build backend và dependency groups có inventory/lý do; tạo package layout theo thiết kế. CLI nền dùng argparse để `--version`/help, chưa giả các commands sản phẩm đã chạy.
2. Tạo frontend workspace/scripts đúng master plan, root packageManager pin pnpm và shared lockfile ở root; frontend mới chỉ shell/build pipeline, không placeholder báo feature done. Chọn versions tương thích và ghi locks; không sao chép pyproject/uv.lock cũ.
3. Cấu hình ruff/import-linter và compiler/lint/format/test scripts; kiểm tra Contracts leaf, Models→Contracts, Agent→Contracts/Models, Verify→Contracts, Platform composition. Test network guard deny Go/Zen và strip real provider variables, chỉ cho declared local fixture endpoints.
4. Tạo checker spec/design/plan IDs và CLI errors chuẩn; CI thường không có model keys/conformance. Exclude generated runtime artifacts/caches/auth state/private oracle, giữ `.env.example` blank keys.

**Verify sau khi tạo:** `uv lock`, `uv sync --locked`; `uv run --locked pytest -q tests/foundation`; các lint/format/import gates; `pnpm --dir apps/web install` để tạo lock lần đầu, rồi `install --frozen-lockfile`, `typecheck`, `test`, `build`; `uv run --locked python tools/check_plan_coverage.py`.

**Done:** Runtime/locks dùng được, gate failure thực sự fail CI, network guard ngăn model requests kể cả khi máy có `.env`. Không cần test chỉ khẳng định package __version__ bằng chính hằng vừa khai báo. Chưa gọi model thật, chưa có feature engine được nghiệm thu.

## P02 — Contracts, canonical content và DSL compiler

**Depends on:** P01.

**Files:** `src/agentqa/contracts/{case.py,values.py,identity.py,observation.py,actions.py,verification.py,runs.py,events.py,models.py,artifacts.py,ports.py,errors.py,canonical.py,compiler.py}`; `tests/contracts/test_{canonical,case_compiler,ports,sensitive_values,compatibility}.py`; `tests/fixtures/contracts/` với vectors độc lập.

1. Implement typed models/union/enums/ports theo thiết kế, UUID scope, UTC/monotonic semantics, Decimal money, finite/safe JSON. SensitiveValue không có serialization path hoặc repr chứa value; Protocol không lộ Playwright/ORM/FastAPI types.
2. Canonicalize bằng thư viện RFC 8785 đã chọn và vectors; content digest loại lifecycle/DB IDs/secret values, tuple/frozen mapping chống nested mutation. Phân biệt digest case/snapshot/artifact và không đổi khi archive/import-remap IDs.
3. DSL safe parser/validator: duplicate keys, tags/alias expansion, source/postcondition/capture refs, unique IDs, type/taint, branch/loop bounds, completion/applicability và capability extraction. Không eval code hoặc secret interpolation vào URL/log/assertion.
4. Chốt error fields/schema version/upcasting contract; add fixtures cho malicious import, empty assertion, inferred chưa confirmed, incomplete branch proof và unsafe captures.

**Verify:** `uv run --locked pytest -q tests/contracts`; lint/import gates. RFC vectors lấy expected bytes/digests độc lập; chạy round trip và nested mutation attempts, không chỉ snapshot output hiện tại của implementation.

**Done:** Content portable và ready immutable có proof, unsupported nodes bị từ chối, APIs có field-path errors an toàn. Backend schema là nguồn chung cho web, không còn field đang được dựa vào contracts v1 cũ.

## P03 — Schema/OpenAPI và typed client

**Depends on:** P02.

**Files:** `src/agentqa/platform/api/{schemas.py,error_models.py,application.py}`, `tools/export_schemas.py`, `apps/web/scripts/generate-client.ts`, `apps/web/src/generated/`, `schemas/`, `tests/contracts/test_schema_parity.py`, `apps/web/src/contracts/schema-parity.test.ts`.

1. Sinh JSON Schema DSL/events và OpenAPI 3.1 từ request/response models; chỉ expose public contracts, không ports/sensitive grants/oracle content. Create schema catalog versioned và release digests.
2. Generate TypeScript với openapi-typescript/openapi-fetch, Ajv runtime validators; AST printer remove generated comments/trivia thay vì regex cắt source. Backend validation vẫn authoritative.
3. Add `--check` deterministic generation; shared invalid/valid vectors cho Python/Ajv, enum discriminators, optional/null/Decimal và source aliases. Unknown schema/action versions phải reject.
4. Tích hợp schema drift check vào CI và client build; future routes dùng cùng error/request/response contracts, không tạo typed client bypass.

**Verify:** `uv run --locked python tools/export_schemas.py --check`; `uv run --locked pytest -q tests/contracts/test_schema_parity.py`; `pnpm --dir apps/web typecheck`; `pnpm --dir apps/web test` với schema fixtures.

**Done:** Python/TS accept/reject cùng vectors, generation không stale, không có key/oracle/sensitive type public. Commands generate/check phân biệt rõ write và read-only check.
