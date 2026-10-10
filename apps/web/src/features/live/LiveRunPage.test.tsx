import { describe, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { makeFakeClient } from "../../test-utils/fake-client";
import { renderWithProviders } from "../../test-utils/render";
import { LiveRunPage, type StreamHandlers } from "./LiveRunPage";

function fakeStreamFactory(handlersRef: { current: StreamHandlers | null }) {
  return {
    open: (_url: string, handlers: StreamHandlers) => {
      handlersRef.current = handlers;
      handlers.onOpen();
      return () => undefined;
    },
  };
}

const runningState = {
  run_id: "run-1",
  status: "running",
  verdict: null,
  gate: null,
  reasons: [],
  snapshot_digest: "a".repeat(64),
  last_run_seq: 2,
  executions: [
    { execution_id: "exec-1", logical_key: "live_case", status: "running", verdict: null },
  ],
  controls: [],
};

describe("LiveRunPage", () => {
  it("hiển thị chưa có kết luận khi active và phân biệt requested/effective", async () => {
    const handlersRef: { current: StreamHandlers | null } = { current: null };
    const client = makeFakeClient({
      getRunState: vi.fn(async () => runningState),
      requestControl: vi.fn(async () => ({ control_id: "c1", control_revision: 1 })),
    });
    renderWithProviders(
      <LiveRunPage workspaceId="w1" runId="run-1" streamFactory={fakeStreamFactory(handlersRef)} />,
      { client },
    );

    expect(await screen.findByText("Chưa có kết luận")).toBeTruthy();
    expect(await screen.findByText(/Requested: 0 · Effective: 0/)).toBeTruthy();

    await userEvent.click(screen.getByRole("button", { name: "Tạm dừng" }));
    await waitFor(() => expect(client.requestControl).toHaveBeenCalledWith("w1", "run-1", "pause"));
    expect(await screen.findByText(/Đã gửi yêu cầu pause \(requested\)/)).toBeTruthy();
  });

  it("chọn bước quá khứ không bị auto-scroll về latest", async () => {
    const handlersRef: { current: StreamHandlers | null } = { current: null };
    const client = makeFakeClient({ getRunState: vi.fn(async () => runningState) });
    renderWithProviders(
      <LiveRunPage workspaceId="w1" runId="run-1" streamFactory={fakeStreamFactory(handlersRef)} />,
      { client },
    );
    await screen.findByText("Chưa có kết luận");

    handlersRef.current?.onEvents([
      {
        event_id: "e3",
        run_seq: 3,
        execution_id: null,
        execution_seq: null,
        type: "action.settled",
      },
      {
        event_id: "e4",
        run_seq: 4,
        execution_id: null,
        execution_seq: null,
        type: "checkpoint.evaluated",
      },
    ]);
    await userEvent.click(await screen.findByRole("button", { name: /#3 action.settled/ }));

    handlersRef.current?.onEvents([
      {
        event_id: "e5",
        run_seq: 5,
        execution_id: null,
        execution_seq: null,
        type: "run.finalized",
      },
    ]);
    await screen.findByRole("button", { name: /#5 run.finalized/ });
    expect(screen.getByRole("button", { name: /#3 action.settled/ })).toBeTruthy();
    expect(await screen.findByRole("button", { name: /Theo dõi trực tiếp/ })).toBeTruthy();
  });

  it("cursor_expired hiển thị missing range typed", async () => {
    const handlersRef: { current: StreamHandlers | null } = { current: null };
    const client = makeFakeClient({ getRunState: vi.fn(async () => runningState) });
    renderWithProviders(
      <LiveRunPage workspaceId="w1" runId="run-1" streamFactory={fakeStreamFactory(handlersRef)} />,
      { client },
    );
    await screen.findByText("Chưa có kết luận");
    handlersRef.current?.onCursorExpired({ cursor: 1, availableFrom: 40 });
    expect(await screen.findByText(/Cursor hết hạn: thiếu 1–40/)).toBeTruthy();
  });
});
