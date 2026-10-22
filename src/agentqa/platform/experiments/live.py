from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from agentqa.contracts.calibration import CalibrationProfile, RankerKind
from agentqa.platform.calibration.live import LiveResearchHarness, _run_db
from agentqa.platform.experiments.analysis import compute_analysis
from agentqa.platform.experiments.exports import build_bundle, write_bundle
from agentqa.platform.experiments.manifests import ExperimentManifest
from agentqa.platform.experiments.runner import ExperimentService

REPO_ROOT = Path(__file__).resolve().parents[4]
CAPABILITY_DIR = REPO_ROOT / "artifacts" / "model-capabilities"

POLICY_BY_ARM: dict[str, str] = {
    "replay_strict": "replay",
    "replay_healing": "replay_healing",
    "llm": "llm",
    "jev_cascade": "jev_cascade",
}

PARAMETER_DEFAULTS = {
    "item_name": "Việc live",
    "keyword": "Ly",
}

APP_DEFAULT_SEED = {
    "taskboard": "success",
    "shopflow": "catalog_default",
    "canvasdesk": "default",
}

CASE_SEEDS = {
    "taskboard_duplicate_label_rejected": "duplicate_rejected",
    "taskboard_delete_twins_healed": "twins",
}

CASE_PARAMETERS = {
    "taskboard_duplicate_label_rejected": {"item_name": "Việc trùng"},
    "taskboard_delete_twins_healed": {"item_name": "Việc trùng"},
}

SCRATCH_SEEDS = {
    "taskboard": "wrong_entity",
    "shopflow": "catalog_default",
    "canvasdesk": "default",
}


def chat_image_verified(pair: str) -> bool:
    from datetime import UTC, datetime

    from agentqa.models.routes import MODEL_PAIRS

    try:
        chat_route, _ = MODEL_PAIRS[pair]
    except KeyError:
        return False
    if not CAPABILITY_DIR.is_dir():
        return False
    receipts = sorted(CAPABILITY_DIR.glob(f"{chat_route.value}-*.json"), key=lambda path: path.stat().st_mtime)
    if not receipts:
        return False
    try:
        document = json.loads(receipts[-1].read_text(encoding="utf-8"))
    except ValueError:
        return False
    expires = document.get("expires_at")
    try:
        moment = datetime.fromisoformat(str(expires).replace("Z", "+00:00"))
    except ValueError:
        return False
    if moment < datetime.now(UTC):
        return False
    return (document.get("capabilities") or {}).get("image") == "verified"


def go_image_verified() -> bool:
    return chat_image_verified("opencode")


def corpus_cases() -> dict[str, tuple[str, dict[str, Any]]]:
    import yaml

    found: dict[str, tuple[str, dict[str, Any]]] = {}
    cases_root = REPO_ROOT / "benchmarks" / "public" / "cases"
    for path in sorted(cases_root.rglob("*.yaml")):
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        if isinstance(document, dict) and document.get("schema_version") == "case/1":
            app = path.parent.name
            found[str(document["logical_key"])] = (app, document)
    return found


def _parameters_for(document: dict[str, Any]) -> dict[str, Any]:
    parameters: dict[str, Any] = {}
    for name in document.get("parameter_defs") or {}:
        parameters[name] = PARAMETER_DEFAULTS.get(name, "live")
    return parameters


def _healing_profile(arm_payload: dict[str, Any], manifest: ExperimentManifest) -> CalibrationProfile | None:
    if not arm_payload.get("healing"):
        return None
    ranker = {
        "heuristic": RankerKind.HEURISTIC,
        "llm": RankerKind.LLM,
        "cascade": RankerKind.CASCADE,
    }.get(str(arm_payload.get("arm_id", "")).split("_")[-1], RankerKind.HEURISTIC)
    if arm_payload.get("arm_id") == "healing_go_llm":
        ranker = RankerKind.LLM
    if arm_payload.get("arm_id") == "jev_cascade":
        ranker = RankerKind.CASCADE
    return CalibrationProfile(
        profile_id=f"live-{arm_payload.get('arm_id')}",
        version=manifest.version,
        ranker=ranker,
        min_score=0.55,
        margin_min=0.15,
    )


