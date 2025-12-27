"""
Recovery Mode System - Aggressive Bottom Testing

AGGRESSIVE MODE (Day 0 Entry):
- Enter IMMEDIATELY when SPY is oversold + any 1 signal fires
- No waiting period required
- Full position size from the start
- Oversold = SPY >3% below 20 EMA OR RSI < 30 OR 2+ down days at 10-day low
"""

from datetime import timedelta


class RecoveryModeConfig:
    # === AGGRESSIVE SETTINGS ===
    MIN_RECOVERY_SIGNALS = 1  # Only need 1 signal when oversold
    MIN_LOCK_DAYS_BEFORE_RECOVERY = 0  # No waiting - enter Day 0
    RECOVERY_POSITION_MULTIPLIER = 1.0  # Full size immediately
    RECOVERY_MAX_POSITIONS = 8
    RELOCK_ON_SPY_DOWN_DAYS = 3  # More tolerance - 3 down days to exit (was 2)
    RECOVERY_MODE_MAX_DAYS = 14  # Extended window (was 10)
    RECOVERY_PROFIT_TARGET = 5.0
    BREADTH_UNLOCK_THRESHOLD = 25.0  # Lowered from 30% - easier to trigger
    BREADTH_LOCK_THRESHOLD = 15.0  # Lowered from 20% - stay in longer

    # === OVERSOLD DETECTION ===
    OVERSOLD_EMA_DEVIATION_PCT = 3.0  # SPY >3% below 20 EMA = oversold
    OVERSOLD_CONSECUTIVE_DOWN_DAYS = 2  # 2+ down days
    OVERSOLD_RSI_THRESHOLD = 30  # RSI below 30


