from lumibot.strategies import Strategy

from config import Config

import stock_data
import signals
import position_sizing
import stops
import position_tracking

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

        self.position_tracking = position_tracking.ProfitTracker(self)

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

        all_stock_data = stock_data.process_data(self.tickers, current_date)

        # Help to customize strategies
        buy_signal_list = ['swing_trade_1', 'swing_trade_2']
        sell_signal_list = ['take_profit_method_1', 'bollinger_sell']

        orders = []
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
            buy_position = position_sizing.calculate_buy_size(self, ticker, data['close'])
            sell_position = position_sizing.calculate_sell_size_1(self, ticker)

            # Set stop losses
            # Stop Loss Options:
            # stop_loss_atr
            # stop_loss_hard
            stop_loss = stops.stop_loss_atr(data)

            # Take a sell signal over a buy signal
            if not sell_signal == None and sell_position['can_trade'] == True and has_position:
                exit_price = data['close']

                # Record and display realized P&L
                self.position_tracking.close_position(ticker, exit_price, current_date, sell_signal)

                order_sig = sell_signal
                order_sig['ticker'] = ticker
                order_sig['quantity'] = sell_position['quantity']
                orders.append(order_sig)
            elif not buy_signal == None and buy_position['can_trade'] == True:

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
                orders.append(order_sig)

        if len(orders) > 1:
            for order in orders:
                submit_order = self.create_order(order['ticker'], order['quantity'], order['side'])
                print(' * Submitting order: ' + str(submit_order) + ' | Signal: ' + str(order['signal_type']))
                print(10 * ' ' + '--> | Price: ' + str(order['limit_price']) + ' | ')
                # print('\n')
                self.submit_order(submit_order)

    def on_strategy_end(self):
        self.position_tracking.display_final_summary()

        return 0
