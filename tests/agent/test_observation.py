from agentqa.agent.observation import MAX_OBSERVATION_BYTES, observe


async def test_observe_captures_elements_and_metadata(page):
    await page.set_content("<button id='b'>Nhấn</button><a href='/x'>Link</a><p>nội dung</p>")
    snapshot = await observe(page)
    assert "button#b" in snapshot.text
    assert "Link" in snapshot.text
    assert snapshot.element_count == 2
    assert snapshot.mode == "a11y"
    assert snapshot.truncated is False


async def test_observe_truncates_large_pages(page):
    await page.set_content(f"<p>{'x' * 20000}</p><input id='name'>")
    snapshot = await observe(page)
    assert snapshot.truncated is True
    assert snapshot.size_bytes == MAX_OBSERVATION_BYTES
    assert len(snapshot.text.encode("utf-8")) <= MAX_OBSERVATION_BYTES
    assert snapshot.element_count == 1
