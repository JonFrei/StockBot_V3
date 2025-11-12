from lumibot.strategies import Strategy

from config import Config

import stock_data
import signals
import position_sizing
import profit_tracking
import position_monitoring
from ticker_cooldown import TickerCooldown

from lumibot.brokers import Alpaca

broker = Alpaca(Config.get_alpaca_config())


class SwingTradeStrategy(Strategy):
    def initialize(self, send_emails=True):
        """Initialize strategy with position tracking"""
        if Config.BACKTESTING:
            self.sleeptime = "1D"
        else:
            self.sleeptime = "10M"
        self.tickers = self.parameters.get("tickers", [])

        # SIMPLIFIED: Tracker just logs completed trades
        self.profit_tracker = profit_tracking.ProfitTracker(self)

        # Position monitoring (for exits + market condition caching)
        self.position_monitor = position_monitoring.PositionMonitor(self)

        # Ticker cooldown to prevent chasing
        self.ticker_cooldown = TickerCooldown(cooldown_days=3)

    def before_starting_trading(self):
        """
        Sync existing positions - SIMPLIFIED
        Just track metadata, broker has quantity/price
        """
        if Config.BACKTESTING:
            return

        try:
            broker_positions = self.get_positions()

            if len(broker_positions) > 0:
                for position in broker_positions:
                    ticker = position.symbol

                    if ticker in self.tickers:
                        # Just track metadata (no quantity/price needed)
                        self.position_monitor.track_position(
                            ticker,
                            self.get_datetime(),
                            'pre_existing'
                        )

                print(f"[SYNC] Loaded {len(self.position_monitor.positions_metadata)} positions\n")

        except Exception as e:
            print(f"[ERROR] Failed to sync positions: {e}")

    def on_trading_iteration(self):
        if not broker.is_market_open() and Config.BACKTESTING == 'False':
            return

        current_date = self.get_datetime()
        current_date_str = current_date.strftime('%Y-%m-%d')

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

        all_tickers = list(set(self.tickers + [p.symbol for p in self.get_positions()]))
        all_stock_data = stock_data.process_data(self.tickers, current_date)

        # =====================================================================
        # STEP 1: CHECK ALL EXISTING POSITIONS FOR EXITS (HIGHEST PRIORITY)
        # =====================================================================

        # Check positions and get exit orders (uses adaptive parameters)
        exit_orders = position_monitoring.check_positions_for_exits(
            strategy=self,
            current_date=current_date,
            all_stock_data=all_stock_data,
            position_monitor=self.position_monitor
        )

        # Execute all exit orders
        position_monitoring.execute_exit_orders(
            strategy=self,
            exit_orders=exit_orders,
            current_date=current_date,
            position_monitor=self.position_monitor,
            profit_tracker=self.profit_tracker,
            ticker_cooldown=self.ticker_cooldown

        )

        # =====================================================================
        # STEP 2: LOOK FOR NEW BUY SIGNALS (only if we have cash)
        # =====================================================================

        # Help to customize strategies
        buy_signal_list = [
            'momentum_breakout',
            'consolidation_breakout',
            'swing_trade_1',
            'gap_up_continuation',
            'swing_trade_2',
            'bollinger_buy',
            'golden_cross'
        ]
        sell_signal_list = ['take_profit_method_1', 'bollinger_sell']

        buy_orders = []
        signal_sell_orders = []

        # Track cash commitments to prevent over-purchasing
        pending_cash_commitment = 0

        # Check Ticker Cooldowns
        active_cooldowns = self.ticker_cooldown.get_all_cooldowns(current_date)
        if active_cooldowns:
            print(f"\n⏰ Active Cooldowns:")
            for ticker, days_left in active_cooldowns:
                print(f"   {ticker}: {days_left} day(s) remaining")

        # Start checking each indicator
        for ticker in self.tickers:

            if ticker not in all_stock_data:
                self.log_message(f"No data for {ticker}, skipping")
                continue

            # Check Cooldown Period
            if not self.ticker_cooldown.can_buy(ticker, current_date):
                days_left = self.ticker_cooldown.days_until_can_buy(ticker, current_date)
                print(f" * SKIP: {ticker} - Cooldown ({days_left} days remaining)")
                continue

            # UPDATED: Get full data structure (has both 'indicators' and 'raw')
            data_full = all_stock_data[ticker]
            data = data_full['indicators']

            # === GET ADAPTIVE PARAMETERS (Cached Daily) ===
            adaptive_params = self.position_monitor.get_cached_market_conditions(
                ticker, current_date_str, data
            )

            # UPDATED: Pass full data structure to signals
            buy_signal = signals.buy_signals(data_full, buy_signal_list)
            sell_signal = signals.sell_signals(data_full, sell_signal_list)

            has_position = ticker in self.positions

            # Size position to buy - PASS ADAPTIVE PARAMETERS
            buy_position = position_sizing.calculate_buy_size(
                self,
                ticker,
                data['close'],
                pending_commitments=pending_cash_commitment,
                adaptive_params=adaptive_params  # Pass adaptive params
            )

            # For signal-based sells, sell 100% of position
            # sell_position = position_sizing.calculate_sell_size(self, ticker, sell_percentage=100.0)

            # === SELL SIGNAL LOGIC (overrides buy) ===
            if sell_signal is not None and has_position:

                # Get broker data (source of truth)
                position = self.get_position(ticker)
                broker_quantity = int(position.quantity)
                broker_entry_price = float(position.avg_fill_price)
                exit_price = data['close']

                # Get entry signal from metadata
                metadata = self.position_monitor.get_position_metadata(ticker)
                entry_signal = metadata.get('entry_signal', 'pre_existing') if metadata else 'pre_existing'

                # Record the trade
                self.profit_tracker.record_trade(
                    ticker=ticker,
                    quantity_sold=broker_quantity,
                    entry_price=broker_entry_price,
                    exit_price=exit_price,
                    exit_date=current_date,
                    entry_signal=entry_signal,
                    exit_signal=sell_signal
                )

                # Clean monitoring metadata
                self.position_monitor.clean_position_metadata(ticker)

                # Clear cooldown on signal-based full exit
                self.ticker_cooldown.clear(ticker)

                order_sig = sell_signal
                order_sig['ticker'] = ticker
                order_sig['quantity'] = broker_quantity
                signal_sell_orders.append(order_sig)

            # === BUY SIGNAL LOGIC ===
            elif buy_signal is not None and buy_signal.get('side') == 'buy' and buy_position['can_trade'] is True:

                # SIMPLIFIED: Just track that we have a position with entry signal
                # Broker will track quantity and entry price
                self.position_monitor.track_position(
                    ticker,
                    current_date,
                    buy_signal.get('signal_type', 'unknown')
                )

                order_sig = buy_signal
                order_sig['ticker'] = ticker
                order_sig['stop_loss'] = 0.90 * data['close']
                order_sig['quantity'] = buy_position['quantity']
                order_sig['position_value'] = buy_position['position_value']
                order_sig['condition'] = adaptive_params['condition_label']  # Add condition
                buy_orders.append(order_sig)

                # ADD COMMITMENT to prevent over-purchasing
                pending_cash_commitment += buy_position['position_value']
                print(
                    f" * PENDING BUY: {ticker} x{buy_position['quantity']} {adaptive_params['condition_label']} = ${buy_position['position_value']:,.2f}")

        # Submit sell orders first
        if len(signal_sell_orders) > 0:
            for order in signal_sell_orders:
                if order['side'] == 'sell':
                    submit_order = self.create_order(order['ticker'], order['quantity'], order['side'])
                    print(' * SIGNAL SELL: ' + str(submit_order) + ' | Signal: ' + str(order['signal_type']))
                    print(10 * ' ' + '--> | Price: ' + str(order['limit_price']))
                    self.submit_order(submit_order)

        # Then submit buy orders
        if len(buy_orders) > 0:
            print(f"\n{'=' * 70}")
            print(f"📊 BUY ORDERS SUMMARY - {len(buy_orders)} order(s)")
            print(f"{'=' * 70}")
            print(f"Total Cash Commitment: ${pending_cash_commitment:,.2f}")
            print(f"Cash After Orders: ${self.get_cash() - pending_cash_commitment:,.2f}")
            print(f"{'=' * 70}\n")

            for order in buy_orders:
                if order['side'] == 'buy':
                    submit_order = self.create_order(order['ticker'], order['quantity'], order['side'])
                    print(
                        f" * BUY: {order['ticker']} x{order['quantity']} {order['condition']} | {order['signal_type']}")
                    print(10 * ' ' + f"--> Price: ${order['limit_price']:.2f} | Value: ${order['position_value']:,.2f}")
                    self.submit_order(submit_order)

                    # Record buy in cooldown tracker
                    self.ticker_cooldown.record_buy(order['ticker'], current_date)

    def on_strategy_end(self):
        self.profit_tracker.display_final_summary()

        # Display cooldown statistics
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

        return 0