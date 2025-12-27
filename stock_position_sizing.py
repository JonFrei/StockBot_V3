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
    'absolute_cash': 0.0,  # Our own running cash balance
    'daily_spent': 0.0,    # Reset each day
    'daily_received': 0.0  # Reset each day
}


def init_backtest_cash(initial_capital):
    """Call once at strategy start with initial capital"""
    global _backtest_cash_tracker
    _backtest_cash_tracker = {
        'initialized': True,
        'absolute_cash': float(initial_capital),
        'daily_spent': 0.0,
        'daily_received': 0.0
    }


def sync_backtest_cash_start_of_day():
    """Call at start of each iteration - just reset daily counters"""
    global _backtest_cash_tracker
    if _backtest_cash_tracker['initialized']:
        # Apply yesterday's activity to absolute cash
        _backtest_cash_tracker['absolute_cash'] += _backtest_cash_tracker['daily_received']
        # daily_spent already subtracted in update_backtest_cash_for_buy
        _backtest_cash_tracker['daily_spent'] = 0.0
        _backtest_cash_tracker['daily_received'] = 0.0


def update_backtest_cash_for_buy(cost):
    """Track buy - immediately subtract from absolute cash"""
    global _backtest_cash_tracker
    if _backtest_cash_tracker['initialized']:
        _backtest_cash_tracker['absolute_cash'] -= cost
        _backtest_cash_tracker['daily_spent'] += cost


def update_backtest_cash_for_sell(proceeds):
    """Track sell - add to daily received (settles next day)"""
    global _backtest_cash_tracker
    if _backtest_cash_tracker['initialized']:
        _backtest_cash_tracker['daily_received'] += proceeds


def get_tracked_cash():
    """Get our tracked cash balance (excludes unsettled sells)"""
    global _backtest_cash_tracker
    if _backtest_cash_tracker['initialized']:
        return _backtest_cash_tracker['absolute_cash']
    return None


def get_daily_spent():
    """Get amount spent today"""
    global _backtest_cash_tracker
    if _backtest_cash_tracker['initialized']:
        return _backtest_cash_tracker['daily_spent']
    return 0.0


def debug_cash_state(label=""):
    if Config.BACKTESTING:
        print(f"[CASH DEBUG] {label}")
        print(f"   initialized: {_backtest_cash_tracker['initialized']}")
        print(f"   absolute_cash: ${_backtest_cash_tracker['absolute_cash']:,.2f}")
        print(f"   daily_spent: ${_backtest_cash_tracker['daily_spent']:,.2f}")
        print(f"   daily_received: ${_backtest_cash_tracker['daily_received']:,.2f}")

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
    Position sizing based on available cash, not portfolio value.

    Logic:
    1. Calculate max we can deploy
    2. Divide evenly among opportunities (capped at BASE_POSITION_PCT of portfolio)
    3. Return sorted by score (highest first) for execution priority
    """
    if not opportunities:
        return []

    if regime_multiplier == 0:
        return []

    portfolio_value = portfolio_context['portfolio_value']
    deployable_cash = portfolio_context['deployable_cash']

    # Safety cap
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

    # === KEY CHANGE: Size based on available cash, not portfolio ===
    # Max per position based on portfolio (original logic)
    max_position_from_portfolio = portfolio_value * (SimplifiedSizingConfig.BASE_POSITION_PCT / 100) * regime_multiplier

    # Max per position based on dividing available deployment evenly
    max_position_from_cash = max_deployment / len(opportunities)

    # Use the SMALLER of the two
    position_dollars = min(max_position_from_portfolio, max_position_from_cash)

    if Config.BACKTESTING:
        print(f"[SIZE DEBUG] max_position_from_portfolio (12%): ${max_position_from_portfolio:,.2f}")
        print(
            f"[SIZE DEBUG] max_position_from_cash (${max_deployment:,.0f} / {len(opportunities)}): ${max_position_from_cash:,.2f}")
        print(f"[SIZE DEBUG] position_dollars (using min): ${position_dollars:,.2f}")

    allocations = []

    for opp in opportunities:
        ticker = opp['ticker']
        data = opp['data']
        current_price = data['close']

        # Adjust for existing positions (add-ons)
        this_position_dollars = position_dollars

        if strategy is not None:
            current_exposure = get_current_position_exposure(strategy, ticker)

            if current_exposure['has_position']:
                if current_exposure['exposure_pct'] >= SimplifiedSizingConfig.MAX_SINGLE_POSITION_PCT:
                    if verbose:
                        print(f"   ⚠️ {ticker}: At max concentration ({current_exposure['exposure_pct']:.1f}%)")
                    continue

                # For add-ons, limit to remaining room
                remaining_room_pct = SimplifiedSizingConfig.MAX_SINGLE_POSITION_PCT - current_exposure['exposure_pct']
                remaining_room_dollars = portfolio_value * (remaining_room_pct / 100)
                this_position_dollars = min(position_dollars, remaining_room_dollars)

        quantity = int(this_position_dollars / current_price)

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

    # Verify total (should already be within budget, but double-check)
    total_cost = sum(a['cost'] for a in allocations)

    if Config.BACKTESTING:
        print(f"[SIZE DEBUG] === FINAL CHECK ===")
        print(f"[SIZE DEBUG] total_cost: ${total_cost:,.2f}")
        print(f"[SIZE DEBUG] max_deployment: ${max_deployment:,.2f}")
        print(f"[SIZE DEBUG] within budget: {total_cost <= max_deployment}")

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


