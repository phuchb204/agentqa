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

  it("schedule panel hiển thị occurrence DST/downtime với nhãn tiếng Việt", async () => {
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
      listSchedules: vi.fn(async () => [
        {
          schedule_id: "sched-1",
          logical_key: "nightly",
          enabled: true,
          latest_revision: {
            revision_id: "srev1",
            revision_no: 1,
            content: {
              schema_version: "schedule/1",
              suite_revision_id: "srev1",
              timezone: "America/New_York",
              hour: 2,
              minute: 30,
              overlap: "skip",
            },
          },
        },
      ]),
      listScheduleOccurrences: vi.fn(async () => [
        {
          occurrence_id: "occ-1",
          schedule_id: "sched-1",
          schedule_revision_id: "srev1",
          occurrence_key: "srev1:2026-03-08T02:30:fold0",
          local_wall_time: "2026-03-08T02:30:00",
          scheduled_at: "2026-03-08T07:30:00+00:00",
          fold: 0,
          state: "skipped",
          reason: "dst_gap",
          run_id: null,
        },
        {
          occurrence_id: "occ-2",
          schedule_id: "sched-1",
          schedule_revision_id: "srev1",
          occurrence_key: "srev1:2026-03-09T02:30:fold0",
          local_wall_time: "2026-03-09T02:30:00",
          scheduled_at: "2026-03-09T06:30:00+00:00",
          fold: 0,
          state: "missed",
          reason: "downtime",
          run_id: null,
        },
      ]),
    });
    renderWithProviders(<SuitesPage workspaceId="w1" suiteId="suite1" />, { client });

    expect(await screen.findByText("nightly")).toBeTruthy();
    expect(await screen.findByText("Giờ DST không tồn tại")).toBeTruthy();
    expect(await screen.findByText("Lỡ lịch (không chạy bù)")).toBeTruthy();
    expect(await screen.findByText(/Downtime — không catch-up/)).toBeTruthy();
    expect(screen.getByText(/timezone America\/New_York/)).toBeTruthy();
  });

  it("dataset revisions hiển thị provenance rows và digest", async () => {
    const client = makeFakeClient({
      listSuites: vi.fn(async () => [{ id: "suite1", logical_key: "smoke" }]),
      listSuiteRevisions: vi.fn(async () => []),
      listDatasets: vi.fn(async () => [{ id: "ds1", logical_key: "rows" }]),
      listDatasetRevisions: vi.fn(async () => [
        {
          revision_id: "drev1",
          entity_id: "ds1",
          revision_no: 1,
          content: { schema_version: "dataset/1", logical_key: "rows", rows: [{ a: 1 }, { a: 2 }] },
          content_digest: "f".repeat(64),
          lifecycle: "ready",
          author: "tester",
        },
      ]),
    });
    renderWithProviders(<SuitesPage workspaceId="w1" suiteId="suite1" />, { client });

    const datasetSelect = await screen.findByLabelText("Dataset ref");
    fireEvent.change(datasetSelect, { target: { value: "rows" } });
    expect(await screen.findByText("v1")).toBeTruthy();
    expect(await screen.findByText("ready")).toBeTruthy();
    expect(screen.getByText("2")).toBeTruthy();
    expect(screen.getByText(/ffffffffffff…/)).toBeTruthy();
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
