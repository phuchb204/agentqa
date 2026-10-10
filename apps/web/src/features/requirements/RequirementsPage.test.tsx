import { describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";

import { makeFakeClient } from "../../test-utils/fake-client";
import { renderWithProviders } from "../../test-utils/render";
import { RequirementsPage } from "./RequirementsPage";

describe("RequirementsPage", () => {
  it("hiển thị revision, impact cần xem lại và định nghĩa coverage từ server", async () => {
    const client = makeFakeClient({
      listRequirements: vi.fn(async () => [{ id: "req1", logical_key: "checkout_rule" }]),
      listRequirementRevisions: vi.fn(async () => [
        {
          revision_id: "rrev1",
          entity_id: "req1",
          revision_no: 1,
          content: {
            schema_version: "requirement/1",
            logical_key: "checkout_rule",
            text: "Đơn hàng được xác nhận",
            source_refs: ["checkout_source"],
            acceptance_statements: ["Tổng tiền hiển thị"],
          },
          content_digest: "a".repeat(64),
          lifecycle: "ready",
          author: "tester",
        },
      ]),
      requirementImpact: vi.fn(async () => ({
        requirement_id: "req1",
        logical_key: "checkout_rule",
        latest_revision_no: 2,
        links: [
          {
            case_id: "case1",
            logical_key: "checkout_case",
            case_revision_id: "crev1",
            revision_no: 1,
            needs_review: true,
            source_names: ["checkout_source"],
            affected_assertions: ["path_reached"],
            affected_nodes: ["check"],
            review_marked_at: new Date().toISOString(),
          },
        ],
      })),
    });

    renderWithProviders(<RequirementsPage workspaceId="w1" requirementId="req1" />, { client });

    expect(await screen.findByText("Đơn hàng được xác nhận")).toBeTruthy();
    expect(screen.getByText("Tổng tiền hiển thị")).toBeTruthy();
    expect(await screen.findByText("Cần xem lại theo yêu cầu mới")).toBeTruthy();
    expect(screen.getByText("path_reached")).toBeTruthy();
    expect(screen.getByText(/không phải phần trăm coverage website/)).toBeTruthy();
  });
});
