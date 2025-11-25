# =============================================================================
# SIMPLIFIED CONFIGURATION - UNIVERSAL PARAMETERS
# =============================================================================

class ExitConfig:
    """Universal exit parameters - adjusted for daily bar slippage"""

    # Initial emergency stop (accounting for daily bar slippage)
    # NOTE: With daily bars, expect 1.5-2% additional slippage
    # A -5.5% stop will typically exit at -7% to -7.5% actual
    # Extreme gaps can cause up to -9% exits (vs -12% with -4.5%)
    INITIAL_EMERGENCY_STOP = -5.5  # Targets ~-7% actual with daily bars

    # Profit targets and sell percentages
    PROFIT_TARGET_1 = 10.0  # First target: +10%
    PROFIT_TARGET_1_SELL = 33.0  # Sell 33% of position

    PROFIT_TARGET_2 = 20.0  # Second target: +20%
    PROFIT_TARGET_2_SELL = 33.0  # Sell another 33%

    PROFIT_TARGET_3 = 30.0  # Third target: +30%
    PROFIT_TARGET_3_SELL = 50.0  # Sell 50% of remaining

    # Trailing stops from local maximum (tighter with intraday detection)
    # With intraday breach detection, we can use tighter stops
    TRAILING_STOP_LEVEL_1 = 6.0  # After Level 1: 6% from local max (was 7%)
    TRAILING_STOP_LEVEL_2 = 7.5  # After Level 2: 7.5% from local max (was 8.5%)
    TRAILING_STOP_LEVEL_3 = 10.0  # After Level 3: 10% from local max (was 11%)


# =============================================================================
# POSITION METADATA TRACKER - SIMPLIFIED
# =============================================================================

class PositionMonitor:
    """Tracks position metadata with simplified state management"""

    def __init__(self, strategy):
        self.strategy = strategy
        self.positions_metadata = {}

    def track_position(self, ticker, entry_date, entry_signal='unknown', entry_score=0):
        """Record position metadata for monitoring"""
        if ticker not in self.positions_metadata:
            current_price = self._get_current_price(ticker)

            self.positions_metadata[ticker] = {
                'entry_date': entry_date,
                'entry_signal': entry_signal,
                'entry_score': entry_score,
                'local_max': current_price,  # Track local maximum
                'last_peak_date': entry_date,
                'profit_level': 0,  # 0 = none, 1 = first, 2 = second, 3 = third
                'level_1_lock_price': None,  # Price when Level 1 locked
                'level_2_lock_price': None,  # Price when Level 2 locked
            }

            if entry_signal in ['recovered_orphan', 'recovered_metadata', 'recovered_unknown']:
                print(f"   [MONITOR] {ticker}: Tracking as {entry_signal}")

    def update_local_max(self, ticker, current_price):
        """Update local maximum for trailing stop calculations"""
        if ticker in self.positions_metadata:
            old_max = self.positions_metadata[ticker]['local_max']

            if current_price > old_max:
                self.positions_metadata[ticker]['local_max'] = current_price
                try:
                    self.positions_metadata[ticker]['last_peak_date'] = self.strategy.get_datetime()
                except:
                    pass

    def advance_profit_level(self, ticker, level, lock_price):
        """Advance to next profit level and record lock price"""
        if ticker in self.positions_metadata:
            self.positions_metadata[ticker]['profit_level'] = level

            if level == 1:
                self.positions_metadata[ticker]['level_1_lock_price'] = lock_price
            elif level == 2:
                self.positions_metadata[ticker]['level_2_lock_price'] = lock_price

    def clean_position_metadata(self, ticker):
        """Remove metadata when position is fully closed"""
        if ticker in self.positions_metadata:
            del self.positions_metadata[ticker]

    def get_position_metadata(self, ticker):
        """Get metadata for a ticker"""
        return self.positions_metadata.get(ticker, None)

    def _get_current_price(self, ticker):
        """Helper to get current price from broker"""
        try:
            return self.strategy.get_last_price(ticker)
        except:
            return 0


# =============================================================================
# EXIT STRATEGY FUNCTIONS - SIMPLIFIED
# =============================================================================

