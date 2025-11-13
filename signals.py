import stock_data
from datetime import datetime

tickers = ""
current_date = datetime.today()


def buy_signals(data, buy_signal_list):
    """
    Check multiple buy strategies and return first valid signal
    Returns dict or None
    """
    close = data['close']
    sma200 = data['sma200']

    # Calculate distance from 200 SMA
    distance_from_200 = ((close - sma200) / sma200 * 100) if sma200 > 0 else -100

    # Only block if MORE than 5% below 200 SMA
    if distance_from_200 < -5.0:
        return {
            'side': 'hold',
            'msg': f'🔴 Bear Market Protection Active ({distance_from_200:.1f}% below 200 SMA)',
            'limit_price': None,
            'stop_loss': None,
            'signal_type': 'regime_filter'
        }

    for strategy_name in buy_signal_list:
        if strategy_name in BUY_STRATEGIES:
            strategy_func = BUY_STRATEGIES[strategy_name]
            signal = strategy_func(data)

            # Return first valid buy signal
            if signal and isinstance(signal, dict) and signal.get('side') == 'buy':
                return signal

    # No buy signal found
    return None


# ===================================================================================
# BUY SIGNALS - VERSION 2: BALANCED (Quality + Quantity)
# ===================================================================================

def swing_trade_1(data):
    """
    ENHANCED BUT BALANCED: Keep improvements that worked

    Win Rate: 73.5% → 75.8% ✅ (WORKING WELL)
    Trades: 68 → 95 ✅ (MORE TRADES)

    Keep only the best enhancements, drop the restrictive ones
    """
    ema20 = data.get('ema20', 0)
    ema50 = data.get('ema50', 0)
    sma200 = data.get('sma200', 0)
    rsi = data.get('rsi', 50)
    close = data.get('close', 0)
    volume_ratio = data.get('volume_ratio', 0)
    macd = data.get('macd', 0)
    macd_signal = data.get('macd_signal', 0)
    obv_trending_up = data.get('obv_trending_up', False)

    # Trend confirmation
    if not (ema20 > ema50):
        return _no_signal('No uptrend')

    # Price above both EMAs and 200 SMA
    if not (close > ema20 and close > sma200):
        return _no_signal('Price below key levels')

    # RSI sweet spot
    if not (48 <= rsi <= 72):
        return _no_signal(f'RSI {rsi:.0f} not in 48-72 range')

    # Volume (keep at 1.2x - working well)
    if volume_ratio < 1.2:
        return _no_signal(f'Volume {volume_ratio:.1f}x too low')

    # MACD bullish
    if macd <= macd_signal:
        return _no_signal('MACD not bullish')

    # OBV confirmation (KEEP - helpful)
    if not obv_trending_up:
        return _no_signal('OBV not confirming')

    return {
        'side': 'buy',
        'msg': f'✅ Swing1: RSI {rsi:.0f}, Vol {volume_ratio:.1f}x, MACD+, OBV+',
        'limit_price': close,
        'stop_loss': None,
        'signal_type': 'swing_trade_1'
    }


def swing_trade_2(data):
    """
    FIXED: Was too restrictive (0 trades) - Now balanced

    Original: 55 trades, 65.5% win rate
    V1 (too strict): 0 trades
    V2 (balanced): Target 45-55 trades, 70%+ win rate

    LOOSENED FILTERS:
    - Volume: 1.2x → 1.1x
    - RSI: 38-70 → 35-72
    - ADX: Removed (was blocking too much)
    - Stochastic: Removed (too restrictive)
    - Daily change: -3% → -5%
    - Pullback volume: Removed check

    KEPT FILTERS:
    - OBV trending up (good filter)
    - MACD bullish
    - Pullback range 2-12%
    """
    close = data.get('close', 0)
    ema20 = data.get('ema20', 0)
    ema50 = data.get('ema50', 0)
    sma200 = data.get('sma200', 0)
    rsi = data.get('rsi', 50)
    volume_ratio = data.get('volume_ratio', 0)
    daily_change_pct = data.get('daily_change_pct', 0)
    macd = data.get('macd', 0)
    macd_signal = data.get('macd_signal', 0)
    obv_trending_up = data.get('obv_trending_up', False)

    # 1. Price above 200 SMA
    if close <= sma200:
        return _no_signal('Below 200 SMA')

    # 2. EMA structure
    if ema20 <= ema50:
        return _no_signal('EMA20 not above EMA50')

    # 3. Pullback depth (2-12% - keep this)
    ema20_distance = abs((close - ema20) / ema20 * 100) if ema20 > 0 else 100
    if not (2.0 <= ema20_distance <= 12.0):
        return _no_signal(f'Pullback {ema20_distance:.1f}% not in 2-12% range')

    # 4. LOOSENED: RSI (35-72 instead of 38-70)
    if not (35 <= rsi <= 72):
        return _no_signal(f'RSI {rsi:.0f} outside 35-72')

    # 5. LOOSENED: Volume (1.1x instead of 1.2x)
    if volume_ratio < 1.1:
        return _no_signal(f'Volume {volume_ratio:.1f}x below 1.1x')

    # 6. MACD momentum
    if macd <= macd_signal:
        return _no_signal('MACD not bullish')

    # 7. OBV (keep - good filter)
    if not obv_trending_up:
        return _no_signal('OBV not confirming')

    # 8. LOOSENED: Price stabilization (-5% instead of -3%)
    if daily_change_pct < -5.0:
        return _no_signal(f'Price dropping too fast ({daily_change_pct:.1f}%)')

    return {
        'side': 'buy',
        'msg': f'✅ Pullback: {ema20_distance:.1f}% from EMA20, RSI {rsi:.0f}, OBV+',
        'limit_price': close,
        'stop_loss': None,
        'signal_type': 'swing_trade_2'
    }


