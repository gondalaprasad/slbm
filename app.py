"""
SLB Tracking Mechanism - Flask Backend

API endpoints for serving SLB data to the frontend.
Designed for easy migration to Supabase later.
"""

from flask import Flask, jsonify, request, render_template
from flask_cors import CORS
import pandas as pd
from pathlib import Path
from datetime import datetime
import json
import os
import asyncio
import random
import subprocess
import sys

app = Flask(__name__)
CORS(app)

# Configuration
DATA_FOLDER = Path(r"D:\Codes\SLBM\Data")
FILTER_CONFIG_FILE = Path(r"D:\Codes\SLBM\Data\filter_config.json")

# Cache for data (refreshes on request)
_data_cache = {"data": None, "timestamp": None, "latest_file_time": None}


def load_filter_config():
    """Load filter configuration from file."""
    try:
        if FILTER_CONFIG_FILE.exists():
            with open(FILTER_CONFIG_FILE, 'r') as f:
                import json
                return json.load(f)
        # Default config
        return {
            'symbol': None,
            'series': None,
            'refreshMode': 'interval',
            'refreshInterval': 30,
            'showBid': True,
            'showAsk': True,
            'showDataTable': True,
            'showSeriesA': False,
            'showSeriesB': True
        }
    except Exception as e:
        print(f"Error loading filter config: {e}")
        return {}


def save_filter_config(config):
    """Save filter configuration to file."""
    try:
        with open(FILTER_CONFIG_FILE, 'w') as f:
            import json
            json.dump(config, f, indent=2)
        return True
    except Exception as e:
        print(f"Error saving filter config: {e}")
        return False


def load_all_slb_data():
    """Load all SLB data from Excel files in hierarchical folder structure."""
    all_data = []
    base_path = DATA_FOLDER

    if not base_path.exists():
        return []

    # Walk through Year/Month/Day folders
    for year_folder in base_path.iterdir():
        if not year_folder.is_dir() or not year_folder.name.isdigit():
            continue

        for month_folder in year_folder.iterdir():
            if not month_folder.is_dir() or not month_folder.name.isdigit():
                continue

            for day_folder in month_folder.iterdir():
                if not day_folder.is_dir() or not day_folder.name.isdigit():
                    continue

                # Read all Excel files in this day folder
                for excel_file in day_folder.glob("slb_data_*.xlsx"):
                    try:
                        # Prefer filtered_data, fallback to all_data
                        df = pd.read_excel(excel_file, sheet_name=['filtered_data', 'all_data'])
                        sheet_data = df['filtered_data'] if 'filtered_data' in df else df['all_data']

                        # Add timestamp from file
                        time_str = excel_file.stem.replace("slb_data_", "")
                        try:
                            timestamp = datetime.strptime(
                                f"{year_folder.name}-{month_folder.name}-{day_folder.name} {time_str}",
                                "%Y-%m-%d %H%M%S"
                            )
                        except:
                            timestamp = None

                        sheet_data['Timestamp'] = timestamp
                        sheet_data['DataFile'] = str(excel_file)
                        all_data.append(sheet_data)

                    except Exception as e:
                        continue

    if not all_data:
        return []

    combined_df = pd.concat(all_data, ignore_index=True)
    return combined_df


def get_latest_file_time():
    """Get the latest file modification time from data folder."""
    latest_time = None
    base_path = DATA_FOLDER

    if not base_path.exists():
        return None

    # Walk through Year/Month/Day folders
    for year_folder in base_path.iterdir():
        if not year_folder.is_dir() or not year_folder.name.isdigit():
            continue

        for month_folder in year_folder.iterdir():
            if not month_folder.is_dir() or not month_folder.name.isdigit():
                continue

            for day_folder in month_folder.iterdir():
                if not day_folder.is_dir() or not day_folder.name.isdigit():
                    continue

                # Check all Excel files in this day folder
                for excel_file in day_folder.glob("slb_data_*.xlsx"):
                    try:
                        file_mtime = excel_file.stat().st_mtime
                        if latest_time is None or file_mtime > latest_time:
                            latest_time = file_mtime
                    except:
                        continue

    return latest_time


