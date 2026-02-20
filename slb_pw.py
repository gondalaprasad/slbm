import asyncio
import random
import pandas as pd
from playwright.async_api import async_playwright
from datetime import datetime, timedelta
import aiohttp


slb_webhook = 'https://chat.googleapis.com/v1/spaces/AAQAkiGnWA0/messages?key=AIzaSyDdI0hCZtE6vySjMm-WEfRq3CPzqKqqsHI&token=o2QDBFdBXA7N0px0zxsP3llEzgufYV50J1kfuL_HLF0'
#config_folder = 'nse_slb_data'

async def human_delay(min_ms=100, max_ms=300):
    """Add random delay to mimic human behavior"""
    await asyncio.sleep(random.uniform(min_ms/1000, max_ms/1000))

# Cache for holiday calendar (refreshes daily)
_holiday_cache = {"dates": None, "date_fetched": None}

async def fetch_holiday_calendar():
    """Fetch NSE trading holidays from Zerodha RSS feed"""
    global _holiday_cache

    today = datetime.now().date()
    # Refresh cache if it's from a different day or empty
    if _holiday_cache["dates"] is not None and _holiday_cache["date_fetched"] == today:
        return _holiday_cache["dates"]

    holidays = set()
    try:
        print("Fetching holiday calendar from Zerodha...")
        async with aiohttp.ClientSession() as session:
            async with session.get("https://zerodha.com/marketintel/holiday-calendar/?format=xml", timeout=10) as response:
                if response.status == 200:
                    xml_content = await response.text()
                    # Parse XML to extract holiday dates
                    root = ET.fromstring(xml_content)

                    # RSS items are in <channel><item> tags
                    for item in root.findall(".//item"):
                        title_elem = item.find("title")
                        if title_elem is not None:
                            title = title_elem.text
                            # Look for NSE holidays in the title
                            if title and "NSE" in title.upper():
                                # Extract date from description or pubDate
                                pub_date = item.find("pubDate")
                                if pub_date is not None:
                                    try:
                                        # Parse RFC 2822 date format
                                        date_str = pub_date.text
                                        # Parse and extract date part
                                        parsed_date = datetime.strptime(date_str.split(" +")[0], "%a, %d %b %Y %H:%M:%S")
                                        holidays.add(parsed_date.date())
                                    except:
                                        pass

                    print(f"Found {len(holidays)} NSE trading holidays")
                    _holiday_cache["dates"] = holidays
                    _holiday_cache["date_fetched"] = today
                else:
                    print(f"Failed to fetch holidays, status: {response.status}")
    except Exception as e:
        print(f"Error fetching holiday calendar: {e}")
        # Return empty set on error
        return set()

    return holidays

def get_first_tuesday_of_month(year: int, month: int) -> datetime:
    """Calculate the first Tuesday of a given month"""
    # First day of the month
    first_day = datetime(year, month, 1)

    # Tuesday is weekday 1 (Monday=0, Tuesday=1, ..., Sunday=6)
    # Find the first Tuesday
    days_until_tuesday = (1 - first_day.weekday()) % 7
    if days_until_tuesday < 0:
        days_until_tuesday += 7

    first_tuesday = first_day + timedelta(days=days_until_tuesday)
    return first_tuesday

async def calculate_expiry_date(series_text: str, holidays: set) -> str:
    """
    Calculate expiry date for a given series text.
    Series format examples: "Mar-2026(M1)**", "Apr-2026", "Feb-2027"

    Returns: Expiry date as DD-MM-YYYY string
    """
    import re

    # Extract month name and year from series text
    # Match patterns like "Mar-2026", "Apr-2026", "Feb-2027"
    match = re.search(r'([A-Za-z]+)-(\d{4})', series_text)
    if not match:
        return "N/A"

    month_name = match.group(1)
    year = int(match.group(2))

    # Convert month name to number
    month_map = {
        'Jan': 1, 'Feb': 2, 'Mar': 3, 'Apr': 4, 'May': 5, 'Jun': 6,
        'Jul': 7, 'Aug': 8, 'Sep': 9, 'Oct': 10, 'Nov': 11, 'Dec': 12
    }

    month = month_map.get(month_name[:3])
    if not month:
        return "N/A"

    # Get first Tuesday of the month
    expiry_date = get_first_tuesday_of_month(year, month)

    # Adjust if it's a holiday (move to next trading day)
    max_days_to_check = 7  # Don't search more than a week
    days_checked = 0
    while expiry_date.date() in holidays and days_checked < max_days_to_check:
        expiry_date += timedelta(days=1)
        days_checked += 1

    # Skip weekends (Saturday, Sunday)
    while expiry_date.weekday() >= 5 and days_checked < max_days_to_check:
        expiry_date += timedelta(days=1)
        days_checked += 1

    return expiry_date.strftime("%d-%m-%Y")

