"""
Update Series Metadata from NSE

This script fetches the latest Series A and Series B options from NSE
and saves them to metadata files for the dashboard to use.
"""

import asyncio
import random
from pathlib import Path
import json

# Import Playwright
from playwright.async_api import async_playwright

# Configuration
DATA_FOLDER = Path(r"D:\Codes\SLBM\Data")


async def fetch_series_from_nse():
    """Fetch Series A and B options from NSE using Playwright."""
    series_a_options = []
    series_b_options = []

    async with async_playwright() as p:
        print("Launching Chrome browser...")
        browser = await p.chromium.launch(
            headless=True,
            channel="chrome",
            args=['--disable-blink-features=AutomationControlled']
        )

        context = await browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        )

        page = await context.new_page()
        print("Navigating to NSE SLB page...")
        await page.goto("https://www.nseindia.com/market-data/securities-lending-and-borrowing",
                        wait_until="domcontentloaded")

        # Wait for page to load
        await asyncio.sleep(random.uniform(2, 3))

        # Wait for dropdown
        try:
            await page.wait_for_selector("#slbSeriesOpt", state="visible", timeout=15000)

            # Click on dropdown to expand it
            await page.click("#slbSeriesOpt")
            await asyncio.sleep(0.5)

            # Get all optgroups
            optgroups = await page.query_selector_all("#slbSeriesOpt optgroup")

            print(f"Found {len(optgroups)} optgroups in dropdown")

            # First optgroup = Series A
            if len(optgroups) >= 1:
                series_a_optgroup = optgroups[0]
                options_a = await series_a_optgroup.query_selector_all("option")
                for option in options_a:
                    value = await option.get_attribute("value")
                    text = await option.inner_text()
                    if value and text.strip():
                        series_a_options.append({"value": value, "text": text.strip()})
                print(f"Series A: {len(series_a_options)} options")

            # Second optgroup = Series B
            if len(optgroups) >= 2:
                series_b_optgroup = optgroups[1]
                options_b = await series_b_optgroup.query_selector_all("option")
                for option in options_b:
                    value = await option.get_attribute("value")
                    text = await option.inner_text()
                    if value and text.strip():
                        series_b_options.append({"value": value, "text": text.strip()})
                print(f"Series B: {len(series_b_options)} options")

        except Exception as e:
            print(f"Error fetching series options: {e}")
            import traceback
            traceback.print_exc()

        await browser.close()

    # Save to metadata files
    print("\nSaving metadata files...")

    if series_a_options:
        with open(DATA_FOLDER / 'series_a_metadata.json', 'w') as f:
            json.dump([{'value': opt['value'], 'text': opt['text']} for opt in series_a_options], f, indent=2)
        print(f"[OK] Saved {len(series_a_options)} Series A options to series_a_metadata.json")
    else:
        print("[X] No Series A options found")

    if series_b_options:
        with open(DATA_FOLDER / 'series_b_metadata.json', 'w') as f:
            json.dump([{'value': opt['value'], 'text': opt['text']} for opt in series_b_options], f, indent=2)
        print(f"[OK] Saved {len(series_b_options)} Series B options to series_b_metadata.json")
    else:
        print("[X] No Series B options found")

    return {
        'series_a_count': len(series_a_options),
        'series_b_count': len(series_b_options)
    }


async def main():
    print("="*60)
    print("  NSE SLB Series Metadata Updater")
    print("="*60)
    print()

    result = await fetch_series_from_nse()

    print()
    print("="*60)
    print(f"  Complete! Series A: {result['series_a_count']} | Series B: {result['series_b_count']}")
    print("="*60)


if __name__ == "__main__":
    asyncio.run(main())
