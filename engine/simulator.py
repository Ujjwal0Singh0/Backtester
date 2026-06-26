"""
The main chronological 'while' loop runner.
"""

from engine.event_bus import EventBus
from data.tick_generator import TickGenerator
from engine.matching_engine import MatchingEngine
from engine.portfolio import Portfolio
from typing import Any

class Simulator:
    """
    Runs a continuous loop that processes the event_bus until the historical data ends.
    Orchestrates the sequence of Clock Tick, Order Evaluation, Fills & Settlement, 
    and Strategy Pulse.
    """
    def __init__(
        self,
        event_bus: EventBus,
        tick_generator: TickGenerator, 
        matching_engine: MatchingEngine, 
        portfolio: Portfolio, 
        strategy: Any
        ):
        """
        Initializes the Simulator.
        
        Args:
            event_bus (EventBus): The centralized event bus.
            tick_generator (TickGenerator): The data source yielding ticks.
            matching_engine (MatchingEngine): The execution simulator.
            portfolio (Portfolio): The active ledger.
            strategy (Any): The trading strategy to execute.
        """

        self.event_bus = event_bus
        self.tick_generator = tick_generator
        self.matching_engine = matching_engine
        self.portfolio = portfolio
        self.strategy = strategy

    def run(self, symbol: str, start_date: str, end_date: str) -> None:
        """
        Starts the simulation loop.
        
        Args:
            symbol (str): The trading symbol.
            start_date (str): The start date.
            end_date (str): The end date.
        """
        tick_stream = self.tick_generator.generate_ticks(
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
        )
        # Main chronological loop
        for tick in tick_stream:

            # Every market tick enters the EventBus first
            self.event_bus.publish(tick)

            # Process every pending event in FIFO order
            while self.event_bus.has_events():

                event = self.event_bus.get_next_event()

                if event is None:
                    continue

                # Tick Events
                if isinstance(event, TickEvent):

                    # Update unrealized PnL.
                    self.portfolio.mark_to_market(event)

                    # Notify the trading strategy.
                    # Strategy may generate new OrderEvents.
                    self.strategy.on_ticks(None, [event])

                    # TODO:
                    # self.matching_engine.evaluate_ticks(event)


                # Order Events
                elif isinstance(event, dict):

                    if event.get("event_type") == "ORDER":

                        # TODO:
                        # self.matching_engine.process_order(event)
                        pass

                    elif event.get("event_type") == "FILL":

                        # TODO:
                        # self.portfolio.update_from_fill(event)
                        pass