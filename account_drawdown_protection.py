from datetime import timedelta, datetime


# =============================================================================
# MARKET REGIME DETECTION
# =============================================================================

class MarketRegimeDetector:
    """
    Detects market tops, corrections, and bear markets.

    Priority order (first failure blocks trading):
    1. VIX Spike (immediate danger)
    2. Market Overextension (prevents buying tops)
    3. Bear Market (SPY below 200 SMA)
    4. Death Cross (EMA50 declining)
    5. Stock Weakness (individual stock health)
    """

    def __init__(self):
        self.VIX_SPIKE_THRESHOLD = 30.0
        self.VIX_LOOKBACK_DAYS = 5
        self.SPY_OVEREXTENSION_THRESHOLD = 5.0
        self.BEAR_MARKET_THRESHOLD = 0.0
        self.DEATH_CROSS_SLOPE = -0.15
        self.STOCK_WEAKNESS_THRESHOLD = -5.0

        # EVENT TRACKING
        self.regime_events = []  # List of all regime change events
        self.current_regime = 'bull'  # Track current state
        self.last_check_date = None
        self.blocks_by_type = {
            'VIX_SPIKE': 0,
            'OVEREXTENSION': 0,
            'BEAR_MARKET': 0,
            'DEATH_CROSS': 0
        }

    def detect_regime(self, spy_data, vix_data, stock_data=None):
        """Detect market regime using VIX, SPY, and optional stock data"""

        if not spy_data or not vix_data:
            return {
                'allow_trading': True,
                'regime': 'unknown',
                'description': '⚪ Missing data - allowing trading',
                'warnings': []
            }

        warnings = []

        # PRIORITY 1: VIX SPIKE
        vix_result = self._check_vix_spike(vix_data)
        if not vix_result['allow_trading']:
            return {
                'allow_trading': False,
                'regime': 'correction',
                'description': vix_result['description'],
                'warnings': vix_result['warnings']
            }
        warnings.extend(vix_result['warnings'])

        # PRIORITY 2: MARKET OVEREXTENSION
        overextension_result = self._check_overextension(spy_data)
        if not overextension_result['allow_trading']:
            return {
                'allow_trading': False,
                'regime': 'caution',
                'description': overextension_result['description'],
                'warnings': warnings + overextension_result['warnings']
            }
        warnings.extend(overextension_result['warnings'])

        # PRIORITY 3: BEAR MARKET
        bear_result = self._check_bear_market(spy_data)
        if not bear_result['allow_trading']:
            return {
                'allow_trading': False,
                'regime': 'bear',
                'description': bear_result['description'],
                'warnings': warnings + bear_result['warnings']
            }
        warnings.extend(bear_result['warnings'])

        # PRIORITY 4: DEATH CROSS
        death_cross_result = self._check_death_cross(spy_data)
        if not death_cross_result['allow_trading']:
            return {
                'allow_trading': False,
                'regime': 'bear',
                'description': death_cross_result['description'],
                'warnings': warnings + death_cross_result['warnings']
            }
        warnings.extend(death_cross_result['warnings'])

        # PRIORITY 5: STOCK WEAKNESS (if provided)
        if stock_data:
            stock_result = self._check_stock_weakness(stock_data)
            if not stock_result['allow_trading']:
                return {
                    'allow_trading': False,
                    'regime': 'caution',
                    'description': stock_result['description'],
                    'warnings': warnings + stock_result['warnings']
                }
            warnings.extend(stock_result['warnings'])

        # ALL CHECKS PASSED
        return {
            'allow_trading': True,
            'regime': 'bull',
            'description': '✅ BULL MARKET - All systems green',
            'warnings': warnings
        }

    def _check_vix_spike(self, vix_data):
        """Detect VIX spikes - 30% increase in 5 days blocks trading"""

        current_vix = vix_data.get('close', 0)
        vix_raw = vix_data.get('raw', None)

        if vix_raw is None or len(vix_raw) < self.VIX_LOOKBACK_DAYS + 1:
            return {'allow_trading': True, 'warnings': []}

        vix_lookback = vix_raw['close'].iloc[-(self.VIX_LOOKBACK_DAYS + 1)]
        vix_change_pct = ((current_vix - vix_lookback) / vix_lookback * 100)

        if vix_change_pct >= self.VIX_SPIKE_THRESHOLD:
            return {
                'allow_trading': False,
                'description': f'🚨 VIX SPIKE: +{vix_change_pct:.1f}% in {self.VIX_LOOKBACK_DAYS} days (VIX: {current_vix:.1f})',
                'warnings': [f'VIX spiked {vix_change_pct:.1f}%']
            }

        if vix_change_pct >= 20.0:
            return {
                'allow_trading': True,
                'warnings': [f'VIX rising: +{vix_change_pct:.1f}% (VIX: {current_vix:.1f})']
            }

        return {'allow_trading': True, 'warnings': []}

    def _check_overextension(self, spy_data):
        """SPY >5% above EMA50 = overextended"""

        spy_close = spy_data.get('close', 0)
        spy_ema50 = spy_data.get('ema50', 0)

        if spy_ema50 == 0:
            return {'allow_trading': True, 'warnings': []}

        distance = ((spy_close - spy_ema50) / spy_ema50 * 100)

        if distance > self.SPY_OVEREXTENSION_THRESHOLD:
            return {
                'allow_trading': False,
                'description': f'⚠️ OVEREXTENDED: SPY {distance:.1f}% above EMA50',
                'warnings': [f'SPY {distance:.1f}% above EMA50']
            }

        if distance > 3.0:
            return {
                'allow_trading': True,
                'warnings': [f'SPY extended: {distance:.1f}% above EMA50']
            }

        return {'allow_trading': True, 'warnings': []}

    def _check_bear_market(self, spy_data):
        """SPY below 200 SMA = bear market"""

        spy_close = spy_data.get('close', 0)
        spy_sma200 = spy_data.get('sma200', 0)

        if spy_sma200 == 0:
            return {'allow_trading': True, 'warnings': []}

        distance = ((spy_close - spy_sma200) / spy_sma200 * 100)

        if distance < self.BEAR_MARKET_THRESHOLD:
            return {
                'allow_trading': False,
                'description': f'🔴 BEAR MARKET: SPY {distance:.1f}% below 200 SMA',
                'warnings': [f'SPY {distance:.1f}% below 200 SMA']
            }

        if distance < 2.0:
            return {
                'allow_trading': True,
                'warnings': [f'SPY near 200 SMA: {distance:+.1f}%']
            }

        return {'allow_trading': True, 'warnings': []}

    def _check_death_cross(self, spy_data):
        """EMA50 declining = death cross forming"""

        spy_raw = spy_data.get('raw', None)

        if spy_raw is None or len(spy_raw) < 60:
            return {'allow_trading': True, 'warnings': []}

        ema50_series = spy_raw['close'].ewm(span=50, adjust=False).mean()

        if len(ema50_series) < 11:
            return {'allow_trading': True, 'warnings': []}

        ema50_current = ema50_series.iloc[-1]
        ema50_10d_ago = ema50_series.iloc[-11]
        slope = ((ema50_current - ema50_10d_ago) / ema50_10d_ago * 100) / 10

        if slope < self.DEATH_CROSS_SLOPE:
            return {
                'allow_trading': False,
                'description': f'🔴 DEATH CROSS: EMA50 declining {slope:.2f}%/day',
                'warnings': [f'EMA50 declining {slope:.2f}%/day']
            }

        if slope < -0.05:
            return {
                'allow_trading': True,
                'warnings': [f'EMA50 weakening: {slope:.2f}%/day']
            }

        return {'allow_trading': True, 'warnings': []}

    def _check_stock_weakness(self, stock_data):
        """Stock <5% below 200 SMA = weak"""

        close = stock_data.get('close', 0)
        sma200 = stock_data.get('sma200', 0)

        if sma200 == 0:
            return {'allow_trading': True, 'warnings': []}

        distance = ((close - sma200) / sma200 * 100)

        if distance < self.STOCK_WEAKNESS_THRESHOLD:
            return {
                'allow_trading': False,
                'description': f'🔴 WEAK STOCK: {distance:.1f}% below 200 SMA',
                'warnings': [f'Stock {distance:.1f}% below 200 SMA']
            }

        return {'allow_trading': True, 'warnings': []}

    def _log_regime_event(self, event_type, description, current_date=None):
        """Log a regime transition event"""
        event_date = current_date or datetime.now()

        # Update block counter
        if event_type in self.blocks_by_type:
            self.blocks_by_type[event_type] += 1

        # Map event types to regime states
        regime_map = {
            'VIX_SPIKE': 'correction',
            'OVEREXTENSION': 'caution',
            'BEAR_MARKET': 'bear',
            'DEATH_CROSS': 'bear',
            'RECOVERY': 'bull'
        }

        new_regime = regime_map.get(event_type, self.current_regime)

        # Only log if regime actually changed
        if new_regime != self.current_regime or event_type == 'RECOVERY':
            event = {
                'date': event_date,
                'event_type': event_type,
                'old_regime': self.current_regime,
                'new_regime': new_regime,
                'description': description
            }

            self.regime_events.append(event)
            self.current_regime = new_regime

            # Print to console for immediate feedback
            emoji = '🚨' if event_type != 'RECOVERY' else '✅'
            print(f"\n{emoji} REGIME EVENT: {event_type}")
            print(f"   Date: {event_date.strftime('%Y-%m-%d')}")
            print(f"   Transition: {event['old_regime']} → {new_regime}")
            print(f"   {description}\n")

    def get_regime_statistics(self):
        """Get regime event statistics for reporting"""
        return {
            'total_events': len(self.regime_events),
            'blocks_by_type': self.blocks_by_type.copy(),
            'current_regime': self.current_regime,
            'last_check_date': self.last_check_date,
            'events': self.regime_events.copy()
        }


