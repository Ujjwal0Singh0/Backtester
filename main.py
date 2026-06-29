"""
The deployment runner (toggles LIVE vs BACKTEST).

This file's only job is wiring: construct one instance of every component,
in dependency order, connect the callback references between them, and
start the simulator. No business logic should live here.

Dependency order (each step only needs things built in earlier steps):
    0. DataIngestion       - runs ONCE at startup to populate Parquet cache
    1. EventBus            - needed by almost everything
    2. TickGenerator       - needs the data directory
    3. MatchingEngine      - needs event_bus
    4. TransactionLogger   - optional, standalone (no dependencies)
    5. TaxDividendAPI      - optional, standalone (no dependencies)
    6. Portfolio           - needs event_bus, optionally logger + tax_api
    7. MockKiteConnect     - needs event_bus AND portfolio (REQUIRED — see
                             mocks/kite_connect.py's __init__ signature,
                             since margins()/positions() read live values
                             straight off the Portfolio instance)
    8. MockKiteTicker      - standalone
    9. Strategy            - needs the two mocks
   10. Wire mock_ticker's callbacks to the strategy's methods
   11. Simulator           - needs everything above
   12. simulator.run(...)
   13. PerformanceAnalyzer - evaluates the strategy's performance
"""

import os
import logging

from engine.event_bus import EventBus
from engine.matching_engine import MatchingEngine
from engine.portfolio import Portfolio
from engine.simulator import Simulator

from data.ingestion import DataIngestion
from data.tick_generator import TickGenerator

from mocks.kite_connect import MockKiteConnect
from mocks.kite_ticker import MockKiteTicker

from strategies.example_strategy import ExampleStrategy

from metrics.transaction_logger import TransactionLogger
from metrics.performance import PerformanceAnalyzer

from settlement.tax_dividend_api import TaxDividendAPI

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# ---------------------------------------------------------------------------
# Global configuration — edit these to control the backtest run
# ---------------------------------------------------------------------------

MODE = "BACKTEST"

SYMBOL = "RELIANCE"
START_DATE = "2023-01-01"
END_DATE = "2023-12-31"

INITIAL_CAPITAL = 100000.0

DATA_DIR = "data_cache/"
TRADE_LOG_PATH = "trades_journal.csv"

# used by DataIngestion and passed as a dummy credential to the mocks
API_KEY = ""
ACCESS_TOKEN = ""

# Set to False to skip the ingestion step when data is already cached locally.
RUN_INGESTION = True


# ---------------------------------------------------------------------------
# Step 0 helper — kept separate so main() stays readable
# ---------------------------------------------------------------------------

FREQUENCY = "minute"  # bar frequency used by both ingestion and tick generator


def _run_ingestion(
    api_key: str,
    symbol: str,
    start_date: str,
    end_date: str,
    data_dir: str,
    frequency: str,
) -> None:
    """
    Fetches historical minute bars for `symbol` and saves them as a
    Parquet file at `data_dir/ohlcv_{frequency}.parquet`.

    Called once at startup (before the simulation loop) if RUN_INGESTION
    is True. If the file already exists you can skip this by setting
    RUN_INGESTION = False at the top of this file.
    """
    filepath = os.path.join(data_dir, f"ohlcv_{frequency}.parquet")

    ingestion = DataIngestion(api_key=api_key)

    logger.info(f"[Ingestion] Fetching data for {symbol} from {start_date} to {end_date}...")
    raw_data = ingestion.fetch_data(
        symbol=symbol,
        start_date=start_date,
        end_date=end_date,
        frequency=frequency,
    )

    if not raw_data:
        raise RuntimeError(
            f"[Ingestion] No data returned for {symbol}. "
            "Check the API key, symbol name, and date range."
        )

    ingestion.save_to_parquet(data=raw_data, filepath=filepath)
    logger.info(f"[Ingestion] Saved {len(raw_data)} bars to {filepath}")


# ---------------------------------------------------------------------------
# Main wiring function
# ---------------------------------------------------------------------------

