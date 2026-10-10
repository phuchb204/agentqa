import { describe, expect, it } from "vitest";

import { initialLiveState, liveReducer } from "./stream";

const event = (seq: number, id: string) => ({
  event_id: id,
  run_seq: seq,
  execution_id: null,
  execution_seq: null,
  type: "run.state_changed",
});

const state = {
  run_id: "r1",
  status: "running",
  verdict: null,
  gate: null,
  reasons: [],
  snapshot_digest: null,
  last_run_seq: 3,
  executions: [],
  controls: [],
};

describe("liveReducer", () => {
  it("merge snapshot và events theo run_seq, dedupe theo event_id", () => {
    let current = liveReducer(initialLiveState, { type: "snapshot", state, cursor: 3 });
    current = liveReducer(current, { type: "events", events: [event(4, "e4"), event(5, "e5")] });
    current = liveReducer(current, { type: "events", events: [event(5, "e5"), event(6, "e6")] });
    expect(current.events.map((item) => item.run_seq)).toEqual([4, 5, 6]);
    expect(current.cursor).toBe(6);
    expect(current.seenEventIds).toEqual(["e4", "e5", "e6"]);
  });

  it("reconnect giữ nguyên events và đánh dấu reconnecting", () => {
    let current = liveReducer(initialLiveState, { type: "snapshot", state, cursor: 3 });
    current = liveReducer(current, { type: "events", events: [event(4, "e4")] });
    current = liveReducer(current, { type: "stream_error" });
    expect(current.reconnecting).toBe(true);
    expect(current.events).toHaveLength(1);
    current = liveReducer(current, { type: "stream_open" });
    expect(current.connected).toBe(true);
    expect(current.events).toHaveLength(1);
  });

  it("cursor_expired typed reset và ghi nhận missing range", () => {
    let current = liveReducer(initialLiveState, { type: "snapshot", state, cursor: 2 });
    current = liveReducer(current, { type: "events", events: [event(3, "e3")] });
    current = liveReducer(current, { type: "cursor_expired", cursor: 2, availableFrom: 50 });
    expect(current.cursorExpired).toEqual({ cursor: 2, availableFrom: 50 });
    expect(current.events).toEqual([]);
    expect(current.cursor).toBe(50);
  });

  it("chọn bước quá khứ không bị kéo về latest", () => {
    let current = liveReducer(initialLiveState, { type: "snapshot", state, cursor: 3 });
    current = liveReducer(current, { type: "events", events: [event(4, "e4"), event(5, "e5")] });
    current = liveReducer(current, { type: "select_event", eventId: "e4" });
    current = liveReducer(current, { type: "events", events: [event(6, "e6")] });
    expect(current.selectedEventId).toBe("e4");
    expect(current.followLatest).toBe(false);

    current = liveReducer(current, { type: "follow_latest" });
    expect(current.followLatest).toBe(true);
    expect(current.selectedEventId).toBe("e6");
  });
});
