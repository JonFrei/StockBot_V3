"""
SIMPLIFIED Position Sizing System - UPDATED WITH MIN_SHARES REQUIREMENT

IMPROVEMENTS IN THIS VERSION:
- MIN_SHARES = 10 (ensures proper multi-level profit taking)
- Price-based filtering when budget is constrained
- Drops most expensive stocks first to fit budget
- Skips trading if can't afford 10+ shares for at least 1 stock

FORMULA: base_size × signal_score_factor × regime_multiplier × volatility_multiplier
"""


# =============================================================================
# SIMPLIFIED CONFIGURATION
# =============================================================================

class SimplifiedSizingConfig:
    """Streamlined position sizing configuration"""

    # Base position size (% of portfolio)
    BASE_POSITION_PCT = 15.0

    # Position bounds
    MIN_SHARES = 10  # Minimum shares per position (for multi-level profit taking)
    MAX_POSITION_PCT = 20.0  # Single position limit

    # Portfolio constraints
    MAX_TOTAL_POSITIONS = 25
    MIN_CASH_RESERVE_PCT = 15.0  # 15% of portfolio (was fixed $20k)

    # Deployment limits
    MAX_CASH_DEPLOYMENT_PCT = 85.0  # Deploy 85% of available cash (was 60%)
    MAX_DAILY_DEPLOYMENT_PCT = 50.0  # Max 50% of portfolio in one day


# =============================================================================
# SIMPLE POSITION SIZING - MAIN FUNCTION
# =============================================================================

def calculate_position_sizes(opportunities, portfolio_context):
    """
    Simple position sizing with MIN_SHARES requirement

    NEW LOGIC:
    1. Calculate ideal position sizes for all opportunities
    2. If any position has < 10 shares: sort by stock price (expensive first)
    3. Drop most expensive stocks until all remaining have 10+ shares
    4. If only 1 stock left and still < 10 shares: skip trading

    Args:
        opportunities: List of dicts with opportunity data
        portfolio_context: Dict with portfolio state

    Returns:
        List of position allocations with quantities (all with 10+ shares)
    """

    if not opportunities:
        return []

    portfolio_value = portfolio_context['portfolio_value']
    deployable_cash = portfolio_context['deployable_cash']
    deployed_capital = portfolio_context.get('deployed_capital', 0)

    # Calculate maximum deployment
    cash_limit = deployable_cash * (SimplifiedSizingConfig.MAX_CASH_DEPLOYMENT_PCT / 100)

    # Daily limit to prevent over-concentration
    daily_limit = portfolio_value * (SimplifiedSizingConfig.MAX_DAILY_DEPLOYMENT_PCT / 100)

    # Use lesser of cash limit or daily limit
    max_deployment = min(cash_limit, daily_limit)

    print(f"\n{'=' * 80}")
    print(f"💰 POSITION SIZING (MIN {SimplifiedSizingConfig.MIN_SHARES} SHARES)")
    print(f"{'=' * 80}")
    print(f"Portfolio Value: ${portfolio_value:,.0f}")
    print(f"Deployed Capital: ${deployed_capital:,.0f} ({deployed_capital / portfolio_value * 100:.1f}%)")
    print(f"Cash Balance: ${portfolio_context['total_cash']:,.0f}")
    print(f"Reserved (15%): ${portfolio_context['reserved_cash']:,.0f}")
    print(f"Deployable Cash: ${deployable_cash:,.0f}")
    print(f"Max Deployment (85%): ${cash_limit:,.0f}")
    print(f"Daily Limit (50%): ${daily_limit:,.0f}")
    print(f"Using: ${max_deployment:,.0f}")
    print(f"Opportunities: {len(opportunities)}")
    print(f"{'=' * 80}\n")

    # Calculate initial positions
    allocations = []
    total_requested = 0

    for opp in opportunities:
        ticker = opp['ticker']
        signal_score = opp['score']
        data = opp['data']

        # Calculate position size with all multipliers
        regime_mult = opp['regime'].get('position_size_multiplier', 1.0)
        vol_mult = opp['vol_metrics'].get('position_multiplier', 1.0)
        stock_mult = opp.get('stock_regime_mult', 1.0)

        position_pct = SimplifiedSizingConfig.BASE_POSITION_PCT * regime_mult * stock_mult

        # Apply bounds
        position_pct = max(1.0, min(position_pct, SimplifiedSizingConfig.MAX_POSITION_PCT))

        # Convert to dollars
        position_dollars = portfolio_value * (position_pct / 100)

        # Calculate quantity
        current_price = data['close']
        quantity = int(position_dollars / current_price)

        # Store allocation (we'll filter later)
        allocations.append({
            'ticker': ticker,
            'quantity': quantity,
            'price': current_price,
            'cost': quantity * current_price,
            'pct_portfolio': (quantity * current_price / portfolio_value * 100),
            'position_pct': position_pct,
            'signal_score': signal_score,
            'signal_type': opp['signal_type'],
            'regime_mult': opp['regime'].get('position_size_multiplier', 1.0),
            'vol_mult': opp['vol_metrics'].get('position_multiplier', 1.0),
            'stock_mult': opp.get('stock_regime_mult', 1.0)
        })

    if not allocations:
        print(f"\n⚠️  No valid allocations after initial sizing\n")
        return []

    # FILTER: Ensure all positions have MIN_SHARES
    allocations = _enforce_min_shares(allocations, max_deployment, portfolio_value)

    if not allocations:
        print(f"\n⚠️  No positions meet minimum {SimplifiedSizingConfig.MIN_SHARES} shares requirement\n")
        return []

    # Calculate total cost
    total_cost = sum(a['cost'] for a in allocations)

    # Check if we're over budget (after filtering)
    if total_cost > max_deployment:
        # Scale down proportionally
        scale_factor = max_deployment / total_cost

        print(f"⚠️  Over budget by ${total_cost - max_deployment:,.0f}")
        print(f"   Requested: ${total_cost:,.0f}")
        print(f"   Available: ${max_deployment:,.0f}")
        print(f"   Scaling all positions by {scale_factor:.2f}x\n")

        scaled_allocations = []
        for alloc in allocations:
            scaled_quantity = int(alloc['quantity'] * scale_factor)

            # Ensure still meets minimum after scaling
            if scaled_quantity >= SimplifiedSizingConfig.MIN_SHARES:
                alloc['quantity'] = scaled_quantity
                alloc['cost'] = scaled_quantity * alloc['price']
                alloc['pct_portfolio'] = (alloc['cost'] / portfolio_value * 100)
                scaled_allocations.append(alloc)
            else:
                print(
                    f"   ⚠️  {alloc['ticker']}: Scaled to {scaled_quantity} shares - Below minimum {SimplifiedSizingConfig.MIN_SHARES}, dropping")

        allocations = scaled_allocations
        total_cost = sum(a['cost'] for a in allocations)

        if not allocations:
            print(f"\n⚠️  No positions remain after scaling to meet minimum shares requirement\n")
            return []

    display_allocations(allocations, portfolio_value, total_cost)
    return allocations


