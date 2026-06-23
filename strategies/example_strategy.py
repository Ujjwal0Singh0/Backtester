"""
A mock Z-score mean reversion strategy designed to stress-test the event-driven backtester boundaries.
"""

from typing import List, Dict, Any
from strategies.base_strategy import BaseStrategy
import logging

logger = logging.getLogger(__name__)

class ExampleStrategy(BaseStrategy):
    """
    A test strategy implementing mock Z-score entry/exit triggers to test
    execution, volume constraints, pessimistic fills, and FIFO settlement.
    """
    
    def __init__(self, kite_connect: Any, kws: Any = None):
        """
        Initializes the ExampleStrategy.
        
        Args:
            kite_connect (Any): The Mock REST API object.
            kws (Any): The Mock WebSocket API object.
        """
        super().__init__(kite_connect)
        self.kws = kws
        self.tick_count = 0

    def on_ticks(self, ws: Any, ticks: List[Dict[str, Any]]) -> None:
        """
        Processes incoming ticks and places orders to trigger test scenarios.
        
        Args:
            ws (Any): The websocket client instance.
            ticks (List[Dict[str, Any]]): Incoming tick data.
        """
        if self.kws is None:
            self.kws = ws
            
        self.tick_count += 1
        
        if not ticks:
            return
            
        tick = ticks[0]
        # Using a dummy tradingsymbol for tests
        tradingsymbol = "TEST_SYMBOL" 
        
        # 1. Basic Execution: Place a standard Market Buy order
        if self.tick_count == 1:
            logger.info("Tick 1: Firing Basic Execution - Market Buy")
            self.kite.place_order(
                variety="regular",
                exchange="NSE",
                tradingsymbol=tradingsymbol,
                transaction_type="BUY",
                quantity=1,
                product="MIS",
                order_type="MARKET",
                tag="basic_execution"
            )
            
        # 2. Volume Constraints: Place a massive Market Sell order
        elif self.tick_count == 2:
            logger.info("Tick 2: Firing Volume Constraints - Massive Market Sell")
            self.kite.place_order(
                variety="regular",
                exchange="NSE",
                tradingsymbol=tradingsymbol,
                transaction_type="SELL",
                quantity=100000,
                product="MIS",
                order_type="MARKET",
                tag="volume_constraints"
            )
            
        # 3. Pessimistic Fill Rule: Limit Buy order at exact 'Low' or 'Best Bid'
        elif self.tick_count == 3:
            price = tick.get("low", tick.get("last_price", 100.0))
            if "depth" in tick and "buy" in tick["depth"] and len(tick["depth"]["buy"]) > 0:
                price = tick["depth"]["buy"][0].get("price", price)
                
            logger.info(f"Tick 3: Firing Pessimistic Fill - Limit Buy at exact price {price}")
            self.kite.place_order(
                variety="regular",
                exchange="NSE",
                tradingsymbol=tradingsymbol,
                transaction_type="BUY",
                quantity=1,
                product="MIS",
                order_type="LIMIT",
                price=price,
                tag="pessimistic_fill"
            )
            
        # 4. FIFO Accounting and Settlement: 3 staggered buys, 1 sell
        elif self.tick_count == 4:
            logger.info("Tick 4: Firing FIFO Accounting and Settlement - Staggered orders")
            base_price = tick.get("last_price", 100.0)
            
            # Staggered buys
            self.kite.place_order(
                variety="regular",
                exchange="NSE",
                tradingsymbol=tradingsymbol,
                transaction_type="BUY",
                quantity=100,
                product="MIS",
                order_type="LIMIT",
                price=base_price - 0.5,
                tag="fifo_buy_1"
            )
            self.kite.place_order(
                variety="regular",
                exchange="NSE",
                tradingsymbol=tradingsymbol,
                transaction_type="BUY",
                quantity=100,
                product="MIS",
                order_type="LIMIT",
                price=base_price - 1.0,
                tag="fifo_buy_2"
            )
            self.kite.place_order(
                variety="regular",
                exchange="NSE",
                tradingsymbol=tradingsymbol,
                transaction_type="BUY",
                quantity=100,
                product="MIS",
                order_type="LIMIT",
                price=base_price - 1.5,
                tag="fifo_buy_3"
            )
            
            # Single sell
            self.kite.place_order(
                variety="regular",
                exchange="NSE",
                tradingsymbol=tradingsymbol,
                transaction_type="SELL",
                quantity=150,
                product="MIS",
                order_type="MARKET",
                tag="fifo_sell_1"
            )

    def on_order_update(self, ws: Any, data: Dict[str, Any]) -> None:
        """
        Callback for order updates. Used here for State Tracking.
        
        Args:
            ws (Any): The websocket client instance.
            data (Dict[str, Any]): Order update data from the broker.
        """
        status = data.get("status")
        order_id = data.get("order_id", "UNKNOWN_ORDER")
        
        # State Tracking: Log when orders transition from OPEN to COMPLETE or REJECTED
        if status in ("COMPLETE", "REJECTED"):
            logger.info(f"[State Tracking] Order {order_id} transitioned to {status}")
        else:
            logger.debug(f"Order {order_id} update: status={status}")