def momentum_breakout(data):
    """
    BALANCED: Was too restrictive (16→3 trades)

    Target: 10-15 trades with 65-70% win rate

    LOOSENED:
    - Consolidation: Made optional (not required)
    - Volume: 1.6x → 1.4x
    - Volume surge score: Removed
    - ADX: 25 → 23
    - ROC: Removed
    - OBV: Made optional
    - Stochastic: Removed

    KEPT:
    - Breaking 20-day high
    - EMA alignment
    - MACD bullish
    - RSI 48-75
    - Distance from EMA8 < 6%
    """
    close = data.get('close', 0)
    ema8 = data.get('ema8', 0)
    ema20 = data.get('ema20', 0)
    ema50 = data.get('ema50', 0)
    sma200 = data.get('sma200', 0)
    rsi = data.get('rsi', 50)
    adx = data.get('adx', 0)
    volume_ratio = data.get('volume_ratio', 0)
    macd = data.get('macd', 0)
    macd_signal = data.get('macd_signal', 0)
    macd_hist = data.get('macd_histogram', 0)

    raw_data = data.get('raw', None)
    if raw_data is None or len(raw_data) < 20:
        return _no_signal('Insufficient data')

    high_20d = raw_data['high'].iloc[-20:].max()

    # 1. BREAKOUT: Price breaking above 20-day high (within 2%)
    if close < high_20d * 0.98:
        return _no_signal('Not breaking out')

    # 2. STRUCTURE: All EMAs bullishly aligned
    if not (close > ema8 > ema20 > ema50 > sma200):
        return _no_signal('EMAs not aligned')

    # 3. LOOSENED: ADX > 23 (from 25)
    if adx < 23:
        return _no_signal(f'ADX {adx:.0f} too weak')

    # 4. MACD bullish
    if macd <= macd_signal or macd_hist <= 0:
        return _no_signal('MACD not bullish')

    # 5. LOOSENED: Volume (1.4x from 1.6x)
    if volume_ratio < 1.4:
        return _no_signal(f'Volume {volume_ratio:.1f}x too low')

    # 6. RSI (48-75)
    if not (48 <= rsi <= 75):
        return _no_signal(f'RSI {rsi:.0f} outside 48-75 range')

    # 7. Distance from EMA8 (< 6%)
    distance_from_ema8 = abs((close - ema8) / ema8 * 100) if ema8 > 0 else 100
    if distance_from_ema8 > 6.0:
        return _no_signal(f'Too extended from EMA8 ({distance_from_ema8:.1f}%)')

    return {
        'side': 'buy',
        'msg': f'🚀 Momentum: ADX {adx:.0f}, Vol {volume_ratio:.1f}x, RSI {rsi:.0f}',
        'limit_price': close,
        'stop_loss': None,
        'signal_type': 'momentum_breakout'
    }


def consolidation_breakout(data):
    """
    REVERTED: My enhancements made it worse (84.8%→74.5%)

    Going back to ORIGINAL logic (before my changes)
    """
    close = data.get('close', 0)
    ema20 = data.get('ema20', 0)
    ema50 = data.get('ema50', 0)
    sma200 = data.get('sma200', 0)
    rsi = data.get('rsi', 50)
    volume_ratio = data.get('volume_ratio', 0)

    raw_data = data.get('raw', None)
    if raw_data is None or len(raw_data) < 20:
        return _no_signal('Insufficient data')

    # Calculate consolidation metrics
    recent_highs = raw_data['high'].iloc[-10:].values
    recent_lows = raw_data['low'].iloc[-10:].values
    consolidation_range = (max(recent_highs) - min(recent_lows)) / min(recent_lows) * 100

    high_10d = max(recent_highs)

    # ORIGINAL LOGIC (no changes)
    if consolidation_range > 12.0:
        return _no_signal(f'Range {consolidation_range:.1f}% too wide')

    if close <= sma200 or ema20 <= ema50:
        return _no_signal('Weak trend structure')

    if close < high_10d * 0.995:
        return _no_signal('Not breaking out')

    if volume_ratio < 1.2:
        return _no_signal(f'Volume {volume_ratio:.1f}x too low')

    if not (45 <= rsi <= 72):
        return _no_signal(f'RSI {rsi:.0f} outside 45-72')

    distance_to_ema20 = abs((close - ema20) / ema20 * 100) if ema20 > 0 else 100
    if distance_to_ema20 > 10.0:
        return _no_signal(f'Too far from EMA20')

    return {
        'side': 'buy',
        'msg': f'📦 Consolidation: {consolidation_range:.1f}% range, Vol {volume_ratio:.1f}x',
        'limit_price': close,
        'stop_loss': None,
        'signal_type': 'consolidation_breakout'
    }


