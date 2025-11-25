"""
SIMPLIFIED Position Sizing System

REMOVED:
- Complex independent allocation (200 lines)
- Tiered scaling system (150 lines)
- Quality scoring (100 lines)
- Award multipliers (already removed)
- Conviction multipliers
- 5-layer multiplier system

NEW APPROACH:
- Simple formula: base_size × signal_score_factor × regime_multiplier
- Single-pass calculation
- Clear, maintainable logic
"""


# =============================================================================
# SIMPLIFIED CONFIGURATION
# =============================================================================

class SimplifiedSizingConfig:
    """Streamlined position sizing configuration"""

    # Base position size (% of portfolio)
    BASE_POSITION_PCT = 15.0

    # Position bounds
    MIN_POSITION_PCT = 5.0  # Below this = skip
    MAX_POSITION_PCT = 20.0  # Single position limit

    # Portfolio constraints
    MAX_TOTAL_POSITIONS = 25
    MIN_CASH_RESERVE = 20000  # Minimum cash buffer
    MAX_CASH_DEPLOYMENT_PCT = 60.0  # % of available cash per iteration


# =============================================================================
# SIMPLE POSITION SIZING - MAIN FUNCTION
# =============================================================================

def calculate_position_sizes(opportunities, portfolio_context):
    """
    Simple position sizing: base × signal_score × regime × volatility

    No tiered scaling, no quality scoring, no complex allocation
    Just straightforward: stronger signals = bigger positions

    Args:
        opportunities: List of dicts with opportunity data
        portfolio_context: Dict with portfolio state

    Returns:
        List of position allocations with quantities
    """

    if not opportunities:
        return []

    portfolio_value = portfolio_context['portfolio_value']
    deployable_cash = portfolio_context['deployable_cash']
    max_deployment = deployable_cash * (SimplifiedSizingConfig.MAX_CASH_DEPLOYMENT_PCT / 100)

    print(f"\n{'=' * 80}")
    print(f"💰 SIMPLIFIED POSITION SIZING")
    print(f"{'=' * 80}")
    print(f"Portfolio Value: ${portfolio_value:,.0f}")
    print(f"Deployable Cash: ${deployable_cash:,.0f}")
    print(f"Max This Iteration: ${max_deployment:,.0f}")
    print(f"Opportunities: {len(opportunities)}")
    print(f"{'=' * 80}\n")

    # Calculate positions
    allocations = []
    total_requested = 0

    for opp in opportunities:
        ticker = opp['ticker']
        signal_score = opp['score']
        data = opp['data']

        # Calculate position size
        position_pct = calculate_simple_position_pct(
            signal_score=signal_score,
            regime_multiplier=opp['regime'].get('position_size_multiplier', 1.0),
            volatility_multiplier=opp['vol_metrics'].get('position_multiplier', 1.0)
        )

        # Convert to dollars
        position_dollars = portfolio_value * (position_pct / 100)

        # Bounds check
        min_dollars = portfolio_value * (SimplifiedSizingConfig.MIN_POSITION_PCT / 100)
        max_dollars = portfolio_value * (SimplifiedSizingConfig.MAX_POSITION_PCT / 100)

        position_dollars = max(min_dollars, min(position_dollars, max_dollars))

        # Calculate quantity
        current_price = data['close']
        quantity = int(position_dollars / current_price)
        actual_cost = quantity * current_price

        if quantity > 0 and actual_cost >= min_dollars:
            allocations.append({
                'ticker': ticker,
                'quantity': quantity,
                'cost': actual_cost,
                'price': current_price,
                'pct_portfolio': (actual_cost / portfolio_value * 100),
                'position_pct': position_pct,
                'signal_score': signal_score,
                'signal_type': opp['signal_type'],
                'regime_mult': opp['regime'].get('position_size_multiplier', 1.0),
                'vol_mult': opp['vol_metrics'].get('position_multiplier', 1.0)
            })

            total_requested += actual_cost

    # Check budget
    if total_requested <= max_deployment:
        print(f"✅ All positions fit within budget\n")
        display_allocations(allocations, portfolio_value, total_requested)
        return allocations

    # Scale down proportionally if over budget
    scale_factor = max_deployment / total_requested

    print(f"⚠️  Over budget by ${total_requested - max_deployment:,.0f}")
    print(f"   Scaling all positions by {scale_factor:.2f}x\n")

    scaled_allocations = []
    total_cost = 0
    min_dollars = portfolio_value * (SimplifiedSizingConfig.MIN_POSITION_PCT / 100)

    for alloc in allocations:
        scaled_cost = alloc['cost'] * scale_factor
        scaled_quantity = int(scaled_cost / alloc['price'])
        scaled_actual_cost = scaled_quantity * alloc['price']

        # Skip if below minimum after scaling
        if scaled_quantity > 0 and scaled_actual_cost >= min_dollars:
            alloc['quantity'] = scaled_quantity
            alloc['cost'] = scaled_actual_cost
            alloc['pct_portfolio'] = (scaled_actual_cost / portfolio_value * 100)
            scaled_allocations.append(alloc)
            total_cost += scaled_actual_cost

    display_allocations(scaled_allocations, portfolio_value, total_cost)
    return scaled_allocations


