"""
SwingTradeStrategy - COMPLETE WITH ALL PRIORITY IMPROVEMENTS

Integrated Features:
- Priority 1: Optimized signals (consolidation + golden_cross loosened)
- Priority 2: Ticker blacklist (integrated in stock_rotation)
- Priority 3: Market regime detection (per-ticker + global)
- Priority 4: Multi-signal conviction sizing
- Priority 5: Momentum death exits
- NEW: Optimal independent position sizing (Option 1)
- ENHANCED: ExecutionTracker for guaranteed daily emails with error reporting
"""

from lumibot.strategies import Strategy
from config import Config

import stock_data
import stock_signals
import stock_position_sizing
import account_profit_tracking
import stock_position_monitoring
from stock_cooldown import TickerCooldown
from server_state_persistence import save_state_safe, load_state_safe  # Crash recovery

# INTEGRATED IMPORTS (consolidated modules)
from stock_rotation import StockRotator  # Has integrated blacklist
import account_drawdown_protection  # Has integrated market regime
import account_broker_data  # Trading window and market hours

from lumibot.brokers import Alpaca

broker = Alpaca(Config.get_alpaca_config())


class SwingTradeStrategy(Strategy):
    # =========================================================================
    # CONFIGURATION
    # =========================================================================

    # Active trading signals (in priority order)
    ACTIVE_SIGNALS = [
        'swing_trade_1',  # EMA crossover + momentum
        'swing_trade_2',  # Pullback plays
        'consolidation_breakout',  # 75% win rate - LOOSENED
        'golden_cross',  # 77% win rate - LOOSENED
        'bollinger_buy',

    ]

    # Cooldown configuration
    COOLDOWN_DAYS = 1  # Days between re-purchases of same ticker

    # =========================================================================

    def initialize(self, send_emails=True):
        """Initialize strategy with all integrated systems"""
        if Config.BACKTESTING:
            self.sleeptime = "1D"
        else:
            self.sleeptime = "10M"

        self.tickers = self.parameters.get("tickers", [])

        # Track if we've traded today (for live mode)
        self.last_trade_date = None

        # SIMPLIFIED: Tracker just logs completed trades
        self.profit_tracker = account_profit_tracking.ProfitTracker(self)

        # Position monitoring (for exits + market condition caching)
        self.position_monitor = stock_position_monitoring.PositionMonitor(self)

        # Ticker cooldown to prevent chasing
        self.ticker_cooldown = TickerCooldown(cooldown_days=self.COOLDOWN_DAYS)

        # PRIORITY 2 & 5: Stock rotation WITH integrated blacklist + profit tracker
        self.stock_rotator = StockRotator(
            rotation_frequency='weekly',  # Changed from biweekly
            profit_tracker=self.profit_tracker  # Blacklist automatic
        )

        # Dynamic rotation controls
        self.idle_iterations_without_buys = 0
        self.force_rotation_next_cycle = False

        # Track rotation timing
        self.last_rotation_week = None

        # Drawdown protection (has integrated market regime)
        self.drawdown_protection = account_drawdown_protection.create_default_protection(
            threshold_pct=-10.0,
            recovery_days=5
        )

        print(
            f"✅ Drawdown Protection: {self.drawdown_protection.threshold_pct:.1f}% threshold, {self.drawdown_protection.recovery_days}d recovery")
        print(f"✅ Ticker Cooldown: {self.ticker_cooldown.cooldown_days} days between purchases")
        print(f"✅ Stock Rotation: Weekly award-based system (all stocks tradeable)")
        print(f"✅ Award System: Premium (1.3x), Standard (1.0x), Trial (1.0x), None (0.6x)")
        print(f"✅ Integrated Blacklist: Automatic (part of rotation)")
        print(f"✅ Market Regime Detection: Integrated (per-ticker + global)")
        print(f"✅ Optimal Position Sizing: Independent allocation (quality-weighted)")
        print(f"✅ Active Signals: {len(self.ACTIVE_SIGNALS)} signals configured")
        print(f"✅ Signal Guard: DISABLED - All signals active without restriction")

        if not Config.BACKTESTING:
            window_info = account_broker_data.get_trading_window_info()
            print(f"✅ LIVE TRADING WINDOW: {window_info['start_time_str']} - {window_info['end_time_str']} EST")
            print(f"✅ Trading Frequency: Once per day")

    def before_starting_trading(self):
        """
        Sync existing positions - WITH CRASH RECOVERY
        """
        if Config.BACKTESTING:
            return

        # LOAD SAVED STATE FIRST (if exists)
        load_state_safe(self)

        try:
            broker_positions = self.get_positions()

            if len(broker_positions) > 0:
                for position in broker_positions:
                    ticker = position.symbol

                    if ticker in self.tickers:
                        # Check if we already have metadata (from loaded state)
                        if ticker not in self.position_monitor.positions_metadata:
                            # No metadata - track as pre_existing
                            self.position_monitor.track_position(
                                ticker,
                                self.get_datetime(),
                                'pre_existing',
                                entry_score=0
                            )

            print(f"[SYNC] Loaded {len(self.position_monitor.positions_metadata)} positions\n")

        except Exception as e:
            print(f"[ERROR] Failed to sync positions: {e}")

    def on_trading_iteration(self):
        # Create execution tracker for email reporting
        import account_email_notifications
        execution_tracker = account_email_notifications.ExecutionTracker()

        try:
            if not Config.BACKTESTING:
                # Check market status
                try:
                    if not self.broker.is_market_open():
                        print(f"[INFO] Market is closed - skipping iteration")
                        execution_tracker.add_warning("Market is closed")
                        execution_tracker.complete('SUCCESS')
                        account_email_notifications.send_daily_summary_email(self, self.get_datetime(),
                                                                             execution_tracker)
                        return
                except Exception as e:
                    print(f"[WARN] Could not check market status: {e}")
                    execution_tracker.add_error("Market Status Check", e)

                # Check if already traded today
                if account_broker_data.has_traded_today(self, self.last_trade_date):
                    execution_tracker.add_warning("Already traded today")
                    execution_tracker.complete('SUCCESS')
                    account_email_notifications.send_daily_summary_email(self, self.get_datetime(), execution_tracker)
                    return

                # Check trading window
                if not account_broker_data.is_within_trading_window(self):
                    execution_tracker.add_warning("Outside trading window")
                    execution_tracker.complete('SUCCESS')
                    account_email_notifications.send_daily_summary_email(self, self.get_datetime(), execution_tracker)
                    return

            current_date = self.get_datetime()
            current_date_str = current_date.strftime('%Y-%m-%d')

            # =====================================================================
            # MARK THAT WE'VE TRADED TODAY
            # =====================================================================

            if not Config.BACKTESTING:
                self.last_trade_date = current_date.date()

            print('\n')
            print(30 * '=' + ' Date: ' + str(current_date) + ' ' + 30 * '=')
            print('Portfolio Value:', self.portfolio_value)
            print('Cash Balance:', self.get_cash())

            # Display active cooldowns
            active_cooldowns = self.ticker_cooldown.get_all_cooldowns(current_date)
            if active_cooldowns:
                print(f"\n⏰ Active Cooldowns:")
                for ticker, days_left in active_cooldowns:
                    print(f"   {ticker}: {days_left} day(s) remaining")

            print('\n')

            # =====================================================================
            # PORTFOLIO DRAWDOWN PROTECTION - HIGHEST PRIORITY
            # =====================================================================

            # Check if protection should trigger
            if self.drawdown_protection.should_trigger(self.portfolio_value):
                try:
                    self.drawdown_protection.activate(
                        strategy=self,
                        current_date=current_date,
                        position_monitor=self.position_monitor,
                        ticker_cooldown=self.ticker_cooldown
                    )
                    execution_tracker.record_action('drawdown_protection')
                except Exception as e:
                    execution_tracker.add_error("Drawdown Protection Activation", e)

                # Complete and send email
                execution_tracker.complete('SUCCESS')
                if not Config.BACKTESTING:
                    account_email_notifications.send_daily_summary_email(self, current_date, execution_tracker)

                return  # Skip rest of iteration

            # Check if in recovery period
            if self.drawdown_protection.is_in_recovery(current_date):
                self.drawdown_protection.print_status(self.portfolio_value, current_date)
                execution_tracker.add_warning("In drawdown recovery period - no new positions")
                # Continue to exits but no new positions

            # =====================================================================
            # FETCH DATA FOR ALL TICKERS + SPY
            # =====================================================================

            try:
                all_tickers = list(set(self.tickers + ['SPY'] + [p.symbol for p in self.get_positions()]))
                all_stock_data = stock_data.process_data(all_tickers, current_date)
                spy_data = all_stock_data.get('SPY', {}).get('indicators', None) if 'SPY' in all_stock_data else None
            except Exception as e:
                execution_tracker.add_error("Data Fetch", e)
                execution_tracker.complete('FAILED')
                if not Config.BACKTESTING:
                    account_email_notifications.send_daily_summary_email(self, current_date, execution_tracker)
                return

            # =====================================================================
            # PRIORITY 3: GLOBAL MARKET REGIME DETECTION
            # =====================================================================

            try:
                regime_info = account_drawdown_protection.detect_market_regime(spy_data)
                print(account_drawdown_protection.format_regime_display(regime_info))
            except Exception as e:
                execution_tracker.add_error("Market Regime Detection", e)
                regime_info = {'allow_trading': True}  # Default to allow trading

            # INTEGRATED: Clean expired blacklists
            try:
                if self.stock_rotator.blacklist:
                    self.stock_rotator.blacklist.clean_expired_blacklists(current_date)
            except Exception as e:
                execution_tracker.add_error("Blacklist Cleanup", e)

            # =====================================================================
            # STEP 1: CHECK ALL EXISTING POSITIONS FOR EXITS (HIGHEST PRIORITY)
            # =====================================================================

            try:
                # Check positions and get exit orders (uses adaptive parameters)
                exit_orders = stock_position_monitoring.check_positions_for_exits(
                    strategy=self,
                    current_date=current_date,
                    all_stock_data=all_stock_data,
                    position_monitor=self.position_monitor
                )

                # Execute all exit orders
                stock_position_monitoring.execute_exit_orders(
                    strategy=self,
                    exit_orders=exit_orders,
                    current_date=current_date,
                    position_monitor=self.position_monitor,
                    profit_tracker=self.profit_tracker,
                    ticker_cooldown=self.ticker_cooldown
                )

                # Record exits
                if exit_orders:
                    execution_tracker.record_action('exits', count=len(exit_orders))

            except Exception as e:
                execution_tracker.add_error("Position Exit Processing", e)

            # =====================================================================
            # SKIP NEW POSITIONS IF IN RECOVERY OR BEAR MARKET
            # =====================================================================

            if self.drawdown_protection.is_in_recovery(current_date):
                print(f"⚠️ In drawdown recovery - no new positions")
                execution_tracker.complete('SUCCESS')
                if not Config.BACKTESTING:
                    account_email_notifications.send_daily_summary_email(self, current_date, execution_tracker)
                return

            if not regime_info.get('allow_trading', True):
                print(f"\n⚠️ {regime_info['description']}")
                print(f"No new positions will be opened.\n")
                execution_tracker.add_warning(f"Trading blocked: {regime_info['description']}")
                execution_tracker.complete('SUCCESS')
                if not Config.BACKTESTING:
                    account_email_notifications.send_daily_summary_email(self, current_date, execution_tracker)
                return

            # PRIORITY 1: SIGNAL GUARD REMOVED - Use all configured signals
            active_signal_list = self.ACTIVE_SIGNALS

            # =====================================================================
            # STEP 2: STOCK ROTATION - WEEKLY AWARD EVALUATION
            # =====================================================================

            try:
                # Calculate weekly period
                current_week = current_date.isocalendar()[1]  # ISO week number
                current_year = current_date.year
                weekly_period = (current_year, current_week)

                force_rotation = False
                if self.force_rotation_next_cycle:
                    force_rotation = True
                    print(
                        f"\n🌀 FORCED ROTATION: No new entries for {self.idle_iterations_without_buys} iteration(s) → refreshing active pool early")

                if self.last_rotation_week != weekly_period or force_rotation:
                    # Time to rotate - perform actual rotation (scheduled or forced)
                    active_tickers = self.stock_rotator.rotate_stocks(
                        strategy=self,
                        all_candidates=self.tickers,
                        current_date=current_date,
                        all_stock_data=all_stock_data
                    )

                    if self.last_rotation_week != weekly_period:
                        self.last_rotation_week = weekly_period

                    self.force_rotation_next_cycle = False
                    self.idle_iterations_without_buys = 0
                    execution_tracker.record_action('rotation')
                else:
                    # NOT time to rotate - use existing active list
                    active_tickers = self.stock_rotator.active_tickers

                    # First iteration or empty pool - initialize active list
                    if not active_tickers:
                        active_tickers = self.stock_rotator.rotate_stocks(
                            strategy=self,
                            all_candidates=self.tickers,
                            current_date=current_date,
                            all_stock_data=all_stock_data
                        )
                        self.last_rotation_week = weekly_period
                        self.idle_iterations_without_buys = 0
                        execution_tracker.record_action('rotation')

            except Exception as e:
                execution_tracker.add_error("Stock Rotation", e)
                active_tickers = self.tickers  # Fallback to all tickers

            # =====================================================================
            # STEP 3: COLLECT ALL BUY OPPORTUNITIES (NEW OPTIMAL SYSTEM)
            # =====================================================================

            opportunities = []

            for ticker in active_tickers:

                try:
                    if ticker not in all_stock_data:
                        self.log_message(f"No data for {ticker}, skipping")
                        continue

                    # Get stock data and indicators
                    data = all_stock_data[ticker]['indicators']

                    # ===================================================================
                    # VOLATILITY FILTER - PREVENTS MAJOR LOSSES ON HIGH-VOLATILITY STOCKS
                    # ===================================================================

                    vol_metrics = data.get('volatility_metrics', {})

                    # Skip if too volatile (blocks NFLX, extreme TSLA moves, etc.)
                    if not vol_metrics.get('allow_trading', True):
                        print(f"   ⚠️ {ticker} BLOCKED: {vol_metrics['risk_class'].upper()} volatility "
                              f"(Score: {vol_metrics['volatility_score']}/10, "
                              f"ATR: {vol_metrics['atr_pct']:.1f}%, "
                              f"Hist Vol: {vol_metrics['hist_vol']:.0f}%)")
                        continue

                    # ===================================================================
                    # PRIORITY 3: CHECK REGIME FOR THIS SPECIFIC TICKER
                    # ===================================================================

                    ticker_regime = account_drawdown_protection.detect_market_regime(spy_data, stock_data=data)

                    # Skip if this ticker blocked by regime
                    if not ticker_regime.get('allow_trading', True):
                        continue

                    # === CHECK COOLDOWN BEFORE PROCESSING ===
                    if not self.ticker_cooldown.can_buy(ticker, current_date):
                        continue

                    # Skip if we already have a position
                    has_position = ticker in self.positions
                    if has_position:
                        continue

                    # ===================================================================
                    # CHECK FOR BUY SIGNAL
                    # ===================================================================

                    buy_signal = stock_signals.buy_signals(data, active_signal_list, spy_data=spy_data)

                    # Skip if no buy signal
                    if not buy_signal or buy_signal.get('side') != 'buy':
                        continue

                    # ===================================================================
                    # COUNT ALL TRIGGERED SIGNALS FOR THIS TICKER
                    # ===================================================================

                    signal_count = stock_position_sizing.count_triggered_signals(
                        ticker, data, active_signal_list, spy_data
                    )

                    # ===================================================================
                    # CALCULATE QUALITY SCORE (Current setup only, no awards)
                    # ===================================================================

                    quality_score = stock_position_sizing.calculate_opportunity_quality(
                        ticker, data, spy_data, signal_count
                    )

                    # Get award info
                    award = self.stock_rotator.get_award(ticker)
                    award_multiplier = self.stock_rotator.get_award_multiplier(ticker)

                    # Get regime and volatility multipliers
                    regime_multiplier = ticker_regime.get('position_size_multiplier', 1.0)
                    volatility_multiplier = vol_metrics.get('position_multiplier', 1.0)

                    # Store opportunity
                    opportunities.append({
                        'ticker': ticker,
                        'data': data,
                        'buy_signal': buy_signal,
                        'quality_score': quality_score,
                        'signal_count': signal_count,
                        'award': award,
                        'award_multiplier': award_multiplier,
                        'regime_multiplier': regime_multiplier,
                        'volatility_multiplier': volatility_multiplier,
                        'vol_metrics': vol_metrics,
                        'ticker_regime': ticker_regime
                    })

                except Exception as e:
                    execution_tracker.add_error(f"Opportunity Analysis - {ticker}", e)
                    continue

            # =====================================================================
            # STEP 4: OPTIMAL POSITION SIZING ACROSS ALL OPPORTUNITIES
            # =====================================================================

            if not opportunities:
                print("\n📊 No buy opportunities found in this iteration\n")
                execution_tracker.complete('SUCCESS')
                if not Config.BACKTESTING:
                    account_email_notifications.send_daily_summary_email(self, current_date, execution_tracker)
                return

            try:
                # Create portfolio context
                portfolio_context = stock_position_sizing.create_portfolio_context(self)

                # Check if we can trade
                if portfolio_context['deployable_cash'] <= 0:
                    print(
                        f"\n⚠️ No deployable cash available (${portfolio_context['total_cash']:,.0f} < ${portfolio_context['reserved_cash']:,.0f} threshold)\n")
                    execution_tracker.add_warning("No deployable cash available")
                    execution_tracker.complete('SUCCESS')
                    if not Config.BACKTESTING:
                        account_email_notifications.send_daily_summary_email(self, current_date, execution_tracker)
                    return

                if portfolio_context['available_slots'] <= 0:
                    print(
                        f"\n⚠️ No available position slots ({portfolio_context['existing_positions_count']}/{stock_position_sizing.OptimalPositionSizingConfig.MAX_TOTAL_POSITIONS})\n")
                    execution_tracker.add_warning("No available position slots")
                    execution_tracker.complete('SUCCESS')
                    if not Config.BACKTESTING:
                        account_email_notifications.send_daily_summary_email(self, current_date, execution_tracker)
                    return

                # Calculate optimal position sizes (independent allocation)
                allocations = stock_position_sizing.calculate_independent_position_sizes(
                    opportunities,
                    portfolio_context
                )

                if not allocations:
                    print("\n⚠️ No positions met minimum size requirements after allocation\n")
                    execution_tracker.add_warning("No positions met minimum size requirements")
                    execution_tracker.complete('SUCCESS')
                    if not Config.BACKTESTING:
                        account_email_notifications.send_daily_summary_email(self, current_date, execution_tracker)
                    return

            except Exception as e:
                execution_tracker.add_error("Position Sizing", e)
                execution_tracker.complete('FAILED')
                if not Config.BACKTESTING:
                    account_email_notifications.send_daily_summary_email(self, current_date, execution_tracker)
                return

            # =====================================================================
            # SUBMIT BUY ORDERS
            # =====================================================================

            print(f"\n{'=' * 70}")
            print(f"📊 SUBMITTING {len(allocations)} BUY ORDER(S)")
            print(f"{'=' * 70}\n")

            for alloc in allocations:
                try:
                    ticker = alloc['ticker']
                    quantity = alloc['quantity']
                    cost = alloc['cost']
                    price = alloc['price']

                    # Find original opportunity data
                    opp = next((o for o in opportunities if o['ticker'] == ticker), None)
                    if not opp:
                        continue

                    buy_signal = opp['buy_signal']
                    signal_count = alloc['signal_count']

                    # Get display info
                    award_emoji = {'premium': '🥇', 'standard': '🥈', 'trial': '🔬', 'none': '⚪', 'frozen': '❄️'}.get(
                        alloc['award'], '❓')
                    conviction_label = ['', '• STANDARD', '⚡ MEDIUM', '🔥 HIGH', '🔥🔥 VERY HIGH'][min(signal_count, 4)]

                    vol_display = f"{opp['vol_metrics']['risk_class'].upper()} (ATR: {opp['vol_metrics']['atr_pct']:.1f}%)"

                    print(f" * BUY: {ticker} x{quantity} {conviction_label} [{award_emoji} {alloc['award'].upper()}] "
                          f"({signal_count} signals)")
                    print(f"        Quality: {alloc['quality_score']:.0f}/100 ({alloc['quality_tier']})")
                    print(
                        f"        Price: ${price:.2f} | Cost: ${cost:,.2f} ({alloc['pct_portfolio']:.1f}% of portfolio)")
                    print(f"        Signal: {buy_signal['signal_type']} | Vol: {vol_display}")
                    print(
                        f"        Multiplier: {alloc['total_multiplier']:.2f}x (Q:{alloc['quality_multiplier']:.2f} × "
                        f"C:{alloc['conviction_multiplier']:.2f} × A:{alloc['award_multiplier']:.2f} × "
                        f"V:{alloc['volatility_multiplier']:.2f} × R:{alloc['regime_multiplier']:.2f})")
                    print()

                    # Track position with entry signal and score
                    self.position_monitor.track_position(
                        ticker,
                        current_date,
                        buy_signal.get('signal_type', 'unknown'),
                        entry_score=signal_count
                    )

                    # Create and submit order
                    order = self.create_order(ticker, quantity, 'buy')
                    self.submit_order(order)

                    # Record buy in cooldown tracker
                    self.ticker_cooldown.record_buy(ticker, current_date)

                    # Record entry
                    execution_tracker.record_action('entries', count=1)

                except Exception as e:
                    execution_tracker.add_error(f"Buy Order - {ticker}", e)
                    continue

            print(f"{'=' * 70}\n")



            # =====================================================================
            # COMPLETE EXECUTION AND SEND EMAIL
            # =====================================================================

            execution_tracker.complete('SUCCESS')

            if not Config.BACKTESTING:
                account_email_notifications.send_daily_summary_email(self, current_date, execution_tracker)
                save_state_safe(self)

        except Exception as e:
            # Catch-all for any unhandled errors
            execution_tracker.add_error("Trading Iteration", e)
            execution_tracker.complete('FAILED')
            if not Config.BACKTESTING:
                account_email_notifications.send_daily_summary_email(self, self.get_datetime(), execution_tracker)
            raise  # Re-raise to trigger crash notification

    def on_strategy_end(self):
        """Display final statistics"""

        # Profit tracking summary
        self.profit_tracker.display_final_summary()

        # Cooldown statistics
        cooldown_stats = self.ticker_cooldown.get_statistics()
        print(f"\n{'=' * 80}")
        print(f"⏰ TICKER COOLDOWN STATISTICS")
        print(f"{'=' * 80}")
        print(f"Cooldown Period: {cooldown_stats['cooldown_days']} days")
        print(f"Total Buys Recorded: {cooldown_stats['total_buys_recorded']}")
        print(f"\nBuy Count by Ticker:")
        for ticker, count in list(cooldown_stats['buy_count_by_ticker'].items())[:10]:
            print(f"   {ticker}: {count} purchases")
        print(f"{'=' * 80}\n")

        # Rotation statistics (includes integrated blacklist)
        from stock_rotation import print_rotation_report
        print_rotation_report(self.stock_rotator)

        # Drawdown protection summary
        account_drawdown_protection.print_protection_summary(self.drawdown_protection)

        return 0