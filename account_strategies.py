"""
SwingTradeStrategy - WITH PORTFOLIO SAFEGUARDS

Changes:
- Calls update_portfolio_value() for peak drawdown tracking
- Stop loss recording already handled by stock_position_monitoring.py
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
from account_drawdown_protection import MarketRegimeDetector, SafeguardConfig
import account_broker_data
from account_profit_tracking import get_summary, reset_summary

from lumibot.brokers import Alpaca

broker = Alpaca(Config.get_alpaca_config())

# =============================================================================
# CAUTION REGIME CONFIGURATION
# =============================================================================
CAUTION_MIN_PROFIT_PCT = 0.0  # Only sell during caution if +3% or more


class SwingTradeStrategy(Strategy):

    def initialize(self, send_emails=True):
        """Initialize strategy"""
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
        self.regime_detector = MarketRegimeDetector()
        self.signal_processor = stock_signals.SignalProcessor()
        self.stock_rotator = StockRotator(profit_tracker=self.profit_tracker)

        # Startup info (once only)
        print(f"\n{'=' * 60}")
        print(f"🤖 SwingTradeStrategy Initialized")
        print(f"   Tickers: {len(self.tickers)} | Threshold: {stock_signals.SignalConfig.MIN_SCORE_THRESHOLD}")
        print(f"   Mode: {'BACKTEST' if Config.BACKTESTING else 'LIVE'}")
        print(f"   Peak Drawdown Protection: {SafeguardConfig.PEAK_DRAWDOWN_ENABLED} ({SafeguardConfig.PEAK_DRAWDOWN_THRESHOLD}%)")
        print(f"   Stop Loss Counter: {SafeguardConfig.STOP_LOSS_COUNTER_ENABLED} ({SafeguardConfig.STOP_LOSS_RATE_THRESHOLD}% rate)")
        print(f"{'=' * 60}\n")

    def before_starting_trading(self):
        """Startup sequence"""
        if Config.BACKTESTING:
            return
        load_state_safe(self)

    def on_trading_iteration(self):
        import account_email_notifications
        execution_tracker = account_email_notifications.ExecutionTracker()

        # Reset daily summary
        summary = reset_summary()

        try:
            # Market checks (live mode)
            if not Config.BACKTESTING:
                try:
                    if not self.broker.is_market_open():
                        return
                except Exception as e:
                    pass

                if account_broker_data.has_traded_today(self, self.last_trade_date):
                    return

                if not account_broker_data.is_within_trading_window(self):
                    return

            current_date = self.get_datetime()

            if not Config.BACKTESTING:
                self.last_trade_date = current_date.date()

            # Set summary context
            summary.set_context(current_date, self.portfolio_value, self.get_cash())

            # =================================================================
            # UPDATE PORTFOLIO VALUE FOR PEAK DRAWDOWN TRACKING (NEW)
            # =================================================================
            self.regime_detector.update_portfolio_value(current_date, self.portfolio_value)

            # =================================================================
            # FETCH DATA
            # =================================================================
            try:
                all_tickers = list(set(self.tickers + ['SPY'] + [p.symbol for p in self.get_positions()]))
                all_stock_data = stock_data.process_data(all_tickers, current_date)

                # Update regime detector with SPY
                if 'SPY' in all_stock_data:
                    spy_indicators = all_stock_data['SPY']['indicators']
                    spy_raw = all_stock_data['SPY'].get('raw')

                    spy_close = spy_indicators['close']
                    spy_50_sma = spy_indicators['ema50']
                    spy_200_sma = spy_indicators['sma200']

                    spy_prev_close = spy_raw['close'].iloc[-2] if spy_raw is not None and len(spy_raw) >= 2 else None
                    spy_volume = spy_raw['volume'].iloc[-1] if spy_raw is not None and len(spy_raw) >= 2 else None
                    spy_prev_volume = spy_raw['volume'].iloc[-2] if spy_raw is not None and len(spy_raw) >= 2 else None

                    self.regime_detector.update_spy(
                        current_date, spy_close, spy_50_sma, spy_200_sma,
                        spy_prev_close, spy_volume, spy_prev_volume
                    )

            except Exception as e:
                summary.add_error(f"Data fetch failed: {e}")
                execution_tracker.add_error("Data Fetch", e)
                execution_tracker.complete('FAILED')
                summary.print_summary()
                return

            # =================================================================
            # MARKET REGIME
            # =================================================================
            try:
                num_positions = len(self.get_positions())
                regime_result = self.regime_detector.detect_regime(num_positions, current_date)

                summary.set_regime(
                    regime_result['action'],
                    regime_result['reason'],
                    regime_result['position_size_multiplier']
                )

                # Handle exit signal
                if regime_result['action'] == 'exit_all':
                    positions = self.get_positions()
                    for position in positions:
                        ticker = position.symbol
                        qty = int(position.quantity)
                        if qty > 0:
                            summary.add_exit(ticker, qty, 0, 0, 'safeguard_exit')
                            sell_order = self.create_order(ticker, qty, 'sell')
                            self.submit_order(sell_order)
                            self.position_monitor.clean_position_metadata(ticker)

                    execution_tracker.record_action('exits', count=num_positions)
                    execution_tracker.record_action('drawdown_protection')
                    execution_tracker.complete('SUCCESS')
                    summary.print_summary()
                    save_state_safe(self)
                    return

            except Exception as e:
                summary.add_error(f"Regime detection failed: {e}")
                regime_result = {
                    'action': 'caution',
                    'position_size_multiplier': 0.75,
                    'allow_new_entries': True,
                    'reason': 'Safeguard error - caution mode'
                }

            # =================================================================
            # CHECK EXITS
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
                    summary=summary  # Pass summary for logging
                )

                if exit_orders:
                    execution_tracker.record_action('exits', count=len(exit_orders))

            except Exception as e:
                summary.add_error(f"Exit processing failed: {e}")

            # =================================================================
            # CAUTION REGIME: SELL PROFITABLE POSITIONS (WITH MINIMUM THRESHOLD)
            # =================================================================
            if regime_result['action'] == 'caution':
                positions = self.get_positions()
                for position in positions:
                    try:
                        ticker = position.symbol
                        qty = int(position.quantity)
                        if qty <= 0:
                            continue

                        # Get entry price
                        entry_price = account_broker_data.get_broker_entry_price(position, self, ticker)
                        if entry_price <= 0:
                            continue

                        current_price = self.get_last_price(ticker)
                        pnl_pct = ((current_price - entry_price) / entry_price * 100)
                        pnl_dollars = (current_price - entry_price) * qty

                        # UPDATED: Only sell if profit >= CAUTION_MIN_PROFIT_PCT
                        # This prevents selling winners for pocket change (+$3, +0.1%)
                        if pnl_pct >= CAUTION_MIN_PROFIT_PCT:
                            summary.add_exit(ticker, qty, pnl_dollars, pnl_pct, 'caution_profit_take')

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
                                exit_signal={'reason': 'caution_profit_take'},
                                entry_score=entry_score
                            )

                            self.position_monitor.clean_position_metadata(ticker)

                            sell_order = self.create_order(ticker, qty, 'sell')
                            self.submit_order(sell_order)

                            execution_tracker.record_action('exits', count=1)

                    except Exception as e:
                        summary.add_warning(f"Caution exit failed {ticker}: {e}")
                        continue

            # =================================================================
            # SKIP IF BLOCKED
            # =================================================================
            if not regime_result['allow_new_entries']:
                execution_tracker.complete('SUCCESS')
                summary.print_summary()
                if not Config.BACKTESTING:
                    account_email_notifications.send_daily_summary_email(self, current_date, execution_tracker)
                save_state_safe(self)
                return

            # =================================================================
            # ROTATION
            # =================================================================
            if should_rotate(self.stock_rotator, current_date, frequency='weekly'):
                self.stock_rotator.evaluate_stocks(self.tickers, current_date)

            # =================================================================
            # SCAN SIGNALS
            # =================================================================
            all_opportunities = []

            current_positions = self.get_positions()
            current_position_symbols = {p.symbol for p in current_positions}

            for ticker in all_tickers:
                try:
                    if ticker in current_position_symbols:
                        continue

                    if not self.stock_rotator.is_tradeable(ticker):
                        continue

                    if ticker not in all_stock_data:
                        continue

                    data = all_stock_data[ticker]['indicators']

                    vol_metrics = data.get('volatility_metrics', {})
                    if not vol_metrics.get('allow_trading', True):
                        continue

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
                            'rotation_mult': self.stock_rotator.get_multiplier(ticker),
                            'rotation_award': self.stock_rotator.get_award(ticker),
                            'source': 'scored'
                        })

                except Exception as e:
                    continue

            # =================================================================
            # POSITION SIZING
            # =================================================================
            if not all_opportunities:
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
                    execution_tracker.complete('SUCCESS')
                    summary.print_summary()
                    save_state_safe(self)
                    return

                if portfolio_context['available_slots'] <= 0:
                    summary.add_warning("No available slots")
                    execution_tracker.complete('SUCCESS')
                    summary.print_summary()
                    save_state_safe(self)
                    return

                sizing_opportunities = []
                for opp in all_opportunities:
                    if opp['score'] >= 60:
                        sizing_opportunities.append({
                            'ticker': opp['ticker'],
                            'data': opp['data'],
                            'score': opp['score'],
                            'signal_type': opp['signal_type'],
                            'vol_metrics': opp['vol_metrics'],
                            'rotation_mult': opp['rotation_mult'],

                        })

                regime_multiplier = regime_result['position_size_multiplier']

                allocations = stock_position_sizing.calculate_position_sizes(
                    sizing_opportunities,
                    portfolio_context,
                    regime_multiplier,
                    verbose=False  # Disable verbose output
                )

                if not allocations:
                    summary.add_warning("No positions met size requirements")
                    execution_tracker.complete('SUCCESS')
                    summary.print_summary()
                    save_state_safe(self)
                    return

            except Exception as e:
                summary.add_error(f"Position sizing failed: {e}")
                execution_tracker.complete('FAILED')
                summary.print_summary()
                return

            # =================================================================
            # EXECUTE BUYS
            # =================================================================
            for alloc in allocations:
                try:
                    ticker = alloc['ticker']
                    quantity = alloc['quantity']
                    cost = alloc['cost']
                    price = alloc['price']
                    signal_type = alloc['signal_type']
                    signal_score = alloc['signal_score']

                    summary.add_entry(ticker, quantity, price, cost, signal_type, signal_score)

                    self.position_monitor.track_position(
                        ticker, current_date, signal_type, entry_score=signal_score
                    )

                    order = self.create_order(ticker, quantity, 'buy')
                    self.submit_order(order)

                    if hasattr(self, 'order_logger'):
                        self.order_logger.log_order(
                            ticker=ticker, side='buy', quantity=quantity,
                            signal_type=signal_type, award='standard', quality_score=signal_score
                        )

                    execution_tracker.record_action('entries', count=1)

                except Exception as e:
                    summary.add_error(f"Buy {ticker} failed: {e}")
                    continue

            # =================================================================
            # COMPLETE
            # =================================================================
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
                account_email_notifications.send_daily_summary_email(self, self.get_datetime(), execution_tracker)
            raise

    def on_strategy_end(self):
        """Display final statistics"""
        self.profit_tracker.display_final_summary(
            stock_rotator=self.stock_rotator,
            regime_detector=self.regime_detector
        )
        return 0