from lumibot.strategies import Strategy

from config import Config

import stock_data
import signals
import position_sizing
import stops
import profit_tracking
import position_monitoring

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

        # Initialize position tracking (for P&L reporting)
        self.position_tracking = profit_tracking.ProfitTracker(self)

        # Initialize position monitoring (for exits)
        self.position_monitor = position_monitoring.PositionMonitor(self)

    def before_starting_trading(self):
        """Runs once before trading starts - sync existing positions from Alpaca"""
        # if Config.BACKTESTING:
        # print("\n[SYNC] Loading existing positions from broker...")
        try:
            broker_positions = self.get_positions()

            if len(broker_positions) > 1:
                for position in broker_positions:
                    ticker = position.symbol
                    quantity = int(position.quantity)
                    entry_price = float(position.avg_fill_price)

                    if ticker in self.tickers:
                        self.position_tracking.record_position(ticker, quantity, entry_price, 'pre_existing')
                        # print(f"  Synced {ticker}: {quantity} shares @ ${entry_price:.2f}")

                print(f"[SYNC] Loaded {len(self.position_tracking.positions)} positions")

        except Exception as e:
            print(f"[ERROR] Failed to sync positions: {e}")

    def on_trading_iteration(self):
        if not broker.is_market_open() and Config.BACKTESTING == 'False':
            return

        current_date = self.get_datetime()
        # print('\n')
        print(30 * '=' + ' Date: ' + str(current_date) + ' ' + 30 * '=')
        print('Portfolio Value:', self.portfolio_value)
        print('Cash Balance:', self.get_cash())
        # print('\n')

        all_tickers = list(set(self.tickers + [p.symbol for p in self.get_positions()]))
        all_stock_data = stock_data.process_data(self.tickers, current_date)

        # =====================================================================
        # STEP 1: CHECK ALL EXISTING POSITIONS FOR EXITS (HIGHEST PRIORITY)
        # =====================================================================

        # Check positions and get exit orders (pure calculation)
        exit_orders = position_monitoring.check_positions_for_exits(
            strategy=self,
            current_date=current_date,
            all_stock_data=all_stock_data,
            position_monitor=self.position_monitor
        )

        # Execute all exit orders (handles orders, tracking, cleanup)
        position_monitoring.execute_exit_orders(
            strategy=self,
            exit_orders=exit_orders,
            current_date=current_date,
            all_stock_data=all_stock_data,
            position_tracking=self.position_tracking,
            position_monitor=self.position_monitor
        )

        # =====================================================================
        # STEP 2: LOOK FOR NEW BUY SIGNALS (only if we have cash)
        # =====================================================================

        # Help to customize strategies
        buy_signal_list = ['swing_trade_1', 'swing_trade_2']
        sell_signal_list = ['take_profit_method_1', 'bollinger_sell']

        buy_orders = []
        signal_sell_orders = []

        # Track cash commitments to prevent over-purchasing
        pending_cash_commitment = 0

        for ticker in self.tickers:
            # print('Ticker: ', ticker)

            if ticker not in all_stock_data:
                self.log_message(f"No data for {ticker}, skipping")
                continue

            # Get stocks and indicators
            data = all_stock_data[ticker]['indicators']
            # print('Stock data: ', data)
            # print('\n')

            # Get buy/sell signal
            buy_signal = signals.buy_signals(data, buy_signal_list)
            sell_signal = signals.sell_signals(data, sell_signal_list)

            has_position = ticker in self.positions

            # Size position to sell
            # Size position to buy/sell - PASS PENDING COMMITMENTS
            buy_position = position_sizing.calculate_buy_size(
                self,
                ticker,
                data['close'],
                pending_commitments=pending_cash_commitment
            )

            # For signal-based sells, sell 100% of position
            sell_position = position_sizing.calculate_sell_size(self, ticker, sell_percentage=100.0)

            # Set stop losses
            # Stop Loss Options:
            # stop_loss_atr
            # stop_loss_hard
            stop_loss = stops.stop_loss_atr(data)

            # === SELL SIGNAL LOGIC (overrides buy) ===
            if not sell_signal == None and sell_position['can_trade'] == True and has_position:
                exit_price = data['close']

                # Record and display realized P&L
                self.position_tracking.close_position(
                    ticker=ticker,
                    exit_price=exit_price,
                    exit_date=current_date,
                    exit_signal=sell_signal,
                    quantity_sold=sell_position['quantity']  # Pass actual sold quantity
                )
                # Clean monitoring metadata
                self.position_monitor.clean_position_metadata(ticker)

                order_sig = sell_signal
                order_sig['ticker'] = ticker
                order_sig['quantity'] = sell_position['quantity']
                signal_sell_orders.append(order_sig)

            # === BUY SIGNAL LOGIC ===
            elif buy_signal is not None and buy_position['can_trade'] is True:

                # Record position
                self.position_tracking.record_position(
                    ticker,
                    buy_position['quantity'],
                    data['close'],
                    buy_signal.get('signal_type', 'unknown')
                )

                order_sig = buy_signal
                order_sig['ticker'] = ticker
                order_sig['stop_loss'] = stop_loss['stop_loss']
                order_sig['quantity'] = buy_position['quantity']
                order_sig['position_value'] = buy_position['position_value']  # Track value
                buy_orders.append(order_sig)

                # ADD COMMITMENT to prevent over-purchasing
                pending_cash_commitment += buy_position['position_value']
                print(f" * PENDING BUY: {ticker} x{buy_position['quantity']} = ${buy_position['position_value']:,.2f} | Total pending: ${pending_cash_commitment:,.2f}")

        # Summary of pending orders
        '''
        if len(buy_orders) > 0:
            print(f"\n{'='*60}")
            print(f"📊 ORDER SUMMARY - {len(buy_orders)} buy order(s)")
            print(f"{'='*60}")
            print(f"Total Cash Commitment: ${pending_cash_commitment:,.2f}")
            print(f"Cash Before Orders: ${self.get_cash():,.2f}")
            print(f"Cash After Orders: ${self.get_cash() - pending_cash_commitment:,.2f}")
            print(f"{'='*60}\n")
        '''

        # Submit sell orders first
        if len(signal_sell_orders) > 0:
            for order in signal_sell_orders:
                if order['side'] == 'sell':
                    submit_order = self.create_order(order['ticker'], order['quantity'], order['side'])
                    print(' * SIGNAL SELL: ' + str(submit_order) + ' | Signal: ' + str(order['signal_type']))
                    print(10 * ' ' + '--> | Price: ' + str(order['limit_price']) + ' | ')
                    self.submit_order(submit_order)

        # Then submit buy orders
        if len(buy_orders) > 0:
            for order in buy_orders:
                if order['side'] == 'buy':
                    submit_order = self.create_order(order['ticker'], order['quantity'], order['side'])
                    print(' * BUY ORDER: ' + str(submit_order) + ' | Signal: ' + str(order['signal_type']))
                    print(10 * ' ' + '--> | Price: ' + str(order['limit_price']) + ' | ')
                    self.submit_order(submit_order)

    def on_strategy_end(self):
        self.position_tracking.display_final_summary()

        return 0
