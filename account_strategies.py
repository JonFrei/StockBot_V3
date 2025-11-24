"""
SwingTradeStrategy - COMPLETE WITH PRIORITY-BASED SIGNAL SYSTEM AND CONFIRMATION

Integrated Features:
- Priority-based signal processing (no multi-signal scoring)
- Watchlist with confirmation for pullback signals
- Database-backed watchlist persistence
- Confirmation tracking in trades and final summary
- All existing features (rotation, drawdown protection, etc.)
"""

from lumibot.strategies import Strategy
from config import Config

import stock_data
import stock_signals
import stock_position_sizing
import account_profit_tracking
import stock_position_monitoring
from stock_cooldown import TickerCooldown
from server_recovery import save_state_safe, load_state_safe

# INTEGRATED IMPORTS
from stock_rotation import StockRotator
import account_drawdown_protection
import account_broker_data

from lumibot.brokers import Alpaca

broker = Alpaca(Config.get_alpaca_config())


class SwingTradeStrategy(Strategy):

    def initialize(self, send_emails=True):
        """Initialize strategy with clean signal architecture"""
        if Config.BACKTESTING:
            self.sleeptime = "1D"
        else:
            self.sleeptime = "10M"

        self.tickers = self.parameters.get("tickers", [])
        self.last_trade_date = None

        # Tracking systems
        self.profit_tracker = account_profit_tracking.ProfitTracker(self)
        self.order_logger = account_profit_tracking.OrderLogger(self)
        self.metrics_recorder = account_profit_tracking.DailyMetricsRecorder(self)
        self.position_monitor = stock_position_monitoring.PositionMonitor(self)
        self.ticker_cooldown = TickerCooldown(cooldown_days=1)

        # Stock rotation
        self.stock_rotator = StockRotator(
            rotation_frequency='weekly',
            profit_tracker=self.profit_tracker
        )

        # Rotation controls
        self.idle_iterations_without_buys = 0
        self.force_rotation_next_cycle = False
        self.last_rotation_week = None

        # Drawdown protection
        self.drawdown_protection = account_drawdown_protection.create_default_protection(
            threshold_pct=-10.0,
            recovery_days=5
        )

        # NEW: Signal processing system
        self.signal_processor = stock_signals.SignalProcessor()
        self.watchlist = stock_signals.Watchlist(strategy=self)

        print(f"✅ Signal Processor: Priority-based (no multi-signal scoring)")
        print(f"   Immediate Signals: {', '.join(stock_signals.SignalConfiguration.IMMEDIATE_SIGNALS)}")
        print(f"   Confirmation Signals: {', '.join(stock_signals.SignalConfiguration.CONFIRMATION_SIGNALS)}")
        print(f"✅ Watchlist: Database-backed with confirmation tracking")
        print(f"✅ Drawdown Protection: {self.drawdown_protection.threshold_pct:.1f}% threshold")
        print(f"✅ Ticker Cooldown: {self.ticker_cooldown.cooldown_days} days")
        print(f"✅ Stock Rotation: Weekly award-based system")

        if not Config.BACKTESTING:
            window_info = account_broker_data.get_trading_window_info()
            print(f"✅ Trading Window: {window_info['start_time_str']} - {window_info['end_time_str']} EST")

    def before_starting_trading(self):
        """
        Startup sequence with automatic broker reconciliation
        """
        if Config.BACKTESTING:
            return

        print(f"\n{'🚀' * 40}")
        print(f"STARTING TRADING BOT - INITIALIZATION SEQUENCE")
        print(f"{'🚀' * 40}\n")

        # Load saved state from database (includes watchlist)
        load_state_safe(self)

        print(f"[STARTUP] Initialization complete\n")

    def on_trading_iteration(self):
        """Main trading loop - clean architecture with watchlist confirmation"""

        # Create execution tracker for email reporting
        import account_email_notifications
        execution_tracker = account_email_notifications.ExecutionTracker()

        try:
            # Market checks (live mode only)
            if not Config.BACKTESTING:
                try:
                    if not self.broker.is_market_open():
                        print(f"[INFO] Market is closed - skipping iteration")
                        execution_tracker.add_warning("Market is closed")
                        execution_tracker.complete('SUCCESS')
                        account_email_notifications.send_daily_summary_email(
                            self, self.get_datetime(), execution_tracker
                        )
                        return
                except Exception as e:
                    print(f"[WARN] Could not check market status: {e}")
                    execution_tracker.add_error("Market Status Check", e)

                if account_broker_data.has_traded_today(self, self.last_trade_date):
                    execution_tracker.add_warning("Already traded today")
                    execution_tracker.complete('SUCCESS')
                    account_email_notifications.send_daily_summary_email(
                        self, self.get_datetime(), execution_tracker
                    )
                    return

                if not account_broker_data.is_within_trading_window(self):
                    execution_tracker.add_warning("Outside trading window")
                    execution_tracker.complete('SUCCESS')
                    account_email_notifications.send_daily_summary_email(
                        self, self.get_datetime(), execution_tracker
                    )
                    return

            current_date = self.get_datetime()
            current_date_str = current_date.strftime('%Y-%m-%d')

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

            # Display watchlist status
            watchlist_stats = self.watchlist.get_statistics()
            if watchlist_stats['total_entries'] > 0:
                print(f"\n📋 Watchlist Status: {watchlist_stats['total_entries']} entries")
                for signal_type, count in watchlist_stats['by_signal'].items():
                    print(f"   {signal_type}: {count}")

            print('\n')

            # =================================================================
            # DRAWDOWN PROTECTION
            # =================================================================

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

                execution_tracker.complete('SUCCESS')
                if not Config.BACKTESTING:
                    account_email_notifications.send_daily_summary_email(
                        self, current_date, execution_tracker
                    )
                return

            if self.drawdown_protection.is_in_recovery(current_date):
                self.drawdown_protection.print_status(self.portfolio_value, current_date)
                execution_tracker.add_warning("In drawdown recovery period - no new positions")

            # =================================================================
            # FETCH DATA
            # =================================================================

            try:
                all_tickers = list(set(self.tickers + ['SPY'] + [p.symbol for p in self.get_positions()]))
                all_stock_data = stock_data.process_data(all_tickers, current_date)
                spy_data = all_stock_data.get('SPY', {}).get('indicators', None) if 'SPY' in all_stock_data else None
            except Exception as e:
                execution_tracker.add_error("Data Fetch", e)
                execution_tracker.complete('FAILED')
                if not Config.BACKTESTING:
                    account_email_notifications.send_daily_summary_email(
                        self, current_date, execution_tracker
                    )
                return

            # =================================================================
            # MARKET REGIME DETECTION
            # =================================================================

            try:
                global_regime_info = account_drawdown_protection.detect_market_regime(spy_data)
                print(account_drawdown_protection.format_regime_display(global_regime_info))
            except Exception as e:
                execution_tracker.add_error("Market Regime Detection", e)
                global_regime_info = {'allow_trading': True, 'position_size_multiplier': 1.0}

            # Clean expired blacklists
            try:
                if self.stock_rotator.blacklist:
                    self.stock_rotator.blacklist.clean_expired_blacklists(current_date)
            except Exception as e:
                execution_tracker.add_error("Blacklist Cleanup", e)

            # =================================================================
            # STEP 1: CHECK POSITIONS FOR EXITS
            # =================================================================

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
                    ticker_cooldown=self.ticker_cooldown
                )

                if exit_orders:
                    execution_tracker.record_action('exits', count=len(exit_orders))

            except Exception as e:
                execution_tracker.add_error("Position Exit Processing", e)

            # =================================================================
            # SKIP NEW POSITIONS IF IN RECOVERY OR BEAR MARKET
            # =================================================================

            if self.drawdown_protection.is_in_recovery(current_date):
                print(f"⚠️ In drawdown recovery - no new positions")
                execution_tracker.complete('SUCCESS')
                if not Config.BACKTESTING:
                    account_email_notifications.send_daily_summary_email(
                        self, current_date, execution_tracker
                    )
                return

            if not global_regime_info.get('allow_trading', True):
                print(f"\n⚠️ {global_regime_info['description']}")
                print(f"No new positions will be opened.\n")
                execution_tracker.add_warning(f"Trading blocked: {global_regime_info['description']}")
                execution_tracker.complete('SUCCESS')
                if not Config.BACKTESTING:
                    account_email_notifications.send_daily_summary_email(
                        self, current_date, execution_tracker
                    )
                return

            # =================================================================
            # STEP 2: STOCK ROTATION
            # =================================================================

            try:
                current_week = current_date.isocalendar()[1]
                current_year = current_date.year
                weekly_period = (current_year, current_week)
                force_rotation = False

                if self.stock_rotator.rotation_count == 0:
                    force_rotation = True
                    print(f"\n🌀 INITIAL ROTATION: First evaluation on startup")

                if self.force_rotation_next_cycle:
                    force_rotation = True
                    print(f"\n🌀 FORCED ROTATION: No entries for {self.idle_iterations_without_buys} iterations")

                if self.last_rotation_week != weekly_period or force_rotation:
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
                    active_tickers = self.stock_rotator.active_tickers

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
                active_tickers = self.tickers

            # =================================================================
            # STEP 3: CHECK WATCHLIST FOR CONFIRMATIONS (Priority)
            # =================================================================

            print(f"\n{'=' * 80}")
            print(f"🔍 STEP 1: CHECKING WATCHLIST FOR CONFIRMATIONS")
            print(f"{'=' * 80}")

            confirmed_entries = []

            try:
                confirmation_results = self.watchlist.check_confirmations(
                    all_stock_data,
                    current_date
                )

                for result in confirmation_results:
                    ticker = result['ticker']

                    if result['confirmed']:
                        print(f"✅ CONFIRMED: {ticker} - {result['signal_type']} - {result['reason']}")
                        confirmed_entries.append(result)
                    else:
                        print(f"⏳ WAITING: {ticker} - {result['signal_type']} - {result['reason']}")

                if not confirmation_results:
                    print(f"   (No entries on watchlist)")

            except Exception as e:
                execution_tracker.add_error("Watchlist Confirmation Check", e)

            # =================================================================
            # STEP 4: SCAN FOR NEW SIGNALS
            # =================================================================

            print(f"\n{'=' * 80}")
            print(f"🔍 STEP 2: SCANNING FOR NEW SIGNALS")
            print(f"{'=' * 80}")

            immediate_buys = []
            watchlist_adds = []

            for ticker in active_tickers:
                try:
                    # Skip if already have position
                    if ticker in self.positions:
                        continue

                    # Skip if already on watchlist
                    if self.watchlist.contains(ticker):
                        continue

                    # Skip if on cooldown
                    if not self.ticker_cooldown.can_buy(ticker, current_date):
                        continue

                    # Get data
                    if ticker not in all_stock_data:
                        continue

                    data = all_stock_data[ticker]['indicators']

                    # Volatility filter
                    vol_metrics = data.get('volatility_metrics', {})
                    if not vol_metrics.get('allow_trading', True):
                        print(f"   ⚠️ {ticker} BLOCKED: {vol_metrics['risk_class'].upper()} volatility")
                        continue

                    # Check regime for this ticker
                    ticker_regime = account_drawdown_protection.detect_market_regime(spy_data, stock_data=data)
                    if not ticker_regime.get('allow_trading', True):
                        continue

                    # Process through signal pipeline
                    signal_result = self.signal_processor.process_ticker(ticker, data, spy_data)

                    if signal_result['action'] == 'buy_now':
                        immediate_buys.append({
                            'ticker': ticker,
                            'signal_result': signal_result,
                            'data': data,
                            'regime': ticker_regime,
                            'vol_metrics': vol_metrics
                        })
                        print(f"🟢 IMMEDIATE: {ticker} - {signal_result['signal_type']}")

                    elif signal_result['action'] == 'add_to_watchlist':
                        watchlist_adds.append({
                            'ticker': ticker,
                            'signal_result': signal_result,
                            'data': data,
                            'regime': ticker_regime,
                            'vol_metrics': vol_metrics
                        })
                        print(f"📋 TO WATCHLIST: {ticker} - {signal_result['signal_type']}")

                except Exception as e:
                    execution_tracker.add_error(f"Signal Processing - {ticker}", e)
                    continue

            if not immediate_buys and not watchlist_adds and not confirmed_entries:
                print(f"   (No signals found)")

            # =================================================================
            # STEP 5: COLLECT ALL BUY OPPORTUNITIES
            # =================================================================

            all_opportunities = []

            # Add confirmed entries from watchlist
            for result in confirmed_entries:
                ticker = result['ticker']

                if ticker not in all_stock_data:
                    continue

                data = all_stock_data[ticker]['indicators']

                # Get fresh regime and vol metrics
                ticker_regime = account_drawdown_protection.detect_market_regime(spy_data, stock_data=data)
                vol_metrics = data.get('volatility_metrics', {})

                all_opportunities.append({
                    'ticker': ticker,
                    'signal_type': result['signal_type'],
                    'signal_data': result['signal_data'],
                    'data': data,
                    'regime': ticker_regime,
                    'vol_metrics': vol_metrics,
                    'source': 'watchlist',
                    'watchlist_age': result['watchlist_age'],
                    'date_added': result['date_added'],
                    'current_price': result['current_price']
                })

            # Add immediate buys
            for opp in immediate_buys:
                all_opportunities.append({
                    'ticker': opp['ticker'],
                    'signal_type': opp['signal_result']['signal_type'],
                    'signal_data': opp['signal_result']['signal_data'],
                    'data': opp['data'],
                    'regime': opp['regime'],
                    'vol_metrics': opp['vol_metrics'],
                    'source': 'immediate'
                })

            # =================================================================
            # STEP 6: ADD TO WATCHLIST (If Applicable)
            # =================================================================

            if watchlist_adds:
                print(f"\n{'=' * 80}")
                print(f"📋 STEP 3: ADDING TO WATCHLIST ({len(watchlist_adds)})")
                print(f"{'=' * 80}")

                for opp in watchlist_adds:
                    try:
                        self.watchlist.add(
                            opp['ticker'],
                            opp['signal_result']['signal_type'],
                            opp['signal_result']['signal_data'],
                            current_date
                        )
                    except Exception as e:
                        execution_tracker.add_error(f"Watchlist Add - {opp['ticker']}", e)

                print()

            # =================================================================
            # STEP 7: AGE OUT STALE WATCHLIST ENTRIES
            # =================================================================

            try:
                self.watchlist.age_out_stale_entries(current_date, max_age_days=5)
            except Exception as e:
                execution_tracker.add_error("Watchlist Age Out", e)

            # =================================================================
            # STEP 8: POSITION SIZING FOR BUY OPPORTUNITIES
            # =================================================================

            if not all_opportunities:
                print(f"\n📊 No buy opportunities this iteration\n")
                execution_tracker.complete('SUCCESS')
                if not Config.BACKTESTING:
                    account_email_notifications.send_daily_summary_email(
                        self, current_date, execution_tracker
                    )
                return

            try:
                portfolio_context = stock_position_sizing.create_portfolio_context(self)

                if portfolio_context['deployable_cash'] <= 0:
                    print(f"\n⚠️ No deployable cash available\n")
                    execution_tracker.add_warning("No deployable cash")
                    execution_tracker.complete('SUCCESS')
                    if not Config.BACKTESTING:
                        account_email_notifications.send_daily_summary_email(
                            self, current_date, execution_tracker
                        )
                    return

                if portfolio_context['available_slots'] <= 0:
                    print(f"\n⚠️ No available position slots\n")
                    execution_tracker.add_warning("No available slots")
                    execution_tracker.complete('SUCCESS')
                    if not Config.BACKTESTING:
                        account_email_notifications.send_daily_summary_email(
                            self, current_date, execution_tracker
                        )
                    return

                # Build opportunities for position sizing
                sizing_opportunities = []

                for opp in all_opportunities:
                    ticker = opp['ticker']
                    data = opp['data']

                    # Calculate quality score (single signal = 1)
                    quality_score = stock_position_sizing.calculate_opportunity_quality(
                        ticker, data, spy_data, signal_count=1
                    )

                    # Get multipliers
                    award = self.stock_rotator.get_award(ticker)
                    award_multiplier = self.stock_rotator.get_award_multiplier(ticker)
                    regime_multiplier = opp['regime'].get('position_size_multiplier', 1.0)
                    volatility_multiplier = opp['vol_metrics'].get('position_multiplier', 1.0)

                    sizing_opportunities.append({
                        'ticker': ticker,
                        'data': data,
                        'buy_signal': opp['signal_data'],
                        'quality_score': quality_score,
                        'signal_count': 1,  # Single signal per ticker
                        'award': award,
                        'award_multiplier': award_multiplier,
                        'regime_multiplier': regime_multiplier,
                        'volatility_multiplier': volatility_multiplier,
                        'vol_metrics': opp['vol_metrics'],
                        'ticker_regime': opp['regime'],
                        'signal_type': opp['signal_type'],
                        'source': opp['source']
                    })

                allocations = stock_position_sizing.calculate_independent_position_sizes(
                    sizing_opportunities,
                    portfolio_context
                )

                if not allocations:
                    print(f"\n⚠️ No positions met minimum size requirements\n")
                    execution_tracker.add_warning("No positions met minimum size")
                    execution_tracker.complete('SUCCESS')
                    if not Config.BACKTESTING:
                        account_email_notifications.send_daily_summary_email(
                            self, current_date, execution_tracker
                        )
                    return

            except Exception as e:
                execution_tracker.add_error("Position Sizing", e)
                execution_tracker.complete('FAILED')
                if not Config.BACKTESTING:
                    account_email_notifications.send_daily_summary_email(
                        self, current_date, execution_tracker
                    )
                return

            # =================================================================
            # STEP 9: EXECUTE BUY ORDERS
            # =================================================================

            print(f"\n{'=' * 80}")
            print(f"💰 STEP 4: EXECUTING BUY ORDERS ({len(allocations)})")
            print(f"{'=' * 80}\n")

            for alloc in allocations:
                try:
                    ticker = alloc['ticker']
                    quantity = alloc['quantity']
                    cost = alloc['cost']
                    price = alloc['price']

                    # Find original opportunity data
                    opp = next((o for o in sizing_opportunities if o['ticker'] == ticker), None)
                    if not opp:
                        continue

                    signal_type = opp['signal_type']
                    source = opp['source']

                    award_emoji = {
                        'premium': '🥇', 'standard': '🥈', 'trial': '🔬',
                        'none': '⚪', 'frozen': '❄️'
                    }.get(alloc['award'], '❓')

                    source_emoji = '✅' if source == 'watchlist' else '🟢'
                    source_label = 'CONFIRMED' if source == 'watchlist' else 'IMMEDIATE'

                    vol_display = opp['vol_metrics']['risk_class'].upper()

                    print(
                        f" {source_emoji} BUY: {ticker} x{quantity} [{source_label}] [{award_emoji} {alloc['award'].upper()}]")
                    print(f"        Signal: {signal_type}")
                    print(f"        Quality: {alloc['quality_score']:.0f}/100 ({alloc['quality_tier']})")
                    print(f"        Price: ${price:.2f} | Cost: ${cost:,.2f} ({alloc['pct_portfolio']:.1f}%)")
                    print(f"        Vol: {vol_display} | Multiplier: {alloc['total_multiplier']:.2f}x")
                    print()

                    # Track confirmation metadata
                    was_watchlisted = (source == 'watchlist')
                    confirmation_date = current_date if was_watchlisted else None
                    days_to_confirmation = 0

                    # Get days to confirmation if from watchlist
                    if was_watchlisted:
                        watchlist_entry = next(
                            (r for r in confirmation_results if r['ticker'] == ticker),
                            None
                        )
                        if watchlist_entry:
                            days_to_confirmation = (current_date - watchlist_entry['date_added']).days

                    # Track position
                    self.position_monitor.track_position(
                        ticker,
                        current_date,
                        signal_type,
                        entry_score=1
                    )

                    # Store confirmation metadata in position tracking
                    if ticker in self.position_monitor.positions_metadata:
                        self.position_monitor.positions_metadata[ticker]['was_watchlisted'] = was_watchlisted
                        self.position_monitor.positions_metadata[ticker]['confirmation_date'] = confirmation_date
                        self.position_monitor.positions_metadata[ticker]['days_to_confirmation'] = days_to_confirmation

                    # Submit order
                    order = self.create_order(ticker, quantity, 'buy')
                    self.submit_order(order)

                    # Record in cooldown
                    self.ticker_cooldown.record_buy(ticker, current_date)

                    # Remove from watchlist if confirmed
                    if source == 'watchlist':
                        current_price = opp['data'].get('close', 0)
                        self.watchlist.remove(ticker, removal_reason='confirmed', current_price=current_price)

                    # Log order with confirmation tracking
                    if hasattr(self, 'order_logger'):
                        self.order_logger.log_order(
                            ticker=ticker,
                            side='buy',
                            quantity=quantity,
                            signal_type=signal_type,
                            award=alloc['award'],
                            quality_score=alloc['quality_score'],
                            was_watchlisted=was_watchlisted,
                            days_on_watchlist=days_to_confirmation
                        )

                    execution_tracker.record_action('entries', count=1)

                except Exception as e:
                    execution_tracker.add_error(f"Buy Order - {ticker}", e)
                    continue

            print(f"{'=' * 80}\n")

            # =================================================================
            # COMPLETE EXECUTION
            # =================================================================

            execution_tracker.complete('SUCCESS')

            if not Config.BACKTESTING:
                account_email_notifications.send_daily_summary_email(
                    self, current_date, execution_tracker
                )
                save_state_safe(self)

        except Exception as e:
            execution_tracker.add_error("Trading Iteration", e)
            execution_tracker.complete('FAILED')
            if not Config.BACKTESTING:
                account_email_notifications.send_daily_summary_email(
                    self, self.get_datetime(), execution_tracker
                )
            raise

    def on_strategy_end(self):
        """Display final statistics"""

        self.profit_tracker.display_final_summary()

        # Display watchlist statistics
        if hasattr(self, 'watchlist'):
            self._display_watchlist_statistics()

        cooldown_stats = self.ticker_cooldown.get_statistics()
        print(f"\n{'=' * 80}")
        print(f"⏰ TICKER COOLDOWN STATISTICS")
        print(f"{'=' * 80}")
        print(f"Cooldown Period: {cooldown_stats['cooldown_days']} days")
        print(f"Total Buys: {cooldown_stats['total_buys_recorded']}")
        print(f"{'=' * 80}\n")

        # Force final rotation to ensure awards are current
        if self.stock_rotator.rotation_count > 0 or Config.BACKTESTING:
            print(f"\n🔄 FINAL AWARD EVALUATION...")
            try:
                current_date = self.get_datetime()

                # Fetch final data for SPY and all tickers
                import stock_data
                all_tickers = list(set(self.tickers + ['SPY']))
                all_stock_data = stock_data.process_data(all_tickers, current_date)

                # Run final rotation to update awards
                self.stock_rotator.rotate_stocks(
                    strategy=self,
                    all_candidates=self.tickers,
                    current_date=current_date,
                    all_stock_data=all_stock_data
                )
            except Exception as e:
                print(f"[WARN] Could not run final rotation: {e}")

        from stock_rotation import print_rotation_report
        print_rotation_report(self.stock_rotator)

        account_drawdown_protection.print_protection_summary(self.drawdown_protection)

        return 0

    def _display_watchlist_statistics(self):
        """Display comprehensive watchlist and confirmation statistics"""

        stats = self.watchlist.get_detailed_statistics()

        print(f"\n{'=' * 80}")
        print(f"📋 WATCHLIST & CONFIRMATION TRACKING")
        print(f"{'=' * 80}\n")

        # Overall summary
        totals = stats['totals']
        print(f"📊 OVERALL SUMMARY:")
        print(f"   Total Signals Added to Watchlist: {totals['added']}")
        print(f"   Confirmations Passed: {totals['passed']} ({totals['pass_rate']:.1f}%)")
        print(f"   Confirmations Failed: {totals['failed']}")
        print(f"   Entries Expired: {totals['expired']}")
        print(f"   Currently on Watchlist: {stats['total_entries']}")

        # By signal type
        if stats['signals_added']:
            print(f"\n📊 BY SIGNAL TYPE:")
            print(f"{'─' * 80}")

            for signal_type in sorted(stats['signals_added'].keys()):
                added = stats['signals_added'].get(signal_type, 0)
                passed = stats['confirmations_passed'].get(signal_type, 0)
                expired = stats['expired_entries'].get(signal_type, 0)

                failed_reasons = stats['confirmations_failed'].get(signal_type, {})
                total_failed = sum(failed_reasons.values())

                pass_rate = (passed / added * 100) if added > 0 else 0

                print(f"\n   🎯 {signal_type}")
                print(f"      Added to Watchlist: {added}")
                print(f"      Confirmations Passed: {passed} ({pass_rate:.1f}%)")
                print(f"      Confirmations Failed: {total_failed}")
                print(f"      Expired: {expired}")

                # Show failure reasons
                if failed_reasons:
                    print(f"      \n      Failure Breakdown:")
                    sorted_reasons = sorted(failed_reasons.items(), key=lambda x: x[1], reverse=True)
                    for reason, count in sorted_reasons[:5]:  # Top 5 reasons
                        pct = (count / total_failed * 100) if total_failed > 0 else 0
                        print(f"         • {reason}: {count} ({pct:.0f}%)")

                    if len(failed_reasons) > 5:
                        remaining = len(failed_reasons) - 5
                        print(f"         • ... and {remaining} other reasons")

        else:
            print(f"\n   ℹ️  No signals were added to watchlist during this backtest")
            print(f"   This means confirmation-required signals never triggered")

        print(f"\n{'=' * 80}\n")