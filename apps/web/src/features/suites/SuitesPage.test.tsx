import { describe, expect, it, vi } from "vitest";
import { fireEvent, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { makeFakeClient } from "../../test-utils/fake-client";
import { renderWithProviders } from "../../test-utils/render";
import { SuitesPage } from "./SuitesPage";

describe("SuitesPage", () => {
  it("bind preview hiển thị executions và facts thiếu ref", async () => {
    const client = makeFakeClient({
      listSuites: vi.fn(async () => [{ id: "suite1", logical_key: "smoke" }]),
      listSuiteRevisions: vi.fn(async () => [
        {
          revision_id: "srev1",
          entity_id: "suite1",
          revision_no: 1,
          content: { schema_version: "suite/1", logical_key: "smoke", case_refs: [] },
          content_digest: "b".repeat(64),
          lifecycle: "ready",
          author: "tester",
        },
      ]),
      bindSuite: vi.fn(async () => ({
        suite_revision_id: "srev1",
        suite_logical_key: "smoke",
        fixture_refs: ["taskboard@1"],
        executions: [
          {
            execution_key: "srev1:pinned_case:2:single",
            case_logical_key: "pinned_case",
            case_revision_id: null,
            dataset_row_index: null,
            parameters: {},
          },
        ],
        facts: ["missing_case_revision:pinned_case@2"],
      })),
    });

    renderWithProviders(<SuitesPage workspaceId="w1" suiteId="suite1" />, { client });
    await userEvent.click(await screen.findByRole("button", { name: "Bind preview" }));

    expect(await screen.findByText("missing_case_revision:pinned_case@2")).toBeTruthy();
    expect(screen.getByText("srev1:pinned_case:2:single")).toBeTruthy();
    expect(screen.getByText(/fixture: taskboard@1/)).toBeTruthy();
  });

  it("dataset rows giữ nguyên buffer và báo lỗi JSON sai định dạng", async () => {
    const client = makeFakeClient({
      listSuites: vi.fn(async () => [{ id: "suite1", logical_key: "smoke" }]),
      listSuiteRevisions: vi.fn(async () => []),
    });
    renderWithProviders(<SuitesPage workspaceId="w1" suiteId="suite1" />, { client });

    const keyInput = await screen.findByLabelText("Logical key dataset");
    await userEvent.type(keyInput, "rows_dataset");
    const rows = screen.getByLabelText("Dataset rows") as HTMLTextAreaElement;
    fireEvent.change(rows, { target: { value: '{"a": 1' } });
    await userEvent.click(screen.getByRole("button", { name: "Lưu dataset revision" }));

    expect(await screen.findByText(/Rows phải là mảng object|Unexpected|JSON/)).toBeTruthy();
    expect((screen.getByLabelText("Dataset rows") as HTMLTextAreaElement).value).toBe('{"a": 1');
  });
});
