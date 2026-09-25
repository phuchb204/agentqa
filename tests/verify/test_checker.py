from agentqa.contracts import AssertionSpec
from agentqa.verify.checker import check, check_all


async def test_text_visible_passes_when_text_present(page):
    await page.set_content("<ul><li>Mua sữa</li></ul>")
    spec = AssertionSpec(id="a1", kind="text_visible", value="Mua sữa")
    result = await check(page, spec)
    assert result.status == "passed"
    assert result.assertion_id == "a1"


async def test_text_visible_fails_when_text_absent(page):
    await page.set_content("<p>khác</p>")
    spec = AssertionSpec(id="a2", kind="text_visible", value="Mua sữa")
    result = await check(page, spec)
    assert result.status == "failed"


async def test_url_contains_uses_current_url(page, demo_server):
    await page.goto(f"{demo_server}/login.html")
    passed = await check(page, AssertionSpec(id="u1", kind="url_contains", value="login.html"))
    failed = await check(page, AssertionSpec(id="u2", kind="url_contains", value="index.html"))
    assert passed.status == "passed"
    assert failed.status == "failed"


async def test_check_all_returns_one_result_per_spec(page):
    await page.set_content("<p>abc</p>")
    specs = [
        AssertionSpec(id="a1", kind="text_visible", value="abc"),
        AssertionSpec(id="a2", kind="text_visible", value="xyz"),
    ]
    results = await check_all(page, specs)
    assert [r.status for r in results] == ["passed", "failed"]