async def open_nse_website():
    """
    Open NSE India website using Playwright with human-like behavior,
    select first 4 Series B options, capture table data, and export to CSV.
    """
    async with async_playwright() as p:
        # Launch Chrome browser with realistic settings
        print("Launching Chrome browser...")
        browser = await p.chromium.launch(
            headless=True,
            channel="chrome",
            args=[
                '--disable-blink-features=AutomationControlled',
                '--disable-dev-shm-usage'
            ]
        )
        
        # Create context with realistic viewport and user agent
        context = await browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        )
        
        # Create a new page
        page = await context.new_page()
        
        # Navigate to the NSE India website
        url = "https://www.nseindia.com/market-data/securities-lending-and-borrowing"
        print(f"Navigating to: {url}")
        
        await page.goto(url, wait_until="domcontentloaded")
        
        # Wait for initial page load with human-like delay
        print("Waiting for page to fully load...")
        await asyncio.sleep(random.uniform(3, 5))
        
        # Wait for the dropdown to be visible
        await page.wait_for_selector("#slbSeriesOpt", state="visible")
        
        print("Page loaded successfully!")
        await human_delay(500, 1000)

        # Dynamically fetch Series A and Series B options from the dropdown
        print("Fetching series options from dropdown...")
        series_a_options = []
        series_b_options = []

        try:
            # Get all optgroups from the dropdown
            optgroups = await page.query_selector_all("#slbSeriesOpt optgroup")

            # First optgroup is Series A, second is Series B
            if len(optgroups) >= 1:
                # Fetch Series A options
                series_a_optgroup = optgroups[0]
                options_a = await series_a_optgroup.query_selector_all("option")
                for option in options_a:
                    value = await option.get_attribute("value")
                    text = await option.inner_text()
                    if value and text.strip():
                        series_a_options.append({"value": value, "text": text.strip()})

                if series_a_options:
                    print(f"Found {len(series_a_options)} Series A options")
                    # Save Series A options to metadata file
                    metadata_file_a = Path(config_folder) / 'series_a_metadata.json'
                    with open(metadata_file_a, 'w') as f:
                        import json
                        json.dump([{'value': opt['value'], 'text': opt['text']} for opt in series_a_options], f, indent=2)
                    print(f"Saved {len(series_a_options)} Series A options to {metadata_file_a}")

            if len(optgroups) >= 2:
                # Fetch Series B options
                series_b_optgroup = optgroups[1]
                options_b = await series_b_optgroup.query_selector_all("option")
                for option in options_b:
                    value = await option.get_attribute("value")
                    text = await option.inner_text()
                    if value and text.strip():
                        series_b_options.append({"value": value, "text": text.strip()})

                if series_b_options:
                    print(f"Found {len(series_b_options)} Series B options")
                    # Save Series B options to metadata file
                    metadata_file_b = Path(config_folder) / 'series_b_metadata.json'
                    with open(metadata_file_b, 'w') as f:
                        import json
                        json.dump([{'value': opt['value'], 'text': opt['text']} for opt in series_b_options], f, indent=2)
                    print(f"Saved {len(series_b_options)} Series B options to {metadata_file_b}")

                    # Take first 4 options (or fewer if less available)
                    series_to_scrape = series_b_options[:4]
                    print(f"Using first {len(series_to_scrape)} Series B options for scraping")
                else:
                    print("No Series B expiries found in dropdown!")

            else:
                print(f"No expiries found - Expected at least 2 optgroups, found {len(optgroups)}")

        except Exception as e:
            print(f"Error fetching series options: {e}")
            import traceback
            traceback.print_exc()

        # If no options found, close browser and return without exporting
        if not series_b_options:
            print("=" * 80)
            print("NO EXPIRIES FOUND - Skipping data export")
            print("=" * 80)
            await browser.close()
            return

        # Master DataFrame to store all data
        all_data = []

        # Fetch holiday calendar for expiry calculation
        holidays = await fetch_holiday_calendar()

        # Define column names (Expiry added as column R)
        columns = [
            'Series', 'Symbol', 'Best Bid Qty', 'Best Bid Price', 'Best Offer Price',
            'Best Offer Qty', 'LTP', 'Underlying LTP', 'Futures LTP',
            'Spread', 'Spread (%)', 'Open Positions', 'Annualised Yield',
            'Volume', 'Turnover', 'Transaction Value', 'CA', 'Expiry'
        ]
        
        # Loop through first 4 Series B options
        for idx, option in enumerate(series_to_scrape, 1):
            print(f"\n{'='*80}")
            print(f"Processing option {idx}/{len(series_b_options)}: {option['text']}")
            print(f"{'='*80}")
            
            # Move mouse to dropdown area naturally
            print("Moving to dropdown...")
            dropdown = await page.query_selector("#slbSeriesOpt")
            box = await dropdown.bounding_box()
            
            if box:
                await page.mouse.move(
                    box['x'] + box['width'] / 2 + random.uniform(-10, 10),
                    box['y'] + box['height'] / 2 + random.uniform(-5, 5),
                    steps=random.randint(10, 20)
                )
                await human_delay(200, 400)
            
            # Click on the dropdown
            print("Clicking on the dropdown...")
            await page.click("#slbSeriesOpt")
            await human_delay(300, 600)
            
            # Select the option
            print(f"Selecting: {option['text']}")
            await page.select_option("#slbSeriesOpt", value=option['value'])
            
            print("Option selected! Waiting for table to update...")
            
            # Wait for table to reload
            await human_delay(2000, 3000)
            
            try:
                # Wait for table body to be present
                await page.wait_for_selector("#table-slb tbody tr", state="visible", timeout=15000)
                print("Table data loaded successfully!")

                # Additional wait to ensure all data is loaded
                await human_delay(1000, 2000)

                # Calculate expiry date for this series
                expiry_date = await calculate_expiry_date(option['text'], holidays)
                print(f"Expiry date for {option['text']}: {expiry_date}")

                # Extract table data
                print("Extracting table data...")

                # Get all table rows
                rows = await page.query_selector_all("#table-slb tbody tr")

                for row in rows:
                    cells = await row.query_selector_all("td")
                    row_data = [option['text']]  # First column is the Series dropdown value

                    for cell in cells:
                        text = await cell.inner_text()
                        row_data.append(text.strip())

                    # Add expiry date as the last column
                    row_data.append(expiry_date)

                    if len(row_data) > 1:  # Only add if we have data beyond the series name
                        all_data.append(row_data)

                print(f"Captured {len(rows)} rows for {option['text']}")
                
            except Exception as e:
                print(f"Table loading or extraction error for {option['text']}: {e}")
                import traceback
                traceback.print_exc()
            
            # Wait before next iteration
            await human_delay(1000, 2000)
            # Wait before next iteration
            await human_delay(1000, 2000)
        
        # Create final DataFrame with all collected data
        print(f"\n{'='*80}")
        print("Creating final DataFrame...")
        print(f"{'='*80}")
        
        df = pd.DataFrame(all_data, columns=columns)
        
        # print(f"\nTotal rows collected: {len(df)}")
        # print("\nDataFrame Head:")
        # print("=" * 180)
        # print(df.head(10).to_string(index=False))
        # print("=" * 180)
        
        
        
        # Generate timestamp
        now = datetime.now()
        readable_time = now.strftime("%Y-%m-%d %H:%M:%S")
        
        # Push to Supabase
        await push_to_supabase(df, now)
        
        # Send success message to Google Chat
        try:
           await send_slb_webhook_message(f"✅ SLB data scraped and pushed to Supabase successfully at {readable_time}")
        except Exception as e:
            print(f"Failed to send webhook message: {e}")
        
        # Wait for 5 seconds to observe
        print("\nWaiting for 5 seconds before closing...")
        await asyncio.sleep(5)
        
        print("Closing browser...")
        
        # Close the browser
        await browser.close()
        
        print("Browser closed successfully!")


