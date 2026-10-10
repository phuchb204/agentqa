import { useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "@tanstack/react-router";

import { ApiClientError } from "../../api/client";
import { useApi } from "../../api/context";
import type { ApplyResult, AuthoringJob, SourceRevision } from "../../api/types";
import { EmptyView, ErrorView, LoadingView } from "../../components/States";
import { canEditCases } from "../../app/permissions";
import { useWorkspaceRole } from "../../app/use-role";

function errorMessage(error: unknown): string {
  return error instanceof ApiClientError ? error.message : "Thao tác thất bại";
}

function contentField(content: Record<string, unknown>, field: string): string {
  const value = content[field];
  return value === undefined || value === null ? "" : String(value);
}

export function RequirementsPage({
  workspaceId,
  requirementId,
}: {
  workspaceId: string;
  requirementId?: string;
}) {
  const api = useApi();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const role = useWorkspaceRole(workspaceId);
  const canEdit = canEditCases(role);

  const requirementsQuery = useQuery({
    queryKey: ["requirements", workspaceId],
    queryFn: () => api.listRequirements(workspaceId),
  });
  const sourcesQuery = useQuery({
    queryKey: ["sources", workspaceId],
    queryFn: () => api.listSources(workspaceId),
  });
  const casesQuery = useQuery({
    queryKey: ["cases", workspaceId],
    queryFn: () => api.listCases(workspaceId),
  });
  const revisionsQuery = useQuery({
    queryKey: ["requirement-revisions", workspaceId, requirementId],
    queryFn: () => api.listRequirementRevisions(workspaceId, requirementId as string),
    enabled: Boolean(requirementId),
  });
  const impactQuery = useQuery({
    queryKey: ["requirement-impact", workspaceId, requirementId],
    queryFn: () => api.requirementImpact(workspaceId, requirementId as string),
    enabled: Boolean(requirementId),
  });
  const sourceRevisionsQuery = useQuery({
    queryKey: [
      "source-revisions",
      workspaceId,
      sourcesQuery.data?.map((item) => item.id).join(","),
    ],
    queryFn: async () => {
      const entries: { sourceId: string; logicalKey: string; latest: SourceRevision | null }[] = [];
      for (const source of sourcesQuery.data ?? []) {
        const revisions = await api.listSourceRevisions(workspaceId, source.id);
        entries.push({
          sourceId: source.id,
          logicalKey: source.logical_key,
          latest: revisions.at(-1) ?? null,
        });
      }
      return entries;
    },
    enabled: Boolean(sourcesQuery.data),
  });

  const [newSourceKey, setNewSourceKey] = useState("");
  const [uploadSourceId, setUploadSourceId] = useState("");
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [sourceMessage, setSourceMessage] = useState<string | null>(null);
  const [goal, setGoal] = useState("");
  const [expectations, setExpectations] = useState("");
  const [authoringSourceId, setAuthoringSourceId] = useState("");
  const [job, setJob] = useState<AuthoringJob | null>(null);
  const [authoringError, setAuthoringError] = useState<string | null>(null);
  const [targetCase, setTargetCase] = useState("");
  const [newCaseKey, setNewCaseKey] = useState("");
  const [applyResult, setApplyResult] = useState<ApplyResult | null>(null);

  const selected = useMemo(
    () => requirementsQuery.data?.find((item) => item.id === requirementId) ?? null,
    [requirementId, requirementsQuery.data],
  );
  const latestRevision =
    revisionsQuery.data?.filter((revision) => revision.lifecycle === "ready").at(-1) ?? null;
  const impact = impactQuery.data ?? null;

  async function createSource() {
    setSourceMessage(null);
    try {
      const created = await api.createSource(workspaceId, newSourceKey);
      setNewSourceKey("");
      setUploadSourceId(created.id);
      await queryClient.invalidateQueries({ queryKey: ["sources", workspaceId] });
    } catch (error) {
      setSourceMessage(errorMessage(error));
    }
  }

  async function upload() {
    if (!uploadFile || uploadSourceId === "") {
      return;
    }
    setSourceMessage(null);
    try {
      const detail = await api.uploadSource(
        workspaceId,
        uploadSourceId,
        uploadFile.name,
        uploadFile,
      );
      setSourceMessage(
        detail.revision.state === "extracted"
          ? `Đã trích xuất ${detail.segments.length} đoạn (privacy: ${detail.revision.privacy_class})`
          : `Trạng thái: ${detail.revision.state}${detail.revision.unextractable_reason ? ` (${detail.revision.unextractable_reason})` : ""}`,
      );
      setUploadFile(null);
      await queryClient.invalidateQueries({ queryKey: ["source-revisions"] });
    } catch (error) {
      setSourceMessage(errorMessage(error));
    }
  }

  async function proposeCases() {
    if (selected === null) {
      return;
    }
    setAuthoringError(null);
    setJob(null);
    setApplyResult(null);
    try {
      const sourceEntry = (sourceRevisionsQuery.data ?? []).find(
        (entry) => entry.sourceId === authoringSourceId,
      );
      const result = await api.createAuthoringJob(workspaceId, {
        goal,
        expectations: expectations
          .split("\n")
          .map((line) => line.trim())
          .filter((line) => line !== ""),
        requirement_keys: [selected.logical_key],
        sources:
          sourceEntry && sourceEntry.latest
            ? [{ source_id: sourceEntry.sourceId, revision_no: sourceEntry.latest.revision_no }]
            : [],
      });
      setJob(result);
    } catch (error) {
      setAuthoringError(errorMessage(error));
    }
  }

  async function applyProposal(proposalId: string) {
    setAuthoringError(null);
    try {
      let caseId = targetCase;
      if (caseId === "") {
        const created = await api.createCase(workspaceId, newCaseKey);
        caseId = created.id;
        await queryClient.invalidateQueries({ queryKey: ["cases", workspaceId] });
      }
      const result = await api.applyProposal(workspaceId, proposalId, caseId, 0);
      setApplyResult(result);
    } catch (error) {
      setAuthoringError(errorMessage(error));
    }
  }

  if (requirementsQuery.isLoading) {
    return <LoadingView label="Đang tải yêu cầu" />;
  }
  if (requirementsQuery.isError) {
    return (
      <ErrorView
        message="Không tải được yêu cầu"
        onRetry={() => void requirementsQuery.refetch()}
      />
    );
  }
  const requirements = requirementsQuery.data ?? [];

  return (
    <div className="stack">
      <section className="panel">
        <h2 className="panel__title">Yêu cầu</h2>
        {requirements.length === 0 ? (
          <p className="muted">Chưa có yêu cầu nào trong workspace.</p>
        ) : (
          <ul>
            {requirements.map((item) => (
              <li key={item.id}>
                <Link
                  to="/w/$workspaceId/requirements/$requirementId"
                  params={{ workspaceId, requirementId: item.id }}
                  data-status={item.id === requirementId ? "active" : undefined}
                >
                  {item.logical_key}
                </Link>
              </li>
            ))}
          </ul>
        )}
      </section>

      {requirementId ? (
        <>
          <section className="panel">
            <h3 className="panel__title">Revision mới nhất</h3>
            {latestRevision === null ? (
              <p className="muted">Yêu cầu chưa có revision.</p>
            ) : (
              <div className="stack">
                <p>{contentField(latestRevision.content, "text")}</p>
                <p className="muted">
                  Revision {latestRevision.revision_no} · digest{" "}
                  {latestRevision.content_digest.slice(0, 12)}… · author {latestRevision.author}
                </p>
                <h4>Tiêu chí nghiệm thu</h4>
                <ul>
                  {(Array.isArray(latestRevision.content.acceptance_statements)
                    ? (latestRevision.content.acceptance_statements as unknown[])
                    : []
                  ).map((statement, index) => (
                    <li key={index}>{String(statement)}</li>
                  ))}
                </ul>
                <h4>Source refs</h4>
                <p>
                  {(Array.isArray(latestRevision.content.source_refs)
                    ? (latestRevision.content.source_refs as unknown[])
                    : []
                  )
                    .map((item) => String(item))
                    .join(", ") || "—"}
                </p>
              </div>
            )}
          </section>

          <section className="panel">
            <h3 className="panel__title">Impact và coverage</h3>
            <p className="muted">
              Coverage theo liên kết ca–yêu cầu: {impact?.links.length ?? 0} ca liên kết. Đây không
              phải phần trăm coverage website.
            </p>
            {impact && impact.links.length > 0 ? (
              <table>
                <thead>
                  <tr>
                    <th>Ca</th>
                    <th>Revision</th>
                    <th>Trạng thái</th>
                    <th>Assertion bị ảnh hưởng</th>
                  </tr>
                </thead>
                <tbody>
                  {impact.links.map((link) => (
                    <tr key={link.case_revision_id}>
                      <td>
                        <Link
                          to="/w/$workspaceId/cases/$caseId"
                          params={{ workspaceId, caseId: link.case_id }}
                        >
                          {link.logical_key}
                        </Link>
                      </td>
                      <td>v{link.revision_no}</td>
                      <td>
                        {link.needs_review ? (
                          <span className="badge badge--warning">Cần xem lại theo yêu cầu mới</span>
                        ) : (
                          <span className="badge badge--passed">Theo yêu cầu hiện tại</span>
                        )}
                      </td>
                      <td>{link.affected_assertions.join(", ") || "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <p className="muted">Chưa có ca nào liên kết requirement này.</p>
            )}
          </section>

          <section className="panel">
            <h3 className="panel__title">Nguồn tài liệu</h3>
            {canEdit ? (
              <div className="row">
                <label className="stack" style={{ flex: 1 }}>
                  Logical key nguồn mới
                  <input
                    value={newSourceKey}
                    onChange={(event) => setNewSourceKey(event.target.value)}
                  />
                </label>
                <button
                  type="button"
                  disabled={newSourceKey.trim() === ""}
                  onClick={() => void createSource()}
                >
                  Tạo nguồn
                </button>
                <label className="stack" style={{ flex: 1 }}>
                  Nguồn để upload
                  <select
                    value={uploadSourceId}
                    onChange={(event) => setUploadSourceId(event.target.value)}
                  >
                    <option value="">—</option>
                    {(sourcesQuery.data ?? []).map((source) => (
                      <option key={source.id} value={source.id}>
                        {source.logical_key}
                      </option>
                    ))}
                  </select>
                </label>
                <input
                  aria-label="File nguồn"
                  type="file"
                  onChange={(event) => setUploadFile(event.target.files?.[0] ?? null)}
                />
                <button
                  type="button"
                  data-variant="primary"
                  disabled={!uploadFile || uploadSourceId === ""}
                  onClick={() => void upload()}
                >
                  Upload an toàn
                </button>
              </div>
            ) : null}
            {sourceMessage ? <p role="status">{sourceMessage}</p> : null}
            {(sourceRevisionsQuery.data ?? []).length === 0 ? (
              <p className="muted">Chưa có nguồn nào.</p>
            ) : (
              <table>
                <thead>
                  <tr>
                    <th>Nguồn</th>
                    <th>Revision</th>
                    <th>Trạng thái</th>
                    <th>Privacy</th>
                    <th>Segments</th>
                  </tr>
                </thead>
                <tbody>
                  {(sourceRevisionsQuery.data ?? []).map((entry) => (
                    <tr key={entry.sourceId}>
                      <td>{entry.logicalKey}</td>
                      <td>{entry.latest ? `v${entry.latest.revision_no}` : "—"}</td>
                      <td>{entry.latest?.state ?? "—"}</td>
                      <td>{entry.latest?.privacy_class ?? "—"}</td>
                      <td>{entry.latest?.segment_count ?? 0}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>

          <section className="panel">
            <h3 className="panel__title">Đề xuất ca từ yêu cầu</h3>
            {canEdit ? (
              <div className="stack">
                <label className="stack">
                  Mục tiêu
                  <textarea
                    aria-label="Mục tiêu đề xuất"
                    value={goal}
                    onChange={(event) => setGoal(event.target.value)}
                  />
                </label>
                <label className="stack">
                  Kỳ vọng (mỗi dòng một ý)
                  <textarea
                    aria-label="Kỳ vọng đề xuất"
                    value={expectations}
                    onChange={(event) => setExpectations(event.target.value)}
                  />
                </label>
                <label className="stack">
                  Nguồn tham chiếu
                  <select
                    value={authoringSourceId}
                    onChange={(event) => setAuthoringSourceId(event.target.value)}
                  >
                    <option value="">—</option>
                    {(sourceRevisionsQuery.data ?? []).map((entry) => (
                      <option key={entry.sourceId} value={entry.sourceId}>
                        {entry.logicalKey}
                      </option>
                    ))}
                  </select>
                </label>
                <button
                  type="button"
                  data-variant="primary"
                  disabled={goal.trim() === ""}
                  onClick={() => void proposeCases()}
                >
                  Đề xuất ca
                </button>
              </div>
            ) : (
              <p className="muted">Vai trò hiện tại không thể tạo đề xuất.</p>
            )}
            {authoringError ? (
              <p role="alert" style={{ color: "var(--color-danger)" }}>
                {authoringError}
              </p>
            ) : null}
            {job ? (
              <div className="stack">
                <p>
                  Job {job.job_id.slice(0, 8)} · {job.state}
                  {job.error_reason ? ` · ${job.error_reason}` : ""}
                </p>
                {job.proposals.map((proposal) => (
                  <article className="node-card" key={proposal.proposal_id}>
                    <div className="row">
                      <strong>{proposal.title}</strong>
                      <span className="badge">{proposal.case_kind}</span>
                      <span
                        className={`badge${proposal.status === "rejected" ? " badge--danger" : ""}`}
                      >
                        {proposal.status}
                        {proposal.rejection_reason ? `: ${proposal.rejection_reason}` : ""}
                      </span>
                    </div>
                    <p className="muted">
                      Provenance:{" "}
                      {proposal.provenance
                        .map((entry) => `${entry.path} (${entry.source})`)
                        .join(", ") || "—"}
                    </p>
                    {proposal.status === "proposed" ? (
                      <div className="row">
                        <select
                          aria-label={`Ca đích cho ${proposal.title}`}
                          value={targetCase}
                          onChange={(event) => setTargetCase(event.target.value)}
                        >
                          <option value="">— Tạo ca mới —</option>
                          {(casesQuery.data ?? []).map((item) => (
                            <option key={item.id} value={item.id}>
                              {item.logical_key}
                            </option>
                          ))}
                        </select>
                        {targetCase === "" ? (
                          <input
                            aria-label="Logical key ca mới"
                            placeholder="logical key ca mới"
                            value={newCaseKey}
                            onChange={(event) => setNewCaseKey(event.target.value)}
                          />
                        ) : null}
                        <button
                          type="button"
                          disabled={targetCase === "" && newCaseKey.trim() === ""}
                          onClick={() => void applyProposal(proposal.proposal_id)}
                        >
                          Áp dụng vào draft
                        </button>
                      </div>
                    ) : null}
                  </article>
                ))}
              </div>
            ) : null}
            {applyResult ? (
              <div className="stack">
                <h4>Diff áp dụng (edit_version {applyResult.edit_version})</h4>
                <ul className="diff-list">
                  {applyResult.diff.map((entry, index) => (
                    <li key={index}>
                      <code>{entry.op}</code> {entry.node_id ?? entry.name ?? entry.field ?? ""}
                      {entry.kind ? ` (${entry.kind})` : ""}
                    </li>
                  ))}
                </ul>
                <button
                  type="button"
                  onClick={() =>
                    void navigate({
                      to: "/w/$workspaceId/cases/$caseId",
                      params: { workspaceId, caseId: applyResult.case_id },
                    })
                  }
                >
                  Mở ca trong editor
                </button>
              </div>
            ) : null}
          </section>
        </>
      ) : (
        <EmptyView
          title="Chọn một yêu cầu"
          hint="Chọn yêu cầu ở danh sách phía trên để xem revision, impact và đề xuất ca."
        />
      )}
    </div>
  );
}