def check_intraday_stop_breach(low_price, entry_price, stop_threshold):
    """
    Check if intraday low breached stop threshold

    Even if close price recovered, exit if low touched stop.
    This catches gaps and intraday spikes on the SAME DAY instead
    of waiting until next day's gap down.

    Args:
        low_price: Day's low price
        entry_price: Entry price
        stop_threshold: Stop threshold percentage (e.g., -5.5)

    Returns:
        dict with exit signal or None
    """
    stop_price = entry_price * (1 + stop_threshold / 100)

    if low_price <= stop_price:
        return {
            'type': 'full_exit',
            'reason': 'intraday_stop_breach',
            'sell_pct': 100.0,
            'message': f'🚨 Intraday Breach: Low ${low_price:.2f} hit stop ${stop_price:.2f} (entry: ${entry_price:.2f})'
        }

    return None


def check_initial_emergency_stop(pnl_pct, current_price, entry_price):
    """
    Initial emergency stop (before any profit taking)

    Triggers at -5.5% from entry (targets ~-7% actual with daily bar slippage)
    """
    if pnl_pct <= ExitConfig.INITIAL_EMERGENCY_STOP:
        return {
            'type': 'full_exit',
            'reason': 'initial_emergency_stop',
            'sell_pct': 100.0,
            'message': f'🛑 Initial Emergency Stop {ExitConfig.INITIAL_EMERGENCY_STOP:.1f}%: ${current_price:.2f} (entry: ${entry_price:.2f})'
        }
    return None


def check_profit_taking(pnl_pct, profit_level):
    """
    Check if any profit level should trigger

    Returns profit level to lock (1, 2, or 3) or None
    """

    # Level 1: +10%
    if profit_level == 0 and pnl_pct >= ExitConfig.PROFIT_TARGET_1:
        return {
            'type': 'partial_exit',
            'reason': 'profit_level_1',
            'sell_pct': ExitConfig.PROFIT_TARGET_1_SELL,
            'profit_level': 1,
            'message': f'💰 Level 1 @ +{ExitConfig.PROFIT_TARGET_1:.0f}%: Selling {ExitConfig.PROFIT_TARGET_1_SELL:.0f}%, keeping {100 - ExitConfig.PROFIT_TARGET_1_SELL:.0f}%'
        }

    # Level 2: +20%
    if profit_level == 1 and pnl_pct >= ExitConfig.PROFIT_TARGET_2:
        remaining_after_l1 = 100 - ExitConfig.PROFIT_TARGET_1_SELL
        return {
            'type': 'partial_exit',
            'reason': 'profit_level_2',
            'sell_pct': ExitConfig.PROFIT_TARGET_2_SELL,
            'profit_level': 2,
            'message': f'💰 Level 2 @ +{ExitConfig.PROFIT_TARGET_2:.0f}%: Selling {ExitConfig.PROFIT_TARGET_2_SELL:.0f}%, keeping {remaining_after_l1 - ExitConfig.PROFIT_TARGET_2_SELL:.0f}%'
        }

    # Level 3: +30%
    if profit_level == 2 and pnl_pct >= ExitConfig.PROFIT_TARGET_3:
        remaining_after_l2 = 100 - ExitConfig.PROFIT_TARGET_1_SELL - ExitConfig.PROFIT_TARGET_2_SELL
        sell_amount = remaining_after_l2 * 0.50
        final_remaining = remaining_after_l2 - sell_amount

        return {
            'type': 'partial_exit',
            'reason': 'profit_level_3',
            'sell_pct': sell_amount,
            'profit_level': 3,
            'message': f'🚀 Level 3 @ +{ExitConfig.PROFIT_TARGET_3:.0f}%: Selling {sell_amount:.0f}%, trailing {final_remaining:.0f}% (BIG WINNER!)'
        }

    return None


