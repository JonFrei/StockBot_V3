"""
PostgreSQL Database Connection and Schema
Railway-optimized with connection pooling

DUAL MODE: PostgreSQL for live, in-memory for backtesting
"""

import os
import psycopg2
from psycopg2 import pool
from psycopg2.extras import RealDictCursor
from datetime import datetime
import json
from config import Config


class Database:
    """PostgreSQL connection manager with pooling"""

    def __init__(self):
        self.connection_pool = None
        self._init_pool()
        self._create_tables()

    def _init_pool(self):
        """Initialize connection pool from DATABASE_URL"""
        database_url = os.getenv('DATABASE_URL')

        if not database_url:
            raise Exception("DATABASE_URL environment variable not set")

        # Railway provides DATABASE_URL, create connection pool
        self.connection_pool = psycopg2.pool.SimpleConnectionPool(
            minconn=1,
            maxconn=10,
            dsn=database_url
        )

        print("[DATABASE] Connection pool initialized")

    def get_connection(self):
        """Get connection from pool"""
        return self.connection_pool.getconn()

    def return_connection(self, conn):
        """Return connection to pool"""
        self.connection_pool.putconn(conn)

    def _create_tables(self):
        """Create all required tables if they don't exist"""
        conn = self.get_connection()
        try:
            cursor = conn.cursor()

            # Closed trades table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS closed_trades (
                    id SERIAL PRIMARY KEY,
                    ticker VARCHAR(10) NOT NULL,
                    quantity INTEGER NOT NULL,
                    entry_price DECIMAL(10, 2) NOT NULL,
                    exit_price DECIMAL(10, 2) NOT NULL,
                    pnl_dollars DECIMAL(10, 2) NOT NULL,
                    pnl_pct DECIMAL(10, 2) NOT NULL,
                    entry_signal VARCHAR(50) NOT NULL,
                    entry_score INTEGER DEFAULT 0,
                    exit_signal VARCHAR(50) NOT NULL,
                    exit_date TIMESTAMP NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_closed_trades_ticker ON closed_trades(ticker);
                CREATE INDEX IF NOT EXISTS idx_closed_trades_exit_date ON closed_trades(exit_date);
            """)

            # Position metadata table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS position_metadata (
                    ticker VARCHAR(10) PRIMARY KEY,
                    entry_date TIMESTAMP NOT NULL,
                    entry_signal VARCHAR(50) NOT NULL,
                    entry_score INTEGER DEFAULT 0,
                    highest_price DECIMAL(10, 2) NOT NULL,
                    profit_level_1_locked BOOLEAN DEFAULT FALSE,
                    profit_level_2_locked BOOLEAN DEFAULT FALSE,
                    profit_level_3_locked BOOLEAN DEFAULT FALSE,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)

            # Bot state table (single row for current state)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS bot_state (
                    id INTEGER PRIMARY KEY DEFAULT 1,
                    portfolio_peak DECIMAL(12, 2),
                    drawdown_protection_active BOOLEAN DEFAULT FALSE,
                    drawdown_protection_end_date TIMESTAMP,
                    last_rotation_date TIMESTAMP,
                    last_rotation_week VARCHAR(10),
                    ticker_awards JSONB DEFAULT '{}',
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    CONSTRAINT single_row CHECK (id = 1)
                );
                INSERT INTO bot_state (id) VALUES (1) ON CONFLICT (id) DO NOTHING;
            """)

            # Cooldowns table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS cooldowns (
                    ticker VARCHAR(10) PRIMARY KEY,
                    last_buy_date TIMESTAMP NOT NULL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)

            # Blacklist table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS blacklist (
                    ticker VARCHAR(10) PRIMARY KEY,
                    blacklist_type VARCHAR(20) NOT NULL,
                    expiry_date TIMESTAMP,
                    consecutive_losses INTEGER DEFAULT 0,
                    reason VARCHAR(200),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)

            conn.commit()
            print("[DATABASE] Tables created/verified successfully")

        except Exception as e:
            conn.rollback()
            raise Exception(f"Failed to create tables: {e}")
        finally:
            cursor.close()
            self.return_connection(conn)

    def close_pool(self):
        """Close all connections in pool"""
        if self.connection_pool:
            self.connection_pool.closeall()
            print("[DATABASE] Connection pool closed")


# =============================================================================
# IN-MEMORY DATABASE FOR BACKTESTING
# =============================================================================

