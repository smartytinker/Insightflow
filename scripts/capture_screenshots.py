"""Capture documentation screenshots from a running InsightFlow app.

Usage:
    # backend on :8010, frontend on :8501 with API_BASE_URL pointing to it
    python scripts/capture_screenshots.py

Requires the optional ``playwright`` package and Chromium:
    pip install playwright && playwright install chromium
"""

from __future__ import annotations

from pathlib import Path

from playwright.sync_api import Page, sync_playwright

BASE_URL = "http://127.0.0.1:8501"
OUTPUT = Path(__file__).resolve().parents[1] / "docs" / "screenshots"


def _settle(page: Page, text: str, timeout: int = 30_000) -> None:
    page.get_by_text(text, exact=False).first.wait_for(timeout=timeout)
    page.wait_for_timeout(1200)
    page.evaluate("document.fonts.ready")


def _goto(page: Page, path: str, text: str) -> None:
    page.locator(f'a[href$="{path}"]').first.click()
    _settle(page, text)


def capture() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(
            viewport={"width": 1440, "height": 1200},
            device_scale_factor=1,
            color_scheme="light",
        )
        page = context.new_page()
        page.goto(BASE_URL, wait_until="domcontentloaded")
        _settle(page, "Overview")
        page.add_style_tag(
            content=(
                '[data-testid="stToolbar"] { display: none !important; } '
                '[data-testid="stDecoration"] { display: none !important; } '
                '[data-testid="stStatusWidget"] { display: none !important; }'
            )
        )
        page.screenshot(path=OUTPUT / "overview.png", full_page=True)

        _goto(page, "/datasets", "Dataset library")
        page.screenshot(path=OUTPUT / "datasets.png", full_page=True)

        _goto(page, "/analytics", "Automated dataset summary")
        page.get_by_role("tab", name="Numeric").click()
        _settle(page, "Distribution")
        page.screenshot(path=OUTPUT / "analytics.png", full_page=True)

        _goto(page, "/anomalies", "Anomaly Detection")
        _settle(page, "Detection summary")
        page.screenshot(path=OUTPUT / "anomalies.png", full_page=True)

        _goto(page, "/assistant", "AI Assistant")
        _settle(page, "Calculated")
        page.screenshot(path=OUTPUT / "assistant.png", full_page=True)

        _goto(page, "/cleaning", "Cleaning recipe")
        run_button = page.get_by_role("button", name="Run cleaning")
        if run_button.count():
            run_button.click()
            _settle(page, "Before and after")
        page.screenshot(path=OUTPUT / "cleaning.png", full_page=True)

        _goto(page, "/reports", "Dataset summary")
        page.screenshot(path=OUTPUT / "reports.png", full_page=True)

        context.close()
        browser.close()


if __name__ == "__main__":
    capture()
