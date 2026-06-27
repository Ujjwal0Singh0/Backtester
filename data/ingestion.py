"""
Two kinds of data are supported, matching the two endpoints the Data API
actually exposes:

  - OHLCV (candles) via GET /instruments/historical/{symbol}/{interval}
  - L2 / order-book snapshots via GET /quote 
"""

import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import requests

IST = "Asia/Kolkata"

# OHLCV schema — mirrors the Data API's own ingestion script (datafetch.py)
# so both halves of the system agree on column names/types. tz is fixed to
# Asia/Kolkata (IST)
OHLCV_PARQUET_SCHEMA = pa.schema([
    ("datetime", pa.timestamp("ns", tz=IST)),
    ("open",     pa.float64()),
    ("high",     pa.float64()),
    ("low",      pa.float64()),
    ("close",    pa.float64()),
    ("volume",   pa.float64()),
    ("symbol",   pa.string()),
])
# L2 schema 
L2_PARQUET_SCHEMA = pa.schema([
    ("datetime", pa.timestamp("ns", tz=IST)),
    ("symbol",   pa.string()),
    ("tick",     pa.string()),
])


def _normalize_ist(date_str: str, end_of_day: bool = False) -> str:
    """
    Accepts either a bare date ("2023-01-01") or a full IST datetime
    ("2023-01-01 09:15:00") and always returns the full
    "YYYY-MM-DD HH:MM:SS" form the Data API expects
    """
    date_str = date_str.strip()
    if " " in date_str or "T" in date_str:
        return date_str.replace("T", " ")
    return f"{date_str} {'23:59:59' if end_of_day else '00:00:00'}"