def _enforce_min_shares(allocations, max_budget, portfolio_value):
    """
    Enforce MIN_SHARES requirement by dropping expensive stocks

    Strategy:
    1. Check if all positions have MIN_SHARES
    2. If not: Sort by price (most expensive first)
    3. Drop expensive stocks one-by-one until all have MIN_SHARES
    4. If only 1 left and still < MIN_SHARES: return empty list

    Args:
        allocations: List of allocation dicts
        max_budget: Maximum dollars available
        portfolio_value: Total portfolio value

    Returns:
        List of allocations with MIN_SHARES requirement met
    """
    MIN_SHARES = SimplifiedSizingConfig.MIN_SHARES

    # Check if any positions below minimum
    below_min = [a for a in allocations if a['quantity'] < MIN_SHARES]

    if not below_min:
        print(f"✅ All {len(allocations)} positions meet minimum {MIN_SHARES} shares\n")
        return allocations

    print(f"\n⚠️  {len(below_min)} position(s) below minimum {MIN_SHARES} shares")
    print(f"   Strategy: Drop most expensive stocks until all remaining have {MIN_SHARES}+ shares\n")

    # Sort by price (most expensive first)
    sorted_allocs = sorted(allocations, key=lambda x: x['price'], reverse=True)

    # Try dropping expensive stocks one by one
    for i in range(len(sorted_allocs)):
        remaining = sorted_allocs[i:]

        # Recalculate quantities with available budget
        total_cost = sum(a['cost'] for a in remaining)

        if total_cost <= max_budget:
            # Budget fits, check if all meet minimum shares
            below_min = [a for a in remaining if a['quantity'] < MIN_SHARES]

            if not below_min:
                # All meet minimum!
                dropped = sorted_allocs[:i]
                if dropped:
                    print(f"   📉 Dropped {len(dropped)} expensive stock(s):")
                    for d in dropped:
                        print(f"      - {d['ticker']} @ ${d['price']:.2f} (only {d['quantity']} shares affordable)")
                    print(f"   ✅ Remaining {len(remaining)} stock(s) all have {MIN_SHARES}+ shares\n")
                return remaining

            # Still have positions below minimum
            # Try to boost them by redistributing budget
            remaining = _redistribute_budget(remaining, max_budget, portfolio_value)

            # Check again
            below_min = [a for a in remaining if a['quantity'] < MIN_SHARES]
            if not below_min:
                dropped = sorted_allocs[:i]
                if dropped:
                    print(f"   📉 Dropped {len(dropped)} expensive stock(s)")
                    print(
                        f"   ✅ After budget redistribution: All {len(remaining)} positions have {MIN_SHARES}+ shares\n")
                return remaining

    # Could not meet minimum shares for any combination
    print(f"   ❌ Cannot afford {MIN_SHARES}+ shares for any combination")
    print(f"   Skipping all trades this iteration\n")
    return []


