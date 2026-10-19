import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";

import { ApiClientError } from "../../api/client";
import { useApi } from "../../api/context";
import { useWorkspaceRole } from "../../app/use-role";
import { canManageSettings } from "../../app/permissions";

function errorMessage(error: unknown): string {
  return error instanceof ApiClientError ? error.message : "Thao tác thất bại";
}

const SECTIONS = [
  { key: "references", label: "Credential references" },
  { key: "providers", label: "Providers" },
  { key: "workers", label: "Workers & health" },
  { key: "retention", label: "Retention" },
] as const;

export function SettingsPage({ workspaceId, section }: { workspaceId: string; section: string }) {
  const role = useWorkspaceRole(workspaceId);
  const canManage = canManageSettings(role);
  const active = SECTIONS.some((item) => item.key === section) ? section : "references";

  return (
    <div className="stack">
      <section className="panel">
        <h2 className="panel__title">Cài đặt</h2>
        <nav className="row" aria-label="Mục cài đặt">
          {SECTIONS.map((item) => (
            <Link
              key={item.key}
              to="/w/$workspaceId/settings/$section"
              params={{ workspaceId, section: item.key }}
              data-status={active === item.key ? "active" : undefined}
              data-testid={`settings-tab-${item.key}`}
            >
              {item.label}
            </Link>
          ))}
        </nav>
      </section>
      {active === "references" ? (
        <ReferencesSection workspaceId={workspaceId} canManage={canManage} />
      ) : null}
      {active === "providers" ? <ProvidersSection workspaceId={workspaceId} /> : null}
      {active === "workers" ? <WorkersSection /> : null}
      {active === "retention" ? <RetentionSection /> : null}
    </div>
  );
}

