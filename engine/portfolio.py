"""
The active ledger tracking Cash, Margin, and Positions.

Design notes (decisions made during planning):
- `available_cash` is a single shared number across all symbols.
- `positions` is a dict keyed by symbol, where each value is a FIFO deque of
  individual lots: {"quantity": int, "price": float, "timestamp": str}.
  Lots (not blended averages) are required because settlement must match
  exits to entries on a strict First-In-First-Out basis.
- `logger` (TransactionLogger) and `tax_api` (TaxDividendAPI) are OPTIONAL,
  injected dependencies (Dependency Injection), not constructed internally.
  This keeps Portfolio detachable/testable: pass None to disable either.
- Deliberately did NOT assume rich OrderEvent/FillEvent/TickEvent classes.
  Only relied on a minimal set of attributes via getattr(), since those
  classes are owned by other contributors and may evolve independently.

Minimal assumed shape of a FillEvent (read via getattr, all but symbol/side/
quantity/price are optional with safe defaults):
    order_id   (str)   - optional, used only for logging context
    symbol     (str)   - required
    side       (str)   - required, "BUY" or "SELL"
    quantity   (int)   - required
    price      (float) - required, actual execution price
    timestamp  (str)   - optional, defaults to "" if missing
    fees       (float) - optional, defaults to 0.0

Minimal assumed shape of a TickEvent (read via getattr):
    symbol      (str)   - required
    last_price  (float) - required (falls back to .close if present)
    timestamp   (str)   - optional

Minimal assumed shape of what `tax_api.calculate_settlement(...)` returns:
    a dict containing at least "net_adjustment" (float) - everything else
    (stt, brokerage, exchange_fees, etc.) is optional and only used for
    logging detail if present.
"""

from collections import deque
from engine.event_bus import EventBus
from data.tick_generator import TickEvent
from typing import Any, Dict, Optional, List
from settlement.tax_dividend_api import TaxDividendAPI
from metrics.transaction_logger import TransactionLogger


