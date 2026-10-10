import { describe, expect, it } from "vitest";

import type { HealingRecord } from "../../api/types";
import { applyHealingPatch, summarizeTarget } from "./healing";

function record(overrides: Partial<HealingRecord> = {}): HealingRecord {
  return {
    record_id: "h1",
    run_id: "run-1",
    execution_id: "exec-1",
    attempt_id: "att-1",
    actor: "action",
    node_id: "delete_item",
    opportunity_id: "opp-1",
    attempt_ref: "heal-1",
    decision: "recovered",
    ranking: null,
    expected_signature: "button|xoá việc",
    actual_signature: "button|xoá",
    original_target: { intent: "delete_item", role: "button", name: "Xoá việc" },
    actual_target: { intent: "delete_item", role: "button", name: "Xoá" },
    dispatch_outcome: "succeeded",
    guard_checks: ["uniqueness", "role"],
    postconditions_ok: true,
    refusal_reason: null,
    error: null,
    proposal: {
      node_id: "delete_item",
      intent: "delete_item",
      proposed: { intent: "delete_item", role: "button", name: "Xoá", locators: [] },
      locator: null,
      source_run_id: "run-1",
    },
    source_run_id: "run-1",
    case_id: "case-1",
    case_revision_id: "rev-1",
    recorded_at: new Date().toISOString(),
    ...overrides,
  };
}

describe("applyHealingPatch", () => {
  it("patches the node target by node id without touching other nodes", () => {
    const content = {
      nodes: [
        { id: "open", kind: "action", target: { intent: "open" } },
        { id: "delete_item", kind: "action", target: { intent: "delete_item", name: "Xoá việc" } },
      ],
    };
    const result = applyHealingPatch(content, record());
    expect(result.applied).toBe(true);
    const nodes = result.content.nodes as Record<string, unknown>[];
    expect((nodes[1].target as Record<string, unknown>).name).toBe("Xoá");
    expect((content.nodes[1].target as Record<string, unknown>).name).toBe("Xoá việc");
  });

  it("patches an assertion target for evidence recovery ids", () => {
    const content = {
      nodes: [
        {
          id: "result",
          kind: "checkpoint",
          assertions: [
            { id: "delete_button_visible", target: { intent: "delete_item", name: "Xoá cũ" } },
          ],
        },
      ],
    };
    const result = applyHealingPatch(
      content,
      record({
        actor: "evidence",
        node_id: "result:delete_button_visible",
        proposal: {
          node_id: "result:delete_button_visible",
          intent: "delete_item",
          proposed: { intent: "delete_item", role: "button", name: "Xoá" },
          locator: { kind: "test_id", value: "delete-a" },
          source_run_id: "run-1",
        },
      }),
    );
    expect(result.applied).toBe(true);
    const nodes = result.content.nodes as Record<string, unknown>[];
    const assertions = nodes[0].assertions as Record<string, unknown>[];
    expect((assertions[0].target as Record<string, unknown>).name).toBe("Xoá");
  });

  it("reports not applied when the node does not exist", () => {
    const result = applyHealingPatch({ nodes: [] }, record());
    expect(result.applied).toBe(false);
  });

  it("reports not applied when there is no proposal", () => {
    const result = applyHealingPatch(
      { nodes: [] },
      record({ proposal: null, decision: "refused" }),
    );
    expect(result.applied).toBe(false);
  });
});

describe("summarizeTarget", () => {
  it("summarizes role/name/scope/locator", () => {
    const summary = summarizeTarget({
      intent: "delete_item",
      role: "button",
      name: "Xoá",
      locators: [{ kind: "test_id", value: "delete-a" }],
      entity_scope: { field: "text", value: { kind: "literal", value: "Việc A" } },
    });
    expect(summary.label).toContain("delete_item");
    expect(summary.locator).toBe("test_id:delete-a");
    expect(summary.entityScope).toBe("Việc A");
  });

  it("handles missing target", () => {
    expect(summarizeTarget(null).label).toBe("—");
  });
});
