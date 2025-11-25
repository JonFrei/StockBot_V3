"""
PROFESSIONAL MARKET SAFEGUARD SYSTEM
Based on William O'Neil, Paul Tudor Jones, Turtle Traders methodology

PHILOSOPHY: "Sell before you have to" - Mark Minervini

THREE-TECHNIQUE APPROACH:
1. Distribution Days (William O'Neil/IBD)
2. Sequential Stop Tracking (Turtle Traders)
3. SPY Extension Detection (Paul Tudor Jones)

Technique #2 is FILTERED by #1 and #3 to reduce false positives
"""

from datetime import datetime, timedelta
from collections import deque


# =============================================================================
# SAFEGUARD CONFIGURATION
# =============================================================================

class SafeguardConfig:
    """Centralized configuration for all market safeguard parameters"""

    # =========================================================================
    # TECHNIQUE #1: DISTRIBUTION DAYS (William O'Neil)
    # =========================================================================
    DISTRIBUTION_DAY_PRICE_THRESHOLD = -0.2  # SPY down >0.2%
    DISTRIBUTION_DAY_VOLUME_THRESHOLD = 20.0  # Volume 20%+ higher
    DISTRIBUTION_LOOKBACK_DAYS = 25  # Count in last 25 days
    DISTRIBUTION_CAUTION = 3  # 3 days = caution
    DISTRIBUTION_WARNING = 4  # 4 days = warning
    DISTRIBUTION_DANGER = 5  # 5 days = danger
    DISTRIBUTION_EXIT = 6  # 6 days = exit all

    # =========================================================================
    # TECHNIQUE #2: SEQUENTIAL STOP TRACKING (Turtle Traders)
    # =========================================================================
    STOPS_PER_POSITION_MULTIPLIER = 0.15  # 15% of positions = 1 "unit"
    STOPS_CAUTION_UNITS = 1.5  # 1.5 units in 5 days = caution
    STOPS_WARNING_UNITS = 2.0  # 2.0 units in 5 days = warning
    STOPS_DANGER_UNITS = 2.5  # 2.5 units in 7 days = danger
    STOPS_EXIT_UNITS = 3.5  # 3.5 units in 10 days = exit

    STOPS_LOOKBACK_SHORT = 5  # Short term: 5 days
    STOPS_LOOKBACK_MEDIUM = 7  # Medium term: 7 days
    STOPS_LOOKBACK_LONG = 10  # Long term: 10 days

    # =========================================================================
    # TECHNIQUE #3: SPY EXTENSION (Paul Tudor Jones)
    # =========================================================================
    SPY_CAUTION_EXTENSION = 6.0  # 6% above 200 SMA
    SPY_WARNING_EXTENSION = 7.0  # 7% above 200 SMA
    SPY_DANGER_EXTENSION = 8.0  # 8% above 200 SMA
    SPY_REVERSAL_DROP = 2.0  # 2% drop from peak = reversal

    SPY_BELOW_50_SMA_EXIT = True  # Exit if SPY < 50 SMA
    SPY_BELOW_200_SMA_EXIT = True  # Exit if SPY < 200 SMA

    # =========================================================================
    # SAFEGUARD LEVELS
    # =========================================================================
    # Level 1: CAUTION - Reduce position sizes
    # Level 2: WARNING - Stop new buys
    # Level 3: DANGER - Exit all positions

    # Position size multipliers per level
    CAUTION_SIZE_MULTIPLIER = 0.75  # 75% of normal size
    WARNING_SIZE_MULTIPLIER = 0.50  # 50% of normal size
    DANGER_SIZE_MULTIPLIER = 0.0  # No trading

    # =========================================================================
    # RECOVERY SETTINGS
    # =========================================================================
    RECOVERY_WAIT_DAYS = 5  # Wait 5 days after exit
    RECOVERY_REQUIRE_SPY_ABOVE_50 = True  # SPY must be above 50 SMA


