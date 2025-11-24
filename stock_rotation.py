"""
Award-Based Stock Rotation System

UPDATED: Integrated with database for blacklist management (per-strategy)

Key Features:
- Performance-based awards (Premium/Standard) with no slot limits
- Weekly rotation that evaluates all stocks
- Trial period for new stocks (1.0x base for first 5 trades)
- Relative volume requirements that scale with system maturity
- Hybrid removal system (immediate for new, rolling window for established)
- Database-backed ticker blacklist (per-strategy tracking)
"""

from datetime import datetime, timedelta
import stock_data
import stock_signals as signals
from stock_position_monitoring import calculate_market_condition_score
from database import get_database
from config import Config


# =============================================================================
# AWARD CONFIGURATION
# =============================================================================

class AwardConfig:
    """Centralized configuration for award system"""

    # === AWARD MULTIPLIERS ===
    PREMIUM_MULTIPLIER = 1.5
    STANDARD_MULTIPLIER = 1.0
    TRIAL_MULTIPLIER = 1.0
    NO_AWARD_MULTIPLIER = 0.6
    FROZEN_MULTIPLIER = 0.0

    # === WIN RATE THRESHOLDS ===
    STANDARD_WIN_RATE = 55.0
    PREMIUM_WIN_RATE = 65.0
    DEATH_ROW_WIN_RATE = 30.0

    # === TRADE COUNT REQUIREMENTS ===
    TRIAL_TRADE_COUNT = 5
    STANDARD_MIN_TRADES = 5
    PREMIUM_MIN_TRADES = 8
    DEATH_ROW_MIN_TRADES = 10

    # === SCALING THRESHOLDS ===
    SCALING_START_TRADES = 100
    STANDARD_VOLUME_RATIO = 0.25
    PREMIUM_VOLUME_RATIO = 0.40

    # === REMOVAL RULES ===
    ROLLING_WINDOW_THRESHOLD = 20
    ROLLING_WINDOW_SIZE = 10
    ROLLING_WINDOW_WR = 50.0

    # === ROTATION ===
    ROTATION_FREQUENCY = 'weekly'

    # === BLACKLIST ===
    BLACKLIST_CONSECUTIVE_LOSSES = 3
    BLACKLIST_TEMP_DAYS = 21
    BLACKLIST_LOOKBACK_TRADES = 3
    BLACKLIST_LOSS_THRESHOLD = -1000


# =============================================================================
# TICKER BLACKLIST SYSTEM (Database-Backed, Per-Strategy)
# =============================================================================