def check_emergency_exit_per_level(profit_level, current_price, entry_price,
                                   level_1_lock_price, level_2_lock_price):
    """
    Emergency exits per profit level (overrides trailing stop)

    - Level 0: Not reached Level 1 yet (uses initial_emergency_stop)
    - Level 1: Emergency at entry price (protect principal)
    - Level 2: Emergency at Level 1 lock price (protect Level 1 gains)
    - Level 3: Emergency at Level 2 lock price (protect Level 2 gains)
    """

    # Level 1: Emergency if falls back to entry
    if profit_level == 1:
        if current_price <= entry_price:
            return {
                'type': 'full_exit',
                'reason': 'emergency_level_1',
                'sell_pct': 100.0,
                'message': f'🛑 Level 1 Emergency: Back to entry ${entry_price:.2f} (current: ${current_price:.2f})'
            }

    # Level 2: Emergency if falls back to Level 1 lock
    if profit_level == 2 and level_1_lock_price:
        if current_price <= level_1_lock_price:
            return {
                'type': 'full_exit',
                'reason': 'emergency_level_2',
                'sell_pct': 100.0,
                'message': f'🛑 Level 2 Emergency: Back to L1 lock ${level_1_lock_price:.2f} (current: ${current_price:.2f})'
            }

    # Level 3: Emergency if falls back to Level 2 lock
    if profit_level == 3 and level_2_lock_price:
        if current_price <= level_2_lock_price:
            return {
                'type': 'full_exit',
                'reason': 'emergency_level_3',
                'sell_pct': 100.0,
                'message': f'🛑 Level 3 Emergency: Back to L2 lock ${level_2_lock_price:.2f} (current: ${current_price:.2f})'
            }

    return None


def check_trailing_stop(profit_level, local_max, current_price):
    """
    Progressive trailing stop based on profit level

    - Level 1: 7% trailing from local max
    - Level 2: 8.5% trailing from local max
    - Level 3: 11% trailing from local max

    Trailing stop is OVERRIDDEN by emergency exits
    """

    if profit_level == 0:
        return None  # No trailing before Level 1

    # Determine trailing stop percentage
    if profit_level == 1:
        trail_pct = ExitConfig.TRAILING_STOP_LEVEL_1
    elif profit_level == 2:
        trail_pct = ExitConfig.TRAILING_STOP_LEVEL_2
    else:  # Level 3
        trail_pct = ExitConfig.TRAILING_STOP_LEVEL_3

    # Calculate drawdown from local max
    drawdown_from_max = ((current_price - local_max) / local_max * 100)

    if drawdown_from_max <= -trail_pct:
        return {
            'type': 'full_exit',
            'reason': f'trailing_stop_level_{profit_level}',
            'sell_pct': 100.0,
            'message': f'📉 Level {profit_level} Trail Stop ({trail_pct:.0f}% from ${local_max:.2f}): Exiting remaining position'
        }

    return None


def check_intraday_trailing_breach(low_price, local_max, profit_level):
    """
    Check if intraday low breached trailing stop

    Same concept as initial stop - catches breaches same day even if close recovered

    Args:
        low_price: Day's low price
        local_max: Local maximum price for trailing
        profit_level: Current profit level (1, 2, or 3)

    Returns:
        dict with exit signal or None
    """
    if profit_level == 0:
        return None  # No trailing before Level 1

    # Determine trailing stop percentage
    if profit_level == 1:
        trail_pct = ExitConfig.TRAILING_STOP_LEVEL_1
    elif profit_level == 2:
        trail_pct = ExitConfig.TRAILING_STOP_LEVEL_2
    else:  # Level 3
        trail_pct = ExitConfig.TRAILING_STOP_LEVEL_3

    trail_stop_price = local_max * (1 - trail_pct / 100)

    if low_price <= trail_stop_price:
        return {
            'type': 'full_exit',
            'reason': f'intraday_trailing_breach_level_{profit_level}',
            'sell_pct': 100.0,
            'message': f'🚨 Intraday Trail Breach L{profit_level}: Low ${low_price:.2f} hit trail ${trail_stop_price:.2f} ({trail_pct:.0f}% from peak ${local_max:.2f})'
        }

    return None


# =============================================================================
# MAIN COORDINATOR FUNCTIONS
# =============================================================================

