"""
Position Sizing - WITH SCALE FACTOR FOR BUDGET CONSTRAINTS

Changes:
- Added scale factor logic: if total cost exceeds budget, proportionally reduce all positions
- Removed MIN_SHARES enforcement (handled by remnant cleanup)
- Applies rotation multiplier from stock rotation system
- MAX_SINGLE_POSITION_PCT prevents over-concentration
- get_current_position_exposure() for add-on sizing
- ALL SIZING NOW REFERENCES CASH, NOT PORTFOLIO VALUE
"""
import account_broker_data
from config import Config

# =============================================================================
# BACKTEST CASH TRACKER
# =============================================================================
'''
_backtest_cash_tracker = {
    'initialized': False,
    'iteration_start_cash': 0.0,
    'buy_adjustments': 0.0,
    'sell_adjustments': 0.0
}


def sync_backtest_cash_start_of_day(strategy):
    global _backtest_cash_tracker
    _backtest_cash_tracker = {
        'initialized': True,
        'iteration_start_cash': float(strategy.get_cash()),
        'buy_adjustments': 0.0,
        'sell_adjustments': 0.0
    }


def update_backtest_cash_for_buy(cost):
    global _backtest_cash_tracker
    if _backtest_cash_tracker['initialized']:
        _backtest_cash_tracker['buy_adjustments'] -= cost


def update_backtest_cash_for_sell(proceeds):
    global _backtest_cash_tracker
    if _backtest_cash_tracker['initialized']:
        _backtest_cash_tracker['sell_adjustments'] += proceeds


def get_tracked_cash():
    global _backtest_cash_tracker
    if _backtest_cash_tracker['initialized']:
        return (_backtest_cash_tracker['iteration_start_cash']
                + _backtest_cash_tracker['buy_adjustments']
                + _backtest_cash_tracker['sell_adjustments'])
    return None


def debug_cash_state(label="", strategy=None):
    
    if Config.BACKTESTING:
        print(f"[CASH DEBUG] {label}")
        print(f"   initialized: {_backtest_cash_tracker['initialized']}")
        print(f"   iteration_start_cash: ${_backtest_cash_tracker['iteration_start_cash']:,.2f}")
        print(f"   buy_adjustments: ${_backtest_cash_tracker['buy_adjustments']:,.2f}")
        print(f"   sell_adjustments: ${_backtest_cash_tracker['sell_adjustments']:,.2f}")
        tracked = get_tracked_cash()
        print(f"   tracked_cash: ${tracked:,.2f}" if tracked else "   tracked_cash: None")

        if strategy is not None:
            lumibot_cash = strategy.get_cash()
            print(f"   lumibot_cash: ${lumibot_cash:,.2f}")
            if tracked is not None:
                discrepancy = lumibot_cash - tracked
                if abs(discrepancy) > 1:
                    print(f"   ⚠️ DISCREPANCY: ${discrepancy:,.2f}")


def validate_end_of_day_cash(strategy):
    """Call at end of iteration to detect cash tracking drift"""
    if Config.BACKTESTING and _backtest_cash_tracker['initialized']:
        tracked = get_tracked_cash()
        lumibot = strategy.get_cash()
        discrepancy = lumibot - tracked if tracked else 0

        print(f"[CASH VALIDATION] End of Day")
        print(f"   Tracked: ${tracked:,.2f}" if tracked else "   Tracked: None")
        print(f"   Lumibot: ${lumibot:,.2f}")
        print(f"   Discrepancy: ${discrepancy:,.2f}")

        if abs(discrepancy) > 100:
            print(f"   ⚠️ SIGNIFICANT DRIFT DETECTED")
'''

# =============================================================================
# CONFIGURATION
# =============================================================================

class SimplifiedSizingConfig:
    """Position sizing configuration"""
    BASE_POSITION_PCT = 18.0
    MAX_POSITION_PCT = 20.0
    MAX_TOTAL_POSITIONS = 30
    MIN_CASH_RESERVE_PCT = 10.0

    MAX_CASH_DEPLOYMENT_PCT = 85.0
    MAX_DAILY_DEPLOYMENT_PCT = 80.0
    MAX_SINGLE_POSITION_PCT = 20.0


# =============================================================================
# POSITION EXPOSURE
# =============================================================================

