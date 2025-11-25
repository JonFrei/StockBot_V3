from datetime import timedelta, datetime
import pandas as pd


# =============================================================================
# SIMPLIFIED MARKET REGIME DETECTION
# =============================================================================

def detect_market_regime(spy_data, stock_data=None):

    warnings = []

    if not spy_data:
        return {
            'allow_trading': True,
            'position_size_multiplier': 1.0,
            'description': '⚪ No SPY data - allowing trading',
            'warnings': ['No SPY data available']
        }

    spy_close = spy_data.get('close', 0)
    spy_sma200 = spy_data.get('sma200', 0)
    spy_ema50 = spy_data.get('ema50', 0)
    spy_raw = spy_data.get('raw', None)

    # =================================================================
    # CHECK 1: SPY BELOW 200 SMA (Classic bear market)
    # =================================================================

    if spy_close < spy_sma200*1.05 and spy_sma200 > 0:
        distance_below = ((spy_close - spy_sma200) / spy_sma200 * 100)
        return {
            'allow_trading': False,
            'description': f'🔴 BEAR MARKET: SPY {distance_below:.1f}% below 200 SMA - BLOCKED',
            'warnings': ['SPY below 200 SMA']
        }

    # =================================================================
    # CHECK 2: DEATH CROSS FORMING (EMA50 declining)
    # =================================================================

    if spy_raw is not None and len(spy_raw) >= 60:
        try:
            ema50_series = spy_raw['close'].ewm(span=50, adjust=False).mean()

            if len(ema50_series) >= 11:
                ema50_current = ema50_series.iloc[-1]
                ema50_10d_ago = ema50_series.iloc[-11]
                ema50_slope = ((ema50_current - ema50_10d_ago) / ema50_10d_ago * 100) / 10

                # If EMA50 declining more than 0.15% per day = death cross forming
                if ema50_slope < -0.15:
                    warnings.append(f'EMA50 declining {ema50_slope:.2f}%/day')

                    return {
                        'allow_trading': False,
                        'description': f'🔴 DEATH CROSS FORMING: EMA50 declining {ema50_slope:.2f}%/day - BLOCKED',
                        'warnings': warnings
                    }
        except Exception as e:
            # Don't block on calculation error
            pass

    # =================================================================
    # CHECK 3: STOCK-SPECIFIC WEAKNESS (if stock_data provided)
    # =================================================================

    if stock_data:
        stock_close = stock_data.get('close', 0)
        stock_sma200 = stock_data.get('sma200', 0)

        if stock_sma200 > 0:
            distance_from_200 = ((stock_close - stock_sma200) / stock_sma200 * 100)

            # Stock must be within 5% of 200 SMA
            if distance_from_200 < -5.0:
                return {
                    'allow_trading': False,
                    'description': f'🔴 STOCK WEAKNESS: {distance_from_200:.1f}% below 200 SMA - BLOCKED',
                    'warnings': [f'Stock {distance_from_200:.1f}% below 200 SMA']
                }

    return {
        'allow_trading': True,
        'description': "None",
        'warnings': ["None"]
    }


def format_regime_display(regime_info):
    """Format regime info for console display"""

    output = f"\n{'=' * 80}\n"
    output += f"📊 MARKET REGIME CHECK\n"
    output += f"{'=' * 80}\n"
    output += f"{regime_info['description']}\n"

    if regime_info.get('warnings'):
        output += f"\n⚠️  Warnings:\n"
        for warning in regime_info['warnings']:
            output += f"   - {warning}\n"

    if regime_info['allow_trading']:
        output += f"\n✅ Trading allowed"
    else:
        output += f"\n🚫 Trading BLOCKED"

    output += f"\n{'=' * 80}\n"

    return output


# =============================================================================
# DRAWDOWN PROTECTION SYSTEM (Keep as-is, works well)
# =============================================================================

