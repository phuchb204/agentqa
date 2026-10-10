import { useEffect, useRef, useState } from "react";

const isTestEnvironment = import.meta.env.MODE === "test";

interface MonacoEditorLike {
  dispose: () => void;
  getValue: () => string;
  setValue: (value: string) => void;
  onDidChangeModelContent: (listener: () => void) => void;
}

export function YamlEditor({
  value,
  onChange,
}: {
  value: string;
  onChange: (text: string) => void;
}) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const editorRef = useRef<MonacoEditorLike | null>(null);
  const [fallback, setFallback] = useState(isTestEnvironment);
  const [buffer, setBuffer] = useState(value);

  useEffect(() => {
    if (fallback || containerRef.current === null) {
      return;
    }
    let disposed = false;
    void (async () => {
      try {
        const { loadMonaco } = await import("./monaco-setup");
        const monaco = await loadMonaco();
        if (disposed || containerRef.current === null) {
          return;
        }
        const editor = monaco.editor.create(containerRef.current, {
          value,
          language: "yaml",
          automaticLayout: true,
          minimap: { enabled: false },
          scrollBeyondLastLine: false,
        }) as unknown as MonacoEditorLike;
        editorRef.current = editor;
        editor.onDidChangeModelContent(() => onChange(editor.getValue()));
      } catch {
        setFallback(true);
      }
    })();
    return () => {
      disposed = true;
      editorRef.current?.dispose();
      editorRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fallback]);

  useEffect(() => {
    const editor = editorRef.current;
    if (editor !== null && editor.getValue() !== value) {
      editor.setValue(value);
    }
  }, [value]);

  useEffect(() => {
    setBuffer(value);
  }, [value]);

  if (fallback) {
    return (
      <textarea
        aria-label="YAML"
        className="yaml-editor"
        value={buffer}
        onChange={(event) => {
          setBuffer(event.target.value);
          onChange(event.target.value);
        }}
      />
    );
  }
  return <div aria-label="YAML" className="yaml-editor" ref={containerRef} />;
}
