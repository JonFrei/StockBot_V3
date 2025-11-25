"""
Position Monitoring - UPDATED VERSION

FIXES APPLIED:
1. ATR-based stop loss (replaces fixed -5.5% emergency stop)
2. Level 0 trailing stop (protects gains before +10% target)
3. Remnant position cleanup (auto-close small positions after partial exits)
"""

import stock_indicators


class ExitConfig:
    """Universal exit parameters"""
    # ATR-based stop loss (replaces fixed emergency stop)
    ATR_STOP_MULTIPLIER = 2.0
    ATR_STOP_MIN_PCT = 3.0
    ATR_STOP_MAX_PCT = 8.0
    FALLBACK_EMERGENCY_STOP = -5.5  # Used if ATR unavailable

    # Level 0 trailing (protects unrealized gains before profit target)
    LEVEL_0_TRAIL_ACTIVATION = 3.0  # Activate after +3% gain
    LEVEL_0_TRAIL_PCT = 8.0  # 8% trailing from peak

    PROFIT_TARGET_1 = 10.0
    PROFIT_TARGET_1_SELL = 33.0

    PROFIT_TARGET_2 = 20.0
    PROFIT_TARGET_2_SELL = 33.0

    PROFIT_TARGET_3 = 30.0
    PROFIT_TARGET_3_SELL = 50.0

    TRAILING_STOP_LEVEL_1 = 6.0
    TRAILING_STOP_LEVEL_2 = 7.5
    TRAILING_STOP_LEVEL_3 = 10.0

    # Remnant position cleanup
    MIN_REMNANT_SHARES = 10
    MIN_REMNANT_VALUE = 500.0  # dollars


class PositionMonitor:
    """Tracks position metadata"""

    def __init__(self, strategy):
        self.strategy = strategy
        self.positions_metadata = {}

    def track_position(self, ticker, entry_date, entry_signal='unknown', entry_score=0):
        """Record position metadata"""
        if ticker not in self.positions_metadata:
            current_price = self._get_current_price(ticker)

            self.positions_metadata[ticker] = {
                'entry_date': entry_date,
                'entry_signal': entry_signal,
                'entry_score': entry_score,
                'local_max': current_price,
                'last_peak_date': entry_date,
                'profit_level': 0,
                'level_1_lock_price': None,
                'level_2_lock_price': None,
            }

    def update_local_max(self, ticker, current_price):
        """Update local maximum"""
        if ticker in self.positions_metadata:
            old_max = self.positions_metadata[ticker]['local_max']
            if current_price > old_max:
                self.positions_metadata[ticker]['local_max'] = current_price
                try:
                    self.positions_metadata[ticker]['last_peak_date'] = self.strategy.get_datetime()
                except:
                    pass

    def advance_profit_level(self, ticker, level, lock_price):
        """Advance to next profit level"""
        if ticker in self.positions_metadata:
            self.positions_metadata[ticker]['profit_level'] = level
            if level == 1:
                self.positions_metadata[ticker]['level_1_lock_price'] = lock_price
            elif level == 2:
                self.positions_metadata[ticker]['level_2_lock_price'] = lock_price

    def clean_position_metadata(self, ticker):
        """Remove metadata when position closed"""
        if ticker in self.positions_metadata:
            del self.positions_metadata[ticker]

    def get_position_metadata(self, ticker):
        """Get metadata for ticker"""
        return self.positions_metadata.get(ticker, None)

    def _get_current_price(self, ticker):
        """Get current price"""
        try:
            return self.strategy.get_last_price(ticker)
        except:
            return 0


# =============================================================================
# EXIT CHECKS
# =============================================================================

