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
    NOW WITH NEW INDICATORS

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

        # Calculate MACD
        macd_data = indicators.get_macd(df)
        temp_data['indicators']['macd'] = round(float(macd_data['macd']), 4)
        temp_data['indicators']['macd_signal'] = round(float(macd_data['macd_signal']), 4)
        temp_data['indicators']['macd_histogram'] = round(float(macd_data['macd_histogram']), 4)

        # Calculate ADX
        temp_data['indicators']['adx'] = round(float(indicators.get_adx(df, period=14)), 2)

        # OBV Trend
        obv_trend = indicators.get_obv_trend(df, period=20)
        temp_data['indicators']['obv'] = round(obv_trend['obv'], 2)
        temp_data['indicators']['obv_ema'] = round(obv_trend['obv_ema'], 2)
        temp_data['indicators']['obv_trending_up'] = obv_trend['obv_trending_up']

        # Stochastic Oscillator
        stoch = indicators.get_stochastic(df, k_period=14, d_period=3)
        temp_data['indicators']['stoch_k'] = stoch['stoch_k']
        temp_data['indicators']['stoch_d'] = stoch['stoch_d']
        temp_data['indicators']['stoch_bullish'] = stoch['stoch_bullish']

        # Rate of Change
        temp_data['indicators']['roc_12'] = indicators.get_roc(df, period=12)

        # Williams %R
        temp_data['indicators']['williams_r'] = indicators.get_williams_r(df, period=14)

        # Volume Surge Score (0-10)
        temp_data['indicators']['volume_surge_score'] = indicators.get_volume_surge_score(df, period=20)

        # MACD previous histogram (for acceleration check)
        if len(df) > 1:
            macd_prev = indicators.get_macd(df.iloc[:-1])
            temp_data['indicators']['macd_hist_prev'] = round(float(macd_prev['macd_histogram']), 4)
        else:
            temp_data['indicators']['macd_hist_prev'] = 0

        # EMA50 10 days ago (for golden cross trend check)
        if len(df) >= 60:
            ema50_series = df['close'].ewm(span=50, adjust=False).mean()
            if len(ema50_series) >= 11:
                temp_data['indicators']['ema50_10d_ago'] = round(float(ema50_series.iloc[-11]), 2)
            else:
                temp_data['indicators']['ema50_10d_ago'] = temp_data['indicators']['ema50']
        else:
            temp_data['indicators']['ema50_10d_ago'] = temp_data['indicators']['ema50']

        # Volatility assessment
        temp_data['indicators']['volatility_metrics'] = indicators.calculate_volatility_score(
            temp_data['indicators'],
            df
        )

        # Add current price data
        temp_data['indicators']['close'] = round(float(df['close'].iloc[-1]), 2)
        temp_data['indicators']['open'] = round(float(df['open'].iloc[-1]), 2)
        temp_data['indicators']['high'] = round(float(df['high'].iloc[-1]), 2)
        temp_data['indicators']['low'] = round(float(df['low'].iloc[-1]), 2)
        temp_data['indicators']['prev_low'] = round(float(df['low'].iloc[-2]), 2) if len(df) > 1 else round(
            float(df['low'].iloc[-1]), 2)
        temp_data['indicators']['raw'] = df

        # Calculate daily change percentage
        if len(df) > 1:
            prev_close = df['close'].iloc[-2]
            current_close = df['close'].iloc[-1]
            temp_data['indicators']['daily_change_pct'] = round(((current_close - prev_close) / prev_close * 100), 2)
            temp_data['indicators']['prev_close'] = round(float(prev_close), 2)
        else:
            temp_data['indicators']['daily_change_pct'] = 0
            temp_data['indicators']['prev_close'] = round(float(df['close'].iloc[-1]), 2)

        processed_data[ticker] = temp_data

    return processed_data


def _fetch_alpaca_batch_data(symbols, current_date, days=250):
    """
    Fetch historical data for multiple symbols using Alpaca API

    FIXED: Removed split-adjustment validation blocks per user request

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

        # Simple if/then: Choose feed based on trading mode
        if Config.BACKTESTING:
            feed_type = 'sip'  # Better data for backtesting
        else:
            feed_type = 'iex'  # Free feed for live trading (no SIP subscription)

        # Build request (handles all tickers in one call)
        request = StockBarsRequest(
            symbol_or_symbols=symbols,
            timeframe=TimeFrame.Day,
            start=start_date,
            end=current_date,
            adjustment='split',
            feed=feed_type
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

                # Minimum data requirement
                if len(df) < 200:
                    continue

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