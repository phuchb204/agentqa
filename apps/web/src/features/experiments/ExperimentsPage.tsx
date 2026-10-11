import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";

import { useApi } from "../../api/context";
import type { ExperimentSlot } from "../../api/types";
import { EmptyView, ErrorView, LoadingView } from "../../components/States";

function formatRatio(value: number | null): string {
  return value === null ? "—" : value.toFixed(3);
}

export function ExperimentsListPage({ workspaceId }: { workspaceId: string }) {
  const api = useApi();
  const queryClient = useQueryClient();
  const revisionsQuery = useQuery({
    queryKey: ["experiment-revisions", workspaceId],
    queryFn: () => api.listExperimentRevisions(workspaceId),
  });
  const executeMutation = useMutation({
    mutationFn: (revisionId: string) => api.executeExperimentRevision(workspaceId, revisionId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["experiment-revisions", workspaceId] });
    },
  });

  if (revisionsQuery.isLoading) {
    return <LoadingView label="Đang tải experiment revisions" />;
  }
  if (revisionsQuery.isError) {
    return (
      <ErrorView
        message="Không tải được experiment revisions"
        onRetry={() => void revisionsQuery.refetch()}
      />
    );
  }
  const items = revisionsQuery.data?.items ?? [];
  if (items.length === 0) {
    return (
      <EmptyView
        title="Chưa có experiment revision"
        hint="Tạo manifest RQ1–RQ3 qua API/CLI trước khi chạy thực nghiệm."
      />
    );
  }
  return (
    <div className="stack" data-testid="experiments-list">
      <section className="panel">
        <h2 className="panel__title">Thực nghiệm nghiên cứu</h2>
        <table>
          <thead>
            <tr>
              <th>Experiment</th>
              <th>Revision</th>
              <th>Digest</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {items.map((item) => (
              <tr key={item.revision_id}>
                <td>{item.logical_key}</td>
                <td>{item.revision_no}</td>
                <td>{item.content_digest.slice(0, 12)}…</td>
                <td className="row">
                  <Link
                    to="/w/$workspaceId/experiments/$revisionId"
                    params={{ workspaceId, revisionId: item.revision_id }}
                  >
                    Mở kết quả
                  </Link>
                  <button
                    type="button"
                    onClick={() => executeMutation.mutate(item.revision_id)}
                    disabled={executeMutation.isPending}
                  >
                    Chạy slots
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {executeMutation.data ? (
          <p className="muted" data-testid="experiment-execute-summary">
            Lần chạy {executeMutation.data.attempt_no}: {executeMutation.data.completed} completed,{" "}
            {executeMutation.data.blocked} blocked, {executeMutation.data.errors} error
          </p>
        ) : null}
      </section>
    </div>
  );
}

export function ExperimentDetailPage({
  workspaceId,
  revisionId,
}: {
  workspaceId: string;
  revisionId: string;
}) {
  const api = useApi();
  const resultsQuery = useQuery({
    queryKey: ["experiment-results", workspaceId, revisionId],
    queryFn: () => api.getExperimentResults(workspaceId, revisionId),
  });
  const [armFilter, setArmFilter] = useState("all");
  const [statusFilter, setStatusFilter] = useState("all");
  const [caseFilter, setCaseFilter] = useState("all");
  const [selectedSlot, setSelectedSlot] = useState<ExperimentSlot | null>(null);

  const slots = useMemo(() => resultsQuery.data?.slots ?? [], [resultsQuery.data]);
  const arms = useMemo(() => Array.from(new Set(slots.map((slot) => slot.arm_id))).sort(), [slots]);
  const cases = useMemo(
    () => Array.from(new Set(slots.map((slot) => slot.case_key))).sort(),
    [slots],
  );
  const filtered = slots.filter(
    (slot) =>
      (armFilter === "all" || slot.arm_id === armFilter) &&
      (statusFilter === "all" || slot.status === statusFilter) &&
      (caseFilter === "all" || slot.case_key === caseFilter),
  );

  if (resultsQuery.isLoading) {
    return <LoadingView label="Đang tải kết quả thực nghiệm" />;
  }
  if (resultsQuery.isError) {
    return (
      <ErrorView
        message="Không tải được kết quả thực nghiệm"
        onRetry={() => void resultsQuery.refetch()}
      />
    );
  }
  const results = resultsQuery.data;
  if (!results) {
    return <EmptyView title="Chưa có kết quả" hint="Chạy slots trước khi xem kết quả." />;
  }
  const analysis = results.analysis;

  return (
    <div className="stack" data-testid="experiment-results">
      <section className="panel">
        <h2 className="panel__title">
          Kết quả · digest {results.content_digest.slice(0, 12)}… · seed {analysis.seeds.join(", ")}
        </h2>
        <p className="muted" data-testid="metric-definitions">
          Oracle success: {analysis.metric_definitions.oracle_task_success}
        </p>
        <table data-testid="arm-summary">
          <thead>
            <tr>
              <th>Arm</th>
              <th>Sản phẩm (pass rate)</th>
              <th>Oracle (lower…upper)</th>
              <th>Unscorable</th>
              <th>Gate/slots</th>
              <th>False pass</th>
              <th>False heal</th>
              <th>Wall time</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(analysis.arms).map(([armId, arm]) => (
              <tr key={armId}>
                <td>{armId}</td>
                <td>{formatRatio(arm.product_pass_rate)}</td>
                <td data-testid={`oracle-uncertainty-${armId}`}>
                  {formatRatio(arm.oracle.success_lower_bound)} …{" "}
                  {formatRatio(arm.oracle.success_upper_bound)}
                </td>
                <td>{arm.oracle.unscorable}</td>
                <td>
                  {arm.completed}/{arm.slots_total} (blocked {arm.blocked}, error {arm.errors})
                </td>
                <td>{arm.false_passes}</td>
                <td>{arm.healing.false_heals}</td>
                <td>{arm.usage.wall_time_seconds}s</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className="panel" data-testid="confound-flags">
        <h3 className="panel__title">Cờ nhiễu cần đọc trước kết luận</h3>
        <ul>
          {Object.entries(analysis.arms).map(([armId, arm]) => (
            <li key={armId}>
              {armId}: alias chưa xác minh{" "}
              {arm.confounds.unverified_model_alias.length
                ? arm.confounds.unverified_model_alias.join(", ")
                : "—"}{" "}
              · provider cache {arm.confounds.provider_cache_observed ? "có" : "không"} · cost basis{" "}
              {arm.confounds.cost_basis_mixed
                ? `trộn (${arm.confounds.cost_bases.join(", ")})`
                : (arm.confounds.cost_bases[0] ?? "—")}
            </li>
          ))}
        </ul>
        {analysis.comparisons.length > 0 ? (
          <table>
            <thead>
              <tr>
                <th>So sánh</th>
                <th>Cặp</th>
                <th>Chênh lệch (CI)</th>
                <th>Đủ hỗ trợ</th>
                <th>Non-inferiority</th>
              </tr>
            </thead>
            <tbody>
              {analysis.comparisons.map((comparison) => (
                <tr key={`${comparison.left}-${comparison.right}`}>
                  <td>
                    {comparison.left} vs {comparison.right}
                  </td>
                  <td>{comparison.pairs}</td>
                  <td>
                    {formatRatio(comparison.estimate)} ({formatRatio(comparison.lower)} …{" "}
                    {formatRatio(comparison.upper)})
                  </td>
                  <td>{comparison.sufficient_support ? "có" : "insufficient_support"}</td>
                  <td>
                    {comparison.non_inferiority_margin === undefined
                      ? "—"
                      : comparison.non_inferior === null
                        ? "chưa kết luận"
                        : comparison.non_inferior
                          ? "đạt"
                          : "không đạt"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : null}
      </section>

      <section className="panel" data-testid="experiment-charts">
        <h3 className="panel__title">Biểu đồ oracle success (lower…upper)</h3>
        <ul>
          {analysis.charts.oracle_success.map((entry) => (
            <li key={entry.arm}>
              {entry.arm}: {formatRatio(entry.lower)} … {formatRatio(entry.upper)}
            </li>
          ))}
        </ul>
      </section>

      <section className="panel" data-testid="slot-filters">
        <h3 className="panel__title">Slots</h3>
        <div className="row">
          <label className="stack">
            Arm
            <select
              aria-label="Lọc arm"
              value={armFilter}
              onChange={(event) => setArmFilter(event.target.value)}
            >
              <option value="all">Tất cả</option>
              {arms.map((arm) => (
                <option key={arm} value={arm}>
                  {arm}
                </option>
              ))}
            </select>
          </label>
          <label className="stack">
            Trạng thái
            <select
              aria-label="Lọc trạng thái"
              value={statusFilter}
              onChange={(event) => setStatusFilter(event.target.value)}
            >
              <option value="all">Tất cả</option>
              {["completed", "blocked", "error", "scheduled", "running"].map((status) => (
                <option key={status} value={status}>
                  {status}
                </option>
              ))}
            </select>
          </label>
          <label className="stack">
            Ca
            <select
              aria-label="Lọc ca"
              value={caseFilter}
              onChange={(event) => setCaseFilter(event.target.value)}
            >
              <option value="all">Tất cả</option>
              {cases.map((caseKey) => (
                <option key={caseKey} value={caseKey}>
                  {caseKey}
                </option>
              ))}
            </select>
          </label>
        </div>
        <table data-testid="slot-table">
          <thead>
            <tr>
              <th>Slot</th>
              <th>Arm</th>
              <th>Ca</th>
              <th>Variant</th>
              <th>Rep</th>
              <th>Lần</th>
              <th>Trạng thái</th>
              <th>Lý do</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((slot) => (
              <tr
                key={`${slot.slot_key}-${slot.attempt_no}`}
                onClick={() => setSelectedSlot(slot)}
                style={{ cursor: "pointer" }}
              >
                <td>{slot.slot_key.slice(-12)}</td>
                <td>{slot.arm_id}</td>
                <td>{slot.case_key}</td>
                <td>{slot.variant_token ?? "—"}</td>
                <td>{slot.repetition}</td>
                <td>{slot.attempt_no}</td>
                <td>{slot.status}</td>
                <td>{slot.blocked_reason ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {selectedSlot ? (
          <div className="panel" data-testid="slot-detail">
            <h4 className="panel__title">Chi tiết slot</h4>
            <p>
              Sản phẩm:{" "}
              {String(
                (selectedSlot.payload.product as { verdict?: string } | undefined)?.verdict ?? "—",
              )}{" "}
              · Oracle:{" "}
              {String(
                (selectedSlot.payload.oracle as { task_outcome?: string } | undefined)
                  ?.task_outcome ?? "—",
              )}{" "}
              · Gate:{" "}
              {String(
                (selectedSlot.payload.gate as { result?: string } | undefined)?.result ?? "—",
              )}
            </p>
            <p className="muted">
              Tách biệt product/oracle/gate; unscorable không quy thành correct. Blocked hợp lệ vẫn
              thuộc denominator task-success.
            </p>
          </div>
        ) : null}
      </section>
    </div>
  );
}
