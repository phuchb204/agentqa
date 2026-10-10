export interface AssertionView {
  nodeId: string;
  nodeKind: string;
  assertion: Record<string, unknown>;
}

export interface SourceView {
  name: string;
  provenance: string;
  confirmationRef: string | null;
}

export interface SecretRefView {
  nodeId: string;
  credentialRef: string;
}

export function asContent(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

export function withField(
  content: Record<string, unknown>,
  field: string,
  value: unknown,
): Record<string, unknown> {
  return { ...content, [field]: value };
}

export function withNodeAssertion(
  content: Record<string, unknown>,
  nodeId: string,
  assertionId: string,
  patch: Record<string, unknown>,
): Record<string, unknown> {
  const nodes = Array.isArray(content.nodes) ? content.nodes : [];
  const nextNodes = nodes.map((node) => {
    const record = asContent(node);
    if (record.kind === "branch") {
      return {
        ...record,
        then_nodes: patchSequence(record.then_nodes, nodeId, assertionId, patch),
        else_nodes: patchSequence(record.else_nodes, nodeId, assertionId, patch),
      };
    }
    if (record.kind === "loop") {
      return { ...record, body: patchSequence(record.body, nodeId, assertionId, patch) };
    }
    return patchNode(record, nodeId, assertionId, patch);
  });
  return { ...content, nodes: nextNodes };
}

function patchSequence(
  value: unknown,
  nodeId: string,
  assertionId: string,
  patch: Record<string, unknown>,
): unknown {
  const nodes = Array.isArray(value) ? value : [];
  return nodes.map((node) => {
    const record = asContent(node);
    if (record.kind === "branch") {
      return {
        ...record,
        then_nodes: patchSequence(record.then_nodes, nodeId, assertionId, patch),
        else_nodes: patchSequence(record.else_nodes, nodeId, assertionId, patch),
      };
    }
    if (record.kind === "loop") {
      return { ...record, body: patchSequence(record.body, nodeId, assertionId, patch) };
    }
    return patchNode(record, nodeId, assertionId, patch);
  });
}

function patchNode(
  node: Record<string, unknown>,
  nodeId: string,
  assertionId: string,
  patch: Record<string, unknown>,
): Record<string, unknown> {
  if (node.id !== nodeId || !Array.isArray(node.assertions)) {
    return node;
  }
  return {
    ...node,
    assertions: node.assertions.map((assertion) => {
      const record = asContent(assertion);
      return record.id === assertionId ? { ...record, ...patch } : record;
    }),
  };
}

export function listAssertions(content: Record<string, unknown>): AssertionView[] {
  const found: AssertionView[] = [];
  const visit = (nodes: unknown) => {
    if (!Array.isArray(nodes)) {
      return;
    }
    for (const node of nodes) {
      const record = asContent(node);
      if (record.kind === "checkpoint" && Array.isArray(record.assertions)) {
        for (const assertion of record.assertions) {
          found.push({
            nodeId: String(record.id ?? ""),
            nodeKind: "checkpoint",
            assertion: asContent(assertion),
          });
        }
      }
      visit(record.then_nodes);
      visit(record.else_nodes);
      visit(record.body);
    }
  };
  visit(content.nodes);
  return found;
}

export function listSources(content: Record<string, unknown>): SourceView[] {
  const defs = asContent(content.source_defs);
  return Object.entries(defs).map(([name, value]) => {
    const record = asContent(value);
    return {
      name,
      provenance: String(record.provenance ?? "user"),
      confirmationRef: record.confirmation_ref ? String(record.confirmation_ref) : null,
    };
  });
}

export function listSecretRefs(content: Record<string, unknown>): SecretRefView[] {
  const refs: SecretRefView[] = [];
  const visitValue = (nodeId: string, value: unknown) => {
    const record = asContent(value);
    if (record.kind === "secret" && typeof record.credential_ref === "string") {
      refs.push({ nodeId, credentialRef: record.credential_ref });
    }
  };
  const visit = (nodes: unknown) => {
    if (!Array.isArray(nodes)) {
      return;
    }
    for (const node of nodes) {
      const record = asContent(node);
      visitValue(String(record.id ?? ""), record.value);
      visit(record.then_nodes);
      visit(record.else_nodes);
      visit(record.body);
    }
  };
  visit(content.nodes);
  return refs;
}

export function requiredAssertions(content: Record<string, unknown>): string[] {
  const completion = asContent(content.completion);
  return Array.isArray(completion.required_assertions)
    ? completion.required_assertions.map((item) => String(item))
    : [];
}
