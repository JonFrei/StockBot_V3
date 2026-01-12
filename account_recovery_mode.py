"""
Recovery Mode System - Dual-Track Bottom Detection

TRACK 1: STRUCTURE-BASED (High Conviction)
    Phase 1: Capitulation - SPY down 1.5%+ on volume OR 3 days -4%
    Phase 2: Swing Low - Price holds above capitulation low
    Phase 3: Follow-Through - SPY up 1.25%+ on volume OR +1.0% above EMA10
    → Full position sizing, all active tier stocks

TRACK 2: TIME-BASED FALLBACK (Lower Conviction)
    Conditions: 15+ days locked AND stabilization signal
    Stabilization: 3 higher lows OR SPY > 10 EMA for 2 days OR within 2% of 20 EMA
    → Reduced sizing (0.5x), premium tier only, tighter stops

SCOPE: Applies to ALL lockout types (CRISIS_LOCKOUT + TREND_BLOCK)
"""

from datetime import timedelta


class RecoveryModeConfig:
    # =========================================================================
    # TRACK 1: STRUCTURE-BASED (High Conviction)
    # =========================================================================

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
    FOLLOW_THROUGH_MIN_WAIT = 1  # Minimum days after swing low

    # === TRACK 1 RECOVERY SETTINGS ===
    RECOVERY_POSITION_MULTIPLIER = 1.0
    RECOVERY_MAX_POSITIONS = 8
    RECOVERY_MAX_POSITIONS_HIGHER_LOW = 10  # More positions if higher low confirmed

    # =========================================================================
    # TRACK 2: TIME-BASED FALLBACK (Lower Conviction)
    # =========================================================================

    # === TIME-BASED ENTRY CONDITIONS ===
    TIME_BASED_MIN_LOCKOUT_DAYS = 15  # Minimum days locked before eligible
    TIME_BASED_HIGHER_LOWS_REQUIRED = 3  # Consecutive higher daily lows
    TIME_BASED_EMA10_DAYS_ABOVE = 2  # Days SPY must be above EMA10
    TIME_BASED_EMA20_PROXIMITY_PCT = 2.0  # Within X% of 20 EMA = consolidating
    TIME_BASED_NO_NEW_LOW_DAYS = 3  # No new 5-day low in past N days

    # === TRACK 2 CAUTIOUS SETTINGS ===
    CAUTIOUS_POSITION_MULTIPLIER = 0.5  # Half position size
    CAUTIOUS_MAX_POSITIONS = 6  # Fewer positions

    # =========================================================================
    # SHARED EXIT CONDITIONS
    # =========================================================================
    RECOVERY_GRACE_PERIOD_DAYS = 2  # Days before exit conditions are checked (allow positions to be opened)
    RELOCK_ON_SPY_DOWN_DAYS = 3  # Exit after 3 consecutive down days
    RECOVERY_MODE_MAX_DAYS = 14  # Max days in recovery without graduating
    BREADTH_LOCK_THRESHOLD = 15.0  # Exit if breadth collapses below 15%
    RELOCK_ON_NEW_LOW_DAYS = 10  # Exit if SPY makes new 10-day low
    RELOCK_ON_PORTFOLIO_DROP_PCT = 3.0  # Exit if portfolio drops 3% from recovery entry