def process_data(df):
    """Process and clean data for frontend."""
    if df.empty:
        return []

    # Convert Timestamp to string for JSON serialization
    df['Timestamp'] = pd.to_datetime(df['Timestamp'])
    df['Timestamp_Str'] = df['Timestamp'].dt.strftime('%Y-%m-%d %H:%M:%S')
    df['Time_Short'] = df['Timestamp'].dt.strftime('%H:%M:%S')

    # Parse Expiry column if exists
    if 'Expiry' in df.columns:
        df['Expiry'] = df['Expiry'].fillna('N/A')
    else:
        df['Expiry'] = 'N/A'

    # Clean numeric columns
    numeric_cols = ['Best Bid Price', 'Best Offer Price', 'LTP', 'Spread', 'Annualised Yield']
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col].replace('-', pd.NA), errors='coerce')

    # Filter out rows with invalid Best Bid Qty ( '-', 0, blank, NaN)
    # First, convert to string and strip whitespace
    df['Best Bid Qty_Str'] = df['Best Bid Qty'].astype(str).str.strip()
    # Keep only rows where Best Bid Qty is not '-', not '0', not 'nan', not empty
    df = df[
        (df['Best Bid Qty_Str'] != '-') &
        (df['Best Bid Qty_Str'] != '0') &
        (df['Best Bid Qty_Str'] != '') &
        (df['Best Bid Qty_Str'] != 'nan') &
        (df['Best Bid Qty_Str'] != 'NaN')
    ].copy()

    # Get unique values - only include symbols/series that have valid data remaining
    unique_symbols = sorted(df['Symbol'].dropna().unique().tolist())
    unique_series = sorted(df['Series'].dropna().unique().tolist())

    # Get latest days to expiry
    if 'Expiry' in df.columns and df['Expiry'].notna().any():
        try:
            # Simple calculation for display
            latest_expiry = df['Expiry'].iloc[0] if len(df) > 0 else 'N/A'
        except:
            latest_expiry = 'N/A'
    else:
        latest_expiry = 'N/A'

    return {
        'symbols': unique_symbols,
        'series': unique_series,
        'latest_expiry': latest_expiry,
        'data': df.to_dict('records')
    }


@app.route('/')
def index():
    """Serve the dashboard page."""
    return render_template('dashboard.html')


