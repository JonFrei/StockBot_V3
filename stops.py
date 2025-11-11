# ==========================================================
# STOP LOSS FUNCTIONS
# ==========================================================
def stop_loss_atr(stock, multiplier=2.0):
    """
    Calculate simple ATR-based stop loss

    Stop Loss = Entry Price - (ATR × Multiplier)

    Args:
        entry_price: Entry price per share
        atr: Average True Range value
        signal_type: Type of signal (affects multiplier)
        multiplier: ATR multiplier (default 2.0)

    Returns:
        dict: {
            'stop_loss': float,
            'stop_distance': float,
            'stop_pct': float
        }
    """
    atr = stock['atr_14']
    entry_price = stock['close']

    if entry_price <= 0 or atr <= 0:
        return {
            'stop_loss': 0,
            'stop_distance': 0,
            'stop_pct': 0,
            'error': 'Invalid entry price or ATR'
        }

    # Get multiplier for this signal type
    atr_multiplier = multiplier

    # Calculate stop loss
    stop_distance = atr * atr_multiplier
    stop_loss = entry_price - stop_distance

    # Calculate percentage
    stop_pct = (stop_distance / entry_price * 100)

    return {
        'stop_loss': round(stop_loss, 2),
        'stop_distance': round(stop_distance, 2),
        'stop_pct': round(stop_pct, 2),
    }


def stop_loss_hard(stock, stop_loss_percent=0.05):
    entry_price = stock['close']
    if not entry_price or entry_price <= 0:
        return {
            'stop_loss': 0,
            'stop_distance': 0,
            'stop_pct': 0,
            'error': 'Invalid entry price'
        }

    # Calculate stop loss
    stop_distance = entry_price * stop_loss_percent
    stop_loss = entry_price - stop_distance

    # Calculate percentage
    stop_pct = (stop_distance / entry_price * 100)

    return {
        'stop_loss': round(stop_loss, 2),
        'stop_distance': round(stop_distance, 2),
        'stop_pct': round(stop_pct, 2),
    }


def trailing_stop_percentage(highest_price, current_price, trail_pct=15.0):
    """
    Calculate percentage-based trailing stop

    Args:
        highest_price: Highest price since entry
        current_price: Current price
        trail_pct: Trailing percentage (default 15%)

    Returns:
        dict: {
            'trailing_stop': float,
            'should_exit': bool,
            'drawdown_from_peak': float
        }
    """
    if highest_price <= 0:
        return {
            'trailing_stop': 0,
            'should_exit': False,
            'drawdown_from_peak': 0,
            'error': 'Invalid highest price'
        }

    trailing_stop = highest_price * (1 - trail_pct / 100)
    should_exit = current_price <= trailing_stop
    drawdown = ((current_price - highest_price) / highest_price * 100)

    return {
        'trailing_stop': round(trailing_stop, 2),
        'should_exit': should_exit,
        'drawdown_from_peak': round(drawdown, 2)
    }


def trailing_stop_atr(highest_price, atr, multiplier=2.5):
    """
    Calculate ATR-based trailing stop (adaptive to volatility)

    Args:
        highest_price: Highest price since entry
        atr: Average True Range value
        multiplier: ATR multiplier (default 2.5)

    Returns:
        dict: {
            'trailing_stop': float,
            'atr_distance': float
        }
    """
    if highest_price <= 0 or atr <= 0:
        return {
            'trailing_stop': 0,
            'atr_distance': 0,
            'error': 'Invalid inputs'
        }

    atr_distance = atr * multiplier
    trailing_stop = highest_price - atr_distance

    return {
        'trailing_stop': round(trailing_stop, 2),
        'atr_distance': round(atr_distance, 2)
    }


def adaptive_trailing_stop(pnl_pct, highest_price, atr):
    """
    Adaptive trailing stop that tightens as profit increases

    Args:
        pnl_pct: Current profit percentage
        highest_price: Highest price since entry
        atr: Average True Range

    Returns:
        dict: Recommended trailing stop parameters
    """
    # Adjust trail tightness based on profit
    if pnl_pct < 25:
        trail_pct = 15.0
        atr_mult = 3.0
        regime = 'wide'
    elif pnl_pct < 50:
        trail_pct = 12.0
        atr_mult = 2.5
        regime = 'medium'
    elif pnl_pct < 100:
        trail_pct = 10.0
        atr_mult = 2.0
        regime = 'tight'
    else:
        trail_pct = 8.0
        atr_mult = 1.5
        regime = 'very_tight'

    pct_stop = trailing_stop_percentage(highest_price, 0, trail_pct)
    atr_stop = trailing_stop_atr(highest_price, atr, atr_mult)

    return {
        'pct_trailing_stop': pct_stop['trailing_stop'],
        'atr_trailing_stop': atr_stop['trailing_stop'],
        'recommended_stop': max(pct_stop['trailing_stop'], atr_stop['trailing_stop']),
        'regime': regime,
        'trail_pct': trail_pct,
        'atr_mult': atr_mult
    }


# =================================
# ACTIVE STOP LOSS LIST
# =================================

STOP_LOSS_STRATEGIES = {
    'stop_loss_hard': stop_loss_hard,
    'stop_loss_atr': stop_loss_atr,
    'trailing_stop_percentage': trailing_stop_percentage,
    'trailing_stop_atr': trailing_stop_atr,
    'adaptive_trailing_stop': adaptive_trailing_stop
}