class RecoveryModeManager:
    def __init__(self):
        # Recovery state
        self.recovery_mode_active = False
        self.recovery_mode_start_date = None
        self.recovery_entry_method = None  # 'structure' or 'time_based'
        self.lock_start_date = None
        self.activation_count = 0

        # Portfolio tracking for exit conditions
        self.portfolio_value_at_entry = None

        # SPY tracking
        self.spy_close = 0
        self.spy_prev_close = 0
        self.spy_ema10 = 0
        self.spy_ema20 = 0
        self.spy_ema21 = 0
        self.spy_consecutive_down_days = 0
        self.spy_price_history = []  # Full OHLCV history

        # Breadth tracking
        self.internal_breadth = {'pct_above_20ema': 0, 'pct_above_50sma': 0, 'pct_green_today': 0}
        self.recent_accum_days = 0
        self.recent_dist_days = 0

        # === TRACK 1: STRUCTURE TRACKING ===
        self.capitulation_detected = False
        self.capitulation_date = None
        self.capitulation_low = None

        self.swing_low_confirmed = False
        self.swing_low_date = None
        self.swing_low_price = None

        self.follow_through_detected = False
        self.follow_through_date = None

        self.prior_swing_low = None
        self.is_higher_low = False

        # === TRACK 2: TIME-BASED TRACKING ===
        self.higher_lows_count = 0
        self.previous_daily_low = None
        self.days_above_ema10 = 0
        self.spy_5_day_low = None

    # =========================================================================
    # DATA UPDATE METHODS
    # =========================================================================

    def update_spy_data(self, date, spy_close, spy_open=None, spy_high=None, spy_low=None,
                        spy_volume=None, spy_avg_volume=None, spy_prev_close=None,
                        spy_ema10=None, spy_ema20=None):
        """Update SPY data and run detection for both tracks"""

        # Store previous close
        if spy_prev_close:
            self.spy_prev_close = spy_prev_close
        elif self.spy_close > 0:
            self.spy_prev_close = self.spy_close

        self.spy_close = spy_close

        # Track EMA10
        if spy_ema10:
            self.spy_ema10 = spy_ema10
        elif self.spy_ema10 == 0:
            self.spy_ema10 = spy_close
        else:
            self.spy_ema10 = spy_close * (2 / 11) + self.spy_ema10 * (9 / 11)

        # Track EMA20
        if spy_ema20:
            self.spy_ema20 = spy_ema20
        elif self.spy_ema20 == 0:
            self.spy_ema20 = spy_close
        else:
            self.spy_ema20 = spy_close * (2 / 21) + self.spy_ema20 * (19 / 21)

        # Update EMA21 (legacy compatibility)
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

        # Update 5-day low for exit conditions
        if len(self.spy_price_history) >= 5:
            recent_lows = [b['low'] for b in self.spy_price_history[-5:]]
            self.spy_5_day_low = min(recent_lows)

        # === TRACK 1: Structure detection ===
        self._detect_capitulation(date)
        self._detect_swing_low(date)
        self._detect_follow_through(date)

        # === TRACK 2: Time-based detection ===
        self._update_higher_lows(spy_low or spy_close)
        self._update_ema10_tracking()

    def _update_higher_lows(self, current_low):
        """Track consecutive higher daily lows for time-based entry"""
        if self.previous_daily_low is None:
            self.previous_daily_low = current_low
            self.higher_lows_count = 0
            return

        if current_low > self.previous_daily_low:
            self.higher_lows_count += 1
        else:
            self.higher_lows_count = 0

        self.previous_daily_low = current_low

    def _update_ema10_tracking(self):
        """Track days SPY is above EMA10"""
        if self.spy_ema10 > 0 and self.spy_close > self.spy_ema10:
            self.days_above_ema10 += 1
        else:
            self.days_above_ema10 = 0

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

    def update_portfolio_value(self, portfolio_value):
        """Update portfolio value for exit condition tracking"""
        if self.recovery_mode_active and self.portfolio_value_at_entry is None:
            self.portfolio_value_at_entry = portfolio_value

    # =========================================================================
    # TRACK 1: CAPITULATION DETECTION (Phase 1)
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
                    lowest_low = min(bar['low'] for bar in recent_bars[1:])
                    self._set_capitulation(current_date, lowest_low, "multi-day")

    def _set_capitulation(self, date, low_price, method):
        """Record capitulation event"""
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
    # TRACK 1: SWING LOW CONFIRMATION (Phase 2)
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

        if days_since_cap < RecoveryModeConfig.SWING_LOW_HOLD_DAYS:
            return

        recent_bars = [b for b in self.spy_price_history if b['date'] > self.capitulation_date]

        if len(recent_bars) < RecoveryModeConfig.SWING_LOW_HOLD_DAYS:
            return

        # All recent lows must be above capitulation low (with tolerance)
        held_above = all(bar['low'] >= self.capitulation_low * 0.998
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
    # TRACK 1: FOLLOW-THROUGH DAY DETECTION (Phase 3)
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

        if days_since_swing < RecoveryModeConfig.FOLLOW_THROUGH_MIN_WAIT:
            return

        if days_since_swing > RecoveryModeConfig.FOLLOW_THROUGH_WINDOW_DAYS:
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
    # TRACK 2: TIME-BASED ENTRY CHECK
    # =========================================================================

    def _check_time_based_entry(self, current_date):
        """
        Check if time-based (Track 2) entry conditions are met

        Requires ALL of:
        1. Lockout duration >= 15 trading days
        2. Stabilization signal (one of):
           - 3 consecutive higher daily lows
           - SPY > 10 EMA for 2 consecutive days
           - SPY within 2% of 20 EMA (consolidating)
        3. No new 5-day low in past 3 trading days

        Returns:
            tuple: (eligible: bool, reason: str)
        """
        if not self.lock_start_date:
            return False, "No lock active"

        # Condition 1: Minimum lockout duration
        days_locked = (current_date - self.lock_start_date).days
        if days_locked < RecoveryModeConfig.TIME_BASED_MIN_LOCKOUT_DAYS:
            return False, f"Only {days_locked} days locked (need {RecoveryModeConfig.TIME_BASED_MIN_LOCKOUT_DAYS})"

        # Condition 3: No new 5-day low recently (check first as it's a blocker)
        if len(self.spy_price_history) >= 5:
            recent_closes = [b['close'] for b in
                             self.spy_price_history[-RecoveryModeConfig.TIME_BASED_NO_NEW_LOW_DAYS:]]
            if self.spy_5_day_low and min(recent_closes) <= self.spy_5_day_low * 1.001:
                # Check if the new low was in the last 3 days
                recent_lows = [b['low'] for b in
                               self.spy_price_history[-RecoveryModeConfig.TIME_BASED_NO_NEW_LOW_DAYS:]]
                five_day_lows_before = [b['low'] for b in self.spy_price_history[-8:-3]] if len(
                    self.spy_price_history) >= 8 else []
                if five_day_lows_before and min(recent_lows) < min(five_day_lows_before) * 0.999:
                    return False, "New 5-day low detected recently"

        # Condition 2: Stabilization signal (need at least one)
        stabilization_met = False
        stabilization_method = None

        # Method A: 3 consecutive higher daily lows
        if self.higher_lows_count >= RecoveryModeConfig.TIME_BASED_HIGHER_LOWS_REQUIRED:
            stabilization_met = True
            stabilization_method = f"{self.higher_lows_count} higher lows"

        # Method B: SPY above 10 EMA for 2+ days
        if not stabilization_met and self.days_above_ema10 >= RecoveryModeConfig.TIME_BASED_EMA10_DAYS_ABOVE:
            stabilization_met = True
            stabilization_method = f"SPY > EMA10 for {self.days_above_ema10} days"

        # Method C: SPY within 2% of 20 EMA (consolidating, not crashing)
        if not stabilization_met and self.spy_ema20 > 0:
            distance_to_ema20 = abs(self.spy_close - self.spy_ema20) / self.spy_ema20 * 100
            if distance_to_ema20 <= RecoveryModeConfig.TIME_BASED_EMA20_PROXIMITY_PCT:
                stabilization_met = True
                stabilization_method = f"SPY within {distance_to_ema20:.1f}% of EMA20"

        if not stabilization_met:
            return False, f"No stabilization signal (higher_lows={self.higher_lows_count}, days_above_ema10={self.days_above_ema10})"

        return True, stabilization_method

    # =========================================================================
    # RECOVERY MODE ENTRY/EXIT
    # =========================================================================

    def check_recovery_mode_entry(self, current_date):
        """
        Check both tracks for recovery mode entry

        Track 1 (Structure): Capitulation → Swing Low → Follow-Through
        Track 2 (Time-Based): 15+ days locked + stabilization

        Returns:
            tuple: (should_enter: bool, method: str or None)
        """
        if self.recovery_mode_active:
            return False, None

        if not self.lock_start_date:
            return False, None

        # === TRACK 1: Structure-based (higher priority) ===
        if self.follow_through_detected:
            print(f"✅ STRUCTURE CONFIRMED: Capitulation → Swing Low → Follow-Through")
            return True, 'structure'

        # === TRACK 2: Time-based fallback ===
        time_eligible, time_reason = self._check_time_based_entry(current_date)
        if time_eligible:
            print(f"✅ TIME-BASED ENTRY: {time_reason}")
            return True, 'time_based'

        return False, None

    def enter_recovery_mode(self, current_date, method='structure'):
        """Enter recovery mode with specified method"""
        self.activation_count += 1
        self.recovery_mode_active = True
        self.recovery_mode_start_date = current_date
        self.recovery_entry_method = method
        self.portfolio_value_at_entry = None  # Will be set on next portfolio update

        if method == 'structure':
            # Track 1: Full recovery mode
            max_positions = (RecoveryModeConfig.RECOVERY_MAX_POSITIONS_HIGHER_LOW
                             if self.is_higher_low
                             else RecoveryModeConfig.RECOVERY_MAX_POSITIONS)
            mode_name = "FULL"
            # eligible_tiers = RecoveryModeConfig.RECOVERY_ELIGIBLE_TIERS
        else:
            # Track 2: Cautious recovery mode
            max_positions = RecoveryModeConfig.CAUTIOUS_MAX_POSITIONS
            mode_name = "CAUTIOUS"
            # eligible_tiers = RecoveryModeConfig.CAUTIOUS_ELIGIBLE_TIERS

        print(f"\n{'=' * 60}")
        print(f"🔓 RECOVERY MODE ACTIVATED - {mode_name} (#{self.activation_count})")
        print(
            f"   Method: {'Structure (Capitulation → Swing Low → Follow-Through)' if method == 'structure' else 'Time-Based Fallback'}")
        if method == 'structure' and self.is_higher_low:
            print(f"   Higher Low: YES (increased conviction)")
        if method == 'structure' and self.swing_low_price:
            print(f"   Swing Low: ${self.swing_low_price:.2f} on {self.swing_low_date.strftime('%Y-%m-%d')}")
        print(f"   Max Positions: {max_positions}")
        # print(f"   Eligible Tiers: {', '.join(eligible_tiers)}")
        if method == 'time_based':
            print(f"   Position Sizing: {RecoveryModeConfig.CAUTIOUS_POSITION_MULTIPLIER}x (reduced)")
            # print(f"   Stop Multiplier: {RecoveryModeConfig.CAUTIOUS_STOP_MULTIPLIER}x (tighter)")
        print(f"{'=' * 60}\n")

    def check_recovery_mode_exit(self, current_date, portfolio_value=None, deployed_capital=0):
        """
        Check if recovery mode should exit

        Exit conditions:
        1. Max duration exceeded (14 days)
        2. 3 consecutive down days
        3. Breadth collapse (only when positions are open)
        4. Price breaks swing low (structure) or new 10-day low
        5. Portfolio drops 3% from entry (if tracking)
        """
        if not self.recovery_mode_active:
            return False, None

        # Update portfolio tracking
        if portfolio_value and self.portfolio_value_at_entry is None:
            self.portfolio_value_at_entry = portfolio_value

        # Calculate days active
        days_active = (current_date - self.recovery_mode_start_date).days

        # Condition 1: Max duration
        if days_active > RecoveryModeConfig.RECOVERY_MODE_MAX_DAYS:
            return True, f"Max duration ({RecoveryModeConfig.RECOVERY_MODE_MAX_DAYS} days)"

        # Condition 2: Consecutive down days (only after grace period)
        if days_active >= RecoveryModeConfig.RECOVERY_GRACE_PERIOD_DAYS:
            if self.spy_consecutive_down_days >= RecoveryModeConfig.RELOCK_ON_SPY_DOWN_DAYS:
                return True, f"SPY down {self.spy_consecutive_down_days} consecutive days"

        # Condition 3: Breadth collapse
        # Skip if: no positions deployed OR within grace period
        if deployed_capital > 0 and days_active >= RecoveryModeConfig.RECOVERY_GRACE_PERIOD_DAYS:
            breadth_pct = self.internal_breadth.get('pct_above_20ema', 100)  # Default to 100 if not set
            if breadth_pct < RecoveryModeConfig.BREADTH_LOCK_THRESHOLD:
                return True, f"Breadth collapsed ({breadth_pct:.0f}%)"

        # Condition 4a: Price breaks swing low (structure-based)
        if self.recovery_entry_method == 'structure' and self.swing_low_price:
            if self.spy_close < self.swing_low_price * 0.99:
                return True, f"Price broke swing low (${self.spy_close:.2f} < ${self.swing_low_price:.2f})"

        # Condition 4b: New 10-day low (both methods) - only after grace period
        if days_active >= RecoveryModeConfig.RECOVERY_GRACE_PERIOD_DAYS:
            if len(self.spy_price_history) >= 10:
                ten_day_lows = [b['low'] for b in self.spy_price_history[-10:]]
                ten_day_low = min(ten_day_lows)
                if self.spy_close < ten_day_low * 0.999:
                    return True, f"SPY made new 10-day low (${self.spy_close:.2f})"

        # Condition 5: Portfolio drop from entry (only when positions are open)
        if deployed_capital > 0 and portfolio_value and self.portfolio_value_at_entry:
            drop_pct = (self.portfolio_value_at_entry - portfolio_value) / self.portfolio_value_at_entry * 100
            if drop_pct >= RecoveryModeConfig.RELOCK_ON_PORTFOLIO_DROP_PCT:
                return True, f"Portfolio dropped {drop_pct:.1f}% from recovery entry"

        return False, None

    def exit_recovery_mode(self, reason):
        """Exit recovery mode and reset state"""
        if self.recovery_mode_active:
            method = self.recovery_entry_method or 'unknown'
            self.recovery_mode_active = False
            self.recovery_mode_start_date = None
            self.recovery_entry_method = None
            self.portfolio_value_at_entry = None
            self._reset_structure_state()
            self._reset_time_based_state()
            print(f"🔒 RECOVERY MODE EXITED ({method}): {reason}")
            return True
        return False

    def _reset_time_based_state(self):
        """Reset time-based tracking"""
        self.higher_lows_count = 0
        self.days_above_ema10 = 0

    # =========================================================================
    # LOCK MANAGEMENT
    # =========================================================================

    def start_lock(self, current_date, reason="SPY below 200 SMA"):
        """Start lock for any lockout type"""
        if not self.lock_start_date:
            self.lock_start_date = current_date
            # Reset time-based tracking on new lock
            self._reset_time_based_state()
            print(f"🔒 LOCK STARTED: {reason}")

    def clear_lock(self):
        """Clear lock when conditions normalize"""
        if self.lock_start_date or self.recovery_mode_active:
            print(f"🔓 LOCK CLEARED: Conditions normalized")
        self.lock_start_date = None
        self.recovery_mode_active = False
        self.recovery_mode_start_date = None
        self.recovery_entry_method = None
        self.portfolio_value_at_entry = None
        self._reset_structure_state()
        self._reset_time_based_state()

    # =========================================================================
    # MAIN EVALUATION
    # =========================================================================

    def evaluate(self, current_date, spy_below_200, lockout_type=None, lockout_active=False, deployed_capital=0):
        """
        Main evaluation - called each trading day

        Args:
            current_date: Current date
            spy_below_200: Whether SPY is below 200 SMA
            lockout_type: Type of lockout ('crisis', 'trend_block', etc.)
            lockout_active: Whether any lockout is currently active
            deployed_capital: Current deployed capital (for breadth check)

        Returns:
            dict with recovery mode settings
        """
        # Normalize to naive datetime for day calculations (handles both backtest and live)
        if hasattr(current_date, 'tzinfo') and current_date.tzinfo is not None:
            current_date = current_date.replace(tzinfo=None)

        # Determine if we should be tracking for recovery
        should_track = spy_below_200 or lockout_active

        # If no lockout conditions, clear everything and return normal
        if not should_track:
            self.clear_lock()
            return {
                'recovery_mode_active': False,
                'recovery_entry_method': None,
                'position_multiplier': 1.0,
                'max_positions': 25,
                # 'allow_entries': True,
                # 'profit_target': 10.0,
                # 'stop_multiplier': 1.0,
                # 'eligible_tiers': ['premium', 'active', 'probation'],
                'signals': {},
                'reason': 'Normal'
            }

        # Start lock if not already locked
        lock_reason = lockout_type or ('SPY below 200 SMA' if spy_below_200 else 'Lockout active')
        self.start_lock(current_date, lock_reason)

        # Check for recovery mode exit (pass deployed_capital for breadth check)
        if self.recovery_mode_active:
            should_exit, exit_signal = self.check_recovery_mode_exit(
                current_date,
                deployed_capital=deployed_capital
            )
            if should_exit:
                self.exit_recovery_mode(exit_signal)

        # Check for recovery mode entry (both tracks)
        if not self.recovery_mode_active:
            should_enter, entry_method = self.check_recovery_mode_entry(current_date)
            if should_enter:
                self.enter_recovery_mode(current_date, entry_method)

        # Build status
        structure_status = self._get_structure_status()
        time_status = self._get_time_based_status(current_date)

        if self.recovery_mode_active:
            if self.recovery_entry_method == 'structure':
                # Full recovery mode (Track 1)
                return {
                    'recovery_mode_active': True,
                    'recovery_entry_method': 'structure',
                    'position_multiplier': RecoveryModeConfig.RECOVERY_POSITION_MULTIPLIER,
                    'max_positions': RecoveryModeConfig.RECOVERY_MAX_POSITIONS,
                    # 'allow_entries': True,
                    # 'profit_target': RecoveryModeConfig.RECOVERY_PROFIT_TARGET,
                    # 'stop_multiplier': RecoveryModeConfig.RECOVERY_STOP_MULTIPLIER,
                    # 'eligible_tiers': RecoveryModeConfig.RECOVERY_ELIGIBLE_TIERS,
                    'signals': {**structure_status, **time_status},
                    'reason': f"Recovery Mode (Structure): Follow-through confirmed"
                }
            else:
                # Cautious recovery mode (Track 2)
                return {
                    'recovery_mode_active': True,
                    'recovery_entry_method': 'time_based',
                    'position_multiplier': RecoveryModeConfig.CAUTIOUS_POSITION_MULTIPLIER,
                    'max_positions': RecoveryModeConfig.CAUTIOUS_MAX_POSITIONS,
                    #'allow_entries': True,
                    # 'profit_target': RecoveryModeConfig.CAUTIOUS_PROFIT_TARGET,
                    # 'stop_multiplier': RecoveryModeConfig.CAUTIOUS_STOP_MULTIPLIER,
                    # 'eligible_tiers': RecoveryModeConfig.CAUTIOUS_ELIGIBLE_TIERS,
                    'signals': {**structure_status, **time_status},
                    'reason': f"Recovery Mode (Time-based): Stabilization detected"
                }

        # Not in recovery mode yet - return waiting status
        return {
            'recovery_mode_active': False,
            'recovery_entry_method': None,
            'position_multiplier': 0.0,
            'max_positions': 0,
            # 'allow_entries': False,
            # 'profit_target': 10.0,
            # 'stop_multiplier': 1.0,
            # 'eligible_tiers': [],
            'signals': {**structure_status, **time_status},
            'reason': self._get_waiting_reason(current_date)
        }

    def _get_structure_status(self):
        """Get current structure detection status"""
        return {
            'track1_capitulation_detected': self.capitulation_detected,
            'track1_capitulation_date': self.capitulation_date,
            'track1_capitulation_low': self.capitulation_low,
            'track1_swing_low_confirmed': self.swing_low_confirmed,
            'track1_swing_low_price': self.swing_low_price,
            'track1_follow_through_detected': self.follow_through_detected,
            'track1_is_higher_low': self.is_higher_low,
            'track1_prior_swing_low': self.prior_swing_low
        }

    def _get_time_based_status(self, current_date):
        """Get current time-based detection status"""
        days_locked = (current_date - self.lock_start_date).days if self.lock_start_date else 0
        ema20_distance = abs(self.spy_close - self.spy_ema20) / self.spy_ema20 * 100 if self.spy_ema20 > 0 else 999

        return {
            'track2_days_locked': days_locked,
            'track2_min_days_required': RecoveryModeConfig.TIME_BASED_MIN_LOCKOUT_DAYS,
            'track2_higher_lows_count': self.higher_lows_count,
            'track2_days_above_ema10': self.days_above_ema10,
            'track2_ema20_distance_pct': round(ema20_distance, 2),
            'track2_eligible': days_locked >= RecoveryModeConfig.TIME_BASED_MIN_LOCKOUT_DAYS
        }

    def _get_waiting_reason(self, current_date):
        """Get human-readable status of what we're waiting for"""
        days_locked = (current_date - self.lock_start_date).days if self.lock_start_date else 0

        # Track 1 status
        if not self.capitulation_detected:
            track1_status = "waiting for capitulation"
        elif not self.swing_low_confirmed:
            track1_status = f"capitulation at ${self.capitulation_low:.2f}, waiting for swing low"
        elif not self.follow_through_detected:
            days_since = (current_date - self.swing_low_date).days if self.swing_low_date else 0
            track1_status = f"swing low ${self.swing_low_price:.2f}, waiting for follow-through (day {days_since}/{RecoveryModeConfig.FOLLOW_THROUGH_WINDOW_DAYS})"
        else:
            track1_status = "ready"

        # Track 2 status
        if days_locked < RecoveryModeConfig.TIME_BASED_MIN_LOCKOUT_DAYS:
            track2_status = f"day {days_locked}/{RecoveryModeConfig.TIME_BASED_MIN_LOCKOUT_DAYS}"
        else:
            track2_status = f"day {days_locked}, waiting for stabilization (HL={self.higher_lows_count}, EMA10={self.days_above_ema10}d)"

        return f"Locked: Track1[{track1_status}] | Track2[{track2_status}]"

    # =========================================================================
    # STATISTICS / COMPATIBILITY
    # =========================================================================

    def get_statistics(self):
        """Get current state for logging and persistence"""
        return {
            'recovery_mode_active': self.recovery_mode_active,
            'recovery_entry_method': self.recovery_entry_method,
            'activation_count': self.activation_count,
            'lock_start_date': self.lock_start_date,
            'spy_ema10': round(self.spy_ema10, 2),
            'spy_ema20': round(self.spy_ema20, 2),
            'spy_ema21': round(self.spy_ema21, 2),
            'spy_consecutive_down_days': self.spy_consecutive_down_days,
            'internal_breadth': self.internal_breadth,
            # Track 1: Structure state
            'capitulation_detected': self.capitulation_detected,
            'capitulation_date': self.capitulation_date,
            'capitulation_low': self.capitulation_low,
            'swing_low_confirmed': self.swing_low_confirmed,
            'swing_low_price': self.swing_low_price,
            'follow_through_detected': self.follow_through_detected,
            'is_higher_low': self.is_higher_low,
            'prior_swing_low': self.prior_swing_low,
            # Track 2: Time-based state
            'higher_lows_count': self.higher_lows_count,
            'days_above_ema10': self.days_above_ema10,
        }

    def count_recovery_signals(self):
        """Compatibility method - returns combined status"""
        signals = {
            # Track 1
            'capitulation': self.capitulation_detected,
            'swing_low': self.swing_low_confirmed,
            'follow_through': self.follow_through_detected,
            'higher_low': self.is_higher_low,
            # Track 2
            'time_based_eligible': self.higher_lows_count >= RecoveryModeConfig.TIME_BASED_HIGHER_LOWS_REQUIRED or self.days_above_ema10 >= RecoveryModeConfig.TIME_BASED_EMA10_DAYS_ABOVE,
            # Shared
            'breadth_improving': self.internal_breadth.get('pct_above_20ema', 0) > 25,
            'spy_above_ema10': self.spy_close > self.spy_ema10 if self.spy_ema10 > 0 else False,
        }
        signals['total'] = sum(1 for v in signals.values() if v is True)
        return signals

    def trigger_relock(self, current_date, reason):
        """Compatibility method"""
        return self.exit_recovery_mode(reason)

    '''
    def is_tier_eligible(self, tier):
        """Check if a tier is eligible for trading in current mode"""
        if not self.recovery_mode_active:
            return True  # Normal mode - all tiers eligible

        if self.recovery_entry_method == 'structure':
            return tier in RecoveryModeConfig.RECOVERY_ELIGIBLE_TIERS
        else:
            return tier in RecoveryModeConfig.CAUTIOUS_ELIGIBLE_TIERS
    '''
