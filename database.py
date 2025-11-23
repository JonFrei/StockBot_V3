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
import pandas as pd


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

            # Blacklist table with strategy column
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS blacklist (
                    ticker VARCHAR(10),
                    strategy VARCHAR(50),
                    blacklist_type VARCHAR(20) NOT NULL,
                    expiry_date TIMESTAMP,
                    consecutive_losses INTEGER DEFAULT 0,
                    reason VARCHAR(200),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (ticker, strategy)
                );
                CREATE INDEX IF NOT EXISTS idx_blacklist_strategy ON blacklist(strategy);
                CREATE INDEX IF NOT EXISTS idx_blacklist_type ON blacklist(blacklist_type);
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
    """DataFrame-based in-memory database for backtesting"""

    def __init__(self):
        # Use DataFrames for tabular data
        self.tickers_df = pd.DataFrame(columns=['ticker', 'name', 'strategies', 'is_blacklisted'])
        self.closed_trades_df = pd.DataFrame(columns=[
            'ticker', 'quantity', 'entry_price', 'exit_price', 'pnl_dollars', 'pnl_pct',
            'entry_signal', 'entry_score', 'exit_signal', 'exit_date'
        ])
        self.order_log_df = pd.DataFrame(columns=[
            'ticker', 'side', 'quantity', 'order_type', 'limit_price', 'filled_price',
            'submitted_at', 'signal_type', 'portfolio_value', 'cash_before', 'award',
            'quality_score', 'broker_order_id'
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

        print("[MEMORY DB] DataFrame-based in-memory database initialized")

    def get_connection(self):
        return self

    def return_connection(self, conn):
        pass

    def close_pool(self):
        pass

    # Trade operations
    def insert_trade(self, ticker, quantity, entry_price, exit_price, pnl_dollars, pnl_pct,
                     entry_signal, entry_score, exit_signal, exit_date):
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
            'exit_date': exit_date
        }])
        self.closed_trades_df = pd.concat([self.closed_trades_df, new_row], ignore_index=True)

    def get_closed_trades(self, limit=None):
        if self.closed_trades_df.empty:
            return []

        df = self.closed_trades_df.sort_values('exit_date', ascending=False)
        if limit:
            df = df.head(limit)
        return df.to_dict('records')

    def get_trades_by_signal(self, signal_name, lookback=None):
        if self.closed_trades_df.empty:
            return []

        df = self.closed_trades_df[self.closed_trades_df['entry_signal'] == signal_name]
        df = df.sort_values('exit_date', ascending=False)
        if lookback:
            df = df.head(lookback)
        return df.to_dict('records')

    def get_trades_by_date(self, target_date):
        if self.closed_trades_df.empty:
            return []

        df = self.closed_trades_df[self.closed_trades_df['exit_date'].dt.date == target_date]
        return df.to_dict('records')

    def get_all_trades_summary(self):
        if self.closed_trades_df.empty:
            return {'total_trades': 0, 'total_wins': 0, 'total_realized': 0.0}

        total_trades = len(self.closed_trades_df)
        total_wins = (self.closed_trades_df['pnl_dollars'] > 0).sum()
        total_realized = self.closed_trades_df['pnl_dollars'].sum()

        return {
            'total_trades': total_trades,
            'total_wins': int(total_wins),
            'total_realized': float(total_realized)
        }

    # Order log operations
    def insert_order_log(self, ticker, side, quantity, order_type, limit_price, filled_price,
                         submitted_at, signal_type, portfolio_value, cash_before, award,
                         quality_score, broker_order_id):
        new_row = pd.DataFrame([{
            'ticker': ticker,
            'side': side,
            'quantity': quantity,
            'order_type': order_type,
            'limit_price': float(limit_price) if limit_price else None,
            'filled_price': float(filled_price) if filled_price else None,
            'submitted_at': submitted_at,
            'signal_type': signal_type,
            'portfolio_value': float(portfolio_value),
            'cash_before': float(cash_before),
            'award': award,
            'quality_score': quality_score,
            'broker_order_id': broker_order_id
        }])
        self.order_log_df = pd.concat([self.order_log_df, new_row], ignore_index=True)

    def get_order_log(self, ticker=None, limit=None):
        if self.order_log_df.empty:
            return []

        df = self.order_log_df
        if ticker:
            df = df[df['ticker'] == ticker]

        df = df.sort_values('submitted_at', ascending=False)
        if limit:
            df = df.head(limit)
        return df.to_dict('records')

    # Daily metrics operations
    def upsert_daily_metrics(self, date, portfolio_value, cash_balance, num_positions,
                             num_trades, realized_pnl, unrealized_pnl, win_rate,
                             spy_close, market_regime):
        # Remove existing entry for this date
        self.daily_metrics_df = self.daily_metrics_df[self.daily_metrics_df['date'] != date]

        new_row = pd.DataFrame([{
            'date': date,
            'portfolio_value': float(portfolio_value),
            'cash_balance': float(cash_balance),
            'num_positions': num_positions,
            'num_trades': num_trades,
            'realized_pnl': float(realized_pnl),
            'unrealized_pnl': float(unrealized_pnl),
            'win_rate': float(win_rate),
            'spy_close': float(spy_close) if spy_close else None,
            'market_regime': market_regime
        }])
        self.daily_metrics_df = pd.concat([self.daily_metrics_df, new_row], ignore_index=True)

    def get_daily_metrics(self, date):
        if self.daily_metrics_df.empty:
            return None

        df = self.daily_metrics_df[self.daily_metrics_df['date'] == date]
        if df.empty:
            return None
        return df.iloc[0].to_dict()

    def get_all_daily_metrics(self):
        if self.daily_metrics_df.empty:
            return []
        return self.daily_metrics_df.sort_values('date', ascending=False).to_dict('records')

    # Signal performance operations
    def upsert_signal_performance(self, signal_name, total_trades, wins, win_rate,
                                  total_pnl, avg_pnl):
        # Remove existing entry
        self.signal_performance_df = self.signal_performance_df[
            self.signal_performance_df['signal_name'] != signal_name
            ]

        new_row = pd.DataFrame([{
            'signal_name': signal_name,
            'total_trades': total_trades,
            'wins': wins,
            'win_rate': float(win_rate),
            'total_pnl': float(total_pnl),
            'avg_pnl': float(avg_pnl),
            'last_updated': datetime.now()
        }])
        self.signal_performance_df = pd.concat([self.signal_performance_df, new_row], ignore_index=True)

    def get_signal_performance(self, signal_name):
        if self.signal_performance_df.empty:
            return None

        df = self.signal_performance_df[self.signal_performance_df['signal_name'] == signal_name]
        if df.empty:
            return None
        return df.iloc[0].to_dict()

    def get_all_signal_performance(self):
        if self.signal_performance_df.empty:
            return []
        return self.signal_performance_df.to_dict('records')

    # Ticker operations
    def get_tickers_by_strategy(self, strategy_name):
        if self.tickers_df.empty:
            return []

        df = self.tickers_df[
            (self.tickers_df['strategies'].apply(lambda x: strategy_name in x if isinstance(x, list) else False)) &
            (self.tickers_df['is_blacklisted'] == False)
            ]
        return df['ticker'].tolist()

    def insert_ticker(self, ticker, name, strategies):
        # Remove existing
        self.tickers_df = self.tickers_df[self.tickers_df['ticker'] != ticker]

        new_row = pd.DataFrame([{
            'ticker': ticker,
            'name': name,
            'strategies': strategies.copy() if isinstance(strategies, list) else [],
            'is_blacklisted': False
        }])
        self.tickers_df = pd.concat([self.tickers_df, new_row], ignore_index=True)

    def get_all_tickers(self):
        if self.tickers_df.empty:
            return {}
        return {row['ticker']: {'name': row['name'], 'strategies': row['strategies'],
                                'is_blacklisted': row['is_blacklisted']}
                for _, row in self.tickers_df.iterrows()}

    # Keep all existing dict-based methods unchanged
    def upsert_position_metadata(self, ticker, entry_date, entry_signal, entry_score,
                                 highest_price, profit_level_1_locked, profit_level_2_locked,
                                 profit_level_3_locked):
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
        return self.position_metadata.copy()

    def delete_position_metadata(self, ticker):
        if ticker in self.position_metadata:
            del self.position_metadata[ticker]

    def clear_all_position_metadata(self):
        self.position_metadata = {}

    def update_bot_state(self, portfolio_peak, drawdown_protection_active,
                         drawdown_protection_end_date, last_rotation_date,
                         last_rotation_week, ticker_awards):
        self.bot_state = {
            'portfolio_peak': portfolio_peak,
            'drawdown_protection_active': drawdown_protection_active,
            'drawdown_protection_end_date': drawdown_protection_end_date,
            'last_rotation_date': last_rotation_date,
            'last_rotation_week': last_rotation_week,
            'ticker_awards': ticker_awards
        }

    def get_bot_state(self):
        return self.bot_state.copy()

    def upsert_cooldown(self, ticker, last_buy_date):
        self.cooldowns[ticker] = last_buy_date

    def get_all_cooldowns(self):
        return self.cooldowns.copy()

    def delete_cooldown(self, ticker):
        if ticker in self.cooldowns:
            del self.cooldowns[ticker]

    def clear_all_cooldowns(self):
        self.cooldowns = {}

    def upsert_blacklist(self, ticker, strategy, blacklist_type, expiry_date, reason):
        key = (ticker, strategy)
        self.blacklist[key] = {
            'blacklist_type': blacklist_type,
            'expiry_date': expiry_date,
            'reason': reason
        }

    def get_blacklist_by_strategy(self, strategy):
        result = {}
        for (ticker, strat), data in self.blacklist.items():
            if strat == strategy:
                result[ticker] = data.copy()
        return result

    def get_all_blacklist(self):
        return self.blacklist.copy()

    def delete_blacklist(self, ticker, strategy):
        key = (ticker, strategy)
        if key in self.blacklist:
            del self.blacklist[key]

    def clear_all_blacklist(self):
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
