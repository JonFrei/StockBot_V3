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
    for strategy_name in buy_signal_list:
        if strategy_name in BUY_STRATEGIES:
            strategy_func = BUY_STRATEGIES[strategy_name]
            signal = strategy_func(data)

            # Return first valid buy signal
            if signal and isinstance(signal, dict) and signal.get('side') == 'buy':
                return signal

    # No buy signal found
    return None


def sell_signals(data, sell_signal_list):
    """
    Check multiple sell strategies and return first valid signal
    Returns dict or None
    """
    for strategy_name in sell_signal_list:
        if strategy_name in SELL_STRATEGIES:
            strategy_func = SELL_STRATEGIES[strategy_name]
            signal = strategy_func(data)

            # Return first valid sell signal
            if signal and isinstance(signal, dict) and signal.get('side') == 'sell':
                return signal

    # No sell signal found
    return None


# ===================================================================================
# BUY SIGNALS
# ===================================================================================

def swing_trade_1(data):
    """
    Swing trading strategy using EMA crossovers, RSI, and volume

    Entry Rules:
    - long: Price above EMA20 > EMA50, RSI 40-70, above 200 SMA
    - short: Price below EMA20 < EMA50, RSI 30-60, below 200 SMA
    - Exit: 1% stop loss, 2:1 reward/risk target

    Args:
        data: Dictionary/Series with technical indicators

    Returns:
        Dictionary with decision and trade parameters
    """
    # Get indicator values
    ema20 = data.get('ema20', 0)
    ema50 = data.get('ema50', 0)
    sma200 = data.get('sma200', 0)
    rsi = data.get('rsi', 50)
    close = data.get('close', 0)  # ADDED: Current price
    volume_ratio = data.get('volume_ratio', 0)

    # Trend confirmation
    if not (ema20 > ema50):
        return _no_setup_message('No uptrend')

    # Price above both EMAs and 200 SMA
    if not (close > ema20 and close > sma200):
        return _no_setup_message('Price below key levels')

    # TIGHTENED: RSI sweet spot (was 40-70, now 50-68)
    if not (52 <= rsi <= 68):
        return _no_setup_message(f'RSI {rsi:.0f} not in 50-68 range')

    # Volume confirmation (keep at 1.2x)
    if volume_ratio < 1.2:
        return _no_setup_message(f'Volume {volume_ratio:.1f}x too low')

    # NEW: Not too far from EMA20 (avoid chasing)
    distance_to_ema20 = abs((close - ema20) / ema20 * 100) if ema20 > 0 else 100
    if distance_to_ema20 > 8.0:
        return _no_setup_message(f'Too far from EMA20 ({distance_to_ema20:.1f}%)')

    return {
        'side': 'buy',
        'msg': f'Swing: Uptrend + RSI {rsi:.0f} + Vol {volume_ratio:.1f}x',
        'limit_price': close,
        'stop_loss': None,
        'signal_type': 'swing_trade_1'
    }


def swing_trade_2(data):
    """
       Enhanced Swing Trade Strategy - Simplified and Improved

       Catches: Trending stocks pulling back to support with volume

       Entry Rules:
       1. Price > 200 SMA (long-term trend)
       2. 20 EMA > 50 EMA (medium-term momentum)
       3. Price within 10% of 20 EMA (pullback, not extended)
       4. Volume > 1.5x average (confirmation)
       5. Price stabilized (higher low + strong candle)
       6. RSI not overbought (< 75)
       """
    prev_low = data.get('prev_low', 0)
    close = data.get('close', 0)
    ema20 = data.get('ema20', 0)
    ema50 = data.get('ema50', 0)
    sma200 = data.get('sma200', 0)
    rsi = data.get('rsi', 50)
    volume_ratio = data.get('volume_ratio', 0)
    daily_change_pct = data.get('daily_change_pct', 0)

    # 1. Price above 200 SMA (uptrend)
    if close <= sma200:
        return _no_setup_message('Below 200 SMA')

    # 2. EMA structure (medium-term momentum)
    if ema20 <= ema50:
        return _no_setup_message('EMA20 not above EMA50')

    # 3. Pullback depth (2-20%)
    ema20_distance = abs((close - ema20) / ema20 * 100) if ema20 > 0 else 100
    if not (2.0 <= ema20_distance <= 20.0):
        return _no_setup_message(f'Pullback {ema20_distance:.1f}% not in 2-15% range')

    # 4. RSI not oversold or overbought (28-78)
    if not (28 <= rsi <= 78):
        return _no_setup_message(f'RSI {rsi:.0f} outside 30-75')

    # 5. Volume confirmation (1.3x)
    if volume_ratio < 1.3:
        return _no_setup_message(f'Volume {volume_ratio:.1f}x below 1.3x')

    return {
        'side': 'buy',
        'msg': f'Pullback: {ema20_distance:.1f}% from EMA20, RSI {rsi:.0f}, Vol {volume_ratio:.1f}x',
        'limit_price': close,
        'stop_loss': None,
        'signal_type': 'swing_trade_2'
    }


