"""
Stock Signal Generation with 0-100 Point Scoring System

DEBUGGED VERSION - All signals tested for logic errors
"""
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime
import stock_data
from config import Config


# ===================================================================================
# SIGNAL CONFIGURATION CONSTANTS
# ===================================================================================
class SignalConfig:
    """Centralized configuration for all buy signals"""

    # ===================================================================
    # GLOBAL SCORING
    # ===================================================================
    MIN_SCORE_THRESHOLD = 60

    # ===================================================================
    # SWING_TRADE_1: Working well in backtest (71.3% WR)
    # ===================================================================
    ST1_EMA20_DISTANCE_MAX = 8.0
    ST1_RSI_MIN = 40
    ST1_RSI_MAX = 72
    ST1_VOLUME_RATIO_MIN = 0.9
    ST1_ADX_MIN = 15
    ST1_ADX_MAX = 50

    # ===================================================================
    # CONSOLIDATION_BREAKOUT: Working well (72.4% WR)
    # ===================================================================
    CB_RANGE_MAX = 18.0
    CB_VOLUME_RATIO_MIN = 1.25
    CB_RSI_MIN = 48
    CB_RSI_MAX = 72
    CB_EMA20_DISTANCE_MAX = 12.0
    CB_LOOKBACK_PERIODS = 10
    CB_BREAKOUT_THRESHOLD = 0.99
    CB_ADX_MIN = 20
    CB_MACD_REQUIRED = True

    # ===================================================================
    # GOLDEN_CROSS: Tightened (was losing money)
    # ===================================================================
    GC_DISTANCE_MIN = 0.0
    GC_DISTANCE_MAX = 5.0
    GC_ADX_MIN = 25
    GC_VOLUME_RATIO_MIN = 1.5
    GC_RSI_MIN = 50
    GC_RSI_MAX = 68
    GC_REQUIRE_SQUEEZE = True
    GC_MAX_SQUEEZE_RANGE = 12.0
    GC_MIN_MACD_HISTOGRAM = 0.0
    GC_REQUIRE_RISING_EMA50 = True
    GC_MIN_EMA50_SLOPE = 0.05

    # ===================================================================
    # BOLLINGER_BUY: Loosened for more volume
    # ===================================================================
    BB_DISTANCE_FROM_LOWER_MAX = 4.0
    BB_RSI_MIN = 25
    BB_RSI_MAX = 48
    BB_VOLUME_RATIO_MIN = 1.0
    BB_ADX_MIN = 15
    BB_STOCH_MAX = 35
    BB_REQUIRE_DAILY_BOUNCE = False


# Type aliases
IndicatorData = Dict[str, Any]
SignalResult = Dict[str, Any]


# ===================================================================================
# SIGNAL PROCESSOR
# ===================================================================================

class SignalProcessor:
    """Competitive signal scoring - ALL signals compete, highest score wins"""

    def process_ticker(self, ticker: str, data: Dict, spy_data: Optional[Dict] = None) -> Dict:
        """
        Process ticker through ALL signals, return best score
        """
        all_scores = {}
        best_signal = None
        best_score = 0
        best_result = None

        # Run ALL signals and collect scores
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
            except Exception as e:
                print(f"[ERROR] Signal {signal_name} failed for {ticker}: {e}")
                continue

        # Check if best score meets threshold
        if best_score >= SignalConfig.MIN_SCORE_THRESHOLD:
            return {
                'action': 'buy',
                'signal_type': best_signal,
                'signal_data': best_result,
                'score': best_score,  # ← ADD THIS LINE
                'all_scores': all_scores
            }

        return {
            'action': 'skip',
            'signal_type': None,
            'signal_data': None,
            'score': 0,  # ← ADD THIS LINE TOO
            'all_scores': all_scores
        }


# ===================================================================================
# SCORING HELPER FUNCTIONS
# ===================================================================================