class TickerBlacklist:
    """
    Database-backed ticker blacklist with per-strategy tracking
    """

    def __init__(self, profit_tracker, strategy_name='swing_trade_stocks'):
        self.profit_tracker = profit_tracker
        self.strategy_name = strategy_name
        self.consecutive_losses = {}
        self.temporary_blacklist = {}  # {ticker: expiry_date}
        self.permanent_blacklist = set()

        # Load from database
        self._load_from_database()

    def _load_from_database(self):
        """Load blacklist from database"""
        if Config.BACKTESTING:
            return  # In-memory mode doesn't persist

        db = get_database()
        conn = db.get_connection()

        try:
            cursor = conn.cursor()

            cursor.execute("""
                SELECT ticker, blacklist_type, expiry_date
                FROM blacklist
                WHERE strategy = %s
            """, (self.strategy_name,))

            for row in cursor.fetchall():
                ticker = row[0]
                blacklist_type = row[1]
                expiry_date = row[2]

                if blacklist_type == 'permanent':
                    self.permanent_blacklist.add(ticker)
                elif blacklist_type == 'temporary' and expiry_date:
                    self.temporary_blacklist[ticker] = expiry_date

            if self.permanent_blacklist or self.temporary_blacklist:
                print(f"[BLACKLIST] Loaded for {self.strategy_name}:")
                print(f"   Permanent: {len(self.permanent_blacklist)}")
                print(f"   Temporary: {len(self.temporary_blacklist)}")

        except Exception as e:
            print(f"[WARN] Could not load blacklist from database: {e}")

        finally:
            cursor.close()
            db.return_connection(conn)

    def update_from_trade(self, ticker, is_winner, current_date):
        """Update tracker when a trade closes"""
        if is_winner:
            self.consecutive_losses[ticker] = 0
        else:
            current_count = self.consecutive_losses.get(ticker, 0)
            self.consecutive_losses[ticker] = current_count + 1

            if self.consecutive_losses[ticker] >= AwardConfig.BLACKLIST_CONSECUTIVE_LOSSES:
                self._apply_temporary_blacklist(
                    ticker,
                    current_date,
                    days=AwardConfig.BLACKLIST_TEMP_DAYS,
                    reason=f'{AwardConfig.BLACKLIST_CONSECUTIVE_LOSSES} consecutive losses'
                )

            self._check_recent_loss_pnl(ticker, current_date)

        self._check_permanent_blacklist(ticker)

    def _apply_temporary_blacklist(self, ticker, current_date, days=21, reason=''):
        """Apply temporary blacklist"""
        if ticker not in self.permanent_blacklist:
            expiry = current_date + timedelta(days=days)
            previous_expiry = self.temporary_blacklist.get(ticker)

            if previous_expiry is None or expiry > previous_expiry:
                self.temporary_blacklist[ticker] = expiry
                print(f"\n⛔ TEMPORARY BLACKLIST: {ticker} ({reason}) - Until {expiry.strftime('%Y-%m-%d')}")

                # Save to database
                self._save_to_database(ticker, 'temporary', expiry, reason)

    def _check_recent_loss_pnl(self, ticker, current_date):
        """Check recent cumulative losses"""
        if not self.profit_tracker:
            return

        ticker_trades = [t for t in self.profit_tracker.closed_trades if t['ticker'] == ticker]
        if len(ticker_trades) < AwardConfig.BLACKLIST_LOOKBACK_TRADES:
            return

        recent_trades = ticker_trades[-AwardConfig.BLACKLIST_LOOKBACK_TRADES:]
        total_recent_pnl = sum(t['pnl_dollars'] for t in recent_trades)

        if total_recent_pnl <= AwardConfig.BLACKLIST_LOSS_THRESHOLD:
            self._apply_temporary_blacklist(
                ticker,
                current_date,
                days=14,
                reason=f'${total_recent_pnl:+,.0f} over last {AwardConfig.BLACKLIST_LOOKBACK_TRADES} trades'
            )

    def _check_permanent_blacklist(self, ticker):
        """Check if ticker should be permanently blacklisted"""
        trades = [t for t in self.profit_tracker.closed_trades if t['ticker'] == ticker]

        if len(trades) < 5:
            return

        wins = sum(1 for t in trades if t['pnl_dollars'] > 0)
        win_rate = wins / len(trades) * 100

        if win_rate < 30.0:
            self.permanent_blacklist.add(ticker)
            if ticker in self.temporary_blacklist:
                del self.temporary_blacklist[ticker]
            print(f"\n🚫 PERMANENT BLACKLIST: {ticker} ({win_rate:.1f}% win rate over {len(trades)} trades)")

            # Save to database
            self._save_to_database(ticker, 'permanent', None, f'{win_rate:.1f}% win rate')

    def _save_to_database(self, ticker, blacklist_type, expiry_date, reason):
        """Save blacklist entry to database"""
        if Config.BACKTESTING:
            return  # Don't persist in backtesting

        db = get_database()
        conn = db.get_connection()

        try:
            cursor = conn.cursor()

            cursor.execute("""
                INSERT INTO blacklist (ticker, strategy, blacklist_type, expiry_date, reason)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (ticker, strategy) DO UPDATE
                SET blacklist_type = EXCLUDED.blacklist_type,
                    expiry_date = EXCLUDED.expiry_date,
                    reason = EXCLUDED.reason,
                    created_at = CURRENT_TIMESTAMP
            """, (ticker, self.strategy_name, blacklist_type, expiry_date, reason))

            conn.commit()

        except Exception as e:
            conn.rollback()
            print(f"[ERROR] Failed to save blacklist for {ticker}: {e}")

        finally:
            cursor.close()
            db.return_connection(conn)

    def clean_expired_blacklists(self, current_date):
        """Remove expired temporary blacklists"""
        expired = [ticker for ticker, expiry in self.temporary_blacklist.items()
                   if current_date >= expiry]

        for ticker in expired:
            del self.temporary_blacklist[ticker]
            self.consecutive_losses[ticker] = 0
            print(f"\n✅ BLACKLIST EXPIRED: {ticker} - Back in rotation pool")

            # Remove from database
            self._remove_from_database(ticker)

    def _remove_from_database(self, ticker):
        """Remove blacklist entry from database"""
        if Config.BACKTESTING:
            return

        db = get_database()
        conn = db.get_connection()

        try:
            cursor = conn.cursor()

            cursor.execute("""
                DELETE FROM blacklist
                WHERE ticker = %s AND strategy = %s
            """, (ticker, self.strategy_name))

            conn.commit()

        except Exception as e:
            conn.rollback()
            print(f"[ERROR] Failed to remove blacklist for {ticker}: {e}")

        finally:
            cursor.close()
            db.return_connection(conn)

    def is_blacklisted(self, ticker):
        """Check if ticker is currently blacklisted"""
        return ticker in self.permanent_blacklist or ticker in self.temporary_blacklist

    def get_statistics(self):
        """Get blacklist statistics"""
        return {
            'strategy': self.strategy_name,
            'permanent_blacklist': list(self.permanent_blacklist),
            'temporary_blacklist': len(self.temporary_blacklist),
            'temp_blacklist_tickers': list(self.temporary_blacklist.keys()),
            'tickers_with_consecutive_losses': {
                ticker: count for ticker, count in self.consecutive_losses.items()
                if count > 0
            }
        }


