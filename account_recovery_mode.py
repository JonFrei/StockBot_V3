"""
Recovery Mode System - Bear Market Rally Trading

Allows constrained trading when SPY is below 200 SMA but recovery signals are firing.
Designed to capture bear market rallies without full exposure.

Key Features:
1. Requires 3+ recovery signals to unlock
2. 35% position size (not 100%)
3. Maximum 5 positions
4. Hair-trigger re-lock on any weakness
5. Reduced profit targets (+7% vs +10%)

Recovery Signals Tracked:
- Internal breadth (% of universe above 20 EMA)
- SPY vs 10/21 EMA
- EMA alignment (10 > 21)
- Accumulation vs Distribution ratio
- Higher low formation
"""

from datetime import timedelta


class RecoveryModeConfig:
    """Recovery mode constraints - CONSERVATIVE"""

    # Entry requirements
    MIN_RECOVERY_SIGNALS = 3
    MIN_LOCK_DAYS_BEFORE_RECOVERY = 5

    # Position constraints
    RECOVERY_POSITION_MULTIPLIER = 0.35
    RECOVERY_MAX_POSITIONS = 5

    # Re-lock triggers (hair trigger)
    RELOCK_ON_SPY_DOWN_DAYS = 2

    # Time constraints
    RECOVERY_MODE_MAX_DAYS = 10

    # Profit target (reduced from normal 10%)
    RECOVERY_PROFIT_TARGET = 7.0

    # Breadth thresholds
    BREADTH_UNLOCK_THRESHOLD = 30.0  # % above 20 EMA to help unlock
    BREADTH_LOCK_THRESHOLD = 20.0  # % below this = weakness


