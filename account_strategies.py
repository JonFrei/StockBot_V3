"""
SwingTradeStrategy - WITH CIRCUIT BREAKER & DAILY POSITION SYNC

Changes:
- Circuit breaker: 3 consecutive failures triggers pause + email alert
- Daily position sync: Broker is source of truth, runs every iteration
- Missing entry price collection and email notification
- Paused state with manual intervention required
"""

from lumibot.strategies import Strategy
from config import Config

import stock_data
import stock_signals
import stock_position_sizing
import account_profit_tracking
import stock_position_monitoring
from stock_rotation import StockRotator, should_rotate

from server_recovery import save_state_safe, load_state_safe
from account_drawdown_protection import MarketRegimeDetector
from account_recovery_mode import RecoveryModeManager
import account_broker_data
from account_profit_tracking import get_summary, reset_summary

from lumibot.brokers import Alpaca
import time
from datetime import datetime

broker = Alpaca(Config.get_alpaca_config())

CAUTION_MIN_PROFIT_PCT = 0.0
CONSECUTIVE_FAILURE_THRESHOLD = 3


class ConsecutiveFailureTracker:
    """
    Tracks consecutive failures across trading iterations.
    Triggers circuit breaker after threshold is reached.
    """

    def __init__(self, threshold=CONSECUTIVE_FAILURE_THRESHOLD):
        self.threshold = threshold
        self.consecutive_failures = 0
        self.failure_history = []  # List of (timestamp, error_context, error_message)
        self.is_paused = False
        self.paused_at = None
        self.pause_reason = None

    def record_failure(self, context, error):
        """Record a failure and check if threshold reached"""
        self.consecutive_failures += 1
        self.failure_history.append({
            'timestamp': datetime.now(),
            'context': context,
            'error': str(error)
        })

        # Keep only recent failures
        if len(self.failure_history) > 10:
            self.failure_history = self.failure_history[-10:]

        print(f"[CIRCUIT BREAKER] Failure {self.consecutive_failures}/{self.threshold}: {context} - {error}")

        return self.consecutive_failures >= self.threshold

    def record_success(self):
        """Reset failure counter on successful iteration"""
        if self.consecutive_failures > 0:
            print(f"[CIRCUIT BREAKER] Success - resetting failure counter (was {self.consecutive_failures})")
        self.consecutive_failures = 0

    def trigger_pause(self, reason):
        """Enter paused state"""
        self.is_paused = True
        self.paused_at = datetime.now()
        self.pause_reason = reason

    def get_recent_failures(self):
        """Get recent failure details for email"""
        return self.failure_history[-self.threshold:]


