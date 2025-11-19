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


# ============================================================================
# NEW INDICATORS FOR IMPROVED SIGNAL QUALITY
# ============================================================================

def get_obv(df):
    """
    Calculate On Balance Volume (OBV)

    OBV measures buying/selling pressure by adding volume on up days
    and subtracting on down days. Rising OBV = accumulation,
    Falling OBV = distribution.

    Args:
        df: DataFrame with 'close' and 'volume' columns

    Returns:
        float: Current OBV value
    """
    if len(df) < 2:
        return 0

    close = df['close']
    volume = df['volume']

    # Calculate price direction
    price_direction = close.diff()

    # OBV calculation
    obv = pd.Series(index=df.index, dtype=float)
    obv.iloc[0] = volume.iloc[0]

    for i in range(1, len(df)):
        if price_direction.iloc[i] > 0:
            obv.iloc[i] = obv.iloc[i - 1] + volume.iloc[i]
        elif price_direction.iloc[i] < 0:
            obv.iloc[i] = obv.iloc[i - 1] - volume.iloc[i]
        else:
            obv.iloc[i] = obv.iloc[i - 1]

    return obv.iloc[-1]


def get_obv_trend(df, period=20):
    """
    Calculate OBV trend direction (rising or falling)

    Returns:
        dict: {
            'obv': current OBV,
            'obv_ema': EMA of OBV,
            'obv_trending_up': bool
        }
    """
    if len(df) < period:
        return {'obv': 0, 'obv_ema': 0, 'obv_trending_up': False}

    close = df['close']
    volume = df['volume']

    # Calculate OBV series
    price_direction = close.diff()
    obv = pd.Series(index=df.index, dtype=float)
    obv.iloc[0] = volume.iloc[0]

    for i in range(1, len(df)):
        if price_direction.iloc[i] > 0:
            obv.iloc[i] = obv.iloc[i - 1] + volume.iloc[i]
        elif price_direction.iloc[i] < 0:
            obv.iloc[i] = obv.iloc[i - 1] - volume.iloc[i]
        else:
            obv.iloc[i] = obv.iloc[i - 1]

    # Calculate EMA of OBV
    obv_ema = obv.ewm(span=period, adjust=False).mean()

    # Check if trending up
    obv_trending_up = obv.iloc[-1] > obv_ema.iloc[-1]

    return {
        'obv': obv.iloc[-1],
        'obv_ema': obv_ema.iloc[-1],
        'obv_trending_up': obv_trending_up
    }


def get_stochastic(df, k_period=14, d_period=3):
    """
    Calculate Stochastic Oscillator (%K and %D)

    Measures momentum by comparing close to recent high/low range.
    - %K > 80: Overbought
    - %K < 20: Oversold
    - %K crossing above %D: Bullish signal
    - %K crossing below %D: Bearish signal

    Args:
        df: DataFrame with 'high', 'low', 'close' columns
        k_period: Period for %K (default 14)
        d_period: Period for %D smoothing (default 3)

    Returns:
        dict: {
            'stoch_k': float (0-100),
            'stoch_d': float (0-100),
            'stoch_bullish': bool (K > D)
        }
    """
    if len(df) < k_period + d_period:
        return {'stoch_k': 50, 'stoch_d': 50, 'stoch_bullish': False}

    high = df['high']
    low = df['low']
    close = df['close']

    # Calculate %K
    lowest_low = low.rolling(window=k_period).min()
    highest_high = high.rolling(window=k_period).max()

    stoch_k = 100 * (close - lowest_low) / (highest_high - lowest_low)

    # Calculate %D (SMA of %K)
    stoch_d = stoch_k.rolling(window=d_period).mean()

    # Get current values
    current_k = stoch_k.iloc[-1] if not pd.isna(stoch_k.iloc[-1]) else 50
    current_d = stoch_d.iloc[-1] if not pd.isna(stoch_d.iloc[-1]) else 50

    return {
        'stoch_k': round(float(current_k), 2),
        'stoch_d': round(float(current_d), 2),
        'stoch_bullish': current_k > current_d
    }


def get_roc(df, period=12):
    """
    Calculate Rate of Change (ROC)

    Measures the percentage price change over a period.
    - ROC > 0: Upward momentum
    - ROC < 0: Downward momentum
    - Rising ROC: Accelerating momentum

    Args:
        df: DataFrame with 'close' column
        period: Lookback period (default 12)

    Returns:
        float: ROC percentage
    """
    if len(df) < period + 1:
        return 0

    close = df['close']

    # Calculate ROC
    roc = ((close - close.shift(period)) / close.shift(period)) * 100

    return round(float(roc.iloc[-1]), 2) if not pd.isna(roc.iloc[-1]) else 0


def get_williams_r(df, period=14):
    """
    Calculate Williams %R

    Similar to Stochastic but inverted scale.
    - %R > -20: Overbought
    - %R < -80: Oversold
    - Rising %R: Bullish momentum

    Args:
        df: DataFrame with 'high', 'low', 'close' columns
        period: Lookback period (default 14)

    Returns:
        float: Williams %R value (-100 to 0)
    """
    if len(df) < period:
        return -50

    high = df['high']
    low = df['low']
    close = df['close']

    # Calculate Williams %R
    highest_high = high.rolling(window=period).max()
    lowest_low = low.rolling(window=period).min()

    williams_r = -100 * (highest_high - close) / (highest_high - lowest_low)

    return round(float(williams_r.iloc[-1]), 2) if not pd.isna(williams_r.iloc[-1]) else -50


