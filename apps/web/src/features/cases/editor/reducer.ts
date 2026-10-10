import type { DiffEntry, Draft, Revision } from "../../../api/types";

export interface ValidationIssue {
  path: string;
  message: string;
}

export interface EditorState {
  mode: "empty" | "ready" | "draft";
  content: Record<string, unknown> | null;
  baseContent: Record<string, unknown> | null;
  editVersion: number;
  readyRevision: Revision | null;
  history: Record<string, unknown>[];
  future: Record<string, unknown>[];
  dirty: boolean;
  validation: ValidationIssue[];
  conflict: Draft | null;
  lastDiff: DiffEntry[] | null;
  saveState: "idle" | "saving" | "saved" | "error";
  saveError: string | null;
}

export const initialEditorState: EditorState = {
  mode: "empty",
  content: null,
  baseContent: null,
  editVersion: 0,
  readyRevision: null,
  history: [],
  future: [],
  dirty: false,
  validation: [],
  conflict: null,
  lastDiff: null,
  saveState: "idle",
  saveError: null,
};

export type EditorAction =
  | { type: "load_ready"; revision: Revision | null }
  | { type: "load_draft"; draft: Draft }
  | { type: "edit"; content: Record<string, unknown> }
  | { type: "undo" }
  | { type: "redo" }
  | { type: "validation"; issues: ValidationIssue[] }
  | { type: "save_started" }
  | { type: "saved"; draft: Draft }
  | { type: "save_failed"; message: string }
  | { type: "conflict"; remote: Draft }
  | { type: "resolve_keep_local" }
  | { type: "resolve_use_remote" }
  | { type: "diff"; entries: DiffEntry[] };

const MAX_HISTORY = 50;

export function editorReducer(state: EditorState, action: EditorAction): EditorState {
  switch (action.type) {
    case "load_ready":
      return {
        ...state,
        mode: action.revision ? "ready" : "empty",
        content: action.revision ? (action.revision.content as Record<string, unknown>) : null,
        baseContent: action.revision ? (action.revision.content as Record<string, unknown>) : null,
        readyRevision: action.revision,
        editVersion: 0,
        history: [],
        future: [],
        dirty: false,
        conflict: null,
        validation: [],
        saveState: "idle",
        saveError: null,
      };
    case "load_draft":
      return {
        ...state,
        mode: "draft",
        content: action.draft.content,
        baseContent: action.draft.content,
        editVersion: action.draft.edit_version,
        history: [],
        future: [],
        dirty: false,
        conflict: null,
        validation: [],
        saveState: "idle",
        saveError: null,
      };
    case "edit":
      return {
        ...state,
        content: action.content,
        history: state.content
          ? [...state.history, state.content].slice(-MAX_HISTORY)
          : state.history,
        future: [],
        dirty: true,
        saveState: "idle",
        saveError: null,
      };
    case "undo": {
      if (state.history.length === 0 || state.content === null) {
        return state;
      }
      const previous = state.history[state.history.length - 1];
      return {
        ...state,
        content: previous,
        history: state.history.slice(0, -1),
        future: [state.content, ...state.future].slice(0, MAX_HISTORY),
        dirty: true,
      };
    }
    case "redo": {
      if (state.future.length === 0 || state.content === null) {
        return state;
      }
      const next = state.future[0];
      return {
        ...state,
        content: next,
        history: [...state.history, state.content].slice(-MAX_HISTORY),
        future: state.future.slice(1),
        dirty: true,
      };
    }
    case "validation":
      return { ...state, validation: action.issues };
    case "save_started":
      return { ...state, saveState: "saving", saveError: null };
    case "saved":
      return {
        ...state,
        mode: "draft",
        content: action.draft.content,
        baseContent: action.draft.content,
        editVersion: action.draft.edit_version,
        dirty: false,
        saveState: "saved",
        saveError: null,
        conflict: null,
      };
    case "save_failed":
      return { ...state, saveState: "error", saveError: action.message };
    case "conflict":
      return {
        ...state,
        conflict: action.remote,
        saveState: "error",
        saveError: "Bản trên server đã thay đổi",
      };
    case "resolve_keep_local":
      if (state.conflict === null) {
        return state;
      }
      return {
        ...state,
        editVersion: state.conflict.edit_version,
        conflict: null,
        dirty: true,
        saveState: "idle",
        saveError: null,
      };
    case "resolve_use_remote":
      if (state.conflict === null) {
        return state;
      }
      return {
        ...state,
        content: state.conflict.content,
        baseContent: state.conflict.content,
        editVersion: state.conflict.edit_version,
        conflict: null,
        dirty: false,
        saveState: "idle",
        saveError: null,
      };
    case "diff":
      return { ...state, lastDiff: action.entries };
    default:
      return state;
  }
}
