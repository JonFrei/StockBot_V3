"""
Position Monitoring - TIERED EXIT SYSTEM WITH KILL SWITCH

NEW SYSTEM:
✅ Level 0 (Entry): Initial ATR stop = Entry - (2 × ATR)
✅ Level 1 (+10%): Sell 33% → Emergency stop = Tier1_Lock - (2 × ATR)
                    → Kill Switch ACTIVE
✅ Level 2 (+20%): Sell 66% of remaining → Peak trailing = Peak - (3 × ATR)
                    → 22.78% position remains

KILL SWITCH (Active after Tier 1):
- Momentum Fade + Price Confirmation → Exit 100% immediately
"""

import stock_indicators


class ExitConfig:
    """Tiered exit configuration"""

    # Initial stop loss (Level 0)
    INITIAL_STOP_ATR_MULT = 2.0

    # Tier 1: First profit target
    TIER1_TARGET_PCT = 10.0  # +10% from entry
    TIER1_SELL_PCT = 33.0  # Sell 33% of position
    TIER1_EMERGENCY_ATR_MULT = 2.0  # Emergency stop = Tier1_Lock - (2 × ATR)

    # Tier 2: Second profit target
    TIER2_TARGET_PCT = 20.0  # +20% from entry
    TIER2_SELL_PCT = 66.0  # Sell 66% of REMAINING position (44.22% of original)
    TIER2_TRAILING_ATR_MULT = 3.0  # Trailing stop = Peak - (3 × ATR)

    # Kill Switch (active after Tier 1)
    KILL_SWITCH_ACTIVE_AFTER_TIER1 = True

    # Stagnant position check
    STAGNANT_MAX_DAYS = 30
    STAGNANT_MIN_GAIN_PCT = 3.0
    STAGNANT_ENABLED = True

    # Remnant cleanup
    MIN_REMNANT_SHARES = 5
    MIN_REMNANT_VALUE = 500.0


class PositionMonitor:
    """Tracks position state for tiered exits"""

    def __init__(self, strategy):
        self.strategy = strategy
        self.positions_metadata = {}

    def track_position(self, ticker, entry_date, entry_signal='unknown', entry_score=0):
        """
        Initialize position tracking with Level 0 state

        Args:
            ticker: Stock symbol
            entry_date: Entry datetime
            entry_signal: Entry signal name
            entry_score: Entry quality score
        """
        if ticker not in self.positions_metadata:
            current_price = self._get_current_price(ticker)

            self.positions_metadata[ticker] = {
                'entry_date': entry_date,
                'entry_signal': entry_signal,
                'entry_score': entry_score,
                'entry_price': current_price,  # For profit calculations
                'profit_level': 0,  # 0=Entry, 1=Tier1, 2=Tier2
                'tier1_lock_price': None,  # Price at Tier 1 execution
                'peak_price': None,  # Peak after Tier 2
                'kill_switch_active': False  # Activated after Tier 1
            }

    def advance_to_tier1(self, ticker, tier1_price):
        """
        Advance position to Tier 1 (33% sold)

        Args:
            ticker: Stock symbol
            tier1_price: Price at which Tier 1 executed
        """
        if ticker in self.positions_metadata:
            self.positions_metadata[ticker]['profit_level'] = 1
            self.positions_metadata[ticker]['tier1_lock_price'] = tier1_price
            self.positions_metadata[ticker]['kill_switch_active'] = True

    def advance_to_tier2(self, ticker, tier2_price):
        """
        Advance position to Tier 2 (66% of remaining sold, trailing active)

        Args:
            ticker: Stock symbol
            tier2_price: Price at which Tier 2 executed
        """
        if ticker in self.positions_metadata:
            self.positions_metadata[ticker]['profit_level'] = 2
            self.positions_metadata[ticker]['peak_price'] = tier2_price  # Initialize peak

    def update_peak_price(self, ticker, current_price):
        """
        Update peak price for Level 2 trailing stop

        Args:
            ticker: Stock symbol
            current_price: Current price
        """
        if ticker in self.positions_metadata:
            meta = self.positions_metadata[ticker]
            if meta['profit_level'] == 2:
                if meta['peak_price'] is None or current_price > meta['peak_price']:
                    meta['peak_price'] = current_price

    def clean_position_metadata(self, ticker):
        """Remove position metadata after full exit"""
        if ticker in self.positions_metadata:
            del self.positions_metadata[ticker]

    def get_position_metadata(self, ticker):
        """Get position metadata"""
        return self.positions_metadata.get(ticker, None)

    def _get_current_price(self, ticker):
        """Get current price from strategy"""
        try:
            return self.strategy.get_last_price(ticker)
        except:
            return 0