class DataIngestion:
    """
    Handles fetching historical OHLCV and L2 data from our internal Data
    API and saving it locally as Parquet (IST), ready for TickGenerator
    to stream from.
    """

    def __init__(self, base_url: str = "http://0.0.0.0:8000", api_key: str = ""):
        """
        Args:
            base_url (str): Root URL of the Data API, e.g. "http://0.0.0.0:8000".
            api_key (str): Reserved for if/when the Data API grows auth.
                Unused today (the service currently has none).
        """
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self._session = requests.Session()

    # OHLCV

    def fetch_data(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        frequency: str,
    ) -> List[Dict[str, Any]]:
        """
        Fetches historical OHLCV bars for one symbol via the Data API's
        Kite-style GET endpoint:

            GET /instruments/historical/{symbol}/{interval}?from=...&to=...

        Args:
            symbol (str): Trading symbol exactly as stored in the Data
                API's parquet (e.g. "AXISBANK_NS").
            start_date (str): Date or full IST datetime string.
            end_date (str): Date or full IST datetime string.
            frequency (str): One of the Data API's Frequency enum values
                ("minute", "3minute", ..., "day", "week", "month").

        Returns:
            List[Dict[str, Any]]: one dict per bar — "datetime" (IST,
            e.g. "2026-06-08T09:15:00+0530"), "open", "high", "low",
            "close", "volume", "symbol".

        Raises:
            RuntimeError: if the Data API responds with a non-200 status,
                or with 200 but zero candles.
        """
        url = f"{self.base_url}/instruments/historical/{symbol}/{frequency}"
        params = {
            "from": _normalize_ist(start_date, end_of_day=False),
            "to":   _normalize_ist(end_date, end_of_day=True),
        }

        response = self._session.get(url, params=params, timeout=120)

        if response.status_code != 200:
            raise RuntimeError(
                f"Data API returned {response.status_code} for "
                f"{symbol} ({frequency}, {params['from']} -> {params['to']}): "
                f"{response.text}"
            )

        body = response.json()
        candles = body.get("data", {}).get("candles", [])

        if not candles:
            raise RuntimeError(
                f"No candles returned for {symbol} ({frequency}) "
                f"between {params['from']} and {params['to']}"
            )

        bars = []
        for candle in candles:
            dt, o, h, l, c, v = candle
            bars.append({
                "datetime": dt, "open": o, "high": h, "low": l,
                "close": c, "volume": v, "symbol": symbol,
            })

        return bars

    def save_to_parquet(self, data: List[Dict[str, Any]], filepath: str) -> None:
        """
        Appends fetched OHLCV bars to a Parquet file, merging with
        whatever is already on disk so repeated ingestion runs never
        clobber previously saved data.
        """
        if not data:
            print("No data to save, skipping.")
            return

        new_df = pd.DataFrame(data)
        new_df["datetime"] = pd.to_datetime(new_df["datetime"]).dt.tz_convert(IST)

        out_path = Path(filepath)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        if out_path.exists():
            existing_df = pq.read_table(out_path).to_pandas()
            combined = pd.concat([existing_df, new_df], ignore_index=True)
        else:
            combined = new_df

        combined = combined.drop_duplicates(subset=["symbol", "datetime"], keep="last")
        combined = combined.sort_values(["symbol", "datetime"]).reset_index(drop=True)
        combined = combined[["datetime", "open", "high", "low", "close", "volume", "symbol"]]

        table = pa.Table.from_pandas(combined, schema=OHLCV_PARQUET_SCHEMA, preserve_index=False)
        pq.write_table(table, out_path)

        print(f"Saved {len(new_df)} new bars -> {out_path} (file now has {len(combined)} total rows)")

    def ingest_universe(
        self,
        symbols: List[str],
        start_date: str,
        end_date: str,
        frequency: str,
        filepath: str,
    ) -> None:
        """
        Fetches + saves OHLCV one symbol at a time, so a single bad/missing
        symbol can't abort the whole batch, and RAM never has to hold more
        than one symbol's worth of bars at once.
        """
        for symbol in symbols:
            print(f"Fetching {symbol} ({frequency}) ...")
            try:
                bars = self.fetch_data(symbol, start_date, end_date, frequency)
            except (RuntimeError, requests.RequestException) as exc:
                print(f"  SKIPPED {symbol}: {exc}")
                continue

            self.save_to_parquet(bars, filepath)
    # L2 / order-book

    def fetch_l2_data(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        interval_seconds: int = 60,
    ) -> List[Dict[str, Any]]:
        """
        Fetches L2 (order-book depth) snapshots for one symbol via the
        Data API's quote endpoint:
        GET /quote?i={symbol}&time={timestamp}

        Args:
            symbol (str): Trading symbol, e.g. "NSE:RELIANCE" (must match
                a column in the orderbook parquet — see
                mock_orderbook_data_generator.py for the naming).
            start_date (str): Date or full IST datetime string.
            end_date (str): Date or full IST datetime string.
            interval_seconds (int): Gap between sampled snapshots.

        Returns:
            List[Dict[str, Any]]: one dict per snapshot with "datetime",
            "symbol", and "tick" (the raw snapshot as a JSON string).
        """
        start_dt = datetime.strptime(_normalize_ist(start_date), "%Y-%m-%d %H:%M:%S")
        end_dt = datetime.strptime(_normalize_ist(end_date, end_of_day=True), "%Y-%m-%d %H:%M:%S")

        records = []
        cursor = start_dt
        while cursor <= end_dt:
            time_str = cursor.strftime("%Y-%m-%d %H:%M:%S")
            response = self._session.get(
                f"{self.base_url}/quote",
                params={"i": symbol, "time": time_str},
                timeout=30,
            )

            if response.status_code == 200:
                tick_data = response.json().get("data", {}).get(symbol, {})
                if tick_data:
                    records.append({
                        "datetime": time_str,
                        "symbol": symbol,
                        "tick": json.dumps(tick_data),
                    })
            # 404 just means no snapshot exists at/before this timestamp yet
            # — skip it rather than failing the whole sweep.

            cursor += timedelta(seconds=interval_seconds)

        return records

    def save_l2_to_parquet(self, data: List[Dict[str, Any]], filepath: str) -> None:
        """
        Appends fetched L2 snapshots to a Parquet file, same merge/dedupe
        approach as save_to_parquet(), against L2_PARQUET_SCHEMA.
        """
        if not data:
            print("No L2 data to save, skipping.")
            return

        new_df = pd.DataFrame(data)
        new_df["datetime"] = pd.to_datetime(new_df["datetime"])
        if new_df["datetime"].dt.tz is None:
            new_df["datetime"] = new_df["datetime"].dt.tz_localize(IST)
        else:
            new_df["datetime"] = new_df["datetime"].dt.tz_convert(IST)

        out_path = Path(filepath)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        if out_path.exists():
            existing_df = pq.read_table(out_path).to_pandas()
            combined = pd.concat([existing_df, new_df], ignore_index=True)
        else:
            combined = new_df

        combined = combined.drop_duplicates(subset=["symbol", "datetime"], keep="last")
        combined = combined.sort_values(["symbol", "datetime"]).reset_index(drop=True)
        combined = combined[["datetime", "symbol", "tick"]]

        table = pa.Table.from_pandas(combined, schema=L2_PARQUET_SCHEMA, preserve_index=False)
        pq.write_table(table, out_path)

        print(f"Saved {len(new_df)} new L2 snapshots -> {out_path} (file now has {len(combined)} total rows)")


