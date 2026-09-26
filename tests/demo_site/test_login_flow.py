async def test_login_rejects_wrong_credentials(page, demo_server):
    await page.goto(f"{demo_server}/login.html")
    await page.fill("#username", "sai")
    await page.fill("#password", "sai")
    await page.click("#login-btn")
    assert await page.inner_text("#login-error") == "Sai tên đăng nhập hoặc mật khẩu"
    assert page.url.endswith("/login.html")


async def test_login_accepts_demo_credentials(page, demo_server):
    await page.goto(f"{demo_server}/login.html")
    await page.fill("#username", "demo")
    await page.fill("#password", "demo")
    await page.click("#login-btn")
    await page.wait_for_url("**/index.html")
    assert page.url.endswith("/index.html")
