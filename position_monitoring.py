"""
Position Monitoring System - Modular Exit Strategies

Architecture:
- Separate functions for each exit type (emergency, profit-taking, trailing)
- Easy to modify individual strategies
- Clean separation of concerns
- Easy to add new exit strategies

Exit Priority Order:
1. Emergency stops (highest priority)
2. Profit taking
3. Trailing stops
"""

from datetime import datetime


# =============================================================================
# CONFIGURATION - Easy to Modify Exit Strategy Parameters
# =============================================================================

class ExitConfig:
    """Centralized configuration for all exit strategies"""

    # Emergency Stop Settings
    EMERGENCY_STOP_PCT = -10.0  # Stop out at -10% loss

    # Profit Taking Settings
    PROFIT_TARGET_PCT = 33.0  # Take profit at +33%
    PROFIT_SELL_PCT = 75.0  # Sell 75% at profit target

    # Trailing Stop Settings
    TRAILING_STOP_PCT = 15.0  # Trail remaining position by 15%


# =============================================================================
# POSITION METADATA TRACKER
# =============================================================================

class PositionMonitor:
    """Tracks position metadata for exit monitoring"""

    def __init__(self, strategy):
        self.strategy = strategy
        self.positions_metadata = {}  # {ticker: {...metadata...}}

    def track_position(self, ticker, entry_price, entry_date):
        """Record position metadata for monitoring"""
        if ticker not in self.positions_metadata:
            self.positions_metadata[ticker] = {
                'entry_price': entry_price,
                'entry_date': entry_date,
                'highest_price': entry_price,
                'profit_locked': False,  # Tracks if we hit profit target and sold partial
                'remaining_pct': 100.0  # % of position still held
            }

    def update_highest_price(self, ticker, current_price):
        """Update highest price for trailing stop calculations"""
        if ticker in self.positions_metadata:
            self.positions_metadata[ticker]['highest_price'] = max(
                self.positions_metadata[ticker]['highest_price'],
                current_price
            )

    def mark_profit_locked(self, ticker, remaining_pct):
        """Mark that we took profit and are trailing the remainder"""
        if ticker in self.positions_metadata:
            self.positions_metadata[ticker]['profit_locked'] = True
            self.positions_metadata[ticker]['remaining_pct'] = remaining_pct

    def clean_position_metadata(self, ticker):
        """Remove metadata when position is fully closed"""
        if ticker in self.positions_metadata:
            del self.positions_metadata[ticker]

    def get_position_metadata(self, ticker):
        """Get metadata for a ticker"""
        return self.positions_metadata.get(ticker, None)


# =============================================================================
# EXIT STRATEGY FUNCTIONS (Modular - Easy to Modify)
# =============================================================================

def check_emergency_stop(pnl_pct, current_price, entry_price, stop_pct=-10.0):
    """
    Emergency stop loss - exits entire position at fixed loss percentage

    Args:
        pnl_pct: Current profit/loss percentage
        current_price: Current stock price
        entry_price: Entry price
        stop_pct: Stop loss percentage (default -10%)

    Returns:
        dict with exit signal or None
    """
    if pnl_pct <= stop_pct:
        return {
            'type': 'full_exit',
            'reason': 'emergency_stop',
            'sell_pct': 100.0,
            'message': f'🛑 Emergency Stop {stop_pct}%: ${current_price:.2f} (entry: ${entry_price:.2f})'
        }
    return None


def check_profit_taking(pnl_pct, profit_locked, profit_target=33.0, profit_sell_pct=75.0):
    """
    Profit taking strategy - sells portion at profit target to recover capital

    Args:
        pnl_pct: Current profit/loss percentage
        profit_locked: Whether we've already taken profit
        profit_target: Profit % to trigger taking (default 33%)
        profit_sell_pct: % of position to sell (default 75%)

    Returns:
        dict with exit signal or None
    """
    if not profit_locked and pnl_pct >= profit_target:
        remaining_pct = 100.0 - profit_sell_pct
        return {
            'type': 'partial_exit',
            'reason': 'profit_taking',
            'sell_pct': profit_sell_pct,
            'message': f'💰 Profit Taking +{profit_target}%: Selling {profit_sell_pct}%, trailing {remaining_pct}%'
        }
    return None


def check_trailing_stop(profit_locked, highest_price, current_price, trail_pct=15.0):
    """
    Trailing stop - exits remaining position if drops from peak

    Args:
        profit_locked: Whether profit was already taken (trailing only after profit-taking)
        highest_price: Highest price since entry
        current_price: Current stock price
        trail_pct: Trailing stop percentage from peak (default 15%)

    Returns:
        dict with exit signal or None
    """
    if not profit_locked:
        return None  # Only trail after profit-taking

    drawdown_from_peak = ((current_price - highest_price) / highest_price * 100)

    if drawdown_from_peak <= -trail_pct:
        return {
            'type': 'full_exit',
            'reason': 'trailing_stop',
            'sell_pct': 100.0,
            'message': f'📉 Trailing Stop ({trail_pct}% from peak ${highest_price:.2f}): Exiting remaining position'
        }
    return None


# =============================================================================
# MAIN COORDINATOR FUNCTIONS
# =============================================================================

