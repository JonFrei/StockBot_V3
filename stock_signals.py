"""
Stock Signal Generation with Type Hints and Extracted Constants
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

    # SWING_TRADE_1: Early Momentum Catch
    ST1_EMA20_DISTANCE_MAX = 3.0  # % above EMA20
    ST1_RSI_MIN = 45
    ST1_RSI_MAX = 70
    ST1_VOLUME_RATIO_MIN = 1.3
    ST1_ADX_MIN = 20
    ST1_ADX_MAX = 35

    # SWING_TRADE_2: Pullback in Trend (IMPROVED)
    ST2_PULLBACK_MIN = 2.0  # Keep - shallow pullbacks are fine
    ST2_PULLBACK_MAX = 8.0  # TIGHTENED from 12.0 - avoid broken trends
    ST2_RSI_MIN = 42  # INCREASED from 40 - avoid weak bounces
    ST2_RSI_MAX = 65  # REDUCED from 68 - avoid overbought entries
    ST2_VOLUME_RATIO_MIN = 1.25  # INCREASED from 1.15 - require stronger confirmation
    ST2_ADX_MIN = 22  # INCREASED from 18 - require stronger trend
    ST2_DAILY_CHANGE_MIN = -3.0  # TIGHTENED from -4.0 - avoid catching falling knives

    # CONSOLIDATION_BREAKOUT - QUALITY FOCUSED
    CB_RANGE_MAX = 18.0  # Keep - wider consolidations OK
    CB_VOLUME_RATIO_MIN = 1.4  # INCREASE from 1.3 → Need strong conviction
    CB_RSI_MIN = 52  # INCREASE from 48 → Must be clearly bullish
    CB_RSI_MAX = 70  # DECREASE from 72 → Avoid overbought
    CB_EMA20_DISTANCE_MAX = 10.0  # TIGHTEN from 12.0 → Stay close to support
    CB_LOOKBACK_PERIODS = 10  # Keep
    CB_BREAKOUT_THRESHOLD = 0.995  # TIGHTEN from 0.99 → Wait for clear break
    CB_ADX_MIN = 22  # INCREASE from 20 → Ensure strong trend
    CB_MACD_REQUIRED = True  # Keep

    # GOLDEN_CROSS
    GC_DISTANCE_MIN = 0.0  # % EMA50 above SMA200
    GC_DISTANCE_MAX = 10.0
    GC_ADX_MIN = 18
    GC_VOLUME_RATIO_MIN = 1.2
    GC_RSI_MIN = 45
    GC_RSI_MAX = 70

    # BOLLINGER_BUY
    BB_BOLLINGER_PROXIMITY = 1.02  # Within 2% of lower band
    BB_RSI_MIN = 30
    BB_RSI_MAX = 42
    BB_VOLUME_RATIO_MIN = 1.5
    BB_ADX_MIN = 20


# Type aliases for clarity
IndicatorData = Dict[str, Any]
SignalResult = Dict[str, Any]
SignalList = List[str]


# ===================================================================================
# SIGNAL PROCESSOR
# ===================================================================================

class SignalProcessor:
    """
    Handles signal detection and routing

    Responsibilities:
    - Check signals in priority order
    - One signal per ticker (first match wins)
    """

    def process_ticker(self, ticker: str, data: Dict, spy_data: Optional[Dict] = None) -> Dict:
        """
        Process a single ticker through signal pipeline

        Args:
            ticker: Stock symbol
            data: Stock technical indicators
            spy_data: SPY indicators (optional)

        Returns:
            {
                'action': 'buy_now' | 'skip',
                'signal_type': str or None,
                'signal_data': dict or None
            }
        """

        # Check immediate signals (priority order, first match wins)
        for key, val in BUY_STRATEGIES.items():
            signal_func = val
            if not signal_func:
                continue

            result = signal_func(data)

            if result and result.get('side') == 'buy':
                return {
                    'action': 'buy',
                    'signal_type': key,
                    'signal_data': result
                }

        # No signals triggered
        return {
            'action': 'skip',
            'signal_type': None,
            'signal_data': None
        }


# ===================================================================================
# BUY SIGNALS
# ===================================================================================

def swing_trade_1(data: IndicatorData) -> SignalResult:
    """
    Early Momentum Catch - Catches trend FORMATION

    Strategy: Buy stocks building momentum BEFORE they become obvious
    - Price near EMA20 support (within 3% above)
    - MACD bullish and accelerating
    - Volume picking up (1.3x+)
    - ADX showing developing trend (20-35)

    Args:
        data: Stock indicator data

    Returns:
        Signal result dictionary
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

    # 1. Uptrend structure
    if not (ema20 > ema50):
        return _no_signal('EMA20 not above EMA50')

    # 2. Price above 200 SMA
    if close <= sma200:
        return _no_signal('Below 200 SMA')

    # 3. Price NEAR EMA20 (not extended)
    ema20_distance = ((close - ema20) / ema20 * 100) if ema20 > 0 else 0
    if close < ema20:
        return _no_signal('Price below EMA20')
    if ema20_distance > SignalConfig.ST1_EMA20_DISTANCE_MAX:
        return _no_signal(f'Price extended {ema20_distance:.1f}% above EMA20')

    # 4. RSI: Healthy momentum zone
    if not (SignalConfig.ST1_RSI_MIN <= rsi <= SignalConfig.ST1_RSI_MAX):
        return _no_signal(f'RSI {rsi:.0f} not in {SignalConfig.ST1_RSI_MIN}-{SignalConfig.ST1_RSI_MAX} range')

    # 5. Volume confirmation
    if volume_ratio < SignalConfig.ST1_VOLUME_RATIO_MIN:
        return _no_signal(f'Volume {volume_ratio:.1f}x too low')

    # 6. MACD: Bullish AND accelerating
    if macd <= macd_signal:
        return _no_signal('MACD not bullish')

    if macd_hist <= macd_hist_prev:
        return _no_signal('MACD not accelerating')

    # 7. OBV confirmation
    if not obv_trending_up:
        return _no_signal('OBV not confirming')

    # 8. ADX: Developing trend
    if adx < SignalConfig.ST1_ADX_MIN:
        return _no_signal(f'ADX {adx:.0f} too weak')
    if adx > SignalConfig.ST1_ADX_MAX:
        return _no_signal(f'ADX {adx:.0f} too strong (trend mature)')

    return {
        'side': 'buy',
        'msg': f'🚀 Early Momentum: {ema20_distance:.1f}% from EMA20, RSI {rsi:.0f}, Vol {volume_ratio:.1f}x, ADX {adx:.0f}, MACD↑',
        'limit_price': close,
        'stop_loss': None,
        'signal_type': 'swing_trade_1'
    }


