"""
Market Safeguard System - SIMPLIFIED

Two-Layer Protection:

Layer 1: Market Trend Gate (Soft Block)
- SPY below 200 SMA → Block new entries (keep positions)
- Recovery Mode can override this

Layer 2: Sentiment Crisis (Hard Exit)
- SPY closes below 20-day low OR
- Technical breakdown (SPY < 50 SMA + < 20 EMA + high volume)
- Action: Exit ALL positions, lockout 5 days + wait for 20 EMA reclaim
- Recovery Mode CANNOT override this
"""

from datetime import timedelta


class SafeguardConfig:
    """Safeguard configuration"""

    # Layer 1: Market Trend Gate
    # (SPY below 200 SMA - soft block, recovery can override)

    # Layer 2: Sentiment Crisis
    CRISIS_LOCKOUT_DAYS = 5  # Minimum days before re-entry
    VOLUME_SURGE_THRESHOLD = 1.0  # Volume must be above 20-day average (1.0 = 100%)

    # Recovery requirement after lockout
    # SPY must close above 20 EMA to resume trading

    # Relative Strength Filter
    RELATIVE_STRENGTH_ENABLED = True
    RELATIVE_STRENGTH_LOOKBACK = 20  # Days to measure performance
    RELATIVE_STRENGTH_MIN_OUTPERFORM = 2.0  # Stock must outperform SPY by this % (0 = match, 1.0 = beat by 1%)


