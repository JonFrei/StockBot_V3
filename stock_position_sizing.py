"""
Position Sizing - Portfolio-Based with Pro-Rata Scaling

Logic:
- Size positions based on PORTFOLIO VALUE (risk control)
- Cap deployment to AVAILABLE CASH (hard constraint)
- Pro-rata scale all positions if total exceeds budget
- Rotation multiplier adjusts position size per tier
"""
import account_broker_data
from config import Config


# =============================================================================
# CONFIGURATION
# =============================================================================
class SimplifiedSizingConfig:
    """Position sizing configuration"""
    BASE_POSITION_PCT = 15.0          # Target size as % of portfolio value
    MAX_TOTAL_POSITIONS = 30          # Maximum concurrent positions
    MIN_CASH_RESERVE_PCT = 5.0        # Minimum cash buffer (% of cash)
    MAX_CASH_DEPLOYMENT_PCT = 95.0    # Max % of deployable cash per cycle
    MAX_SINGLE_POSITION_PCT = 20.0    # Max concentration in single stock


# =============================================================================
# POSITION EXPOSURE
# =============================================================================
def get_current_position_exposure(strategy, ticker, portfolio_context):
    """
    Get current exposure to a ticker as percentage of portfolio value.

    Returns:
        dict with has_position, quantity, market_value, exposure_pct
    """
    positions = strategy.get_positions()
    portfolio_value = portfolio_context['portfolio_value']

    for position in positions:
        if position.symbol == ticker:
            try:
                quantity = int(position.quantity)
                current_price = strategy.get_last_price(ticker)
                market_value = quantity * current_price
                exposure_pct = (market_value / portfolio_value * 100) if portfolio_value > 0 else 0

                return {
                    'has_position': True,
                    'quantity': quantity,
                    'market_value': market_value,
                    'exposure_pct': exposure_pct
                }
            except:
                return {
                    'has_position': True,
                    'quantity': 0,
                    'market_value': 0,
                    'exposure_pct': 0
                }

    return {
        'has_position': False,
        'quantity': 0,
        'market_value': 0,
        'exposure_pct': 0
    }


# =============================================================================
# POSITION SIZING
# =============================================================================
def calculate_position_sizes(opportunities, portfolio_context, regime_multiplier=1.0, verbose=True, strategy=None):
    """
    Portfolio-based position sizing with pro-rata scaling.

    Logic:
    1. Calculate ideal position size from portfolio value
    2. Apply rotation multiplier per stock
    3. Check concentration limits for add-ons
    4. Pro-rata scale ALL positions if total exceeds cash budget
    5. Return sorted by score (highest first)
    """
    if not opportunities or regime_multiplier == 0:
        return []

    portfolio_value = portfolio_context['portfolio_value']
    deployable_cash = portfolio_context['deployable_cash']

    # Calculate max deployment budget
    max_deployment = deployable_cash * (SimplifiedSizingConfig.MAX_CASH_DEPLOYMENT_PCT / 100)

    if max_deployment <= 0:
        return []

    # === STEP 1: Calculate ideal position size (portfolio-based) ===
    ideal_position_dollars = portfolio_value * (SimplifiedSizingConfig.BASE_POSITION_PCT / 100) * regime_multiplier

    # === STEP 2: Size each position ===
    allocations = []

    for opp in opportunities:
        try:
            ticker = opp['ticker']
            current_price = strategy.get_last_price(ticker)
            rotation_mult = opp.get('rotation_mult', 1.0)

            # Apply rotation multiplier
            tier_adjusted_dollars = ideal_position_dollars * rotation_mult
            this_position_dollars = tier_adjusted_dollars

            # Check concentration for add-ons
            if strategy is not None:
                current_exposure = get_current_position_exposure(strategy, ticker, portfolio_context)

                if current_exposure['has_position']:
                    if current_exposure['exposure_pct'] >= SimplifiedSizingConfig.MAX_SINGLE_POSITION_PCT:
                        if verbose:
                            print(f"   ⚠️ {ticker}: At max concentration ({current_exposure['exposure_pct']:.1f}%)")
                        continue

                    # Limit add-on to remaining room
                    remaining_room_pct = SimplifiedSizingConfig.MAX_SINGLE_POSITION_PCT - current_exposure['exposure_pct']
                    remaining_room_dollars = portfolio_value * (remaining_room_pct / 100)
                    this_position_dollars = min(tier_adjusted_dollars, remaining_room_dollars)

            # Calculate quantity
            raw_quantity = this_position_dollars / current_price

            if raw_quantity < 1.0:
                # For reduced tiers, allow minimum 1 share
                if rotation_mult < 1.0 and raw_quantity >= 0.01:
                    quantity = 1
                else:
                    continue
            else:
                quantity = int(raw_quantity)

            allocations.append({
                'ticker': ticker,
                'quantity': quantity,
                'price': current_price,
                'cost': quantity * current_price,
                'signal_score': opp['score'],
                'signal_type': opp['signal_type'],
                'rotation_mult': rotation_mult
            })

        except Exception as e:
            ticker_name = opp.get('ticker', 'unknown')
            if verbose:
                print(f"   ⚠️ {ticker_name}: Sizing failed - {e}")
            continue

    if not allocations:
        return []

    # === STEP 3: Pro-rata scale if over budget ===
    total_cost = sum(a['cost'] for a in allocations)

    if total_cost > max_deployment:
        scale_factor = max_deployment / total_cost

        scaled_allocations = []
        for alloc in allocations:
            scaled_quantity = int(alloc['quantity'] * scale_factor)

            # Keep at least 1 share if scaling results in fractional
            if scaled_quantity < 1 and alloc['quantity'] >= 1:
                scaled_quantity = 1

            if scaled_quantity < 1:
                continue

            scaled_allocations.append({
                'ticker': alloc['ticker'],
                'quantity': scaled_quantity,
                'price': alloc['price'],
                'cost': scaled_quantity * alloc['price'],
                'signal_score': alloc['signal_score'],
                'signal_type': alloc['signal_type'],
                'rotation_mult': alloc['rotation_mult']
            })

        allocations = scaled_allocations

    if not allocations:
        return []

    # Sort by score (highest first) for execution priority
    allocations.sort(key=lambda x: x['signal_score'], reverse=True)

    return allocations


# =============================================================================
# PORTFOLIO CONTEXT
# =============================================================================
def create_portfolio_context(strategy):
    """Create portfolio context dict with accurate cash tracking"""

    portfolio_value = strategy.portfolio_value
    existing_positions = len(strategy.get_positions())

    # Get cash balance
    if Config.BACKTESTING:
        cash_balance = strategy.get_cash()
    else:
        cash_balance = account_broker_data.get_cash_balance(strategy)

    deployed_capital = portfolio_value - cash_balance

    # Calculate reserve and deployable cash
    min_reserve = cash_balance * (SimplifiedSizingConfig.MIN_CASH_RESERVE_PCT / 100)
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