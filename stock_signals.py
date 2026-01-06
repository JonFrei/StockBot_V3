"""
Stock Signal Generation - STREAMLINED VERSION

Removed verbose per-signal logging
"""
from typing import Dict, Any


class SignalConfig:
    """Signal configuration"""
    MIN_SCORE_THRESHOLD = 55 # was 55 on 1/5/26

    # SWING_TRADE_1
    ST1_EMA20_DISTANCE_MAX = 8.0
    ST1_RSI_MIN = 40
    ST1_RSI_MAX = 72
    ST1_VOLUME_RATIO_MIN = 0.9
    ST1_ADX_MIN = 15
    ST1_ADX_MAX = 50

    '''
    # CONSOLIDATION_BREAKOUT
    CB_RANGE_MAX = 18.0
    CB_VOLUME_RATIO_MIN = 1.10
    CB_RSI_MIN = 48
    CB_RSI_MAX = 72
    CB_EMA20_DISTANCE_MAX = 12.0
    CB_LOOKBACK_PERIODS = 10
    CB_BREAKOUT_THRESHOLD = 0.97
    CB_ADX_MIN = 18
    CB_MACD_REQUIRED = True
    '''
    # CONSOLIDATION_BREAKOUT (tightened)
    CB_RANGE_MAX = 12.0              # Was 18.0 - tighter consolidation required
    CB_VOLUME_RATIO_MIN = 1.5        # Was 1.10 - require real volume surge
    CB_RSI_MIN = 50                  # Was 48 - ensure momentum
    CB_RSI_MAX = 70                  # Was 72 - avoid overextended
    CB_EMA20_DISTANCE_MAX = 8.0      # Was 12.0 - stay closer to mean
    CB_LOOKBACK_PERIODS = 15         # Was 10 - longer base formation
    CB_BREAKOUT_THRESHOLD = 1.005    # Was 0.97 - must break HIGH by 0.5%
    CB_ADX_MIN = 20                  # Was 18 - stronger trend required
    CB_MACD_REQUIRED = True
    CB_MIN_BASE_DAYS = 5             # NEW - minimum consolidation days
    CB_PRIOR_UPTREND_PCT = 5.0       # NEW - must have gained before consolidating

    # GOLDEN_CROSS (loosened for more signals)
    GC_DISTANCE_MIN = 0.0
    GC_DISTANCE_MAX = 12.0
    GC_ADX_MIN = 18  # Was 20 - allow slightly weaker trends
    GC_VOLUME_RATIO_MIN = 1.0
    GC_RSI_MIN = 48  # Was 50 - catch earlier in momentum build
    GC_RSI_MAX = 75  # Was 72 - allow slightly more extended entries
    GC_REQUIRE_SQUEEZE = False
    GC_MAX_SQUEEZE_RANGE = 12.0
    GC_MIN_MACD_HISTOGRAM = 0.0
    GC_REQUIRE_RISING_EMA50 = True
    GC_MIN_EMA50_SLOPE = 0.01

    # MOMENTUM_THRUST (loosened for more volume)
    MT_CLOSE_POSITION_MIN = 0.60  # Was 0.75
    MT_VOLUME_RATIO_MIN = 1.2  # Was 1.5
    MT_RSI_MIN = 50  # Was 55
    MT_RSI_MAX = 80  # Was 78
    MT_ADX_MIN = 18  # Was 22
    MT_ROC_MIN = 1.5  # Was 3.0
    MT_MACD_HIST_MIN = 0.0


IndicatorData = Dict[str, Any]
SignalResult = Dict[str, Any]


class SignalProcessor:
    """Signal scoring processor"""

    def process_ticker(self, ticker: str, data: Dict, spy_data=None) -> Dict:
        """Process ticker through all signals"""
        all_scores = {}
        best_signal = None
        best_score = 0
        best_result = None

        for signal_name, signal_func in BUY_STRATEGIES.items():
            try:
                result = signal_func(data)
                if result and 'score' in result:
                    score = result['score']
                    all_scores[signal_name] = score
                    if score > best_score:
                        best_score = score
                        best_signal = signal_name
                        best_result = result
            except:
                continue

        if best_score >= SignalConfig.MIN_SCORE_THRESHOLD:
            return {
                'action': 'buy',
                'signal_type': best_signal,
                'signal_data': best_result,
                'score': best_score,
                'all_scores': all_scores
            }

        return {
            'action': 'skip',
            'signal_type': None,
            'signal_data': None,
            'score': 0,
            'all_scores': all_scores,
            'reason': f'Best {best_score:.0f} < {SignalConfig.MIN_SCORE_THRESHOLD}'
        }