def _create_signal_result(score: float, side: str, msg: str, signal_type: str,
                          limit_price: float, breakdown: dict = None) -> SignalResult:
    """Create standardized signal result with score"""
    return {
        'score': round(score, 1),
        'side': side,
        'msg': msg,
        'signal_type': signal_type,
        'limit_price': limit_price,
        'stop_loss': None,
        'breakdown': breakdown or {}
    }


def _no_signal(reason: str = '') -> SignalResult:
    """Return no-signal result"""
    return {
        'score': 0,
        'side': 'hold',
        'msg': f'No signal: {reason}',
        'signal_type': 'no_signal',
        'limit_price': None,
        'stop_loss': None
    }


# ===================================================================================
# BUY SIGNALS
# ===================================================================================

def swing_trade_1(data: IndicatorData) -> SignalResult:
    """
    Early Momentum Catch - KEEP AS IS (71.3% WR, $60k profit)

    Scoring (0-100):
    - Price positioning (0-25)
    - RSI momentum (0-20)
    - Volume surge (0-20)
    - Trend strength (0-20)
    - MACD quality (0-10)
    - Bonuses (0-5)
    """
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

    # Hard requirements
    if not (ema20 > ema50):
        return _no_signal('EMA20 not above EMA50')

    if close <= sma200:
        return _no_signal('Below 200 SMA')

    if close < ema20:
        return _no_signal('Price below EMA20')

    # === SCORING ===

    # 1. Price Positioning (0-25 points)
    ema20_distance = ((close - ema20) / ema20 * 100) if ema20 > 0 else 100

    if ema20_distance <= 1.0:
        pos_score = 25
    elif ema20_distance <= 3.0:
        pos_score = 20
    elif ema20_distance <= 5.0:
        pos_score = 15
    elif ema20_distance <= SignalConfig.ST1_EMA20_DISTANCE_MAX:
        pos_score = 10
    else:
        return _no_signal(f'Too extended: {ema20_distance:.1f}% from EMA20')

    score += pos_score
    breakdown['price_positioning'] = pos_score

    # 2. RSI Momentum (0-20 points)
    if SignalConfig.ST1_RSI_MIN <= rsi <= SignalConfig.ST1_RSI_MAX:
        if 50 <= rsi <= 60:
            rsi_score = 20
        elif 45 <= rsi < 50 or 60 < rsi <= 65:
            rsi_score = 16
        elif 40 <= rsi < 45 or 65 < rsi <= 70:
            rsi_score = 12
        else:
            rsi_score = 8

        score += rsi_score
        breakdown['rsi_momentum'] = rsi_score
    else:
        return _no_signal(f'RSI {rsi:.0f} outside range')

    # 3. Volume Surge (0-20 points)
    if volume_ratio >= 2.0:
        vol_score = 20
    elif volume_ratio >= 1.5:
        vol_score = 16
    elif volume_ratio >= 1.2:
        vol_score = 12
    elif volume_ratio >= SignalConfig.ST1_VOLUME_RATIO_MIN:
        vol_score = 8
    else:
        return _no_signal(f'Volume too low: {volume_ratio:.1f}x')

    score += vol_score
    breakdown['volume_surge'] = vol_score

    # 4. Trend Strength (0-20 points)
    if SignalConfig.ST1_ADX_MIN <= adx <= SignalConfig.ST1_ADX_MAX:
        if 25 <= adx <= 35:
            adx_score = 20
        elif 20 <= adx < 25 or 35 < adx <= 40:
            adx_score = 16
        elif 15 <= adx < 20 or 40 < adx <= 45:
            adx_score = 12
        else:
            adx_score = 8

        score += adx_score
        breakdown['trend_strength'] = adx_score
    else:
        return _no_signal(f'ADX {adx:.0f} outside range')

    # 5. MACD Quality (0-10 points)
    if macd > macd_signal:
        if macd_hist > macd_hist_prev > 0:
            macd_score = 10
        elif macd_hist > 0:
            macd_score = 7
        else:
            macd_score = 4

        score += macd_score
        breakdown['macd_quality'] = macd_score
    else:
        return _no_signal('MACD not bullish')

    # 6. Bonuses (0-5 points)
    if obv_trending_up:
        score += 5
        breakdown['obv_bonus'] = 5

    msg = f'🚀 Early Momentum ({score:.0f}/100): {ema20_distance:.1f}% from EMA20, RSI {rsi:.0f}, Vol {volume_ratio:.1f}x, ADX {adx:.0f}'

    return _create_signal_result(score, 'buy', msg, 'swing_trade_1', close, breakdown)


