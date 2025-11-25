"""
Market Safeguard System - ENHANCED IBD-STYLE

Based on Investor's Business Daily methodology with improvements:
1. Distribution Days: Institutional selling (down ≥0.4% on volume up ≥25%)
2. Accumulation Days: Institutional buying (up ≥0.4% on volume up ≥25%) - OFFSETS distribution
3. Follow-Through Day: Confirms new uptrend (up ≥1.5% on higher volume, day 4+ of rally)
4. Options Expiration Filter: Skips monthly opex from distribution count
5. Dual SMA Check: 50 SMA early warning, 200 SMA full stop

Regime Priority:
1. SPY below 200 SMA → STOP_BUYING
2. SPY below 50 SMA → CAUTION (early warning)
3. Net Distribution ≥ 6 → EXIT_ALL (wait for follow-through)
4. Net Distribution 5 → STOP_BUYING
5. Net Distribution 4 → WARNING (50% size)
6. Net Distribution 3 → CAUTION (75% size)
7. Otherwise → NORMAL
"""

from datetime import datetime, timedelta
import calendar


class SafeguardConfig:
    """Enhanced safeguard configuration"""

    # Distribution/Accumulation Day Thresholds (tightened from original)
    DISTRIBUTION_DAY_PRICE_THRESHOLD = -0.4  # Was -0.2%
    ACCUMULATION_DAY_PRICE_THRESHOLD = 0.4  # NEW: +0.4% for accumulation
    VOLUME_THRESHOLD = 25.0  # Was 20%, now 25%

    # Lookback period
    DISTRIBUTION_LOOKBACK_DAYS = 25

    # Net distribution thresholds (distribution - accumulation)
    NET_DISTRIBUTION_CAUTION = 3
    NET_DISTRIBUTION_WARNING = 4
    NET_DISTRIBUTION_DANGER = 5
    NET_DISTRIBUTION_EXIT = 6

    # Position size multipliers
    CAUTION_SIZE_MULTIPLIER = 0.75
    WARNING_SIZE_MULTIPLIER = 0.50
    DANGER_SIZE_MULTIPLIER = 0.0

    # Follow-Through Day Requirements
    FTD_MIN_RALLY_DAYS = 4  # Must be day 4+ of rally attempt
    FTD_MIN_PRICE_GAIN = 1.5  # Must gain ≥1.5%
    FTD_REQUIRE_HIGHER_VOLUME = True  # Volume must be higher than previous day

    # Early warning
    EARLY_WARNING_ENABLED = True  # Use 50 SMA as early warning