def calculate_atr_stop_pct(atr, current_price):
    """
    Calculate ATR-based stop loss percentage

    Args:
        atr: Average True Range value
        current_price: Current stock price

    Returns:
        float: Stop loss percentage (negative, e.g., -5.0)
    """
    if not atr or atr <= 0 or current_price <= 0:
        return ExitConfig.FALLBACK_EMERGENCY_STOP

    # ATR as percentage of price
    atr_pct = (atr / current_price) * 100

    # Apply multiplier
    stop_pct = atr_pct * ExitConfig.ATR_STOP_MULTIPLIER

    # Clamp to bounds
    stop_pct = max(ExitConfig.ATR_STOP_MIN_PCT, min(stop_pct, ExitConfig.ATR_STOP_MAX_PCT))

    return -stop_pct  # Return as negative


def check_intraday_stop_breach(low_price, entry_price, stop_threshold):
    """Check if intraday low breached stop"""
    stop_price = entry_price * (1 + stop_threshold / 100)
    if low_price <= stop_price:
        return {
            'type': 'full_exit',
            'reason': 'intraday_stop',
            'sell_pct': 100.0,
            'message': f'Intraday stop @ ${stop_price:.2f}'
        }
    return None


def check_atr_emergency_stop(pnl_pct, current_price, entry_price, atr=None):
    """
    ATR-based emergency stop (replaces fixed -5.5%)

    Args:
        pnl_pct: Current P&L percentage
        current_price: Current price
        entry_price: Entry price
        atr: ATR value (optional, falls back to fixed stop)
    """
    stop_threshold = calculate_atr_stop_pct(atr, current_price)

    if pnl_pct <= stop_threshold:
        return {
            'type': 'full_exit',
            'reason': 'atr_stop' if atr else 'emergency_stop',
            'sell_pct': 100.0,
            'message': f'ATR stop {pnl_pct:.1f}% (threshold: {stop_threshold:.1f}%)'
        }
    return None


def check_level_0_trailing_stop(pnl_pct, local_max, current_price, entry_price):
    """
    Level 0 trailing stop - protects gains before hitting +10% target

    Activates when position reaches +3% gain, then trails at 8% from peak
    """
    # Calculate gain from peak
    peak_gain_pct = ((local_max - entry_price) / entry_price * 100) if entry_price > 0 else 0

    # Only activate if we've reached activation threshold
    if peak_gain_pct < ExitConfig.LEVEL_0_TRAIL_ACTIVATION:
        return None

    # Calculate drawdown from peak
    drawdown_from_peak = ((current_price - local_max) / local_max * 100) if local_max > 0 else 0

    # Check if trailing stop triggered
    if drawdown_from_peak <= -ExitConfig.LEVEL_0_TRAIL_PCT:
        return {
            'type': 'full_exit',
            'reason': 'level_0_trail',
            'sell_pct': 100.0,
            'message': f'L0 trail {ExitConfig.LEVEL_0_TRAIL_PCT}% from ${local_max:.2f} (peak +{peak_gain_pct:.1f}%)'
        }

    return None


def check_profit_taking(pnl_pct, profit_level):
    """Check profit level triggers"""
    if profit_level == 0 and pnl_pct >= ExitConfig.PROFIT_TARGET_1:
        return {
            'type': 'partial_exit',
            'reason': 'profit_level_1',
            'sell_pct': ExitConfig.PROFIT_TARGET_1_SELL,
            'profit_level': 1,
            'message': f'Level 1 @ +{pnl_pct:.1f}%'
        }

    if profit_level == 1 and pnl_pct >= ExitConfig.PROFIT_TARGET_2:
        return {
            'type': 'partial_exit',
            'reason': 'profit_level_2',
            'sell_pct': ExitConfig.PROFIT_TARGET_2_SELL,
            'profit_level': 2,
            'message': f'Level 2 @ +{pnl_pct:.1f}%'
        }

    if profit_level == 2 and pnl_pct >= ExitConfig.PROFIT_TARGET_3:
        remaining = 100 - ExitConfig.PROFIT_TARGET_1_SELL - ExitConfig.PROFIT_TARGET_2_SELL
        sell_amount = remaining * 0.50
        return {
            'type': 'partial_exit',
            'reason': 'profit_level_3',
            'sell_pct': sell_amount,
            'profit_level': 3,
            'message': f'Level 3 @ +{pnl_pct:.1f}%'
        }

    return None