# =============================================================================
# DISTRIBUTION DAY TRACKER
# =============================================================================

class DistributionDayTracker:
    """
    Track distribution days using William O'Neil's IBD methodology

    Distribution Day = Down day on high volume (institutions selling)
    """

    def __init__(self):
        self.distribution_days = deque(maxlen=SafeguardConfig.DISTRIBUTION_LOOKBACK_DAYS)

    def check_distribution_day(self, date, spy_close, spy_prev_close,
                               spy_volume, spy_prev_volume):
        """
        Check if today is a distribution day

        Returns: (is_distribution_day, price_change_pct, volume_change_pct)
        """
        if spy_prev_close == 0 or spy_prev_volume == 0:
            return False, 0, 0

        # Calculate price change
        price_change_pct = ((spy_close - spy_prev_close) / spy_prev_close) * 100

        # Calculate volume change
        volume_change_pct = ((spy_volume - spy_prev_volume) / spy_prev_volume) * 100

        # Check criteria
        is_distribution = (
                price_change_pct <= SafeguardConfig.DISTRIBUTION_DAY_PRICE_THRESHOLD and
                volume_change_pct >= SafeguardConfig.DISTRIBUTION_DAY_VOLUME_THRESHOLD
        )

        if is_distribution:
            self.distribution_days.append({
                'date': date,
                'price_change': price_change_pct,
                'volume_change': volume_change_pct
            })

        return is_distribution, price_change_pct, volume_change_pct

    def get_count(self):
        """Get current distribution day count"""
        return len(self.distribution_days)

    def get_level(self):
        """
        Get danger level based on distribution days

        Returns: ('normal', 'caution', 'warning', 'danger', 'exit')
        """
        count = self.get_count()

        if count >= SafeguardConfig.DISTRIBUTION_EXIT:
            return 'exit'
        elif count >= SafeguardConfig.DISTRIBUTION_DANGER:
            return 'danger'
        elif count >= SafeguardConfig.DISTRIBUTION_WARNING:
            return 'warning'
        elif count >= SafeguardConfig.DISTRIBUTION_CAUTION:
            return 'caution'
        else:
            return 'normal'


# =============================================================================
# SEQUENTIAL STOP LOSS TRACKER
# =============================================================================

class SequentialStopTracker:
    """
    Track recent stop losses with position-count scaling

    Based on Turtle Traders and Paul Tudor Jones methodology
    """

    def __init__(self):
        self.stops = deque(maxlen=100)  # Keep last 100 stops

    def add_stop(self, date, ticker, loss_pct):
        """Record a stop loss"""
        self.stops.append({
            'date': date,
            'ticker': ticker,
            'loss_pct': loss_pct
        })

    def get_stops_in_period(self, days, as_of_date=None):
        """
        Count stops in last N days

        Returns: (count, list_of_stops)
        """
        if as_of_date is None:
            as_of_date = datetime.now()

        cutoff = as_of_date - timedelta(days=days)

        recent_stops = [
            stop for stop in self.stops
            if stop['date'] > cutoff
        ]

        return len(recent_stops), recent_stops

    def calculate_stop_units(self, num_positions):
        """
        Calculate "stop units" based on portfolio size

        Logic: Each position represents X% of portfolio
        If trading 10 positions, 1 stop = 0.15 units (15% of 10)
        If trading 20 positions, 1 stop = 0.15 units (15% of 20)

        This scales the threshold based on portfolio breadth
        """
        if num_positions == 0:
            return 1.0  # Default multiplier

        return SafeguardConfig.STOPS_PER_POSITION_MULTIPLIER * num_positions

    def get_level(self, num_positions, as_of_date=None):
        """
        Get danger level based on recent stops (scaled by position count)

        Returns: ('normal', 'caution', 'warning', 'danger', 'exit')
        """
        # Get stops in different timeframes
        stops_5d, _ = self.get_stops_in_period(SafeguardConfig.STOPS_LOOKBACK_SHORT, as_of_date)
        stops_7d, _ = self.get_stops_in_period(SafeguardConfig.STOPS_LOOKBACK_MEDIUM, as_of_date)
        stops_10d, _ = self.get_stops_in_period(SafeguardConfig.STOPS_LOOKBACK_LONG, as_of_date)

        # Calculate unit thresholds based on position count
        unit_multiplier = self.calculate_stop_units(num_positions)

        # Normalized stop counts (stops per unit)
        stops_5d_normalized = stops_5d / unit_multiplier if unit_multiplier > 0 else stops_5d
        stops_7d_normalized = stops_7d / unit_multiplier if unit_multiplier > 0 else stops_7d
        stops_10d_normalized = stops_10d / unit_multiplier if unit_multiplier > 0 else stops_10d

        # Check thresholds (most severe wins)
        if stops_10d_normalized >= SafeguardConfig.STOPS_EXIT_UNITS:
            return 'exit'
        elif stops_7d_normalized >= SafeguardConfig.STOPS_DANGER_UNITS:
            return 'danger'
        elif stops_5d_normalized >= SafeguardConfig.STOPS_WARNING_UNITS:
            return 'warning'
        elif stops_5d_normalized >= SafeguardConfig.STOPS_CAUTION_UNITS:
            return 'caution'
        else:
            return 'normal'


