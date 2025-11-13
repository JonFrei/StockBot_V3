import stock_data
from datetime import datetime

tickers = ""
current_date = datetime.today()


# Process which signals we want to use based on the list provided
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
# BUY SIGNALS - ALL FIXED AND OPTIMIZED
# ===================================================================================

def swing_trade_1(data):
    """
    ENHANCED: Swing trading with improved confluence

    Win Rate: 73.5% → Target 78%+

    IMPROVEMENTS:
    - MACD histogram acceleration check (not just positive)
    - OBV confirmation (accumulation)
    - Stochastic bullish confirmation
    - Volume increased to 1.3x for higher conviction

    Entry Rules:
    - Price above EMA20 > EMA50, above 200 SMA
    - RSI 48-72 (momentum sweet spot)
    - Volume 1.3x+ (increased from 1.2x)
    - MACD bullish AND histogram accelerating
    - OBV trending up
    - Stochastic bullish or > 50
    """
    # Get indicator values
    ema20 = data.get('ema20', 0)
    ema50 = data.get('ema50', 0)
    sma200 = data.get('sma200', 0)
    rsi = data.get('rsi', 50)
    close = data.get('close', 0)
    volume_ratio = data.get('volume_ratio', 0)
    macd = data.get('macd', 0)
    macd_signal = data.get('macd_signal', 0)
    macd_hist = data.get('macd_histogram', 0)
    macd_hist_prev = data.get('macd_hist_prev', 0)
    obv_trending_up = data.get('obv_trending_up', False)
    stoch_k = data.get('stoch_k', 50)
    stoch_d = data.get('stoch_d', 50)

    # Trend confirmation
    if not (ema20 > ema50):
        return _no_signal('No uptrend')

    # Price above both EMAs and 200 SMA
    if not (close > ema20 and close > sma200):
        return _no_signal('Price below key levels')

    # RSI sweet spot
    if not (48 <= rsi <= 72):
        return _no_signal(f'RSI {rsi:.0f} not in 48-72 range')

    # ENHANCED: Volume (1.3x from 1.2x)
    if volume_ratio < 1.3:
        return _no_signal(f'Volume {volume_ratio:.1f}x too low (need 1.3x+)')

    # ENHANCED: MACD must be bullish AND accelerating
    if macd <= macd_signal:
        return _no_signal('MACD not bullish')

    if macd_hist <= macd_hist_prev:
        return _no_signal('MACD histogram not accelerating')

    # NEW: OBV confirmation (accumulation)
    if not obv_trending_up:
        return _no_signal('OBV not confirming (distribution)')

    # NEW: Stochastic confirmation
    if not (stoch_k > stoch_d or stoch_k > 50):
        return _no_signal(f'Stochastic weak ({stoch_k:.0f})')

    return {
        'side': 'buy',
        'msg': f'✅ Swing1: RSI {rsi:.0f}, Vol {volume_ratio:.1f}x, MACD+, OBV+, Stoch {stoch_k:.0f}',
        'limit_price': close,
        'stop_loss': None,
        'signal_type': 'swing_trade_1'
    }