class DrawdownProtection:
    """
    Portfolio-level drawdown protection

    Triggers at -8% from peak, closes all positions, waits 5 days
    This system works well - no changes needed
    """

    def __init__(self, threshold_pct=-8.0, recovery_days=5):
        """
        Initialize drawdown protection

        Args:
            threshold_pct: Drawdown % to trigger (default -8%)
            recovery_days: Days to wait after trigger (default 5)
        """
        self.threshold_pct = threshold_pct
        self.recovery_days = recovery_days

        self.portfolio_peak = None
        self.protection_active = False
        self.protection_end_date = None

        self.trigger_count = 0
        self.max_drawdown_seen = 0.0

    def update_peak(self, current_portfolio_value):
        """Update portfolio peak if new high reached"""
        if self.portfolio_peak is None:
            self.portfolio_peak = current_portfolio_value
            return

        if current_portfolio_value > self.portfolio_peak:
            self.portfolio_peak = current_portfolio_value

            if self.protection_active:
                self.protection_active = False
                self.protection_end_date = None

    def calculate_drawdown(self, current_portfolio_value):
        """Calculate current drawdown % from peak"""
        if self.portfolio_peak is None or self.portfolio_peak == 0:
            return 0.0

        drawdown_pct = ((current_portfolio_value - self.portfolio_peak) / self.portfolio_peak * 100)

        if drawdown_pct < self.max_drawdown_seen:
            self.max_drawdown_seen = drawdown_pct

        return drawdown_pct

    def should_trigger(self, current_portfolio_value):
        """Check if drawdown protection should trigger"""
        self.update_peak(current_portfolio_value)
        drawdown_pct = self.calculate_drawdown(current_portfolio_value)

        if drawdown_pct <= self.threshold_pct and not self.protection_active:
            return True

        return False

    def activate(self, strategy, current_date, position_monitor=None):
        """Activate protection - close all positions"""
        current_portfolio_value = strategy.portfolio_value
        drawdown_pct = self.calculate_drawdown(current_portfolio_value)

        print(f"\n{'=' * 80}")
        print(f"🚨 DRAWDOWN PROTECTION TRIGGERED")
        print(f"{'=' * 80}")
        print(f"Peak: ${self.portfolio_peak:,.2f}")
        print(f"Current: ${current_portfolio_value:,.2f}")
        print(f"Drawdown: {drawdown_pct:.1f}%")
        print(f"\n🛑 CLOSING ALL POSITIONS - Going to cash for {self.recovery_days} days")
        print(f"{'=' * 80}\n")

        # Close all positions
        positions = strategy.get_positions()
        closed_count = 0

        for position in positions:
            ticker = position.symbol
            qty = int(position.quantity)

            if qty > 0:
                print(f"   🚪 Emergency Exit: {ticker} x{qty}")
                sell_order = strategy.create_order(ticker, qty, 'sell')
                strategy.submit_order(sell_order)
                closed_count += 1

                if position_monitor:
                    position_monitor.clean_position_metadata(ticker)

        self.protection_active = True
        self.protection_end_date = current_date + timedelta(days=self.recovery_days)
        self.trigger_count += 1

        print(f"\n   ✅ Closed {closed_count} position(s)")
        print(f"   📅 Protection active until {self.protection_end_date.strftime('%Y-%m-%d')}\n")

    def is_in_recovery(self, current_date):
        """Check if in recovery period"""
        if self.protection_end_date is None:
            return False
        return current_date < self.protection_end_date

    def get_recovery_days_remaining(self, current_date):
        """Get days remaining in recovery"""
        if not self.is_in_recovery(current_date):
            return 0
        return (self.protection_end_date - current_date).days

    def print_status(self, current_portfolio_value, current_date):
        """Print current status"""
        self.update_peak(current_portfolio_value)
        drawdown_pct = self.calculate_drawdown(current_portfolio_value)

        if self.is_in_recovery(current_date):
            days_remaining = self.get_recovery_days_remaining(current_date)
            print(f"\n🛡️ PROTECTION MODE: Recovery period ({days_remaining} days remaining)")
            print(f"   Drawdown: {drawdown_pct:.1f}% from peak ${self.portfolio_peak:,.2f}\n")
        elif drawdown_pct < -5.0:
            print(f"\n⚠️  Portfolio Drawdown: {drawdown_pct:.1f}% from peak ${self.portfolio_peak:,.2f}")
            print(f"   Protection triggers at {self.threshold_pct:.1f}%\n")

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
    """Create default drawdown protection instance"""
    return DrawdownProtection(threshold_pct=threshold_pct, recovery_days=recovery_days)


def print_protection_summary(protection):
    """Print detailed protection summary"""
    stats = protection.get_statistics()

    print(f"\n{'=' * 80}")
    print(f"🛡️ DRAWDOWN PROTECTION SUMMARY")
    print(f"{'=' * 80}")
    print(f"Threshold: {stats['threshold_pct']:.1f}%")
    print(f"Recovery Period: {stats['recovery_days']} days")
    print(f"Times Triggered: {stats['trigger_count']}")
    print(f"Max Drawdown: {stats['max_drawdown_seen']:.1f}%")

    if stats['portfolio_peak']:
        print(f"Portfolio Peak: ${stats['portfolio_peak']:,.2f}")

    if stats['protection_active']:
        print(f"\n⚠️  Currently in protection mode")
        if stats['protection_end_date']:
            print(f"   Recovery ends: {stats['protection_end_date'].strftime('%Y-%m-%d')}")
    else:
        print(f"\n✅ Protection armed and monitoring")

    print(f"{'=' * 80}\n")