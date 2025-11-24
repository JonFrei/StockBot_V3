"""
Stock Signal Generation with Centralized Confirmation Scoring (0-100)

KEY CONCEPT:
- Each signal returns a score 0-100 (higher = better quality)
- SignalProcessor picks the HIGHEST scoring signal
- Minimum threshold (e.g., 40) prevents low-quality trades
- Simple, comparable scoring across all signals
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

    # === GLOBAL SETTINGS ===
    MIN_SCORE_THRESHOLD = 55  # Minimum score to trigger any trade (0-100)

    # === SWING_TRADE_1: Early Momentum Catch ===
    ST1_EMA20_DISTANCE_MAX = 8.0  # % above EMA20
    ST1_RSI_MIN = 40
    ST1_RSI_MAX = 72
    ST1_VOLUME_RATIO_MIN = 0.9
    ST1_ADX_MIN = 15
    ST1_ADX_MAX = 50

    # === SWING_TRADE_2: Pullback in Trend ===
    ST2_PULLBACK_MIN = 2.0
    ST2_PULLBACK_MAX = 10.0
    ST2_RSI_MIN = 40
    ST2_RSI_MAX = 68
    ST2_VOLUME_RATIO_MIN = 1.15
    ST2_ADX_MIN = 18
    ST2_DAILY_CHANGE_MIN = -4.0

    # === CONSOLIDATION_BREAKOUT ===
    CB_RANGE_MAX = 18.0
    CB_VOLUME_RATIO_MIN = 1.25
    CB_RSI_MIN = 48
    CB_RSI_MAX = 72
    CB_EMA20_DISTANCE_MAX = 12.0
    CB_LOOKBACK_PERIODS = 10
    CB_BREAKOUT_THRESHOLD = 0.99
    CB_ADX_MIN = 20
    CB_MACD_REQUIRED = True

    # === GOLDEN_CROSS ===
    GC_DISTANCE_MIN = 0.0
    GC_DISTANCE_MAX = 10.0
    GC_ADX_MIN = 18
    GC_VOLUME_RATIO_MIN = 1.2
    GC_RSI_MIN = 45
    GC_RSI_MAX = 70

    # === BOLLINGER_BUY ===
    BB_DISTANCE_FROM_LOWER_MAX = 3.0
    BB_RSI_MIN = 28
    BB_RSI_MAX = 45
    BB_STOCH_OVERSOLD = 30
    BB_VOLUME_RATIO_STRONG = 1.5
    BB_VOLUME_RATIO_GOOD = 1.2
    BB_ADX_STRONG = 22
    BB_ADX_MODERATE = 18

    # === BOLLINGER BAND WIDTH (Universal) ===
    BB_WIDTH_VERY_TIGHT = 5.0
    BB_WIDTH_TIGHT = 8.0
    BB_WIDTH_NORMAL = 12.0


# Type aliases
IndicatorData = Dict[str, Any]
SignalResult = Dict[str, Any]


# ===================================================================================
# CENTRALIZED SIGNAL PROCESSOR
# ===================================================================================

class SignalProcessor:
    """
    Handles signal detection with centralized scoring

    Process:
    1. Test all signals for a ticker
    2. Each returns score 0-100
    3. Pick signal with HIGHEST score
    4. If highest score < MIN_THRESHOLD, skip trade
    """

    def process_ticker(self, ticker: str, data: Dict, spy_data: Optional[Dict] = None) -> Dict:
        """
        Process a single ticker through all signals, pick best one

        Args:
            ticker: Stock symbol
            data: Stock technical indicators
            spy_data: SPY indicators (optional)

        Returns:
            {
                'action': 'buy' | 'skip',
                'signal_type': str or None,
                'signal_data': dict or None,
                'score': float (0-100),
                'all_scores': dict {signal_name: score}
            }
        """

        all_scores = {}
        all_results = {}

        # Test each signal and collect scores
        for signal_name, signal_func in BUY_STRATEGIES.items():
            if not signal_func:
                continue

            result = signal_func(data)
            score = result.get('score', 0)

            all_scores[signal_name] = score
            all_results[signal_name] = result

        # Find highest scoring signal
        if not all_scores:
            return {
                'action': 'skip',
                'signal_type': None,
                'signal_data': None,
                'score': 0,
                'all_scores': {}
            }

        best_signal = max(all_scores.items(), key=lambda x: x[1])
        best_signal_name = best_signal[0]
        best_score = best_signal[1]

        # Check minimum threshold
        if best_score < SignalConfig.MIN_SCORE_THRESHOLD:
            return {
                'action': 'skip',
                'signal_type': None,
                'signal_data': None,
                'score': best_score,
                'all_scores': all_scores,
                'reason': f'Best score {best_score:.0f} below threshold {SignalConfig.MIN_SCORE_THRESHOLD}'
            }

        # Return winning signal
        return {
            'action': 'buy',
            'signal_type': best_signal_name,
            'signal_data': all_results[best_signal_name],
            'score': best_score,
            'all_scores': all_scores
        }


# ===================================================================================
# BUY SIGNALS - SIMPLIFIED WITH 0-100 SCORING
# ===================================================================================

def swing_trade_1(data: IndicatorData) -> SignalResult:
    """
    Early Momentum Catch - Score 0-100

    Scoring Breakdown:
    - Price Positioning (0-25): Closer to EMA20 = higher score
    - RSI Momentum (0-20): Sweet spot 50-65
    - Volume (0-20): Higher volume = higher score
    - Trend Strength (0-20): ADX 25-35 ideal
    - MACD (0-10): Bullish + accelerating
    - Bonuses (0-5): OBV, Stoch, BB squeeze

    Total: 0-100 points
    """
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
    stoch_bullish = data.get('stoch_bullish', False)
    bb_width = data.get('bollinger_width', 100)

    score = 0
    reasons = []

    # === CORE FILTERS (Must Pass) ===
    if not (ema20 > ema50):
        return _no_signal_scored('EMA20 not above EMA50')

    if close <= sma200:
        return _no_signal_scored('Below 200 SMA')

    if close < ema20:
        return _no_signal_scored('Price below EMA20')

    # === 1. PRICE POSITIONING (0-25 points) ===
    ema20_distance = ((close - ema20) / ema20 * 100) if ema20 > 0 else 100

    if ema20_distance > SignalConfig.ST1_EMA20_DISTANCE_MAX:
        return _no_signal_scored(f'Too extended: {ema20_distance:.1f}% above EMA20')

    if ema20_distance <= 2.0:
        score += 25
        reasons.append('Perfect entry')
    elif ema20_distance <= 4.0:
        score += 20
        reasons.append('Excellent entry')
    elif ema20_distance <= 6.0:
        score += 15
        reasons.append('Good entry')
    else:  # 6-8%
        score += 10
        reasons.append('Fair entry')

    # === 2. RSI MOMENTUM (0-20 points) ===
    if rsi < SignalConfig.ST1_RSI_MIN or rsi > SignalConfig.ST1_RSI_MAX:
        return _no_signal_scored(f'RSI {rsi:.0f} outside {SignalConfig.ST1_RSI_MIN}-{SignalConfig.ST1_RSI_MAX}')

    if 50 <= rsi <= 65:
        score += 20
        reasons.append(f'Strong RSI ({rsi:.0f})')
    elif 45 <= rsi < 50 or 65 < rsi <= 70:
        score += 15
        reasons.append(f'Good RSI ({rsi:.0f})')
    else:
        score += 10
        reasons.append(f'OK RSI ({rsi:.0f})')

    # === 3. VOLUME (0-20 points) ===
    if volume_ratio < SignalConfig.ST1_VOLUME_RATIO_MIN:
        return _no_signal_scored(f'Volume too low ({volume_ratio:.1f}x)')

    if volume_ratio >= 1.8:
        score += 20
        reasons.append(f'Explosive vol ({volume_ratio:.1f}x)')
    elif volume_ratio >= 1.4:
        score += 16
        reasons.append(f'Strong vol ({volume_ratio:.1f}x)')
    elif volume_ratio >= 1.1:
        score += 12
        reasons.append(f'Good vol ({volume_ratio:.1f}x)')
    else:
        score += 8
        reasons.append(f'Moderate vol ({volume_ratio:.1f}x)')

    # === 4. TREND STRENGTH (0-20 points) ===
    if adx < SignalConfig.ST1_ADX_MIN:
        return _no_signal_scored(f'ADX too weak ({adx:.0f})')

    if 25 <= adx <= 35:
        score += 20
        reasons.append(f'Perfect ADX ({adx:.0f})')
    elif 20 <= adx < 25 or 35 < adx <= 40:
        score += 16
        reasons.append(f'Strong ADX ({adx:.0f})')
    elif 15 <= adx < 20:
        score += 12
        reasons.append(f'Developing ADX ({adx:.0f})')
    else:  # > 40
        score += 8
        reasons.append(f'Mature trend ({adx:.0f})')

    # === 5. MACD (0-10 points) ===
    if macd <= macd_signal:
        return _no_signal_scored('MACD not bullish')

    if macd_hist > macd_hist_prev > 0:
        score += 10
        reasons.append('MACD accelerating')
    elif macd_hist > 0:
        score += 7
        reasons.append('MACD bullish')
    else:
        score += 5
        reasons.append('MACD turned bullish')

    # === 6. BONUSES (0-5 points) ===
    if obv_trending_up:
        score += 2
        reasons.append('OBV+')

    if stoch_bullish:
        score += 2
        reasons.append('Stoch+')

    if bb_width < SignalConfig.BB_WIDTH_TIGHT:
        score += 1
        reasons.append(f'Squeeze')

    return {
        'side': 'buy',
        'score': min(100, score),
        'msg': f'Early Momentum: {score:.0f}/100 | {", ".join(reasons[:3])}',
        'reasons': reasons,
        'limit_price': close,
        'stop_loss': None,
        'signal_type': 'swing_trade_1'
    }


def swing_trade_2(data: IndicatorData) -> SignalResult:
    """
    Pullback Buy - Score 0-100

    Scoring Breakdown:
    - Pullback Quality (0-30): 3-7% pullback ideal
    - RSI Recovery (0-20): 40-55 sweet spot
    - Volume (0-20): Confirming bounce
    - Trend Context (0-15): ADX + EMA structure
    - MACD/OBV (0-10): Momentum confirmation
    - Bonuses (0-5): Squeeze, stochastic

    Total: 0-100 points
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
    stoch_k = data.get('stoch_k', 50)
    bb_width = data.get('bollinger_width', 100)

    score = 0
    reasons = []

    # === CORE FILTERS ===
    if close <= sma200:
        return _no_signal_scored('Below 200 SMA')

    if ema20 <= ema50:
        return _no_signal_scored('No uptrend structure')

    # === 1. PULLBACK QUALITY (0-30 points) ===
    ema20_distance = abs((close - ema20) / ema20 * 100) if ema20 > 0 else 100

    if not (SignalConfig.ST2_PULLBACK_MIN <= ema20_distance <= SignalConfig.ST2_PULLBACK_MAX):
        return _no_signal_scored(f'Pullback {ema20_distance:.1f}% outside range')

    if 3.0 <= ema20_distance <= 7.0:
        score += 30
        reasons.append(f'Perfect pullback ({ema20_distance:.1f}%)')
    elif 2.0 <= ema20_distance < 3.0 or 7.0 < ema20_distance <= 9.0:
        score += 24
        reasons.append(f'Good pullback ({ema20_distance:.1f}%)')
    else:
        score += 18
        reasons.append(f'OK pullback ({ema20_distance:.1f}%)')

    # === 2. RSI RECOVERY (0-20 points) ===
    if not (SignalConfig.ST2_RSI_MIN <= rsi <= SignalConfig.ST2_RSI_MAX):
        return _no_signal_scored(f'RSI {rsi:.0f} outside range')

    if 45 <= rsi <= 55:
        score += 20
        reasons.append(f'Perfect RSI ({rsi:.0f})')
    elif 40 <= rsi < 45 or 55 < rsi <= 60:
        score += 16
        reasons.append(f'Good RSI ({rsi:.0f})')
    else:
        score += 12
        reasons.append(f'OK RSI ({rsi:.0f})')

    # === 3. VOLUME (0-20 points) ===
    if volume_ratio < SignalConfig.ST2_VOLUME_RATIO_MIN:
        return _no_signal_scored(f'Volume {volume_ratio:.1f}x too low')

    if volume_ratio >= 1.5:
        score += 20
        reasons.append(f'Strong vol ({volume_ratio:.1f}x)')
    elif volume_ratio >= 1.3:
        score += 16
        reasons.append(f'Good vol ({volume_ratio:.1f}x)')
    else:
        score += 12
        reasons.append(f'OK vol ({volume_ratio:.1f}x)')

    # === 4. TREND CONTEXT (0-15 points) ===
    if adx < SignalConfig.ST2_ADX_MIN:
        return _no_signal_scored(f'ADX {adx:.0f} too weak')

    if adx >= 25:
        score += 15
        reasons.append(f'Strong ADX ({adx:.0f})')
    elif adx >= 20:
        score += 12
        reasons.append(f'Good ADX ({adx:.0f})')
    else:
        score += 9
        reasons.append(f'Developing ADX ({adx:.0f})')

    # === 5. MACD/OBV (0-10 points) ===
    if macd <= macd_signal:
        return _no_signal_scored('MACD not bullish')

    score += 5
    reasons.append('MACD bullish')

    if obv_trending_up:
        score += 5
        reasons.append('OBV+')

    # === 6. BONUSES (0-5 points) ===
    if daily_change_pct > 0:
        score += 2
        reasons.append('Bouncing')

    if stoch_k < 20:
        score += 2
        reasons.append('Stoch oversold')

    if bb_width < SignalConfig.BB_WIDTH_TIGHT:
        score += 1
        reasons.append('Squeeze')

    return {
        'side': 'buy',
        'score': min(100, score),
        'msg': f'Pullback: {score:.0f}/100 | {", ".join(reasons[:3])}',
        'reasons': reasons,
        'limit_price': close,
        'stop_loss': None,
        'signal_type': 'swing_trade_2'
    }


