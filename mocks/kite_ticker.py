"""
Mock WebSocket (on_ticks pushes to strategy).
"""

from typing import Callable, List, Dict, Any

class MockKiteTicker:
    """
    Simulates the WebSocket. Receives a tick from the event_bus and triggers strategy.on_ticks()
    """
    def __init__(self, api_key: str, access_token: str=None):
        """
        Initializes the Mock KiteTicker.
        
        Args:
            api_key (str): Mock API key.
            access_token (str): Mock access token.
        """
        self.api_key=api_key
        self.access_token=access_token
        self.is_connected: bool=False

        # These mirror the real SDK's attribute names exactly.
        self.on_ticks: Callable = None
        self.on_connect: Callable = None
        self.on_close: Callable = None
        self.on_error: Callable = None
        self.on_reconnect: Callable = None
        self.on_noreconnect: Callable = None
        self.on_order_update: Callable = None

        #subscribed tokens
        self._subscribed_tokens: List[int] = []
        self._mode_map: Dict[int, str] = {}

    """def on_ticks(self, ws: Any, ticks: List[Dict[str, Any]]) -> None:

        Callback triggered when a new tick is received.
        Passes the tick data to the subscribed strategy.
        
        Args:
            ws (Any): The mock websocket instance.
            ticks (List[Dict[str, Any]]): The list of tick dictionaries.
        
        raise NotImplementedError"""

    def connect(self, threaded: bool = False, disable_ssl_verification: bool = False, 
                proxy: Dict[str, Any] = None) -> None:
        """
        Mocks the connection process.
        """
        self.is_connected=True
        if self.on_connect:
            self.on_connect(self,None)
        
    def close(self, code: int =None, reason:str=None) -> None:
        """
        Mocks the disconnection process.
        """
        self.is_connected=False
        if self.on_close:
            self.on_close(self,code,reason)
    
    def subscribe(self,instrument_tokens:List[int])->None:
        #mirrors kws.subscribe
        for token in instrument_tokens:
            if token not in self._subscribed_tokens:
                self._subscribed_tokens.append(token)
    
    def unsubscribe(self, instrument_tokens: List[int]) -> None:
        for token in instrument_tokens:
            if token in self._subscribed_tokens:
                self._subscribed_tokens.remove(token)
            self._mode_map.pop(token, None)
    
    def set_mode(self,mode:str,instrument_tokens:List[int])->None:
        #mirrors kws.set_mode
        for token in instrument_tokens:
            self._mode_map[token]=mode
    
    #Mode constants
    MODE_FULL="full"
    MODE_QUOTE="quote"
    MODE_LTP="ltp"

    def stop_retry(self) -> None:
        #for ws.stop_retry()
        pass

    def dispatch_ticks(self, ticks: List[Dict[str, Any]]) -> None:
        #called by simulator.py
        if self.on_ticks and self.is_connected:
            self.on_ticks(self, ticks) 