# =============================================================================
# AWARD-BASED STOCK ROTATION SYSTEM
# =============================================================================

class StockRotator:
    """Award-based rotation system with database-backed blacklist"""

    def __init__(self, rotation_frequency='weekly', profit_tracker=None, strategy_name='swing_trade_stocks'):
        self.rotation_frequency = rotation_frequency
        self.strategy_name = strategy_name
        self.active_tickers = []
        self.last_rotation_date = None
        self.rotation_count = 0

        # Award tracking
        self.ticker_awards = {}
        self.ticker_stats = {}

        # Profit tracking integration
        self.profit_tracker = profit_tracker

        # Database-backed blacklist
        self.blacklist = TickerBlacklist(profit_tracker, strategy_name) if profit_tracker else None

    def should_rotate(self, current_date):
        """Check if it's time to rotate based on frequency"""
        if self.last_rotation_date is None:
            return True

        days_since_rotation = (current_date - self.last_rotation_date).days

        if self.rotation_frequency == 'daily':
            return days_since_rotation >= 1
        elif self.rotation_frequency == 'weekly':
            return days_since_rotation >= 7
        elif self.rotation_frequency == 'biweekly':
            return days_since_rotation >= 14
        elif self.rotation_frequency == 'monthly':
            return days_since_rotation >= 30

        return False

    def update_ticker_stats_from_tracker(self):
        """Update ticker statistics from profit tracker"""
        if not self.profit_tracker:
            return

        # Reset stats
        self.ticker_stats = {}

        # Get closed trades - USE THE METHOD, NOT ATTRIBUTE
        closed_trades = self.profit_tracker.get_closed_trades()

        for trade in closed_trades:
            ticker = trade['ticker']
            is_winner = trade['pnl_dollars'] > 0

            if ticker not in self.ticker_stats:
                self.ticker_stats[ticker] = {
                    'trades': 0,
                    'wins': 0,
                    'losses': 0,
                    'win_rate': 0.0,
                    'recent_trades': []
                }

            self.ticker_stats[ticker]['trades'] += 1

            if is_winner:
                self.ticker_stats[ticker]['wins'] += 1
            else:
                self.ticker_stats[ticker]['losses'] += 1

            # Store recent trades for rolling window
            self.ticker_stats[ticker]['recent_trades'].append(is_winner)
            if len(self.ticker_stats[ticker]['recent_trades']) > 20:
                self.ticker_stats[ticker]['recent_trades'].pop(0)

            # Calculate win rate
            total = self.ticker_stats[ticker]['trades']
            wins = self.ticker_stats[ticker]['wins']
            self.ticker_stats[ticker]['win_rate'] = (wins / total * 100) if total > 0 else 0

    def calculate_rolling_window_wr(self, ticker):
        """Calculate win rate for last N trades"""
        if ticker not in self.ticker_stats:
            return None

        recent = self.ticker_stats[ticker]['recent_trades']
        if len(recent) < AwardConfig.ROLLING_WINDOW_SIZE:
            return None

        last_n = recent[-AwardConfig.ROLLING_WINDOW_SIZE:]
        wins = sum(1 for trade in last_n if trade)
        wr = (wins / len(last_n) * 100) if last_n else 0

        return wr

    def calculate_award(self, ticker, total_system_trades):
        """Calculate award for a ticker based on performance"""
        if ticker not in self.ticker_stats:
            return 'trial'

        stats = self.ticker_stats[ticker]
        trades = stats['trades']
        wr = stats['win_rate']

        # Check if blacklisted
        if self.blacklist and self.blacklist.is_blacklisted(ticker):
            return 'frozen'

        # Death row check
        if trades >= AwardConfig.DEATH_ROW_MIN_TRADES and wr < AwardConfig.DEATH_ROW_WIN_RATE:
            return 'frozen'

        # Trial period
        if trades < AwardConfig.TRIAL_TRADE_COUNT:
            return 'trial'

        # Removal check for established tickers
        if trades >= AwardConfig.ROLLING_WINDOW_THRESHOLD:
            rolling_wr = self.calculate_rolling_window_wr(ticker)

            if rolling_wr is not None and rolling_wr < AwardConfig.ROLLING_WINDOW_WR:
                return 'none'

        # Calculate minimum trade requirements
        if total_system_trades >= AwardConfig.SCALING_START_TRADES:
            num_tickers = len(self.ticker_stats) if self.ticker_stats else 1
            avg_per_ticker = total_system_trades / num_tickers

            standard_min = max(
                AwardConfig.STANDARD_MIN_TRADES,
                avg_per_ticker * AwardConfig.STANDARD_VOLUME_RATIO
            )
            premium_min = max(
                AwardConfig.PREMIUM_MIN_TRADES,
                avg_per_ticker * AwardConfig.PREMIUM_VOLUME_RATIO
            )
        else:
            standard_min = AwardConfig.STANDARD_MIN_TRADES
            premium_min = AwardConfig.PREMIUM_MIN_TRADES

        # Award qualification
        if trades >= premium_min and wr >= AwardConfig.PREMIUM_WIN_RATE:
            return 'premium'

        if trades >= standard_min and wr >= AwardConfig.STANDARD_WIN_RATE:
            return 'standard'

        return 'none'

    def get_award_multiplier(self, ticker):
        """Get position size multiplier based on award"""
        award = self.ticker_awards.get(ticker, 'trial')

        multipliers = {
            'premium': AwardConfig.PREMIUM_MULTIPLIER,
            'standard': AwardConfig.STANDARD_MULTIPLIER,
            'trial': AwardConfig.TRIAL_MULTIPLIER,
            'none': AwardConfig.NO_AWARD_MULTIPLIER,
            'frozen': AwardConfig.FROZEN_MULTIPLIER
        }

        return multipliers.get(award, AwardConfig.NO_AWARD_MULTIPLIER)

    def rotate_stocks(self, strategy, all_candidates, current_date, all_stock_data):
        """Perform weekly award evaluation"""
        if not all_candidates:
            return []

        print(f"\n{'=' * 80}")
        print(f"🏆 AWARD EVALUATION - {current_date.strftime('%Y-%m-%d')}")
        print(f"{'=' * 80}")

        # Update statistics from profit tracker
        self.update_ticker_stats_from_tracker()

        # Calculate total system trades
        total_system_trades = sum(stats['trades'] for stats in self.ticker_stats.values())

        # Track award changes
        previous_awards = dict(self.ticker_awards)
        award_changes = {
            'promoted': [],
            'demoted': [],
            'new_awards': [],
            'removed': []
        }

        # Evaluate each ticker
        for ticker in all_candidates:
            new_award = self.calculate_award(ticker, total_system_trades)
            old_award = previous_awards.get(ticker, 'trial')

            self.ticker_awards[ticker] = new_award

            # Track changes
            award_hierarchy = {'frozen': 0, 'none': 1, 'trial': 2, 'standard': 3, 'premium': 4}

            if ticker not in previous_awards:
                if new_award not in ['trial', 'none']:
                    award_changes['new_awards'].append((ticker, new_award))
            elif award_hierarchy.get(new_award, 0) > award_hierarchy.get(old_award, 0):
                award_changes['promoted'].append((ticker, old_award, new_award))
            elif award_hierarchy.get(new_award, 0) < award_hierarchy.get(old_award, 0):
                award_changes['demoted'].append((ticker, old_award, new_award))

        # Display summary
        self._display_award_summary(total_system_trades, award_changes)

        # Update state
        self.active_tickers = all_candidates
        self.last_rotation_date = current_date
        self.rotation_count += 1

        return all_candidates

    def _display_award_summary(self, total_system_trades, award_changes):
        """Display award evaluation summary"""
        # Calculate scaling requirements
        if total_system_trades >= AwardConfig.SCALING_START_TRADES:
            num_tickers = len(self.ticker_stats) if self.ticker_stats else 1
            avg_per_ticker = total_system_trades / num_tickers
            standard_min = max(
                AwardConfig.STANDARD_MIN_TRADES,
                avg_per_ticker * AwardConfig.STANDARD_VOLUME_RATIO
            )
            premium_min = max(
                AwardConfig.PREMIUM_MIN_TRADES,
                avg_per_ticker * AwardConfig.PREMIUM_VOLUME_RATIO
            )
        else:
            standard_min = AwardConfig.STANDARD_MIN_TRADES
            premium_min = AwardConfig.PREMIUM_MIN_TRADES

        print(f"\n📊 System Status: {total_system_trades} total trades")
        print(f"   Standard requires: {standard_min:.0f} trades, {AwardConfig.STANDARD_WIN_RATE:.0f}% WR")
        print(f"   Premium requires: {premium_min:.0f} trades, {AwardConfig.PREMIUM_WIN_RATE:.0f}% WR")

        # Count awards
        award_counts = {
            'premium': 0,
            'standard': 0,
            'trial': 0,
            'none': 0,
            'frozen': 0
        }

        for award in self.ticker_awards.values():
            award_counts[award] = award_counts.get(award, 0) + 1

        print(f"\n🏆 Award Distribution:")
        print(f"   Premium ({AwardConfig.PREMIUM_MULTIPLIER}x):  {award_counts['premium']} tickers")
        print(f"   Standard ({AwardConfig.STANDARD_MULTIPLIER}x): {award_counts['standard']} tickers")
        print(f"   Trial ({AwardConfig.TRIAL_MULTIPLIER}x):    {award_counts['trial']} tickers")
        print(f"   None ({AwardConfig.NO_AWARD_MULTIPLIER}x):     {award_counts['none']} tickers")
        print(f"   Frozen ({AwardConfig.FROZEN_MULTIPLIER}x):   {award_counts['frozen']} tickers")

        # Display changes
        if award_changes['promoted']:
            print(f"\n⬆️  PROMOTIONS:")
            for ticker, old, new in award_changes['promoted']:
                print(f"   {ticker}: {old} → {new}")

        if award_changes['demoted']:
            print(f"\n⬇️  DEMOTIONS:")
            for ticker, old, new in award_changes['demoted']:
                print(f"   {ticker}: {old} → {new}")

        if award_changes['new_awards']:
            print(f"\n✨ NEW AWARDS:")
            for ticker, award in award_changes['new_awards']:
                print(f"   {ticker}: {award}")

        # Display ticker details
        # print(f"\n{'─' * 80}")
        # print(f"{'Ticker':<8} {'Award':<10} {'Trades':<8} {'WR':<8} {'Recent':<10} {'Multiplier'}")
        # print(f"{'─' * 80}")

        tier_order = {'premium': 0, 'standard': 1, 'trial': 2, 'none': 3, 'frozen': 4}
        sorted_tickers = sorted(
            self.ticker_awards.items(),
            key=lambda x: (tier_order.get(x[1], 5), x[0])
        )
        '''
        for ticker, award in sorted_tickers:
            if ticker in self.ticker_stats:
                stats = self.ticker_stats[ticker]
                trades = stats['trades']
                wr = stats['win_rate']

                rolling_wr = self.calculate_rolling_window_wr(ticker)
                recent_str = f"{rolling_wr:.0f}%" if rolling_wr is not None else "N/A"

                multiplier = self.get_award_multiplier(ticker)

                award_emoji = {
                    'premium': '🥇',
                    'standard': '🥈',
                    'trial': '🔬',
                    'none': '⚪',
                    'frozen': '❄️'
                }.get(award, '❓')

                print(f"{ticker:<8} {award_emoji} {award:<8} {trades:<8} {wr:>5.1f}%  {recent_str:<10} {multiplier}x")
            else:
                print(f"{ticker:<8} 🔬 trial     0        N/A    N/A        {AwardConfig.TRIAL_MULTIPLIER}x")
        '''
        # print(f"{'─' * 80}\n")


    def get_award(self, ticker):
        """Get current award for a ticker"""
        return self.ticker_awards.get(ticker, 'trial')

    def get_rotation_summary(self):
        """Get summary statistics about rotation"""
        award_counts = {}
        for award in self.ticker_awards.values():
            award_counts[award] = award_counts.get(award, 0) + 1

        return {
            'rotation_count': self.rotation_count,
            'last_rotation': self.last_rotation_date,
            'active_count': len(self.active_tickers),
            'active_tickers': self.active_tickers,
            'award_distribution': award_counts,
            'total_tracked': len(self.ticker_awards)
        }


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def print_rotation_report(rotator):
    """Print detailed rotation report including blacklist stats"""
    summary = rotator.get_rotation_summary()

    print(f"\n{'=' * 80}")
    print(f"🏆 AWARD-BASED ROTATION SUMMARY")
    print(f"{'=' * 80}")
    print(f"Total Rotations: {summary['rotation_count']}")
    print(f"Last Rotation: {summary['last_rotation']}")
    print(f"Active Stocks: {summary['active_count']} (all tradeable)")
    print(f"Total Stocks Tracked: {summary['total_tracked']}")

    award_dist = summary['award_distribution']
    print(f"\n🏆 Award Distribution:")
    for award, count in sorted(award_dist.items()):
        multiplier = {
            'premium': AwardConfig.PREMIUM_MULTIPLIER,
            'standard': AwardConfig.STANDARD_MULTIPLIER,
            'trial': AwardConfig.TRIAL_MULTIPLIER,
            'none': AwardConfig.NO_AWARD_MULTIPLIER,
            'frozen': AwardConfig.FROZEN_MULTIPLIER
        }.get(award, 1.0)

        emoji = {
            'premium': '🥇',
            'standard': '🥈',
            'trial': '🔬',
            'none': '⚪',
            'frozen': '❄️'
        }.get(award, '❓')

        print(f"   {emoji} {award.title()}: {count} tickers ({multiplier}x)")

    # List tickers by award
    print(f"\n📋 Tickers by Award:")

    tickers_by_award = {}
    for ticker, award in rotator.ticker_awards.items():
        if award not in tickers_by_award:
            tickers_by_award[award] = []
        tickers_by_award[award].append(ticker)

    for award in ['premium', 'standard', 'trial', 'none', 'frozen']:
        if award in tickers_by_award:
            tickers = sorted(tickers_by_award[award])
            preview = tickers[:10]
            suffix = f" ... (+{len(tickers) - 10} more)" if len(tickers) > 10 else ""
            print(f"   {award.title()}: {', '.join(preview)}{suffix}")

    print(f"{'=' * 80}\n")

    # Display blacklist stats
    if rotator.blacklist:
        blacklist_stats = rotator.blacklist.get_statistics()
        print(f"{'=' * 80}")
        print(f"⛔ TICKER BLACKLIST SUMMARY ({blacklist_stats['strategy']})")
        print(f"{'=' * 80}")
        if blacklist_stats['permanent_blacklist']:
            print(f"Permanent Blacklist: {', '.join(blacklist_stats['permanent_blacklist'])}")
        else:
            print(f"Permanent Blacklist: None")

        if blacklist_stats['temp_blacklist_tickers']:
            print(f"Temporary Blacklist: {', '.join(blacklist_stats['temp_blacklist_tickers'])}")
        else:
            print(f"Temporary Blacklist: None")

        if blacklist_stats['tickers_with_consecutive_losses']:
            print(f"\nTickers with Consecutive Losses:")
            for ticker, count in blacklist_stats['tickers_with_consecutive_losses'].items():
                print(f"   {ticker}: {count} loss(es)")
        print(f"{'=' * 80}\n")