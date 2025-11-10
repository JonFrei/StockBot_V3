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
    entry_price = stock[('close'
                         '')]
    if entry_price:
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


def calculate_position_with_stop(cash_balance, stock, stop_type='stop_loss_hard',
                                 account_threshold=20000, max_position_pct=15.0):
    """
    All-in-one function: Calculate position size AND stop loss

    Args:
        cash_balance: Current cash in account
        entry_price: Entry price per share
        atr: Average True Range
        signal_type: Type of signal
        account_threshold: Minimum cash to keep (default $20,000)
        max_position_pct: Max % of cash to use (default 15%)

    Returns:
        dict: Complete position info with stop loss
        :param max_position_pct:
        :param account_threshold:
        :param stock:
        :param cash_balance:
        :param stop_type:
    """
    # Calculate position size
    position = calculate_position_size(
        cash_balance=cash_balance,
        entry_price=stock['close'],
        account_threshold=account_threshold,
        max_position_pct=max_position_pct
    )

    if not position['can_trade']:
        return position

    stop_loss_value = 0
    stop_loss_pct = 0
    for strategies in  STOP_LOSS_STRATEGIES:
        if stop_type in strategies:
            stop_loss_func = STOP_LOSS_STRATEGIES[stop_type]
            stop_loss = stop_loss_func(stock)
            stop_loss_value = stop_loss['stop_loss']
            stop_loss_pct = stop_loss['stop_pct']

    # Combine results
    position.update({
        'entry_price': stock['close'],
        'stop_loss': stop_loss_value,
        'stop_pct': stop_loss_pct,
        'risk_per_share': round(stock['close'] - stop_loss_value, 2),
        'total_risk': round(position['quantity'] * (stock['close'] - stop_loss_value), 2)
    })

    return position


STOP_LOSS_STRATEGIES = {
    'stop_loss_hard': stop_loss_hard,
    'stop_loss_atr': stop_loss_atr
}
