"""
State Persistence - Dual Mode with Resilient Fallback

Features:
- PostgreSQL for live, in-memory for backtesting
- Retry logic on database operations
- In-memory fallback window (30 min) before halt
- Alert email on persistent database failure
- Integrated position reconciliation and rotation state
"""

from datetime import datetime, timedelta
from database import get_database
from config import Config
import time

# Fallback configuration
FALLBACK_WINDOW_MINUTES = 30
DB_RETRY_ATTEMPTS = 3
DB_RETRY_DELAY_SECONDS = 2


class FallbackState:
    """Tracks in-memory fallback state"""

    def __init__(self):
        self.active = False
        self.started_at = None
        self.last_db_error = None
        self.alert_sent = False

    def activate(self, error):
        """Activate fallback mode"""
        if not self.active:
            self.active = True
            self.started_at = datetime.now()
            self.last_db_error = str(error)
            print(f"\n⚠️ [FALLBACK] Database unavailable - running in-memory")
            print(f"   Window: {FALLBACK_WINDOW_MINUTES} minutes before halt")
            print(f"   Error: {error}\n")

    def deactivate(self):
        """Deactivate fallback mode"""
        if self.active:
            print(f"✅ [FALLBACK] Database recovered - resuming normal operation")
            self.active = False
            self.started_at = None
            self.last_db_error = None
            self.alert_sent = False

    def should_halt(self):
        """Check if fallback window exceeded"""
        if not self.active or not self.started_at:
            return False
        elapsed = datetime.now() - self.started_at
        return elapsed > timedelta(minutes=FALLBACK_WINDOW_MINUTES)

    def minutes_remaining(self):
        """Get minutes remaining in fallback window"""
        if not self.active or not self.started_at:
            return FALLBACK_WINDOW_MINUTES
        elapsed = datetime.now() - self.started_at
        remaining = timedelta(minutes=FALLBACK_WINDOW_MINUTES) - elapsed
        return max(0, remaining.total_seconds() / 60)


# Global fallback state
_fallback_state = FallbackState()


def _retry_db_operation(operation, fallback_state, *args, **kwargs):
    """
    Execute database operation with retries

    Returns:
        Tuple of (success: bool, result: any)
    """
    last_error = None

    for attempt in range(1, DB_RETRY_ATTEMPTS + 1):
        try:
            result = operation(*args, **kwargs)
            # Success - deactivate fallback if active
            if fallback_state.active:
                fallback_state.deactivate()
            return True, result
        except Exception as e:
            last_error = e
            if attempt < DB_RETRY_ATTEMPTS:
                print(f"[DATABASE] Attempt {attempt} failed: {e}")
                time.sleep(DB_RETRY_DELAY_SECONDS)
            else:
                print(f"[DATABASE] All {DB_RETRY_ATTEMPTS} attempts failed")
                fallback_state.activate(e)

    return False, last_error


def _send_database_failure_alert(error, fallback_state):
    """Send alert email for database failure"""
    if fallback_state.alert_sent:
        return

    try:
        import account_email_notifications

        html_body = f"""
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; }}
                .error-box {{ background-color: #fadbd8; padding: 15px; border-left: 5px solid #e74c3c; margin: 10px 0; }}
            </style>
        </head>
        <body>
            <h2>🚨 Database Connection Failure</h2>

            <div class="error-box">
                <p><strong>Status:</strong> Bot will HALT after fallback window expires</p>
                <p><strong>Fallback Started:</strong> {fallback_state.started_at.strftime('%Y-%m-%d %H:%M:%S') if fallback_state.started_at else 'Unknown'}</p>
                <p><strong>Window:</strong> {FALLBACK_WINDOW_MINUTES} minutes</p>
                <p><strong>Minutes Remaining:</strong> {fallback_state.minutes_remaining():.0f}</p>
                <p><strong>Error:</strong> {error}</p>
            </div>

            <h3>Action Required:</h3>
            <ul>
                <li>Check Railway PostgreSQL status</li>
                <li>Verify DATABASE_URL environment variable</li>
                <li>Check Railway logs for connection errors</li>
            </ul>

            <p><em>Bot is running with in-memory state. Positions are safe but state won't persist if bot restarts.</em></p>
        </body>
        </html>
        """

        account_email_notifications.send_email(
            "🚨 DATABASE FAILURE - Trading Bot Alert",
            html_body
        )
        fallback_state.alert_sent = True
        print("[ALERT] Database failure email sent")

    except Exception as e:
        print(f"[ALERT] Failed to send database failure email: {e}")


