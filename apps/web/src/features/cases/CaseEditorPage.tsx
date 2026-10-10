import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";

import { ApiClientError } from "../../api/client";
import { useApi } from "../../api/context";
import type { DraftRun, Promotion } from "../../api/types";
import { Modal } from "../../components/Modal";
import { Tabs } from "../../components/Tabs";
import { EmptyView, ErrorView, LoadingView } from "../../components/States";
import { canEditCases, canPromoteCases, canRunCases } from "../../app/permissions";
import { useWorkspaceRole } from "../../app/use-role";
import { listSources, requiredAssertions } from "./editor/content-ops";
import { editorReducer, initialEditorState } from "./editor/reducer";
import { StructuredView } from "./editor/StructuredView";
import { YamlEditor } from "./editor/YamlEditor";
import { parseCaseYaml, serializeCaseYaml, validateCaseContent } from "./editor/yaml";

function errorMessage(error: unknown): string {
  return error instanceof ApiClientError ? error.message : "Thao tác thất bại";
}

export function CaseEditorPage({ workspaceId, caseId }: { workspaceId: string; caseId: string }) {
  const api = useApi();
  const queryClient = useQueryClient();
  const role = useWorkspaceRole(workspaceId);
  const canEdit = canEditCases(role);
  const canPromote = canPromoteCases(role);
  const canRun = canRunCases(role);

  const [state, dispatch] = useReducer(editorReducer, initialEditorState);
  const [tab, setTab] = useState("structured");
  const [yamlText, setYamlText] = useState("");
  const [yamlError, setYamlError] = useState<string | null>(null);
  const [promoteOpen, setPromoteOpen] = useState(false);
  const [promoteReceipt, setPromoteReceipt] = useState<Promotion | null>(null);
  const [promoteError, setPromoteError] = useState<string | null>(null);
  const [draftRun, setDraftRun] = useState<DraftRun | null>(null);
  const [runError, setRunError] = useState<string | null>(null);
  const [environments, setEnvironments] = useState<{ id: string; label: string }[]>([]);
  const [selectedEnvironment, setSelectedEnvironment] = useState("");
  const savingRef = useRef(false);

  const revisionsQuery = useQuery({
    queryKey: ["case-revisions", workspaceId, caseId],
    queryFn: () => api.listCaseRevisions(workspaceId, caseId),
  });
  const draftQuery = useQuery({
    queryKey: ["case-draft", workspaceId, caseId],
    queryFn: () => api.getDraft(workspaceId, caseId),
  });

  useEffect(() => {
    if (draftQuery.data) {
      dispatch({ type: "load_draft", draft: draftQuery.data });
    } else if (revisionsQuery.data) {
      const latest =
        revisionsQuery.data.filter((revision) => revision.lifecycle === "ready").at(-1) ?? null;
      dispatch({ type: "load_ready", revision: latest });
    }
  }, [draftQuery.data, revisionsQuery.data]);

  useEffect(() => {
    if (state.mode !== "draft" || state.content === null) {
      return;
    }
    dispatch({ type: "validation", issues: validateCaseContent(state.content) });
  }, [state.content, state.mode]);

  useEffect(() => {
    if (state.content === null) {
      return;
    }
    setYamlText(serializeCaseYaml(state.content));
    setYamlError(null);
  }, [state.content]);

  const save = useCallback(async () => {
    if (state.content === null || state.mode !== "draft" || savingRef.current) {
      return;
    }
    savingRef.current = true;
    dispatch({ type: "save_started" });
    try {
      const draft = await api.saveDraft(workspaceId, caseId, state.content, state.editVersion);
      dispatch({ type: "saved", draft });
      await queryClient.invalidateQueries({ queryKey: ["case-draft", workspaceId, caseId] });
    } catch (error) {
      if (error instanceof ApiClientError && error.status === 412) {
        const remote = await api.getDraft(workspaceId, caseId);
        if (remote) {
          dispatch({ type: "conflict", remote });
        } else {
          dispatch({ type: "save_failed", message: "Bản trên server đã thay đổi" });
        }
      } else {
        dispatch({ type: "save_failed", message: errorMessage(error) });
      }
    } finally {
      savingRef.current = false;
    }
  }, [api, caseId, queryClient, state.content, state.editVersion, state.mode, workspaceId]);

  useEffect(() => {
    if (
      state.mode !== "draft" ||
      !state.dirty ||
      state.validation.length > 0 ||
      state.conflict !== null ||
      savingRef.current
    ) {
      return;
    }
    const handle = window.setTimeout(() => void save(), 800);
    return () => window.clearTimeout(handle);
  }, [save, state.conflict, state.dirty, state.mode, state.validation]);

  useEffect(() => {
    if (state.mode !== "draft") {
      return;
    }
    void (async () => {
      try {
        const applications = await api.listApplications(workspaceId);
        const options: { id: string; label: string }[] = [];
        for (const application of applications) {
          const revisions = await api.listEnvironmentRevisions(workspaceId, application.id);
          const latest = revisions.filter((revision) => revision.lifecycle === "ready").at(-1);
          if (latest) {
            options.push({
              id: latest.revision_id,
              label: `${application.logical_key} · revision ${latest.revision_no}`,
            });
          }
        }
        setEnvironments(options);
        if (options.length > 0) {
          setSelectedEnvironment((current) => current || options[0].id);
        }
      } catch {
        setEnvironments([]);
      }
    })();
  }, [api, state.mode, workspaceId]);

  const sources = useMemo(() => (state.content ? listSources(state.content) : []), [state.content]);
  const unconfirmed = sources.filter(
    (source) => source.provenance === "inferred" && !source.confirmationRef,
  );
  const required = useMemo(
    () => (state.content ? requiredAssertions(state.content) : []),
    [state.content],
  );

  async function createDraft() {
    if (state.content === null) {
      return;
    }
    dispatch({ type: "save_started" });
    try {
      const draft = await api.saveDraft(workspaceId, caseId, state.content, 0);
      dispatch({ type: "saved", draft });
      await queryClient.invalidateQueries({ queryKey: ["case-draft", workspaceId, caseId] });
    } catch (error) {
      dispatch({ type: "save_failed", message: errorMessage(error) });
    }
  }

  async function confirmSources() {
    if (state.mode !== "draft" || unconfirmed.length === 0) {
      return;
    }
    try {
      const draft = await api.confirmSources(
        workspaceId,
        caseId,
        unconfirmed.map((source) => source.name),
        state.editVersion,
      );
      dispatch({ type: "saved", draft });
      await queryClient.invalidateQueries({ queryKey: ["case-draft", workspaceId, caseId] });
    } catch (error) {
      setPromoteError(errorMessage(error));
    }
  }

  async function promote() {
    if (state.mode !== "draft") {
      return;
    }
    setPromoteError(null);
    try {
      const receipt = await api.promoteDraft(workspaceId, caseId, state.editVersion);
      setPromoteReceipt(receipt);
      setPromoteOpen(false);
      await queryClient.invalidateQueries({ queryKey: ["case-revisions", workspaceId, caseId] });
    } catch (error) {
      setPromoteError(errorMessage(error));
    }
  }

  async function startDraftRun() {
    if (state.mode !== "draft") {
      return;
    }
    setRunError(null);
    try {
      const result = await api.runDraft(
        workspaceId,
        caseId,
        crypto.randomUUID(),
        selectedEnvironment || null,
      );
      setDraftRun(result);
    } catch (error) {
      setRunError(errorMessage(error));
    }
  }

  function onYamlChange(text: string) {
    setYamlText(text);
    const parsed = parseCaseYaml(text);
    if (!parsed.ok) {
      setYamlError(parsed.message);
      dispatch({ type: "validation", issues: [{ path: "/", message: parsed.message }] });
      return;
    }
    const issues = validateCaseContent(parsed.content);
    if (issues.length > 0) {
      setYamlError(`${issues[0].path}: ${issues[0].message}`);
      dispatch({ type: "validation", issues });
      return;
    }
    setYamlError(null);
    dispatch({ type: "edit", content: parsed.content });
  }

  if (revisionsQuery.isLoading || draftQuery.isLoading) {
    return <LoadingView label="Đang tải ca kiểm thử" />;
  }
  if (revisionsQuery.isError) {
    return (
      <ErrorView
        message="Không tải được revision của ca"
        onRetry={() => void revisionsQuery.refetch()}
      />
    );
  }
  if (state.mode === "empty" || state.content === null) {
    return (
      <EmptyView
        title="Ca chưa có nội dung"
        hint="Tạo draft hoặc đề xuất ca từ trang Yêu cầu để bắt đầu."
        action={
          canEdit ? (
            <button
              type="button"
              data-variant="primary"
              onClick={() =>
                dispatch({
                  type: "edit",
                  content: {
                    schema_version: "case/1",
                    nodes: [],
                    completion: { required_nodes: [], required_assertions: [] },
                  },
                })
              }
            >
              Tạo nội dung trống
            </button>
          ) : null
        }
      />
    );
  }

  const saveLabel =
    state.saveState === "saving"
      ? "Đang lưu…"
      : state.saveState === "saved"
        ? "Đã lưu"
        : state.saveState === "error"
          ? "Lỗi lưu"
          : state.dirty
            ? "Có thay đổi chưa lưu"
            : "Đã đồng bộ";

  return (
    <div className="stack">
      <section className="panel">
        <div className="row">
          <h2 className="panel__title">Ca: {String(state.content.logical_key ?? caseId)}</h2>
          <span className="badge">
            {state.mode === "ready" ? "Ready (chỉ đọc)" : `Draft v${state.editVersion}`}
          </span>
          {state.dirty ? <span className="badge badge--warning">Chưa lưu</span> : null}
          <span className="muted" role="status" aria-live="polite">
            {saveLabel}
          </span>
          <div className="app-shell__spacer" />
          {state.mode === "ready" && canEdit ? (
            <button type="button" data-variant="primary" onClick={() => void createDraft()}>
              Tạo bản chỉnh sửa
            </button>
          ) : null}
          {state.mode === "draft" ? (
            <>
              <button
                type="button"
                disabled={state.history.length === 0}
                onClick={() => dispatch({ type: "undo" })}
              >
                Hoàn tác
              </button>
              <button
                type="button"
                disabled={state.future.length === 0}
                onClick={() => dispatch({ type: "redo" })}
              >
                Làm lại
              </button>
              <button
                type="button"
                disabled={!state.dirty || state.validation.length > 0}
                onClick={() => void save()}
              >
                Lưu
              </button>
              <button
                type="button"
                data-variant="primary"
                disabled={!canPromote || state.dirty || state.validation.length > 0}
                onClick={() => setPromoteOpen(true)}
              >
                Promote…
              </button>
            </>
          ) : null}
        </div>
        {promoteReceipt ? (
          <p role="status" className="badge badge--passed">
            Đã promote revision {promoteReceipt.revision_no} · digest{" "}
            {promoteReceipt.content_digest.slice(0, 12)}…
          </p>
        ) : null}
      </section>

      {state.conflict ? (
        <section className="panel" role="alert">
          <h3 className="panel__title">Xung đột phiên bản với server</h3>
          <p>
            Bản server đang ở edit_version {state.conflict.edit_version}. Bản local của bạn được giữ
            nguyên, không tự ghi đè.
          </p>
          <div className="row">
            <button type="button" onClick={() => dispatch({ type: "resolve_keep_local" })}>
              Giữ bản của tôi (lưu lại trên bản server mới)
            </button>
            <button type="button" onClick={() => dispatch({ type: "resolve_use_remote" })}>
              Dùng bản server
            </button>
          </div>
        </section>
      ) : null}

      <div className="editor-grid">
        <section className="panel">
          <Tabs
            value={tab}
            onValueChange={setTab}
            items={[
              {
                value: "structured",
                label: "Cấu trúc",
                content: (
                  <StructuredView
                    content={state.content}
                    readOnly={state.mode !== "draft" || !canEdit}
                    onEdit={(next) => dispatch({ type: "edit", content: next })}
                  />
                ),
              },
              {
                value: "yaml",
                label: "YAML",
                content: (
                  <div className="stack">
                    <YamlEditor value={yamlText} onChange={onYamlChange} />
                    {yamlError ? (
                      <p role="alert" style={{ color: "var(--color-danger)" }}>
                        YAML chưa hợp lệ, buffer được giữ nguyên: {yamlError}
                      </p>
                    ) : null}
                  </div>
                ),
              },
            ]}
          />
        </section>

        <aside className="stack">
          <section className="panel">
            <h3 className="panel__title">Validation</h3>
            {state.validation.length === 0 ? (
              <p className="badge badge--passed">Nội dung hợp lệ theo case/1</p>
            ) : (
              <ul>
                {state.validation.map((issue) => (
                  <li key={`${issue.path}:${issue.message}`}>
                    <code>{issue.path}</code> — {issue.message}
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section className="panel">
            <h3 className="panel__title">Assertion bắt buộc</h3>
            {required.length === 0 ? (
              <p className="muted">Chưa khai báo assertion bắt buộc.</p>
            ) : (
              <p>{required.join(", ")}</p>
            )}
            <h3 className="panel__title">Nguồn suy luận</h3>
            {unconfirmed.length === 0 ? (
              <p className="muted">Không còn nguồn suy luận chưa xác nhận.</p>
            ) : (
              <ul>
                {unconfirmed.map((source) => (
                  <li key={source.name}>
                    {source.name} <span className="badge badge--warning">Suy luận từ quan sát</span>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section className="panel">
            <h3 className="panel__title">Chạy thử draft</h3>
            {state.mode !== "draft" ? (
              <p className="muted">Chạy thử chỉ áp dụng cho draft.</p>
            ) : (
              <div className="stack">
                <label className="stack">
                  Environment
                  <select
                    aria-label="Chọn environment"
                    value={selectedEnvironment}
                    onChange={(event) => setSelectedEnvironment(event.target.value)}
                  >
                    <option value="">— Không chỉ định —</option>
                    {environments.map((environment) => (
                      <option key={environment.id} value={environment.id}>
                        {environment.label}
                      </option>
                    ))}
                  </select>
                </label>
                <button
                  type="button"
                  disabled={!canRun || state.dirty || state.validation.length > 0}
                  onClick={() => void startDraftRun()}
                >
                  Chạy thử (provisional)
                </button>
                {draftRun ? (
                  <p role="status">
                    <span className="badge badge--provisional">Thử nghiệm</span> run{" "}
                    {draftRun.run_id.slice(0, 8)} · provisional={String(draftRun.provisional)} ·{" "}
                    {draftRun.planned_executions} execution
                  </p>
                ) : null}
                {runError ? (
                  <p role="alert" style={{ color: "var(--color-danger)" }}>
                    {runError}
                  </p>
                ) : null}
              </div>
            )}
          </section>

          <section className="panel">
            <h3 className="panel__title">Revision</h3>
            <ul>
              {(revisionsQuery.data ?? []).map((revision) => (
                <li key={revision.revision_id}>
                  v{revision.revision_no} · {revision.lifecycle} ·{" "}
                  {revision.content_digest.slice(0, 12)}…
                </li>
              ))}
            </ul>
            <Link to="/w/$workspaceId/cases" params={{ workspaceId }}>
              ← Danh sách ca
            </Link>
          </section>
        </aside>
      </div>

      <Modal
        open={promoteOpen}
        onOpenChange={setPromoteOpen}
        title="Promote draft thành ready"
        description="Kiểm tra kỳ vọng và nguồn trước khi tạo revision bất biến."
      >
        <div className="stack">
          <p>
            Assertion bắt buộc: {required.length > 0 ? required.join(", ") : "chưa có"} · Nguồn chờ
            xác nhận: {unconfirmed.length}
          </p>
          {unconfirmed.length > 0 ? (
            <button type="button" onClick={() => void confirmSources()}>
              Xác nhận nguồn suy luận ({unconfirmed.map((source) => source.name).join(", ")})
            </button>
          ) : null}
          <button
            type="button"
            data-variant="primary"
            disabled={unconfirmed.length > 0 || state.validation.length > 0 || state.dirty}
            onClick={() => void promote()}
          >
            Promote revision
          </button>
          {promoteError ? (
            <p role="alert" style={{ color: "var(--color-danger)" }}>
              {promoteError}
            </p>
          ) : null}
        </div>
      </Modal>
    </div>
  );
}

export function CasesListPage({ workspaceId }: { workspaceId: string }) {
  const api = useApi();
  const role = useWorkspaceRole(workspaceId);
  const canEdit = canEditCases(role);
  const [logicalKey, setLogicalKey] = useState("");
  const [error, setError] = useState<string | null>(null);
  const queryClient = useQueryClient();
  const casesQuery = useQuery({
    queryKey: ["cases", workspaceId],
    queryFn: () => api.listCases(workspaceId),
  });

  async function createCase() {
    setError(null);
    try {
      await api.createCase(workspaceId, logicalKey);
      setLogicalKey("");
      await queryClient.invalidateQueries({ queryKey: ["cases", workspaceId] });
    } catch (caught) {
      setError(errorMessage(caught));
    }
  }

  if (casesQuery.isLoading) {
    return <LoadingView label="Đang tải danh sách ca" />;
  }
  if (casesQuery.isError) {
    return (
      <ErrorView message="Không tải được danh sách ca" onRetry={() => void casesQuery.refetch()} />
    );
  }
  const cases = casesQuery.data ?? [];
  return (
    <div className="stack">
      <section className="panel">
        <h2 className="panel__title">Ca kiểm thử</h2>
        {canEdit ? (
          <div className="row">
            <label className="stack" style={{ flex: 1 }}>
              Logical key ca mới
              <input value={logicalKey} onChange={(event) => setLogicalKey(event.target.value)} />
            </label>
            <button
              type="button"
              data-variant="primary"
              disabled={logicalKey.trim() === ""}
              onClick={() => void createCase()}
            >
              Tạo ca
            </button>
          </div>
        ) : (
          <p className="muted">Vai trò hiện tại chỉ đọc ca.</p>
        )}
        {error ? (
          <p role="alert" style={{ color: "var(--color-danger)" }}>
            {error}
          </p>
        ) : null}
      </section>
      {cases.length === 0 ? (
        <EmptyView title="Chưa có ca" hint="Tạo ca mới hoặc áp dụng đề xuất từ trang Yêu cầu." />
      ) : (
        <section className="panel">
          <ul>
            {cases.map((item) => (
              <li key={item.id}>
                <Link to="/w/$workspaceId/cases/$caseId" params={{ workspaceId, caseId: item.id }}>
                  {item.logical_key}
                </Link>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