# =============================================================================
# EXIT CONDITION CHECKS
# =============================================================================

def check_initial_stop(entry_price, prev_low, atr):
    """
    Check Level 0 initial ATR stop

    Stop = Entry - (2 × ATR)
    Checked using prev_low as intraday proxy

    Args:
        entry_price: Original entry price
        prev_low: Previous bar's low (intraday proxy)
        atr: ATR(14) value

    Returns:
        dict or None: Exit signal if triggered
    """
    if not atr or atr <= 0 or entry_price <= 0:
        return None

    stop_price = entry_price - (ExitConfig.INITIAL_STOP_ATR_MULT * atr)

    if prev_low <= stop_price:
        return {
            'type': 'full_exit',
            'reason': 'initial_atr_stop',
            'sell_pct': 100.0,
            'message': f'Initial stop @ ${stop_price:.2f} (Entry: ${entry_price:.2f}, ATR: ${atr:.2f})'
        }

    return None


def check_tier1_target(pnl_pct):
    """
    Check if Tier 1 profit target reached (+10%)

    Args:
        pnl_pct: Current P&L percentage

    Returns:
        dict or None: Tier 1 exit signal
    """
    if pnl_pct >= ExitConfig.TIER1_TARGET_PCT:
        return {
            'type': 'tier1_exit',
            'reason': 'tier1_profit',
            'sell_pct': ExitConfig.TIER1_SELL_PCT,
            'tier': 1,
            'message': f'Tier 1 @ +{pnl_pct:.1f}% (target: +{ExitConfig.TIER1_TARGET_PCT}%)'
        }

    return None


def check_emergency_stop(tier1_lock_price, prev_low, atr):
    """
    Check Level 1 emergency stop after Tier 1

    Stop = Tier1_Lock - (2 × ATR)

    Args:
        tier1_lock_price: Price at which Tier 1 executed
        prev_low: Previous bar's low
        atr: ATR(14) value

    Returns:
        dict or None: Exit signal if triggered
    """
    if not tier1_lock_price or not atr or atr <= 0:
        return None

    emergency_stop = tier1_lock_price - (ExitConfig.TIER1_EMERGENCY_ATR_MULT * atr)

    if prev_low <= emergency_stop:
        return {
            'type': 'full_exit',
            'reason': 'emergency_stop_tier1',
            'sell_pct': 100.0,
            'message': f'Emergency stop @ ${emergency_stop:.2f} (Lock: ${tier1_lock_price:.2f}, ATR: ${atr:.2f})'
        }

    return None


def check_tier2_target(pnl_pct, current_profit_level):
    """
    Check if Tier 2 profit target reached (+20%)

    Args:
        pnl_pct: Current P&L percentage
        current_profit_level: Current position level (must be 1)

    Returns:
        dict or None: Tier 2 exit signal
    """
    if current_profit_level != 1:
        return None

    if pnl_pct >= ExitConfig.TIER2_TARGET_PCT:
        return {
            'type': 'tier2_exit',
            'reason': 'tier2_profit',
            'sell_pct': ExitConfig.TIER2_SELL_PCT,  # 66% of remaining
            'tier': 2,
            'message': f'Tier 2 @ +{pnl_pct:.1f}% (target: +{ExitConfig.TIER2_TARGET_PCT}%)'
        }

    return None


def check_trailing_stop(peak_price, prev_low, atr):
    """
    Check Level 2 trailing stop after Tier 2

    Stop = Peak - (3 × ATR)

    Args:
        peak_price: Highest price since Tier 2
        prev_low: Previous bar's low
        atr: ATR(14) value

    Returns:
        dict or None: Exit signal if triggered
    """
    if not peak_price or not atr or atr <= 0:
        return None

    trailing_stop = peak_price - (ExitConfig.TIER2_TRAILING_ATR_MULT * atr)

    if prev_low <= trailing_stop:
        return {
            'type': 'full_exit',
            'reason': 'trailing_stop_tier2',
            'sell_pct': 100.0,
            'message': f'Trailing stop @ ${trailing_stop:.2f} (Peak: ${peak_price:.2f}, ATR: ${atr:.2f})'
        }

    return None


