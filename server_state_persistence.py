"""
State Persistence - Dual Mode (PostgreSQL for live, in-memory for backtesting)
"""

from datetime import datetime
from database import get_database
import json
from config import Config


class StatePersistence:
    """Dual-mode state persistence"""

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

            # Save bot state
            cursor.execute("""
                UPDATE bot_state SET
                    portfolio_peak = %s,
                    drawdown_protection_active = %s,
                    drawdown_protection_end_date = %s,
                    last_rotation_date = %s,
                    last_rotation_week = %s,
                    ticker_awards = %s,
                    updated_at = %s
                WHERE id = 1
            """, (
                strategy.drawdown_protection.portfolio_peak,
                strategy.drawdown_protection.protection_active,
                strategy.drawdown_protection.protection_end_date,
                strategy.stock_rotator.last_rotation_date,
                strategy.last_rotation_week,
                json.dumps(strategy.stock_rotator.ticker_awards),
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

            # Clear and save cooldowns
            cursor.execute("DELETE FROM cooldowns")
            for ticker, date in strategy.ticker_cooldown.last_buy_dates.items():
                cursor.execute("""
                    INSERT INTO cooldowns (ticker, last_buy_date)
                    VALUES (%s, %s)
                """, (ticker, date))

            # Clear and save blacklist
            cursor.execute("DELETE FROM blacklist")
            if strategy.stock_rotator.blacklist:
                # Permanent blacklist
                for ticker in strategy.stock_rotator.blacklist.permanent_blacklist:
                    cursor.execute("""
                        INSERT INTO blacklist (ticker, blacklist_type, reason)
                        VALUES (%s, %s, %s)
                    """, (ticker, 'permanent', 'Low performance'))

                # Temporary blacklist
                for ticker, expiry in strategy.stock_rotator.blacklist.temporary_blacklist.items():
                    cursor.execute("""
                        INSERT INTO blacklist (ticker, blacklist_type, expiry_date, reason)
                        VALUES (%s, %s, %s, %s)
                    """, (ticker, 'temporary', expiry, 'Recent losses'))

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

        # Save bot state
        self.db.update_bot_state(
            portfolio_peak=strategy.drawdown_protection.portfolio_peak,
            drawdown_protection_active=strategy.drawdown_protection.protection_active,
            drawdown_protection_end_date=strategy.drawdown_protection.protection_end_date,
            last_rotation_date=strategy.stock_rotator.last_rotation_date,
            last_rotation_week=strategy.last_rotation_week,
            ticker_awards=strategy.stock_rotator.ticker_awards.copy()
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

        # Save cooldowns
        self.db.clear_all_cooldowns()
        for ticker, date in strategy.ticker_cooldown.last_buy_dates.items():
            self.db.upsert_cooldown(ticker, date)

        # Save blacklist
        self.db.clear_all_blacklist()
        if strategy.stock_rotator.blacklist:
            for ticker in strategy.stock_rotator.blacklist.permanent_blacklist:
                self.db.upsert_blacklist(ticker, 'permanent', None, 'Low performance')

            for ticker, expiry in strategy.stock_rotator.blacklist.temporary_blacklist.items():
                self.db.upsert_blacklist(ticker, 'temporary', expiry, 'Recent losses')

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

                # Restore rotation state
                if state[4]:  # last_rotation_date
                    strategy.stock_rotator.last_rotation_date = state[4]
                    strategy.last_rotation_week = state[5]

                if state[6]:  # ticker_awards
                    strategy.stock_rotator.ticker_awards = json.loads(state[6])
                    print(f"✅ Stock Rotation: {len(strategy.stock_rotator.ticker_awards)} awards restored")

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

            # Load cooldowns
            cursor.execute("SELECT * FROM cooldowns")
            cooldowns = cursor.fetchall()
            for cooldown in cooldowns:
                strategy.ticker_cooldown.last_buy_dates[cooldown[0]] = cooldown[1]
            print(f"✅ Cooldowns: {len(cooldowns)} ticker(s)")

            # Load blacklist
            cursor.execute("SELECT * FROM blacklist")
            blacklist_entries = cursor.fetchall()
            if strategy.stock_rotator.blacklist:
                for entry in blacklist_entries:
                    ticker = entry[0]
                    blacklist_type = entry[1]

                    if blacklist_type == 'permanent':
                        strategy.stock_rotator.blacklist.permanent_blacklist.add(ticker)
                    elif blacklist_type == 'temporary':
                        strategy.stock_rotator.blacklist.temporary_blacklist[ticker] = entry[2]

                print(f"✅ Blacklist: {len(blacklist_entries)} entries restored")

            print(f"{'=' * 80}\n")

            # Validate with broker
            self._validate_with_broker(strategy)

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

        if state['last_rotation_date']:
            strategy.stock_rotator.last_rotation_date = state['last_rotation_date']
            strategy.last_rotation_week = state['last_rotation_week']

        if state['ticker_awards']:
            strategy.stock_rotator.ticker_awards = state['ticker_awards'].copy()
            print(f"✅ Stock Rotation: {len(strategy.stock_rotator.ticker_awards)} awards restored")

        # Load position metadata
        positions = self.db.get_all_position_metadata()
        strategy.position_monitor.positions_metadata = positions.copy()
        print(f"✅ Position Metadata: {len(positions)} position(s)")

        # Load cooldowns
        cooldowns = self.db.get_all_cooldowns()
        strategy.ticker_cooldown.last_buy_dates = cooldowns.copy()
        print(f"✅ Cooldowns: {len(cooldowns)} ticker(s)")

        # Load blacklist
        blacklist_entries = self.db.get_all_blacklist()
        if strategy.stock_rotator.blacklist:
            for ticker, entry in blacklist_entries.items():
                if entry['blacklist_type'] == 'permanent':
                    strategy.stock_rotator.blacklist.permanent_blacklist.add(ticker)
                elif entry['blacklist_type'] == 'temporary':
                    strategy.stock_rotator.blacklist.temporary_blacklist[ticker] = entry['expiry_date']

            print(f"✅ Blacklist: {len(blacklist_entries)} entries restored")

        print(f"{'=' * 80}\n")

        return True

    def _validate_with_broker(self, strategy):
        """Cross-check saved state with broker positions"""
        try:
            broker_positions = strategy.get_positions()
            broker_tickers = {p.symbol for p in broker_positions}
            state_tickers = set(strategy.position_monitor.positions_metadata.keys())

            missing_metadata = broker_tickers - state_tickers
            if missing_metadata:
                print(f"\n⚠️ [VALIDATION] Broker has positions without metadata: {missing_metadata}")
                for ticker in missing_metadata:
                    strategy.position_monitor.track_position(
                        ticker,
                        strategy.get_datetime(),
                        'recovered_unknown',
                        entry_score=0
                    )

            extra_metadata = state_tickers - broker_tickers
            if extra_metadata:
                print(f"\n⚠️ [VALIDATION] Cleaning metadata for closed positions: {extra_metadata}")
                for ticker in extra_metadata:
                    strategy.position_monitor.clean_position_metadata(ticker)

            if not missing_metadata and not extra_metadata:
                print(f"✅ [VALIDATION] State matches broker ({len(broker_tickers)} position(s))")

        except Exception as e:
            print(f"⚠️ [VALIDATION] Could not validate with broker: {e}")


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