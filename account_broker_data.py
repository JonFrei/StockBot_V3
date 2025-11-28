"""
Trading Window Configuration and Market Data

Handles:
- Trading window times and validation
- Market holiday detection
- Trading frequency controls
- Broker position utilities (entry price extraction, validation)
"""

from datetime import time, date
from typing import Any, Tuple, Optional
import pytz
from config import Config

# =============================================================================
# TRADING WINDOW CONFIGURATION
# =============================================================================

TRADING_START_TIME = time(10, 0)  # 10:00 AM EST
TRADING_END_TIME = time(16, 0)  # 4:00 PM EST

# =============================================================================
# US MARKET HOLIDAYS (2025)
# =============================================================================

# NYSE/NASDAQ holiday schedule
US_MARKET_HOLIDAYS_2025 = {
    date(2025, 1, 1),  # New Year's Day
    date(2025, 1, 20),  # Martin Luther King Jr. Day
    date(2025, 2, 17),  # Presidents' Day
    date(2025, 4, 18),  # Good Friday
    date(2025, 5, 26),  # Memorial Day
    date(2025, 6, 19),  # Juneteenth
    date(2025, 7, 4),  # Independence Day
    date(2025, 9, 1),  # Labor Day
    date(2025, 11, 27),  # Thanksgiving
    date(2025, 12, 25),  # Christmas
}

# =============================================================================
# SYMBOLS TO SKIP (not tradeable stock positions)
# =============================================================================

# Lumibot may include USD as a "position" representing cash/quote asset
# These should be filtered out when processing positions
SKIP_SYMBOLS = {'USD', 'USDT', 'USDC', 'EUR', 'GBP', 'JPY', 'CAD', 'AUD'}


# =============================================================================
# MARKET HOLIDAY FUNCTIONS
# =============================================================================

def is_market_holiday(check_date):
    """
    Check if date is a US market holiday

    Args:
        check_date: datetime.date object

    Returns:
        bool: True if holiday, False otherwise
    """
    # Check if weekend
    if check_date.weekday() >= 5:  # Saturday = 5, Sunday = 6
        return True

    # Check if holiday
    return check_date in US_MARKET_HOLIDAYS_2025


# =============================================================================
# TRADING WINDOW FUNCTIONS
# =============================================================================

def is_within_trading_window(strategy):
    """
    Check if current time is within trading window (10 AM - 4 PM EST)

    Args:
        strategy: Lumibot Strategy instance

    Returns:
        bool: True if within trading window, False otherwise
    """
    if Config.BACKTESTING:
        return True

    try:
        # Get current time in EST
        est = pytz.timezone('US/Eastern')
        current_datetime_est = strategy.get_datetime().astimezone(est)
        current_time_est = current_datetime_est.time()
        current_date = current_datetime_est.date()

        # Check if market holiday
        if is_market_holiday(current_date):
            day_name = current_datetime_est.strftime('%A')
            print(f"[INFO] Market closed - {day_name}, {current_date} is a holiday/weekend")
            return False

        # Check if within window
        is_within = TRADING_START_TIME <= current_time_est <= TRADING_END_TIME

        if not is_within:
            if current_time_est < TRADING_START_TIME:
                print(f"[INFO] Before trading window (current: {current_time_est.strftime('%I:%M %p')} EST, "
                      f"window opens at {TRADING_START_TIME.strftime('%I:%M %p')} EST)")
            else:
                print(f"[INFO] After trading window (current: {current_time_est.strftime('%I:%M %p')} EST, "
                      f"window closed at {TRADING_END_TIME.strftime('%I:%M %p')} EST)")

        return is_within

    except Exception as e:
        print(f"[WARN] Could not check trading window: {e}")
        return False


def has_traded_today(strategy, last_trade_date) -> bool:
    """
    Check if strategy has already traded today

    Args:
        strategy: Lumibot Strategy instance
        last_trade_date: Last date trading occurred (date object)

    Returns:
        bool: True if already traded today, False otherwise
    """
    if Config.BACKTESTING:
        return False

    current_date = strategy.get_datetime().date()

    if last_trade_date == current_date:
        print(f"[INFO] Already traded today ({current_date}) - skipping iteration")
        return True

    return False


def get_trading_window_info():
    """
    Get trading window configuration info

    Returns:
        dict: Trading window details
    """
    return {
        'start_time': TRADING_START_TIME,
        'end_time': TRADING_END_TIME,
        'start_time_str': TRADING_START_TIME.strftime('%I:%M %p'),
        'end_time_str': TRADING_END_TIME.strftime('%I:%M %p'),
        'timezone': 'US/Eastern'
    }


