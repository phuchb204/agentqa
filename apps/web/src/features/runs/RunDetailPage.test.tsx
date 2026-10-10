import { describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";

import { makeFakeClient } from "../../test-utils/fake-client";
import { renderWithProviders } from "../../test-utils/render";
import { RunDetailPage } from "./RunDetailPage";

describe("RunDetailPage", () => {
  it("hiển thị lỗi đầu tiên với expected/observed và unknown money khác zero", async () => {
    const client = makeFakeClient({
      getRunDetail: vi.fn(async () => ({
        run_id: "run-1",
        status: "succeeded",
        verdict: "failed",
        gate: "refused",
        reasons: ["healed"],
        annotations: ["healed"],
        terminal: true,
        snapshot: {
          policy: "default",
          observation_mode: "semantic",
          gate_profile: "strict",
          cache_profile: "default",
          calibration_ref: null,
          budgets: {},
          content_digests: [],
          environment_revision: null,
          provisional: false,
        },
        executions: [
          {
            execution_id: "exec-1",
            logical_key: "detail_case",
            status: "succeeded",
            verdict: "failed",
            assertions: [
              {
                checkpoint_id: "check",
                assertion_id: "a1",
                result: "failed",
                proof: {
                  expected: "/done",
                  observed: "/start",
                  evidence: "present",
                  reason: "mismatch",
                },
              },
            ],
          },
        ],
        controls: [
          {
            control_id: "c1",
            action: "pause",
            requested_at: "2026-10-10T00:00:00Z",
            effective_at: null,
            effective_reason: null,
          },
        ],
        artifacts: [
          {
            artifact_id: "art-1",
            kind: "screenshot",
            state: "expired",
            media_type: "image/png",
            digest: "a".repeat(64),
            redacted: true,
            unavailable_reason: "retention_expired",
          },
        ],
        usage: {
          state: "partial",
          input_tokens: 100,
          output_tokens: 20,
          settled_calls: 1,
          unknown_calls: 1,
          cost_state: "unknown",
          cost_total: null,
          cost_currency: null,
        },
      })),
    });
    renderWithProviders(<RunDetailPage workspaceId="w1" runId="run-1" />, { client });

    expect(await screen.findByText(/Vấn đề đầu tiên có căn cứ/)).toBeTruthy();
    expect(screen.getAllByText("/done").length).toBeGreaterThan(0);
    expect(screen.getAllByText("/start").length).toBeGreaterThan(0);
    expect(screen.getByText(/Không có dữ liệu chi phí/)).toBeTruthy();
    expect(screen.getByText(/1 call unknown/)).toBeTruthy();
    expect(screen.getByText("retention_expired")).toBeTruthy();
    expect(screen.getByText(/requested 00:00:00 · chưa effective/)).toBeTruthy();
  });
});
