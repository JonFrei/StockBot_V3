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


def manage_ticker_list():
    # Load config
    with open('ticker_config.json', 'r') as f:
        config = json.load(f)

    # Get swing trade stocks
    swing_stocks = set(config.get('swing_trade_stocks', []))

    # Remove swing stocks from watch_list if it exists
    if 'watch_list' in config:
        original_count = len(config['watch_list'])
        config['watch_list'] = [ticker for ticker in config['watch_list'] if ticker not in swing_stocks]
        removed_count = original_count - len(config['watch_list'])

        print(f"Removed {removed_count} tickers from watch_list")
        print(f"Watch list now has {len(config['watch_list'])} tickers")
    else:
        print("No 'watch_list' found in config")

    # Save back to file
    with open('ticker_config.json', 'w') as f:
        json.dump(config, f, indent=2)

    print("✓ Config updated")
