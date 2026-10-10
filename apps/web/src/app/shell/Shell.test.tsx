import { describe, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { makeFakeClient } from "../../test-utils/fake-client";
import { renderWithProviders } from "../../test-utils/render";
import { Shell } from "./Shell";

vi.mock("@tanstack/react-router", async () => {
  const actual =
    await vi.importActual<typeof import("@tanstack/react-router")>("@tanstack/react-router");
  return {
    ...actual,
    Link: ({
      children,
      to,
      ...rest
    }: { children?: unknown; to?: unknown } & Record<string, unknown>) => (
      <a href={typeof to === "string" ? to : "#"} {...rest}>
        {children as never}
      </a>
    ),
    Outlet: () => <div data-testid="outlet" />,
    useNavigate: () => vi.fn(async () => undefined),
    useParams: () => ({ workspaceId: "w1" }),
  };
});

describe("Shell", () => {
  it("hiển thị điều hướng, workspace và vai trò từ server", async () => {
    const client = makeFakeClient();
    renderWithProviders(<Shell />, { client });

    expect(await screen.findByText("Workspace 1")).toBeTruthy();
    for (const label of ["Tổng quan", "Yêu cầu", "Ca kiểm thử", "Bộ ca"]) {
      expect(screen.getByRole("link", { name: label })).toBeTruthy();
    }
    const userMenu = await screen.findByRole("button", { name: "Menu người dùng" });
    await waitFor(() => expect(userMenu.textContent).toContain("Biên tập"));
    expect(screen.getByLabelText("Chọn workspace")).toBeTruthy();
  });

  it("đổi theme và contrast bằng token, không lưu token vào storage", async () => {
    const client = makeFakeClient();
    renderWithProviders(<Shell />, { client });
    await screen.findByText("Workspace 1");

    await userEvent.click(screen.getByRole("button", { name: "Tối" }));
    expect(document.documentElement.dataset.theme).toBe("dark");

    await userEvent.click(screen.getByRole("checkbox", { name: /Tương phản cao/ }));
    expect(document.documentElement.dataset.contrast).toBe("high");

    const storageDump = JSON.stringify({
      local: window.localStorage,
      session: window.sessionStorage,
    });
    expect(storageDump).not.toMatch(/csrf|token|credential|password/i);
    expect(window.location.search).not.toMatch(/token|csrf/i);
  });
});
