"""
Stock Position Monitoring - Structure-Anchored Trailing Exit System

CORE PHILOSOPHY: One primary mechanism, structure-based stops, let position sizing handle risk.

EXIT SYSTEM:
1. Initial Stop: Structure-based (lowest low of 10 bars - 0.5% buffer)
2. Trailing Stop: Chandelier Exit (highest close - 3×ATR10)
3. Profit Take: Sell 50% at +2R
4. Dead Money Filter: 5 consecutive closes below EMA50
5. Hard Stop: 10% max loss (circuit breaker)

PHASES:
- Entry: Stop = structure-based (lowest low)
- Breakeven Lock: When price reaches +2×ATR, stop moves to entry
- Profit Lock: When price reaches +3.5×ATR, stop moves to entry + 1.5×ATR
- Trailing: After profit lock, Chandelier trailing (peak - 2.5×ATR)
"""

import stock_indicators
from config import Config
import stock_position_sizing
import account_broker_data


class ExitConfig:
    """Structure-Anchored Trailing Exit Configuration"""

    # Structure-based initial stop
    STRUCTURE_LOOKBACK_BARS = 10  # Bars for lowest low
    STRUCTURE_BUFFER_PCT = 0.5  # Buffer below lowest low (%)
    MAX_INITIAL_STOP_PCT = 8.0  # Maximum initial stop distance (%)

    # ATR settings
    ATR_PERIOD = 10  # Faster ATR for adaptation

    # Chandelier trailing
    CHANDELIER_MULTIPLIER = 3.0  # Peak - (3.0 × ATR)

    # Phase transitions (in ATR multiples from entry)
    BREAKEVEN_LOCK_ATR = 2.0  # Move stop to entry at +2×ATR
    PROFIT_LOCK_ATR = 3.5  # Move stop to entry + 1.5×ATR at +3.5×ATR
    PROFIT_LOCK_STOP_ATR = 1.5  # Stop level after profit lock

    # Trailing multiplier after profit lock
    TRAILING_ATR_MULT = 2.5  # Peak - (2.5 × current ATR)

    # Profit taking
    PROFIT_TAKE_R_MULTIPLE = 2.0  # Take profit at 2R
    PROFIT_TAKE_PCT = 50.0  # Sell 50% at profit target

    # Dead money filter
    DEAD_MONEY_EMA_PERIOD = 50  # EMA period for dead money check
    DEAD_MONEY_BARS_BELOW = 5  # Consecutive bars below EMA to trigger
    DEAD_MONEY_MAX_LOSS_R = 1.0  # Only trigger if loss < 1R

    # Hard stop (circuit breaker)
    HARD_STOP_PCT = 10.0  # Maximum loss percentage

    # Regime adjustment
    REGIME_TIGHTENING_PCT = 20.0  # Reduce multipliers by 20% when SPY < 50 SMA

    # Remnant cleanup
    MIN_REMNANT_SHARES = 5
    MIN_REMNANT_VALUE = 300.0