# =============================================================================
# SPY EXTENSION TRACKER
# =============================================================================

class SPYExtensionTracker:
    """
    Track SPY's distance from 200 SMA and detect reversals

    Based on Paul Tudor Jones methodology
    """

    def __init__(self):
        self.peak_extension = 0
        self.peak_date = None
        self.last_close = 0
        self.last_50_sma = 0
        self.last_200_sma = 0

    def update(self, date, spy_close, spy_50_sma, spy_200_sma):
        """Update SPY tracking"""
        self.last_close = spy_close
        self.last_50_sma = spy_50_sma
        self.last_200_sma = spy_200_sma

        # Track peak extension
        current_extension = self.get_extension_from_200()

        if current_extension > self.peak_extension:
            self.peak_extension = current_extension
            self.peak_date = date

    def get_extension_from_200(self):
        """Get current distance from 200 SMA"""
        if self.last_200_sma == 0:
            return 0

        return ((self.last_close - self.last_200_sma) / self.last_200_sma) * 100

    def is_below_50_sma(self):
        """Check if SPY is below 50 SMA"""
        return self.last_close < self.last_50_sma

    def is_below_200_sma(self):
        """Check if SPY is below 200 SMA"""
        return self.last_close < self.last_200_sma

    def detect_reversal(self):
        """
        Detect reversal from extended levels

        Logic: If SPY was >8% extended, then drops to <6%, reversal confirmed
        """
        current_extension = self.get_extension_from_200()

        if self.peak_extension >= SafeguardConfig.SPY_DANGER_EXTENSION:
            drop_from_peak = self.peak_extension - current_extension

            if drop_from_peak >= SafeguardConfig.SPY_REVERSAL_DROP:
                return True

        return False

    def get_level(self):
        """
        Get danger level based on SPY extension

        Returns: ('normal', 'caution', 'warning', 'danger', 'reversal')
        """
        extension = self.get_extension_from_200()

        # Check for reversal first
        if self.detect_reversal():
            return 'reversal'

        # Check for MA breaks
        if SafeguardConfig.SPY_BELOW_200_SMA_EXIT and self.is_below_200_sma():
            return 'reversal'  # Treat as reversal

        if SafeguardConfig.SPY_BELOW_50_SMA_EXIT and self.is_below_50_sma():
            return 'danger'

        # Check extension levels
        if extension >= SafeguardConfig.SPY_DANGER_EXTENSION:
            return 'danger'
        elif extension >= SafeguardConfig.SPY_WARNING_EXTENSION:
            return 'warning'
        elif extension >= SafeguardConfig.SPY_CAUTION_EXTENSION:
            return 'caution'
        else:
            return 'normal'


