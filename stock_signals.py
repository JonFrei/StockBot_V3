"""
Stock Signal Generation - STREAMLINED VERSION

Removed verbose per-signal logging
"""
from typing import Dict, Any


class SignalConfig:
    """Signal configuration"""
    MIN_SCORE_THRESHOLD = 60

    # SWING_TRADE_1
    ST1_EMA20_DISTANCE_MAX = 8.0
    ST1_RSI_MIN = 40
    ST1_RSI_MAX = 72
    ST1_VOLUME_RATIO_MIN = 0.9
    ST1_ADX_MIN = 15
    ST1_ADX_MAX = 50

    # CONSOLIDATION_BREAKOUT
    CB_RANGE_MAX = 18.0
    CB_VOLUME_RATIO_MIN = 1.25
    CB_RSI_MIN = 48
    CB_RSI_MAX = 72
    CB_EMA20_DISTANCE_MAX = 12.0
    CB_LOOKBACK_PERIODS = 10
    CB_BREAKOUT_THRESHOLD = 0.99
    CB_ADX_MIN = 20
    CB_MACD_REQUIRED = True

    # GOLDEN_CROSS
    GC_DISTANCE_MIN = 0.0
    GC_DISTANCE_MAX = 8.0
    GC_ADX_MIN = 20
    GC_VOLUME_RATIO_MIN = 1.2
    GC_RSI_MIN = 50
    GC_RSI_MAX = 72
    GC_REQUIRE_SQUEEZE = True
    GC_MAX_SQUEEZE_RANGE = 12.0
    GC_MIN_MACD_HISTOGRAM = 0.0
    GC_REQUIRE_RISING_EMA50 = True
    GC_MIN_EMA50_SLOPE = 0.03

    # BOLLINGER_BUY
    BB_DISTANCE_FROM_LOWER_MAX = 2.5
    BB_RSI_MIN = 25
    BB_RSI_MAX = 48
    BB_VOLUME_RATIO_MIN = 1.2
    BB_ADX_MIN = 15
    BB_STOCH_MAX = 35
    BB_REQUIRE_DAILY_BOUNCE = True


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
    return {'score': 0, 'side': 'hold', 'msg': reason, 'signal_type': 'no_signal', 'limit_price': None, 'stop_loss': None}


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
    if ema20_distance <= 1.0: score += 25
    elif ema20_distance <= 3.0: score += 20
    elif ema20_distance <= 5.0: score += 15
    elif ema20_distance <= SignalConfig.ST1_EMA20_DISTANCE_MAX: score += 10
    else: return _no_signal()

    if not (SignalConfig.ST1_RSI_MIN <= rsi <= SignalConfig.ST1_RSI_MAX): return _no_signal()
    if 50 <= rsi <= 60: score += 20
    elif 45 <= rsi < 50 or 60 < rsi <= 65: score += 16
    elif 40 <= rsi < 45 or 65 < rsi <= 70: score += 12
    else: score += 8

    if volume_ratio >= 2.0: score += 20
    elif volume_ratio >= 1.5: score += 16
    elif volume_ratio >= 1.2: score += 12
    elif volume_ratio >= SignalConfig.ST1_VOLUME_RATIO_MIN: score += 8
    else: return _no_signal()

    if not (SignalConfig.ST1_ADX_MIN <= adx <= SignalConfig.ST1_ADX_MAX): return _no_signal()
    if 25 <= adx <= 35: score += 20
    elif 20 <= adx < 25 or 35 < adx <= 40: score += 16
    elif 15 <= adx < 20 or 40 < adx <= 45: score += 12
    else: score += 8

    if macd > macd_signal:
        if macd_hist > macd_hist_prev > 0: score += 10
        elif macd_hist > 0: score += 7
        else: score += 4
    else: return _no_signal()

    if obv_trending_up: score += 5

    return _create_signal_result(score, 'buy', f'swing_trade_1 [{score:.0f}]', 'swing_trade_1', close, breakdown)


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

    if consolidation_range < 5.0: score += 30
    elif consolidation_range < 8.0: score += 25
    elif consolidation_range < 12.0: score += 20
    else: score += 15

    if volume_ratio >= 2.0: score += 15
    elif volume_ratio >= 1.6: score += 12
    elif volume_ratio >= SignalConfig.CB_VOLUME_RATIO_MIN: score += 9
    else: return _no_signal()

    breakout_strength = ((close - high_10d) / high_10d * 100) if high_10d > 0 else 0
    if breakout_strength >= 2.0: score += 10
    elif breakout_strength >= 1.0: score += 7
    else: score += 4

    if not (SignalConfig.CB_RSI_MIN <= rsi <= SignalConfig.CB_RSI_MAX): return _no_signal()
    if 55 <= rsi <= 65: score += 20
    elif 50 <= rsi < 55 or 65 < rsi <= 70: score += 16
    else: score += 12

    distance_to_ema20 = abs((close - ema20) / ema20 * 100) if ema20 > 0 else 100
    if distance_to_ema20 > SignalConfig.CB_EMA20_DISTANCE_MAX: return _no_signal()
    if distance_to_ema20 <= 3.0: score += 8
    elif distance_to_ema20 <= 6.0: score += 6
    else: score += 4

    if adx < SignalConfig.CB_ADX_MIN: return _no_signal()
    if adx >= 25: score += 7
    else: score += 5

    if SignalConfig.CB_MACD_REQUIRED:
        if macd > macd_signal: score += 10
        else: return _no_signal()

    return _create_signal_result(score, 'buy', f'consolidation_breakout [{score:.0f}]', 'consolidation_breakout', close)