def sync_positions_with_broker(strategy, current_date, position_monitor):
    """
    Daily position sync - Broker is source of truth.

    Runs at start of each iteration to:
    1. Adopt orphaned positions (in broker, not in metadata)
    2. Remove stale metadata (in metadata, not in broker)
    3. Collect positions with missing entry prices

    Args:
        strategy: Lumibot Strategy instance
        current_date: Current datetime
        position_monitor: PositionMonitor instance

    Returns:
        dict: {
            'synced': bool,
            'orphaned_adopted': list of tickers,
            'stale_removed': list of tickers,
            'missing_entry_prices': list of position dicts
        }
    """
    result = {
        'synced': False,
        'orphaned_adopted': [],
        'stale_removed': [],
        'missing_entry_prices': []
    }

    try:
        print(f"\n{'=' * 60}")
        print(f"🔄 DAILY POSITION SYNC - {current_date.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'=' * 60}")

        # Get broker positions
        broker_positions = strategy.get_positions()
        broker_tickers = {}
        for p in broker_positions:
            qty = account_broker_data.get_position_quantity(p, p.symbol)
            if qty > 0:
                broker_tickers[p.symbol] = p

        # Get local metadata
        local_tickers = set(position_monitor.positions_metadata.keys())

        print(f"📊 Broker positions: {len(broker_tickers)}")
        print(f"📊 Local metadata: {len(local_tickers)}")

        # === ADOPT ORPHANED POSITIONS ===
        # Positions in broker but not in local metadata
        orphaned = set(broker_tickers.keys()) - local_tickers

        if orphaned:
            print(f"\n⚠️  ORPHANED POSITIONS: {len(orphaned)}")
            print(f"{'─' * 60}")

            for ticker in orphaned:
                position = broker_tickers[ticker]
                quantity = account_broker_data.get_position_quantity(position, ticker)
                entry_price = account_broker_data.get_broker_entry_price(position, strategy, ticker)

                try:
                    current_price = strategy.get_last_price(ticker)
                except:
                    current_price = entry_price if entry_price > 0 else 0

                # Track position with whatever data we have
                position_monitor.positions_metadata[ticker] = {
                    'entry_date': current_date,
                    'entry_signal': 'recovered_orphan',
                    'entry_score': 0,
                    'entry_price': entry_price if entry_price > 0 else current_price,
                    'highest_price': max(entry_price, current_price) if entry_price > 0 else current_price,
                    'local_max': max(entry_price, current_price) if entry_price > 0 else current_price,
                    'profit_level': 0,
                    'tier1_lock_price': None,
                    'level_1_lock_price': None,
                    'level_2_lock_price': None,
                    'kill_switch_active': False,
                    'peak_price': None
                }

                result['orphaned_adopted'].append(ticker)

                if entry_price > 0:
                    print(f"   ✅ {ticker}: ADOPTED - {quantity} shares @ ${entry_price:.2f}")
                else:
                    print(f"   ⚠️  {ticker}: ADOPTED - {quantity} shares (NO ENTRY PRICE)")
                    result['missing_entry_prices'].append({
                        'ticker': ticker,
                        'quantity': quantity,
                        'current_price': current_price,
                        'market_value': quantity * current_price if current_price > 0 else 0,
                        'issue': 'Missing entry price (orphaned position)'
                    })

            print(f"{'─' * 60}")

        # === REMOVE STALE METADATA ===
        # Positions in local metadata but not in broker
        stale = local_tickers - set(broker_tickers.keys())

        if stale:
            print(f"\n🧹 STALE METADATA: {len(stale)}")
            print(f"{'─' * 60}")

            for ticker in stale:
                print(f"   🗑️  {ticker}: Position closed at broker - removing metadata")
                del position_monitor.positions_metadata[ticker]
                result['stale_removed'].append(ticker)

            print(f"{'─' * 60}")

        # === CHECK EXISTING POSITIONS FOR MISSING ENTRY PRICES ===
        for ticker, position in broker_tickers.items():
            if ticker in result['orphaned_adopted']:
                continue  # Already handled above

            metadata = position_monitor.positions_metadata.get(ticker, {})
            entry_price = metadata.get('entry_price', 0)

            # If metadata has no entry price, try to get from broker
            if not entry_price or entry_price <= 0:
                broker_entry = account_broker_data.get_broker_entry_price(position, strategy, ticker)

                if broker_entry > 0:
                    # Update metadata with broker entry price
                    if ticker in position_monitor.positions_metadata:
                        position_monitor.positions_metadata[ticker]['entry_price'] = broker_entry
                        print(f"   📝 {ticker}: Updated entry price from broker: ${broker_entry:.2f}")
                else:
                    # Still no entry price
                    quantity = account_broker_data.get_position_quantity(position, ticker)
                    try:
                        current_price = strategy.get_last_price(ticker)
                    except:
                        current_price = 0

                    result['missing_entry_prices'].append({
                        'ticker': ticker,
                        'quantity': quantity,
                        'current_price': current_price,
                        'market_value': quantity * current_price if current_price > 0 else 0,
                        'issue': 'Missing entry price'
                    })

        # === SUMMARY ===
        print(f"\n📋 SYNC SUMMARY:")
        print(f"   Orphaned Adopted: {len(result['orphaned_adopted'])}")
        print(f"   Stale Removed: {len(result['stale_removed'])}")
        print(f"   Missing Entry Prices: {len(result['missing_entry_prices'])}")

        if not result['orphaned_adopted'] and not result['stale_removed'] and not result['missing_entry_prices']:
            print(f"   ✅ All positions in sync!")

        print(f"{'=' * 60}\n")

        result['synced'] = True

        # Save state if any changes were made
        if result['orphaned_adopted'] or result['stale_removed']:
            save_state_safe(strategy)

    except Exception as e:
        print(f"\n❌ POSITION SYNC ERROR: {e}")
        import traceback
        traceback.print_exc()
        result['synced'] = False

    return result


