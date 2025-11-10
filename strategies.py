from lumibot.strategies import Strategy

import signals
from config import Config
import stock_data


class SwingTradeStrategy(Strategy):
    def initialize(self, send_emails=True):
        """Initialize strategy with position tracking"""
        self.sleeptime = "10M"
        self.tickers = self.parameters.get("tickers", [])

    def before_starting_trading(self):
        """Runs once before trading starts - sync existing positions from Alpaca"""
        if Config.BACKTESTING:
            print("[BACKTEST MODE] Skipping position sync")
            return

    def on_trading_iteration(self):

        current_date = self.get_datetime().today()
        print('\n' + 30 * '=' + ' Date: ' + str(current_date) + ' ' + 30 * '=')

        all_stock_data = stock_data.process_data(self.tickers, current_date)

        # Help to customize strategies
        buy_signal_list = ['swing_trade_1', 'swing_trade_2']
        sell_signal_list = ['take_profit_method_1', 'bollinger_sell']

        orders = []
        for ticker in self.tickers:
            print('Ticker: ', ticker)
            data = all_stock_data[ticker]['indicators']
            print('\nStock data: ', data)
            sell_signal = signals.sell_signals(data, sell_signal_list)
            buy_signal = signals.buy_signals(data, buy_signal_list)

            #Make sure we don't buy and sell at the same time
            if sell_signal:
                orders.append(self.process_sell(sell_signal))
            elif buy_signal:
                orders.append(self.process_buy(buy_signal))

        for order in orders:
            order = self.create_order(order['symbol'], order['quantity'], order['side'])
            self.submit_order(order)

        return 0

    def on_strategy_end(self):
        return 0

    def process_buy(self, buy_list):
        for item in buy_list:
            ticker = item['ticker']
            qty = item['qty']
            return {'side': 'buy',
                    'ticker': ticker,
                    'qty': qty,
                    'limit_price': 100.0,
                    'stop_loss': 95.0}

    def process_sell(self, sell_list):
        for item in sell_list:
            ticker = item['ticker']
            qty = item['qty']
            return {'side': 'sell',
                    'ticker': ticker,
                    'qty': qty,
                    'limit_price': 100.0}
