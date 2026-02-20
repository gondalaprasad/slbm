import os
import pandas as pd
from supabase import create_client, Client
from pathlib import Path
from datetime import datetime

# Supabase Config
url = "https://qhvyndpxndcsdqpzacdd.supabase.co"
key = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InFodnluZHB4bmRjc2RxcHphY2RkIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzE1NjIzODYsImV4cCI6MjA4NzEzODM4Nn0.KyNHLcQzFalfzY_z4N37dmw8qspN1MWbGRB3xIylGgM"
supabase: Client = create_client(url, key)

DATA_DIR = Path('d:/Codes/SLBM/Data')

def process_excel_file(file_path):
    print(f"Processing {file_path}")
    try:
        # Read Excel - sheet 'all_data' is preferred as per slb_pw.py logic
        df = pd.read_excel(file_path, sheet_name='all_data')
        
        # Determine timestamp from filename or folder structure
        # Filename format: slb_data_HHMMSS.xlsx
        # Parent folder structure: YYYY/MM/DD
        filename = file_path.name
        try:
            time_part = filename.split('_')[2].split('.')[0] # HHMMSS
            date_part = f"{file_path.parent.parent.parent.name}-{file_path.parent.parent.name}-{file_path.parent.name}" # YYYY-MM-DD
            timestamp_str = f"{date_part} {time_part[:2]}:{time_part[2:4]}:{time_part[4:]}"
            timestamp = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")
        except Exception as e:
            print(f"Could not parse timestamp from path, using file modified time: {e}")
            timestamp = datetime.fromtimestamp(os.path.getmtime(file_path))

        # Filter Logic: Exclude rows where 'Best Bid Price' is Blank, '-', '0'
        # 'Best Bid Price' column index or name
        if 'Best Bid Price' not in df.columns:
            print(f"Skipping {file_path}: 'Best Bid Price' column missing")
            return

        # Clean and Filter
        df['Best Bid Price'] = pd.to_numeric(df['Best Bid Price'], errors='coerce')
        valid_rows = df[
            (df['Best Bid Price'].notnull()) & 
            (df['Best Bid Price'] != 0)
        ].copy()

        if valid_rows.empty:
            print(f"No valid rows in {file_path}")
            return

        records = []
        for _, row in valid_rows.iterrows():
            def safe_float(val):
                try:
                    num = pd.to_numeric(val, errors='coerce')
                    return None if pd.isna(num) else float(num)
                except:
                    return None

            def safe_int(val):
                try:
                    num = pd.to_numeric(val, errors='coerce')
                    return None if pd.isna(num) else int(num)
                except:
                    return None

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
                 # "ltp_change": row.get('LTP Change') # Not in standard columns list from slb_pw.py, check if needed
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
                    print(f"Inserted {len(chunk)} rows (chunk {i//chunk_size + 1}) from {file_path}")
                except Exception as e:
                    print(f"Error inserting chunk {i//chunk_size + 1} from {file_path}: {e}")

    except Exception as e:
        print(f"Error processing {file_path}: {e}")

def main():
    # Walk through the data directory
    for root, dirs, files in os.walk(DATA_DIR):
        for file in files:
            if file.startswith("slb_data_") and file.endswith(".xlsx"):
                file_path = Path(root) / file
                process_excel_file(file_path)

if __name__ == "__main__":
    main()
