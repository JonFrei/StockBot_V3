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


# =================================
# ACTIVE STOP LOSS LIST
# =================================

STOP_LOSS_STRATEGIES = {
    'stop_loss_hard': stop_loss_hard,
    'stop_loss_atr': stop_loss_atr
}
