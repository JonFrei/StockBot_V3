"""
Diagnostic script to inspect Alpaca positions and their attributes.
Run this to see exactly what positions are being returned and their entry price data.
"""

import os
from dotenv import load_dotenv

load_dotenv()

ALPACA_API_KEY = os.getenv('ALPACA_API_KEY')
ALPACA_API_SECRET = os.getenv('ALPACA_API_SECRET')
ALPACA_PAPER = os.getenv('ALPACA_PAPER', 'True').lower() == 'true'

print("=" * 80)
print("ALPACA POSITION DIAGNOSTIC")
print("=" * 80)
print(f"Paper Trading: {ALPACA_PAPER}")
print()

# Method 1: Using alpaca-py (TradingClient)
print("-" * 40)
print("METHOD 1: alpaca-py TradingClient")
print("-" * 40)

try:
    from alpaca.trading.client import TradingClient

    client = TradingClient(ALPACA_API_KEY, ALPACA_API_SECRET, paper=ALPACA_PAPER)
    positions = client.get_all_positions()

    print(f"Total positions returned: {len(positions)}")
    print()

    for pos in positions:
        print(f"Symbol: {pos.symbol}")
        print(f"  qty: {pos.qty}")
        print(f"  avg_entry_price: {getattr(pos, 'avg_entry_price', 'N/A')}")
        print(f"  cost_basis: {getattr(pos, 'cost_basis', 'N/A')}")
        print(f"  market_value: {getattr(pos, 'market_value', 'N/A')}")
        print(f"  current_price: {getattr(pos, 'current_price', 'N/A')}")
        print(f"  asset_class: {getattr(pos, 'asset_class', 'N/A')}")
        print(f"  exchange: {getattr(pos, 'exchange', 'N/A')}")
        print()

except Exception as e:
    print(f"Error with alpaca-py: {e}")
    import traceback

    traceback.print_exc()

print()

# Method 2: Using alpaca-trade-api (older library)
print("-" * 40)
print("METHOD 2: alpaca-trade-api")
print("-" * 40)

try:
    import alpaca_trade_api as tradeapi

    base_url = 'https://paper-api.alpaca.markets' if ALPACA_PAPER else 'https://api.alpaca.markets'
    api = tradeapi.REST(ALPACA_API_KEY, ALPACA_API_SECRET, base_url)

    positions = api.list_positions()

    print(f"Total positions returned: {len(positions)}")
    print()

    for pos in positions:
        print(f"Symbol: {pos.symbol}")
        print(f"  qty: {pos.qty}")
        print(f"  avg_entry_price: {getattr(pos, 'avg_entry_price', 'N/A')}")
        print(f"  cost_basis: {getattr(pos, 'cost_basis', 'N/A')}")
        print(f"  market_value: {getattr(pos, 'market_value', 'N/A')}")
        print(f"  current_price: {getattr(pos, 'current_price', 'N/A')}")
        print(f"  asset_class: {getattr(pos, 'asset_class', 'N/A')}")
        print(f"  exchange: {getattr(pos, 'exchange', 'N/A')}")
        print()

        # Show ALL attributes
        print(f"  All attributes: {[attr for attr in dir(pos) if not attr.startswith('_')]}")
        print()

except Exception as e:
    print(f"Error with alpaca-trade-api: {e}")
    import traceback

    traceback.print_exc()

print()

# Method 3: Using Lumibot
print("-" * 40)
print("METHOD 3: Lumibot Alpaca Broker")
print("-" * 40)

try:
    from lumibot.brokers import Alpaca

    ALPACA_CONFIG = {
        "API_KEY": ALPACA_API_KEY,
        "API_SECRET": ALPACA_API_SECRET,
        "PAPER": ALPACA_PAPER,
    }

    broker = Alpaca(ALPACA_CONFIG)

    # Get positions through broker
    positions = broker.get_tracked_positions()

    print(f"Total positions returned: {len(positions)}")
    print()

    for symbol, pos in positions.items():
        print(f"Symbol: {symbol}")
        print(f"  Type: {type(pos)}")
        print(f"  quantity: {getattr(pos, 'quantity', 'N/A')}")
        print(f"  avg_fill_price: {getattr(pos, 'avg_fill_price', 'N/A')}")

        # Check if it has an asset
        if hasattr(pos, 'asset'):
            print(f"  asset.symbol: {pos.asset.symbol if pos.asset else 'N/A'}")
            print(f"  asset.asset_type: {getattr(pos.asset, 'asset_type', 'N/A')}")

        # Show ALL attributes
        print(f"  All attributes: {[attr for attr in dir(pos) if not attr.startswith('_')]}")
        print()

except Exception as e:
    print(f"Error with Lumibot: {e}")
    import traceback

    traceback.print_exc()

print("=" * 80)
print("DIAGNOSTIC COMPLETE")
print("=" * 80)