"""
Market Safeguard System - WITH PORTFOLIO DRAWDOWN PROTECTION

Three-Layer Protection:

Layer 0: Portfolio Drawdown (Highest Priority)
- Portfolio drops 10% from 30-day rolling peak → Exit ALL positions
- 5-day cooldown lockout
- Cannot be overridden by Recovery Mode

Layer 1: Market Trend Gate (Soft Block)
- SPY below 200 SMA → Block new entries (keep positions)
- Recovery Mode can override this

Layer 2: Sentiment Crisis (Hard Exit)
- SPY closes below 20-day low OR
- Technical breakdown (SPY < 50 SMA + < 20 EMA + high volume)
- Action: Exit ALL positions, lockout 5 days + wait for 20 EMA reclaim
- Recovery Mode CAN override during lockout (not during initial exit)
"""

from datetime import timedelta


class SafeguardConfig:
    """Safeguard configuration"""

    # Layer 0: Portfolio Drawdown Protection
    PORTFOLIO_DRAWDOWN_THRESHOLD = 10.0  # Exit all at 10% drawdown
    PORTFOLIO_DRAWDOWN_LOOKBACK = 30  # Rolling 30-day peak
    PORTFOLIO_DRAWDOWN_COOLDOWN_DAYS = 5  # Lockout after trigger

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
    RELATIVE_STRENGTH_MIN_OUTPERFORM = 0.0  # Stock must outperform SPY by this %