def _no_setup_message(reason):
    """Helper function to return consistent 'no setup' message"""
    return {
        'side': 'hold',
        'msg': f'No swing setup: {reason}',
        'limit_price': None,
        'stop_loss': None,
        'signal_type': 'swing_trade_2'
    }


def golden_cross(data, position_size='normal'):
    """
    Detects upcoming or recent Golden Cross

    Signal: 50 EMA crossing above 200 SMA
    Best for: Major trend changes in quality stocks

    Strategy:
    - Setup 1 (Pre-cross): Buy 30% position (test the waters)
    - Setup 2 (Post-cross): Buy 70% position (confirmed signal)

    Args:
        position_size: 'starter' (30%), 'full' (70%), or 'normal' (100%)
        :param position_size:
        :param data:
    """
    ema8 = data.get('ema8', 0)
    ema20 = data.get('ema20', 0)
    ema50 = data.get('ema50', 0)
    sma200 = data.get('sma200', 0)
    rsi = data.get('rsi', 50)
    volume_ratio = data.get('volume_ratio', 0)
    close = data.get('close', 0)  # ADDED
    atr = data.get('atr_14', 0)
    daily_change_pct = data.get('daily_change_pct', 0)

    # ATR volatility filter - skip extremely volatile stocks
    atr_pct = (atr / close * 100) if close > 0 else 100
    if atr_pct > 12.0:  # Skip if ATR > 12% of price
        return _no_signal('Too volatile for golden cross')

    # Calculate distance
    distance_pct = ((ema50 - sma200) / sma200 * 100)

    # SETUP 1: Fresh Cross (0-3% above)
    if 0 < distance_pct <= 3.0:

        # Require volume confirmation
        if volume_ratio < 1.5:  # Increased from 1.2
            return _no_signal('Pre-cross needs stronger volume (1.5x+)')

        # RSI range
        if not (45 <= rsi <= 70):
            return _no_signal(f'RSI {rsi:.0f} outside 45-70 range')

        # All EMAs aligned
        if not (close > ema8 > ema20 > ema50):
            return _no_signal('EMAs not aligned')

        # Green candle
        if daily_change_pct <= 0:
            return _no_signal('Not a green candle')

        # Not overextended from EMA20
        distance_to_ema20 = abs((close - ema20) / ema20 * 100) if ema20 > 0 else 100
        if distance_to_ema20 > 5.0:
            return _no_signal(f'Too far from EMA20 ({distance_to_ema20:.1f}%)')

        return {
            'side': 'buy',
            'msg': f'Golden cross SETUP: {abs(distance_pct):.1f}% from cross',
            'limit_price': close,
            'stop_loss': None,
            'signal_type': 'golden_cross_pullback'
        }

    # SETUP 2: Pullback to EMA50 (3-8% above 200 SMA)
    if 3.0 < distance_pct <= 8.0:
        # Price near EMA50 support
        price_to_ema50_pct = ((close - ema50) / ema50 * 100) if ema50 > 0 else 100

        if not (-2.0 <= price_to_ema50_pct <= 3.0):
            return _no_signal(f'Not near EMA50 ({price_to_ema50_pct:.1f}%)')

        # Volume
        if volume_ratio < 1.3:
            return _no_signal('Volume too low for pullback')

        # RSI in pullback range
        if not (35 <= rsi <= 55):
            return _no_signal(f'RSI {rsi:.0f} not in pullback range (35-55)')

        # Bouncing (green candle)
        if daily_change_pct <= 0:
            return _no_signal('Not bouncing (need green candle)')

        # Short-term trend intact
        if ema8 <= ema20:
            return _no_signal('Short-term trend weakening')

        return {
            'side': 'buy',
            'msg': f'Golden cross CONFIRMED: {distance_pct:.1f}% above 200 SMA',
            'limit_price': close,
            'stop_loss': None,
            'signal_type': 'golden_cross_pullback'
        }

    # SETUP 3: Well-established cross (Optional - Full position if you missed it)
    if 5.0 < distance_pct <= 10.0 and close > ema50:
        # Only if there's a pullback opportunity
        price_to_ema50_pct = ((close - ema50) / ema50 * 100)

        if -5.0 <= price_to_ema50_pct <= 2.0:  # Near EMA50 support
            return {
                'side': 'buy',
                'msg': f'Golden cross pullback: {distance_pct:.1f}% above 200 SMA, near EMA50',
                'limit_price': close,
                'stop_loss': None,
                'signal_type': 'golden_cross_pullback'
            }

    return _no_signal('No golden cross setup')