# =============================================================================
# MARKET REGIME DETECTOR (MAIN CLASS)
# =============================================================================

class MarketRegimeDetector:
    """
    Professional 3-technique market safeguard system

    OPTION A: Boolean Filter
    - Technique #2 (Sequential Stops) triggers are FILTERED by #1 and #3
    - Stop losses only trigger exit if market is ALSO in danger zone
    """

    def __init__(self):
        self.distribution_tracker = DistributionDayTracker()
        self.stop_tracker = SequentialStopTracker()
        self.spy_tracker = SPYExtensionTracker()

        self.exit_triggered = False
        self.exit_date = None

    def update_spy(self, date, spy_close, spy_50_sma, spy_200_sma,
                   spy_prev_close=None, spy_volume=None, spy_prev_volume=None):
        """
        Update all trackers with SPY data

        Args:
            date: Current date
            spy_close: SPY closing price
            spy_50_sma: SPY 50-day SMA
            spy_200_sma: SPY 200-day SMA
            spy_prev_close: Previous day's close (for distribution days)
            spy_volume: Today's volume (for distribution days)
            spy_prev_volume: Previous day's volume (for distribution days)
        """
        # Update SPY extension tracker
        self.spy_tracker.update(date, spy_close, spy_50_sma, spy_200_sma)

        # Update distribution day tracker
        if spy_prev_close and spy_volume and spy_prev_volume:
            is_dist, price_chg, vol_chg = self.distribution_tracker.check_distribution_day(
                date, spy_close, spy_prev_close, spy_volume, spy_prev_volume
            )

            if is_dist:
                print(f"   📉 Distribution Day: SPY {price_chg:.1f}% on volume +{vol_chg:.0f}%")

    def record_stop_loss(self, date, ticker, loss_pct):
        """Record a stop loss for sequential tracking"""
        self.stop_tracker.add_stop(date, ticker, loss_pct)

    def detect_regime(self, num_positions, current_date=None):
        """
        Main detection logic using OPTION A (Boolean Filter)

        LOGIC:
        1. Get individual technique levels
        2. Check if Technique #1 or #3 are in danger zones
        3. If yes, make Technique #2 more sensitive (filter active)
        4. Determine final action

        Args:
            num_positions: Current number of open positions
            current_date: Current date (for recovery check)

        Returns:
            dict: {
                'action': 'normal', 'caution', 'stop_buying', 'exit_all',
                'position_size_multiplier': float,
                'allow_new_entries': bool,
                'reason': str,
                'details': {...}
            }
        """
        # Check if in recovery period
        if self.exit_triggered:
            if self._should_exit_recovery(current_date):
                self.exit_triggered = False
                self.exit_date = None
            else:
                return self._recovery_response(current_date)

        # Get individual technique levels
        dist_level = self.distribution_tracker.get_level()
        stop_level = self.stop_tracker.get_level(num_positions, current_date)
        spy_level = self.spy_tracker.get_level()

        # Check if market is in danger zone (Technique #1 or #3)
        market_danger = (
                dist_level in ['danger', 'exit'] or
                spy_level in ['danger', 'reversal']
        )

        market_warning = (
                dist_level == 'warning' or
                spy_level == 'warning'
        )

        # OPTION A: FILTERED LOGIC

        # LEVEL 4: EXIT ALL (Highest priority)
        if dist_level == 'exit':
            return self._trigger_exit('exit_all',
                                      f"Distribution Days: {self.distribution_tracker.get_count()} (EXIT threshold)",
                                      dist_level, stop_level, spy_level, current_date)

        if spy_level == 'reversal':
            return self._trigger_exit('exit_all',
                                      f"SPY Reversal Detected (dropped from {self.spy_tracker.peak_extension:.1f}%)",
                                      dist_level, stop_level, spy_level, current_date)

        # FILTERED STOP LOGIC: Stops trigger exit only if market is dangerous
        if stop_level == 'exit':
            return self._trigger_exit('exit_all',
                                      f"Too many stop losses ({self.stop_tracker.get_stops_in_period(10)[0]} in 10 days)",
                                      dist_level, stop_level, spy_level, current_date)

        if stop_level == 'danger' and market_danger:
            return self._trigger_exit('exit_all',
                                      f"Stop losses + Market danger (Stops: {stop_level}, Dist: {dist_level}, SPY: {spy_level})",
                                      dist_level, stop_level, spy_level, current_date)

        # LEVEL 3: DANGER - Stop buying
        if spy_level == 'danger':
            return self._build_response('stop_buying', SafeguardConfig.DANGER_SIZE_MULTIPLIER,
                                        f"SPY Extended: {self.spy_tracker.get_extension_from_200():.1f}% above 200 SMA",
                                        dist_level, stop_level, spy_level)

        if dist_level == 'danger':
            return self._build_response('stop_buying', SafeguardConfig.DANGER_SIZE_MULTIPLIER,
                                        f"Distribution Days: {self.distribution_tracker.get_count()}",
                                        dist_level, stop_level, spy_level)

        if stop_level == 'danger':
            return self._build_response('stop_buying', SafeguardConfig.DANGER_SIZE_MULTIPLIER,
                                        f"Multiple stop losses in short period",
                                        dist_level, stop_level, spy_level)

        # LEVEL 2: WARNING - Reduce sizes
        if stop_level == 'warning' and market_warning:
            return self._build_response('caution', SafeguardConfig.WARNING_SIZE_MULTIPLIER,
                                        f"Stop losses + Market warning (Stops: {stop_level}, Dist: {dist_level}, SPY: {spy_level})",
                                        dist_level, stop_level, spy_level)

        if spy_level == 'warning' or dist_level == 'warning':
            return self._build_response('caution', SafeguardConfig.WARNING_SIZE_MULTIPLIER,
                                        f"Market showing weakness (Dist: {dist_level}, SPY: {spy_level})",
                                        dist_level, stop_level, spy_level)

        # LEVEL 1: CAUTION - Slight reduction
        if spy_level == 'caution' or dist_level == 'caution' or stop_level == 'caution':
            return self._build_response('caution', SafeguardConfig.CAUTION_SIZE_MULTIPLIER,
                                        f"Early warning signs (Dist: {dist_level}, Stops: {stop_level}, SPY: {spy_level})",
                                        dist_level, stop_level, spy_level)

        # LEVEL 0: NORMAL - All clear
        return self._build_response('normal', 1.0,
                                    "All systems normal",
                                    dist_level, stop_level, spy_level)

    def _build_response(self, action, size_multiplier, reason, dist_level, stop_level, spy_level):
        """Build regime detection response"""
        return {
            'action': action,
            'position_size_multiplier': size_multiplier,
            'allow_new_entries': action not in ['stop_buying', 'exit_all'],
            'reason': reason,
            'details': {
                'distribution_level': dist_level,
                'distribution_count': self.distribution_tracker.get_count(),
                'stop_level': stop_level,
                'stops_recent': self.stop_tracker.get_stops_in_period(5)[0],
                'spy_level': spy_level,
                'spy_extension': self.spy_tracker.get_extension_from_200(),
                'spy_below_50': self.spy_tracker.is_below_50_sma(),
                'spy_below_200': self.spy_tracker.is_below_200_sma()
            }
        }

    def _trigger_exit(self, action, reason, dist_level, stop_level, spy_level, current_date):
        """Trigger exit and enter recovery period"""
        self.exit_triggered = True
        self.exit_date = current_date

        print(f"\n{'=' * 80}")
        print(f"🚨 MARKET SAFEGUARD: EXIT ALL POSITIONS")
        print(f"{'=' * 80}")
        print(f"Reason: {reason}")
        print(f"Distribution Level: {dist_level} ({self.distribution_tracker.get_count()} days)")
        print(f"Stop Loss Level: {stop_level}")
        print(f"SPY Level: {spy_level} ({self.spy_tracker.get_extension_from_200():.1f}% from 200 SMA)")
        print(f"{'=' * 80}\n")

        return self._build_response(action, 0.0, reason, dist_level, stop_level, spy_level)

    def _should_exit_recovery(self, current_date):
        """Check if should exit recovery period"""
        if not self.exit_date or not current_date:
            return False

        # Check days elapsed
        days_elapsed = (current_date - self.exit_date).days

        if days_elapsed < SafeguardConfig.RECOVERY_WAIT_DAYS:
            return False

        # Check SPY condition if required
        if SafeguardConfig.RECOVERY_REQUIRE_SPY_ABOVE_50:
            if self.spy_tracker.is_below_50_sma():
                return False

        return True

    def _recovery_response(self, current_date):
        """Build response during recovery period"""
        days_remaining = SafeguardConfig.RECOVERY_WAIT_DAYS - (current_date - self.exit_date).days
        days_remaining = max(0, days_remaining)

        recovery_msg = f"Recovery period: {days_remaining} days remaining"

        if SafeguardConfig.RECOVERY_REQUIRE_SPY_ABOVE_50 and self.spy_tracker.is_below_50_sma():
            recovery_msg += " + SPY must reclaim 50 SMA"

        return {
            'action': 'exit_all',
            'position_size_multiplier': 0.0,
            'allow_new_entries': False,
            'reason': recovery_msg,
            'details': {
                'in_recovery': True,
                'exit_date': self.exit_date,
                'days_remaining': days_remaining
            }
        }

    def get_statistics(self):
        """Get statistics for reporting"""
        return {
            'distribution_days': self.distribution_tracker.get_count(),
            'distribution_level': self.distribution_tracker.get_level(),
            'recent_stops_5d': self.stop_tracker.get_stops_in_period(5)[0],
            'recent_stops_10d': self.stop_tracker.get_stops_in_period(10)[0],
            'spy_extension': self.spy_tracker.get_extension_from_200(),
            'spy_below_50': self.spy_tracker.is_below_50_sma(),
            'spy_below_200': self.spy_tracker.is_below_200_sma(),
            'in_recovery': self.exit_triggered,
            'exit_date': self.exit_date
        }


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def format_regime_display(regime_result):
    """Format regime detection result for console display"""
    action = regime_result['action']
    reason = regime_result['reason']
    details = regime_result['details']

    # Action emoji
    emoji_map = {
        'normal': '✅',
        'caution': '⚠️',
        'stop_buying': '🚫',
        'exit_all': '🚨'
    }
    emoji = emoji_map.get(action, '❓')

    output = f"\n{'=' * 80}\n"
    output += f"{emoji} MARKET SAFEGUARD: {action.upper().replace('_', ' ')}\n"
    output += f"{'=' * 80}\n"
    output += f"Reason: {reason}\n\n"

    output += f"📊 TECHNIQUE STATUS:\n"
    output += f"   Distribution Days: {details['distribution_level']} ({details['distribution_count']} days)\n"
    output += f"   Stop Losses: {details['stop_level']} ({details['stops_recent']} in 5 days)\n"
    output += f"   SPY Extension: {details['spy_level']} ({details['spy_extension']:.1f}% from 200 SMA)\n"

    if details.get('spy_below_50') or details.get('spy_below_200'):
        output += f"\n⚠️  SPY MA Status:\n"
        if details['spy_below_50']:
            output += f"   • Below 50 SMA\n"
        if details['spy_below_200']:
            output += f"   • Below 200 SMA\n"

    output += f"\n🎯 TRADING PERMISSIONS:\n"
    output += f"   New Entries: {'✅ Allowed' if regime_result['allow_new_entries'] else '🚫 Blocked'}\n"
    output += f"   Position Size: {regime_result['position_size_multiplier'] * 100:.0f}% of normal\n"

    output += f"{'=' * 80}\n"

    return output