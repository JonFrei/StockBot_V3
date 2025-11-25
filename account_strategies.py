"""
SwingTradeStrategy - WITH SIMPLIFIED SYSTEMS

Changes from previous version:
- Uses simplified position sizing (calculate_position_sizes instead of calculate_independent_position_sizes)
- Uses simplified regime detection (3 checks instead of 7)
- Removed quality scoring (uses signal_score directly)
- Cleaner, more maintainable code
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

# INTEGRATED IMPORTS
import account_drawdown_protection
import account_broker_data

from lumibot.brokers import Alpaca

broker = Alpaca(Config.get_alpaca_config())


class SwingTradeStrategy(Strategy):

    def initialize(self, send_emails=True):
        """Initialize strategy with simplified systems"""
        if Config.BACKTESTING:
            self.sleeptime = "1D"
        else:
            self.sleeptime = "10M"

        self.tickers = self.parameters.get("tickers", [])
        self.last_trade_date = None

        # Tracking systems
        self.profit_tracker = account_profit_tracking.ProfitTracker(self)
        self.order_logger = account_profit_tracking.OrderLogger(self)
        self.position_monitor = stock_position_monitoring.PositionMonitor(self)

        # Drawdown protection
        self.drawdown_protection = account_drawdown_protection.create_default_protection(
            threshold_pct=-8.0,
            recovery_days=5
        )

        # Signal processor
        self.signal_processor = stock_signals.SignalProcessor()

        # Stock rotation system
        self.stock_rotator = StockRotator(profit_tracker=self.profit_tracker)

        print(f"✅ Signal Processor: Centralized Scoring (0-100)")
        print(f"   Minimum Score Threshold: {stock_signals.SignalConfig.MIN_SCORE_THRESHOLD}")
        print(f"   Available Signals: {', '.join(stock_signals.BUY_STRATEGIES.keys())}")
        print(f"✅ Drawdown Protection: {self.drawdown_protection.threshold_pct:.1f}% threshold")
        print(f"✅ Position Sizing: Simplified formula (base × score × regime × volatility)")
        print(f"✅ Regime Detection: Simplified (3 critical checks)")
        print(f"✅ Stock Rotation: 3-tier system (premium 1.5x / standard 1.0x / frozen blocked)")

        if not Config.BACKTESTING:
            window_info = account_broker_data.get_trading_window_info()
            print(f"✅ Trading Window: {window_info['start_time_str']} - {window_info['end_time_str']} EST")

    def before_starting_trading(self):
        """Startup sequence with automatic broker reconciliation"""
        if Config.BACKTESTING:
            return

        print(f"\n{'🚀' * 40}")
        print(f"STARTING TRADING BOT - INITIALIZATION SEQUENCE")
        print(f"{'🚀' * 40}\n")

        # Load saved state from database
        load_state_safe(self)

        print(f"[STARTUP] Initialization complete\n")

    def on_trading_iteration(self):

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

            # =================================================================
            # DRAWDOWN PROTECTION
            # =================================================================

            if self.drawdown_protection.should_trigger(self.portfolio_value):
                try:
                    self.drawdown_protection.activate(
                        strategy=self,
                        current_date=current_date,
                        position_monitor=self.position_monitor
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
            # SIMPLIFIED MARKET REGIME DETECTION (3 checks instead of 7)
            # =================================================================

            try:
                global_regime_info = account_drawdown_protection.detect_market_regime(spy_data)
                print(account_drawdown_protection.format_regime_display(global_regime_info))

                # Early warning - Portfolio underperformance check
                current_drawdown = self.drawdown_protection.calculate_drawdown(self.portfolio_value)

                if current_drawdown <= -5.0 and global_regime_info.get('allow_trading', True):
                    if spy_data:
                        spy_close = spy_data.get('close', 0)
                        spy_sma200 = spy_data.get('sma200', 0)
                        spy_from_200 = ((spy_close - spy_sma200) / spy_sma200 * 100) if spy_sma200 > 0 else -100

                        if abs(spy_from_200) < 3.0:
                            print(
                                f"\n🔴 EARLY WARNING: Portfolio {current_drawdown:.1f}% drawdown while SPY only {spy_from_200:+.1f}% from 200 SMA")
                            print(f"⚠️ Blocking new positions - portfolio underperforming market")
                            print(f"No new positions will be opened.\n")

                            execution_tracker.add_warning(
                                f"Portfolio underperformance: {current_drawdown:.1f}% vs market")
                            execution_tracker.complete('SUCCESS')
                            if not Config.BACKTESTING:
                                account_email_notifications.send_daily_summary_email(
                                    self, current_date, execution_tracker
                                )
                            return

                if not global_regime_info.get('allow_trading', True):
                    print(f"\n⚠️ {global_regime_info['description']}")
                    print(f"🚫 BEAR MARKET DETECTED - FORCE CLOSING ALL POSITIONS")

                    # Force exit ALL positions immediately
                    positions = self.get_positions()
                    for position in positions:
                        ticker = position.symbol
                        qty = int(position.quantity)
                        if qty > 0:
                            print(f"   🚪 Bear Market Exit: {ticker} x{qty}")
                            sell_order = self.create_order(ticker, qty, 'sell')
                            self.submit_order(sell_order)
                            self.position_monitor.clean_position_metadata(ticker)
                    return

            except Exception as e:
                execution_tracker.add_error("Market Regime Detection", e)
                global_regime_info = {'allow_trading': True, 'position_size_multiplier': 1.0}

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
                    profit_tracker=self.profit_tracker
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
            # STOCK ROTATION (Weekly Evaluation)
            # =================================================================

            if should_rotate(self.stock_rotator, current_date, frequency='weekly'):
                self.stock_rotator.evaluate_stocks(self.tickers, current_date)

            # =================================================================
            # STEP 2: SCAN FOR SIGNALS
            # =================================================================

            print(f"\n{'=' * 80}")
            print(f"🔍 SCANNING FOR SIGNALS (Centralized Scoring System)")
            print(f"{'=' * 80}")

            all_opportunities = []

            for ticker in all_tickers:
                try:
                    if ticker in self.positions:
                        continue

                    # Skip frozen stocks (blocked from trading)
                    if not self.stock_rotator.is_tradeable(ticker):
                        continue

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

                    # Process through centralized scoring system
                    signal_result = self.signal_processor.process_ticker(ticker, data, spy_data)

                    if signal_result['action'] == 'buy':
                        winning_score = signal_result['score']
                        all_scores = signal_result['all_scores']

                        competitors = sorted(
                            [(sig, score) for sig, score in all_scores.items() if score > 0],
                            key=lambda x: x[1],
                            reverse=True
                        )

                        competition_str = ", ".join([f"{sig}: {score:.0f}" for sig, score in competitors[:3]])

                        print(f"🟢 SIGNAL: {ticker} - {signal_result['signal_type']} (Score: {winning_score:.0f}/100)")
                        print(f"   Competition: {competition_str}")

                        # Stock health check (blocks weak stocks even in strong market)
                        allow_entry, stock_mult, stock_reason = account_drawdown_protection.check_stock_regime(ticker,
                                                                                                               data)
                        print(f"   {stock_reason}")

                        if not allow_entry:
                            continue  # Skip this stock

                        all_opportunities.append({
                            'ticker': ticker,
                            'signal_type': signal_result['signal_type'],
                            'signal_data': signal_result['signal_data'],
                            'score': winning_score,
                            'all_scores': all_scores,
                            'data': data,
                            'regime': ticker_regime,
                            'vol_metrics': vol_metrics,
                            'stock_regime_mult': stock_mult,
                            'rotation_mult': self.stock_rotator.get_multiplier(ticker),
                            'rotation_award': self.stock_rotator.get_award(ticker),
                            'source': 'scored'
                        })
                    elif signal_result['action'] == 'skip' and signal_result.get('reason'):
                        if signal_result.get('all_scores'):
                            best_score = max(signal_result['all_scores'].values())
                            if best_score > 0:
                                print(f"   ⚠️ {ticker}: Best score {best_score:.0f}/100 - {signal_result['reason']}")

                except Exception as e:
                    execution_tracker.add_error(f"Signal Processing - {ticker}", e)
                    continue

            if not all_opportunities:
                print(f"   (No signals above threshold of {stock_signals.SignalConfig.MIN_SCORE_THRESHOLD})")

            # =================================================================
            # STEP 3: SIMPLIFIED POSITION SIZING
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

                # Build opportunities for simplified position sizing
                sizing_opportunities = []

                for opp in all_opportunities:
                    ticker = opp['ticker']
                    data = opp['data']
                    signal_score = opp['score']

                    # Quality floor check (removed complex quality scoring)
                    if signal_score < 60:  # Signal processor already enforces this
                        print(f"   ⚠️ {ticker}: Score {signal_score:.0f}/100 below threshold - SKIPPED")
                        continue

                    sizing_opportunities.append({
                        'ticker': ticker,
                        'data': data,
                        'score': signal_score,
                        'signal_type': opp['signal_type'],
                        'regime': opp['regime'],
                        'vol_metrics': opp['vol_metrics'],
                        'stock_regime_mult': opp.get('stock_regime_mult', 1.0)  # Stock health multiplier
                    })

                # SIMPLIFIED POSITION SIZING (uses new calculate_position_sizes function)
                allocations = stock_position_sizing.calculate_position_sizes(
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
            # STEP 4: EXECUTE BUY ORDERS
            # =================================================================

            print(f"\n{'=' * 80}")
            print(f"💰 EXECUTING BUY ORDERS ({len(allocations)})")
            print(f"{'=' * 80}\n")

            for alloc in allocations:
                try:
                    ticker = alloc['ticker']
                    quantity = alloc['quantity']
                    cost = alloc['cost']
                    price = alloc['price']
                    signal_type = alloc['signal_type']
                    signal_score = alloc['signal_score']

                    print(f" 🟢 BUY: {ticker} x{quantity}")
                    print(f"        Signal: {signal_type} (Score: {signal_score:.0f}/100)")
                    print(f"        Price: ${price:.2f} | Cost: ${cost:,.2f} ({alloc['pct_portfolio']:.1f}%)")
                    stock_mult = alloc.get('stock_mult', 1.0)
                    print(
                        f"        Multipliers: Regime {alloc['regime_mult']:.2f}x × Vol {alloc['vol_mult']:.2f}x × Health {stock_mult:.2f}x")
                    print()

                    # Track position
                    self.position_monitor.track_position(
                        ticker,
                        current_date,
                        signal_type,
                        entry_score=signal_score
                    )

                    # Submit order
                    order = self.create_order(ticker, quantity, 'buy')
                    self.submit_order(order)

                    # Log order
                    if hasattr(self, 'order_logger'):
                        self.order_logger.log_order(
                            ticker=ticker,
                            side='buy',
                            quantity=quantity,
                            signal_type=signal_type,
                            award='standard',
                            quality_score=signal_score
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
        """Display final statistics with all components"""
        self.profit_tracker.display_final_summary(
            stock_rotator=self.stock_rotator,
            drawdown_protection=self.drawdown_protection
        )
        return 0