def consolidation_breakout(data: IndicatorData) -> SignalResult:
    """
    Consolidation Breakout - Score 0-100

    Scoring Breakdown:
    - Squeeze Quality (0-30): Band width + consolidation range
    - Breakout Strength (0-25): Volume + price action
    - RSI Position (0-20): 50-65 ideal
    - Trend Context (0-15): ADX + EMA structure
    - MACD (0-10): Bullish confirmation

    Total: 0-100 points
    """
    close = data.get('close', 0)
    ema20 = data.get('ema20', 0)
    ema50 = data.get('ema50', 0)
    sma200 = data.get('sma200', 0)
    rsi = data.get('rsi', 50)
    volume_ratio = data.get('volume_ratio', 0)
    adx = data.get('adx', 0)
    macd = data.get('macd', 0)
    macd_signal = data.get('macd_signal', 0)
    bb_width = data.get('bollinger_width', 100)

    raw_data = data.get('raw', None)

    score = 0
    reasons = []

    # === CORE FILTERS ===
    if raw_data is None or len(raw_data) < SignalConfig.CB_LOOKBACK_PERIODS:
        return _no_signal_scored('Insufficient data')

    if close <= sma200 or ema20 <= ema50:
        return _no_signal_scored('Weak trend structure')

    # Calculate consolidation metrics
    recent_highs = raw_data['high'].iloc[-SignalConfig.CB_LOOKBACK_PERIODS:].values
    recent_lows = raw_data['low'].iloc[-SignalConfig.CB_LOOKBACK_PERIODS:].values
    consolidation_range = (max(recent_highs) - min(recent_lows)) / min(recent_lows) * 100
    high_10d = max(recent_highs)

    if consolidation_range > SignalConfig.CB_RANGE_MAX:
        return _no_signal_scored(f'Range {consolidation_range:.1f}% too wide')

    if close < high_10d * SignalConfig.CB_BREAKOUT_THRESHOLD:
        return _no_signal_scored('Not breaking out')

    # === 1. SQUEEZE QUALITY (0-30 points) ===

    # Band width component (0-20)
    if bb_width < 5.0:
        score += 20
        reasons.append(f'Very tight ({bb_width:.1f}%)')
    elif bb_width < 8.0:
        score += 16
        reasons.append(f'Tight ({bb_width:.1f}%)')
    elif bb_width < 10.0:
        score += 12
        reasons.append(f'Moderate ({bb_width:.1f}%)')
    else:
        score += 8
        reasons.append(f'Normal width ({bb_width:.1f}%)')

    # Consolidation range component (0-10)
    if consolidation_range < 8.0:
        score += 10
        reasons.append(f'Tight range ({consolidation_range:.1f}%)')
    elif consolidation_range < 12.0:
        score += 8
        reasons.append(f'Good range ({consolidation_range:.1f}%)')
    else:
        score += 6
        reasons.append(f'OK range ({consolidation_range:.1f}%)')

    # === 2. BREAKOUT STRENGTH (0-25 points) ===
    if volume_ratio < SignalConfig.CB_VOLUME_RATIO_MIN:
        return _no_signal_scored(f'Volume {volume_ratio:.1f}x too low')

    if volume_ratio >= 2.0:
        score += 25
        reasons.append(f'Explosive vol ({volume_ratio:.1f}x)')
    elif volume_ratio >= 1.6:
        score += 20
        reasons.append(f'Strong vol ({volume_ratio:.1f}x)')
    elif volume_ratio >= 1.4:
        score += 16
        reasons.append(f'Good vol ({volume_ratio:.1f}x)')
    else:
        score += 12
        reasons.append(f'OK vol ({volume_ratio:.1f}x)')

    # === 3. RSI POSITION (0-20 points) ===
    if not (SignalConfig.CB_RSI_MIN <= rsi <= SignalConfig.CB_RSI_MAX):
        return _no_signal_scored(f'RSI {rsi:.0f} outside range')

    if 52 <= rsi <= 62:
        score += 20
        reasons.append(f'Perfect RSI ({rsi:.0f})')
    elif 48 <= rsi < 52 or 62 < rsi <= 68:
        score += 16
        reasons.append(f'Good RSI ({rsi:.0f})')
    else:
        score += 12
        reasons.append(f'OK RSI ({rsi:.0f})')

    # === 4. TREND CONTEXT (0-15 points) ===
    if adx < SignalConfig.CB_ADX_MIN:
        return _no_signal_scored(f'ADX {adx:.0f} too weak')

    if adx >= 25:
        score += 15
        reasons.append(f'Strong ADX ({adx:.0f})')
    elif adx >= 22:
        score += 12
        reasons.append(f'Good ADX ({adx:.0f})')
    else:
        score += 9
        reasons.append(f'Developing ADX ({adx:.0f})')

    # Check distance from EMA20
    distance_to_ema20 = abs((close - ema20) / ema20 * 100) if ema20 > 0 else 100
    if distance_to_ema20 > SignalConfig.CB_EMA20_DISTANCE_MAX:
        score -= 5  # Penalty for being too extended
        reasons.append('Extended from EMA20')

    # === 5. MACD (0-10 points) ===
    if SignalConfig.CB_MACD_REQUIRED and macd <= macd_signal:
        return _no_signal_scored('MACD not bullish')

    if macd > macd_signal:
        score += 10
        reasons.append('MACD bullish')

    return {
        'side': 'buy',
        'score': min(100, score),
        'msg': f'Breakout: {score:.0f}/100 | {", ".join(reasons[:3])}',
        'reasons': reasons,
        'limit_price': close,
        'stop_loss': None,
        'signal_type': 'consolidation_breakout'
    }