def swing_trade_2(data: IndicatorData) -> SignalResult:
    """
    Pullback Buy - Catches PULLBACKS in established trends

    Strategy: Buy quality pullbacks in confirmed uptrends
    - Pullback to EMA20 (2-8% away)
    - RSI oversold but not extreme (42-65)
    - Volume confirming (1.25x+)
    - ADX confirming trend (22+)

    Args:
        data: Stock indicator data

    Returns:
        Signal result dictionary
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

    # 3. Pullback depth
    ema20_distance = abs((close - ema20) / ema20 * 100) if ema20 > 0 else 100
    if not (SignalConfig.ST2_PULLBACK_MIN <= ema20_distance <= SignalConfig.ST2_PULLBACK_MAX):
        return _no_signal(
            f'Pullback {ema20_distance:.1f}% not in {SignalConfig.ST2_PULLBACK_MIN}-{SignalConfig.ST2_PULLBACK_MAX}% range')

    # 4. RSI
    if not (SignalConfig.ST2_RSI_MIN <= rsi <= SignalConfig.ST2_RSI_MAX):
        return _no_signal(f'RSI {rsi:.0f} outside {SignalConfig.ST2_RSI_MIN}-{SignalConfig.ST2_RSI_MAX}')

    # 5. Volume
    if volume_ratio < SignalConfig.ST2_VOLUME_RATIO_MIN:
        return _no_signal(f'Volume {volume_ratio:.1f}x below {SignalConfig.ST2_VOLUME_RATIO_MIN}x')

    # 6. MACD momentum
    if macd <= macd_signal:
        return _no_signal('MACD not bullish')

    # 7. OBV confirmation
    if not obv_trending_up:
        return _no_signal('OBV not confirming')

    # 8. ADX requirement
    if adx < SignalConfig.ST2_ADX_MIN:
        return _no_signal(f'ADX {adx:.0f} too weak')

    # 9. Price stabilization
    if daily_change_pct < SignalConfig.ST2_DAILY_CHANGE_MIN:
        return _no_signal(f'Price dropping too fast ({daily_change_pct:.1f}%)')

    # 10. Stochastic confirmation - must not be in extreme oversold
    stoch_k = data.get('stoch_k', 50)
    if stoch_k < 20:
        return _no_signal(f'Stochastic too oversold ({stoch_k:.0f})')

    return {
        'side': 'buy',
        'msg': f'✅ Pullback: {ema20_distance:.1f}% from EMA20, RSI {rsi:.0f}, ADX {adx:.0f}, OBV+',
        'limit_price': close,
        'stop_loss': None,
        'signal_type': 'swing_trade_2'
    }


def consolidation_breakout(data: IndicatorData) -> SignalResult:
    """
    Consolidation Breakout - ENHANCED FOR HIGHER WIN SIZE

    Strategy: Only take HIGH CONVICTION breakouts
    - Tighter consolidation range
    - Stronger volume surge (1.4x+)
    - Higher RSI floor (52+) = already in bullish zone
    - Closer to EMA20 (within 10%)
    - MACD must be bullish
    - ADX must show trend formation (22+)
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

    raw_data = data.get('raw', None)
    if raw_data is None or len(raw_data) < SignalConfig.CB_LOOKBACK_PERIODS:
        return _no_signal('Insufficient data')

    # Calculate consolidation metrics
    recent_highs = raw_data['high'].iloc[-SignalConfig.CB_LOOKBACK_PERIODS:].values
    recent_lows = raw_data['low'].iloc[-SignalConfig.CB_LOOKBACK_PERIODS:].values
    consolidation_range = (max(recent_highs) - min(recent_lows)) / min(recent_lows) * 100
    high_10d = max(recent_highs)

    # 1. Tight consolidation
    if consolidation_range > SignalConfig.CB_RANGE_MAX:
        return _no_signal(f'Range {consolidation_range:.1f}% too wide')

    # 2. Trend structure
    if close <= sma200 or ema20 <= ema50:
        return _no_signal('Weak trend structure')

    # 3. Breakout confirmation
    if close < high_10d * SignalConfig.CB_BREAKOUT_THRESHOLD:
        return _no_signal('Not breaking out')

    # 4. STRONG volume surge
    if volume_ratio < SignalConfig.CB_VOLUME_RATIO_MIN:
        return _no_signal(f'Volume {volume_ratio:.1f}x too weak (need {SignalConfig.CB_VOLUME_RATIO_MIN}x+)')

    # 5. RSI in bullish zone
    if not (SignalConfig.CB_RSI_MIN <= rsi <= SignalConfig.CB_RSI_MAX):
        return _no_signal(f'RSI {rsi:.0f} outside {SignalConfig.CB_RSI_MIN}-{SignalConfig.CB_RSI_MAX}')

    # 6. Not overextended
    distance_to_ema20 = abs((close - ema20) / ema20 * 100) if ema20 > 0 else 100
    if distance_to_ema20 > SignalConfig.CB_EMA20_DISTANCE_MAX:
        return _no_signal(f'Too far from EMA20 ({distance_to_ema20:.1f}% > {SignalConfig.CB_EMA20_DISTANCE_MAX}%)')

    # 7. ADX shows trend formation
    if adx < SignalConfig.CB_ADX_MIN:
        return _no_signal(f'ADX {adx:.0f} too weak (need {SignalConfig.CB_ADX_MIN}+)')

    # 8. MACD bullish
    if SignalConfig.CB_MACD_REQUIRED and macd <= macd_signal:
        return _no_signal('MACD not bullish')

    return {
        'side': 'buy',
        'msg': f'📦 STRONG Breakout: {consolidation_range:.1f}% range, Vol {volume_ratio:.1f}x, RSI {rsi:.0f}, ADX {adx:.0f}',
        'limit_price': close,
        'stop_loss': None,
        'signal_type': 'consolidation_breakout'
    }


