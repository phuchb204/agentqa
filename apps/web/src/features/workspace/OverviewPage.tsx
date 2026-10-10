import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";

import { useApi } from "../../api/context";
import { LoadingView } from "../../components/States";

export function OverviewPage({ workspaceId }: { workspaceId: string }) {
  const api = useApi();
  const casesQuery = useQuery({
    queryKey: ["cases", workspaceId],
    queryFn: () => api.listCases(workspaceId),
  });
  const requirementsQuery = useQuery({
    queryKey: ["requirements", workspaceId],
    queryFn: () => api.listRequirements(workspaceId),
  });
  const sourcesQuery = useQuery({
    queryKey: ["sources", workspaceId],
    queryFn: () => api.listSources(workspaceId),
  });
  const suitesQuery = useQuery({
    queryKey: ["suites", workspaceId],
    queryFn: () => api.listSuites(workspaceId),
  });

  if (
    casesQuery.isLoading ||
    requirementsQuery.isLoading ||
    sourcesQuery.isLoading ||
    suitesQuery.isLoading
  ) {
    return <LoadingView label="Đang tải tổng quan" />;
  }

  const counts = [
    {
      label: "Ca kiểm thử",
      value: casesQuery.data?.length ?? 0,
      to: "/w/$workspaceId/cases" as const,
    },
    {
      label: "Yêu cầu",
      value: requirementsQuery.data?.length ?? 0,
      to: "/w/$workspaceId/requirements" as const,
    },
    { label: "Bộ ca", value: suitesQuery.data?.length ?? 0, to: "/w/$workspaceId/suites" as const },
    {
      label: "Nguồn tài liệu",
      value: sourcesQuery.data?.length ?? 0,
      to: "/w/$workspaceId/requirements" as const,
    },
  ];

  return (
    <div className="stack">
      <section className="panel">
        <h2 className="panel__title">Tổng quan workspace</h2>
        <p className="muted">
          Dữ liệu lấy trực tiếp từ server theo quyền của bạn; giao diện không tự tính verdict hay
          trạng thái thay server.
        </p>
        <table>
          <thead>
            <tr>
              <th>Hạng mục</th>
              <th>Số lượng</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {counts.map((count) => (
              <tr key={count.label}>
                <td>{count.label}</td>
                <td>{count.value}</td>
                <td>
                  <Link to={count.to} params={{ workspaceId }}>
                    Mở
                  </Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  );
}