def golden_cross(data: IndicatorData) -> SignalResult:
    """
    Golden Cross - Score 0-100

    Scoring Breakdown:
    - Cross Freshness (0-30): 0-5% above 200 SMA ideal
    - Trend Strength (0-25): ADX quality
    - Price Structure (0-20): EMAs aligned
    - Volume (0-15): Confirmation
    - RSI (0-10): Not overbought

    Total: 0-100 points
    """
    ema20 = data.get('ema20', 0)
    ema50 = data.get('ema50', 0)
    sma200 = data.get('sma200', 0)
    rsi = data.get('rsi', 50)
    volume_ratio = data.get('volume_ratio', 0)
    close = data.get('close', 0)
    adx = data.get('adx', 0)
    bb_width = data.get('bollinger_width', 100)

    score = 0
    reasons = []

    # Calculate distance of EMA50 from SMA200
    distance_pct = ((ema50 - sma200) / sma200 * 100) if sma200 > 0 else -100

    # === CORE FILTERS ===
    if not (SignalConfig.GC_DISTANCE_MIN <= distance_pct <= SignalConfig.GC_DISTANCE_MAX):
        return _no_signal_scored('No fresh golden cross')

    if not (close > ema20 > ema50):
        return _no_signal_scored('Price structure weak')

    # === 1. CROSS FRESHNESS (0-30 points) ===
    if distance_pct <= 3.0:
        score += 30
        reasons.append(f'Very fresh cross ({distance_pct:.1f}%)')
    elif distance_pct <= 5.0:
        score += 25
        reasons.append(f'Fresh cross ({distance_pct:.1f}%)')
    elif distance_pct <= 7.0:
        score += 20
        reasons.append(f'Recent cross ({distance_pct:.1f}%)')
    else:
        score += 15
        reasons.append(f'Older cross ({distance_pct:.1f}%)')

    # === 2. TREND STRENGTH (0-25 points) ===
    if adx < SignalConfig.GC_ADX_MIN:
        return _no_signal_scored('ADX too weak')

    if adx >= 30:
        score += 25
        reasons.append(f'Strong ADX ({adx:.0f})')
    elif adx >= 25:
        score += 21
        reasons.append(f'Good ADX ({adx:.0f})')
    elif adx >= 20:
        score += 17
        reasons.append(f'Developing ADX ({adx:.0f})')
    else:
        score += 13
        reasons.append(f'Weak ADX ({adx:.0f})')

    # === 3. PRICE STRUCTURE (0-20 points) ===
    # Already confirmed close > ema20 > ema50
    score += 15
    reasons.append('EMAs aligned')

    # Distance from EMA20
    ema20_distance = ((close - ema20) / ema20 * 100) if ema20 > 0 else 0
    if ema20_distance <= 3.0:
        score += 5
        reasons.append('Near EMA20')

    # === 4. VOLUME (0-15 points) ===
    if volume_ratio < SignalConfig.GC_VOLUME_RATIO_MIN:
        return _no_signal_scored('Volume too low')

    if volume_ratio >= 1.6:
        score += 15
        reasons.append(f'Strong vol ({volume_ratio:.1f}x)')
    elif volume_ratio >= 1.4:
        score += 12
        reasons.append(f'Good vol ({volume_ratio:.1f}x)')
    else:
        score += 9
        reasons.append(f'OK vol ({volume_ratio:.1f}x)')

    # === 5. RSI (0-10 points) ===
    if not (SignalConfig.GC_RSI_MIN <= rsi <= SignalConfig.GC_RSI_MAX):
        return _no_signal_scored(f'RSI outside range')

    if 50 <= rsi <= 65:
        score += 10
        reasons.append(f'Good RSI ({rsi:.0f})')
    else:
        score += 7
        reasons.append(f'OK RSI ({rsi:.0f})')

    # === BONUS: Squeeze (0-5 points extra) ===
    if bb_width < SignalConfig.BB_WIDTH_TIGHT:
        score += 5
        reasons.append('Squeeze')

    return {
        'side': 'buy',
        'score': min(100, score),
        'msg': f'Golden Cross: {score:.0f}/100 | {", ".join(reasons[:3])}',
        'reasons': reasons,
        'limit_price': close,
        'stop_loss': None,
        'signal_type': 'golden_cross'
    }


