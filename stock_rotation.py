"""
Stock Rotation System - MINIMAL & FOCUSED

CORE PRINCIPLES:
1. Always analyze all stocks (never skip analysis)
2. Only block trading when frozen
3. Monitor frozen stocks for recovery (3 consecutive passes → upgrade)
4. Simple tier system: premium (1.5x) / standard (1.0x) / frozen (0.0x = blocked)

RECOVERY MECHANISM:
- Frozen stocks are still analyzed every rotation
- If meets standard requirements (55% WR, 5+ trades) for 3 consecutive evaluations → unfreeze
- Counts EVALUATIONS not actual trades (stock doesn't need to trade to recover)
"""

from datetime import datetime
from config import Config


# =============================================================================
# CONFIGURATION
# =============================================================================

class RotationConfig:
    """Simple rotation configuration"""

    # Award thresholds
    PREMIUM_WIN_RATE = 70.0
    PREMIUM_MIN_TRADES = 10

    STANDARD_WIN_RATE = 55.0
    STANDARD_MIN_TRADES = 7

    FROZEN_WIN_RATE = 40.0  # Below this after 10+ trades = frozen
    FROZEN_MIN_TRADES = 7

    # Position size multipliers
    PREMIUM_MULTIPLIER = 1.5
    STANDARD_MULTIPLIER = 1.0
    FROZEN_MULTIPLIER = 0.0  # Blocked from trading

    # Recovery settings
    RECOVERY_CONSECUTIVE_PASSES = 3  # Need 3 evaluations meeting standard to unfreeze


# =============================================================================
# STOCK ROTATOR
# =============================================================================