def enter_paused_state(strategy, failure_tracker, execution_tracker=None):
    """
    Enter paused state after circuit breaker triggers.
    Sends alert email and waits for manual intervention.

    Args:
        strategy: Lumibot Strategy instance
        failure_tracker: ConsecutiveFailureTracker instance
        execution_tracker: ExecutionTracker instance (optional)
    """
    import account_email_notifications

    current_date = strategy.get_datetime()
    failure_tracker.trigger_pause("Circuit breaker triggered - consecutive failures exceeded threshold")

    print(f"\n{'=' * 80}")
    print(f"🚨 CIRCUIT BREAKER TRIGGERED - BOT PAUSED")
    print(f"{'=' * 80}")
    print(f"Consecutive failures: {failure_tracker.consecutive_failures}")
    print(f"Threshold: {failure_tracker.threshold}")
    print(f"Paused at: {failure_tracker.paused_at}")
    print(f"\nRecent failures:")
    for f in failure_tracker.get_recent_failures():
        print(f"   [{f['timestamp'].strftime('%H:%M:%S')}] {f['context']}: {f['error']}")
    print(f"\n⏸️  Bot is now PAUSED. Manual intervention required.")
    print(f"   Restart the bot via Railway dashboard to resume.")
    print(f"{'=' * 80}\n")

    # Send alert email
    try:
        account_email_notifications.send_circuit_breaker_alert_email(
            failure_tracker=failure_tracker,
            current_date=current_date
        )
    except Exception as e:
        print(f"[EMAIL] Failed to send circuit breaker alert: {e}")

    # Enter infinite pause loop
    # Health check server keeps running so Railway doesn't kill the container
    print("[PAUSED] Entering pause loop. Health check server remains active.")
    print("[PAUSED] To resume, restart the bot via Railway dashboard.")

    pause_log_interval = 300  # Log every 5 minutes
    last_log_time = time.time()

    while True:
        time.sleep(60)  # Check every minute

        # Periodic logging so we know it's still alive
        if time.time() - last_log_time >= pause_log_interval:
            elapsed = datetime.now() - failure_tracker.paused_at
            hours, remainder = divmod(int(elapsed.total_seconds()), 3600)
            minutes, _ = divmod(remainder, 60)
            print(f"[PAUSED] Still paused. Elapsed: {hours}h {minutes}m. Waiting for manual restart...")
            last_log_time = time.time()


