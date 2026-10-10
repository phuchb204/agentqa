import { describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";

import { makeFakeClient } from "./test-utils/fake-client";
import { renderWithProviders } from "./test-utils/render";
import { App } from "./App";

describe("App session gate", () => {
  it("hiển thị màn đăng nhập khi chưa có session", async () => {
    const client = makeFakeClient({
      session: vi.fn(async () => null),
    });
    renderWithProviders(<App clientOverride={client} />, { client });
    expect(await screen.findByText("Đăng nhập AgentQA")).toBeTruthy();
  });
});
