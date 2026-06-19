"""
Scripts to hit Data API 1 and save as Parquet.
"""

from typing import List, Dict, Any

class DataIngestion:
    """
    Handles fetching historical data from external APIs and saving it locally.
    """
    def __init__(self, api_key: str):
        """
        Initializes the DataIngestion module.
        
        Args:
            api_key (str): The API key for the data provider.
        """
        pass

    def fetch_data(self, symbol: str, start_date: str, end_date: str) -> List[Dict[str, Any]]:
        """
        Fetches historical data for a given symbol and date range.
        
        Args:
            symbol (str): The trading symbol.
            start_date (str): The start date for the data.
            end_date (str): The end date for the data.
            
        Returns:
            List[Dict[str, Any]]: The fetched historical data.
        """
        raise NotImplementedError

    def save_to_parquet(self, data: List[Dict[str, Any]], filepath: str) -> None:
        """
        Saves the fetched data to a Parquet file.
        
        Args:
            data (List[Dict[str, Any]]): The data to save.
            filepath (str): The path to the Parquet file.
        """
        raise NotImplementedError
