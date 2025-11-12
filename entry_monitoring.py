"""
Signal Strength & Confluence System

Adaptive signal evaluation similar to the adaptive exit system.
Scores signals 0-100, detects confluence, and adjusts position sizing.

Usage:
    from entry_monitoring import evaluate_all_signals

    # Evaluate all signals
    eval_result = evaluate_all_signals(data, signal_list)

    # Check recommendation
    if eval_result['recommendation'] != 'skip':
        # Trade!
"""

from position_monitoring import calculate_market_condition_score


# =============================================================================
# CONFIGURATION
# =============================================================================

class SignalStrengthConfig:
    """Configuration for signal strength thresholds and multipliers"""

    # Score thresholds
    EXCEPTIONAL_THRESHOLD = 90
    STRONG_THRESHOLD = 75
    GOOD_THRESHOLD = 60
    WEAK_THRESHOLD = 40

    # Confluence bonuses
    CONFLUENCE_BONUS_4_PLUS = 30  # 4+ signals
    CONFLUENCE_BONUS_3 = 20  # 3 signals
    CONFLUENCE_BONUS_2 = 10  # 2 signals

    # Position size multipliers
    SIZE_EXCEPTIONAL = 1.5  # 150% of base
    SIZE_STRONG = 1.2  # 120% of base
    SIZE_GOOD = 1.0  # 100% of base
    SIZE_WEAK = 0.8  # 80% of base
    SIZE_SKIP = 0.0  # Don't trade


# =============================================================================
# SIGNAL STRENGTH CALCULATION
# =============================================================================

def calculate_signal_strength(signal_type, data):
    """
    Calculate strength score for a specific signal (0-100)

    Scoring Components:
    1. Technical Strength (40 pts) - RSI, MACD, ADX quality
    2. Volume Conviction (25 pts) - Volume confirmation
    3. Trend Quality (20 pts) - EMA alignment, distance from 200 SMA
    4. Risk/Reward (15 pts) - Entry timing

    Args:
        signal_type: Signal name (e.g., 'momentum_breakout')
        data: Dictionary with technical indicators

    Returns:
        dict: {
            'score': float (0-100),
            'level': str,
            'breakdown': dict
        }
    """
    score = 0.0
    breakdown = {}

    # Get indicators
    close = data.get('close', 0)
    rsi = data.get('rsi', 50)
    adx = data.get('adx', 0)
    volume_ratio = data.get('volume_ratio', 0)
    macd = data.get('macd', 0)
    macd_signal = data.get('macd_signal', 0)
    macd_hist = data.get('macd_histogram', 0)
    ema8 = data.get('ema8', 0)
    ema20 = data.get('ema20', 0)
    ema50 = data.get('ema50', 0)
    sma200 = data.get('sma200', 0)

    # === 1. TECHNICAL STRENGTH (40 points) ===
    technical_score = 0.0

    # RSI positioning (15 pts)
    if 55 <= rsi <= 65:  # Sweet spot
        technical_score += 15.0
    elif 50 <= rsi <= 70:  # Good
        technical_score += 12.0
    elif 45 <= rsi <= 75:  # Acceptable
        technical_score += 8.0
    elif 40 <= rsi <= 80:  # Marginal
        technical_score += 4.0

    # MACD strength (15 pts)
    if macd > macd_signal and macd_hist > 0:
        # Bullish and expanding - scale by histogram strength
        macd_strength = min(15.0, 10.0 + abs(macd_hist) * 2)
        technical_score += macd_strength
    elif macd > macd_signal:
        # Bullish but not expanding
        technical_score += 8.0

    # ADX trend strength (10 pts)
    if adx > 40:
        technical_score += 10.0
    elif adx > 30:
        technical_score += 8.0
    elif adx > 20:
        technical_score += 5.0
    elif adx > 15:
        technical_score += 2.0

    score += technical_score
    breakdown['technical'] = round(technical_score, 1)

    # === 2. VOLUME CONVICTION (25 points) ===
    volume_score = 0.0

    if volume_ratio > 3.0:
        volume_score = 25.0  # Exceptional volume
    elif volume_ratio > 2.5:
        volume_score = 22.0
    elif volume_ratio > 2.0:
        volume_score = 20.0
    elif volume_ratio > 1.5:
        volume_score = 15.0
    elif volume_ratio > 1.2:
        volume_score = 10.0
    elif volume_ratio > 1.0:
        volume_score = 5.0

    score += volume_score
    breakdown['volume'] = round(volume_score, 1)

    # === 3. TREND QUALITY (20 points) ===
    trend_score = 0.0

    # EMA alignment (12 pts)
    if close > ema8 > ema20 > ema50 > sma200:
        trend_score += 12.0  # Perfect alignment
    elif close > ema20 > ema50 > sma200:
        trend_score += 10.0  # Good alignment
    elif close > ema20 > sma200:
        trend_score += 7.0  # Decent
    elif close > sma200:
        trend_score += 4.0  # Weak

    # Distance from 200 SMA (8 pts)
    if sma200 > 0:
        distance_pct = ((close - sma200) / sma200 * 100)
        if distance_pct > 20:
            trend_score += 8.0
        elif distance_pct > 10:
            trend_score += 6.0
        elif distance_pct > 5:
            trend_score += 4.0
        elif distance_pct > 0:
            trend_score += 2.0

    score += trend_score
    breakdown['trend'] = round(trend_score, 1)

    # === 4. RISK/REWARD SETUP (15 points) ===
    rr_score = 0.0

    # Distance from EMA20 (entry timing)
    if ema20 > 0:
        distance_from_ema20 = abs((close - ema20) / ema20 * 100)

        # Closer to EMA20 = better R/R
        if distance_from_ema20 < 2:
            rr_score += 15.0  # Very close
        elif distance_from_ema20 < 4:
            rr_score += 12.0
        elif distance_from_ema20 < 6:
            rr_score += 9.0
        elif distance_from_ema20 < 8:
            rr_score += 6.0
        elif distance_from_ema20 < 10:
            rr_score += 3.0

    score += rr_score
    breakdown['risk_reward'] = round(rr_score, 1)

    # === DETERMINE LEVEL ===
    config = SignalStrengthConfig

    if score >= config.EXCEPTIONAL_THRESHOLD:
        level = 'exceptional'
    elif score >= config.STRONG_THRESHOLD:
        level = 'strong'
    elif score >= config.GOOD_THRESHOLD:
        level = 'good'
    elif score >= config.WEAK_THRESHOLD:
        level = 'weak'
    else:
        level = 'very_weak'

    return {
        'score': round(score, 2),
        'level': level,
        'breakdown': breakdown
    }


