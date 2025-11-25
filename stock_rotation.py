"""
Stock Rotation System - STREAMLINED VERSION

Reduced logging - only summary at end of rotation
"""

from datetime import datetime
from config import Config


class RotationConfig:
    """Rotation configuration"""
    PREMIUM_WIN_RATE = 70.0
    PREMIUM_MIN_TRADES = 10
    STANDARD_WIN_RATE = 55.0
    STANDARD_MIN_TRADES = 7
    FROZEN_WIN_RATE = 40.0
    FROZEN_MIN_TRADES = 7
    PREMIUM_MULTIPLIER = 1.5
    STANDARD_MULTIPLIER = 1.0
    FROZEN_MULTIPLIER = 0.0
    RECOVERY_CONSECUTIVE_PASSES = 3


class StockRotator:
    """Stock rotation system"""

    def __init__(self, profit_tracker=None):
        self.profit_tracker = profit_tracker
        self.ticker_awards = {}
        self.recovery_tracking = {}
        self.last_rotation_date = None
        self.rotation_count = 0

    def evaluate_stocks(self, tickers, current_date):
        """Evaluate all stocks and update awards"""
        if not self.profit_tracker:
            return

        ticker_stats = self._build_performance_stats()
        changes = []

        for ticker in tickers:
            old_award = self.ticker_awards.get(ticker, 'standard')
            new_award = self._evaluate_ticker(ticker, ticker_stats)
            if old_award != new_award:
                changes.append((ticker, old_award, new_award))

        # Compact summary
        if changes:
            print(f"\n🏆 ROTATION [{current_date.strftime('%Y-%m-%d')}]: {len(changes)} changes")
            for ticker, old, new in changes[:5]:  # Show max 5
                print(f"   {ticker}: {old} → {new}")
            if len(changes) > 5:
                print(f"   ... and {len(changes) - 5} more")

        self.last_rotation_date = current_date
        self.rotation_count += 1

    def _build_performance_stats(self):
        stats = {}
        all_trades = self.profit_tracker.get_closed_trades()

        for trade in all_trades:
            ticker = trade['ticker']
            if ticker not in stats:
                stats[ticker] = {'trades': 0, 'wins': 0, 'total_pnl': 0.0}

            stats[ticker]['trades'] += 1
            if trade['pnl_dollars'] > 0:
                stats[ticker]['wins'] += 1
            stats[ticker]['total_pnl'] += trade['pnl_dollars']

        for ticker in stats:
            trades = stats[ticker]['trades']
            wins = stats[ticker]['wins']
            stats[ticker]['win_rate'] = (wins / trades * 100) if trades > 0 else 0.0

        return stats

    def _evaluate_ticker(self, ticker, ticker_stats):
        current_award = self.ticker_awards.get(ticker, 'standard')
        stats = ticker_stats.get(ticker)

        if not stats or stats['trades'] == 0:
            self.ticker_awards[ticker] = 'standard'
            return 'standard'

        trades = stats['trades']
        win_rate = stats['win_rate']

        # Frozen check
        if trades >= RotationConfig.FROZEN_MIN_TRADES and win_rate < RotationConfig.FROZEN_WIN_RATE:
            if current_award == 'frozen':
                recovery_award = self._check_recovery(ticker, win_rate, trades)
                if recovery_award:
                    self.ticker_awards[ticker] = recovery_award
                    return recovery_award

            self.ticker_awards[ticker] = 'frozen'
            self.recovery_tracking[ticker] = 0
            return 'frozen'

        # Premium check
        if trades >= RotationConfig.PREMIUM_MIN_TRADES and win_rate >= RotationConfig.PREMIUM_WIN_RATE:
            self.ticker_awards[ticker] = 'premium'
            self.recovery_tracking.pop(ticker, None)
            return 'premium'

        # Standard check
        if trades >= RotationConfig.STANDARD_MIN_TRADES and win_rate >= RotationConfig.STANDARD_WIN_RATE:
            self.ticker_awards[ticker] = 'standard'
            self.recovery_tracking.pop(ticker, None)
            return 'standard'

        self.ticker_awards[ticker] = 'standard'
        self.recovery_tracking.pop(ticker, None)
        return 'standard'

    def _check_recovery(self, ticker, win_rate, trades):
        meets_standard = (
                trades >= RotationConfig.STANDARD_MIN_TRADES and
                win_rate >= RotationConfig.STANDARD_WIN_RATE
        )

        if meets_standard:
            current_passes = self.recovery_tracking.get(ticker, 0)
            self.recovery_tracking[ticker] = current_passes + 1

            if self.recovery_tracking[ticker] >= RotationConfig.RECOVERY_CONSECUTIVE_PASSES:
                self.recovery_tracking.pop(ticker, None)
                return 'standard'
        else:
            self.recovery_tracking[ticker] = 0

        return None

    def get_award(self, ticker):
        return self.ticker_awards.get(ticker, 'standard')

    def get_multiplier(self, ticker):
        award = self.get_award(ticker)
        return {
            'premium': RotationConfig.PREMIUM_MULTIPLIER,
            'standard': RotationConfig.STANDARD_MULTIPLIER,
            'frozen': RotationConfig.FROZEN_MULTIPLIER
        }.get(award, RotationConfig.STANDARD_MULTIPLIER)

    def is_tradeable(self, ticker):
        return self.get_award(ticker) != 'frozen'

    def get_statistics(self):
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


def should_rotate(rotator, current_date, frequency='weekly'):
    """Check if rotation should run"""
    if rotator.last_rotation_date is None:
        return True

    days_since = (current_date - rotator.last_rotation_date).days
    thresholds = {'daily': 1, 'weekly': 7, 'monthly': 30}
    return days_since >= thresholds.get(frequency, 7)


def print_rotation_report(rotator):
    """Print rotation report - compact version"""
    stats = rotator.get_statistics()
    dist = stats['award_distribution']

    print(f"\n🏆 Rotation: {stats['rotation_count']} total | "
          f"🥇{dist.get('premium', 0)} 🥈{dist.get('standard', 0)} ❄️{dist.get('frozen', 0)}")

    if stats['frozen_stocks']:
        print(f"   Frozen: {', '.join(stats['frozen_stocks'][:5])}")