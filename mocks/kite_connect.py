"""
MockREST API (margins, place_order, positions).
"""
import uuid 
from datetime import datetime
from typing import Dict, Any, List

from engine.event_bus import EventBus
from engine.matching_engine import OrderEvent 

class MockKiteConnect:
    """
    Possesses the exact method signatures as the official KiteConnect class.
    When called, creates OrderEvents and drops them into the event_bus.
    """
    # Variety
    VARIETY_REGULAR = "regular"
    VARIETY_AMO     = "amo"
    VARIETY_CO      = "co"
    VARIETY_ICEBERG = "iceberg"
    VARIETY_AUCTION = "auction"
 
    # Exchange
    EXCHANGE_NSE = "NSE"
    EXCHANGE_BSE = "BSE"
    EXCHANGE_NFO = "NFO"
    EXCHANGE_CDS = "CDS"
    EXCHANGE_BFO = "BFO"
    EXCHANGE_MCX = "MCX"
    EXCHANGE_BCD = "BCD"
 
    # Transaction type
    TRANSACTION_TYPE_BUY  = "BUY"
    TRANSACTION_TYPE_SELL = "SELL"
 
    # Product
    PRODUCT_MIS  = "MIS"
    PRODUCT_CNC  = "CNC"
    PRODUCT_NRML = "NRML"
    PRODUCT_CO   = "CO"
 
    # Order type
    ORDER_TYPE_MARKET = "MARKET"
    ORDER_TYPE_LIMIT  = "LIMIT"
    ORDER_TYPE_SL     = "SL"
    ORDER_TYPE_SLM    = "SL-M"
 
    # Validity
    VALIDITY_DAY = "DAY"
    VALIDITY_IOC = "IOC"
    VALIDITY_TTL = "TTL"
 
    # Position type
    POSITION_TYPE_DAY = "day"
    POSITION_TYPE_OVERNIGHT = "overnight"
 
    # Margins segment
    MARGIN_EQUITY    = "equity"
    MARGIN_COMMODITY = "commodity"

    def __init__(self, api_key: str, event_bus: EventBus, portfolio: Any, access_token: str = None):
        """
        Initializes the Mock KiteConnect.
        """
        self.api_key      = api_key
        self.access_token = access_token
        self.event_bus    = event_bus
        self.portfolio    = portfolio
        self._order_book: Dict[str, Dict[str, Any]] = {}
        
        # Added to maintain historical simulation time
        self._sim_time: datetime = None
    
    def set_access_token(self, access_token: str) -> None:
        self.access_token = access_token

    def sync_time(self, current_time: datetime) -> None:
        """
        Keeps the mock API synchronized with the simulator's historical clock.
        Must be called by the simulator tick loop.
        """
        self._sim_time = current_time

    def _get_current_time(self) -> datetime:
        return self._sim_time if self._sim_time else datetime.utcnow()
    
    # --- ORDER MANAGEMENT ---

    def place_order(self, variety: str, exchange: str, tradingsymbol: str, 
                    transaction_type: str, quantity: int, product: str, 
                    order_type: str, price: float = None, validity: str = None, 
                    disclosed_quantity: int = None, trigger_price: float = None, 
                    squareoff: float = None, stoploss: float = None, 
                    trailing_stoploss: float = None, tag: str = None) -> str:
        """
        Mocks placing an order. Queues an OrderEvent.
        """
        order_id = f"MOCK{uuid.uuid4().hex[:11].upper()}"
        
        # 1. Store the rich metadata in the internal dictionary
        order_dict = {
            "order_id":           order_id,
            "timestamp":          self._get_current_time(),
            "variety":            variety,
            "exchange":           exchange,
            "tradingsymbol":      tradingsymbol,
            "transaction_type":   transaction_type.upper(),
            "quantity":           quantity,
            "product":            product.upper(),
            "order_type":         order_type.upper(),
            "price":              float(price) if price else 0.0,
            "validity":           validity or self.VALIDITY_DAY,
            "disclosed_quantity": disclosed_quantity or 0,
            "trigger_price":      float(trigger_price) if trigger_price else 0.0,
            "squareoff":          squareoff,
            "stoploss":           stoploss,
            "trailing_stoploss":  trailing_stoploss,
            "tag":                tag,
            "status":             "OPEN",
            "filled_quantity":    0,
            "pending_quantity":   quantity,
            "average_price":      0.0,
        }
        self._order_book[order_id] = order_dict 

        # 2. Construct the exact OrderEvent object expected by simulator.py
        order_event = OrderEvent(
            order_id=order_id,
            timestamp=order_dict["timestamp"],
            symbol=tradingsymbol,
            side=transaction_type.upper(),
            order_type=order_type.upper(),
            quantity=quantity,
            price=order_dict["price"]
        )
        
        # 3. Attach the rich dictionary to avoid Data Loss
        order_event.meta = order_dict 
        order_event.action = "NEW" 
        
        # 4. Push onto the EventBus
        self.event_bus.publish(order_event)
        
        return order_id
    
    def modify_order(self, variety: str, order_id: str,
                    parent_order_id: str = None, exchange: str = None,
                    tradingsymbol: str = None, transaction_type: str = None,
                    quantity: int = None, price: float = None,
                    order_type: str = None, trigger_price: float = None,
                    validity: str = None,
                    disclosed_quantity: int = None) -> str:
        
        if order_id in self._order_book:
            orig_order = self._order_book[order_id]
            
            # Update local book
            if quantity is not None:
                orig_order["quantity"] = quantity
                orig_order["pending_quantity"] = max(0, quantity - orig_order.get("filled_quantity", 0))
            if price is not None:
                orig_order["price"] = float(price)

            # Publish the modification to the matching engine
            modify_event = OrderEvent(
                order_id=order_id,
                timestamp=self._get_current_time(),
                symbol=orig_order["tradingsymbol"],
                side=orig_order["transaction_type"],
                order_type=orig_order["order_type"],
                quantity=orig_order["quantity"],
                price=orig_order["price"]
            )
            modify_event.meta = orig_order
            modify_event.action = "MODIFY"
            
            self.event_bus.publish(modify_event)
            
        return order_id
    
    def cancel_order(self, variety: str, order_id: str,
                    parent_order_id: str = None) -> str:
        
        if order_id in self._order_book:
            orig_order = self._order_book[order_id]
            orig_order["status"] = "CANCELLED"
            orig_order["pending_quantity"] = 0
            
            # Publish the cancellation to the matching engine
            cancel_event = OrderEvent(
                order_id=order_id,
                timestamp=self._get_current_time(),
                symbol=orig_order["tradingsymbol"],
                side=orig_order["transaction_type"],
                order_type=orig_order["order_type"],
                quantity=0,
                price=0.0
            )
            cancel_event.meta = orig_order
            cancel_event.action = "CANCEL"
            
            self.event_bus.publish(cancel_event)
            
        return order_id
    
    def orders(self) -> List[Dict[str, Any]]:
        result = []
        for order_id, ev in self._order_book.items():
            result.append(ev)
        return result

    def update_order_status(self, order_id: str, status: str,
                        fill_price: float = None,
                        filled_qty: int = None) -> None:
        if order_id in self._order_book:
            self._order_book[order_id]["status"] = status
            if fill_price is not None:
                self._order_book[order_id]["average_price"] = fill_price
            if filled_qty is not None:
                self._order_book[order_id]["filled_quantity"] = filled_qty
                original_qty = self._order_book[order_id].get("quantity", 0)
                self._order_book[order_id]["pending_quantity"] = max(
                    0, original_qty - filled_qty
                )

    # --- PORTFOLIO QUERIES ---

    def margins(self) -> Dict[str, Any]:
        cash_balance    = getattr(self.portfolio, "available_cash",  0.0)
        opening_balance = getattr(self.portfolio, "initial_capital", cash_balance)
 
        return {
            "equity": {
                "enabled": True,
                "net": cash_balance,
                "available": {
                    "ad_hoc_margin":   0.0,
                    "cash":            cash_balance,
                    "collateral":      0.0,
                    "intraday_payin":  0.0,
                    "live_balance":    cash_balance,
                    "opening_balance": opening_balance,
                },
                "utilised": {
                    "debits":           0.0,
                    "exposure":         0.0,
                    "m2m_realised":     0.0,
                    "m2m_unrealised":   0.0,
                    "option_premium":   0.0,
                    "payout":           0.0,
                    "span":             0.0,
                    "holding_sales":    0.0,
                    "turnover":         0.0,
                    "liquid_bees_margin": 0.0,
                    "delivery_margin":  0.0,
                },
            },
            "commodity": {
                "enabled": False,
                "net": 0.0,
            },
        }
    
    def positions(self) -> Dict[str, Any]:
        formatted_positions = []
        positions_dict = getattr(self.portfolio, "positions", {})
 
        for symbol, pos_data in positions_dict.items():
            qty = pos_data.get("quantity", 0)
            if qty == 0:
                continue
 
            avg_price  = pos_data.get("average_price", 0.0)
            last_price = pos_data.get("current_price", avg_price)
            product    = pos_data.get("product", "MIS")
            exchange   = pos_data.get("exchange", "NSE")
            pnl        = (last_price - avg_price) * qty
 
            formatted_positions.append({
                "tradingsymbol":      symbol,
                "exchange":           exchange,
                "instrument_token":   pos_data.get("instrument_token", 0),
                "product":            product,
                "quantity":           qty,
                "overnight_quantity": 0,
                "multiplier":         1,
                "average_price":      avg_price,
                "close_price":        0.0,
                "last_price":         last_price,
                "value":              qty * last_price,
                "pnl":                pnl,
                "m2m":                pnl,
                "realised":           0.0,
                "unrealised":         pnl,
                "buy_quantity":       qty       if qty > 0 else 0,
                "buy_price":          avg_price if qty > 0 else 0.0,
                "buy_value":          (qty * avg_price) if qty > 0 else 0.0,
                "sell_quantity":      abs(qty)       if qty < 0 else 0,
                "sell_price":         avg_price      if qty < 0 else 0.0,
                "sell_value":         (abs(qty) * avg_price) if qty < 0 else 0.0,
                "day_buy_quantity":   qty       if qty > 0 else 0,
                "day_buy_price":      avg_price if qty > 0 else 0.0,
                "day_buy_value":      (qty * avg_price) if qty > 0 else 0.0,
                "day_sell_quantity":  abs(qty)       if qty < 0 else 0,
                "day_sell_price":     avg_price      if qty < 0 else 0.0,
                "day_sell_value":     (abs(qty) * avg_price) if qty < 0 else 0.0,
            })
 
        return {
            "net": formatted_positions,
            "day": formatted_positions,
        }
    
    def holdings(self) -> List[Dict[str, Any]]:
        return []
    
    def ltp(self, *instruments) -> Dict[str, Any]:
        result = {}
        positions_dict = getattr(self.portfolio, "positions", {})
 
        for instrument in instruments:
            if ":" in instrument:
                _, symbol = instrument.split(":", 1)
            else:
                symbol = instrument
 
            pos        = positions_dict.get(symbol, {})
            last_price = pos.get("current_price", 0.0)
            token      = pos.get("instrument_token", 0)
 
            result[instrument] = {
                "instrument_token": token,
                "last_price":       last_price,
            }
        return result
    
    def quote(self, *instruments) -> Dict[str, Any]:
        result = {}
        positions_dict = getattr(self.portfolio, "positions", {})
 
        for instrument in instruments:
            if ":" in instrument:
                _, symbol = instrument.split(":", 1)
            else:
                symbol = instrument
 
            pos        = positions_dict.get(symbol, {})
            last_price = pos.get("current_price", 0.0)
            token      = pos.get("instrument_token", 0)
 
            result[instrument] = {
                "instrument_token": token,
                "timestamp":        "",
                "last_trade_time":  "",
                "last_price":       last_price,
                "last_quantity":    0,
                "buy_quantity":     0,
                "sell_quantity":    0,
                "volume":           0,
                "average_price":    last_price,
                "oi":               0,
                "oi_day_high":      0,
                "oi_day_low":       0,
                "net_change":       0.0,
                "lower_circuit_limit": 0.0,
                "upper_circuit_limit": 0.0,
                "ohlc": {
                    "open":  last_price,
                    "high":  last_price,
                    "low":   last_price,
                    "close": last_price,
                },
                "depth": {
                    "buy":  [{"price": 0.0, "quantity": 0, "orders": 0}] * 5,
                    "sell": [{"price": 0.0, "quantity": 0, "orders": 0}] * 5,
                },
            }
 
        return result