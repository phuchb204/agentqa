import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  createRootRouteWithContext,
  createRoute,
  createRouter,
  useNavigate,
} from "@tanstack/react-router";
import type { QueryClient } from "@tanstack/react-query";

import { useApi } from "../api/context";
import { LoadingView } from "../components/States";
import { CaseEditorPage, CasesListPage } from "../features/cases/CaseEditorPage";
import { ComparePage } from "../features/compare/ComparePage";
import { LiveRunPage, RunsListPage } from "../features/live/LiveRunPage";
import { RequirementsPage } from "../features/requirements/RequirementsPage";
import { RunDetailPage } from "../features/runs/RunDetailPage";
import { SettingsPage } from "../features/settings/SettingsPage";
import { SuitesPage } from "../features/suites/SuitesPage";
import { OverviewPage } from "../features/workspace/OverviewPage";
import { Shell } from "./shell/Shell";

export interface RouterContext {
  queryClient: QueryClient;
}

const rootRoute = createRootRouteWithContext<RouterContext>()({
  component: Shell,
});

function IndexRedirect() {
  const api = useApi();
  const navigate = useNavigate();
  const query = useQuery({ queryKey: ["workspaces"], queryFn: () => api.listWorkspaces() });
  useEffect(() => {
    if (query.data && query.data.length > 0) {
      void navigate({
        to: "/w/$workspaceId",
        params: { workspaceId: query.data[0].id },
        replace: true,
      });
    }
  }, [navigate, query.data]);
  return <LoadingView label="Đang chọn workspace" />;
}

const indexRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/",
  component: IndexRedirect,
});

const workspaceRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/w/$workspaceId",
  component: function WorkspaceRoute() {
    const { workspaceId } = workspaceRoute.useParams();
    return <OverviewPage workspaceId={workspaceId} />;
  },
});

const requirementsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/w/$workspaceId/requirements",
  component: function RequirementsRoute() {
    const { workspaceId } = requirementsRoute.useParams();
    return <RequirementsPage workspaceId={workspaceId} />;
  },
});

const requirementDetailRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/w/$workspaceId/requirements/$requirementId",
  component: function RequirementDetailRoute() {
    const { workspaceId, requirementId } = requirementDetailRoute.useParams();
    return <RequirementsPage workspaceId={workspaceId} requirementId={requirementId} />;
  },
});

const casesRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/w/$workspaceId/cases",
  component: function CasesRoute() {
    const { workspaceId } = casesRoute.useParams();
    return <CasesListPage workspaceId={workspaceId} />;
  },
});

const caseDetailRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/w/$workspaceId/cases/$caseId",
  component: function CaseDetailRoute() {
    const { workspaceId, caseId } = caseDetailRoute.useParams();
    return <CaseEditorPage workspaceId={workspaceId} caseId={caseId} />;
  },
});

const suitesRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/w/$workspaceId/suites",
  component: function SuitesRoute() {
    const { workspaceId } = suitesRoute.useParams();
    return <SuitesPage workspaceId={workspaceId} />;
  },
});

const suiteDetailRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/w/$workspaceId/suites/$suiteId",
  component: function SuiteDetailRoute() {
    const { workspaceId, suiteId } = suiteDetailRoute.useParams();
    return <SuitesPage workspaceId={workspaceId} suiteId={suiteId} />;
  },
});

const settingsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/w/$workspaceId/settings/$section",
  component: function SettingsRoute() {
    const { workspaceId, section } = settingsRoute.useParams();
    return <SettingsPage workspaceId={workspaceId} section={section} />;
  },
});

const settingsIndexRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/w/$workspaceId/settings",
  component: function SettingsIndexRoute() {
    const { workspaceId } = settingsIndexRoute.useParams();
    return <SettingsPage workspaceId={workspaceId} section="references" />;
  },
});

const runsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/w/$workspaceId/runs",
  component: function RunsRoute() {
    const { workspaceId } = runsRoute.useParams();
    return <RunsListPage workspaceId={workspaceId} />;
  },
});

const runDetailRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/w/$workspaceId/runs/$runId",
  component: function RunDetailRoute() {
    const { workspaceId, runId } = runDetailRoute.useParams();
    return <RunDetailPage workspaceId={workspaceId} runId={runId} />;
  },
});

const liveRunRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/w/$workspaceId/live/$runId",
  component: function LiveRunRoute() {
    const { workspaceId, runId } = liveRunRoute.useParams();
    return <LiveRunPage workspaceId={workspaceId} runId={runId} />;
  },
});

const compareRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/w/$workspaceId/compare",
  validateSearch: (search: Record<string, unknown>) => ({
    run_a: typeof search.run_a === "string" ? search.run_a : undefined,
    run_b: typeof search.run_b === "string" ? search.run_b : undefined,
  }),
  component: function CompareRoute() {
    const { workspaceId } = compareRoute.useParams();
    return <ComparePage workspaceId={workspaceId} />;
  },
});

export const routeTree = rootRoute.addChildren([
  indexRoute,
  workspaceRoute,
  requirementsRoute,
  requirementDetailRoute,
  casesRoute,
  caseDetailRoute,
  suitesRoute,
  suiteDetailRoute,
  runsRoute,
  runDetailRoute,
  liveRunRoute,
  compareRoute,
  settingsRoute,
  settingsIndexRoute,
]);

export function createAppRouter(context: RouterContext) {
  return createRouter({ routeTree, context });
}

declare module "@tanstack/react-router" {
  interface Register {
    router: ReturnType<typeof createAppRouter>;
  }
}
