import { useQuery } from "@tanstack/react-query";

import { useApi } from "../api/context";
import { useSession } from "./session-context";
import type { Role } from "./permissions";

export function useWorkspaceRole(workspaceId: string | undefined): Role | undefined {
  const api = useApi();
  const { user } = useSession();
  const query = useQuery({
    queryKey: ["memberships", workspaceId],
    queryFn: () => api.listMemberships(workspaceId as string),
    enabled: Boolean(workspaceId),
  });
  return query.data?.find((membership) => membership.user_id === user.user_id)?.role as
    Role | undefined;
}