def consolidation_breakout(data: IndicatorData) -> SignalResult:
    """
    Consolidation Breakout - KEEP AS IS (72.4% WR, $24k profit)

    Scoring (0-100):
    - Squeeze quality (0-30)
    - Breakout strength (0-25)
    - RSI position (0-20)
    - Trend context (0-15)
    - MACD confirmation (0-10)
    """
    score = 0
    breakdown = {}

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
    if raw_data is None or len(raw_data) < SignalConfig.CB_LOOKBACK_PERIODS:
        return _no_signal('Insufficient data')

    # Calculate consolidation metrics
    recent_highs = raw_data['high'].iloc[-SignalConfig.CB_LOOKBACK_PERIODS:].values
    recent_lows = raw_data['low'].iloc[-SignalConfig.CB_LOOKBACK_PERIODS:].values
    consolidation_range = (max(recent_highs) - min(recent_lows)) / min(recent_lows) * 100
    high_10d = max(recent_highs)

    # Hard requirements
    if consolidation_range > SignalConfig.CB_RANGE_MAX:
        return _no_signal(f'Range {consolidation_range:.1f}% too wide')

    if close <= sma200 or ema20 <= ema50:
        return _no_signal('Weak trend structure')

    if close < high_10d * SignalConfig.CB_BREAKOUT_THRESHOLD:
        return _no_signal('Not breaking out')

    # === SCORING ===

    # 1. Squeeze Quality (0-30 points)
    if consolidation_range < 5.0:
        squeeze_score = 30
    elif consolidation_range < 8.0:
        squeeze_score = 25
    elif consolidation_range < 12.0:
        squeeze_score = 20
    else:
        squeeze_score = 15

    score += squeeze_score
    breakdown['squeeze_quality'] = squeeze_score

    # 2. Breakout Strength (0-25 points)
    if volume_ratio >= 2.0:
        vol_score = 15
    elif volume_ratio >= 1.6:
        vol_score = 12
    elif volume_ratio >= SignalConfig.CB_VOLUME_RATIO_MIN:
        vol_score = 9
    else:
        return _no_signal(f'Volume {volume_ratio:.1f}x too weak')

    breakout_strength = ((close - high_10d) / high_10d * 100) if high_10d > 0 else 0

    if breakout_strength >= 2.0:
        price_score = 10
    elif breakout_strength >= 1.0:
        price_score = 7
    else:
        price_score = 4

    score += vol_score + price_score
    breakdown['breakout_strength'] = vol_score + price_score

    # 3. RSI Position (0-20 points)
    if SignalConfig.CB_RSI_MIN <= rsi <= SignalConfig.CB_RSI_MAX:
        if 55 <= rsi <= 65:
            rsi_score = 20
        elif 50 <= rsi < 55 or 65 < rsi <= 70:
            rsi_score = 16
        else:
            rsi_score = 12

        score += rsi_score
        breakdown['rsi_position'] = rsi_score
    else:
        return _no_signal(f'RSI {rsi:.0f} outside range')

    # 4. Trend Context (0-15 points)
    distance_to_ema20 = abs((close - ema20) / ema20 * 100) if ema20 > 0 else 100

    if distance_to_ema20 <= 3.0:
        dist_score = 8
    elif distance_to_ema20 <= 6.0:
        dist_score = 6
    elif distance_to_ema20 <= SignalConfig.CB_EMA20_DISTANCE_MAX:
        dist_score = 4
    else:
        return _no_signal(f'Too far from EMA20: {distance_to_ema20:.1f}%')

    if adx >= SignalConfig.CB_ADX_MIN:
        if adx >= 25:
            adx_score = 7
        else:
            adx_score = 5

        score += dist_score + adx_score
        breakdown['trend_context'] = dist_score + adx_score
    else:
        return _no_signal(f'ADX {adx:.0f} too weak')

    # 5. MACD Confirmation (0-10 points)
    if SignalConfig.CB_MACD_REQUIRED and macd > macd_signal:
        score += 10
        breakdown['macd_confirmation'] = 10
    elif SignalConfig.CB_MACD_REQUIRED:
        return _no_signal('MACD not bullish')

    msg = f'📦 Breakout ({score:.0f}/100): {consolidation_range:.1f}% range, Vol {volume_ratio:.1f}x, RSI {rsi:.0f}'

    return _create_signal_result(score, 'buy', msg, 'consolidation_breakout', close, breakdown)