def check_kill_switch(raw_df, indicators, kill_switch_active):
    """
    Check Kill Switch: Momentum Fade + Price Confirmation

    Only active after Tier 1 executes
    Overrides all other exits

    Args:
        raw_df: DataFrame with OHLC data
        indicators: Dict with current indicators
        kill_switch_active: Bool - is kill switch armed?

    Returns:
        dict or None: Kill switch exit signal
    """
    if not kill_switch_active:
        return None

    if raw_df is None or len(raw_df) < 10:
        return None

    # Check momentum fade
    fade_result = stock_indicators.detect_momentum_fade(raw_df, indicators)

    if not fade_result['fade_detected']:
        return None

    # Check price confirmation
    confirm_result = stock_indicators.detect_price_confirmation(raw_df, indicators)

    if confirm_result['confirmed']:
        fade_signals = ', '.join(fade_result['signals'])

        return {
            'type': 'full_exit',
            'reason': 'kill_switch',
            'sell_pct': 100.0,
            'message': f'KILL SWITCH: Fade [{fade_signals}] + Confirmation [{confirm_result["reason"]}]'
        }

    return None


def check_stagnant_position(entry_date, current_date, pnl_pct):
    """
    Check for stagnant position (30 days, <3% gain)

    Args:
        entry_date: Entry datetime
        current_date: Current datetime
        pnl_pct: Current P&L percentage

    Returns:
        dict or None: Exit signal if stagnant
    """
    if not ExitConfig.STAGNANT_ENABLED or entry_date is None or current_date is None:
        return None

    # Normalize dates
    entry = entry_date.replace(tzinfo=None) if hasattr(entry_date, 'tzinfo') and entry_date.tzinfo else entry_date
    current = current_date.replace(tzinfo=None) if hasattr(current_date,
                                                           'tzinfo') and current_date.tzinfo else current_date

    days_held = (current - entry).days

    if days_held >= ExitConfig.STAGNANT_MAX_DAYS and pnl_pct < ExitConfig.STAGNANT_MIN_GAIN_PCT:
        return {
            'type': 'full_exit',
            'reason': 'stagnant_exit',
            'sell_pct': 100.0,
            'message': f'Stagnant {days_held}d with only {pnl_pct:+.1f}%'
        }

    return None


def check_remnant_position(remaining_shares, current_price):
    """
    Check for remnant position cleanup

    Args:
        remaining_shares: Current position size
        current_price: Current price

    Returns:
        dict or None: Exit signal if remnant
    """
    remaining_value = remaining_shares * current_price

    if remaining_shares < ExitConfig.MIN_REMNANT_SHARES:
        return {
            'type': 'full_exit',
            'reason': 'remnant_cleanup',
            'sell_pct': 100.0,
            'message': f'Remnant cleanup: {remaining_shares} shares'
        }

    if remaining_value < ExitConfig.MIN_REMNANT_VALUE:
        return {
            'type': 'full_exit',
            'reason': 'remnant_cleanup',
            'sell_pct': 100.0,
            'message': f'Remnant cleanup: ${remaining_value:.0f}'
        }

    return None


# =============================================================================
# MAIN POSITION CHECKING FUNCTION
# =============================================================================

