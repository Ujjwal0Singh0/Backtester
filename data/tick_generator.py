from datetime import datetime
from pathlib import Path
from typing import Iterator
from zoneinfo import ZoneInfo

import pyarrow.parquet as pq

IST = ZoneInfo("Asia/Kolkata")


class TickEvent:
  
    __slots__ = ("timestamp", "symbol", "last_price", "volume")

    def __init__(self, timestamp, symbol: str, last_price: float, volume: int):
        self.timestamp = timestamp
        self.symbol = symbol
        self.last_price = last_price
        self.volume = volume

    def __repr__(self) -> str:
        return f"TickEvent({self.timestamp}, {self.symbol}, {self.last_price}, {self.volume})"


def _parse_ist(date_str: str, end_of_day: bool = False) -> datetime:
    """
    Accepts either a bare date ("2026-06-08") or a full datetime
    ("2026-06-08 09:15:00") and returns an IST-aware datetime.
    A bare date defaults to 00:00:00 (start) or 23:59:59 (end_of_day=True).
    """
    date_str = date_str.strip()
    if " " not in date_str and "T" not in date_str:
        date_str += " 23:59:59" if end_of_day else " 00:00:00"
    date_str = date_str.replace("T", " ")

    dt = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S")
    return dt.replace(tzinfo=IST)


class TickGenerator:
    """
    Reads a locally cached .parquet file and yields TickEvents
    chronologically, in IST. Must never make network calls during the
    backtest loop.
    """

    def __init__(self, data_dir: str, frequency: str):

        self.frequency = frequency
        self.filepath = Path(data_dir) / f"ohlcv_{frequency}.parquet"

    def generate_ticks(self, symbol: str, start_date: str, end_date: str) -> Iterator:
        """
        Yields TickEvents chronologically for a given symbol and date
        range, with timestamps in IST.

        Args:
            symbol (str): The trading symbol.
            start_date (str): Date or full IST datetime string.
            end_date (str): Date or full IST datetime string.

        Yields:
            TickEvent: the next chronological tick event.
        """
        if not self.filepath.exists():
            raise FileNotFoundError(
                f"No ingested data at {self.filepath}. "
                f"Run ingestion.py with frequency='{self.frequency}' first."
            )

        start_ts = _parse_ist(start_date, end_of_day=False)
        end_ts = _parse_ist(end_date, end_of_day=True)

        table = pq.read_table(
            self.filepath,
            columns=["datetime", "close", "volume", "symbol"],
            filters=[
                ("symbol", "=", symbol),
                ("datetime", ">=", start_ts),
                ("datetime", "<=", end_ts),
            ],
        )

        if table.num_rows == 0:
            return

        table = table.sort_by("datetime")
        df = table.to_pandas()

        for row in df.itertuples(index=False):
            yield TickEvent(
                timestamp=row.datetime,  
                symbol=symbol,
                last_price=row.close,
                volume=int(row.volume),
            )