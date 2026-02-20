"""
SLB Tracking Mechanism - Streamlit Dashboard

Data Structure:
- Excel files in hierarchical folders: Year/Month/Day/slb_data_HHMMSS.xlsx
- Each file has 'all_data' and 'filtered_data' sheets
- Columns: Series, Symbol, Best Bid Qty, Best Bid Price, Best Offer Price, ..., CA, Expiry

Designed for easy migration to Supabase later.
"""

import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta
import plotly.graph_objects as go
from dateutil import parser
import time

# Page configuration
st.set_page_config(
    page_title="SLB Tracking Mechanism",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for better styling
st.markdown("""
<style>
    .main-title {
        text-align: center;
        font-size: 3rem;
        font-weight: bold;
        color: #1f77b4;
        margin-bottom: 1rem;
    }
    .metric-card {
        background-color: #f0f2f6;
        border-radius: 10px;
        padding: 1rem;
        margin: 0.5rem 0;
    }
</style>
""", unsafe_allow_html=True)


# ============================================================================
# DATA LOADING FUNCTIONS (To be replaced with Supabase calls later)
# ============================================================================

@st.cache_data(ttl=30)  # Cache for 30 seconds (matches default refresh interval)
def load_all_slb_data(data_folder: str) -> pd.DataFrame:
    """
    Load all SLB data from Excel files in hierarchical folder structure.

    Folder structure: Year/Month/Day/slb_data_HHMMSS.xlsx
    Sheets: 'all_data' or 'filtered_data'

    TODO: Replace with Supabase query
    """
    all_data = []
    base_path = Path(data_folder)

    if not base_path.exists():
        st.warning(f"Data folder not found: {data_folder}")
        return pd.DataFrame()

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
                        # Skip problematic files
                        continue

    if not all_data:
        return pd.DataFrame()

    combined_df = pd.concat(all_data, ignore_index=True)
    return combined_df


def parse_expiry_date(expiry_str):
    """Parse expiry date string to datetime object"""
    try:
        return datetime.strptime(expiry_str, "%d-%m-%Y")
    except:
        return None


def calculate_days_to_expiry(expiry_str, current_date):
    """Calculate days remaining until expiry"""
    expiry_dt = parse_expiry_date(expiry_str)
    if expiry_dt and current_date:
        return (expiry_dt - current_date).days
    return None


# ============================================================================
# STREAMLIT UI
# ============================================================================

def main():
    # Title
    st.markdown('<h1 class="main-title">📈 SLB Tracking Mechanism</h1>', unsafe_allow_html=True)

    # Configuration
    config_folder = st.sidebar.text_input(
        "Data Folder Path",
        value="D:\\Codes\\SLBM\\Data",
        help="Path to the folder containing Year/Month/Day data structure"
    )

    st.sidebar.markdown("---")

    # Auto-refresh configuration in sidebar
    st.sidebar.header("⚙️ Settings")

    auto_refresh = st.sidebar.toggle("Auto-refresh", value=True)
    refresh_interval = st.sidebar.slider(
        "Refresh interval (seconds)",
        min_value=10,
        max_value=300,
        value=30,
        step=10,
        disabled=not auto_refresh
    )

    # Use Streamlit's built-in autorefresh (non-blocking)
    if auto_refresh:
        st.autorefresh(interval=refresh_interval * 1000, key="data_refresh")
        st.sidebar.caption(f"✓ Auto-refreshing every {refresh_interval}s")

    st.sidebar.markdown("---")

    # Load data (cached, only reloads when cache expires)
    df = load_all_slb_data(config_folder)

    if df.empty:
        st.error("No data found! Please check the data folder path or run the scraper first.")
        st.info("""
        **Expected folder structure:**
        ```
        Data_Folder/
        ├── 2026/
        │   ├── 02/
        │   │   ├── 19/
        │   │   │   ├── slb_data_091500.xlsx
        │   │   │   └── slb_data_092000.xlsx
        ```
        """)
        return

    # Parse Expiry column (if exists - for backwards compatibility)
    if 'Expiry' in df.columns:
        df['Expiry_Date'] = df['Expiry'].apply(parse_expiry_date)
        df['Days_To_Expiry'] = df.apply(
            lambda row: calculate_days_to_expiry(row['Expiry'], row['Timestamp']) if pd.notna(row['Timestamp']) else None,
            axis=1
        )
    else:
        # For old files without Expiry column, create empty columns
        df['Expiry'] = 'N/A'
        df['Expiry_Date'] = None
        df['Days_To_Expiry'] = None

    # Clean numeric columns
    numeric_cols = ['Best Bid Price', 'Best Offer Price', 'LTP', 'Spread', 'Annualised Yield']
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col].replace('-', pd.NA), errors='coerce')

    # Filter out rows with '-' in Best Bid Qty (already done in filtered_data sheet, but double-check)
    df = df[df['Best Bid Qty'] != '-'].copy()

    # Get unique values for filters
    unique_symbols = sorted(df['Symbol'].unique()) if 'Symbol' in df.columns else []
    unique_series = sorted(df['Series'].unique()) if 'Series' in df.columns else []
    unique_expiries = sorted(df['Expiry'].dropna().unique()) if 'Expiry' in df.columns else []

    # Sidebar Filters
    st.sidebar.header("🔍 Filters")

    selected_symbol = st.sidebar.selectbox(
        "Select Symbol",
        options=unique_symbols,
        index=0 if unique_symbols else None
    )

    selected_series = st.sidebar.selectbox(
        "Select Series (Expiry)",
        options=unique_series,
        index=0 if unique_series else None
    )

    # Date range filter
    if 'Timestamp' in df.columns and df['Timestamp'].notna().any():
        min_date = df['Timestamp'].min().date()
        max_date = df['Timestamp'].max().date()

        selected_date_range = st.sidebar.date_input(
            "Date Range",
            value=(min_date, max_date),
            min_value=min_date,
            max_value=max_date
        )

        if len(selected_date_range) == 2:
            start_date, end_date = selected_date_range
            df = df[
                (df['Timestamp'].dt.date >= start_date) &
                (df['Timestamp'].dt.date <= end_date)
            ]
    else:
        start_date = end_date = None

    # Apply filters
    filtered_df = df[
        (df['Symbol'] == selected_symbol) &
        (df['Series'] == selected_series)
    ].copy()

    filtered_df = filtered_df.sort_values('Timestamp')

    # Display filtered data info
    st.sidebar.markdown("---")
    st.sidebar.subheader("📊 Data Info")
    st.sidebar.metric("Total Records", len(filtered_df))

    if 'Timestamp' in filtered_df.columns and filtered_df['Timestamp'].notna().any():
        st.sidebar.metric("Date Range",
                         f"{filtered_df['Timestamp'].min().strftime('%Y-%m-%d')} to "
                         f"{filtered_df['Timestamp'].max().strftime('%Y-%m-%d')}")

    if 'Days_To_Expiry' in filtered_df.columns:
        latest_days = filtered_df['Days_To_Expiry'].max()
        if pd.notna(latest_days):
            st.sidebar.metric("Days to Expiry", int(latest_days))

    # ============================================================================
    # MAIN CHART AREA
    # ============================================================================

    if filtered_df.empty:
        st.warning("No data available for the selected filters.")
        return

    # Chart title with symbol info
    expiry_info = filtered_df['Expiry'].iloc[0] if 'Expiry' in filtered_df.columns else 'N/A'

    st.subheader(f"Price Movement: {selected_symbol} | {selected_series} | Expiry: {expiry_info}")

    # Toggle for Bid/Ask lines
    col1, col2 = st.columns(2)
    with col1:
        show_bid = st.checkbox("Show Best Bid Price", value=True)
    with col2:
        show_ask = st.checkbox("Show Best Offer Price", value=True)

    # Create the main chart
    fig = go.Figure()

    # Prepare hover template with both time and expiry info
    bid_hover = []
    ask_hover = []

    for idx, row in filtered_df.iterrows():
        time_str = row['Timestamp'].strftime('%H:%M:%S') if pd.notna(row['Timestamp']) else 'N/A'
        days_str = f"{int(row['Days_To_Expiry'])} days" if pd.notna(row['Days_To_Expiry']) else 'N/A'

        if pd.notna(row.get('Best Bid Price')):
            bid_hover.append(f"<b>Time:</b> {time_str}<br><b>Days to Expiry:</b> {days_str}<br><b>Bid Price:</b> {row['Best Bid Price']:.2f}")
        else:
            bid_hover.append("")

        if pd.notna(row.get('Best Offer Price')):
            ask_hover.append(f"<b>Time:</b> {time_str}<br><b>Days to Expiry:</b> {days_str}<br><b>Offer Price:</b> {row['Best Offer Price']:.2f}")
        else:
            ask_hover.append("")

    # Add Bid Price line (Time on X-axis)
    if show_bid and 'Best Bid Price' in filtered_df.columns:
        bid_mask = filtered_df['Best Bid Price'].notna()
        fig.add_trace(go.Scatter(
            x=filtered_df.loc[bid_mask, 'Timestamp'],
            y=filtered_df.loc[bid_mask, 'Best Bid Price'],
            mode='lines+markers',
            name='Best Bid Price',
            line=dict(color='#00cc96', width=2),
            marker=dict(size=6),
            hovertext=[bid_hover[i] for i in range(len(bid_hover)) if bid_mask.iloc[i] if isinstance(bid_mask, pd.Series) else True],
            hoverinfo='text',
            customdata=filtered_df.loc[bid_mask, 'Days_To_Expiry']
        ))

    # Add Ask Price line (Time on X-axis)
    if show_ask and 'Best Offer Price' in filtered_df.columns:
        ask_mask = filtered_df['Best Offer Price'].notna()
        fig.add_trace(go.Scatter(
            x=filtered_df.loc[ask_mask, 'Timestamp'],
            y=filtered_df.loc[ask_mask, 'Best Offer Price'],
            mode='lines+markers',
            name='Best Offer Price',
            line=dict(color='#ef553b', width=2),
            marker=dict(size=6),
            hovertext=[ask_hover[i] for i in range(len(ask_hover)) if ask_mask.iloc[i] if isinstance(ask_mask, pd.Series) else True],
            hoverinfo='text',
            customdata=filtered_df.loc[ask_mask, 'Days_To_Expiry']
        ))

    # Update layout with Time as X-axis
    days_to_expiry = filtered_df['Days_To_Expiry'].max() if 'Days_To_Expiry' in filtered_df.columns else 'N/A'
    days_display = f"{int(days_to_expiry)} days to expiry" if pd.notna(days_to_expiry) else 'N/A'

    fig.update_layout(
        title=dict(
            text=f"{selected_symbol} - Price Movement ({days_display})",
            x=0.5,
            xanchor='center'
        ),
        xaxis_title="Time",
        yaxis_title="Price",
        hovermode='closest',
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1
        ),
        height=500,
        margin=dict(l=20, r=20, t=60, b=20),
        xaxis=dict(
            rangeslider=dict(visible=True),
            type="date"
        )
    )

    st.plotly_chart(fig, width="stretch")

    # ============================================================================
    # DATA TABLE
    # ============================================================================

    st.markdown("---")
    st.subheader("📋 Raw Data")

    # Select columns to display
    display_columns = [
        'Timestamp', 'Series', 'Symbol', 'Best Bid Price', 'Best Offer Price',
        'LTP', 'Spread', 'Days_To_Expiry', 'Expiry'
    ]

    # Filter available columns
    available_cols = [col for col in display_columns if col in filtered_df.columns]

    if available_cols:
        display_df = filtered_df[available_cols].copy()

        # Format timestamp for display
        if 'Timestamp' in display_df.columns:
            display_df['Timestamp'] = display_df['Timestamp'].dt.strftime('%Y-%m-%d %H:%M:%S')

        # Format numeric columns
        if 'Best Bid Price' in display_df.columns:
            display_df['Best Bid Price'] = display_df['Best Bid Price'].apply(lambda x: f"{x:.2f}" if pd.notna(x) else 'N/A')
        if 'Best Offer Price' in display_df.columns:
            display_df['Best Offer Price'] = display_df['Best Offer Price'].apply(lambda x: f"{x:.2f}" if pd.notna(x) else 'N/A')

        st.dataframe(display_df, width="stretch", height=300)
    else:
        st.dataframe(filtered_df, width="stretch", height=300)

    # Export button
    csv = filtered_df.to_csv(index=False)
    st.download_button(
        label="📥 Download Filtered Data as CSV",
        data=csv,
        file_name=f"slb_{selected_symbol}_{selected_series}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
        mime="text/csv"
    )


if __name__ == "__main__":
    main()
