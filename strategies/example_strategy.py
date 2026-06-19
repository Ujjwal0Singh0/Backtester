"""
A dummy strategy to test the pipeline.
"""

from strategies.base_strategy import BaseStrategy
from typing import List, Dict, Any

class ExampleStrategy(BaseStrategy):
    """
    A simple example strategy that buys when price crosses a threshold.
    """
    def __init__(self, kite_connect: Any, threshold_price: float):
        """
        Initializes the ExampleStrategy.
        
        Args:
            kite_connect (Any): The KiteConnect instance.
            threshold_price (float): The price at which to buy.
        """
        super().__init__(kite_connect)
        self.threshold_price = threshold_price

    def on_ticks(self, ws: Any, ticks: List[Dict[str, Any]]) -> None:
        """
        Processes incoming ticks and places orders if conditions are met.
        
        Args:
            ws (Any): The websocket client instance.
            ticks (List[Dict[str, Any]]): Incoming tick data.
        """
        raise NotImplementedError
