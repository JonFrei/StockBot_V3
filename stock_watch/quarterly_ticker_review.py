"""
Quarterly Ticker Review
Runs as a Railway cron job on the 1st of Jan, Apr, Jul, Oct at 8 AM EST

Usage:
    python stock_watch/quarterly_ticker_review.py
"""

import os
import sys
import psycopg2
from datetime import datetime
import pytz

EST = pytz.timezone('US/Eastern')


def get_db_connection():
    """Connect to PostgreSQL using DATABASE_URL"""
    database_url = os.getenv('postgresql://postgres:mlUjfZIPRFmFgOTONgIzUHbpfPnAqeXW@postgres.railway.internal:5432/railway')
    if not database_url:
        print("[ERROR] DATABASE_URL not set")
        sys.exit(1)
    return psycopg2.connect(database_url)


def fetch_all_tickers(conn):
    """Query all tickers from database"""
    cursor = conn.cursor()
    cursor.execute("""
        SELECT ticker, strategies, is_blacklisted
        FROM tickers
        ORDER BY ticker
    """)
    rows = cursor.fetchall()
    cursor.close()
    return rows


def main():
    now_est = datetime.now(EST)
    print("=" * 60)
    print("QUARTERLY TICKER REVIEW")
    print(f"Run time: {now_est.strftime('%Y-%m-%d %I:%M:%S %p %Z')}")
    print("=" * 60)

    conn = get_db_connection()

    try:
        tickers = fetch_all_tickers(conn)

        # Summary counts
        total = len(tickers)
        active = sum(1 for t in tickers if not t[2])
        blacklisted = sum(1 for t in tickers if t[2])

        print(f"\nTotal tickers: {total}")
        print(f"  Active: {active}")
        print(f"  Blacklisted: {blacklisted}")

        # Group by strategy
        strategy_counts = {}
        for ticker, strategies, is_blacklisted in tickers:
            if is_blacklisted:
                continue
            for strategy in (strategies or []):
                strategy_counts[strategy] = strategy_counts.get(strategy, 0) + 1

        print("\nBy strategy:")
        for strategy, count in sorted(strategy_counts.items()):
            print(f"  {strategy}: {count}")

        # List all active tickers
        print("\nActive tickers:")
        for ticker, strategies, is_blacklisted in tickers:
            if not is_blacklisted:
                print(f"  {ticker}: {strategies}")

        print("\n" + "=" * 60)
        print("QUARTERLY REVIEW COMPLETE")
        print("=" * 60)

    finally:
        conn.close()


if __name__ == "__main__":
    main()