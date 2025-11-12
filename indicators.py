import numpy
import pandas as pd
import statistics


def get_sma(df, period):
    df = df[-period:]
    close_data = df['close']
    close_data.reset_index(drop=True, inplace=True)
    MA = statistics.mean(close_data)
    SD = statistics.stdev(close_data)
    return {'sma': MA, 'sd': SD}


def get_rsi(over: pd.Series, fn_roll: callable) -> pd.Series:
    # Source: stackoverflow.com/questions/20526414/relative-strength-index-in-python-pandas
    delta = over.diff()
    delta = delta[1:]

    up = delta.clip(lower=0)
    down = delta.clip(upper=0).abs()

    roll_up = fn_roll(up)
    roll_down = fn_roll(down)
    rs = roll_up / roll_down
    rsi = 100.0 - (100.0 / (1.0 + rs))

    rsi[:] = numpy.select([roll_down == 0, roll_up == 0, True], [100, 0, rsi])
    rsi.name = 'rsi'

    return rsi.iloc[-1]


def get_bollinger(df, stdev, period):
    sma = get_sma(df, period)
    bollinger_mean = sma['sma']
    bollinger_upper = sma['sma'] + stdev * sma['sd']
    bollinger_lower = sma['sma'] - stdev * sma['sd']
    return {'bollinger_mean': bollinger_mean, 'bollinger_upper': bollinger_upper, 'bollinger_lower': bollinger_lower}


def get_ema(df, period):
    close_data = df['close'].tail(period * 2)  # Get extra data for better EMA calculation

    # Calculate EMA using pandas ewm (exponentially weighted moving average)
    # alpha = 2 / (period + 1) is the standard EMA smoothing factor
    ema = close_data.ewm(span=period, adjust=False).mean()

    return ema.iloc[-1]


def get_avg_volume(df, period=20):
    """
    Calculate average volume over specified period

    Args:
        df: DataFrame with 'volume' column
        period: Number of periods for average (default 20)

    Returns:
        float: Average volume
    """
    if 'volume' not in df.columns:
        return 0

    volume_data = df['volume'].tail(period)
    avg_vol = volume_data.mean()
    return avg_vol


def get_atr(df, period=14):
    """
    Calculate Average True Range (ATR)

    ATR measures volatility by decomposing the entire range of an asset price
    for that period. Higher ATR = more volatile stock.

    Args:
        df: DataFrame with 'high', 'low', 'close' columns
        period: Number of periods for ATR calculation (default 14)

    Returns:
        float: ATR value for the most recent period
    """
    if len(df) < period + 1:
        return 0

    # Calculate True Range for each period
    # TR = max(high - low, abs(high - prev_close), abs(low - prev_close))

    high = df['high']
    low = df['low']
    close = df['close']

    # Previous close (shifted by 1)
    prev_close = close.shift(1)

    # Three components of True Range
    tr1 = high - low  # High - Low
    tr2 = (high - prev_close).abs()  # High - Previous Close
    tr3 = (low - prev_close).abs()  # Low - Previous Close

    # True Range is the maximum of the three
    true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    # Calculate ATR as exponential moving average of True Range
    # Using pandas ewm (exponentially weighted moving average)
    atr = true_range.ewm(span=period, adjust=False).mean()

    # Return the most recent ATR value
    return atr.iloc[-1] if len(atr) > 0 else 0


def get_atr_stop_loss(current_price, atr, atr_multiplier=2.0, min_pct=3.0, max_pct=10.0):
    """
    Calculate ATR-based stop loss with safety bounds

    Args:
        current_price: Current stock price
        atr: ATR value
        atr_multiplier: How many ATRs below price (default 2.0)
        min_pct: Minimum stop distance as % (default 3%)
        max_pct: Maximum stop distance as % (default 10%)

    Returns:
        float: Stop loss price
    """
    if atr is None or atr == 0:
        # Fallback to 5% if ATR unavailable
        return current_price * 0.95

    # Calculate ATR-based stop
    stop_price = current_price - (atr * atr_multiplier)

    # Apply safety bounds
    min_stop = current_price * (1 - max_pct / 100)  # Maximum stop distance
    max_stop = current_price * (1 - min_pct / 100)  # Minimum stop distance

    # Ensure stop is within bounds
    stop_price = max(min_stop, min(stop_price, max_stop))

    return round(stop_price, 2)


def get_macd(df, fast_period=12, slow_period=26, signal_period=9):
    """
    Calculate MACD (Moving Average Convergence Divergence)

    MACD measures momentum and trend direction
    - MACD line = 12 EMA - 26 EMA
    - Signal line = 9 EMA of MACD line
    - Histogram = MACD line - Signal line

    Args:
        df: DataFrame with 'close' column
        fast_period: Fast EMA period (default 12)
        slow_period: Slow EMA period (default 26)
        signal_period: Signal line EMA period (default 9)

    Returns:
        dict: {
            'macd': float,
            'macd_signal': float,
            'macd_histogram': float
        }
    """
    if len(df) < slow_period + signal_period:
        return {'macd': 0, 'macd_signal': 0, 'macd_histogram': 0}

    close = df['close']

    # Calculate fast and slow EMAs
    ema_fast = close.ewm(span=fast_period, adjust=False).mean()
    ema_slow = close.ewm(span=slow_period, adjust=False).mean()

    # MACD line = Fast EMA - Slow EMA
    macd_line = ema_fast - ema_slow

    # Signal line = 9-period EMA of MACD line
    signal_line = macd_line.ewm(span=signal_period, adjust=False).mean()

    # Histogram = MACD - Signal
    histogram = macd_line - signal_line

    # Return most recent values
    return {
        'macd': macd_line.iloc[-1],
        'macd_signal': signal_line.iloc[-1],
        'macd_histogram': histogram.iloc[-1]
    }


def get_adx(df, period=14):
    """
    Calculate ADX (Average Directional Index)

    ADX measures trend strength (not direction)
    - ADX > 25: Strong trend
    - ADX < 20: Weak/choppy trend
    - Rising ADX: Strengthening trend
    - Falling ADX: Weakening trend

    Args:
        df: DataFrame with 'high', 'low', 'close' columns
        period: Lookback period (default 14)

    Returns:
        float: ADX value (0-100)
    """
    if len(df) < period * 2:
        return 0

    high = df['high']
    low = df['low']
    close = df['close']

    # Calculate +DM and -DM
    high_diff = high.diff()
    low_diff = -low.diff()

    plus_dm = high_diff.where((high_diff > low_diff) & (high_diff > 0), 0)
    minus_dm = low_diff.where((low_diff > high_diff) & (low_diff > 0), 0)

    # Calculate True Range
    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    # Smooth the values using Wilder's smoothing (EMA with alpha = 1/period)
    atr = true_range.ewm(alpha=1 / period, adjust=False).mean()
    plus_di = 100 * (plus_dm.ewm(alpha=1 / period, adjust=False).mean() / atr)
    minus_di = 100 * (minus_dm.ewm(alpha=1 / period, adjust=False).mean() / atr)

    # Calculate DX (Directional Index)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di)

    # ADX is smoothed DX
    adx = dx.ewm(alpha=1 / period, adjust=False).mean()

    return adx.iloc[-1] if len(adx) > 0 else 0