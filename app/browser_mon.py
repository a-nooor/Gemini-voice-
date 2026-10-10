import re
from datetime import datetime
from urllib.parse import urlparse

import httpx

from app.config import DATA_DIR, config
from app.status import hub


def playwright_installed() -> bool:
    try:
        import playwright  # noqa: F401

        return True
    except ImportError:
        return False


def _validate(url: str) -> str:
    parsed = urlparse(url.strip())
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("Only http and https URLs are allowed.")
    return parsed.geturl()


def _title(html: str) -> str:
    match = re.search(r"<title[^>]*>(.*?)</title>", html, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return ""
    return re.sub(r"\s+", " ", match.group(1)).strip()[:200]


def _excerpt(html: str) -> str:
    text = re.sub(r"(?is)<script.*?>.*?</script>", " ", html)
    text = re.sub(r"(?is)<style.*?>.*?</style>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()[:1500]


async def fetch_http(url: str) -> dict:
    target = _validate(url)
    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        response = await client.get(target, headers={"User-Agent": "local-agent"})
    html = response.text[:60000]
    return {
        "url": str(response.url),
        "status": response.status_code,
        "ok": response.status_code < 400,
        "title": _title(html),
        "excerpt": _excerpt(html),
        "via": "http",
    }


async def browse(url: str) -> dict:
    target = _validate(url)
    hub.set_state("browsing", target)
    hub.note(f"Browse {target}")
    if playwright_installed():
        try:
            return await _browse_playwright(target)
        except Exception as exc:
            hub.note(f"Browser fallback after: {exc}", "error")
    result = await fetch_http(target)
    return result


async def _browse_playwright(url: str) -> dict:
    from playwright.async_api import async_playwright

    shots = DATA_DIR / "shots"
    shots.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    shot = shots / f"{stamp}.png"
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        response = await page.goto(url, wait_until="domcontentloaded", timeout=20000)
        title = await page.title()
        text = await page.inner_text("body")
        await page.screenshot(path=str(shot), full_page=False)
        status = response.status if response else 0
        final_url = page.url
        await browser.close()
    return {
        "url": final_url,
        "status": status,
        "ok": status < 400,
        "title": title[:200],
        "excerpt": re.sub(r"\s+", " ", text).strip()[:1500],
        "screenshot": str(shot),
        "via": "browser",
    }


async def refresh_monitors() -> list[dict]:
    rows = []
    for item in config().get("monitors", []):
        name = item.get("name") or item.get("url")
        url = item.get("url", "")
        try:
            fetched = await fetch_http(url)
            rows.append({"name": name, "url": url, **fetched})
        except Exception as exc:
            rows.append({"name": name, "url": url, "ok": False, "status": 0, "title": "", "excerpt": str(exc), "via": "http"})
    hub.set_monitors(rows)
    return rows
