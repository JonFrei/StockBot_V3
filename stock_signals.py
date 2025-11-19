import stock_data
from datetime import datetime

tickers = ""
current_date = datetime.today()


def buy_signals(data, buy_signal_list, spy_data=None):
    """
    Check multiple buy strategies and return first valid signal
    Returns dict or None

    NOTE: 200 SMA / SPY regime check is now handled in market_regime.py
    """
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
# BUY SIGNALS - PRIORITY 1 IMPROVEMENTS
# ===================================================================================

def swing_trade_1(data):
    """
    PRIORITY 3A: LOOSENED from restrictive requirements

    Changes:
    - RSI: 52-68 → 48-70 (wider range)
    - Volume: 1.4x → 1.2x (easier to meet)
    - ADX: 20 → 18 (allow slightly weaker trends)

    Goal: Increase trade frequency while maintaining quality
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
    adx = data.get('adx', 0)

    # Trend confirmation
    if not (ema20 > ema50):
        return _no_signal('No uptrend')

    # Price above both EMAs and 200 SMA
    if not (close > ema20 and close > sma200):
        return _no_signal('Price below key levels')

    # LOOSENED: RSI sweet spot (48-70 from 52-68)
    if not (48 <= rsi <= 70):
        return _no_signal(f'RSI {rsi:.0f} not in 48-70 range')

    # LOOSENED: Volume (1.2x from 1.4x)
    if volume_ratio < 1.2:
        return _no_signal(f'Volume {volume_ratio:.1f}x too low')

    # MACD bullish
    if macd <= macd_signal:
        return _no_signal('MACD not bullish')

    # OBV confirmation
    if not obv_trending_up:
        return _no_signal('OBV not confirming')

    # LOOSENED: ADX requirement (18 from 20)
    if adx < 18:
        return _no_signal(f'ADX {adx:.0f} too weak')

    return {
        'side': 'buy',
        'msg': f'✅ Swing1: RSI {rsi:.0f}, Vol {volume_ratio:.1f}x, ADX {adx:.0f}, OBV+',
        'limit_price': close,
        'stop_loss': None,
        'signal_type': 'swing_trade_1'
    }


def swing_trade_2(data):
    """
    PRIORITY 3B: LOOSENED for higher volume (76.2% WR, only 21 trades)

    Changes:
    - Pullback: 3-10% → 2-12% (catch more pullbacks)
    - Volume: 1.25x → 1.15x (easier to meet)
    - RSI: 40-68 (unchanged - already good)
    - ADX: 18 (unchanged)

    Goal: Increase trade frequency on best-performing signal
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
    adx = data.get('adx', 0)

    # 1. Price above 200 SMA
    if close <= sma200:
        return _no_signal('Below 200 SMA')

    # 2. EMA structure
    if ema20 <= ema50:
        return _no_signal('EMA20 not above EMA50')

    # 3. LOOSENED: Pullback depth (2-12% from 3-10%)
    ema20_distance = abs((close - ema20) / ema20 * 100) if ema20 > 0 else 100
    if not (2.0 <= ema20_distance <= 12.0):
        return _no_signal(f'Pullback {ema20_distance:.1f}% not in 2-12% range')

    # 4. RSI (40-68 unchanged)
    if not (40 <= rsi <= 68):
        return _no_signal(f'RSI {rsi:.0f} outside 40-68')

    # 5. LOOSENED: Volume (1.15x from 1.25x)
    if volume_ratio < 1.15:
        return _no_signal(f'Volume {volume_ratio:.1f}x below 1.15x')

    # 6. MACD momentum
    if macd <= macd_signal:
        return _no_signal('MACD not bullish')

    # 7. OBV confirmation
    if not obv_trending_up:
        return _no_signal('OBV not confirming')

    # 8. ADX requirement (18 unchanged)
    if adx < 18:
        return _no_signal(f'ADX {adx:.0f} too weak')

    # 9. Price stabilization (-4% unchanged)
    if daily_change_pct < -4.0:
        return _no_signal(f'Price dropping too fast ({daily_change_pct:.1f}%)')

    return {
        'side': 'buy',
        'msg': f'✅ Pullback: {ema20_distance:.1f}% from EMA20, RSI {rsi:.0f}, ADX {adx:.0f}, OBV+',
        'limit_price': close,
        'stop_loss': None,
        'signal_type': 'swing_trade_2'
    }


