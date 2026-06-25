"""
Writes raw execution events to CSV.
"""

import csv
import os
import logging
from typing import Any

logger = logging.getLogger(__name__)

class TransactionLogger:
    """
    Logs every execution (fill, order placement, etc.) to a file for later analysis.
    Optimized for low-latency append operations in event-driven systems.
    """
    def __init__(self, log_filepath: str):
        """
        Initializes the TransactionLogger.
        
        Args:
            log_filepath (str): The path to the CSV file where logs will be written.
        """
        self.log_filepath = log_filepath
        self._headers = ['timestamp', 'symbol', 'event_type', 'side', 'quantity', 'price', 'fees']
        self._initialize_file()

    def _initialize_file(self) -> None:
        """
        Creates the log file and writes headers if it does not already exist.
        """
        if not os.path.exists(self.log_filepath):
            try:
                with open(self.log_filepath, 'w', newline='') as f:
                    writer = csv.writer(f)
                    writer.writerow(self._headers)
            except IOError as e:
                logger.error(f"Failed to initialize transaction log at {self.log_filepath}: {e}")

    def log_event(self, event: Any) -> None:
        """
        Writes a single event to the log file.
        
        Args:
            event (Any): The event to log (e.g., FillEvent, OrderEvent).
                         Handles both dictionaries and class objects.
        """
        # Extract data safely whether the event is a dictionary or an object
        if isinstance(event, dict):
            timestamp = event.get('timestamp', '')
            symbol = event.get('symbol', event.get('tradingsymbol', ''))
            event_type = event.get('event_type', event.get('status', 'UNKNOWN'))
            side = event.get('side', event.get('transaction_type', ''))
            quantity = event.get('quantity', event.get('filled_quantity', 0))
            price = event.get('price', event.get('average_price', 0.0))
            fees = event.get('fees', 0.0)
        else:
            # Fallback for dataclasses or custom objects
            timestamp = getattr(event, 'timestamp', '')
            symbol = getattr(event, 'symbol', getattr(event, 'tradingsymbol', ''))
            event_type = getattr(event, 'event_type', type(event).__name__)
            side = getattr(event, 'side', getattr(event, 'transaction_type', ''))
            quantity = getattr(event, 'quantity', getattr(event, 'filled_quantity', 0))
            price = getattr(event, 'price', getattr(event, 'average_price', 0.0))
            fees = getattr(event, 'fees', 0.0)

        row = [timestamp, symbol, event_type, side, quantity, price, fees]

        try:
            with open(self.log_filepath, 'a', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(row)
        except IOError as e:
            logger.error(f"Failed to write event to log: {e}")
