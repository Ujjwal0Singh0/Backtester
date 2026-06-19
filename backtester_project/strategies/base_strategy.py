"""
The interface requiring on_ticks() and place_order().
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Any

class BaseStrategy(ABC):
    """
    Abstract base class for all trading strategies.
    Ensures that strategies are compatible with both live and backtesting environments.
    """
    def __init__(self, kite_connect: Any):
        """
        Initializes the strategy.
        
        Args:
            kite_connect (Any): The KiteConnect instance (Mock or Live).
        """
        self.kite = kite_connect

    @abstractmethod
    def on_ticks(self, ws: Any, ticks: List[Dict[str, Any]]) -> None:
        """
        Callback invoked when new market data arrives.
        
        Args:
            ws (Any): The websocket client instance.
            ticks (List[Dict[str, Any]]): The list of incoming ticks.
        """
        pass
