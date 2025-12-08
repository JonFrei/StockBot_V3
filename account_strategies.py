"""
SwingTradeStrategy - WITH CIRCUIT BREAKER & DAILY POSITION SYNC

Changes:
- Circuit breaker: 3 consecutive failures triggers pause + email alert
- Daily position sync: Broker is source of truth, runs every iteration
- Missing entry price collection and email notification
- Paused state with manual intervention required
- UPDATED: Removed time-based trading window for live trading
- UPDATED: Per-stock daily tracking (no stock traded more than once per day)
- UPDATED: Daily traded stocks persisted to database for crash recovery
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
from account_profit_tracking import get_summary, reset_summary, update_end_of_day_metrics

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
    1. Adopt orphaned broker positions (positions we don't have metadata for)
    2. Remove stale metadata (for positions no longer at broker)
    3. Collect positions with missing entry prices for notification
    """
    result = {
        'synced': False,
        'orphaned_adopted': [],
        'stale_removed': [],
        'missing_entry_prices': []
    }

    try:
        print(f"\n{'=' * 60}")
        print(f"🔄 DAILY POSITION SYNC - {current_date.strftime('%Y-%m-%d %H:%M')}")
        print(f"{'=' * 60}")

        # Get broker positions
        broker_positions = strategy.get_positions()
        broker_tickers = set()

        for position in broker_positions:
            ticker = position.symbol
            if ticker in account_broker_data.SKIP_SYMBOLS:
                continue
            broker_tickers.add(ticker)

        # Get our tracked positions
        tracked_tickers = set(position_monitor.positions_metadata.keys())

        print(f"   Broker positions: {len(broker_tickers)}")
        print(f"   Tracked positions: {len(tracked_tickers)}")

        # === ADOPT ORPHANED POSITIONS ===
        orphaned = broker_tickers - tracked_tickers
        for ticker in orphaned:
            print(f"   📥 Adopting orphaned position: {ticker}")

            # Try to get entry price from broker
            position = next((p for p in broker_positions if p.symbol == ticker), None)
            entry_price = account_broker_data.get_broker_entry_price(position, strategy, ticker)

            position_monitor.track_position(
                ticker=ticker,
                entry_date=current_date,
                entry_signal='adopted_orphan',
                entry_score=0,
                entry_price=entry_price if entry_price > 0 else None
            )
            result['orphaned_adopted'].append(ticker)

        # === REMOVE STALE METADATA ===
        stale = tracked_tickers - broker_tickers
        for ticker in stale:
            print(f"   🗑️ Removing stale metadata: {ticker}")
            position_monitor.clean_position_metadata(ticker)
            result['stale_removed'].append(ticker)

        # === CHECK FOR MISSING ENTRY PRICES ===
        for position in broker_positions:
            ticker = position.symbol
            if ticker in account_broker_data.SKIP_SYMBOLS:
                continue

            metadata = position_monitor.get_position_metadata(ticker)
            entry_price = metadata.get('entry_price') if metadata else None

            if not entry_price or entry_price <= 0:
                # Try to get from broker
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


'''
def update_end_of_day_metrics(strategy, current_date, regime_result):
    """Update daily_metrics and signal_performance tables at end of iteration"""
    try:
        from database import get_database
        from collections import defaultdict

        db = get_database()

        # Gather daily metrics data
        portfolio_value = strategy.portfolio_value
        cash_balance = strategy.get_cash()
        positions = strategy.get_positions()
        num_positions = len(positions)

        # Calculate unrealized P&L
        unrealized_pnl = 0
        for pos in positions:
            if hasattr(pos, 'unrealized_pl'):
                unrealized_pnl += float(pos.unrealized_pl or 0)

        # Get today's trades and calculate realized P&L
        closed_trades = strategy.profit_tracker.get_closed_trades()
        today_trades = [t for t in closed_trades if
                        t['exit_date'].date() == current_date.date()] if closed_trades else []
        num_trades = len(today_trades)
        realized_pnl = sum(t['pnl_dollars'] for t in today_trades)

        # Calculate overall win rate
        if closed_trades:
            winners = [t for t in closed_trades if t['pnl_dollars'] > 0]
            win_rate = (len(winners) / len(closed_trades)) * 100
        else:
            win_rate = 0

        # Get SPY close and regime
        spy_close = regime_result.get('spy_close', 0) if regime_result else 0
        market_regime = regime_result.get('action', 'unknown') if regime_result else 'unknown'

        # Save daily metrics
        db.save_daily_metrics(
            date=current_date.date(),
            portfolio_value=portfolio_value,
            cash_balance=cash_balance,
            num_positions=num_positions,
            num_trades=num_trades,
            realized_pnl=realized_pnl,
            unrealized_pnl=unrealized_pnl,
            win_rate=win_rate,
            spy_close=spy_close,
            market_regime=market_regime
        )

        # Update signal performance
        if closed_trades:
            signal_stats = defaultdict(lambda: {'trades': 0, 'wins': 0, 'pnl': 0})
            for trade in closed_trades:
                signal = trade['entry_signal']
                signal_stats[signal]['trades'] += 1
                signal_stats[signal]['pnl'] += trade['pnl_dollars']
                if trade['pnl_dollars'] > 0:
                    signal_stats[signal]['wins'] += 1

            for signal_name, stats in signal_stats.items():
                db.update_signal_performance(
                    signal_name=signal_name,
                    total_trades=stats['trades'],
                    wins=stats['wins'],
                    total_pnl=stats['pnl']
                )

    except Exception as e:
        print(f"[METRICS] Error updating end-of-day metrics: {e}")

'''