def check_emergency_exit_per_level(profit_level, current_price, entry_price,
                                   level_1_lock_price, level_2_lock_price):
    """Emergency exits per profit level"""
    if profit_level == 1:
        if current_price <= entry_price:
            return {
                'type': 'full_exit',
                'reason': 'emergency_L1',
                'sell_pct': 100.0,
                'message': f'L1 emergency - back to entry'
            }

    if profit_level == 2 and level_1_lock_price:
        if current_price <= level_1_lock_price:
            return {
                'type': 'full_exit',
                'reason': 'emergency_L2',
                'sell_pct': 100.0,
                'message': f'L2 emergency - back to L1'
            }

    if profit_level == 3 and level_2_lock_price:
        if current_price <= level_2_lock_price:
            return {
                'type': 'full_exit',
                'reason': 'emergency_L3',
                'sell_pct': 100.0,
                'message': f'L3 emergency - back to L2'
            }

    return None


def check_trailing_stop(profit_level, local_max, current_price):
    """Progressive trailing stop"""
    if profit_level == 0:
        return None

    trail_pct = {1: ExitConfig.TRAILING_STOP_LEVEL_1,
                 2: ExitConfig.TRAILING_STOP_LEVEL_2,
                 3: ExitConfig.TRAILING_STOP_LEVEL_3}.get(profit_level, 10.0)

    drawdown = ((current_price - local_max) / local_max * 100)

    if drawdown <= -trail_pct:
        return {
            'type': 'full_exit',
            'reason': f'trailing_L{profit_level}',
            'sell_pct': 100.0,
            'message': f'L{profit_level} trail {trail_pct}% from ${local_max:.2f}'
        }

    return None


def check_intraday_trailing_breach(low_price, local_max, profit_level):
    """Intraday trailing breach"""
    if profit_level == 0:
        return None

    trail_pct = {1: ExitConfig.TRAILING_STOP_LEVEL_1,
                 2: ExitConfig.TRAILING_STOP_LEVEL_2,
                 3: ExitConfig.TRAILING_STOP_LEVEL_3}.get(profit_level, 10.0)

    trail_stop_price = local_max * (1 - trail_pct / 100)

    if low_price <= trail_stop_price:
        return {
            'type': 'full_exit',
            'reason': f'intraday_trail_L{profit_level}',
            'sell_pct': 100.0,
            'message': f'Intraday trail L{profit_level}'
        }

    return None


def check_remnant_position(remaining_shares, current_price):
    """
    Check if remaining position is too small after partial exit

    Returns exit signal if position should be fully closed
    """
    remaining_value = remaining_shares * current_price

    if remaining_shares < ExitConfig.MIN_REMNANT_SHARES:
        return {
            'type': 'full_exit',
            'reason': 'remnant_cleanup',
            'sell_pct': 100.0,
            'message': f'Remnant cleanup: {remaining_shares} shares < {ExitConfig.MIN_REMNANT_SHARES} min'
        }

    if remaining_value < ExitConfig.MIN_REMNANT_VALUE:
        return {
            'type': 'full_exit',
            'reason': 'remnant_cleanup',
            'sell_pct': 100.0,
            'message': f'Remnant cleanup: ${remaining_value:.0f} < ${ExitConfig.MIN_REMNANT_VALUE:.0f} min'
        }

    return None


# =============================================================================
# MAIN FUNCTIONS
# =============================================================================