def _create_signal_result(score, side, msg, signal_type, limit_price, breakdown=None):
    return {
        'score': round(score, 1),
        'side': side,
        'msg': msg,
        'signal_type': signal_type,
        'limit_price': limit_price,
        'stop_loss': None,
        'breakdown': breakdown or {}
    }


def _no_signal(reason=''):
    return {'score': 0, 'side': 'hold', 'msg': reason, 'signal_type': 'no_signal', 'limit_price': None,
            'stop_loss': None}


def swing_trade_1(data: IndicatorData) -> SignalResult:
    """Early Momentum Catch"""
    score = 0
    breakdown = {}

    close = data.get('close', 0)
    ema20 = data.get('ema20', 0)
    ema50 = data.get('ema50', 0)
    sma200 = data.get('sma200', 0)
    rsi = data.get('rsi', 50)
    volume_ratio = data.get('volume_ratio', 0)
    macd = data.get('macd', 0)
    macd_signal = data.get('macd_signal', 0)
    macd_hist = data.get('macd_histogram', 0)
    macd_hist_prev = data.get('macd_hist_prev', 0)
    obv_trending_up = data.get('obv_trending_up', False)
    adx = data.get('adx', 0)

    if not (ema20 > ema50): return _no_signal()
    if close <= sma200: return _no_signal()
    if close < ema20: return _no_signal()

    ema20_distance = ((close - ema20) / ema20 * 100) if ema20 > 0 else 100
    if ema20_distance <= 1.0:
        score += 25
    elif ema20_distance <= 3.0:
        score += 20
    elif ema20_distance <= 5.0:
        score += 15
    elif ema20_distance <= SignalConfig.ST1_EMA20_DISTANCE_MAX:
        score += 10
    else:
        return _no_signal()

    if not (SignalConfig.ST1_RSI_MIN <= rsi <= SignalConfig.ST1_RSI_MAX): return _no_signal()
    if 50 <= rsi <= 60:
        score += 20
    elif 45 <= rsi < 50 or 60 < rsi <= 65:
        score += 16
    elif 40 <= rsi < 45 or 65 < rsi <= 70:
        score += 12
    else:
        score += 8

    if volume_ratio >= 2.0:
        score += 20
    elif volume_ratio >= 1.5:
        score += 16
    elif volume_ratio >= 1.2:
        score += 12
    elif volume_ratio >= SignalConfig.ST1_VOLUME_RATIO_MIN:
        score += 8
    else:
        return _no_signal()

    if not (SignalConfig.ST1_ADX_MIN <= adx <= SignalConfig.ST1_ADX_MAX): return _no_signal()
    if 25 <= adx <= 35:
        score += 20
    elif 20 <= adx < 25 or 35 < adx <= 40:
        score += 16
    elif 15 <= adx < 20 or 40 < adx <= 45:
        score += 12
    else:
        score += 8

    if macd > macd_signal:
        if macd_hist > macd_hist_prev > 0:
            score += 10
        elif macd_hist > 0:
            score += 7
        else:
            score += 4
    else:
        return _no_signal()

    if obv_trending_up: score += 5

    return _create_signal_result(score, 'buy', f'swing_trade_1 [{score:.0f}]', 'swing_trade_1', close, breakdown)

