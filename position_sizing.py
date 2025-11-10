import indicators


def calculate_position_size(cash_balance, entry_price, account_threshold=20000, max_position_pct=15.0):
    """
    Calculate position size based on available cash

    Rules:
    1. Don't trade if cash < threshold ($20,000)
    2. Max position = 15% of cash balance
    3. Must ensure we can afford it
    4. Must ensure purchase won't drop us below threshold

    Args:
        cash_balance: Current cash in account
        entry_price: Price per share
        account_threshold: Minimum cash to keep in account (default $20,000)
        max_position_pct: Maximum % of cash to use (default 15%)

    Returns:
        dict: {
            'quantity': int,
            'position_value': float,
            'remaining_cash': float,
            'can_trade': bool,
            'message': str
        }
    """
    # Check if we have enough cash to trade
    if cash_balance < account_threshold:
        return {
            'quantity': 0,
            'position_value': 0,
            'remaining_cash': cash_balance,
            'can_trade': False,
            'message': f'Cash ${cash_balance:,.2f} below threshold ${account_threshold:,.2f}'
        }

    if entry_price <= 0:
        return {
            'quantity': 0,
            'position_value': 0,
            'remaining_cash': cash_balance,
            'can_trade': False,
            'message': 'Invalid entry price'
        }

    # Calculate available cash (keep threshold protected)
    available_cash = cash_balance - account_threshold

    if available_cash <= 0:
        return {
            'quantity': 0,
            'position_value': 0,
            'remaining_cash': cash_balance,
            'can_trade': False,
            'message': f'No available cash after threshold'
        }

    # Calculate max position value (15% of cash balance)
    max_position_value = cash_balance * (max_position_pct / 100)

    # Can't use more than available cash
    position_value = min(max_position_value, available_cash)

    # Calculate quantity (round down)
    quantity = int(position_value / entry_price)

    # Recalculate actual position value
    actual_position_value = quantity * entry_price

    # Final check: can we afford it?
    if actual_position_value > available_cash:
        # Reduce by 1 share to be safe
        quantity = max(0, quantity - 1)
        actual_position_value = quantity * entry_price

    # Check if position is too small
    if quantity == 0:
        return {
            'quantity': 0,
            'position_value': 0,
            'remaining_cash': cash_balance,
            'can_trade': False,
            'message': f'Position too small. Entry ${entry_price:.2f} vs available ${available_cash:,.2f}'
        }

    remaining_cash = cash_balance - actual_position_value

    return {
        'quantity': quantity,
        'position_value': round(actual_position_value, 2),
        'remaining_cash': round(remaining_cash, 2),
        'can_trade': True,
        'message': f'{quantity} shares @ ${entry_price:.2f}'
    }


