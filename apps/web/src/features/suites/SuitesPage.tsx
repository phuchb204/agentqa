import { useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";

import { ApiClientError } from "../../api/client";
import { useApi } from "../../api/context";
import type { BindResult } from "../../api/types";
import { EmptyView, ErrorView, LoadingView } from "../../components/States";
import { canEditCases } from "../../app/permissions";
import { useWorkspaceRole } from "../../app/use-role";

function errorMessage(error: unknown): string {
  return error instanceof ApiClientError ? error.message : "Thao tác thất bại";
}

interface CaseRef {
  logical_key: string;
  revision_no: number;
}

export function SuitesPage({ workspaceId, suiteId }: { workspaceId: string; suiteId?: string }) {
  const api = useApi();
  const queryClient = useQueryClient();
  const role = useWorkspaceRole(workspaceId);
  const canEdit = canEditCases(role);

  const suitesQuery = useQuery({
    queryKey: ["suites", workspaceId],
    queryFn: () => api.listSuites(workspaceId),
  });
  const casesQuery = useQuery({
    queryKey: ["cases", workspaceId],
    queryFn: () => api.listCases(workspaceId),
  });
  const datasetsQuery = useQuery({
    queryKey: ["datasets", workspaceId],
    queryFn: () => api.listDatasets(workspaceId),
  });
  const fixturesQuery = useQuery({
    queryKey: ["fixtures", workspaceId],
    queryFn: () => api.listFixtures(workspaceId),
  });
  const revisionsQuery = useQuery({
    queryKey: ["suite-revisions", workspaceId, suiteId],
    queryFn: () => api.listSuiteRevisions(workspaceId, suiteId as string),
    enabled: Boolean(suiteId),
  });

  const [caseRefs, setCaseRefs] = useState<CaseRef[]>([]);
  const [datasetRef, setDatasetRef] = useState("");
  const [fixtureRefs, setFixtureRefs] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [bind, setBind] = useState<BindResult | null>(null);
  const [datasetKey, setDatasetKey] = useState("");
  const [datasetRows, setDatasetRows] = useState('[\n  {"item_name": "Việc A"}\n]');
  const [datasetMessage, setDatasetMessage] = useState<string | null>(null);

  const latestRevision =
    revisionsQuery.data?.filter((revision) => revision.lifecycle === "ready").at(-1) ?? null;
  const selectedCases = useMemo(() => casesQuery.data ?? [], [casesQuery.data]);

  async function createSuite(logicalKey: string) {
    setMessage(null);
    try {
      const created = await api.createSuite(workspaceId, logicalKey);
      await queryClient.invalidateQueries({ queryKey: ["suites", workspaceId] });
      return created;
    } catch (error) {
      setMessage(errorMessage(error));
      return null;
    }
  }

  async function saveRevision() {
    if (!suiteId) {
      return;
    }
    setMessage(null);
    try {
      await api.promoteSuiteRevision(workspaceId, suiteId, {
        schema_version: "suite/1",
        logical_key: suitesQuery.data?.find((item) => item.id === suiteId)?.logical_key ?? suiteId,
        case_refs: caseRefs,
        dataset_ref: datasetRef || null,
        fixture_refs: fixtureRefs
          .split(",")
          .map((item) => item.trim())
          .filter((item) => item !== ""),
      });
      setMessage("Đã tạo suite revision mới");
      await queryClient.invalidateQueries({ queryKey: ["suite-revisions", workspaceId, suiteId] });
    } catch (error) {
      setMessage(errorMessage(error));
    }
  }

  async function previewBind() {
    if (!suiteId || !latestRevision) {
      return;
    }
    setMessage(null);
    try {
      setBind(await api.bindSuite(workspaceId, suiteId, latestRevision.revision_id));
    } catch (error) {
      setMessage(errorMessage(error));
    }
  }

  async function saveDataset() {
    setDatasetMessage(null);
    try {
      const rows = JSON.parse(datasetRows) as unknown;
      if (
        !Array.isArray(rows) ||
        rows.some((row) => typeof row !== "object" || row === null || Array.isArray(row))
      ) {
        throw new Error("Rows phải là mảng object");
      }
      let datasetId = datasetsQuery.data?.find((item) => item.logical_key === datasetKey)?.id;
      if (!datasetId) {
        const created = await api.createDataset(workspaceId, datasetKey);
        datasetId = created.id;
        await queryClient.invalidateQueries({ queryKey: ["datasets", workspaceId] });
      }
      await api.promoteDatasetRevision(workspaceId, datasetId, {
        schema_version: "dataset/1",
        logical_key: datasetKey,
        rows,
      });
      setDatasetMessage(`Đã lưu dataset revision với ${rows.length} dòng`);
      setDatasetRef(datasetKey);
    } catch (error) {
      setDatasetMessage(errorMessage(error));
    }
  }

  if (suitesQuery.isLoading) {
    return <LoadingView label="Đang tải bộ ca" />;
  }
  if (suitesQuery.isError) {
    return <ErrorView message="Không tải được bộ ca" onRetry={() => void suitesQuery.refetch()} />;
  }
  const suites = suitesQuery.data ?? [];

  return (
    <div className="stack">
      <section className="panel">
        <h2 className="panel__title">Bộ ca</h2>
        {suites.length === 0 ? (
          <p className="muted">Chưa có bộ ca nào.</p>
        ) : (
          <ul>
            {suites.map((item) => (
              <li key={item.id}>
                <Link
                  to="/w/$workspaceId/suites/$suiteId"
                  params={{ workspaceId, suiteId: item.id }}
                  data-status={item.id === suiteId ? "active" : undefined}
                >
                  {item.logical_key}
                </Link>
              </li>
            ))}
          </ul>
        )}
        {canEdit ? (
          <CreateSuiteForm onCreate={(key) => void createSuite(key)} />
        ) : (
          <p className="muted">Vai trò hiện tại chỉ đọc bộ ca.</p>
        )}
        {message ? <p role="status">{message}</p> : null}
      </section>

      {suiteId ? (
        <>
          <section className="panel">
            <h3 className="panel__title">Revision mới nhất</h3>
            {latestRevision === null ? (
              <p className="muted">Bộ ca chưa có revision.</p>
            ) : (
              <p className="muted">
                v{latestRevision.revision_no} · digest {latestRevision.content_digest.slice(0, 12)}…
                · {JSON.stringify(latestRevision.content.case_refs ?? [])}
              </p>
            )}
            <button
              type="button"
              disabled={latestRevision === null}
              onClick={() => void previewBind()}
            >
              Bind preview
            </button>
            {bind ? (
              <div className="stack">
                <p>
                  {bind.executions.length} execution dự kiến · fixture:{" "}
                  {bind.fixture_refs.join(", ") || "—"}
                </p>
                {bind.facts.length > 0 ? (
                  <ul>
                    {bind.facts.map((fact) => (
                      <li key={fact} className="badge badge--danger">
                        {fact}
                      </li>
                    ))}
                  </ul>
                ) : null}
                <table>
                  <thead>
                    <tr>
                      <th>Execution key</th>
                      <th>Ca</th>
                      <th>Revision</th>
                      <th>Dòng dữ liệu</th>
                    </tr>
                  </thead>
                  <tbody>
                    {bind.executions.map((execution) => (
                      <tr key={execution.execution_key}>
                        <td>
                          <code>{execution.execution_key}</code>
                        </td>
                        <td>{execution.case_logical_key}</td>
                        <td>{execution.case_revision_id ? "đã pin" : "thiếu"}</td>
                        <td>{execution.dataset_row_index ?? "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : null}
          </section>

          {canEdit ? (
            <section className="panel">
              <h3 className="panel__title">Soạn revision mới</h3>
              <div className="stack">
                <div className="row">
                  <label className="stack" style={{ flex: 1 }}>
                    Ca (logical key)
                    <select
                      aria-label="Ca tham chiếu"
                      value={caseRefs.at(-1)?.logical_key ?? ""}
                      onChange={(event) => {
                        const key = event.target.value;
                        if (key) {
                          setCaseRefs((current) => [
                            ...current,
                            { logical_key: key, revision_no: 1 },
                          ]);
                        }
                      }}
                    >
                      <option value="">— Thêm ca —</option>
                      {selectedCases.map((item) => (
                        <option key={item.id} value={item.logical_key}>
                          {item.logical_key}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="stack">
                    Dataset ref
                    <select
                      value={datasetRef}
                      onChange={(event) => setDatasetRef(event.target.value)}
                    >
                      <option value="">—</option>
                      {(datasetsQuery.data ?? []).map((item) => (
                        <option key={item.id} value={item.logical_key}>
                          {item.logical_key}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="stack">
                    Fixture refs (phẩy)
                    <input
                      value={fixtureRefs}
                      list="fixture-options"
                      onChange={(event) => setFixtureRefs(event.target.value)}
                    />
                    <datalist id="fixture-options">
                      {(fixturesQuery.data ?? []).map((fixture) => (
                        <option key={fixture.id} value={fixture.logical_key} />
                      ))}
                    </datalist>
                  </label>
                </div>
                {caseRefs.length > 0 ? (
                  <table>
                    <thead>
                      <tr>
                        <th>Ca</th>
                        <th>Revision</th>
                        <th />
                      </tr>
                    </thead>
                    <tbody>
                      {caseRefs.map((ref, index) => (
                        <tr key={`${ref.logical_key}-${index}`}>
                          <td>{ref.logical_key}</td>
                          <td>
                            <input
                              aria-label={`Revision cho ${ref.logical_key}`}
                              type="number"
                              min={1}
                              value={ref.revision_no}
                              onChange={(event) =>
                                setCaseRefs((current) =>
                                  current.map((item, itemIndex) =>
                                    itemIndex === index
                                      ? { ...item, revision_no: Number(event.target.value) }
                                      : item,
                                  ),
                                )
                              }
                            />
                          </td>
                          <td>
                            <button
                              type="button"
                              onClick={() =>
                                setCaseRefs((current) =>
                                  current.filter((_, itemIndex) => itemIndex !== index),
                                )
                              }
                            >
                              Xoá
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                ) : null}
                <button type="button" data-variant="primary" onClick={() => void saveRevision()}>
                  Lưu revision mới
                </button>
              </div>
            </section>
          ) : null}

          <section className="panel">
            <h3 className="panel__title">Dataset rows</h3>
            <div className="stack">
              <label className="stack">
                Logical key dataset
                <input value={datasetKey} onChange={(event) => setDatasetKey(event.target.value)} />
              </label>
              <label className="stack">
                Rows (JSON array)
                <textarea
                  aria-label="Dataset rows"
                  value={datasetRows}
                  onChange={(event) => setDatasetRows(event.target.value)}
                />
              </label>
              <button
                type="button"
                disabled={!canEdit || datasetKey.trim() === ""}
                onClick={() => void saveDataset()}
              >
                Lưu dataset revision
              </button>
              {datasetMessage ? <p role="status">{datasetMessage}</p> : null}
            </div>
          </section>
        </>
      ) : (
        <EmptyView
          title="Chọn một bộ ca"
          hint="Chọn bộ ca để soạn revision, dataset rows và bind preview."
        />
      )}
    </div>
  );
}

function CreateSuiteForm({ onCreate }: { onCreate: (key: string) => void }) {
  const [key, setKey] = useState("");
  return (
    <div className="row">
      <label className="stack" style={{ flex: 1 }}>
        Logical key bộ ca mới
        <input value={key} onChange={(event) => setKey(event.target.value)} />
      </label>
      <button type="button" disabled={key.trim() === ""} onClick={() => onCreate(key)}>
        Tạo bộ ca
      </button>
    </div>
  );
}
