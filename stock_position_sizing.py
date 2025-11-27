"""
Position Sizing - STREAMLINED VERSION (No MIN_SHARES Enforcement)

Changes from previous version:
- Removed MIN_SHARES enforcement (was 5)
- Let stock_position_monitoring.py handle small positions via remnant cleanup
- Applies rotation multiplier from stock rotation system
"""


class SimplifiedSizingConfig:
    """Position sizing configuration"""
    BASE_POSITION_PCT = 10.0
    MAX_POSITION_PCT = 15.0
    MAX_TOTAL_POSITIONS = 25
    MIN_CASH_RESERVE_PCT = 10.0
    MAX_CASH_DEPLOYMENT_PCT = 85.0
    MAX_DAILY_DEPLOYMENT_PCT = 50.0


def calculate_position_sizes(opportunities, portfolio_context, regime_multiplier=1.0, verbose=True):
    """
    Position sizing with rotation multiplier support

    Args:
        opportunities: List of opportunity dicts
        portfolio_context: Portfolio state dict
        regime_multiplier: From safeguard system (0.0 to 1.0)
        verbose: If False, suppress detailed logging

    Returns:
        List of allocation dicts with quantity, price, cost, etc.
    """
    if not opportunities:
        return []

    portfolio_value = portfolio_context['portfolio_value']
    deployable_cash = portfolio_context['deployable_cash']

    cash_limit = deployable_cash * (SimplifiedSizingConfig.MAX_CASH_DEPLOYMENT_PCT / 100)
    daily_limit = portfolio_value * (SimplifiedSizingConfig.MAX_DAILY_DEPLOYMENT_PCT / 100)
    max_deployment = min(cash_limit, daily_limit)

    # Calculate positions
    allocations = []

    for opp in opportunities:
        ticker = opp['ticker']
        data = opp['data']
        vol_mult = opp['vol_metrics'].get('position_multiplier', 1.0)
        rotation_mult = opp.get('rotation_mult', 1.0)

        # Apply all multipliers: regime, volatility, and rotation
        position_pct = SimplifiedSizingConfig.BASE_POSITION_PCT * regime_multiplier * vol_mult * rotation_mult
        position_pct = max(0.5, min(position_pct, SimplifiedSizingConfig.MAX_POSITION_PCT))

        position_dollars = portfolio_value * (position_pct / 100)
        current_price = data['close']

        # Calculate quantity - no minimum enforcement
        quantity = int(position_dollars / current_price)

        # Skip if quantity is 0 (price too high for allocated dollars)
        if quantity <= 0:
            if verbose:
                print(f"   ⚠️ {ticker}: Position too small (${position_dollars:.0f} / ${current_price:.2f} = 0 shares)")
            continue

        allocations.append({
            'ticker': ticker,
            'quantity': quantity,
            'price': current_price,
            'cost': quantity * current_price,
            'pct_portfolio': (quantity * current_price / portfolio_value * 100),
            'position_pct': position_pct,
            'signal_score': opp['score'],
            'signal_type': opp['signal_type'],
            'regime_mult': regime_multiplier,
            'vol_mult': vol_mult,
            'rotation_mult': rotation_mult
        })

    if not allocations:
        return []

    # Scale if over budget
    total_cost = sum(a['cost'] for a in allocations)
    if total_cost > max_deployment:
        scale_factor = max_deployment / total_cost

        scaled = []
        for alloc in allocations:
            scaled_qty = int(alloc['quantity'] * scale_factor)
            if scaled_qty > 0:  # Keep if at least 1 share
                alloc['quantity'] = scaled_qty
                alloc['cost'] = scaled_qty * alloc['price']
                alloc['pct_portfolio'] = (alloc['cost'] / portfolio_value * 100)
                scaled.append(alloc)

        allocations = scaled

    return allocations


def create_portfolio_context(strategy):
    """Create portfolio context dict"""
    cash_balance = strategy.get_cash()
    portfolio_value = strategy.portfolio_value
    existing_positions = len(strategy.get_positions())

    deployed_capital = portfolio_value - cash_balance
    min_reserve = portfolio_value * (SimplifiedSizingConfig.MIN_CASH_RESERVE_PCT / 100)
    deployable_cash = max(0, cash_balance - min_reserve)

    return {
        'total_cash': cash_balance,
        'portfolio_value': portfolio_value,
        'deployed_capital': deployed_capital,
        'deployment_pct': (deployed_capital / portfolio_value * 100) if portfolio_value > 0 else 0,
        'existing_positions_count': existing_positions,
        'available_slots': SimplifiedSizingConfig.MAX_TOTAL_POSITIONS - existing_positions,
        'reserved_cash': min_reserve,
        'deployable_cash': deployable_cash
    }