class PositionMonitor:
    """Tracks position state for structure-anchored trailing exits"""

    def __init__(self, strategy):
        self.strategy = strategy
        self.positions_metadata = {}

    def track_position(self, ticker, entry_date, entry_signal='unknown', entry_score=0,
                       is_addon=False, entry_price=None, raw_df=None, atr=None):
        """
        Initialize or update position tracking with structure-based stop

        Args:
            ticker: Stock symbol
            entry_date: Entry datetime
            entry_signal: Entry signal name
            entry_score: Entry quality score
            is_addon: True if adding to existing position
            entry_price: Entry price
            raw_df: DataFrame with OHLC for structure calculation
            atr: ATR value for R calculation
        """
        current_price = entry_price if entry_price and entry_price > 0 else self._get_current_price(ticker)

        if ticker not in self.positions_metadata:
            # Calculate structure-based initial stop
            initial_stop = self._calculate_structure_stop(current_price, raw_df)

            # Calculate R (initial risk)
            R = current_price - initial_stop if initial_stop > 0 else current_price * 0.05

            # Store ATR at entry for reference
            entry_atr = atr if atr and atr > 0 else R / 2.5  # Fallback estimate

            self.positions_metadata[ticker] = {
                'entry_date': entry_date,
                'entry_signal': entry_signal,
                'entry_score': entry_score,
                'entry_price': current_price,
                'initial_stop': initial_stop,
                'R': R,
                'entry_atr': entry_atr,
                'highest_close': current_price,
                'current_stop': initial_stop,
                'phase': 'entry',  # entry, breakeven, profit_lock, trailing
                'partial_taken': False,
                'bars_below_ema50': 0,
                'add_count': 0
            }
        elif is_addon:
            # Add-on: preserve phase state, increment add count
            self.positions_metadata[ticker]['add_count'] = self.positions_metadata[ticker].get('add_count', 0) + 1
            # Entry price will be updated by broker's avg_entry_price

    def _calculate_structure_stop(self, entry_price, raw_df):
        """
        Calculate structure-based initial stop

        Stop = Lowest low of past 10 bars minus 0.5% buffer
        Capped at 8% from entry
        """
        if raw_df is None or len(raw_df) < ExitConfig.STRUCTURE_LOOKBACK_BARS:
            # Fallback: 5% stop
            return entry_price * 0.95

        # Get lowest low of lookback period
        lookback_lows = raw_df['low'].tail(ExitConfig.STRUCTURE_LOOKBACK_BARS)
        lowest_low = lookback_lows.min()

        # Apply buffer
        structure_stop = lowest_low * (1 - ExitConfig.STRUCTURE_BUFFER_PCT / 100)

        # Cap at maximum stop distance
        min_stop = entry_price * (1 - ExitConfig.MAX_INITIAL_STOP_PCT / 100)
        structure_stop = max(structure_stop, min_stop)

        return structure_stop

    def update_position_state(self, ticker, current_close, current_atr, ema50, regime_bearish=False):
        """
        Update position state each bar

        Updates highest_close, phase transitions, current_stop, bars_below_ema50
        """
        if ticker not in self.positions_metadata:
            return

        meta = self.positions_metadata[ticker]
        entry_price = meta['entry_price']
        R = meta['R']
        entry_atr = meta['entry_atr']

        # Update highest close
        if current_close > meta['highest_close']:
            meta['highest_close'] = current_close

        # Calculate current gain in ATR terms
        gain_atr = (current_close - entry_price) / entry_atr if entry_atr > 0 else 0

        # Apply regime tightening if bearish
        regime_mult = 1.0 - (ExitConfig.REGIME_TIGHTENING_PCT / 100) if regime_bearish else 1.0

        # Phase transitions (only advance, never retreat)
        current_phase = meta['phase']

        if current_phase == 'entry':
            if gain_atr >= ExitConfig.BREAKEVEN_LOCK_ATR:
                meta['phase'] = 'breakeven'
                meta['current_stop'] = entry_price  # Move to breakeven

        if current_phase in ['entry', 'breakeven']:
            if gain_atr >= ExitConfig.PROFIT_LOCK_ATR:
                meta['phase'] = 'profit_lock'
                profit_lock_stop = entry_price + (ExitConfig.PROFIT_LOCK_STOP_ATR * entry_atr)
                meta['current_stop'] = max(meta['current_stop'], profit_lock_stop)

        # Trailing stop calculation (after profit lock)
        if meta['phase'] == 'profit_lock':
            # Use current ATR for trailing, with regime adjustment
            trailing_mult = ExitConfig.TRAILING_ATR_MULT * regime_mult
            chandelier_stop = meta['highest_close'] - (trailing_mult * current_atr)

            # Stop only moves up
            if chandelier_stop > meta['current_stop']:
                meta['current_stop'] = chandelier_stop
                meta['phase'] = 'trailing'

        if meta['phase'] == 'trailing':
            trailing_mult = ExitConfig.TRAILING_ATR_MULT * regime_mult
            chandelier_stop = meta['highest_close'] - (trailing_mult * current_atr)
            meta['current_stop'] = max(meta['current_stop'], chandelier_stop)

        # Update bars below EMA50 counter
        if ema50 and current_close < ema50:
            meta['bars_below_ema50'] = meta.get('bars_below_ema50', 0) + 1
        else:
            meta['bars_below_ema50'] = 0

    def record_partial_taken(self, ticker):
        """Record that partial profit was taken"""
        if ticker in self.positions_metadata:
            self.positions_metadata[ticker]['partial_taken'] = True

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

def check_hard_stop(entry_price, current_price):
    """
    Check hard stop (10% max loss circuit breaker)

    This is the absolute backstop - no exceptions.
    """
    if entry_price <= 0 or current_price <= 0:
        return None

    pnl_pct = ((current_price - entry_price) / entry_price) * 100

    if pnl_pct <= -ExitConfig.HARD_STOP_PCT:
        return {
            'type': 'full_exit',
            'reason': 'hard_stop',
            'sell_pct': 100.0,
            'message': f'HARD STOP: {pnl_pct:.1f}% loss (limit: -{ExitConfig.HARD_STOP_PCT}%)'
        }

    return None


