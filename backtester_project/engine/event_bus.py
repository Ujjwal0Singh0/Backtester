"""
Pub/Sub queue for Ticks, Orders, and Fills.
"""

from typing import List, Any
from collections import deque

class EventBus:
    """
    A centralized FIFO (First-In-First-Out) queue.
    Routes TickEvents to the Strategy, OrderEvents to the Matching Engine, 
    and FillEvents to the Portfolio.
    """
    def __init__(self):
        """
        Initializes the EventBus.
        """
        self.queue: deque = deque()

    def publish(self, event: Any) -> None:
        """
        Pushes an event onto the queue.
        
        Args:
            event (Any): The event to publish (TickEvent, OrderEvent, FillEvent, etc.).
        """
        raise NotImplementedError

    def get_next_event(self) -> Any:
        """
        Retrieves the next event from the queue.
        
        Returns:
            Any: The next event, or None if the queue is empty.
        """
        raise NotImplementedError
        
    def has_events(self) -> bool:
        """
        Checks if there are any events in the queue.
        
        Returns:
            bool: True if events exist, False otherwise.
        """
        raise NotImplementedError