class StockRotator:
    """
    Minimal stock rotation system

    Responsibilities:
    1. Track stock performance (win rate, trade count)
    2. Assign awards (premium/standard/frozen)
    3. Monitor frozen stocks for recovery
    4. Block trading for frozen stocks only
    """

    def __init__(self, profit_tracker=None):
        self.profit_tracker = profit_tracker

        # Current awards: {ticker: 'premium'/'standard'/'frozen'}
        self.ticker_awards = {}

        # Recovery tracking: {ticker: consecutive_passes}
        # Tracks how many consecutive evaluations a frozen stock has passed
        self.recovery_tracking = {}

        # Rotation metadata
        self.last_rotation_date = None
        self.rotation_count = 0

    def evaluate_stocks(self, tickers, current_date):
        """
        Evaluate all stocks and update awards

        Called weekly to update stock awards based on performance

        Args:
            tickers: List of all tickers to evaluate
            current_date: Current datetime
        """

        if not self.profit_tracker:
            print("[WARN] No profit tracker - skipping rotation")
            return

        print(f"\n{'=' * 80}")
        print(f"🏆 STOCK ROTATION - {current_date.strftime('%Y-%m-%d')}")
        print(f"{'=' * 80}\n")

        # Build performance stats from closed trades
        ticker_stats = self._build_performance_stats()

        # Evaluate each ticker
        changes = []
        for ticker in tickers:
            old_award = self.ticker_awards.get(ticker, 'standard')
            new_award = self._evaluate_ticker(ticker, ticker_stats)

            if old_award != new_award:
                changes.append((ticker, old_award, new_award, ticker_stats.get(ticker)))

        # Display changes
        if changes:
            print(f"📊 AWARD CHANGES:")
            for ticker, old, new, stats in changes:
                self._display_change(ticker, old, new, stats)
        else:
            print(f"📊 No award changes this rotation")

        # Display summary
        self._display_summary()

        # Update metadata
        self.last_rotation_date = current_date
        self.rotation_count += 1

        print(f"{'=' * 80}\n")

    def _build_performance_stats(self):
        """Build performance statistics from profit tracker"""

        stats = {}
        all_trades = self.profit_tracker.get_closed_trades()

        for trade in all_trades:
            ticker = trade['ticker']

            if ticker not in stats:
                stats[ticker] = {
                    'trades': 0,
                    'wins': 0,
                    'total_pnl': 0.0
                }

            stats[ticker]['trades'] += 1
            if trade['pnl_dollars'] > 0:
                stats[ticker]['wins'] += 1
            stats[ticker]['total_pnl'] += trade['pnl_dollars']

        # Calculate win rates
        for ticker in stats:
            trades = stats[ticker]['trades']
            wins = stats[ticker]['wins']
            stats[ticker]['win_rate'] = (wins / trades * 100) if trades > 0 else 0.0

        return stats

    def _evaluate_ticker(self, ticker, ticker_stats):
        """
        Evaluate single ticker and assign award

        Logic:
        1. No history → standard (new stock, give it a chance)
        2. Poor performance (< 30% WR after 10+ trades) → frozen (block trading)
        3. Excellent performance (65%+ WR, 8+ trades) → premium (1.5x size)
        4. Good performance (55%+ WR, 5+ trades) → standard (1.0x size)
        5. Default → standard

        For frozen stocks:
        - Check if currently meets standard requirements
        - Track consecutive passes
        - After 3 consecutive passes → upgrade to standard
        """

        current_award = self.ticker_awards.get(ticker, 'standard')
        stats = ticker_stats.get(ticker)

        # No history → standard (give new stocks a chance)
        if not stats or stats['trades'] == 0:
            self.ticker_awards[ticker] = 'standard'
            return 'standard'

        trades = stats['trades']
        win_rate = stats['win_rate']

        # Check for frozen (poor performance)
        if trades >= RotationConfig.FROZEN_MIN_TRADES and win_rate < RotationConfig.FROZEN_WIN_RATE:

            # If already frozen, check for recovery
            if current_award == 'frozen':
                recovery_award = self._check_recovery(ticker, win_rate, trades)
                if recovery_award:
                    self.ticker_awards[ticker] = recovery_award
                    return recovery_award

            self.ticker_awards[ticker] = 'frozen'
            self.recovery_tracking[ticker] = 0  # Reset recovery counter
            return 'frozen'

        # Check for premium
        if trades >= RotationConfig.PREMIUM_MIN_TRADES and win_rate >= RotationConfig.PREMIUM_WIN_RATE:
            self.ticker_awards[ticker] = 'premium'
            self.recovery_tracking.pop(ticker, None)  # Clear recovery tracking
            return 'premium'

        # Check for standard
        if trades >= RotationConfig.STANDARD_MIN_TRADES and win_rate >= RotationConfig.STANDARD_WIN_RATE:
            self.ticker_awards[ticker] = 'standard'
            self.recovery_tracking.pop(ticker, None)  # Clear recovery tracking
            return 'standard'

        # Default to standard
        self.ticker_awards[ticker] = 'standard'
        self.recovery_tracking.pop(ticker, None)  # Clear recovery tracking
        return 'standard'

    def _check_recovery(self, ticker, win_rate, trades):
        """
        Check if frozen stock qualifies for recovery

        Recovery requires:
        - Win rate >= 55% (standard threshold)
        - Trades >= 5 (standard minimum)
        - 3 consecutive evaluations meeting these requirements

        This checks EVALUATIONS, not actual trades. The stock doesn't need
        to trade to recover - it just needs to have the right stats for
        3 consecutive rotation evaluations.

        Returns:
            str: 'standard' if recovered, None otherwise
        """

        # Check if meets standard requirements
        meets_standard = (
                trades >= RotationConfig.STANDARD_MIN_TRADES and
                win_rate >= RotationConfig.STANDARD_WIN_RATE
        )

        if meets_standard:
            # Increment consecutive passes
            current_passes = self.recovery_tracking.get(ticker, 0)
            self.recovery_tracking[ticker] = current_passes + 1

            # Check if recovered
            if self.recovery_tracking[ticker] >= RotationConfig.RECOVERY_CONSECUTIVE_PASSES:
                print(f"   ✨ {ticker}: UNFROZEN → standard")
                print(f"      Passed {RotationConfig.RECOVERY_CONSECUTIVE_PASSES} consecutive evaluations")
                print(f"      Win rate: {win_rate:.1f}%, Trades: {trades}")
                self.recovery_tracking.pop(ticker, None)
                return 'standard'
            else:
                remaining = RotationConfig.RECOVERY_CONSECUTIVE_PASSES - self.recovery_tracking[ticker]
                print(
                    f"   🔄 {ticker}: Recovery progress {self.recovery_tracking[ticker]}/{RotationConfig.RECOVERY_CONSECUTIVE_PASSES} ({remaining} more needed)")
        else:
            # Reset counter if doesn't meet requirements
            self.recovery_tracking[ticker] = 0

        return None

    def _display_change(self, ticker, old_award, new_award, stats):
        """Display award change"""

        if stats:
            info = f"WR: {stats['win_rate']:.1f}%, Trades: {stats['trades']}, P&L: ${stats['total_pnl']:+,.0f}"
        else:
            info = "No trades yet"

        emoji_map = {
            'premium': '🥇',
            'standard': '🥈',
            'frozen': '❄️'
        }

        old_emoji = emoji_map.get(old_award, '❓')
        new_emoji = emoji_map.get(new_award, '❓')

        print(f"   {old_emoji} {ticker}: {old_award} → {new_emoji} {new_award}")
        print(f"      {info}")

    def _display_summary(self):
        """Display rotation summary"""

        # Count awards
        award_counts = {'premium': 0, 'standard': 0, 'frozen': 0}
        for award in self.ticker_awards.values():
            award_counts[award] = award_counts.get(award, 0) + 1

        print(f"\n{'─' * 80}")
        print(f"📈 AWARD DISTRIBUTION:")
        print(f"   🥇 Premium ({RotationConfig.PREMIUM_MULTIPLIER}x): {award_counts['premium']} stocks")
        print(f"   🥈 Standard ({RotationConfig.STANDARD_MULTIPLIER}x): {award_counts['standard']} stocks")
        print(f"   ❄️  Frozen (BLOCKED): {award_counts['frozen']} stocks")

        # Show recovery progress
        if self.recovery_tracking:
            print(f"\n🔄 RECOVERY TRACKING:")
            for ticker, passes in sorted(self.recovery_tracking.items()):
                remaining = RotationConfig.RECOVERY_CONSECUTIVE_PASSES - passes
                print(
                    f"   {ticker}: {passes}/{RotationConfig.RECOVERY_CONSECUTIVE_PASSES} evaluations passed ({remaining} more needed)")

        print(f"{'─' * 80}")

    def get_award(self, ticker):
        """Get current award for ticker (default: standard)"""
        return self.ticker_awards.get(ticker, 'standard')

    def get_multiplier(self, ticker):
        """
        Get position size multiplier for ticker

        Returns:
            float: 0.0 (frozen/blocked), 1.0 (standard), or 1.5 (premium)
        """
        award = self.get_award(ticker)

        multipliers = {
            'premium': RotationConfig.PREMIUM_MULTIPLIER,
            'standard': RotationConfig.STANDARD_MULTIPLIER,
            'frozen': RotationConfig.FROZEN_MULTIPLIER
        }

        return multipliers.get(award, RotationConfig.STANDARD_MULTIPLIER)

    def is_tradeable(self, ticker):
        """
        Check if ticker is allowed to trade

        Returns:
            bool: True if tradeable, False if frozen
        """
        return self.get_award(ticker) != 'frozen'

    def get_statistics(self):
        """Get rotation statistics for reporting"""

        award_counts = {}
        for award in self.ticker_awards.values():
            award_counts[award] = award_counts.get(award, 0) + 1

        return {
            'rotation_count': self.rotation_count,
            'last_rotation_date': self.last_rotation_date,
            'total_tracked': len(self.ticker_awards),
            'award_distribution': award_counts,
            'recovery_tracking': dict(self.recovery_tracking),
            'frozen_stocks': [t for t, a in self.ticker_awards.items() if a == 'frozen']
        }


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def should_rotate(rotator, current_date, frequency='weekly'):
    """
    Check if rotation should run

    Args:
        rotator: StockRotator instance
        current_date: Current datetime
        frequency: 'daily', 'weekly', 'monthly'

    Returns:
        bool: True if should rotate
    """

    if rotator.last_rotation_date is None:
        return True

    days_since = (current_date - rotator.last_rotation_date).days

    thresholds = {
        'daily': 1,
        'weekly': 7,
        'monthly': 30
    }

    return days_since >= thresholds.get(frequency, 7)


