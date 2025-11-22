"""
One-Time Migration Script: Populate Database from ticker_config.json

Run this script once to migrate your existing JSON ticker configuration
to the PostgreSQL database.

Usage:
    python migrate_tickers.py

Note: This is safe to run multiple times - it will only add/update tickers.
"""

from Utils import migrate_json_to_database
from config import Config


def main():
    """Run ticker migration"""
    print("\n" + "=" * 70)
    print("TICKER MIGRATION SCRIPT")
    print("=" * 70)

    if Config.BACKTESTING:
        print("\n❌ ERROR: Cannot run migration in backtesting mode")
        print("   Set BACKTESTING=False in environment variables")
        return 1

    print("\nThis will migrate tickers from ticker_config.json to database")
    print("Existing tickers will be updated (strategies will be merged)")
    print("\n" + "=" * 70)

    # Ask for confirmation
    response = input("\nProceed with migration? (yes/no): ").strip().lower()

    if response not in ['yes', 'y']:
        print("\n❌ Migration cancelled")
        return 0

    # Run migration
    success = migrate_json_to_database()

    if success:
        print("\n✅ Migration completed successfully!")
        print("\nNext steps:")
        print("1. Verify tickers in database:")
        print("   SELECT * FROM tickers ORDER BY ticker;")
        print("2. Test bot startup to confirm ticker loading works")
        return 0
    else:
        print("\n❌ Migration failed - check error messages above")
        return 1


if __name__ == "__main__":
    exit(main())