def consolidation_breakout(data):
    """
    ⭐ PRIORITY 1: LOOSENED - 75% win rate, increase trade frequency

    Changes:
    - Range: 12% → 15% (allow slightly wider consolidations)
    - Volume: 1.2x → 1.15x (slightly lower volume requirement)
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

    # ⭐ LOOSENED: Range 15% (from 12%)
    if consolidation_range > 15.0:
        return _no_signal(f'Range {consolidation_range:.1f}% too wide')

    if close <= sma200 or ema20 <= ema50:
        return _no_signal('Weak trend structure')

    if close < high_10d * 0.995:
        return _no_signal('Not breaking out')

    # ⭐ LOOSENED: Volume 1.15x (from 1.2x)
    if volume_ratio < 1.15:
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
    ⭐ PRIORITY 1: LOOSENED - 81.8% win rate, get more trades

    Changes:
    - Distance range: 0-8% → 0-10% (catch slightly later crosses)
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

    # ⭐ LOOSENED: Fresh cross 0-10% (from 0-8%)
    if not (0 <= distance_pct <= 10.0):
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
    PRIORITY 2: IMPROVED bollinger_buy from 33.3% to 70%+

    Analysis: Was too rare and caught bad reversals

    NEW FILTERS ADDED:
    - ADX > 20 (require strong trend, not choppy)
    - EMA20 > EMA50 (uptrend structure confirmation)
    - MACD bullish (momentum confirmation)
    - Tighter RSI: 28-45 → 30-42 (more oversold)
    - Tighter Bollinger proximity: 3% → 2% (closer to band)
    - Higher volume: 1.3x → 1.5x (stronger conviction)

    Strategy: Only catch strong bounces in confirmed uptrends
    """
    rsi = data.get('rsi', 50)
    volume_ratio = data.get('volume_ratio', 0)
    sma200 = data.get('sma200', 0)
    bollinger_lower = data.get('bollinger_lower', 0)
    close = data.get('close', 0)
    daily_change_pct = data.get('daily_change_pct', 0)
    obv_trending_up = data.get('obv_trending_up', False)
    ema20 = data.get('ema20', 0)
    ema50 = data.get('ema50', 0)
    adx = data.get('adx', 0)
    macd = data.get('macd', 0)
    macd_signal = data.get('macd_signal', 0)

    # NEW: Require strong trend (not choppy/range-bound)
    if adx < 20:
        return _no_signal('ADX too weak for Bollinger')

    # NEW: Require uptrend structure
    if not (ema20 > ema50):
        return _no_signal('No uptrend structure')

    # Price at lower Bollinger (TIGHTENED: within 2% from 3%)
    if bollinger_lower == 0 or close > bollinger_lower * 1.02:
        return _no_signal('Not close enough to lower Bollinger')

    # Above 200 SMA (uptrend)
    if close <= sma200:
        return _no_signal('Below 200 SMA')

    # TIGHTENED: RSI oversold (30-42 from 28-45)
    if not (30 <= rsi <= 42):
        return _no_signal(f'RSI {rsi:.0f} not in 30-42 range')

    # TIGHTENED: Volume confirmation (1.5x from 1.3x)
    if volume_ratio < 1.5:
        return _no_signal(f'Volume {volume_ratio:.1f}x below 1.5x')

    # NEW: MACD momentum confirmation
    if macd <= macd_signal:
        return _no_signal('MACD not bullish')

    # OBV confirmation
    if not obv_trending_up:
        return _no_signal('OBV not confirming')

    # Starting to bounce
    if daily_change_pct <= 0:
        return _no_signal('Not bouncing yet')

    return {
        'side': 'buy',
        'msg': f'🎪 Bollinger Bounce: RSI {rsi:.0f}, Vol {volume_ratio:.1f}x, ADX {adx:.0f}, OBV+',
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
# STRATEGY REGISTRY
# =======================================================================================================================

BUY_STRATEGIES = {
    'consolidation_breakout': consolidation_breakout,
    'swing_trade_1': swing_trade_1,
    'swing_trade_2': swing_trade_2,
    'golden_cross': golden_cross,
    'bollinger_buy': bollinger_buy,
}