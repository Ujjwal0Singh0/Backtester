"""
The "Master Clock" that yields rows chronologically.
"""
import os
import pandas as pd
from typing import Iterator

class TickEvent:
    """
    Represents a single historical tick or OHLCV row.
    
    PERFORMANCE HACK: Using __slots__ prevents Python from allocating a 
    dynamic __dict__ for every single tick. When yielding 1,000,000+ ticks, 
    this saves hundreds of megabytes of RAM and cuts instantiation time drastically.
    """
    __slots__ = ['timestamp', 'symbol', 'last_price', 'volume']
    
    def __init__(self, timestamp: str, symbol: str, last_price: float, volume: int):
        self.timestamp = timestamp
        self.symbol = symbol
        self.last_price = last_price
        self.volume = volume

class TickGenerator:
    """
    Reads locally cached .parquet files line-by-line into memory and yields a TickEvent.
    Must never make network calls during the backtest loop.
    """
    def __init__(self, data_dir: str):
        """
        Initializes the TickGenerator.
        """
        self.data_dir = data_dir

    def generate_ticks(self, symbol: str, start_date: str, end_date: str) -> Iterator[TickEvent]:
        """
        Yields TickEvents chronologically for a given symbol and date range.
        Strictly prohibits network calls and avoids Pandas.iterrows() for performance.
        """
        filepath = os.path.join(self.data_dir, f"{symbol}.parquet")
        
        if not os.path.exists(filepath):
            raise FileNotFoundError(
                f"Missing Parquet file for {symbol}. Run ingestion before backtesting."
            )

        # 1. READ ONLY REQUIRED COLUMNS: Massively reduces memory overhead
        required_cols = ['datetime', 'close', 'volume']
        df = pd.read_parquet(filepath, engine='pyarrow', columns=required_cols)
        
        # 2. EFFICIENT FILTERING: Vectorized mask instead of row-by-row checks
        start = pd.to_datetime(start_date, utc=True)
        end = pd.to_datetime(end_date, utc=True)
        mask = (df['datetime'] >= start) & (df['datetime'] <= end)
        filtered_df = df.loc[mask]

        # 3. YIELD IN SEQUENCE: itertuples(index=False) returns a lightweight C-level 
        # NamedTuple, which is orders of magnitude faster than iterrows().
        for row in filtered_df.itertuples(index=False):
            yield TickEvent(
                timestamp=str(row.datetime),
                symbol=symbol,
                last_price=float(row.close),
                volume=int(row.volume)
            )