def golden_cross(data: IndicatorData) -> SignalResult:
    """Golden Cross - Tightened"""
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
        except: pass

    if macd_hist <= SignalConfig.GC_MIN_MACD_HISTOGRAM: return _no_signal()

    if distance_pct <= 2.0: score += 30
    elif distance_pct <= 3.5: score += 24
    else: score += 18

    if raw_data is not None and len(raw_data) >= 60:
        try:
            ema50_series = raw_data['close'].ewm(span=50, adjust=False).mean()
            if len(ema50_series) >= 11:
                ema50_slope = ((ema50_series.iloc[-1] - ema50_series.iloc[-11]) / ema50_series.iloc[-11] * 100) / 10
                if ema50_slope >= 0.20: score += 25
                elif ema50_slope >= 0.15: score += 20
                elif ema50_slope >= 0.10: score += 15
                else: score += 10
        except: score += 15
    else: score += 15

    if adx < SignalConfig.GC_ADX_MIN: return _no_signal()
    if adx >= 30: score += 20
    elif adx >= 27: score += 16
    else: score += 12

    if volume_ratio < SignalConfig.GC_VOLUME_RATIO_MIN: return _no_signal()
    if volume_ratio >= 2.0: score += 15
    elif volume_ratio >= 1.7: score += 12
    else: score += 9

    if not (SignalConfig.GC_RSI_MIN <= rsi <= SignalConfig.GC_RSI_MAX): return _no_signal()
    if 55 <= rsi <= 62: score += 10
    elif 50 <= rsi < 55 or 62 < rsi <= 65: score += 8
    else: score += 6

    if SignalConfig.GC_REQUIRE_SQUEEZE and raw_data is not None and len(raw_data) >= 20:
        try:
            recent_highs = raw_data['high'].iloc[-20:].values
            recent_lows = raw_data['low'].iloc[-20:].values
            consolidation_range = (max(recent_highs) - min(recent_lows)) / min(recent_lows) * 100
            if consolidation_range > SignalConfig.GC_MAX_SQUEEZE_RANGE: return _no_signal()
        except: pass

    return _create_signal_result(score, 'buy', f'golden_cross [{score:.0f}]', 'golden_cross', close)


def bollinger_buy(data: IndicatorData) -> SignalResult:
    """Bollinger Band Bounce - Tightened"""
    score = 0

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
    stoch_k = data.get('stoch_k', 50)
    stoch_d = data.get('stoch_d', 50)

    if adx < SignalConfig.BB_ADX_MIN: return _no_signal()
    if not (ema20 > ema50): return _no_signal()
    if close <= sma200: return _no_signal()
    if bollinger_lower == 0: return _no_signal()

    distance_from_lower = ((close - bollinger_lower) / bollinger_lower * 100)
    if distance_from_lower > SignalConfig.BB_DISTANCE_FROM_LOWER_MAX: return _no_signal()

    if SignalConfig.BB_REQUIRE_DAILY_BOUNCE and daily_change_pct < 0: return _no_signal()

    if distance_from_lower <= 0.5: score += 25
    elif distance_from_lower <= 1.0: score += 22
    elif distance_from_lower <= 1.5: score += 18
    elif distance_from_lower <= 2.0: score += 14
    else: score += 10

    if stoch_k > SignalConfig.BB_STOCH_MAX: return _no_signal()
    if stoch_k < 20:
        if stoch_k > stoch_d: score += 20
        else: score += 16
    elif stoch_k < 30:
        if stoch_k > stoch_d: score += 18
        else: score += 14
    else: score += 12

    if not (SignalConfig.BB_RSI_MIN <= rsi <= SignalConfig.BB_RSI_MAX): return _no_signal()
    if 28 <= rsi <= 35: score += 20
    elif 25 <= rsi < 28 or 35 < rsi <= 40: score += 17
    else: score += 14

    if volume_ratio < SignalConfig.BB_VOLUME_RATIO_MIN: return _no_signal()
    if volume_ratio >= 2.0: score += 15
    elif volume_ratio >= 1.5: score += 13
    elif volume_ratio >= 1.2: score += 11
    else: score += 9

    if adx >= 25: score += 15
    elif adx >= 20: score += 13
    elif adx >= 18: score += 11
    else: score += 9

    bonus = 0
    if macd > macd_signal: bonus += 3
    if obv_trending_up: bonus += 2
    score += bonus

    return _create_signal_result(score, 'buy', f'bollinger_buy [{score:.0f}]', 'bollinger_buy', close)


BUY_STRATEGIES: Dict[str, Any] = {
    'swing_trade_1': swing_trade_1,
    'consolidation_breakout': consolidation_breakout,
    'golden_cross': golden_cross,
    # 'bollinger_buy': bollinger_buy,
}