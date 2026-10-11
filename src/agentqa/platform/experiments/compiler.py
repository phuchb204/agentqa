from __future__ import annotations

from dataclasses import dataclass, field

from agentqa.platform.experiments.manifests import ExperimentManifest


@dataclass(frozen=True)
class Slot:
    slot_key: str
    arm_id: str
    case_key: str
    variant_token: str | None
    data_row: str | None
    repetition: int
    cohorts: tuple[str, ...] = field(default_factory=tuple)

    def as_payload(self) -> dict:
        return {
            "slot_key": self.slot_key,
            "arm_id": self.arm_id,
            "case_key": self.case_key,
            "variant_token": self.variant_token,
            "data_row": self.data_row,
            "repetition": self.repetition,
            "cohorts": list(self.cohorts),
        }


def build_slots(manifest: ExperimentManifest) -> list[Slot]:
    cases = list(manifest.corpus.get("cases", []))
    data_rows = list(manifest.corpus.get("data_rows", []))
    variants = {key: list(value) for key, value in manifest.variant_tokens.items()}
    slots: list[Slot] = []
    seen: set[str] = set()
    for arm in manifest.arms:
        for case_key in cases:
            variant_tokens = variants.get(case_key) or [None]
            rows = data_rows or [None]
            for variant_token in variant_tokens:
                for data_row in rows:
                    for repetition in range(1, manifest.samples.repetitions + 1):
                        key = "|".join(
                            [
                                manifest.digest(),
                                arm.arm_id,
                                case_key,
                                variant_token or "-",
                                str(data_row) if data_row is not None else "-",
                                str(repetition),
                            ]
                        )
                        if key in seen:
                            raise ValueError(f"slot_key không unique: {key}")
                        seen.add(key)
                        slots.append(
                            Slot(
                                slot_key=key,
                                arm_id=arm.arm_id,
                                case_key=case_key,
                                variant_token=variant_token,
                                data_row=data_row,
                                repetition=repetition,
                                cohorts=tuple(arm.cohorts),
                            )
                        )
    return slots


def expected_slot_count(manifest: ExperimentManifest) -> int:
    cases = len(manifest.corpus.get("cases", []))
    rows = len(manifest.corpus.get("data_rows", [])) or 1
    arms = len(manifest.arms)
    variant_total = sum(len(value) or 1 for value in manifest.variant_tokens.values()) or cases
    return (
        cases * arms * rows * manifest.samples.repetitions
        if not manifest.variant_tokens
        else variant_total * arms * rows * manifest.samples.repetitions
    )