# Supabase Configuration
from supabase import create_client, Client
SUPABASE_URL = "https://qhvyndpxndcsdqpzacdd.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InFodnluZHB4bmRjc2RxcHphY2RkIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzE1NjIzODYsImV4cCI6MjA4NzEzODM4Nn0.KyNHLcQzFalfzY_z4N37dmw8qspN1MWbGRB3xIylGgM"
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

async def push_to_supabase(df, timestamp):
    """Push dataframe processing to Supabase"""
    print("Pushing data to Supabase...")
    try:
        # Filter Logic: Exclude rows where 'Best Bid Price' is Blank, '-', '0'
        # 'Best Bid Price' column index or name
        if 'Best Bid Price' not in df.columns:
            print("Skipping Supabase push: 'Best Bid Price' column missing")
            return

        # Helper functions
        def safe_float(val):
            try:
                # Remove commas if present
                if isinstance(val, str):
                    val = val.replace(',', '')
                num = pd.to_numeric(val, errors='coerce')
                return None if pd.isna(num) else float(num)
            except:
                return None

        def safe_int(val):
            try:
                # Remove commas if present
                if isinstance(val, str):
                    val = val.replace(',', '')
                num = pd.to_numeric(val, errors='coerce')
                return None if pd.isna(num) else int(num)
            except:
                return None

        # Clean and Filter
        # 1. Convert numeric columns to ensure correct filtering
        df['Best Bid Price_Clean'] = df['Best Bid Price'].apply(safe_float)
        df['Best Bid Qty_Clean'] = df['Best Bid Qty'].apply(safe_int)

        # 2. Filter: 
        # - Best Bid Price must be valid and > 0
        # - Best Bid Qty must be valid (not '-') and > 0
        valid_rows = df[
            (df['Best Bid Price_Clean'].notnull()) & 
            (df['Best Bid Price_Clean'] > 0) &
            (df['Best Bid Qty_Clean'].notnull()) &
            (df['Best Bid Qty_Clean'] > 0)
        ].copy()

        if valid_rows.empty:
            print("No valid rows to push to Supabase (after filtering 0 prices/qtys)")
            return

        print(f"Pushing {len(valid_rows)} valid rows to Supabase...")

        records = []
        for _, row in valid_rows.iterrows():
            record = {
                "symbol": str(row.get('Symbol', '')),
                "series": str(row.get('Series', '')),
                # "expiry_date": row.get('Expiry') if pd.notnull(row.get('Expiry')) else None, # Needs date format
                "best_bid_price": safe_float(row.get('Best Bid Price')),
                "best_offer_price": safe_float(row.get('Best Offer Price')),
                "best_bid_qty": safe_int(row.get('Best Bid Qty')), # Qty as int?
                "best_offer_qty": safe_int(row.get('Best Offer Qty')),
                "ltp": safe_float(row.get('LTP')),
                "spread": safe_float(row.get('Spread')),
                "annualised_yield": safe_float(row.get('Annualised Yield')),
                "timestamp": timestamp.isoformat(),
            }

            # Date formatting for expiry
            expiry_val = row.get('Expiry')
            if pd.notnull(expiry_val):
                 try:
                    # Input format usually DD-MM-YYYY from slb_pw.py
                    d = datetime.strptime(str(expiry_val).strip(), "%d-%m-%Y")
                    record['expiry_date'] = d.strftime("%Y-%m-%d")
                 except:
                    record['expiry_date'] = None
            else:
                record['expiry_date'] = None
            
            records.append(record)

        # Batch Insert
        if records:
            # Chunk the inserts to avoid payload too large errors
            chunk_size = 100
            for i in range(0, len(records), chunk_size):
                chunk = records[i:i + chunk_size]
                try:
                    data, count = supabase.table('slb_data').insert(chunk).execute()
                    print(f"Pushed {len(chunk)} rows (chunk {i//chunk_size + 1}) to Supabase")
                except Exception as e:
                    print(f"Error pushing chunk {i//chunk_size + 1} to Supabase: {e}")
        
        print("Supabase push complete.")

    except Exception as e:
        print(f"Error pushing to Supabase: {e}")
        import traceback
        traceback.print_exc()

