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

        temp_data['indicators']['sma14'] = round(sma14['sma'], 2)
        temp_data['indicators']['sma20'] = round(sma20['sma'], 2)
        temp_data['indicators']['sma50'] = round(sma50['sma'], 2)
        temp_data['indicators']['sma200'] = round(sma200['sma'], 2)

        # Calculate EMAs (8, 12, 14, 20, 50 day)
        temp_data['indicators']['ema8'] = round(float(indicators.get_ema(df, period=8)), 2)
        temp_data['indicators']['ema12'] = round(float(indicators.get_ema(df, period=12)), 2)
        temp_data['indicators']['ema14'] = round(float(indicators.get_ema(df, period=14)), 2)
        temp_data['indicators']['ema20'] = round(float(indicators.get_ema(df, period=20)), 2)
        temp_data['indicators']['ema50'] = round(float(indicators.get_ema(df, period=50)), 2)

        # Calculate RSI (14 period)
        def rolling_fn(series):
            return series.rolling(window=14).mean()

        temp_data['indicators']['rsi'] = round(float(indicators.get_rsi(df['close'], rolling_fn)), 2)

        # Calculate Bollinger Bands (20 period, 2 stdev)
        bollinger = indicators.get_bollinger(df, stdev=2, period=20)
        temp_data['indicators']['bollinger_mean'] = round(bollinger['bollinger_mean'], 2)
        temp_data['indicators']['bollinger_upper'] = round(bollinger['bollinger_upper'], 2)
        temp_data['indicators']['bollinger_lower'] = round(bollinger['bollinger_lower'], 2)

        # Calculate Average Volume (20 period)
        avg_volume = indicators.get_avg_volume(df, period=20)
        temp_data['indicators']['avg_volume'] = round(avg_volume, 2)

        # Calculate current volume ratio
        current_volume = df['volume'].iloc[-1]
        temp_data['indicators']['volume_ratio'] = round(current_volume / avg_volume, 2) if avg_volume > 0 else 0

        # Calculate ATR (14 period)
        temp_data['indicators']['atr_14'] = round(float(indicators.get_atr(df, period=14)), 2)

        # === NEW: Calculate MACD ===
        macd_data = indicators.get_macd(df)
        temp_data['indicators']['macd'] = round(float(macd_data['macd']), 4)
        temp_data['indicators']['macd_signal'] = round(float(macd_data['macd_signal']), 4)
        temp_data['indicators']['macd_histogram'] = round(float(macd_data['macd_histogram']), 4)

        # === NEW: Calculate ADX ===
        temp_data['indicators']['adx'] = round(float(indicators.get_adx(df, period=14)), 2)

        # Add current price data
        temp_data['indicators']['close'] = round(float(df['close'].iloc[-1]), 2)
        temp_data['indicators']['open'] = round(float(df['open'].iloc[-1]), 2)
        temp_data['indicators']['high'] = round(float(df['high'].iloc[-1]), 2)
        temp_data['indicators']['low'] = round(float(df['low'].iloc[-1]), 2)
        temp_data['indicators']['prev_low'] = round(float(df['low'].iloc[-2]), 2) if len(df) > 1 else round(
            float(df['low'].iloc[-1]), 2)

        # Calculate daily change percentage
        if len(df) > 1:
            prev_close = df['close'].iloc[-2]
            current_close = df['close'].iloc[-1]
            temp_data['indicators']['daily_change_pct'] = round(((current_close - prev_close) / prev_close * 100), 2)
        else:
            temp_data['indicators']['daily_change_pct'] = 0

        processed_data[ticker] = temp_data

    return processed_data


def _fetch_alpaca_batch_data(symbols, current_date, days=250):
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
            adjustment='split',

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