class InMemoryDatabase:
    """
    In-memory database that mimics PostgreSQL structure for backtesting
    Provides same interface as Database class
    """

    def __init__(self):
        self.closed_trades = []
        self.position_metadata = {}
        self.bot_state = {
            'portfolio_peak': None,
            'drawdown_protection_active': False,
            'drawdown_protection_end_date': None,
            'last_rotation_date': None,
            'last_rotation_week': None,
            'ticker_awards': {}
        }
        self.cooldowns = {}
        self.blacklist = {}

        print("[MEMORY DB] In-memory database initialized for backtesting")

    def get_connection(self):
        """Return self (no connection needed for in-memory)"""
        return self

    def return_connection(self, conn):
        """No-op for in-memory"""
        pass

    def close_pool(self):
        """No-op for in-memory"""
        pass

    # Trade operations
    def insert_trade(self, ticker, quantity, entry_price, exit_price, pnl_dollars, pnl_pct,
                     entry_signal, entry_score, exit_signal, exit_date):
        """Insert trade into in-memory list"""
        trade = {
            'ticker': ticker,
            'quantity': quantity,
            'entry_price': float(entry_price),
            'exit_price': float(exit_price),
            'pnl_dollars': float(pnl_dollars),
            'pnl_pct': float(pnl_pct),
            'entry_signal': entry_signal,
            'entry_score': entry_score,
            'exit_signal': exit_signal,
            'exit_date': exit_date
        }
        self.closed_trades.append(trade)

    def get_closed_trades(self, limit=None):
        """Get closed trades from memory"""
        trades = sorted(self.closed_trades, key=lambda x: x['exit_date'], reverse=True)
        if limit:
            return trades[:limit]
        return trades

    def get_trades_by_signal(self, signal_name, lookback=None):
        """Get trades for specific signal"""
        trades = [t for t in self.closed_trades if t['entry_signal'] == signal_name]
        trades = sorted(trades, key=lambda x: x['exit_date'], reverse=True)
        if lookback:
            return trades[:lookback]
        return trades

    def get_trades_by_date(self, target_date):
        """Get trades for specific date"""
        return [t for t in self.closed_trades if t['exit_date'].date() == target_date]

    def get_all_trades_summary(self):
        """Get summary stats for all trades"""
        if not self.closed_trades:
            return {'total_trades': 0, 'total_wins': 0, 'total_realized': 0.0}

        total_trades = len(self.closed_trades)
        total_wins = sum(1 for t in self.closed_trades if t['pnl_dollars'] > 0)
        total_realized = sum(t['pnl_dollars'] for t in self.closed_trades)

        return {
            'total_trades': total_trades,
            'total_wins': total_wins,
            'total_realized': total_realized
        }

    # Position metadata operations
    def upsert_position_metadata(self, ticker, entry_date, entry_signal, entry_score,
                                 highest_price, profit_level_1_locked, profit_level_2_locked,
                                 profit_level_3_locked):
        """Insert or update position metadata"""
        self.position_metadata[ticker] = {
            'entry_date': entry_date,
            'entry_signal': entry_signal,
            'entry_score': entry_score,
            'highest_price': float(highest_price),
            'profit_level_1_locked': profit_level_1_locked,
            'profit_level_2_locked': profit_level_2_locked,
            'profit_level_3_locked': profit_level_3_locked
        }

    def get_all_position_metadata(self):
        """Get all position metadata"""
        return self.position_metadata.copy()

    def delete_position_metadata(self, ticker):
        """Delete position metadata"""
        if ticker in self.position_metadata:
            del self.position_metadata[ticker]

    def clear_all_position_metadata(self):
        """Clear all position metadata"""
        self.position_metadata = {}

    # Bot state operations
    def update_bot_state(self, portfolio_peak, drawdown_protection_active,
                         drawdown_protection_end_date, last_rotation_date,
                         last_rotation_week, ticker_awards):
        """Update bot state"""
        self.bot_state = {
            'portfolio_peak': portfolio_peak,
            'drawdown_protection_active': drawdown_protection_active,
            'drawdown_protection_end_date': drawdown_protection_end_date,
            'last_rotation_date': last_rotation_date,
            'last_rotation_week': last_rotation_week,
            'ticker_awards': ticker_awards
        }

    def get_bot_state(self):
        """Get bot state"""
        return self.bot_state.copy()

    # Cooldown operations
    def upsert_cooldown(self, ticker, last_buy_date):
        """Insert or update cooldown"""
        self.cooldowns[ticker] = last_buy_date

    def get_all_cooldowns(self):
        """Get all cooldowns"""
        return self.cooldowns.copy()

    def delete_cooldown(self, ticker):
        """Delete cooldown"""
        if ticker in self.cooldowns:
            del self.cooldowns[ticker]

    def clear_all_cooldowns(self):
        """Clear all cooldowns"""
        self.cooldowns = {}

    # Blacklist operations
    def upsert_blacklist(self, ticker, blacklist_type, expiry_date, reason):
        """Insert or update blacklist entry"""
        self.blacklist[ticker] = {
            'blacklist_type': blacklist_type,
            'expiry_date': expiry_date,
            'reason': reason
        }

    def get_all_blacklist(self):
        """Get all blacklist entries"""
        return self.blacklist.copy()

    def delete_blacklist(self, ticker):
        """Delete blacklist entry"""
        if ticker in self.blacklist:
            del self.blacklist[ticker]

    def clear_all_blacklist(self):
        """Clear all blacklist entries"""
        self.blacklist = {}


# Global database instance
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