def _redistribute_budget(allocations, max_budget, portfolio_value):
    """
    Redistribute budget to boost positions below MIN_SHARES

    Strategy:
    1. Calculate how much each position needs to reach MIN_SHARES
    2. Reallocate from positions above MIN_SHARES to those below
    3. Ensure we stay within max_budget

    Args:
        allocations: List of allocations
        max_budget: Maximum budget
        portfolio_value: Portfolio value

    Returns:
        Updated allocations
    """
    MIN_SHARES = SimplifiedSizingConfig.MIN_SHARES

    # Separate positions
    below_min = [a for a in allocations if a['quantity'] < MIN_SHARES]
    above_min = [a for a in allocations if a['quantity'] >= MIN_SHARES]

    if not below_min:
        return allocations  # Already all good

    # Calculate how much we need to boost below-min positions
    boost_needed = 0
    for alloc in below_min:
        shares_needed = MIN_SHARES - alloc['quantity']
        boost_needed += shares_needed * alloc['price']

    # Try to free up budget by reducing above-min positions
    total_available = max_budget
    total_above_cost = sum(a['cost'] for a in above_min)
    total_below_cost = sum(a['cost'] for a in below_min)

    # If we have room in budget, boost below-min positions
    remaining_budget = max_budget - total_above_cost - total_below_cost

    if remaining_budget >= boost_needed:
        # Can boost without reducing others
        for alloc in below_min:
            if alloc['quantity'] < MIN_SHARES:
                old_qty = alloc['quantity']
                alloc['quantity'] = MIN_SHARES
                alloc['cost'] = MIN_SHARES * alloc['price']
                alloc['pct_portfolio'] = (alloc['cost'] / portfolio_value * 100)
        return allocations
    else:
        # Need to reduce above-min positions proportionally
        if above_min and boost_needed > 0:
            # Calculate reduction factor
            reduction_needed = boost_needed - remaining_budget
            reduction_factor = 1.0 - (reduction_needed / total_above_cost)

            # Apply reduction
            for alloc in above_min:
                new_qty = max(MIN_SHARES, int(alloc['quantity'] * reduction_factor))
                alloc['quantity'] = new_qty
                alloc['cost'] = new_qty * alloc['price']
                alloc['pct_portfolio'] = (alloc['cost'] / portfolio_value * 100)

            # Boost below-min to MIN_SHARES
            for alloc in below_min:
                alloc['quantity'] = MIN_SHARES
                alloc['cost'] = MIN_SHARES * alloc['price']
                alloc['pct_portfolio'] = (alloc['cost'] / portfolio_value * 100)

    return allocations


def display_allocations(allocations, portfolio_value, total_cost):
    """Display allocation table with improved formatting"""

    if not allocations:
        print(f"\n⚠️  No positions after sizing\n")
        return

    print(f"\n{'=' * 100}")
    print(f"📊 FINAL ALLOCATIONS (All positions have {SimplifiedSizingConfig.MIN_SHARES}+ shares)")
    print(f"{'=' * 100}")
    print(f"Total Allocated: ${total_cost:,.0f} ({total_cost / portfolio_value * 100:.1f}% of portfolio)")
    print(f"Position Count: {len(allocations)}")
    print(f"Average Position: ${total_cost / len(allocations):,.0f}")
    print(f"{'=' * 100}\n")

    # Sort by cost (largest first)
    allocations.sort(key=lambda x: x['cost'], reverse=True)

    print(f"{'Ticker':<8} {'Signal':<20} {'Score':<7} {'Shares':<8} {'Price':<10} {'Cost':<14} {'Multipliers'}")
    print(f"{'-' * 100}")

    for alloc in allocations:
        signal = alloc['signal_type'][:18]
        score = f"{alloc['signal_score']:.0f}"
        shares = f"{alloc['quantity']}"
        price = f"${alloc['price']:.2f}"
        cost = f"${alloc['cost']:,.0f}"

        # Multipliers breakdown
        stock_mult = alloc.get('stock_mult', 1.0)
        total_mult = alloc['regime_mult'] * alloc['vol_mult'] * stock_mult
        mults = f"R:{alloc['regime_mult']:.2f} V:{alloc['vol_mult']:.2f} H:{stock_mult:.2f} = {total_mult:.2f}x"

        print(f"{alloc['ticker']:<8} {signal:<20} {score:<7} {shares:<8} {price:<10} {cost:<14} {mults}")

    print(f"{'-' * 100}\n")


# =============================================================================
# PORTFOLIO CONTEXT BUILDER - IMPROVED
# =============================================================================

def create_portfolio_context(strategy):
    """
    Create portfolio context dict from strategy

    IMPROVEMENTS:
    - Portfolio-relative cash reserve (15% instead of fixed $20k)
    - Tracks deployed capital
    - More detailed context for sizing decisions

    Args:
        strategy: Lumibot Strategy instance

    Returns:
        dict: Portfolio context with enhanced information
    """
    cash_balance = strategy.get_cash()
    portfolio_value = strategy.portfolio_value
    existing_positions = len(strategy.get_positions())

    # Calculate deployed capital
    deployed_capital = portfolio_value - cash_balance

    # Portfolio-relative reserve (15% instead of fixed $20k)
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