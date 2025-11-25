"""
Market Safeguard System - STREAMLINED VERSION

Reduced logging - only critical events printed
"""

from datetime import datetime, timedelta
from collections import deque


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

    # Sequential Stops
    STOPS_PER_POSITION_MULTIPLIER = 0.15
    STOPS_CAUTION_UNITS = 1.5
    STOPS_WARNING_UNITS = 2.0
    STOPS_DANGER_UNITS = 2.5
    STOPS_EXIT_UNITS = 3.5
    STOPS_LOOKBACK_SHORT = 5
    STOPS_LOOKBACK_MEDIUM = 7
    STOPS_LOOKBACK_LONG = 10

    # SPY Extension
    SPY_CAUTION_EXTENSION = 6.0
    SPY_WARNING_EXTENSION = 7.0
    SPY_DANGER_EXTENSION = 8.0
    SPY_REVERSAL_DROP = 2.0
    SPY_BELOW_50_SMA_EXIT = True
    SPY_BELOW_200_SMA_EXIT = True

    # Position size multipliers
    CAUTION_SIZE_MULTIPLIER = 0.75
    WARNING_SIZE_MULTIPLIER = 0.50
    DANGER_SIZE_MULTIPLIER = 0.0

    # Recovery
    RECOVERY_WAIT_DAYS = 5
    RECOVERY_REQUIRE_SPY_ABOVE_50 = True


class DistributionDayTracker:
    """Track distribution days"""

    def __init__(self):
        self.distribution_days = deque(maxlen=SafeguardConfig.DISTRIBUTION_LOOKBACK_DAYS)

    def check_distribution_day(self, date, spy_close, spy_prev_close, spy_volume, spy_prev_volume):
        if spy_prev_close == 0 or spy_prev_volume == 0:
            return False, 0, 0

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

        return is_distribution, price_change_pct, volume_change_pct

    def get_count(self):
        return len(self.distribution_days)

    def get_level(self):
        count = self.get_count()
        if count >= SafeguardConfig.DISTRIBUTION_EXIT:
            return 'exit'
        elif count >= SafeguardConfig.DISTRIBUTION_DANGER:
            return 'danger'
        elif count >= SafeguardConfig.DISTRIBUTION_WARNING:
            return 'warning'
        elif count >= SafeguardConfig.DISTRIBUTION_CAUTION:
            return 'caution'
        return 'normal'


class SequentialStopTracker:
    """Track sequential stop losses"""

    def __init__(self):
        self.stops = deque(maxlen=100)

    def add_stop(self, date, ticker, loss_pct):
        self.stops.append({'date': date, 'ticker': ticker, 'loss_pct': loss_pct})

    def get_stops_in_period(self, days, as_of_date=None):
        if as_of_date is None:
            as_of_date = datetime.now()

        if hasattr(as_of_date, 'tzinfo') and as_of_date.tzinfo is not None:
            as_of_date = as_of_date.replace(tzinfo=None)

        cutoff = as_of_date - timedelta(days=days)
        recent_stops = []

        for stop in self.stops:
            stop_date = stop['date']
            if hasattr(stop_date, 'tzinfo') and stop_date.tzinfo is not None:
                stop_date = stop_date.replace(tzinfo=None)
            if stop_date > cutoff:
                recent_stops.append(stop)

        return len(recent_stops), recent_stops

    def calculate_stop_units(self, num_positions):
        if num_positions == 0:
            return 1.0
        return SafeguardConfig.STOPS_PER_POSITION_MULTIPLIER * num_positions

    def get_level(self, num_positions, as_of_date=None):
        stops_5d, _ = self.get_stops_in_period(SafeguardConfig.STOPS_LOOKBACK_SHORT, as_of_date)
        stops_7d, _ = self.get_stops_in_period(SafeguardConfig.STOPS_LOOKBACK_MEDIUM, as_of_date)
        stops_10d, _ = self.get_stops_in_period(SafeguardConfig.STOPS_LOOKBACK_LONG, as_of_date)

        unit_multiplier = self.calculate_stop_units(num_positions)

        stops_5d_norm = stops_5d / unit_multiplier if unit_multiplier > 0 else stops_5d
        stops_7d_norm = stops_7d / unit_multiplier if unit_multiplier > 0 else stops_7d
        stops_10d_norm = stops_10d / unit_multiplier if unit_multiplier > 0 else stops_10d

        if stops_10d_norm >= SafeguardConfig.STOPS_EXIT_UNITS:
            return 'exit'
        elif stops_7d_norm >= SafeguardConfig.STOPS_DANGER_UNITS:
            return 'danger'
        elif stops_5d_norm >= SafeguardConfig.STOPS_WARNING_UNITS:
            return 'warning'
        elif stops_5d_norm >= SafeguardConfig.STOPS_CAUTION_UNITS:
            return 'caution'
        return 'normal'


