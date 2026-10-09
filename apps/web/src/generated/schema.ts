export interface paths {
    "/api/v1/schemas": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get: operations["list_schemas_api_v1_schemas_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/schemas/{name}/{version}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get: operations["get_schema_api_v1_schemas__name___version__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/health/live": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get: operations["health_live_health_live_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
}
export type webhooks = Record<string, never>;
export interface components {
    schemas: {
        ErrorCode: "input_invalid" | "not_found" | "duplicate_key" | "unsupported_schema_version" | "unsupported_node" | "unknown_operation" | "unknown_reference" | "duplicate_id" | "invalid_capture" | "type_mismatch" | "secret_interpolation" | "source_unconfirmed" | "empty_assertion" | "incomplete_branch_proof" | "loop_bound_invalid" | "capability_mismatch" | "unsafe_json" | "secret_serialization" | "document_too_large" | "alias_limit_exceeded" | "custom_tag_rejected" | "capability_unavailable" | "permission_denied" | "fixture_failed" | "locator_missing" | "locator_ambiguous" | "identity_mismatch" | "action_timeout" | "action_outcome_unknown" | "provider_auth" | "provider_quota" | "provider_rate_limit" | "provider_timeout" | "provider_schema" | "verification_error" | "evidence_missing" | "evidence_redaction_failed" | "storage_unavailable" | "lease_lost" | "worker_lost" | "resource_exhausted";
        ErrorResponse: {
            code: components["schemas"]["ErrorCode"];
            field_errors: components["schemas"]["FieldErrorModel"][];
            message: string;
            request_id?: string | null;
            retryable: boolean;
        };
        FieldErrorModel: {
            code: components["schemas"]["ErrorCode"];
            message: string;
            path: (string | number)[];
        };
        HTTPValidationError: {
            detail?: components["schemas"]["ValidationError"][];
        };
        HealthResponse: {
            schema_versions: {
                [key: string]: string;
            };
            status: string;
            version: string;
        };
        ValidationError: {
            ctx?: Record<string, never>;
            input?: unknown;
            loc: (string | number)[];
            msg: string;
            type: string;
        };
    };
    responses: never;
    parameters: never;
    requestBodies: never;
    headers: never;
    pathItems: never;
}
export type $defs = Record<string, never>;
export interface operations {
    list_schemas_api_v1_schemas_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
        };
    };
    get_schema_api_v1_schemas__name___version__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                name: string;
                version: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    health_live_health_live_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HealthResponse"];
                };
            };
        };
    };
}
