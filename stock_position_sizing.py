"""
Position Sizing - STREAMLINED VERSION

Added verbose=False option to suppress detailed output
Now applies rotation_mult from stock rotation system
"""


class SimplifiedSizingConfig:
    """Position sizing configuration"""
    BASE_POSITION_PCT = 12.0
    MIN_SHARES = 10
    MAX_POSITION_PCT = 20.0
    MAX_TOTAL_POSITIONS = 25
    MIN_CASH_RESERVE_PCT = 15.0
    MAX_CASH_DEPLOYMENT_PCT = 85.0
    MAX_DAILY_DEPLOYMENT_PCT = 50.0


def calculate_position_sizes(opportunities, portfolio_context, regime_multiplier=1.0, verbose=True):
    """
    Position sizing with optional verbose output

    Args:
        opportunities: List of opportunity dicts
        portfolio_context: Portfolio state dict
        regime_multiplier: From safeguard system (0.0 to 1.0)
        verbose: If False, suppress detailed logging
    """
    if not opportunities:
        return []

    portfolio_value = portfolio_context['portfolio_value']
    deployable_cash = portfolio_context['deployable_cash']

    cash_limit = deployable_cash * (SimplifiedSizingConfig.MAX_CASH_DEPLOYMENT_PCT / 100)
    daily_limit = portfolio_value * (SimplifiedSizingConfig.MAX_DAILY_DEPLOYMENT_PCT / 100)
    max_deployment = min(cash_limit, daily_limit)

    # Calculate initial positions
    allocations = []

    for opp in opportunities:
        ticker = opp['ticker']
        data = opp['data']
        vol_mult = opp['vol_metrics'].get('position_multiplier', 1.0)
        rotation_mult = opp.get('rotation_mult', 1.0)

        # Apply all multipliers: regime, volatility, and rotation
        position_pct = SimplifiedSizingConfig.BASE_POSITION_PCT * regime_multiplier * vol_mult * rotation_mult
        position_pct = max(1.0, min(position_pct, SimplifiedSizingConfig.MAX_POSITION_PCT))

        position_dollars = portfolio_value * (position_pct / 100)
        current_price = data['close']
        quantity = int(position_dollars / current_price)

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

    # Enforce MIN_SHARES
    allocations = _enforce_min_shares(allocations, max_deployment, portfolio_value, verbose)

    if not allocations:
        return []

    # Scale if over budget
    total_cost = sum(a['cost'] for a in allocations)
    if total_cost > max_deployment:
        scale_factor = max_deployment / total_cost

        scaled = []
        for alloc in allocations:
            scaled_qty = int(alloc['quantity'] * scale_factor)
            if scaled_qty >= SimplifiedSizingConfig.MIN_SHARES:
                alloc['quantity'] = scaled_qty
                alloc['cost'] = scaled_qty * alloc['price']
                alloc['pct_portfolio'] = (alloc['cost'] / portfolio_value * 100)
                scaled.append(alloc)

        allocations = scaled

    return allocations


def _enforce_min_shares(allocations, max_budget, portfolio_value, verbose=True):
    """Enforce MIN_SHARES requirement"""
    MIN_SHARES = SimplifiedSizingConfig.MIN_SHARES

    below_min = [a for a in allocations if a['quantity'] < MIN_SHARES]
    if not below_min:
        return allocations

    # Sort by price (most expensive first)
    sorted_allocs = sorted(allocations, key=lambda x: x['price'], reverse=True)

    for i in range(len(sorted_allocs)):
        remaining = sorted_allocs[i:]
        total_cost = sum(a['cost'] for a in remaining)

        if total_cost <= max_budget:
            below_min = [a for a in remaining if a['quantity'] < MIN_SHARES]
            if not below_min:
                return remaining

            remaining = _redistribute_budget(remaining, max_budget, portfolio_value)
            below_min = [a for a in remaining if a['quantity'] < MIN_SHARES]
            if not below_min:
                return remaining

    return []


def _redistribute_budget(allocations, max_budget, portfolio_value):
    """Redistribute budget to meet MIN_SHARES"""
    MIN_SHARES = SimplifiedSizingConfig.MIN_SHARES

    below_min = [a for a in allocations if a['quantity'] < MIN_SHARES]
    above_min = [a for a in allocations if a['quantity'] >= MIN_SHARES]

    if not below_min:
        return allocations

    boost_needed = sum((MIN_SHARES - a['quantity']) * a['price'] for a in below_min)

    total_above_cost = sum(a['cost'] for a in above_min)
    total_below_cost = sum(a['cost'] for a in below_min)
    remaining_budget = max_budget - total_above_cost - total_below_cost

    if remaining_budget >= boost_needed:
        for alloc in below_min:
            if alloc['quantity'] < MIN_SHARES:
                alloc['quantity'] = MIN_SHARES
                alloc['cost'] = MIN_SHARES * alloc['price']
                alloc['pct_portfolio'] = (alloc['cost'] / portfolio_value * 100)
        return allocations
    else:
        if above_min and boost_needed > 0:
            reduction_needed = boost_needed - remaining_budget
            reduction_factor = 1.0 - (reduction_needed / total_above_cost) if total_above_cost > 0 else 1.0

            for alloc in above_min:
                new_qty = max(MIN_SHARES, int(alloc['quantity'] * reduction_factor))
                alloc['quantity'] = new_qty
                alloc['cost'] = new_qty * alloc['price']
                alloc['pct_portfolio'] = (alloc['cost'] / portfolio_value * 100)

            for alloc in below_min:
                alloc['quantity'] = MIN_SHARES
                alloc['cost'] = MIN_SHARES * alloc['price']
                alloc['pct_portfolio'] = (alloc['cost'] / portfolio_value * 100)

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