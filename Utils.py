"""
Ticker Management Utilities

DUAL MODE:
- Backtesting: Load from ticker_config.json
- Live Trading: Load from PostgreSQL database

Returns dict with strategy-organized ticker lists
"""

import json
from database import get_database
from config import Config


def load_tickers(config_file='ticker_config.json'):
    """
    Load ticker lists - DUAL MODE

    Backtesting: Read from JSON file
    Live Trading: Read from PostgreSQL database

    Args:
        config_file: Path to JSON config file (used for backtesting only)

    Returns:
        dict: {
            'core_stocks': [list of tickers],
            'swing_trade_stocks': [list of tickers],
            'watch_list': [list of tickers]
        }
    """
    if Config.BACKTESTING:
        return _load_tickers_from_json(config_file)
    else:
        return _load_tickers_from_database()


def _load_tickers_from_json(config_file='ticker_config.json'):
    """
    Load tickers from JSON file (backtesting mode)

    Args:
        config_file: Path to JSON config file

    Returns:
        dict: Strategy-organized ticker lists
    """
    try:
        with open(config_file, 'r') as f:
            config = json.load(f)

        print(f"\n📁 Loading tickers from JSON: {config_file}")
        print(f"   Core stocks: {len(config.get('core_stocks', []))}")
        print(f"   Swing Trade Stocks: {len(config.get('swing_trade_stocks', []))}")

        return {
            'core_stocks': config.get('core_stocks', []),
            'swing_trade_stocks': config.get('swing_trade_stocks', []),
            'watch_list': config.get('watch_list', [])
        }

    except FileNotFoundError:
        print(f"[ERROR] Ticker config file not found: {config_file}")
        return {'core_stocks': [], 'swing_trade_stocks': [], 'watch_list': []}
    except json.JSONDecodeError as e:
        print(f"[ERROR] Invalid JSON in {config_file}: {e}")
        return {'core_stocks': [], 'swing_trade_stocks': [], 'watch_list': []}
    except Exception as e:
        print(f"[ERROR] Failed to load tickers from JSON: {e}")
        return {'core_stocks': [], 'swing_trade_stocks': [], 'watch_list': []}


def _load_tickers_from_database():
    """
    Load tickers from PostgreSQL database (live trading mode)

    Queries tickers table and organizes by strategy array

    Returns:
        dict: Strategy-organized ticker lists
    """
    db = get_database()
    conn = db.get_connection()

    try:
        cursor = conn.cursor()

        # Query all active (non-blacklisted) tickers with their strategies
        cursor.execute("""
            SELECT ticker, strategies
            FROM tickers
            WHERE is_blacklisted = FALSE
            ORDER BY ticker
        """)

        rows = cursor.fetchall()

        # Organize tickers by strategy
        result = {
            'core_stocks': [],
            'swing_trade_stocks': [],
            'watch_list': []
        }

        for row in rows:
            ticker = row[0]
            strategies = row[1] or []  # Handle NULL

            # Add ticker to each strategy it belongs to
            for strategy in strategies:
                if strategy in result:
                    result[strategy].append(ticker)

        print(f"\n💾 Loading tickers from DATABASE:")
        print(f"   Core stocks: {len(result['core_stocks'])}")
        print(f"   Swing Trade Stocks: {len(result['swing_trade_stocks'])}")
        print(f"   Watch List: {len(result['watch_list'])}")

        return result

    except Exception as e:
        print(f"[ERROR] Failed to load tickers from database: {e}")
        print(f"[ERROR] Falling back to empty ticker lists")
        return {'core_stocks': [], 'swing_trade_stocks': [], 'watch_list': []}

    finally:
        cursor.close()
        db.return_connection(conn)


def get_all_unique_tickers():
    """
    Get all unique tickers across all strategies

    Returns:
        list: Deduplicated list of all tickers
    """
    ticker_config = load_tickers()

    all_tickers = set()
    all_tickers.update(ticker_config.get('core_stocks', []))
    all_tickers.update(ticker_config.get('swing_trade_stocks', []))
    all_tickers.update(ticker_config.get('watch_list', []))

    return sorted(list(all_tickers))