# Helper function
def _no_signal(reason):
    return {
        'side': 'hold',
        'msg': f'No signal: {reason}',
        'limit_price': None,
        'stop_loss': None,
        'signal_type': 'golden_cross_pullback'
    }


def bollinger_buy(data):
    rsi = data.get('rsi', 50)
    volume_ratio = data.get('volume_ratio', 0)
    sma200 = data.get('sma200', 0)
    bollinger_lower = data.get('bollinger_lower', 0)
    bollinger_upper = data.get('bollinger_upper', 0)
    close = data.get('close', 0)  # ADDED: Current price

    # BUY: Must have ALL these confirmations
    if rsi < 30.0 and bollinger_lower >= close > sma200 and volume_ratio >= 1.2:  # ADDED: Volume confirmation
        return {
            'side': 'buy',
            'limit_price': close,
            'stop_loss': None,
            'msg': 'Oversold + Volume + Above 200 SMA',
            'signal_type': 'bollinger_buy',
        }
    return None


# ===================================================================================
# SELL SIGNALS
# ===================================================================================
def bollinger_sell(data):
    rsi = data.get('rsi', 50)
    volume_ratio = data.get('volume_ratio', 0)
    sma200 = data.get('sma200', 0)
    bollinger_upper = data.get('bollinger_upper', 0)
    close = data.get('close', 0)  # ADDED: Current price
    # SELL: Keep same logic
    if rsi > 70.0 and close >= bollinger_upper:
        return {
            'side': 'sell',
            'limit_price': close,
            'stop_loss': None,
            'msg': 'Overbought above upper band',
            'signal_type': 'bollinger_sell',
        }
    return None


def take_profit_method_1(data):
    """
    Simple ATR-based take profit signal

    Exits when price reaches 2x ATR above EMA20 (proxy for entry level)
    """
    close = data.get('close', 0)
    ema20 = data.get('ema20', 0)
    atr = data.get('atr_14', 0)

    if atr == 0 or ema20 == 0:
        return None

    # Take profit target: 2x ATR above EMA20
    take_profit_level = ema20 + (atr * 2.0)

    if close >= take_profit_level:
        profit_pct = ((close - ema20) / ema20 * 100)
        return {
            'side': 'sell',
            'limit_price': close,
            'stop_loss': None,
            'msg': f'ATR Take Profit: +{profit_pct:.1f}% (2x ATR hit)',
            'signal_type': 'take_profit_atr'
        }

    return None


# =======================================================================================================================
# Strategy registry - add new strategies here
#  swing_trade - More Strict
#  swing_trade_1 - ema crossover

# 'buy_and_hold': buy_and_hold,
BUY_STRATEGIES = {
    'bollinger_buy': bollinger_buy,
    'swing_trade_1': swing_trade_1,
    'swing_trade_2': swing_trade_2,
    'golden_cross': golden_cross
}

SELL_STRATEGIES = {
    'bollinger_sell': bollinger_sell,
    'take_profit_method_1': take_profit_method_1
}