class StatePersistence:
    """Dual-mode state persistence with broker reconciliation"""

    def __init__(self):
        self.db = get_database()
        self.is_memory_db = Config.BACKTESTING
        self.fallback_state = _fallback_state

    def save_state(self, strategy):
        """Save complete bot state with fallback handling"""

        if self.is_memory_db:
            self._save_state_memory(strategy)
            return

        # Check if we should halt
        if self.fallback_state.should_halt():
            _send_database_failure_alert(self.fallback_state.last_db_error, self.fallback_state)
            raise Exception(f"Database unavailable for {FALLBACK_WINDOW_MINUTES}+ minutes - halting")

        # Try PostgreSQL with retries
        success, result = _retry_db_operation(
            self._save_state_postgres,
            self.fallback_state,
            strategy
        )

        if not success:
            # Fallback to memory save
            print(f"[FALLBACK] Saving to memory ({self.fallback_state.minutes_remaining():.0f} min remaining)")
            self._save_state_memory(strategy)

            # Send alert if not already sent
            if not self.fallback_state.alert_sent:
                _send_database_failure_alert(result, self.fallback_state)

    def _save_state_postgres(self, strategy):
        """Save to PostgreSQL"""
        conn = self.db.get_connection()
        try:
            cursor = conn.cursor()

            # Clear and save position metadata
            cursor.execute("DELETE FROM position_metadata")
            for ticker, meta in strategy.position_monitor.positions_metadata.items():
                cursor.execute("""
                    INSERT INTO position_metadata 
                    (ticker, entry_date, entry_signal, entry_score, highest_price, 
                     profit_level, level_1_lock_price, level_2_lock_price,
                     entry_price, kill_switch_active, peak_price)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    ticker,
                    meta['entry_date'],
                    meta['entry_signal'],
                    meta.get('entry_score', 0),
                    meta.get('highest_price', meta.get('local_max', 0)),
                    meta.get('profit_level', 0),
                    meta.get('level_1_lock_price') or meta.get('tier1_lock_price'),
                    meta.get('level_2_lock_price'),
                    meta.get('entry_price'),
                    meta.get('kill_switch_active', False),
                    meta.get('peak_price')
                ))

            conn.commit()

            # Save rotation state
            if hasattr(strategy, 'stock_rotator') and strategy.stock_rotator:
                rotation_states = strategy.stock_rotator.get_state_for_persistence()
                self.db.save_rotation_state(rotation_states)

            print(f"[DATABASE] State saved at {datetime.now().strftime('%H:%M:%S')}")

        except Exception as e:
            conn.rollback()
            raise
        finally:
            cursor.close()
            self.db.return_connection(conn)

    def _save_state_memory(self, strategy):
        """Save to in-memory database"""
        # Save position metadata
        self.db.clear_all_position_metadata()
        for ticker, meta in strategy.position_monitor.positions_metadata.items():
            self.db.upsert_position_metadata(
                ticker=ticker,
                entry_date=meta['entry_date'],
                entry_signal=meta['entry_signal'],
                entry_score=meta.get('entry_score', 0),
                highest_price=meta.get('highest_price', meta.get('local_max', 0)),
                profit_level=meta.get('profit_level', 0),
                level_1_lock_price=meta.get('level_1_lock_price') or meta.get('tier1_lock_price'),
                level_2_lock_price=meta.get('level_2_lock_price'),
                entry_price=meta.get('entry_price'),
                kill_switch_active=meta.get('kill_switch_active', False),
                peak_price=meta.get('peak_price')
            )

        # Save rotation state
        if hasattr(strategy, 'stock_rotator') and strategy.stock_rotator:
            rotation_states = strategy.stock_rotator.get_state_for_persistence()
            self.db.save_rotation_state(rotation_states)

    def load_state(self, strategy):
        """Load bot state with fallback handling"""

        if self.is_memory_db:
            return self._load_state_memory(strategy)

        # Try PostgreSQL with retries
        success, result = _retry_db_operation(
            self._load_state_postgres,
            self.fallback_state,
            strategy
        )

        if success:
            return result
        else:
            print(f"[FALLBACK] Could not load from database - starting fresh")
            return False

    def _load_state_postgres(self, strategy):
        """Load from PostgreSQL"""
        conn = self.db.get_connection()
        try:
            cursor = conn.cursor()

            print(f"\n{'=' * 80}")
            print(f"🔄 RESTORING STATE FROM DATABASE")
            print(f"{'=' * 80}")

            # Load position metadata with new columns
            cursor.execute("""
                SELECT ticker, entry_date, entry_signal, entry_score, highest_price, 
                       profit_level, level_1_lock_price, level_2_lock_price,
                       entry_price, kill_switch_active, peak_price
                FROM position_metadata
            """)
            positions = cursor.fetchall()
            for pos in positions:
                strategy.position_monitor.positions_metadata[pos[0]] = {
                    'entry_date': pos[1],
                    'entry_signal': pos[2],
                    'entry_score': pos[3],
                    'highest_price': float(pos[4]) if pos[4] else 0,
                    'local_max': float(pos[4]) if pos[4] else 0,
                    'profit_level': pos[5] if pos[5] else 0,
                    'level_1_lock_price': float(pos[6]) if pos[6] else None,
                    'tier1_lock_price': float(pos[6]) if pos[6] else None,
                    'level_2_lock_price': float(pos[7]) if pos[7] else None,
                    'entry_price': float(pos[8]) if pos[8] else None,
                    'kill_switch_active': pos[9] if pos[9] is not None else False,
                    'peak_price': float(pos[10]) if pos[10] else None
                }
            print(f"✅ Position Metadata: {len(positions)} position(s)")

            # Load rotation state
            if hasattr(strategy, 'stock_rotator') and strategy.stock_rotator:
                rotation_states = self.db.load_rotation_state()
                if rotation_states:
                    strategy.stock_rotator.load_state_from_persistence(rotation_states)
                    print(f"✅ Rotation State: {len(rotation_states)} ticker(s)")

            print(f"{'=' * 80}\n")

            cursor.close()
            self.db.return_connection(conn)

            # Reconcile with broker
            self._reconcile_broker_positions(strategy)

            return True

        except Exception as e:
            cursor.close()
            self.db.return_connection(conn)
            raise

    def _load_state_memory(self, strategy):
        """Load from in-memory database"""
        print(f"\n{'=' * 80}")
        print(f"🔄 RESTORING STATE FROM MEMORY (Backtest)")
        print(f"{'=' * 80}")

        positions = self.db.get_all_position_metadata()
        strategy.position_monitor.positions_metadata = positions.copy()
        print(f"✅ Position Metadata: {len(positions)} position(s)")

        if hasattr(strategy, 'stock_rotator') and strategy.stock_rotator:
            rotation_states = self.db.load_rotation_state()
            if rotation_states:
                strategy.stock_rotator.load_state_from_persistence(rotation_states)
                print(f"✅ Rotation State: {len(rotation_states)} ticker(s)")

        print(f"{'=' * 80}\n")
        return True

    def _reconcile_broker_positions(self, strategy):
        """
        Reconcile broker positions with database state
        """
        import account_broker_data

        print(f"\n{'=' * 80}")
        print(f"🔄 BROKER RECONCILIATION - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'=' * 80}")

        try:
            current_date = strategy.get_datetime()

            broker_positions = strategy.get_positions()
            broker_tickers = {p.symbol for p in broker_positions}
            db_tickers = set(strategy.position_monitor.positions_metadata.keys())

            print(f"📊 Broker: {len(broker_tickers)} position(s)")
            print(f"📊 Database: {len(db_tickers)} position(s)")

            orphaned_count = 0
            cleaned_count = 0

            # Orphaned positions (in broker, not in database)
            orphaned = broker_tickers - db_tickers

            if orphaned:
                print(f"\n⚠️  ORPHANED POSITIONS: {len(orphaned)}")
                print(f"{'─' * 80}")

                for ticker in orphaned:
                    position = next(p for p in broker_positions if p.symbol == ticker)
                    quantity = account_broker_data.get_position_quantity(position, ticker)
                    entry_price = account_broker_data.get_broker_entry_price(position, strategy, ticker)

                    if not account_broker_data.validate_entry_price(entry_price, ticker):
                        print(f"   ❌ {ticker}: Invalid entry price - SKIPPING")
                        continue

                    try:
                        current_price = strategy.get_last_price(ticker)
                        highest_price = max(entry_price, current_price)
                    except:
                        highest_price = entry_price

                    strategy.position_monitor.positions_metadata[ticker] = {
                        'entry_date': current_date,
                        'entry_signal': 'recovered_orphan',
                        'entry_score': 0,
                        'entry_price': entry_price,
                        'highest_price': highest_price,
                        'local_max': highest_price,
                        'profit_level': 0,
                        'tier1_lock_price': None,
                        'level_1_lock_price': None,
                        'level_2_lock_price': None,
                        'kill_switch_active': False,
                        'peak_price': None
                    }

                    print(f"   ✅ {ticker}: ADOPTED - {quantity} shares @ ${entry_price:.2f}")
                    orphaned_count += 1

                print(f"{'─' * 80}")

            # Missing from broker (in database, not in broker)
            missing = db_tickers - broker_tickers

            if missing:
                print(f"\n🧹 STALE ENTRIES: {len(missing)}")
                print(f"{'─' * 80}")

                for ticker in missing:
                    print(f"   🗑️  {ticker}: Position closed - cleaning metadata")
                    del strategy.position_monitor.positions_metadata[ticker]
                    cleaned_count += 1

                print(f"{'─' * 80}")

            print(f"\n📋 RECONCILIATION SUMMARY:")
            print(f"   Orphaned Adopted: {orphaned_count}")
            print(f"   Stale Cleaned: {cleaned_count}")

            if orphaned_count == 0 and cleaned_count == 0:
                print(f"   ✅ All positions in sync!")

            print(f"{'=' * 80}\n")

            if orphaned_count > 0 or cleaned_count > 0:
                save_state_safe(strategy)
                print(f"💾 State saved after reconciliation\n")

        except Exception as e:
            print(f"\n❌ RECONCILIATION ERROR: {e}")
            print(f"   Continuing with current state...\n")
            import traceback
            traceback.print_exc()


def save_state_safe(strategy):
    """Save state with error handling"""
    try:
        persistence = StatePersistence()
        persistence.save_state(strategy)
    except Exception as e:
        print(f"⚠️ Failed to save state: {e}")
        if not Config.BACKTESTING:
            # Check if we should halt
            if _fallback_state.should_halt():
                raise


def load_state_safe(strategy):
    """Load state with error handling"""
    try:
        persistence = StatePersistence()
        return persistence.load_state(strategy)
    except Exception as e:
        print(f"⚠️ Failed to load state: {e}")
        return False


def get_fallback_state():
    """Get current fallback state for monitoring"""
    return _fallback_state