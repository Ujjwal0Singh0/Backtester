"""
The active ledger tracking Cash, Margin, and Positions.

REVISED to match the now-finalized mocks/kite_connect.py and
metrics/transaction_logger.py:

- Events (OrderEvent/FillEvent) are plain dicts with Kite-style keys:
  "tradingsymbol" (not "symbol"), "transaction_type" (not "side"),
  "quantity", "price", "order_id", "fees" (optional), "timestamp" (optional).
  This mirrors exactly what MockKiteConnect.place_order() builds, and what
  TransactionLogger.log_event() already expects (it falls back between
  "symbol"/"tradingsymbol" and "side"/"transaction_type").

- kite_connect.positions()/ltp()/quote() all read self.portfolio.positions
  as: {symbol: {"quantity", "average_price", "current_price", "product",
  "exchange", "instrument_token"}} — ONE FLAT DICT per symbol, not a list
  of lots. Since kite_connect.py is already finalized and reads this shape
  directly, `self.positions` MUST stay in this flat/aggregated form.

  FIFO lot-level detail (needed for correct settlement matching) is instead
  kept privately in `self._lots`, and is never read by kite_connect.

- `logger` and `tax_api` remain optional, injected (Dependency Injection),
  defaulting to None so either can be detached without touching this
  class's internals.
"""

from collections import deque
from engine.event_bus import EventBus
from data.tick_generator import TickEvent
from typing import Any, Dict, Optional, List
from settlement.tax_dividend_api import TaxDividendAPI
from metrics.transaction_logger import TransactionLogger


def _sign(value: float) -> int:
    """Returns +1, -1, or 0 for the sign of a numeric value."""
    if value > 0:
        return 1
    if value < 0:
        return -1
    return 0


def _get(event: Any, *keys: str, default: Any = None) -> Any:
    """
    Reads a field off an event that may be a dict OR an object, trying
    each candidate key/attribute name in order. This insulates Portfolio
    from minor naming differences across event producers (e.g. "quantity"
    vs "filled_quantity"), matching the same defensive style already used
    in transaction_logger.py.
    """
    for key in keys:
        if isinstance(event, dict):
            if key in event and event[key] is not None:
                return event[key]
        else:
            value = getattr(event, key, None)
            if value is not None:
                return value
    return default


