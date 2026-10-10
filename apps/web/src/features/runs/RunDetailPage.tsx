import { useMutation, useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useState } from "react";

import { useApi } from "../../api/context";
import type { HealingRecord } from "../../api/types";
import { ErrorView, LoadingView } from "../../components/States";
import { applyHealingPatch, summarizeTarget } from "./healing";
import { formatCost, formatUsage, verdictLabel } from "../live/money";

export function RunDetailPage({ workspaceId, runId }: { workspaceId: string; runId: string }) {
  const api = useApi();
  const [applyState, setApplyState] = useState<{
    recordId: string;
    message: string;
    error?: string;
  } | null>(null);
  const detailQuery = useQuery({
    queryKey: ["run-detail", workspaceId, runId],
    queryFn: () => api.getRunDetail(workspaceId, runId),
  });
  const healingQuery = useQuery({
    queryKey: ["run-healing", workspaceId, runId],
    queryFn: () => api.listRunHealing(workspaceId, runId),
  });
  const reportsQuery = useQuery({
    queryKey: ["run-reports", workspaceId, runId],
    queryFn: () => api.listRunReports(workspaceId, runId),
  });
  const diagnosticsQuery = useQuery({
    queryKey: ["run-diagnostics", workspaceId, runId],
    queryFn: () => api.listRunDiagnostics(workspaceId, runId),
  });
  const reportMutation = useMutation({
    mutationFn: (format: string) => api.createRunReport(workspaceId, runId, format),
    onSuccess: () => void reportsQuery.refetch(),
  });
  const issuePackageMutation = useMutation({
    mutationFn: () => api.createIssuePackage(workspaceId, runId),
  });
  const diagnosticMutation = useMutation({
    mutationFn: () => api.createRunDiagnostic(workspaceId, runId),
    onSuccess: () => void diagnosticsQuery.refetch(),
  });
  const applyMutation = useMutation({
    mutationFn: async (record: HealingRecord) => {
      if (!record.case_id || !record.proposal?.proposed) {
        throw new Error("Bản ghi phục hồi thiếu case hoặc đề xuất locator");
      }
      const draft = await api.getDraft(workspaceId, record.case_id);
      let base = draft?.content ?? null;
      if (!base) {
        const revisions = await api.listCaseRevisions(workspaceId, record.case_id);
        base = revisions.length > 0 ? revisions[revisions.length - 1].content : null;
      }
      if (!base) {
        throw new Error("Không tìm thấy nội dung ca để tạo bản chỉnh sửa");
      }
      const patched = applyHealingPatch(base, record);
      if (!patched.applied) {
        throw new Error("Không tìm thấy node/assertion để áp dụng đề xuất");
      }
      return api.saveDraft(workspaceId, record.case_id, patched.content, draft?.edit_version ?? 0);
    },
    onSuccess: (_draft, record) =>
      setApplyState({
        recordId: record.record_id,
        message: "Đã lưu đề xuất vào bản chỉnh sửa (chưa promote).",
      }),
    onError: (error, record) =>
      setApplyState({
        recordId: record.record_id,
        message: "",
        error: error instanceof Error ? error.message : "Không lưu được bản chỉnh sửa",
      }),
  });

  if (detailQuery.isLoading) {
    return <LoadingView label="Đang tải chi tiết lượt chạy" />;
  }
  if (detailQuery.isError || !detailQuery.data) {
    return (
      <ErrorView
        message="Không tải được chi tiết lượt chạy"
        onRetry={() => void detailQuery.refetch()}
      />
    );
  }
  const detail = detailQuery.data;
  const assertions = detail.executions.flatMap((execution) =>
    execution.assertions.map((assertion) => ({ ...assertion, execution })),
  );
  const firstProblem = assertions.find(
    (assertion) => assertion.result === "failed" || assertion.result === "error",
  );
  const evidenceIssues = detail.artifacts.filter((artifact) => artifact.state !== "available");

  return (
    <div className="stack">
      <section className="panel">
        <div className="row">
          <h2 className="panel__title">Kết luận lượt chạy {runId.slice(0, 8)}</h2>
          <span className="badge">{verdictLabel(detail.verdict, detail.terminal)}</span>
          <span className="badge">{detail.status}</span>
          <span className="badge">Gate: {detail.gate ?? "chưa có"}</span>
          {detail.annotations.map((annotation) => (
            <span key={annotation} className="badge badge--warning">
              {annotation}
            </span>
          ))}
        </div>
        <p className="muted">
          Evidence: {detail.artifacts.length} artifact · thiếu/redacted/expired:{" "}
          {evidenceIssues.length}
        </p>
      </section>

      {firstProblem ? (
        <section className="panel" role="alert">
          <h3 className="panel__title">
            Vấn đề đầu tiên có căn cứ: {firstProblem.execution.logical_key} /{" "}
            {firstProblem.checkpoint_id} / {firstProblem.assertion_id}
          </h3>
          <table>
            <tbody>
              <tr>
                <th>Expected</th>
                <td>{String(firstProblem.proof.expected ?? "—")}</td>
              </tr>
              <tr>
                <th>Observed</th>
                <td>{String(firstProblem.proof.observed ?? "—")}</td>
              </tr>
              <tr>
                <th>Evidence</th>
                <td>
                  {String(firstProblem.proof.evidence ?? "—")}
                  {detail.artifacts.length > 0 ? (
                    <>
                      {" · "}
                      <a
                        href={api.artifactContentUrl(workspaceId, detail.artifacts[0].artifact_id)}
                        target="_blank"
                        rel="noreferrer"
                      >
                        Mở artifact của run
                      </a>
                    </>
                  ) : (
                    " · Không có artifact"
                  )}
                </td>
              </tr>
              <tr>
                <th>Reason</th>
                <td>{String(firstProblem.proof.reason ?? "—")}</td>
              </tr>
            </tbody>
          </table>
        </section>
      ) : null}

      {(healingQuery.data?.length ?? 0) > 0 ? (
        <section className="panel" data-testid="healing-section">
          <h3 className="panel__title">Phục hồi ({healingQuery.data?.length})</h3>
          <p className="muted">
            Target gốc và candidate thực tế kèm guard/proof. Đề xuất locator chỉ tạo bản chỉnh sửa;
            promote vẫn là thao tác riêng trong editor.
          </p>
          {(healingQuery.data ?? []).map((record) => {
            const original = summarizeTarget(record.original_target);
            const actual = summarizeTarget(record.actual_target);
            return (
              <div key={record.record_id} className="stack" data-testid="healing-record">
                <div className="row">
                  <span
                    className={`badge${record.decision === "recovered" ? " badge--warning" : " badge--danger"}`}
                  >
                    {record.decision === "recovered" ? "Đã phục hồi" : "Từ chối phục hồi"}
                  </span>
                  <span className="badge">
                    {record.actor === "evidence" ? "bằng chứng" : "hành động"}
                  </span>
                  <strong>{record.node_id}</strong>
                  {record.source_run_id ? (
                    <Link
                      to="/w/$workspaceId/runs/$runId"
                      params={{ workspaceId, runId: record.source_run_id }}
                    >
                      Source run
                    </Link>
                  ) : null}
                </div>
                <table>
                  <tbody>
                    <tr>
                      <th>Target gốc</th>
                      <td>
                        {original.label}
                        {original.entityScope ? ` · scope: ${original.entityScope}` : ""}
                      </td>
                    </tr>
                    <tr>
                      <th>Target thực tế</th>
                      <td>
                        {record.actual_target
                          ? `${actual.label}${actual.entityScope ? ` · scope: ${actual.entityScope}` : ""}`
                          : "—"}
                      </td>
                    </tr>
                    <tr>
                      <th>Guard checks</th>
                      <td>{record.guard_checks.join(", ") || "—"}</td>
                    </tr>
                    <tr>
                      <th>Postcondition</th>
                      <td>
                        {record.postconditions_ok === null
                          ? "—"
                          : record.postconditions_ok
                            ? "đạt"
                            : "không đạt"}
                      </td>
                    </tr>
                    {record.refusal_reason ? (
                      <tr>
                        <th>Lý do từ chối</th>
                        <td>{record.refusal_reason}</td>
                      </tr>
                    ) : null}
                    {record.proposal?.locator ? (
                      <tr>
                        <th>Locator đề xuất</th>
                        <td>
                          {record.proposal.locator.kind}:{record.proposal.locator.value}
                        </td>
                      </tr>
                    ) : null}
                  </tbody>
                </table>
                {record.decision === "recovered" && record.proposal && record.case_id ? (
                  <div className="row">
                    <button
                      type="button"
                      onClick={() => applyMutation.mutate(record)}
                      disabled={applyMutation.isPending}
                    >
                      Tạo bản chỉnh sửa với locator đề xuất
                    </button>
                    {applyState?.recordId === record.record_id ? (
                      <span className={applyState.error ? "form-error" : "muted"}>
                        {applyState.error ?? applyState.message}
                      </span>
                    ) : null}
                  </div>
                ) : null}
              </div>
            );
          })}
        </section>
      ) : null}

      <section className="panel">
        <h3 className="panel__title">Assertions</h3>
        {assertions.length === 0 ? (
          <p className="muted">Chưa có assertion result được lưu.</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Ca</th>
                <th>Checkpoint</th>
                <th>Assertion</th>
                <th>Kết quả</th>
                <th>Expected</th>
                <th>Observed</th>
                <th>Evidence</th>
              </tr>
            </thead>
            <tbody>
              {assertions.map((assertion) => (
                <tr
                  key={`${assertion.execution.execution_id}:${assertion.checkpoint_id}:${assertion.assertion_id}`}
                >
                  <td>{assertion.execution.logical_key}</td>
                  <td>{assertion.checkpoint_id}</td>
                  <td>{assertion.assertion_id}</td>
                  <td>
                    <span
                      className={`badge${assertion.result === "failed" ? " badge--danger" : assertion.result === "passed" ? " badge--passed" : " badge--warning"}`}
                    >
                      {assertion.result}
                    </span>
                  </td>
                  <td>{String(assertion.proof.expected ?? "—")}</td>
                  <td>{String(assertion.proof.observed ?? "—")}</td>
                  <td>{String(assertion.proof.evidence ?? "—")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section className="panel">
        <h3 className="panel__title">Artifacts</h3>
        {detail.artifacts.length === 0 ? (
          <p className="muted">Không có artifact cho lượt chạy này.</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Kind</th>
                <th>Trạng thái</th>
                <th>Media</th>
                <th>Redacted</th>
                <th>Ghi chú</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {detail.artifacts.map((artifact) => (
                <tr key={artifact.artifact_id}>
                  <td>{artifact.kind}</td>
                  <td>{artifact.state}</td>
                  <td>{artifact.media_type ?? "—"}</td>
                  <td>{artifact.redacted ? "có" : "không"}</td>
                  <td>{artifact.unavailable_reason ?? "—"}</td>
                  <td>
                    {artifact.state === "available" ? (
                      <a
                        href={api.artifactContentUrl(workspaceId, artifact.artifact_id)}
                        target="_blank"
                        rel="noreferrer"
                      >
                        Tải
                      </a>
                    ) : (
                      <span className="muted">không khả dụng</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section className="panel">
        <h3 className="panel__title">Usage và chi phí</h3>
        <p>{formatUsage(detail.usage)}</p>
        <p>
          Chi phí:{" "}
          <strong>
            {formatCost(
              detail.usage.cost_state,
              detail.usage.cost_total,
              detail.usage.cost_currency,
            )}
          </strong>
        </p>
        <p className="muted">
          Unknown khác zero: thiếu dữ liệu chi phí được hiển thị rõ, không mặc định bằng 0.
        </p>
      </section>

      <section className="panel">
        <h3 className="panel__title">Controls</h3>
        <ul>
          {detail.controls.map((control) => (
            <li key={control.control_id}>
              {control.action} · requested {control.requested_at.slice(11, 19)} ·{" "}
              {control.effective_at
                ? `effective ${control.effective_at.slice(11, 19)}`
                : "chưa effective"}
            </li>
          ))}
          {detail.controls.length === 0 ? <li className="muted">Không có control nào.</li> : null}
        </ul>
      </section>

      <section className="panel" data-testid="reports-section">
        <h3 className="panel__title">Báo cáo và gói lỗi</h3>
        <p className="muted">
          Export dùng read model có version của server; gói lỗi chỉ tải về, hệ thống không tự gửi ra
          ngoài.
        </p>
        <div className="row">
          {["json", "csv", "jsonl", "html", "junit"].map((format) => (
            <button
              key={format}
              type="button"
              onClick={() => reportMutation.mutate(format)}
              disabled={reportMutation.isPending}
            >
              Tạo báo cáo {format.toUpperCase()}
            </button>
          ))}
          <button
            type="button"
            onClick={() => issuePackageMutation.mutate()}
            disabled={issuePackageMutation.isPending}
          >
            Tạo gói lỗi
          </button>
          <button
            type="button"
            onClick={() => diagnosticMutation.mutate()}
            disabled={diagnosticMutation.isPending}
          >
            Tạo phân tích đề xuất
          </button>
        </div>
        {(reportsQuery.data ?? []).length > 0 ? (
          <ul>
            {(reportsQuery.data ?? []).map((report) => (
              <li key={report.report_id}>
                <a
                  href={api.reportContentUrl(workspaceId, report.report_id)}
                  target="_blank"
                  rel="noreferrer"
                >
                  {report.format.toUpperCase()} · checksum {report.digest?.slice(0, 12) ?? "—"}
                </a>
              </li>
            ))}
          </ul>
        ) : (
          <p className="muted">Chưa có báo cáo nào được tạo.</p>
        )}
        {issuePackageMutation.data ? (
          <div className="stack">
            <p className="muted">
              Gói lỗi có provenance và bản xem trước redacted; tải về để chia sẻ thủ công.
            </p>
            <pre data-testid="issue-package-preview">
              {JSON.stringify(issuePackageMutation.data.preview, null, 2)}
            </pre>
            <a
              href={api.issuePackageContentUrl(workspaceId, issuePackageMutation.data.package_id)}
              target="_blank"
              rel="noreferrer"
            >
              Tải gói lỗi
            </a>
          </div>
        ) : null}
        {(diagnosticsQuery.data ?? []).length > 0 ? (
          <div className="stack" data-testid="diagnostics-list">
            {(diagnosticsQuery.data ?? []).map((diagnostic) => (
              <div key={diagnostic.diagnostic_id}>
                <span className="badge badge--warning">{diagnostic.label}</span>{" "}
                <span className="muted">
                  confidence {diagnostic.confidence ?? "—"} · {diagnostic.state}
                </span>
                <p>{diagnostic.explanation ?? "—"}</p>
                <p className="muted">
                  Không thay kết luận cuối; đây là đề xuất có bằng chứng tham chiếu.
                </p>
              </div>
            ))}
          </div>
        ) : null}
      </section>

      <section className="panel">
        <Link
          to="/w/$workspaceId/compare"
          params={{ workspaceId }}
          search={{ run_a: runId, run_b: "" }}
        >
          So sánh lượt chạy này →
        </Link>
      </section>
    </div>
  );
}
