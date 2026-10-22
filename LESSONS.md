# LESSONS.md — AgentQA project notebook (agent mistakes log)

- 2026-10-22: Committed UI fix + family work on wrong branch (`feat/calibration-new-families` instead of `fix/ui-frame-flake`); had to untangle via reset. Rule: `git branch --show-current` before every commit.
- 2026-10-22: Used `grep/sed/head` and multi-path `ls` in PowerShell — not available. Rule: use `Select-String`, one path per `Get-ChildItem`, or the `grep` tool.
- 2026-10-22: Claimed PR #20 CI green from a stale check run; merge commit still failed. Rule: verify checks on the exact head SHA being merged, not "PR checks" in general.
- 2026-10-22: Set `bool` payload key (`degraded`) that bundle export whitelist dropped; probe showed `None`. Rule: check export/whitelist path end to end before relying on a new field.
