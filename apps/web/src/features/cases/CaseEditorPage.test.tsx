import { describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { ApiClientError } from "../../api/client";
import { makeFakeClient } from "../../test-utils/fake-client";
import { renderWithProviders } from "../../test-utils/render";
import { CaseEditorPage } from "./CaseEditorPage";

const caseContent = {
  schema_version: "case/1",
  logical_key: "editor_case",
  title: "Ca editor",
  goal: "Mục tiêu",
  requirements: ["r1"],
  source_defs: {
    r1: {
      source_content_digest: "a".repeat(64),
      anchor: { type: "section", value: "flow" },
      quote_digest: "b".repeat(64),
      provenance: "inferred",
    },
  },
  nodes: [
    {
      id: "open",
      kind: "action",
      operation: "navigate",
      value: { kind: "literal", value: "/start" },
      side_effect: "read",
    },
    {
      id: "login",
      kind: "action",
      operation: "fill",
      target: { intent: "login", role: "textbox", name: "Tài khoản" },
      value: { kind: "secret", credential_ref: "demo_login.password" },
      side_effect: "reversible",
    },
    {
      id: "check",
      kind: "checkpoint",
      assertions: [
        {
          id: "a1",
          required: true,
          comparator: "url_path_equals",
          expected: { kind: "literal", value: "/start" },
          source_refs: ["r1"],
        },
      ],
    },
  ],
  completion: { required_nodes: ["open", "check"], required_assertions: ["a1"] },
};

function readyRevision() {
  return {
    revision_id: "rev-1",
    entity_id: "case-1",
    revision_no: 1,
    content: caseContent,
    content_digest: "c".repeat(64),
    lifecycle: "ready",
    author: "tester",
  };
}

function draftState(content: Record<string, unknown>, editVersion = 1) {
  return {
    entity_id: "case-1",
    edit_version: editVersion,
    content,
    updated_by: "tester",
    updated_at: new Date().toISOString(),
  };
}

describe("CaseEditorPage", () => {
  it("ready view là chỉ đọc và tạo draft mới từ revision", async () => {
    const saveDraft = vi.fn(async (_w: string, _c: string, content: unknown, editVersion: number) =>
      draftState(content as Record<string, unknown>, editVersion + 1),
    );
    const client = makeFakeClient({
      listCaseRevisions: vi.fn(async () => [readyRevision()]),
      getDraft: vi.fn(async () => null),
      saveDraft: saveDraft as never,
    });
    renderWithProviders(<CaseEditorPage workspaceId="w1" caseId="case-1" />, { client });

    expect(await screen.findByText("Ready (chỉ đọc)")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Lưu" })).toBeNull();

    await userEvent.click(screen.getByRole("button", { name: "Tạo bản chỉnh sửa" }));
    await waitFor(() => expect(saveDraft).toHaveBeenCalledTimes(1));
    expect(saveDraft.mock.calls[0][3]).toBe(0);
    expect(await screen.findByText("Draft v1")).toBeTruthy();
  });

  it("hiển thị trạng thái credential reference thay vì giá trị", async () => {
    const client = makeFakeClient({
      listCaseRevisions: vi.fn(async () => [readyRevision()]),
      getDraft: vi.fn(async () => draftState(caseContent)),
    });
    renderWithProviders(<CaseEditorPage workspaceId="w1" caseId="case-1" />, { client });
    expect(await screen.findByText(/credential reference/)).toBeTruthy();
    expect(screen.getByText("demo_login.password")).toBeTruthy();
    expect(screen.queryByText(/password-value/)).toBeNull();
  });

  it("promote bị chặn khi nguồn suy luận chưa xác nhận", async () => {
    const confirmSources = vi.fn(async () => draftState(caseContent, 2));
    const client = makeFakeClient({
      listCaseRevisions: vi.fn(async () => [readyRevision()]),
      getDraft: vi.fn(async () => draftState(caseContent)),
      confirmSources: confirmSources as never,
    });
    renderWithProviders(<CaseEditorPage workspaceId="w1" caseId="case-1" />, { client });
    await userEvent.click(await screen.findByRole("button", { name: "Promote…" }));

    const promoteButton = await screen.findByRole("button", { name: "Promote revision" });
    expect((promoteButton as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getAllByText(/Suy luận từ quan sát/).length).toBeGreaterThan(0);

    await userEvent.click(screen.getByRole("button", { name: /Xác nhận nguồn suy luận/ }));
    await waitFor(() => expect(confirmSources).toHaveBeenCalledWith("w1", "case-1", ["r1"], 1));
  });

  it("YAML không hợp lệ giữ buffer và chặn lưu", async () => {
    const client = makeFakeClient({
      listCaseRevisions: vi.fn(async () => [readyRevision()]),
      getDraft: vi.fn(async () => draftState(caseContent)),
    });
    renderWithProviders(<CaseEditorPage workspaceId="w1" caseId="case-1" />, { client });
    await screen.findByText("Draft v1");

    await userEvent.click(screen.getByRole("tab", { name: "YAML" }));
    const textarea = (await screen.findByRole("textbox", { name: "YAML" })) as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: "key: [unclosed" } });

    expect(await screen.findByText(/buffer được giữ nguyên/)).toBeTruthy();
    expect((screen.getByRole("textbox", { name: "YAML" }) as HTMLTextAreaElement).value).toBe(
      "key: [unclosed",
    );
    expect((screen.getByRole("button", { name: "Lưu" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("xung đột 412 mở panel merge và không tự ghi đè", async () => {
    const client = makeFakeClient({
      listCaseRevisions: vi.fn(async () => [readyRevision()]),
      getDraft: vi
        .fn()
        .mockResolvedValueOnce(draftState(caseContent, 1))
        .mockResolvedValueOnce(draftState({ ...caseContent, title: "Remote" }, 2)),
      saveDraft: vi.fn(async () => {
        throw new ApiClientError(412, "input_invalid", "Edit version đã thay đổi");
      }) as never,
    });
    renderWithProviders(<CaseEditorPage workspaceId="w1" caseId="case-1" />, { client });
    await screen.findByText("Draft v1");

    const title = screen.getByLabelText("Tiêu đề ca");
    await userEvent.clear(title);
    await userEvent.type(title, "Local");

    expect(await screen.findByText("Xung đột phiên bản với server")).toBeTruthy();
    expect(screen.getByRole("button", { name: /Giữ bản của tôi/ })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Dùng bản server" })).toBeTruthy();
    expect((screen.getByLabelText("Tiêu đề ca") as HTMLInputElement).value).toBe("Local");
  });

  it("chạy thử draft hiển thị provisional", async () => {
    const runDraft = vi.fn(async () => ({
      run_id: "run-12345678",
      snapshot_digest: "d".repeat(64),
      provisional: true,
      blocked: false,
      planned_executions: 1,
    }));
    const client = makeFakeClient({
      listCaseRevisions: vi.fn(async () => [readyRevision()]),
      getDraft: vi.fn(async () => draftState(caseContent)),
      runDraft: runDraft as never,
    });
    renderWithProviders(<CaseEditorPage workspaceId="w1" caseId="case-1" />, { client });
    await screen.findByText("Draft v1");
    await userEvent.click(screen.getByRole("button", { name: "Chạy thử (provisional)" }));
    await waitFor(() => expect(runDraft).toHaveBeenCalledTimes(1));
    expect(await screen.findByText(/Thử nghiệm/)).toBeTruthy();
    expect(screen.getByText(/provisional=true/)).toBeTruthy();
  });
});
