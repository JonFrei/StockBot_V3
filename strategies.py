from lumibot.strategies import Strategy

from config import Config

import stock_data
import signals
import position_sizing
import stops

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

    def before_starting_trading(self):
        """Runs once before trading starts - sync existing positions from Alpaca"""
        if Config.BACKTESTING:
            print("[BACKTEST MODE] Skipping position sync")
            return

    def on_trading_iteration(self):

        if not broker.is_market_open() and Config.BACKTESTING == 'False':
            return

        current_date = self.get_datetime()
        # print('\n')
        print(30 * '=' + ' Date: ' + str(current_date) + ' ' + 30 * '=')

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

            # Size position to sell
            buy_position = position_sizing.calculate_buy_size(self, ticker, data['close'])
            sell_position = position_sizing.calculate_sell_size_1(self, ticker)

            # Set stop losses
            # Stop Loss Options:
            # stop_loss_atr
            # stop_loss_hard
            stop_loss = stops.stop_loss_atr(data)

            # Take a sell signal over a buy signal
            if sell_signal:
                # order_sig = self.process_sell(sell_signal)
                order_sig = sell_signal
                order_sig['ticker'] = ticker
                order_sig['quantity'] = sell_position['quantity']
                orders.append(order_sig)
            elif buy_signal and buy_position.get('can_trade', False):
                # order_sig = self.process_buy(buy_signal)
                order_sig = buy_signal
                order_sig['ticker'] = ticker
                order_sig['stop_loss'] = stop_loss['stop_loss']
                order_sig['quantity'] = buy_position['quantity']
                orders.append(order_sig)

        for order in orders:
            order = self.create_order(order['ticker'], order['quantity'], order['side'])
            print('Submitting order: ', order)
            self.submit_order(order)

        return 0

    def on_strategy_end(self):
        return 0