@app.route('/api/data')
def get_data():
    """API endpoint to get all SLB data."""
    try:
        df = load_all_slb_data()
        result = process_data(df)
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/filter')
def filter_data():
    """API endpoint to get filtered data."""
    try:
        symbol = request.args.get('symbol')
        series = request.args.get('series')

        df = load_all_slb_data()

        # Apply filters
        if symbol:
            df = df[df['Symbol'] == symbol]
        if series:
            df = df[df['Series'] == series]

        df = df.sort_values('Timestamp')
        result = process_data(df)
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/metadata')
def get_metadata():
    """API endpoint to get metadata (symbols, series, etc.) without full data."""
    try:
        df = load_all_slb_data()
        if df.empty:
            return jsonify({'symbols': [], 'series': [], 'latest_expiry': 'N/A'})

        # Filter out rows with invalid Best Bid Qty (same logic as process_data)
        df['Best Bid Qty_Str'] = df['Best Bid Qty'].astype(str).str.strip()
        df = df[
            (df['Best Bid Qty_Str'] != '-') &
            (df['Best Bid Qty_Str'] != '0') &
            (df['Best Bid Qty_Str'] != '') &
            (df['Best Bid Qty_Str'] != 'nan') &
            (df['Best Bid Qty_Str'] != 'NaN')
        ].copy()

        # Get unique symbols after filtering
        unique_symbols = sorted(df['Symbol'].dropna().unique().tolist())

        # Load config to check which series to show
        config = load_filter_config()
        show_series_a = config.get('showSeriesA', False)
        show_series_b = config.get('showSeriesB', True)

        all_series = []

        # Load Series A options if enabled
        if show_series_a:
            series_a_metadata_file = DATA_FOLDER / 'series_a_metadata.json'
            if series_a_metadata_file.exists():
                try:
                    with open(series_a_metadata_file, 'r') as f:
                        import json
                        series_data = json.load(f)
                        all_series.extend([s['text'] for s in series_data])
                except Exception as e:
                    print(f"Error loading Series A metadata: {e}")

        # Load Series B options if enabled
        if show_series_b:
            series_b_metadata_file = DATA_FOLDER / 'series_b_metadata.json'
            if series_b_metadata_file.exists():
                try:
                    with open(series_b_metadata_file, 'r') as f:
                        import json
                        series_data = json.load(f)
                        all_series.extend([s['text'] for s in series_data])
                except Exception as e:
                    print(f"Error loading Series B metadata: {e}")

        # If no metadata files found, fallback to unique series from data
        if not all_series:
            all_series = sorted(df['Series'].dropna().unique().tolist())
        # Don't sort - keep NSE original order
        # else:
        #     all_series = sorted(all_series)

        # Get latest expiry
        latest_expiry = df['Expiry'].iloc[0] if 'Expiry' in df.columns and len(df) > 0 else 'N/A'

        return jsonify({
            'symbols': unique_symbols,
            'series': all_series,
            'latest_expiry': latest_expiry
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/check-updates')
def check_updates():
    """API endpoint to check if new data files have been added."""
    try:
        current_latest_time = get_latest_file_time()

        # Get cached latest time
        cached_time = _data_cache.get("latest_file_time")

        # Update cache
        _data_cache["latest_file_time"] = current_latest_time

        # Check if new data exists
        has_update = cached_time is not None and current_latest_time is not None and current_latest_time > cached_time

        return jsonify({
            'has_update': has_update,
            'latest_time': current_latest_time,
            'cached_time': cached_time
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/filter-config', methods=['GET', 'POST'])
def filter_config():
    """API endpoint to get or save filter configuration."""
    if request.method == 'GET':
        # Return current filter config
        config = load_filter_config()
        return jsonify(config)

    elif request.method == 'POST':
        # Save filter config
        try:
            config = request.get_json()
            success = save_filter_config(config)
            if success:
                return jsonify({'success': True})
            else:
                return jsonify({'error': 'Failed to save config'}), 500
        except Exception as e:
            return jsonify({'error': str(e)}), 500


@app.route('/api/ltp')
def get_ltp():
    """API endpoint to get LTP from NSE using yfinance."""
    try:
        symbol = request.args.get('symbol')
        if not symbol:
            return jsonify({'ltp': None, 'change': None})

        import yfinance as yf

        # Convert to yfinance format (add .NS for NSE)
        yf_symbol = f"{symbol}.NS"
        ticker = yf.Ticker(yf_symbol)
        info = ticker.info

        ltp = info.get('regularMarketPrice') or info.get('currentPrice')

        # Calculate change % if previous close available
        prev_close = info.get('previousClose')
        change = None
        if ltp and prev_close:
            change = ((ltp - prev_close) / prev_close) * 100

        return jsonify({
            'ltp': ltp,
            'change': change
        })
    except Exception as e:
        print(f"Error fetching LTP: {e}")
        return jsonify({'ltp': None, 'change': None})


@app.route('/api/series-counts')
def series_counts():
    """API endpoint to get current series A and B counts."""
    try:
        series_a_file = DATA_FOLDER / 'series_a_metadata.json'
        series_b_file = DATA_FOLDER / 'series_b_metadata.json'

        series_a_count = 0
        series_b_count = 0

        if series_a_file.exists():
            with open(series_a_file, 'r') as f:
                import json
                series_a_data = json.load(f)
                series_a_count = len(series_a_data) if series_a_data else 0

        if series_b_file.exists():
            with open(series_b_file, 'r') as f:
                import json
                series_b_data = json.load(f)
                series_b_count = len(series_b_data) if series_b_data else 0

        return jsonify({
            'series_a_count': series_a_count,
            'series_b_count': series_b_count
        })
    except Exception as e:
        print(f"Error getting series counts: {e}")
        return jsonify({'series_a_count': 0, 'series_b_count': 0})


@app.route('/api/rankings')
def get_rankings():
    """API endpoint to get top 10 symbols by earning % for a given series."""
    try:
        series = request.args.get('series')
        if not series:
            return jsonify({'rankings': []})

        df = load_all_slb_data()
        if df.empty:
            return jsonify({'rankings': []})

        # Filter out rows with invalid Best Bid Qty (same logic as process_data)
        df['Best Bid Qty_Str'] = df['Best Bid Qty'].astype(str).str.strip()
        df = df[
            (df['Best Bid Qty_Str'] != '-') &
            (df['Best Bid Qty_Str'] != '0') &
            (df['Best Bid Qty_Str'] != '') &
            (df['Best Bid Qty_Str'] != 'nan') &
            (df['Best Bid Qty_Str'] != 'NaN')
        ].copy()

        # Filter by series
        df = df[df['Series'] == series].copy()

        # Get the latest bid price for each symbol
        df = df.sort_values('Timestamp')
        latest_data = df.groupby('Symbol').last().reset_index()

        # Clean bid price column
        latest_data['Best Bid Price'] = pd.to_numeric(
            latest_data['Best Bid Price'].replace('-', pd.NA), errors='coerce'
        )

        # Filter out symbols with no bid price
        latest_data = latest_data[latest_data['Best Bid Price'].notna()]

        # Get LTP for each symbol
        import yfinance as yf

        rankings = []
        for symbol in latest_data['Symbol']:
            try:
                yf_symbol = f"{symbol}.NS"
                ticker = yf.Ticker(yf_symbol)
                info = ticker.info
                ltp = info.get('regularMarketPrice') or info.get('currentPrice')

                if ltp and ltp > 0:
                    bid_price = latest_data[latest_data['Symbol'] == symbol]['Best Bid Price'].values[0]
                    earning_pct = (bid_price / ltp) * 100
                    rankings.append({
                        'symbol': symbol,
                        'earning_pct': round(earning_pct, 2),
                        'bid_price': round(bid_price, 2),
                        'ltp': round(ltp, 2)
                    })
            except Exception as e:
                print(f"Error fetching LTP for {symbol}: {e}")
                continue

        # Sort by earning % descending and get top 10
        rankings = sorted(rankings, key=lambda x: x['earning_pct'], reverse=True)[:10]

        # Add rank
        for i, item in enumerate(rankings, 1):
            item['rank'] = i

        return jsonify({'rankings': rankings})

    except Exception as e:
        print(f"Error getting rankings: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'rankings': []})


@app.route('/api/update-series', methods=['POST'])
def update_series():
    """API endpoint to run the update_series.py script."""
    try:
        script_path = DATA_FOLDER / 'update_series.py'

        if not script_path.exists():
            return jsonify({
                'success': False,
                'error': 'update_series.py not found'
            })

        # Run the script using subprocess
        result = subprocess.run(
            [sys.executable, str(script_path)],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=str(DATA_FOLDER)
        )

        if result.returncode == 0:
            # Script succeeded, reload series counts
            series_a_file = DATA_FOLDER / 'series_a_metadata.json'
            series_b_file = DATA_FOLDER / 'series_b_metadata.json'

            series_a_count = 0
            series_b_count = 0

            if series_a_file.exists():
                with open(series_a_file, 'r') as f:
                    data = json.load(f)
                    series_a_count = len(data) if data else 0

            if series_b_file.exists():
                with open(series_b_file, 'r') as f:
                    data = json.load(f)
                    series_b_count = len(data) if data else 0

            return jsonify({
                'success': True,
                'series_a_count': series_a_count,
                'series_b_count': series_b_count
            })
        else:
            return jsonify({
                'success': False,
                'error': result.stderr or 'Script execution failed'
            })

    except subprocess.TimeoutExpired:
        return jsonify({
            'success': False,
            'error': 'Update timed out (60 seconds)'
        })
    except Exception as e:
        print(f"Error updating series: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        })


@app.route('/config')
def config_page():
    """Serve the config page."""
    return render_template('config.html')


if __name__ == '__main__':
    import os
    import sys
    # Check if running from start.py via environment variable
    from_start_py = os.environ.get('FLASK_FROM_START') == '1'

    print("""
========================================================================

         SLB Tracking Mechanism - Flask Server

   Dashboard: http://localhost:5000
   API:       http://localhost:5000/api/data

========================================================================
    """)

    # When running from start.py, disable debug mode completely to prevent reloader
    app.run(host='0.0.0.0', port=5000, debug=not from_start_py, use_reloader=False)
