import { describe, expect, it } from "vitest";

import { parseCaseYaml, serializeCaseYaml, validateCaseContent } from "./yaml";

const validCase = {
  schema_version: "case/1",
  logical_key: "sample",
  title: "Ca mẫu",
  goal: "Đi tới trạng thái",
  requirements: ["r1"],
  nodes: [
    {
      id: "open",
      kind: "action",
      operation: "navigate",
      value: { kind: "literal", value: "/start" },
      side_effect: "read",
    },
    {
      id: "check",
      kind: "checkpoint",
      assertions: [
        {
          id: "a1",
          required: true,
          comparator: "url_path_equals",
          expected: { kind: "literal", value: "/start" },
          source_refs: ["r1"],
        },
      ],
    },
  ],
  source_defs: {
    r1: {
      source_content_digest: "a".repeat(64),
      anchor: { type: "section", value: "flow" },
      quote_digest: "b".repeat(64),
      provenance: "user",
    },
  },
  completion: { required_nodes: ["open", "check"], required_assertions: ["a1"] },
};

describe("yaml helpers", () => {
  it("parse YAML hợp lệ và giữ nội dung", () => {
    const result = parseCaseYaml(serializeCaseYaml(validCase));
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.content.logical_key).toBe("sample");
    }
  });

  it("báo lỗi YAML không parse được", () => {
    const result = parseCaseYaml("key: [unclosed");
    expect(result.ok).toBe(false);
  });

  it("validate nội dung theo schema case/1", () => {
    expect(validateCaseContent(validCase)).toEqual([]);
    const issues = validateCaseContent({ schema_version: "case/1" });
    expect(issues.length).toBeGreaterThan(0);
    expect(issues[0].path.startsWith("/")).toBe(true);
  });
});