def print_trading_window_info():
    """Print trading window information"""
    info = get_trading_window_info()
    print(f"\n{'=' * 80}")
    print(f"⏰ TRADING WINDOW CONFIGURATION")
    print(f"{'=' * 80}")
    print(f"Start Time: {info['start_time_str']} {info['timezone']}")
    print(f"End Time:   {info['end_time_str']} {info['timezone']}")
    print(f"Duration:   {(TRADING_END_TIME.hour - TRADING_START_TIME.hour)} hours")
    print(f"Frequency:  Once per day")
    print(f"{'=' * 80}\n")


# =============================================================================
# BROKER POSITION UTILITIES
# =============================================================================

def is_valid_stock_position(position, ticker: str = "") -> bool:
    """
    Check if this is a valid stock position (not cash/forex/quote asset).

    Lumibot may include USD as a "position" representing cash/quote asset.
    This function filters those out.

    Args:
        position: Broker position object
        ticker: Ticker symbol

    Returns:
        bool: True if valid stock position, False if should be skipped
    """
    # Get symbol from position or use provided ticker
    symbol = ticker
    if not symbol:
        if hasattr(position, 'symbol'):
            symbol = position.symbol
        elif hasattr(position, 'asset') and hasattr(position.asset, 'symbol'):
            symbol = position.asset.symbol

    if not symbol:
        return False

    symbol = symbol.upper()

    # Skip known non-stock symbols (cash, forex, stablecoins)
    if symbol in SKIP_SYMBOLS:
        return False

    # Check asset_type if available (Lumibot positions have this)
    if hasattr(position, 'asset') and position.asset:
        asset_type = getattr(position.asset, 'asset_type', None)
        if asset_type:
            asset_type_str = str(asset_type).lower()
            # Only allow stocks/equities
            if 'forex' in asset_type_str or 'crypto' in asset_type_str:
                return False

    # Check asset_class if available (Alpaca positions have this)
    if hasattr(position, 'asset_class'):
        asset_class = str(position.asset_class).lower()
        if 'us_equity' not in asset_class and 'stock' not in asset_class:
            # Could be crypto, forex, etc.
            if 'crypto' in asset_class or 'forex' in asset_class:
                return False

    return True


def get_broker_entry_price(position: Any, strategy: Any = None, ticker: str = "") -> float:
    """
    Extract entry price from broker position object.

    Handles both:
    - Direct Alpaca API positions (avg_entry_price, cost_basis)
    - Lumibot wrapped positions (avg_fill_price)

    Tries multiple attributes in order of preference:
    1. avg_entry_price (Alpaca direct)
    2. cost_basis / quantity (Alpaca calculation)
    3. cost_basis / qty (Alpaca alternate)
    4. avg_fill_price (Lumibot)

    Returns 0.0 if no valid entry price found - position will be flagged for manual review.

    Args:
        position: Broker position object
        strategy: Strategy instance (optional, can be used for price lookup fallback)
        ticker: Ticker symbol (optional, for logging)

    Returns:
        float: Entry price, or 0.0 if unable to determine
    """
    # First check if this is a valid stock position
    if not is_valid_stock_position(position, ticker):
        # Silently skip non-stock positions (USD, etc.)
        return 0.0

    # Try avg_entry_price first (Alpaca direct API)
    if hasattr(position, 'avg_entry_price') and position.avg_entry_price:
        try:
            price = float(position.avg_entry_price)
            if price > 0:
                return price
        except (ValueError, TypeError):
            pass

    # Try cost_basis / quantity (alpaca-trade-api format with 'quantity')
    if hasattr(position, 'cost_basis') and hasattr(position, 'quantity'):
        try:
            cost_basis = float(position.cost_basis)
            quantity = float(position.quantity)
            if quantity > 0 and cost_basis > 0:
                price = cost_basis / quantity
                if price > 0:
                    return price
        except (ValueError, TypeError, ZeroDivisionError):
            pass

    # Try cost_basis / qty (alpaca-trade-api format with 'qty')
    if hasattr(position, 'cost_basis') and hasattr(position, 'qty'):
        try:
            cost_basis = float(position.cost_basis)
            qty = float(position.qty)
            if qty > 0 and cost_basis > 0:
                price = cost_basis / qty
                if price > 0:
                    return price
        except (ValueError, TypeError, ZeroDivisionError):
            pass

    # Try avg_fill_price (Lumibot Position object)
    if hasattr(position, 'avg_fill_price') and position.avg_fill_price:
        try:
            price = float(position.avg_fill_price)
            if price > 0:
                return price
        except (ValueError, TypeError):
            pass

    # Try current_price as last resort (better than 0)
    if hasattr(position, 'current_price') and position.current_price:
        try:
            price = float(position.current_price)
            if price > 0:
                if ticker:
                    print(f"[WARN] {ticker} - Using current_price as fallback entry price: ${price:.2f}")
                return price
        except (ValueError, TypeError):
            pass

    # Try to get price from strategy if available
    if strategy and ticker:
        try:
            price = strategy.get_last_price(ticker)
            if price and price > 0:
                print(f"[WARN] {ticker} - Using live price as fallback entry price: ${price:.2f}")
                return float(price)
        except:
            pass

    # No valid entry price found - return 0.0 for manual review
    if ticker:
        print(f"[ERROR] {ticker} - Could not determine entry price, flagging for manual review")

    return 0.0