def check_positions_for_exits(strategy, current_date, all_stock_data, position_monitor):
    """Check all positions for exit conditions"""
    import account_broker_data

    exit_orders = []
    positions = strategy.get_positions()

    if not positions:
        return exit_orders

    for position in positions:
        ticker = position.symbol

        broker_entry_price = account_broker_data.get_broker_entry_price(position, strategy, ticker)
        if not account_broker_data.validate_entry_price(broker_entry_price, ticker):
            continue

        broker_quantity = account_broker_data.get_position_quantity(position, ticker)
        if broker_quantity <= 0:
            continue

        if ticker not in all_stock_data:
            continue

        data = all_stock_data[ticker]['indicators']
        current_price = data.get('close', 0)
        if current_price <= 0:
            continue

        # Get ATR for dynamic stop loss
        atr = data.get('atr_14', None)

        # Ensure tracked
        metadata = position_monitor.get_position_metadata(ticker)
        if not metadata:
            position_monitor.track_position(ticker, current_date, 'pre_existing', entry_score=0)
            metadata = position_monitor.get_position_metadata(ticker)

        # Calculate P&L
        pnl_pct = ((current_price - broker_entry_price) / broker_entry_price * 100)
        pnl_dollars = (current_price - broker_entry_price) * broker_quantity

        # Get state
        profit_level = metadata.get('profit_level', 0)
        local_max = metadata.get('local_max', broker_entry_price)
        level_1_lock_price = metadata.get('level_1_lock_price', None)
        level_2_lock_price = metadata.get('level_2_lock_price', None)

        low_price = data.get('low', current_price)

        # Calculate ATR-based stop threshold
        atr_stop_threshold = calculate_atr_stop_pct(atr, current_price)

        # Check exits in priority order
        exit_signal = None

        # Level 0: ATR-based stops
        if profit_level == 0:
            # Intraday ATR stop breach
            exit_signal = check_intraday_stop_breach(
                low_price, broker_entry_price, atr_stop_threshold
            )
            # Close-based ATR stop
            if not exit_signal:
                exit_signal = check_atr_emergency_stop(pnl_pct, current_price, broker_entry_price, atr)
            # Level 0 trailing (protect unrealized gains)
            if not exit_signal:
                exit_signal = check_level_0_trailing_stop(pnl_pct, local_max, current_price, broker_entry_price)

        # Profit taking (highest priority after initial stops)
        if not exit_signal:
            exit_signal = check_profit_taking(pnl_pct, profit_level)

        # Level 1+ exits
        if not exit_signal and profit_level > 0:
            exit_signal = check_emergency_exit_per_level(
                profit_level, current_price, broker_entry_price,
                level_1_lock_price, level_2_lock_price
            )

        if not exit_signal and profit_level > 0:
            exit_signal = check_intraday_trailing_breach(low_price, local_max, profit_level)

        if not exit_signal and profit_level > 0:
            exit_signal = check_trailing_stop(profit_level, local_max, current_price)

        # Update local max if no exit
        if not exit_signal:
            position_monitor.update_local_max(ticker, current_price)

        # Build exit order
        if exit_signal:
            exit_signal['ticker'] = ticker
            exit_signal['broker_quantity'] = broker_quantity
            exit_signal['broker_entry_price'] = broker_entry_price
            exit_signal['current_price'] = current_price
            exit_signal['pnl_dollars'] = pnl_dollars
            exit_signal['pnl_pct'] = pnl_pct
            exit_signal['entry_signal'] = metadata.get('entry_signal', 'pre_existing')
            exit_signal['entry_score'] = metadata.get('entry_score', 0)
            exit_signal['current_profit_level'] = profit_level
            exit_orders.append(exit_signal)

    return exit_orders


