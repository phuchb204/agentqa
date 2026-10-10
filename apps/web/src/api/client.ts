import createClient from "openapi-fetch";

import type { paths } from "../generated/schema";
import type {
  ApplyResult,
  ArtifactSummary,
  AuthoringJob,
  BindResult,
  DiffEntry,
  Draft,
  DraftRun,
  Entity,
  FieldError,
  Impact,
  Membership,
  Promotion,
  Revision,
  RunComparison,
  RunDetail,
  RunList,
  RunState,
  SessionInfo,
  SourceDetail,
  SourceRevision,
  Workspace,
} from "./types";

export class ApiClientError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly fieldErrors: FieldError[] = [],
  ) {
    super(message);
    this.name = "ApiClientError";
  }
}

type ClientResult = { data?: unknown; error?: unknown; response: Response };

export interface ApiClient {
  session(): Promise<SessionInfo | null>;
  ensureCsrf(): Promise<void>;
  login(username: string, password: string): Promise<{ csrfToken: string; user: SessionInfo }>;
  localBootstrap(nonce: string): Promise<{ csrfToken: string; user: SessionInfo }>;
  logout(): Promise<void>;
  listWorkspaces(): Promise<Workspace[]>;
  listMemberships(workspaceId: string): Promise<Membership[]>;
  listCases(workspaceId: string): Promise<Entity[]>;
  createCase(workspaceId: string, logicalKey: string): Promise<Entity>;
  getDraft(workspaceId: string, caseId: string): Promise<Draft | null>;
  saveDraft(
    workspaceId: string,
    caseId: string,
    content: unknown,
    editVersion: number,
  ): Promise<Draft>;
  promoteDraft(workspaceId: string, caseId: string, editVersion: number): Promise<Promotion>;
  listCaseRevisions(workspaceId: string, caseId: string): Promise<Revision[]>;
  confirmSources(
    workspaceId: string,
    caseId: string,
    names: string[],
    editVersion: number,
  ): Promise<Draft>;
  runDraft(
    workspaceId: string,
    caseId: string,
    idempotencyKey: string,
    environmentRevisionId?: string | null,
  ): Promise<DraftRun>;
  createAuthoringJob(workspaceId: string, payload: Record<string, unknown>): Promise<AuthoringJob>;
  getJob(workspaceId: string, jobId: string): Promise<AuthoringJob>;
  applyProposal(
    workspaceId: string,
    proposalId: string,
    caseId: string,
    editVersion: number,
  ): Promise<ApplyResult>;
  listRequirements(workspaceId: string): Promise<Entity[]>;
  listRequirementRevisions(workspaceId: string, requirementId: string): Promise<Revision[]>;
  promoteRequirementRevision(
    workspaceId: string,
    requirementId: string,
    content: unknown,
  ): Promise<Promotion>;
  requirementImpact(workspaceId: string, requirementId: string): Promise<Impact>;
  listSources(workspaceId: string): Promise<Entity[]>;
  createSource(workspaceId: string, logicalKey: string): Promise<Entity>;
  uploadSource(
    workspaceId: string,
    sourceId: string,
    logicalKey: string,
    file: File,
  ): Promise<SourceDetail>;
  listSourceRevisions(workspaceId: string, sourceId: string): Promise<SourceRevision[]>;
  getSourceRevision(
    workspaceId: string,
    sourceId: string,
    revisionNo: number,
  ): Promise<SourceDetail>;
  listSuites(workspaceId: string): Promise<Entity[]>;
  createSuite(workspaceId: string, logicalKey: string): Promise<Entity>;
  listSuiteRevisions(workspaceId: string, suiteId: string): Promise<Revision[]>;
  promoteSuiteRevision(workspaceId: string, suiteId: string, content: unknown): Promise<Promotion>;
  bindSuite(workspaceId: string, suiteId: string, revisionId: string): Promise<BindResult>;
  listDatasets(workspaceId: string): Promise<Entity[]>;
  createDataset(workspaceId: string, logicalKey: string): Promise<Entity>;
  listDatasetRevisions(workspaceId: string, datasetId: string): Promise<Revision[]>;
  promoteDatasetRevision(
    workspaceId: string,
    datasetId: string,
    content: unknown,
  ): Promise<Promotion>;
  listFixtures(workspaceId: string): Promise<Entity[]>;
  listApplications(workspaceId: string): Promise<Entity[]>;
  listEnvironmentRevisions(workspaceId: string, applicationId: string): Promise<Revision[]>;
  listRuns(
    workspaceId: string,
    filters: Record<string, string | boolean | undefined>,
  ): Promise<RunList>;
  getRunState(workspaceId: string, runId: string): Promise<RunState>;
  getRunDetail(workspaceId: string, runId: string): Promise<RunDetail>;
  compareRuns(workspaceId: string, runId: string, against: string): Promise<RunComparison>;
  requestControl(
    workspaceId: string,
    runId: string,
    action: string,
  ): Promise<{ control_id: string; control_revision: number }>;
  getArtifact(workspaceId: string, artifactId: string): Promise<ArtifactSummary>;
  artifactContentUrl(workspaceId: string, artifactId: string): string;
}

