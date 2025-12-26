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
    'iteration_start_cash': 0.0,  # Cash at start of iteration (from Lumibot)
    'iteration_adjustments': 0.0   # Buy/sell adjustments within iteration
}


def sync_backtest_cash_start_of_day(lumibot_cash):
    """Call at START of each iteration to sync with Lumibot's cash"""
    global _backtest_cash_tracker
    _backtest_cash_tracker = {
        'initialized': True,
        'iteration_start_cash': float(lumibot_cash),
        'iteration_adjustments': 0.0
    }


def update_backtest_cash_for_buy(cost):
    """Track buy within current iteration"""
    global _backtest_cash_tracker
    if _backtest_cash_tracker['initialized']:
        _backtest_cash_tracker['iteration_adjustments'] -= cost


def update_backtest_cash_for_sell(proceeds):
    """Track sell within current iteration"""
    global _backtest_cash_tracker
    if _backtest_cash_tracker['initialized']:
        _backtest_cash_tracker['iteration_adjustments'] += proceeds


def get_tracked_cash():
    """Get adjusted cash for current iteration"""
    global _backtest_cash_tracker
    if _backtest_cash_tracker['initialized']:
        return _backtest_cash_tracker['iteration_start_cash'] + _backtest_cash_tracker['iteration_adjustments']
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
    Position sizing with rotation multiplier support and concentration limits
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

    cash_limit = deployable_cash * (SimplifiedSizingConfig.MAX_CASH_DEPLOYMENT_PCT / 100)
    daily_limit = portfolio_value * (SimplifiedSizingConfig.MAX_DAILY_DEPLOYMENT_PCT / 100)
    max_deployment = min(cash_limit, daily_limit)

    allocations = []

    for opp in opportunities:
        ticker = opp['ticker']
        data = opp['data']
        vol_mult = opp['vol_metrics'].get('position_multiplier', 1.0)
        rotation_mult = opp.get('rotation_mult', 1.0)

        current_exposure = {'has_position': False, 'exposure_pct': 0, 'quantity': 0, 'market_value': 0}
        is_addon = False

        if strategy is not None:
            current_exposure = get_current_position_exposure(strategy, ticker)
            is_addon = current_exposure['has_position']

            if current_exposure['exposure_pct'] >= SimplifiedSizingConfig.MAX_SINGLE_POSITION_PCT:
                if verbose:
                    print(f"   ⚠️ {ticker}: At max concentration ({current_exposure['exposure_pct']:.1f}%)")
                continue

        position_pct = SimplifiedSizingConfig.BASE_POSITION_PCT * regime_multiplier * vol_mult * rotation_mult
        position_pct = min(position_pct, SimplifiedSizingConfig.MAX_POSITION_PCT)
        if position_pct < 0.5:
            continue  # Skip positions that are too small

        if is_addon:
            remaining_room_pct = SimplifiedSizingConfig.MAX_SINGLE_POSITION_PCT - current_exposure['exposure_pct']
            position_pct = min(position_pct, remaining_room_pct)

            if position_pct <= 0.5:
                if verbose:
                    print(f"   ⚠️ {ticker}: Insufficient room for add-on ({remaining_room_pct:.1f}% remaining)")
                continue

        position_dollars = portfolio_value * (position_pct / 100)
        current_price = data['close']

        quantity = int(position_dollars / current_price)

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
            'rotation_mult': rotation_mult,
            'is_addon': is_addon,
            'existing_exposure_pct': current_exposure['exposure_pct'],
            'existing_quantity': current_exposure['quantity']
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
            if scaled_qty > 0:
                alloc['quantity'] = scaled_qty
                alloc['cost'] = scaled_qty * alloc['price']
                alloc['pct_portfolio'] = (alloc['cost'] / portfolio_value * 100)
                scaled.append(alloc)

        allocations = scaled

    return allocations


# =============================================================================
# PORTFOLIO CONTEXT
# =============================================================================

def create_portfolio_context(strategy):
    """Create portfolio context dict with accurate cash tracking"""
    import account_broker_data

    portfolio_value = strategy.portfolio_value
    existing_positions = len(strategy.get_positions())

    # Use tracked cash for backtesting, Alpaca for live
    if Config.BACKTESTING and _backtest_cash_tracker['initialized']:
        cash_balance = _backtest_cash_tracker['cash']
    else:
        cash_balance = account_broker_data.get_cash_balance(strategy)

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


def calculate_pending_exit_proceeds(exit_orders):
    """
    Calculate expected cash proceeds from exit orders that haven't settled yet.
    Fixes negative cash in backtesting where sell orders don't immediately update cash.
    """
    if not exit_orders:
        return 0.0

    proceeds = 0.0
    for order in exit_orders:
        exit_type = order.get('type', 'full_exit')
        broker_quantity = order.get('broker_quantity', 0)
        current_price = order.get('current_price', 0)
        sell_pct = order.get('sell_pct', 100)

        if exit_type in ['tier1_exit', 'tier2_exit']:
            sell_qty = int(broker_quantity * (sell_pct / 100))
        else:
            sell_qty = broker_quantity

        proceeds += sell_qty * current_price

    return proceeds
