import Ajv2020 from "ajv/dist/2020";
import caseSchema from "./schemas/case-1.schema.json";
import eventSchema from "./schemas/run-event-1.schema.json";
import moneySchema from "./schemas/money-1.schema.json";
const ajv = new Ajv2020({ allErrors: true, strict: false, validateFormats: false });
export const validateCaseDocument = ajv.compile(caseSchema);
export const validateRunEvent = ajv.compile(eventSchema);
export const validateMoney = ajv.compile(moneySchema);
