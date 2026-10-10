import { describe, expect, it } from "vitest";

import { editorReducer, initialEditorState } from "./reducer";

const contentA = { title: "A", nodes: [] };
const contentB = { title: "B", nodes: [] };
const contentC = { title: "C", nodes: [] };

describe("editorReducer", () => {
  it("theo dõi history cho undo/redo", () => {
    let state = editorReducer(initialEditorState, {
      type: "load_draft",
      draft: draftWith(contentA),
    });
    state = editorReducer(state, { type: "edit", content: contentB });
    state = editorReducer(state, { type: "edit", content: contentC });
    expect(state.dirty).toBe(true);

    state = editorReducer(state, { type: "undo" });
    expect(state.content).toEqual(contentB);
    state = editorReducer(state, { type: "undo" });
    expect(state.content).toEqual(contentA);

    state = editorReducer(state, { type: "redo" });
    expect(state.content).toEqual(contentB);
    state = editorReducer(state, { type: "redo" });
    expect(state.content).toEqual(contentC);
  });

  it("giữ edit_version và không dirty sau khi lưu", () => {
    let state = editorReducer(initialEditorState, {
      type: "load_draft",
      draft: draftWith(contentA),
    });
    state = editorReducer(state, { type: "edit", content: contentB });
    state = editorReducer(state, { type: "saved", draft: draftWith(contentB, 2) });
    expect(state.dirty).toBe(false);
    expect(state.editVersion).toBe(2);
    expect(state.content).toEqual(contentB);
  });

  it("xung đột không tự ghi đè: giữ local hoặc dùng remote theo lựa chọn", () => {
    let state = editorReducer(initialEditorState, {
      type: "load_draft",
      draft: draftWith(contentA),
    });
    state = editorReducer(state, { type: "edit", content: contentB });
    state = editorReducer(state, { type: "conflict", remote: draftWith(contentC, 5) });
    expect(state.conflict?.edit_version).toBe(5);
    expect(state.content).toEqual(contentB);

    const keepLocal = editorReducer(state, { type: "resolve_keep_local" });
    expect(keepLocal.content).toEqual(contentB);
    expect(keepLocal.editVersion).toBe(5);
    expect(keepLocal.dirty).toBe(true);

    const useRemote = editorReducer(state, { type: "resolve_use_remote" });
    expect(useRemote.content).toEqual(contentC);
    expect(useRemote.dirty).toBe(false);
    expect(useRemote.editVersion).toBe(5);
  });

  it("load ready đặt chế độ chỉ đọc", () => {
    const state = editorReducer(initialEditorState, {
      type: "load_ready",
      revision: {
        revision_id: "r1",
        entity_id: "c1",
        revision_no: 1,
        content: contentA,
        content_digest: "a".repeat(64),
        lifecycle: "ready",
        author: "tester",
      },
    });
    expect(state.mode).toBe("ready");
    expect(state.dirty).toBe(false);
    expect(state.editVersion).toBe(0);
  });
});

function draftWith(content: Record<string, unknown>, editVersion = 1) {
  return {
    entity_id: "c1",
    edit_version: editVersion,
    content,
    updated_by: "tester",
    updated_at: new Date().toISOString(),
  };
}