def check_positions_for_exits(strategy, current_date, all_stock_data, position_monitor):
    """
    Check all positions for exit signals

    Priority order:
    1. Kill Switch (if active)
    2. Tier 1 target
    3. Tier 2 target
    4. Stops (initial, emergency, or trailing based on level)
    5. Stagnant/Remnant

    Args:
        strategy: Lumibot Strategy instance
        current_date: Current datetime
        all_stock_data: Dict of ticker -> stock data
        position_monitor: PositionMonitor instance

    Returns:
        list: Exit orders
    """
    import account_broker_data

    exit_orders = []
    positions = strategy.get_positions()

    if not positions:
        return exit_orders

    for position in positions:
        ticker = position.symbol

        # Get broker data
        broker_entry_price = account_broker_data.get_broker_entry_price(position, strategy, ticker)
        if not account_broker_data.validate_entry_price(broker_entry_price, ticker):
            continue

        broker_quantity = account_broker_data.get_position_quantity(position, ticker)
        if broker_quantity <= 0 or ticker not in all_stock_data:
            continue

        # Get market data
        data = all_stock_data[ticker]['indicators']
        raw_df = all_stock_data[ticker].get('raw')

        current_price = data.get('close', 0)
        prev_low = data.get('prev_low', current_price)
        atr = data.get('atr_14', None)

        if current_price <= 0:
            continue

        # Get or create position metadata
        metadata = position_monitor.get_position_metadata(ticker)
        if not metadata:
            position_monitor.track_position(ticker, current_date, 'pre_existing', entry_score=0)
            metadata = position_monitor.get_position_metadata(ticker)

        # Use metadata entry_price for calculations (more accurate than broker for pre-existing)
        entry_price = metadata.get('entry_price', broker_entry_price)

        # Calculate P&L
        pnl_pct = ((current_price - entry_price) / entry_price * 100) if entry_price > 0 else 0
        pnl_dollars = (current_price - entry_price) * broker_quantity

        # Get position state
        profit_level = metadata.get('profit_level', 0)
        tier1_lock_price = metadata.get('tier1_lock_price')
        peak_price = metadata.get('peak_price')
        kill_switch_active = metadata.get('kill_switch_active', False)

        exit_signal = None

        # =====================================================================
        # PRIORITY 1: KILL SWITCH (after Tier 1 only)
        # =====================================================================
        if profit_level >= 1 and ExitConfig.KILL_SWITCH_ACTIVE_AFTER_TIER1:
            exit_signal = check_kill_switch(raw_df, data, kill_switch_active)

        # =====================================================================
        # PRIORITY 2: TIER PROFIT TARGETS
        # =====================================================================
        if not exit_signal:
            if profit_level == 0:
                exit_signal = check_tier1_target(pnl_pct)
            elif profit_level == 1:
                exit_signal = check_tier2_target(pnl_pct, profit_level)

        # =====================================================================
        # PRIORITY 3: STOPS (based on current level)
        # =====================================================================
        if not exit_signal:
            if profit_level == 0:
                # Level 0: Initial ATR stop
                exit_signal = check_initial_stop(entry_price, prev_low, atr)

            elif profit_level == 1:
                # Level 1: Emergency stop
                exit_signal = check_emergency_stop(tier1_lock_price, prev_low, atr)

            elif profit_level == 2:
                # Level 2: Trailing stop
                exit_signal = check_trailing_stop(peak_price, prev_low, atr)

        # =====================================================================
        # PRIORITY 4: STAGNANT POSITION
        # =====================================================================
        if not exit_signal:
            entry_date = metadata.get('entry_date')
            exit_signal = check_stagnant_position(entry_date, current_date, pnl_pct)

        # =====================================================================
        # NO EXIT: UPDATE PEAK PRICE IF LEVEL 2
        # =====================================================================
        if not exit_signal and profit_level == 2:
            position_monitor.update_peak_price(ticker, current_price)

        # =====================================================================
        # PACKAGE EXIT ORDER
        # =====================================================================
        if exit_signal:
            exit_signal['ticker'] = ticker
            exit_signal['broker_quantity'] = broker_quantity
            exit_signal['broker_entry_price'] = broker_entry_price
            exit_signal['entry_price'] = entry_price
            exit_signal['current_price'] = current_price
            exit_signal['pnl_dollars'] = pnl_dollars
            exit_signal['pnl_pct'] = pnl_pct
            exit_signal['entry_signal'] = metadata.get('entry_signal', 'pre_existing')
            exit_signal['entry_score'] = metadata.get('entry_score', 0)
            exit_signal['current_profit_level'] = profit_level
            exit_orders.append(exit_signal)

    return exit_orders


# =============================================================================
# EXIT ORDER EXECUTION
# =============================================================================

