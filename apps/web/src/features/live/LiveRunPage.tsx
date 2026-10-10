import { useEffect, useMemo, useReducer, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useSearch } from "@tanstack/react-router";

import { useApi } from "../../api/context";
import type { RunEventView, RunState } from "../../api/types";
import { EmptyView, ErrorView, LoadingView } from "../../components/States";
import { useWorkspaceRole } from "../../app/use-role";
import { canRunCases } from "../../app/permissions";
import { initialLiveState, liveReducer } from "./stream";
import { verdictLabel } from "./money";

export interface StreamFactory {
  open(url: string, handlers: StreamHandlers): () => void;
}

export interface StreamHandlers {
  onOpen: () => void;
  onError: () => void;
  onSnapshot: (payload: { state: RunState; cursor: number }) => void;
  onEvents: (events: RunEventView[]) => void;
  onClosed: (status: string) => void;
  onCursorExpired: (payload: { cursor: number; availableFrom: number }) => void;
}

export const eventSourceFactory: StreamFactory = {
  open(url, handlers) {
    const source = new EventSource(url);
    source.onopen = () => handlers.onOpen();
    source.onerror = () => handlers.onError();
    source.addEventListener("snapshot", (event) => {
      const payload = JSON.parse((event as MessageEvent).data) as {
        cursor: number;
        state: RunState;
      };
      handlers.onSnapshot({ state: payload.state, cursor: payload.cursor });
    });
    source.addEventListener("run_event", (event) => {
      const payload = JSON.parse((event as MessageEvent).data) as RunEventView;
      handlers.onEvents([payload]);
    });
    source.addEventListener("closed", (event) => {
      const payload = JSON.parse((event as MessageEvent).data) as { status: string };
      handlers.onClosed(payload.status);
    });
    source.addEventListener("cursor_expired", (event) => {
      const payload = JSON.parse((event as MessageEvent).data) as {
        cursor: number;
        availableFrom: number;
      };
      handlers.onCursorExpired(payload);
    });
    return () => source.close();
  },
};