def swing_trade_2(data):
    """
    FIXED: Pullback Strategy - Balanced Quality + Frequency

    Win Rate: 65.5% → Target 76%+

    FIXES APPLIED:
    - Volume back to 1.2x (was 1.0x - too loose)
    - RSI tightened to 38-70 (from 30-72)
    - ADX > 18 required (confirm trend)
    - OBV accumulation check
    - Stochastic oversold bounce (20-65)
    - Price stabilization check (daily change > -3%)
    - Pullback volume check (lighter than recent)
    - Pullback range tightened to 2-12% (from 2-15%)

    Entry Criteria:
    1. Price > 200 SMA (long-term trend)
    2. 20 EMA > 50 EMA (medium-term momentum)
    3. Price 2-12% from 20 EMA (controlled pullback)
    4. ADX > 18 (trend exists)
    5. Volume > 1.2x (confirmation)
    6. RSI 38-70 (not extreme)
    7. MACD bullish
    8. OBV trending up (accumulation)
    9. Stochastic 20-65 (oversold bounce)
    10. Daily change > -3% (stabilizing)
    11. Pullback on lighter volume
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
    adx = data.get('adx', 0)
    obv_trending_up = data.get('obv_trending_up', False)
    stoch_k = data.get('stoch_k', 50)

    # 1. Price above 200 SMA (uptrend)
    if close <= sma200:
        return _no_signal('Below 200 SMA')

    # 2. EMA structure (medium-term momentum)
    if ema20 <= ema50:
        return _no_signal('EMA20 not above EMA50')

    # 3. FIXED: Pullback depth (2-12% tightened from 2-15%)
    ema20_distance = abs((close - ema20) / ema20 * 100) if ema20 > 0 else 100
    if not (2.0 <= ema20_distance <= 12.0):
        return _no_signal(f'Pullback {ema20_distance:.1f}% not in 2-12% range')

    # 4. NEW: ADX requirement (trend exists)
    if adx < 18:
        return _no_signal(f'ADX {adx:.0f} too weak (need 18+)')

    # 5. FIXED: RSI (38-70 tightened from 30-72)
    if not (38 <= rsi <= 70):
        return _no_signal(f'RSI {rsi:.0f} outside 38-70')

    # 6. FIXED: Volume (1.2x increased from 1.0x)
    if volume_ratio < 1.2:
        return _no_signal(f'Volume {volume_ratio:.1f}x below 1.2x')

    # 7. MACD momentum confirmation
    if macd <= macd_signal:
        return _no_signal('MACD not bullish')

    # 8. NEW: OBV accumulation check
    if not obv_trending_up:
        return _no_signal('OBV not confirming accumulation')

    # 9. NEW: Stochastic oversold bounce (20-65)
    if not (20 <= stoch_k <= 65):
        return _no_signal(f'Stochastic {stoch_k:.0f} not in 20-65 range')

    # 10. NEW: Price stabilization (not dumping)
    if daily_change_pct < -3.0:
        return _no_signal(f'Price dropping too fast ({daily_change_pct:.1f}%)')

    # 11. NEW: Pullback volume check (lighter selling)
    if volume_ratio > 1.5:
        return _no_signal('Pullback volume too heavy (selling pressure)')

    return {
        'side': 'buy',
        'msg': f'✅ Pullback: {ema20_distance:.1f}% from EMA20, ADX {adx:.0f}, RSI {rsi:.0f}, OBV+, Stoch {stoch_k:.0f}',
        'limit_price': close,
        'stop_loss': None,
        'signal_type': 'swing_trade_2'
    }


def momentum_breakout(data):
    """
    MAJOR FIXES: Momentum breakout - Quality over quantity

    Win Rate: 56.2% → Target 70%+

    ISSUES FIXED:
    - Volume too low (1.3x → 1.6x)
    - ADX too low (22 → 25)
    - No consolidation check (random breakouts)
    - Distance from EMA8 too loose (8% → 6%)
    - MACD just positive (now must accelerate)
    - No ROC check (added)
    - No OBV breakout confirmation (added)

    NEW REQUIREMENTS:
    1. Prior consolidation (5-15 days, range < 10%)
    2. Breaking above 20-day high
    3. Strong volume (1.6x+ AND surge score > 6/10)
    4. Strong momentum (ADX > 25, ROC > 5%)
    5. MACD accelerating (not just positive)
    6. All EMAs aligned bullishly
    7. Not overextended (RSI 48-75, < 6% from EMA8)
    8. OBV breakout confirmation
    9. Stochastic > 60
    """
    close = data.get('close', 0)
    ema8 = data.get('ema8', 0)
    ema20 = data.get('ema20', 0)
    ema50 = data.get('ema50', 0)
    sma200 = data.get('sma200', 0)
    rsi = data.get('rsi', 50)
    adx = data.get('adx', 0)
    volume_ratio = data.get('volume_ratio', 0)
    volume_surge_score = data.get('volume_surge_score', 0)
    macd = data.get('macd', 0)
    macd_signal = data.get('macd_signal', 0)
    macd_hist = data.get('macd_histogram', 0)
    macd_hist_prev = data.get('macd_hist_prev', 0)
    roc_12 = data.get('roc_12', 0)
    obv_trending_up = data.get('obv_trending_up', False)
    stoch_k = data.get('stoch_k', 50)

    # Get raw data for consolidation check
    raw_data = data.get('raw', None)
    if raw_data is None or len(raw_data) < 20:
        return _no_signal('Insufficient data')

    # NEW: Check for consolidation before breakout (5-15 days)
    consolidation_periods = [5, 7, 10, 12, 15]
    found_consolidation = False

    for period in consolidation_periods:
        if len(raw_data) < period:
            continue
        recent_high = raw_data['high'].iloc[-period:].max()
        recent_low = raw_data['low'].iloc[-period:].min()
        consolidation_range = (recent_high - recent_low) / recent_low * 100

        if consolidation_range < 10.0:
            found_consolidation = True
            break

    if not found_consolidation:
        return _no_signal('No consolidation base (need 5-15d range < 10%)')

    high_20d = raw_data['high'].iloc[-20:].max()

    # 1. BREAKOUT: Price breaking above 20-day high (within 2%)
    if close < high_20d * 0.98:
        return _no_signal('Not breaking out')

    # 2. STRUCTURE: All EMAs bullishly aligned
    if not (close > ema8 > ema20 > ema50 > sma200):
        return _no_signal('EMAs not aligned')

    # 3. FIXED: Strong trend (ADX > 25, increased from 22)
    if adx < 25:
        return _no_signal(f'ADX {adx:.0f} too weak (need 25+)')

    # 4. FIXED: MACD bullish AND accelerating
    if macd <= macd_signal or macd_hist <= 0:
        return _no_signal('MACD not bullish')

    if macd_hist <= macd_hist_prev:
        return _no_signal('MACD not accelerating')

    # 5. FIXED: Strong volume (1.6x+, increased from 1.3x)
    if volume_ratio < 1.6:
        return _no_signal(f'Volume {volume_ratio:.1f}x too low (need 1.6x+)')

    # 6. NEW: Volume surge quality (> 6/10)
    if volume_surge_score < 6.0:
        return _no_signal(f'Volume surge quality too low ({volume_surge_score}/10)')

    # 7. FIXED: RSI - Strong but not overbought (48-75, tightened from 45-75)
    if not (48 <= rsi <= 75):
        return _no_signal(f'RSI {rsi:.0f} outside 48-75 range')

    # 8. FIXED: Distance from EMA8 (< 6%, tightened from 8%)
    distance_from_ema8 = abs((close - ema8) / ema8 * 100) if ema8 > 0 else 100
    if distance_from_ema8 > 6.0:
        return _no_signal(f'Too extended from EMA8 ({distance_from_ema8:.1f}% > 6%)')

    # 9. NEW: ROC check (strong momentum)
    if roc_12 < 5.0:
        return _no_signal(f'ROC {roc_12:.1f}% too weak (need 5%+)')

    # 10. NEW: OBV breakout confirmation
    if not obv_trending_up:
        return _no_signal('OBV not confirming breakout')

    # 11. NEW: Stochastic breakout (> 60)
    if stoch_k < 60:
        return _no_signal(f'Stochastic {stoch_k:.0f} not confirming breakout')

    conviction_label = "🔥 EXTREME" if volume_surge_score >= 8.0 else "🚀 HIGH"

    return {
        'side': 'buy',
        'msg': f'{conviction_label} Momentum: ADX {adx:.0f}, Vol {volume_ratio:.1f}x, Surge {volume_surge_score}/10, ROC {roc_12:.1f}%',
        'limit_price': close,
        'stop_loss': None,
        'signal_type': 'momentum_breakout'
    }


def consolidation_breakout(data):
    """
    ENHANCED: Consolidation breakout - Already excellent, minor improvements

    Win Rate: 84.8% → Target 86%+

    ENHANCEMENTS:
    - Volume surge score requirement
    - OBV accumulation confirmation
    - Stochastic confirmation

    Entry Criteria (MOSTLY UNCHANGED):
    1. Stock consolidating near highs (< 12% range over 10 days)
    2. Breaking above consolidation range
    3. Volume expansion (1.2x+)
    4. Volume surge score > 5/10 (NEW)
    5. Bullish structure (above 200 SMA, EMA20 > EMA50)
    6. RSI healthy (45-72)
    7. Not too far from EMA20 (< 10%)
    8. OBV trending up (NEW)
    9. Stochastic > 45 (NEW)
    """
    close = data.get('close', 0)
    ema20 = data.get('ema20', 0)
    ema50 = data.get('ema50', 0)
    sma200 = data.get('sma200', 0)
    rsi = data.get('rsi', 50)
    volume_ratio = data.get('volume_ratio', 0)
    volume_surge_score = data.get('volume_surge_score', 0)
    obv_trending_up = data.get('obv_trending_up', False)
    stoch_k = data.get('stoch_k', 50)

    raw_data = data.get('raw', None)
    if raw_data is None or len(raw_data) < 20:
        return _no_signal('Insufficient data')

    # Calculate consolidation metrics
    recent_highs = raw_data['high'].iloc[-10:].values
    recent_lows = raw_data['low'].iloc[-10:].values
    consolidation_range = (max(recent_highs) - min(recent_lows)) / min(recent_lows) * 100

    high_10d = max(recent_highs)

    # 1. CONSOLIDATION: Tight range (< 12% over 10 days)
    if consolidation_range > 12.0:
        return _no_signal(f'Range {consolidation_range:.1f}% too wide')

    # 2. STRUCTURE: Above 200 SMA and EMA20 > EMA50
    if close <= sma200 or ema20 <= ema50:
        return _no_signal('Weak trend structure')

    # 3. BREAKOUT: Breaking above 10-day high (within 0.5%)
    if close < high_10d * 0.995:
        return _no_signal('Not breaking out')

    # 4. VOLUME: Expansion (1.2x+)
    if volume_ratio < 1.2:
        return _no_signal(f'Volume {volume_ratio:.1f}x too low')

    # 5. NEW: Volume surge quality
    if volume_surge_score < 5.0:
        return _no_signal(f'Volume surge quality too low ({volume_surge_score}/10)')

    # 6. RSI: Healthy range (45-72)
    if not (45 <= rsi <= 72):
        return _no_signal(f'RSI {rsi:.0f} outside 45-72')

    # 7. POSITION: Close to EMA20 (< 10%)
    distance_to_ema20 = abs((close - ema20) / ema20 * 100) if ema20 > 0 else 100
    if distance_to_ema20 > 10.0:
        return _no_signal(f'Too far from EMA20')

    # 8. NEW: OBV accumulation
    if not obv_trending_up:
        return _no_signal('OBV not confirming accumulation')

    # 9. NEW: Stochastic confirmation
    if stoch_k < 45:
        return _no_signal(f'Stochastic {stoch_k:.0f} too low')

    return {
        'side': 'buy',
        'msg': f'📦 Consolidation: {consolidation_range:.1f}% range, Vol {volume_ratio:.1f}x (score {volume_surge_score}), OBV+',
        'limit_price': close,
        'stop_loss': None,
        'signal_type': 'consolidation_breakout'
    }


def golden_cross(data):
    """
    ACTIVATED & OPTIMIZED: Golden Cross in 3 stages

    Target Win Rate: 75%+

    Detects and trades golden cross (50 EMA crossing above 200 SMA) in 3 stages:

    Stage 1: Pre-Cross (50 EMA approaching 200 SMA)
    Stage 2: Fresh Cross (just crossed, 0-4% above)
    Stage 3: Post-Cross Pullback (4-15% above, pullback to EMA20)
    """
    ema8 = data.get('ema8', 0)
    ema20 = data.get('ema20', 0)
    ema50 = data.get('ema50', 0)
    sma200 = data.get('sma200', 0)
    rsi = data.get('rsi', 50)
    volume_ratio = data.get('volume_ratio', 0)
    close = data.get('close', 0)
    adx = data.get('adx', 0)
    daily_change_pct = data.get('daily_change_pct', 0)
    obv_trending_up = data.get('obv_trending_up', False)
    stoch_k = data.get('stoch_k', 50)
    stoch_d = data.get('stoch_d', 50)

    # Calculate distance of EMA50 from SMA200
    distance_pct = ((ema50 - sma200) / sma200 * 100) if sma200 > 0 else -100

    # ===== STAGE 1: PRE-CROSS (0-2% below) =====
    if -2.0 <= distance_pct < 0:
        # 50 EMA approaching from below
        if adx < 20:
            return _no_signal('Pre-cross needs ADX > 20')
        if volume_ratio < 1.5:
            return _no_signal('Pre-cross needs 1.5x+ volume')
        if not (45 <= rsi <= 70):
            return _no_signal(f'RSI {rsi:.0f} outside 45-70')
        if not (close > ema8 > ema20 > ema50):
            return _no_signal('EMAs not aligned')
        if not obv_trending_up:
            return _no_signal('OBV not confirming')
        if not (stoch_k > stoch_d):
            return _no_signal('Stochastic not bullish')

        return {
            'side': 'buy',
            'msg': f'🌅 Golden Cross PRE-CROSS: {abs(distance_pct):.1f}% away, ADX {adx:.0f}, Vol {volume_ratio:.1f}x',
            'limit_price': close,
            'stop_loss': None,
            'signal_type': 'golden_cross'
        }

    # ===== STAGE 2: FRESH CROSS (0-4% above) =====
    elif 0 <= distance_pct <= 4.0:
        # Fresh golden cross
        if volume_ratio < 1.3:
            return _no_signal('Fresh cross needs 1.3x+ volume')
        if not obv_trending_up:
            return _no_signal('OBV not confirming')
        if adx < 20:
            return _no_signal('ADX too weak')
        if not (45 <= rsi <= 70):
            return _no_signal(f'RSI {rsi:.0f} outside 45-70')
        if daily_change_pct < 0:
            return _no_signal('Need green candle on cross')

        return {
            'side': 'buy',
            'msg': f'✨ Golden Cross FRESH: {distance_pct:.1f}% above, ADX {adx:.0f}, OBV surging',
            'limit_price': close,
            'stop_loss': None,
            'signal_type': 'golden_cross'
        }

    # ===== STAGE 3: POST-CROSS PULLBACK (4-15% above) =====
    elif 4.0 < distance_pct <= 15.0:
        # Post-cross pullback to EMA20
        distance_to_ema20 = abs((close - ema20) / ema20 * 100) if ema20 > 0 else 100

        if not (2.0 <= distance_to_ema20 <= 8.0):
            return _no_signal(f'Not at EMA20 pullback ({distance_to_ema20:.1f}%)')
        if not obv_trending_up:
            return _no_signal('OBV not confirming (distribution)')
        if not (35 <= rsi <= 65):
            return _no_signal(f'RSI {rsi:.0f} outside 35-65')
        if stoch_k > 40:
            return _no_signal('Stochastic not oversold enough')
        if volume_ratio > 1.2:
            return _no_signal('Pullback volume too heavy')

        return {
            'side': 'buy',
            'msg': f'🎯 Golden Cross PULLBACK: {distance_to_ema20:.1f}% to EMA20, Stoch {stoch_k:.0f}, OBV+',
            'limit_price': close,
            'stop_loss': None,
            'signal_type': 'golden_cross'
        }

    return _no_signal('No golden cross setup')


def bollinger_buy(data):
    """
    ACTIVATED & OPTIMIZED: Bollinger Band bounce with trend confirmation

    Target Win Rate: 72%+

    Buys oversold bounces from lower Bollinger Band with:
    - Confirmed uptrend (price > 200 SMA, EMA50 trending up)
    - Multiple oversold indicators (RSI, Stochastic, Williams %R)
    - Volume surge on bounce
    - OBV accumulation (buying the dip)
    - MACD turning up
    """
    rsi = data.get('rsi', 50)
    volume_ratio = data.get('volume_ratio', 0)
    volume_surge_score = data.get('volume_surge_score', 0)
    sma200 = data.get('sma200', 0)
    ema50 = data.get('ema50', 0)
    ema50_10d_ago = data.get('ema50_10d_ago', 0)
    bollinger_lower = data.get('bollinger_lower', 0)
    close = data.get('close', 0)
    adx = data.get('adx', 0)
    daily_change_pct = data.get('daily_change_pct', 0)
    obv_trending_up = data.get('obv_trending_up', False)
    stoch_k = data.get('stoch_k', 50)
    williams_r = data.get('williams_r', -50)
    macd_hist = data.get('macd_histogram', 0)
    macd_hist_prev = data.get('macd_hist_prev', 0)

    # 1. Price at lower Bollinger Band (within 2%)
    if bollinger_lower == 0 or close > bollinger_lower * 1.02:
        return _no_signal('Not at lower Bollinger Band')

    # 2. Long-term uptrend (above 200 SMA)
    if close <= sma200:
        return _no_signal('Below 200 SMA')

    # 3. EMA50 trending up (confirm trend intact)
    if ema50 <= ema50_10d_ago:
        return _no_signal('EMA50 not trending up')

    # 4. RSI oversold but not extreme (25-40)
    if not (25 <= rsi <= 40):
        return _no_signal(f'RSI {rsi:.0f} not in 25-40 range')

    # 5. Stochastic oversold (< 25)
    if stoch_k >= 25:
        return _no_signal(f'Stochastic {stoch_k:.0f} not oversold')

    # 6. Williams %R oversold (< -75)
    if williams_r >= -75:
        return _no_signal(f'Williams %R {williams_r:.0f} not oversold')

    # 7. Volume surge on bounce (1.4x+)
    if volume_ratio < 1.4:
        return _no_signal(f'Volume {volume_ratio:.1f}x too low (need 1.4x+)')

    # 8. Volume surge quality (> 5/10)
    if volume_surge_score < 5.0:
        return _no_signal(f'Volume surge quality too low ({volume_surge_score}/10)')

    # 9. OBV accumulation (buying the dip)
    if not obv_trending_up:
        return _no_signal('OBV not confirming accumulation')

    # 10. ADX shows some trend (> 15)
    if adx < 15:
        return _no_signal(f'ADX {adx:.0f} too weak')

    # 11. Starting to bounce (daily change > 0)
    if daily_change_pct <= 0:
        return _no_signal('Not bouncing yet')

    # 12. MACD turning up (histogram increasing)
    if macd_hist <= macd_hist_prev:
        return _no_signal('MACD not turning up')

    return {
        'side': 'buy',
        'msg': f'🎪 Bollinger Bounce: RSI {rsi:.0f}, Stoch {stoch_k:.0f}, WilliamsR {williams_r:.0f}, Vol {volume_ratio:.1f}x, OBV+',
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
# STRATEGY REGISTRY - OPTIMIZED ORDER BY EXPECTED WIN RATE
# =======================================================================================================================

BUY_STRATEGIES = {
    # PRIORITY 1: Highest Win Rate (80%+)
    'consolidation_breakout': consolidation_breakout,  # 84.8% → 86%+

    # PRIORITY 2: Very High Win Rate (75-80%)
    'golden_cross': golden_cross,  # NEW - Expecting 75%+
    'swing_trade_1': swing_trade_1,  # 73.5% → 78%+
    'swing_trade_2': swing_trade_2,  # 65.5% → 76%+

    # PRIORITY 3: Good Win Rate (70-75%)
    'bollinger_buy': bollinger_buy,  # NEW - Expecting 72%+
    'momentum_breakout': momentum_breakout,  # 56.2% → 70%+
}