"""
Position Sizing - WITH SCALE FACTOR FOR BUDGET CONSTRAINTS

Changes:
- Added scale factor logic: if total cost exceeds budget, proportionally reduce all positions
- Removed MIN_SHARES enforcement (handled by remnant cleanup)
- Applies rotation multiplier from stock rotation system
- MAX_SINGLE_POSITION_PCT prevents over-concentration
- get_current_position_exposure() for add-on sizing
"""
import account_broker_data
from config import Config

# =============================================================================
# BACKTEST CASH TRACKER
# =============================================================================
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


# =============================================================================
# CONFIGURATION
# =============================================================================

class SimplifiedSizingConfig:
    """Position sizing configuration"""
    BASE_POSITION_PCT = 18.0
    MAX_POSITION_PCT = 20.0
    MAX_TOTAL_POSITIONS = 25
    MIN_CASH_RESERVE_PCT = 10.0
    MAX_CASH_DEPLOYMENT_PCT = 85.0
    MAX_DAILY_DEPLOYMENT_PCT = 50.0
    MAX_SINGLE_POSITION_PCT = 20.0


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
    Position sizing based on available cash with scale factor for budget constraints.

    Logic:
    1. Calculate max we can deploy
    2. Size each position (capped at BASE_POSITION_PCT of portfolio)
    3. Sum all positions and check against available cash
    4. If sum exceeds budget, apply scale factor to reduce all positions proportionally
    5. Return sorted by score (highest first) for execution priority
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
    daily_limit = deployable_cash * (SimplifiedSizingConfig.MAX_DAILY_DEPLOYMENT_PCT / 100)
    max_deployment = min(cash_limit, daily_limit)

    if Config.BACKTESTING:
        print(f"[SIZE DEBUG] === BUDGET CONSTRAINTS ===")
        print(f"[SIZE DEBUG] deployable_cash: ${deployable_cash:,.2f}")
        print(f"[SIZE DEBUG] cash_limit ({SimplifiedSizingConfig.MAX_CASH_DEPLOYMENT_PCT}%): ${cash_limit:,.2f}")
        print(f"[SIZE DEBUG] daily_limit ({SimplifiedSizingConfig.MAX_DAILY_DEPLOYMENT_PCT}% of ${portfolio_value:,.0f}): ${daily_limit:,.2f}")
        print(f"[SIZE DEBUG] max_deployment: ${max_deployment:,.2f}")
        print(f"[SIZE DEBUG] opportunities count: {len(opportunities)}")

    if max_deployment <= 0:
        return []

    # === Size based on available cash, not portfolio ===
    # Max per position based on portfolio (original logic)
    max_position_from_portfolio = portfolio_value * (SimplifiedSizingConfig.BASE_POSITION_PCT / 100) * regime_multiplier

    # Max per position based on dividing available deployment evenly
    max_position_from_cash = max_deployment / len(opportunities)

    # Use the SMALLER of the two
    position_dollars = min(max_position_from_portfolio, max_position_from_cash)

    if Config.BACKTESTING:
        print(f"[SIZE DEBUG] max_position_from_portfolio (12%): ${max_position_from_portfolio:,.2f}")
        print(f"[SIZE DEBUG] max_position_from_cash (${max_deployment:,.0f} / {len(opportunities)}): ${max_position_from_cash:,.2f}")
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

    # === STEP 3 & 4: Check total and apply scale factor if needed ===
    total_cost = sum(a['cost'] for a in allocations)

    if Config.BACKTESTING:
        print(f"[SIZE DEBUG] === BUDGET CHECK ===")
        print(f"[SIZE DEBUG] total_cost (before scaling): ${total_cost:,.2f}")
        print(f"[SIZE DEBUG] max_deployment: ${max_deployment:,.2f}")

    if total_cost > max_deployment:
        # Calculate scale factor
        scale_factor = max_deployment / total_cost

        if Config.BACKTESTING:
            print(f"[SIZE DEBUG] ⚠️ OVER BUDGET - applying scale factor: {scale_factor:.4f}")

        # Apply scale factor to all positions
        scaled_allocations = []
        for alloc in allocations:
            scaled_quantity = int(alloc['quantity'] * scale_factor)

            # Skip if scaled to 0 shares
            if scaled_quantity <= 0:
                if Config.BACKTESTING:
                    print(f"[SIZE DEBUG]    {alloc['ticker']}: scaled to 0 shares, skipping")
                continue

            scaled_cost = scaled_quantity * alloc['price']
            scaled_allocations.append({
                'ticker': alloc['ticker'],
                'quantity': scaled_quantity,
                'price': alloc['price'],
                'cost': scaled_cost,
                'signal_score': alloc['signal_score'],
                'signal_type': alloc['signal_type'],
                'rotation_mult': alloc['rotation_mult']
            })

            if Config.BACKTESTING:
                print(f"[SIZE DEBUG]    {alloc['ticker']}: {alloc['quantity']} → {scaled_quantity} shares (${alloc['cost']:,.2f} → ${scaled_cost:,.2f})")

        allocations = scaled_allocations

        # Recalculate total after scaling
        total_cost = sum(a['cost'] for a in allocations)

        if Config.BACKTESTING:
            print(f"[SIZE DEBUG] total_cost (after scaling): ${total_cost:,.2f}")

    if not allocations:
        return []

    if Config.BACKTESTING:
        print(f"[SIZE DEBUG] === FINAL CHECK ===")
        print(f"[SIZE DEBUG] total_cost: ${total_cost:,.2f}")
        print(f"[SIZE DEBUG] max_deployment: ${max_deployment:,.2f}")
        print(f"[SIZE DEBUG] within budget: {total_cost <= max_deployment}")
        print(f"[SIZE DEBUG] positions count: {len(allocations)}")

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