class RecoveryModeManager:
    """
    Manages recovery mode state and signals

    Works alongside MarketRegimeDetector - does not replace it
    """

    def __init__(self):
        # State
        self.recovery_mode_active = False
        self.recovery_mode_start_date = None
        self.lock_start_date = None

        # SPY tracking
        self.spy_ema10 = 0
        self.spy_ema21 = 0
        self.spy_close = 0
        self.spy_prev_close = 0
        self.spy_consecutive_down_days = 0
        self.spy_price_history = []

        # Breadth tracking
        self.internal_breadth = {
            'pct_above_20ema': 0,
            'pct_above_50sma': 0,
            'pct_green_today': 0,
        }

        # Accumulation/Distribution tracking (mirrors regime detector)
        self.recent_accum_days = 0
        self.recent_dist_days = 0

    # =========================================================================
    # UPDATE METHODS
    # =========================================================================

    def update_spy_data(self, date, spy_close, spy_prev_close=None):
        """Update SPY price data and EMAs"""
        self.spy_close = spy_close

        if spy_prev_close:
            self.spy_prev_close = spy_prev_close

            # Track consecutive down days
            if spy_close < spy_prev_close:
                self.spy_consecutive_down_days += 1
            else:
                self.spy_consecutive_down_days = 0

        # Update EMAs
        if self.spy_ema10 == 0:
            self.spy_ema10 = spy_close
            self.spy_ema21 = spy_close
        else:
            self.spy_ema10 = spy_close * (2 / 11) + self.spy_ema10 * (9 / 11)
            self.spy_ema21 = spy_close * (2 / 22) + self.spy_ema21 * (20 / 22)

        # Track price history for higher low detection
        if hasattr(date, 'tzinfo') and date.tzinfo is not None:
            date = date.replace(tzinfo=None)

        self.spy_price_history.append({'date': date, 'close': spy_close})
        self.spy_price_history = self.spy_price_history[-30:]

    def update_breadth(self, all_stock_data):
        """Calculate internal breadth from trading universe"""
        above_20ema = 0
        above_50sma = 0
        green_today = 0
        total = 0

        for ticker, data in all_stock_data.items():
            if ticker == 'SPY':
                continue

            ind = data.get('indicators', {})
            if not ind:
                continue

            total += 1
            close = ind.get('close', 0)

            if close > ind.get('ema20', 0):
                above_20ema += 1
            if close > ind.get('sma50', 0):
                above_50sma += 1
            if close > ind.get('prev_close', 0):
                green_today += 1

        if total > 0:
            self.internal_breadth = {
                'pct_above_20ema': round(above_20ema / total * 100, 1),
                'pct_above_50sma': round(above_50sma / total * 100, 1),
                'pct_green_today': round(green_today / total * 100, 1),
            }

    def update_accum_dist(self, accum_days, dist_days):
        """Sync accumulation/distribution counts from regime detector"""
        self.recent_accum_days = accum_days
        self.recent_dist_days = dist_days

    # =========================================================================
    # RECOVERY SIGNAL DETECTION
    # =========================================================================

    def count_recovery_signals(self):
        """
        Count active recovery signals

        Returns dict with individual signals and total count
        """
        signals = {
            'breadth_improving': False,
            'spy_above_ema10': False,
            'spy_above_ema21': False,
            'ema10_above_ema21': False,
            'accumulation_dominant': False,
            'higher_low_forming': False,
        }

        # 1. Breadth improving
        if self.internal_breadth.get('pct_above_20ema', 0) > RecoveryModeConfig.BREADTH_UNLOCK_THRESHOLD:
            signals['breadth_improving'] = True

        # 2. SPY above short-term EMAs
        if self.spy_close > self.spy_ema10:
            signals['spy_above_ema10'] = True

        if self.spy_close > self.spy_ema21:
            signals['spy_above_ema21'] = True

        # 3. EMA alignment
        if self.spy_ema10 > self.spy_ema21:
            signals['ema10_above_ema21'] = True

        # 4. Accumulation > Distribution
        if self.recent_dist_days > 0:
            ad_ratio = self.recent_accum_days / self.recent_dist_days
        else:
            ad_ratio = 10.0 if self.recent_accum_days > 0 else 1.0

        if ad_ratio > 1.0:
            signals['accumulation_dominant'] = True

        # 5. Higher low forming
        if self._check_higher_low():
            signals['higher_low_forming'] = True

        signals['total'] = sum(1 for k, v in signals.items() if k != 'total' and v is True)

        return signals

    def _check_higher_low(self):
        """Check if SPY is forming higher low (bullish)"""
        if len(self.spy_price_history) < 15:
            return False

        prices = [p['close'] for p in self.spy_price_history[-15:]]

        # Find swing lows (simplified)
        lows = []
        for i in range(2, len(prices) - 2):
            if prices[i] < prices[i - 1] and prices[i] < prices[i - 2] and \
                    prices[i] < prices[i + 1] and prices[i] < prices[i + 2]:
                lows.append(prices[i])

        if len(lows) >= 2:
            return lows[-1] > lows[-2]

        return False

    # =========================================================================
    # STATE MANAGEMENT
    # =========================================================================

    def start_lock(self, current_date):
        """Called when SPY drops below 200 SMA"""
        if not self.lock_start_date:
            self.lock_start_date = current_date
            print(f"🔒 LOCK STARTED: SPY below 200 SMA")

    def clear_lock(self):
        """Called when SPY rises above 200 SMA"""
        if self.lock_start_date or self.recovery_mode_active:
            print(f"🔓 LOCK CLEARED: SPY above 200 SMA")

        self.lock_start_date = None
        self.recovery_mode_active = False
        self.recovery_mode_start_date = None

    def check_recovery_mode_entry(self, current_date):
        """
        Check if we should enter recovery mode

        Returns:
            bool: True if should enter recovery mode
        """
        # Must be locked first
        if not self.lock_start_date:
            return False

        # Already in recovery mode
        if self.recovery_mode_active:
            return False

        # Must be locked for minimum period
        days_locked = (current_date - self.lock_start_date).days
        if days_locked < RecoveryModeConfig.MIN_LOCK_DAYS_BEFORE_RECOVERY:
            return False

        # Must have enough recovery signals
        signals = self.count_recovery_signals()
        if signals['total'] < RecoveryModeConfig.MIN_RECOVERY_SIGNALS:
            return False

        return True

    def enter_recovery_mode(self, current_date):
        """Enter recovery mode"""
        self.recovery_mode_active = True
        self.recovery_mode_start_date = current_date

        signals = self.count_recovery_signals()
        print(f"\n{'=' * 60}")
        print(f"🔓 RECOVERY MODE ACTIVATED")
        print(f"{'=' * 60}")
        print(f"   Signals: {signals['total']}/{RecoveryModeConfig.MIN_RECOVERY_SIGNALS}")
        print(f"   Breadth: {self.internal_breadth.get('pct_above_20ema', 0):.1f}% above 20 EMA")
        print(f"   SPY vs EMA10: {'Above' if signals['spy_above_ema10'] else 'Below'}")
        print(f"   SPY vs EMA21: {'Above' if signals['spy_above_ema21'] else 'Below'}")
        print(f"   Position Size: {RecoveryModeConfig.RECOVERY_POSITION_MULTIPLIER * 100:.0f}%")
        print(f"   Max Positions: {RecoveryModeConfig.RECOVERY_MAX_POSITIONS}")
        print(f"{'=' * 60}\n")

    def check_recovery_mode_exit(self, current_date):
        """
        Check if we should exit recovery mode (re-lock)

        Returns:
            tuple: (should_exit: bool, reason: str or None)
        """
        if not self.recovery_mode_active:
            return False, None

        # Check max days
        days_in_recovery = (current_date - self.recovery_mode_start_date).days
        if days_in_recovery > RecoveryModeConfig.RECOVERY_MODE_MAX_DAYS:
            return True, f"Max duration ({RecoveryModeConfig.RECOVERY_MODE_MAX_DAYS} days)"

        # Check consecutive down days
        if self.spy_consecutive_down_days >= RecoveryModeConfig.RELOCK_ON_SPY_DOWN_DAYS:
            return True, f"SPY down {self.spy_consecutive_down_days} consecutive days"

        # Check if recovery signals faded
        signals = self.count_recovery_signals()
        if signals['total'] < RecoveryModeConfig.MIN_RECOVERY_SIGNALS:
            return True, f"Signals weakened ({signals['total']}/{RecoveryModeConfig.MIN_RECOVERY_SIGNALS})"

        # Check breadth collapse
        if self.internal_breadth.get('pct_above_20ema', 0) < RecoveryModeConfig.BREADTH_LOCK_THRESHOLD:
            return True, f"Breadth collapsed ({self.internal_breadth.get('pct_above_20ema', 0):.1f}%)"

        return False, None

    def exit_recovery_mode(self, reason):
        """Exit recovery mode (re-lock)"""
        if self.recovery_mode_active:
            self.recovery_mode_active = False
            self.recovery_mode_start_date = None

            print(f"\n{'=' * 60}")
            print(f"🔒 RECOVERY MODE TERMINATED")
            print(f"   Reason: {reason}")
            print(f"{'=' * 60}\n")

            return True
        return False

    def trigger_relock(self, reason):
        """External trigger to re-lock (distribution day, stop loss, etc.)"""
        return self.exit_recovery_mode(reason)

    # =========================================================================
    # MAIN INTERFACE
    # =========================================================================

    def evaluate(self, current_date, spy_below_200):
        """
        Main evaluation method - call each iteration

        Args:
            current_date: Current datetime
            spy_below_200: Boolean from regime detector

        Returns:
            dict: {
                'recovery_mode_active': bool,
                'position_multiplier': float,
                'max_positions': int,
                'allow_entries': bool,
                'profit_target': float,
                'signals': dict,
                'reason': str,
            }
        """
        # If SPY above 200, clear lock state
        if not spy_below_200:
            self.clear_lock()
            return {
                'recovery_mode_active': False,
                'position_multiplier': 1.0,
                'max_positions': 25,
                'allow_entries': True,
                'profit_target': 10.0,
                'signals': {},
                'reason': 'Normal - SPY above 200 SMA',
            }

        # SPY below 200 - track lock
        self.start_lock(current_date)

        # Check for recovery mode exit first
        if self.recovery_mode_active:
            should_exit, exit_reason = self.check_recovery_mode_exit(current_date)
            if should_exit:
                self.exit_recovery_mode(exit_reason)

        # Check for recovery mode entry
        if not self.recovery_mode_active and self.check_recovery_mode_entry(current_date):
            self.enter_recovery_mode(current_date)

        signals = self.count_recovery_signals()

        # Return appropriate state
        if self.recovery_mode_active:
            return {
                'recovery_mode_active': True,
                'position_multiplier': RecoveryModeConfig.RECOVERY_POSITION_MULTIPLIER,
                'max_positions': RecoveryModeConfig.RECOVERY_MAX_POSITIONS,
                'allow_entries': True,
                'profit_target': RecoveryModeConfig.RECOVERY_PROFIT_TARGET,
                'signals': signals,
                'reason': f"Recovery Mode: {signals['total']} signals active",
            }
        else:
            days_locked = (current_date - self.lock_start_date).days if self.lock_start_date else 0
            return {
                'recovery_mode_active': False,
                'position_multiplier': 0.0,
                'max_positions': 0,
                'allow_entries': False,
                'profit_target': 10.0,
                'signals': signals,
                'reason': f"Locked: {signals['total']}/{RecoveryModeConfig.MIN_RECOVERY_SIGNALS} signals, day {days_locked}/{RecoveryModeConfig.MIN_LOCK_DAYS_BEFORE_RECOVERY}",
            }

    # =========================================================================
    # STATISTICS
    # =========================================================================

    def get_statistics(self):
        """Get current state for logging/email"""
        signals = self.count_recovery_signals()

        return {
            'recovery_mode_active': self.recovery_mode_active,
            'recovery_mode_start_date': self.recovery_mode_start_date,
            'lock_start_date': self.lock_start_date,
            'spy_ema10': round(self.spy_ema10, 2),
            'spy_ema21': round(self.spy_ema21, 2),
            'spy_consecutive_down_days': self.spy_consecutive_down_days,
            'internal_breadth': self.internal_breadth,
            'recovery_signals': signals,
            'config': {
                'min_signals': RecoveryModeConfig.MIN_RECOVERY_SIGNALS,
                'min_lock_days': RecoveryModeConfig.MIN_LOCK_DAYS_BEFORE_RECOVERY,
                'position_multiplier': RecoveryModeConfig.RECOVERY_POSITION_MULTIPLIER,
                'max_positions': RecoveryModeConfig.RECOVERY_MAX_POSITIONS,
                'profit_target': RecoveryModeConfig.RECOVERY_PROFIT_TARGET,
            }
        }