# =============================================================================
# GLOBAL INSTANCE
# =============================================================================

detector = MarketRegimeDetector()


def detect_market_regime(spy_data, vix_data, stock_data=None):
    """Detect market regime"""
    return detector.detect_regime(spy_data, vix_data, stock_data)


def format_regime_display(regime_info):
    """Format regime info for console"""
    output = f"\n{'=' * 80}\n📊 MARKET REGIME\n{'=' * 80}\n"
    output += f"{regime_info['description']}\n"

    if regime_info.get('warnings'):
        output += "\n⚠️  Warnings:\n"
        for warning in regime_info['warnings']:
            output += f"   - {warning}\n"

    output += f"\n{'✅ Trading allowed' if regime_info['allow_trading'] else '🚫 Trading BLOCKED'}\n"
    output += f"{'=' * 80}\n"
    return output


# =============================================================================
# STOCK HEALTH CHECK
# =============================================================================

def check_stock_regime(ticker, stock_data):
    """Pre-entry health check for individual stock"""

    close = stock_data.get('close', 0)
    sma200 = stock_data.get('sma200', 0)
    ema20 = stock_data.get('ema20', 0)
    ema50 = stock_data.get('ema50', 0)
    rsi = stock_data.get('rsi', 50)

    if sma200 > 0:
        distance = ((close - sma200) / sma200 * 100)
        if distance <= 5:
            return (False, 0.0, f"⚠️ {ticker}: {distance:.1f}% from 200 SMA")

    if ema20 > 0 and ema50 > 0 and ema20 < ema50:
        return (False, 0.0, f"❌ {ticker}: EMA20 < EMA50")

    if rsi > 80:
        return (False, 0.0, f"⚠️ {ticker}: RSI {rsi:.0f} overbought")

    distance = ((close - sma200) / sma200 * 100) if sma200 > 0 else 0
    return (True, 1.0, f"✅ {ticker}: Healthy (SMA200: {distance:+.1f}%, RSI {rsi:.0f})")


