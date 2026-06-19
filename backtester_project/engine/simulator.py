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
    def __init__(self, event_bus: EventBus, tick_generator: TickGenerator, 
                 matching_engine: MatchingEngine, portfolio: Portfolio, strategy: Any):
        """
        Initializes the Simulator.
        
        Args:
            event_bus (EventBus): The centralized event bus.
            tick_generator (TickGenerator): The data source yielding ticks.
            matching_engine (MatchingEngine): The execution simulator.
            portfolio (Portfolio): The active ledger.
            strategy (Any): The trading strategy to execute.
        """
        pass

    def run(self, symbol: str, start_date: str, end_date: str) -> None:
        """
        Starts the simulation loop.
        
        Args:
            symbol (str): The trading symbol.
            start_date (str): The start date.
            end_date (str): The end date.
        """
        raise NotImplementedError