def check_positions_for_exits(strategy, current_date, all_stock_data, position_monitor):
    """
    SIMPLIFIED EXIT PRIORITY ORDER:

    1. Initial emergency stop (-4.5% before any profit taking)
    2. Profit taking (triggers Level 1, 2, 3)
    3. Emergency exit per level (overrides trailing)
    4. Trailing stop (progressive 5%/6%/8% from local max)
    """
    import account_broker_data

    exit_orders = []

    positions = strategy.get_positions()
    if not positions:
        return exit_orders

    for position in positions:
        ticker = position.symbol

        broker_entry_price = account_broker_data.get_broker_entry_price(position, strategy, ticker)

        if not account_broker_data.validate_entry_price(broker_entry_price, ticker):
            print(f"[WARN] Skipping {ticker} - invalid entry price after all attempts")
            continue

        broker_quantity = account_broker_data.get_position_quantity(position, ticker)

        if broker_quantity <= 0:
            print(f"[WARN] Skipping {ticker} - invalid quantity: {broker_quantity}")
            continue

        if ticker not in all_stock_data:
            continue

        data = all_stock_data[ticker]['indicators']
        current_price = data.get('close', 0)

        if current_price <= 0:
            continue

        # Ensure position is tracked
        metadata = position_monitor.get_position_metadata(ticker)
        if not metadata:
            position_monitor.track_position(ticker, current_date, 'pre_existing', entry_score=0)
            metadata = position_monitor.get_position_metadata(ticker)

        # Update local maximum
        position_monitor.update_local_max(ticker, current_price)

        # Calculate P&L
        pnl_pct = ((current_price - broker_entry_price) / broker_entry_price * 100)
        pnl_dollars = (current_price - broker_entry_price) * broker_quantity

        # Get position state
        profit_level = metadata.get('profit_level', 0)
        local_max = metadata.get('local_max', broker_entry_price)
        level_1_lock_price = metadata.get('level_1_lock_price', None)
        level_2_lock_price = metadata.get('level_2_lock_price', None)

        # Get today's low price for intraday breach detection
        low_price = data.get('low', current_price)

        # CHECK EXIT CONDITIONS (Priority Order)
        exit_signal = None

        # PRIORITY 1: Intraday stop breach (catches breaches same day)
        if profit_level == 0:
            exit_signal = check_intraday_stop_breach(
                low_price=low_price,
                entry_price=broker_entry_price,
                stop_threshold=ExitConfig.INITIAL_EMERGENCY_STOP
            )

        # PRIORITY 2: Intraday trailing breach (for positions past Level 1)
        if not exit_signal and profit_level > 0:
            exit_signal = check_intraday_trailing_breach(
                low_price=low_price,
                local_max=local_max,
                profit_level=profit_level
            )

        # PRIORITY 3: Profit taking (if no intraday breach)
        if not exit_signal:
            exit_signal = check_profit_taking(
                pnl_pct=pnl_pct,
                profit_level=profit_level
            )

        # PRIORITY 4: Emergency exit per level (overrides trailing)
        if not exit_signal and profit_level > 0:
            exit_signal = check_emergency_exit_per_level(
                profit_level=profit_level,
                current_price=current_price,
                entry_price=broker_entry_price,
                level_1_lock_price=level_1_lock_price,
                level_2_lock_price=level_2_lock_price
            )

        # PRIORITY 5: Close-based initial stop (fallback if no intraday breach)
        if not exit_signal and profit_level == 0:
            exit_signal = check_initial_emergency_stop(
                pnl_pct=pnl_pct,
                current_price=current_price,
                entry_price=broker_entry_price
            )

        # PRIORITY 6: Close-based trailing stop (fallback)
        if not exit_signal and profit_level > 0:
            exit_signal = check_trailing_stop(
                profit_level=profit_level,
                local_max=local_max,
                current_price=current_price
            )

        # Add to exit orders
        if exit_signal:
            exit_signal['ticker'] = ticker
            exit_signal['broker_quantity'] = broker_quantity
            exit_signal['broker_entry_price'] = broker_entry_price
            exit_signal['current_price'] = current_price
            exit_signal['pnl_dollars'] = pnl_dollars
            exit_signal['pnl_pct'] = pnl_pct
            exit_signal['entry_signal'] = metadata.get('entry_signal', 'pre_existing')
            exit_signal['entry_score'] = metadata.get('entry_score', 0)
            exit_signal['profit_level'] = profit_level
            exit_orders.append(exit_signal)

    return exit_orders


