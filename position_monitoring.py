"""
Position Monitoring System
Monitors open positions for exits, profit-taking, and emergency conditions
"""
import stops


class PositionMonitor:
    """
    Active monitoring of positions with multiple exit strategies:
    - Stop losses (ATR-based and hard stops)
    - Trailing stops (percentage and ATR-based)
    - Gradual profit taking (scale out at targets)
    - Emergency exits (circuit breakers)
    """

    def __init__(self, strategy):
        """
        Initialize position monitor

        Args:
            strategy: Lumibot Strategy object
        """
        self.strategy = strategy
        self.position_metadata = {}  # Track highest prices, entry dates, etc.

    def check_all_positions(self, current_date, all_stock_data):
        """
        Check all open positions for exit conditions

        Args:
            current_date: Current datetime
            all_stock_data: Dict of {ticker: {'indicators': {...}, 'raw': DataFrame}}

        Returns:
            list: List of exit orders to execute
        """
        exit_orders = []
        positions = self.strategy.get_positions()

        for position in positions:
            ticker = position.symbol

            # Skip if no data available
            if ticker not in all_stock_data:
                continue

            # Get position details
            quantity = int(position.quantity)
            entry_price = float(position.avg_fill_price)
            current_price = all_stock_data[ticker]['indicators']['close']

            # Initialize metadata for new positions
            if ticker not in self.position_metadata:
                self.position_metadata[ticker] = {
                    'highest_price': current_price,
                    'entry_date': current_date,
                    'partial_exits': 0,
                    'original_quantity': quantity
                }

            # Update highest price for trailing stop
            if current_price > self.position_metadata[ticker]['highest_price']:
                self.position_metadata[ticker]['highest_price'] = current_price

            # Get stock indicators
            data = all_stock_data[ticker]['indicators']

            # Calculate current P&L
            pnl_pct = ((current_price - entry_price) / entry_price) * 100

            # === EXIT CHECKS (in priority order) ===

            # 1. EMERGENCY EXITS (highest priority)
            emergency_exit = self._check_emergency_exits(
                ticker, data, pnl_pct, current_price, entry_price
            )
            if emergency_exit:
                exit_orders.append(emergency_exit)
                continue

            # 2. STOP LOSS CHECKS
            stop_loss_exit = self._check_stop_losses(
                ticker, quantity, entry_price, current_price, data
            )
            if stop_loss_exit:
                exit_orders.append(stop_loss_exit)
                continue

            # 3. TRAILING STOP CHECK
            trailing_exit = self._check_trailing_stops(
                ticker, quantity, entry_price, current_price, data, pnl_pct
            )
            if trailing_exit:
                exit_orders.append(trailing_exit)
                continue

            # 4. GRADUAL PROFIT TAKING (partial exits)
            profit_taking_exit = self._check_profit_taking(
                ticker, quantity, entry_price, current_price, pnl_pct
            )
            if profit_taking_exit:
                exit_orders.append(profit_taking_exit)
                # Note: Don't continue - can still be in position after partial exit

        return exit_orders

    def _check_emergency_exits(self, ticker, data, pnl_pct, current_price, entry_price):
        """
        Emergency circuit breakers - exit immediately

        Triggers:
        - Catastrophic loss (> -20% in one day)
        - Extreme volatility spike
        - Flash crash detection
        """
        daily_change = data.get('daily_change_pct', 0)
        atr_pct = (data.get('atr_14', 0) / current_price * 100) if current_price > 0 else 0

        # EMERGENCY 1: Catastrophic single-day loss
        if daily_change < -20.0:
            return {
                'ticker': ticker,
                'quantity': 'all',  # Sell entire position
                'side': 'sell',
                'reason': f'🚨 EMERGENCY: Catastrophic drop {daily_change:.1f}%',
                'exit_type': 'emergency_crash'
            }

        # EMERGENCY 2: Extreme volatility spike (ATR > 20% of price)
        if atr_pct > 20.0 and pnl_pct < -10.0:
            return {
                'ticker': ticker,
                'quantity': 'all',
                'side': 'sell',
                'reason': f'🚨 EMERGENCY: Extreme volatility ATR={atr_pct:.1f}% + loss',
                'exit_type': 'emergency_volatility'
            }

        # EMERGENCY 3: Major loss threshold (position down >30%)
        if pnl_pct < -30.0:
            return {
                'ticker': ticker,
                'quantity': 'all',
                'side': 'sell',
                'reason': f'🚨 EMERGENCY: Major loss {pnl_pct:.1f}%',
                'exit_type': 'emergency_major_loss'
            }

        return None

    def _check_stop_losses(self, ticker, quantity, entry_price, current_price, data):
        """
        Check hard and ATR-based stop losses

        Uses stops.py functions for calculations
        """
        # Calculate ATR stop loss
        atr_stop = stops.stop_loss_atr(data, multiplier=2.0)

        # Calculate hard stop (5% default)
        hard_stop = stops.stop_loss_hard(data, stop_loss_percent=0.05)

        # Use the tighter (higher) stop loss
        stop_price = max(atr_stop['stop_loss'], hard_stop['stop_loss'])

        if current_price <= stop_price:
            stop_pct = ((current_price - entry_price) / entry_price * 100)
            return {
                'ticker': ticker,
                'quantity': quantity,
                'side': 'sell',
                'reason': f'Stop Loss Hit: {stop_pct:.1f}% (${stop_price:.2f})',
                'exit_type': 'stop_loss'
            }

        return None

    def _check_trailing_stops(self, ticker, quantity, entry_price, current_price, data, pnl_pct):
        """
        Check trailing stops - only activate when in profit

        Uses both percentage-based and ATR-based trailing
        """
        # Only use trailing stops when position is profitable
        if pnl_pct <= 0:
            return None

        highest_price = self.position_metadata[ticker]['highest_price']
        atr = data.get('atr_14', 0)

        # PERCENTAGE-BASED TRAILING STOP
        # Adjust trail tightness based on profit level
        if pnl_pct < 25:
            trail_pct = 15.0  # Wide trail for small gains
        elif pnl_pct < 50:
            trail_pct = 12.0  # Medium trail
        elif pnl_pct < 100:
            trail_pct = 10.0  # Tighter trail
        else:
            trail_pct = 8.0  # Very tight for massive gains

        pct_trailing_stop = highest_price * (1 - trail_pct / 100)

        # ATR-BASED TRAILING STOP (adaptive to volatility)
        atr_trailing_stop = highest_price - (atr * 2.5)

        # Use the tighter (higher) trailing stop
        trailing_stop = max(pct_trailing_stop, atr_trailing_stop)

        if current_price <= trailing_stop:
            drawdown_from_peak = ((current_price - highest_price) / highest_price * 100)
            return {
                'ticker': ticker,
                'quantity': quantity,
                'side': 'sell',
                'reason': f'Trailing Stop: {drawdown_from_peak:.1f}% from peak (P&L: {pnl_pct:.1f}%)',
                'exit_type': 'trailing_stop'
            }

        return None

    def _check_profit_taking(self, ticker, quantity, entry_price, current_price, pnl_pct):
        """
        Gradual profit taking - scale out at key levels

        Strategy:
        - 25% at +30% gain
        - 25% at +60% gain  (50% total sold)
        - 25% at +100% gain (75% total sold)
        - Let remaining 25% run with trailing stop
        """
        partial_exits = self.position_metadata[ticker]['partial_exits']
        original_qty = self.position_metadata[ticker]['original_quantity']

        # Calculate how much to sell (25% of original position)
        scale_out_qty = max(1, int(original_qty * 0.25))

        # LEVEL 1: Take 25% at +30%
        if pnl_pct >= 30.0 and partial_exits == 0:
            self.position_metadata[ticker]['partial_exits'] = 1
            return {
                'ticker': ticker,
                'quantity': scale_out_qty,
                'side': 'sell',
                'reason': f'💰 Profit Taking 1/4: +{pnl_pct:.1f}% (lock gains)',
                'exit_type': 'profit_scale_1'
            }

        # LEVEL 2: Take 25% at +60%
        if pnl_pct >= 60.0 and partial_exits == 1:
            self.position_metadata[ticker]['partial_exits'] = 2
            return {
                'ticker': ticker,
                'quantity': scale_out_qty,
                'side': 'sell',
                'reason': f'💰 Profit Taking 2/4: +{pnl_pct:.1f}% (lock more)',
                'exit_type': 'profit_scale_2'
            }

        # LEVEL 3: Take 25% at +100%
        if pnl_pct >= 100.0 and partial_exits == 2:
            self.position_metadata[ticker]['partial_exits'] = 3
            return {
                'ticker': ticker,
                'quantity': scale_out_qty,
                'side': 'sell',
                'reason': f'💰 Profit Taking 3/4: +{pnl_pct:.1f}% (secure double)',
                'exit_type': 'profit_scale_3'
            }

        # LEVEL 4: Take another 25% at +200% (optional aggressive scaling)
        if pnl_pct >= 200.0 and partial_exits == 3:
            self.position_metadata[ticker]['partial_exits'] = 4
            # At this point, we've sold 100% in quarters
            # Let final portion run or could add more levels
            return {
                'ticker': ticker,
                'quantity': scale_out_qty,
                'side': 'sell',
                'reason': f'💰 Profit Taking 4/4: +{pnl_pct:.1f}% (triple!)',
                'exit_type': 'profit_scale_4'
            }

        return None

    def clean_position_metadata(self, ticker):
        """Remove metadata when position is fully closed"""
        if ticker in self.position_metadata:
            del self.position_metadata[ticker]

    def get_position_stats(self, ticker):
        """Get position metadata for reporting"""
        return self.position_metadata.get(ticker, {})