def main(
    mode: str,
    symbol: str,
    start_date: str,
    end_date: str,
    initial_capital: float,
    data_dir: str,
    trade_log_path: str,
    api_key: str,
    access_token: str,
    run_ingestion: bool,
) -> None:
    """
    Main entry point. Instantiates the environment (Live or Backtest) based
    on arguments/config, wires up all the components, and starts execution.

    Args:
        mode (str): "BACKTEST" or "LIVE". Only BACKTEST is wired up here;
            LIVE would swap MockKiteConnect/MockKiteTicker for the real
            kiteconnect SDK objects, leaving everything else identical.
        symbol (str): Trading symbol to run the simulation on.
        start_date (str): Start of the historical data window (YYYY-MM-DD).
        end_date (str): End of the historical data window (YYYY-MM-DD).
        initial_capital (float): Starting cash for the Portfolio.
        data_dir (str): Directory containing (or to receive) cached Parquet files.
        trade_log_path (str): Where TransactionLogger writes fills.
        api_key (str): API key forwarded to DataIngestion and the mock broker.
        access_token (str): Access token forwarded to the mock broker.
        run_ingestion (bool): If True, fetch + cache data before the simulation.
            Set to False when the Parquet cache already exists.
    """
    if mode != "BACKTEST":
        raise NotImplementedError(
            "LIVE mode wiring (real KiteConnect/KiteTicker) is not yet implemented."
        )

    # 0. Data Ingestion (runs once to populate the local Parquet cache)
    if run_ingestion:
        _run_ingestion(
            api_key=api_key,
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            data_dir=data_dir,
            frequency=FREQUENCY,
        )
    else:
        expected_path = os.path.join(data_dir, f"ohlcv_{FREQUENCY}.parquet")
        if not os.path.exists(expected_path):
            raise FileNotFoundError(
                f"RUN_INGESTION is False but no cached file found at {expected_path}. "
                "Set RUN_INGESTION = True to fetch the data first."
            )
        logger.info(f"[Ingestion] Skipped. Using cached file: {expected_path}")

    # 1. Shared event bus
    event_bus = EventBus()

    # 2. Data source (reads the Parquet file we just cached above)
    tick_generator = TickGenerator(data_dir=data_dir, frequency=FREQUENCY)

    # 3. Matching engine
    matching_engine = MatchingEngine(event_bus=event_bus)

    # 4 & 5. collaborators for Portfolio
    transaction_logger = TransactionLogger(log_filepath=trade_log_path)
    tax_api = TaxDividendAPI()

    # 6. Portfolio (the ledger) — must exist BEFORE MockKiteConnect, since
    # MockKiteConnect.__init__ requires a portfolio reference to serve
    # margins()/positions()/ltp()/quote() queries.
    portfolio = Portfolio(
        event_bus=event_bus,
        initial_capital=initial_capital,
        logger=transaction_logger,
        tax_api=tax_api,
    )

    # 7 & 8. Mock broker layer.
    mock_kite = MockKiteConnect(
        api_key=api_key,
        event_bus=event_bus,
        portfolio=portfolio,
        access_token=access_token,
    )
    mock_ticker = MockKiteTicker(api_key=api_key, access_token=access_token)

    # 9. Strategy, injected with the mock REST + WebSocket clients
    strategy = ExampleStrategy(kite_connect=mock_kite, kws=mock_ticker)

    # 10. Wire the ticker's callbacks to the strategy's handler methods,
    # mirroring how a real KiteTicker integration would be set up.
    mock_ticker.on_ticks = strategy.on_ticks
    mock_ticker.on_order_update = strategy.on_order_update

    # 11. Simulator — the conductor that owns the main chronological loop
    simulator = Simulator(
        event_bus=event_bus,
        tick_generator=tick_generator,
        matching_engine=matching_engine,
        portfolio=portfolio,
        strategy=strategy,
    )

    # 12. Run the backtest
    logger.info(f"[Simulator] Starting backtest: {symbol} | {start_date} → {end_date}")
    simulator.run(symbol=symbol, start_date=start_date, end_date=end_date)
    logger.info("[Simulator] Backtest complete.")

    analyzer = PerformanceAnalyzer(log_filepath=trade_log_path)
    metrics = analyzer.calculate_metrics()
    print("\nBacktest complete. Performance metrics:")
    for key, value in metrics.items():
        print(f"  {key}: {value}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    main(
        mode=MODE,
        symbol=SYMBOL,
        start_date=START_DATE,
        end_date=END_DATE,
        initial_capital=INITIAL_CAPITAL,
        data_dir=DATA_DIR,
        trade_log_path=TRADE_LOG_PATH,
        api_key=API_KEY,
        access_token=ACCESS_TOKEN,
        run_ingestion=RUN_INGESTION
    )