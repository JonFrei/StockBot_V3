"""
SIMPLIFIED Position Sizing System - FIXED VERSION

IMPROVEMENTS IN THIS VERSION:
- MAX_CASH_DEPLOYMENT increased from 60% → 85% (more aggressive)
- MIN_CASH_RESERVE now portfolio-relative (15% instead of fixed $20k)
- Added deployed capital tracking
- Added daily deployment limits
- Better handling of multiple opportunities

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
    MIN_POSITION_PCT = 8.0  # Below this = skip
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
    Simple position sizing: base × signal_score × regime × volatility

    IMPROVEMENTS:
    - Increased cash deployment from 60% → 85%
    - Added daily deployment tracking
    - Portfolio-relative reserve (15% instead of fixed $20k)
    - Better multi-opportunity handling

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
    deployed_capital = portfolio_context.get('deployed_capital', 0)

    # Calculate maximum deployment
    cash_limit = deployable_cash * (SimplifiedSizingConfig.MAX_CASH_DEPLOYMENT_PCT / 100)

    # Daily limit to prevent over-concentration
    daily_limit = portfolio_value * (SimplifiedSizingConfig.MAX_DAILY_DEPLOYMENT_PCT / 100)

    # Use lesser of cash limit or daily limit
    max_deployment = min(cash_limit, daily_limit)

    print(f"\n{'=' * 80}")
    print(f"💰 POSITION SIZING")
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

    # Calculate positions
    allocations = []
    total_requested = 0

    for opp in opportunities:
        ticker = opp['ticker']
        signal_score = opp['score']
        data = opp['data']

        # Calculate position size with all multipliers
        # Base: 15%, Score factor: 0.8x to 1.2x (60-100), Regime: 0.5-1.0x, Vol: 0.5-1.0x, Stock: 0.6-1.0x
        regime_mult = opp['regime'].get('position_size_multiplier', 1.0)
        vol_mult = opp['vol_metrics'].get('position_multiplier', 1.0)
        stock_mult = opp.get('stock_regime_mult', 1.0)  # Stock-specific health multiplier

        score_factor = 0.8 + (signal_score - 60) / 100
        #position_pct = SimplifiedSizingConfig.BASE_POSITION_PCT * score_factor * regime_mult * vol_mult * stock_mult
        position_pct = SimplifiedSizingConfig.BASE_POSITION_PCT * regime_mult * stock_mult

        # Apply bounds
        position_pct = max(SimplifiedSizingConfig.MIN_POSITION_PCT,
                           min(position_pct, SimplifiedSizingConfig.MAX_POSITION_PCT))

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
                'vol_mult': opp['vol_metrics'].get('position_multiplier', 1.0),
                'stock_mult': opp.get('stock_regime_mult', 1.0)  # Stock health multiplier
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
    print(f"   Requested: ${total_requested:,.0f}")
    print(f"   Available: ${max_deployment:,.0f}")
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
        else:
            print(
                f"   ⚠️  {alloc['ticker']}: Scaled to ${scaled_actual_cost:,.0f} - Below minimum ${min_dollars:,.0f}, skipping")

    display_allocations(scaled_allocations, portfolio_value, total_cost)
    return scaled_allocations


def display_allocations(allocations, portfolio_value, total_cost):
    """Display allocation table with improved formatting"""

    if not allocations:
        print(f"\n⚠️  No positions after sizing\n")
        return

    print(f"\n{'=' * 100}")
    print(f"📊 FINAL ALLOCATIONS")
    print(f"{'=' * 100}")
    print(f"Total Allocated: ${total_cost:,.0f} ({total_cost / portfolio_value * 100:.1f}% of portfolio)")
    print(f"Position Count: {len(allocations)}")
    print(f"Average Position: ${total_cost / len(allocations):,.0f}")
    print(f"{'=' * 100}\n")

    # Sort by cost (largest first)
    allocations.sort(key=lambda x: x['cost'], reverse=True)

    print(f"{'Ticker':<8} {'Signal':<20} {'Score':<7} {'Size%':<8} {'Qty':<7} {'Cost':<14} {'Multipliers'}")
    print(f"{'-' * 100}")

    for alloc in allocations:
        signal = alloc['signal_type'][:18]
        score = f"{alloc['signal_score']:.0f}"
        size_pct = f"{alloc['position_pct']:.1f}%"
        qty = f"{alloc['quantity']}"
        cost = f"${alloc['cost']:,.0f}"

        # Multipliers breakdown (now includes Stock health)
        score_factor = 0.8 + (alloc['signal_score'] - 60) / 100
        stock_mult = alloc.get('stock_mult', 1.0)
        total_mult = score_factor * alloc['regime_mult'] * alloc['vol_mult'] * stock_mult
        mults = f"S:{score_factor:.2f} R:{alloc['regime_mult']:.2f} V:{alloc['vol_mult']:.2f} H:{stock_mult:.2f} = {total_mult:.2f}x"

        print(f"{alloc['ticker']:<8} {signal:<20} {score:<7} {size_pct:<8} {qty:<7} {cost:<14} {mults}")

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