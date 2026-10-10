import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useSearch } from "@tanstack/react-router";

import { useApi } from "../../api/context";
import { EmptyView, ErrorView, LoadingView } from "../../components/States";
import { formatCost } from "../live/money";

export function ComparePage({ workspaceId }: { workspaceId: string }) {
  const api = useApi();
  const search = useSearch({ strict: false }) as { run_a?: string; run_b?: string };
  const [runA, setRunA] = useState(search.run_a ?? "");
  const [runB, setRunB] = useState(search.run_b ?? "");

  const runsQuery = useQuery({
    queryKey: ["runs", workspaceId, "compare-picker"],
    queryFn: () => api.listRuns(workspaceId, { limit: "50" }),
  });

  useEffect(() => {
    if (!runsQuery.data) {
      return;
    }
    const ids = runsQuery.data.items.map((item) => item.run_id);
    if (runA === "" && ids.length > 0) {
      setRunA(ids[0]);
    }
    if (runB === "" && ids.length > 1) {
      setRunB(ids[1]);
    }
  }, [runsQuery.data, runA, runB]);

  const comparisonQuery = useQuery({
    queryKey: ["comparison", workspaceId, runA, runB],
    queryFn: () => api.compareRuns(workspaceId, runA, runB),
    enabled: runA !== "" && runB !== "" && runA !== runB,
  });

  if (runsQuery.isLoading) {
    return <LoadingView label="Đang tải danh sách lượt chạy" />;
  }
  if (runsQuery.isError) {
    return (
      <ErrorView
        message="Không tải được danh sách lượt chạy"
        onRetry={() => void runsQuery.refetch()}
      />
    );
  }
  const items = runsQuery.data?.items ?? [];
  if (items.length < 2) {
    return (
      <EmptyView
        title="Cần ít nhất hai lượt chạy"
        hint="Chạy thêm một lượt để so sánh cấu hình và kết quả."
      />
    );
  }

  return (
    <div className="stack">
      <section className="panel">
        <h2 className="panel__title">So sánh lượt chạy</h2>
        <div className="row">
          <label className="stack">
            Run A
            <select
              aria-label="Chọn run A"
              value={runA}
              onChange={(event) => setRunA(event.target.value)}
            >
              {items.map((item) => (
                <option key={item.run_id} value={item.run_id}>
                  {item.run_id.slice(0, 8)} · {item.status} · {item.verdict ?? "—"}
                </option>
              ))}
            </select>
          </label>
          <label className="stack">
            Run B
            <select
              aria-label="Chọn run B"
              value={runB}
              onChange={(event) => setRunB(event.target.value)}
            >
              {items.map((item) => (
                <option key={item.run_id} value={item.run_id}>
                  {item.run_id.slice(0, 8)} · {item.status} · {item.verdict ?? "—"}
                </option>
              ))}
            </select>
          </label>
        </div>
      </section>

      {comparisonQuery.isLoading ? <LoadingView label="Đang so sánh" /> : null}
      {comparisonQuery.isError ? (
        <ErrorView
          message="Không so sánh được hai lượt chạy"
          onRetry={() => void comparisonQuery.refetch()}
        />
      ) : null}
      {comparisonQuery.data ? (
        <>
          <section className="panel">
            <h3 className="panel__title">Khác biệt cấu hình (kiểm tra trước khi đọc metrics)</h3>
            <table>
              <thead>
                <tr>
                  <th>Trường</th>
                  <th>Run A</th>
                  <th>Run B</th>
                  <th>Khớp</th>
                </tr>
              </thead>
              <tbody>
                {comparisonQuery.data.config_diff.map((entry) => (
                  <tr key={entry.field}>
                    <td>{entry.field}</td>
                    <td>{JSON.stringify(entry.a)}</td>
                    <td>{JSON.stringify(entry.b)}</td>
                    <td>
                      {entry.equal ? (
                        <span className="badge badge--passed">khớp</span>
                      ) : (
                        <span className="badge badge--warning">khác</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>

          <section className="panel">
            <h3 className="panel__title">Metrics</h3>
            <table>
              <thead>
                <tr>
                  <th>Run</th>
                  <th>Verdict</th>
                  <th>Gate</th>
                  <th>Usage</th>
                  <th>Chi phí</th>
                </tr>
              </thead>
              <tbody>
                {(["a", "b"] as const).map((side) => {
                  const metric = comparisonQuery.data.metrics[side];
                  return (
                    <tr key={side}>
                      <td>{side === "a" ? runA.slice(0, 8) : runB.slice(0, 8)}</td>
                      <td>{metric.verdict ?? "—"}</td>
                      <td>{metric.gate ?? "—"}</td>
                      <td>
                        {metric.usage_state === "unknown"
                          ? "Không có dữ liệu usage"
                          : `${metric.usage_input_tokens} / ${metric.usage_output_tokens}`}
                      </td>
                      <td>
                        {formatCost(metric.cost_state, metric.cost_total, metric.cost_currency)}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </section>

          <section className="panel">
            <h3 className="panel__title">Alignment theo checkpoint (không theo step index)</h3>
            {comparisonQuery.data.alignment.map((entry) => (
              <div key={entry.logical_key} className="stack">
                <h4>
                  {entry.logical_key}{" "}
                  {entry.aligned ? (
                    <span className="badge">
                      {entry.a_status ?? "—"} vs {entry.b_status ?? "—"}
                    </span>
                  ) : (
                    <span className="badge badge--danger">Không có bước tương ứng</span>
                  )}
                </h4>
                {entry.assertions.length > 0 ? (
                  <table>
                    <thead>
                      <tr>
                        <th>Checkpoint</th>
                        <th>Assertion</th>
                        <th>Aligned</th>
                        <th>A expected → observed</th>
                        <th>B expected → observed</th>
                      </tr>
                    </thead>
                    <tbody>
                      {entry.assertions.map((row) => (
                        <tr key={`${row.checkpoint_id}:${row.assertion_id}`}>
                          <td>{row.checkpoint_id}</td>
                          <td>{row.assertion_id}</td>
                          <td>{row.aligned ? "có" : "không"}</td>
                          <td>
                            {row.a_expected ?? "—"} → {row.a_observed ?? "—"}
                          </td>
                          <td>
                            {row.b_expected ?? "—"} → {row.b_observed ?? "—"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                ) : null}
              </div>
            ))}
          </section>
        </>
      ) : null}
    </div>
  );
}
