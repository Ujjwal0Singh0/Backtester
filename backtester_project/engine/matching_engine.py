"""
Evaluates orders against ticks (Volume/Latency rules).
"""

from engine.event_bus import EventBus
from data.tick_generator import TickEvent
from typing import Any

class MatchingEngine:
    """
    Contains strict, pessimistic rules to evaluate open orders against incoming ticks.
    """
    def __init__(self, event_bus: EventBus):
        """
        Initializes the MatchingEngine.
        
        Args:
            event_bus (EventBus): The centralized event bus for publishing FillEvents.
        """
        pass

    def process_order(self, order_event: Any) -> None:
        """
        Receives an OrderEvent and adds it to the internal open orders list.
        
        Args:
            order_event (Any): The order event to track.
        """
        raise NotImplementedError

    def evaluate_ticks(self, tick_event: TickEvent) -> None:
        """
        Evaluates all pending open orders against the new TickEvent.
        Applies pessimistic rules (e.g., volume limits, strict limit price checking).
        If an order is filled, generates a FillEvent and publishes it to the event_bus.
        
        Args:
            tick_event (TickEvent): The incoming tick event.
        """
        raise NotImplementedError
