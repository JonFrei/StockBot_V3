"""
Portfolio Drawdown Protection System + Market Regime Detection + Circuit Breaker

ENHANCED BEAR MARKET DETECTION:
- EMA50 slope analysis (catches declining trends)
- Multi-timeframe confirmation
- Volume deterioration detection
- Blocks trading BEFORE major drawdowns occur

Usage:
    protection = DrawdownProtection(
        threshold_pct=-10.0,
        recovery_days=5
    )

    # In strategy loop:
    if protection.should_trigger(portfolio_value):
        protection.activate(strategy, current_date)
        return

    regime_info = detect_market_regime(spy_data, stock_data)
    if not regime_info['allow_trading']:
        return  # Skip new positions
"""

from datetime import timedelta, datetime
import pandas as pd


# =============================================================================
# ENHANCED MARKET REGIME DETECTION
# =============================================================================

def detect_market_regime(spy_data, stock_data=None):
    """
    Detect current market regime with ENHANCED BEAR MARKET DETECTION

    NEW CHECKS (prevents March-July 2025 drawdown):
    1. EMA50 slope analysis - catches death cross FORMING
    2. Volume deterioration - detects weakening conviction
    3. Price momentum check - confirms trend direction
    4. Multiple timeframe alignment - stronger confirmation

    PRIORITY 1: BEAR MARKET (BLOCKING)
    - EMA50 declining over 10 days
    - SPY below 200 SMA
    - Stock >5% below 200 SMA
    - Negative price momentum

    Returns:
        dict: {
            'regime': str,
            'position_size_multiplier': float (0.0-1.0),
            'emergency_stop_multiplier': float (0.75-1.0),
            'max_positions': int,
            'description': str,
            'allow_trading': bool,
            'warnings': list
        }
    """

    warnings = []

    # =======================================================================
    # CRITICAL: ENHANCED BEAR MARKET DETECTION
    # =======================================================================

    if spy_data:
        spy_close = spy_data.get('close', 0)
        spy_sma200 = spy_data.get('sma200', 0)
        spy_ema50 = spy_data.get('ema50', 0)
        spy_ema20 = spy_data.get('ema20', 0)
        spy_raw = spy_data.get('raw', None)

        # === CHECK 1: Classic Bear Market (SPY below 200 SMA) ===
        spy_below_200 = spy_close < spy_sma200 if spy_sma200 > 0 else False

        if spy_below_200:
            distance_below = ((spy_close - spy_sma200) / spy_sma200 * 100) if spy_sma200 > 0 else 0
            return {
                'regime': 'bear_market',
                'position_size_multiplier': 0.0,
                'emergency_stop_multiplier': 1.0,
                'max_positions': 0,
                'description': f'🔴 BEAR MARKET: SPY {distance_below:.1f}% below 200 SMA - TRADING BLOCKED',
                'allow_trading': False,
                'warnings': ['SPY below 200 SMA']
            }

        # === CHECK 2: DEATH CROSS FORMING (EMA50 declining) ===
        if spy_raw is not None and len(spy_raw) >= 60:
            # Calculate EMA50 slope over last 10 days
            ema50_series = spy_raw['close'].ewm(span=50, adjust=False).mean()

            if len(ema50_series) >= 11:
                ema50_current = ema50_series.iloc[-1]
                ema50_10d_ago = ema50_series.iloc[-11]

                # Calculate slope (% change per day)
                ema50_slope = ((ema50_current - ema50_10d_ago) / ema50_10d_ago * 100) / 10

                # If EMA50 declining more than 0.15% per day = death cross forming
                if ema50_slope < -0.15:
                    warnings.append(f'SPY EMA50 declining ({ema50_slope:.2f}%/day)')

                    return {
                        'regime': 'bear_market',
                        'position_size_multiplier': 0.0,
                        'emergency_stop_multiplier': 1.0,
                        'max_positions': 0,
                        'description': f'🔴 BEAR MARKET FORMING: SPY EMA50 declining {ema50_slope:.2f}%/day - TRADING BLOCKED',
                        'allow_trading': False,
                        'warnings': warnings
                    }

        # === CHECK 3: DEATH CROSS PRESENT (EMA20 < EMA50) ===
        if spy_ema20 > 0 and spy_ema50 > 0:
            if spy_ema20 < spy_ema50:
                warnings.append('SPY death cross (EMA20 < EMA50)')

                return {
                    'regime': 'bear_market',
                    'position_size_multiplier': 0.0,
                    'emergency_stop_multiplier': 1.0,
                    'max_positions': 0,
                    'description': f'🔴 DEATH CROSS: SPY EMA20 < EMA50 - TRADING BLOCKED',
                    'allow_trading': False,
                    'warnings': warnings
                }

        # === CHECK 4: NEGATIVE PRICE MOMENTUM ===
        if spy_raw is not None and len(spy_raw) >= 10:
            recent_closes = spy_raw['close'].iloc[-10:].values
            momentum_10d = ((recent_closes[-1] - recent_closes[0]) / recent_closes[0] * 100)

            # If SPY down >3% over 10 days while near 200 SMA = warning
            if momentum_10d < -3.0:
                distance_from_200 = ((spy_close - spy_sma200) / spy_sma200 * 100) if spy_sma200 > 0 else 0

                if distance_from_200 < 3.0:  # Within 3% of 200 SMA
                    warnings.append(f'SPY momentum: {momentum_10d:.1f}% over 10d')

                    return {
                        'regime': 'bear_market',
                        'position_size_multiplier': 0.0,
                        'emergency_stop_multiplier': 1.0,
                        'max_positions': 0,
                        'description': f'🔴 WEAKENING TREND: SPY -{momentum_10d:.1f}% over 10 days - TRADING BLOCKED',
                        'allow_trading': False,
                        'warnings': warnings
                    }

        # === CHECK 5: VOLUME DETERIORATION ===
        if spy_raw is not None and len(spy_raw) >= 20:
            volume_series = spy_raw['volume'].iloc[-20:].values

            # Compare last 5 days vs previous 15 days
            recent_vol = volume_series[-5:].mean()
            previous_vol = volume_series[-20:-5].mean()

            volume_change = ((recent_vol - previous_vol) / previous_vol * 100) if previous_vol > 0 else 0

            # If volume down >30% = warning sign
            if volume_change < -30:
                warnings.append(f'SPY volume declining {volume_change:.0f}%')

                # Only block if also seeing price weakness
                if momentum_10d < -2.0:
                    return {
                        'regime': 'bear_market',
                        'position_size_multiplier': 0.0,
                        'emergency_stop_multiplier': 1.0,
                        'max_positions': 0,
                        'description': f'🔴 VOLUME DRYING UP: SPY volume -{volume_change:.0f}% + negative momentum - TRADING BLOCKED',
                        'allow_trading': False,
                        'warnings': warnings
                    }

    # === CHECK 6: STOCK-SPECIFIC BEAR CHECK ===
    if stock_data:
        stock_close = stock_data.get('close', 0)
        stock_sma200 = stock_data.get('sma200', 0)
        distance_from_200 = ((stock_close - stock_sma200) / stock_sma200 * 100) if stock_sma200 > 0 else -100

        # Stock must be within 5% of 200 SMA (tightened from original)
        if distance_from_200 < -5.0:
            return {
                'regime': 'bear_market',
                'position_size_multiplier': 0.0,
                'emergency_stop_multiplier': 1.0,
                'max_positions': 0,
                'description': f'🔴 STOCK BEAR: {distance_from_200:.1f}% below 200 SMA - BLOCKED',
                'allow_trading': False,
                'warnings': [f'Stock {distance_from_200:.1f}% below 200 SMA']
            }

    # =======================================================================
    # NORMAL REGIME DETECTION (Market is healthy)
    # =======================================================================

    if not spy_data:
        # Default to cautious if no SPY data
        return {
            'regime': 'unknown',
            'position_size_multiplier': 0.7,
            'emergency_stop_multiplier': 0.85,
            'max_positions': 8,
            'description': 'No SPY data - Cautious mode',
            'allow_trading': True,
            'warnings': ['No SPY data']
        }

    # Extract indicators for normal regime detection
    adx = spy_data.get('adx', 0)
    atr = spy_data.get('atr_14', 0)
    sma50 = spy_data.get('sma50', 0)
    close = spy_data.get('close', 0)
    ema20 = spy_data.get('ema20', 0)
    ema50 = spy_data.get('ema50', 0)

    # Calculate relative volatility (ATR as % of price)
    atr_pct = (atr / close * 100) if close > 0 else 0

    # Calculate distance from SMA50
    distance_from_sma50 = ((close - sma50) / sma50 * 100) if sma50 > 0 else 0

    # =======================================================================
    # REGIME 1: TRENDING (Strong uptrend)
    # =======================================================================
    if (adx > 25 and
            close > ema20 and
            ema20 > ema50 and
            distance_from_sma50 > 1.0):

        return {
            'regime': 'trending',
            'position_size_multiplier': 1.0,
            'emergency_stop_multiplier': 1.0,
            'max_positions': 10,
            'description': f'🟢 TRENDING: ADX {adx:.0f}, Price > EMAs, +{distance_from_sma50:.1f}% from SMA50',
            'allow_trading': True,
            'warnings': warnings
        }

    # =======================================================================
    # REGIME 2: VOLATILE (High uncertainty)
    # =======================================================================
    elif (atr_pct > 3.0 or
          (adx < 20 and atr_pct > 2.0)):

        return {
            'regime': 'volatile',
            'position_size_multiplier': 0.4,
            'emergency_stop_multiplier': 0.75,
            'max_positions': 6,
            'description': f'🔴 VOLATILE: ATR {atr_pct:.1f}% of price, ADX {adx:.0f}',
            'allow_trading': True,
            'warnings': warnings
        }

    # =======================================================================
    # REGIME 3: CHOPPY (Default - Sideways action)
    # =======================================================================
    else:
        return {
            'regime': 'choppy',
            'position_size_multiplier': 0.7,
            'emergency_stop_multiplier': 0.85,
            'max_positions': 8,
            'description': f'🟡 CHOPPY: ADX {adx:.0f}, ATR {atr_pct:.1f}%, Sideways action',
            'allow_trading': True,
            'warnings': warnings
        }