def get_current_position_exposure(strategy, ticker, portfolio_context):
    """
    Get current exposure to a ticker as percentage of total cash.

    Args:
        strategy: Trading strategy instance
        ticker: Stock symbol
        portfolio_context: Dict containing 'total_cash' and other context

    Returns:
        dict with has_position, quantity, market_value, exposure_pct
    """
    positions = strategy.get_positions()
    cash_basis = portfolio_context['portfolio_value']

    for position in positions:
        if position.symbol == ticker:
            try:
                quantity = int(position.quantity)
                current_price = strategy.get_last_price(ticker)
                market_value = quantity * current_price
                exposure_pct = (market_value / cash_basis * 100) if cash_basis > 0 else 0

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
    Position sizing based on available cash with scale factor for budget constraints.

    Logic:
    1. Apply rotation tier multiplier FIRST (premium=1.5x, probation=0.5x, etc.)
    2. Size each position based on adjusted dollars
    3. Handle fractional shares: round to 1 for reduced tiers (0.01-0.99 shares)
    4. If over budget, scale down - but protect minimum (1 share) positions
    5. Return sorted by score (highest first) for execution priority
    """
    if not opportunities:
        return []

    if regime_multiplier == 0:
        return []

    portfolio_value = portfolio_context['portfolio_value']
    deployable_cash = portfolio_context['deployable_cash']
    total_cash = portfolio_context['total_cash']

    # Safety cap
    actual_cash = portfolio_context['total_cash']
    if deployable_cash > actual_cash:
        deployable_cash = max(0, actual_cash - total_cash * (SimplifiedSizingConfig.MIN_CASH_RESERVE_PCT / 100))

    # Calculate limits
    cash_limit = deployable_cash * (SimplifiedSizingConfig.MAX_CASH_DEPLOYMENT_PCT / 100)
    daily_limit = deployable_cash * (SimplifiedSizingConfig.MAX_DAILY_DEPLOYMENT_PCT / 100)
    max_deployment = min(cash_limit, daily_limit)

    if max_deployment <= 0:
        return []

    # === STEP 1: Calculate base position size (before rotation multiplier) ===
    # Max per position based on cash
    base_position_from_cash = total_cash * (SimplifiedSizingConfig.BASE_POSITION_PCT / 100) * regime_multiplier

    # Max per position based on dividing available deployment evenly
    base_position_from_deployment = max_deployment / len(opportunities)

    # Use the SMALLER of the two as base
    base_position_dollars = min(base_position_from_cash, base_position_from_deployment)

    # === STEP 2: Size each position with rotation multiplier applied FIRST ===
    allocations = []

    for opp in opportunities:
        try:
            ticker = opp['ticker']
            data = opp['data']
            # current_price = data['close']
            current_price = strategy.get_last_price(ticker)
            rotation_mult = opp.get('rotation_mult', 1.0)

            # Apply rotation multiplier FIRST to get tier-adjusted position size
            tier_adjusted_dollars = base_position_dollars * rotation_mult

            # Adjust for existing positions (add-ons)
            this_position_dollars = tier_adjusted_dollars

            if strategy is not None:
                current_exposure = get_current_position_exposure(strategy, ticker, portfolio_context)

                if current_exposure['has_position']:
                    if current_exposure['exposure_pct'] >= SimplifiedSizingConfig.MAX_SINGLE_POSITION_PCT:
                        if verbose:
                            print(f"   ⚠️ {ticker}: At max concentration ({current_exposure['exposure_pct']:.1f}%)")
                        continue

                    # For add-ons, limit to remaining room (based on portfolio)
                    remaining_room_pct = SimplifiedSizingConfig.MAX_SINGLE_POSITION_PCT - current_exposure['exposure_pct']
                    remaining_room_dollars = portfolio_value * (remaining_room_pct / 100)
                    # Also apply rotation multiplier to add-on room
                    this_position_dollars = min(tier_adjusted_dollars, remaining_room_dollars)

            # Calculate raw quantity (as float)
            raw_quantity = this_position_dollars / current_price

            # Determine if this is a reduced-size tier (probation, rehabilitation, frozen)
            is_reduced_tier = rotation_mult < 1.0
            is_minimum_position = False

            # Handle quantity calculation with fractional share logic
            if raw_quantity >= 1.0:
                # Normal case: use integer portion
                quantity = int(raw_quantity)
            elif is_reduced_tier and raw_quantity >= 0.01:
                # Reduced tiers (probation/rehab/frozen): round up to minimum 1 share
                quantity = 1
                is_minimum_position = True
            else:
                # Position too small - skip
                if verbose and is_reduced_tier:
                    tier_name = 'frozen' if rotation_mult <= 0.1 else ('rehab' if rotation_mult <= 0.25 else 'probation')
                    print(f"   ⚠️ {ticker}: Position too small for {tier_name} tier ({rotation_mult}x → ${this_position_dollars:.2f})")
                continue

            allocations.append({
                'ticker': ticker,
                'quantity': quantity,
                'price': current_price,
                'cost': quantity * current_price,
                'signal_score': opp['score'],
                'signal_type': opp['signal_type'],
                'rotation_mult': rotation_mult,
                'is_minimum_position': is_minimum_position  # Track if this is a protected 1-share position
            })

        except Exception as e:
            ticker_name = opp.get('ticker', 'unknown')
            if verbose:
                print(f"   ⚠️ {ticker_name}: Sizing failed - {e}")
            continue

    if not allocations:
        return []

    # === STEP 3: Check budget and apply scale factor if needed ===
    total_cost = sum(a['cost'] for a in allocations)

    if total_cost > max_deployment:
        # Separate minimum positions (protected) from scalable positions
        minimum_positions = [a for a in allocations if a.get('is_minimum_position', False)]
        scalable_positions = [a for a in allocations if not a.get('is_minimum_position', False)]

        # Calculate how much budget is consumed by minimum positions
        minimum_cost = sum(a['cost'] for a in minimum_positions)
        scalable_cost = sum(a['cost'] for a in scalable_positions)

        # Remaining budget for scalable positions
        remaining_budget = max_deployment - minimum_cost

        if remaining_budget <= 0:
            # Not enough budget even for minimum positions - prioritize by score
            # Sort by score and take what fits
            minimum_positions.sort(key=lambda x: x['signal_score'], reverse=True)
            final_allocations = []
            running_cost = 0
            for alloc in minimum_positions:
                if running_cost + alloc['cost'] <= max_deployment:
                    final_allocations.append(alloc)
                    running_cost += alloc['cost']
            allocations = final_allocations
        elif scalable_cost > 0 and scalable_cost > remaining_budget:
            # Need to scale down scalable positions
            scale_factor = remaining_budget / scalable_cost

            scaled_allocations = []
            for alloc in scalable_positions:
                raw_scaled = alloc['quantity'] * scale_factor
                rotation_mult = alloc.get('rotation_mult', 1.0)
                is_reduced_tier = rotation_mult < 1.0

                # Handle fractional shares after scaling
                if raw_scaled >= 1.0:
                    scaled_quantity = int(raw_scaled)
                elif is_reduced_tier and raw_scaled >= 0.01:
                    # Reduced tier scaled below 1 - becomes minimum position
                    scaled_quantity = 1
                else:
                    # Too small after scaling - skip
                    continue

                scaled_cost = scaled_quantity * alloc['price']
                scaled_allocations.append({
                    'ticker': alloc['ticker'],
                    'quantity': scaled_quantity,
                    'price': alloc['price'],
                    'cost': scaled_cost,
                    'signal_score': alloc['signal_score'],
                    'signal_type': alloc['signal_type'],
                    'rotation_mult': alloc['rotation_mult'],
                    'is_minimum_position': alloc.get('is_minimum_position', False) or scaled_quantity == 1
                })

            # Combine minimum + scaled positions
            allocations = minimum_positions + scaled_allocations
        else:
            # Scalable positions fit within remaining budget - no scaling needed
            allocations = minimum_positions + scalable_positions

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
    import account_broker_data

    portfolio_value = strategy.portfolio_value
    existing_positions = len(strategy.get_positions())

    # DEBUG: Log state before getting cash
    if Config.BACKTESTING:
        '''
        debug_cash_state("create_portfolio_context - START")
        '''
        lumibot_cash = strategy.get_cash()
        '''
        print(f"[CASH DEBUG] Lumibot get_cash(): ${lumibot_cash:,.2f}")
        '''

    # Use tracked cash for backtesting, Alpaca for live
    if Config.BACKTESTING:
        # cash_balance = get_tracked_cash()
        cash_balance = strategy.get_cash()
        '''
        print(f"[CASH DEBUG] Using tracked cash: ${cash_balance:,.2f}")
        '''

    else:
        cash_balance = account_broker_data.get_cash_balance(strategy)
        if Config.BACKTESTING:
            '''
            print(f"[CASH DEBUG] Using broker cash (tracker not init): ${cash_balance:,.2f}")
            '''
    deployed_capital = portfolio_value - cash_balance
    # MIN_CASH_RESERVE now based on cash_balance, not portfolio_value
    min_reserve = cash_balance * (SimplifiedSizingConfig.MIN_CASH_RESERVE_PCT / 100)
    deployable_cash = max(0, cash_balance - min_reserve)

    # DEBUG: Log all calculated values
    '''
    if Config.BACKTESTING:
        print(f"[CASH DEBUG] portfolio_value: ${portfolio_value:,.2f}")
        print(f"[CASH DEBUG] cash_balance: ${cash_balance:,.2f}")
        print(f"[CASH DEBUG] deployed_capital: ${deployed_capital:,.2f}")
        print(f"[CASH DEBUG] min_reserve ({SimplifiedSizingConfig.MIN_CASH_RESERVE_PCT}% of cash): ${min_reserve:,.2f}")
        print(f"[CASH DEBUG] deployable_cash: ${deployable_cash:,.2f}")
    '''

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
