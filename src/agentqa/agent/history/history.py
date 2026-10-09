from __future__ import annotations

from dataclasses import dataclass, field

MAX_SUMMARY_ENTRIES = 12


@dataclass(frozen=True)
class HistoryEntry:
    step: int
    operation: str
    target_intent: str | None
    outcome: str
    reason: str | None = None
    scene_version: int = 1


@dataclass
class ActionHistory:
    run_snapshot_digest: str
    entries: list[HistoryEntry] = field(default_factory=list)

    def record(self, entry: HistoryEntry) -> None:
        self.entries.append(entry)

    @property
    def steps(self) -> int:
        return len(self.entries)

    def failure_count(self, *, operation: str, target_intent: str | None, reason: str | None) -> int:
        return sum(
            1
            for entry in self.entries
            if entry.operation == operation
            and entry.target_intent == target_intent
            and entry.outcome != "succeeded"
            and entry.reason == reason
        )

    def summary(self) -> list[dict[str, str | int | None]]:
        recent = self.entries[-MAX_SUMMARY_ENTRIES:]
        return [
            {
                "step": entry.step,
                "operation": entry.operation,
                "target": entry.target_intent,
                "outcome": entry.outcome,
                "reason": entry.reason,
            }
            for entry in recent
        ]

    def text_summary(self) -> str:
        lines = []
        for entry in self.entries[-MAX_SUMMARY_ENTRIES:]:
            target = entry.target_intent or "-"
            reason = f" ({entry.reason})" if entry.reason else ""
            lines.append(f"{entry.step}. {entry.operation} {target} -> {entry.outcome}{reason}")
        return "\n".join(lines)
