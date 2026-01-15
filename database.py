"""
PostgreSQL Database Connection and Schema
Railway-optimized with connection pooling and retry logic

DUAL MODE: PostgreSQL for live, in-memory for backtesting

Features:
- Connection retry with exponential backoff
- Health check endpoint
- Rotation state persistence
- Dashboard settings (bot pause control)
- Position metadata persistence
- Bot state persistence (regime detector state)
- Daily metrics tracking
- Signal performance tracking
- Daily traded stocks tracking (prevents duplicate trades per day)
"""

import os
import time
import psycopg2
from psycopg2 import pool
from psycopg2.extras import RealDictCursor
from datetime import datetime
import json
from config import Config
import pandas as pd

# Retry configuration
DB_RETRY_ATTEMPTS = 3
DB_RETRY_DELAY_SECONDS = 2


class Database:
    """PostgreSQL connection manager with pooling and retry logic"""

    def __init__(self):
        self.connection_pool = None
        self._init_pool()
        self._create_tables()

    def _init_pool(self):
        """Initialize connection pool from DATABASE_URL"""
        database_url = os.getenv('DATABASE_URL')

        if not database_url:
            raise Exception("DATABASE_URL environment variable not set")

        self.connection_pool = psycopg2.pool.SimpleConnectionPool(
            minconn=1,
            maxconn=10,
            dsn=database_url
        )

        print("[DATABASE] Connection pool initialized")

    def _retry_operation(self, operation, *args, **kwargs):
        """
        Execute database operation with retry logic

        Args:
            operation: Callable to execute
            *args, **kwargs: Arguments to pass to operation

        Returns:
            Result of operation

        Raises:
            Exception after all retries exhausted
        """
        last_exception = None

        for attempt in range(1, DB_RETRY_ATTEMPTS + 1):
            try:
                return operation(*args, **kwargs)
            except (psycopg2.OperationalError, psycopg2.InterfaceError, pool.PoolError) as e:
                last_exception = e
                if attempt < DB_RETRY_ATTEMPTS:
                    print(f"[DATABASE] Connection attempt {attempt} failed: {e}")
                    print(f"[DATABASE] Retrying in {DB_RETRY_DELAY_SECONDS}s...")
                    time.sleep(DB_RETRY_DELAY_SECONDS)

                    # Try to reinitialize pool on connection errors
                    try:
                        if self.connection_pool:
                            self.connection_pool.closeall()
                        self._init_pool()
                    except:
                        pass
                else:
                    print(f"[DATABASE] All {DB_RETRY_ATTEMPTS} attempts failed")
                    raise last_exception
            except Exception as e:
                # Non-connection errors - don't retry
                raise e

        raise last_exception

    def health_check(self):
        """
        Check database connectivity

        Returns:
            bool: True if healthy, False otherwise
        """
        try:
            conn = self.get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("SELECT 1")
                cursor.fetchone()
                cursor.close()
                return True
            finally:
                self.return_connection(conn)
        except Exception as e:
            print(f"[DATABASE] Health check failed: {e}")
            return False

    def get_connection(self):
        """Get connection from pool"""
        return self.connection_pool.getconn()

    def get_connection_safe(self):
        """
        Get connection with retry logic

        Returns:
            Connection object

        Raises:
            Exception if all retries fail
        """
        return self._retry_operation(self.connection_pool.getconn)

    def return_connection(self, conn):
        """Return connection to pool"""
        self.connection_pool.putconn(conn)

    def _create_tables(self):
        """Create all required tables if they don't exist"""
        conn = self.get_connection()
        try:
            cursor = conn.cursor()

            # Tickers table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS tickers (
                    ticker VARCHAR(10) PRIMARY KEY,
                    name VARCHAR(100),
                    strategies TEXT[] DEFAULT '{}',
                    is_blacklisted BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_tickers_strategies ON tickers USING GIN(strategies);
                CREATE INDEX IF NOT EXISTS idx_tickers_blacklisted ON tickers(is_blacklisted);
            """)

            # Closed trades table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS closed_trades (
                    id SERIAL PRIMARY KEY,
                    ticker VARCHAR(10) NOT NULL,
                    quantity INTEGER NOT NULL,
                    entry_price DECIMAL(10, 2) NOT NULL,
                    exit_price DECIMAL(10, 2) NOT NULL,
                    pnl_dollars DECIMAL(12, 2) NOT NULL,
                    pnl_pct DECIMAL(8, 4) NOT NULL,
                    entry_signal VARCHAR(50),
                    entry_score INTEGER DEFAULT 0,
                    exit_signal VARCHAR(50),
                    exit_date TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_closed_trades_ticker ON closed_trades(ticker);
                CREATE INDEX IF NOT EXISTS idx_closed_trades_exit_date ON closed_trades(exit_date);
                CREATE INDEX IF NOT EXISTS idx_closed_trades_exit_signal ON closed_trades(exit_signal);
            """)

            # Position metadata table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS position_metadata (
                    ticker VARCHAR(10) PRIMARY KEY,
                    entry_date TIMESTAMP NOT NULL,
                    entry_signal VARCHAR(50) NOT NULL,
                    entry_score INTEGER DEFAULT 0,
                    entry_price DECIMAL(10, 2),
                    initial_stop DECIMAL(10, 2),
                    current_stop DECIMAL(10, 2),
                    R DECIMAL(10, 4),
                    entry_atr DECIMAL(10, 4),
                    highest_close DECIMAL(10, 2),
                    phase VARCHAR(20) DEFAULT 'entry',
                    bars_below_ema50 INTEGER DEFAULT 0,
                    partial_taken BOOLEAN DEFAULT FALSE,
                    add_count INTEGER DEFAULT 0,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_position_metadata_entry_date ON position_metadata(entry_date);
            """)

            # Bot state table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS bot_state (
                    id INTEGER PRIMARY KEY DEFAULT 1,
                    portfolio_peak DECIMAL(12, 2),
                    drawdown_protection_active BOOLEAN DEFAULT FALSE,
                    drawdown_protection_end_date TIMESTAMP,
                    last_rotation_date TIMESTAMP,
                    last_rotation_week VARCHAR(10),
                    rotation_count INTEGER DEFAULT 0,
                    runtime_state JSONB DEFAULT '{}',                    
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    CONSTRAINT single_row CHECK (id = 1)
                );
                INSERT INTO bot_state (id) VALUES (1) ON CONFLICT (id) DO NOTHING;
            """)

            # Rotation state table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS rotation_state (
                    ticker VARCHAR(10) PRIMARY KEY,
                    tier VARCHAR(20) NOT NULL DEFAULT 'active',
                    consecutive_wins INTEGER DEFAULT 0,
                    consecutive_losses INTEGER DEFAULT 0,
                    total_trades INTEGER DEFAULT 0,
                    total_wins INTEGER DEFAULT 0,
                    total_pnl DECIMAL(12, 2) DEFAULT 0,
                    total_win_pnl DECIMAL(12, 2) DEFAULT 0,
                    total_loss_pnl DECIMAL(12, 2) DEFAULT 0,
                    last_tier_change TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_rotation_tier ON rotation_state(tier);
                CREATE INDEX IF NOT EXISTS idx_rotation_state_updated ON rotation_state(updated_at);
            """)

            # Daily metrics table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS daily_metrics (
                    date DATE PRIMARY KEY,
                    portfolio_value DECIMAL(12, 2),
                    cash_balance DECIMAL(12, 2),
                    num_positions INTEGER DEFAULT 0,
                    num_trades INTEGER DEFAULT 0,
                    realized_pnl DECIMAL(12, 2) DEFAULT 0,
                    unrealized_pnl DECIMAL(12, 2) DEFAULT 0,
                    win_rate DECIMAL(5, 2) DEFAULT 0,
                    spy_close DECIMAL(10, 2),
                    market_regime VARCHAR(50),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_daily_metrics_date ON daily_metrics(date);
            """)

            # Dashboard settings table (for bot pause control)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS dashboard_settings (
                    key VARCHAR(50) PRIMARY KEY,
                    value VARCHAR(200),
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)

            # Daily traded stocks table (prevents same stock being traded twice in one day)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS daily_traded_stocks (
                    id SERIAL PRIMARY KEY,
                    ticker VARCHAR(10) NOT NULL,
                    trade_date DATE NOT NULL,
                    traded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(ticker, trade_date)
                );
                CREATE INDEX IF NOT EXISTS idx_daily_traded_date ON daily_traded_stocks(trade_date);
            """)

            conn.commit()
            print("[DATABASE] Tables created/verified successfully")

        except Exception as e:
            conn.rollback()
            raise Exception(f"Failed to create tables: {e}")
        finally:
            cursor.close()
            self.return_connection(conn)

    # =========================================================================
    # DASHBOARD SETTINGS METHODS
    # =========================================================================

    def get_bot_paused(self):
        """Check if bot is paused via dashboard"""

        def _get():
            conn = self.get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("SELECT value FROM dashboard_settings WHERE key = 'bot_paused'")
                row = cursor.fetchone()
                cursor.close()
                return row[0] == '1' if row else False
            finally:
                self.return_connection(conn)

        try:
            return self._retry_operation(_get)
        except Exception as e:
            print(f"[DATABASE] Error checking bot_paused: {e}")
            return False

    def set_bot_paused(self, paused):
        """Set bot paused state from dashboard"""

        def _set():
            conn = self.get_connection()
            try:
                cursor = conn.cursor()
                value = '1' if paused else '0'
                cursor.execute("""
                    INSERT INTO dashboard_settings (key, value, updated_at)
                    VALUES ('bot_paused', %s, CURRENT_TIMESTAMP)
                    ON CONFLICT (key) DO UPDATE SET value = %s, updated_at = CURRENT_TIMESTAMP
                """, (value, value))
                conn.commit()
                cursor.close()
                print(f"[DATABASE] Bot paused state set to: {paused}")
            finally:
                self.return_connection(conn)

        self._retry_operation(_set)

    # =========================================================================
    # DAILY TRADED STOCKS METHODS (Live Trading Only)
    # =========================================================================

    def add_daily_traded_stock(self, ticker, trade_date):
        """
        Record that a stock was traded today (prevents duplicate trades)

        Args:
            ticker: Stock symbol
            trade_date: Date of trade (date object)
        """

        def _add():
            conn = self.get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO daily_traded_stocks (ticker, trade_date)
                    VALUES (%s, %s)
                    ON CONFLICT (ticker, trade_date) DO NOTHING
                """, (ticker.upper(), trade_date))
                conn.commit()
                cursor.close()
            finally:
                self.return_connection(conn)

        try:
            self._retry_operation(_add)
        except Exception as e:
            print(f"[DATABASE] Error adding daily traded stock {ticker}: {e}")

    def get_daily_traded_stocks(self, trade_date):
        """
        Get set of tickers already traded today

        Args:
            trade_date: Date to check (date object)

        Returns:
            set: Set of ticker symbols traded on this date
        """

        def _get():
            conn = self.get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT ticker FROM daily_traded_stocks WHERE trade_date = %s",
                    (trade_date,)
                )
                result = {row[0] for row in cursor.fetchall()}
                cursor.close()
                return result
            finally:
                self.return_connection(conn)

        try:
            return self._retry_operation(_get)
        except Exception as e:
            print(f"[DATABASE] Error getting daily traded stocks: {e}")
            return set()

    def clear_old_daily_traded(self, current_date):
        """
        Clear traded stocks from previous days

        Args:
            current_date: Current date (date object) - entries before this are deleted
        """

        def _clear():
            conn = self.get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute(
                    "DELETE FROM daily_traded_stocks WHERE trade_date < %s",
                    (current_date,)
                )
                deleted = cursor.rowcount
                conn.commit()
                cursor.close()
                if deleted > 0:
                    print(f"[DATABASE] Cleared {deleted} old daily traded entries")
            finally:
                self.return_connection(conn)

        try:
            self._retry_operation(_clear)
        except Exception as e:
            print(f"[DATABASE] Error clearing old daily traded: {e}")

    # =========================================================================
    # POSITION METADATA METHODS
    # =========================================================================

    def upsert_position_metadata(self, ticker, entry_date, entry_signal, entry_score,
                                 entry_price=None, initial_stop=None, current_stop=None,
                                 R=None, entry_atr=None, highest_close=None,
                                 phase='entry', bars_below_ema50=0, partial_taken=False,
                                 add_count=0):
        """Insert or update position metadata"""

        def _upsert():
            conn = self.get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO position_metadata 
                    (ticker, entry_date, entry_signal, entry_score, entry_price,
                     initial_stop, current_stop, R, entry_atr, highest_close,
                     phase, bars_below_ema50, partial_taken, add_count, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                    ON CONFLICT (ticker) DO UPDATE SET
                        entry_date = EXCLUDED.entry_date,
                        entry_signal = EXCLUDED.entry_signal,
                        entry_score = EXCLUDED.entry_score,
                        entry_price = EXCLUDED.entry_price,
                        initial_stop = EXCLUDED.initial_stop,
                        current_stop = EXCLUDED.current_stop,
                        R = EXCLUDED.R,
                        entry_atr = EXCLUDED.entry_atr,
                        highest_close = EXCLUDED.highest_close,
                        phase = EXCLUDED.phase,
                        bars_below_ema50 = EXCLUDED.bars_below_ema50,
                        partial_taken = EXCLUDED.partial_taken,
                        add_count = EXCLUDED.add_count,
                        updated_at = CURRENT_TIMESTAMP
                """, (
                    ticker, entry_date, entry_signal, entry_score,
                    float(entry_price) if entry_price is not None else None,
                    float(initial_stop) if initial_stop is not None else None,
                    float(current_stop) if current_stop is not None else None,
                    float(R) if R is not None else None,
                    float(entry_atr) if entry_atr is not None else None,
                    float(highest_close) if highest_close is not None else None,
                    phase, bars_below_ema50, partial_taken, add_count
                ))
                conn.commit()
            finally:
                cursor.close()
                self.return_connection(conn)

        try:
            self._retry_operation(_upsert)
        except Exception as e:
            print(f"[DATABASE] Error upserting position metadata for {ticker}: {e}")

    def get_position_metadata(self, ticker):
        """Get position metadata for a ticker"""

        def _get():
            conn = self.get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT entry_date, entry_signal, entry_score, entry_price,
                           initial_stop, current_stop, R, entry_atr, highest_close,
                           phase, bars_below_ema50, partial_taken, add_count
                    FROM position_metadata WHERE ticker = %s
                """, (ticker,))
                row = cursor.fetchone()
                cursor.close()

                if row:
                    return {
                        'entry_date': row[0],
                        'entry_signal': row[1],
                        'entry_score': row[2],
                        'entry_price': float(row[3]) if row[3] else None,
                        'initial_stop': float(row[4]) if row[4] else None,
                        'current_stop': float(row[5]) if row[5] else None,
                        'R': float(row[6]) if row[6] else None,
                        'entry_atr': float(row[7]) if row[7] else None,
                        'highest_close': float(row[8]) if row[8] else None,
                        'phase': row[9] or 'entry',
                        'bars_below_ema50': row[10] or 0,
                        'partial_taken': row[11] or False,
                        'add_count': row[12] or 0
                    }
                return None
            finally:
                self.return_connection(conn)

        try:
            return self._retry_operation(_get)
        except Exception as e:
            print(f"[DATABASE] Error getting position metadata for {ticker}: {e}")
            return None

    def get_all_position_metadata(self):
        """Get all position metadata"""

        def _get_all():
            conn = self.get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT ticker, entry_date, entry_signal, entry_score, entry_price,
                           initial_stop, current_stop, R, entry_atr, highest_close,
                           phase, bars_below_ema50, partial_taken, add_count
                    FROM position_metadata
                """)

                positions = {}
                for row in cursor.fetchall():
                    positions[row[0]] = {
                        'entry_date': row[1],
                        'entry_signal': row[2],
                        'entry_score': row[3],
                        'entry_price': float(row[4]) if row[4] else None,
                        'initial_stop': float(row[5]) if row[5] else None,
                        'current_stop': float(row[6]) if row[6] else None,
                        'R': float(row[7]) if row[7] else None,
                        'entry_atr': float(row[8]) if row[8] else None,
                        'highest_close': float(row[9]) if row[9] else None,
                        'phase': row[10] or 'entry',
                        'bars_below_ema50': row[11] or 0,
                        'partial_taken': row[12] or False,
                        'add_count': row[13] or 0
                    }
                cursor.close()
                return positions
            finally:
                self.return_connection(conn)

        try:
            return self._retry_operation(_get_all)
        except Exception as e:
            print(f"[DATABASE] Error getting all position metadata: {e}")
            return {}

    def delete_position_metadata(self, ticker):
        """Delete position metadata for a ticker"""

        def _delete():
            conn = self.get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM position_metadata WHERE ticker = %s", (ticker,))
                conn.commit()
                cursor.close()
            finally:
                self.return_connection(conn)

        try:
            self._retry_operation(_delete)
        except Exception as e:
            print(f"[DATABASE] Error deleting position metadata for {ticker}: {e}")

    def clear_all_position_metadata(self):
        """Clear all position metadata"""

        def _clear():
            conn = self.get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM position_metadata")
                conn.commit()
                cursor.close()
            finally:
                self.return_connection(conn)

        try:
            self._retry_operation(_clear)
        except Exception as e:
            print(f"[DATABASE] Error clearing position metadata: {e}")

    # =========================================================================
    # ROTATION STATE METHODS
    # =========================================================================

    def save_rotation_state(self, ticker_states):
        """
        Save rotation states to database

        Args:
            ticker_states: Dict of {ticker: state_dict}
        """

        def _save():
            conn = self.get_connection()
            try:
                cursor = conn.cursor()

                for ticker, state in ticker_states.items():
                    cursor.execute("""
                        INSERT INTO rotation_state 
                        (ticker, tier, consecutive_wins, consecutive_losses, total_trades,
                         total_wins, total_pnl, total_win_pnl, total_loss_pnl, last_tier_change, updated_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                        ON CONFLICT (ticker) DO UPDATE SET
                            tier = EXCLUDED.tier,
                            consecutive_wins = EXCLUDED.consecutive_wins,
                            consecutive_losses = EXCLUDED.consecutive_losses,
                            total_trades = EXCLUDED.total_trades,
                            total_wins = EXCLUDED.total_wins,
                            total_pnl = EXCLUDED.total_pnl,
                            total_win_pnl = EXCLUDED.total_win_pnl,
                            total_loss_pnl = EXCLUDED.total_loss_pnl,
                            last_tier_change = EXCLUDED.last_tier_change,
                            updated_at = CURRENT_TIMESTAMP
                    """, (
                        ticker,
                        state.get('tier', 'active'),
                        state.get('consecutive_wins', 0),
                        state.get('consecutive_losses', 0),
                        state.get('total_trades', 0),
                        state.get('total_wins', 0),
                        state.get('total_pnl', 0),
                        state.get('total_win_pnl', 0),
                        state.get('total_loss_pnl', 0),
                        state.get('last_tier_change')
                    ))

                conn.commit()
                print(f"[DATABASE] Saved rotation state for {len(ticker_states)} tickers")

            finally:
                cursor.close()
                self.return_connection(conn)

        try:
            self._retry_operation(_save)
        except Exception as e:
            print(f"[DATABASE] Error saving rotation state after retries: {e}")
            raise

    def load_rotation_state(self):
        """
        Load all rotation states from database

        Returns:
            Dict of {ticker: state_dict}
        """

        def _load():
            conn = self.get_connection()
            try:
                cursor = conn.cursor()

                cursor.execute("""
                    SELECT ticker, tier, consecutive_wins, consecutive_losses, total_trades,
                           total_wins, total_pnl, total_win_pnl, total_loss_pnl, last_tier_change
                    FROM rotation_state
                """)

                states = {}
                for row in cursor.fetchall():
                    states[row[0]] = {
                        'ticker': row[0],
                        'tier': row[1],
                        'consecutive_wins': row[2],
                        'consecutive_losses': row[3],
                        'total_trades': row[4],
                        'total_wins': row[5],
                        'total_pnl': float(row[6]) if row[6] else 0,
                        'total_win_pnl': float(row[7]) if row[7] else 0,
                        'total_loss_pnl': float(row[8]) if row[8] else 0,
                        'last_tier_change': row[9].isoformat() if row[9] else None
                    }

                print(f"[DATABASE] Loaded rotation state for {len(states)} tickers")
                return states

            finally:
                cursor.close()
                self.return_connection(conn)

        try:
            return self._retry_operation(_load)
        except Exception as e:
            print(f"[DATABASE] Error loading rotation state: {e}")
            return {}

    # =========================================================================
    # TRADE OPERATIONS
    # =========================================================================

    def insert_trade(self, ticker, quantity, entry_price, exit_price, pnl_dollars, pnl_pct,
                     entry_signal, entry_score, exit_signal, exit_date,
                     confirmation_date=None, days_to_confirmation=0):
        """Insert a closed trade record"""

        def _insert():
            conn = self.get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO closed_trades 
                    (ticker, quantity, entry_price, exit_price, pnl_dollars, pnl_pct,
                     entry_signal, entry_score, exit_signal, exit_date,
                     confirmation_date, days_to_confirmation)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    ticker, quantity, entry_price, exit_price, pnl_dollars, pnl_pct,
                    entry_signal, entry_score, exit_signal, exit_date,
                    confirmation_date, days_to_confirmation
                ))
                conn.commit()
            finally:
                cursor.close()
                self.return_connection(conn)

        try:
            self._retry_operation(_insert)
        except Exception as e:
            print(f"[DATABASE] Error inserting trade: {e}")

    def get_closed_trades(self, limit=None):
        """Get closed trades"""

        def _get():
            conn = self.get_connection()
            try:
                cursor = conn.cursor()
                query = """
                    SELECT ticker, quantity, entry_price, exit_price, pnl_dollars, pnl_pct,
                           entry_signal, entry_score, exit_signal, exit_date
                    FROM closed_trades ORDER BY exit_date DESC
                """
                df = self.closed_trades_df.sort_values('exit_date', ascending=False)
                if limit:
                    df = df.head(limit)
                trades = []
                for _, row in df.iterrows():
                    trades.append({
                        'ticker': row['ticker'],
                        'quantity': row['quantity'],
                        'entry_price': float(row['entry_price']),
                        'exit_price': float(row['exit_price']),
                        'pnl_dollars': float(row['pnl_dollars']),
                        'pnl_pct': float(row['pnl_pct']),
                        'entry_signal': row['entry_signal'],
                        'entry_score': row['entry_score'],
                        'exit_signal': row['exit_signal'],
                        'exit_date': row['exit_date']
                    })
                return trades
            finally:
                self.return_connection(conn)

        try:
            return self._retry_operation(_get)
        except Exception as e:
            print(f"[DATABASE] Error getting closed trades: {e}")
            return []

    # =========================================================================
    # DAILY METRICS METHODS
    # =========================================================================

    def save_daily_metrics(self, date, portfolio_value, cash_balance, num_positions,
                           num_trades, realized_pnl, unrealized_pnl, win_rate,
                           spy_close, market_regime):
        """Save daily metrics"""

        def _save():
            conn = self.get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO daily_metrics 
                    (date, portfolio_value, cash_balance, num_positions, num_trades,
                     realized_pnl, unrealized_pnl, win_rate, spy_close, market_regime)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (date) DO UPDATE SET
                        portfolio_value = EXCLUDED.portfolio_value,
                        cash_balance = EXCLUDED.cash_balance,
                        num_positions = EXCLUDED.num_positions,
                        num_trades = EXCLUDED.num_trades,
                        realized_pnl = EXCLUDED.realized_pnl,
                        unrealized_pnl = EXCLUDED.unrealized_pnl,
                        win_rate = EXCLUDED.win_rate,
                        spy_close = EXCLUDED.spy_close,
                        market_regime = EXCLUDED.market_regime
                """, (
                    date, portfolio_value, cash_balance, num_positions, num_trades,
                    realized_pnl, unrealized_pnl, win_rate, spy_close, market_regime
                ))
                conn.commit()
            finally:
                cursor.close()
                self.return_connection(conn)

        try:
            self._retry_operation(_save)
        except Exception as e:
            print(f"[DATABASE] Error saving daily metrics: {e}")

    # =========================================================================
    # BOT STATE METHODS
    # =========================================================================

    def get_bot_state(self):
        """Get bot state from database"""

        def _get():
            conn = self.get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT portfolio_peak, drawdown_protection_active, drawdown_protection_end_date,
                           last_rotation_date, last_rotation_week, rotation_count, runtime_state
                    FROM bot_state WHERE id = 1
                """)
                row = cursor.fetchone()
                cursor.close()

                if row:
                    return {
                        'portfolio_peak': float(row[0]) if row[0] else None,
                        'drawdown_protection_active': row[1] or False,
                        'drawdown_protection_end_date': row[2],
                        'last_rotation_date': row[3],
                        'last_rotation_week': row[4],
                        'rotation_count': row[5] or 0,
                        'runtime_state': row[6] or {}
                    }
                return {
                    'portfolio_peak': None,
                    'drawdown_protection_active': False,
                    'drawdown_protection_end_date': None,
                    'last_rotation_date': None,
                    'last_rotation_week': None,
                    'rotation_count': 0,
                    'runtime_state': {}
                }
            finally:
                self.return_connection(conn)

        try:
            return self._retry_operation(_get)
        except Exception as e:
            print(f"[DATABASE] Error getting bot state: {e}")
            return {
                'portfolio_peak': None,
                'drawdown_protection_active': False,
                'drawdown_protection_end_date': None,
                'last_rotation_date': None,
                'last_rotation_week': None,
                'rotation_count': 0,
                'runtime_state': {}
            }

    def update_bot_state(self, portfolio_peak=None, drawdown_protection_active=None,
                         drawdown_protection_end_date=None, last_rotation_date=None,
                         last_rotation_week=None, rotation_count=None, runtime_state=None,
                         regime_state=None, rotation_metadata=None):
        """Update bot state in database"""

        def _update():
            conn = self.get_connection()
            try:
                cursor = conn.cursor()

                # Build dynamic update based on provided values
                updates = []
                values = []

                if portfolio_peak is not None:
                    updates.append("portfolio_peak = %s")
                    values.append(portfolio_peak)
                if drawdown_protection_active is not None:
                    updates.append("drawdown_protection_active = %s")
                    values.append(drawdown_protection_active)
                if drawdown_protection_end_date is not None:
                    updates.append("drawdown_protection_end_date = %s")
                    values.append(drawdown_protection_end_date)
                if last_rotation_date is not None:
                    updates.append("last_rotation_date = %s")
                    values.append(last_rotation_date)
                if last_rotation_week is not None:
                    updates.append("last_rotation_week = %s")
                    values.append(last_rotation_week)
                if rotation_count is not None:
                    updates.append("rotation_count = %s")
                    values.append(rotation_count)
                if runtime_state is not None:
                    updates.append("runtime_state = %s")
                    values.append(json.dumps(runtime_state) if isinstance(runtime_state, dict) else runtime_state)

                updates.append("updated_at = CURRENT_TIMESTAMP")

                if updates:
                    query = f"UPDATE bot_state SET {', '.join(updates)} WHERE id = 1"
                    cursor.execute(query, values)
                    conn.commit()

                cursor.close()
            finally:
                self.return_connection(conn)

        try:
            self._retry_operation(_update)
        except Exception as e:
            print(f"[DATABASE] Error updating bot state: {e}")

    def delete_stale_position_metadata(self, current_tickers):
        """Delete position metadata for tickers no longer in current positions"""

        def _delete_stale():
            conn = self.get_connection()
            try:
                cursor = conn.cursor()
                if current_tickers:
                    placeholders = ','.join(['%s'] * len(current_tickers))
                    cursor.execute(f"""
                        DELETE FROM position_metadata 
                        WHERE ticker NOT IN ({placeholders})
                    """, tuple(current_tickers))
                else:
                    # No current positions - clear all
                    cursor.execute("DELETE FROM position_metadata")
                conn.commit()
                cursor.close()
            finally:
                self.return_connection(conn)

        try:
            self._retry_operation(_delete_stale)
        except Exception as e:
            print(f"[DATABASE] Error deleting stale position metadata: {e}")

    def close_pool(self):
        """Close all connections in pool"""
        if self.connection_pool:
            self.connection_pool.closeall()
            print("[DATABASE] Connection pool closed")

    # In PostgresDatabase class:

    def get_daily_signal_scan_date(self):
        """Get the date when daily signal scan was last completed"""

        def _get():
            conn = self.get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("SELECT value FROM dashboard_settings WHERE key = 'last_signal_scan_date'")
                row = cursor.fetchone()
                cursor.close()
                if row and row[0]:
                    return datetime.strptime(row[0], '%Y-%m-%d').date()
                return None
            finally:
                self.return_connection(conn)

        try:
            return self._retry_operation(_get)
        except Exception as e:
            print(f"[DATABASE] Error getting signal scan date: {e}")
            return None

    def set_daily_signal_scan_date(self, scan_date):
        """Record that daily signal scan completed for this date"""

        def _set():
            conn = self.get_connection()
            try:
                cursor = conn.cursor()
                value = scan_date.strftime('%Y-%m-%d')
                cursor.execute("""
                    INSERT INTO dashboard_settings (key, value, updated_at)
                    VALUES ('last_signal_scan_date', %s, CURRENT_TIMESTAMP)
                    ON CONFLICT (key) DO UPDATE SET value = %s, updated_at = CURRENT_TIMESTAMP
                """, (value, value))
                conn.commit()
                cursor.close()
                print(f"[DATABASE] Signal scan date set to: {value}")
            finally:
                self.return_connection(conn)

        try:
            self._retry_operation(_set)
        except Exception as e:
            print(f"[DATABASE] Error setting signal scan date: {e}")

# =============================================================================
# IN-MEMORY DATABASE FOR BACKTESTING
# =============================================================================

class InMemoryDatabase:
    """DataFrame-based in-memory database for backtesting"""

    def __init__(self):
        # Use DataFrames for tabular data
        self.tickers_df = pd.DataFrame(columns=['ticker', 'name', 'strategies', 'is_blacklisted'])
        self.closed_trades_df = pd.DataFrame(columns=[
            'ticker', 'quantity', 'entry_price', 'exit_price', 'pnl_dollars', 'pnl_pct',
            'entry_signal', 'entry_score', 'exit_signal', 'exit_date'
        ])
        self.daily_metrics_df = pd.DataFrame(columns=[
            'date', 'portfolio_value', 'cash_balance', 'num_positions', 'num_trades',
            'realized_pnl', 'unrealized_pnl', 'win_rate', 'spy_close', 'market_regime'
        ])
        self.signal_performance_df = pd.DataFrame(columns=[
            'signal_name', 'total_trades', 'wins', 'win_rate', 'total_pnl', 'avg_pnl', 'last_updated'
        ])

        # Keep dicts for other data
        self.position_metadata = {}
        self.rotation_state = {}
        self.bot_state = {
            'portfolio_peak': None,
            'drawdown_protection_active': False,
            'drawdown_protection_end_date': None,
            'last_rotation_date': None,
            'last_rotation_week': None,
            'rotation_count': 0,
            'runtime_state': {}
        }
        self.dashboard_settings = {'bot_paused': False}

        print("[MEMORY DB] DataFrame-based in-memory database initialized")

    def get_connection(self):
        return self

    def return_connection(self, conn):
        pass

    def close_pool(self):
        pass

    def health_check(self):
        """In-memory database is always healthy"""
        return True

    # =========================================================================
    # DASHBOARD SETTINGS METHODS
    # =========================================================================

    def get_bot_paused(self):
        """Check if bot is paused via dashboard"""
        return self.dashboard_settings.get('bot_paused', False)

    def set_bot_paused(self, paused):
        """Set bot paused state from dashboard"""
        self.dashboard_settings['bot_paused'] = paused

    # =========================================================================
    # DAILY TRADED STOCKS METHODS (No-ops for backtesting)
    # =========================================================================

    def add_daily_traded_stock(self, ticker, trade_date):
        """No-op for backtesting - trades controlled by last_trade_date"""
        pass

    def get_daily_traded_stocks(self, trade_date):
        """Return empty set for backtesting - trades controlled by last_trade_date"""
        return set()

    def clear_old_daily_traded(self, current_date):
        """No-op for backtesting"""
        pass

    # =========================================================================
    # ROTATION STATE METHODS
    # =========================================================================

    def save_rotation_state(self, ticker_states):
        """Save rotation states to memory"""
        self.rotation_state = ticker_states.copy()

    def load_rotation_state(self):
        """Load rotation states from memory"""
        return self.rotation_state.copy()

    # =========================================================================
    # TRADE OPERATIONS
    # =========================================================================

    def insert_trade(self, ticker, quantity, entry_price, exit_price, pnl_dollars, pnl_pct,
                     entry_signal, entry_score, exit_signal, exit_date,
                     confirmation_date=None, days_to_confirmation=0):
        new_row = pd.DataFrame([{
            'ticker': ticker,
            'quantity': quantity,
            'entry_price': float(entry_price),
            'exit_price': float(exit_price),
            'pnl_dollars': float(pnl_dollars),
            'pnl_pct': float(pnl_pct),
            'entry_signal': entry_signal,
            'entry_score': entry_score,
            'exit_signal': exit_signal,
            'exit_date': exit_date,
            'confirmation_date': confirmation_date,
            'days_to_confirmation': days_to_confirmation
        }])
        if self.closed_trades_df.empty:
            self.closed_trades_df = new_row
        else:
            self.closed_trades_df = pd.concat([self.closed_trades_df, new_row], ignore_index=True)

    def get_closed_trades(self, limit=None):
        if self.closed_trades_df.empty:
            return []

        df = self.closed_trades_df.sort_values('exit_date', ascending=False)
        if limit:
            df = df.head(limit)

        trades = []
        for _, row in df.iterrows():
            trade = row.to_dict()
            # Map exit_signal to exit_signal for consistency with live DB
            if 'exit_signal' in trade and 'exit_signal' not in trade:
                trade['exit_signal'] = trade.get('exit_signal', 'unknown')
            trades.append(trade)
        return trades

    def record_closed_trade(self, ticker, quantity, entry_price, exit_price,
                            pnl_dollars, pnl_pct, entry_signal, entry_score,
                            exit_signal, exit_date):
        new_row = pd.DataFrame([{
            'ticker': ticker,
            'quantity': quantity,
            'entry_price': entry_price,
            'exit_price': exit_price,
            'pnl_dollars': pnl_dollars,
            'pnl_pct': pnl_pct,
            'entry_signal': entry_signal,
            'entry_score': entry_score,
            'exit_signal': exit_signal,
            'exit_date': exit_date
        }])
        if self.closed_trades_df.empty:
            self.closed_trades_df = new_row
        else:
            self.closed_trades_df = pd.concat([self.closed_trades_df, new_row], ignore_index=True)

    def get_trades_by_signal(self, signal_name, lookback=None):
        if self.closed_trades_df.empty:
            return []

        df = self.closed_trades_df[self.closed_trades_df['entry_signal'] == signal_name]
        if lookback:
            df = df.tail(lookback)
        return df.to_dict('records')

    # =========================================================================
    # POSITION METADATA OPERATIONS
    # =========================================================================

    def upsert_position_metadata(self, ticker, entry_date, entry_signal, entry_score,
                                 entry_price=None, initial_stop=None, current_stop=None,
                                 R=None, entry_atr=None, highest_close=None,
                                 phase='entry', bars_below_ema50=0, partial_taken=False,
                                 add_count=0):

        self.position_metadata[ticker] = {
            'entry_date': entry_date,
            'entry_signal': entry_signal,
            'entry_score': entry_score,
            'entry_price': float(entry_price) if entry_price else None,
            'initial_stop': float(initial_stop) if initial_stop else None,
            'current_stop': float(current_stop) if current_stop else None,
            'R': float(R) if R else None,
            'entry_atr': float(entry_atr) if entry_atr else None,
            'highest_close': float(highest_close) if highest_close else None,
            'phase': phase or 'entry',
            'bars_below_ema50': bars_below_ema50 or 0,
            'partial_taken': partial_taken or False,
            'add_count': add_count or 0
        }

    def clear_all_position_metadata(self):
        self.position_metadata = {}

    # =========================================================================
    # BOT STATE OPERATIONS
    # =========================================================================

    def update_bot_state(self, portfolio_peak, drawdown_protection_active,
                         drawdown_protection_end_date, last_rotation_date,
                         last_rotation_week, rotation_count, runtime_state):
        self.bot_state = {
            'portfolio_peak': portfolio_peak,
            'drawdown_protection_active': drawdown_protection_active,
            'drawdown_protection_end_date': drawdown_protection_end_date,
            'last_rotation_date': last_rotation_date,
            'last_rotation_week': last_rotation_week,
            'rotation_count': rotation_count,
            'runtime_state': runtime_state
        }

    def get_bot_state(self):
        return self.bot_state.copy()

    # =========================================================================
    # DAILY METRICS OPERATIONS
    # =========================================================================

    def save_daily_metrics(self, date, portfolio_value, cash_balance, num_positions,
                           num_trades, realized_pnl, unrealized_pnl, win_rate,
                           spy_close, market_regime):
        """Save daily metrics to DataFrame"""
        new_row = pd.DataFrame([{
            'date': date,
            'portfolio_value': portfolio_value,
            'cash_balance': cash_balance,
            'num_positions': num_positions,
            'num_trades': num_trades,
            'realized_pnl': realized_pnl,
            'unrealized_pnl': unrealized_pnl,
            'win_rate': win_rate,
            'spy_close': spy_close,
            'market_regime': market_regime
        }])

        # Remove existing row for this date if exists
        if not self.daily_metrics_df.empty:
            self.daily_metrics_df = self.daily_metrics_df[self.daily_metrics_df['date'] != date]

        if self.daily_metrics_df.empty:
            self.daily_metrics_df = new_row
        else:
            self.daily_metrics_df = pd.concat([self.daily_metrics_df, new_row], ignore_index=True)

    # =========================================================================
    # SIGNAL PERFORMANCE OPERATIONS
    # =========================================================================

    def update_signal_performance(self, signal_name, total_trades, wins, total_pnl):
        """Update signal performance in DataFrame"""
        win_rate = (wins / total_trades * 100) if total_trades > 0 else 0
        avg_pnl = total_pnl / total_trades if total_trades > 0 else 0

        new_row = pd.DataFrame([{
            'signal_name': signal_name,
            'total_trades': total_trades,
            'wins': wins,
            'win_rate': win_rate,
            'total_pnl': total_pnl,
            'avg_pnl': avg_pnl,
            'last_updated': datetime.now()
        }])

        # Remove existing row for this signal if exists
        if not self.signal_performance_df.empty:
            self.signal_performance_df = self.signal_performance_df[
                self.signal_performance_df['signal_name'] != signal_name
                ]

        if self.signal_performance_df.empty:
            self.signal_performance_df = new_row
        else:
            self.signal_performance_df = pd.concat([self.signal_performance_df, new_row], ignore_index=True)

    # In InMemoryDatabase class (no-ops for backtesting):

    def get_daily_signal_scan_date(self):
        """Backtesting uses last_trade_date instead"""
        return None

    def set_daily_signal_scan_date(self, scan_date):
        """No-op for backtesting"""
        pass

# =============================================================================
# GLOBAL DATABASE INSTANCE
# =============================================================================

_db_instance = None


def get_database():
    """Get or create global database instance (PostgreSQL or in-memory based on mode)"""
    global _db_instance

    if _db_instance is None:
        if Config.BACKTESTING:
            _db_instance = InMemoryDatabase()
        else:
            _db_instance = Database()

    return _db_instance
