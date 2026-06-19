"""
Mock WebSocket (on_ticks pushes to strategy).
"""

from typing import Callable, List, Dict, Any

class MockKiteTicker:
    """
    Simulates the WebSocket. Receives a tick from the event_bus and triggers strategy.on_ticks().
    """
    def __init__(self, api_key: str, access_token: str):
        """
        Initializes the Mock KiteTicker.
        
        Args:
            api_key (str): Mock API key.
            access_token (str): Mock access token.
        """
        pass

    def on_ticks(self, ws: Any, ticks: List[Dict[str, Any]]) -> None:
        """
        Callback triggered when a new tick is received.
        Passes the tick data to the subscribed strategy.
        
        Args:
            ws (Any): The mock websocket instance.
            ticks (List[Dict[str, Any]]): The list of tick dictionaries.
        """
        raise NotImplementedError

    def connect(self, threaded: bool = False, disable_ssl_verification: bool = False, 
                proxy: Dict[str, Any] = None) -> None:
        """
        Mocks the connection process.
        """
        raise NotImplementedError
        
    def close(self) -> None:
        """
        Mocks the disconnection process.
        """
        raise NotImplementedError
