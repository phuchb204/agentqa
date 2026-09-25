from playwright.async_api import Error, Page

from agentqa.contracts import AssertionResult, AssertionSpec


async def check(page: Page, spec: AssertionSpec) -> AssertionResult:
    try:
        if spec.kind == "text_visible":
            visible = await page.is_visible(f"text={spec.value}")
            return AssertionResult(
                assertion_id=spec.id,
                status="passed" if visible else "failed",
                detail=spec.value,
            )
        if spec.kind == "url_contains":
            matched = spec.value in page.url
            return AssertionResult(
                assertion_id=spec.id,
                status="passed" if matched else "failed",
                detail=page.url,
            )
        return AssertionResult(
            assertion_id=spec.id, status="error", detail=f"unknown kind: {spec.kind}"
        )
    except Error as exc:
        return AssertionResult(assertion_id=spec.id, status="error", detail=str(exc))


async def check_all(page: Page, specs: list[AssertionSpec]) -> list[AssertionResult]:
    return [await check(page, spec) for spec in specs]
