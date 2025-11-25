"""
SwingTradeStrategy - WITH NEW PROFESSIONAL SAFEGUARD SYSTEM

UPDATED:
- Replaced DrawdownProtection with MarketRegimeDetector
- Integrated Distribution Days, Sequential Stops, SPY Extension tracking
- Added stop loss recording to regime detector
- Applied regime position size multipliers
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

# UPDATED IMPORTS
from account_drawdown_protection import MarketRegimeDetector, SafeguardConfig, format_regime_display
import account_broker_data

from lumibot.brokers import Alpaca

broker = Alpaca(Config.get_alpaca_config())


class SwingTradeStrategy(Strategy):

    def initialize(self, send_emails=True):
        """Initialize strategy with new safeguard system"""
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

        # NEW: Market safeguard system (replaces DrawdownProtection)
        self.regime_detector = MarketRegimeDetector()

        # Signal processor
        self.signal_processor = stock_signals.SignalProcessor()

        # Stock rotation system
        self.stock_rotator = StockRotator(profit_tracker=self.profit_tracker)

        print(f"✅ Signal Processor: Centralized Scoring (0-100)")
        print(f"   Minimum Score Threshold: {stock_signals.SignalConfig.MIN_SCORE_THRESHOLD}")
        print(f"   Available Signals: {', '.join(stock_signals.BUY_STRATEGIES.keys())}")
        print(f"✅ Market Safeguard: 3-technique system (Distribution Days, Sequential Stops, SPY Extension)")
        print(f"✅ Position Sizing: Simplified formula (base × score × regime × volatility)")
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
            # FETCH DATA (INCLUDING SPY FOR SAFEGUARD SYSTEM)
            # =================================================================

            try:
                # Fetch all data including SPY
                all_tickers = list(set(self.tickers + ['SPY'] + [p.symbol for p in self.get_positions()]))
                all_stock_data = stock_data.process_data(all_tickers, current_date)

                # Extract SPY data for regime detection
                if 'SPY' in all_stock_data:
                    spy_indicators = all_stock_data['SPY']['indicators']
                    spy_raw = all_stock_data['SPY'].get('raw')

                    # Get current values
                    spy_close = spy_indicators['close']
                    spy_50_sma = spy_indicators['ema50']  # Use EMA50 as proxy
                    spy_200_sma = spy_indicators['sma200']

                    # Get previous day data for distribution day tracking
                    if spy_raw is not None and len(spy_raw) >= 2:
                        spy_prev_close = spy_raw['close'].iloc[-2]
                        spy_volume = spy_raw['volume'].iloc[-1]
                        spy_prev_volume = spy_raw['volume'].iloc[-2]
                    else:
                        spy_prev_close = None
                        spy_volume = None
                        spy_prev_volume = None

                    # Update regime detector
                    self.regime_detector.update_spy(
                        current_date,
                        spy_close,
                        spy_50_sma,
                        spy_200_sma,
                        spy_prev_close,
                        spy_volume,
                        spy_prev_volume
                    )
                else:
                    print(f"[WARN] No SPY data - safeguard system operating in degraded mode")

            except Exception as e:
                execution_tracker.add_error("Data Fetch", e)
                execution_tracker.complete('FAILED')
                if not Config.BACKTESTING:
                    account_email_notifications.send_daily_summary_email(
                        self, current_date, execution_tracker
                    )
                return

            # =================================================================
            # NEW MARKET SAFEGUARD SYSTEM (REPLACES DRAWDOWN PROTECTION)
            # =================================================================

            try:
                # Get current regime status
                num_positions = len(self.get_positions())
                regime_result = self.regime_detector.detect_regime(num_positions, current_date)

                # Display regime status
                print(format_regime_display(regime_result))

                # Handle exit signal
                if regime_result['action'] == 'exit_all':
                    print(f"\n🚨 SAFEGUARD EXIT: Closing all positions")

                    # Force close all positions
                    positions = self.get_positions()
                    for position in positions:
                        ticker = position.symbol
                        qty = int(position.quantity)
                        if qty > 0:
                            print(f"   🚪 Safeguard Exit: {ticker} x{qty}")
                            sell_order = self.create_order(ticker, qty, 'sell')
                            self.submit_order(sell_order)
                            self.position_monitor.clean_position_metadata(ticker)

                    execution_tracker.record_action('exits', count=num_positions)
                    execution_tracker.record_action('drawdown_protection')
                    execution_tracker.complete('SUCCESS')

                    if not Config.BACKTESTING:
                        account_email_notifications.send_daily_summary_email(
                            self, current_date, execution_tracker
                        )

                    save_state_safe(self)
                    return

                # Block new entries if not allowed
                if not regime_result['allow_new_entries']:
                    print(f"\n⚠️ New entries blocked by safeguard system")
                    print(f"Reason: {regime_result['reason']}\n")

                    execution_tracker.add_warning(f"Trading blocked: {regime_result['reason']}")

            except Exception as e:
                execution_tracker.add_error("Market Safeguard Detection", e)
                # Default to safe mode on error
                regime_result = {
                    'action': 'caution',
                    'position_size_multiplier': 0.75,
                    'allow_new_entries': True,
                    'reason': 'Safeguard error - operating in caution mode'
                }

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
            # SKIP NEW POSITIONS IF BLOCKED BY SAFEGUARD
            # =================================================================

            if not regime_result['allow_new_entries']:
                execution_tracker.complete('SUCCESS')
                if not Config.BACKTESTING:
                    account_email_notifications.send_daily_summary_email(
                        self, current_date, execution_tracker
                    )
                save_state_safe(self)
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

                    # Process through centralized scoring system
                    signal_result = self.signal_processor.process_ticker(ticker, data, None)

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

                        all_opportunities.append({
                            'ticker': ticker,
                            'signal_type': signal_result['signal_type'],
                            'signal_data': signal_result['signal_data'],
                            'score': winning_score,
                            'all_scores': all_scores,
                            'data': data,
                            'vol_metrics': vol_metrics,
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
            # STEP 3: POSITION SIZING WITH REGIME MULTIPLIER
            # =================================================================

            if not all_opportunities:
                print(f"\n📊 No buy opportunities this iteration\n")
                execution_tracker.complete('SUCCESS')
                if not Config.BACKTESTING:
                    account_email_notifications.send_daily_summary_email(
                        self, current_date, execution_tracker
                    )
                save_state_safe(self)
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
                    save_state_safe(self)
                    return

                if portfolio_context['available_slots'] <= 0:
                    print(f"\n⚠️ No available position slots\n")
                    execution_tracker.add_warning("No available slots")
                    execution_tracker.complete('SUCCESS')
                    if not Config.BACKTESTING:
                        account_email_notifications.send_daily_summary_email(
                            self, current_date, execution_tracker
                        )
                    save_state_safe(self)
                    return

                # Build opportunities for position sizing
                sizing_opportunities = []

                for opp in all_opportunities:
                    ticker = opp['ticker']
                    data = opp['data']
                    signal_score = opp['score']

                    # Quality floor check
                    if signal_score < 60:
                        print(f"   ⚠️ {ticker}: Score {signal_score:.0f}/100 below threshold - SKIPPED")
                        continue

                    sizing_opportunities.append({
                        'ticker': ticker,
                        'data': data,
                        'score': signal_score,
                        'signal_type': opp['signal_type'],
                        'vol_metrics': opp['vol_metrics'],
                    })

                # Get regime multiplier
                regime_multiplier = regime_result['position_size_multiplier']

                # POSITION SIZING with regime multiplier
                allocations = stock_position_sizing.calculate_position_sizes(
                    sizing_opportunities,
                    portfolio_context,
                    regime_multiplier  # NEW: Pass regime multiplier
                )

                if not allocations:
                    print(f"\n⚠️ No positions met minimum size requirements\n")
                    execution_tracker.add_warning("No positions met minimum size")
                    execution_tracker.complete('SUCCESS')
                    if not Config.BACKTESTING:
                        account_email_notifications.send_daily_summary_email(
                            self, current_date, execution_tracker
                        )
                    save_state_safe(self)
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
                    print(f"        Multipliers: Regime {alloc['regime_mult']:.2f}x × Vol {alloc['vol_mult']:.2f}x")
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
        """Display final statistics with safeguard system"""
        self.profit_tracker.display_final_summary(
            stock_rotator=self.stock_rotator,
            regime_detector=self.regime_detector  # NEW: Pass regime detector
        )
        return 0