def bollinger_buy(data: IndicatorData) -> SignalResult:
    """
    Bollinger Band Bounce - Score 0-100

    Scoring Breakdown:
    - Band Position (0-25): Closer to lower band = higher
    - Stochastic (0-20): Oversold bounce
    - RSI Recovery (0-20): 28-45 range
    - Volume (0-15): Surge confirmation
    - Trend Context (0-15): ADX + EMA structure
    - MACD/OBV (0-5): Bonus confirmation

    Total: 0-100 points
    """
    close = data.get('close', 0)
    bollinger_lower = data.get('bollinger_lower', 0)
    rsi = data.get('rsi', 50)
    volume_ratio = data.get('volume_ratio', 0)
    sma200 = data.get('sma200', 0)
    ema20 = data.get('ema20', 0)
    ema50 = data.get('ema50', 0)
    adx = data.get('adx', 0)
    macd = data.get('macd', 0)
    macd_signal = data.get('macd_signal', 0)
    obv_trending_up = data.get('obv_trending_up', False)
    stoch_k = data.get('stoch_k', 50)
    stoch_d = data.get('stoch_d', 50)
    stoch_bullish = data.get('stoch_bullish', False)
    daily_change_pct = data.get('daily_change_pct', 0)

    score = 0
    reasons = []

    # === CORE FILTERS ===
    if bollinger_lower == 0:
        return _no_signal_scored('No Bollinger data')

    if close <= sma200:
        return _no_signal_scored('Below 200 SMA')

    distance_from_lower = ((close - bollinger_lower) / bollinger_lower * 100)

    if distance_from_lower > SignalConfig.BB_DISTANCE_FROM_LOWER_MAX:
        return _no_signal_scored(f'Price {distance_from_lower:.1f}% above lower band')

    # === 1. BAND POSITION (0-25 points) ===
    if distance_from_lower <= 0.5:
        score += 25
        reasons.append(f'At lower band ({distance_from_lower:.1f}%)')
    elif distance_from_lower <= 1.5:
        score += 22
        reasons.append(f'Very near band ({distance_from_lower:.1f}%)')
    elif distance_from_lower <= 2.5:
        score += 18
        reasons.append(f'Near band ({distance_from_lower:.1f}%)')
    else:
        score += 14
        reasons.append(f'Close to band ({distance_from_lower:.1f}%)')

    # === 2. STOCHASTIC (0-20 points) ===
    if stoch_k < SignalConfig.BB_STOCH_OVERSOLD:
        score += 12
        reasons.append(f'Stoch oversold ({stoch_k:.0f})')

        if stoch_bullish:
            score += 8
            reasons.append('Stoch bullish cross')
    else:
        score += 5
        reasons.append(f'Stoch ({stoch_k:.0f})')

    # === 3. RSI RECOVERY (0-20 points) ===
    if not (SignalConfig.BB_RSI_MIN <= rsi <= SignalConfig.BB_RSI_MAX):
        return _no_signal_scored(f'RSI {rsi:.0f} outside range')

    if 30 <= rsi <= 38:
        score += 20
        reasons.append(f'Perfect RSI ({rsi:.0f})')
    elif 28 <= rsi < 30 or 38 < rsi <= 42:
        score += 16
        reasons.append(f'Good RSI ({rsi:.0f})')
    else:
        score += 12
        reasons.append(f'OK RSI ({rsi:.0f})')

    # === 4. VOLUME (0-15 points) ===
    if volume_ratio >= SignalConfig.BB_VOLUME_RATIO_STRONG:
        score += 15
        reasons.append(f'Strong vol ({volume_ratio:.1f}x)')
    elif volume_ratio >= SignalConfig.BB_VOLUME_RATIO_GOOD:
        score += 12
        reasons.append(f'Good vol ({volume_ratio:.1f}x)')
    else:
        score += 8
        reasons.append(f'OK vol ({volume_ratio:.1f}x)')

    # === 5. TREND CONTEXT (0-15 points) ===
    if ema20 > ema50:
        score += 8
        reasons.append('EMA20>50')

    if adx >= SignalConfig.BB_ADX_STRONG:
        score += 7
        reasons.append(f'Strong ADX ({adx:.0f})')
    elif adx >= SignalConfig.BB_ADX_MODERATE:
        score += 5
        reasons.append(f'Moderate ADX ({adx:.0f})')

    # === 6. MACD/OBV BONUS (0-5 points) ===
    if macd > macd_signal:
        score += 3
        reasons.append('MACD+')

    if obv_trending_up:
        score += 2
        reasons.append('OBV+')

    if daily_change_pct > 0:
        score += 2
        reasons.append('Bouncing')

    return {
        'side': 'buy',
        'score': min(100, score),
        'msg': f'Bollinger Bounce: {score:.0f}/100 | {", ".join(reasons[:3])}',
        'reasons': reasons,
        'limit_price': close,
        'stop_loss': None,
        'signal_type': 'bollinger_buy'
    }


def _no_signal_scored(reason: str) -> SignalResult:
    """
    Return no signal with 0 score
    """
    return {
        'side': 'hold',
        'score': 0,
        'msg': f'No signal: {reason}',
        'reasons': [reason],
        'limit_price': None,
        'stop_loss': None,
        'signal_type': 'no_signal'
    }


# ===================================================================================
# STRATEGY REGISTRY
# ===================================================================================

BUY_STRATEGIES: Dict[str, Any] = {
    'swing_trade_1': swing_trade_1,
    # 'swing_trade_2': swing_trade_2,
    'consolidation_breakout': consolidation_breakout,
    'golden_cross': golden_cross,
    'bollinger_buy': bollinger_buy,
}