def check_positions_for_exits(strategy, current_date, all_stock_data, position_monitor):
    """
    Check all positions and return list of exit orders (pure function)

    This function has NO side effects - it only calculates and returns exit decisions.

    Args:
        strategy: Lumibot Strategy object
        current_date: Current datetime
        all_stock_data: Dict of stock data with indicators
        position_monitor: PositionMonitor instance

    Returns:
        list: Exit orders to execute, each order is a dict with:
            - ticker: str
            - quantity: int or 'all'
            - side: 'sell'
            - reason: str (explanation)
            - exit_type: str (emergency_crash, stop_loss, etc.)
    """
    return position_monitor.check_all_positions(current_date, all_stock_data)


def execute_exit_orders(strategy, exit_orders, current_date, all_stock_data,
                        position_tracking, position_monitor):
    """
    Execute all exit orders and handle tracking/cleanup (side effects)

    This function handles:
    - Converting 'all' quantities to actual share counts
    - Recording realized P&L for closed positions
    - Cleaning up monitoring metadata
    - Submitting orders to broker
    - Logging exit information

    Args:
        strategy: Lumibot Strategy object (for get_position, submit_order, etc.)
        exit_orders: List of exit order dicts from check_positions_for_exits()
        current_date: Current datetime
        all_stock_data: Dict of stock data with indicators
        position_tracking: ProfitTracker instance
        position_monitor: PositionMonitor instance
    """
    if not exit_orders:
        return

    for exit_order in exit_orders:
        ticker = exit_order['ticker']

        # Get current position
        position = strategy.get_position(ticker)
        if not position:
            print(f"[WARNING] Exit order for {ticker} but no position found")
            continue

        # Handle 'all' quantity (sell entire position)
        if exit_order['quantity'] == 'all':
            quantity = int(position.quantity)
        else:
            quantity = exit_order['quantity']

        # Validate quantity
        if quantity <= 0 or quantity > position.quantity:
            print(f"[WARNING] Invalid exit quantity for {ticker}: {quantity}")
            continue

        # Determine if this closes the entire position
        is_full_exit = (quantity == position.quantity)

        # Record realized P&L if closing entire position
        if is_full_exit:
            exit_price = all_stock_data[ticker]['indicators']['close']
            position_tracking.close_position(
                ticker,
                exit_price,
                current_date,
                {
                    'msg': exit_order['reason'],
                    'signal_type': exit_order['exit_type']
                }
            )
            # Clean up monitoring metadata when position fully closed
            position_monitor.clean_position_metadata(ticker)
        else:
            # Partial exit - just log it
            print(f"\n{'=' * 60}")
            print(f"📊 PARTIAL EXIT - {ticker}")
            print(f"{'=' * 60}")
            print(f"Selling: {quantity} of {position.quantity} shares")
            print(f"Reason:  {exit_order['reason']}")
            print(f"Remaining: {position.quantity - quantity} shares")
            print(f"{'=' * 60}\n")

        # Submit exit order to broker
        order = strategy.create_order(ticker, quantity, 'sell')
        print(f" * EXIT ORDER: {ticker} x{quantity} | {exit_order['reason']}")
        strategy.submit_order(order)