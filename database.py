"""
PostgreSQL Database Connection and Schema
Railway-optimized with connection pooling and retry logic

DUAL MODE: PostgreSQL for live, in-memory for backtesting

Features:
- Connection retry with exponential backoff
- Health check endpoint
- Rotation state persistence
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
                    pnl_dollars DECIMAL(10, 2) NOT NULL,
                    pnl_pct DECIMAL(10, 2) NOT NULL,
                    entry_signal VARCHAR(50) NOT NULL,
                    entry_score INTEGER DEFAULT 0,
                    exit_signal VARCHAR(50) NOT NULL,
                    exit_date TIMESTAMP NOT NULL,
                    was_watchlisted BOOLEAN DEFAULT FALSE,
                    confirmation_date TIMESTAMP,
                    days_to_confirmation INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_closed_trades_ticker ON closed_trades(ticker);
                CREATE INDEX IF NOT EXISTS idx_closed_trades_exit_date ON closed_trades(exit_date);
                CREATE INDEX IF NOT EXISTS idx_closed_trades_confirmation ON closed_trades(was_watchlisted, confirmation_date);
                CREATE INDEX IF NOT EXISTS idx_closed_trades_signal_confirmation ON closed_trades(entry_signal, was_watchlisted);
            """)

            # Position metadata table with new columns
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS position_metadata (
                    ticker VARCHAR(10) PRIMARY KEY,
                    entry_date TIMESTAMP NOT NULL,
                    entry_signal VARCHAR(50) NOT NULL,
                    entry_score INTEGER DEFAULT 0,
                    highest_price DECIMAL(10, 2) NOT NULL,
                    profit_level INTEGER DEFAULT 0,
                    level_1_lock_price DECIMAL(10, 2),
                    level_2_lock_price DECIMAL(10, 2),
                    was_watchlisted BOOLEAN DEFAULT FALSE,
                    confirmation_date TIMESTAMP,
                    days_to_confirmation INTEGER DEFAULT 0,
                    entry_price DECIMAL(10, 2),
                    kill_switch_active BOOLEAN DEFAULT FALSE,
                    peak_price DECIMAL(10, 2),
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
                    ticker_awards JSONB DEFAULT '{}',
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

            # Order log table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS order_log (
                    id SERIAL PRIMARY KEY,
                    ticker VARCHAR(10) NOT NULL,
                    side VARCHAR(10) NOT NULL,
                    quantity INTEGER NOT NULL,
                    order_type VARCHAR(20) NOT NULL,
                    limit_price DECIMAL(10, 2),
                    filled_price DECIMAL(10, 2),
                    submitted_at TIMESTAMP NOT NULL,
                    signal_type VARCHAR(50),
                    portfolio_value DECIMAL(12, 2),
                    cash_before DECIMAL(12, 2),
                    award VARCHAR(20),
                    quality_score INTEGER,
                    broker_order_id VARCHAR(100),
                    was_watchlisted BOOLEAN DEFAULT FALSE,
                    days_on_watchlist INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_order_log_ticker ON order_log(ticker);
                CREATE INDEX IF NOT EXISTS idx_order_log_submitted ON order_log(submitted_at);
                CREATE INDEX IF NOT EXISTS idx_order_log_watchlist ON order_log(was_watchlisted);
            """)

            # Daily metrics table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS daily_metrics (
                    date DATE PRIMARY KEY,
                    portfolio_value DECIMAL(12, 2),
                    cash_balance DECIMAL(12, 2),
                    num_positions INTEGER,
                    num_trades INTEGER,
                    realized_pnl DECIMAL(12, 2),
                    unrealized_pnl DECIMAL(12, 2),
                    win_rate DECIMAL(5, 2),
                    spy_close DECIMAL(10, 2),
                    market_regime VARCHAR(50),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)

            # Signal performance table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS signal_performance (
                    signal_name VARCHAR(50) PRIMARY KEY,
                    total_trades INTEGER DEFAULT 0,
                    wins INTEGER DEFAULT 0,
                    win_rate DECIMAL(5, 2) DEFAULT 0,
                    total_pnl DECIMAL(12, 2) DEFAULT 0,
                    avg_pnl DECIMAL(10, 2) DEFAULT 0,
                    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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

    # =========================================================================
    # ROTATION STATE METHODS
    # =========================================================================

    def save_rotation_state(self, ticker_states):
        """
        Save all rotation states to database with retry logic

        Args:
            ticker_states: Dict of {ticker: state_dict} from StockRotator
        """
        def _save():
            conn = self.get_connection()
            try:
                cursor = conn.cursor()

                for ticker, state in ticker_states.items():
                    cursor.execute("""
                        INSERT INTO rotation_state 
                        (ticker, tier, consecutive_wins, consecutive_losses, total_trades,
                         total_wins, total_pnl, total_win_pnl, total_loss_pnl, last_tier_change)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
            'entry_signal', 'entry_score', 'exit_signal', 'exit_date', 'was_watchlisted',
            'confirmation_date', 'days_to_confirmation'
        ])
        self.order_log_df = pd.DataFrame(columns=[
            'ticker', 'side', 'quantity', 'order_type', 'limit_price', 'filled_price',
            'submitted_at', 'signal_type', 'portfolio_value', 'cash_before', 'award',
            'quality_score', 'broker_order_id', 'was_watchlisted', 'days_on_watchlist'
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

    def health_check(self):
        """In-memory database is always healthy"""
        return True

    # =========================================================================
    # ROTATION STATE METHODS
    # =========================================================================

    def save_rotation_state(self, ticker_states):
        """Save rotation states to memory"""
        self.rotation_state = ticker_states.copy()

    def load_rotation_state(self):
        """Load rotation states from memory"""
        return self.rotation_state.copy()

    # Trade operations
    def insert_trade(self, ticker, quantity, entry_price, exit_price, pnl_dollars, pnl_pct,
                     entry_signal, entry_score, exit_signal, exit_date, was_watchlisted=False,
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
            'was_watchlisted': was_watchlisted,
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
                         quality_score, broker_order_id, was_watchlisted=False, days_on_watchlist=0):
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
            'broker_order_id': broker_order_id,
            'was_watchlisted': was_watchlisted,
            'days_on_watchlist': days_on_watchlist
        }])
        if self.order_log_df.empty:
            self.order_log_df = new_row
        else:
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
        if self.daily_metrics_df.empty:
            self.daily_metrics_df = new_row
        else:
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
        if self.signal_performance_df.empty:
            self.signal_performance_df = new_row
        else:
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

    # Position metadata operations
    def upsert_position_metadata(self, ticker, entry_date, entry_signal, entry_score,
                                 highest_price, profit_level=0,
                                 level_1_lock_price=None, level_2_lock_price=None,
                                 was_watchlisted=False, confirmation_date=None,
                                 days_to_confirmation=0, entry_price=None,
                                 kill_switch_active=False, peak_price=None):
        """Save position metadata with all fields"""
        self.position_metadata[ticker] = {
            'entry_date': entry_date,
            'entry_signal': entry_signal,
            'entry_score': entry_score,
            'highest_price': float(highest_price) if highest_price else 0,
            'local_max': float(highest_price) if highest_price else 0,
            'profit_level': profit_level,
            'level_1_lock_price': float(level_1_lock_price) if level_1_lock_price else None,
            'tier1_lock_price': float(level_1_lock_price) if level_1_lock_price else None,
            'level_2_lock_price': float(level_2_lock_price) if level_2_lock_price else None,
            'was_watchlisted': was_watchlisted,
            'confirmation_date': confirmation_date,
            'days_to_confirmation': days_to_confirmation,
            'entry_price': float(entry_price) if entry_price else None,
            'kill_switch_active': kill_switch_active,
            'peak_price': float(peak_price) if peak_price else None
        }

    def get_all_position_metadata(self):
        return self.position_metadata.copy()

    def delete_position_metadata(self, ticker):
        if ticker in self.position_metadata:
            del self.position_metadata[ticker]

    def clear_all_position_metadata(self):
        self.position_metadata = {}

    # Bot state operations
    def update_bot_state(self, portfolio_peak, drawdown_protection_active,
                         drawdown_protection_end_date, last_rotation_date,
                         last_rotation_week, rotation_count, ticker_awards):
        self.bot_state = {
            'portfolio_peak': portfolio_peak,
            'drawdown_protection_active': drawdown_protection_active,
            'drawdown_protection_end_date': drawdown_protection_end_date,
            'last_rotation_date': last_rotation_date,
            'last_rotation_week': last_rotation_week,
            'rotation_count': rotation_count,
            'ticker_awards': ticker_awards
        }

    def get_bot_state(self):
        return self.bot_state.copy()

    # Cooldown operations
    def upsert_cooldown(self, ticker, last_buy_date):
        self.cooldowns[ticker] = last_buy_date

    def get_all_cooldowns(self):
        return self.cooldowns.copy()

    def delete_cooldown(self, ticker):
        if ticker in self.cooldowns:
            del self.cooldowns[ticker]

    def clear_all_cooldowns(self):
        self.cooldowns = {}

    # Blacklist operations
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