def execute_exit_orders(strategy, exit_orders, current_date, position_monitor, profit_tracker,
                        summary=None, recovery_manager=None):
    """
    Execute exit orders with tier-specific handling

    Args:
        strategy: Lumibot Strategy instance
        exit_orders: List of exit order dicts
        current_date: Current datetime
        position_monitor: PositionMonitor instance
        profit_tracker: ProfitTracker instance
        summary: DailySummary instance (optional)
        recovery_manager: RecoveryModeManager instance (optional)
    """
    for order in exit_orders:
        ticker = order['ticker']
        exit_type = order['type']
        sell_pct = order['sell_pct']
        reason = order['reason']

        broker_quantity = order['broker_quantity']
        entry_price = order['entry_price']
        current_price = order['current_price']
        entry_signal = order.get('entry_signal', 'pre_existing')
        entry_score = order.get('entry_score', 0)
        current_profit_level = order.get('current_profit_level', 0)

        # Calculate sell quantity
        if exit_type in ['tier1_exit', 'tier2_exit']:
            # Tier exits: percentage of CURRENT position
            sell_quantity = int(broker_quantity * (sell_pct / 100))
        else:
            # Full exits: 100% of position
            sell_quantity = broker_quantity

        if sell_quantity <= 0 or entry_price <= 0:
            continue

        # Calculate P&L for this exit
        pnl_per_share = current_price - entry_price
        total_pnl = pnl_per_share * sell_quantity
        pnl_pct = (pnl_per_share / entry_price * 100)

        # =====================================================================
        # TIER 1 EXIT: Partial exit + activate emergency stop
        # =====================================================================
        if exit_type == 'tier1_exit':
            remaining_shares = broker_quantity - sell_quantity

            # Check if remaining position too small
            remnant_check = check_remnant_position(remaining_shares, current_price)
            if remnant_check:
                # Too small - exit everything instead
                sell_quantity = broker_quantity
                total_pnl = pnl_per_share * sell_quantity
                reason = f"{reason}+remnant"

                if summary:
                    summary.add_exit(ticker, sell_quantity, total_pnl, pnl_pct, reason)

                profit_tracker.record_trade(
                    ticker=ticker,
                    quantity_sold=sell_quantity,
                    entry_price=entry_price,
                    exit_price=current_price,
                    exit_date=current_date,
                    entry_signal=entry_signal,
                    exit_signal=order,
                    entry_score=entry_score
                )

                position_monitor.clean_position_metadata(ticker)

                sell_order = strategy.create_order(ticker, sell_quantity, 'sell')
                strategy.submit_order(sell_order)
                continue

            # Normal Tier 1 exit
            if summary:
                summary.add_profit_take(ticker, 1, sell_quantity, total_pnl, pnl_pct)

            # Advance to Level 1 (emergency stop active)
            position_monitor.advance_to_tier1(ticker, current_price)

            profit_tracker.record_trade(
                ticker=ticker,
                quantity_sold=sell_quantity,
                entry_price=entry_price,
                exit_price=current_price,
                exit_date=current_date,
                entry_signal=entry_signal,
                exit_signal=order,
                entry_score=entry_score
            )

            sell_order = strategy.create_order(ticker, sell_quantity, 'sell')
            strategy.submit_order(sell_order)

        # =====================================================================
        # TIER 2 EXIT: Partial exit + activate trailing stop
        # =====================================================================
        elif exit_type == 'tier2_exit':
            remaining_shares = broker_quantity - sell_quantity

            # Check if remaining position too small
            remnant_check = check_remnant_position(remaining_shares, current_price)
            if remnant_check:
                # Too small - exit everything instead
                sell_quantity = broker_quantity
                total_pnl = pnl_per_share * sell_quantity
                reason = f"{reason}+remnant"

                if summary:
                    summary.add_exit(ticker, sell_quantity, total_pnl, pnl_pct, reason)

                profit_tracker.record_trade(
                    ticker=ticker,
                    quantity_sold=sell_quantity,
                    entry_price=entry_price,
                    exit_price=current_price,
                    exit_date=current_date,
                    entry_signal=entry_signal,
                    exit_signal=order,
                    entry_score=entry_score
                )

                position_monitor.clean_position_metadata(ticker)

                sell_order = strategy.create_order(ticker, sell_quantity, 'sell')
                strategy.submit_order(sell_order)
                continue

            # Normal Tier 2 exit
            if summary:
                summary.add_profit_take(ticker, 2, sell_quantity, total_pnl, pnl_pct)

            # Advance to Level 2 (trailing stop active)
            position_monitor.advance_to_tier2(ticker, current_price)

            profit_tracker.record_trade(
                ticker=ticker,
                quantity_sold=sell_quantity,
                entry_price=entry_price,
                exit_price=current_price,
                exit_date=current_date,
                entry_signal=entry_signal,
                exit_signal=order,
                entry_score=entry_score
            )

            sell_order = strategy.create_order(ticker, sell_quantity, 'sell')
            strategy.submit_order(sell_order)

        # =====================================================================
        # FULL EXIT: Close entire position
        # =====================================================================
        else:
            if summary:
                summary.add_exit(ticker, sell_quantity, total_pnl, pnl_pct, reason)

            profit_tracker.record_trade(
                ticker=ticker,
                quantity_sold=sell_quantity,
                entry_price=entry_price,
                exit_price=current_price,
                exit_date=current_date,
                entry_signal=entry_signal,
                exit_signal=order,
                entry_score=entry_score
            )

            position_monitor.clean_position_metadata(ticker)

            # Record stop loss to regime detector
            is_stop_loss = any(kw in reason for kw in ['stop', 'emergency', 'trailing', 'kill_switch'])
            if is_stop_loss and hasattr(strategy, 'regime_detector'):
                strategy.regime_detector.record_stop_loss(current_date, ticker, pnl_pct)

            # Trigger recovery mode re-lock on stop loss
            if is_stop_loss and recovery_manager is not None:
                recovery_manager.trigger_relock(current_date, f"stop_loss_{ticker}")

            sell_order = strategy.create_order(ticker, sell_quantity, 'sell')
            strategy.submit_order(sell_order)