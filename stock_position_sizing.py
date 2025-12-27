"""
Position Sizing - WITH CONCENTRATION LIMITS FOR ADD-ONS

Changes from previous version:
- Removed MIN_SHARES enforcement (was 5)
- Let stock_position_monitoring.py handle small positions via remnant cleanup
- Applies rotation multiplier from stock rotation system
- NEW: Added MAX_SINGLE_POSITION_PCT to prevent over-concentration
- NEW: Added get_current_position_exposure() for add-on sizing
- NEW: Returns is_addon flag and existing position details
"""
import account_broker_data
from config import Config

# =============================================================================
# BACKTEST CASH TRACKER
# =============================================================================

_backtest_cash_tracker = {
    'initialized': False,
    'iteration_start_cash': 0.0,
    'buy_adjustments': 0.0,  # Negative values (money spent)
    'sell_adjustments': 0.0  # Positive values (money received) - not used for deployment
}


def sync_backtest_cash_start_of_day(strategy):
    """
    Sync cash at START of each iteration.
    Calculate actual cash from portfolio value minus positions (avoids margin/buying power issues).
    """
    global _backtest_cash_tracker

    portfolio_value = strategy.portfolio_value

    # Calculate actual cash = portfolio_value - total position value
    positions = strategy.get_positions()
    total_position_value = 0

    for position in positions:
        try:
            qty = abs(int(position.quantity))
            price = strategy.get_last_price(position.symbol)
            total_position_value += qty * price
        except:
            continue

    calculated_cash = portfolio_value - total_position_value
    lumibot_cash = strategy.get_cash()

    # Use calculated cash (more reliable than get_cash which may include margin)
    actual_cash = calculated_cash

    if Config.BACKTESTING:
        if abs(calculated_cash - lumibot_cash) > 100:
            print(
                f"[CASH WARNING] Lumibot cash: ${lumibot_cash:,.2f} | Calculated cash: ${calculated_cash:,.2f} | Using calculated")

    _backtest_cash_tracker = {
        'initialized': True,
        'iteration_start_cash': float(actual_cash),
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
    """Get adjusted cash for current iteration - buys only, no sell proceeds"""
    global _backtest_cash_tracker
    if _backtest_cash_tracker['initialized']:
        # Only use start cash minus buy adjustments (sells tracked separately)
        return _backtest_cash_tracker['iteration_start_cash'] + _backtest_cash_tracker['buy_adjustments']
    return None


# =============================================================================
# CONFIGURATION
# =============================================================================

class SimplifiedSizingConfig:
    """Position sizing configuration"""
    BASE_POSITION_PCT = 12.0
    MAX_POSITION_PCT = 15.0
    MAX_TOTAL_POSITIONS = 25
    MIN_CASH_RESERVE_PCT = 5.0
    MAX_CASH_DEPLOYMENT_PCT = 85.0
    MAX_DAILY_DEPLOYMENT_PCT = 50.0
    MAX_SINGLE_POSITION_PCT = 18.0


# =============================================================================
# POSITION EXPOSURE
# =============================================================================

def get_current_position_exposure(strategy, ticker):
    """
    Get current exposure to a ticker as percentage of portfolio
    """
    positions = strategy.get_positions()
    portfolio_value = strategy.portfolio_value

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
    Position sizing with equal allocation and uniform scaling.

    Logic:
    1. Each position gets BASE_POSITION_PCT of portfolio
    2. If total exceeds daily_limit, scale ALL down equally
    3. Return sorted by score (highest first) for execution priority
    """
    if not opportunities:
        return []

    # Don't allow any buying when regime says no trading
    if regime_multiplier == 0:
        return []

    portfolio_value = portfolio_context['portfolio_value']
    deployable_cash = portfolio_context['deployable_cash']

    # Safety cap: Never deploy more than actual reported cash
    actual_cash = portfolio_context['total_cash']
    if deployable_cash > actual_cash:
        deployable_cash = max(0, actual_cash - portfolio_value * (SimplifiedSizingConfig.MIN_CASH_RESERVE_PCT / 100))

    # Calculate limits
    cash_limit = deployable_cash * (SimplifiedSizingConfig.MAX_CASH_DEPLOYMENT_PCT / 100)
    daily_limit = portfolio_value * (SimplifiedSizingConfig.MAX_DAILY_DEPLOYMENT_PCT / 100)
    max_deployment = min(cash_limit, daily_limit)

    if Config.BACKTESTING:
        print(f"[SIZE DEBUG] === BUDGET CONSTRAINTS ===")
        print(f"[SIZE DEBUG] deployable_cash: ${deployable_cash:,.2f}")
        print(f"[SIZE DEBUG] cash_limit (85%): ${cash_limit:,.2f}")
        print(f"[SIZE DEBUG] daily_limit (50% of ${portfolio_value:,.0f}): ${daily_limit:,.2f}")
        print(f"[SIZE DEBUG] max_deployment: ${max_deployment:,.2f}")
        print(f"[SIZE DEBUG] opportunities count: {len(opportunities)}")

    if max_deployment <= 0:
        return []

    # Base position size (equal for all)
    base_position_pct = SimplifiedSizingConfig.BASE_POSITION_PCT * regime_multiplier
    base_position_dollars = portfolio_value * (base_position_pct / 100)

    allocations = []

    for opp in opportunities:
        ticker = opp['ticker']
        data = opp['data']
        current_price = data['close']

        # Check concentration limits for existing positions
        if strategy is not None:
            current_exposure = get_current_position_exposure(strategy, ticker)

            if current_exposure['has_position']:
                if current_exposure['exposure_pct'] >= SimplifiedSizingConfig.MAX_SINGLE_POSITION_PCT:
                    if verbose:
                        print(f"   ⚠️ {ticker}: At max concentration ({current_exposure['exposure_pct']:.1f}%)")
                    continue

                # For add-ons, limit to remaining room
                remaining_room_pct = SimplifiedSizingConfig.MAX_SINGLE_POSITION_PCT - current_exposure['exposure_pct']
                position_dollars = min(base_position_dollars, portfolio_value * (remaining_room_pct / 100))
            else:
                position_dollars = base_position_dollars
        else:
            position_dollars = base_position_dollars

        quantity = int(position_dollars / current_price)

        if quantity <= 0:
            continue

        allocations.append({
            'ticker': ticker,
            'quantity': quantity,
            'price': current_price,
            'cost': quantity * current_price,
            'signal_score': opp['score'],
            'signal_type': opp['signal_type'],
            'rotation_mult': opp.get('rotation_mult', 1.0)
        })

    if not allocations:
        return []

    # Calculate total cost
    total_cost = sum(a['cost'] for a in allocations)

    if Config.BACKTESTING:
        print(f"[SIZE DEBUG] === SCALING CHECK ===")
        print(f"[SIZE DEBUG] total_cost before scaling: ${total_cost:,.2f}")
        print(f"[SIZE DEBUG] max_deployment: ${max_deployment:,.2f}")
        print(f"[SIZE DEBUG] over budget: {total_cost > max_deployment}")

    # Scale down uniformly if over budget
    if total_cost > max_deployment:
        scale_factor = max_deployment / total_cost

        if Config.BACKTESTING:
            print(f"[SIZE DEBUG] SCALING DOWN by factor: {scale_factor:.3f}")

        scaled = []
        for alloc in allocations:
            scaled_qty = int(alloc['quantity'] * scale_factor)
            if scaled_qty > 0:
                alloc['quantity'] = scaled_qty
                alloc['cost'] = scaled_qty * alloc['price']
                scaled.append(alloc)

        allocations = scaled

        if Config.BACKTESTING:
            new_total = sum(a['cost'] for a in allocations)
            print(f"[SIZE DEBUG] total_cost after scaling: ${new_total:,.2f}")

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
        debug_cash_state("create_portfolio_context - START")
        lumibot_cash = strategy.get_cash()
        print(f"[CASH DEBUG] Lumibot get_cash(): ${lumibot_cash:,.2f}")

    # Use tracked cash for backtesting, Alpaca for live
    if Config.BACKTESTING and _backtest_cash_tracker['initialized']:
        cash_balance = get_tracked_cash()
        print(f"[CASH DEBUG] Using tracked cash: ${cash_balance:,.2f}")

    else:
        cash_balance = account_broker_data.get_cash_balance(strategy)
        if Config.BACKTESTING:
            print(f"[CASH DEBUG] Using broker cash (tracker not init): ${cash_balance:,.2f}")

    deployed_capital = portfolio_value - cash_balance
    min_reserve = portfolio_value * (SimplifiedSizingConfig.MIN_CASH_RESERVE_PCT / 100)
    deployable_cash = max(0, cash_balance - min_reserve)

    # DEBUG: Log all calculated values
    if Config.BACKTESTING:
        print(f"[CASH DEBUG] portfolio_value: ${portfolio_value:,.2f}")
        print(f"[CASH DEBUG] cash_balance: ${cash_balance:,.2f}")
        print(f"[CASH DEBUG] deployed_capital: ${deployed_capital:,.2f}")
        print(f"[CASH DEBUG] min_reserve (5%): ${min_reserve:,.2f}")
        print(f"[CASH DEBUG] deployable_cash: ${deployable_cash:,.2f}")

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


def debug_cash_state(label=""):
    if Config.BACKTESTING:
        print(f"[CASH DEBUG] {label}")
        print(f"   initialized: {_backtest_cash_tracker['initialized']}")
        print(f"   iteration_start_cash: ${_backtest_cash_tracker['iteration_start_cash']:,.2f}")
        print(f"   buy_adjustments: ${_backtest_cash_tracker['buy_adjustments']:,.2f}")
        print(f"   sell_adjustments: ${_backtest_cash_tracker['sell_adjustments']:,.2f}")
        tracked = get_tracked_cash()
        print(f"   tracked_cash (for buys): ${tracked:,.2f}" if tracked else "   tracked_cash: None")
