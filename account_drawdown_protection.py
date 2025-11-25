"""
Market Safeguard System - SIMPLIFIED

Two checks only:
1. DrawdownProtection: SPY below 200 SMA = no trading (overrides everything)
2. Distribution Days: Tracks institutional selling pressure

One unified method: detect_regime() returns all info needed
"""

from datetime import datetime, timedelta


class SafeguardConfig:
    """Safeguard configuration"""
    # Distribution Days
    DISTRIBUTION_DAY_PRICE_THRESHOLD = -0.2
    DISTRIBUTION_DAY_VOLUME_THRESHOLD = 20.0
    DISTRIBUTION_LOOKBACK_DAYS = 25
    DISTRIBUTION_CAUTION = 3
    DISTRIBUTION_WARNING = 4
    DISTRIBUTION_DANGER = 5
    DISTRIBUTION_EXIT = 6

    # Position size multipliers
    CAUTION_SIZE_MULTIPLIER = 0.75
    WARNING_SIZE_MULTIPLIER = 0.50
    DANGER_SIZE_MULTIPLIER = 0.0

    # Recovery after EXIT_ALL
    RECOVERY_WAIT_DAYS = 3


class MarketRegimeDetector:
    """
    Unified market regime detection

    Priority (highest to lowest):
    1. SPY below 200 SMA → STOP_BUYING (DrawdownProtection)
    2. Distribution days ≥ 6 → EXIT_ALL
    3. Distribution days 5 → STOP_BUYING
    4. Distribution days 4 → WARNING (50% size)
    5. Distribution days 3 → CAUTION (75% size)
    6. Otherwise → NORMAL (100% size)
    """

    def __init__(self):
        # Distribution day tracking
        self.distribution_days = []

        # SPY data
        self.spy_close = 0
        self.spy_200_sma = 0

        # Recovery tracking
        self.exit_triggered = False
        self.exit_date = None

    # =========================================================================
    # MAIN METHOD - Call this to get regime
    # =========================================================================

    def detect_regime(self, num_positions=0, current_date=None):
        """
        Unified regime detection - single method for all market state info

        Args:
            num_positions: Number of current positions (kept for interface compatibility)
            current_date: Current date for expiration checks

        Returns:
            dict: {
                'action': 'normal' | 'caution' | 'stop_buying' | 'exit_all',
                'position_size_multiplier': float (0.0 to 1.0),
                'allow_new_entries': bool,
                'reason': str,
                'details': {
                    'spy_below_200': bool,
                    'distribution_count': int,
                    'distribution_level': str,
                    'in_recovery': bool
                }
            }
        """
        # Expire old distribution days
        if current_date:
            self._expire_old_distribution_days(current_date)

        # Check recovery state first
        if self.exit_triggered:
            if self._should_exit_recovery(current_date):
                self.exit_triggered = False
                self.exit_date = None
            else:
                return self._recovery_response(current_date)

        # Get current state
        spy_below_200 = self._is_spy_below_200()
        dist_count = len(self.distribution_days)
        dist_level = self._get_distribution_level()

        # =====================================================================
        # PRIORITY 1: DrawdownProtection - SPY below 200 SMA
        # =====================================================================
        if spy_below_200:
            return {
                'action': 'stop_buying',
                'position_size_multiplier': SafeguardConfig.DANGER_SIZE_MULTIPLIER,
                'allow_new_entries': False,
                'reason': f"SPY below 200 SMA (DrawdownProtection)",
                'details': {
                    'spy_below_200': True,
                    'spy_close': self.spy_close,
                    'spy_200_sma': self.spy_200_sma,
                    'distribution_count': dist_count,
                    'distribution_level': dist_level,
                    'in_recovery': False
                }
            }

        # =====================================================================
        # PRIORITY 2: Distribution Days
        # =====================================================================
        if dist_level == 'exit':
            self.exit_triggered = True
            self.exit_date = current_date
            return {
                'action': 'exit_all',
                'position_size_multiplier': 0.0,
                'allow_new_entries': False,
                'reason': f"Distribution Days: {dist_count} (EXIT threshold)",
                'details': {
                    'spy_below_200': False,
                    'distribution_count': dist_count,
                    'distribution_level': dist_level,
                    'in_recovery': False
                }
            }

        if dist_level == 'danger':
            return {
                'action': 'stop_buying',
                'position_size_multiplier': SafeguardConfig.DANGER_SIZE_MULTIPLIER,
                'allow_new_entries': False,
                'reason': f"Distribution Days: {dist_count} (DANGER)",
                'details': {
                    'spy_below_200': False,
                    'distribution_count': dist_count,
                    'distribution_level': dist_level,
                    'in_recovery': False
                }
            }

        if dist_level == 'warning':
            return {
                'action': 'caution',
                'position_size_multiplier': SafeguardConfig.WARNING_SIZE_MULTIPLIER,
                'allow_new_entries': True,
                'reason': f"Distribution Days: {dist_count} (WARNING)",
                'details': {
                    'spy_below_200': False,
                    'distribution_count': dist_count,
                    'distribution_level': dist_level,
                    'in_recovery': False
                }
            }

        if dist_level == 'caution':
            return {
                'action': 'caution',
                'position_size_multiplier': SafeguardConfig.CAUTION_SIZE_MULTIPLIER,
                'allow_new_entries': True,
                'reason': f"Distribution Days: {dist_count} (CAUTION)",
                'details': {
                    'spy_below_200': False,
                    'distribution_count': dist_count,
                    'distribution_level': dist_level,
                    'in_recovery': False
                }
            }

        # =====================================================================
        # NORMAL - All clear
        # =====================================================================
        return {
            'action': 'normal',
            'position_size_multiplier': 1.0,
            'allow_new_entries': True,
            'reason': "Normal",
            'details': {
                'spy_below_200': False,
                'distribution_count': dist_count,
                'distribution_level': dist_level,
                'in_recovery': False
            }
        }

    # =========================================================================
    # UPDATE METHODS - Call these to feed data
    # =========================================================================

    def update_spy(self, date, spy_close, spy_50_sma, spy_200_sma,
                   spy_prev_close=None, spy_volume=None, spy_prev_volume=None):
        """
        Update SPY data and check for distribution day

        Args:
            date: Current date
            spy_close: SPY closing price
            spy_50_sma: SPY 50-day SMA (not used but kept for interface compatibility)
            spy_200_sma: SPY 200-day SMA
            spy_prev_close: Previous day's close (for distribution day check)
            spy_volume: Today's volume (for distribution day check)
            spy_prev_volume: Previous day's volume (for distribution day check)
        """
        self.spy_close = spy_close
        self.spy_200_sma = spy_200_sma

        # Check for distribution day
        if spy_prev_close and spy_volume and spy_prev_volume:
            self._check_distribution_day(date, spy_close, spy_prev_close, spy_volume, spy_prev_volume)

    def record_stop_loss(self, date, ticker, loss_pct):
        """
        Record stop loss - kept for interface compatibility but not used in simplified system
        """
        pass  # Not used in simplified system

    # =========================================================================
    # INTERNAL METHODS
    # =========================================================================

    def _is_spy_below_200(self):
        """Check if SPY is below 200 SMA"""
        if self.spy_200_sma == 0:
            return False
        return self.spy_close < self.spy_200_sma

    def _check_distribution_day(self, date, spy_close, spy_prev_close, spy_volume, spy_prev_volume):
        """Check if today qualifies as a distribution day"""
        if spy_prev_close == 0 or spy_prev_volume == 0:
            return False

        price_change_pct = ((spy_close - spy_prev_close) / spy_prev_close) * 100
        volume_change_pct = ((spy_volume - spy_prev_volume) / spy_prev_volume) * 100

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

        return is_distribution

    def _expire_old_distribution_days(self, current_date):
        """Remove distribution days older than lookback period"""
        if not self.distribution_days:
            return

        if hasattr(current_date, 'tzinfo') and current_date.tzinfo is not None:
            current_date = current_date.replace(tzinfo=None)

        cutoff = current_date - timedelta(days=SafeguardConfig.DISTRIBUTION_LOOKBACK_DAYS)

        self.distribution_days = [
            d for d in self.distribution_days
            if self._normalize_date(d['date']) > cutoff
        ]

    def _normalize_date(self, date):
        """Remove timezone for comparison"""
        if hasattr(date, 'tzinfo') and date.tzinfo is not None:
            return date.replace(tzinfo=None)
        return date

    def _get_distribution_level(self):
        """Get distribution day severity level"""
        count = len(self.distribution_days)
        if count >= SafeguardConfig.DISTRIBUTION_EXIT:
            return 'exit'
        elif count >= SafeguardConfig.DISTRIBUTION_DANGER:
            return 'danger'
        elif count >= SafeguardConfig.DISTRIBUTION_WARNING:
            return 'warning'
        elif count >= SafeguardConfig.DISTRIBUTION_CAUTION:
            return 'caution'
        return 'normal'

    def _should_exit_recovery(self, current_date):
        """Check if we can exit recovery mode"""
        if not self.exit_date or not current_date:
            return False

        exit_date = self._normalize_date(self.exit_date)
        current_date = self._normalize_date(current_date)

        days_elapsed = (current_date - exit_date).days

        # Must wait minimum days AND SPY must be above 200 SMA
        if days_elapsed < SafeguardConfig.RECOVERY_WAIT_DAYS:
            return False

        if self._is_spy_below_200():
            return False

        return True

    def _recovery_response(self, current_date):
        """Build response while in recovery mode"""
        exit_date = self._normalize_date(self.exit_date)
        current_date_norm = self._normalize_date(current_date) if current_date else exit_date

        days_elapsed = (current_date_norm - exit_date).days
        days_remaining = max(0, SafeguardConfig.RECOVERY_WAIT_DAYS - days_elapsed)

        reason = f"Recovery: {days_remaining}d remaining"
        if self._is_spy_below_200():
            reason += " + SPY < 200 SMA"

        return {
            'action': 'exit_all',
            'position_size_multiplier': 0.0,
            'allow_new_entries': False,
            'reason': reason,
            'details': {
                'spy_below_200': self._is_spy_below_200(),
                'distribution_count': len(self.distribution_days),
                'distribution_level': self._get_distribution_level(),
                'in_recovery': True,
                'days_remaining': days_remaining
            }
        }

    # =========================================================================
    # STATISTICS
    # =========================================================================

    def get_statistics(self):
        """Get current state for logging/debugging"""
        return {
            'spy_close': self.spy_close,
            'spy_200_sma': self.spy_200_sma,
            'spy_below_200': self._is_spy_below_200(),
            'distribution_days': len(self.distribution_days),
            'distribution_level': self._get_distribution_level(),
            'in_recovery': self.exit_triggered,
            'exit_date': self.exit_date
        }