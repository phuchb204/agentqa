import type { HealingRecord } from "../../api/types";

export interface HealingTargetSummary {
  label: string;
  role: string | null;
  name: string | null;
  locator: string | null;
  entityScope: string | null;
}

export function summarizeTarget(
  target: Record<string, unknown> | null | undefined,
): HealingTargetSummary {
  if (!target) {
    return { label: "—", role: null, name: null, locator: null, entityScope: null };
  }
  const locators = Array.isArray(target.locators)
    ? (target.locators as { kind?: string; value?: string }[])
    : [];
  const first = locators[0];
  const scope = target.entity_scope as { value?: { value?: unknown } } | undefined;
  const scopeValue = scope?.value?.value;
  return {
    label: [target.intent, target.role, target.name].filter(Boolean).join(" · ") || "—",
    role: (target.role as string | null) ?? null,
    name: (target.name as string | null) ?? null,
    locator: first ? `${first.kind}:${first.value}` : null,
    entityScope: typeof scopeValue === "string" ? scopeValue : null,
  };
}

function patchTarget(node: Record<string, unknown>, proposed: Record<string, unknown>): boolean {
  const before = JSON.stringify(node.target ?? null);
  node.target = proposed;
  return JSON.stringify(node.target) !== before;
}

function patchNodes(nodes: unknown, record: HealingRecord): boolean {
  if (!Array.isArray(nodes)) {
    return false;
  }
  for (const entry of nodes) {
    if (!entry || typeof entry !== "object") {
      continue;
    }
    const node = entry as Record<string, unknown>;
    if (node.id === record.node_id && record.proposal?.proposed) {
      return patchTarget(node, record.proposal.proposed as Record<string, unknown>);
    }
    if (Array.isArray(node.assertions)) {
      for (const assertion of node.assertions) {
        const item = assertion as Record<string, unknown>;
        if (
          `${String(node.id)}:${String(item.id)}` === record.node_id &&
          record.proposal?.proposed
        ) {
          return patchTarget(item, record.proposal.proposed as Record<string, unknown>);
        }
      }
    }
    if (
      patchNodes(node.then_nodes, record) ||
      patchNodes(node.else_nodes, record) ||
      patchNodes(node.body, record)
    ) {
      return true;
    }
  }
  return false;
}

export function applyHealingPatch(
  content: Record<string, unknown>,
  record: HealingRecord,
): { content: Record<string, unknown>; applied: boolean } {
  if (!record.proposal?.proposed) {
    return { content, applied: false };
  }
  const cloned = JSON.parse(JSON.stringify(content)) as Record<string, unknown>;
  const applied = patchNodes(cloned.nodes, record);
  return { content: cloned, applied };
}