'''
def consolidation_breakout(data: IndicatorData) -> SignalResult:
    """Consolidation Breakout"""
    score = 0

    close = data.get('close', 0)
    ema20 = data.get('ema20', 0)
    ema50 = data.get('ema50', 0)
    sma200 = data.get('sma200', 0)
    rsi = data.get('rsi', 50)
    volume_ratio = data.get('volume_ratio', 0)
    adx = data.get('adx', 0)
    macd = data.get('macd', 0)
    macd_signal = data.get('macd_signal', 0)

    raw_data = data.get('raw', None)
    if raw_data is None or len(raw_data) < SignalConfig.CB_LOOKBACK_PERIODS: return _no_signal()

    recent_highs = raw_data['high'].iloc[-SignalConfig.CB_LOOKBACK_PERIODS:].values
    recent_lows = raw_data['low'].iloc[-SignalConfig.CB_LOOKBACK_PERIODS:].values
    consolidation_range = (max(recent_highs) - min(recent_lows)) / min(recent_lows) * 100
    high_10d = max(recent_highs)

    if consolidation_range > SignalConfig.CB_RANGE_MAX: return _no_signal()
    if close <= sma200 or ema20 <= ema50: return _no_signal()
    if close < high_10d * SignalConfig.CB_BREAKOUT_THRESHOLD: return _no_signal()

    if consolidation_range < 5.0:
        score += 30
    elif consolidation_range < 8.0:
        score += 25
    elif consolidation_range < 12.0:
        score += 20
    else:
        score += 15

    if volume_ratio >= 2.0:
        score += 15
    elif volume_ratio >= 1.6:
        score += 12
    elif volume_ratio >= SignalConfig.CB_VOLUME_RATIO_MIN:
        score += 9
    else:
        return _no_signal()

    breakout_strength = ((close - high_10d) / high_10d * 100) if high_10d > 0 else 0
    if breakout_strength >= 2.0:
        score += 10
    elif breakout_strength >= 1.0:
        score += 7
    else:
        score += 4

    if not (SignalConfig.CB_RSI_MIN <= rsi <= SignalConfig.CB_RSI_MAX): return _no_signal()
    if 55 <= rsi <= 65:
        score += 20
    elif 50 <= rsi < 55 or 65 < rsi <= 70:
        score += 16
    else:
        score += 12

    distance_to_ema20 = abs((close - ema20) / ema20 * 100) if ema20 > 0 else 100
    if distance_to_ema20 > SignalConfig.CB_EMA20_DISTANCE_MAX: return _no_signal()
    if distance_to_ema20 <= 3.0:
        score += 8
    elif distance_to_ema20 <= 6.0:
        score += 6
    else:
        score += 4

    if adx < SignalConfig.CB_ADX_MIN: return _no_signal()
    if adx >= 25:
        score += 7
    else:
        score += 5

    if SignalConfig.CB_MACD_REQUIRED:
        if macd > macd_signal:
            score += 10
        else:
            return _no_signal()

    return _create_signal_result(score, 'buy', f'consolidation_breakout [{score:.0f}]', 'consolidation_breakout', close)
'''


