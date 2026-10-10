import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";

import { useApi } from "../../api/context";
import { ErrorView, LoadingView } from "../../components/States";
import { formatCost, formatUsage, verdictLabel } from "../live/money";

export function RunDetailPage({ workspaceId, runId }: { workspaceId: string; runId: string }) {
  const api = useApi();
  const detailQuery = useQuery({
    queryKey: ["run-detail", workspaceId, runId],
    queryFn: () => api.getRunDetail(workspaceId, runId),
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