def get_regime_adjusted_params(base_params, regime_info):
    """
    Adjust trading parameters based on market regime

    Args:
        base_params: Base parameters dict
        regime_info: Regime info from detect_market_regime()

    Returns:
        dict: Adjusted parameters
    """
    adjusted = base_params.copy()

    # Adjust position size
    if 'position_size_pct' in adjusted:
        adjusted['position_size_pct'] *= regime_info['position_size_multiplier']

    # Adjust emergency stop
    if 'emergency_stop_pct' in adjusted:
        adjusted['emergency_stop_pct'] *= regime_info['emergency_stop_multiplier']

    # Add regime info
    adjusted['regime'] = regime_info['regime']
    adjusted['regime_description'] = regime_info['description']
    adjusted['max_positions_allowed'] = regime_info['max_positions']

    return adjusted


def format_regime_display(regime_info):
    """
    Format regime info for console display

    Args:
        regime_info: Regime dict from detect_market_regime()

    Returns:
        str: Formatted display string
    """
    output = f"\n{'=' * 80}\n"
    output += f"{regime_info['description']}\n"
    output += f"{'=' * 80}\n"

    if regime_info.get('warnings'):
        output += f"⚠️  Warnings:\n"
        for warning in regime_info['warnings']:
            output += f"   - {warning}\n"
        output += f"{'─' * 80}\n"

    if regime_info['allow_trading']:
        output += f"Position Size: {regime_info['position_size_multiplier'] * 100:.0f}% of normal\n"
        output += f"Emergency Stops: {regime_info['emergency_stop_multiplier'] * 100:.0f}% of normal\n"
        output += f"Max Positions: {regime_info['max_positions']}\n"
    else:
        output += f"🚫 NEW POSITIONS BLOCKED\n"

    output += f"{'=' * 80}\n"

    return output


# =============================================================================
# DRAWDOWN PROTECTION SYSTEM (Enhanced)
# =============================================================================

class DrawdownProtection:
    """
    Manages portfolio-level drawdown protection

    ENHANCED: Tighter threshold recommended based on backtest
    """

    def __init__(self, threshold_pct=-8.0, recovery_days=5):  # CHANGED from -10.0 to -8.0
        """
        Initialize drawdown protection

        Args:
            threshold_pct: Drawdown percentage to trigger (default -8%)
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
            strategy: Strategy instance
            current_date: Current date
            position_monitor: Position monitor instance (optional)
            ticker_cooldown: Ticker cooldown instance (optional)
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

def create_default_protection(threshold_pct=-8.0, recovery_days=5):  # CHANGED from -10.0
    """
    Create default drawdown protection instance

    UPDATED: Tighter -8% threshold based on backtest analysis

    Args:
        threshold_pct: Drawdown % to trigger (default -8%)
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