def consolidation_breakout(data: IndicatorData) -> SignalResult:
    """
    Consolidation Breakout - Professional Implementation

    Detects true breakouts from tight consolidation patterns:
    1. Prior uptrend (not breaking out of a downtrend)
    2. Tight consolidation range (volatility squeeze)
    3. Actual breakout above range high (not just "near" high)
    4. Volume surge confirmation
    5. Trend structure intact
    """
    score = 0

    close = data.get('close', 0)
    high = data.get('high', 0)
    ema20 = data.get('ema20', 0)
    ema50 = data.get('ema50', 0)
    sma200 = data.get('sma200', 0)
    rsi = data.get('rsi', 50)
    volume_ratio = data.get('volume_ratio', 0)
    adx = data.get('adx', 0)
    macd = data.get('macd', 0)
    macd_signal = data.get('macd_signal', 0)

    # Bollinger bands for squeeze detection
    bb_upper = data.get('bollinger_upper', 0)
    bb_lower = data.get('bollinger_lower', 0)
    bb_mean = data.get('bollinger_mean', 0)

    raw_data = data.get('raw', None)
    if raw_data is None or len(raw_data) < SignalConfig.CB_LOOKBACK_PERIODS + 10:
        return _no_signal('Insufficient data')

    # =========================================================================
    # HARD FILTERS
    # =========================================================================

    # 1. TREND STRUCTURE - must be in uptrend
    if close <= sma200:
        return _no_signal('Below 200 SMA')
    if ema20 <= ema50:
        return _no_signal('EMA20 below EMA50')

    # 2. PRIOR UPTREND - must have gained before consolidating
    #    Check price 30 days ago vs start of consolidation
    try:
        price_30d_ago = float(raw_data['close'].iloc[-30]) if len(raw_data) >= 30 else float(raw_data['close'].iloc[0])
        price_at_consolidation_start = float(raw_data['close'].iloc[-SignalConfig.CB_LOOKBACK_PERIODS])
        prior_gain_pct = ((price_at_consolidation_start - price_30d_ago) / price_30d_ago) * 100

        if prior_gain_pct < SignalConfig.CB_PRIOR_UPTREND_PCT:
            return _no_signal(f'No prior uptrend: {prior_gain_pct:.1f}%')
    except:
        return _no_signal('Cannot calculate prior trend')

    # 3. CONSOLIDATION RANGE - must be tight
    recent_highs = raw_data['high'].iloc[-SignalConfig.CB_LOOKBACK_PERIODS:].values
    recent_lows = raw_data['low'].iloc[-SignalConfig.CB_LOOKBACK_PERIODS:].values
    range_high = max(recent_highs)
    range_low = min(recent_lows)
    consolidation_range = ((range_high - range_low) / range_low) * 100

    if consolidation_range > SignalConfig.CB_RANGE_MAX:
        return _no_signal(f'Range too wide: {consolidation_range:.1f}%')

    # 4. ACTUAL BREAKOUT - price must break ABOVE the range high
    #    Not just "near" the high - must exceed it
    breakout_threshold = range_high * SignalConfig.CB_BREAKOUT_THRESHOLD
    if close < breakout_threshold:
        return _no_signal(f'No breakout: ${close:.2f} < ${breakout_threshold:.2f}')

    # 5. VOLUME SURGE - breakouts need volume confirmation
    if volume_ratio < SignalConfig.CB_VOLUME_RATIO_MIN:
        return _no_signal(f'Weak volume: {volume_ratio:.1f}x')

    # 6. RSI - momentum but not overextended
    if not (SignalConfig.CB_RSI_MIN <= rsi <= SignalConfig.CB_RSI_MAX):
        return _no_signal(f'RSI out of range: {rsi:.1f}')

    # 7. ADX - trend strength
    if adx < SignalConfig.CB_ADX_MIN:
        return _no_signal(f'ADX too weak: {adx:.1f}')

    # 8. MACD - momentum confirmation
    if SignalConfig.CB_MACD_REQUIRED and macd <= macd_signal:
        return _no_signal('MACD not bullish')

    # =========================================================================
    # SCORING
    # =========================================================================

    # Consolidation tightness (0-25 points) - tighter is better
    if consolidation_range <= 5.0:
        score += 25
    elif consolidation_range <= 7.0:
        score += 20
    elif consolidation_range <= 9.0:
        score += 15
    else:
        score += 10

    # Volume surge strength (0-20 points)
    if volume_ratio >= 2.5:
        score += 20
    elif volume_ratio >= 2.0:
        score += 16
    elif volume_ratio >= 1.8:
        score += 12
    else:
        score += 8

    # Breakout strength - how far above range high (0-15 points)
    breakout_pct = ((close - range_high) / range_high) * 100
    if breakout_pct >= 2.0:
        score += 15
    elif breakout_pct >= 1.5:
        score += 12
    elif breakout_pct >= 1.0:
        score += 9
    else:
        score += 6

    # Volatility squeeze - Bollinger bandwidth (0-15 points)
    # Tighter bands = better setup
    if bb_mean > 0 and bb_upper > 0 and bb_lower > 0:
        bb_width_pct = ((bb_upper - bb_lower) / bb_mean) * 100
        if bb_width_pct <= 8.0:
            score += 15  # Very tight squeeze
        elif bb_width_pct <= 12.0:
            score += 12
        elif bb_width_pct <= 16.0:
            score += 8
        else:
            score += 4
    else:
        score += 5  # Default if no BB data

    # RSI positioning (0-10 points)
    if 55 <= rsi <= 65:
        score += 10  # Sweet spot
    elif 50 <= rsi < 55 or 65 < rsi <= 68:
        score += 7
    else:
        score += 4

    # ADX trend strength (0-10 points)
    if adx >= 30:
        score += 10
    elif adx >= 25:
        score += 8
    else:
        score += 5

    # Prior uptrend strength bonus (0-5 points)
    if prior_gain_pct >= 15.0:
        score += 5
    elif prior_gain_pct >= 10.0:
        score += 3
    else:
        score += 1

    return _create_signal_result(
        score, 'buy',
        f'consolidation_breakout [{score:.0f}] rng:{consolidation_range:.1f}% vol:{volume_ratio:.1f}x brk:{breakout_pct:.1f}%',
        'consolidation_breakout',
        close
    )