def calculate_simple_position_pct(signal_score, regime_multiplier, volatility_multiplier):
    """
    Simple position sizing formula

    Base: 15%
    Signal Score Factor: 0.8x to 1.2x (based on 60-100 score)
    Regime Multiplier: 0.5x to 1.0x (from regime detection)
    Volatility Multiplier: 0.5x to 1.0x (from volatility check)

    Args:
        signal_score: Signal score 60-100
        regime_multiplier: Regime adjustment 0.5-1.0
        volatility_multiplier: Volatility adjustment 0.5-1.0

    Returns:
        float: Position size as % of portfolio (5-20%)
    """

    base_pct = SimplifiedSizingConfig.BASE_POSITION_PCT

    # Score factor: 60 score = 0.8x, 100 score = 1.2x
    # Linear scaling: (score - 60) / 100 gives 0 to 0.4, add 0.8 = 0.8 to 1.2
    score_factor = 0.8 + (signal_score - 60) / 100

    # Calculate final size
    final_pct = base_pct * score_factor * regime_multiplier * volatility_multiplier

    # Apply bounds
    final_pct = max(SimplifiedSizingConfig.MIN_POSITION_PCT,
                    min(final_pct, SimplifiedSizingConfig.MAX_POSITION_PCT))

    return final_pct


def display_allocations(allocations, portfolio_value, total_cost):
    """Display allocation table"""

    if not allocations:
        print(f"\n⚠️  No positions after sizing\n")
        return

    print(f"\n{'=' * 90}")
    print(f"📊 FINAL ALLOCATIONS")
    print(f"{'=' * 90}")
    print(f"Total Allocated: ${total_cost:,.0f} ({total_cost / portfolio_value * 100:.1f}% of portfolio)")
    print(f"Position Count: {len(allocations)}")
    print(f"{'=' * 90}\n")

    # Sort by cost (largest first)
    allocations.sort(key=lambda x: x['cost'], reverse=True)

    print(f"{'Ticker':<8} {'Signal':<20} {'Score':<7} {'Size%':<7} {'Qty':<6} {'Cost':<12} {'Multipliers'}")
    print(f"{'-' * 90}")

    for alloc in allocations:
        signal = alloc['signal_type'][:18]  # Truncate if too long
        score = f"{alloc['signal_score']:.0f}"
        size_pct = f"{alloc['position_pct']:.1f}%"
        qty = f"{alloc['quantity']}"
        cost = f"${alloc['cost']:,.0f}"

        # Multipliers
        total_mult = alloc['regime_mult'] * alloc['vol_mult']
        mults = f"R:{alloc['regime_mult']:.1f} V:{alloc['vol_mult']:.1f} = {total_mult:.2f}x"

        print(f"{alloc['ticker']:<8} {signal:<20} {score:<7} {size_pct:<7} {qty:<6} {cost:<12} {mults}")

    print(f"{'-' * 90}\n")


# =============================================================================
# PORTFOLIO CONTEXT BUILDER
# =============================================================================

def create_portfolio_context(strategy):
    """
    Create portfolio context dict from strategy

    Args:
        strategy: Lumibot Strategy instance

    Returns:
        dict: Portfolio context
    """
    cash_balance = strategy.get_cash()
    portfolio_value = strategy.portfolio_value
    existing_positions = len(strategy.get_positions())

    deployable_cash = cash_balance - SimplifiedSizingConfig.MIN_CASH_RESERVE
    deployable_cash = max(0, deployable_cash)

    return {
        'total_cash': cash_balance,
        'portfolio_value': portfolio_value,
        'existing_positions_count': existing_positions,
        'available_slots': SimplifiedSizingConfig.MAX_TOTAL_POSITIONS - existing_positions,
        'reserved_cash': SimplifiedSizingConfig.MIN_CASH_RESERVE,
        'deployable_cash': deployable_cash
    }