def golden_cross(data):
    """
    SIMPLIFIED: Was too complex (0 trades)

    Now much simpler - just detect fresh golden cross with basic confirmation
    """
    ema20 = data.get('ema20', 0)
    ema50 = data.get('ema50', 0)
    sma200 = data.get('sma200', 0)
    rsi = data.get('rsi', 50)
    volume_ratio = data.get('volume_ratio', 0)
    close = data.get('close', 0)
    adx = data.get('adx', 0)

    # Calculate distance of EMA50 from SMA200
    distance_pct = ((ema50 - sma200) / sma200 * 100) if sma200 > 0 else -100

    # SIMPLIFIED: Just look for fresh cross (0-8% above)
    if not (0 <= distance_pct <= 8.0):
        return _no_signal('No fresh golden cross')

    # Basic confirmations only
    if adx < 18:
        return _no_signal('ADX too weak')

    if volume_ratio < 1.2:
        return _no_signal('Volume too low')

    if not (45 <= rsi <= 70):
        return _no_signal(f'RSI outside range')

    if not (close > ema20 > ema50):
        return _no_signal('Price structure weak')

    return {
        'side': 'buy',
        'msg': f'✨ Golden Cross: {distance_pct:.1f}% above SMA200, ADX {adx:.0f}',
        'limit_price': close,
        'stop_loss': None,
        'signal_type': 'golden_cross'
    }


def bollinger_buy(data):
    """
    REVERTED TO ORIGINAL: Strict filters that gave 100% win rate

    Back to original settings:
    - Bollinger proximity: 3% (NOT 4%)
    - RSI range: 28-45 (NOT 25-48)
    - Volume: 1.3x (NOT 1.2x)

    Goal: 6-10 trades with 90%+ win rate (quality over quantity)
    """
    rsi = data.get('rsi', 50)
    volume_ratio = data.get('volume_ratio', 0)
    sma200 = data.get('sma200', 0)
    bollinger_lower = data.get('bollinger_lower', 0)
    close = data.get('close', 0)
    daily_change_pct = data.get('daily_change_pct', 0)
    obv_trending_up = data.get('obv_trending_up', False)

    # ORIGINAL: Price at lower Bollinger (within 3% - STRICT)
    if bollinger_lower == 0 or close > bollinger_lower * 1.03:
        return _no_signal('Not at lower Bollinger')

    # Above 200 SMA (uptrend)
    if close <= sma200:
        return _no_signal('Below 200 SMA')

    # ORIGINAL: RSI oversold (28-45 - STRICT)
    if not (28 <= rsi <= 45):
        return _no_signal(f'RSI not in range')

    # ORIGINAL: Volume confirmation (1.3x - STRICT)
    if volume_ratio < 1.3:
        return _no_signal('Volume too low')

    # OBV confirmation
    if not obv_trending_up:
        return _no_signal('OBV not confirming')

    # Starting to bounce
    if daily_change_pct <= 0:
        return _no_signal('Not bouncing yet')

    return {
        'side': 'buy',
        'msg': f'🎪 Bollinger Bounce: RSI {rsi:.0f}, Vol {volume_ratio:.1f}x, OBV+',
        'limit_price': close,
        'stop_loss': None,
        'signal_type': 'bollinger_buy',
    }


def _no_signal(reason):
    """Helper function to return consistent 'no signal' message"""
    return {
        'side': 'hold',
        'msg': f'No signal: {reason}',
        'limit_price': None,
        'stop_loss': None,
        'signal_type': 'no_signal'
    }


# =======================================================================================================================
# STRATEGY REGISTRY - BALANCED ORDER
# =======================================================================================================================

BUY_STRATEGIES = {
    'consolidation_breakout': consolidation_breakout,  # Reverted to original
    'swing_trade_1': swing_trade_1,  # Keep enhancements (working)
    'swing_trade_2': swing_trade_2,  # Fixed (was 0 trades)
    'golden_cross': golden_cross,  # Simplified
    'bollinger_buy': bollinger_buy,  # REVERTED to strict original
    'momentum_breakout': momentum_breakout,  # Loosened
}