class RecoveryModeManager:
    def __init__(self):
        self.recovery_mode_active = False
        self.recovery_mode_start_date = None
        self.lock_start_date = None
        self.activation_count = 0
        self.spy_ema10 = 0
        self.spy_ema21 = 0
        self.spy_ema20 = 0  # For oversold detection
        self.spy_close = 0
        self.spy_prev_close = 0
        self.spy_consecutive_down_days = 0
        self.spy_price_history = []
        self.internal_breadth = {'pct_above_20ema': 0, 'pct_above_50sma': 0, 'pct_green_today': 0}
        self.recent_accum_days = 0
        self.recent_dist_days = 0
        self.spy_rsi = 50  # Track SPY RSI for oversold

    def update_spy_data(self, date, spy_close, spy_prev_close=None, spy_ema20=None, spy_rsi=None,
                        spy_high=None, spy_low=None, spy_volume=None, spy_avg_volume=None):
        """Update SPY data with oversold detection"""
        self.spy_close = spy_close

        # Track EMA20 for oversold calculation
        if spy_ema20:
            self.spy_ema20 = spy_ema20

        # Track RSI
        if spy_rsi:
            self.spy_rsi = spy_rsi

        # Track consecutive down days
        if spy_prev_close:
            self.spy_prev_close = spy_prev_close
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

        # Normalize date
        if hasattr(date, 'tzinfo') and date.tzinfo is not None:
            date = date.replace(tzinfo=None)

        # Store price history
        self.spy_price_history.append({
            'date': date,
            'close': spy_close,
            'high': spy_high or spy_close,
            'low': spy_low or spy_close
        })
        self.spy_price_history = self.spy_price_history[-30:]

    def update_breadth(self, all_stock_data):
        """Track internal breadth across portfolio"""
        above_20ema = above_50sma = green_today = total = 0
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
        self.recent_accum_days = accum_days
        self.recent_dist_days = dist_days

    # =========================================================================
    # OVERSOLD DETECTION (Aggressive Entry Trigger)
    # =========================================================================

    def _is_spy_oversold(self):
        """
        Check if SPY is oversold - triggers immediate entry eligibility

        Oversold conditions (any one triggers):
        1. SPY >3% below 20 EMA
        2. RSI < 30
        3. 2+ consecutive down days AND at/near 10-day low
        """
        reasons = []

        # Condition 1: Price deviation from EMA20
        if self.spy_ema20 > 0:
            deviation_pct = ((self.spy_ema20 - self.spy_close) / self.spy_ema20) * 100
            if deviation_pct >= RecoveryModeConfig.OVERSOLD_EMA_DEVIATION_PCT:
                reasons.append(f"SPY {deviation_pct:.1f}% below 20 EMA")

        # Condition 2: RSI oversold
        if self.spy_rsi < RecoveryModeConfig.OVERSOLD_RSI_THRESHOLD:
            reasons.append(f"RSI {self.spy_rsi:.0f} < {RecoveryModeConfig.OVERSOLD_RSI_THRESHOLD}")

        # Condition 3: Consecutive down days + near 10-day low
        if self.spy_consecutive_down_days >= RecoveryModeConfig.OVERSOLD_CONSECUTIVE_DOWN_DAYS:
            if len(self.spy_price_history) >= 10:
                ten_day_low = min(p['close'] for p in self.spy_price_history[-10:])
                if self.spy_close <= ten_day_low * 1.01:  # Within 1% of 10-day low
                    reasons.append(f"{self.spy_consecutive_down_days} down days at 10-day low")

        return len(reasons) > 0, reasons

    # =========================================================================
    # AGGRESSIVE ENTRY LOGIC (Day 0)
    # =========================================================================

    def check_recovery_mode_entry(self, current_date):
        """
        AGGRESSIVE: Enter immediately when oversold + 1 signal
        No waiting period required.
        """
        if not self.lock_start_date or self.recovery_mode_active:
            return False

        signals = self.count_recovery_signals()
        is_oversold, oversold_reasons = self._is_spy_oversold()

        # AGGRESSIVE: If oversold, only need 1 signal
        if is_oversold and signals['total'] >= RecoveryModeConfig.MIN_RECOVERY_SIGNALS:
            print(f"⚡ AGGRESSIVE ENTRY TRIGGERED")
            print(f"   Oversold: {', '.join(oversold_reasons)}")
            print(f"   Signals: {signals['total']}/{RecoveryModeConfig.MIN_RECOVERY_SIGNALS}")
            return True

        # Fallback: Even if not oversold, allow entry with stronger signals (3+)
        days_locked = (current_date - self.lock_start_date).days
        if days_locked >= 1 and signals['total'] >= 3:
            print(f"✅ Standard recovery entry: {signals['total']} signals on day {days_locked}")
            return True

        return False

    # =========================================================================
    # ORIGINAL METHODS (preserved)
    # =========================================================================

    def count_recovery_signals(self):
        signals = {
            'breadth_improving': False,
            'spy_above_ema10': False,
            'spy_above_ema21': False,
            'ema10_above_ema21': False,
            'accumulation_dominant': False,
            'higher_low_forming': False
        }

        if self.internal_breadth.get('pct_above_20ema', 0) > RecoveryModeConfig.BREADTH_UNLOCK_THRESHOLD:
            signals['breadth_improving'] = True
        if self.spy_close > self.spy_ema10:
            signals['spy_above_ema10'] = True
        if self.spy_close > self.spy_ema21:
            signals['spy_above_ema21'] = True
        if self.spy_ema10 > self.spy_ema21:
            signals['ema10_above_ema21'] = True

        ad_ratio = (self.recent_accum_days / self.recent_dist_days) if self.recent_dist_days > 0 else (
            10.0 if self.recent_accum_days > 0 else 1.0)
        if ad_ratio > 1.0:
            signals['accumulation_dominant'] = True

        if self._check_higher_low():
            signals['higher_low_forming'] = True

        signals['total'] = sum(1 for k, v in signals.items() if k != 'total' and v is True)
        return signals

    def _check_higher_low(self):
        if len(self.spy_price_history) < 15:
            return False
        prices = [p['close'] for p in self.spy_price_history[-15:]]
        lows = []
        for i in range(2, len(prices) - 2):
            if prices[i] < prices[i - 1] and prices[i] < prices[i - 2] and prices[i] < prices[i + 1] and prices[i] < \
                    prices[i + 2]:
                lows.append(prices[i])
        return len(lows) >= 2 and lows[-1] > lows[-2]

    def start_lock(self, current_date):
        if not self.lock_start_date:
            self.lock_start_date = current_date
            print(f"🔒 LOCK STARTED: SPY below 200 SMA")

    def clear_lock(self):
        if self.lock_start_date or self.recovery_mode_active:
            print(f"🔓 LOCK CLEARED: SPY above 200 SMA")
        self.lock_start_date = None
        self.recovery_mode_active = False
        self.recovery_mode_start_date = None

    def enter_recovery_mode(self, current_date):
        self.activation_count += 1
        self.recovery_mode_active = True
        self.recovery_mode_start_date = current_date
        signals = self.count_recovery_signals()
        is_oversold, oversold_reasons = self._is_spy_oversold()

        print(f"\n{'=' * 60}")
        print(f"🔓 RECOVERY MODE ACTIVATED (#{self.activation_count}) - AGGRESSIVE")
        if is_oversold:
            print(f"   Oversold: {', '.join(oversold_reasons)}")
        print(
            f"   Signals: {signals['total']}/{RecoveryModeConfig.MIN_RECOVERY_SIGNALS} | Size: {RecoveryModeConfig.RECOVERY_POSITION_MULTIPLIER * 100:.0f}% | Max: {RecoveryModeConfig.RECOVERY_MAX_POSITIONS}")
        print(f"{'=' * 60}\n")

    def check_recovery_mode_exit(self, current_date):
        if not self.recovery_mode_active:
            return False, None

        days = (current_date - self.recovery_mode_start_date).days
        if days > RecoveryModeConfig.RECOVERY_MODE_MAX_DAYS:
            return True, f"Max duration ({RecoveryModeConfig.RECOVERY_MODE_MAX_DAYS}d)"

        if self.spy_consecutive_down_days >= RecoveryModeConfig.RELOCK_ON_SPY_DOWN_DAYS:
            return True, f"SPY down {self.spy_consecutive_down_days}d"

        signals = self.count_recovery_signals()
        if signals['total'] < RecoveryModeConfig.MIN_RECOVERY_SIGNALS:
            return True, f"Signals weak ({signals['total']}/{RecoveryModeConfig.MIN_RECOVERY_SIGNALS})"

        if self.internal_breadth.get('pct_above_20ema', 0) < RecoveryModeConfig.BREADTH_LOCK_THRESHOLD:
            return True, f"Breadth collapsed"

        return False, None

    def exit_recovery_mode(self, reason):
        if self.recovery_mode_active:
            self.recovery_mode_active = False
            self.recovery_mode_start_date = None
            print(f"🔒 RECOVERY MODE TERMINATED: {reason}")
            return True
        return False

    def trigger_relock(self, current_date, reason):
        return self.exit_recovery_mode(reason)

    def evaluate(self, current_date, spy_below_200):
        if not spy_below_200:
            self.clear_lock()
            return {
                'recovery_mode_active': False,
                'position_multiplier': 1.0,
                'max_positions': 25,
                'allow_entries': True,
                'profit_target': 10.0,
                'signals': {},
                'reason': 'Normal'
            }

        self.start_lock(current_date)

        if self.recovery_mode_active:
            should_exit, exit_reason = self.check_recovery_mode_exit(current_date)
            if should_exit:
                self.exit_recovery_mode(exit_reason)

        if not self.recovery_mode_active and self.check_recovery_mode_entry(current_date):
            self.enter_recovery_mode(current_date)

        signals = self.count_recovery_signals()

        if self.recovery_mode_active:
            return {
                'recovery_mode_active': True,
                'position_multiplier': RecoveryModeConfig.RECOVERY_POSITION_MULTIPLIER,
                'max_positions': RecoveryModeConfig.RECOVERY_MAX_POSITIONS,
                'allow_entries': True,
                'profit_target': RecoveryModeConfig.RECOVERY_PROFIT_TARGET,
                'signals': signals,
                'reason': f"Recovery: {signals['total']} signals"
            }

        days_locked = (current_date - self.lock_start_date).days if self.lock_start_date else 0
        is_oversold, oversold_reasons = self._is_spy_oversold()

        # Enhanced reason with oversold status
        reason_parts = [
            f"Locked: {signals['total']}/{RecoveryModeConfig.MIN_RECOVERY_SIGNALS} signals, day {days_locked}"]
        if is_oversold:
            reason_parts.append(f"⚡OVERSOLD")

        return {
            'recovery_mode_active': False,
            'position_multiplier': 0.0,
            'max_positions': 0,
            'allow_entries': False,
            'profit_target': 10.0,
            'signals': signals,
            'reason': " | ".join(reason_parts)
        }

    def get_statistics(self):
        is_oversold, oversold_reasons = self._is_spy_oversold()
        return {
            'recovery_mode_active': self.recovery_mode_active,
            'activation_count': self.activation_count,
            'lock_start_date': self.lock_start_date,
            'spy_ema10': round(self.spy_ema10, 2),
            'spy_ema21': round(self.spy_ema21, 2),
            'spy_ema20': round(self.spy_ema20, 2),
            'spy_rsi': round(self.spy_rsi, 1),
            'spy_consecutive_down_days': self.spy_consecutive_down_days,
            'internal_breadth': self.internal_breadth,
            'recovery_signals': self.count_recovery_signals(),
            'is_oversold': is_oversold,
            'oversold_reasons': oversold_reasons,
        }