async def send_slb_webhook_message(message):
    """Send message to Google Chat via webhook"""
    async with aiohttp.ClientSession() as session:
        payload = {
            "text": message
        }
        async with session.post(slb_webhook, json=payload) as response:
            if response.status == 200:
                print("Webhook message sent successfully")
            else:
                print(f"Failed to send webhook message. Status: {response.status}")


async def main():
    # Configurable start and end times (in 24-hour format)
    start_hour = 9  # 9 AM
    start_minute = 15  # 15 minutes
    end_hour = 17  # 5 PM
    end_minute = 0  # 0 minutes
    interval_minutes = 1  # Run every 5 minutes (configurable)
    
    while True:
        now = datetime.now()
        current_time = now.time()
        start_time = datetime.combine(now.date(), datetime.min.time()).replace(hour=start_hour, minute=start_minute).time()
        end_time = datetime.combine(now.date(), datetime.min.time()).replace(hour=end_hour, minute=end_minute).time()
        
        # Check if current time is within the allowed range
        if start_time <= current_time <= end_time:
            try:
                await open_nse_website()
            except Exception as e:
                print(f"Error occurred: {e}")
                import traceback
                traceback.print_exc()
                # Send failure message to Google Chat
                try:
                    readable_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    await send_slb_webhook_message(f"❌ SLB data export failed with timestamp of {readable_time}")
                except Exception as webhook_error:
                    print(f"Failed to send webhook failure message: {webhook_error}")
                    
            print(f"Waiting {interval_minutes} minutes before next execution...")
            await asyncio.sleep(interval_minutes * 60)  # Convert minutes to seconds
        else:
            print(f"Current time is outside the allowed range ({start_hour}:{start_minute:02d} to {end_hour}:{end_minute:02d}). Exiting...")
            break  # Exit the loop and end the program


if __name__ == "__main__":
    asyncio.run(main())