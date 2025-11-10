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

        # Calculate SMAs (14, 20, 50, 200 day)
        sma14 = indicators.get_sma(df, period=14)
        sma20 = indicators.get_sma(df, period=20)
        sma50 = indicators.get_sma(df, period=50)
        sma200 = indicators.get_sma(df, period=200)

        temp_data['indicators']['sma14'] = sma14['sma']
        temp_data['indicators']['sma20'] = sma20['sma']
        temp_data['indicators']['sma50'] = sma50['sma']
        temp_data['indicators']['sma200'] = sma200['sma']

        # Calculate EMAs (8, 12, 14, 20, 50 day)
        temp_data['indicators']['ema8'] = indicators.get_ema(df, period=8)
        temp_data['indicators']['ema12'] = indicators.get_ema(df, period=12)
        temp_data['indicators']['ema14'] = indicators.get_ema(df, period=14)
        temp_data['indicators']['ema20'] = indicators.get_ema(df, period=20)
        temp_data['indicators']['ema50'] = indicators.get_ema(df, period=50)

        # Calculate RSI (14 period)
        def rolling_fn(series):
            return series.rolling(window=14).mean()

        temp_data['indicators']['rsi'] = indicators.get_rsi(df['close'], rolling_fn)

        # Calculate Bollinger Bands (20 period, 2 stdev)
        bollinger = indicators.get_bollinger(df, stdev=2, period=20)
        temp_data['indicators']['bollinger_mean'] = bollinger['bollinger_mean']
        temp_data['indicators']['bollinger_upper'] = bollinger['bollinger_upper']
        temp_data['indicators']['bollinger_lower'] = bollinger['bollinger_lower']

        # Calculate Average Volume (20 period)
        avg_volume = indicators.get_avg_volume(df, period=20)
        temp_data['indicators']['avg_volume'] = avg_volume

        # Calculate current volume ratio
        current_volume = df['volume'].iloc[-1]
        temp_data['indicators']['volume_ratio'] = current_volume / avg_volume if avg_volume > 0 else 0

        # Calculate ATR (14 period)
        temp_data['indicators']['atr_14'] = indicators.get_atr(df, period=14)

        # Add current price data
        temp_data['indicators']['close'] = df['close'].iloc[-1]
        temp_data['indicators']['open'] = df['open'].iloc[-1]
        temp_data['indicators']['high'] = df['high'].iloc[-1]
        temp_data['indicators']['low'] = df['low'].iloc[-1]
        temp_data['indicators']['prev_low'] = df['low'].iloc[-2] if len(df) > 1 else df['low'].iloc[-1]

        # Calculate daily change percentage
        if len(df) > 1:
            prev_close = df['close'].iloc[-2]
            current_close = df['close'].iloc[-1]
            temp_data['indicators']['daily_change_pct'] = ((current_close - prev_close) / prev_close * 100)
        else:
            temp_data['indicators']['daily_change_pct'] = 0

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