export function LiveRunPage({
  workspaceId,
  runId,
  streamFactory = eventSourceFactory,
}: {
  workspaceId: string;
  runId: string;
  streamFactory?: StreamFactory;
}) {
  const api = useApi();
  const role = useWorkspaceRole(workspaceId);
  const canControl = canRunCases(role);
  const [state, dispatch] = useReducer(liveReducer, initialLiveState);
  const [frame, setFrame] = useState<{ seq: number; png: string } | null>(null);
  const [frameStatus, setFrameStatus] = useState("Chưa kết nối browser view");
  const [controlMessage, setControlMessage] = useState<string | null>(null);

  const stateQuery = useQuery({
    queryKey: ["run-state", workspaceId, runId],
    queryFn: () => api.getRunState(workspaceId, runId),
    refetchInterval: 3000,
  });

  useEffect(() => {
    if (stateQuery.data) {
      dispatch({ type: "snapshot", state: stateQuery.data, cursor: stateQuery.data.last_run_seq });
    }
  }, [stateQuery.data]);

  const cursorRef = useRef(0);
  useEffect(() => {
    cursorRef.current = state.cursor;
  }, [state.cursor]);

  useEffect(() => {
    const dispose = streamFactory.open(
      `/api/v1/workspaces/${workspaceId}/runs/${runId}/events/stream?cursor=${cursorRef.current}`,
      {
        onOpen: () => dispatch({ type: "stream_open" }),
        onError: () => dispatch({ type: "stream_error" }),
        onSnapshot: ({ state: snapshot, cursor }) =>
          dispatch({ type: "snapshot", state: snapshot, cursor }),
        onEvents: (events) => dispatch({ type: "events", events }),
        onClosed: (status) => dispatch({ type: "closed", status }),
        onCursorExpired: ({ cursor, availableFrom }) =>
          dispatch({ type: "cursor_expired", cursor, availableFrom }),
      },
    );
    return dispose;
  }, [runId, streamFactory, workspaceId]);

  useEffect(() => {
    const protocol = window.location.protocol === "https:" ? "wss" : "ws";
    const socket = new WebSocket(
      `${protocol}://${window.location.host}/api/v1/workspaces/${workspaceId}/runs/${runId}/browser-stream`,
    );
    socket.onmessage = (event) => {
      const payload = JSON.parse(event.data) as {
        type: string;
        seq?: number;
        png_b64?: string;
        reason?: string;
        status?: string;
      };
      if (payload.type === "frame" && payload.png_b64) {
        setFrame({ seq: payload.seq ?? 0, png: payload.png_b64 });
        setFrameStatus(`Frame đã mask #${payload.seq}`);
      } else if (payload.type === "frame_unavailable") {
        setFrameStatus(`Không có frame (${payload.reason})`);
      } else if (payload.type === "closed") {
        setFrameStatus(`Browser stream đã đóng (${payload.status})`);
      }
    };
    socket.onerror = () => setFrameStatus("Browser view không kết nối được");
    socket.onclose = (event) => {
      setFrameStatus((current) =>
        current.startsWith("Frame") ? current : `Browser stream đã đóng (${event.code || 0})`,
      );
    };
    return () => socket.close();
  }, [runId, workspaceId]);

  const snapshot = state.snapshot;
  const terminal = snapshot
    ? ["succeeded", "failed", "cancelled", "error", "inconclusive"].includes(snapshot.status)
    : false;
  const verdict = useMemo(
    () => verdictLabel(snapshot?.verdict ?? null, terminal),
    [snapshot, terminal],
  );

  async function control(action: string) {
    setControlMessage(null);
    try {
      await api.requestControl(workspaceId, runId, action);
      setControlMessage(`Đã gửi yêu cầu ${action} (requested)`);
      await stateQuery.refetch();
    } catch (error) {
      setControlMessage(error instanceof Error ? error.message : "Yêu cầu điều khiển thất bại");
    }
  }

  if (stateQuery.isLoading) {
    return <LoadingView label="Đang tải lượt chạy" />;
  }
  if (stateQuery.isError || snapshot === null) {
    return (
      <ErrorView message="Không tải được lượt chạy" onRetry={() => void stateQuery.refetch()} />
    );
  }

  const controls = snapshot.controls;
  const requested = controls.filter((item) => item.effective_at === null);
  const effective = controls.filter((item) => item.effective_at !== null);

  return (
    <div className="stack">
      <section className="panel">
        <div className="row">
          <h2 className="panel__title">Lượt chạy {runId.slice(0, 8)}</h2>
          <span className="badge">{snapshot.status}</span>
          <span className="badge badge--provisional" role="status">
            {verdict}
          </span>
          <span className="muted" aria-live="polite">
            {state.connected
              ? "Đang theo dõi trực tiếp"
              : state.reconnecting
                ? "Đang kết nối lại…"
                : "Chưa kết nối"}
          </span>
          {state.cursorExpired ? (
            <span className="badge badge--warning">
              Cursor hết hạn: thiếu {state.cursorExpired.cursor}–{state.cursorExpired.availableFrom}
            </span>
          ) : null}
          <div className="app-shell__spacer" />
          {canControl ? (
            <>
              <button type="button" onClick={() => void control("pause")}>
                Tạm dừng
              </button>
              <button type="button" onClick={() => void control("resume")}>
                Tiếp tục
              </button>
              <button type="button" data-variant="danger" onClick={() => void control("cancel")}>
                Huỷ
              </button>
            </>
          ) : null}
        </div>
        {controlMessage ? <p role="status">{controlMessage}</p> : null}
        <p className="muted">
          Requested: {requested.length} · Effective: {effective.length}
        </p>
      </section>

      <div className="editor-grid">
        <section className="panel">
          <h3 className="panel__title">Timeline theo run_seq</h3>
          {state.events.length === 0 ? (
            <p className="muted">Chưa có event nào.</p>
          ) : (
            <ol>
              {state.events.map((event) => (
                <li key={event.event_id}>
                  <button
                    type="button"
                    data-variant={state.selectedEventId === event.event_id ? "primary" : undefined}
                    onClick={() => dispatch({ type: "select_event", eventId: event.event_id })}
                  >
                    #{event.run_seq} {event.type}
                  </button>
                </li>
              ))}
            </ol>
          )}
          {!state.followLatest ? (
            <button type="button" onClick={() => dispatch({ type: "follow_latest" })}>
              Theo dõi trực tiếp (quay lại bước mới nhất)
            </button>
          ) : null}
        </section>

        <aside className="stack">
          <section className="panel">
            <h3 className="panel__title">Browser view (ảnh đã mask)</h3>
            <p role="status">{frameStatus}</p>
            {frame ? (
              <img
                alt={`Frame đã mask #${frame.seq}`}
                src={`data:image/png;base64,${frame.png}`}
                style={{ maxWidth: "100%", border: "1px solid var(--color-border)" }}
              />
            ) : null}
          </section>
          <section className="panel">
            <h3 className="panel__title">Execution</h3>
            <ul>
              {snapshot.executions.map((execution) => (
                <li key={execution.execution_id}>
                  {execution.logical_key} · {execution.status} ·{" "}
                  {execution.verdict ?? "chưa có verdict"}
                </li>
              ))}
            </ul>
            <Link to="/w/$workspaceId/runs/$runId" params={{ workspaceId, runId }}>
              Xem chi tiết →
            </Link>
          </section>
        </aside>
      </div>
    </div>
  );
}

