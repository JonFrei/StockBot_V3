"""
Stock Entry Filters

Entry-related checks and filters for stock selection.
"""

from account_drawdown_protection import SafeguardConfig


def check_relative_strength(stock_current, stock_past, spy_current=None, spy_past=None):
    """
    Check if stock passes relative strength filter.

    If SPY data provided: compares stock return vs SPY return (true relative strength)
    If no SPY data: checks stock's absolute return only

    Args:
        stock_current: Current stock price
        stock_past: Stock price N days ago (typically 20)
        spy_current: Current SPY price (optional)
        spy_past: SPY price N days ago (optional)

    Returns:
        dict: {
            'passes': bool,
            'relative_strength': float (% outperformance vs SPY, or absolute return if no SPY),
            'stock_return': float,
            'spy_return': float or None
        }
    """
    if not SafeguardConfig.RELATIVE_STRENGTH_ENABLED:
        return {'passes': True, 'relative_strength': 0, 'stock_return': 0, 'spy_return': None}

    if stock_past <= 0:
        return {'passes': False, 'relative_strength': 0, 'stock_return': 0, 'spy_return': None}

    stock_return = ((stock_current - stock_past) / stock_past) * 100

    # If SPY data provided, calculate relative strength
    if spy_current is not None and spy_past is not None and spy_past > 0:
        spy_return = ((spy_current - spy_past) / spy_past) * 100
        relative_strength = stock_return - spy_return
        passes = relative_strength >= SafeguardConfig.RELATIVE_STRENGTH_MIN_OUTPERFORM

        return {
            'passes': passes,
            'relative_strength': round(relative_strength, 2),
            'stock_return': round(stock_return, 2),
            'spy_return': round(spy_return, 2)
        }

    # No SPY data - use absolute return (stock must be positive)
    passes = stock_return >= SafeguardConfig.RELATIVE_STRENGTH_MIN_OUTPERFORM

    return {
        'passes': passes,
        'relative_strength': round(stock_return, 2),
        'stock_return': round(stock_return, 2),
        'spy_return': None
    }