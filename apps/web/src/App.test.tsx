import { renderToString } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { App } from "./App";

describe("App shell", () => {
  it("renders the AgentQA heading", () => {
    const html = renderToString(<App />);
    expect(html).toContain("AgentQA");
  });
});
