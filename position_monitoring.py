"""
Position Monitoring System - Modular Exit Strategies

Architecture:
- Separate functions for each exit type (emergency, profit-taking, trailing)
- Easy to modify individual strategies
- Clean separation of concerns
- Easy to add new exit strategies

Exit Priority Order:
1. Emergency stops (highest priority)
2. Profit taking (two levels: 80/20 rule)
3. Trailing stops
"""

from datetime import datetime


# =============================================================================
# CONFIGURATION - 80/20 Rule Exit Strategy
# =============================================================================

class ExitConfig:
    """
    Centralized configuration for all exit strategies

    80/20 Rule: Take 80% off at two levels, let 20% run with tight trail
    - Locks in 80% of gains quickly (high win rate, fast capital rotation)
    - Keeps 20% for monster moves (captures occasional big winners)
    - Optimized for swing trading (3-15 day holds)
    """

    # Emergency Stop Settings
    EMERGENCY_STOP_PCT = -5.0  # Quick exit on losers (tight for swing trading)

    # Profit Taking Settings - 80/20 Rule
    PROFIT_TARGET_1_PCT = 12.0  # First target: +12% gain
    PROFIT_TARGET_1_SELL = 40.0  # Sell 40% at first target

    PROFIT_TARGET_2_PCT = 25.0  # Second target: +25% gain
    PROFIT_TARGET_2_SELL = 40.0  # Sell another 40% at second target

    # Total locked in: 80% by +25%
    # Remaining: 20% trails with tight stop

    # Trailing Stop Settings (for remaining 20%)
    TRAILING_STOP_PCT = 8.0  # Tight trail on remaining 20%


# =============================================================================
# POSITION METADATA TRACKER
# =============================================================================

class PositionMonitor:
    """Tracks position metadata for exit monitoring"""

    def __init__(self, strategy):
        self.strategy = strategy
        self.positions_metadata = {}  # {ticker: {...metadata...}}

    def track_position(self, ticker, entry_price, entry_date):
        """
        Record position metadata for monitoring
        Also migrates old metadata to new structure if needed
        """
        if ticker not in self.positions_metadata:
            # Create new metadata with all required keys
            self.positions_metadata[ticker] = {
                'entry_price': entry_price,
                'entry_date': entry_date,
                'highest_price': entry_price,
                'profit_level_1_locked': False,  # Hit first profit target (+12%)
                'profit_level_2_locked': False,  # Hit second profit target (+25%)
                'remaining_pct': 100.0  # % of position still held
            }
        else:
            # Metadata exists - ensure it has all new keys (migration)
            existing = self.positions_metadata[ticker]
            if 'profit_level_1_locked' not in existing:
                existing['profit_level_1_locked'] = False
            if 'profit_level_2_locked' not in existing:
                existing['profit_level_2_locked'] = False
            if 'remaining_pct' not in existing:
                existing['remaining_pct'] = 100.0
            if 'highest_price' not in existing:
                existing['highest_price'] = entry_price

    def update_highest_price(self, ticker, current_price):
        """Update highest price for trailing stop calculations"""
        if ticker in self.positions_metadata:
            self.positions_metadata[ticker]['highest_price'] = max(
                self.positions_metadata[ticker]['highest_price'],
                current_price
            )

    def mark_profit_level_1_locked(self, ticker, remaining_pct):
        """Mark that we took profit at level 1 (sold 40%)"""
        if ticker in self.positions_metadata:
            self.positions_metadata[ticker]['profit_level_1_locked'] = True
            self.positions_metadata[ticker]['remaining_pct'] = remaining_pct

    def mark_profit_level_2_locked(self, ticker, remaining_pct):
        """Mark that we took profit at level 2 (sold another 40%)"""
        if ticker in self.positions_metadata:
            self.positions_metadata[ticker]['profit_level_2_locked'] = True
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