def print_rotation_report(rotator):
    """Print detailed rotation report"""

    stats = rotator.get_statistics()

    print(f"\n{'=' * 80}")
    print(f"🏆 ROTATION SYSTEM SUMMARY")
    print(f"{'=' * 80}")
    print(f"Total Rotations: {stats['rotation_count']}")
    print(f"Last Rotation: {stats['last_rotation_date']}")
    print(f"Stocks Tracked: {stats['total_tracked']}")

    print(f"\n📊 Award Distribution:")
    dist = stats['award_distribution']
    print(f"   🥇 Premium: {dist.get('premium', 0)}")
    print(f"   🥈 Standard: {dist.get('standard', 0)}")
    print(f"   ❄️  Frozen: {dist.get('frozen', 0)}")

    if stats['frozen_stocks']:
        print(f"\n❄️  Frozen Stocks: {', '.join(stats['frozen_stocks'])}")

    if stats['recovery_tracking']:
        print(f"\n🔄 Recovery Progress:")
        for ticker, passes in stats['recovery_tracking'].items():
            remaining = RotationConfig.RECOVERY_CONSECUTIVE_PASSES - passes
            print(f"   {ticker}: {passes}/{RotationConfig.RECOVERY_CONSECUTIVE_PASSES} ({remaining} more)")

    print(f"{'=' * 80}\n")