# =============================================================================
# DRAWDOWN PROTECTION
# =============================================================================

class DrawdownProtection:
    """Portfolio drawdown protection - triggers at -8%, waits 5 days"""

    def __init__(self, threshold_pct=-8.0, recovery_days=5):
        self.threshold_pct = threshold_pct
        self.recovery_days = recovery_days
        self.portfolio_peak = None
        self.protection_active = False
        self.protection_end_date = None
        self.trigger_count = 0
        self.max_drawdown_seen = 0.0

    def update_peak(self, current_portfolio_value):
        """Update portfolio peak"""
        if self.portfolio_peak is None:
            self.portfolio_peak = current_portfolio_value
            return

        if current_portfolio_value > self.portfolio_peak:
            self.portfolio_peak = current_portfolio_value
            if self.protection_active:
                self.protection_active = False
                self.protection_end_date = None

    def calculate_drawdown(self, current_portfolio_value):
        """Calculate drawdown % from peak"""
        if self.portfolio_peak is None or self.portfolio_peak == 0:
            return 0.0

        drawdown_pct = ((current_portfolio_value - self.portfolio_peak) / self.portfolio_peak * 100)
        if drawdown_pct < self.max_drawdown_seen:
            self.max_drawdown_seen = drawdown_pct

        return drawdown_pct

    def should_trigger(self, current_portfolio_value):
        """Check if should trigger"""
        self.update_peak(current_portfolio_value)
        drawdown_pct = self.calculate_drawdown(current_portfolio_value)
        return drawdown_pct <= self.threshold_pct and not self.protection_active

    def activate(self, strategy, current_date, position_monitor=None):
        """Activate protection - close all positions"""
        drawdown_pct = self.calculate_drawdown(strategy.portfolio_value)

        print(f"\n{'=' * 80}")
        print(f"🚨 DRAWDOWN PROTECTION TRIGGERED")
        print(f"Peak: ${self.portfolio_peak:,.2f} → Current: ${strategy.portfolio_value:,.2f}")
        print(f"Drawdown: {drawdown_pct:.1f}%")
        print(f"{'=' * 80}\n")

        closed_count = 0
        for position in strategy.get_positions():
            qty = int(position.quantity)
            if qty > 0:
                print(f"   🚪 {position.symbol} x{qty}")
                strategy.submit_order(strategy.create_order(position.symbol, qty, 'sell'))
                if position_monitor:
                    position_monitor.clean_position_metadata(position.symbol)
                closed_count += 1

        self.protection_active = True
        self.protection_end_date = current_date + timedelta(days=self.recovery_days)
        self.trigger_count += 1

        print(f"\n   ✅ Closed {closed_count} position(s)")
        print(f"   📅 Recovery until {self.protection_end_date.strftime('%Y-%m-%d')}\n")

    def is_in_recovery(self, current_date):
        """Check if in recovery"""
        if self.protection_end_date is None:
            return False
        return current_date < self.protection_end_date

    def get_recovery_days_remaining(self, current_date):
        """Get days remaining"""
        if not self.is_in_recovery(current_date):
            return 0
        return (self.protection_end_date - current_date).days

    def print_status(self, current_portfolio_value, current_date):
        """Print status"""
        self.update_peak(current_portfolio_value)
        drawdown_pct = self.calculate_drawdown(current_portfolio_value)

        if self.is_in_recovery(current_date):
            days = self.get_recovery_days_remaining(current_date)
            print(f"\n🛡️ PROTECTION: Recovery period ({days} days remaining)")
            print(f"   Drawdown: {drawdown_pct:.1f}% from ${self.portfolio_peak:,.2f}\n")
        elif drawdown_pct < -5.0:
            print(f"\n⚠️ Drawdown: {drawdown_pct:.1f}% from ${self.portfolio_peak:,.2f}\n")

    def get_statistics(self):
        """Get statistics"""
        return {
            'threshold_pct': self.threshold_pct,
            'recovery_days': self.recovery_days,
            'portfolio_peak': self.portfolio_peak,
            'protection_active': self.protection_active,
            'protection_end_date': self.protection_end_date,
            'trigger_count': self.trigger_count,
            'max_drawdown_seen': self.max_drawdown_seen
        }


def create_default_protection(threshold_pct=-8.0, recovery_days=5):
    """Create default drawdown protection"""
    return DrawdownProtection(threshold_pct, recovery_days)