def execute_exit_orders(strategy, exit_orders, current_date, position_monitor, profit_tracker):
    """
    Execute exit orders using BROKER data for P&L calculation

    UPDATED: Now records stop losses to regime detector
    """

    for order in exit_orders:
        ticker = order['ticker']
        exit_type = order['type']
        sell_pct = order['sell_pct']
        reason = order['reason']
        message = order['message']

        broker_quantity = order['broker_quantity']
        broker_entry_price = order['broker_entry_price']
        current_price = order['current_price']
        entry_signal = order.get('entry_signal', 'pre_existing')
        entry_score = order.get('entry_score', 0)
        profit_level = order.get('profit_level', 0)

        # Calculate quantity to sell
        sell_quantity = int(broker_quantity * (sell_pct / 100))

        if sell_quantity <= 0:
            continue

        if broker_entry_price <= 0:
            print(f"[WARN] Skipping {ticker} - invalid entry price: {broker_entry_price}")
            continue

        # Calculate P&L
        pnl_per_share = current_price - broker_entry_price
        total_pnl = pnl_per_share * sell_quantity
        pnl_pct = (pnl_per_share / broker_entry_price * 100)

        # PARTIAL EXIT
        if exit_type == 'partial_exit':
            new_profit_level = order.get('profit_level', profit_level)
            remaining = broker_quantity - sell_quantity

            print(f"\n{'=' * 70}")
            print(f"💰 PROFIT TAKING LEVEL {new_profit_level} - {ticker}")
            print(f"{'=' * 70}")
            print(f"Position: {broker_quantity} shares @ ${broker_entry_price:.2f}")
            print(f"Selling: {sell_quantity} shares ({sell_pct:.0f}%) @ ${current_price:.2f}")
            print(f"P&L: ${total_pnl:+,.2f} ({pnl_pct:+.1f}%)")
            print(f"Remaining: {remaining} shares")
            print(f"{'=' * 70}\n")

            # Advance profit level and lock price
            position_monitor.advance_profit_level(ticker, new_profit_level, current_price)

            # Record the trade
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

            # Execute sell
            sell_order = strategy.create_order(ticker, sell_quantity, 'sell')
            print(f" * EXIT: {ticker} x{sell_quantity} | {message}")
            strategy.submit_order(sell_order)

            if hasattr(strategy, 'order_logger'):
                strategy.order_logger.log_order(
                    ticker=ticker,
                    side='sell',
                    quantity=sell_quantity,
                    signal_type=order['reason'],
                    award='n/a',
                    quality_score=0
                )

        # FULL EXIT
        elif exit_type == 'full_exit':
            print(f"\n{'=' * 70}")
            print(f"🚪 FULL EXIT - {ticker}")
            print(f"{'=' * 70}")
            print(f"Position: {broker_quantity} shares @ ${broker_entry_price:.2f}")
            print(f"Selling: {sell_quantity} shares @ ${current_price:.2f}")
            print(f"P&L: ${total_pnl:+,.2f} ({pnl_pct:+.1f}%)")
            print(f"Reason: {message}")
            print(f"{'=' * 70}\n")

            # Record the trade
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

            # ===================================================================
            # NEW: RECORD STOP LOSS TO REGIME DETECTOR
            # ===================================================================
            # Check if this is a stop loss (not profit taking)
            is_stop_loss = any(keyword in reason for keyword in [
                'stop', 'emergency', 'intraday', 'trailing', 'initial'
            ])

            if is_stop_loss and hasattr(strategy, 'regime_detector'):
                # Record stop loss for sequential tracking
                strategy.regime_detector.record_stop_loss(
                    current_date,
                    ticker,
                    pnl_pct
                )
                print(f"   📊 Stop loss recorded: {ticker} ({pnl_pct:.1f}%)")
            # ===================================================================

            # Execute sell
            sell_order = strategy.create_order(ticker, sell_quantity, 'sell')
            print(f" * EXIT: {ticker} x{sell_quantity} | {message}")
            strategy.submit_order(sell_order)