def golden_cross(data: IndicatorData) -> SignalResult:
    """Golden Cross - Loosened for more signals"""
    score = 0

    ema20 = data.get('ema20', 0)
    ema50 = data.get('ema50', 0)
    sma200 = data.get('sma200', 0)
    rsi = data.get('rsi', 50)
    volume_ratio = data.get('volume_ratio', 0)
    close = data.get('close', 0)
    adx = data.get('adx', 0)
    macd_hist = data.get('macd_histogram', 0)
    raw_data = data.get('raw', None)

    distance_pct = ((ema50 - sma200) / sma200 * 100) if sma200 > 0 else -100
    if not (SignalConfig.GC_DISTANCE_MIN <= distance_pct <= SignalConfig.GC_DISTANCE_MAX): return _no_signal()
    if not (close > ema20 > ema50): return _no_signal()

    if SignalConfig.GC_REQUIRE_RISING_EMA50 and raw_data is not None and len(raw_data) >= 60:
        try:
            ema50_series = raw_data['close'].ewm(span=50, adjust=False).mean()
            if len(ema50_series) >= 11:
                ema50_slope = ((ema50_series.iloc[-1] - ema50_series.iloc[-11]) / ema50_series.iloc[-11] * 100) / 10
                if ema50_slope < SignalConfig.GC_MIN_EMA50_SLOPE: return _no_signal()
        except:
            pass

    if macd_hist <= SignalConfig.GC_MIN_MACD_HISTOGRAM: return _no_signal()

    if distance_pct <= 2.0:
        score += 30
    elif distance_pct <= 3.5:
        score += 24
    else:
        score += 18

    if raw_data is not None and len(raw_data) >= 60:
        try:
            ema50_series = raw_data['close'].ewm(span=50, adjust=False).mean()
            if len(ema50_series) >= 11:
                ema50_slope = ((ema50_series.iloc[-1] - ema50_series.iloc[-11]) / ema50_series.iloc[-11] * 100) / 10
                if ema50_slope >= 0.20:
                    score += 25
                elif ema50_slope >= 0.15:
                    score += 20
                elif ema50_slope >= 0.10:
                    score += 15
                else:
                    score += 10
        except:
            score += 15
    else:
        score += 15

    if adx < SignalConfig.GC_ADX_MIN: return _no_signal()
    if adx >= 30:
        score += 20
    elif adx >= 27:
        score += 16
    else:
        score += 12

    if volume_ratio < SignalConfig.GC_VOLUME_RATIO_MIN: return _no_signal()
    if volume_ratio >= 2.0:
        score += 15
    elif volume_ratio >= 1.7:
        score += 12
    else:
        score += 9

    if not (SignalConfig.GC_RSI_MIN <= rsi <= SignalConfig.GC_RSI_MAX): return _no_signal()
    if 55 <= rsi <= 65:
        score += 10
    elif 50 <= rsi < 55 or 65 < rsi <= 70:
        score += 8
    else:
        score += 6

    if SignalConfig.GC_REQUIRE_SQUEEZE and raw_data is not None and len(raw_data) >= 20:
        try:
            recent_highs = raw_data['high'].iloc[-20:].values
            recent_lows = raw_data['low'].iloc[-20:].values
            consolidation_range = (max(recent_highs) - min(recent_lows)) / min(recent_lows) * 100
            if consolidation_range > SignalConfig.GC_MAX_SQUEEZE_RANGE: return _no_signal()
        except:
            pass

    return _create_signal_result(score, 'buy', f'golden_cross [{score:.0f}]', 'golden_cross', close)