def validate_entry_price(entry_price: float, ticker: str = "", min_price: float = 0.01) -> bool:
    """
    Validate that entry price is reasonable.

    Args:
        entry_price: Entry price to validate
        ticker: Ticker symbol (for logging)
        min_price: Minimum acceptable price (default $0.01)

    Returns:
        bool: True if valid, False otherwise
    """
    # Skip validation for non-stock symbols (they return 0.0 intentionally)
    if ticker and ticker.upper() in SKIP_SYMBOLS:
        return False

    if entry_price <= 0:
        if ticker:
            print(f"[ERROR] {ticker} - Invalid entry price: ${entry_price:.2f} (must be > 0)")
        return False

    if entry_price < min_price:
        if ticker:
            print(f"[WARN] {ticker} - Entry price ${entry_price:.2f} below minimum ${min_price:.2f}")
        return False

    return True


def get_position_quantity(position: Any, ticker: str = "") -> int:
    """
    Extract quantity from broker position object.

    Handles both:
    - Alpaca positions (qty)
    - Lumibot positions (quantity)

    Args:
        position: Broker position object
        ticker: Ticker symbol (for logging)

    Returns:
        int: Position quantity, or 0 if unable to determine
    """
    # First check if this is a valid stock position
    if not is_valid_stock_position(position, ticker):
        # Silently skip non-stock positions (USD, etc.)
        return 0

    # Try 'quantity' first (Lumibot format)
    if hasattr(position, 'quantity'):
        try:
            qty = int(float(position.quantity))
            if qty > 0:
                return qty
            elif qty < 0:
                # Handle short positions (convert to positive)
                return abs(qty)
        except (ValueError, TypeError):
            pass

    # Try 'qty' (Alpaca format)
    if hasattr(position, 'qty'):
        try:
            qty = int(float(position.qty))
            if qty > 0:
                return qty
            elif qty < 0:
                return abs(qty)
        except (ValueError, TypeError):
            pass

    if ticker:
        print(f"[ERROR] {ticker} - Could not extract quantity from position")

    return 0


def calculate_position_pnl(entry_price: float, current_price: float, quantity: int) -> Tuple[float, float]:
    """
    Calculate position P&L

    Args:
        entry_price: Entry price per share
        current_price: Current price per share
        quantity: Number of shares

    Returns:
        tuple: (pnl_dollars, pnl_pct)
    """
    if entry_price <= 0 or quantity <= 0:
        return 0.0, 0.0

    pnl_per_share = current_price - entry_price
    pnl_dollars = pnl_per_share * quantity
    pnl_pct = (pnl_per_share / entry_price * 100)

    return pnl_dollars, pnl_pct


def format_price(price: float, decimals: int = 2) -> str:
    """
    Format price for display

    Args:
        price: Price to format
        decimals: Number of decimal places (default 2)

    Returns:
        str: Formatted price string
    """
    return f"${price:,.{decimals}f}"


def format_pnl(pnl_dollars: float, pnl_pct: float) -> str:
    """
    Format P&L for display with color indicator

    Args:
        pnl_dollars: P&L in dollars
        pnl_pct: P&L percentage

    Returns:
        str: Formatted P&L string with emoji
    """
    emoji = "✅" if pnl_dollars > 0 else "❌"
    return f"{emoji} ${pnl_dollars:+,.2f} ({pnl_pct:+.1f}%)"