"""
Basic Lumibot Template - Inject Your Code Here
"""
import sys
import logging

import os
import json
import signal
from datetime import datetime
from lumibot.brokers import Alpaca
from lumibot.traders import Trader

from config import Config
import server_health_check

# from check_core_transaction import CoreHoldingsStrategy
from strategies import SwingTradeStrategy

import logging

import warnings
import pandas as pd

warnings.filterwarnings('ignore', category=pd.errors.SettingWithCopyWarning)

# Set the logging level for the root logger to WARNING or ERROR
# Alternatively, set the level for specific loggers if known (e.g., 'lumibot.brokers.alpaca')
# You might need to experiment with the exact logger name
logging.getLogger('lumibot.brokers.alpaca').setLevel(logging.INFO)
logging.getLogger().setLevel(logging.INFO)
# logging.getLogger('Alpaca').setLevel(logging.WARNING)


# ==================== Settings ====================== #
TESTING = os.getenv('BACKTESTING', 'False').lower() == 'true'
DATA_DIR = os.getenv('DATA_DIR', '/app/data')  # Railway volume mount point

core_tickers = []
swing_tickers = []
watch_list = []

try:
    with open('ticker_config.json', 'r') as f:
        config = json.load(f)
        core_tickers = config.get('core_stocks', [])
        swing_tickers = config.get('swing_trade_stocks', [])
        watch_list = config.get('watch_list', [])
except Exception as e:
    print(f"Could not load ticker list: {e}")
    exit()

ALPACA_CONFIG = Config.get_alpaca_config()


# ===================================================== #

def setup_data_directory():
    """Create data directory if it doesn't exist"""
    if not os.path.exists(DATA_DIR):
        try:
            os.makedirs(DATA_DIR, exist_ok=True)
            print(f"Created data directory: {DATA_DIR}")
        except Exception as data_dir:
            print(f"Warning: Could not create data directory: {data_dir}")


def signal_handler(_signum, _frame):
    """Handle shutdown signals gracefully"""
    print("\n" + "=" * 80)
    print("SHUTDOWN SIGNAL RECEIVED")
    print("=" * 80)
    print("Saving state and shutting down gracefully...")
    sys.exit(0)


def main():
    """Main entry point for Railway deployment"""
    print("\n" + "=" * 80)
    print("TRADING BOT STARTING ON RAILWAY")
    print(f"Time: {datetime.now()}")
    print(f"Testing Mode: {TESTING}")
    print(f"Data Directory: {DATA_DIR}")
    print("=" * 80 + "\n")

    # Setup
    setup_data_directory()
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    if not Config.BACKTESTING:
        server_health_check.start_healthcheck_server()

    if Config.BACKTESTING:
        # BACKTESTING
        from lumibot.backtesting import YahooDataBacktesting
        from lumibot.backtesting import AlpacaBacktesting

        start = datetime(2024, 1, 8)
        end = datetime(2025, 11, 6)

        '''
        core_results = CoreHoldingsStrategy.backtest(
            YahooDataBacktesting,
            start,
            end,
            parameters={"tickers": core_tickers},
            testing=testing
        )'''

        SwingTradeStrategy.backtest(
            datasource_class=AlpacaBacktesting,
            backtesting_start=start,
            backtesting_end=end,
            parameters={
                "tickers": swing_tickers,
                "send_emails": False
            },
            benchmark_asset='SPY',
            config=ALPACA_CONFIG
        )
    else:

        try:
            # LIVE
            broker = Alpaca(ALPACA_CONFIG)

            # core_strategy = CoreHoldingsStrategy(
            #     broker=broker,
            #     tickers=core_tickers,
            #     send_emails=True
            # )

            swing_strategy = SwingTradeStrategy(
                broker=broker,
                tickers=swing_tickers,
                parameters={
                    "send_emails": True
                },
            )

            # Initialize trader
            trader = Trader()

            # trader.add_strategy(core_strategy)
            trader.add_strategy(swing_strategy)

            print("\n" + "=" * 80)
            print("BOT READY - Starting trading loop...")
            print("=" * 80 + "\n")

            trader.run_all()

            print("Finished working today")

        except KeyboardInterrupt:
            print("\nShutdown requested by user")
        except Exception as fatal_error:
            print(f"\n[ERROR] Fatal error: {fatal_error}")
            import traceback
            traceback.print_exc()
            sys.exit(1)

        finally:
            print("\n" + "=" * 80)
            print("BOT SHUTDOWN COMPLETE")
            print("=" * 80 + "\n")


if __name__ == "__main__":
    main()
