"""
Writes raw execution events to CSV.
"""

from typing import Any

class TransactionLogger:
    """
    Logs every execution (fill, order placement, etc.) to a file for later analysis.
    """
    def __init__(self, log_filepath: str):
        """
        Initializes the TransactionLogger.
        
        Args:
            log_filepath (str): The path to the CSV file where logs will be written.
        """
        pass

    def log_event(self, event: Any) -> None:
        """
        Writes a single event to the log file.
        
        Args:
            event (Any): The event to log (e.g., FillEvent, OrderEvent).
        """
        raise NotImplementedError