if __name__ == "__main__":
    # SCENARIO: 50 symbols, 1 year, 1-minute OHLCV.

    SYMBOLS = [
        "RELIANCE_NS", "TCS_NS", "INFY_NS", "HDFCBANK_NS", "ICICIBANK_NS",
        "SBIN_NS", "WIPRO_NS", "BAJFINANCE_NS", "AXISBANK_NS", "KOTAKBANK_NS",
        "HINDUNILVR_NS", "ITC_NS", "LT_NS", "MARUTI_NS", "SUNPHARMA_NS",
        "TITAN_NS", "ULTRACEMCO_NS", "ASIANPAINT_NS", "BAJAJFINSV_NS", "NESTLEIND_NS",
        "HCLTECH_NS", "ADANIENT_NS", "ADANIPORTS_NS", "NTPC_NS", "POWERGRID_NS",
        "ONGC_NS", "COALINDIA_NS", "TATAMOTORS_NS", "TATASTEEL_NS", "JSWSTEEL_NS",
        "GRASIM_NS", "SHREECEM_NS", "DRREDDY_NS", "CIPLA_NS", "DIVISLAB_NS",
        "APOLLOHOSP_NS", "EICHERMOT_NS", "HEROMOTOCO_NS", "BAJAJ-AUTO_NS", "TECHM_NS",
        "HDFCLIFE_NS", "SBILIFE_NS", "BRITANNIA_NS", "DABUR_NS", "GODREJCP_NS",
        "PIDILITIND_NS", "BPCL_NS", "IOC_NS", "GAIL_NS", "VEDL_NS",
    ]
    assert len(SYMBOLS) == 50, f"expected 50 symbols, got {len(SYMBOLS)}"

    FREQUENCY = "minute"  # 1-minute bars

    # Rolling 1-year window ending today, rather than a date that'll go
    # stale — re-running this script later still asks for "the last year".
    END_DATE = datetime.now().strftime("%Y-%m-%d")
    START_DATE = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")

    OUTPUT_PATH = f"data_cache/ohlcv_{FREQUENCY}.parquet"

    ingestion = DataIngestion(base_url="http://0.0.0.0:8000")

    print(f"Ingesting {len(SYMBOLS)} symbols, {FREQUENCY}, {START_DATE} -> {END_DATE}")
    started = time.time()
    ingestion.ingest_universe(
        symbols=SYMBOLS,
        start_date=START_DATE,
        end_date=END_DATE,
        frequency=FREQUENCY,
        filepath=OUTPUT_PATH,
    )
    print(f"Done in {time.time() - started:.1f}s")
    