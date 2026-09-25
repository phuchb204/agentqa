# Chuẩn hoá repo AgentQA — tài liệu, quy trình, git baseline

- **Ngày:** 2026-09-25
- **Trạng thái:** Chờ duyệt
- **Phạm vi ảnh hưởng:** toàn repo (`docs/`, `.github/`, `AGENTS.md`, `README.md`, `.gitignore`, `pyproject.toml`, cấu hình git/GitHub). Không đụng logic `src/`, `tests/`, `apps/`, `experiments/cases/`, `infra/` và không sửa nội dung `docs/reports/`.
- **Liên quan:** rà soát toàn repo ngày 2026-09-25 (báo cáo trong hội thoại), `docs/reports/WORK/00_NGU_CANH.md` (nguồn thông tin).

## 1. Bối cảnh

- Repo hiện tổ chức theo lối đồ án chia việc trên lớp: nhãn nhóm công việc gắn tên thành viên, nhật ký tuần, spec tổ chức công việc, plan phân task theo người, milestone theo tuần, label theo thành viên, branch prefix theo nhóm, CODEOWNERS chỉ owner.
- Lịch sử commit/PR lẫn các artifact đó; còn 3 branch remote cũ và tag `v0.1-skeleton`.
- `docs/reports/` là gói báo cáo đồ án — giữ nguyên nội dung, chỉ dùng làm nguồn thông tin.
- Kết quả rà soát 2026-09-25: 80 test pass, import-linter 4 contract kept, `ruff check .` đỏ 5 lỗi do `docs/reports/WORK/export_docx.py`; docs lệch trạng thái (spec Jev ghi "Chờ duyệt" trong khi đã merge; ADR 0001 ghi chưa wire Jev trong khi đã wire).

## 2. Mục tiêu

1. Repo baseline sạch: đúng 1 commit, không còn dấu vết chia việc kiểu lớp học.
2. Bộ tài liệu chuẩn kỹ thuật, có index và quy ước viết rõ ràng.
3. Quy trình làm việc viết một chỗ (branch/commit/PR/review/CI) và thực thi được.
4. CI bắt đủ gate hiện có, thêm gate format; GitHub repo public có bảo vệ `main`.
5. Không mất thông tin quyết định kỹ thuật (ADR Jev, spec cascade được viết lại).
6. Không sửa logic code, không đụng `docs/reports/`.

## 3. Ngoài phạm vi

- Không đổi `contracts/` v1, không refactor code (ngoại lệ duy nhất: `ruff format` một lần).
- Không sửa nội dung `docs/reports/`.
- Không thêm tính năng mới (hybrid observation, vision-first, self-healing, mutation generator thuộc roadmap).
- Không đổi dependency của `pyproject.toml`.

## 4. Quyết định

### 4.1 Git & GitHub

- **Backup trước khi xoá lịch sử:** `git bundle` + zip toàn bộ repo ra thư mục ngoài repo; xác minh bundle bằng `git bundle verify`.
- **Tái tạo tại chỗ:** xoá `.git`, `git init -b main`, đúng 1 commit baseline `chore: initial public baseline`.
- **Remote mới:** `phuchb204/agentqa`, public (điều kiện để bật branch protection ở gói GitHub Free), giấy phép MIT.
- **Tag:** `v0.1.0` trên commit baseline; `CHANGELOG.md` bắt đầu từ mục này.
- **Bảo vệ `main`:** bắt buộc PR, bắt buộc status check `test`, 1 approval bất kỳ collaborator, cấm force-push, cấm xoá; owner giữ quyền admin-bypass.
- **Collaborators:** mời lại `ZDS2004` và `daungocnghia` với quyền write.
- **Không tạo lại:** label/milestone theo thành viên hay theo tuần, CODEOWNERS.

### 4.2 Cấu trúc repo sau baseline

```
AgentQA/
├─ README.md                      # giới thiệu, quickstart, cấu hình, testing, cấu trúc, license
├─ LICENSE                        # MIT
├─ CONTRIBUTING.md                # quy trình làm việc: branch/commit/PR/review/CI/docs rule
├─ CHANGELOG.md                   # Keep a Changelog; mục [0.1.0] - 2026-09-25
├─ AGENTS.md                      # nội quy AI coding assistant
├─ CLAUDE.md                      # @AGENTS.md
├─ pyproject.toml · uv.lock · .env.example · .gitignore · .gitattributes
├─ .github/
│  ├─ workflows/ci.yml
│  ├─ pull_request_template.md
│  └─ ISSUE_TEMPLATE/bug.md · feature.md
├─ docs/
│  ├─ README.md                   # index tài liệu + chuẩn viết
│  ├─ architecture.md             # kiến trúc, module, data flow, luật import
│  ├─ roadmap.md                  # mốc theo phiên bản, không chia theo tuần
│  ├─ adr/template.md
│  ├─ adr/0001-jev-openrouter-decision-layer.md
│  ├─ specs/2026-09-25-jev-cascade-policy-design.md
│  ├─ specs/2026-09-25-repo-standardization-design.md   # spec này
│  ├─ plans/TEMPLATE.md
│  ├─ runbooks/dev-setup.md
│  └─ reports/                    # git-ignored, giữ local, không sửa
├─ src/agentqa/{contracts,llm,agent,verify,platform} · cli.py
├─ tests/
├─ apps/demo-site/
├─ experiments/cases/
└─ infra/docker-compose.yml
```