def check_trailing_stop(current_stop, current_close, phase):
    """
    Check if trailing/structure stop hit

    Uses close price, not intraday low, to filter noise.
    """
    if not current_stop or current_stop <= 0:
        return None

    if current_close <= current_stop:
        reason_map = {
            'entry': 'structure_stop',
            'breakeven': 'breakeven_stop',
            'profit_lock': 'profit_lock_stop',
            'trailing': 'chandelier_stop'
        }
        reason = reason_map.get(phase, 'trailing_stop')

        return {
            'type': 'full_exit',
            'reason': reason,
            'sell_pct': 100.0,
            'message': f'{reason.upper()}: Close ${current_close:.2f} <= Stop ${current_stop:.2f}'
        }

    return None


def check_dead_money(bars_below_ema50, pnl_pct, R, entry_price, current_price):
    """
    Check dead money filter

    Exit if:
    - 5+ consecutive closes below EMA50
    - Loss is less than 1R (not already deep in the hole)
    """
    if bars_below_ema50 < ExitConfig.DEAD_MONEY_BARS_BELOW:
        return None

    # Calculate loss in R terms
    loss_dollars = entry_price - current_price
    loss_R = loss_dollars / R if R > 0 else 0

    # Only trigger if not already at a large loss
    if loss_R <= ExitConfig.DEAD_MONEY_MAX_LOSS_R:
        return {
            'type': 'full_exit',
            'reason': 'dead_money',
            'sell_pct': 100.0,
            'message': f'DEAD MONEY: {bars_below_ema50} bars below EMA50, {pnl_pct:+.1f}%'
        }

    return None


def check_profit_take(entry_price, current_price, R, partial_taken):
    """
    Check profit take at 2R

    Sells 50% of position at 2R profit.
    Only triggers once per position.
    """
    if partial_taken:
        return None

    if R <= 0 or entry_price <= 0:
        return None

    gain = current_price - entry_price
    gain_R = gain / R

    if gain_R >= ExitConfig.PROFIT_TAKE_R_MULTIPLE:
        pnl_pct = (gain / entry_price) * 100
        return {
            'type': 'profit_take',
            'reason': 'profit_take_2R',
            'sell_pct': ExitConfig.PROFIT_TAKE_PCT,
            'message': f'PROFIT TAKE: +{gain_R:.1f}R (+{pnl_pct:.1f}%)'
        }

    return None


