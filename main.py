"""
The deployment runner (toggles LIVE vs BACKTEST).

This file's only job is wiring: construct one instance of every component,
in dependency order, connect the callback references between them, and
start the simulator. No business logic should live here.

Dependency order (each step only needs things built in earlier steps):
    1. EventBus            - needed by almost everything
    2. TickGenerator       - needs the data directory
    3. MatchingEngine      - needs event_bus
    4. TransactionLogger   - optional, standalone (no dependencies)
    5. TaxDividendAPI      - optional, standalone (no dependencies)
    6. Portfolio           - needs event_bus, optionally logger + tax_api
    7. MockKiteConnect     - needs event_bus
    8. MockKiteTicker      - standalone
    9. Strategy            - needs the two mocks
   10. Wire mock_ticker's callbacks to the strategy's methods
   11. Simulator           - needs everything above
   12. simulator.run(...)
"""

from engine.event_bus import EventBus
from engine.matching_engine import MatchingEngine
from engine.portfolio import Portfolio
from engine.simulator import Simulator

from data.tick_generator import TickGenerator

from mocks.kite_connect import MockKiteConnect
from mocks.kite_ticker import MockKiteTicker

from strategies.example_strategy import ExampleStrategy

from metrics.transaction_logger import TransactionLogger
from metrics.performance import PerformanceAnalyzer

from settlement.tax_dividend_api import TaxDividendAPI


MODE = "BACKTEST"

SYMBOL = "RELIANCE"
START_DATE = "2023-01-01"
END_DATE = "2023-12-31"

INITIAL_CAPITAL = 100000.0

DATA_DIR = "data_cache/"

TRADE_LOG_PATH = "trades_journal.csv"


def main(
    mode: str,
    symbol: str,
    start_date: str,
    end_date: str,
    initial_capital: float,
    data_dir: str,
    trade_log_path: str,
    enable_logger: bool = True,
    enable_tax_api: bool = True,
) -> None:
    """
    Main entry point. Instantiates the environment (Live or Backtest) based
    on arguments/config, wires up all the components, and starts execution.

    Args:
        mode (str): "BACKTEST" or "LIVE". Only BACKTEST is wired up here;
            LIVE would swap MockKiteConnect/MockKiteTicker for the real
            kiteconnect SDK objects, leaving everything else identical.
        symbol (str): Trading symbol to run the simulation on.
        start_date (str): Start of the historical data window.
        end_date (str): End of the historical data window.
        initial_capital (float): Starting cash for the Portfolio.
        data_dir (str): Directory containing cached Parquet files.
        trade_log_path (str): Where TransactionLogger writes fills.
        enable_logger (bool): If False, Portfolio runs with logger=None.
        enable_tax_api (bool): If False, Portfolio runs with tax_api=None
            and settlement/tax adjustments are skipped entirely.
    """
    if mode != "BACKTEST":
        raise NotImplementedError(
            "LIVE mode wiring (real KiteConnect/KiteTicker) is not yet implemented."
        )

    # 1. Shared event bus
    event_bus = EventBus()

    # 2. Data source
    tick_generator = TickGenerator(data_dir=data_dir)

    # 3. Matching engine
    matching_engine = MatchingEngine(event_bus=event_bus)

    # 4 & 5. Optional collaborators for Portfolio (Dependency Injection —
    # both can be swapped for None to detach logging/tax behavior).
    logger = TransactionLogger(log_filepath=trade_log_path) if enable_logger else None
    tax_api = TaxDividendAPI() if enable_tax_api else None

    # 6. Portfolio (the ledger)
    portfolio = Portfolio(
        event_bus=event_bus,
        initial_capital=initial_capital,
        logger=logger,
        tax_api=tax_api,
    )

    # 7 & 8. Mock broker layer
    mock_kite = MockKiteConnect(api_key="mock_api_key", event_bus=event_bus)
    mock_ticker = MockKiteTicker(api_key="mock_api_key")

    # 9. Strategy, injected with the mock REST + WebSocket clients
    strategy = ExampleStrategy(kite_connect=mock_kite, kws=mock_ticker)

    # 10. Wire the ticker's callbacks to the strategy's handler methods,
    # mirroring how a real KiteTicker integration would be set up.
    mock_ticker.on_ticks = strategy.on_ticks
    mock_ticker.on_order_update = strategy.on_order_update

    # 11. Simulator — the conductor that owns the main loop
    simulator = Simulator(
        event_bus=event_bus,
        tick_generator=tick_generator,
        matching_engine=matching_engine,
        portfolio=portfolio,
        strategy=strategy,
    )

    # 12. Run the backtest
    simulator.run(symbol=symbol, start_date=start_date, end_date=end_date)

    # Post-processing: only meaningful if logging was enabled, since the
    # analyzer reads the CSV that the logger produced.
    if logger is not None:
        analyzer = PerformanceAnalyzer(log_filepath=trade_log_path)
        metrics = analyzer.calculate_metrics()
        print("Backtest complete. Performance metrics:")
        for key, value in metrics.items():
            print(f"  {key}: {value}")
    else:
        print("Backtest complete. Logging was disabled, so no performance report was generated.")


if __name__ == "__main__":
    main(MODE, SYMBOL, START_DATE, END_DATE, INITIAL_CAPITAL, DATA_DIR, TRADE_LOG_PATH)
