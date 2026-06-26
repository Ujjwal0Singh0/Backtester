"""
Scripts to hit Data API 1 and save as Parquet.
"""
import urllib.request
import urllib.error
import json
import os
import re
import pandas as pd
from typing import List, Dict, Any
import logging

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

class DataIngestion:
    """
    Handles fetching historical data from external APIs and saving it locally.
    """
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "http://127.0.0.1:8000"

    def fetch_data(self, symbol: str, start_date: str, end_date: str, auto_retry: bool = True) -> List[Dict[str, Any]]:
        """
        Fetches historical data. Includes an auto-retry mechanism to adapt to the 
        strict date-range validation rules of the internal Data API.
        """
        url = f"{self.base_url}/data"
        
        payload = {
            "symbols": [symbol],
            "frequency": "1m",
            "date_from": start_date,
            "date_to": end_date
        }
        
        req = urllib.request.Request(
            url, 
            data=json.dumps(payload).encode('utf-8'),
            headers={
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {self.api_key}'
            },
            method='POST'
        )
        
        try:
            with urllib.request.urlopen(req) as response:
                res_data = json.loads(response.read().decode('utf-8'))
                
                # 1. Success Case
                if res_data.get('status') in ['ok', 'partial']:
                    data_list = res_data.get('data', [])
                    if data_list and len(data_list) > 0:
                        return data_list[0].get('bars', [])
                
                # 2. Strict API Rejection Case
                unavail = res_data.get('unavailable', [])
                if unavail:
                    reason = unavail[0].get('reason', '')
                    logger.warning(f"Data API Refused: {reason}")
                    
                    # INTELLIGENT AUTO-RETRY: Parse the exact database limits from the error message
                    if auto_retry and ("data starts at" in reason or "data ends at" in reason):
                        logger.info("Auto-correcting requested dates to match the API's database limits...")
                        
                        new_start = start_date
                        new_end = end_date
                        
                        start_match = re.search(r"data starts at (\d{4}-\d{2}-\d{2})", reason)
                        if start_match:
                            new_start = f"{start_match.group(1)} 00:00:00"
                            
                        end_match = re.search(r"data ends at (\d{4}-\d{2}-\d{2})", reason)
                        if end_match:
                            new_end = f"{end_match.group(1)} 23:59:59"
                            
                        logger.info(f"Retrying fetch with exact bounds: {new_start} to {new_end}")
                        return self.fetch_data(symbol, new_start, new_end, auto_retry=False)

                return []
                
        except urllib.error.HTTPError as e:
            error_body = e.read().decode('utf-8')
            logger.error(f"FastAPI Validation Error (422): {error_body}")
            return []
        except Exception as e:
            logger.error(f"Failed to fetch data for {symbol}: {e}")
            return []

    def save_to_parquet(self, data: List[Dict[str, Any]], filepath: str) -> None:
        """
        Saves the fetched data to a Parquet file.
        """
        if not data:
            logger.warning(f"No data provided to save for {filepath}. Skipping.")
            return
            
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        
        df = pd.DataFrame(data)
        if 'datetime' in df.columns:
            df['datetime'] = pd.to_datetime(df['datetime'], utc=True)
            
        df.to_parquet(filepath, engine='pyarrow', index=False)
        logger.info(f"Successfully saved {len(df)} rows to {filepath}")