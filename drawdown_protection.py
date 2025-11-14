"""
Portfolio Drawdown Protection System

Protects portfolio from deep drawdowns by:
1. Tracking portfolio peak (highest value achieved)
2. Monitoring current drawdown percentage
3. Triggering circuit breaker when threshold exceeded
4. Closing all positions and going to cash
5. Enforcing recovery period before allowing new entries

Usage:
    protection = DrawdownProtection(
        threshold_pct=-10.0,
        recovery_days=5
    )

    # In strategy loop:
    if protection.should_trigger(portfolio_value):
        protection.activate(strategy, current_date)
        return  # Skip rest of iteration

    if protection.is_in_recovery(current_date):
        # Only process exits, no new entries
        return
"""

from datetime import timedelta


class DrawdownProtection:
    """
    Manages portfolio-level drawdown protection

    Attributes:
        threshold_pct: Drawdown % to trigger protection (e.g., -10.0 = -10%)
        recovery_days: Days to wait before allowing new positions
        portfolio_peak: Highest portfolio value achieved
        protection_active: Whether protection is currently active
        protection_end_date: When recovery period ends
    """

    def __init__(self, threshold_pct=-10.0, recovery_days=5):
        """
        Initialize drawdown protection

        Args:
            threshold_pct: Drawdown percentage to trigger (default -10%)
            recovery_days: Days to wait after trigger (default 5)
        """
        self.threshold_pct = threshold_pct
        self.recovery_days = recovery_days

        # State tracking
        self.portfolio_peak = None
        self.protection_active = False
        self.protection_end_date = None

        # Statistics
        self.trigger_count = 0
        self.max_drawdown_seen = 0.0

    def update_peak(self, current_portfolio_value):
        """
        Update portfolio peak if new high reached

        Args:
            current_portfolio_value: Current portfolio value
        """
        # Initialize peak on first call
        if self.portfolio_peak is None:
            self.portfolio_peak = current_portfolio_value
            return

        # Update if new high
        if current_portfolio_value > self.portfolio_peak:
            self.portfolio_peak = current_portfolio_value

            # Reset protection if we recovered
            if self.protection_active:
                self.protection_active = False
                self.protection_end_date = None

    def calculate_drawdown(self, current_portfolio_value):
        """
        Calculate current drawdown percentage from peak

        Args:
            current_portfolio_value: Current portfolio value

        Returns:
            float: Drawdown percentage (negative value)
        """
        if self.portfolio_peak is None or self.portfolio_peak == 0:
            return 0.0

        drawdown_pct = ((current_portfolio_value - self.portfolio_peak) / self.portfolio_peak * 100)

        # Track max drawdown seen
        if drawdown_pct < self.max_drawdown_seen:
            self.max_drawdown_seen = drawdown_pct

        return drawdown_pct

    def should_trigger(self, current_portfolio_value):
        """
        Check if drawdown protection should trigger

        Args:
            current_portfolio_value: Current portfolio value

        Returns:
            bool: True if should trigger protection
        """
        # Update peak
        self.update_peak(current_portfolio_value)

        # Calculate current drawdown
        drawdown_pct = self.calculate_drawdown(current_portfolio_value)

        # Trigger if:
        # 1. Drawdown exceeds threshold
        # 2. Not already in protection mode
        if drawdown_pct <= self.threshold_pct and not self.protection_active:
            return True

        return False

    def activate(self, strategy, current_date, position_monitor=None, ticker_cooldown=None):
        """
        Activate drawdown protection - close all positions

        Args:
            strategy: Strategy instance (for get_positions, create_order, etc.)
            current_date: Current date
            position_monitor: Position monitor instance (optional, for cleanup)
            ticker_cooldown: Ticker cooldown instance (optional, for cleanup)
        """
        current_portfolio_value = strategy.portfolio_value
        drawdown_pct = self.calculate_drawdown(current_portfolio_value)

        print(f"\n{'=' * 80}")
        print(f"🚨 PORTFOLIO PROTECTION TRIGGERED")
        print(f"{'=' * 80}")
        print(f"Peak Portfolio: ${self.portfolio_peak:,.2f}")
        print(f"Current Portfolio: ${current_portfolio_value:,.2f}")
        print(f"Drawdown: {drawdown_pct:.1f}%")
        print(f"Threshold: {self.threshold_pct:.1f}%")
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

                # Clean up tracking if provided
                if position_monitor:
                    position_monitor.clean_position_metadata(ticker)

                if ticker_cooldown:
                    ticker_cooldown.clear(ticker)

        # Set protection mode
        self.protection_active = True
        self.protection_end_date = current_date + timedelta(days=self.recovery_days)
        self.trigger_count += 1

        print(f"\n   ✅ Closed {closed_count} position(s)")
        print(f"   📅 Protection active until {self.protection_end_date.strftime('%Y-%m-%d')}")
        print(f"   🔄 Will reassess market conditions after recovery period\n")

    def is_in_recovery(self, current_date):
        """
        Check if currently in recovery period

        Args:
            current_date: Current date

        Returns:
            bool: True if in recovery period
        """
        if self.protection_end_date is None:
            return False

        return current_date < self.protection_end_date

    def get_recovery_days_remaining(self, current_date):
        """
        Get number of days remaining in recovery period

        Args:
            current_date: Current date

        Returns:
            int: Days remaining (0 if not in recovery)
        """
        if not self.is_in_recovery(current_date):
            return 0

        return (self.protection_end_date - current_date).days

    def print_status(self, current_portfolio_value, current_date):
        """
        Print current drawdown protection status

        Args:
            current_portfolio_value: Current portfolio value
            current_date: Current date
        """
        # Update peak
        self.update_peak(current_portfolio_value)

        # Calculate drawdown
        drawdown_pct = self.calculate_drawdown(current_portfolio_value)

        # In recovery period
        if self.is_in_recovery(current_date):
            days_remaining = self.get_recovery_days_remaining(current_date)
            print(f"\n🛡️ PROTECTION MODE: Recovery period ({days_remaining} days remaining)")
            print(f"   Drawdown: {drawdown_pct:.1f}% from peak ${self.portfolio_peak:,.2f}")
            print(f"   No new positions until {self.protection_end_date.strftime('%Y-%m-%d')}\n")

        # Warning zone (approaching threshold)
        elif drawdown_pct < -5.0:
            print(f"\n⚠️  Portfolio Drawdown: {drawdown_pct:.1f}% from peak ${self.portfolio_peak:,.2f}")
            print(f"   Protection triggers at {self.threshold_pct:.1f}%\n")

    def get_statistics(self):
        """
        Get drawdown protection statistics

        Returns:
            dict: Statistics about protection system
        """
        return {
            'threshold_pct': self.threshold_pct,
            'recovery_days': self.recovery_days,
            'portfolio_peak': self.portfolio_peak,
            'protection_active': self.protection_active,
            'protection_end_date': self.protection_end_date,
            'trigger_count': self.trigger_count,
            'max_drawdown_seen': self.max_drawdown_seen
        }

    def reset(self):
        """Reset protection system (useful for testing)"""
        self.portfolio_peak = None
        self.protection_active = False
        self.protection_end_date = None


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def create_default_protection(threshold_pct=-10.0, recovery_days=5):
    """
    Create default drawdown protection instance

    Args:
        threshold_pct: Drawdown % to trigger (default -10%)
        recovery_days: Days to wait after trigger (default 5)

    Returns:
        DrawdownProtection instance
    """
    return DrawdownProtection(threshold_pct=threshold_pct, recovery_days=recovery_days)


def print_protection_summary(protection):
    """
    Print detailed summary of protection system

    Args:
        protection: DrawdownProtection instance
    """
    stats = protection.get_statistics()

    print(f"\n{'=' * 80}")
    print(f"🛡️ DRAWDOWN PROTECTION SUMMARY")
    print(f"{'=' * 80}")
    print(f"Threshold: {stats['threshold_pct']:.1f}%")
    print(f"Recovery Period: {stats['recovery_days']} days")
    print(f"Times Triggered: {stats['trigger_count']}")
    print(f"Max Drawdown Seen: {stats['max_drawdown_seen']:.1f}%")

    if stats['portfolio_peak']:
        print(f"Portfolio Peak: ${stats['portfolio_peak']:,.2f}")

    if stats['protection_active']:
        print(f"\n⚠️  Currently in protection mode")
        if stats['protection_end_date']:
            print(f"   Recovery ends: {stats['protection_end_date'].strftime('%Y-%m-%d')}")
    else:
        print(f"\n✅ Protection system armed and monitoring")

    print(f"{'=' * 80}\n")