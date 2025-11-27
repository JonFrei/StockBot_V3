"""
SwingTradeStrategy - WITH SIMPLIFIED SAFEGUARD SYSTEM
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

broker = Alpaca(Config.get_alpaca_config())

CAUTION_MIN_PROFIT_PCT = 0.0


class SwingTradeStrategy(Strategy):

    def initialize(self, send_emails=True):
        if Config.BACKTESTING:
            self.sleeptime = "1D"
        else:
            self.sleeptime = "10M"

        self.tickers = self.parameters.get("tickers", [])
        self.last_trade_date = None

        self.profit_tracker = account_profit_tracking.ProfitTracker(self)
        self.order_logger = account_profit_tracking.OrderLogger(self)
        self.position_monitor = stock_position_monitoring.PositionMonitor(self)
        self.regime_detector = MarketRegimeDetector()
        self.recovery_manager = RecoveryModeManager()
        self.signal_processor = stock_signals.SignalProcessor()
        self.stock_rotator = StockRotator(profit_tracker=self.profit_tracker)

        print(f"\n{'=' * 60}")
        print(f"🤖 SwingTradeStrategy Initialized")
        print(f"   Tickers: {len(self.tickers)} | Mode: {'BACKTEST' if Config.BACKTESTING else 'LIVE'}")
        print(f"{'=' * 60}\n")

    def before_starting_trading(self):
        if Config.BACKTESTING:
            return
        load_state_safe(self)

    def on_trading_iteration(self):
        import account_email_notifications
        execution_tracker = account_email_notifications.ExecutionTracker()
        summary = reset_summary()

        try:
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

            # Fetch data
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
                        spy_avg_volume = spy_ind.get('avg_volume', spy_raw['volume'].iloc[-20:].mean() if len(spy_raw) >= 20 else None)
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
                execution_tracker.complete('FAILED')
                summary.print_summary()
                return

            # Regime detection with simplified system
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
                # HANDLE CRISIS EXIT - Exit ALL positions
                # =============================================================

                if regime_result.get('exit_all', False):
                    positions = self.get_positions()
                    exit_count = 0

                    for position in positions:
                        ticker = position.symbol
                        qty = int(position.quantity)
                        if qty > 0:
                            try:
                                entry_price = account_broker_data.get_broker_entry_price(position, self, ticker)
                                current_price = self.get_last_price(ticker)
                                pnl_dollars = (current_price - entry_price) * qty if entry_price > 0 else 0
                                pnl_pct = ((current_price - entry_price) / entry_price * 100) if entry_price > 0 else 0

                                summary.add_exit(ticker, qty, pnl_dollars, pnl_pct, 'crisis_exit')

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
                                    exit_signal={'reason': 'crisis_exit'},
                                    entry_score=entry_score
                                )

                                self.position_monitor.clean_position_metadata(ticker)
                                sell_order = self.create_order(ticker, qty, 'sell')
                                self.submit_order(sell_order)
                                exit_count += 1

                            except Exception as e:
                                summary.add_error(f"Crisis exit {ticker} failed: {e}")

                    execution_tracker.record_action('exits', count=exit_count)
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
                    execution_tracker.complete('SUCCESS')
                    summary.print_summary()

                    if not Config.BACKTESTING:
                        account_email_notifications.send_daily_summary_email(self, current_date, execution_tracker)

                    save_state_safe(self)
                    return

            except Exception as e:
                summary.add_error(f"Regime detection failed: {e}")
                regime_result = {
                    'action': 'error_fallback',
                    'position_size_multiplier': 0.5,
                    'allow_new_entries': True,
                    'exit_all': False,
                    'reason': f'Safeguard error: {e}'
                }

            # Check exits (normal position monitoring)
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

            # Recovery position limit check
            num_positions = len(self.get_positions())
            if regime_result['action'] == 'recovery_override':
                max_positions = regime_result.get('max_positions', 5)
                if num_positions >= max_positions:
                    summary.add_warning(f"Recovery mode: at max {max_positions} positions")
                    execution_tracker.complete('SUCCESS')
                    summary.print_summary()
                    if not Config.BACKTESTING:
                        account_email_notifications.send_daily_summary_email(self, current_date, execution_tracker)
                    save_state_safe(self)
                    return

            # Rotation
            if should_rotate(self.stock_rotator, current_date, frequency='weekly'):
                self.stock_rotator.evaluate_stocks(self.tickers, current_date)

            # Scan signals
            all_opportunities = []

            for ticker in all_tickers:
                try:
                    if ticker in self.positions:
                        continue
                    if not self.stock_rotator.is_tradeable(ticker):
                        continue
                    if ticker not in all_stock_data:
                        continue

                    data = all_stock_data[ticker]['indicators']
                    vol_metrics = data.get('volatility_metrics', {})
                    if not vol_metrics.get('allow_trading', True):
                        continue

                    # Relative strength filter
                    raw_df = data.get('raw')
                    if raw_df is not None and len(raw_df) >= 20:
                        try:
                            stock_current = data['close']
                            stock_past = float(raw_df['close'].iloc[-21]) if len(raw_df) >= 21 else float(raw_df['close'].iloc[0])
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
                            'rotation_mult': self.stock_rotator.get_multiplier(ticker),
                            'rotation_award': self.stock_rotator.get_award(ticker),
                            'source': 'scored'
                        })
                except:
                    continue

            # Position sizing
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
                    execution_tracker.complete('SUCCESS')
                    summary.print_summary()
                    save_state_safe(self)
                    return

            except Exception as e:
                summary.add_error(f"Position sizing failed: {e}")
                execution_tracker.complete('FAILED')
                summary.print_summary()
                return

            # Execute buys
            for alloc in allocations:
                try:
                    ticker = alloc['ticker']
                    quantity = alloc['quantity']
                    cost = alloc['cost']
                    price = alloc['price']
                    signal_type = alloc['signal_type']
                    signal_score = alloc['signal_score']

                    summary.add_entry(ticker, quantity, price, cost, signal_type, signal_score)
                    self.position_monitor.track_position(ticker, current_date, signal_type, entry_score=signal_score)

                    order = self.create_order(ticker, quantity, 'buy')
                    self.submit_order(order)

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
                    summary.add_error(f"Buy {ticker} failed: {e}")
                    continue

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
        self.profit_tracker.display_final_summary(
            stock_rotator=self.stock_rotator,
            regime_detector=self.regime_detector,
            recovery_manager=self.recovery_manager
        )
        return 0