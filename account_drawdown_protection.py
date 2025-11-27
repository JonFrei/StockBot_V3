"""
Market Safeguard System - ENHANCED IBD-STYLE + PORTFOLIO SAFEGUARDS

Based on Investor's Business Daily methodology with improvements:
1. Distribution Days: Institutional selling (down ≥0.4% on volume up ≥25%)
2. Accumulation Days: Institutional buying (up ≥0.4% on volume up ≥25%) - OFFSETS distribution
3. Follow-Through Day: Confirms new uptrend (up ≥1.5% on higher volume, day 4+ of rally)
4. Options Expiration Filter: Skips monthly opex from distribution count
5. Dual SMA Check: 50 SMA early warning, 200 SMA full stop

NEW PORTFOLIO-LEVEL SAFEGUARDS:
6. Portfolio Peak Drawdown: Stop buying if portfolio drops 5% from 30-day peak
7. Scaled Stop Loss Counter: Caution mode if stop loss rate exceeds threshold

Regime Priority:
1. Portfolio Peak Drawdown triggered → STOP_BUYING (5 days)
2. Scaled Stop Loss Rate exceeded → CAUTION (5 days)
3. SPY below 200 SMA → STOP_BUYING
4. SPY below 50 SMA → CAUTION (early warning)
5. Net Distribution ≥ 6 → EXIT_ALL (wait for follow-through)
6. Net Distribution 5 → STOP_BUYING
7. Net Distribution 4 → WARNING (50% size)
8. Net Distribution 3 → CAUTION (75% size)
9. Otherwise → NORMAL
"""

from datetime import datetime, timedelta
import calendar


class SafeguardConfig:
    """Enhanced safeguard configuration"""

    # Distribution/Accumulation Day Thresholds (tightened from original)
    DISTRIBUTION_DAY_PRICE_THRESHOLD = -0.25  # Was -0.2%
    ACCUMULATION_DAY_PRICE_THRESHOLD = 0.4  # NEW: +0.4% for accumulation
    VOLUME_THRESHOLD = 15.0  # Was 20%, now 25%

    # Lookback period
    DISTRIBUTION_LOOKBACK_DAYS = 25

    # Net distribution thresholds (distribution - accumulation)
    NET_DISTRIBUTION_CAUTION = 4
    NET_DISTRIBUTION_WARNING = 4
    NET_DISTRIBUTION_DANGER = 5
    NET_DISTRIBUTION_EXIT = 6

    # Position size multipliers
    CAUTION_SIZE_MULTIPLIER = 0.65
    WARNING_SIZE_MULTIPLIER = 0.0
    DANGER_SIZE_MULTIPLIER = 0.0

    # Follow-Through Day Requirements
    FTD_MIN_RALLY_DAYS = 4  # Must be day 4+ of rally attempt
    FTD_MIN_PRICE_GAIN = 1.5  # Must gain ≥1.5%
    FTD_REQUIRE_HIGHER_VOLUME = True  # Volume must be higher than previous day

    # Early warning
    EARLY_WARNING_ENABLED = True  # Use 50 SMA as early warning

    # ==========================================================================
    # PORTFOLIO-LEVEL SAFEGUARDS (NEW)
    # ==========================================================================

    # Portfolio Peak Drawdown Circuit Breaker
    PEAK_DRAWDOWN_ENABLED = True
    PEAK_DRAWDOWN_THRESHOLD = 6.0  # Trigger if portfolio drops 5% from 30-day peak
    PEAK_DRAWDOWN_LOOKBACK_DAYS = 30  # Rolling window for peak calculation
    PEAK_DRAWDOWN_LOCKOUT_DAYS = 7  # Trading days to stay in STOP_BUYING
    PEAK_DRAWDOWN_RECOVERY_PCT = 97.0  # Must recover to 97% of peak to reset

    # Scaled Stop Loss Counter
    STOP_LOSS_COUNTER_ENABLED = True
    STOP_LOSS_LOOKBACK_DAYS = 10  # Rolling window for counting stop losses
    STOP_LOSS_RATE_THRESHOLD = 35.0  # Trigger if 30%+ of positions stopped out
    STOP_LOSS_MIN_COUNT = 3  # Minimum stop losses before rate applies
    STOP_LOSS_LOCKOUT_DAYS = 5  # Trading days to stay in CAUTION

    # Relative Strength Filter
    RELATIVE_STRENGTH_ENABLED = True
    RELATIVE_STRENGTH_LOOKBACK = 20  # Days to measure performance
    RELATIVE_STRENGTH_MIN_OUTPERFORM = 0.0  # Stock must outperform SPY by this % (0 = match, 1.0 = beat by 1%)