def momentum_thrust(data: IndicatorData) -> SignalResult:
    """Momentum Thrust - Strong momentum or reversal in medium/large caps"""
    score = 0

    close = data.get('close', 0)
    high = data.get('high', 0)
    low = data.get('low', 0)
    ema20 = data.get('ema20', 0)
    ema50 = data.get('ema50', 0)
    sma200 = data.get('sma200', 0)
    rsi = data.get('rsi', 50)
    volume_ratio = data.get('volume_ratio', 0)
    adx = data.get('adx', 0)
    macd_hist = data.get('macd_histogram', 0)
    macd_hist_prev = data.get('macd_hist_prev', 0)
    roc_12 = data.get('roc_12', 0)

    # Calculate close position in daily range
    daily_range = high - low
    if daily_range <= 0:
        return _no_signal('No daily range')
    close_position = (close - low) / daily_range

    # FILTERS (loosened)
    if close_position < SignalConfig.MT_CLOSE_POSITION_MIN:
        return _no_signal('Close not in upper range')
    if volume_ratio < SignalConfig.MT_VOLUME_RATIO_MIN:
        return _no_signal('Insufficient volume')
    if not (SignalConfig.MT_RSI_MIN <= rsi <= SignalConfig.MT_RSI_MAX):
        return _no_signal('RSI out of range')
    if adx < SignalConfig.MT_ADX_MIN:
        return _no_signal('ADX too weak')
    if macd_hist <= SignalConfig.MT_MACD_HIST_MIN:
        return _no_signal('MACD histogram not positive')
    if roc_12 < SignalConfig.MT_ROC_MIN:
        return _no_signal('Insufficient momentum')
    if not (close > ema20 > ema50):
        return _no_signal('Trend not aligned')

    # SCORING

    # Close position (0-20 points)
    if close_position >= 0.90:
        score += 20
    elif close_position >= 0.80:
        score += 16
    elif close_position >= 0.70:
        score += 12
    else:
        score += 8

    # Volume (0-25 points)
    if volume_ratio >= 2.5:
        score += 25
    elif volume_ratio >= 2.0:
        score += 20
    elif volume_ratio >= 1.5:
        score += 15
    elif volume_ratio >= 1.3:
        score += 11
    else:
        score += 7

    # RSI positioning (0-15 points)
    if 58 <= rsi <= 68:
        score += 15
    elif 53 <= rsi < 58 or 68 < rsi <= 73:
        score += 12
    elif 50 <= rsi < 53 or 73 < rsi <= 80:
        score += 8

    # ADX trend strength (0-15 points)
    if 25 <= adx <= 35:
        score += 15
    elif 22 <= adx < 25 or 35 < adx <= 40:
        score += 12
    elif adx >= 18:
        score += 8

    # MACD acceleration (0-15 points) - NOW BONUS, NOT FILTER
    if macd_hist > macd_hist_prev:
        macd_accel = macd_hist - macd_hist_prev
        if macd_accel > 0.08:
            score += 15
        elif macd_accel > 0.04:
            score += 12
        elif macd_accel > 0:
            score += 8
    else:
        # Not accelerating but still positive - small points
        score += 4

    # ROC momentum (0-10 points)
    if roc_12 >= 6.0:
        score += 10
    elif roc_12 >= 4.0:
        score += 8
    elif roc_12 >= 2.5:
        score += 6
    else:
        score += 4

    # Bonus: Above 200 SMA (long-term trend)
    if sma200 > 0 and close > sma200:
        score += 5

    return _create_signal_result(score, 'buy', f'momentum_thrust [{score:.0f}]', 'momentum_thrust', close)


BUY_STRATEGIES: Dict[str, Any] = {
    'swing_trade_1': swing_trade_1,
    'consolidation_breakout': consolidation_breakout,
    'golden_cross': golden_cross,
    'momentum_thrust': momentum_thrust,

}
