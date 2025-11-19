import json
import os

def load_tickers(config_file='ticker_config.json'):
    """
    Load ticker lists from JSON configuration file

    Args:
        config_file: Path to JSON config file

    Returns:
        List of all tickers (core_stocks + current_stocks combined)
    """
    with open(config_file, 'r') as f:
        config = json.load(f)

    # Combine both lists and remove duplicates
    all_tickers = list(set(config['core_stocks'] + config['swing_trade_stocks']))

    print(f"\n Loaded tickers:")
    print(f"   Core stocks: {len(config['core_stocks'])}")
    print(f"   Swing Trade Stocks: {len(config['swing_trade_stocks'])}")
    print(f"   Total unique: {len(all_tickers)}")

    return all_tickers

