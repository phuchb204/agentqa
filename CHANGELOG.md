# Changelog

Mọi thay đổi đáng chú ý của AgentQA được ghi tại đây.
Định dạng theo [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); phiên bản theo [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.1.0] - 2026-09-25

### Added

- Contracts v1 đóng băng (`ObservationSnapshot`, `Action`, `StepResult`, `AssertionSpec/Result`, `MutationSpec`, `RunTrace`, `TestCase`) làm hợp đồng giữa các module.
- LLM adapter OpenAI-compatible hỗ trợ chế độ `chat` và `responses` (kèm header OpenCode Go) và `FakeLLM` cho test.
- Jev client gọi OpenRouter Decisions API; policy cascade `JevCascadePolicy` chọn action đóng bằng Jev, sinh text bằng LLM, escalate fail-closed khi thiếu tự tin hoặc lỗi.
- Agent loop `observe → decide → execute → verify` với observation ngân sách 8 KB/bước và executor Playwright async.
- Assertion checker (`text_visible`, `url_contains`) chạy độc lập sau khi agent kết thúc.
- Trace JSON store tại `experiments/runs/<run_id>/trace.json` gồm bước, assertion, token, thời gian và phiên bản app/model/prompt.
- CLI `agentqa run`, demo-site tĩnh (đăng nhập + danh sách việc) và generator biến thể UI `id-change`.
- CI GitHub Actions: ruff, ruff format, import-linter, pytest — không gọi API thật.
