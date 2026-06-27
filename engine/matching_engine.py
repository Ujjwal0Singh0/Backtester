"""
Evaluates orders against ticks (Volume/Latency rules).
"""

from engine.event_bus import EventBus
from data.tick_generator import TickEvent
from typing import Any
from dataclasses import dataclass, field
from datetime import datetime, timedelta


@dataclass
class OrderEvent:
    order_id: str
    timestamp: datetime
    symbol: str
    side: str          # "BUY" or "SELL"
    order_type: str    # "MARKET" or "LIMIT"
    quantity: int
    price: float = 0.0 # Only used for LIMIT orders
    activation_time: datetime = None # Enforces the 50ms latency penalty

    def __post_init__(self):
        if self.quantity <= 0:
            raise ValueError(f"Order quantity must be positive, got {self.quantity}")
        if self.side not in ("BUY", "SELL"):
            raise ValueError(f"Order side must be 'BUY' or 'SELL', got '{self.side}'")
        if self.order_type not in ("MARKET", "LIMIT"):
            raise ValueError(f"Order type must be 'MARKET' or 'LIMIT', got '{self.order_type}'")
        if self.order_type == "LIMIT" and self.price <= 0:
            raise ValueError(f"LIMIT order must have a positive price, got {self.price}")


@dataclass
class FillEvent:
    order_id: str
    timestamp: datetime
    symbol: str
    side: str
    quantity: int
    price: float


