"""
Recovery Mode System - Structure-Based Bottom Detection

APPROACH: Market Structure (B) + Follow-Through (D)

Phase 1: CAPITULATION DETECTION
    - SPY down 1.5%+ on volume >=1.3x average
    - OR 3+ consecutive down days totaling 4%+ decline
    - Marks potential swing low

Phase 2: SWING LOW CONFIRMATION (1-3 days)
    - Price holds above capitulation low for 1-2 days
    - Establishes the swing low point

Phase 3: FOLLOW-THROUGH DAY (within 4-7 days of swing low)
    - SPY up 1.25%+ on volume >=1.0x average
    - OR SPY up 1.0%+ AND closes above 10 EMA
    - Triggers recovery mode entry

BONUS: HIGHER LOW = Higher conviction (vs prior swing low)
"""

from datetime import timedelta


class RecoveryModeConfig:
    # === CAPITULATION DETECTION (Phase 1) ===
    CAPITULATION_SINGLE_DAY_DROP = 1.5  # % drop for single-day capitulation
    CAPITULATION_VOLUME_MULT = 1.3  # Volume must be 1.3x average
    CAPITULATION_MULTI_DAY_DAYS = 3  # Consecutive down days
    CAPITULATION_MULTI_DAY_DROP = 4.0  # Total % drop over multi-day

    # === SWING LOW CONFIRMATION (Phase 2) ===
    SWING_LOW_HOLD_DAYS = 1  # Days price must hold above low

    # === FOLLOW-THROUGH DAY (Phase 3) ===
    FOLLOW_THROUGH_MIN_GAIN = 1.25  # % gain required
    FOLLOW_THROUGH_ALT_GAIN = 1.0  # Alternative: smaller gain + above EMA
    FOLLOW_THROUGH_VOLUME_MULT = 1.0  # Volume must be at least average
    FOLLOW_THROUGH_WINDOW_DAYS = 7  # Must occur within N days of swing low
    FOLLOW_THROUGH_MIN_WAIT = 1  # Minimum days after swing low (avoid Day 0 noise)

    # === HIGHER LOW DETECTION ===
    HIGHER_LOW_LOOKBACK_DAYS = 20  # How far back to find prior swing low

    # === RECOVERY MODE SETTINGS ===
    RECOVERY_POSITION_MULTIPLIER = 1.0
    RECOVERY_MAX_POSITIONS = 8
    RECOVERY_MAX_POSITIONS_HIGHER_LOW = 10  # More positions if higher low confirmed
    RELOCK_ON_SPY_DOWN_DAYS = 3  # Exit after 3 consecutive down days
    RECOVERY_MODE_MAX_DAYS = 14
    RECOVERY_PROFIT_TARGET = 5.0
    BREADTH_LOCK_THRESHOLD = 15.0  # Exit if breadth collapses