class SPYExtensionTracker:
    """Track SPY extension from 200 SMA"""

    def __init__(self):
        self.peak_extension = 0
        self.peak_date = None
        self.last_close = 0
        self.last_50_sma = 0
        self.last_200_sma = 0

    def update(self, date, spy_close, spy_50_sma, spy_200_sma):
        self.last_close = spy_close
        self.last_50_sma = spy_50_sma
        self.last_200_sma = spy_200_sma

        current_extension = self.get_extension_from_200()
        if current_extension > self.peak_extension:
            self.peak_extension = current_extension
            self.peak_date = date

    def get_extension_from_200(self):
        if self.last_200_sma == 0:
            return 0
        return ((self.last_close - self.last_200_sma) / self.last_200_sma) * 100

    def is_below_50_sma(self):
        return self.last_close < self.last_50_sma

    def is_below_200_sma(self):
        return self.last_close < self.last_200_sma

    def detect_reversal(self):
        current_extension = self.get_extension_from_200()
        if self.peak_extension >= SafeguardConfig.SPY_DANGER_EXTENSION:
            drop_from_peak = self.peak_extension - current_extension
            if drop_from_peak >= SafeguardConfig.SPY_REVERSAL_DROP:
                return True
        return False

    def get_level(self):
        extension = self.get_extension_from_200()

        if self.detect_reversal():
            return 'reversal'

        if SafeguardConfig.SPY_BELOW_200_SMA_EXIT and self.is_below_200_sma():
            return 'reversal'

        if SafeguardConfig.SPY_BELOW_50_SMA_EXIT and self.is_below_50_sma():
            return 'danger'

        if extension >= SafeguardConfig.SPY_DANGER_EXTENSION:
            return 'danger'
        elif extension >= SafeguardConfig.SPY_WARNING_EXTENSION:
            return 'warning'
        elif extension >= SafeguardConfig.SPY_CAUTION_EXTENSION:
            return 'caution'
        return 'normal'


