"""
MockREST API (margins, place_order, positions).
"""

from engine.event_bus import EventBus
from typing import Dict, Any

class MockKiteConnect:
    """
    Possesses the exact method signatures as the official KiteConnect class.
    When called, creates OrderEvents and drops them into the event_bus.
    """
    def __init__(self, api_key: str, event_bus: EventBus):
        """
        Initializes the Mock KiteConnect.
        
        Args:
            api_key (str): Mock API key.
            event_bus (EventBus): The centralized event bus to route orders.
        """
        pass

    def place_order(self, variety: str, exchange: str, tradingsymbol: str, 
                    transaction_type: str, quantity: int, product: str, 
                    order_type: str, price: float = None, validity: str = None, 
                    disclosed_quantity: int = None, trigger_price: float = None, 
                    squareoff: float = None, stoploss: float = None, 
                    trailing_stoploss: float = None, tag: str = None) -> str:
        """
        Mocks placing an order. Queues an OrderEvent.
        
        Returns:
            str: A mocked order ID.
        """
        raise NotImplementedError

    def margins(self) -> Dict[str, Any]:
        """
        Mocks fetching margin details.
        
        Returns:
            Dict[str, Any]: Mock margin data.
        """
        raise NotImplementedError

    def positions(self) -> Dict[str, Any]:
        """
        Mocks fetching active positions.
        
        Returns:
            Dict[str, Any]: Mock positions data.
        """
        raise NotImplementedError
