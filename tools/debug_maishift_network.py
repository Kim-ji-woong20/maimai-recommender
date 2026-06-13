from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from playwright.sync_api import sync_playwright


PROFILE_URL = "https://maimai.shiftpsh.com/profile/hapum/records"
OUT_DIR = Path("back/data/debug_maishift")
OUT_DIR.mkdir(parents=True, exist_ok=True)


def main() -> None:
    network_logs: list[dict[str, Any]] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--disable-dev-shm-usage",
                "--no-sandbox",
            ],
        )

        page = browser.new_page(
            viewport={
                "width": 1400,
                "height": 1800,
            },
            locale="ko-KR",
        )

        def handle_response(response):
            try:
                request = response.request
                resource_type = request.resource_type
                url = response.url

                if resource_type in {"xhr", "fetch"} or "api" in url.lower() or "profile" in url.lower():
                    item = {
                        "url": url,
                        "status": response.status,
                        "resource_type": resource_type,
                        "method": request.method,
                    }

                    content_type = response.headers.get("content-type", "")

                    if "json" in content_type:
                        try:
                            body = response.text()
                            item["body_preview"] = body[:1000]
                        except Exception as exc:
                            item["body_error"] = str(exc)

                    network_logs.append(item)

            except Exception as exc:
                network_logs.append({
                    "error": str(exc),
                })

        page.on("response", handle_response)

        page.goto(
            PROFILE_URL,
            wait_until="domcontentloaded",
            timeout=60000,
        )

        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass

        page.wait_for_timeout(2000)

        for i in range(8):
            page.mouse.wheel(0, 2400)
            page.wait_for_timeout(800)

            page.evaluate(
                """
                () => {
                    window.scrollBy(0, 2400);

                    const candidates = [
                        document.scrollingElement,
                        document.documentElement,
                        document.body,
                        ...Array.from(document.querySelectorAll("main, section, div"))
                    ].filter(Boolean);

                    for (const el of candidates) {
                        try {
                            if (el.scrollHeight > el.clientHeight + 50) {
                                el.scrollTop = Math.min(
                                    el.scrollTop + 2400,
                                    el.scrollHeight
                                );
                            }
                        } catch (e) {}
                    }
                }
                """
            )

            page.wait_for_timeout(800)

        html = page.content()
        screenshot_path = OUT_DIR / "records_debug.png"
        html_path = OUT_DIR / "records_debug.html"
        json_path = OUT_DIR / "network_logs.json"

        page.screenshot(path=str(screenshot_path), full_page=True)
        html_path.write_text(html, encoding="utf-8")
        json_path.write_text(
            json.dumps(network_logs, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        browser.close()

    print(f"saved screenshot: {screenshot_path}")
    print(f"saved html: {html_path}")
    print(f"saved network logs: {json_path}")
    print(f"network log count: {len(network_logs)}")

    for item in network_logs[:30]:
        print("-" * 80)
        print(item.get("status"), item.get("resource_type"), item.get("method"))
        print(item.get("url"))
        preview = item.get("body_preview")
        if preview:
            print(preview[:500])


if __name__ == "__main__":
    main()