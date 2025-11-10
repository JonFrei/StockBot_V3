import pandas as pd
from datetime import timedelta
from config import Config

import indicators

from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame


def process_data(symbols, current_date):
    """
    Process historical data and calculate indicators for each symbol

    Returns:
        dict: {ticker: {'indicators': {...}, 'raw': DataFrame}}
    """
    historical_data = _fetch_alpaca_batch_data(symbols, current_date, days=500)
    processed_data = {}

    for ticker, df in historical_data.items():
        temp_data = {
            'indicators': {},
            'raw': df
        }

        # Calculate indicators
        temp_data['indicators']['sma20'] = indicators.get_sma(df, period=20)
        temp_data['indicators']['sma50'] = indicators.get_sma(df, period=50)
        temp_data['indicators']['sma200'] = indicators.get_sma(df, period=200)

        processed_data[ticker] = temp_data

    return processed_data


def _fetch_alpaca_batch_data(symbols, current_date, days=500):
    """
    Fetch historical data for multiple symbols using Alpaca API
    Similar interface to Twelve Data batch fetching

    Args:
        symbols: List of stock symbols or single symbol string
        days: Number of days of historical data (default: 500)

    Returns:
        Dictionary: {symbol: processed_data_dict}
    """

    if isinstance(symbols, str):
        symbols = [symbols]

    if not symbols:
        return {}

    try:
        client = StockHistoricalDataClient(
            Config.ALPACA_API_KEY,
            Config.ALPACA_API_SECRET
        )

        # Ensure days is integer
        if not isinstance(days, int):
            days = int(days)

        start_date = current_date - timedelta(days=days)

        request = StockBarsRequest(
            symbol_or_symbols=symbols,
            timeframe=TimeFrame.Day,
            start=start_date,
            end=current_date,
            adjustment='split'
        )

        bars = client.get_stock_bars(request)
        stock_data = {}

        for symbol in symbols:
            try:
                if symbol not in bars.data:
                    continue

                symbol_bars = bars.data[symbol]
                if not symbol_bars:
                    continue

                # Create DataFrame
                df = pd.DataFrame([{
                    'open': bar.open,
                    'high': bar.high,
                    'low': bar.low,
                    'close': bar.close,
                    'volume': bar.volume,
                    'timestamp': bar.timestamp
                } for bar in symbol_bars])

                df.set_index('timestamp', inplace=True)
                df.sort_index(inplace=True)

                if len(df) < 200:
                    continue

                # CRITICAL: Call process_data to calculate indicators
                # processed = process_data(df, symbol)
                # if processed:
                #     stock_data[symbol] = processed
                stock_data[symbol] = df

            except Exception as e:
                print(f"[ERROR] Processing {symbol}: {e}")
                continue

        return stock_data

    except Exception as e:
        print(f"[ERROR] Alpaca batch request failed: {e}")
        return {}


if __name__ == '__main__':
    # Test single ticker
    print('Reserved for testing')
