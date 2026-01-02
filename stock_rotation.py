"""
Stock Rotation System - STREAK-BASED TIERS WITH RECOVERY PATH

Tier Structure:
- Premium (1.5x):  Strong performers - PF ≥ 2.0, WR ≥ 70%, 7+ trades, positive P&L
- Active (1.0x):   Default state
- Probation (0.5x): Underperforming - 2 consecutive losses OR (3+ trades, negative P&L, <50% WR)
- Frozen (0.1x):   Poor performers - 2 consecutive losses while on Probation
- Rehabilitation (0.25x): Recovery path - 2 consecutive wins while Frozen

Philosophy: "Innocent until proven guilty" - Every ticker starts Active.
The system demotes poor performers and provides a path back.
"""

from datetime import datetime
from config import Config


class RotationConfig:
    """Rotation configuration"""

    # Premium requirements (reward strong performers)
    PREMIUM_WIN_RATE = 70.0
    PREMIUM_MIN_TRADES = 7
    PREMIUM_MIN_PROFIT_FACTOR = 2.0

    # Probation triggers
    PROBATION_CONSECUTIVE_LOSSES = 2
    PROBATION_MIN_TRADES = 3
    PROBATION_MAX_WIN_RATE = 50.0

    # Frozen trigger (from Probation)
    FROZEN_CONSECUTIVE_LOSSES = 2  # While on Probation

    # Recovery requirements
    REHAB_CONSECUTIVE_WINS = 2  # While Frozen → Rehabilitation
    REHAB_TO_PROBATION_WINS = 1  # Rehabilitation win → Probation
    PROBATION_TO_ACTIVE_WINS = 2  # Probation → Active

    # Position size multipliers
    MULTIPLIERS = {
        'premium': 1.25,  # 1.5
        'active': 1.0,  # 1.0
        'probation': 1.0,  # 0.5
        'rehabilitation': 0.75,  # 0.25
        'frozen': 0.5  # 0.1
    }


class TickerState:
    """Tracks individual ticker rotation state"""

    def __init__(self, ticker):
        self.ticker = ticker
        self.tier = 'active'
        self.consecutive_wins = 0
        self.consecutive_losses = 0
        self.total_trades = 0
        self.total_wins = 0
        self.total_pnl = 0.0
        self.total_win_pnl = 0.0
        self.total_loss_pnl = 0.0
        self.last_tier_change = None
        self.tier_history = []  # [(date, old_tier, new_tier, reason)]

    def record_trade(self, pnl_dollars, trade_date=None):
        """Record a completed trade and update streaks"""
        self.total_trades += 1
        self.total_pnl += pnl_dollars

        if pnl_dollars > 0:
            self.total_wins += 1
            self.total_win_pnl += pnl_dollars
            self.consecutive_wins += 1
            self.consecutive_losses = 0
        elif pnl_dollars < 0:
            self.total_loss_pnl += abs(pnl_dollars)
            self.consecutive_losses += 1
            self.consecutive_wins = 0
        # Breakeven: reset both streaks
        else:
            self.consecutive_wins = 0
            self.consecutive_losses = 0

    def get_win_rate(self):
        """Calculate win rate percentage"""
        if self.total_trades == 0:
            return 0.0
        return (self.total_wins / self.total_trades) * 100

    def get_profit_factor(self):
        """Calculate profit factor (gross wins / gross losses)"""
        if self.total_loss_pnl == 0:
            return float('inf') if self.total_win_pnl > 0 else 0.0
        return self.total_win_pnl / self.total_loss_pnl

    def change_tier(self, new_tier, reason, date=None):
        """Change tier and record history"""
        if new_tier == self.tier:
            return False

        old_tier = self.tier
        self.tier = new_tier
        self.last_tier_change = date or datetime.now()

        self.tier_history.append({
            'date': self.last_tier_change,
            'old_tier': old_tier,
            'new_tier': new_tier,
            'reason': reason
        })

        # Reset streaks on tier change (fresh start in new tier)
        if new_tier in ['probation', 'frozen', 'rehabilitation']:
            self.consecutive_wins = 0
            self.consecutive_losses = 0

        return True

    def to_dict(self):
        """Serialize state for persistence"""
        return {
            'ticker': self.ticker,
            'tier': self.tier,
            'consecutive_wins': self.consecutive_wins,
            'consecutive_losses': self.consecutive_losses,
            'total_trades': self.total_trades,
            'total_wins': self.total_wins,
            'total_pnl': self.total_pnl,
            'total_win_pnl': self.total_win_pnl,
            'total_loss_pnl': self.total_loss_pnl,
            'last_tier_change': self.last_tier_change.isoformat() if self.last_tier_change else None
        }

    @classmethod
    def from_dict(cls, data):
        """Deserialize state from persistence"""
        state = cls(data['ticker'])
        state.tier = data.get('tier', 'active')
        state.consecutive_wins = data.get('consecutive_wins', 0)
        state.consecutive_losses = data.get('consecutive_losses', 0)
        state.total_trades = data.get('total_trades', 0)
        state.total_wins = data.get('total_wins', 0)
        state.total_pnl = data.get('total_pnl', 0.0)
        state.total_win_pnl = data.get('total_win_pnl', 0.0)
        state.total_loss_pnl = data.get('total_loss_pnl', 0.0)

        if data.get('last_tier_change'):
            try:
                state.last_tier_change = datetime.fromisoformat(data['last_tier_change'])
            except:
                state.last_tier_change = None

        return state