def check_emergency_stop(pnl_pct, current_price, entry_price, stop_pct=-5.0):
    """
    Emergency stop loss - exits entire position at fixed loss percentage

    Args:
        pnl_pct: Current profit/loss percentage
        current_price: Current stock price
        entry_price: Entry price
        stop_pct: Stop loss percentage (default -5%)

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


def check_profit_taking_80_20(pnl_pct, profit_level_1_locked, profit_level_2_locked):
    """
    80/20 Rule Profit Taking - Two profit levels

    Level 1: Sell 40% at +12%
    Level 2: Sell 40% at +25%
    Remaining 20% trails with tight stop

    Args:
        pnl_pct: Current profit/loss percentage
        profit_level_1_locked: Whether we've already taken level 1 profit
        profit_level_2_locked: Whether we've already taken level 2 profit

    Returns:
        dict with exit signal or None
    """
    # Level 1: First profit target (+12%)
    if not profit_level_1_locked and pnl_pct >= ExitConfig.PROFIT_TARGET_1_PCT:
        remaining_pct = 100.0 - ExitConfig.PROFIT_TARGET_1_SELL
        return {
            'type': 'partial_exit',
            'reason': 'profit_level_1',
            'sell_pct': ExitConfig.PROFIT_TARGET_1_SELL,
            'profit_level': 1,
            'message': f'💰 Level 1 Profit +{ExitConfig.PROFIT_TARGET_1_PCT:.0f}%: Selling {ExitConfig.PROFIT_TARGET_1_SELL:.0f}%, keeping {remaining_pct:.0f}%'
        }

    # Level 2: Second profit target (+25%)
    if profit_level_1_locked and not profit_level_2_locked and pnl_pct >= ExitConfig.PROFIT_TARGET_2_PCT:
        remaining_pct = 100.0 - ExitConfig.PROFIT_TARGET_1_SELL - ExitConfig.PROFIT_TARGET_2_SELL
        return {
            'type': 'partial_exit',
            'reason': 'profit_level_2',
            'sell_pct': ExitConfig.PROFIT_TARGET_2_SELL,
            'profit_level': 2,
            'message': f'💰 Level 2 Profit +{ExitConfig.PROFIT_TARGET_2_PCT:.0f}%: Selling {ExitConfig.PROFIT_TARGET_2_SELL:.0f}%, trailing {remaining_pct:.0f}%'
        }

    return None


def check_trailing_stop(profit_level_2_locked, highest_price, current_price, trail_pct=8.0):
    """
    Trailing stop - exits remaining position if drops from peak

    Only activates after BOTH profit levels are locked (remaining 20%)

    Args:
        profit_level_2_locked: Whether both profit levels were taken
        highest_price: Highest price since entry
        current_price: Current stock price
        trail_pct: Trailing stop percentage from peak (default 8%)

    Returns:
        dict with exit signal or None
    """
    if not profit_level_2_locked:
        return None  # Only trail after both profit levels taken

    drawdown_from_peak = ((current_price - highest_price) / highest_price * 100)

    if drawdown_from_peak <= -trail_pct:
        return {
            'type': 'full_exit',
            'reason': 'trailing_stop',
            'sell_pct': 100.0,
            'message': f'📉 Trailing Stop ({trail_pct}% from peak ${highest_price:.2f}): Exiting remaining 20%'
        }
    return None


# =============================================================================
# MAIN COORDINATOR FUNCTIONS
# =============================================================================

def check_positions_for_exits(strategy, current_date, all_stock_data, position_monitor):
    """
    Check all positions for exit conditions using 80/20 rule

    Exit Priority Order:
    1. Emergency stops (highest priority - protect capital)
    2. Profit taking level 1 (+12%, sell 40%)
    3. Profit taking level 2 (+25%, sell 40%)
    4. Trailing stops (8% from peak on remaining 20%)

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

        # 2. Profit taking (80/20 rule - two levels)
        if not exit_signal:
            exit_signal = check_profit_taking_80_20(
                pnl_pct=pnl_pct,
                profit_level_1_locked=metadata.get('profit_level_1_locked', False),
                profit_level_2_locked=metadata.get('profit_level_2_locked', False)
            )

        # 3. Trailing stop (only on remaining 20%)
        if not exit_signal:
            exit_signal = check_trailing_stop(
                profit_level_2_locked=metadata.get('profit_level_2_locked', False),
                highest_price=metadata.get('highest_price', entry_price),
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

        # === PARTIAL EXIT (Profit Taking Level 1 or 2) ===
        if exit_type == 'partial_exit':
            profit_level = order.get('profit_level', 0)

            print(f"\n{'=' * 60}")
            print(f"💰 PROFIT TAKING LEVEL {profit_level} - {ticker}")
            print(f"{'=' * 60}")
            print(f"Selling: {sell_quantity} of {total_quantity} shares ({sell_pct:.0f}%)")
            print(f"Reason:  {message}")
            print(f"Remaining: {total_quantity - sell_quantity} shares")
            print(f"P&L: ${order['pnl_dollars']:,.2f} ({order['pnl_pct']:+.1f}%)")
            print(f"{'=' * 60}\n")

            # Mark which profit level was locked
            remaining_pct = 100.0 - sell_pct
            if profit_level == 1:
                position_monitor.mark_profit_level_1_locked(ticker, remaining_pct)
            elif profit_level == 2:
                position_monitor.mark_profit_level_2_locked(ticker, remaining_pct)

            # Record partial exit in profit tracking
            position_tracking.record_partial_exit(
                ticker=ticker,
                sell_quantity=sell_quantity,
                exit_price=current_price,
                exit_date=current_date,
                exit_signal={'msg': message, 'signal_type': reason}
            )

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
            position_tracking.close_position(
                ticker=ticker,
                exit_price=current_price,
                exit_date=current_date,
                exit_signal={'msg': message, 'signal_type': reason},
                quantity_sold=sell_quantity
            )

            # Clean up metadata
            position_monitor.clean_position_metadata(ticker)

            # Create and submit sell order
            sell_order = strategy.create_order(ticker, sell_quantity, 'sell')
            print(f" * EXIT ORDER: {ticker} x{sell_quantity} | {message}")
            strategy.submit_order(sell_order)