class RecoveryModeManager:
    def __init__(self):
        # Recovery state
        self.recovery_mode_active = False
        self.recovery_mode_start_date = None
        self.lock_start_date = None
        self.activation_count = 0

        # SPY tracking
        self.spy_close = 0
        self.spy_prev_close = 0
        self.spy_ema10 = 0
        self.spy_ema21 = 0
        self.spy_consecutive_down_days = 0
        self.spy_price_history = []  # Full OHLCV history

        # Breadth tracking
        self.internal_breadth = {'pct_above_20ema': 0, 'pct_above_50sma': 0, 'pct_green_today': 0}
        self.recent_accum_days = 0
        self.recent_dist_days = 0

        # === STRUCTURE TRACKING (B + D) ===
        self.capitulation_detected = False
        self.capitulation_date = None
        self.capitulation_low = None  # The low price on capitulation

        self.swing_low_confirmed = False
        self.swing_low_date = None
        self.swing_low_price = None

        self.follow_through_detected = False
        self.follow_through_date = None

        self.prior_swing_low = None  # For higher low detection
        self.is_higher_low = False

    # =========================================================================
    # DATA UPDATE METHODS
    # =========================================================================

    def update_spy_data(self, date, spy_close, spy_open=None, spy_high=None, spy_low=None,
                        spy_volume=None, spy_avg_volume=None, spy_prev_close=None, spy_ema10=None):
        """Update SPY data and run structure detection"""

        # Store previous close
        if spy_prev_close:
            self.spy_prev_close = spy_prev_close
        elif self.spy_close > 0:
            self.spy_prev_close = self.spy_close

        self.spy_close = spy_close

        # Track EMA10 for follow-through
        if spy_ema10:
            self.spy_ema10 = spy_ema10
        elif self.spy_ema10 == 0:
            self.spy_ema10 = spy_close
        else:
            self.spy_ema10 = spy_close * (2 / 11) + self.spy_ema10 * (9 / 11)

        # Update EMA21
        if self.spy_ema21 == 0:
            self.spy_ema21 = spy_close
        else:
            self.spy_ema21 = spy_close * (2 / 22) + self.spy_ema21 * (20 / 22)

        # Track consecutive down days
        if self.spy_prev_close > 0:
            if spy_close < self.spy_prev_close:
                self.spy_consecutive_down_days += 1
            else:
                self.spy_consecutive_down_days = 0

        # Normalize date
        if hasattr(date, 'tzinfo') and date.tzinfo is not None:
            date = date.replace(tzinfo=None)

        # Store full bar data
        bar_data = {
            'date': date,
            'open': spy_open or spy_close,
            'high': spy_high or spy_close,
            'low': spy_low or spy_close,
            'close': spy_close,
            'volume': spy_volume or 0,
            'avg_volume': spy_avg_volume or 0
        }
        self.spy_price_history.append(bar_data)
        self.spy_price_history = self.spy_price_history[-50:]  # Keep 50 days

        # Run structure detection
        self._detect_capitulation(date)
        self._detect_swing_low(date)
        self._detect_follow_through(date)

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
    # PHASE 1: CAPITULATION DETECTION
    # =========================================================================

    def _detect_capitulation(self, current_date):
        """
        Detect capitulation selling - marks potential swing low

        Triggers on:
        1. Single day: Down 1.5%+ on volume 1.3x+ average
        2. Multi-day: 3+ down days totaling 4%+ decline
        """
        if len(self.spy_price_history) < 2:
            return

        today = self.spy_price_history[-1]
        yesterday = self.spy_price_history[-2]

        # Skip if already in confirmed swing low phase
        if self.swing_low_confirmed:
            return

        # === Method 1: Single-day capitulation ===
        if yesterday['close'] > 0:
            daily_change_pct = ((today['close'] - yesterday['close']) / yesterday['close']) * 100
            volume_ratio = today['volume'] / today['avg_volume'] if today['avg_volume'] > 0 else 0

            if (daily_change_pct <= -RecoveryModeConfig.CAPITULATION_SINGLE_DAY_DROP and
                    volume_ratio >= RecoveryModeConfig.CAPITULATION_VOLUME_MULT):

                self._set_capitulation(current_date, today['low'], "single-day")
                return

        # === Method 2: Multi-day capitulation ===
        if len(self.spy_price_history) >= RecoveryModeConfig.CAPITULATION_MULTI_DAY_DAYS + 1:
            lookback = RecoveryModeConfig.CAPITULATION_MULTI_DAY_DAYS
            recent_bars = self.spy_price_history[-(lookback + 1):]

            # Check if all recent days were down
            all_down = True
            for i in range(1, len(recent_bars)):
                if recent_bars[i]['close'] >= recent_bars[i - 1]['close']:
                    all_down = False
                    break

            if all_down:
                start_price = recent_bars[0]['close']
                end_price = recent_bars[-1]['close']
                total_drop = ((start_price - end_price) / start_price) * 100

                if total_drop >= RecoveryModeConfig.CAPITULATION_MULTI_DAY_DROP:
                    # Find the lowest low in this period
                    lowest_low = min(bar['low'] for bar in recent_bars[1:])
                    self._set_capitulation(current_date, lowest_low, "multi-day")

    def _set_capitulation(self, date, low_price, method):
        """Record capitulation event"""
        # Store prior swing low before overwriting
        if self.swing_low_price is not None:
            self.prior_swing_low = self.swing_low_price

        self.capitulation_detected = True
        self.capitulation_date = date
        self.capitulation_low = low_price

        # Reset downstream states
        self.swing_low_confirmed = False
        self.swing_low_date = None
        self.swing_low_price = None
        self.follow_through_detected = False
        self.follow_through_date = None
        self.is_higher_low = False

        print(f"⚡ CAPITULATION DETECTED ({method}): Low ${low_price:.2f} on {date.strftime('%Y-%m-%d')}")

    # =========================================================================
    # PHASE 2: SWING LOW CONFIRMATION
    # =========================================================================

    def _detect_swing_low(self, current_date):
        """
        Confirm swing low - price holds above capitulation low

        Requires: Price holds above the capitulation low for N days
        """
        if not self.capitulation_detected or self.swing_low_confirmed:
            return

        if self.capitulation_date is None or self.capitulation_low is None:
            return

        days_since_cap = (current_date - self.capitulation_date).days

        # Need at least 1 day after capitulation
        if days_since_cap < RecoveryModeConfig.SWING_LOW_HOLD_DAYS:
            return

        # Check if price has held above capitulation low
        recent_bars = [b for b in self.spy_price_history
                       if b['date'] > self.capitulation_date]

        if len(recent_bars) < RecoveryModeConfig.SWING_LOW_HOLD_DAYS:
            return

        # All recent lows must be above capitulation low
        held_above = all(bar['low'] >= self.capitulation_low * 0.998  # 0.2% tolerance
                         for bar in recent_bars[-RecoveryModeConfig.SWING_LOW_HOLD_DAYS:])

        if held_above:
            self.swing_low_confirmed = True
            self.swing_low_date = self.capitulation_date
            self.swing_low_price = self.capitulation_low

            # Check for higher low
            if self.prior_swing_low is not None:
                self.is_higher_low = self.swing_low_price > self.prior_swing_low
                hl_status = "HIGHER LOW ✓" if self.is_higher_low else "Lower low"
            else:
                hl_status = "First swing low"

            print(f"📍 SWING LOW CONFIRMED: ${self.swing_low_price:.2f} ({hl_status})")
            print(f"   Watching for follow-through day within {RecoveryModeConfig.FOLLOW_THROUGH_WINDOW_DAYS} days...")

    # =========================================================================
    # PHASE 3: FOLLOW-THROUGH DAY DETECTION
    # =========================================================================

    def _detect_follow_through(self, current_date):
        """
        Detect follow-through day - confirms the bottom

        Requires:
        - Within 4-7 days of swing low
        - SPY up 1.25%+ on volume >= average
        - OR SPY up 1.0%+ and closes above 10 EMA
        """
        if not self.swing_low_confirmed or self.follow_through_detected:
            return

        if self.swing_low_date is None:
            return

        days_since_swing = (current_date - self.swing_low_date).days

        # Must wait minimum days (avoid noise)
        if days_since_swing < RecoveryModeConfig.FOLLOW_THROUGH_MIN_WAIT:
            return

        # Must be within window
        if days_since_swing > RecoveryModeConfig.FOLLOW_THROUGH_WINDOW_DAYS:
            # Window expired - reset and wait for new capitulation
            print(f"⏰ Follow-through window expired ({days_since_swing} days). Resetting...")
            self._reset_structure_state()
            return

        if len(self.spy_price_history) < 2:
            return

        today = self.spy_price_history[-1]
        yesterday = self.spy_price_history[-2]

        if yesterday['close'] <= 0:
            return

        daily_gain_pct = ((today['close'] - yesterday['close']) / yesterday['close']) * 100
        volume_ratio = today['volume'] / today['avg_volume'] if today['avg_volume'] > 0 else 0

        # === Method 1: Strong follow-through (1.25%+ on volume) ===
        if (daily_gain_pct >= RecoveryModeConfig.FOLLOW_THROUGH_MIN_GAIN and
                volume_ratio >= RecoveryModeConfig.FOLLOW_THROUGH_VOLUME_MULT):

            self._set_follow_through(current_date, daily_gain_pct, volume_ratio, "strong")
            return

        # === Method 2: Moderate follow-through (1.0%+ and above EMA10) ===
        if (daily_gain_pct >= RecoveryModeConfig.FOLLOW_THROUGH_ALT_GAIN and
                today['close'] > self.spy_ema10):

            self._set_follow_through(current_date, daily_gain_pct, volume_ratio, "ema_reclaim")
            return

    def _set_follow_through(self, date, gain_pct, volume_ratio, method):
        """Record follow-through day"""
        self.follow_through_detected = True
        self.follow_through_date = date

        hl_bonus = " [HIGHER LOW]" if self.is_higher_low else ""
        print(f"🚀 FOLLOW-THROUGH DAY ({method}){hl_bonus}")
        print(f"   Gain: +{gain_pct:.2f}% | Volume: {volume_ratio:.1f}x avg")

    def _reset_structure_state(self):
        """Reset structure tracking (keep prior swing low for higher low detection)"""
        # Preserve prior swing low
        if self.swing_low_price is not None:
            self.prior_swing_low = self.swing_low_price

        self.capitulation_detected = False
        self.capitulation_date = None
        self.capitulation_low = None
        self.swing_low_confirmed = False
        self.swing_low_date = None
        self.swing_low_price = None
        self.follow_through_detected = False
        self.follow_through_date = None
        self.is_higher_low = False

    # =========================================================================
    # RECOVERY MODE ENTRY/EXIT
    # =========================================================================

    def check_recovery_mode_entry(self, current_date):
        """
        Enter recovery mode when follow-through day confirms the bottom

        Structure-based entry:
        1. Capitulation detected (Phase 1) ✓
        2. Swing low confirmed (Phase 2) ✓
        3. Follow-through day (Phase 3) ✓
        """
        if self.recovery_mode_active:
            return False

        if not self.lock_start_date:
            return False

        # All three phases must be complete
        if self.follow_through_detected:
            print(f"✅ STRUCTURE CONFIRMED: Capitulation → Swing Low → Follow-Through")
            return True

        return False

    def enter_recovery_mode(self, current_date):
        """Enter recovery mode after structure confirmation"""
        self.activation_count += 1
        self.recovery_mode_active = True
        self.recovery_mode_start_date = current_date

        # Determine position limits based on higher low
        max_positions = (RecoveryModeConfig.RECOVERY_MAX_POSITIONS_HIGHER_LOW
                         if self.is_higher_low
                         else RecoveryModeConfig.RECOVERY_MAX_POSITIONS)

        print(f"\n{'=' * 60}")
        print(f"🔓 RECOVERY MODE ACTIVATED (#{self.activation_count})")
        print(f"   Method: Structure (Capitulation → Swing Low → Follow-Through)")
        if self.is_higher_low:
            print(f"   Higher Low: YES (increased conviction)")
        print(f"   Swing Low: ${self.swing_low_price:.2f} on {self.swing_low_date.strftime('%Y-%m-%d')}")
        print(f"   Max Positions: {max_positions}")
        print(f"{'=' * 60}\n")

    def check_recovery_mode_exit(self, current_date):
        """Check if recovery mode should exit"""
        if not self.recovery_mode_active:
            return False, None

        # Max duration
        days_active = (current_date - self.recovery_mode_start_date).days
        if days_active > RecoveryModeConfig.RECOVERY_MODE_MAX_DAYS:
            return True, f"Max duration ({RecoveryModeConfig.RECOVERY_MODE_MAX_DAYS} days)"

        # Consecutive down days
        if self.spy_consecutive_down_days >= RecoveryModeConfig.RELOCK_ON_SPY_DOWN_DAYS:
            return True, f"SPY down {self.spy_consecutive_down_days} consecutive days"

        # Breadth collapse
        if self.internal_breadth.get('pct_above_20ema', 0) < RecoveryModeConfig.BREADTH_LOCK_THRESHOLD:
            return True, f"Breadth collapsed ({self.internal_breadth.get('pct_above_20ema', 0):.0f}%)"

        # Price breaks swing low (structure failed)
        if self.swing_low_price and self.spy_close < self.swing_low_price * 0.99:
            return True, f"Price broke swing low (${self.spy_close:.2f} < ${self.swing_low_price:.2f})"

        return False, None

    def exit_recovery_mode(self, reason):
        """Exit recovery mode and reset structure state"""
        if self.recovery_mode_active:
            self.recovery_mode_active = False
            self.recovery_mode_start_date = None
            self._reset_structure_state()
            print(f"🔒 RECOVERY MODE EXITED: {reason}")
            return True
        return False

    # =========================================================================
    # LOCK MANAGEMENT
    # =========================================================================

    def start_lock(self, current_date):
        """Start lock when SPY drops below 200 SMA"""
        if not self.lock_start_date:
            self.lock_start_date = current_date
            print(f"🔒 LOCK STARTED: SPY below 200 SMA")

    def clear_lock(self):
        """Clear lock when SPY recovers above 200 SMA"""
        if self.lock_start_date or self.recovery_mode_active:
            print(f"🔓 LOCK CLEARED: SPY above 200 SMA")
        self.lock_start_date = None
        self.recovery_mode_active = False
        self.recovery_mode_start_date = None
        self._reset_structure_state()

    # =========================================================================
    # MAIN EVALUATION
    # =========================================================================

    def evaluate(self, current_date, spy_below_200):
        """Main evaluation - called each trading day"""

        # If SPY above 200 SMA, clear everything and return normal
        if not spy_below_200:
            self.clear_lock()
            return {
                'recovery_mode_active': False,
                'position_multiplier': 1.0,
                'max_positions': 25,
                'allow_entries': True,
                'profit_target': 10.0,
                'signals': {},
                'reason': 'Normal (SPY > 200 SMA)'
            }

        # Start lock if not already locked
        self.start_lock(current_date)

        # Check for recovery mode exit
        if self.recovery_mode_active:
            should_exit, exit_reason = self.check_recovery_mode_exit(current_date)
            if should_exit:
                self.exit_recovery_mode(exit_reason)

        # Check for recovery mode entry
        if not self.recovery_mode_active and self.check_recovery_mode_entry(current_date):
            self.enter_recovery_mode(current_date)

        # Build status
        structure_status = self._get_structure_status()

        if self.recovery_mode_active:
            max_positions = (RecoveryModeConfig.RECOVERY_MAX_POSITIONS_HIGHER_LOW
                             if self.is_higher_low
                             else RecoveryModeConfig.RECOVERY_MAX_POSITIONS)
            return {
                'recovery_mode_active': True,
                'position_multiplier': RecoveryModeConfig.RECOVERY_POSITION_MULTIPLIER,
                'max_positions': max_positions,
                'allow_entries': True,
                'profit_target': RecoveryModeConfig.RECOVERY_PROFIT_TARGET,
                'signals': structure_status,
                'reason': f"Recovery Mode (Higher Low: {self.is_higher_low})"
            }

        # Locked but not in recovery
        return {
            'recovery_mode_active': False,
            'position_multiplier': 0.0,
            'max_positions': 0,
            'allow_entries': False,
            'profit_target': 10.0,
            'signals': structure_status,
            'reason': self._get_waiting_reason()
        }

    def _get_structure_status(self):
        """Get current structure detection status"""
        return {
            'capitulation_detected': self.capitulation_detected,
            'capitulation_date': self.capitulation_date,
            'capitulation_low': self.capitulation_low,
            'swing_low_confirmed': self.swing_low_confirmed,
            'swing_low_price': self.swing_low_price,
            'follow_through_detected': self.follow_through_detected,
            'is_higher_low': self.is_higher_low,
            'prior_swing_low': self.prior_swing_low
        }

    def _get_waiting_reason(self):
        """Get human-readable status of what we're waiting for"""
        if not self.capitulation_detected:
            return "Locked: Waiting for capitulation (selloff)"
        elif not self.swing_low_confirmed:
            return f"Locked: Capitulation at ${self.capitulation_low:.2f}, waiting for swing low confirmation"
        elif not self.follow_through_detected:
            days_since = (self.spy_price_history[-1]['date'] - self.swing_low_date).days if self.swing_low_date else 0
            return f"Locked: Swing low ${self.swing_low_price:.2f}, waiting for follow-through (day {days_since}/{RecoveryModeConfig.FOLLOW_THROUGH_WINDOW_DAYS})"
        else:
            return "Locked: Structure complete, entering recovery"

    # =========================================================================
    # STATISTICS / COMPATIBILITY
    # =========================================================================

    def get_statistics(self):
        """Get current state for logging and persistence"""
        return {
            'recovery_mode_active': self.recovery_mode_active,
            'activation_count': self.activation_count,
            'lock_start_date': self.lock_start_date,
            'spy_ema10': round(self.spy_ema10, 2),
            'spy_ema21': round(self.spy_ema21, 2),
            'spy_consecutive_down_days': self.spy_consecutive_down_days,
            'internal_breadth': self.internal_breadth,
            # Structure state
            'capitulation_detected': self.capitulation_detected,
            'capitulation_date': self.capitulation_date,
            'capitulation_low': self.capitulation_low,
            'swing_low_confirmed': self.swing_low_confirmed,
            'swing_low_price': self.swing_low_price,
            'follow_through_detected': self.follow_through_detected,
            'is_higher_low': self.is_higher_low,
            'prior_swing_low': self.prior_swing_low,
        }

    def count_recovery_signals(self):
        """Compatibility method - returns structure status as signals"""
        signals = {
            'capitulation': self.capitulation_detected,
            'swing_low': self.swing_low_confirmed,
            'follow_through': self.follow_through_detected,
            'higher_low': self.is_higher_low,
            'breadth_improving': self.internal_breadth.get('pct_above_20ema', 0) > 25,
            'spy_above_ema10': self.spy_close > self.spy_ema10 if self.spy_ema10 > 0 else False,
        }
        signals['total'] = sum(1 for v in signals.values() if v is True)
        return signals

    def trigger_relock(self, current_date, reason):
        """Compatibility method"""
        return self.exit_recovery_mode(reason)