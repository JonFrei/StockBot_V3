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
- UPDATED: Daily signal scan time-gate (once per day after 10 AM ET)
- UPDATED: Uses previous day's completed bar data for signal generation
"""

from lumibot.strategies import Strategy
from config import Config

import stock_data
import stock_signals
import stock_position_sizing
import account_profit_tracking
import stock_position_monitoring
import account_email_notifications

from stock_rotation import StockRotator, should_rotate

from server_recovery import save_state_safe, load_state_safe, repair_incomplete_position_metadata
from account_drawdown_protection import MarketRegimeDetector
from account_recovery_mode import RecoveryModeManager
import account_broker_data
from account_broker_data import sync_positions_with_broker
from account_profit_tracking import get_summary, reset_summary, update_end_of_day_metrics

from lumibot.brokers import Alpaca
import time
from datetime import datetime
from datetime import time as dt_time

broker = Alpaca(Config.get_alpaca_config())

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
        self._daily_email_sent_date = None  # Track which date we sent the daily email

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

        # Clear split tracker at start of new session
        account_broker_data.split_tracker.clear()

        self._current_regime_result = None  # Store for metrics tracking

        print(f"\n{'=' * 60}")
        print(f"🤖 SwingTradeStrategy Initialized")
        print(f"   Tickers: {len(self.tickers)} | Mode: {'BACKTEST' if Config.BACKTESTING else 'LIVE'}")
        print(f"   Rotation: 5-tier streak-based system")
        print(f"   Safeguards: Portfolio DD (15%) + Market Crisis + SPY<200")
        if not Config.BACKTESTING:
            print(f"   Circuit Breaker: {CONSECUTIVE_FAILURE_THRESHOLD} consecutive failures → pause")
            print(f"   Signal Scan: Once daily after 10:00 AM ET (previous day's data)")
            print(f"   Position Monitoring: Every 30 minutes")
        print(f"{'=' * 60}\n")

    def before_starting_trading(self):
        if Config.BACKTESTING:
            return
        load_state_safe(self)

        # Sync positions with broker immediately on startup
        from datetime import datetime
        try:
            sync_result = sync_positions_with_broker(
                strategy=self,
                current_date=datetime.now(),
                position_monitor=self.position_monitor
            )
            if sync_result['orphaned_adopted']:
                print(f"🔄 Startup sync: Adopted {len(sync_result['orphaned_adopted'])} positions")
        except Exception as e:
            print(f"⚠️ Startup position sync failed: {e}")

    def on_filled_order(self, position, order, price, quantity, multiplier):
        if Config.BACKTESTING:
            if order.side == 'buy':
                print(f"[FILL] BUY {order.symbol}: {quantity} @ ${price:.2f} = ${quantity * price:,.2f}")
            else:
                print(f"[FILL] SELL {order.symbol}: {quantity} @ ${price:.2f} = ${quantity * price:,.2f}")
            print(f"[FILL] Lumibot cash after fill: ${self.get_cash():,.2f}")

    def after_market_closes(self):
        """Called by Lumibot after market closes - perfect for daily email"""
        if Config.BACKTESTING:
            return

        print("\n[EMAIL] after_market_closes triggered - sending daily summary...")

        try:
            eod_tracker = account_email_notifications.ExecutionTracker()
            eod_tracker.complete('SUCCESS')

            current_time = self.get_datetime()
            account_email_notifications.send_daily_summary_email(self, current_time, eod_tracker)
            print(f"[EMAIL] Daily email sent for {current_time.date()}")
        except Exception as e:
            import traceback
            print(f"[EMAIL ERROR] Failed: {e}")
            print(traceback.format_exc())

    def on_trading_iteration(self):
        execution_tracker = account_email_notifications.ExecutionTracker()
        summary = reset_summary()

        # =================================================================
        # END OF DAY EMAIL CHECK
        # =================================================================
        if not Config.BACKTESTING:
            try:
                from datetime import time as dt_time
                current_time = self.get_datetime()
                current_date_only = current_time.date()

                print(
                    f"[EMAIL DEBUG] Time check: {current_time.time()}, sent date: {self._daily_email_sent_date}, today: {current_date_only}")

                # Send email if after 3:00 PM EST and haven't sent today
                if current_time.time() >= dt_time(15, 0) and self._daily_email_sent_date != current_date_only:
                    print("\n[EMAIL] on_trading_iteration End of Day Triggered - sending daily summary...")

                    eod_tracker = account_email_notifications.ExecutionTracker()
                    eod_tracker.complete('SUCCESS')

                    account_email_notifications.send_daily_summary_email(self, current_time, eod_tracker)
                    self._daily_email_sent_date = current_date_only
                    print(f"[EMAIL] Daily email sent for {current_date_only}")
            except Exception as e:
                import traceback
                print(f"[EMAIL ERROR] Failed during end-of-day email check: {e}")
                print(f"[EMAIL ERROR] Traceback:\n{traceback.format_exc()}")

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

            # =================================================================
            # DAILY SIGNAL SCAN TIME-GATE (Live Trading Only)
            # Signal scanning runs ONCE per day after 10:00 AM ET
            # Position monitoring (exits) runs every 30 minutes
            # =================================================================
            signal_scan_allowed = True  # Default True for backtesting

            if not Config.BACKTESTING:
                current_time = self.get_datetime()
                current_date_only = current_time.date()

                # Check if we've already completed signal scan today
                last_scan_date = db.get_daily_signal_scan_date()

                if last_scan_date == current_date_only:
                    # Already scanned today - only run position monitoring
                    signal_scan_allowed = False
                    print(
                        f"[SCAN] Daily signal scan already completed for {current_date_only}. Position monitoring only.")
                elif current_time.time() < dt_time(10, 0):
                    # Before 10 AM - only run position monitoring
                    signal_scan_allowed = False
                    print(f"[SCAN] Before 10:00 AM ET ({current_time.time()}). Position monitoring only.")
                else:
                    # After 10 AM and haven't scanned - will run full scan
                    print(f"\n{'=' * 70}")
                    print(f"🔍 DAILY SIGNAL SCAN - {current_date_only}")
                    print(f"   Time: {current_time.time()} ET (after 10 AM gate)")
                    print(f"   Using: Previous day's completed daily bars")
                    print(f"{'=' * 70}\n")

            # Use tracked cash for backtesting display
            if Config.BACKTESTING:
                display_cash = self.get_cash()
            else:
                display_cash = self.get_cash()
            summary.set_context(current_date, self.portfolio_value, display_cash)

            # =============================================================
            # REFRESH ALPACA POSITION CACHE (Direct API)
            # =============================================================
            if not Config.BACKTESTING:
                account_broker_data.refresh_position_cache()

            # =============================================================
            # FETCH MARKET DATA
            # Note: stock_data.process_data() now excludes today's incomplete
            # bar for live trading, using only completed daily bars
            # =============================================================
            try:
                # Get tickers from positions we hold (for exit monitoring)
                held_tickers = []
                try:
                    positions = self.get_positions()
                    held_tickers = [p.symbol for p in positions if p.symbol not in account_broker_data.SKIP_SYMBOLS]
                except:
                    pass

                # Combine universe + held positions + SPY
                all_tickers = list(set(self.tickers + held_tickers + ['SPY']))
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

                # Repair any positions with incomplete metadata (missing stops, R, ATR, etc.)
                if not Config.BACKTESTING:
                    repaired = repair_incomplete_position_metadata(
                        self, self.position_monitor, all_stock_data, current_date
                    )
                    if repaired:
                        print(f"   📝 Repaired metadata for {len(repaired)} position(s)")
                        save_state_safe(self)

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
            # DAILY POSITION SYNC (Broker is Source of Truth)
            # =============================================================
            if not Config.BACKTESTING:
                try:
                    sync_result = sync_positions_with_broker(
                        strategy=self,
                        current_date=current_date,
                        position_monitor=self.position_monitor,
                        all_stock_data=all_stock_data
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
                exit_signal = regime_result['reason']
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

                                ticker_data = all_stock_data.get(ticker, {})
                                exit_indicators = ticker_data.get('indicators', {}) if ticker_data else {}
                                summary.add_exit(ticker, qty, pnl_dollars, pnl_pct, exit_signal, exit_indicators)

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
                                    exit_signal={'reason': exit_signal},
                                    entry_score=entry_score
                                )

                                self.position_monitor.clean_position_metadata(ticker)
                                sell_order = self.create_order(ticker, qty, 'sell')
                                self.submit_order(sell_order)
                                exit_count += 1

                            except Exception as e:
                                summary.add_error(f"{exit_signal} {ticker} failed: {e}")

                    execution_tracker.record_action('exits', count=exit_count)

                    if regime_result.get('exit_all', False):
                        execution_tracker.record_action('drawdown_protection', count=1)

                    # Success - reset failure counter
                    if not Config.BACKTESTING:
                        self.failure_tracker.record_success()

                    execution_tracker.complete('SUCCESS')
                    summary.print_summary()

                    if not Config.BACKTESTING:
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
            # PROCESS EXISTING POSITIONS (Exits) - ALWAYS RUNS
            # This section runs every 30 minutes for position monitoring
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
            # EARLY RETURN IF SIGNAL SCAN NOT ALLOWED (Live Trading Only)
            # Position monitoring is complete - skip new entry logic
            # =============================================================
            if not signal_scan_allowed:
                if not Config.BACKTESTING:
                    self.failure_tracker.record_success()

                execution_tracker.complete('SUCCESS')
                summary.print_summary()

                if not Config.BACKTESTING:
                    update_end_of_day_metrics(self, current_date, self._current_regime_result)
                    save_state_safe(self)
                return

            # =============================================================
            # === EVERYTHING BELOW RUNS ONCE PER DAY (Signal Scan) ===
            # =============================================================

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
                        # Record that we completed the daily scan (even if no trades)
                        db.set_daily_signal_scan_date(current_date_only)

                    execution_tracker.complete('SUCCESS')
                    summary.print_summary()
                    if not Config.BACKTESTING:
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
                        adx = data.get('adx', 0)
                        volume_ratio = data.get('volume_ratio', 0)
                        ema20 = data.get('ema20', 0)
                        ema50 = data.get('ema50', 0)
                        sma200 = data.get('sma200', 0)
                        print(
                            f"[SCAN] {ticker:<6} | ${price:>8.2f} | RSI:{rsi:>5.1f} | ADX:{adx:>5.1f} | Vol:{volume_ratio:>4.1f}x | EMA20:${ema20:>7.2f} | EMA50:${ema50:>7.2f} | SMA200:${sma200:>8.2f}")

                    vol_metrics = data.get('volatility_metrics', {})
                    if not vol_metrics.get('allow_trading', True):
                        summary.add_skip(ticker, f"Volatility blocked: {vol_metrics.get('risk_class', 'unknown')}")
                        continue

                    # Skip if already holding
                    if ticker in current_holdings:
                        continue

                    # 200 SMA trend filter - only buy stocks in uptrends with rising 200 SMA
                    sma200 = data.get('sma200', 0)
                    close = data.get('close', 0)
                    if sma200 > 0 and close > 0:
                        if close <= sma200:
                            pct_below = ((sma200 - close) / sma200) * 100
                            summary.add_skip(ticker, f"Below 200 SMA: {pct_below:.1f}% under")
                            continue

                        # Check 200 SMA slope (must be rising)
                        raw_df = data.get('raw')
                        if raw_df is not None and len(raw_df) >= 210:
                            try:
                                sma200_series = raw_df['close'].rolling(window=200).mean()
                                if len(sma200_series) >= 11:
                                    sma200_current = sma200_series.iloc[-1]
                                    sma200_past = sma200_series.iloc[-11]  # 10 days ago
                                    if sma200_past > 0:
                                        sma200_slope = ((sma200_current - sma200_past) / sma200_past) * 100
                                        if sma200_slope < 0:
                                            summary.add_skip(ticker, f"200 SMA declining: {sma200_slope:.2f}%")
                                            continue
                            except:
                                pass

                    # =============================================================
                    # UNIVERSAL ENTRY FILTERS (V5)
                    # Catches risk factors that individual signals miss
                    # =============================================================
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
                except Exception as e:
                    if Config.BACKTESTING:
                        import traceback
                        print(f"[BACKTEST ERROR] {ticker}: {e}")
                        traceback.print_exc()
                    continue

            # =============================================================
            # FILTER OUT STOCKS ALREADY TRADED TODAY (Live Trading Only)
            # =============================================================
            if not Config.BACKTESTING and hasattr(self, 'daily_traded_stocks') and self.daily_traded_stocks:
                filtered_tickers = [opp['ticker'] for opp in all_opportunities if
                                    opp['ticker'] in self.daily_traded_stocks]

                all_opportunities = [
                    opp for opp in all_opportunities
                    if opp['ticker'] not in self.daily_traded_stocks
                ]

                if filtered_tickers:
                    print(f"[INFO] Filtered {len(filtered_tickers)} stock(s) already traded today")
                    for ticker in filtered_tickers:
                        summary.add_warning(f"{ticker} already traded today - skipped")

            # =============================================================
            # POSITION SIZING
            # =============================================================
            if not all_opportunities:
                if not Config.BACKTESTING:
                    self.failure_tracker.record_success()
                    # Record that we completed the daily scan (even if no opportunities)
                    db.set_daily_signal_scan_date(current_date_only)
                    print(f"[SCAN] ✅ Daily signal scan completed for {current_date_only} (no opportunities)")

                execution_tracker.complete('SUCCESS')
                summary.print_summary()
                if not Config.BACKTESTING:
                    update_end_of_day_metrics(self, current_date, self._current_regime_result)
                    save_state_safe(self)
                return

            try:
                portfolio_context = stock_position_sizing.create_portfolio_context(self)

                sizing_opportunities = []
                for opp in all_opportunities:
                    sizing_opportunities.append({
                        'ticker': opp['ticker'],
                        'signal_type': opp['signal_type'],
                        'signal_score': opp['score'],
                        'rotation_mult': opp.get('rotation_mult', 1.0),
                        'vol_metrics': opp.get('vol_metrics', {}),
                        'data': opp.get('data', {})
                    })

                regime_multiplier = regime_result['position_size_multiplier']

                allocations = stock_position_sizing.calculate_position_sizes(
                    sizing_opportunities,
                    portfolio_context,
                    regime_multiplier,
                    verbose=False,
                    strategy=self
                )

                if not allocations:
                    summary.add_warning("No positions met size requirements")

                    if not Config.BACKTESTING:
                        self.failure_tracker.record_success()
                        # Record that we completed the daily scan
                        db.set_daily_signal_scan_date(current_date_only)
                        print(f"[SCAN] ✅ Daily signal scan completed for {current_date_only} (no allocations)")

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
            daily_spent = 0.0

            for alloc in allocations:
                try:
                    ticker = alloc['ticker']
                    quantity = alloc['quantity']
                    cost = alloc['cost']
                    price = alloc['price']
                    sizing_price = alloc['price']
                    signal_type = alloc['signal_type']
                    signal_score = alloc['signal_score']
                    rotation_mult = alloc.get('rotation_mult', 1.0)

                    # Check 1: Would this buy exceed daily deployment limit?
                    if Config.BACKTESTING:
                        available_cash = self.get_cash()
                        min_reserve = self.portfolio_value * (
                                stock_position_sizing.SimplifiedSizingConfig.MIN_CASH_RESERVE_PCT / 100)
                        if available_cash is None or (available_cash - cost) < min_reserve:
                            summary.add_warning(
                                f"Skipped {ticker}: insufficient cash (${available_cash:,.0f} - ${cost:,.0f} < ${min_reserve:,.0f} reserve)")
                            continue
                    else:
                        # LIVE TRADING: Verify cash before each buy
                        try:
                            current_cash = account_broker_data.get_cash_balance(self)
                            min_reserve = self.portfolio_value * (
                                    stock_position_sizing.SimplifiedSizingConfig.MIN_CASH_RESERVE_PCT / 100)
                            if (current_cash - daily_spent - cost) < min_reserve:
                                summary.add_warning(
                                    f"Skipped {ticker}: insufficient cash (${current_cash - daily_spent:,.0f} - ${cost:,.0f} < ${min_reserve:,.0f} reserve)")
                                continue
                        except Exception as e:
                            summary.add_warning(f"Skipped {ticker}: cash check failed ({e})")
                            continue

                    # Get tier for logging
                    tier = self.stock_rotator.get_tier(ticker)
                    tier_emoji = {'premium': '🥇', 'active': '🥈', 'probation': '⚠️',
                                  'rehabilitation': '🔄', 'frozen': '❄️'}.get(tier, '❓')

                    # Get entry indicators from signal data
                    entry_indicators = {}
                    for opp in all_opportunities:
                        if opp['ticker'] == ticker:
                            entry_indicators = opp.get('signal_data', {}).get('indicators', {})
                            break

                    summary.add_entry(ticker, quantity, price, cost, f"{signal_type} {tier_emoji}", signal_score,
                                      entry_indicators)

                    ticker_data = all_stock_data.get(ticker, {})
                    self.position_monitor.track_position(
                        ticker=ticker,
                        entry_date=current_date,
                        entry_signal=signal_type,
                        entry_score=signal_score,
                        entry_price=price,
                        raw_df=ticker_data.get('raw'),
                        atr=ticker_data.get('indicators', {}).get('atr_14', 0),
                        entry_indicators=entry_indicators
                    )

                    order = self.create_order(ticker, quantity, 'buy')
                    self.submit_order(order)

                    # Track spending
                    daily_spent += cost

                    # Record stock as traded today (live trading only)
                    if not Config.BACKTESTING:
                        db.add_daily_traded_stock(ticker, current_date.date())
                        self.daily_traded_stocks.add(ticker)

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

            # =============================================================
            # RECORD DAILY SIGNAL SCAN COMPLETION (Live Trading Only)
            # =============================================================
            if not Config.BACKTESTING:
                db.set_daily_signal_scan_date(current_date_only)
                print(f"[SCAN] ✅ Daily signal scan completed and recorded for {current_date_only}")

            # Success - reset failure counter
            if not Config.BACKTESTING:
                self.failure_tracker.record_success()

            execution_tracker.complete('SUCCESS')
            summary.print_summary()

            if not Config.BACKTESTING:
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
