"""
Position Monitoring - STREAMLINED VERSION

FIXES:
- profit_level key renamed to current_profit_level to avoid overwrite bug
- Removed verbose per-event logging
- Uses DailySummary for consolidated output
"""


class ExitConfig:
    """Universal exit parameters"""
    INITIAL_EMERGENCY_STOP = -5.5

    PROFIT_TARGET_1 = 10.0
    PROFIT_TARGET_1_SELL = 33.0

    PROFIT_TARGET_2 = 20.0
    PROFIT_TARGET_2_SELL = 33.0

    PROFIT_TARGET_3 = 30.0
    PROFIT_TARGET_3_SELL = 50.0

    TRAILING_STOP_LEVEL_1 = 6.0
    TRAILING_STOP_LEVEL_2 = 7.5
    TRAILING_STOP_LEVEL_3 = 10.0


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


def check_initial_emergency_stop(pnl_pct, current_price, entry_price):
    """Initial emergency stop"""
    if pnl_pct <= ExitConfig.INITIAL_EMERGENCY_STOP:
        return {
            'type': 'full_exit',
            'reason': 'emergency_stop',
            'sell_pct': 100.0,
            'message': f'Emergency stop {pnl_pct:.1f}%'
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

        # Check exits in priority order
        exit_signal = None

        # Level 0: Initial stops
        if profit_level == 0:
            exit_signal = check_intraday_stop_breach(
                low_price, broker_entry_price, ExitConfig.INITIAL_EMERGENCY_STOP
            )
            if not exit_signal:
                exit_signal = check_initial_emergency_stop(pnl_pct, current_price, broker_entry_price)

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
            exit_signal['current_profit_level'] = profit_level  # FIX: renamed to avoid overwrite
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

            # Log to summary
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
            is_stop_loss = any(kw in reason for kw in ['stop', 'emergency', 'intraday', 'trailing'])
            if is_stop_loss and hasattr(strategy, 'regime_detector'):
                strategy.regime_detector.record_stop_loss(current_date, ticker, pnl_pct)

            # Execute
            sell_order = strategy.create_order(ticker, sell_quantity, 'sell')
            strategy.submit_order(sell_order)