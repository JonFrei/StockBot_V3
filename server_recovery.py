"""
State Persistence - Dual Mode with Resilient Fallback

Features:
- PostgreSQL for live, in-memory for backtesting
- Retry logic on database operations
- In-memory fallback window (30 min) before halt
- Alert email on persistent database failure
- Integrated rotation state persistence
- Regime detector state persistence (drawdown, crisis lockouts)

Note: Position reconciliation has been moved to account_strategies.py
      and runs at the start of each trading iteration.
"""

from datetime import datetime, timedelta
from database import get_database
from config import Config
import time
import json

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

            <p><em>Bot is running with in-memory state.
            Positions are safe but state won't persist if bot restarts.</em></p>
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
    """Dual-mode state persistence"""

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
        """Save to PostgreSQL using database class methods"""

        # Save position metadata using class methods
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

        # Save bot state (regime detector state, rotation metadata)
        self._save_bot_state(strategy)

        print(f"[DATABASE] State saved at {datetime.now().strftime('%H:%M:%S')}")

    def _save_bot_state(self, strategy):
        """Save bot_state table with regime detector and rotation info"""

        # Gather regime detector state
        regime_state = {}
        if hasattr(strategy, 'regime_detector') and strategy.regime_detector:
            rd = strategy.regime_detector
            regime_state = {
                'portfolio_drawdown_active': rd.portfolio_drawdown_active,
                'portfolio_drawdown_trigger_date': rd.portfolio_drawdown_trigger_date.isoformat() if rd.portfolio_drawdown_trigger_date else None,
                'portfolio_drawdown_lockout_end': rd.portfolio_drawdown_lockout_end.isoformat() if rd.portfolio_drawdown_lockout_end else None,
                'crisis_active': rd.crisis_active,
                'crisis_trigger_date': rd.crisis_trigger_date.isoformat() if rd.crisis_trigger_date else None,
                'crisis_trigger_reason': rd.crisis_trigger_reason,
                'lockout_end_date': rd.lockout_end_date.isoformat() if rd.lockout_end_date else None,
                'portfolio_value_history': [
                    {'date': p['date'].isoformat(), 'value': p['value']}
                    for p in rd.portfolio_value_history[-35:]  # Keep last 35 days
                ] if rd.portfolio_value_history else []
            }

        # Gather rotation metadata
        rotation_metadata = {}
        if hasattr(strategy, 'stock_rotator') and strategy.stock_rotator:
            sr = strategy.stock_rotator
            rotation_metadata = {
                'last_rotation_date': sr.last_rotation_date.isoformat() if sr.last_rotation_date else None,
                'rotation_count': sr.rotation_count
            }

        # Calculate portfolio peak from regime detector history
        portfolio_peak = None
        if regime_state.get('portfolio_value_history'):
            values = [p['value'] for p in regime_state['portfolio_value_history']]
            portfolio_peak = max(values) if values else None

        # Get current week for rotation tracking
        current_date = strategy.get_datetime() if hasattr(strategy, 'get_datetime') else datetime.now()
        last_rotation_week = current_date.strftime('%Y-W%W') if current_date else None

        # Combine all state into ticker_awards JSON field (repurposed for extended state)
        extended_state = {
            'regime_detector': regime_state,
            'rotation_metadata': rotation_metadata
        }

        # Update bot_state table
        self.db.update_bot_state(
            portfolio_peak=portfolio_peak,
            drawdown_protection_active=regime_state.get('portfolio_drawdown_active', False),
            drawdown_protection_end_date=_parse_datetime(regime_state.get('portfolio_drawdown_lockout_end')),
            last_rotation_date=_parse_datetime(rotation_metadata.get('last_rotation_date')),
            last_rotation_week=last_rotation_week,
            rotation_count=rotation_metadata.get('rotation_count', 0),
            ticker_awards=extended_state  # Store extended state as JSON
        )

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
        """Load from PostgreSQL using database class methods"""

        print(f"\n{'=' * 80}")
        print(f"🔄 LOADING STATE FROM DATABASE")
        print(f"{'=' * 80}")

        # Load position metadata using class methods
        positions = self.db.get_all_position_metadata()
        strategy.position_monitor.positions_metadata = {}
        for ticker, meta in positions.items():
            strategy.position_monitor.positions_metadata[ticker] = {
                'entry_date': meta['entry_date'],
                'entry_signal': meta['entry_signal'],
                'entry_score': meta.get('entry_score', 0),
                'highest_price': meta.get('highest_price', 0),
                'local_max': meta.get('highest_price', 0),
                'profit_level': meta.get('profit_level', 0),
                'level_1_lock_price': meta.get('level_1_lock_price'),
                'tier1_lock_price': meta.get('level_1_lock_price'),
                'level_2_lock_price': meta.get('level_2_lock_price'),
                'entry_price': meta.get('entry_price'),
                'kill_switch_active': meta.get('kill_switch_active', False),
                'peak_price': meta.get('peak_price')
            }
        print(f"✅ Position Metadata: {len(positions)} position(s)")

        # Load rotation state
        if hasattr(strategy, 'stock_rotator') and strategy.stock_rotator:
            rotation_states = self.db.load_rotation_state()
            if rotation_states:
                strategy.stock_rotator.load_state_from_persistence(rotation_states)
                print(f"✅ Rotation State: {len(rotation_states)} ticker(s)")

        # Load bot state (regime detector state, rotation metadata)
        self._load_bot_state(strategy)

        print(f"{'=' * 80}\n")
        return True

    def _load_bot_state(self, strategy):
        """Load bot_state table and restore regime detector state"""

        bot_state = self.db.get_bot_state()
        if not bot_state:
            print(f"⚠️ No bot_state found - starting fresh")
            return

        # Extract extended state from ticker_awards JSON
        extended_state = bot_state.get('ticker_awards', {})
        if isinstance(extended_state, str):
            try:
                extended_state = json.loads(extended_state)
            except:
                extended_state = {}

        regime_state = extended_state.get('regime_detector', {})
        rotation_metadata = extended_state.get('rotation_metadata', {})

        # Restore regime detector state
        if hasattr(strategy, 'regime_detector') and strategy.regime_detector and regime_state:
            rd = strategy.regime_detector

            # Restore portfolio drawdown state
            rd.portfolio_drawdown_active = regime_state.get('portfolio_drawdown_active', False)
            rd.portfolio_drawdown_trigger_date = _parse_datetime(regime_state.get('portfolio_drawdown_trigger_date'))
            rd.portfolio_drawdown_lockout_end = _parse_datetime(regime_state.get('portfolio_drawdown_lockout_end'))

            # Restore crisis state
            rd.crisis_active = regime_state.get('crisis_active', False)
            rd.crisis_trigger_date = _parse_datetime(regime_state.get('crisis_trigger_date'))
            rd.crisis_trigger_reason = regime_state.get('crisis_trigger_reason')
            rd.lockout_end_date = _parse_datetime(regime_state.get('lockout_end_date'))

            # Restore portfolio value history
            history = regime_state.get('portfolio_value_history', [])
            rd.portfolio_value_history = []
            for entry in history:
                try:
                    rd.portfolio_value_history.append({
                        'date': _parse_datetime(entry['date']),
                        'value': entry['value']
                    })
                except:
                    pass

            status_parts = []
            if rd.portfolio_drawdown_active:
                status_parts.append(f"Portfolio Drawdown Active (until {rd.portfolio_drawdown_lockout_end})")
            if rd.crisis_active:
                status_parts.append(f"Crisis Active: {rd.crisis_trigger_reason}")
            if rd.portfolio_value_history:
                status_parts.append(f"{len(rd.portfolio_value_history)} days history")

            status = ", ".join(status_parts) if status_parts else "Normal"
            print(f"✅ Regime Detector: {status}")

        # Restore rotation metadata
        if hasattr(strategy, 'stock_rotator') and strategy.stock_rotator and rotation_metadata:
            sr = strategy.stock_rotator
            sr.last_rotation_date = _parse_datetime(rotation_metadata.get('last_rotation_date'))
            sr.rotation_count = rotation_metadata.get('rotation_count', 0)
            print(f"✅ Rotation Metadata: {sr.rotation_count} rotations, last: {sr.last_rotation_date}")

    def _load_state_memory(self, strategy):
        """Load from in-memory database"""
        print(f"\n{'=' * 80}")
        print(f"🔄 LOADING STATE FROM MEMORY (Backtest)")
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


def _parse_datetime(value):
    """Parse datetime from string or return None"""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(value)
    except:
        return None


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