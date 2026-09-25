import pytest

from agentqa.agent.executor import ActionExecutionError, execute
from agentqa.contracts import Action


async def test_execute_navigate_loads_login_page(page, demo_server):
    await execute(page, Action(type="navigate", target=f"{demo_server}/login.html"))
    assert page.url.endswith("/login.html")


async def test_execute_fill_sets_input_value(page):
    await page.set_content("<input id='name'>")
    await execute(page, Action(type="fill", target="#name", value="Xin chào"))
    assert await page.input_value("#name") == "Xin chào"


async def test_execute_click_triggers_script(page):
    await page.set_content(
        "<button id='go'>Go</button>"
        "<script>document.getElementById('go').onclick=()=>{document.title='clicked'}</script>"
    )
    await execute(page, Action(type="click", target="#go"))
    assert await page.title() == "clicked"


async def test_execute_finish_is_noop(page):
    await page.set_content("<p>x</p>")
    await execute(page, Action(type="finish"))
    assert "<p>x</p>" in await page.content()


async def test_execute_click_missing_target_raises(page):
    await page.set_content("<p>x</p>")
    with pytest.raises(ActionExecutionError):
        await execute(page, Action(type="click", target="#missing"))