class LiveSlotRunner:
    def __init__(
        self,
        *,
        harness: LiveResearchHarness,
        manifest: ExperimentManifest,
        oracle_module,
        image_verified: bool,
        slot_limit: int | None = None,
    ) -> None:
        self.harness = harness
        self.manifest = manifest
        self.oracle_module = oracle_module
        self.image_verified = image_verified
        self.slot_limit = slot_limit
        self.executed = 0
        self.calls_used = 0
        self.case_revisions: dict[str, UUID] = {}
        self.case_docs = corpus_cases()
        self.apps = {app.name: app for app in harness.apps}
        self.blocked: list[dict[str, Any]] = []

    def _prepare(self, arm_payload: dict[str, Any], slot) -> dict[str, Any]:
        if arm_payload.get("observation") == "vision_first" and not self.image_verified:
            return {"status": "blocked", "blocked_reason": "image_capability_unverified"}
        if self.slot_limit is not None and self.executed >= self.slot_limit:
            return {"status": "blocked", "blocked_reason": "slot_limit_reached"}
        if self.calls_used >= self.manifest.budgets.max_calls:
            return {"status": "blocked", "blocked_reason": "budget_exceeded"}
        entry = self.case_docs.get(slot.case_key)
        if entry is None:
            return {"status": "blocked", "blocked_reason": "case_not_in_corpus"}
        app_name, document = entry
        app = self.apps.get(app_name)
        if app is None:
            return {"status": "blocked", "blocked_reason": f"app_missing:{app_name}"}
        namespace = f"rq-{slot.arm_id[:16]}-{uuid4().hex[:8]}".replace(".", "_")
        seed = CASE_SEEDS.get(slot.case_key, APP_DEFAULT_SEED.get(app_name, "success"))
        variant_manifest = None
        if slot.variant_token:
            from agentqa.platform.experiments.variants import generate_variant

            scratch = f"scratch-{uuid4().hex[:8]}"
            self.harness.prepare_namespace(app, scratch, SCRATCH_SEEDS.get(app_name, seed))
            outcome = generate_variant(
                app=app.name,
                base_url=app.base_url,
                control_token=app.control_token,
                control_header={
                    "taskboard": "x-taskboard-control",
                    "shopflow": "x-shopflow-control",
                    "canvasdesk": "x-canvasdesk-control",
                }[app.name],
                namespace=scratch,
                fixture_ref=app.fixture_ref,
                case_key=slot.case_key,
                group="benign",
            )
            if not outcome.valid or outcome.manifest is None:
                return {"status": "blocked", "blocked_reason": f"variant_invalid:{outcome.reason}"}
            if outcome.manifest["variant_token"] != slot.variant_token:
                return {"status": "blocked", "blocked_reason": "variant_token_mismatch"}
            armed = self.harness.arm_mutation(
                app,
                namespace,
                str(outcome.manifest["operator"]["name"]),
                dict(outcome.manifest.get("params") or {}),
            )
            if not armed.get("armed"):
                return {"status": "blocked", "blocked_reason": f"variant_arm_failed:{armed.get('reason')}"}
            variant_manifest = outcome.manifest
        else:
            self.harness.prepare_namespace(app, namespace, seed)
        case_document = document
        if arm_payload.get("baseline") and arm_payload.get("plan_ref"):
            import yaml

            case_document = yaml.safe_load((REPO_ROOT / str(arm_payload["plan_ref"])).read_text(encoding="utf-8"))
        revision = self._case_revision(case_document)
        parameters = {**_parameters_for(document), **CASE_PARAMETERS.get(slot.case_key, {})}
        environment = self.harness.seed_environment(
            app=app, namespace=namespace, parameters=parameters, fixture_seed=seed
        )
        policy = POLICY_BY_ARM.get(str(arm_payload.get("policy")), "replay")
        gate_profile = str(arm_payload.get("gate_profile", "strict"))
        if gate_profile not in ("strict", "allow_healing"):
            return {"status": "blocked", "blocked_reason": f"gate_profile_invalid:{gate_profile}"}
        run = self.harness.run_case(
            case_revision_id=revision,
            environment_revision_id=environment,
            policy=policy,
            observation=str(arm_payload.get("observation", "semantic")),
            healing_profile=_healing_profile(arm_payload, self.manifest),
            gate_profile=gate_profile,
        )
        self.executed += 1
        self.calls_used += int(run.usage.get("calls", 0))
        if variant_manifest is not None:
            oracle_record = self.oracle_module.variant_oracle_record(variant_manifest)
        else:
            base = self.oracle_module.record_for(slot.case_key)
            if base is None:
                return {"status": "error", "blocked_reason": "oracle_record_missing"}
            oracle_record = dict(base)
            oracle_record["case_key"] = slot.case_key
        try:
            scoring = self.harness.score_run(run.run_id, oracle_record)
        except Exception as error:
            scoring = {"task_outcome": "unscorable", "counters": {}, "false_pass": False, "error": type(error).__name__}
        product = {"verdict": run.state.get("verdict"), "gate": run.state.get("gate")}
        gate_detail = self.harness.final_gate(run.run_id)
        gate = {"result": run.state.get("gate"), "reasons": list(gate_detail.get("reasons") or [])}
        oracle = {
            "task_outcome": scoring.get("oracle_task_outcome"),
            "counters": scoring.get("counters") or {},
            "false_pass": bool(scoring.get("false_pass")),
            "scorable": bool(scoring.get("scorable", True)),
            "unscorable_reason": scoring.get("unscorable_reason"),
        }
        payload: dict[str, Any] = {
            "status": "completed",
            "run_id": str(run.run_id),
            "product": product,
            "oracle": oracle,
            "gate": gate,
            "degraded": bool(gate_detail.get("degraded", False)),
            "usage": run.usage,
            "reasons": list(run.state.get("reasons") or []),
            "aborted_reason": self.harness.abort_reason(run.run_id),
            "model_requested": ",".join(run.usage.get("model_requested") or []) or None,
            "model_resolved": ",".join(run.usage.get("model_resolved") or []) or None,
            "provider_cache_observed": bool(run.usage.get("provider_cache_observed")),
            "cost_basis": (run.usage.get("cost_bases") or [None])[0],
            "variant_token": slot.variant_token,
        }
        return payload

    def _case_revision(self, document: dict[str, Any]) -> UUID:
        key = str(document["logical_key"])
        if key not in self.case_revisions:
            self.case_revisions[key] = self.harness.seed_case(logical_key=key, document=document)
        return self.case_revisions[key]

    async def run_slot(self, slot, arm_payload: dict[str, Any]) -> dict[str, Any]:
        result = await asyncio.to_thread(self._prepare, arm_payload, slot)
        if result.get("status") != "completed":
            self.blocked.append({"slot_key": slot.slot_key, **result})
        return result