class MarketRegimeDetector:
    """
    Simplified market regime detection

    Two layers:
    1. SPY < 200 SMA → Soft block (recovery can override)
    2. Sentiment Crisis → Hard exit + lockout (no override)
    """

    def __init__(self):
        # SPY data
        self.spy_close = 0
        self.spy_20_ema = 0
        self.spy_50_sma = 0
        self.spy_200_sma = 0
        self.spy_volume = 0
        self.spy_avg_volume = 0

        # Price history for 20-day low
        self.spy_price_history = []  # [{'date': date, 'close': float}]

        # Crisis state
        self.crisis_active = False
        self.crisis_trigger_date = None
        self.crisis_trigger_reason = None
        self.lockout_end_date = None

    def update_spy(self, date, spy_close, spy_20_ema, spy_50_sma, spy_200_sma,
                   spy_volume=None, spy_avg_volume=None):
        """
        Update SPY data

        Args:
            date: Current date
            spy_close: SPY closing price
            spy_20_ema: SPY 20-day EMA
            spy_50_sma: SPY 50-day SMA
            spy_200_sma: SPY 200-day SMA
            spy_volume: Today's volume (optional)
            spy_avg_volume: 20-day average volume (optional)
        """
        self.spy_close = spy_close
        self.spy_20_ema = spy_20_ema
        self.spy_50_sma = spy_50_sma
        self.spy_200_sma = spy_200_sma
        self.spy_volume = spy_volume or 0
        self.spy_avg_volume = spy_avg_volume or 0

        # Update price history
        self._update_price_history(date, spy_close)

    def _update_price_history(self, date, spy_close):
        """Track SPY price history for 20-day low calculation"""
        # Normalize date
        if hasattr(date, 'tzinfo') and date.tzinfo is not None:
            date = date.replace(tzinfo=None)

        # Avoid duplicates
        self.spy_price_history = [
            p for p in self.spy_price_history
            if p['date'].date() != date.date()
        ]

        self.spy_price_history.append({'date': date, 'close': spy_close})

        # Keep only last 25 days (buffer for 20-day calculation)
        if len(self.spy_price_history) > 25:
            self.spy_price_history = sorted(
                self.spy_price_history,
                key=lambda x: x['date']
            )[-25:]

    def _get_20_day_low(self):
        """Get SPY 20-day low (excluding today)"""
        if len(self.spy_price_history) < 2:
            return None

        # Sort by date, exclude most recent (today)
        sorted_history = sorted(self.spy_price_history, key=lambda x: x['date'])
        past_prices = sorted_history[:-1]  # Exclude today

        if len(past_prices) < 20:
            # Use what we have if less than 20 days
            return min(p['close'] for p in past_prices) if past_prices else None

        # Get last 20 days (excluding today)
        last_20 = past_prices[-20:]
        return min(p['close'] for p in last_20)

    def _check_sentiment_crisis(self, current_date):
        """
        Check for sentiment crisis conditions

        Returns:
            dict with 'triggered' and 'reason' if crisis detected, None otherwise
        """
        # Condition A: SPY closes below 20-day low
        twenty_day_low = self._get_20_day_low()
        if twenty_day_low is not None and self.spy_close < twenty_day_low:
            return {
                'triggered': True,
                'reason': f"SPY ${self.spy_close:.2f} below 20-day low ${twenty_day_low:.2f}"
            }

        # Condition B: Technical breakdown
        # SPY below 50 SMA + below 20 EMA + volume above average
        if self.spy_50_sma > 0 and self.spy_20_ema > 0:
            below_50_sma = self.spy_close < self.spy_50_sma
            below_20_ema = self.spy_close < self.spy_20_ema
            high_volume = (
                self.spy_volume > self.spy_avg_volume * SafeguardConfig.VOLUME_SURGE_THRESHOLD
                if self.spy_avg_volume > 0 else False
            )

            if below_50_sma and below_20_ema and high_volume:
                return {
                    'triggered': True,
                    'reason': f"Technical breakdown: SPY ${self.spy_close:.2f} < 50 SMA ${self.spy_50_sma:.2f} & 20 EMA ${self.spy_20_ema:.2f} on high volume"
                }

        return None

    def _check_crisis_recovery(self, current_date):
        """
        Check if crisis lockout can be lifted

        Requires:
        1. Minimum lockout days passed
        2. SPY closes above 20 EMA
        """
        if not self.crisis_active:
            return False

        # Check minimum lockout period
        if self.lockout_end_date and current_date < self.lockout_end_date:
            return False

        # Check SPY above 20 EMA
        if self.spy_20_ema > 0 and self.spy_close > self.spy_20_ema:
            return True

        return False

    def detect_regime(self, current_date=None, recovery_mode_active=False):
        """
        Main regime detection - two layer system

        Args:
            current_date: Current datetime
            recovery_mode_active: Whether recovery mode is active (from RecoveryModeManager)

        Returns:
            dict with action, allow_new_entries, exit_all, reason
        """
        # Build details dict
        details = {
            'spy_close': self.spy_close,
            'spy_20_ema': self.spy_20_ema,
            'spy_50_sma': self.spy_50_sma,
            'spy_200_sma': self.spy_200_sma,
            'spy_below_200': self._is_spy_below_200(),
            'twenty_day_low': self._get_20_day_low(),
            'crisis_active': self.crisis_active,
            'lockout_end_date': self.lockout_end_date,
        }

        # =================================================================
        # LAYER 2: SENTIMENT CRISIS (Highest Priority - No Override)
        # =================================================================

        # Check if in active crisis lockout
        if self.crisis_active:
            if self._check_crisis_recovery(current_date):
                # Crisis over - clear state
                self.crisis_active = False
                self.crisis_trigger_date = None
                self.crisis_trigger_reason = None
                self.lockout_end_date = None
                print(f"✅ CRISIS LOCKOUT LIFTED: SPY ${self.spy_close:.2f} above 20 EMA ${self.spy_20_ema:.2f}")
            else:
                # Still in lockout
                days_remaining = (
                            self.lockout_end_date - current_date).days if self.lockout_end_date and current_date else 0
                reason = f"CRISIS LOCKOUT: {self.crisis_trigger_reason}"
                if days_remaining > 0:
                    reason += f" ({days_remaining}d until eligible)"
                else:
                    reason += f" (waiting for SPY > 20 EMA ${self.spy_20_ema:.2f})"

                return {
                    'action': 'crisis_lockout',
                    'position_size_multiplier': 0.0,
                    'allow_new_entries': False,
                    'exit_all': False,  # Already exited when crisis triggered
                    'reason': reason,
                    'details': details
                }

        # Check for new crisis
        crisis_check = self._check_sentiment_crisis(current_date)
        if crisis_check and crisis_check['triggered']:
            # Trigger crisis
            self.crisis_active = True
            self.crisis_trigger_date = current_date
            self.crisis_trigger_reason = crisis_check['reason']
            self.lockout_end_date = current_date + timedelta(
                days=SafeguardConfig.CRISIS_LOCKOUT_DAYS + 2)  # +2 for weekends

            print(f"\n{'=' * 60}")
            print(f"🚨 SENTIMENT CRISIS TRIGGERED")
            print(f"   {crisis_check['reason']}")
            print(f"   Action: EXIT ALL POSITIONS")
            print(f"   Lockout until: {self.lockout_end_date.strftime('%Y-%m-%d')} + SPY > 20 EMA")
            print(f"{'=' * 60}\n")

            return {
                'action': 'crisis_exit',
                'position_size_multiplier': 0.0,
                'allow_new_entries': False,
                'exit_all': True,  # Signal to exit everything
                'reason': f"CRISIS: {crisis_check['reason']}",
                'details': details
            }

        # =================================================================
        # LAYER 1: SPY BELOW 200 SMA (Soft Block - Recovery Can Override)
        # =================================================================

        if self._is_spy_below_200():
            if recovery_mode_active:
                # Recovery mode overrides soft block
                return {
                    'action': 'recovery_override',
                    'position_size_multiplier': 1.0,  # Recovery mode sets its own multiplier
                    'allow_new_entries': True,
                    'exit_all': False,
                    'reason': f"SPY ${self.spy_close:.2f} < 200 SMA ${self.spy_200_sma:.2f} (Recovery Mode Override)",
                    'details': details
                }
            else:
                # Soft block - no new entries, keep positions
                return {
                    'action': 'trend_block',
                    'position_size_multiplier': 0.0,
                    'allow_new_entries': False,
                    'exit_all': False,
                    'reason': f"SPY ${self.spy_close:.2f} below 200 SMA ${self.spy_200_sma:.2f}",
                    'details': details
                }

        # =================================================================
        # NORMAL
        # =================================================================

        return {
            'action': 'normal',
            'position_size_multiplier': 1.0,
            'allow_new_entries': True,
            'exit_all': False,
            'reason': "Normal",
            'details': details
        }

    def _is_spy_below_200(self):
        """Check if SPY is below 200 SMA"""
        if self.spy_200_sma == 0:
            return False
        return self.spy_close < self.spy_200_sma

    def record_stop_loss(self, date, ticker, loss_pct):
        """
        No-op for compatibility with stock_position_monitoring.py

        Stop loss rate tracking was removed in simplified system.
        """
        pass

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

    def get_statistics(self):
        """Get current state for logging"""
        return {
            'spy_close': self.spy_close,
            'spy_20_ema': self.spy_20_ema,
            'spy_50_sma': self.spy_50_sma,
            'spy_200_sma': self.spy_200_sma,
            'spy_below_200': self._is_spy_below_200(),
            'twenty_day_low': self._get_20_day_low(),
            'crisis_active': self.crisis_active,
            'crisis_trigger_date': self.crisis_trigger_date,
            'crisis_trigger_reason': self.crisis_trigger_reason,
            'lockout_end_date': self.lockout_end_date,
            # Compatibility keys for account_profit_tracking.py
            'distribution_days': 0,
            'accumulation_days': 0,
            'net_distribution': 0,
        }