def golden_cross(data: IndicatorData) -> SignalResult:
    """
    Golden Cross - EMA50 crossing above SMA200

    Strategy: Catch fresh golden crosses with confirmation
    - EMA50 0-10% above SMA200 (fresh cross)
    - ADX showing trend strength (18+)
    - Volume confirmation (1.2x+)
    - RSI in healthy range (45-70)

    Args:
        data: Stock indicator data

    Returns:
        Signal result dictionary
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

    # Fresh cross check
    if not (SignalConfig.GC_DISTANCE_MIN <= distance_pct <= SignalConfig.GC_DISTANCE_MAX):
        return _no_signal('No fresh golden cross')

    # Basic confirmations
    if adx < SignalConfig.GC_ADX_MIN:
        return _no_signal('ADX too weak')

    if volume_ratio < SignalConfig.GC_VOLUME_RATIO_MIN:
        return _no_signal('Volume too low')

    if not (SignalConfig.GC_RSI_MIN <= rsi <= SignalConfig.GC_RSI_MAX):
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


def bollinger_buy(data: IndicatorData) -> SignalResult:
    """
    Bollinger Band Bounce - Buy oversold bounces in uptrends

    Strategy: Buy strong bounces off lower Bollinger Band
    - Price at/near lower Bollinger Band (within 2%)
    - Confirmed uptrend (EMA20 > EMA50, ADX > 20)
    - RSI oversold (30-42)
    - High volume surge (1.5x+)
    - MACD bullish

    Args:
        data: Stock indicator data

    Returns:
        Signal result dictionary
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

    # Require strong trend
    if adx < SignalConfig.BB_ADX_MIN:
        return _no_signal('ADX too weak for Bollinger')

    # Require uptrend structure
    if not (ema20 > ema50):
        return _no_signal('No uptrend structure')

    # Price at lower Bollinger
    if bollinger_lower == 0 or close > bollinger_lower * SignalConfig.BB_BOLLINGER_PROXIMITY:
        return _no_signal('Not close enough to lower Bollinger')

    # Above 200 SMA
    if close <= sma200:
        return _no_signal('Below 200 SMA')

    # RSI oversold
    if not (SignalConfig.BB_RSI_MIN <= rsi <= SignalConfig.BB_RSI_MAX):
        return _no_signal(f'RSI {rsi:.0f} not in {SignalConfig.BB_RSI_MIN}-{SignalConfig.BB_RSI_MAX} range')

    # Volume confirmation
    if volume_ratio < SignalConfig.BB_VOLUME_RATIO_MIN:
        return _no_signal(f'Volume {volume_ratio:.1f}x below {SignalConfig.BB_VOLUME_RATIO_MIN}x')

    # MACD momentum confirmation
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


def _no_signal(reason: str) -> SignalResult:
    """
    Helper function to return consistent 'no signal' message

    Args:
        reason: Human-readable reason for no signal

    Returns:
        No-signal result dictionary
    """
    return {
        'side': 'hold',
        'msg': f'No signal: {reason}',
        'limit_price': None,
        'stop_loss': None,
        'signal_type': 'no_signal'
    }


# ===================================================================================
# STRATEGY REGISTRY
# ===================================================================================

BUY_STRATEGIES: Dict[str, Any] = {
    'consolidation_breakout': consolidation_breakout,
    'swing_trade_1': swing_trade_1,
    # 'swing_trade_2': swing_trade_2,
    'golden_cross': golden_cross,
    # 'bollinger_buy': bollinger_buy,
}