def check_remnant_position(remaining_shares, current_price):
    """
    Check for remnant position cleanup
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
    1. Hard Stop (10% max loss)
    2. Trailing/Structure Stop
    3. Dead Money Filter
    4. Profit Take (2R)
    5. Remnant Cleanup (handled in execution)

    Args:
        strategy: Lumibot Strategy instance
        current_date: Current datetime
        all_stock_data: Dict of {ticker: {'indicators': {...}, 'raw': DataFrame}}
        position_monitor: PositionMonitor instance

    Returns:
        list: Exit orders to execute
    """
    exit_orders = []
    positions = strategy.get_positions()

    # Check if in bearish regime (SPY < 50 SMA)
    regime_bearish = False
    if 'SPY' in all_stock_data:
        spy_data = all_stock_data['SPY']['indicators']
        spy_close = spy_data.get('close', 0)
        spy_sma50 = spy_data.get('sma50', 0)
        if spy_close > 0 and spy_sma50 > 0:
            regime_bearish = spy_close < spy_sma50

    for position in positions:
        ticker = position.symbol

        if ticker in account_broker_data.SKIP_SYMBOLS:
            continue

        broker_quantity = account_broker_data.get_position_quantity(position, ticker)
        if broker_quantity <= 0:
            continue

        # Get price data
        if ticker not in all_stock_data:
            continue

        data = all_stock_data[ticker]['indicators']
        raw_df = all_stock_data[ticker].get('raw')

        current_price = data.get('close', 0)
        if current_price <= 0:
            continue

        # Get ATR (use ATR10 if available, else ATR14)
        current_atr = stock_indicators.get_atr(raw_df, period=ExitConfig.ATR_PERIOD) if raw_df is not None else 0
        if current_atr <= 0:
            current_atr = data.get('atr_14', 0)

        # Get EMA50
        ema50 = data.get('ema50', 0)

        # Get metadata
        metadata = position_monitor.get_position_metadata(ticker)
        if not metadata:
            # Orphan position - skip (will be adopted by sync)
            continue

        # Get entry price (prefer broker avg, fallback to metadata)
        broker_entry_price = account_broker_data.get_broker_entry_price(position, strategy, ticker)
        entry_price = broker_entry_price if broker_entry_price > 0 else metadata.get('entry_price', 0)

        if entry_price <= 0:
            continue

        # Update position state
        position_monitor.update_position_state(
            ticker=ticker,
            current_close=current_price,
            current_atr=current_atr,
            ema50=ema50,
            regime_bearish=regime_bearish
        )

        # Refresh metadata after update
        metadata = position_monitor.get_position_metadata(ticker)

        # Calculate P&L
        pnl_dollars = (current_price - entry_price) * broker_quantity
        pnl_pct = ((current_price - entry_price) / entry_price * 100)

        # Get position state
        R = metadata.get('R', entry_price * 0.05)
        current_stop = metadata.get('current_stop', 0)
        phase = metadata.get('phase', 'entry')
        partial_taken = metadata.get('partial_taken', False)
        bars_below_ema50 = metadata.get('bars_below_ema50', 0)

        exit_signal = None

        # =====================================================================
        # PRIORITY 1: HARD STOP (10% max loss)
        # =====================================================================
        exit_signal = check_hard_stop(entry_price, current_price)

        # =====================================================================
        # PRIORITY 2: TRAILING/STRUCTURE STOP
        # =====================================================================
        if not exit_signal:
            exit_signal = check_trailing_stop(current_stop, current_price, phase)

        # =====================================================================
        # PRIORITY 3: DEAD MONEY FILTER
        # =====================================================================
        if not exit_signal:
            exit_signal = check_dead_money(bars_below_ema50, pnl_pct, R, entry_price, current_price)

        # =====================================================================
        # PRIORITY 4: PROFIT TAKE (2R)
        # =====================================================================
        if not exit_signal:
            exit_signal = check_profit_take(entry_price, current_price, R, partial_taken)

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
            exit_signal['phase'] = phase
            exit_signal['R'] = R
            exit_orders.append(exit_signal)

    return exit_orders


# =============================================================================
# EXIT ORDER EXECUTION
# =============================================================================

def execute_exit_orders(strategy, exit_orders, current_date, position_monitor, profit_tracker,
                        summary=None, recovery_manager=None):
    """
    Execute exit orders

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
        phase = order.get('phase', 'entry')

        # Calculate sell quantity
        if exit_type == 'profit_take':
            sell_quantity = int(broker_quantity * (sell_pct / 100))
        else:
            sell_quantity = broker_quantity

        if sell_quantity <= 0 or entry_price <= 0:
            continue

        # Calculate P&L for this exit
        pnl_per_share = current_price - entry_price
        total_pnl = pnl_per_share * sell_quantity
        pnl_pct = (pnl_per_share / entry_price * 100)

        # =====================================================================
        # PROFIT TAKE: Partial exit (50%)
        # =====================================================================
        if exit_type == 'profit_take':
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
                if Config.BACKTESTING:
                    stock_position_sizing.update_backtest_cash_for_sell(sell_quantity * current_price)
                continue

            # Normal profit take
            if summary:
                summary.add_profit_take(ticker, 1, sell_quantity, total_pnl, pnl_pct)

            # Record partial taken
            position_monitor.record_partial_taken(ticker)

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
            if Config.BACKTESTING:
                stock_position_sizing.update_backtest_cash_for_sell(sell_quantity * current_price)

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
            is_stop_loss = any(kw in reason for kw in ['stop', 'hard_stop', 'chandelier', 'structure', 'breakeven', 'dead_money'])
            if is_stop_loss and hasattr(strategy, 'regime_detector'):
                strategy.regime_detector.record_stop_loss(current_date, ticker, pnl_pct)

            # Trigger recovery mode re-lock on stop loss
            if is_stop_loss and recovery_manager is not None:
                recovery_manager.trigger_relock(current_date, f"stop_loss_{ticker}")

            sell_order = strategy.create_order(ticker, sell_quantity, 'sell')
            strategy.submit_order(sell_order)
            if Config.BACKTESTING:
                stock_position_sizing.update_backtest_cash_for_sell(sell_quantity * current_price)