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
TRADING_END_TIME = time(14, 0)    # 11:00 AM EST (changed from 4:00 PM)

# =============================================================================
# US MARKET HOLIDAYS (2025)
# =============================================================================

# NYSE/NASDAQ holiday schedule
US_MARKET_HOLIDAYS_2025 = {
    date(2025, 1, 1),   # New Year's Day
    date(2025, 1, 20),  # Martin Luther King Jr. Day
    date(2025, 2, 17),  # Presidents' Day
    date(2025, 4, 18),  # Good Friday
    date(2025, 5, 26),  # Memorial Day
    date(2025, 6, 19),  # Juneteenth
    date(2025, 7, 4),   # Independence Day
    date(2025, 9, 1),   # Labor Day
    date(2025, 11, 27), # Thanksgiving
    date(2025, 12, 25), # Christmas
}


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


def is_within_trading_window(strategy):
    """
    Check if current time is within trading window (10-11 AM EST)

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


def has_traded_today(strategy, last_trade_date):
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
    print(f"Duration:   1 hour")
    print(f"Frequency:  Once per day")
    print(f"{'=' * 80}\n")


# =============================================================================
# BROKER POSITION UTILITIES
# =============================================================================

def get_broker_entry_price(position: Any, strategy: Any = None, ticker: str = "") -> float:
    """
    Extract entry price from broker position object

    Tries multiple attributes in order of preference:
    1. avg_entry_price (most reliable)
    2. cost_basis / quantity (alpaca-trade-api format)

    Returns 0.0 if no valid entry price found - position will be flagged for manual review.

    Args:
        position: Broker position object
        strategy: Strategy instance (optional, not used for price fallback)
        ticker: Ticker symbol (optional, for logging)

    Returns:
        float: Entry price, or 0.0 if unable to determine
    """

    # Try avg_entry_price first (most common)
    if hasattr(position, 'avg_entry_price') and position.avg_entry_price:
        try:
            price = float(position.avg_entry_price)
            if price > 0:
                return price
        except (ValueError, TypeError):
            pass

    # Try cost_basis / quantity (alpaca-trade-api format)
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

    # Try fill_avg_price
    if hasattr(position, 'fill_avg_price') and position.fill_avg_price:
        try:
            price = float(position.fill_avg_price)
            if price > 0:
                return price
        except (ValueError, TypeError):
            pass

    # Try avg_fill_price (alternative naming)
    if hasattr(position, 'avg_fill_price') and position.avg_fill_price:
        try:
            price = float(position.avg_fill_price)
            if price > 0:
                return price
        except (ValueError, TypeError):
            pass

    # No valid entry price found - return 0.0 for manual review
    if ticker:
        print(f"[ERROR] {ticker} - Could not determine entry price, flagging for manual review")

    return 0.0


def validate_entry_price(entry_price: float, ticker: str = "", min_price: float = 0.01) -> bool:
    """
    Validate that entry price is reasonable

    Args:
        entry_price: Entry price to validate
        ticker: Ticker symbol (for logging)
        min_price: Minimum acceptable price (default $0.01)

    Returns:
        bool: True if valid, False otherwise
    """
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
    Extract quantity from broker position object

    Args:
        position: Broker position object
        ticker: Ticker symbol (for logging)

    Returns:
        int: Position quantity, or 0 if unable to determine
    """
    # Try qty first (most common)
    if hasattr(position, 'qty'):
        try:
            return int(float(position.qty))
        except (ValueError, TypeError):
            pass

    # Try quantity
    if hasattr(position, 'quantity'):
        try:
            return int(float(position.quantity))
        except (ValueError, TypeError):
            pass

    if ticker:
        print(f"[ERROR] {ticker} - Could not determine position quantity")

    return 0