class SwingTradeStrategy(Strategy):

    def initialize(self, send_emails=True):
        if Config.BACKTESTING:
            self.sleeptime = "1D"
        else:
            self.sleeptime = "10M"

        self.tickers = self.parameters.get("tickers", [])
        self.last_trade_date = None

        # Initialize circuit breaker (disabled in backtesting)
        self.failure_tracker = ConsecutiveFailureTracker(threshold=CONSECUTIVE_FAILURE_THRESHOLD)

        # Initialize components
        self.position_monitor = stock_position_monitoring.PositionMonitor(self)
        self.regime_detector = MarketRegimeDetector()
        self.recovery_manager = RecoveryModeManager()
        self.signal_processor = stock_signals.SignalProcessor()

        # Initialize rotation system FIRST (before profit tracker)
        self.stock_rotator = StockRotator(profit_tracker=None)

        # Initialize profit tracker WITH rotation reference
        self.profit_tracker = account_profit_tracking.ProfitTracker(self, stock_rotator=self.stock_rotator)

        # Now set the profit_tracker reference in rotator
        self.stock_rotator.profit_tracker = self.profit_tracker

        self.order_logger = account_profit_tracking.OrderLogger(self)

        print(f"\n{'=' * 60}")
        print(f"🤖 SwingTradeStrategy Initialized")
        print(f"   Tickers: {len(self.tickers)} | Mode: {'BACKTEST' if Config.BACKTESTING else 'LIVE'}")
        print(f"   Rotation: 5-tier streak-based system")
        print(f"   Safeguards: Portfolio DD (15%) + Market Crisis + SPY<200")
        if not Config.BACKTESTING:
            print(f"   Circuit Breaker: {CONSECUTIVE_FAILURE_THRESHOLD} consecutive failures → pause")
        print(f"{'=' * 60}\n")

    def before_starting_trading(self):
        if Config.BACKTESTING:
            return
        load_state_safe(self)

    def on_trading_iteration(self):
        import account_email_notifications
        execution_tracker = account_email_notifications.ExecutionTracker()
        summary = reset_summary()

        # Check if paused (shouldn't happen but safety check)
        if not Config.BACKTESTING and self.failure_tracker.is_paused:
            print("[PAUSED] Bot is paused. Skipping iteration.")
            return

        try:
            # === MARKET OPEN CHECK (Live Only) ===
            if not Config.BACKTESTING:
                try:
                    if not self.broker.is_market_open():
                        return
                except:
                    pass

                if account_broker_data.has_traded_today(self, self.last_trade_date):
                    return

                if not account_broker_data.is_within_trading_window(self):
                    return

            current_date = self.get_datetime()

            if not Config.BACKTESTING:
                self.last_trade_date = current_date.date()

            summary.set_context(current_date, self.portfolio_value, self.get_cash())

            # =============================================================
            # REFRESH ALPACA POSITION CACHE (Direct API)
            # =============================================================
            if not Config.BACKTESTING:
                account_broker_data.refresh_position_cache()

            # =============================================================
            # DAILY POSITION SYNC (Broker is Source of Truth)
            # =============================================================
            if not Config.BACKTESTING:
                try:
                    sync_result = sync_positions_with_broker(
                        strategy=self,
                        current_date=current_date,
                        position_monitor=self.position_monitor
                    )

                    # Send email if there are missing entry prices
                    if sync_result['missing_entry_prices']:
                        try:
                            account_email_notifications.send_missing_entry_prices_email(
                                positions=sync_result['missing_entry_prices'],
                                current_date=current_date
                            )
                        except Exception as e:
                            print(f"[EMAIL] Failed to send missing entry prices email: {e}")

                        # Add to summary warnings
                        for pos in sync_result['missing_entry_prices']:
                            summary.add_warning(f"{pos['ticker']}: {pos['issue']} - will be skipped")

                except Exception as e:
                    # Position sync failure is critical
                    should_pause = self.failure_tracker.record_failure("Position Sync", e)
                    execution_tracker.add_error("Position Sync", e)

                    if should_pause:
                        enter_paused_state(self, self.failure_tracker, execution_tracker)
                        return

                    # Continue with caution if not at threshold
                    summary.add_error(f"Position sync failed: {e}")

            # =============================================================
            # UPDATE PORTFOLIO VALUE FOR DRAWDOWN TRACKING
            # =============================================================
            self.regime_detector.update_portfolio_value(current_date, self.portfolio_value)

            # =============================================================
            # FETCH DATA
            # =============================================================
            try:
                all_tickers = list(set(self.tickers + ['SPY'] + [p.symbol for p in self.get_positions()]))
                all_stock_data = stock_data.process_data(all_tickers, current_date)

                if 'SPY' in all_stock_data:
                    spy_ind = all_stock_data['SPY']['indicators']
                    spy_raw = all_stock_data['SPY'].get('raw')

                    spy_close = spy_ind['close']
                    spy_20_ema = spy_ind.get('ema20', 0)
                    spy_50_sma = spy_ind.get('sma50', spy_ind.get('ema50', 0))
                    spy_200_sma = spy_ind['sma200']

                    # Get volume data
                    spy_volume = None
                    spy_avg_volume = None
                    if spy_raw is not None and len(spy_raw) >= 2:
                        spy_volume = spy_raw['volume'].iloc[-1]
                        spy_avg_volume = spy_ind.get('avg_volume', spy_raw['volume'].iloc[-20:].mean() if len(
                            spy_raw) >= 20 else None)
                        spy_prev_close = spy_raw['close'].iloc[-2]
                    else:
                        spy_prev_close = None

                    # Update regime detector with new simplified interface
                    self.regime_detector.update_spy(
                        date=current_date,
                        spy_close=spy_close,
                        spy_20_ema=spy_20_ema,
                        spy_50_sma=spy_50_sma,
                        spy_200_sma=spy_200_sma,
                        spy_volume=spy_volume,
                        spy_avg_volume=spy_avg_volume
                    )

                    # Update recovery manager
                    self.recovery_manager.update_spy_data(current_date, spy_close, spy_prev_close)
                    self.recovery_manager.update_breadth(all_stock_data)

            except Exception as e:
                summary.add_error(f"Data fetch failed: {e}")
                execution_tracker.add_error("Data Fetch", e)

                if not Config.BACKTESTING:
                    should_pause = self.failure_tracker.record_failure("Data Fetch", e)
                    if should_pause:
                        enter_paused_state(self, self.failure_tracker, execution_tracker)
                        return

                execution_tracker.complete('FAILED')
                summary.print_summary()
                return

            # =============================================================
            # REGIME DETECTION (includes portfolio drawdown check)
            # =============================================================
            try:
                # Check if recovery mode is active
                spy_below_200 = self.regime_detector._is_spy_below_200()
                recovery_result = self.recovery_manager.evaluate(current_date, spy_below_200)
                recovery_mode_active = recovery_result.get('recovery_mode_active', False)

                # Get regime result (pass recovery mode status)
                regime_result = self.regime_detector.detect_regime(
                    current_date=current_date,
                    recovery_mode_active=recovery_mode_active
                )

                # Handle recovery mode override for display
                if regime_result['action'] == 'recovery_override':
                    regime_result['position_size_multiplier'] = recovery_result['position_multiplier']
                    regime_result['max_positions'] = recovery_result['max_positions']
                    regime_result['recovery_profit_target'] = recovery_result['profit_target']

                summary.set_regime(
                    regime_result['action'],
                    regime_result['reason'],
                    regime_result['position_size_multiplier']
                )

                # =============================================================
                # HANDLE EXIT ALL - Crisis or Portfolio Drawdown
                # =============================================================

                if regime_result.get('exit_all', False):
                    positions = self.get_positions()
                    exit_count = 0
                    exit_reason = 'crisis_exit' if regime_result[
                                                       'action'] == 'crisis_exit' else 'portfolio_drawdown_exit'

                    for position in positions:
                        ticker = position.symbol
                        qty = int(position.quantity)
                        if qty > 0:
                            try:
                                entry_price = account_broker_data.get_broker_entry_price(position, self, ticker)
                                current_price = self.get_last_price(ticker)
                                pnl_dollars = (current_price - entry_price) * qty if entry_price > 0 else 0
                                pnl_pct = ((current_price - entry_price) / entry_price * 100) if entry_price > 0 else 0

                                summary.add_exit(ticker, qty, pnl_dollars, pnl_pct, exit_reason)

                                # Record trade
                                metadata = self.position_monitor.get_position_metadata(ticker)
                                entry_signal = metadata.get('entry_signal', 'unknown') if metadata else 'unknown'
                                entry_score = metadata.get('entry_score', 0) if metadata else 0

                                self.profit_tracker.record_trade(
                                    ticker=ticker,
                                    quantity_sold=qty,
                                    entry_price=entry_price,
                                    exit_price=current_price,
                                    exit_date=current_date,
                                    entry_signal=entry_signal,
                                    exit_signal={'reason': exit_reason},
                                    entry_score=entry_score
                                )

                                self.position_monitor.clean_position_metadata(ticker)
                                sell_order = self.create_order(ticker, qty, 'sell')
                                self.submit_order(sell_order)
                                exit_count += 1

                            except Exception as e:
                                summary.add_error(f"{exit_reason} {ticker} failed: {e}")

                    execution_tracker.record_action('exits', count=exit_count)

                    if regime_result['action'] == 'portfolio_drawdown_exit':
                        execution_tracker.record_action('drawdown_protection', count=1)

                    # Success - reset failure counter
                    if not Config.BACKTESTING:
                        self.failure_tracker.record_success()

                    execution_tracker.complete('SUCCESS')
                    summary.print_summary()

                    if not Config.BACKTESTING:
                        account_email_notifications.send_daily_summary_email(self, current_date, execution_tracker)

                    save_state_safe(self)
                    return

                # =============================================================
                # HANDLE LOCKOUT/BLOCK - No new entries
                # =============================================================
                if not regime_result['allow_new_entries']:
                    # Success - reset failure counter
                    if not Config.BACKTESTING:
                        self.failure_tracker.record_success()

                    execution_tracker.complete('SUCCESS')
                    summary.print_summary()

                    if not Config.BACKTESTING:
                        account_email_notifications.send_daily_summary_email(self, current_date, execution_tracker)

                    save_state_safe(self)
                    return

            except Exception as e:
                summary.add_error(f"Regime detection failed: {e}")

                if not Config.BACKTESTING:
                    should_pause = self.failure_tracker.record_failure("Regime Detection", e)
                    if should_pause:
                        enter_paused_state(self, self.failure_tracker, execution_tracker)
                        return

                regime_result = {
                    'action': 'error_fallback',
                    'position_size_multiplier': 0.5,
                    'allow_new_entries': True,
                    'exit_all': False,
                    'reason': f'Safeguard error: {e}'
                }

            # =============================================================
            # CHECK EXITS (normal position monitoring)
            # =============================================================
            try:
                exit_orders = stock_position_monitoring.check_positions_for_exits(
                    strategy=self,
                    current_date=current_date,
                    all_stock_data=all_stock_data,
                    position_monitor=self.position_monitor
                )

                stock_position_monitoring.execute_exit_orders(
                    strategy=self,
                    exit_orders=exit_orders,
                    current_date=current_date,
                    position_monitor=self.position_monitor,
                    profit_tracker=self.profit_tracker,
                    summary=summary,
                    recovery_manager=self.recovery_manager
                )

                if exit_orders:
                    execution_tracker.record_action('exits', count=len(exit_orders))

            except Exception as e:
                summary.add_error(f"Exit processing failed: {e}")
                execution_tracker.add_error("Exit Processing", e)

                if not Config.BACKTESTING:
                    should_pause = self.failure_tracker.record_failure("Exit Processing", e)
                    if should_pause:
                        enter_paused_state(self, self.failure_tracker, execution_tracker)
                        return

            # =============================================================
            # RECOVERY POSITION LIMIT CHECK
            # =============================================================
            num_positions = len(self.get_positions())
            if regime_result['action'] == 'recovery_override':
                max_positions = regime_result.get('max_positions', 5)
                if num_positions >= max_positions:
                    summary.add_warning(f"Recovery mode: at max {max_positions} positions")

                    if not Config.BACKTESTING:
                        self.failure_tracker.record_success()

                    execution_tracker.complete('SUCCESS')
                    summary.print_summary()
                    if not Config.BACKTESTING:
                        account_email_notifications.send_daily_summary_email(self, current_date, execution_tracker)
                    save_state_safe(self)
                    return

            # =============================================================
            # WEEKLY ROTATION EVALUATION
            # =============================================================
            if should_rotate(self.stock_rotator, current_date, frequency='weekly'):
                self.stock_rotator.evaluate_stocks(self.tickers, current_date)
                execution_tracker.record_action('rotation', count=1)

            # =============================================================
            # SCAN SIGNALS - ALL tickers can trade (frozen gets 0.1x)
            # =============================================================
            all_opportunities = []

            # Get current holdings to avoid buying into existing positions
            current_holdings = {p.symbol for p in self.get_positions()}

            for ticker in all_tickers:
                try:
                    if ticker not in all_stock_data:
                        continue

                    # Get rotation tier and multiplier
                    tier = self.stock_rotator.get_tier(ticker)
                    rotation_mult = self.stock_rotator.get_multiplier(ticker)

                    data = all_stock_data[ticker]['indicators']
                    vol_metrics = data.get('volatility_metrics', {})
                    if not vol_metrics.get('allow_trading', True):
                        continue

                    # Relative strength filter
                    raw_df = data.get('raw')
                    if raw_df is not None and len(raw_df) >= 20:
                        try:
                            stock_current = data['close']
                            stock_past = float(raw_df['close'].iloc[-21]) if len(raw_df) >= 21 else float(
                                raw_df['close'].iloc[0])
                            rs_result = self.regime_detector.check_relative_strength(stock_current, stock_past)
                            if not rs_result['passes']:
                                summary.add_skip(ticker, f"Weak RS: {rs_result['relative_strength']:+.1f}%")
                                continue
                        except:
                            pass

                    signal_result = self.signal_processor.process_ticker(ticker, data, None)

                    if signal_result['action'] == 'buy':
                        summary.add_signal(ticker, signal_result['signal_type'], signal_result['score'])
                        all_opportunities.append({
                            'ticker': ticker,
                            'signal_type': signal_result['signal_type'],
                            'signal_data': signal_result['signal_data'],
                            'score': signal_result['score'],
                            'all_scores': signal_result['all_scores'],
                            'data': data,
                            'vol_metrics': vol_metrics,
                            'rotation_mult': rotation_mult,
                            'rotation_tier': tier,
                            'source': 'scored'
                        })
                except:
                    continue

            # =============================================================
            # POSITION SIZING
            # =============================================================
            if not all_opportunities:
                if not Config.BACKTESTING:
                    self.failure_tracker.record_success()

                execution_tracker.complete('SUCCESS')
                summary.print_summary()
                if not Config.BACKTESTING:
                    account_email_notifications.send_daily_summary_email(self, current_date, execution_tracker)
                save_state_safe(self)
                return

            try:
                portfolio_context = stock_position_sizing.create_portfolio_context(self)

                if portfolio_context['deployable_cash'] <= 0:
                    summary.add_warning("No deployable cash")

                    if not Config.BACKTESTING:
                        self.failure_tracker.record_success()

                    execution_tracker.complete('SUCCESS')
                    summary.print_summary()
                    save_state_safe(self)
                    return

                if portfolio_context['available_slots'] <= 0:
                    summary.add_warning("No available slots")

                    if not Config.BACKTESTING:
                        self.failure_tracker.record_success()

                    execution_tracker.complete('SUCCESS')
                    summary.print_summary()
                    save_state_safe(self)
                    return

                sizing_opportunities = [
                    {
                        'ticker': opp['ticker'],
                        'data': opp['data'],
                        'score': opp['score'],
                        'signal_type': opp['signal_type'],
                        'vol_metrics': opp['vol_metrics'],
                        'rotation_mult': opp['rotation_mult']
                    }
                    for opp in all_opportunities if opp['score'] >= 60
                ]

                regime_multiplier = regime_result['position_size_multiplier']
                allocations = stock_position_sizing.calculate_position_sizes(
                    sizing_opportunities,
                    portfolio_context,
                    regime_multiplier,
                    verbose=False
                )

                if not allocations:
                    summary.add_warning("No positions met size requirements")

                    if not Config.BACKTESTING:
                        self.failure_tracker.record_success()

                    execution_tracker.complete('SUCCESS')
                    summary.print_summary()
                    save_state_safe(self)
                    return

            except Exception as e:
                summary.add_error(f"Position sizing failed: {e}")
                execution_tracker.add_error("Position Sizing", e)

                if not Config.BACKTESTING:
                    should_pause = self.failure_tracker.record_failure("Position Sizing", e)
                    if should_pause:
                        enter_paused_state(self, self.failure_tracker, execution_tracker)
                        return

                execution_tracker.complete('FAILED')
                summary.print_summary()
                return

            # =============================================================
            # EXECUTE BUYS
            # =============================================================
            buy_failures = 0
            for alloc in allocations:
                try:
                    ticker = alloc['ticker']
                    quantity = alloc['quantity']
                    cost = alloc['cost']
                    price = alloc['price']
                    signal_type = alloc['signal_type']
                    signal_score = alloc['signal_score']
                    rotation_mult = alloc.get('rotation_mult', 1.0)

                    # Get tier for logging
                    tier = self.stock_rotator.get_tier(ticker)
                    tier_emoji = {'premium': '🥇', 'active': '🥈', 'probation': '⚠️',
                                  'rehabilitation': '🔄', 'frozen': '❄️'}.get(tier, '❓')

                    summary.add_entry(ticker, quantity, price, cost, f"{signal_type} {tier_emoji}", signal_score)
                    self.position_monitor.track_position(ticker, current_date, signal_type, entry_score=signal_score)

                    order = self.create_order(ticker, quantity, 'buy')
                    self.submit_order(order)

                    if hasattr(self, 'order_logger'):
                        self.order_logger.log_order(
                            ticker=ticker,
                            side='buy',
                            quantity=quantity,
                            signal_type=signal_type,
                            award=tier,
                            quality_score=signal_score
                        )

                    execution_tracker.record_action('entries', count=1)

                except Exception as e:
                    summary.add_error(f"Buy {ticker} failed: {e}")
                    execution_tracker.add_error(f"Buy Order ({ticker})", e)
                    buy_failures += 1
                    continue

            # Check if all buys failed
            if not Config.BACKTESTING and buy_failures == len(allocations) and len(allocations) > 0:
                should_pause = self.failure_tracker.record_failure("All Buy Orders Failed",
                                                                   f"{buy_failures}/{len(allocations)} orders failed")
                if should_pause:
                    enter_paused_state(self, self.failure_tracker, execution_tracker)
                    return

            # Success - reset failure counter
            if not Config.BACKTESTING:
                self.failure_tracker.record_success()

            execution_tracker.complete('SUCCESS')
            summary.print_summary()

            if not Config.BACKTESTING:
                account_email_notifications.send_daily_summary_email(self, current_date, execution_tracker)
                save_state_safe(self)

        except Exception as e:
            summary.add_error(f"Fatal: {e}")
            summary.print_summary()
            execution_tracker.add_error("Trading Iteration", e)
            execution_tracker.complete('FAILED')

            if not Config.BACKTESTING:
                # Record failure and check threshold
                should_pause = self.failure_tracker.record_failure("Unhandled Exception", e)

                account_email_notifications.send_daily_summary_email(self, self.get_datetime(), execution_tracker)

                if should_pause:
                    enter_paused_state(self, self.failure_tracker, execution_tracker)
                    return

            raise

    def on_strategy_end(self):
        self.profit_tracker.display_final_summary(
            stock_rotator=self.stock_rotator,
            regime_detector=self.regime_detector,
            recovery_manager=self.recovery_manager
        )
        return 0