import editorWorker from "monaco-editor/editor/editor.worker.js?worker";

export async function loadMonaco() {
  const monaco = await import("monaco-editor");
  (self as unknown as { MonacoEnvironment: unknown }).MonacoEnvironment = {
    getWorker: () => new editorWorker(),
  };
  return monaco;
}