class MarketRegimeDetector:
    """
    Market regime detection with portfolio drawdown protection

    Three layers:
    0. Portfolio drawdown 15% from 30-day peak → Hard exit + lockout (highest priority)
    1. SPY < 200 SMA → Soft block (recovery can override)
    2. Sentiment Crisis → Hard exit + lockout (recovery can override during lockout)
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

        # Crisis state (Layer 2)
        self.crisis_active = False
        self.crisis_trigger_date = None
        self.crisis_trigger_reason = None
        self.lockout_end_date = None

        # Portfolio drawdown tracking (Layer 0)
        self.portfolio_value_history = []  # [{'date': date, 'value': float}]
        self.portfolio_drawdown_active = False
        self.portfolio_drawdown_trigger_date = None
        self.portfolio_drawdown_lockout_end = None

    def update_spy(self, date, spy_close, spy_20_ema, spy_50_sma, spy_200_sma,
                   spy_volume=None, spy_avg_volume=None):
        """Update SPY data"""
        self.spy_close = spy_close
        self.spy_20_ema = spy_20_ema
        self.spy_50_sma = spy_50_sma
        self.spy_200_sma = spy_200_sma
        self.spy_volume = spy_volume or 0
        self.spy_avg_volume = spy_avg_volume or 0

        # Normalize date
        if hasattr(date, 'tzinfo') and date.tzinfo is not None:
            date = date.replace(tzinfo=None)

        # Update price history
        self.spy_price_history.append({'date': date, 'close': spy_close})
        self.spy_price_history = self.spy_price_history[-25:]

    def update_portfolio_value(self, date, portfolio_value):
        """Update portfolio value for drawdown tracking"""
        if hasattr(date, 'tzinfo') and date.tzinfo is not None:
            date = date.replace(tzinfo=None)

        self.portfolio_value_history.append({'date': date, 'value': portfolio_value})
        self.portfolio_value_history = self.portfolio_value_history[-35:]

    def _get_20_day_low(self):
        """Get 20-day low for crisis detection"""
        if len(self.spy_price_history) < 20:
            return None
        closes = [p['close'] for p in self.spy_price_history[-20:]]
        return min(closes)

    def _get_rolling_peak(self):
        """Get rolling 30-day peak for drawdown calculation"""
        if not self.portfolio_value_history:
            return None
        values = [p['value'] for p in self.portfolio_value_history[-SafeguardConfig.PORTFOLIO_DRAWDOWN_LOOKBACK:]]
        return max(values) if values else None

    def _check_sentiment_crisis(self, current_date):
        """
        Check for sentiment crisis conditions

        Triggers on:
        1. SPY closes below 20-day low
        2. Technical breakdown: SPY < 50 SMA AND < 20 EMA with volume surge
        """
        # Condition 1: SPY below 20-day low
        twenty_day_low = self._get_20_day_low()
        if twenty_day_low and self.spy_close < twenty_day_low:
            return {
                'triggered': True,
                'reason': f"SPY ${self.spy_close:.2f} below 20-day low ${twenty_day_low:.2f}"
            }

        # Condition 2: Technical breakdown
        if (self.spy_close < self.spy_50_sma and
                self.spy_close < self.spy_20_ema and
                self.spy_avg_volume > 0 and
                self.spy_volume > self.spy_avg_volume * SafeguardConfig.VOLUME_SURGE_THRESHOLD):
            return {
                'triggered': True,
                'reason': f"Technical breakdown: SPY ${self.spy_close:.2f} < 50 SMA ${self.spy_50_sma:.2f} & 20 EMA ${self.spy_20_ema:.2f} on high volume"
            }

        return None

    def _check_crisis_recovery(self, current_date):
        """Check if crisis lockout can be lifted"""
        if not self.crisis_active:
            return False

        # Must be past minimum lockout period
        if self.lockout_end_date and current_date < self.lockout_end_date:
            return False

        # SPY must be above 20 EMA
        if self.spy_close > self.spy_20_ema:
            return True

        return False

    def _check_portfolio_drawdown(self, current_date):
        """Check for portfolio drawdown trigger"""
        if self.portfolio_drawdown_active:
            return None

        rolling_peak = self._get_rolling_peak()
        if not rolling_peak or not self.portfolio_value_history:
            return None

        current_value = self.portfolio_value_history[-1]['value']
        drawdown_pct = (rolling_peak - current_value) / rolling_peak * 100

        if drawdown_pct >= SafeguardConfig.PORTFOLIO_DRAWDOWN_THRESHOLD:
            return {
                'triggered': True,
                'reason': f"Portfolio down {drawdown_pct:.1f}% from 30-day peak ${rolling_peak:,.0f}",
                'drawdown_pct': drawdown_pct,
                'peak': rolling_peak
            }

        return None

    def _check_portfolio_drawdown_recovery(self, current_date):
        """Check if portfolio drawdown lockout can be lifted"""
        if not self.portfolio_drawdown_active:
            return False

        # Condition 1: Must be past minimum lockout period
        if self.portfolio_drawdown_lockout_end and current_date >= self.portfolio_drawdown_lockout_end:
            return True

        # Condition 2: Market stability check - don't re-enter into active crash
        # If SPY is below 20 EMA AND making new 5-day lows, stay locked
        if self.spy_close < self.spy_20_ema:
            five_day_low = self._get_n_day_low(5)
            if five_day_low and self.spy_close <= five_day_low * 1.002:  # Within 0.2% of 5-day low
                return False  # Market still falling, stay locked

        return False

    def _add_trading_days(self, start_date, trading_days):
        """
        Add N trading days to a date, skipping weekends.

        Args:
            start_date: Starting datetime
            trading_days: Number of trading days to add

        Returns:
            datetime after N trading days
        """
        current = start_date
        days_added = 0

        while days_added < trading_days:
            current += timedelta(days=1)
            # Skip weekends (Saturday=5, Sunday=6)
            if current.weekday() < 5:
                days_added += 1

        return current

    def _get_n_day_low(self, days):
        """Get N-day low from price history"""
        if len(self.spy_price_history) < days:
            return None
        closes = [p['close'] for p in self.spy_price_history[-days:]]
        return min(closes)

    # =========================================================================
    # MAIN REGIME DETECTION
    # =========================================================================

    def detect_regime(self, current_date=None, recovery_mode_active=False, recovery_entry_method=None):
        """
        Main regime detection - three layer system

        Args:
            current_date: Current datetime
            recovery_mode_active: Whether recovery mode is active (from RecoveryModeManager)
            recovery_entry_method: 'structure' or 'time_based' if recovery is active

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
            'portfolio_drawdown_active': self.portfolio_drawdown_active,
            'portfolio_rolling_peak': self._get_rolling_peak(),
        }

        # =================================================================
        # LAYER 0: PORTFOLIO DRAWDOWN (Highest Priority - No Override)
        # =================================================================

        # Check if in active portfolio drawdown lockout
        if self.portfolio_drawdown_active:
            if self._check_portfolio_drawdown_recovery(current_date):
                self.portfolio_drawdown_active = False
                self.portfolio_drawdown_trigger_date = None
                self.portfolio_drawdown_lockout_end = None
                print(f"✅ PORTFOLIO DRAWDOWN LOCKOUT LIFTED")
            else:
                days_remaining = (self.portfolio_drawdown_lockout_end - current_date).days if self.portfolio_drawdown_lockout_end else 0
                return {
                    'action': 'portfolio_drawdown_lockout',
                    'position_size_multiplier': 0.0,
                    'allow_new_entries': False,
                    'exit_all': False,
                    'reason': f"PORTFOLIO DRAWDOWN LOCKOUT ({days_remaining}d remaining)",
                    'details': details,
                    'lockout_type': 'portfolio_drawdown'
                }

        # Check for new portfolio drawdown trigger
        drawdown_check = self._check_portfolio_drawdown(current_date)
        if drawdown_check and drawdown_check['triggered']:
            self.portfolio_drawdown_active = True
            self.portfolio_drawdown_trigger_date = current_date
            # self.portfolio_drawdown_lockout_end = current_date + timedelta(days=SafeguardConfig.PORTFOLIO_DRAWDOWN_COOLDOWN_DAYS + 2)
            self.portfolio_drawdown_lockout_end = self._add_trading_days(current_date,
                                                                         SafeguardConfig.PORTFOLIO_DRAWDOWN_COOLDOWN_DAYS)

            print(f"\n{'=' * 60}")
            print(f"🚨 PORTFOLIO DRAWDOWN TRIGGERED")
            print(f"   {drawdown_check['reason']}")
            print(f"   Action: EXIT ALL POSITIONS")
            print(f"   Lockout until: {self.portfolio_drawdown_lockout_end.strftime('%Y-%m-%d')}")
            print(f"{'=' * 60}\n")

            return {
                'action': 'portfolio_drawdown_exit',
                'position_size_multiplier': 0.0,
                'allow_new_entries': False,
                'exit_all': True,
                'reason': f"PORTFOLIO DRAWDOWN: {drawdown_check['reason']}",
                'details': details,
                'lockout_type': 'portfolio_drawdown'
            }

        # =================================================================
        # LAYER 2: SENTIMENT CRISIS
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
                # Still in lockout - but recovery mode CAN override
                days_remaining = (self.lockout_end_date - current_date).days if self.lockout_end_date and current_date else 0
                reason = f"CRISIS LOCKOUT: {self.crisis_trigger_reason}"
                if days_remaining > 0:
                    reason += f" ({days_remaining}d until eligible)"
                else:
                    reason += f" (waiting for SPY > 20 EMA ${self.spy_20_ema:.2f})"

                # Recovery mode can override crisis lockout (not initial exit)
                if recovery_mode_active:
                    mode_type = "FULL" if recovery_entry_method == 'structure' else "CAUTIOUS"
                    return {
                        'action': 'recovery_override',
                        'position_size_multiplier': 1.0,  # Recovery mode sets its own multiplier
                        'allow_new_entries': True,
                        'exit_all': False,
                        'reason': f"Crisis Lockout - Recovery Mode {mode_type} Override",
                        'details': details,
                        'lockout_type': 'crisis',
                        'recovery_override': True
                    }

                return {
                    'action': 'crisis_lockout',
                    'position_size_multiplier': 0.0,
                    'allow_new_entries': False,
                    'exit_all': False,
                    'reason': reason,
                    'details': details,
                    'lockout_type': 'crisis'
                }

        # Check for new crisis
        crisis_check = self._check_sentiment_crisis(current_date)
        if crisis_check and crisis_check['triggered']:
            # Trigger crisis - this is an EXIT event, recovery cannot override
            self.crisis_active = True
            self.crisis_trigger_date = current_date
            self.crisis_trigger_reason = crisis_check['reason']
            # self.lockout_end_date = current_date + timedelta(days=SafeguardConfig.CRISIS_LOCKOUT_DAYS + 2)
            self.lockout_end_date = self._add_trading_days(current_date, SafeguardConfig.CRISIS_LOCKOUT_DAYS)

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
                'exit_all': True,
                'reason': f"CRISIS: {crisis_check['reason']}",
                'details': details,
                'lockout_type': 'crisis'
            }

        # =================================================================
        # LAYER 1: SPY BELOW 200 SMA (Soft Block - Recovery Can Override)
        # =================================================================

        if self._is_spy_below_200():
            if recovery_mode_active:
                # Recovery mode overrides soft block
                mode_type = "FULL" if recovery_entry_method == 'structure' else "CAUTIOUS"
                return {
                    'action': 'recovery_override',
                    'position_size_multiplier': 1.0,  # Recovery mode sets its own multiplier
                    'allow_new_entries': True,
                    'exit_all': False,
                    'reason': f"SPY ${self.spy_close:.2f} < 200 SMA ${self.spy_200_sma:.2f} (Recovery Mode {mode_type} Override)",
                    'details': details,
                    'lockout_type': 'trend_block',
                    'recovery_override': True
                }
            else:
                # Soft block - no new entries, keep positions
                return {
                    'action': 'trend_block',
                    'position_size_multiplier': 0.0,
                    'allow_new_entries': False,
                    'exit_all': False,
                    'reason': f"SPY ${self.spy_close:.2f} below 200 SMA ${self.spy_200_sma:.2f}",
                    'details': details,
                    'lockout_type': 'trend_block'
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
            'details': details,
            'lockout_type': None
        }

    def _is_spy_below_200(self):
        """Check if SPY is below 200 SMA"""
        if self.spy_200_sma == 0:
            return False
        return self.spy_close < self.spy_200_sma

    # def record_stop_loss(self, date, ticker, loss_pct):
    #     """No-op for compatibility"""
    #     pass

    # =========================================================================
    # STATISTICS / COMPATIBILITY
    # =========================================================================

    def get_statistics(self):
        """Get current state for logging and persistence"""
        return {
            'spy_close': self.spy_close,
            'spy_20_ema': self.spy_20_ema,
            'spy_50_sma': self.spy_50_sma,
            'spy_200_sma': self.spy_200_sma,
            'spy_below_200': self._is_spy_below_200(),
            'crisis_active': self.crisis_active,
            'crisis_trigger_date': self.crisis_trigger_date,
            'crisis_trigger_reason': self.crisis_trigger_reason,
            'lockout_end_date': self.lockout_end_date,
            'portfolio_drawdown_active': self.portfolio_drawdown_active,
            'portfolio_drawdown_trigger_date': self.portfolio_drawdown_trigger_date,
            'portfolio_drawdown_lockout_end': self.portfolio_drawdown_lockout_end,
            'portfolio_rolling_peak': self._get_rolling_peak(),
            'twenty_day_low': self._get_20_day_low(),
        }

    # =========================================================================
    # HIGH-LEVEL REGIME EVALUATION
    # =========================================================================

    def evaluate_regime(self, strategy, current_date, recovery_manager):
        """
        High-level regime evaluation - orchestrates data gathering and detection

        Args:
            strategy: The trading strategy (for portfolio value and data access)
            current_date: Current datetime
            recovery_manager: RecoveryModeManager instance

        Returns:
            dict with action, reason, position_size_multiplier, and optional recovery_details
        """
        import stock_data

        # Get SPY data
        try:
            spy_data = stock_data.process_data(['SPY'], current_date)
            if 'SPY' in spy_data:
                spy_ind = spy_data['SPY']['indicators']
                spy_raw = spy_data['SPY'].get('raw')

                # Get volume data if available
                spy_volume = 0
                spy_avg_volume = 0
                if spy_raw is not None and 'volume' in spy_raw.columns:
                    spy_volume = spy_raw['volume'].iloc[-1]
                    spy_avg_volume = spy_ind.get('avg_volume', 0)

                self.update_spy(
                    date=current_date,
                    spy_close=spy_ind.get('close', 0),
                    spy_20_ema=spy_ind.get('ema20', 0),
                    spy_50_sma=spy_ind.get('sma50', 0),
                    spy_200_sma=spy_ind.get('sma200', 0),
                    spy_volume=spy_volume,
                    spy_avg_volume=spy_avg_volume
                )

                if recovery_manager:
                    # Get OHLCV data for recovery manager
                    spy_open = spy_raw['open'].iloc[-1] if spy_raw is not None and 'open' in spy_raw.columns else None
                    spy_high = spy_raw['high'].iloc[-1] if spy_raw is not None and 'high' in spy_raw.columns else None
                    spy_low = spy_raw['low'].iloc[-1] if spy_raw is not None and 'low' in spy_raw.columns else None

                    recovery_manager.update_spy_data(
                        date=current_date,
                        spy_close=spy_ind.get('close', 0),
                        spy_open=spy_open,
                        spy_high=spy_high,
                        spy_low=spy_low,
                        spy_volume=spy_volume,
                        spy_avg_volume=spy_avg_volume,
                        spy_prev_close=spy_ind.get('prev_close'),
                        spy_ema10=spy_ind.get('ema8'),  # Using ema8 as proxy for ema10
                        spy_ema20=spy_ind.get('ema20')
                    )

        except Exception as e:
            print(f"[REGIME] Warning: Could not fetch SPY data: {e}")

        # Update portfolio value for drawdown tracking
        portfolio_value = None
        try:
            portfolio_value = strategy.get_portfolio_value()
            if portfolio_value and portfolio_value > 0:
                self.update_portfolio_value(current_date, portfolio_value)
        except Exception as e:
            print(f"[REGIME] Warning: Could not get portfolio value: {e}")

        # =====================================================================
        # STEP 1: Run initial regime detection (without recovery mode)
        # =====================================================================
        initial_result = self.detect_regime(
            current_date=current_date,
            recovery_mode_active=False
        )

        # =====================================================================
        # STEP 2: Evaluate recovery mode with lockout information
        # =====================================================================
        recovery_mode_active = False
        recovery_details = None
        recovery_result = None

        if recovery_manager:
            # Determine lockout status from initial regime result
            lockout_type = initial_result.get('lockout_type')
            lockout_active = initial_result['action'] in ['crisis_lockout', 'trend_block', 'crisis_exit']
            spy_below_200 = self._is_spy_below_200()

            # Calculate deployed capital for breadth check
            deployed_capital = 0
            try:
                cash = strategy.get_cash()
                if portfolio_value and cash:
                    deployed_capital = portfolio_value - cash
            except Exception:
                pass

            # Evaluate recovery mode with full context
            recovery_result = recovery_manager.evaluate(
                current_date=current_date,
                spy_below_200=spy_below_200,
                lockout_type=lockout_type,
                lockout_active=lockout_active,
                deployed_capital=deployed_capital
            )

            # Update portfolio value in recovery manager for exit tracking
            if portfolio_value:
                recovery_manager.update_portfolio_value(portfolio_value)

            recovery_mode_active = recovery_result.get('recovery_mode_active', False)

            if recovery_mode_active:
                recovery_details = {
                    'start_date': recovery_manager.recovery_mode_start_date,
                    'activation_count': recovery_manager.activation_count,
                    'entry_method': recovery_manager.recovery_entry_method,
                    'position_multiplier': recovery_result.get('position_multiplier', 1.0),
                    'max_positions': recovery_result.get('max_positions', 8),
                    # 'profit_target': recovery_result.get('profit_target', 5.0),
                    # 'stop_multiplier': recovery_result.get('stop_multiplier', 1.0),
                    # 'eligible_tiers': recovery_result.get('eligible_tiers', ['premium', 'active'])
                }

        # =====================================================================
        # STEP 3: Re-run regime detection with recovery mode status
        # =====================================================================
        if recovery_mode_active:
            result = self.detect_regime(
                current_date=current_date,
                recovery_mode_active=True,
                recovery_entry_method=recovery_manager.recovery_entry_method if recovery_manager else None
            )
        else:
            result = initial_result

        # Add recovery details if applicable
        if recovery_details:
            result['recovery_details'] = recovery_details
            # Override position sizing with recovery mode settings
            result['position_size_multiplier'] = recovery_details['position_multiplier']

        # Add recovery status to result for logging
        if recovery_result:
            result['recovery_status'] = recovery_result.get('reason', '')
            result['recovery_signals'] = recovery_result.get('signals', {})

        return result