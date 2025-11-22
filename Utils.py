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
        print(f"   Watch List: {len(config.get('watch_list', []))}")

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


def add_ticker_to_database(ticker, name, strategies):
    """
    Add ticker to database (live trading only)

    Args:
        ticker: Stock symbol (e.g., 'AAPL')
        name: Company name (e.g., 'Apple Inc.')
        strategies: List of strategies (e.g., ['core_stocks', 'swing_trade_stocks'])

    Returns:
        bool: True if successful, False otherwise
    """
    if Config.BACKTESTING:
        print("[WARN] Cannot add ticker to database in backtesting mode")
        return False

    db = get_database()
    conn = db.get_connection()

    try:
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO tickers (ticker, name, strategies, is_blacklisted)
            VALUES (%s, %s, %s, FALSE)
            ON CONFLICT (ticker) DO UPDATE
            SET name = EXCLUDED.name,
                strategies = EXCLUDED.strategies,
                updated_at = CURRENT_TIMESTAMP
        """, (ticker.upper(), name, strategies))

        conn.commit()
        print(f"✅ Added/Updated ticker: {ticker} → {strategies}")
        return True

    except Exception as e:
        conn.rollback()
        print(f"[ERROR] Failed to add ticker {ticker}: {e}")
        return False

    finally:
        cursor.close()
        db.return_connection(conn)


def update_ticker_blacklist_status(ticker, is_blacklisted):
    """
    Update ticker blacklist status (live trading only)

    Args:
        ticker: Stock symbol
        is_blacklisted: Boolean blacklist status

    Returns:
        bool: True if successful, False otherwise
    """
    if Config.BACKTESTING:
        print("[WARN] Cannot update blacklist in backtesting mode")
        return False

    db = get_database()
    conn = db.get_connection()

    try:
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE tickers
            SET is_blacklisted = %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE ticker = %s
        """, (is_blacklisted, ticker.upper()))

        conn.commit()

        status = "BLACKLISTED" if is_blacklisted else "UNBLACKLISTED"
        print(f"✅ {ticker} {status}")
        return True

    except Exception as e:
        conn.rollback()
        print(f"[ERROR] Failed to update blacklist status for {ticker}: {e}")
        return False

    finally:
        cursor.close()
        db.return_connection(conn)


def migrate_json_to_database(config_file='ticker_config.json'):
    """
    One-time migration: Load tickers from JSON and insert into database

    Args:
        config_file: Path to JSON config file

    Returns:
        bool: True if successful, False otherwise
    """
    if Config.BACKTESTING:
        print("[ERROR] Cannot migrate to database in backtesting mode")
        return False

    try:
        # Load from JSON
        with open(config_file, 'r') as f:
            config = json.load(f)

        db = get_database()
        conn = db.get_connection()
        cursor = conn.cursor()

        print(f"\n🔄 MIGRATING TICKERS FROM JSON TO DATABASE")
        print(f"{'=' * 70}")

        total_inserted = 0
        total_updated = 0

        # Process each strategy
        for strategy_name, tickers in config.items():
            if strategy_name == 'last_updated':
                continue

            if not isinstance(tickers, list):
                continue

            print(f"\nProcessing {strategy_name}: {len(tickers)} tickers")

            for ticker in tickers:
                try:
                    # Check if ticker exists
                    cursor.execute("SELECT strategies FROM tickers WHERE ticker = %s", (ticker,))
                    existing = cursor.fetchone()

                    if existing:
                        # Update: add strategy to existing strategies
                        existing_strategies = existing[0] or []
                        if strategy_name not in existing_strategies:
                            existing_strategies.append(strategy_name)

                        cursor.execute("""
                            UPDATE tickers
                            SET strategies = %s,
                                updated_at = CURRENT_TIMESTAMP
                            WHERE ticker = %s
                        """, (existing_strategies, ticker))

                        total_updated += 1
                        print(f"   ✓ Updated {ticker} → {existing_strategies}")
                    else:
                        # Insert new ticker
                        cursor.execute("""
                            INSERT INTO tickers (ticker, name, strategies, is_blacklisted)
                            VALUES (%s, %s, %s, FALSE)
                        """, (ticker, ticker, [strategy_name]))

                        total_inserted += 1
                        print(f"   ✓ Inserted {ticker} → [{strategy_name}]")

                except Exception as e:
                    print(f"   ✗ Error processing {ticker}: {e}")
                    continue

        conn.commit()

        print(f"\n{'=' * 70}")
        print(f"✅ MIGRATION COMPLETE")
        print(f"   Inserted: {total_inserted} tickers")
        print(f"   Updated: {total_updated} tickers")
        print(f"{'=' * 70}\n")

        cursor.close()
        db.return_connection(conn)

        return True

    except Exception as e:
        print(f"[ERROR] Migration failed: {e}")
        if 'conn' in locals():
            conn.rollback()
            cursor.close()
            db.return_connection(conn)
        return False