class MarketRegimeDetector:
    """Main safeguard system"""

    def __init__(self):
        self.distribution_tracker = DistributionDayTracker()
        self.stop_tracker = SequentialStopTracker()
        self.spy_tracker = SPYExtensionTracker()
        self.exit_triggered = False
        self.exit_date = None

    def update_spy(self, date, spy_close, spy_50_sma, spy_200_sma,
                   spy_prev_close=None, spy_volume=None, spy_prev_volume=None):
        self.spy_tracker.update(date, spy_close, spy_50_sma, spy_200_sma)

        if spy_prev_close and spy_volume and spy_prev_volume:
            self.distribution_tracker.check_distribution_day(
                date, spy_close, spy_prev_close, spy_volume, spy_prev_volume
            )

    def record_stop_loss(self, date, ticker, loss_pct):
        self.stop_tracker.add_stop(date, ticker, loss_pct)

    def detect_regime(self, num_positions, current_date=None):
        if self.exit_triggered:
            if self._should_exit_recovery(current_date):
                self.exit_triggered = False
                self.exit_date = None
            else:
                return self._recovery_response(current_date)

        dist_level = self.distribution_tracker.get_level()
        stop_level = self.stop_tracker.get_level(num_positions, current_date)
        spy_level = self.spy_tracker.get_level()

        market_danger = dist_level in ['danger', 'exit'] or spy_level in ['danger', 'reversal']

        # EXIT ALL
        if dist_level == 'exit':
            return self._trigger_exit('exit_all',
                                      f"Distribution Days: {self.distribution_tracker.get_count()}",
                                      dist_level, stop_level, spy_level, current_date)

        if spy_level == 'reversal':
            return self._trigger_exit('exit_all',
                                      f"SPY Reversal from {self.spy_tracker.peak_extension:.1f}%",
                                      dist_level, stop_level, spy_level, current_date)

        if stop_level == 'exit':
            return self._trigger_exit('exit_all',
                                      f"Too many stops ({self.stop_tracker.get_stops_in_period(10)[0]} in 10d)",
                                      dist_level, stop_level, spy_level, current_date)

        if stop_level == 'danger' and market_danger:
            return self._trigger_exit('exit_all',
                                      f"Stops + Market danger",
                                      dist_level, stop_level, spy_level, current_date)

        # STOP BUYING
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
                                        f"Multiple stop losses",
                                        dist_level, stop_level, spy_level)

        # WARNING
        if spy_level == 'warning' or dist_level == 'warning':
            return self._build_response('caution', SafeguardConfig.WARNING_SIZE_MULTIPLIER,
                                        f"Market weakness",
                                        dist_level, stop_level, spy_level)

        # CAUTION
        if spy_level == 'caution' or dist_level == 'caution' or stop_level == 'caution':
            return self._build_response('caution', SafeguardConfig.CAUTION_SIZE_MULTIPLIER,
                                        f"Early warning",
                                        dist_level, stop_level, spy_level)

        # NORMAL
        return self._build_response('normal', 1.0, "Normal", dist_level, stop_level, spy_level)

    def _build_response(self, action, size_multiplier, reason, dist_level, stop_level, spy_level):
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
        self.exit_triggered = True
        self.exit_date = current_date
        return self._build_response(action, 0.0, reason, dist_level, stop_level, spy_level)

    def _should_exit_recovery(self, current_date):
        if not self.exit_date or not current_date:
            return False

        exit_date = self.exit_date
        if hasattr(exit_date, 'tzinfo') and exit_date.tzinfo is not None:
            exit_date = exit_date.replace(tzinfo=None)
        if hasattr(current_date, 'tzinfo') and current_date.tzinfo is not None:
            current_date = current_date.replace(tzinfo=None)

        days_elapsed = (current_date - exit_date).days
        if days_elapsed < SafeguardConfig.RECOVERY_WAIT_DAYS:
            return False

        if SafeguardConfig.RECOVERY_REQUIRE_SPY_ABOVE_50:
            if self.spy_tracker.is_below_50_sma():
                return False

        return True

    def _recovery_response(self, current_date):
        exit_date = self.exit_date
        if hasattr(exit_date, 'tzinfo') and exit_date.tzinfo is not None:
            exit_date = exit_date.replace(tzinfo=None)
        if hasattr(current_date, 'tzinfo') and current_date.tzinfo is not None:
            current_date = current_date.replace(tzinfo=None)

        days_remaining = max(0, SafeguardConfig.RECOVERY_WAIT_DAYS - (current_date - exit_date).days)
        recovery_msg = f"Recovery: {days_remaining}d remaining"

        if SafeguardConfig.RECOVERY_REQUIRE_SPY_ABOVE_50 and self.spy_tracker.is_below_50_sma():
            recovery_msg += " + SPY < 50 SMA"

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


def format_regime_display(regime_result):
    """Minimal regime display - single line"""
    return ""  # Removed - summary handles this