class MatchingEngine:
    """
    Contains strict, pessimistic rules to evaluate open orders against incoming ticks.
    """
    def __init__(self, event_bus: EventBus, volume_cap: float = 0.05, latency_ms: int = 50):
        """
        Initializes the MatchingEngine.
        
        Args:
            event_bus (EventBus): The centralized event bus for publishing FillEvents.
            volume_cap (float): The maximum percentage of tick volume an order can consume.
            latency_ms (int): The simulated network latency penalty in milliseconds.
        """
        self.event_bus = event_bus
        self.volume_cap = volume_cap
        self.latency = timedelta(milliseconds=latency_ms) 
        
        # Dictionaries mapping symbol -> list of resting OrderEvents
        self.pending_limits: dict[str, list[OrderEvent]] = {}
        self.pending_markets: dict[str, list[OrderEvent]] = {}

    def process_order(self, order_event: Any) -> None:
        """
        Receives an OrderEvent and adds it to the internal open orders list.
        Because of latency, ALL orders are queued and stamped with an activation time.
        
        Args:
            order_event (Any): The order event to track.
        """
        order_event.activation_time = order_event.timestamp + self.latency
        
        if order_event.order_type == "MARKET":
            self.pending_markets.setdefault(order_event.symbol, []).append(order_event)
        elif order_event.order_type == "LIMIT":
            self.pending_limits.setdefault(order_event.symbol, []).append(order_event)

    def evaluate_ticks(self, tick_event: TickEvent) -> None:
        """
        Evaluates all pending open orders against the new TickEvent.
        Applies pessimistic rules (e.g., volume limits, strict limit price checking).
        If an order is filled, generates a FillEvent and publishes it to the event_bus.
        
        Args:
            tick_event (TickEvent): The incoming tick event.
        """
        # Note: If TickEvent is a class object instead of a dict, change these dict 
        # accesses (e.g., tick_event["symbol"]) to attribute accesses (e.g., tick_event.symbol)
        symbol = tick_event["symbol"]
        tick_time = tick_event.get("datetime") or datetime.strptime(tick_event["timestamp"], "%Y-%m-%d %H:%M:%S")

        # --- GATE 1: Process Delayed Market Orders ---
        if symbol in self.pending_markets:
            surviving_markets = []
            for order in self.pending_markets[symbol]:
                if tick_time >= order.activation_time:
                    # Execute and discard remainder (Fill-or-Kill)
                    self._execute_market_order(order, tick_event, tick_time)
                else:
                    # Latency hasn't passed, hold for next tick
                    surviving_markets.append(order) 
            self.pending_markets[symbol] = surviving_markets

        # --- GATE 2: Process Limit Orders ---
        if symbol in self.pending_limits:
            ohlc = tick_event["ohlc"]
            tick_vol = tick_event["volume"]
            max_fill_allowance = int(tick_vol * self.volume_cap)
            
            surviving_limits = []

            for order in self.pending_limits[symbol]:
                # Latency check
                if tick_time < order.activation_time:
                    surviving_limits.append(order)
                    continue

                if max_fill_allowance <= 0:
                    surviving_limits.append(order)
                    continue

                filled_this_tick = 0
                fill_price = 0.0

                # Pessimistic Fill Rule uses strictly < and >
                if order.side == "BUY" and ohlc["low"] < order.price:
                    fill_price = min(order.price, ohlc["open"]) 
                    filled_this_tick = min(order.quantity, max_fill_allowance)

                elif order.side == "SELL" and ohlc["high"] > order.price:
                    fill_price = max(order.price, ohlc["open"]) 
                    filled_this_tick = min(order.quantity, max_fill_allowance)

                # Gate 3: State Persistence & Partial Fills
                if filled_this_tick > 0:
                    # Note: Adjust .append() to .publish() or .put() if your EventBus class requires it
                    self.event_bus.append(FillEvent(
                        order_id=order.order_id,
                        timestamp=tick_time,
                        symbol=order.symbol,
                        side=order.side,
                        quantity=filled_this_tick,
                        price=fill_price,
                    ))

                    order.quantity -= filled_this_tick
                    max_fill_allowance -= filled_this_tick

                if order.quantity > 0:
                    surviving_limits.append(order)

            self.pending_limits[symbol] = surviving_limits


    def _execute_market_order(self, order: Any, tick: TickEvent, tick_time: datetime) -> None:
        """
        Executes a MARKET order using L2 Depth and Synthetic Extrapolation.
        Strictly caps total execution at 5% of tick volume.
        Any remaining quantity is intentionally rejected (discarded).
        """
        book_side = "sell" if order.side == "BUY" else "buy"
        visible_levels = tick.get("depth", {}).get(book_side, [])

        # The absolute hard limit this order is allowed to consume
        max_allowable_qty = int(tick["volume"] * self.volume_cap)

        remaining_qty = order.quantity 
        filled_this_tick = 0
        total_cost = 0.0

        # Phase 1: Walk the visible book
        for level in visible_levels:
            if remaining_qty <= 0 or filled_this_tick >= max_allowable_qty:
                break
            
            # Constrain the fill by what's remaining, what's available, AND what's allowed by the cap
            qty_to_take = min(remaining_qty, level["quantity"], max_allowable_qty - filled_this_tick)
            total_cost += qty_to_take * level["price"]
            
            remaining_qty -= qty_to_take
            filled_this_tick += qty_to_take

        # Phase 2: Synthetic Depth Extrapolation (Capped)
        if remaining_qty > 0 and filled_this_tick < max_allowable_qty:
            if not visible_levels:
                # Absolute fallback if depth is entirely empty 
                penalty_price = tick["ohlc"]["high"] if order.side == "BUY" else tick["ohlc"]["low"]
                qty_to_take = min(remaining_qty, max_allowable_qty - filled_this_tick)
                
                total_cost += qty_to_take * penalty_price
                remaining_qty -= qty_to_take
                filled_this_tick += qty_to_take
            else:
                avg_qty_per_level = max(1, sum(lvl["quantity"] for lvl in visible_levels) // len(visible_levels))

                if len(visible_levels) > 1:
                    avg_spread = abs(visible_levels[-1]["price"] - visible_levels[0]["price"]) / (len(visible_levels) - 1)
                else:
                    avg_spread = 0.05  # NSE minimum tick size fallback

                last_price = visible_levels[-1]["price"]
                direction_multiplier = 1 if order.side == "BUY" else -1

                # Loop continues only while we haven't hit the volume cap
                while remaining_qty > 0 and filled_this_tick < max_allowable_qty:
                    last_price += avg_spread * direction_multiplier
                    
                    qty_to_take = min(remaining_qty, avg_qty_per_level, max_allowable_qty - filled_this_tick)
                    total_cost += qty_to_take * last_price
                    
                    remaining_qty -= qty_to_take
                    filled_this_tick += qty_to_take

        # Phase 3: Emit FillEvent
        # Only emit if we actually filled shares. 
        # Leftover remaining_qty is discarded automatically when the function ends.
        if filled_this_tick > 0:
            final_vwap = round(total_cost / filled_this_tick, 2)
            
            # Note: Adjust .append() to .publish() or .put() if your EventBus class requires it
            self.event_bus.append(FillEvent(
                order_id=order.order_id,
                timestamp=tick_time + self.latency,
                symbol=order.symbol,
                side=order.side,
                quantity=filled_this_tick,
                price=final_vwap,
            ))
