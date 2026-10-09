import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import Ajv2020 from "ajv/dist/2020";
import type { ValidateFunction } from "ajv";
import { describe, expect, it } from "vitest";
import caseSchema from "../generated/schemas/case-1.schema.json";
import eventSchema from "../generated/schemas/run-event-1.schema.json";
import moneySchema from "../generated/schemas/money-1.schema.json";
import { validateCaseDocument, validateMoney, validateRunEvent } from "../generated/validators";

type Vector = {
  id: string;
  schema: { name: string; version: string };
  valid: boolean;
  document: unknown;
};

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..", "..", "..");
const vectorsFile = JSON.parse(
  readFileSync(path.join(repoRoot, "schemas", "vectors", "parity.json"), "utf8"),
) as { vectors: Vector[] };

const ajv = new Ajv2020({ allErrors: true, strict: false, validateFormats: false });
const directValidators: Record<string, ValidateFunction> = {
  case: ajv.compile(caseSchema),
  "run-event": ajv.compile(eventSchema),
  money: ajv.compile(moneySchema),
};
const generatedValidators: Record<string, ValidateFunction> = {
  case: validateCaseDocument,
  "run-event": validateRunEvent,
  money: validateMoney,
};
const FORBIDDEN_PUBLIC_NAMES = [
  "SensitiveValue",
  "SecretGrant",
  "BrowserReadPort",
  "BrowserActionPort",
  "VerificationPort",
  "IdentityPort",
  "oracle",
  "Oracle",
];

describe("schema parity vectors", () => {
  for (const vector of vectorsFile.vectors) {
    it(`${vector.id} matches expected validity`, () => {
      const generated = generatedValidators[vector.schema.name];
      const direct = directValidators[vector.schema.name];
      expect(generated(vector.document)).toBe(vector.valid);
      expect(direct(vector.document)).toBe(vector.valid);
    });
  }

  it("rejects unknown schema and action versions", () => {
    const unknownVersion = {
      schema_version: "case/2",
      logical_key: "x",
      title: "x",
      goal: "x",
      requirements: [],
      nodes: [],
      completion: { required_nodes: [] },
    };
    expect(validateCaseDocument(unknownVersion)).toBe(false);
    const unknownAction = {
      schema_version: "case/1",
      logical_key: "x",
      title: "x",
      goal: "x",
      requirements: [],
      nodes: [{ id: "n", kind: "action", operation: "teleport", side_effect: "read" }],
      completion: { required_nodes: ["n"] },
    };
    expect(validateCaseDocument(unknownAction)).toBe(false);
  });
});

describe("public surface", () => {
  it("generated schemas exclude internal types", () => {
    const generatedDir = path.join(repoRoot, "apps", "web", "src", "generated", "schemas");
    const files = [
      "case-1.schema.json",
      "run-event-1.schema.json",
      "money-1.schema.json",
      "error-1.schema.json",
    ];
    for (const file of files) {
      const text = readFileSync(path.join(generatedDir, file), "utf8");
      for (const forbidden of FORBIDDEN_PUBLIC_NAMES) {
        expect(text).not.toContain(forbidden);
      }
    }
  });
});
