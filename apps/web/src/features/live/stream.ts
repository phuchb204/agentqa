import type { RunEventView, RunState } from "../../api/types";

export interface CursorExpired {
  cursor: number;
  availableFrom: number;
}

export interface LiveState {
  connected: boolean;
  reconnecting: boolean;
  cursor: number;
  snapshot: RunState | null;
  events: RunEventView[];
  seenEventIds: string[];
  cursorExpired: CursorExpired | null;
  followLatest: boolean;
  selectedEventId: string | null;
  closedStatus: string | null;
}

export const initialLiveState: LiveState = {
  connected: false,
  reconnecting: false,
  cursor: 0,
  snapshot: null,
  events: [],
  seenEventIds: [],
  cursorExpired: null,
  followLatest: true,
  selectedEventId: null,
  closedStatus: null,
};

export type LiveAction =
  | { type: "stream_open" }
  | { type: "stream_error" }
  | { type: "snapshot"; state: RunState; cursor: number }
  | { type: "events"; events: RunEventView[] }
  | { type: "cursor_expired"; cursor: number; availableFrom: number }
  | { type: "closed"; status: string }
  | { type: "select_event"; eventId: string }
  | { type: "follow_latest" };

const MAX_EVENTS = 500;

export function liveReducer(state: LiveState, action: LiveAction): LiveState {
  switch (action.type) {
    case "stream_open":
      return { ...state, connected: true, reconnecting: false };
    case "stream_error":
      return { ...state, connected: false, reconnecting: true };
    case "snapshot": {
      const events = mergeEvents(state.events, state.seenEventIds, []);
      const merged: RunState =
        state.snapshot === null
          ? action.state
          : {
              ...state.snapshot,
              ...action.state,
              executions: action.state.executions ?? state.snapshot.executions,
              controls: action.state.controls ?? state.snapshot.controls,
              reasons: action.state.reasons ?? state.snapshot.reasons,
            };
      return {
        ...state,
        snapshot: merged,
        cursor: Math.max(state.cursor, action.cursor),
        events: events.events,
        seenEventIds: events.seenEventIds,
      };
    }
    case "events": {
      const merged = mergeEvents(state.events, state.seenEventIds, action.events);
      const cursor =
        merged.events.length > 0 ? merged.events[merged.events.length - 1].run_seq : state.cursor;
      const selected = state.followLatest
        ? (merged.events[merged.events.length - 1]?.event_id ?? state.selectedEventId)
        : state.selectedEventId;
      return {
        ...state,
        events: merged.events,
        seenEventIds: merged.seenEventIds,
        cursor,
        selectedEventId: selected,
      };
    }
    case "cursor_expired":
      return {
        ...state,
        cursorExpired: { cursor: action.cursor, availableFrom: action.availableFrom },
        cursor: Math.max(state.cursor, action.availableFrom),
        events: [],
        seenEventIds: [],
        selectedEventId: null,
        followLatest: true,
      };
    case "closed":
      return { ...state, closedStatus: action.status, connected: false, reconnecting: false };
    case "select_event":
      return { ...state, selectedEventId: action.eventId, followLatest: false };
    case "follow_latest":
      return {
        ...state,
        followLatest: true,
        selectedEventId: state.events[state.events.length - 1]?.event_id ?? state.selectedEventId,
      };
    default:
      return state;
  }
}

function mergeEvents(
  current: RunEventView[],
  seen: string[],
  incoming: RunEventView[],
): { events: RunEventView[]; seenEventIds: string[] } {
  const seenSet = new Set(seen);
  const bySeq = new Map<number, RunEventView>();
  for (const event of current) {
    bySeq.set(event.run_seq, event);
  }
  for (const event of incoming) {
    if (seenSet.has(event.event_id)) {
      continue;
    }
    if (bySeq.has(event.run_seq)) {
      continue;
    }
    seenSet.add(event.event_id);
    bySeq.set(event.run_seq, event);
  }
  const events = [...bySeq.values()]
    .sort((left, right) => left.run_seq - right.run_seq)
    .slice(-MAX_EVENTS);
  return { events, seenEventIds: [...seenSet].slice(-MAX_EVENTS * 2) };
}
