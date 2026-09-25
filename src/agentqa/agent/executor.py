from playwright.async_api import Page

from agentqa.contracts import Action

ACTION_TIMEOUT_MS = 5000


class ActionExecutionError(RuntimeError):
    pass


async def execute(page: Page, action: Action) -> None:
    try:
        if action.type == "navigate":
            await page.goto(action.target or "")
        elif action.type == "click":
            await page.click(action.target or "", timeout=ACTION_TIMEOUT_MS)
        elif action.type == "fill":
            await page.fill(action.target or "", action.value or "", timeout=ACTION_TIMEOUT_MS)
        elif action.type == "finish":
            return
    except Exception as exc:
        raise ActionExecutionError(str(exc)) from exc