def enter_paused_state(strategy, failure_tracker, execution_tracker=None):
    """
    Enter paused state after circuit breaker triggers.
    Sends alert email and waits for manual intervention.
    """
    import account_email_notifications

    failure_tracker.trigger_pause(f"{failure_tracker.consecutive_failures} consecutive failures")

    print(f"\n{'=' * 80}")
    print(f"🚨 CIRCUIT BREAKER TRIGGERED - BOT PAUSED")
    print(f"{'=' * 80}")
    print(f"Failures: {failure_tracker.consecutive_failures}/{failure_tracker.threshold}")
    print(f"Paused at: {failure_tracker.paused_at}")
    print(f"\nRecent failures:")
    for f in failure_tracker.get_recent_failures():
        print(f"  - {f['timestamp']}: {f['context']} - {f['error'][:100]}")
    print(f"{'=' * 80}\n")

    # Send circuit breaker email
    try:
        account_email_notifications.send_circuit_breaker_alert_email(
            failure_tracker=failure_tracker,
            current_date=datetime.now()
        )
    except Exception as e:
        print(f"[EMAIL] Failed to send circuit breaker email: {e}")

    # Enter infinite wait loop
    print("[PAUSED] Bot is now paused. Manual intervention required.")
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
            self.sleeptime = "30M"

        self.tickers = self.parameters.get("tickers", [])
        self.last_trade_date = None

        # Daily traded stocks tracker (live trading only)
        # This is loaded from DB at start of each iteration
        self.daily_traded_stocks = set()

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
        self._current_regime_result = None  # Store for metrics tracking

        print(f"\n{'=' * 60}")
        print(f"🤖 SwingTradeStrategy Initialized")
        print(f"   Tickers: {len(self.tickers)} | Mode: {'BACKTEST' if Config.BACKTESTING else 'LIVE'}")
        print(f"   Rotation: 5-tier streak-based system")
        print(f"   Safeguards: Portfolio DD (15%) + Market Crisis + SPY<200")
        if not Config.BACKTESTING:
            print(f"   Circuit Breaker: {CONSECUTIVE_FAILURE_THRESHOLD} consecutive failures → pause")
            print(f"   Trading: Continuous throughout market hours (per-stock daily limit)")
        print(f"{'=' * 60}\n")

    def before_starting_trading(self):
        if Config.BACKTESTING:
            return
        load_state_safe(self)

    def on_trading_iteration(self):
        import account_email_notifications
        execution_tracker = account_email_notifications.ExecutionTracker()
        summary = reset_summary()

        # Check if paused by circuit breaker (shouldn't happen but safety check)
        if not Config.BACKTESTING and self.failure_tracker.is_paused:
            print("[PAUSED] Bot is paused by circuit breaker. Skipping iteration.")
            return

        # Check dashboard pause (user-controlled via dashboard)
        if not Config.BACKTESTING:
            from database import get_database
            db = get_database()
            if db.get_bot_paused():
                print("[DASHBOARD] Bot paused by user via dashboard. Skipping iteration.")
                return

        try:
            # === MARKET OPEN CHECK (Live Only) ===
            if not Config.BACKTESTING:
                try:
                    if not self.broker.is_market_open():
                        return
                except:
                    pass

                # Load daily traded stocks from database (survives crashes/deploys)
                current_date_only = self.get_datetime().date()
                db.clear_old_daily_traded(current_date_only)
                self.daily_traded_stocks = db.get_daily_traded_stocks(current_date_only)

                if self.daily_traded_stocks:
                    print(f"[INFO] Stocks already traded today: {', '.join(sorted(self.daily_traded_stocks))}")

            # Backtesting: use existing once-per-day behavior
            if Config.BACKTESTING:
                if account_broker_data.has_traded_today(self, self.last_trade_date):
                    return

            current_date = self.get_datetime()

            # Only update last_trade_date in backtesting mode
            if Config.BACKTESTING:
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

            # =============================================================
            # MARKET REGIME DETECTION
            # =============================================================
            try:
                regime_result = self.regime_detector.evaluate_regime(
                    strategy=self,
                    current_date=current_date,
                    recovery_manager=self.recovery_manager
                )
                self._current_regime_result = regime_result

                summary.set_regime(
                    regime_result['action'],
                    regime_result['reason'],
                    regime_result['position_size_multiplier'],
                    recovery_details=regime_result.get('recovery_details')
                )

            except Exception as e:
                summary.add_error(f"Regime detection failed: {e}")
                execution_tracker.add_error("Regime Detection", e)

                if not Config.BACKTESTING:
                    should_pause = self.failure_tracker.record_failure("Regime Detection", e)
                    if should_pause:
                        enter_paused_state(self, self.failure_tracker, execution_tracker)
                        return

                execution_tracker.complete('FAILED')
                summary.print_summary()
                return

            # =============================================================
            # EMERGENCY EXIT HANDLERS
            # =============================================================
            if regime_result['action'] in ['exit_all', 'portfolio_drawdown_exit']:
                exit_reason = regime_result['reason']
                exit_count = 0

                positions = self.get_positions()
                if positions:
                    for position in positions:
                        ticker = position.symbol
                        qty = int(position.quantity)

                        if ticker in account_broker_data.SKIP_SYMBOLS:
                            continue

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

                    update_end_of_day_metrics(self, current_date, self._current_regime_result)
                    save_state_safe(self)
                    return

            # =============================================================
            # STOP BUYING MODE
            # =============================================================
            if regime_result['action'] == 'stop_buying':
                if not Config.BACKTESTING:
                    self.failure_tracker.record_success()

                execution_tracker.complete('SUCCESS')
                summary.print_summary()

                update_end_of_day_metrics(self, current_date, self._current_regime_result)
                save_state_safe(self)
                return

            # =============================================================
            # FETCH MARKET DATA
            # =============================================================
            try:
                all_tickers = list(set(self.tickers + ['SPY']))
                all_stock_data = stock_data.process_data(all_tickers, current_date)

                if not all_stock_data:
                    summary.add_error("No stock data available")

                    if not Config.BACKTESTING:
                        should_pause = self.failure_tracker.record_failure("Stock Data", "No data returned")
                        if should_pause:
                            enter_paused_state(self, self.failure_tracker, execution_tracker)
                            return

                    execution_tracker.complete('FAILED')
                    summary.print_summary()
                    return

            except Exception as e:
                summary.add_error(f"Stock data fetch failed: {e}")
                execution_tracker.add_error("Stock Data", e)

                if not Config.BACKTESTING:
                    should_pause = self.failure_tracker.record_failure("Stock Data", e)
                    if should_pause:
                        enter_paused_state(self, self.failure_tracker, execution_tracker)
                        return

                execution_tracker.complete('FAILED')
                summary.print_summary()
                return

            # =============================================================
            # PROCESS EXISTING POSITIONS (Exits)
            # =============================================================
            try:
                exit_orders = stock_position_monitoring.check_positions_for_exits(
                    strategy=self,
                    current_date=current_date,
                    all_stock_data=all_stock_data,
                    position_monitor=self.position_monitor
                )

                if exit_orders:
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

                    update_end_of_day_metrics(self, current_date, self._current_regime_result)
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

            for ticker in self.tickers:
                try:
                    if ticker not in all_stock_data:
                        continue

                    # Get rotation tier and multiplier
                    tier = self.stock_rotator.get_tier(ticker)
                    rotation_mult = self.stock_rotator.get_multiplier(ticker)

                    data = all_stock_data[ticker]['indicators']

                    if not Config.BACKTESTING:
                        price = data.get('close', 0)
                        rsi = data.get('rsi', 0)
                        sma200 = data.get('sma200', 0)
                        print(f"[SCAN] {ticker:<6} | ${price:>8.2f} | RSI: {rsi:>5.1f} | SMA200: ${sma200:>8.2f}")

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
            # FILTER OUT STOCKS ALREADY TRADED TODAY (Live Trading Only)
            # =============================================================
            if not Config.BACKTESTING and hasattr(self, 'daily_traded_stocks') and self.daily_traded_stocks:
                pre_filter_count = len(all_opportunities)
                all_opportunities = [
                    opp for opp in all_opportunities
                    if opp['ticker'] not in self.daily_traded_stocks
                ]
                filtered_count = pre_filter_count - len(all_opportunities)
                if filtered_count > 0:
                    print(f"[INFO] Filtered {filtered_count} stock(s) already traded today")
                    for opp_ticker in [o['ticker'] for o in all_opportunities[:filtered_count]]:
                        summary.add_warning(f"{opp_ticker} already traded today - skipped")

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

                update_end_of_day_metrics(self, current_date, self._current_regime_result)
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

                    update_end_of_day_metrics(self, current_date, self._current_regime_result)
                    save_state_safe(self)
                    return

                if portfolio_context['available_slots'] <= 0:
                    summary.add_warning("No available slots")

                    if not Config.BACKTESTING:
                        self.failure_tracker.record_success()

                    execution_tracker.complete('SUCCESS')
                    summary.print_summary()

                    update_end_of_day_metrics(self, current_date, self._current_regime_result)
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

                    update_end_of_day_metrics(self, current_date, self._current_regime_result)
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

                    # Record stock as traded today (live trading only)
                    if not Config.BACKTESTING:
                        db.add_daily_traded_stock(ticker, current_date.date())
                        self.daily_traded_stocks.add(ticker)

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

                update_end_of_day_metrics(self, current_date, self._current_regime_result)
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