Vai trò từng tài liệu:

| File | Vai trò | Vòng đời |
|---|---|---|
| `docs/README.md` | Index + chuẩn viết docs | Cập nhật khi cấu trúc đổi |
| `docs/architecture.md` | Bản handoff kiến trúc hệ thống | Cập nhật khi kiến trúc đổi |
| `docs/roadmap.md` | Mốc phiên bản và trạng thái | Cập nhật khi mốc đổi trạng thái |
| `docs/adr/` | Quyết định kiến trúc, đánh số | Bất biến; thay thế thì tạo ADR mới |
| `docs/specs/` | Thiết kế feature | Bất biến sau khi duyệt |
| `docs/plans/` | Kế hoạch triển khai feature đang làm | Xoá khi merge xong; giữ `TEMPLATE.md` |
| `docs/runbooks/` | Hướng dẫn vận hành (setup, tái lập) | Cập nhật khi quy trình đổi |
| `CONTRIBUTING.md` | Chuẩn đóng góp | Cập nhật khi quy trình đổi |
| `CHANGELOG.md` | Lịch sử phát hành | Cập nhật mỗi release |

### 4.3 Chuẩn viết tài liệu

- Ngôn ngữ: docs tiếng Việt; code, commit, branch, tên file tiếng Anh.
- Đặt tên: `adr/NNNN-<slug>.md`, `specs|plans/YYYY-MM-DD-<slug>.md`.
- Đầu file ghi Ngày + Trạng thái (+ Phạm vi ảnh hưởng với ADR/spec).
- Docs tả dự án, không phải nhật ký cá nhân; không ghi phân công thành viên trong repo.
- **Docs cùng PR:** PR đổi hành vi, kiến trúc hoặc quy trình phải cập nhật tài liệu tương ứng trong cùng PR.
- **Contracts frozen:** sửa `src/agentqa/contracts/` phải kèm ADR, ghi rõ module bị ảnh hưởng và bump version.

### 4.4 Quy trình làm việc (viết tại `CONTRIBUTING.md`)

- Branch: `feat/<slug>`, `fix/<slug>`, `chore/<slug>`, `docs/<slug>`; sống ngắn, rebase `main` thường xuyên.
- Commit: Conventional Commits, scope ∈ {contracts, llm, agent, verify, platform, cli, demo-site, ci, docs}.
- PR: 1 mục đích/PR, mô tả What/Why/How verified, squash merge, cần ≥1 approval + CI xanh; không push thẳng `main`.
- Không merge code không hiểu; code do AI sinh phải kèm test.
- Cấm gọi LLM/Jev API thật trong test/CI — dùng `FakeLLM`/stub.
- Issue: template `bug`/`feature`; label dùng mặc định (bug, enhancement, documentation).

### 4.5 CI (`.github/workflows/ci.yml`)

Các bước theo thứ tự:

1. `uv sync --locked`
2. `uv run ruff check .`
3. `uv run ruff format --check .`
4. `uv run lint-imports`
5. `uv run playwright install --with-deps chromium`
6. `uv run pytest -q`

Chuẩn bị cho gate format: chạy `uv run ruff format .` một lần (8 file code/test cần định dạng lại; thay đổi thuần định dạng, không đổi hành vi). `pyproject.toml` thêm `extend-exclude = ["docs"]` cho ruff: docs chứa snippet minh hoạ, không phải code chạy, và ruff format có thể viết lại code block trong Markdown ngoài ý muốn.

### 4.6 `.gitignore`

- Thêm: `docs/reports/`, `.import_linter_cache/`, `.playwright-mcp/`.
- Bỏ: `.superpowers/` (đã xoá khỏi máy).
- Giữ: `.env`, `experiments/runs/`, `apps/demo-site/variants/*`, cache Python/ruff/pytest.

## 5. Danh sách file cụ thể

**Tạo mới:** `LICENSE`, `CONTRIBUTING.md`, `CHANGELOG.md`, `docs/README.md`, `docs/architecture.md`, `docs/roadmap.md`, `docs/adr/template.md`, `docs/plans/TEMPLATE.md`, `docs/specs/2026-09-25-repo-standardization-design.md`, `.github/ISSUE_TEMPLATE/feature.md`.

