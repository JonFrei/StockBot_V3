def check_position_concentration(strategy, ticker, new_position_value, max_concentration_pct=20.0):
    """
    Check if adding a new position would exceed concentration limits

    Args:
        strategy: Lumibot Strategy object
        ticker: Stock symbol
        new_position_value: Value of new position to add
        max_concentration_pct: Max % of portfolio per ticker (default 20%)

    Returns:
        dict: {
            'allowed': bool,
            'current_value': float,
            'new_total_value': float,
            'concentration_pct': float,
            'max_allowed_value': float,
            'message': str
        }
    """
    portfolio_value = strategy.portfolio_value

    # Get existing position value for this ticker
    existing_position = strategy.get_position(ticker)
    existing_value = 0

    if existing_position and existing_position.quantity > 0:
        current_price = strategy.get_last_price(ticker)
        existing_value = existing_position.quantity * current_price

    # Calculate new total if we add this position
    new_total_value = existing_value + new_position_value
    concentration_pct = (new_total_value / portfolio_value * 100) if portfolio_value > 0 else 0

    # Calculate max allowed value for this ticker
    max_allowed_value = portfolio_value * (max_concentration_pct / 100)

    # Check if within limits
    allowed = new_total_value <= max_allowed_value

    if not allowed:
        # Calculate how much we CAN add
        room_left = max(0, max_allowed_value - existing_value)
        message = f'Would exceed {max_concentration_pct}% limit. Current: ${existing_value:,.0f}, Room: ${room_left:,.0f}'
    else:
        message = f'OK - {concentration_pct:.1f}% of portfolio'

    return {
        'allowed': allowed,
        'current_value': round(existing_value, 2),
        'new_total_value': round(new_total_value, 2),
        'concentration_pct': round(concentration_pct, 2),
        'max_allowed_value': round(max_allowed_value, 2),
        'room_left': round(max(0, max_allowed_value - existing_value), 2),
        'message': message
    }


def calculate_buy_size(strategy, entry_price, account_threshold=40000,
                       max_position_pct=12.0, pending_commitments=0, adaptive_params=None):
    """
    Calculate position size based on available cash - NOW ADAPTIVE

    FIXED: Uses effective_cash for max_position_value calculation (was using cash_balance)

    Adaptive behavior:
    - STRONG conditions: Use 15% position sizes (more aggressive)
    - NEUTRAL conditions: Use 12% position sizes (standard)
    - WEAK conditions: Use 10% position sizes (more conservative)

    Args:
        strategy: Lumibot Strategy object (to access portfolio)
        ticker: Stock symbol
        entry_price: Price per share
        account_threshold: Minimum cash to keep in account (default $40,000)
        max_position_pct: Maximum % of cash to use (default 12%, overridden by adaptive_params)
        pending_commitments: Cash already committed to pending orders
        adaptive_params: Dict with 'position_size_pct' from market conditions (NEW)

    Returns:
        dict: {
            'quantity': int,
            'position_value': float,
            'remaining_cash': float,
            'can_trade': bool,
            'message': str
        }
    """
    # === USE ADAPTIVE POSITION SIZE IF PROVIDED ===
    if adaptive_params and 'position_size_pct' in adaptive_params:
        max_position_pct = adaptive_params['position_size_pct']
        condition_label = adaptive_params.get('condition_label', '')
    else:
        condition_label = ''

    # Get cash balance from strategy
    cash_balance = strategy.get_cash()

    # Deduct pending commitments to get TRUE available cash
    effective_cash = cash_balance - pending_commitments

    # Check if we have enough cash to trade
    if effective_cash < account_threshold:
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
    available_cash = effective_cash - account_threshold

    if available_cash <= 0:
        return {
            'quantity': 0,
            'position_value': 0,
            'remaining_cash': cash_balance,
            'can_trade': False,
            'message': f'No available cash after threshold'
        }

    # FIXED: Calculate max position value using EFFECTIVE_CASH (not cash_balance)
    max_position_value = effective_cash * (max_position_pct / 100)

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

    remaining_cash = cash_balance - actual_position_value - pending_commitments

    return {
        'quantity': quantity,
        'position_value': round(actual_position_value, 2),
        'remaining_cash': round(remaining_cash, 2),
        'can_trade': True,
        'message': f'{quantity} shares @ ${entry_price:.2f} ({max_position_pct:.0f}% {condition_label})'
    }


def calculate_sell_size(strategy, ticker, sell_percentage=50.0):
    """
    Calculate sell quantity based on current position

    Args:
        strategy: Lumibot Strategy object (to access portfolio)
        ticker: Stock symbol
        sell_percentage: Percentage of position to sell (default 50%)

    Returns:
        dict: {
            'quantity': int,
            'position_value': float,
            'remaining_position_value': float,
            'can_trade': bool,
            'message': str
        }
    """
    # Get current position from strategy
    position = strategy.get_position(ticker)

    if position is None or position.quantity == 0:
        return {
            'quantity': 0,
            'position_value': 0,
            'remaining_position_value': 0,
            'can_trade': False,
            'message': f'No position in {ticker}'
        }

    # Get current price from strategy
    current_price = strategy.get_last_price(ticker)

    if current_price <= 0:
        return {
            'quantity': 0,
            'position_value': 0,
            'remaining_position_value': position.quantity * position.price,
            'can_trade': False,
            'message': f'Invalid price for {ticker}'
        }

    # Calculate sell quantity (round down)
    sell_quantity = int(position.quantity * (sell_percentage / 100))

    if sell_quantity == 0:
        return {
            'quantity': 0,
            'position_value': 0,
            'remaining_position_value': position.quantity * current_price,
            'can_trade': False,
            'message': f'Position too small to sell ({position.quantity} shares)'
        }

    # Calculate values
    position_value = sell_quantity * current_price
    remaining_quantity = position.quantity - sell_quantity
    remaining_position_value = remaining_quantity * current_price

    return {
        'quantity': sell_quantity,
        'position_value': round(position_value, 2),
        'remaining_position_value': round(remaining_position_value, 2),
        'can_trade': True,
        'message': f'Selling {sell_quantity} of {position.quantity} shares ({sell_percentage}%)'
    }