class Portfolio:
    """
    Maintains available_cash and a per-symbol position ledger.

    `positions` (flat, aggregated) is the PUBLIC shape kite_connect.py
    reads from directly — do not change its structure without checking
    kite_connect.py's margins()/positions()/ltp()/quote() implementations.

    `_lots` (FIFO deques) is PRIVATE — used only internally for correct
    FIFO settlement matching. Nothing outside Portfolio should read it.
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
            event_bus (EventBus): The centralized event bus (kept for symmetry
                with other modules; Portfolio doesn't currently publish).
            initial_capital (float): The starting cash balance.
            logger (Optional[TransactionLogger]): Object exposing `log_event(event)`.
                If None, logging is silently skipped.
            tax_api (Optional[TaxDividendAPI]): Object exposing
                `calculate_settlement(entry_date, entry_price, exit_date,
                exit_price, qty) -> dict` (must contain "net_adjustment").
                If None, settlement is skipped — raw fill price stands.
        """
        self.event_bus = event_bus
        self.available_cash: float = initial_capital
        self.initial_capital: float = initial_capital

        # PUBLIC flat view — this exact shape is read directly by
        # mocks/kite_connect.py's positions()/ltp()/quote().
        # symbol -> {"quantity", "average_price", "current_price",
        #            "product", "exchange", "instrument_token"}
        self.positions: Dict[str, Dict[str, Any]] = {}

        # PRIVATE FIFO detail — symbol -> deque of lots:
        # {"quantity", "price", "timestamp"}
        self._lots: Dict[str, deque] = {}

        self.logger = logger
        self.tax_api = tax_api

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _log(self, event: Any) -> None:
        """Safely logs an event if a logger was injected. No-op otherwise."""
        if self.logger is not None:
            self.logger.log_event(event)

    def _ensure_position_entry(self, symbol: str) -> None:
        """Creates an empty flat position entry for a symbol if absent."""
        if symbol not in self.positions:
            self.positions[symbol] = {
                "quantity": 0,
                "average_price": 0.0,
                "current_price": 0.0,
                "product": "MIS",
                "exchange": "NSE",
                "instrument_token": 0,
            }
        if symbol not in self._lots:
            self._lots[symbol] = deque()

    # ------------------------------------------------------------------
    # Pre-fill validation (used by MatchingEngine before finalizing a fill)
    # ------------------------------------------------------------------

    def can_afford(self, cost: float) -> bool:
        """
        Checks whether the portfolio currently has enough cash to cover a
        prospective buy. MatchingEngine should call this BEFORE finalizing
        a BUY fill, so insufficient-funds orders can be rejected/partially
        filled rather than silently overdrawing cash.
        """
        return self.available_cash >= cost

    # ------------------------------------------------------------------
    # Core transaction handling
    # ------------------------------------------------------------------

    def update_from_fill(self, fill_event: Any) -> None:
        """
        Updates positions and cash based on a newly filled order.
        If a position is closed (net quantity returns to zero), triggers
        settlement via the optional tax_api, then finalizes via adjust_cash.

        Reads fields defensively (dict or object), using the same key
        fallbacks as TransactionLogger: "tradingsymbol"/"symbol",
        "transaction_type"/"side", "quantity", "price", optionally
        "fees", "timestamp", "product", "exchange", "instrument_token".
        """
        symbol = _get(fill_event, "tradingsymbol", "symbol")
        side = _get(fill_event, "transaction_type", "side")
        quantity = _get(fill_event, "quantity", default=0)
        price = _get(fill_event, "price", default=0.0)
        timestamp = _get(fill_event, "timestamp", default="")
        fees = _get(fill_event, "fees", default=0.0)
        product = _get(fill_event, "product", default="MIS")
        exchange = _get(fill_event, "exchange", default="NSE")
        instrument_token = _get(fill_event, "instrument_token", default=0)

        if symbol is None or side is None:
            raise ValueError(
                "FillEvent missing required symbol/side fields "
                f"(got tradingsymbol/symbol={symbol}, "
                f"transaction_type/side={side})"
            )

        self._ensure_position_entry(symbol)
        side = side.upper()
        lots = self._lots[symbol]

        if side == "BUY":
            self.available_cash -= (quantity * price) + fees
            # direction = +1 (opening long). Close phase covers any existing
            # SHORT lots (negative quantity) first, FIFO; open phase appends
            # whatever's left as a new long lot.
            realized_lots = self._apply_fifo(
                lots, quantity, price, timestamp,
                closing_lot_sign=-1, opening_sign=+1,
            )
            self._recompute_flat_position(symbol, product, exchange, instrument_token, price)
            self._log(fill_event)

        elif side == "SELL":
            self.available_cash += (quantity * price) - fees
            # direction = -1 (opening short). Close phase consumes any
            # existing LONG lots (positive quantity) first, FIFO; open phase
            # appends whatever's left as a new SHORT lot (negative qty) 
            realized_lots = self._apply_fifo(
                lots, quantity, price, timestamp,
                closing_lot_sign=+1, opening_sign=-1,
            )
            self._recompute_flat_position(symbol, product, exchange, instrument_token, price)
            self._log(fill_event)

        else:
            raise ValueError(f"Unknown fill side: {side!r}")

        # Settle every realized (closed) lot as its own round trip — entry
        # is the lot being closed, exit is this fill. This fires whenever
        # ANY closing happened, not only when the position returns to
        # exactly flat, so partial closes/covers are settled correctly too.
        #
        # `trade_side` tells tax_api which direction this round trip was:
        # - BUY closing short lots  -> "SHORT" (entry=original short sell,
        #   exit=this covering buy; profit = entry_price - exit_price)
        # - SELL closing long lots  -> "LONG"  (entry=original buy,
        #   exit=this sell; profit = exit_price - entry_price)
        # Without this, a generic (exit - entry) formula silently reports
        # a profitable short as a loss, since the raw numbers alone don't
        # say which direction the trade was.

        trade_side = "SHORT" if side == "BUY" else "LONG"
        if realized_lots:
            self._settle_realized_lots(realized_lots, price, timestamp, trade_side)

    @staticmethod
    def _apply_fifo(
        lots: deque,
        quantity: int,
        price: float,
        timestamp: str,
        closing_lot_sign: int,
        opening_sign: int,
    ) -> List[Dict[str, Any]]:
        """
        Generic two-phase FIFO application, symmetric for both directions:

        Phase 1 (close): consume lots at the FRONT of the deque whose
        quantity sign matches `closing_lot_sign`, reducing/removing them,
        until either `quantity` is exhausted or no more closable lots
        remain. Each unit consumed here is a completed round trip and is
        returned for settlement.

        Phase 2 (open): if any of `quantity` remains after phase 1 (no more
        opposite-signed lots to close against), append a NEW lot in the
        `opening_sign` direction for the remainder — this is what makes
        short-selling (and going long again after fully covering a short)
        work, instead of silently discarding leftover quantity.

        Returns:
            List[Dict]: realized lots consumed during the close phase, each
            with a positive "quantity" (magnitude) for settlement purposes.
        """
        remaining = quantity
        realized_lots: List[Dict[str, Any]] = []

        while remaining > 0 and lots and _sign(lots[0]["quantity"]) == closing_lot_sign:
            front_lot = lots[0]
            front_qty_abs = abs(front_lot["quantity"])

            if front_qty_abs <= remaining:
                realized_lots.append({
                    "quantity": front_qty_abs,
                    "price": front_lot["price"],
                    "timestamp": front_lot["timestamp"],
                })
                remaining -= front_qty_abs
                lots.popleft()
            else:
                realized_lots.append({
                    "quantity": remaining,
                    "price": front_lot["price"],
                    "timestamp": front_lot["timestamp"],
                })
                front_lot["quantity"] -= remaining * closing_lot_sign
                remaining = 0

        if remaining > 0:
            # Nothing left to close against — open a new lot in this
            # fill's own direction (long for BUY, short for SELL).
            lots.append({
                "quantity": remaining * opening_sign,
                "price": price,
                "timestamp": timestamp,
            })

        return realized_lots

    def _recompute_flat_position(
        self, symbol: str, product: str, exchange: str, instrument_token: Any,
        fill_price: float,
    ) -> None:
        """
        Rebuilds the PUBLIC flat position entry for a symbol from its
        private FIFO lots, so kite_connect.py's positions()/ltp()/quote()
        always see an up-to-date aggregated view.

        `fill_price` seeds `current_price` at the moment of the fill itself
        (a real, observed price), so margins()/positions()/ltp()/quote()
        never see a stale current_price=0.0 (or an unrelated old value) if
        they're queried in the gap between a fill and the NEXT tick — the
        only other thing that would otherwise update current_price is
        mark_to_market(), which only runs once a new TickEvent arrives.
        Once that next tick does arrive, mark_to_market() simply overwrites
        this with the live tick price as usual — this is purely a sane
        placeholder for the in-between window, not a permanent substitute.
        """
        lots = self._lots[symbol]
        net_qty = sum(lot["quantity"] for lot in lots)

        if net_qty == 0:
            avg_price = 0.0
        else:
            cost_total = sum(lot["quantity"] * lot["price"] for lot in lots)
            avg_price = cost_total / net_qty

        flat = self.positions[symbol]
        flat["quantity"] = net_qty
        flat["average_price"] = avg_price
        flat["current_price"] = fill_price
        flat["product"] = product
        flat["exchange"] = exchange
        flat["instrument_token"] = instrument_token

    def _settle_realized_lots(
        self,
        realized_lots: List[Dict[str, Any]],
        exit_price: float,
        exit_timestamp: str,
        trade_side: str
    ) -> None:
        """
        Runs settlement (tax/brokerage/fees) for each FIFO-matched entry lot
        against the exit price, applying the net adjustment to cash.
        No-op if tax_api was not provided (detached).

        Note: "entry" and "exit" here are relative to direction — for a
        long position, entry=buy/exit=sell as usual; for a covered short,
        entry=the original short sell/exit=this covering buy. The tax_api
        contract doesn't need to know which case it is; it just receives
        an entry price/date and an exit price/date.

        `trade_side` is "LONG" or "SHORT" and is passed through to tax_api
        explicitly, because entry_price/exit_price alone are direction-
        agnostic numbers — without knowing which side the trade was, a
        generic (exit_price - entry_price) profit formula would silently
        compute a profitable SHORT as a loss (and vice versa for a losing
        short reported as a gain). For LONG: profit = exit - entry. For
        SHORT: profit = entry - exit (entry being the original short sell
        price, exit being the covering buy price).

        NOTE: this assumes tax_dividend_api.calculate_settlement() accepts
        a `side` keyword and uses it to pick the correct profit sign. This
        needs to be confirmed with whoever implements that module — if its
        signature doesn't support a side/direction argument yet, it will
        need to be added there too, or this call will need adjusting to
        match whatever contract is actually agreed.
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
                side=trade_side,
            )
            net_adjustment = result.get("net_adjustment", 0.0)
            self.adjust_cash(net_adjustment)

    # ------------------------------------------------------------------
    # Mark-to-market
    # ------------------------------------------------------------------

    def mark_to_market(self, tick_event: TickEvent) -> None:
        """
        Updates current_price for the symbol this tick belongs to, in the
        PUBLIC flat positions view. Reads defensively: "tradingsymbol" or
        "symbol" for the identifier, "last_price" or "close" for price.
        Only affects that one symbol — every other symbol is untouched.
        """
        symbol = _get(tick_event, "tradingsymbol", "symbol")
        price = _get(tick_event, "last_price", "close")
        if symbol is None or price is None:
            return

        self._ensure_position_entry(symbol)
        self.positions[symbol]["current_price"] = price

    # ------------------------------------------------------------------
    # Generic cash adjustment (used by settlement, and available externally)
    # ------------------------------------------------------------------

    def adjust_cash(self, amount: float) -> None:
        """Adjusts available cash (e.g. for taxes, dividends, or fees)."""
        self.available_cash += amount

    # ------------------------------------------------------------------
    # Convenience read-only views
    # ------------------------------------------------------------------

    def get_equity(self) -> float:
        """Returns total equity: cash + unrealized P&L across all symbols."""
        total_unrealized = 0.0
        for symbol, flat in self.positions.items():
            qty = flat["quantity"]
            if qty:
                total_unrealized += (flat["current_price"] - flat["average_price"]) * qty
        return self.available_cash + total_unrealized

    def get_lots_snapshot(self, symbol: str) -> List[Dict[str, Any]]:
        """Returns a plain list copy of the current FIFO lots for a symbol (debug/testing only)."""
        lots = self._lots.get(symbol)
        return list(lots) if lots else []