def get_volume_surge_score(df, period=20):
    """
    Calculate volume surge quality score (0-10)

    Analyzes recent volume patterns to score quality of volume surge.
    Higher score = more significant/unusual volume

    Args:
        df: DataFrame with 'volume' column
        period: Lookback period (default 20)

    Returns:
        float: Score 0-10
    """
    if len(df) < period:
        return 0

    volume = df['volume']
    current_volume = volume.iloc[-1]
    avg_volume = volume.iloc[-period:].mean()

    # Calculate percentile rank
    volume_history = volume.iloc[-period:]
    percentile = (volume_history < current_volume).sum() / len(volume_history) * 100

    # Score based on volume ratio and percentile
    volume_ratio = current_volume / avg_volume if avg_volume > 0 else 0

    score = 0

    # Volume ratio component (0-5 points)
    if volume_ratio > 3.0:
        score += 5
    elif volume_ratio > 2.0:
        score += 4
    elif volume_ratio > 1.5:
        score += 3
    elif volume_ratio > 1.2:
        score += 2
    elif volume_ratio > 1.0:
        score += 1

    # Percentile component (0-5 points)
    if percentile >= 95:
        score += 5
    elif percentile >= 90:
        score += 4
    elif percentile >= 80:
        score += 3
    elif percentile >= 70:
        score += 2
    elif percentile >= 60:
        score += 1

    return round(score, 1)


# ============================================================================
# VOLATILITY ASSESSMENT
# ============================================================================

def get_historical_volatility(df, period=20):
    """
    Calculate annualized historical volatility

    Args:
        df: DataFrame with 'close' column
        period: Lookback period (default 20)

    Returns:
        float: Annualized volatility percentage (e.g., 65.0 = 65% annual volatility)
    """
    if len(df) < period + 1:
        return 0.0

    # Calculate daily returns
    returns = df['close'].pct_change().dropna()

    # Get last N periods
    recent_returns = returns.tail(period)

    if len(recent_returns) < 2:
        return 0.0

    # Calculate standard deviation and annualize
    # 252 = trading days per year
    daily_vol = recent_returns.std()
    annual_vol = daily_vol * (252 ** 0.5) * 100

    return round(annual_vol, 2)


def calculate_volatility_score(data, df):
    """
    Multi-factor volatility assessment (0-7 scale)

    LOOSENED: Allow high-performing tech stocks (NVDA, META, AMD) to trade

    Prevents trading excessively volatile stocks like extreme TSLA moves
    and reduces position sizes for medium-volatility stocks

    Components:
    - ATR% (0-4 points): Daily volatility measure
    - Historical Volatility (0-3 points): 20-day annualized vol

    Score Interpretation (UPDATED):
    - 0-2: Low volatility (normal trading, 100% size)
    - 3-4: Medium volatility (100% position size)
    - 5: High volatility (75% position size)
    - 6: Very High volatility (50% position size)
    - 7: Extreme volatility (BLOCKED - too risky)

    Args:
        data: Dictionary with calculated indicators
        df: DataFrame with price history

    Returns:
        dict: {
            'volatility_score': float (0-7),
            'risk_class': str ('low', 'medium', 'high', 'very_high', 'extreme'),
            'position_multiplier': float (0.0-1.0),
            'allow_trading': bool,
            'atr_pct': float,
            'hist_vol': float
        }
    """
    score = 0

    # 1. ATR Percentage (0-4 points)
    # Most reliable real-time volatility measure
    atr = data.get('atr_14', 0)
    close = data.get('close', 0)
    atr_pct = (atr / close * 100) if close > 0 else 0

    # LOOSENED: Higher thresholds allow more stocks through
    if atr_pct > 6.0:  # Was 5.0
        score += 4  # Extreme
    elif atr_pct > 4.5:  # Was 3.5
        score += 3  # High
    elif atr_pct > 3.5:  # Was 2.5
        score += 2  # Medium-high
    elif atr_pct > 2.0:  # Was 1.5
        score += 1  # Medium-low
    # else: 0 points (low volatility)

    # 2. Historical Volatility (0-3 points)
    # Longer-term volatility context
    hist_vol = get_historical_volatility(df, period=20)

    # LOOSENED: Higher thresholds
    if hist_vol > 80:  # Was 60
        score += 3  # Extreme
    elif hist_vol > 60:  # Was 40
        score += 2  # High
    elif hist_vol > 45:  # Was 30
        score += 1  # Medium
    # else: 0 points (low volatility)

    # Classification and Risk Management (UPDATED for 0-7 scale)
    if score >= 7:
        risk_class = 'extreme'
        position_multiplier = 0.0  # Block entirely
        allow_trading = False
    elif score >= 6:
        risk_class = 'very_high'
        position_multiplier = 0.5  # Half position size
        allow_trading = True
    elif score >= 5:
        risk_class = 'high'
        position_multiplier = 0.75
        allow_trading = True
    elif score >= 3:
        risk_class = 'medium'
        position_multiplier = 1.0  # Full size
        allow_trading = True
    else:
        risk_class = 'low'
        position_multiplier = 1.0  # Full position size
        allow_trading = True

    return {
        'volatility_score': round(score, 1),
        'risk_class': risk_class,
        'position_multiplier': position_multiplier,
        'allow_trading': allow_trading,
        'atr_pct': round(atr_pct, 2),
        'hist_vol': hist_vol
    }