from lumibot.strategies import Strategy

from config import Config

import stock_data
import signals
import position_sizing
import stops


class SwingTradeStrategy(Strategy):
    def initialize(self, send_emails=True):
        """Initialize strategy with position tracking"""
        self.sleeptime = "1D"
        self.tickers = self.parameters.get("tickers", [])

    def before_starting_trading(self):
        """Runs once before trading starts - sync existing positions from Alpaca"""
        if Config.BACKTESTING:
            print("[BACKTEST MODE] Skipping position sync")
            return

    def on_trading_iteration(self):

        current_date = self.get_datetime()
        print('\n' + 30 * '=' + ' Date: ' + str(current_date) + ' ' + 30 * '=')

        all_stock_data = stock_data.process_data(self.tickers, current_date)

        # Help to customize strategies
        buy_signal_list = ['swing_trade_1', 'swing_trade_2']
        sell_signal_list = ['take_profit_method_1', 'bollinger_sell']

        orders = []
        for ticker in self.tickers:
            print('Ticker: ', ticker)

            # Get stocks and indicators
            data = all_stock_data[ticker]['indicators']
            print('Stock data: ', data)
            print('\n')

            # Get buy/sell signal
            buy_signal = signals.buy_signals(data, buy_signal_list)
            sell_signal = signals.sell_signals(data, sell_signal_list)

            # Size position to sell
            sizing = position_sizing.calculate_position_size(self.get_cash(), data['close'])

            # Set stop losses
            # Stop Loss Options:
            # stop_loss_atr
            # stop_loss_hard
            stop_loss = stops.stop_loss_atr(ticker)

            # Check if we are able to trade based on sizing and cash
            if not sizing.get('can_trade', False):
                print(f"[SKIP] {ticker}: {sizing.get('message', 'Cannot trade')}")
                continue  # Skip this ticker

            # Take a sell signal over a buy signal
            if sell_signal:
                # order_sig = self.process_sell(sell_signal)
                order_sig = sell_signal
                order_sig['ticker'] = ticker
                order_sig['quantity'] = 5
                orders.append(order_sig)
            elif buy_signal:
                # order_sig = self.process_buy(buy_signal)
                order_sig = buy_signal
                order_sig['ticker'] = ticker
                order_sig['stop_loss'] = stop_loss['stop_loss']
                order_sig['quantity'] = sizing['quantity']
                orders.append(order_sig)

        for order in orders:
            order = self.create_order(order['ticker'], order['quantity'], order['side'])
            print('Submitting order: ', order)
            self.submit_order(order)

        return 0

    def on_strategy_end(self):
        return 0

