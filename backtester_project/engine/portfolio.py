"""
The active ledger tracking Cash, Margin, and Positions.
"""

from engine.event_bus import EventBus
from data.tick_generator import TickEvent
from typing import Dict, Any

class Portfolio:
    """
    Maintains available_cash and an active positions dictionary.
    Marks positions to market on every tick.
    """
    def __init__(self, event_bus: EventBus, initial_capital: float = 100000.0):
        """
        Initializes the Portfolio.
        
        Args:
            event_bus (EventBus): The centralized event bus.
            initial_capital (float): The starting cash balance.
        """
        pass

    def update_from_fill(self, fill_event: Any) -> None:
        """
        Updates positions and cash based on a newly filled order.
        If a position is closed, triggers the settlement API.
        
        Args:
            fill_event (Any): The fill event indicating an executed trade.
        """
        raise NotImplementedError

    def mark_to_market(self, tick_event: TickEvent) -> None:
        """
        Updates the current market value of open positions based on the latest tick.
        
        Args:
            tick_event (TickEvent): The incoming tick event.
        """
        raise NotImplementedError
        
    def adjust_cash(self, amount: float) -> None:
        """
        Adjusts the available cash in the portfolio (e.g., for taxes, dividends, or fees).
        
        Args:
            amount (float): The amount to adjust (positive for credit, negative for debit).
        """
        raise NotImplementedError