function ReferencesSection({
  workspaceId,
  canManage,
}: {
  workspaceId: string;
  canManage: boolean;
}) {
  const api = useApi();
  const queryClient = useQueryClient();
  const [credentialRef, setCredentialRef] = useState("opencode_go");
  const [envVarName, setEnvVarName] = useState("OPENCODE_GO_API_KEY");
  const [rotateValue, setRotateValue] = useState("");
  const [rotateTarget, setRotateTarget] = useState("");
  const [message, setMessage] = useState<string | null>(null);

  const referencesQuery = useQuery({
    queryKey: ["credential-references", workspaceId],
    queryFn: () => api.listCredentialReferences(workspaceId),
  });

  const createMutation = useMutation({
    mutationFn: () => api.createCredentialReference(workspaceId, credentialRef, envVarName),
    onSuccess: async () => {
      setMessage("Đã tạo credential reference (không hiển thị giá trị)");
      await queryClient.invalidateQueries({ queryKey: ["credential-references", workspaceId] });
    },
    onError: (error) => setMessage(errorMessage(error)),
  });

  const rotateMutation = useMutation({
    mutationFn: () => api.rotateCredentialReference(workspaceId, rotateTarget, rotateValue),
    onSuccess: async () => {
      setRotateValue("");
      setMessage("Đã tạo version mới; grant/admission của version cũ bị vô hiệu");
      await queryClient.invalidateQueries({ queryKey: ["credential-references", workspaceId] });
    },
    onError: (error) => setMessage(errorMessage(error)),
  });

  const revokeMutation = useMutation({
    mutationFn: (ref: string) => api.revokeCredentialReference(workspaceId, ref, "owner revoke"),
    onSuccess: async () => {
      setMessage("Đã thu hồi credential reference; grant đang hoạt động bị vô hiệu");
      await queryClient.invalidateQueries({ queryKey: ["credential-references", workspaceId] });
    },
    onError: (error) => setMessage(errorMessage(error)),
  });

  const references = referencesQuery.data ?? [];

  return (
    <section className="panel" data-testid="settings-references">
      <h3 className="panel__title">Credential references</h3>
      <p className="muted">
        Chỉ metadata được hiển thị; không có endpoint đọc giá trị credential. Rotation tạo version
        mới và vô hiệu grant cũ.
      </p>
      {referencesQuery.isLoading ? <p className="muted">Đang tải credential references…</p> : null}
      {referencesQuery.isError && canManage ? (
        <p className="muted">Không tải được credential references.</p>
      ) : null}
      {referencesQuery.isError && !canManage ? (
        <p className="muted" data-testid="settings-permission-note">
          Vai trò hiện tại không có quyền xem cấu hình credential; liên hệ chủ sở hữu workspace.
        </p>
      ) : null}
      {referencesQuery.isSuccess && references.length === 0 ? (
        <p className="muted">Chưa có credential reference nào.</p>
      ) : null}
      {referencesQuery.isSuccess && references.length > 0 ? (
        <table>
          <thead>
            <tr>
              <th>Reference</th>
              <th>Version</th>
              <th>Kind</th>
              <th>Status</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {references.map((item) => (
              <tr key={`${item.credential_ref}-${item.version}`}>
                <td>{item.credential_ref}</td>
                <td>v{item.version}</td>
                <td>{item.kind}</td>
                <td data-credential-status={item.status}>{item.status}</td>
                <td>
                  {canManage && item.status === "active" ? (
                    <button
                      type="button"
                      onClick={() => revokeMutation.mutate(item.credential_ref)}
                      disabled={revokeMutation.isPending}
                    >
                      Thu hồi
                    </button>
                  ) : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
      {canManage ? (
        <div className="stack">
          <div className="row">
            <label className="stack" style={{ flex: 1 }}>
              Reference mới
              <input
                aria-label="Credential reference"
                value={credentialRef}
                onChange={(event) => setCredentialRef(event.target.value)}
              />
            </label>
            <label className="stack" style={{ flex: 1 }}>
              Env var (local bind)
              <input
                aria-label="Env var"
                value={envVarName}
                onChange={(event) => setEnvVarName(event.target.value)}
              />
            </label>
            <button
              type="button"
              disabled={createMutation.isPending || credentialRef.trim() === ""}
              onClick={() => createMutation.mutate()}
            >
              Thêm reference
            </button>
          </div>
          <div className="row">
            <label className="stack" style={{ flex: 1 }}>
              Reference cần rotate
              <input
                aria-label="Rotate reference"
                value={rotateTarget}
                onChange={(event) => setRotateTarget(event.target.value)}
              />
            </label>
            <label className="stack" style={{ flex: 1 }}>
              Giá trị mới (không hiển thị lại)
              <input
                aria-label="Giá trị mới"
                type="password"
                value={rotateValue}
                onChange={(event) => setRotateValue(event.target.value)}
              />
            </label>
            <button
              type="button"
              disabled={
                rotateMutation.isPending || rotateTarget.trim() === "" || rotateValue === ""
              }
              onClick={() => rotateMutation.mutate()}
            >
              Rotate
            </button>
          </div>
          {message ? <p role="status">{message}</p> : null}
        </div>
      ) : referencesQuery.isError ? null : (
        <p className="muted">Vai trò hiện tại chỉ đọc cấu hình credential.</p>
      )}
    </section>
  );
}

const FIXED_PROVIDERS = [
  { route: "opencode_zen", model: "jev-1.13-free", refs: ["opencode_zen"], pair: "opencode" },
  { route: "opencode_go", model: "deepseek-v4.1-flash", refs: ["opencode_go"], pair: "opencode" },
  {
    route: "commandcode_systemone",
    model: "typesafe/jev",
    refs: ["commandcode"],
    pair: "commandcode",
  },
  {
    route: "commandcode_chat",
    model: "deepseek/deepseek-v4.1-flash",
    refs: ["commandcode"],
    pair: "commandcode",
  },
];

function ProvidersSection({ workspaceId }: { workspaceId: string }) {
  const api = useApi();
  const referencesQuery = useQuery({
    queryKey: ["credential-references", workspaceId],
    queryFn: () => api.listCredentialReferences(workspaceId),
  });
  const activeRefs = new Set(
    (referencesQuery.data ?? [])
      .filter((item) => item.status === "active")
      .map((item) => item.credential_ref),
  );
  const pending = referencesQuery.isPending;
  return (
    <section className="panel" data-testid="settings-providers">
      <h3 className="panel__title">Providers</h3>
      <p className="muted">
        Hai cặp route theo pair đang chọn (<code>AGENTQA_MODEL_PAIR</code>: opencode mặc định,
        commandcode dùng chung <code>AGENTQA_CMD_API_KEY</code>); không có fallback trả phí tự động.
        Readiness dựa trên credential reference đang active.
      </p>
      {referencesQuery.isError ? (
        <p className="muted" role="status">
          Không đọc được credential references
        </p>
      ) : null}
      <table>
        <thead>
          <tr>
            <th>Route</th>
            <th>Model</th>
            <th>Credential</th>
            <th>Readiness</th>
          </tr>
        </thead>
        <tbody>
          {FIXED_PROVIDERS.map((provider) => {
            const ready = provider.refs.some((ref) => activeRefs.has(ref));
            return (
              <tr key={provider.route}>
                <td>{provider.route}</td>
                <td>{provider.model}</td>
                <td>{provider.refs.join(", ")}</td>
                <td data-readiness={pending ? "loading" : ready ? "ready" : "missing"}>
                  {pending ? "Đang tải..." : ready ? "Đã cấu hình" : "Chưa cấu hình"}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </section>
  );
}

function WorkersSection() {
  const [health, setHealth] = useState<{ status: string; version: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    fetch("/health/live")
      .then((response) => (response.ok ? response.json() : Promise.reject(new Error("health lỗi"))))
      .then((body: { status: string; version: string }) => {
        if (!cancelled) {
          setHealth(body);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setError("Không đọc được health");
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);
  return (
    <section className="panel" data-testid="settings-workers">
      <h3 className="panel__title">Workers & health</h3>
      {error ? <p className="muted">{error}</p> : null}
      {health ? (
        <p>
          API: <strong>{health.status}</strong> · version {health.version}
        </p>
      ) : (
        <p className="muted">Đang đọc trạng thái API…</p>
      )}
      <p className="muted">
        Chi tiết readiness queue/worker/storage theo capability vận hành sẽ hiển thị khi API tương
        ứng được bật; UI không suy diễn trạng thái thay backend.
      </p>
    </section>
  );
}

function RetentionSection() {
  return (
    <section className="panel" data-testid="settings-retention">
      <h3 className="panel__title">Retention</h3>
      <p className="muted">
        Chưa có capability cấu hình retention trong phiên bản này; artifact lifecycle và tombstone
        được quản lý bởi dịch vụ vận hành. UI không hiển thị thao tác không được backend hỗ trợ.
      </p>
    </section>
  );
}
