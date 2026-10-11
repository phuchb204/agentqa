from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from agentqa.platform.calibration.jobs import CalibrationRunner, run_calibration
from agentqa.platform.calibration.models import CalibrationManifest, CalibrationReceipt

DEFAULT_RECEIPT_DIR = Path("artifacts") / "calibration"


def load_manifest(path: Path) -> CalibrationManifest:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    return CalibrationManifest.model_validate(document)


class CalibrationService:
    def __init__(self, manifest: CalibrationManifest, receipt_dir: Path | None = None) -> None:
        self.manifest = manifest
        self.receipt_dir = receipt_dir or DEFAULT_RECEIPT_DIR

    def validate(self) -> dict[str, Any]:
        return {
            "ok": True,
            "profile_id": self.manifest.profile_id,
            "version": self.manifest.version,
            "manifest_digest": self.manifest.digest(),
            "splits": {name: len(cases) for name, cases in self.manifest.splits.items()},
            "budgets": self.manifest.budgets.model_dump(mode="json"),
            "quality_policy": self.manifest.quality_policy.model_dump(mode="json"),
        }

    def receipt_path(self) -> Path:
        return self.receipt_dir / f"{self.manifest.profile_id}-{self.manifest.version}.json"

    def load_receipt(self) -> CalibrationReceipt | None:
        path = self.receipt_path()
        if not path.is_file():
            return None
        return CalibrationReceipt.model_validate(json.loads(path.read_text(encoding="utf-8")))

    def save_receipt(self, receipt: CalibrationReceipt) -> Path:
        path = self.receipt_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(receipt.as_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        return path

    def status(self) -> dict[str, Any]:
        receipt = self.load_receipt()
        if receipt is None:
            return {
                "profile_id": self.manifest.profile_id,
                "version": self.manifest.version,
                "status": "provisional",
                "reason": "missing_receipt",
                "production_ready": False,
                "receipt_path": None,
                "manifest_digest": self.manifest.digest(),
            }
        return {
            "profile_id": receipt.profile_id,
            "version": receipt.version,
            "status": receipt.status,
            "reason": receipt.reason,
            "production_ready": receipt.status == "ready" and receipt.evidence == "measured",
            "evidence": receipt.evidence,
            "bound_upper": receipt.bound_upper,
            "sample_units": receipt.sample_units,
            "groups": receipt.groups,
            "receipt_path": str(self.receipt_path()),
            "manifest_digest": self.manifest.digest(),
        }

    async def execute(self, runner: CalibrationRunner) -> CalibrationReceipt:
        outcome = await run_calibration(self.manifest, runner)
        receipt: CalibrationReceipt = outcome["receipt"]
        self.save_receipt(receipt)
        return receipt
