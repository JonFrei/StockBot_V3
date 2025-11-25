"""
State Persistence - Dual Mode (PostgreSQL for live, in-memory for backtesting)
WITH INTEGRATED POSITION RECONCILIATION

SIMPLIFIED: Removed stock rotation system
"""

from datetime import datetime
from database import get_database
import json
from config import Config


class StatePersistence:
    """Dual-mode state persistence with broker reconciliation"""

    def __init__(self):
        self.db = get_database()
        self.is_memory_db = Config.BACKTESTING

    def save_state(self, strategy):
        """Save complete bot state (PostgreSQL or in-memory)"""

        if self.is_memory_db:
            self._save_state_memory(strategy)
        else:
            self._save_state_postgres(strategy)

    def _save_state_postgres(self, strategy):
        """Save to PostgreSQL"""
        conn = self.db.get_connection()
        try:
            cursor = conn.cursor()

            # Save bot state (simplified - no rotation)
            cursor.execute("""
                UPDATE bot_state SET
                    portfolio_peak = %s,
                    drawdown_protection_active = %s,
                    drawdown_protection_end_date = %s,
                    updated_at = %s
                WHERE id = 1
            """, (
                strategy.drawdown_protection.portfolio_peak,
                strategy.drawdown_protection.protection_active,
                strategy.drawdown_protection.protection_end_date,
                datetime.now()
            ))

            # Clear and save position metadata
            cursor.execute("DELETE FROM position_metadata")
            for ticker, meta in strategy.position_monitor.positions_metadata.items():
                cursor.execute("""
                    INSERT INTO position_metadata 
                    (ticker, entry_date, entry_signal, entry_score, highest_price, 
                     profit_level_1_locked, profit_level_2_locked, profit_level_3_locked)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    ticker,
                    meta['entry_date'],
                    meta['entry_signal'],
                    meta.get('entry_score', 0),
                    meta['highest_price'],
                    meta.get('profit_level_1_locked', False),
                    meta.get('profit_level_2_locked', False),
                    meta.get('profit_level_3_locked', False)
                ))

            conn.commit()
            print(f"[DATABASE] State saved to PostgreSQL at {datetime.now().strftime('%H:%M:%S')}")

        except Exception as e:
            conn.rollback()
            print(f"[DATABASE] Error saving state: {e}")
            raise
        finally:
            cursor.close()
            self.db.return_connection(conn)

    def _save_state_memory(self, strategy):
        """Save to in-memory database"""

        # Save bot state (simplified)
        self.db.update_bot_state(
            portfolio_peak=strategy.drawdown_protection.portfolio_peak,
            drawdown_protection_active=strategy.drawdown_protection.protection_active,
            drawdown_protection_end_date=strategy.drawdown_protection.protection_end_date,
            last_rotation_date=None,
            last_rotation_week=None,
            rotation_count=0,
            ticker_awards={}
        )

        # Save position metadata
        self.db.clear_all_position_metadata()
        for ticker, meta in strategy.position_monitor.positions_metadata.items():
            self.db.upsert_position_metadata(
                ticker=ticker,
                entry_date=meta['entry_date'],
                entry_signal=meta['entry_signal'],
                entry_score=meta.get('entry_score', 0),
                highest_price=meta['highest_price'],
                profit_level_1_locked=meta.get('profit_level_1_locked', False),
                profit_level_2_locked=meta.get('profit_level_2_locked', False),
                profit_level_3_locked=meta.get('profit_level_3_locked', False)
            )

    def load_state(self, strategy):
        """Load bot state (PostgreSQL or in-memory)"""

        if self.is_memory_db:
            return self._load_state_memory(strategy)
        else:
            return self._load_state_postgres(strategy)

    def _load_state_postgres(self, strategy):
        """Load from PostgreSQL"""
        conn = self.db.get_connection()
        try:
            cursor = conn.cursor()

            print(f"\n{'=' * 80}")
            print(f"🔄 RESTORING STATE FROM DATABASE")
            print(f"{'=' * 80}")

            # Load bot state
            cursor.execute("SELECT * FROM bot_state WHERE id = 1")
            state = cursor.fetchone()

            if state:
                # Restore drawdown protection
                if state[1]:  # portfolio_peak
                    strategy.drawdown_protection.portfolio_peak = float(state[1])
                    strategy.drawdown_protection.protection_active = state[2]
                    strategy.drawdown_protection.protection_end_date = state[3]
                    print(f"✅ Drawdown Protection: Peak ${state[1]:,.2f}")

            # Load position metadata
            cursor.execute("SELECT * FROM position_metadata")
            positions = cursor.fetchall()
            for pos in positions:
                strategy.position_monitor.positions_metadata[pos[0]] = {
                    'entry_date': pos[1],
                    'entry_signal': pos[2],
                    'entry_score': pos[3],
                    'highest_price': float(pos[4]),
                    'profit_level_1_locked': pos[5],
                    'profit_level_2_locked': pos[6],
                    'profit_level_3_locked': pos[7]
                }
            print(f"✅ Position Metadata: {len(positions)} position(s)")

            print(f"{'=' * 80}\n")

            # CRITICAL: Reconcile with broker after loading state
            self._reconcile_broker_positions(strategy)

            return True

        except Exception as e:
            print(f"\n⚠️ [DATABASE] Failed to load state: {e}")
            return False
        finally:
            cursor.close()
            self.db.return_connection(conn)

    def _load_state_memory(self, strategy):
        """Load from in-memory database"""

        print(f"\n{'=' * 80}")
        print(f"🔄 RESTORING STATE FROM MEMORY (Backtest)")
        print(f"{'=' * 80}")

        # Load bot state
        state = self.db.get_bot_state()

        if state['portfolio_peak']:
            strategy.drawdown_protection.portfolio_peak = state['portfolio_peak']
            strategy.drawdown_protection.protection_active = state['drawdown_protection_active']
            strategy.drawdown_protection.protection_end_date = state['drawdown_protection_end_date']
            print(f"✅ Drawdown Protection: Peak ${state['portfolio_peak']:,.2f}")

        # Load position metadata
        positions = self.db.get_all_position_metadata()
        strategy.position_monitor.positions_metadata = positions.copy()
        print(f"✅ Position Metadata: {len(positions)} position(s)")

        print(f"{'=' * 80}\n")

        return True

    def _reconcile_broker_positions(self, strategy):
        """
        INTEGRATED RECONCILIATION - Runs on every startup
        NOW USES CENTRALIZED BROKER UTILITIES from account_broker_data

        Syncs broker positions with database:
        - Adopts orphaned positions (in broker, not in database)
        - Cleans stale entries (in database, not in broker)
        - Uses broker's avg_entry_price for accuracy
        - Broker is source of truth for quantity/price
        """
        import account_broker_data

        print(f"\n{'=' * 80}")
        print(f"🔄 BROKER RECONCILIATION - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'=' * 80}")

        try:
            current_date = strategy.get_datetime()

            # Get positions from broker (SOURCE OF TRUTH)
            broker_positions = strategy.get_positions()
            broker_tickers = {p.symbol for p in broker_positions}

            # Get positions from database
            db_tickers = set(strategy.position_monitor.positions_metadata.keys())

            print(f"📊 Broker: {len(broker_tickers)} position(s)")
            print(f"📊 Database: {len(db_tickers)} position(s)")

            orphaned_count = 0
            cleaned_count = 0

            # CASE 1: ORPHANED POSITIONS (In broker, not in database)
            orphaned = broker_tickers - db_tickers

            if orphaned:
                print(f"\n⚠️  ORPHANED POSITIONS: {len(orphaned)}")
                print(f"{'─' * 80}")

                for ticker in orphaned:
                    position = next(p for p in broker_positions if p.symbol == ticker)
                    quantity = account_broker_data.get_position_quantity(position, ticker)

                    # USE CENTRALIZED UTILITY
                    entry_price = account_broker_data.get_broker_entry_price(position, strategy, ticker)

                    if not account_broker_data.validate_entry_price(entry_price, ticker):
                        print(f"   ❌ {ticker}: Invalid entry price - SKIPPING")
                        continue

                    # Get current price for highest_price
                    try:
                        current_price = strategy.get_last_price(ticker)
                        highest_price = max(entry_price, current_price)
                    except:
                        highest_price = entry_price

                    # Add to position tracking
                    strategy.position_monitor.positions_metadata[ticker] = {
                        'entry_date': current_date,
                        'entry_signal': 'recovered_orphan',
                        'entry_score': 0,
                        'highest_price': highest_price,
                        'profit_level_1_locked': False,
                        'profit_level_2_locked': False,
                        'profit_level_3_locked': False
                    }

                    # Save to database
                    self._save_position_metadata(ticker, current_date, entry_price, highest_price)

                    print(f"   ✅ {ticker}: ADOPTED - {quantity} shares @ ${entry_price:.2f}")

                    orphaned_count += 1

                print(f"{'─' * 80}")

            # CASE 2: MISSING FROM BROKER (In database, not in broker)
            missing = db_tickers - broker_tickers

            if missing:
                print(f"\n🧹 STALE ENTRIES: {len(missing)}")
                print(f"{'─' * 80}")

                for ticker in missing:
                    print(f"   🗑️  {ticker}: Position closed - cleaning metadata")

                    # Remove from tracking
                    del strategy.position_monitor.positions_metadata[ticker]

                    # Remove from database
                    self._delete_position_metadata(ticker)

                    cleaned_count += 1

                print(f"{'─' * 80}")

            # SUMMARY
            print(f"\n📋 RECONCILIATION SUMMARY:")
            print(f"   Orphaned Adopted: {orphaned_count}")
            print(f"   Stale Cleaned: {cleaned_count}")

            if orphaned_count == 0 and cleaned_count == 0:
                print(f"   ✅ All positions in sync!")

            print(f"{'=' * 80}\n")

            # Save state if anything changed
            if orphaned_count > 0 or cleaned_count > 0:
                save_state_safe(strategy)
                print(f"💾 State saved after reconciliation\n")

        except Exception as e:
            print(f"\n❌ RECONCILIATION ERROR: {e}")
            print(f"   Continuing with current state...\n")

            import traceback
            traceback.print_exc()

    def _save_position_metadata(self, ticker, entry_date, entry_price, highest_price):
        """Save position metadata to database"""

        try:
            conn = self.db.get_connection()

            try:
                cursor = conn.cursor()

                cursor.execute("""
                    INSERT INTO position_metadata 
                    (ticker, entry_date, entry_signal, entry_score, highest_price,
                     profit_level_1_locked, profit_level_2_locked, profit_level_3_locked)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (ticker) DO UPDATE SET
                        entry_date = EXCLUDED.entry_date,
                        entry_signal = EXCLUDED.entry_signal,
                        highest_price = EXCLUDED.highest_price,
                        updated_at = CURRENT_TIMESTAMP
                """, (
                    ticker,
                    entry_date,
                    'recovered_orphan',
                    0,
                    highest_price,
                    False,
                    False,
                    False
                ))

                conn.commit()

            finally:
                cursor.close()
                self.db.return_connection(conn)

        except Exception as e:
            print(f"      ⚠️  Save failed: {e}")

    def _delete_position_metadata(self, ticker):
        """Delete position metadata from database"""

        try:
            conn = self.db.get_connection()

            try:
                cursor = conn.cursor()

                cursor.execute("""
                    DELETE FROM position_metadata WHERE ticker = %s
                """, (ticker,))

                conn.commit()

            finally:
                cursor.close()
                self.db.return_connection(conn)

        except Exception as e:
            print(f"      ⚠️  Delete failed: {e}")


def save_state_safe(strategy):
    """Save state with error handling"""
    try:
        persistence = StatePersistence()
        persistence.save_state(strategy)
    except Exception as e:
        print(f"⚠️ Failed to save state: {e}")
        if not Config.BACKTESTING:
            raise  # Don't continue if DB save fails in live mode


def load_state_safe(strategy):
    """Load state with error handling"""
    try:
        persistence = StatePersistence()
        return persistence.load_state(strategy)
    except Exception as e:
        print(f"⚠️ Failed to load state: {e}")
        if not Config.BACKTESTING:
            raise  # Don't continue if DB load fails in live mode
        return False