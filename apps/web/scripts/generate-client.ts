import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import openapiTS, { astToString } from "openapi-typescript";
import ts from "typescript";

const webRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const repoRoot = path.resolve(webRoot, "..", "..");
const generatedDir = path.join(webRoot, "src", "generated");
const checkMode = process.argv.includes("--check");

const SCHEMA_FILES = [
  { source: "schemas/dsl/case/1.schema.json", target: "case-1.schema.json" },
  { source: "schemas/events/run-event/1.schema.json", target: "run-event-1.schema.json" },
  { source: "schemas/contracts/money/1.schema.json", target: "money-1.schema.json" },
  { source: "schemas/api/error/1.schema.json", target: "error-1.schema.json" },
];

function printWithoutTrivia(source: string): string {
  const file = ts.createSourceFile(
    "generated.ts",
    source,
    ts.ScriptTarget.ES2022,
    true,
    ts.ScriptKind.TS,
  );
  const printer = ts.createPrinter({ removeComments: true, newLine: ts.NewLineKind.LineFeed });
  return printer.printFile(file);
}

function validatorsSource(): string {
  return printWithoutTrivia(
    [
      'import Ajv2020 from "ajv/dist/2020";',
      'import caseSchema from "./schemas/case-1.schema.json";',
      'import eventSchema from "./schemas/run-event-1.schema.json";',
      'import moneySchema from "./schemas/money-1.schema.json";',
      "",
      "const ajv = new Ajv2020({ allErrors: true, strict: false, validateFormats: false });",
      "",
      "export const validateCaseDocument = ajv.compile(caseSchema);",
      "export const validateRunEvent = ajv.compile(eventSchema);",
      "export const validateMoney = ajv.compile(moneySchema);",
      "",
    ].join("\n"),
  );
}

function clientSource(): string {
  return printWithoutTrivia(
    [
      'import createClient from "openapi-fetch";',
      'import type { paths } from "./schema";',
      "",
      'export const api = createClient<paths>({ baseUrl: "/api/v1" });',
      "",
    ].join("\n"),
  );
}

async function expectedFiles(): Promise<Map<string, string>> {
  const files = new Map<string, string>();
  const openapi = JSON.parse(readFileSync(path.join(repoRoot, "schemas", "openapi.json"), "utf8"));
  const ast = await openapiTS(openapi);
  files.set(path.join(generatedDir, "schema.ts"), printWithoutTrivia(astToString(ast)));
  files.set(path.join(generatedDir, "client.ts"), clientSource());
  files.set(path.join(generatedDir, "validators.ts"), validatorsSource());
  for (const { source, target } of SCHEMA_FILES) {
    const text = readFileSync(path.join(repoRoot, source), "utf8");
    files.set(path.join(generatedDir, "schemas", target), text);
  }
  return files;
}

async function main(): Promise<void> {
  const files = await expectedFiles();
  const stale: string[] = [];
  for (const [filePath, expected] of files) {
    const relative = path.relative(webRoot, filePath).replaceAll("\\", "/");
    let current: string | null = null;
    try {
      current = readFileSync(filePath, "utf8");
    } catch {
      current = null;
    }
    if (current !== expected) {
      stale.push(relative);
      if (!checkMode) {
        mkdirSync(path.dirname(filePath), { recursive: true });
        writeFileSync(filePath, expected, "utf8");
        console.log(`[WROTE] ${relative}`);
      }
    }
  }
  if (checkMode) {
    if (stale.length > 0) {
      for (const relative of stale) {
        console.log(`[STALE] ${relative}`);
      }
      console.log(`STALE: ${stale.length}`);
      process.exit(1);
    }
    console.log(`CHECK OK: ${files.size} generated client files up to date`);
    return;
  }
  console.log(`WRITTEN: ${stale.length}/${files.size}`);
}

main().catch((error: unknown) => {
  console.error(error);
  process.exit(2);
});
