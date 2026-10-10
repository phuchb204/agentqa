import { parse as parseYaml, stringify as stringifyYaml } from "yaml";

import { validateCaseDocument } from "../../../generated/validators";
import type { ValidationIssue } from "./reducer";

export type YamlParseResult =
  { ok: true; content: Record<string, unknown> } | { ok: false; message: string };

export function parseCaseYaml(text: string): YamlParseResult {
  let document: unknown;
  try {
    document = parseYaml(text);
  } catch (error) {
    return { ok: false, message: error instanceof Error ? error.message : "YAML không hợp lệ" };
  }
  if (document === null || typeof document !== "object" || Array.isArray(document)) {
    return { ok: false, message: "YAML phải là một mapping" };
  }
  return { ok: true, content: document as Record<string, unknown> };
}

export function serializeCaseYaml(content: Record<string, unknown>): string {
  return stringifyYaml(content, { lineWidth: 0 });
}

export function validateCaseContent(content: Record<string, unknown>): ValidationIssue[] {
  const valid = validateCaseDocument(content);
  if (valid) {
    return [];
  }
  return (validateCaseDocument.errors ?? []).map((error) => ({
    path: error.instancePath || "/",
    message: `${error.message ?? "không hợp lệ"}`,
  }));
}
