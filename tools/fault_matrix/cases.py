from __future__ import annotations

from dataclasses import dataclass

MATRIX_VERSION = "fault-matrix/1"


@dataclass(frozen=True)
class FaultCase:
    id: str
    group: str
    node_id: str
    effect_proof: str


FAULT_CASES: tuple[FaultCase, ...] = (
    FaultCase(
        "submit.idempotent_duplicate_single_run",
        "submit",
        "tests/platform/test_idempotency.py::test_concurrent_duplicate_creates_single_run",
        "counter: số run tạo ra == 1 khi cùng idempotency key",
    ),
    FaultCase(
        "submit.api_same_key",
        "submit",
        "tests/api/test_runs.py::test_submit_idempotency_same_key",
        "counter: cùng key cùng input trả cùng run, không tạo run thứ hai",
    ),
    FaultCase(
        "lease.heartbeat_expiry_quarantine",
        "lease",
        "tests/faults/test_lease_loss.py::test_heartbeat_expiry_quarantines_and_blocks_requeue",
        "counter: job không quay lại queue sau khi lease hết hạn",
    ),
    FaultCase(
        "lease.two_workers_distinct",
        "lease",
        "tests/faults/test_lease_loss.py::test_two_workers_claim_distinct_jobs",
        "counter: hai worker nhận hai job khác nhau, không trùng ownership",
    ),
    FaultCase(
        "admission.global_limit",
        "admission",
        "tests/faults/test_scheduler_races.py::test_duplicate_claims_do_not_exceed_global_limit",
        "counter: reserved slots không vượt global limit dù claim trùng",
    ),
    FaultCase(
        "admission.cancel_blocks_new",
        "admission",
        "tests/faults/test_cancel_barrier.py::test_cancel_requested_blocks_admission_then_effective",
        "counter: không command nào được admit sau cancel requested trước effective",
    ),
    FaultCase(
        "dispatch.kill_after_effect",
        "dispatch",
        "tests/faults/test_crash_after_effect.py::test_kill_after_dispatch_marks_unknown_without_redispatch",
        "counter: label count trên fixture backend <= 1 và không tăng sau reconcile",
    ),
    FaultCase(
        "dispatch.response_loss_same_receipt",
        "dispatch",
        "tests/faults/test_crash_after_effect.py::test_response_loss_after_side_effect_returns_same_receipt",
        "counter: dispatch lần hai trả cùng receipt, executor không gọi lại",
    ),
    FaultCase(
        "verify.failed_survives_cleanup_error",
        "verify",
        "tests/verify/test_truth_table.py::test_failure_retained_despite_later_cleanup_error",
        "truth: verdict failed giữ nguyên khi cleanup lỗi sau đó",
    ),
    FaultCase(
        "verify.evidence_error_not_business_failure",
        "verify",
        "tests/verify/test_evidence_errors.py::test_evidence_error_does_not_become_business_failure",
        "truth: evidence error không chuyển thành failed nghiệp vụ",
    ),
    FaultCase(
        "db.outage_stops_admission_journal",
        "db",
        "tests/faults/test_command_journal.py::test_db_unavailable_stops_admission_without_side_effect",
        "counter: executor.calls == 0 khi DB unavailable",
    ),
    FaultCase(
        "db.outage_stops_admission_queue",
        "db",
        "tests/faults/test_lease_loss.py::test_db_unavailable_raises_and_stops_admission",
        "counter: không job nào được claim khi DB unavailable",
    ),
    FaultCase(
        "blob.failed_write_zero_blobs",
        "blob",
        "tests/faults/test_partial_artifact.py::test_failed_blob_write_keeps_unavailable_record_with_zero_blobs",
        "counter: số blob file ghi ra == 0, artifact unavailable có reason",
    ),
    FaultCase(
        "blob.storage_fault_partial_trace",
        "blob",
        "tests/faults/test_partial_artifact.py::test_storage_fault_keeps_partial_trace_without_false_pass",
        "verdict: không passed khi evidence storage lỗi; partial trace vẫn đọc được",
    ),
    FaultCase(
        "finalization.cleanup_exhaustion_bounded",
        "finalization",
        "tests/faults/test_cleanup_failure.py::test_cleanup_exhaustion_records_bounded_attempts",
        "counter: số lần gọi cleanup backend == max_attempts, không vượt bound",
    ),
    FaultCase(
        "finalization.business_failure_survives_cleanup",
        "finalization",
        "tests/platform/test_fixture_lifecycle.py::test_business_failure_survives_successful_cleanup",
        "truth: verdict failed giữ nguyên qua finalization; cleanup_ok không xóa failure",
    ),
    FaultCase(
        "finalization.cleanup_retries_bounded",
        "finalization",
        "tests/platform/test_fixture_lifecycle.py::test_cleanup_retries_bounded_then_exhausted",
        "counter: attempts == 3 rồi exhausted, lần process tiếp theo không chạy thêm",
    ),
    FaultCase(
        "stale_worker.reconcile_no_replay",
        "stale_worker",
        "tests/faults/test_supervisor_recovery.py::test_reconcile_marks_unknown_and_quarantines_without_replay",
        "counter: executor.calls == 0 sau reconcile; commands chuyển unknown",
    ),
    FaultCase(
        "stale_worker.stale_fence_blocked",
        "stale_worker",
        "tests/faults/test_command_journal.py::test_stale_fence_cannot_write_terminal",
        "counter: stale fence epoch không ghi được terminal state",
    ),
    FaultCase(
        "cancel_race.inflight_unknown",
        "cancel_race",
        "tests/faults/test_cancel_barrier.py::test_cancel_during_inflight_marks_unknown_within_bound",
        "counter: inflight command chuyển unknown trong bound, không replay",
    ),
    FaultCase(
        "cancel_race.pause_resume",
        "cancel_race",
        "tests/faults/test_cancel_barrier.py::test_pause_effective_then_resume_allows_new_commands",
        "counter: pause chặn command mới, resume cho phép lại đúng ranh giới",
    ),
    FaultCase(
        "duplicate_message.same_receipt",
        "duplicate_message",
        "tests/faults/test_command_journal.py::test_receipt_lifecycle_duplicate_returns_same_receipt",
        "counter: gửi lại cùng command_id trả cùng receipt, không dispatch lần hai",
    ),
    FaultCase(
        "duplicate_message.control_once",
        "duplicate_message",
        "tests/faults/test_cancel_barrier.py::test_duplicate_control_request_returns_same_record",
        "counter: control request trùng trả cùng record",
    ),
    FaultCase(
        "duplicate_schedule.single_admission",
        "duplicate_schedule",
        "tests/faults/test_scheduler_races.py::test_scheduler_claim_race_creates_single_run_and_single_admission",
        "counter: claim race tạo đúng một run và một admission",
    ),
)

GROUP_ORDER = (
    "submit",
    "lease",
    "admission",
    "dispatch",
    "verify",
    "db",
    "blob",
    "finalization",
    "stale_worker",
    "cancel_race",
    "duplicate_message",
    "duplicate_schedule",
)