export function RunsListPage({ workspaceId }: { workspaceId: string }) {
  const api = useApi();
  const search = useSearch({ strict: false }) as {
    status?: string;
    verdict?: string;
    policy?: string;
  };
  const [cursor, setCursor] = useState<string | null>(null);
  const [status, setStatus] = useState(search.status ?? "");
  const [verdict, setVerdict] = useState(search.verdict ?? "");
  const [policy, setPolicy] = useState(search.policy ?? "");

  const runsQuery = useQuery({
    queryKey: ["runs", workspaceId, status, verdict, policy, cursor],
    queryFn: () =>
      api.listRuns(workspaceId, {
        status: status || undefined,
        verdict: verdict || undefined,
        policy: policy || undefined,
        cursor: cursor ?? undefined,
      }),
  });

  if (runsQuery.isLoading) {
    return <LoadingView label="Đang tải lượt chạy" />;
  }
  if (runsQuery.isError) {
    return (
      <ErrorView message="Không tải được lượt chạy" onRetry={() => void runsQuery.refetch()} />
    );
  }
  const data = runsQuery.data;
  if (!data) {
    return (
      <EmptyView
        title="Chưa có lượt chạy"
        hint="Gửi một lượt chạy từ editor hoặc API để bắt đầu."
      />
    );
  }

  return (
    <div className="stack">
      <section className="panel">
        <h2 className="panel__title">Lượt chạy ({data.total})</h2>
        <div className="row">
          <label className="stack">
            Trạng thái
            <select
              aria-label="Lọc trạng thái"
              value={status}
              onChange={(event) => setStatus(event.target.value)}
            >
              <option value="">—</option>
              {[
                "queued",
                "running",
                "succeeded",
                "failed",
                "inconclusive",
                "error",
                "cancelled",
              ].map((value) => (
                <option key={value} value={value}>
                  {value}
                </option>
              ))}
            </select>
          </label>
          <label className="stack">
            Verdict
            <select
              aria-label="Lọc verdict"
              value={verdict}
              onChange={(event) => setVerdict(event.target.value)}
            >
              <option value="">—</option>
              {["passed", "failed", "inconclusive"].map((value) => (
                <option key={value} value={value}>
                  {value}
                </option>
              ))}
            </select>
          </label>
          <label className="stack">
            Policy
            <input
              aria-label="Lọc policy"
              value={policy}
              onChange={(event) => setPolicy(event.target.value)}
            />
          </label>
        </div>
      </section>
      {data.items.length === 0 ? (
        <EmptyView
          title="Không có lượt chạy phù hợp"
          hint="Thử bỏ bộ lọc hoặc gửi lượt chạy mới."
        />
      ) : (
        <section className="panel">
          <table>
            <thead>
              <tr>
                <th>Run</th>
                <th>Trạng thái</th>
                <th>Verdict</th>
                <th>Annotations</th>
                <th>Policy</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {data.items.map((item) => (
                <tr key={item.run_id}>
                  <td>{item.run_id.slice(0, 8)}</td>
                  <td>{item.status}</td>
                  <td>{item.verdict ?? "—"}</td>
                  <td>{item.annotations.join(", ") || "—"}</td>
                  <td>{item.policy ?? "—"}</td>
                  <td>
                    <Link
                      to="/w/$workspaceId/runs/$runId"
                      params={{ workspaceId, runId: item.run_id }}
                    >
                      Chi tiết
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {data.next_cursor ? (
            <button type="button" onClick={() => setCursor(data.next_cursor)}>
              Trang tiếp
            </button>
          ) : null}
          {cursor ? (
            <button type="button" onClick={() => setCursor(null)}>
              Về trang đầu
            </button>
          ) : null}
        </section>
      )}
    </div>
  );
}
