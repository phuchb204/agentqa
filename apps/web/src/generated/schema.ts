export interface paths {
    "/api/v1/auth/csrf": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post: operations["refresh_csrf_api_v1_auth_csrf_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/auth/local-bootstrap": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post: operations["local_bootstrap_api_v1_auth_local_bootstrap_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/auth/login": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post: operations["login_api_v1_auth_login_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/auth/logout": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post: operations["logout_api_v1_auth_logout_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/auth/session": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get: operations["current_session_api_v1_auth_session_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/auth/tokens": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post: operations["create_token_api_v1_auth_tokens_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/schemas": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get: operations["_list_schemas_api_v1_schemas_get"];
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
        get: operations["_get_schema_api_v1_schemas__name___version__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/workspaces": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get: operations["list_workspaces_api_v1_workspaces_get"];
        put?: never;
        post: operations["create_workspace_api_v1_workspaces_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/workspaces/{workspace_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get: operations["get_workspace_api_v1_workspaces__workspace_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch: operations["patch_workspace_api_v1_workspaces__workspace_id__patch"];
        trace?: never;
    };
    "/api/v1/workspaces/{workspace_id}/applications": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get: operations["list_applications_api_v1_workspaces__workspace_id__applications_get"];
        put?: never;
        post: operations["create_application_api_v1_workspaces__workspace_id__applications_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/workspaces/{workspace_id}/applications/{application_id}/environment-revisions": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get: operations["list_environment_revisions_api_v1_workspaces__workspace_id__applications__application_id__environment_revisions_get"];
        put?: never;
        post: operations["promote_environment_revision_api_v1_workspaces__workspace_id__applications__application_id__environment_revisions_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/workspaces/{workspace_id}/artifacts/{artifact_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get: operations["get_artifact_api_v1_workspaces__workspace_id__artifacts__artifact_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/workspaces/{workspace_id}/artifacts/{artifact_id}/content": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get: operations["get_artifact_content_api_v1_workspaces__workspace_id__artifacts__artifact_id__content_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/workspaces/{workspace_id}/authoring-jobs": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post: operations["create_authoring_job_api_v1_workspaces__workspace_id__authoring_jobs_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/workspaces/{workspace_id}/cases": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get: operations["list_cases_api_v1_workspaces__workspace_id__cases_get"];
        put?: never;
        post: operations["create_case_api_v1_workspaces__workspace_id__cases_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/workspaces/{workspace_id}/cases/{case_id}/draft": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get: operations["get_case_draft_api_v1_workspaces__workspace_id__cases__case_id__draft_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch: operations["patch_case_draft_api_v1_workspaces__workspace_id__cases__case_id__draft_patch"];
        trace?: never;
    };
    "/api/v1/workspaces/{workspace_id}/cases/{case_id}/draft/confirm-sources": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post: operations["confirm_sources_api_v1_workspaces__workspace_id__cases__case_id__draft_confirm_sources_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/workspaces/{workspace_id}/cases/{case_id}/draft/promote": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post: operations["promote_case_draft_api_v1_workspaces__workspace_id__cases__case_id__draft_promote_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/workspaces/{workspace_id}/cases/{case_id}/draft/run": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post: operations["run_draft_api_v1_workspaces__workspace_id__cases__case_id__draft_run_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/workspaces/{workspace_id}/cases/{case_id}/draft/validate": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post: operations["validate_case_draft_api_v1_workspaces__workspace_id__cases__case_id__draft_validate_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/workspaces/{workspace_id}/cases/{case_id}/revisions": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get: operations["list_case_revisions_api_v1_workspaces__workspace_id__cases__case_id__revisions_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/workspaces/{workspace_id}/cases/{case_id}/revisions/{revision_id}/archive": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post: operations["archive_case_revision_api_v1_workspaces__workspace_id__cases__case_id__revisions__revision_id__archive_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/workspaces/{workspace_id}/credential-references": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get: operations["list_credential_references_api_v1_workspaces__workspace_id__credential_references_get"];
        put?: never;
        post: operations["create_credential_reference_api_v1_workspaces__workspace_id__credential_references_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/workspaces/{workspace_id}/credential-references/{credential_ref}/revoke": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post: operations["revoke_credential_reference_api_v1_workspaces__workspace_id__credential_references__credential_ref__revoke_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/workspaces/{workspace_id}/credential-references/{credential_ref}/rotate": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post: operations["rotate_credential_reference_api_v1_workspaces__workspace_id__credential_references__credential_ref__rotate_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/workspaces/{workspace_id}/exploration-jobs": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post: operations["create_exploration_job_api_v1_workspaces__workspace_id__exploration_jobs_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/workspaces/{workspace_id}/exploration-jobs/{job_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get: operations["get_exploration_job_api_v1_workspaces__workspace_id__exploration_jobs__job_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/workspaces/{workspace_id}/exports": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post: operations["export_bundle_api_v1_workspaces__workspace_id__exports_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/workspaces/{workspace_id}/imports": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post: operations["import_bundle_api_v1_workspaces__workspace_id__imports_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/workspaces/{workspace_id}/issue-packages/{package_id}/content": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get: operations["download_issue_package_api_v1_workspaces__workspace_id__issue_packages__package_id__content_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/workspaces/{workspace_id}/jobs/{job_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get: operations["get_job_api_v1_workspaces__workspace_id__jobs__job_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/workspaces/{workspace_id}/memberships": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get: operations["list_memberships_api_v1_workspaces__workspace_id__memberships_get"];
        put?: never;
        post: operations["add_membership_api_v1_workspaces__workspace_id__memberships_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/workspaces/{workspace_id}/memberships/{user_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        delete: operations["delete_membership_api_v1_workspaces__workspace_id__memberships__user_id__delete"];
        options?: never;
        head?: never;
        patch: operations["patch_membership_api_v1_workspaces__workspace_id__memberships__user_id__patch"];
        trace?: never;
    };
    "/api/v1/workspaces/{workspace_id}/proposals/{proposal_id}/apply": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post: operations["apply_proposal_api_v1_workspaces__workspace_id__proposals__proposal_id__apply_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/workspaces/{workspace_id}/reports/{report_id}/content": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get: operations["download_report_api_v1_workspaces__workspace_id__reports__report_id__content_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/workspaces/{workspace_id}/requirements/{requirement_id}/impact": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get: operations["requirement_impact_api_v1_workspaces__workspace_id__requirements__requirement_id__impact_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/workspaces/{workspace_id}/revisions/export": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get: operations["export_revisions_api_v1_workspaces__workspace_id__revisions_export_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/workspaces/{workspace_id}/revisions/import": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post: operations["import_revisions_api_v1_workspaces__workspace_id__revisions_import_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/workspaces/{workspace_id}/runs": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get: operations["list_runs_api_v1_workspaces__workspace_id__runs_get"];
        put?: never;
        post: operations["submit_run_api_v1_workspaces__workspace_id__runs_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/workspaces/{workspace_id}/runs/{run_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get: operations["get_run_state_api_v1_workspaces__workspace_id__runs__run_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/workspaces/{workspace_id}/runs/{run_id}/comparison": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get: operations["compare_runs_api_v1_workspaces__workspace_id__runs__run_id__comparison_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/workspaces/{workspace_id}/runs/{run_id}/controls": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get: operations["list_controls_api_v1_workspaces__workspace_id__runs__run_id__controls_get"];
        put?: never;
        post: operations["request_control_api_v1_workspaces__workspace_id__runs__run_id__controls_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/workspaces/{workspace_id}/runs/{run_id}/detail": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get: operations["get_run_detail_api_v1_workspaces__workspace_id__runs__run_id__detail_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/workspaces/{workspace_id}/runs/{run_id}/diagnostics": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get: operations["list_diagnostics_api_v1_workspaces__workspace_id__runs__run_id__diagnostics_get"];
        put?: never;
        post: operations["create_diagnostic_api_v1_workspaces__workspace_id__runs__run_id__diagnostics_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/workspaces/{workspace_id}/runs/{run_id}/events": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get: operations["list_events_api_v1_workspaces__workspace_id__runs__run_id__events_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/workspaces/{workspace_id}/runs/{run_id}/events/stream": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get: operations["stream_events_api_v1_workspaces__workspace_id__runs__run_id__events_stream_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/workspaces/{workspace_id}/runs/{run_id}/healing": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get: operations["list_run_healing_api_v1_workspaces__workspace_id__runs__run_id__healing_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/workspaces/{workspace_id}/runs/{run_id}/issue-packages": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post: operations["create_issue_package_api_v1_workspaces__workspace_id__runs__run_id__issue_packages_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/workspaces/{workspace_id}/runs/{run_id}/reports": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get: operations["list_reports_api_v1_workspaces__workspace_id__runs__run_id__reports_get"];
        put?: never;
        post: operations["create_report_api_v1_workspaces__workspace_id__runs__run_id__reports_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/workspaces/{workspace_id}/runs/{run_id}/result": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get: operations["get_run_result_api_v1_workspaces__workspace_id__runs__run_id__result_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/workspaces/{workspace_id}/schedules": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get: operations["list_schedules_api_v1_workspaces__workspace_id__schedules_get"];
        put?: never;
        post: operations["create_schedule_api_v1_workspaces__workspace_id__schedules_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/workspaces/{workspace_id}/schedules/{schedule_id}/disable": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post: operations["disable_schedule_api_v1_workspaces__workspace_id__schedules__schedule_id__disable_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/workspaces/{workspace_id}/schedules/{schedule_id}/enable": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post: operations["enable_schedule_api_v1_workspaces__workspace_id__schedules__schedule_id__enable_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/workspaces/{workspace_id}/schedules/{schedule_id}/occurrences": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get: operations["list_occurrences_api_v1_workspaces__workspace_id__schedules__schedule_id__occurrences_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/workspaces/{workspace_id}/schedules/{schedule_id}/revisions": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post: operations["add_revision_api_v1_workspaces__workspace_id__schedules__schedule_id__revisions_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/workspaces/{workspace_id}/sources": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get: operations["list_sources_api_v1_workspaces__workspace_id__sources_get"];
        put?: never;
        post: operations["create_source_api_v1_workspaces__workspace_id__sources_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/workspaces/{workspace_id}/sources/{source_id}/extract": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post: operations["extract_source_api_v1_workspaces__workspace_id__sources__source_id__extract_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/workspaces/{workspace_id}/sources/{source_id}/revisions": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get: operations["list_source_revisions_api_v1_workspaces__workspace_id__sources__source_id__revisions_get"];
        put?: never;
        post: operations["upload_source_revision_api_v1_workspaces__workspace_id__sources__source_id__revisions_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/workspaces/{workspace_id}/sources/{source_id}/revisions/{revision_no}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get: operations["get_source_revision_api_v1_workspaces__workspace_id__sources__source_id__revisions__revision_no__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/workspaces/{workspace_id}/suites/{suite_id}/revisions/{revision_id}/bind": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post: operations["bind_suite_revision_api_v1_workspaces__workspace_id__suites__suite_id__revisions__revision_id__bind_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/workspaces/{workspace_id}/{kind}s": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get: operations["list_entities_api_v1_workspaces__workspace_id___kind_s_get"];
        put?: never;
        post: operations["create_entity_api_v1_workspaces__workspace_id___kind_s_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/workspaces/{workspace_id}/{kind}s/{entity_id}/revisions": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get: operations["list_entity_revisions_api_v1_workspaces__workspace_id___kind_s__entity_id__revisions_get"];
        put?: never;
        post: operations["promote_entity_revision_api_v1_workspaces__workspace_id___kind_s__entity_id__revisions_post"];
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
        get: operations["_health_live_health_live_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/health/ready": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get: operations["health_ready_health_ready_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/metrics": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get: operations["metrics_metrics_get"];
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
        AlignmentResponse: {
            a_status?: string | null;
            a_verdict?: string | null;
            aligned: boolean;
            assertions: components["schemas"]["ComparisonAssertionResponse"][];
            b_status?: string | null;
            b_verdict?: string | null;
            logical_key: string;
            reason?: string | null;
        };
        AnchorType: "section" | "page" | "paragraph" | "heading" | "table_cell";
        ApplicationCreateRequest: {
            name: string;
            slug: string;
        };
        ApplyProposalRequest: {
            case_id: string;
            expected_edit_version: number;
        };
        ApplyProposalResponse: {
            case_id: string;
            content: {
                [key: string]: unknown;
            };
            diff: {
                [key: string]: unknown;
            }[];
            edit_version: number;
            proposal_id: string;
        };
        ArtifactResponse: {
            artifact_id: string;
            available_at?: string | null;
            created_at: string;
            digest?: string | null;
            kind: string;
            media_type?: string | null;
            redacted: boolean;
            retention: string;
            run_id?: string | null;
            size_bytes?: number | null;
            state: string;
            tombstoned_at?: string | null;
            unavailable_reason?: string | null;
        };
        ArtifactSummaryResponse: {
            artifact_id: string;
            digest?: string | null;
            kind: string;
            media_type?: string | null;
            redacted: boolean;
            state: string;
            unavailable_reason?: string | null;
        };
        AssertionDetailResponse: {
            assertion_id: string;
            checkpoint_id: string;
            proof: {
                [key: string]: unknown;
            };
            result: string;
        };
        AuthoringJobRequest: {
            expectations: string[];
            goal: string;
            model_requested?: string | null;
            requirement_keys: string[];
            sources: components["schemas"]["SourceInput"][];
            url?: string | null;
        };
        BindResponse: {
            executions: components["schemas"]["PlannedExecutionResponse"][];
            facts: string[];
            fixture_refs: string[];
            suite_logical_key: string;
            suite_revision_id: string;
        };
        Body_upload_source_revision_api_v1_workspaces__workspace_id__sources__source_id__revisions_post: {
            file: string;
            logical_key: string;
        };
        BootstrapRequest: {
            nonce: string;
        };
        BundleImportRequest: {
            bundle: {
                [key: string]: unknown;
            };
        };
        BundleResponse: {
            kind: string;
            revisions: {
                [key: string]: unknown;
            }[];
            schema_version: string;
        };
        ComparisonAssertionResponse: {
            a_expected?: string | null;
            a_observed?: string | null;
            a_status?: string | null;
            aligned: boolean;
            assertion_id: string;
            b_expected?: string | null;
            b_observed?: string | null;
            b_status?: string | null;
            checkpoint_id: string;
        };
        ComparisonMetricResponse: {
            cost_currency?: string | null;
            cost_state: string;
            cost_total?: string | null;
            gate?: string | null;
            status: string;
            usage_input_tokens: number;
            usage_output_tokens: number;
            usage_state: string;
            verdict?: string | null;
        };
        ComparisonResponse: {
            alignment: components["schemas"]["AlignmentResponse"][];
            config_diff: components["schemas"]["ConfigDiffResponse"][];
            denominators?: {
                [key: string]: unknown;
            } | null;
            metrics: {
                [key: string]: components["schemas"]["ComparisonMetricResponse"];
            };
            provenance?: {
                [key: string]: unknown;
            } | null;
            run_a: string;
            run_b: string;
        };
        ConfigDiffResponse: {
            a?: unknown | null;
            b?: unknown | null;
            equal: boolean;
            field: string;
        };
        ConfirmSourcesRequest: {
            source_names: string[];
        };
        ConfirmSourcesResponse: {
            content: {
                [key: string]: unknown;
            };
            edit_version: number;
            entity_id: string;
        };
        ContentRequest: {
            content: {
                [key: string]: unknown;
            };
        };
        ControlAction: "pause" | "resume" | "cancel";
        ControlListEntry: {
            action: string;
            control_id: string;
            effective_at?: string | null;
            effective_reason?: string | null;
            requested_at: string;
        };
        ControlListResponse: {
            controls: components["schemas"]["ControlListEntry"][];
        };
        ControlRequestBody: {
            action: components["schemas"]["ControlAction"];
            reason?: string | null;
        };
        ControlResponse: {
            control_id: string;
            control_revision: number;
        };
        ControlStateResponse: {
            action: string;
            control_id: string;
            effective_at?: string | null;
            effective_reason?: string | null;
            requested_at: string;
        };
        CredentialReferenceCreateRequest: {
            credential_ref: string;
            env_var_name: string;
        };
        CredentialReferenceListResponse: {
            items: components["schemas"]["CredentialReferenceResponse"][];
        };
        CredentialReferenceResponse: {
            algorithm?: string | null;
            credential_ref: string;
            kind: string;
            rotated_from?: string | null;
            status: string;
            version: number;
        };
        CredentialRevokeRequest: {
            reason: string;
        };
        CredentialRevokeResponse: {
            credential_ref: string;
            revoked_versions: number;
        };
        CredentialRotateRequest: {
            value: string;
        };
        CredentialVersionResponse: {
            credential_ref: string;
            status: string;
            version: number;
        };
        CsrfResponse: {
            csrf_token: string;
        };
        DiagnosticListResponse: {
            items: components["schemas"]["DiagnosticResponse"][];
        };
        DiagnosticResponse: {
            confidence?: string | null;
            created_at: string;
            diagnostic_id: string;
            evidence_refs: string[];
            explanation?: string | null;
            label: string;
            model_call_id?: string | null;
            run_id: string;
            state: string;
        };
        DraftPatchRequest: {
            content: {
                [key: string]: unknown;
            };
        };
        DraftResponse: {
            content: {
                [key: string]: unknown;
            };
            edit_version: number;
            entity_id: string;
            updated_at: string;
            updated_by: string;
        };
        DraftRunRequest: {
            environment_revision_id?: string | null;
            gate_profile: string;
            idempotency_key: string;
        };
        DraftRunResponse: {
            blocked: boolean;
            planned_executions: number;
            provisional: boolean;
            run_id: string;
            snapshot_digest: string;
        };
        DraftValidateResponse: {
            field_errors: {
                [key: string]: unknown;
            }[];
            valid: boolean;
        };
        EntityCreateRequest: {
            logical_key: string;
        };
        EntityResponse: {
            id: string;
            logical_key: string;
        };
        ErrorCode: "input_invalid" | "not_found" | "duplicate_key" | "unsupported_schema_version" | "unsupported_node" | "unknown_operation" | "unknown_reference" | "duplicate_id" | "invalid_capture" | "type_mismatch" | "secret_interpolation" | "source_unconfirmed" | "empty_assertion" | "incomplete_branch_proof" | "loop_bound_invalid" | "capability_mismatch" | "unsafe_json" | "secret_serialization" | "document_too_large" | "alias_limit_exceeded" | "custom_tag_rejected" | "capability_unavailable" | "permission_denied" | "fixture_failed" | "locator_missing" | "locator_ambiguous" | "identity_mismatch" | "action_timeout" | "action_outcome_unknown" | "provider_auth" | "provider_quota" | "provider_rate_limit" | "provider_timeout" | "provider_schema" | "verification_error" | "evidence_missing" | "evidence_redaction_failed" | "storage_unavailable" | "lease_lost" | "worker_lost" | "resource_exhausted";
        ErrorResponse: {
            code: components["schemas"]["ErrorCode"];
            field_errors: components["schemas"]["FieldErrorModel"][];
            message: string;
            request_id?: string | null;
            retryable: boolean;
        };
        ExecutionDetailResponse: {
            assertions: components["schemas"]["AssertionDetailResponse"][];
            execution_id: string;
            logical_key: string;
            status: string;
            verdict?: string | null;
        };
        ExecutionStateResponse: {
            execution_id: string;
            logical_key: string;
            status: string;
            verdict?: string | null;
        };
        ExplorationJobRequest: {
            environment_revision_id: string;
            goal: string;
            max_depth: number;
            max_pages: number;
        };
        ExplorationResponse: {
            actions: {
                [key: string]: unknown;
            }[];
            coverage_gaps: {
                [key: string]: unknown;
            }[];
            environment_revision_id?: string | null;
            error_reason?: string | null;
            job_id: string;
            pages: {
                [key: string]: unknown;
            }[];
            proposals: {
                [key: string]: unknown;
            }[];
            state: string;
            write_allowed: boolean;
        };
        ExportRequest: {
            format: "yaml" | "json";
            kinds?: string[] | null;
        };
        ExportResponse: {
            content: string;
            digest: string;
            format: string;
            schema_version: string;
        };
        FieldErrorModel: {
            code: components["schemas"]["ErrorCode"];
            message: string;
            path: (string | number)[];
        };
        HTTPValidationError: {
            detail?: components["schemas"]["ValidationError"][];
        };
        HealingListResponse: {
            items: components["schemas"]["HealingRecordResponse"][];
        };
        HealingRecordResponse: {
            actor: string;
            actual_signature?: string | null;
            actual_target?: {
                [key: string]: unknown;
            } | null;
            attempt_id?: string | null;
            attempt_ref: string;
            case_id?: string | null;
            case_revision_id?: string | null;
            decision: string;
            dispatch_outcome?: string | null;
            error?: string | null;
            execution_id?: string | null;
            expected_signature?: string | null;
            guard_checks: string[];
            node_id: string;
            opportunity_id: string;
            original_target?: {
                [key: string]: unknown;
            } | null;
            postconditions_ok?: boolean | null;
            proposal?: {
                [key: string]: unknown;
            } | null;
            ranking?: {
                [key: string]: unknown;
            } | null;
            record_id: string;
            recorded_at: string;
            refusal_reason?: string | null;
            run_id: string;
            source_run_id?: string | null;
        };
        HealthResponse: {
            schema_versions: {
                [key: string]: string;
            };
            status: string;
            version: string;
        };
        ImpactLinkResponse: {
            affected_assertions: string[];
            affected_nodes: string[];
            case_id: string;
            case_revision_id: string;
            logical_key: string;
            needs_review: boolean;
            review_marked_at?: string | null;
            revision_no: number;
            source_names: string[];
        };
        ImpactResponse: {
            latest_revision_no?: number | null;
            links: components["schemas"]["ImpactLinkResponse"][];
            logical_key: string;
            requirement_id: string;
        };
        ImportRequest: {
            content: string;
            format: "yaml" | "json";
        };
        ImportResponse: {
            imported: components["schemas"]["PromotionSummary"][];
        };
        IssuePackageResponse: {
            artifact_id: string;
            created_at: string;
            digest?: string | null;
            package_id: string;
            preview: {
                [key: string]: unknown;
            };
            run_id: string;
        };
        JobResponse: {
            created_at: string;
            error_reason?: string | null;
            finished_at?: string | null;
            job_id: string;
            kind: string;
            model_requested?: string | null;
            proposals: components["schemas"]["ProposalResponse"][];
            started_at?: string | null;
            state: string;
        };
        LoginRequest: {
            password: string;
            username: string;
        };
        MembershipCreateRequest: {
            permission_flags: string[];
            role: components["schemas"]["Role"];
            user_id?: string | null;
            username?: string | null;
        };
        MembershipPatchRequest: {
            role: components["schemas"]["Role"];
        };
        MembershipResponse: {
            permission_flags: string[];
            role: components["schemas"]["Role"];
            user_id: string;
            workspace_id: string;
        };
        OccurrenceListResponse: {
            items: components["schemas"]["OccurrenceResponse"][];
        };
        OccurrenceResponse: {
            fold: number;
            local_wall_time: string;
            occurrence_id: string;
            occurrence_key: string;
            reason?: string | null;
            run_id?: string | null;
            schedule_id: string;
            schedule_revision_id: string;
            scheduled_at?: string | null;
            state: string;
        };
        PlannedExecutionResponse: {
            case_logical_key: string;
            case_revision_id?: string | null;
            dataset_row_index?: number | null;
            execution_key: string;
            parameters: {
                [key: string]: unknown;
            };
        };
        PrincipalResponse: {
            session_id?: string | null;
            token_id?: string | null;
            user_id: string;
            username: string;
        };
        PromotionResponse: {
            content_digest: string;
            entity_id: string;
            promoted_at: string;
            promoted_by: string;
            revision_id: string;
            revision_no: number;
            supersedes?: string | null;
        };
        PromotionSummary: {
            content_digest: string;
            entity_id: string;
            revision_id: string;
            revision_no: number;
        };
        ProposalResponse: {
            case_kind: string;
            content: {
                [key: string]: unknown;
            };
            job_id: string;
            proposal_id: string;
            provenance: {
                [key: string]: unknown;
            }[];
            rejection_reason?: string | null;
            requirement_keys: string[];
            status: string;
            title: string;
        };
        ReportCreateRequest: {
            format: string;
        };
        ReportListResponse: {
            items: components["schemas"]["ReportResponse"][];
        };
        ReportResponse: {
            artifact_id: string;
            created_at: string;
            digest?: string | null;
            format: string;
            media_type: string;
            report_id: string;
            run_id: string;
        };
        RevisionResponse: {
            archived_at?: string | null;
            author: string;
            content: {
                [key: string]: unknown;
            };
            content_digest: string;
            entity_id: string;
            lifecycle: string;
            promoted_at?: string | null;
            promoted_by?: string | null;
            revision_id: string;
            revision_no: number;
            supersedes?: string | null;
        };
        Role: "owner" | "editor" | "runner" | "viewer";
        RunDetailResponse: {
            annotations: string[];
            artifacts: components["schemas"]["ArtifactSummaryResponse"][];
            controls: components["schemas"]["ControlStateResponse"][];
            executions: components["schemas"]["ExecutionDetailResponse"][];
            gate?: string | null;
            reasons: string[];
            run_id: string;
            snapshot: components["schemas"]["SnapshotSummaryResponse"];
            status: string;
            terminal: boolean;
            usage: components["schemas"]["UsageSummaryResponse"];
            verdict?: string | null;
        };
        RunListItemResponse: {
            annotations: string[];
            created_at: string;
            environment_revision_id?: string | null;
            executions: components["schemas"]["ExecutionStateResponse"][];
            finalized_at?: string | null;
            gate?: string | null;
            observation_mode?: string | null;
            policy?: string | null;
            reasons: string[];
            run_id: string;
            status: string;
            verdict?: string | null;
        };
        RunListResponse: {
            items: components["schemas"]["RunListItemResponse"][];
            next_cursor?: string | null;
            total: number;
        };
        RunResultResponse: {
            executions: components["schemas"]["ExecutionStateResponse"][];
            gate?: string | null;
            reasons: string[];
            run_id: string;
            status: string;
            terminal: boolean;
            verdict?: string | null;
        };
        RunStateResponse: {
            controls: components["schemas"]["ControlStateResponse"][];
            executions: components["schemas"]["ExecutionStateResponse"][];
            gate?: string | null;
            last_run_seq: number;
            reasons: string[];
            run_id: string;
            snapshot_digest?: string | null;
            status: string;
            verdict?: string | null;
        };
        ScheduleCreateRequest: {
            logical_key: string;
        };
        ScheduleListResponse: {
            items: components["schemas"]["ScheduleResponse"][];
        };
        ScheduleResponse: {
            enabled: boolean;
            latest_revision?: components["schemas"]["ScheduleRevisionSummary"] | null;
            logical_key: string;
            schedule_id: string;
        };
        ScheduleRevisionRequest: {
            content: {
                [key: string]: unknown;
            };
        };
        ScheduleRevisionSummary: {
            content: {
                [key: string]: unknown;
            };
            revision_id: string;
            revision_no: number;
        };
        SessionResponse: {
            csrf_token?: string | null;
            expires_at: string;
            user_id: string;
            username: string;
        };
        SnapshotSummaryResponse: {
            budgets?: {
                [key: string]: unknown;
            } | null;
            cache_profile?: string | null;
            calibration_ref?: string | null;
            content_digests: string[];
            environment_revision?: string | null;
            gate_profile?: string | null;
            observation_mode?: string | null;
            policy?: string | null;
            provisional: boolean;
        };
        SourceAnchor: {
            column?: number | null;
            row?: number | null;
            table_index?: number | null;
            type: components["schemas"]["AnchorType"];
            value?: string | number | null;
        };
        SourceCreateRequest: {
            logical_key: string;
        };
        SourceDetailResponse: {
            revision: components["schemas"]["SourceRevisionResponse"];
            segments: components["schemas"]["SourceSegmentResponse"][];
        };
        SourceEntityResponse: {
            id: string;
            logical_key: string;
        };
        SourceInput: {
            revision_no?: number | null;
            source_id: string;
        };
        SourceRevisionResponse: {
            created_at: string;
            file_digest: string;
            filename: string;
            logical_key: string;
            media_type: string;
            privacy_class: string;
            revision_id: string;
            revision_no: number;
            segment_count: number;
            size_bytes: number;
            source_id: string;
            state: string;
            unextractable_reason?: string | null;
        };
        SourceSegmentResponse: {
            anchor: components["schemas"]["SourceAnchor"];
            ordinal: number;
            privacy: string;
            text: string;
            text_digest: string;
        };
        SubmitRunRequest: {
            budgets: {
                [key: string]: number;
            };
            case_revision_ids: string[];
            environment_revision_id?: string | null;
            gate_profile: string;
            idempotency_key?: string | null;
            policy: string;
            provided_capabilities: string[];
            suite_revision_id?: string | null;
        };
        SubmitRunResponse: {
            blocked: boolean;
            blocked_reasons: string[];
            planned_executions: number;
            run_id: string;
            snapshot_digest: string;
            status: string;
        };
        TokenCreateRequest: {
            expires_at?: string | null;
            name: string;
            permission_flags: string[];
            scopes: string[];
        };
        TokenIssuedResponse: {
            token: string;
            token_id: string;
        };
        UsageSummaryResponse: {
            cost_currency?: string | null;
            cost_state: string;
            cost_total?: string | null;
            input_tokens: number;
            output_tokens: number;
            settled_calls: number;
            state: string;
            unknown_calls: number;
        };
        ValidationError: {
            ctx?: Record<string, never>;
            input?: unknown;
            loc: (string | number)[];
            msg: string;
            type: string;
        };
        WorkspaceCreateRequest: {
            name: string;
            slug: string;
        };
        WorkspacePatchRequest: {
            name: string;
        };
        WorkspaceResponse: {
            id: string;
            name: string;
            slug: string;
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
    refresh_csrf_api_v1_auth_csrf_post: {
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
                    "application/json": components["schemas"]["CsrfResponse"];
                };
            };
        };
    };
    local_bootstrap_api_v1_auth_local_bootstrap_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["BootstrapRequest"];
            };
        };
        responses: {
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SessionResponse"];
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
    login_api_v1_auth_login_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["LoginRequest"];
            };
        };
        responses: {
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SessionResponse"];
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
    logout_api_v1_auth_logout_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
    current_session_api_v1_auth_session_get: {
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
                    "application/json": components["schemas"]["PrincipalResponse"];
                };
            };
        };
    };
    create_token_api_v1_auth_tokens_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["TokenCreateRequest"];
            };
        };
        responses: {
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TokenIssuedResponse"];
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
    _list_schemas_api_v1_schemas_get: {
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
    _get_schema_api_v1_schemas__name___version__get: {
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
    list_workspaces_api_v1_workspaces_get: {
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
                    "application/json": components["schemas"]["WorkspaceResponse"][];
                };
            };
        };
    };
    create_workspace_api_v1_workspaces_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["WorkspaceCreateRequest"];
            };
        };
        responses: {
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["WorkspaceResponse"];
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
    get_workspace_api_v1_workspaces__workspace_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                workspace_id: string;
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
                    "application/json": components["schemas"]["WorkspaceResponse"];
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
    patch_workspace_api_v1_workspaces__workspace_id__patch: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                workspace_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["WorkspacePatchRequest"];
            };
        };
        responses: {
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["WorkspaceResponse"];
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
    list_applications_api_v1_workspaces__workspace_id__applications_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                workspace_id: string;
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
                    "application/json": components["schemas"]["EntityResponse"][];
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
    create_application_api_v1_workspaces__workspace_id__applications_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                workspace_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ApplicationCreateRequest"];
            };
        };
        responses: {
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["EntityResponse"];
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
    list_environment_revisions_api_v1_workspaces__workspace_id__applications__application_id__environment_revisions_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                workspace_id: string;
                application_id: string;
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
                    "application/json": components["schemas"]["RevisionResponse"][];
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
    promote_environment_revision_api_v1_workspaces__workspace_id__applications__application_id__environment_revisions_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                workspace_id: string;
                application_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ContentRequest"];
            };
        };
        responses: {
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PromotionResponse"];
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
    get_artifact_api_v1_workspaces__workspace_id__artifacts__artifact_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                workspace_id: string;
                artifact_id: string;
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
                    "application/json": components["schemas"]["ArtifactResponse"];
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
    get_artifact_content_api_v1_workspaces__workspace_id__artifacts__artifact_id__content_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                workspace_id: string;
                artifact_id: string;
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
    create_authoring_job_api_v1_workspaces__workspace_id__authoring_jobs_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                workspace_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["AuthoringJobRequest"];
            };
        };
        responses: {
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["JobResponse"];
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
    list_cases_api_v1_workspaces__workspace_id__cases_get: {
        parameters: {
            query?: {
                logical_key?: string | null;
                limit?: number;
            };
            header?: never;
            path: {
                workspace_id: string;
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
                    "application/json": components["schemas"]["EntityResponse"][];
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
    create_case_api_v1_workspaces__workspace_id__cases_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                workspace_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["EntityCreateRequest"];
            };
        };
        responses: {
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["EntityResponse"];
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
    get_case_draft_api_v1_workspaces__workspace_id__cases__case_id__draft_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                workspace_id: string;
                case_id: string;
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
    patch_case_draft_api_v1_workspaces__workspace_id__cases__case_id__draft_patch: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                workspace_id: string;
                case_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["DraftPatchRequest"];
            };
        };
        responses: {
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DraftResponse"];
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
    confirm_sources_api_v1_workspaces__workspace_id__cases__case_id__draft_confirm_sources_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                workspace_id: string;
                case_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ConfirmSourcesRequest"];
            };
        };
        responses: {
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ConfirmSourcesResponse"];
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
    promote_case_draft_api_v1_workspaces__workspace_id__cases__case_id__draft_promote_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                workspace_id: string;
                case_id: string;
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
                    "application/json": components["schemas"]["PromotionResponse"];
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
    run_draft_api_v1_workspaces__workspace_id__cases__case_id__draft_run_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                workspace_id: string;
                case_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["DraftRunRequest"];
            };
        };
        responses: {
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DraftRunResponse"];
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
    validate_case_draft_api_v1_workspaces__workspace_id__cases__case_id__draft_validate_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                workspace_id: string;
                case_id: string;
            };
            cookie?: never;
        };
        requestBody?: {
            content: {
                "application/json": components["schemas"]["ContentRequest"] | null;
            };
        };
        responses: {
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DraftValidateResponse"];
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
    list_case_revisions_api_v1_workspaces__workspace_id__cases__case_id__revisions_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                workspace_id: string;
                case_id: string;
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
                    "application/json": components["schemas"]["RevisionResponse"][];
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
    archive_case_revision_api_v1_workspaces__workspace_id__cases__case_id__revisions__revision_id__archive_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                workspace_id: string;
                case_id: string;
                revision_id: string;
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
                    "application/json": components["schemas"]["RevisionResponse"];
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
    list_credential_references_api_v1_workspaces__workspace_id__credential_references_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                workspace_id: string;
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
                    "application/json": components["schemas"]["CredentialReferenceListResponse"];
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
    create_credential_reference_api_v1_workspaces__workspace_id__credential_references_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                workspace_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CredentialReferenceCreateRequest"];
            };
        };
        responses: {
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CredentialVersionResponse"];
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
    revoke_credential_reference_api_v1_workspaces__workspace_id__credential_references__credential_ref__revoke_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                workspace_id: string;
                credential_ref: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CredentialRevokeRequest"];
            };
        };
        responses: {
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CredentialRevokeResponse"];
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
    rotate_credential_reference_api_v1_workspaces__workspace_id__credential_references__credential_ref__rotate_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                workspace_id: string;
                credential_ref: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CredentialRotateRequest"];
            };
        };
        responses: {
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CredentialVersionResponse"];
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
    create_exploration_job_api_v1_workspaces__workspace_id__exploration_jobs_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                workspace_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ExplorationJobRequest"];
            };
        };
        responses: {
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ExplorationResponse"];
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
    get_exploration_job_api_v1_workspaces__workspace_id__exploration_jobs__job_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                workspace_id: string;
                job_id: string;
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
                    "application/json": components["schemas"]["ExplorationResponse"];
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
    export_bundle_api_v1_workspaces__workspace_id__exports_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                workspace_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ExportRequest"];
            };
        };
        responses: {
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ExportResponse"];
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
    import_bundle_api_v1_workspaces__workspace_id__imports_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                workspace_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ImportRequest"];
            };
        };
        responses: {
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ImportResponse"];
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
    download_issue_package_api_v1_workspaces__workspace_id__issue_packages__package_id__content_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                workspace_id: string;
                package_id: string;
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
    get_job_api_v1_workspaces__workspace_id__jobs__job_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                workspace_id: string;
                job_id: string;
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
                    "application/json": components["schemas"]["JobResponse"];
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
    list_memberships_api_v1_workspaces__workspace_id__memberships_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                workspace_id: string;
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
                    "application/json": components["schemas"]["MembershipResponse"][];
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
    add_membership_api_v1_workspaces__workspace_id__memberships_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                workspace_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["MembershipCreateRequest"];
            };
        };
        responses: {
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["MembershipResponse"];
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
    delete_membership_api_v1_workspaces__workspace_id__memberships__user_id__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                workspace_id: string;
                user_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
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
    patch_membership_api_v1_workspaces__workspace_id__memberships__user_id__patch: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                workspace_id: string;
                user_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["MembershipPatchRequest"];
            };
        };
        responses: {
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["MembershipResponse"];
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
    apply_proposal_api_v1_workspaces__workspace_id__proposals__proposal_id__apply_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                workspace_id: string;
                proposal_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ApplyProposalRequest"];
            };
        };
        responses: {
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ApplyProposalResponse"];
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
    download_report_api_v1_workspaces__workspace_id__reports__report_id__content_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                workspace_id: string;
                report_id: string;
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
    requirement_impact_api_v1_workspaces__workspace_id__requirements__requirement_id__impact_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                workspace_id: string;
                requirement_id: string;
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
                    "application/json": components["schemas"]["ImpactResponse"];
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
    export_revisions_api_v1_workspaces__workspace_id__revisions_export_get: {
        parameters: {
            query: {
                kind: string;
            };
            header?: never;
            path: {
                workspace_id: string;
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
                    "application/json": components["schemas"]["BundleResponse"];
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
    import_revisions_api_v1_workspaces__workspace_id__revisions_import_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                workspace_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["BundleImportRequest"];
            };
        };
        responses: {
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PromotionResponse"][];
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
    list_runs_api_v1_workspaces__workspace_id__runs_get: {
        parameters: {
            query?: {
                status?: string | null;
                verdict?: string | null;
                healed?: boolean | null;
                policy?: string | null;
                environment_revision_id?: string | null;
                case_logical_key?: string | null;
                date_from?: string | null;
                date_to?: string | null;
                cursor?: string | null;
                limit?: number;
            };
            header?: never;
            path: {
                workspace_id: string;
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
                    "application/json": components["schemas"]["RunListResponse"];
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
    submit_run_api_v1_workspaces__workspace_id__runs_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                workspace_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["SubmitRunRequest"];
            };
        };
        responses: {
            202: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SubmitRunResponse"];
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
    get_run_state_api_v1_workspaces__workspace_id__runs__run_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                workspace_id: string;
                run_id: string;
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
                    "application/json": components["schemas"]["RunStateResponse"];
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
    compare_runs_api_v1_workspaces__workspace_id__runs__run_id__comparison_get: {
        parameters: {
            query: {
                against: string;
            };
            header?: never;
            path: {
                workspace_id: string;
                run_id: string;
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
                    "application/json": components["schemas"]["ComparisonResponse"];
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
    list_controls_api_v1_workspaces__workspace_id__runs__run_id__controls_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                workspace_id: string;
                run_id: string;
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
                    "application/json": components["schemas"]["ControlListResponse"];
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
    request_control_api_v1_workspaces__workspace_id__runs__run_id__controls_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                workspace_id: string;
                run_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ControlRequestBody"];
            };
        };
        responses: {
            202: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ControlResponse"];
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
    get_run_detail_api_v1_workspaces__workspace_id__runs__run_id__detail_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                workspace_id: string;
                run_id: string;
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
                    "application/json": components["schemas"]["RunDetailResponse"];
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
    list_diagnostics_api_v1_workspaces__workspace_id__runs__run_id__diagnostics_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                workspace_id: string;
                run_id: string;
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
                    "application/json": components["schemas"]["DiagnosticListResponse"];
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
    create_diagnostic_api_v1_workspaces__workspace_id__runs__run_id__diagnostics_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                workspace_id: string;
                run_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DiagnosticResponse"];
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
    list_events_api_v1_workspaces__workspace_id__runs__run_id__events_get: {
        parameters: {
            query?: {
                cursor?: number;
                limit?: number;
            };
            header?: never;
            path: {
                workspace_id: string;
                run_id: string;
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
                    "application/json": {
                        [key: string]: unknown;
                    };
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
    stream_events_api_v1_workspaces__workspace_id__runs__run_id__events_stream_get: {
        parameters: {
            query?: {
                cursor?: number;
            };
            header?: never;
            path: {
                workspace_id: string;
                run_id: string;
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
    list_run_healing_api_v1_workspaces__workspace_id__runs__run_id__healing_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                workspace_id: string;
                run_id: string;
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
                    "application/json": components["schemas"]["HealingListResponse"];
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
    create_issue_package_api_v1_workspaces__workspace_id__runs__run_id__issue_packages_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                workspace_id: string;
                run_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["IssuePackageResponse"];
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
    list_reports_api_v1_workspaces__workspace_id__runs__run_id__reports_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                workspace_id: string;
                run_id: string;
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
                    "application/json": components["schemas"]["ReportListResponse"];
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
    create_report_api_v1_workspaces__workspace_id__runs__run_id__reports_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                workspace_id: string;
                run_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ReportCreateRequest"];
            };
        };
        responses: {
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ReportResponse"];
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
    get_run_result_api_v1_workspaces__workspace_id__runs__run_id__result_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                workspace_id: string;
                run_id: string;
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
                    "application/json": components["schemas"]["RunResultResponse"];
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
    list_schedules_api_v1_workspaces__workspace_id__schedules_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                workspace_id: string;
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
                    "application/json": components["schemas"]["ScheduleListResponse"];
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
    create_schedule_api_v1_workspaces__workspace_id__schedules_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                workspace_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ScheduleCreateRequest"];
            };
        };
        responses: {
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ScheduleResponse"];
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
    disable_schedule_api_v1_workspaces__workspace_id__schedules__schedule_id__disable_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                workspace_id: string;
                schedule_id: string;
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
                    "application/json": components["schemas"]["ScheduleResponse"];
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
    enable_schedule_api_v1_workspaces__workspace_id__schedules__schedule_id__enable_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                workspace_id: string;
                schedule_id: string;
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
                    "application/json": components["schemas"]["ScheduleResponse"];
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
    list_occurrences_api_v1_workspaces__workspace_id__schedules__schedule_id__occurrences_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                workspace_id: string;
                schedule_id: string;
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
                    "application/json": components["schemas"]["OccurrenceListResponse"];
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
    add_revision_api_v1_workspaces__workspace_id__schedules__schedule_id__revisions_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                workspace_id: string;
                schedule_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ScheduleRevisionRequest"];
            };
        };
        responses: {
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ScheduleRevisionSummary"];
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
    list_sources_api_v1_workspaces__workspace_id__sources_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                workspace_id: string;
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
                    "application/json": components["schemas"]["SourceEntityResponse"][];
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
    create_source_api_v1_workspaces__workspace_id__sources_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                workspace_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["SourceCreateRequest"];
            };
        };
        responses: {
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SourceEntityResponse"];
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
    extract_source_api_v1_workspaces__workspace_id__sources__source_id__extract_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                workspace_id: string;
                source_id: string;
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
                    "application/json": components["schemas"]["SourceDetailResponse"];
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
    list_source_revisions_api_v1_workspaces__workspace_id__sources__source_id__revisions_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                workspace_id: string;
                source_id: string;
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
                    "application/json": components["schemas"]["SourceRevisionResponse"][];
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
    upload_source_revision_api_v1_workspaces__workspace_id__sources__source_id__revisions_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                workspace_id: string;
                source_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "multipart/form-data": components["schemas"]["Body_upload_source_revision_api_v1_workspaces__workspace_id__sources__source_id__revisions_post"];
            };
        };
        responses: {
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SourceDetailResponse"];
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
    get_source_revision_api_v1_workspaces__workspace_id__sources__source_id__revisions__revision_no__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                workspace_id: string;
                source_id: string;
                revision_no: number;
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
                    "application/json": components["schemas"]["SourceDetailResponse"];
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
    bind_suite_revision_api_v1_workspaces__workspace_id__suites__suite_id__revisions__revision_id__bind_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                workspace_id: string;
                suite_id: string;
                revision_id: string;
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
                    "application/json": components["schemas"]["BindResponse"];
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
    list_entities_api_v1_workspaces__workspace_id___kind_s_get: {
        parameters: {
            query?: {
                logical_key?: string | null;
                limit?: number;
            };
            header?: never;
            path: {
                workspace_id: string;
                kind: string;
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
                    "application/json": components["schemas"]["EntityResponse"][];
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
    create_entity_api_v1_workspaces__workspace_id___kind_s_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                workspace_id: string;
                kind: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["EntityCreateRequest"];
            };
        };
        responses: {
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["EntityResponse"];
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
    list_entity_revisions_api_v1_workspaces__workspace_id___kind_s__entity_id__revisions_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                workspace_id: string;
                kind: string;
                entity_id: string;
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
                    "application/json": components["schemas"]["RevisionResponse"][];
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
    promote_entity_revision_api_v1_workspaces__workspace_id___kind_s__entity_id__revisions_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                workspace_id: string;
                kind: string;
                entity_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ContentRequest"];
            };
        };
        responses: {
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PromotionResponse"];
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
    _health_live_health_live_get: {
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
    health_ready_health_ready_get: {
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
    metrics_metrics_get: {
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
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
        };
    };
}