class Portfolio:
    """
    Maintains available_cash and a per-symbol FIFO lot ledger.
    Marks positions to market on every tick.

    `logger` and `tax_api` are optional collaborators (Dependency Injection).
    Pass None for either to disable that behavior without changing this
    class's internals.
    """

    def __init__(
        self,
        event_bus: EventBus,
        initial_capital: float,
        logger: Optional[TransactionLogger] = None,
        tax_api: Optional[TaxDividendAPI] = None,
    ):
        """
        Initializes the Portfolio.

        Args:
            event_bus (EventBus): The centralized event bus. Portfolio itself
                doesn't currently need to publish anything onto it (the
                simulator is responsible for routing FillEvents to us), but
                we keep the reference for symmetry with other modules and
                in case future settlement events need to be published.
            initial_capital (float): The starting cash balance.
            logger (Optional[TransactionLogger]): Object exposing `log_event(event)`.
                If None, logging is silently skipped.
            tax_api (Optional[TaxDividendAPI]): Object exposing
                `calculate_settlement(entry_date, entry_price, exit_date,
                exit_price, qty) -> dict`. If None, settlement is skipped
                and the raw fill price difference stands as-is (no tax/fees
                applied).
        """
        self.event_bus: EventBus = event_bus
        self.available_cash: float = initial_capital
        self.initial_capital: float = initial_capital

        # symbol -> deque of lots, each lot: {"quantity", "price", "timestamp"}
        self.positions: Dict[str, deque] = {}

        # symbol -> last known unrealized P&L (recomputed on every mark_to_market)
        self.unrealized_pnl: Dict[str, float] = {}

        # symbol -> last seen market price (used by mark_to_market / equity calc)
        self._last_price: Dict[str, float] = {}

        self.logger = logger
        self.tax_api = tax_api

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _net_quantity(self, symbol: str) -> int:
        """Returns the current net open quantity held for a symbol (sum of lots)."""
        lots = self.positions.get(symbol)
        if not lots:
            return 0
        return sum(lot["quantity"] for lot in lots)

    def _log(self, event: Any) -> None:
        """Safely logs an event if a logger was injected. No-op otherwise."""
        if self.logger is not None:
            self.logger.log_event(event)

    # ------------------------------------------------------------------
    # Pre-fill validation (used by MatchingEngine before finalizing a fill)
    # ------------------------------------------------------------------

    def can_afford(self, cost: float) -> bool:
        """
        Checks whether the portfolio currently has enough cash to cover a
        prospective buy. MatchingEngine should call this BEFORE creating a
        FillEvent for a BUY order, so insufficient-funds orders can be
        rejected/partially-filled rather than silently overdrawing cash.

        Args:
            cost (float): The total cost of the prospective trade
                (quantity * price), or quantity * price + estimated fees.

        Returns:
            bool: True if available_cash >= cost.
        """
        return self.available_cash >= cost

    # ------------------------------------------------------------------
    # Core transaction handling
    # ------------------------------------------------------------------

    def update_from_fill(self, fill_event: Any) -> None:
        """
        Updates positions and cash based on a newly filled order.
        If a position is closed (net quantity returns to zero), triggers
        the settlement process via the optional tax_api, then finalizes
        the ledger via adjust_cash.

        This is the ONLY place transactions are recorded — whether they
        originate purely from a fill, or are later adjusted by tax/fees,
        everything funnels through this method (and adjust_cash).

        Args:
            fill_event (Any): The fill event indicating an executed trade.
                Must expose: symbol, side, quantity, price.
                Optionally: order_id, timestamp, fees.
        """
        symbol: str = fill_event.symbol
        side: str = fill_event.side
        quantity: int = fill_event.quantity
        price: float = fill_event.price
        timestamp: str = getattr(fill_event, "timestamp", "")
        fees: float = getattr(fill_event, "fees", 0.0)

        if symbol not in self.positions:
            self.positions[symbol] = deque()

        lots = self.positions[symbol]

        if side.upper() == "BUY":
            # Cash leaves immediately; a new lot is appended (FIFO order
            # preserved by always appending to the back).
            self.available_cash -= (quantity * price) + fees
            lots.append({
                "quantity": quantity,
                "price": price,
                "timestamp": timestamp,
            })
            self._log(fill_event)

        elif side.upper() == "SELL":
            # Cash arrives immediately for the raw proceeds; lots are
            # consumed FIFO (oldest first), splitting a lot if the sell
            # quantity doesn't exactly match the lot at the front.
            self.available_cash += (quantity * price) - fees

            remaining_to_sell = quantity
            realized_lots: List[Dict[str, Any]] = []

            while remaining_to_sell > 0 and lots:
                front_lot = lots[0]
                if front_lot["quantity"] <= remaining_to_sell:
                    # Consume the entire front lot.
                    realized_lots.append(front_lot)
                    remaining_to_sell -= front_lot["quantity"]
                    lots.popleft()
                else:
                    # Partially consume the front lot; reduce it in place.
                    realized_lots.append({
                        "quantity": remaining_to_sell,
                        "price": front_lot["price"],
                        "timestamp": front_lot["timestamp"],
                    })
                    front_lot["quantity"] -= remaining_to_sell
                    remaining_to_sell = 0

            self._log(fill_event)

            # run settlement for each matched FIFO lot (entry) against this exit.
            if realized_lots: # self._net_quantity(symbol) == 0 and realized_lots
                self._settle_realized_lots(realized_lots, price, timestamp)

        else:
            raise ValueError(f"Unknown fill side: {side!r}")

    def _settle_realized_lots(
        self,
      # symbol: str,
        realized_lots: List[Dict[str, Any]],
        exit_price: float,
        exit_timestamp: str,
    ) -> None:
        """
        Runs settlement (tax/brokerage/fees) for each FIFO-matched entry lot
        against the exit price, applying the net adjustment to cash.

        If `tax_api` was not provided, this is a no-op — the raw price
        difference already booked via cash flow in update_from_fill stands
        as the final number (no tax/fee adjustment applied).

        Args:
            symbol (str): The symbol whose position just closed.
            realized_lots (List[Dict]): The individual entry lots consumed
                to fulfill this exit, in FIFO order.
            exit_price (float): The price the closing fill executed at.
            exit_timestamp (str): The timestamp of the closing fill.
        """
        if self.tax_api is None:
            return

        for lot in realized_lots:
            result = self.tax_api.calculate_settlement(
                entry_date=lot["timestamp"],
                entry_price=lot["price"],
                exit_date=exit_timestamp,
                exit_price=exit_price,
                qty=lot["quantity"],
            )
            net_adjustment = result.get("net_adjustment", 0.0)
            self.adjust_cash(net_adjustment)

    # ------------------------------------------------------------------
    # Mark-to-market
    # ------------------------------------------------------------------

    def mark_to_market(self, tick_event: TickEvent) -> None:
        """
        Updates the current market value of open positions based on the
        latest tick, for the symbol that tick belongs to. Only affects
        that one symbol's unrealized P&L — every other symbol's state is
        untouched.

        Args:
            tick_event (TickEvent): The incoming tick event. Must expose `symbol`
                and a price field (`last_price`, falling back to `close`).
        """
        symbol = tick_event.symbol
        price = getattr(tick_event, "last_price", None)
        if price is None:
            price = getattr(tick_event, "close", None)
        if price is None:
            return  # Nothing usable to mark against.

        self._last_price[symbol] = price

        lots = self.positions.get(symbol)
        if not lots:
            self.unrealized_pnl[symbol] = 0.0
            return

        cost_basis = sum(lot["quantity"] * lot["price"] for lot in lots)
        held_qty = sum(lot["quantity"] for lot in lots)
        market_value = held_qty * price
        self.unrealized_pnl[symbol] = market_value - cost_basis

    # ------------------------------------------------------------------
    # Generic cash adjustment (used by settlement, and available externally)
    # ------------------------------------------------------------------

    def adjust_cash(self, amount: float) -> None:
        """
        Adjusts the available cash in the portfolio (e.g. for taxes,
        dividends, or fees). Positive credits, negative debits.

        Args:
            amount (float): The amount to adjust.
        """
        self.available_cash += amount

    # ------------------------------------------------------------------
    # Convenience read-only views (useful for mocks/kite_connect.py later)
    # ------------------------------------------------------------------

    def get_equity(self) -> float:
        """Returns total equity: cash + unrealized P&L across all symbols."""
        return self.available_cash + sum(self.unrealized_pnl.values())

    def get_position_snapshot(self, symbol: str) -> List[Dict[str, Any]]:
        """Returns a plain list copy of the current lots held for a symbol."""
        lots = self.positions.get(symbol)
        return list(lots) if lots else []