def run_live_experiment(
    manifest: ExperimentManifest,
    harness: LiveResearchHarness,
    oracle_module,
    *,
    slot_limit: int | None = None,
) -> dict[str, Any]:
    image_verified = chat_image_verified(manifest.budgets.model_pair)
    runner = LiveSlotRunner(
        harness=harness,
        manifest=manifest,
        oracle_module=oracle_module,
        image_verified=image_verified,
        slot_limit=slot_limit,
    )

    async def execute() -> dict[str, Any]:
        service = ExperimentService(harness._engines["agentqa_api"])
        revision = await service.create_revision(
            workspace_id=harness.workspace_id,
            principal_id=harness.user_id,
            actor=harness.username,
            logical_key=f"{manifest.experiment_id}-{manifest.version}",
            content=manifest.model_dump(mode="json"),
        )
        summary = await service.execute(
            workspace_id=harness.workspace_id,
            principal_id=harness.user_id,
            revision_id=revision.revision_id,
            slot_runner=runner,
        )
        results = await service.results(
            workspace_id=harness.workspace_id, principal_id=harness.user_id, revision_id=revision.revision_id
        )
        return {"revision": revision, "summary": summary, "results": results}

    outcome = _run_db(execute())
    analysis = compute_analysis(manifest, outcome["results"]["slots"])
    root = Path("artifacts") / "research" / f"{manifest.experiment_id}-{manifest.version}-{int(time.time())}"
    bundle_files = build_bundle(results=outcome["results"], analysis=analysis)
    write_bundle(root, bundle_files)
    (root / "slot-summary.json").write_text(
        json.dumps(
            {
                "summary": outcome["summary"],
                "calls_used": runner.calls_used,
                "blocked": runner.blocked,
                "image_capability_verified": image_verified,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return {
        "revision_id": str(outcome["revision"].revision_id),
        "summary": outcome["summary"],
        "analysis": analysis,
        "calls_used": runner.calls_used,
        "blocked": runner.blocked,
        "image_capability_verified": image_verified,
        "bundle_dir": str(root),
    }