class MarketRegimeDetector:
    """
    Enhanced IBD-style market regime detection

    Tracks both distribution AND accumulation days.
    Uses follow-through day for re-entry confirmation.
    """

    def __init__(self):
        # Distribution/Accumulation tracking
        self.distribution_days = []  # {'date', 'price_change', 'volume_change'}
        self.accumulation_days = []  # {'date', 'price_change', 'volume_change'}

        # SPY data
        self.spy_close = 0
        self.spy_prev_close = 0
        self.spy_50_sma = 0
        self.spy_200_sma = 0
        self.spy_volume = 0
        self.spy_prev_volume = 0

        # Rally attempt / Follow-through tracking
        self.in_rally_attempt = False
        self.rally_attempt_start = None
        self.rally_attempt_low = None
        self.rally_day_count = 0
        self.follow_through_confirmed = False
        self.last_ftd_date = None

        # Exit state
        self.exit_triggered = False
        self.exit_date = None

    # =========================================================================
    # MAIN METHOD
    # =========================================================================

    def detect_regime(self, num_positions=0, current_date=None):
        """
        Unified regime detection

        Returns:
            dict with action, multiplier, allow_new_entries, reason, details
        """
        # Expire old days
        if current_date:
            self._expire_old_days(current_date)

        # Get current state
        spy_below_200 = self._is_spy_below_200()
        spy_below_50 = self._is_spy_below_50()
        net_distribution = self._get_net_distribution()
        dist_level = self._get_distribution_level(net_distribution)

        # Build details dict
        details = {
            'spy_close': self.spy_close,
            'spy_50_sma': self.spy_50_sma,
            'spy_200_sma': self.spy_200_sma,
            'spy_below_50': spy_below_50,
            'spy_below_200': spy_below_200,
            'distribution_count': len(self.distribution_days),
            'accumulation_count': len(self.accumulation_days),
            'net_distribution': net_distribution,
            'distribution_level': dist_level,
            'in_rally_attempt': self.in_rally_attempt,
            'rally_day_count': self.rally_day_count,
            'follow_through_confirmed': self.follow_through_confirmed,
            'in_recovery': self.exit_triggered
        }

        # =================================================================
        # CHECK EXIT RECOVERY STATE
        # =================================================================
        if self.exit_triggered:
            if self._check_follow_through(current_date):
                # Follow-through confirmed - exit recovery
                self.exit_triggered = False
                self.exit_date = None
                self.follow_through_confirmed = True
                self.last_ftd_date = current_date
                details['follow_through_confirmed'] = True
            else:
                # Still waiting for follow-through
                return self._recovery_response(current_date, details)

        # =================================================================
        # PRIORITY 1: SPY below 200 SMA (DrawdownProtection)
        # =================================================================
        if spy_below_200:
            return {
                'action': 'stop_buying',
                'position_size_multiplier': SafeguardConfig.DANGER_SIZE_MULTIPLIER,
                'allow_new_entries': False,
                'reason': f"SPY ${self.spy_close:.2f} below 200 SMA ${self.spy_200_sma:.2f}",
                'details': details
            }

        # =================================================================
        # PRIORITY 2: Distribution Days (Net)
        # =================================================================
        if dist_level == 'exit':
            self.exit_triggered = True
            self.exit_date = current_date
            self._start_rally_attempt(current_date)
            return {
                'action': 'exit_all',
                'position_size_multiplier': 0.0,
                'allow_new_entries': False,
                'reason': f"Net Distribution: {net_distribution} (EXIT - waiting for follow-through)",
                'details': details
            }

        if dist_level == 'danger':
            return {
                'action': 'stop_buying',
                'position_size_multiplier': SafeguardConfig.DANGER_SIZE_MULTIPLIER,
                'allow_new_entries': False,
                'reason': f"Net Distribution: {net_distribution} (DANGER)",
                'details': details
            }

        if dist_level == 'warning':
            return {
                'action': 'caution',
                'position_size_multiplier': SafeguardConfig.WARNING_SIZE_MULTIPLIER,
                'allow_new_entries': True,
                'reason': f"Net Distribution: {net_distribution} (WARNING)",
                'details': details
            }

        if dist_level == 'caution':
            return {
                'action': 'caution',
                'position_size_multiplier': SafeguardConfig.CAUTION_SIZE_MULTIPLIER,
                'allow_new_entries': True,
                'reason': f"Net Distribution: {net_distribution} (CAUTION)",
                'details': details
            }

        # =================================================================
        # PRIORITY 3: SPY below 50 SMA (Early Warning)
        # =================================================================
        if SafeguardConfig.EARLY_WARNING_ENABLED and spy_below_50:
            return {
                'action': 'caution',
                'position_size_multiplier': SafeguardConfig.CAUTION_SIZE_MULTIPLIER,
                'allow_new_entries': True,
                'reason': f"SPY ${self.spy_close:.2f} below 50 SMA ${self.spy_50_sma:.2f} (early warning)",
                'details': details
            }

        # =================================================================
        # NORMAL
        # =================================================================
        return {
            'action': 'normal',
            'position_size_multiplier': 1.0,
            'allow_new_entries': True,
            'reason': f"Normal (Net Dist: {net_distribution})",
            'details': details
        }

    # =========================================================================
    # UPDATE METHODS
    # =========================================================================

    def update_spy(self, date, spy_close, spy_50_sma, spy_200_sma,
                   spy_prev_close=None, spy_volume=None, spy_prev_volume=None):
        """
        Update SPY data and check for distribution/accumulation day
        """
        self.spy_close = spy_close
        self.spy_50_sma = spy_50_sma
        self.spy_200_sma = spy_200_sma
        self.spy_prev_close = spy_prev_close or self.spy_prev_close
        self.spy_volume = spy_volume or 0
        self.spy_prev_volume = spy_prev_volume or 0

        # Check for distribution or accumulation day
        if spy_prev_close and spy_volume and spy_prev_volume:
            self._check_distribution_or_accumulation(
                date, spy_close, spy_prev_close, spy_volume, spy_prev_volume
            )

        # Update rally attempt tracking
        if self.in_rally_attempt:
            self._update_rally_attempt(date, spy_close, spy_prev_close, spy_volume, spy_prev_volume)

    def record_stop_loss(self, date, ticker, loss_pct):
        """Kept for interface compatibility"""
        pass

    # =========================================================================
    # DISTRIBUTION / ACCUMULATION DETECTION
    # =========================================================================

    def _check_distribution_or_accumulation(self, date, spy_close, spy_prev_close,
                                            spy_volume, spy_prev_volume):
        """Check for distribution OR accumulation day"""
        if spy_prev_close == 0 or spy_prev_volume == 0:
            return

        # Skip options expiration days
        if self._is_options_expiration(date):
            return

        price_change_pct = ((spy_close - spy_prev_close) / spy_prev_close) * 100
        volume_change_pct = ((spy_volume - spy_prev_volume) / spy_prev_volume) * 100

        # Check DISTRIBUTION (down day on higher volume)
        if (price_change_pct <= SafeguardConfig.DISTRIBUTION_DAY_PRICE_THRESHOLD and
                volume_change_pct >= SafeguardConfig.VOLUME_THRESHOLD):
            self.distribution_days.append({
                'date': date,
                'price_change': price_change_pct,
                'volume_change': volume_change_pct
            })
            return

        # Check ACCUMULATION (up day on higher volume)
        if (price_change_pct >= SafeguardConfig.ACCUMULATION_DAY_PRICE_THRESHOLD and
                volume_change_pct >= SafeguardConfig.VOLUME_THRESHOLD):
            self.accumulation_days.append({
                'date': date,
                'price_change': price_change_pct,
                'volume_change': volume_change_pct
            })

    def _is_options_expiration(self, date):
        """Check if date is monthly options expiration (3rd Friday)"""
        if not hasattr(date, 'year'):
            return False

        try:
            # Get the calendar for the month
            cal = calendar.monthcalendar(date.year, date.month)

            # Find third Friday
            # Fridays are at index 4 in the week array
            third_friday = None
            friday_count = 0

            for week in cal:
                if week[4] != 0:  # Friday exists in this week
                    friday_count += 1
                    if friday_count == 3:
                        third_friday = week[4]
                        break

            if third_friday and date.day == third_friday:
                return True

            return False

        except Exception:
            return False

    def _expire_old_days(self, current_date):
        """Remove days older than lookback period"""
        if hasattr(current_date, 'tzinfo') and current_date.tzinfo is not None:
            current_date = current_date.replace(tzinfo=None)

        cutoff = current_date - timedelta(days=SafeguardConfig.DISTRIBUTION_LOOKBACK_DAYS)

        self.distribution_days = [
            d for d in self.distribution_days
            if self._normalize_date(d['date']) > cutoff
        ]

        self.accumulation_days = [
            d for d in self.accumulation_days
            if self._normalize_date(d['date']) > cutoff
        ]

    def _normalize_date(self, date):
        """Remove timezone for comparison"""
        if hasattr(date, 'tzinfo') and date.tzinfo is not None:
            return date.replace(tzinfo=None)
        return date

    def _get_net_distribution(self):
        """Calculate net distribution (distribution - accumulation)"""
        return max(0, len(self.distribution_days) - len(self.accumulation_days))

    def _get_distribution_level(self, net_distribution=None):
        """Get distribution severity level based on NET count"""
        if net_distribution is None:
            net_distribution = self._get_net_distribution()

        if net_distribution >= SafeguardConfig.NET_DISTRIBUTION_EXIT:
            return 'exit'
        elif net_distribution >= SafeguardConfig.NET_DISTRIBUTION_DANGER:
            return 'danger'
        elif net_distribution >= SafeguardConfig.NET_DISTRIBUTION_WARNING:
            return 'warning'
        elif net_distribution >= SafeguardConfig.NET_DISTRIBUTION_CAUTION:
            return 'caution'
        return 'normal'

    def _is_spy_below_200(self):
        """Check if SPY is below 200 SMA"""
        if self.spy_200_sma == 0:
            return False
        return self.spy_close < self.spy_200_sma

    def _is_spy_below_50(self):
        """Check if SPY is below 50 SMA"""
        if self.spy_50_sma == 0:
            return False
        return self.spy_close < self.spy_50_sma

    # =========================================================================
    # RALLY ATTEMPT / FOLLOW-THROUGH DAY
    # =========================================================================

    def _start_rally_attempt(self, date):
        """Start tracking a rally attempt after exit signal"""
        self.in_rally_attempt = True
        self.rally_attempt_start = date
        self.rally_attempt_low = self.spy_close
        self.rally_day_count = 0
        self.follow_through_confirmed = False

    def _update_rally_attempt(self, date, spy_close, spy_prev_close, spy_volume, spy_prev_volume):
        """Update rally attempt state"""
        if not self.in_rally_attempt:
            return

        # Check if rally attempt is broken (undercuts low)
        if spy_close < self.rally_attempt_low:
            # Rally failed - reset
            self.rally_attempt_low = spy_close
            self.rally_day_count = 0
            return

        # Increment day count
        if spy_close > spy_prev_close:
            self.rally_day_count += 1

        # Update low if needed
        low_today = spy_close  # Approximation - in real system would use actual low
        if low_today < self.rally_attempt_low:
            self.rally_attempt_low = low_today

    def _check_follow_through(self, current_date):
        """Check if follow-through day conditions are met"""
        if not self.in_rally_attempt:
            return False

        # Must be day 4+ of rally attempt
        if self.rally_day_count < SafeguardConfig.FTD_MIN_RALLY_DAYS:
            return False

        # Calculate today's gain
        if self.spy_prev_close == 0:
            return False

        price_gain_pct = ((self.spy_close - self.spy_prev_close) / self.spy_prev_close) * 100

        # Must gain minimum percentage
        if price_gain_pct < SafeguardConfig.FTD_MIN_PRICE_GAIN:
            return False

        # Must be on higher volume (if required)
        if SafeguardConfig.FTD_REQUIRE_HIGHER_VOLUME:
            if self.spy_prev_volume == 0:
                return False
            if self.spy_volume <= self.spy_prev_volume:
                return False

        # SPY must be above 200 SMA
        if self._is_spy_below_200():
            return False

        # All conditions met!
        self.in_rally_attempt = False
        return True

    def _recovery_response(self, current_date, details):
        """Build response while waiting for follow-through"""
        reason = f"Waiting for follow-through (Rally Day {self.rally_day_count}/{SafeguardConfig.FTD_MIN_RALLY_DAYS}+)"

        if self._is_spy_below_200():
            reason += " | SPY < 200 SMA"

        return {
            'action': 'exit_all',
            'position_size_multiplier': 0.0,
            'allow_new_entries': False,
            'reason': reason,
            'details': details
        }

    # =========================================================================
    # STATISTICS
    # =========================================================================

    def get_statistics(self):
        """Get current state for logging"""
        net_dist = self._get_net_distribution()

        # Calculate SPY extension from 50 SMA
        spy_extension = 0
        if self.spy_50_sma > 0:
            spy_extension = ((self.spy_close - self.spy_50_sma) / self.spy_50_sma) * 100

        return {
            'spy_close': self.spy_close,
            'spy_50_sma': self.spy_50_sma,
            'spy_200_sma': self.spy_200_sma,
            'spy_extension': spy_extension,
            'spy_below_50': self._is_spy_below_50(),
            'spy_below_200': self._is_spy_below_200(),
            'distribution_days': len(self.distribution_days),
            'accumulation_days': len(self.accumulation_days),
            'net_distribution': net_dist,
            'distribution_level': self._get_distribution_level(net_dist),
            'in_rally_attempt': self.in_rally_attempt,
            'rally_day_count': self.rally_day_count,
            'follow_through_confirmed': self.follow_through_confirmed,
            'in_recovery': self.exit_triggered,
            'exit_date': self.exit_date
        }

    def get_distribution_details(self):
        """Get detailed distribution/accumulation day info"""
        return {
            'distribution_days': [
                {
                    'date': d['date'].strftime('%Y-%m-%d') if hasattr(d['date'], 'strftime') else str(d['date']),
                    'price_change': f"{d['price_change']:.2f}%",
                    'volume_change': f"{d['volume_change']:.1f}%"
                }
                for d in sorted(self.distribution_days, key=lambda x: x['date'], reverse=True)
            ],
            'accumulation_days': [
                {
                    'date': d['date'].strftime('%Y-%m-%d') if hasattr(d['date'], 'strftime') else str(d['date']),
                    'price_change': f"{d['price_change']:.2f}%",
                    'volume_change': f"{d['volume_change']:.1f}%"
                }
                for d in sorted(self.accumulation_days, key=lambda x: x['date'], reverse=True)
            ]
        }