# =============================================================================
# MULTI-SIGNAL EVALUATION
# =============================================================================

def evaluate_all_signals(data, signal_list):
    """
    Evaluate ALL signals and return scored results with confluence

    OPTIMIZED: Uses BUY_STRATEGIES registry instead of getattr()

    Process:
    1. Check each signal in list
    2. If valid (side='buy'), calculate strength
    3. Identify best signal
    4. Apply confluence bonus
    5. Return recommendation and position size multiplier

    Args:
        data: Stock data dictionary
        signal_list: List of signal names to check

    Returns:
        dict: {
            'signals': list of valid signals with scores,
            'best_signal': dict (highest scoring),
            'confluence_count': int,
            'confluence_bonus': float,
            'final_score': float,
            'recommendation': str,
            'size_multiplier': float
        }
    """
    # Import BUY_STRATEGIES registry from signals module
    from signals import BUY_STRATEGIES

    valid_signals = []

    # Check each signal
    for signal_name in signal_list:
        try:
            # Get signal function from registry (OPTIMIZED)
            if signal_name not in BUY_STRATEGIES:
                continue

            signal_func = BUY_STRATEGIES[signal_name]

            # Get signal result
            signal_result = signal_func(data)

            # If signal is valid (side='buy')
            if signal_result and isinstance(signal_result, dict) and signal_result.get('side') == 'buy':
                # Calculate strength
                strength = calculate_signal_strength(signal_name, data)

                valid_signals.append({
                    'name': signal_name,
                    'signal_data': signal_result,
                    'strength': strength
                })
        except Exception as e:
            # Skip signals that error
            print(f"Warning: Error evaluating {signal_name}: {e}")
            continue

    # No valid signals
    if not valid_signals:
        return {
            'signals': [],
            'best_signal': None,
            'confluence_count': 0,
            'confluence_bonus': 0,
            'final_score': 0,
            'recommendation': 'skip',
            'size_multiplier': 0.0
        }

    # Sort by strength score (highest first)
    valid_signals.sort(key=lambda x: x['strength']['score'], reverse=True)
    best_signal = valid_signals[0]

    # Calculate confluence bonus
    config = SignalStrengthConfig
    confluence_count = len(valid_signals)

    if confluence_count >= 4:
        confluence_bonus = config.CONFLUENCE_BONUS_4_PLUS
    elif confluence_count == 3:
        confluence_bonus = config.CONFLUENCE_BONUS_3
    elif confluence_count == 2:
        confluence_bonus = config.CONFLUENCE_BONUS_2
    else:
        confluence_bonus = 0.0

    # Final score (capped at 100)
    final_score = min(100.0, best_signal['strength']['score'] + confluence_bonus)

    # Determine recommendation and size multiplier
    if final_score >= config.EXCEPTIONAL_THRESHOLD:
        recommendation = 'buy_large'
        size_multiplier = config.SIZE_EXCEPTIONAL
    elif final_score >= config.STRONG_THRESHOLD:
        recommendation = 'buy_full'
        size_multiplier = config.SIZE_STRONG
    elif final_score >= config.GOOD_THRESHOLD:
        recommendation = 'buy_reduced'
        size_multiplier = config.SIZE_GOOD
    elif final_score >= config.WEAK_THRESHOLD:
        recommendation = 'buy_small'
        size_multiplier = config.SIZE_WEAK
    else:
        recommendation = 'skip'
        size_multiplier = config.SIZE_SKIP

    return {
        'signals': valid_signals,
        'best_signal': best_signal,
        'confluence_count': confluence_count,
        'confluence_bonus': confluence_bonus,
        'final_score': final_score,
        'recommendation': recommendation,
        'size_multiplier': size_multiplier
    }