class MarketRegimeDetector:
    """
    Enhanced IBD-style market regime detection + Portfolio Safeguards

    Tracks both distribution AND accumulation days.
    Uses follow-through day for re-entry confirmation.
    NEW: Portfolio peak drawdown and stop loss rate tracking.
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
        self.spy_price_history = []  # [{'date': date, 'close': float}]

        # ======================================================================
        # NEW: Portfolio-Level Safeguard State
        # ======================================================================

        # Portfolio Peak Drawdown tracking
        self.portfolio_history = []  # [{'date': date, 'value': float}]
        self.peak_drawdown_triggered = False
        self.peak_drawdown_trigger_date = None
        self.peak_drawdown_lockout_end = None

        # Stop Loss Counter tracking
        self.recent_stop_losses = []  # [{'date': date, 'ticker': str, 'loss_pct': float}]
        self.stop_loss_caution_triggered = False
        self.stop_loss_trigger_date = None
        self.stop_loss_lockout_end = None

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
            self._expire_old_stop_losses(current_date)
            self._expire_old_portfolio_history(current_date)

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
            'in_recovery': self.exit_triggered,
            # NEW: Portfolio safeguard details
            'peak_drawdown_triggered': self.peak_drawdown_triggered,
            'stop_loss_caution_triggered': self.stop_loss_caution_triggered,
            'recent_stop_loss_count': len(self.recent_stop_losses),
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
        # PRIORITY 0: PORTFOLIO PEAK DRAWDOWN (NEW - HIGHEST PRIORITY)
        # =================================================================
        if SafeguardConfig.PEAK_DRAWDOWN_ENABLED:
            drawdown_result = self._check_peak_drawdown(current_date)
            if drawdown_result:
                details['peak_drawdown_pct'] = drawdown_result.get('drawdown_pct', 0)
                details['portfolio_peak'] = drawdown_result.get('peak_value', 0)
                return {
                    'action': 'stop_buying',
                    'position_size_multiplier': SafeguardConfig.DANGER_SIZE_MULTIPLIER,
                    'allow_new_entries': False,
                    'reason': drawdown_result['reason'],
                    'details': details
                }

        # =================================================================
        # PRIORITY 0.5: SCALED STOP LOSS COUNTER (NEW)
        # =================================================================
        if SafeguardConfig.STOP_LOSS_COUNTER_ENABLED:
            stop_loss_result = self._check_stop_loss_rate(num_positions, current_date)
            if stop_loss_result:
                details['stop_loss_rate'] = stop_loss_result.get('rate', 0)
                return {
                    'action': 'stop_buying',
                    'position_size_multiplier': SafeguardConfig.CAUTION_SIZE_MULTIPLIER,
                    'allow_new_entries': False,
                    'reason': stop_loss_result['reason'],
                    'details': details
                }

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
                'allow_new_entries': True,  # Changed from True
                'reason': f"Net Distribution: {net_distribution} (WARNING)",
                'details': details
            }

        if dist_level == 'caution':
            return {
                'action': 'caution',
                'position_size_multiplier': SafeguardConfig.CAUTION_SIZE_MULTIPLIER,
                'allow_new_entries': True,  # Changed from True
                'reason': f"Net Distribution: {net_distribution} (CAUTION)",
                'details': details
            }

        # =================================================================
        # PRIORITY 3: SPY below 50 SMA (Early Warning)
        # =================================================================
        if SafeguardConfig.EARLY_WARNING_ENABLED and spy_below_50:
            return {
                'action': 'stop_buying',
                'position_size_multiplier': SafeguardConfig.CAUTION_SIZE_MULTIPLIER,
                'allow_new_entries': False,  # Changed from True
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

        # Track SPY price history for relative strength
        self.update_spy_price_history(date, spy_close)

        # Check for distribution or accumulation day
        if spy_prev_close and spy_volume and spy_prev_volume:
            self._check_distribution_or_accumulation(
                date, spy_close, spy_prev_close, spy_volume, spy_prev_volume
            )

        # Update rally attempt tracking
        if self.in_rally_attempt:
            self._update_rally_attempt(date, spy_close, spy_prev_close, spy_volume, spy_prev_volume)

    def update_portfolio_value(self, date, portfolio_value):
        """
        NEW: Update portfolio value for peak drawdown tracking

        Args:
            date: Current date
            portfolio_value: Current portfolio value
        """
        if not SafeguardConfig.PEAK_DRAWDOWN_ENABLED:
            return

        # Normalize date
        if hasattr(date, 'tzinfo') and date.tzinfo is not None:
            date = date.replace(tzinfo=None)

        # Add to history (avoid duplicates for same date)
        self.portfolio_history = [
            p for p in self.portfolio_history
            if self._normalize_date(p['date']).date() != date.date()
        ]
        self.portfolio_history.append({'date': date, 'value': portfolio_value})

    def update_spy_price_history(self, date, spy_close):
        """
        Track SPY price history for relative strength calculations

        Args:
            date: Current date
            spy_close: SPY closing price
        """
        # Normalize date
        if hasattr(date, 'tzinfo') and date.tzinfo is not None:
            date = date.replace(tzinfo=None)

        # Avoid duplicates for same date
        self.spy_price_history = [
            p for p in self.spy_price_history
            if self._normalize_date(p['date']).date() != date.date()
        ]
        self.spy_price_history.append({'date': date, 'close': spy_close})

        # Keep only lookback period + buffer
        max_history = SafeguardConfig.RELATIVE_STRENGTH_LOOKBACK + 5
        if len(self.spy_price_history) > max_history:
            self.spy_price_history = sorted(
                self.spy_price_history,
                key=lambda x: x['date']
            )[-max_history:]

    def get_spy_performance(self, lookback_days=None):
        """
        Get SPY performance over lookback period

        Args:
            lookback_days: Days to look back (default: RELATIVE_STRENGTH_LOOKBACK)

        Returns:
            float: SPY percentage change, or None if insufficient data
        """
        if lookback_days is None:
            lookback_days = SafeguardConfig.RELATIVE_STRENGTH_LOOKBACK

        if len(self.spy_price_history) < 2:
            return None

        # Sort by date
        sorted_history = sorted(self.spy_price_history, key=lambda x: x['date'])

        # Get current and past price
        current_price = sorted_history[-1]['close']

        # Find price from ~lookback_days ago
        if len(sorted_history) <= lookback_days:
            past_price = sorted_history[0]['close']
        else:
            past_price = sorted_history[-lookback_days - 1]['close']

        if past_price <= 0:
            return None

        return ((current_price - past_price) / past_price) * 100

    def check_relative_strength(self, stock_current_price, stock_past_price):
        """
        Check if stock is outperforming SPY

        Args:
            stock_current_price: Stock's current price
            stock_past_price: Stock's price from lookback_days ago

        Returns:
            dict: {
                'passes': bool,
                'stock_performance': float,
                'spy_performance': float,
                'relative_strength': float (stock - SPY)
            }
        """
        if not SafeguardConfig.RELATIVE_STRENGTH_ENABLED:
            return {'passes': True, 'stock_performance': 0, 'spy_performance': 0, 'relative_strength': 0}

        # Get SPY performance
        spy_perf = self.get_spy_performance()
        if spy_perf is None:
            # Insufficient SPY data - allow trade
            return {'passes': True, 'stock_performance': 0, 'spy_performance': 0, 'relative_strength': 0}

        # Calculate stock performance
        if stock_past_price <= 0 or stock_current_price <= 0:
            return {'passes': True, 'stock_performance': 0, 'spy_performance': spy_perf, 'relative_strength': 0}

        stock_perf = ((stock_current_price - stock_past_price) / stock_past_price) * 100

        # Calculate relative strength (positive = outperforming SPY)
        relative_strength = stock_perf - spy_perf

        # Check if passes threshold
        passes = relative_strength >= SafeguardConfig.RELATIVE_STRENGTH_MIN_OUTPERFORM

        return {
            'passes': passes,
            'stock_performance': round(stock_perf, 2),
            'spy_performance': round(spy_perf, 2),
            'relative_strength': round(relative_strength, 2)
        }

    def record_stop_loss(self, date, ticker, loss_pct):
        """
        NEW: Record a stop loss for rate calculation

        Args:
            date: Date of stop loss
            ticker: Stock symbol
            loss_pct: Loss percentage (negative number)
        """
        if not SafeguardConfig.STOP_LOSS_COUNTER_ENABLED:
            return

        # Normalize date
        if hasattr(date, 'tzinfo') and date.tzinfo is not None:
            date = date.replace(tzinfo=None)

        self.recent_stop_losses.append({
            'date': date,
            'ticker': ticker,
            'loss_pct': loss_pct
        })

    # =========================================================================
    # PORTFOLIO PEAK DRAWDOWN (NEW)
    # =========================================================================

    def _check_peak_drawdown(self, current_date):
        """
        Check if portfolio has dropped 5% from 30-day rolling peak

        Returns:
            dict with reason if triggered, None otherwise
        """
        # Check if still in lockout period
        if self.peak_drawdown_triggered and self.peak_drawdown_lockout_end:
            if current_date and current_date < self.peak_drawdown_lockout_end:
                days_remaining = (self.peak_drawdown_lockout_end - current_date).days
                return {
                    'reason': f"Peak Drawdown lockout ({days_remaining}d remaining)",
                    'drawdown_pct': 0,
                    'peak_value': 0
                }
            else:
                # Lockout expired - reset
                self.peak_drawdown_triggered = False
                self.peak_drawdown_trigger_date = None
                self.peak_drawdown_lockout_end = None

        # Need portfolio history to calculate
        if len(self.portfolio_history) < 2:
            return None

        # Get current value (most recent entry)
        current_value = self.portfolio_history[-1]['value']

        # Calculate 30-day peak
        peak_value = max(p['value'] for p in self.portfolio_history)

        if peak_value <= 0:
            return None

        # Calculate drawdown percentage
        drawdown_pct = ((peak_value - current_value) / peak_value) * 100

        # Check threshold
        if drawdown_pct >= SafeguardConfig.PEAK_DRAWDOWN_THRESHOLD:
            # Trigger drawdown protection
            self.peak_drawdown_triggered = True
            self.peak_drawdown_trigger_date = current_date

            # Calculate lockout end (5 trading days ≈ 7 calendar days)
            if current_date:
                self.peak_drawdown_lockout_end = current_date + timedelta(
                    days=SafeguardConfig.PEAK_DRAWDOWN_LOCKOUT_DAYS + 2  # +2 for weekends
                )

            return {
                'reason': f"Portfolio -{drawdown_pct:.1f}% from peak ${peak_value:,.0f} (threshold: -{SafeguardConfig.PEAK_DRAWDOWN_THRESHOLD}%)",
                'drawdown_pct': drawdown_pct,
                'peak_value': peak_value
            }

        # Check recovery (if previously triggered but now recovered)
        if self.peak_drawdown_triggered:
            recovery_threshold = peak_value * (SafeguardConfig.PEAK_DRAWDOWN_RECOVERY_PCT / 100)
            if current_value >= recovery_threshold:
                self.peak_drawdown_triggered = False
                self.peak_drawdown_trigger_date = None
                self.peak_drawdown_lockout_end = None

        return None

    def _expire_old_portfolio_history(self, current_date):
        """Remove portfolio values older than lookback period"""
        if not self.portfolio_history:
            return

        if hasattr(current_date, 'tzinfo') and current_date.tzinfo is not None:
            current_date = current_date.replace(tzinfo=None)

        cutoff = current_date - timedelta(days=SafeguardConfig.PEAK_DRAWDOWN_LOOKBACK_DAYS)

        self.portfolio_history = [
            p for p in self.portfolio_history
            if self._normalize_date(p['date']) > cutoff
        ]

    # =========================================================================
    # SCALED STOP LOSS COUNTER (NEW)
    # =========================================================================

    def _check_stop_loss_rate(self, num_positions, current_date):
        """
        Check if stop loss rate exceeds threshold

        Rate = stop_losses / (current_positions + stop_losses)
        This answers: "What % of positions got stopped out?"

        Args:
            num_positions: Current number of open positions
            current_date: Current date

        Returns:
            dict with reason if triggered, None otherwise
        """
        # Check if still in lockout period
        if self.stop_loss_caution_triggered and self.stop_loss_lockout_end:
            if current_date and current_date < self.stop_loss_lockout_end:
                days_remaining = (self.stop_loss_lockout_end - current_date).days
                return {
                    'reason': f"Stop Loss Caution lockout ({days_remaining}d remaining)",
                    'rate': 0
                }
            else:
                # Lockout expired - reset
                self.stop_loss_caution_triggered = False
                self.stop_loss_trigger_date = None
                self.stop_loss_lockout_end = None

        # Count recent stop losses
        stop_loss_count = len(self.recent_stop_losses)

        # Need minimum stop losses before checking rate
        if stop_loss_count < SafeguardConfig.STOP_LOSS_MIN_COUNT:
            return None

        # Calculate denominator: positions we had = current + those stopped out
        total_positions_base = num_positions + stop_loss_count

        if total_positions_base <= 0:
            return None

        # Calculate rate
        stop_loss_rate = (stop_loss_count / total_positions_base) * 100

        # Check threshold
        if stop_loss_rate >= SafeguardConfig.STOP_LOSS_RATE_THRESHOLD:
            # Trigger caution mode
            self.stop_loss_caution_triggered = True
            self.stop_loss_trigger_date = current_date

            # Calculate lockout end
            if current_date:
                self.stop_loss_lockout_end = current_date + timedelta(
                    days=SafeguardConfig.STOP_LOSS_LOCKOUT_DAYS + 2  # +2 for weekends
                )

            # Get tickers for logging
            tickers = [sl['ticker'] for sl in self.recent_stop_losses[-5:]]  # Last 5
            ticker_str = ', '.join(tickers)

            return {
                'reason': f"Stop Loss Rate {stop_loss_rate:.0f}% ({stop_loss_count}/{total_positions_base}) - Recent: {ticker_str}",
                'rate': stop_loss_rate
            }

        return None

    def _expire_old_stop_losses(self, current_date):
        """Remove stop losses older than lookback period"""
        if not self.recent_stop_losses:
            return

        if hasattr(current_date, 'tzinfo') and current_date.tzinfo is not None:
            current_date = current_date.replace(tzinfo=None)

        cutoff = current_date - timedelta(days=SafeguardConfig.STOP_LOSS_LOOKBACK_DAYS)

        self.recent_stop_losses = [
            sl for sl in self.recent_stop_losses
            if self._normalize_date(sl['date']) > cutoff
        ]

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
            'exit_date': self.exit_date,
            # NEW: Portfolio safeguard stats
            'peak_drawdown_triggered': self.peak_drawdown_triggered,
            'peak_drawdown_trigger_date': self.peak_drawdown_trigger_date,
            'stop_loss_caution_triggered': self.stop_loss_caution_triggered,
            'recent_stop_loss_count': len(self.recent_stop_losses),
            'portfolio_history_days': len(self.portfolio_history),
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
            ],
            # NEW: Stop loss details
            'recent_stop_losses': [
                {
                    'date': sl['date'].strftime('%Y-%m-%d') if hasattr(sl['date'], 'strftime') else str(sl['date']),
                    'ticker': sl['ticker'],
                    'loss_pct': f"{sl['loss_pct']:.1f}%"
                }
                for sl in sorted(self.recent_stop_losses, key=lambda x: x['date'], reverse=True)
            ]
        }