def check_positions_for_exits(strategy, current_date, all_stock_data, position_monitor):
    """
    Check all positions for exit conditions using modular exit strategies

    Exit Priority Order:
    1. Emergency stops (highest priority - protect capital)
    2. Profit taking (lock in gains)
    3. Trailing stops (protect profits)

    Args:
        strategy: Strategy instance
        current_date: Current date
        all_stock_data: Dict of stock data
        position_monitor: PositionMonitor instance

    Returns:
        List of exit order dicts
    """
    exit_orders = []

    positions = strategy.get_positions()
    if not positions:
        return exit_orders

    for position in positions:
        ticker = position.symbol
        quantity = int(position.quantity)
        entry_price = float(position.avg_fill_price)

        if ticker not in all_stock_data:
            continue

        data = all_stock_data[ticker]['indicators']
        current_price = data.get('close', 0)

        if current_price <= 0:
            continue

        # Ensure position is tracked
        metadata = position_monitor.get_position_metadata(ticker)
        if not metadata:
            position_monitor.track_position(ticker, entry_price, current_date)
            metadata = position_monitor.get_position_metadata(ticker)

        # Update highest price for trailing
        position_monitor.update_highest_price(ticker, current_price)

        # Calculate P&L
        pnl_pct = ((current_price - entry_price) / entry_price * 100)
        pnl_dollars = (current_price - entry_price) * quantity

        # === CHECK EXIT CONDITIONS (Priority Order) ===
        exit_signal = None

        # 1. Emergency stop (highest priority)
        exit_signal = check_emergency_stop(
            pnl_pct=pnl_pct,
            current_price=current_price,
            entry_price=entry_price,
            stop_pct=ExitConfig.EMERGENCY_STOP_PCT
        )

        # 2. Profit taking (if no emergency)
        if not exit_signal:
            exit_signal = check_profit_taking(
                pnl_pct=pnl_pct,
                profit_locked=metadata['profit_locked'],
                profit_target=ExitConfig.PROFIT_TARGET_PCT,
                profit_sell_pct=ExitConfig.PROFIT_SELL_PCT
            )

        # 3. Trailing stop (if no emergency or profit-taking)
        if not exit_signal:
            exit_signal = check_trailing_stop(
                profit_locked=metadata['profit_locked'],
                highest_price=metadata['highest_price'],
                current_price=current_price,
                trail_pct=ExitConfig.TRAILING_STOP_PCT
            )

        # Add to exit orders if signal found
        if exit_signal:
            exit_signal['ticker'] = ticker
            exit_signal['quantity'] = quantity
            exit_signal['pnl_dollars'] = pnl_dollars
            exit_signal['pnl_pct'] = pnl_pct
            exit_orders.append(exit_signal)

    return exit_orders


def execute_exit_orders(strategy, exit_orders, current_date, all_stock_data, position_tracking, position_monitor):
    """
    Execute exit orders and handle all tracking/cleanup

    Args:
        strategy: Strategy instance
        exit_orders: List of exit order dicts from check_positions_for_exits()
        current_date: Current date
        all_stock_data: Stock data dict
        position_tracking: ProfitTracker instance
        position_monitor: PositionMonitor instance
    """

    for order in exit_orders:
        ticker = order['ticker']
        exit_type = order['type']
        sell_pct = order['sell_pct']
        reason = order['reason']
        message = order['message']

        position = strategy.get_position(ticker)
        if not position:
            continue

        current_price = all_stock_data[ticker]['indicators'].get('close', 0)

        # Calculate quantity to sell
        total_quantity = int(position.quantity)
        sell_quantity = int(total_quantity * (sell_pct / 100))

        if sell_quantity <= 0:
            continue

        # === PARTIAL EXIT (Profit Taking) ===
        if exit_type == 'partial_exit':
            print(f"\n{'=' * 60}")
            print(f"📊 PARTIAL EXIT - {ticker}")
            print(f"{'=' * 60}")
            print(f"Selling: {sell_quantity} of {total_quantity} shares")
            print(f"Reason:  {message}")
            print(f"Remaining: {total_quantity - sell_quantity} shares")
            print(f"{'=' * 60}\n")

            # Mark that we've locked profit
            remaining_pct = 100.0 - sell_pct
            position_monitor.mark_profit_locked(ticker, remaining_pct)

            # Create and submit sell order
            sell_order = strategy.create_order(ticker, sell_quantity, 'sell')
            print(f" * EXIT ORDER: {ticker} x{sell_quantity} | {message}")
            strategy.submit_order(sell_order)

        # === FULL EXIT (Emergency or Trailing Stop) ===
        elif exit_type == 'full_exit':
            print(f"\n{'=' * 60}")
            print(f"🚪 FULL EXIT - {ticker}")
            print(f"{'=' * 60}")
            print(f"Selling: {sell_quantity} shares")
            print(f"Reason:  {message}")
            print(f"P&L: ${order['pnl_dollars']:,.2f} ({order['pnl_pct']:+.1f}%)")
            print(f"{'=' * 60}\n")

            # Record realized P&L
            position_tracking.close_position(ticker, current_price, current_date, {'msg': message})

            # Clean up metadata
            position_monitor.clean_position_metadata(ticker)

            # Create and submit sell order
            sell_order = strategy.create_order(ticker, sell_quantity, 'sell')
            print(f" * EXIT ORDER: {ticker} x{sell_quantity} | {message}")
            strategy.submit_order(sell_order)