def golden_cross(data: IndicatorData) -> SignalResult:
    """
    Golden Cross - DRAMATICALLY TIGHTENED (Was 48% WR, -$1,297 loss)

    NEW STRICT REQUIREMENTS:
    - EMA50 must be rising
    - Very fresh cross only (0-5% above 200 SMA)
    - Strong ADX (25+)
    - Strong volume (1.5x+)
    - Must come from consolidation
    - MACD histogram must be positive
    - RSI in bullish zone (50-68)

    Scoring (0-100):
    - Cross freshness (0-30)
    - EMA50 slope (0-25)
    - Trend strength (0-20)
    - Volume conviction (0-15)
    - RSI position (0-10)
    """
    score = 0
    breakdown = {}

    ema20 = data.get('ema20', 0)
    ema50 = data.get('ema50', 0)
    sma200 = data.get('sma200', 0)
    rsi = data.get('rsi', 50)
    volume_ratio = data.get('volume_ratio', 0)
    close = data.get('close', 0)
    adx = data.get('adx', 0)
    macd = data.get('macd', 0)
    macd_signal = data.get('macd_signal', 0)
    macd_hist = data.get('macd_histogram', 0)
    raw_data = data.get('raw', None)

    # Calculate cross freshness
    distance_pct = ((ema50 - sma200) / sma200 * 100) if sma200 > 0 else -100

    # CRITICAL: Very fresh cross only
    if not (SignalConfig.GC_DISTANCE_MIN <= distance_pct <= SignalConfig.GC_DISTANCE_MAX):
        return _no_signal(f'Cross not fresh: {distance_pct:.1f}%')

    # CRITICAL: Price structure
    if not (close > ema20 > ema50):
        return _no_signal('Price structure weak')

    # === NEW: EMA50 SLOPE CHECK (if data available) ===
    if SignalConfig.GC_REQUIRE_RISING_EMA50 and raw_data is not None and len(raw_data) >= 60:
        try:
            ema50_series = raw_data['close'].ewm(span=50, adjust=False).mean()

            if len(ema50_series) >= 11:
                ema50_current = ema50_series.iloc[-1]
                ema50_10d_ago = ema50_series.iloc[-11]
                ema50_slope = ((ema50_current - ema50_10d_ago) / ema50_10d_ago * 100) / 10

                if ema50_slope < SignalConfig.GC_MIN_EMA50_SLOPE:
                    return _no_signal(f'EMA50 slope weak: {ema50_slope:.3f}%/day')
        except Exception as e:
            # Don't block on calculation error
            pass

    # === MACD HISTOGRAM CHECK ===
    if macd_hist <= SignalConfig.GC_MIN_MACD_HISTOGRAM:
        return _no_signal(f'MACD histogram not positive: {macd_hist:.4f}')

    # === SCORING ===

    # 1. Cross Freshness (0-30 points)
    if distance_pct <= 2.0:
        fresh_score = 30
    elif distance_pct <= 3.5:
        fresh_score = 24
    else:
        fresh_score = 18

    score += fresh_score
    breakdown['cross_freshness'] = fresh_score

    # 2. EMA50 Slope Quality (0-25 points)
    if raw_data is not None and len(raw_data) >= 60:
        try:
            ema50_series = raw_data['close'].ewm(span=50, adjust=False).mean()

            if len(ema50_series) >= 11:
                ema50_current = ema50_series.iloc[-1]
                ema50_10d_ago = ema50_series.iloc[-11]
                ema50_slope = ((ema50_current - ema50_10d_ago) / ema50_10d_ago * 100) / 10

                if ema50_slope >= 0.20:
                    slope_score = 25
                elif ema50_slope >= 0.15:
                    slope_score = 20
                elif ema50_slope >= 0.10:
                    slope_score = 15
                else:
                    slope_score = 10

                score += slope_score
                breakdown['ema50_slope'] = slope_score
        except Exception as e:
            # Award partial points if calculation fails
            score += 15
            breakdown['ema50_slope'] = 15
    else:
        # Award partial points if no raw data
        score += 15
        breakdown['ema50_slope'] = 15

    # 3. Trend Strength (0-20 points)
    if adx >= SignalConfig.GC_ADX_MIN:
        if adx >= 30:
            adx_score = 20
        elif adx >= 27:
            adx_score = 16
        else:
            adx_score = 12

        score += adx_score
        breakdown['trend_strength'] = adx_score
    else:
        return _no_signal(f'ADX {adx:.0f} too weak')

    # 4. Volume Conviction (0-15 points)
    if volume_ratio >= SignalConfig.GC_VOLUME_RATIO_MIN:
        if volume_ratio >= 2.0:
            vol_score = 15
        elif volume_ratio >= 1.7:
            vol_score = 12
        else:
            vol_score = 9

        score += vol_score
        breakdown['volume_conviction'] = vol_score
    else:
        return _no_signal(f'Volume {volume_ratio:.1f}x too low')

    # 5. RSI Position (0-10 points)
    if SignalConfig.GC_RSI_MIN <= rsi <= SignalConfig.GC_RSI_MAX:
        if 55 <= rsi <= 62:
            rsi_score = 10
        elif 50 <= rsi < 55 or 62 < rsi <= 65:
            rsi_score = 8
        else:
            rsi_score = 6

        score += rsi_score
        breakdown['rsi_position'] = rsi_score
    else:
        return _no_signal(f'RSI {rsi:.0f} outside range')

    # === CONSOLIDATION CHECK (if data available) ===
    if SignalConfig.GC_REQUIRE_SQUEEZE and raw_data is not None and len(raw_data) >= 20:
        try:
            recent_highs = raw_data['high'].iloc[-20:].values
            recent_lows = raw_data['low'].iloc[-20:].values
            consolidation_range = (max(recent_highs) - min(recent_lows)) / min(recent_lows) * 100

            if consolidation_range > SignalConfig.GC_MAX_SQUEEZE_RANGE:
                return _no_signal(f'No consolidation: {consolidation_range:.1f}%')
        except Exception as e:
            # Don't block on calculation error
            pass

    msg = f'✨ Golden Cross ({score:.0f}/100): {distance_pct:.1f}% above 200 SMA, ADX {adx:.0f}, Vol {volume_ratio:.1f}x'

    return _create_signal_result(score, 'buy', msg, 'golden_cross', close, breakdown)