class StockRotator:
    """
    Stock rotation system with streak-based tier management

    Key behaviors:
    - All tickers start at 'active' (1.0x)
    - Trades update streaks immediately (not weekly)
    - Tier evaluation happens after each trade
    - Frozen stocks still trade at 0.1x (no shadow trading)
    """

    def __init__(self, profit_tracker=None):
        self.profit_tracker = profit_tracker
        self.ticker_states = {}  # {ticker: TickerState}
        self.last_rotation_date = None
        self.rotation_count = 0

    def get_or_create_state(self, ticker):
        """Get existing state or create new one"""
        if ticker not in self.ticker_states:
            self.ticker_states[ticker] = TickerState(ticker)
        return self.ticker_states[ticker]

    def record_trade_result(self, ticker, pnl_dollars, trade_date=None):
        """
        Record a trade result and evaluate tier change

        Called by profit_tracker after each closed trade.
        This is the main entry point for the rotation system.

        Args:
            ticker: Stock symbol
            pnl_dollars: P&L in dollars (positive = win, negative = loss)
            trade_date: Date of trade (optional)

        Returns:
            dict: Tier change info if changed, None otherwise
        """
        state = self.get_or_create_state(ticker)
        old_tier = state.tier

        # Record the trade
        state.record_trade(pnl_dollars, trade_date)

        # Evaluate tier change
        tier_change = self._evaluate_tier_change(state, trade_date)

        if tier_change:
            self._log_tier_change(ticker, old_tier, state.tier, tier_change['reason'])

        return tier_change

    def _evaluate_tier_change(self, state, current_date=None):
        """
        Evaluate if ticker should change tiers based on current state

        Returns:
            dict with 'new_tier' and 'reason' if change needed, None otherwise
        """
        current_tier = state.tier
        new_tier = None
        reason = None

        # =================================================================
        # PREMIUM EVALUATION (from Active only)
        # =================================================================
        # if current_tier == 'active':
        #    if self._qualifies_for_premium(state):
        #        new_tier = 'premium'
        #        reason = f"Premium: {state.total_trades} trades, {state.get_win_rate():.0f}% WR, PF {state.get_profit_factor():.1f}"

        if current_tier == 'active':
            if self._qualifies_for_premium(state):
                new_tier = 'premium'
                reason = f"Premium: {state.total_trades} trades, {state.get_win_rate():.0f}% WR, PF {state.get_profit_factor():.1f}"
            elif self._should_demote_to_probation(state):
                new_tier = 'probation'
                reason = self._get_probation_reason(state)

        # =================================================================
        # PREMIUM DEMOTION (loses premium status)
        # =================================================================
        elif current_tier == 'premium':
            if not self._qualifies_for_premium(state):
                # Check if should go to probation or just active
                if self._should_demote_to_probation(state):
                    new_tier = 'probation'
                    reason = f"Premium → Probation: {state.consecutive_losses} consecutive losses"
                else:
                    new_tier = 'active'
                    reason = f"Lost premium: PF {state.get_profit_factor():.1f} < {RotationConfig.PREMIUM_MIN_PROFIT_FACTOR}"

        # =================================================================
        # ACTIVE → PROBATION
        # =================================================================
        # elif current_tier == 'active':
        #     if self._should_demote_to_probation(state):
        #         new_tier = 'probation'
        #         reason = self._get_probation_reason(state)

        # =================================================================
        # PROBATION TRANSITIONS
        # =================================================================
        elif current_tier == 'probation':
            # Recovery: consecutive wins → Active
            if state.consecutive_wins >= RotationConfig.PROBATION_TO_ACTIVE_WINS:
                new_tier = 'active'
                reason = f"Recovery: {state.consecutive_wins} consecutive wins"

            # Further demotion: consecutive losses → Frozen
            elif state.consecutive_losses >= RotationConfig.FROZEN_CONSECUTIVE_LOSSES:
                new_tier = 'frozen'
                reason = f"Frozen: {state.consecutive_losses} consecutive losses on Probation"

        # =================================================================
        # FROZEN → REHABILITATION
        # =================================================================
        elif current_tier == 'frozen':
            if state.consecutive_wins >= RotationConfig.REHAB_CONSECUTIVE_WINS:
                new_tier = 'rehabilitation'
                reason = f"Rehabilitation: {state.consecutive_wins} consecutive wins while Frozen"

        # =================================================================
        # REHABILITATION TRANSITIONS
        # =================================================================
        elif current_tier == 'rehabilitation':
            # Win → Probation (graduated recovery)
            if state.consecutive_wins >= RotationConfig.REHAB_TO_PROBATION_WINS:
                new_tier = 'probation'
                reason = f"Rehab success: {state.consecutive_wins} win(s) → Probation"

            # Loss → Back to Frozen
            elif state.consecutive_losses >= 1:
                new_tier = 'frozen'
                reason = f"Rehab failed: loss during rehabilitation"

        # Apply tier change if needed
        if new_tier and new_tier != current_tier:
            state.change_tier(new_tier, reason, current_date)
            return {'new_tier': new_tier, 'reason': reason}

        return None

    def _qualifies_for_premium(self, state):
        """Check if ticker qualifies for premium tier"""
        return (
                state.total_trades >= RotationConfig.PREMIUM_MIN_TRADES and
                state.get_win_rate() >= RotationConfig.PREMIUM_WIN_RATE and
                state.total_pnl > 0 and
                state.get_profit_factor() >= RotationConfig.PREMIUM_MIN_PROFIT_FACTOR
        )

    def _should_demote_to_probation(self, state):
        """Check if ticker should be demoted to probation"""
        # Trigger 1: Consecutive losses
        if state.consecutive_losses >= RotationConfig.PROBATION_CONSECUTIVE_LOSSES:
            return True

        # Trigger 2: Pattern of poor performance
        if (state.total_trades >= RotationConfig.PROBATION_MIN_TRADES and
                state.total_pnl < 0 and
                state.get_win_rate() < RotationConfig.PROBATION_MAX_WIN_RATE):
            return True

        return False

    def _get_probation_reason(self, state):
        """Get human-readable reason for probation"""
        if state.consecutive_losses >= RotationConfig.PROBATION_CONSECUTIVE_LOSSES:
            return f"Probation: {state.consecutive_losses} consecutive losses"

        return (f"Probation: {state.total_trades} trades, "
                f"{state.get_win_rate():.0f}% WR, ${state.total_pnl:+,.0f} P&L")

    def _log_tier_change(self, ticker, old_tier, new_tier, reason):
        """Log tier change"""
        emoji = {
            'premium': '🥇',
            'active': '🥈',
            'probation': '⚠️',
            'rehabilitation': '🔄',
            'frozen': '❄️'
        }

        old_emoji = emoji.get(old_tier, '❓')
        new_emoji = emoji.get(new_tier, '❓')

        print(f"   {old_emoji}→{new_emoji} {ticker}: {old_tier} → {new_tier} | {reason}")

    # =========================================================================
    # PUBLIC API (used by account_strategies.py)
    # =========================================================================

    def get_tier(self, ticker):
        """Get current tier for ticker"""
        if ticker in self.ticker_states:
            return self.ticker_states[ticker].tier
        return 'active'

    def get_award(self, ticker):
        """Alias for get_tier (backward compatibility)"""
        return self.get_tier(ticker)

    def get_multiplier(self, ticker):
        """Get position size multiplier for ticker"""
        tier = self.get_tier(ticker)
        return RotationConfig.MULTIPLIERS.get(tier, 1.0)

    def is_tradeable(self, ticker):
        """Check if ticker can be traded (all tiers are tradeable now)"""
        # All tiers trade, just at different sizes
        return True

    def evaluate_stocks(self, tickers, current_date):
        """
        Weekly evaluation - rebuild stats from profit_tracker

        This syncs rotation state with actual closed trades.
        Called weekly by account_strategies.py.
        """
        if not self.profit_tracker:
            return

        # Rebuild stats from closed trades
        self._rebuild_from_trades()

        # Log summary
        self._log_rotation_summary(current_date)

        self.last_rotation_date = current_date
        self.rotation_count += 1

    def _rebuild_from_trades(self):
        """
        Rebuild all ticker states from closed trades history

        This ensures consistency between profit_tracker and rotation state.
        """
        closed_trades = self.profit_tracker.get_closed_trades()

        if not closed_trades:
            return

        # Group trades by ticker, ordered by date
        ticker_trades = {}
        for trade in closed_trades:
            ticker = trade['ticker']
            if ticker not in ticker_trades:
                ticker_trades[ticker] = []
            ticker_trades[ticker].append(trade)

        # Sort each ticker's trades by date (oldest first)
        for ticker in ticker_trades:
            ticker_trades[ticker].sort(
                key=lambda t: t.get('exit_date') or datetime.min
            )

        # Rebuild each ticker's state
        for ticker, trades in ticker_trades.items():
            state = TickerState(ticker)

            for trade in trades:
                pnl = trade['pnl_dollars']
                trade_date = trade.get('exit_date')

                # Record trade (updates streaks)
                state.record_trade(pnl, trade_date)

                # Evaluate tier after each trade
                self._evaluate_tier_change(state, trade_date)

            self.ticker_states[ticker] = state

    def _log_rotation_summary(self, current_date):
        """Log rotation summary"""
        tier_counts = {'premium': 0, 'active': 0, 'probation': 0, 'rehabilitation': 0, 'frozen': 0}
        tier_tickers = {'premium': [], 'active': [], 'probation': [], 'rehabilitation': [], 'frozen': []}

        for ticker, state in self.ticker_states.items():
            tier = state.tier
            tier_counts[tier] = tier_counts.get(tier, 0) + 1
            tier_tickers[tier].append(ticker)

        date_str = current_date.strftime('%Y-%m-%d') if current_date else 'Unknown'

        print(f"\n🔄 ROTATION SUMMARY [{date_str}]")
        print(f"   🥇 Premium ({tier_counts['premium']}): {', '.join(tier_tickers['premium'][:5]) or 'None'}")
        print(f"   🥈 Active ({tier_counts['active']}): {len(tier_tickers['active'])} stocks")
        print(f"   ⚠️  Probation ({tier_counts['probation']}): {', '.join(tier_tickers['probation'][:5]) or 'None'}")
        print(
            f"   🔄 Rehab ({tier_counts['rehabilitation']}): {', '.join(tier_tickers['rehabilitation'][:5]) or 'None'}")
        print(f"   ❄️  Frozen ({tier_counts['frozen']}): {', '.join(tier_tickers['frozen'][:5]) or 'None'}")

    def get_statistics(self):
        """Get rotation statistics for reporting"""
        tier_counts = {'premium': 0, 'active': 0, 'probation': 0, 'rehabilitation': 0, 'frozen': 0}
        tier_tickers = {'premium': [], 'active': [], 'probation': [], 'rehabilitation': [], 'frozen': []}

        for ticker, state in self.ticker_states.items():
            tier = state.tier
            tier_counts[tier] = tier_counts.get(tier, 0) + 1
            tier_tickers[tier].append(ticker)

        return {
            'rotation_count': self.rotation_count,
            'last_rotation_date': self.last_rotation_date,
            'total_tracked': len(self.ticker_states),
            'award_distribution': tier_counts,  # Backward compatibility
            'tier_distribution': tier_counts,
            'premium_stocks': tier_tickers['premium'],
            'frozen_stocks': tier_tickers['frozen'],
            'probation_stocks': tier_tickers['probation'],
            'rehabilitation_stocks': tier_tickers['rehabilitation']
        }

    def get_state_for_persistence(self):
        """Get all state data for database persistence"""
        return {
            ticker: state.to_dict()
            for ticker, state in self.ticker_states.items()
        }

    def load_state_from_persistence(self, state_data):
        """Load state from database persistence"""
        self.ticker_states = {}
        for ticker, data in state_data.items():
            self.ticker_states[ticker] = TickerState.from_dict(data)


def should_rotate(rotator, current_date, frequency='weekly'):
    """Check if rotation should run"""
    if rotator.last_rotation_date is None:
        return True

    days_since = (current_date - rotator.last_rotation_date).days
    thresholds = {'daily': 1, 'weekly': 7, 'monthly': 30}
    return days_since >= thresholds.get(frequency, 7)


def print_rotation_report(rotator):
    """Print rotation report"""
    stats = rotator.get_statistics()
    dist = stats['tier_distribution']

    print(f"\n🏆 Rotation: {stats['rotation_count']} evaluations")
    print(f"   🥇 Premium: {dist.get('premium', 0)} | "
          f"🥈 Active: {dist.get('active', 0)} | "
          f"⚠️ Probation: {dist.get('probation', 0)} | "
          f"🔄 Rehab: {dist.get('rehabilitation', 0)} | "
          f"❄️ Frozen: {dist.get('frozen', 0)}")

    if stats['premium_stocks']:
        print(f"   Premium: {', '.join(stats['premium_stocks'][:5])}")

    if stats['frozen_stocks']:
        print(f"   Frozen: {', '.join(stats['frozen_stocks'][:5])}")
