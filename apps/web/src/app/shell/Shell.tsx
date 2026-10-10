import { useQuery } from "@tanstack/react-query";
import { Link, Outlet, useNavigate, useParams } from "@tanstack/react-router";
import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import { useApi } from "../../api/context";
import { EmptyView, ErrorView, LoadingView } from "../../components/States";
import { roleLabel } from "../permissions";
import { useSession } from "../session-context";
import { useTheme } from "../theme";
import { useWorkspaceRole } from "../use-role";

function ThemeControls() {
  const { theme, contrast, setTheme, setContrast } = useTheme();
  return (
    <div className="row" role="group" aria-label="Giao diện">
      <button
        type="button"
        aria-pressed={theme === "light"}
        onClick={() => setTheme("light")}
        data-variant={theme === "light" ? "primary" : undefined}
      >
        Sáng
      </button>
      <button
        type="button"
        aria-pressed={theme === "dark"}
        onClick={() => setTheme("dark")}
        data-variant={theme === "dark" ? "primary" : undefined}
      >
        Tối
      </button>
      <label className="row" style={{ gap: 4 }}>
        <input
          type="checkbox"
          checked={contrast === "high"}
          onChange={(event) => setContrast(event.target.checked ? "high" : "normal")}
        />
        Tương phản cao
      </label>
    </div>
  );
}

function UserMenu({ role }: { role: string | undefined }) {
  const { user, logout } = useSession();
  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger asChild>
        <button type="button" aria-label="Menu người dùng">
          {user.username} · {roleLabel(role as never)}
        </button>
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content className="panel" sideOffset={4}>
          <DropdownMenu.Item className="muted" disabled>
            Vai trò: {roleLabel(role as never)}
          </DropdownMenu.Item>
          <DropdownMenu.Item asChild>
            <button type="button" onClick={() => void logout()}>
              Đăng xuất
            </button>
          </DropdownMenu.Item>
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  );
}

const NAV_ITEMS = [
  { to: "/w/$workspaceId", label: "Tổng quan", exact: true },
  { to: "/w/$workspaceId/requirements", label: "Yêu cầu", exact: false },
  { to: "/w/$workspaceId/cases", label: "Ca kiểm thử", exact: false },
  { to: "/w/$workspaceId/suites", label: "Bộ ca", exact: false },
  { to: "/w/$workspaceId/runs", label: "Lượt chạy", exact: false },
  { to: "/w/$workspaceId/compare", label: "So sánh", exact: false },
] as const;

export function Shell() {
  const api = useApi();
  const navigate = useNavigate();
  const params = useParams({ strict: false }) as { workspaceId?: string };
  const workspaceId = params.workspaceId;

  const workspacesQuery = useQuery({
    queryKey: ["workspaces"],
    queryFn: () => api.listWorkspaces(),
  });
  const role = useWorkspaceRole(workspaceId);

  const workspaces = workspacesQuery.data ?? [];

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main">
        Bỏ qua điều hướng
      </a>
      <header className="app-shell__header">
        <span className="app-shell__brand">AgentQA</span>
        {workspaces.length > 0 ? (
          <label className="row">
            <span className="muted">Workspace</span>
            <select
              aria-label="Chọn workspace"
              value={workspaceId ?? ""}
              onChange={(event) => {
                const next = event.target.value;
                if (next) {
                  void navigate({ to: "/w/$workspaceId", params: { workspaceId: next } });
                }
              }}
            >
              {workspaceId ? null : <option value="">—</option>}
              {workspaces.map((workspace) => (
                <option key={workspace.id} value={workspace.id}>
                  {workspace.name}
                </option>
              ))}
            </select>
          </label>
        ) : null}
        <div className="app-shell__spacer" />
        <ThemeControls />
        <UserMenu role={role} />
      </header>
      {workspaceId ? (
        <nav className="app-shell__nav" aria-label="Điều hướng chính">
          {NAV_ITEMS.map((item) => (
            <Link
              key={item.to}
              to={item.to}
              params={{ workspaceId }}
              activeOptions={{ exact: item.exact }}
              activeProps={{ "data-status": "active" }}
            >
              {item.label}
            </Link>
          ))}
          <Link
            to="/w/$workspaceId/settings/$section"
            params={{ workspaceId, section: "references" }}
            activeOptions={{ exact: false }}
            activeProps={{ "data-status": "active" }}
          >
            Cài đặt
          </Link>
        </nav>
      ) : (
        <nav className="app-shell__nav" aria-label="Điều hướng chính" />
      )}
      <main id="main" className="app-shell__main">
        {workspacesQuery.isLoading ? <LoadingView label="Đang tải workspace" /> : null}
        {workspacesQuery.isError ? (
          <ErrorView
            message="Không tải được danh sách workspace"
            onRetry={() => void workspacesQuery.refetch()}
          />
        ) : null}
        {workspacesQuery.isSuccess && workspaces.length === 0 ? (
          <EmptyView
            title="Chưa có workspace"
            hint="Tạo workspace qua API hoặc công cụ quản trị trước khi sử dụng giao diện."
          />
        ) : null}
        <Outlet />
      </main>
    </div>
  );
}
