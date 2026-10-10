import { describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";

import { makeFakeClient } from "../../test-utils/fake-client";
import { renderWithProviders } from "../../test-utils/render";
import { ComparePage } from "./ComparePage";

vi.mock("@tanstack/react-router", async () => {
  const actual =
    await vi.importActual<typeof import("@tanstack/react-router")>("@tanstack/react-router");
  return {
    ...actual,
    Link: ({ children }: { children?: unknown }) => <span>{children as never}</span>,
    useNavigate: () => vi.fn(async () => undefined),
    useParams: () => ({ workspaceId: "w1" }),
    useSearch: () => ({ run_a: "run-a", run_b: "run-b" }),
  };
});

describe("ComparePage", () => {
  it("hiển thị config diff trước metrics, align theo checkpoint và missing row", async () => {
    const client = makeFakeClient({
      listRuns: vi.fn(async () => ({
        items: [
          {
            run_id: "run-a",
            status: "succeeded",
            verdict: "passed",
            gate: "accepted",
            annotations: [],
            reasons: [],
            policy: "default",
            observation_mode: "semantic",
            environment_revision_id: null,
            created_at: new Date().toISOString(),
            finalized_at: null,
            executions: [],
          },
          {
            run_id: "run-b",
            status: "failed",
            verdict: "failed",
            gate: "refused",
            annotations: [],
            reasons: [],
            policy: "llm",
            observation_mode: "semantic",
            environment_revision_id: null,
            created_at: new Date().toISOString(),
            finalized_at: null,
            executions: [],
          },
        ],
        next_cursor: null,
        total: 2,
      })),
      compareRuns: vi.fn(async () => ({
        run_a: "run-a",
        run_b: "run-b",
        config_diff: [
          { field: "policy", a: "default", b: "llm", equal: false },
          { field: "observation_mode", a: "semantic", b: "semantic", equal: true },
        ],
        metrics: {
          a: {
            verdict: "passed",
            status: "succeeded",
            gate: "accepted",
            usage_state: "complete",
            usage_input_tokens: 10,
            usage_output_tokens: 5,
            cost_state: "complete",
            cost_total: "0",
            cost_currency: "USD",
          },
          b: {
            verdict: "failed",
            status: "failed",
            gate: "refused",
            usage_state: "unknown",
            usage_input_tokens: 0,
            usage_output_tokens: 0,
            cost_state: "unknown",
            cost_total: null,
            cost_currency: null,
          },
        },
        alignment: [
          {
            logical_key: "compare_case",
            aligned: true,
            reason: null,
            a_status: "succeeded",
            b_status: "failed",
            a_verdict: "passed",
            b_verdict: "failed",
            assertions: [
              {
                checkpoint_id: "check",
                assertion_id: "a1",
                aligned: true,
                a_status: "passed",
                b_status: "failed",
                a_expected: "/start",
                b_expected: "/done",
                a_observed: "/start",
                b_observed: "/start",
              },
              {
                checkpoint_id: "check",
                assertion_id: "a2",
                aligned: false,
                a_status: "passed",
                b_status: null,
                a_expected: "1",
                b_expected: null,
                a_observed: "1",
                b_observed: null,
              },
            ],
          },
        ],
      })),
    });

    const { container } = renderWithProviders(<ComparePage workspaceId="w1" />, { client });
    expect(await screen.findByText(/Khác biệt cấu hình/)).toBeTruthy();
    const configSection = screen.getByText(/Khác biệt cấu hình/);
    const metricsSection = screen.getByText("Metrics");
    const order = configSection.compareDocumentPosition(metricsSection);
    expect(order & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getAllByText("khác").length).toBeGreaterThan(0);
    expect(screen.getByText("Không có dữ liệu chi phí")).toBeTruthy();
    expect(screen.getByText("0 USD")).toBeTruthy();
    expect(screen.getAllByText("không").length).toBeGreaterThan(0);
    expect(container.textContent).toContain("/done");
  });
});