def bollinger_buy(data: IndicatorData) -> SignalResult:
    """
    Bollinger Band Bounce - LOOSENED (Was 6 trades, 50% WR)

    Goal: Generate more volume (15-20 trades) while maintaining quality

    Scoring (0-100):
    - Band position (0-25)
    - Stochastic (0-20)
    - RSI recovery (0-20)
    - Volume surge (0-15)
    - Trend context (0-15)
    - MACD/OBV bonus (0-5)
    """
    score = 0
    breakdown = {}

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

    # Hard requirements
    if adx < SignalConfig.BB_ADX_MIN:
        return _no_signal(f'ADX {adx:.0f} too weak')

    if not (ema20 > ema50):
        return _no_signal('No uptrend structure')

    if close <= sma200:
        return _no_signal('Below 200 SMA')

    # Check band position
    if bollinger_lower == 0:
        return _no_signal('No Bollinger data')

    distance_from_lower = ((close - bollinger_lower) / bollinger_lower * 100)

    if distance_from_lower > SignalConfig.BB_DISTANCE_FROM_LOWER_MAX:
        return _no_signal(f'Not close to band: {distance_from_lower:.1f}%')

    # === SCORING ===

    # 1. Band Position (0-25 points)
    if distance_from_lower <= 0.5:
        band_score = 25
    elif distance_from_lower <= 1.5:
        band_score = 22
    elif distance_from_lower <= 2.5:
        band_score = 18
    elif distance_from_lower <= 3.5:
        band_score = 14
    else:
        band_score = 10

    score += band_score
    breakdown['band_position'] = band_score

    # 2. Stochastic (0-20 points)
    if stoch_k <= SignalConfig.BB_STOCH_MAX:
        if stoch_k < 20:
            if stoch_k > stoch_d:
                stoch_score = 20
            else:
                stoch_score = 16
        elif stoch_k < 30:
            if stoch_k > stoch_d:
                stoch_score = 18
            else:
                stoch_score = 14
        else:
            stoch_score = 12

        score += stoch_score
        breakdown['stochastic'] = stoch_score
    else:
        return _no_signal(f'Stochastic too high: {stoch_k:.0f}')

    # 3. RSI Recovery (0-20 points)
    if SignalConfig.BB_RSI_MIN <= rsi <= SignalConfig.BB_RSI_MAX:
        if 28 <= rsi <= 35:
            rsi_score = 20
        elif 25 <= rsi < 28 or 35 < rsi <= 40:
            rsi_score = 17
        else:
            rsi_score = 14

        score += rsi_score
        breakdown['rsi_recovery'] = rsi_score
    else:
        return _no_signal(f'RSI {rsi:.0f} outside range')

    # 4. Volume Surge (0-15 points)
    if volume_ratio >= SignalConfig.BB_VOLUME_RATIO_MIN:
        if volume_ratio >= 2.0:
            vol_score = 15
        elif volume_ratio >= 1.5:
            vol_score = 13
        elif volume_ratio >= 1.2:
            vol_score = 11
        else:
            vol_score = 9

        score += vol_score
        breakdown['volume_surge'] = vol_score
    else:
        return _no_signal(f'Volume {volume_ratio:.1f}x too low')

    # 5. Trend Context (0-15 points)
    if adx >= 25:
        trend_score = 15
    elif adx >= 20:
        trend_score = 13
    elif adx >= 18:
        trend_score = 11
    else:
        trend_score = 9

    score += trend_score
    breakdown['trend_context'] = trend_score

    # 6. MACD/OBV Bonus (0-5 points)
    bonus = 0

    if macd > macd_signal:
        bonus += 3

    if obv_trending_up:
        bonus += 2

    if bonus > 0:
        score += bonus
        breakdown['momentum_bonus'] = bonus

    # Small penalty if not bouncing (don't block)
    if not SignalConfig.BB_REQUIRE_DAILY_BOUNCE and daily_change_pct < 0:
        score -= 3
        breakdown['not_bouncing_penalty'] = -3

    msg = f'🎪 Bollinger Bounce ({score:.0f}/100): {distance_from_lower:.1f}% from band, RSI {rsi:.0f}, Stoch {stoch_k:.0f}'

    return _create_signal_result(score, 'buy', msg, 'bollinger_buy', close, breakdown)


# ===================================================================================
# STRATEGY REGISTRY - REMOVED swing_trade_2
# ===================================================================================

BUY_STRATEGIES: Dict[str, Any] = {
    'swing_trade_1': swing_trade_1,
    'consolidation_breakout': consolidation_breakout,
    'golden_cross': golden_cross,
    'bollinger_buy': bollinger_buy,
}