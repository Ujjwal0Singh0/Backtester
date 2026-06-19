"""
The "Master Clock" that yields rows chronologically.
"""

from typing import Iterator, Dict, Any

class TickEvent:
    """
    Represents a single historical tick or OHLCV row.
    """
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
        
        Args:
            data_dir (str): The directory containing historical .parquet files.
        """
        pass

    def generate_ticks(self, symbol: str, start_date: str, end_date: str) -> Iterator[TickEvent]:
        """
        Yields TickEvents chronologically for a given symbol and date range.
        
        Args:
            symbol (str): The trading symbol.
            start_date (str): The start date.
            end_date (str): The end date.
            
        Yields:
            TickEvent: The next chronological tick event.
        """
        raise NotImplementedError
