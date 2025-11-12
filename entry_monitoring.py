"""
Signal Strength & Confluence System

Adaptive signal evaluation similar to the adaptive exit system.
Scores signals 0-100, detects confluence, and adjusts position sizing.

Usage:
    from signal_strength import evaluate_all_signals, calculate_adaptive_position_size

    # Evaluate all signals
    eval_result = evaluate_all_signals(data, signal_list)

    # Get position size
    position_size = calculate_adaptive_position_size(
        cash=cash,
        signal_evaluation=eval_result,
        market_condition='strong'
    )
"""

import signals
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
    SIZE_STRONG = 1.0  # 100% of base
    SIZE_GOOD = 0.8  # 80% of base
    SIZE_WEAK = 0.6  # 60% of base
    SIZE_SKIP = 0.0  # Don't trade

    # Base position sizes by market condition
    BASE_SIZE_STRONG_MARKET = 0.15  # 15% in strong markets
    BASE_SIZE_NEUTRAL_MARKET = 0.12  # 12% in neutral markets
    BASE_SIZE_WEAK_MARKET = 0.10  # 10% in weak markets

    # Safety caps
    MAX_POSITION_PCT = 0.25  # Never more than 25% of cash
    MIN_POSITION_PCT = 0.05  # Never less than 5% of cash


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
    valid_signals = []

    # Check each signal
    for signal_name in signal_list:
        try:
            # Get signal function
            signal_func = getattr(signals, signal_name, None)
            if signal_func is None:
                continue

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


# =============================================================================
# POSITION SIZING
# =============================================================================

def calculate_adaptive_position_size(cash, signal_evaluation, market_condition='neutral'):
    """
    Calculate position size based on signal strength and market conditions

    Formula:
        position_size = cash × base_pct × signal_multiplier

    Where:
        - base_pct depends on market condition (10-15%)
        - signal_multiplier from signal evaluation (0.6-1.5x)

    Args:
        cash: Available cash
        signal_evaluation: Result from evaluate_all_signals()
        market_condition: 'strong', 'neutral', or 'weak'

    Returns:
        float: Dollar amount for position
    """
    config = SignalStrengthConfig

    # Base position sizes by market condition
    base_pcts = {
        'strong': config.BASE_SIZE_STRONG_MARKET,
        'neutral': config.BASE_SIZE_NEUTRAL_MARKET,
        'weak': config.BASE_SIZE_WEAK_MARKET
    }

    base_pct = base_pcts.get(market_condition, config.BASE_SIZE_NEUTRAL_MARKET)

    # Apply signal strength multiplier
    size_multiplier = signal_evaluation['size_multiplier']

    # Calculate position size
    position_size = cash * base_pct * size_multiplier

    # Safety caps
    max_position = cash * config.MAX_POSITION_PCT
    min_position = cash * config.MIN_POSITION_PCT

    # Apply caps (but allow zero for 'skip' recommendation)
    if size_multiplier == 0:
        return 0

    position_size = max(min_position, min(max_position, position_size))

    return position_size


# =============================================================================
# DISPLAY HELPERS
# =============================================================================

def print_signal_evaluation(ticker, signal_eval, market_condition):
    """
    Pretty print signal evaluation results

    Args:
        ticker: Stock symbol
        signal_eval: Result from evaluate_all_signals()
        market_condition: Market condition string
    """
    if signal_eval['recommendation'] == 'skip':
        print(f" * SKIP: {ticker} - No strong signals (score < {SignalStrengthConfig.WEAK_THRESHOLD})")
        return

    print(f"\n{'=' * 70}")
    print(f"🎯 SIGNAL EVALUATION - {ticker}")
    print(f"{'=' * 70}")

    # Show all valid signals
    print(f"Valid Signals: {signal_eval['confluence_count']}")
    for sig in signal_eval['signals']:
        name = sig['name']
        score = sig['strength']['score']
        level = sig['strength']['level']
        breakdown = sig['strength']['breakdown']

        # Format level with emoji
        level_emoji = {
            'exceptional': '🔥',
            'strong': '🟢',
            'good': '🟡',
            'weak': '🟠',
            'very_weak': '🔴'
        }

        emoji = level_emoji.get(level, '⚪')
        print(f"  {emoji} {name}: {score:.0f} pts ({level.upper()})")
        print(f"      Tech: {breakdown['technical']:.0f} | Vol: {breakdown['volume']:.0f} | "
              f"Trend: {breakdown['trend']:.0f} | R/R: {breakdown['risk_reward']:.0f}")

    # Show best signal and scoring
    best = signal_eval['best_signal']
    print(f"\nBest Signal: {best['name']}")
    print(f"Base Score: {best['strength']['score']:.0f} pts")

    if signal_eval['confluence_bonus'] > 0:
        print(
            f"Confluence Bonus: +{signal_eval['confluence_bonus']:.0f} pts ({signal_eval['confluence_count']} signals)")

    print(f"Final Score: {signal_eval['final_score']:.0f} pts")
    print(f"Market Condition: {market_condition.upper()}")
    print(f"Recommendation: {signal_eval['recommendation'].upper()}")
    print(f"Size Multiplier: {signal_eval['size_multiplier']:.1f}x")
    print(f"{'=' * 70}")


# =============================================================================
# USAGE EXAMPLE
# =============================================================================

def example_usage():
    """
    Example showing how to use signal strength system
    """

    # Mock data (in real usage, this comes from stock_data.process_data())
    data = {
        'close': 100.0,
        'rsi': 60,
        'adx': 35,
        'volume_ratio': 2.5,
        'macd': 1.5,
        'macd_signal': 1.0,
        'macd_histogram': 0.5,
        'ema8': 99.0,
        'ema20': 98.0,
        'ema50': 95.0,
        'sma200': 90.0
    }

    # Define signal list
    signal_list = [
        'momentum_breakout',
        'consolidation_breakout',
        'swing_trade_1',
        'gap_up_continuation',
        'swing_trade_2'
    ]

    # Evaluate all signals
    signal_eval = evaluate_all_signals(data, signal_list)

    # Get market condition (from existing adaptive exit system)
    market_score = calculate_market_condition_score(data)
    market_condition = market_score['condition']

    # Calculate position size
    cash = 100000  # $100k cash
    position_size = calculate_adaptive_position_size(
        cash=cash,
        signal_evaluation=signal_eval,
        market_condition=market_condition
    )

    # Display results
    print_signal_evaluation('NVDA', signal_eval, market_condition)
    print(f"Position Size: ${position_size:,.0f}\n")

    return signal_eval, position_size


if __name__ == "__main__":
    # Run example
    example_usage()