**Viết lại:** `README.md`, `AGENTS.md`, `docs/adr/0001-jev-openrouter-decision-layer.md`, `docs/specs/2026-09-25-jev-cascade-policy-design.md`, `docs/runbooks/dev-setup.md`, `.github/pull_request_template.md`, `.github/ISSUE_TEMPLATE/bug.md`, `.gitignore`, `pyproject.toml` (chỉ thêm extend-exclude), `.github/workflows/ci.yml` (thêm format gate).

**Xoá:** `docs/specs/2026-09-17-agentqa-workstream-design.md`, `docs/plans/2026-09-17-agentqa-walking-skeleton.md`, `docs/plans/2026-09-25-jev-cascade-policy.md`, `docs/adr/0002-docs-structure-and-update-standard.md`, `docs/runbooks/team-workflow.md`, `CODEOWNERS`, `.github/ISSUE_TEMPLATE/task.md`, `.import_linter_cache/`, `docs/reports/` (khỏi git, giữ local), thư mục `docs/weekly/` (đã xoá, không tạo lại), `docs/superpowers/` (đã rename, không tạo lại).

**Giữ nguyên:** `src/`, `tests/`, `apps/demo-site/`, `experiments/cases/`, `infra/docker-compose.yml`, `uv.lock`, `.env.example`, `.gitattributes`, `CLAUDE.md`.

**Dọn ngoài repo:** xoá 3 branch remote cũ cùng repo cũ, xoá tag `v0.1-skeleton`, không tái tạo labels/milestones theo nhóm công việc.

## 6. Runbook thực thi

0. **Backup:** `git bundle create D:\WORK\_agentqa-backup\agentqa-20260925.bundle --all` + zip toàn bộ workspace; `git bundle verify`.
1. **Viết spec này** (đang làm) và chờ duyệt.
2. **Dọn & viết docs:** xoá file theo §5; tạo/viết lại docs; cập nhật `.gitignore`, `pyproject.toml`, CI, templates.
3. **Gate local:** `uv run ruff format .`; `uv run ruff check .`; `uv run ruff format --check .`; `uv run lint-imports`; `uv run pytest -q` → tất cả xanh (80 test).
4. **Reinit git:** xoá `.git`; `git init -b main`; `git add -A`; 1 commit `chore: initial public baseline`.
5. **GitHub:** xoá repo cũ sau khi backup xác minh; `gh repo create agentqa --public --source . --push`; `git tag v0.1.0; git push origin v0.1.0`.
6. **Cấu hình:** bật protection (`test` required, PR + 1 approval, no force-push/delete); mời lại collaborators; tạo label `documentation` nếu thiếu (labels mặc định của GitHub đã đủ).
7. **Verify:** CI xanh trên `main`; `git log --oneline` đúng 1 commit; README link nội bộ không chết; `docs/reports/` còn nguyên local và không xuất hiện trong `git status`.

## 7. Rủi ro & rollback

| Rủi ro | Xử lý |
|---|---|
| Mất lịch sử commit/PR cũ | Backup bundle + zip ngoài repo, verify trước khi xoá; rollback bằng `git clone <bundle>` |
| Lộ key khi push repo mới | Quét `git grep` các mẫu key trước khi push; `.env` nằm trong `.gitignore`; kiểm tra `git status` không có `.env` |
| Branch protection chỉ hiệu lực ở repo public | Đã chọn public từ đầu |
| `ruff format` làm diff lớn | Chấp nhận, thuần định dạng; test xanh xác nhận không đổi hành vi |
| Xoá nhầm file còn cần | Danh sách §5 chốt trước; mọi thứ vẫn nằm trong backup bundle |
| Tên repo trùng khi tạo mới | Xoá/ngừng dùng repo cũ trước khi `gh repo create agentqa`; nếu cần giữ tạm thì đổi tên repo cũ |

## 8. Definition of Done

1. `git log --oneline` đúng 1 commit; cây repo khớp §4.2.
2. `uv run pytest -q` → 80 passed; `ruff check`, `ruff format --check`, `lint-imports` đều xanh.
3. Không còn dấu vết chia việc kiểu lớp học trong tài liệu vận hành (`README.md`, `CONTRIBUTING.md`, `AGENTS.md`, `docs/architecture.md`, `docs/roadmap.md`, `docs/runbooks/`, `.github/`) — ngoại lệ: spec này (bản ghi việc dọn dẹp, có liệt kê file cũ) và `docs/reports/` bị ignore.
4. Repo GitHub mới public, protection bật, CI xanh trên `main`, tag `v0.1.0`, collaborators đã mời.
5. `docs/reports/` còn nguyên trên máy và không nằm trong git.
6. Spec này đã duyệt và nằm trong commit baseline.