function fieldErrorsFrom(error: unknown): FieldError[] {
  if (
    error &&
    typeof error === "object" &&
    Array.isArray((error as { field_errors?: unknown }).field_errors)
  ) {
    return (error as { field_errors: FieldError[] }).field_errors;
  }
  return [];
}

export function createApiClient(
  options: { getCsrf?: () => string | null; setCsrf?: (token: string) => void } = {},
): ApiClient {
  const client = createClient<paths>({ baseUrl: "", credentials: "include" });
  client.use({
    onRequest({ request }) {
      if (request.method !== "GET" && request.method !== "HEAD") {
        const token = options.getCsrf?.();
        if (token) {
          request.headers.set("X-CSRF-Token", token);
        }
      }
      return request;
    },
  });

  async function unwrap<T>(result: ClientResult): Promise<T> {
    if (!result.response.ok || result.error !== undefined) {
      const body = (result.error ?? {}) as { code?: string; message?: string };
      throw new ApiClientError(
        result.response.status,
        body.code ?? "error",
        body.message ?? "Yêu cầu thất bại",
        fieldErrorsFrom(result.error),
      );
    }
    return result.data as T;
  }

  function ifMatch(editVersion: number): Record<string, string> {
    return { "If-Match": `"${editVersion}"` };
  }

  async function ensureCsrf(): Promise<void> {
    const result = await client.POST("/api/v1/auth/csrf");
    const body = await unwrap<{ csrf_token: string }>(result);
    options.setCsrf?.(body.csrf_token);
  }

  async function withCsrfRetry<T>(operation: () => Promise<T>): Promise<T> {
    try {
      return await operation();
    } catch (error) {
      if (error instanceof ApiClientError && error.status === 403 && /csrf/i.test(error.message)) {
        await ensureCsrf();
        return await operation();
      }
      throw error;
    }
  }

  return {
    async session() {
      const result = await client.GET("/api/v1/auth/session");
      if (result.response.status === 401) {
        return null;
      }
      const principal = await unwrap<{ user_id: string; username: string }>(result);
      return { user_id: principal.user_id, username: principal.username };
    },
    ensureCsrf,
    async login(username, password) {
      const result = await client.POST("/api/v1/auth/login", { body: { username, password } });
      const body = await unwrap<{ user_id: string; username: string; csrf_token: string | null }>(
        result,
      );
      return {
        csrfToken: body.csrf_token ?? "",
        user: { user_id: body.user_id, username: body.username },
      };
    },
    async localBootstrap(nonce) {
      const result = await client.POST("/api/v1/auth/local-bootstrap", { body: { nonce } });
      const body = await unwrap<{ user_id: string; username: string; csrf_token: string | null }>(
        result,
      );
      return {
        csrfToken: body.csrf_token ?? "",
        user: { user_id: body.user_id, username: body.username },
      };
    },
    async logout() {
      await client.POST("/api/v1/auth/logout");
    },
    async listWorkspaces() {
      const result = await client.GET("/api/v1/workspaces");
      return unwrap<Workspace[]>(result);
    },
    async listMemberships(workspaceId) {
      const result = await client.GET("/api/v1/workspaces/{workspace_id}/memberships", {
        params: { path: { workspace_id: workspaceId } },
      });
      return unwrap<Membership[]>(result);
    },
    async listCases(workspaceId) {
      const result = await client.GET("/api/v1/workspaces/{workspace_id}/cases", {
        params: { path: { workspace_id: workspaceId } },
      });
      return unwrap<Entity[]>(result);
    },
    async createCase(workspaceId, logicalKey) {
      const result = await client.POST("/api/v1/workspaces/{workspace_id}/cases", {
        params: { path: { workspace_id: workspaceId } },
        body: { logical_key: logicalKey },
      });
      return unwrap<Entity>(result);
    },
    async getDraft(workspaceId, caseId) {
      const result = await client.GET("/api/v1/workspaces/{workspace_id}/cases/{case_id}/draft", {
        params: { path: { workspace_id: workspaceId, case_id: caseId } },
      });
      if (result.response.status === 404) {
        return null;
      }
      return unwrap<Draft>(result);
    },
    async saveDraft(workspaceId, caseId, content, editVersion) {
      const result = await client.PATCH("/api/v1/workspaces/{workspace_id}/cases/{case_id}/draft", {
        params: { path: { workspace_id: workspaceId, case_id: caseId } },
        body: { content: content as Record<string, unknown> },
        headers: ifMatch(editVersion),
      });
      return unwrap<Draft>(result);
    },
    async promoteDraft(workspaceId, caseId, editVersion) {
      const result = await client.POST(
        "/api/v1/workspaces/{workspace_id}/cases/{case_id}/draft/promote",
        {
          params: { path: { workspace_id: workspaceId, case_id: caseId } },
          headers: ifMatch(editVersion),
        },
      );
      return unwrap<Promotion>(result);
    },
    async listCaseRevisions(workspaceId, caseId) {
      const result = await client.GET(
        "/api/v1/workspaces/{workspace_id}/cases/{case_id}/revisions",
        {
          params: { path: { workspace_id: workspaceId, case_id: caseId } },
        },
      );
      return unwrap<Revision[]>(result);
    },
    async confirmSources(workspaceId, caseId, names, editVersion) {
      const result = await client.POST(
        "/api/v1/workspaces/{workspace_id}/cases/{case_id}/draft/confirm-sources",
        {
          params: { path: { workspace_id: workspaceId, case_id: caseId } },
          body: { source_names: names },
          headers: ifMatch(editVersion),
        },
      );
      const body = await unwrap<{
        entity_id: string;
        edit_version: number;
        content: Record<string, unknown>;
      }>(result);
      return {
        entity_id: body.entity_id,
        edit_version: body.edit_version,
        content: body.content,
        updated_by: "",
        updated_at: new Date().toISOString(),
      };
    },
    async runDraft(workspaceId, caseId, idempotencyKey, environmentRevisionId) {
      const result = await client.POST(
        "/api/v1/workspaces/{workspace_id}/cases/{case_id}/draft/run",
        {
          params: { path: { workspace_id: workspaceId, case_id: caseId } },
          body: {
            idempotency_key: idempotencyKey,
            environment_revision_id: environmentRevisionId ?? null,
            gate_profile: "strict",
          },
        },
      );
      return unwrap<DraftRun>(result);
    },
    async createAuthoringJob(workspaceId, payload) {
      const result = await client.POST("/api/v1/workspaces/{workspace_id}/authoring-jobs", {
        params: { path: { workspace_id: workspaceId } },
        body: payload as never,
      });
      return unwrap<AuthoringJob>(result);
    },
    async getJob(workspaceId, jobId) {
      const result = await client.GET("/api/v1/workspaces/{workspace_id}/jobs/{job_id}", {
        params: { path: { workspace_id: workspaceId, job_id: jobId } },
      });
      return unwrap<AuthoringJob>(result);
    },
    async applyProposal(workspaceId, proposalId, caseId, editVersion) {
      const result = await client.POST(
        "/api/v1/workspaces/{workspace_id}/proposals/{proposal_id}/apply",
        {
          params: { path: { workspace_id: workspaceId, proposal_id: proposalId } },
          body: { case_id: caseId, expected_edit_version: editVersion },
          headers: ifMatch(editVersion),
        },
      );
      const body = await unwrap<{
        proposal_id: string;
        case_id: string;
        edit_version: number;
        content: Record<string, unknown>;
        diff: DiffEntry[];
      }>(result);
      return body;
    },
    async listRequirements(workspaceId) {
      const result = await client.GET("/api/v1/workspaces/{workspace_id}/{kind}s", {
        params: { path: { workspace_id: workspaceId, kind: "requirement" } },
      });
      return unwrap<Entity[]>(result);
    },
    async listRequirementRevisions(workspaceId, requirementId) {
      const result = await client.GET(
        "/api/v1/workspaces/{workspace_id}/{kind}s/{entity_id}/revisions",
        {
          params: {
            path: { workspace_id: workspaceId, kind: "requirement", entity_id: requirementId },
          },
        },
      );
      return unwrap<Revision[]>(result);
    },
    async promoteRequirementRevision(workspaceId, requirementId, content) {
      const result = await client.POST(
        "/api/v1/workspaces/{workspace_id}/{kind}s/{entity_id}/revisions",
        {
          params: {
            path: { workspace_id: workspaceId, kind: "requirement", entity_id: requirementId },
          },
          body: { content: content as Record<string, unknown> },
        },
      );
      return unwrap<Promotion>(result);
    },
    async requirementImpact(workspaceId, requirementId) {
      const result = await client.GET(
        "/api/v1/workspaces/{workspace_id}/requirements/{requirement_id}/impact",
        {
          params: { path: { workspace_id: workspaceId, requirement_id: requirementId } },
        },
      );
      return unwrap<Impact>(result);
    },
    async listSources(workspaceId) {
      const result = await client.GET("/api/v1/workspaces/{workspace_id}/sources", {
        params: { path: { workspace_id: workspaceId } },
      });
      return unwrap<Entity[]>(result);
    },
    async createSource(workspaceId, logicalKey) {
      const result = await client.POST("/api/v1/workspaces/{workspace_id}/sources", {
        params: { path: { workspace_id: workspaceId } },
        body: { logical_key: logicalKey },
      });
      return unwrap<Entity>(result);
    },
    async uploadSource(workspaceId, sourceId, logicalKey, file) {
      const form = new FormData();
      form.append("logical_key", logicalKey);
      form.append("file", file);
      const result = await client.POST(
        "/api/v1/workspaces/{workspace_id}/sources/{source_id}/revisions",
        {
          params: { path: { workspace_id: workspaceId, source_id: sourceId } },
          body: form as never,
          bodySerializer: (body) => body as unknown as FormData,
        },
      );
      return unwrap<SourceDetail>(result);
    },
    async listSourceRevisions(workspaceId, sourceId) {
      const result = await client.GET(
        "/api/v1/workspaces/{workspace_id}/sources/{source_id}/revisions",
        {
          params: { path: { workspace_id: workspaceId, source_id: sourceId } },
        },
      );
      return unwrap<SourceRevision[]>(result);
    },
    async getSourceRevision(workspaceId, sourceId, revisionNo) {
      const result = await client.GET(
        "/api/v1/workspaces/{workspace_id}/sources/{source_id}/revisions/{revision_no}",
        {
          params: {
            path: { workspace_id: workspaceId, source_id: sourceId, revision_no: revisionNo },
          },
        },
      );
      return unwrap<SourceDetail>(result);
    },
    async listSuites(workspaceId) {
      const result = await client.GET("/api/v1/workspaces/{workspace_id}/{kind}s", {
        params: { path: { workspace_id: workspaceId, kind: "suite" } },
      });
      return unwrap<Entity[]>(result);
    },
    async createSuite(workspaceId, logicalKey) {
      const result = await client.POST("/api/v1/workspaces/{workspace_id}/{kind}s", {
        params: { path: { workspace_id: workspaceId, kind: "suite" } },
        body: { logical_key: logicalKey },
      });
      return unwrap<Entity>(result);
    },
    async listSuiteRevisions(workspaceId, suiteId) {
      const result = await client.GET(
        "/api/v1/workspaces/{workspace_id}/{kind}s/{entity_id}/revisions",
        {
          params: { path: { workspace_id: workspaceId, kind: "suite", entity_id: suiteId } },
        },
      );
      return unwrap<Revision[]>(result);
    },
    async promoteSuiteRevision(workspaceId, suiteId, content) {
      const result = await client.POST(
        "/api/v1/workspaces/{workspace_id}/{kind}s/{entity_id}/revisions",
        {
          params: { path: { workspace_id: workspaceId, kind: "suite", entity_id: suiteId } },
          body: { content: content as Record<string, unknown> },
        },
      );
      return unwrap<Promotion>(result);
    },
    async bindSuite(workspaceId, suiteId, revisionId) {
      const result = await client.POST(
        "/api/v1/workspaces/{workspace_id}/suites/{suite_id}/revisions/{revision_id}/bind",
        {
          params: {
            path: { workspace_id: workspaceId, suite_id: suiteId, revision_id: revisionId },
          },
        },
      );
      return unwrap<BindResult>(result);
    },
    async listDatasets(workspaceId) {
      const result = await client.GET("/api/v1/workspaces/{workspace_id}/{kind}s", {
        params: { path: { workspace_id: workspaceId, kind: "dataset" } },
      });
      return unwrap<Entity[]>(result);
    },
    async createDataset(workspaceId, logicalKey) {
      const result = await client.POST("/api/v1/workspaces/{workspace_id}/{kind}s", {
        params: { path: { workspace_id: workspaceId, kind: "dataset" } },
        body: { logical_key: logicalKey },
      });
      return unwrap<Entity>(result);
    },
    async listDatasetRevisions(workspaceId, datasetId) {
      const result = await client.GET(
        "/api/v1/workspaces/{workspace_id}/{kind}s/{entity_id}/revisions",
        {
          params: { path: { workspace_id: workspaceId, kind: "dataset", entity_id: datasetId } },
        },
      );
      return unwrap<Revision[]>(result);
    },
    async promoteDatasetRevision(workspaceId, datasetId, content) {
      const result = await client.POST(
        "/api/v1/workspaces/{workspace_id}/{kind}s/{entity_id}/revisions",
        {
          params: { path: { workspace_id: workspaceId, kind: "dataset", entity_id: datasetId } },
          body: { content: content as Record<string, unknown> },
        },
      );
      return unwrap<Promotion>(result);
    },
    async listFixtures(workspaceId) {
      const result = await client.GET("/api/v1/workspaces/{workspace_id}/{kind}s", {
        params: { path: { workspace_id: workspaceId, kind: "fixture" } },
      });
      return unwrap<Entity[]>(result);
    },
    async listApplications(workspaceId) {
      const result = await client.GET("/api/v1/workspaces/{workspace_id}/applications", {
        params: { path: { workspace_id: workspaceId } },
      });
      return unwrap<Entity[]>(result);
    },
    async listEnvironmentRevisions(workspaceId, applicationId) {
      const result = await client.GET(
        "/api/v1/workspaces/{workspace_id}/applications/{application_id}/environment-revisions",
        { params: { path: { workspace_id: workspaceId, application_id: applicationId } } },
      );
      return unwrap<Revision[]>(result);
    },
    async listRuns(workspaceId, filters) {
      const query: Record<string, string | number | boolean> = {};
      for (const [key, value] of Object.entries(filters)) {
        if (value === undefined || value === "" || value === null) {
          continue;
        }
        query[key] = value;
      }
      const result = await client.GET("/api/v1/workspaces/{workspace_id}/runs", {
        params: { path: { workspace_id: workspaceId }, query: query as never },
      });
      return unwrap<RunList>(result);
    },
    async getRunState(workspaceId, runId) {
      const result = await client.GET("/api/v1/workspaces/{workspace_id}/runs/{run_id}", {
        params: { path: { workspace_id: workspaceId, run_id: runId } },
      });
      return unwrap<RunState>(result);
    },
    async getRunDetail(workspaceId, runId) {
      const result = await client.GET("/api/v1/workspaces/{workspace_id}/runs/{run_id}/detail", {
        params: { path: { workspace_id: workspaceId, run_id: runId } },
      });
      return unwrap<RunDetail>(result);
    },
    async compareRuns(workspaceId, runId, against) {
      const result = await client.GET(
        "/api/v1/workspaces/{workspace_id}/runs/{run_id}/comparison",
        {
          params: { path: { workspace_id: workspaceId, run_id: runId }, query: { against } },
        },
      );
      return unwrap<RunComparison>(result);
    },
    async requestControl(workspaceId, runId, action) {
      return withCsrfRetry(async () => {
        const result = await client.POST(
          "/api/v1/workspaces/{workspace_id}/runs/{run_id}/controls",
          {
            params: { path: { workspace_id: workspaceId, run_id: runId } },
            body: { action, reason: null } as never,
          },
        );
        return unwrap<{ control_id: string; control_revision: number }>(result);
      });
    },
    async getArtifact(workspaceId, artifactId) {
      const result = await client.GET("/api/v1/workspaces/{workspace_id}/artifacts/{artifact_id}", {
        params: { path: { workspace_id: workspaceId, artifact_id: artifactId } },
      });
      return unwrap<ArtifactSummary>(result);
    },
    artifactContentUrl(workspaceId, artifactId) {
      return `/api/v1/workspaces/${workspaceId}/artifacts/${artifactId}/content`;
    },
  };
}