def execute_exit_orders(strategy, exit_orders, current_date, position_monitor, profit_tracker, summary=None):
    """Execute exit orders with summary logging"""

    for order in exit_orders:
        ticker = order['ticker']
        exit_type = order['type']
        sell_pct = order['sell_pct']
        reason = order['reason']

        broker_quantity = order['broker_quantity']
        broker_entry_price = order['broker_entry_price']
        current_price = order['current_price']
        entry_signal = order.get('entry_signal', 'pre_existing')
        entry_score = order.get('entry_score', 0)
        current_profit_level = order.get('current_profit_level', 0)

        sell_quantity = int(broker_quantity * (sell_pct / 100))
        if sell_quantity <= 0:
            continue

        if broker_entry_price <= 0:
            continue

        # Calculate P&L
        pnl_per_share = current_price - broker_entry_price
        total_pnl = pnl_per_share * sell_quantity
        pnl_pct = (pnl_per_share / broker_entry_price * 100)

        # PARTIAL EXIT (Profit Taking)
        if exit_type == 'partial_exit':
            new_profit_level = order.get('profit_level', current_profit_level)

            # Calculate remaining shares after this sale
            remaining_shares = broker_quantity - sell_quantity

            # Check if remnant is too small - convert to full exit
            remnant_check = check_remnant_position(remaining_shares, current_price)
            if remnant_check:
                # Convert to full exit
                sell_quantity = broker_quantity
                total_pnl = pnl_per_share * sell_quantity
                reason = f"{reason}+remnant"

                # Log to summary as full exit
                if summary:
                    summary.add_exit(ticker, sell_quantity, total_pnl, pnl_pct, reason)

                # Record trade
                profit_tracker.record_trade(
                    ticker=ticker,
                    quantity_sold=sell_quantity,
                    entry_price=broker_entry_price,
                    exit_price=current_price,
                    exit_date=current_date,
                    entry_signal=entry_signal,
                    exit_signal=order,
                    entry_score=entry_score
                )

                # Clean metadata (full exit)
                position_monitor.clean_position_metadata(ticker)

                # Execute
                sell_order = strategy.create_order(ticker, sell_quantity, 'sell')
                strategy.submit_order(sell_order)

                if hasattr(strategy, 'order_logger'):
                    strategy.order_logger.log_order(
                        ticker=ticker, side='sell', quantity=sell_quantity,
                        signal_type=reason, award='n/a', quality_score=0
                    )
                continue

            # Normal partial exit (remnant is OK)
            if summary:
                summary.add_profit_take(ticker, new_profit_level, sell_quantity, total_pnl, pnl_pct)

            # Advance profit level
            position_monitor.advance_profit_level(ticker, new_profit_level, current_price)
            position_monitor.update_local_max(ticker, current_price)

            # Record trade
            profit_tracker.record_trade(
                ticker=ticker,
                quantity_sold=sell_quantity,
                entry_price=broker_entry_price,
                exit_price=current_price,
                exit_date=current_date,
                entry_signal=entry_signal,
                exit_signal=order,
                entry_score=entry_score
            )

            # Execute
            sell_order = strategy.create_order(ticker, sell_quantity, 'sell')
            strategy.submit_order(sell_order)

            if hasattr(strategy, 'order_logger'):
                strategy.order_logger.log_order(
                    ticker=ticker, side='sell', quantity=sell_quantity,
                    signal_type=reason, award='n/a', quality_score=0
                )

        # FULL EXIT
        elif exit_type == 'full_exit':
            # Log to summary
            if summary:
                summary.add_exit(ticker, sell_quantity, total_pnl, pnl_pct, reason)

            # Record trade
            profit_tracker.record_trade(
                ticker=ticker,
                quantity_sold=sell_quantity,
                entry_price=broker_entry_price,
                exit_price=current_price,
                exit_date=current_date,
                entry_signal=entry_signal,
                exit_signal=order,
                entry_score=entry_score
            )

            # Clean metadata
            position_monitor.clean_position_metadata(ticker)

            # Record stop loss to regime detector
            is_stop_loss = any(kw in reason for kw in ['stop', 'emergency', 'intraday', 'trailing', 'atr'])
            if is_stop_loss and hasattr(strategy, 'regime_detector'):
                strategy.regime_detector.record_stop_loss(current_date, ticker, pnl_pct)

            # Execute
            sell_order = strategy.create_order(ticker, sell_quantity, 'sell')
            strategy.submit_order(sell_order)

            if hasattr(strategy, 'order_logger'):
                strategy.order_logger.log_order(
                    ticker=ticker, side='sell', quantity=sell_quantity,
                    signal_type=reason, award='n/a', quality_score=0
                )